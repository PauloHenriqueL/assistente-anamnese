"""Chamadas à IA com resposta em formato fixo.

O provedor é escolhido por IA_PROVEDOR no .env: gemini ou openai. Toda
chamada passa por `chamar`, o que facilita trocar o modelo e simular a IA
nos testes. O nome do módulo ficou gemini por ser o provedor original.
"""

import enum
import logging
import time

from django.conf import settings
from pydantic import BaseModel

from functools import lru_cache

from pydantic import create_model

from . import secoes

logger = logging.getLogger(__name__)


class Modo(str, enum.Enum):
    geracao = "geracao"
    ajuste = "ajuste"
    revisao = "revisao"


class ParagrafoIA(BaseModel):
    id: str
    tema: str
    texto: str
    trechos_origem: list[str]
    modo: Modo
    texto_base_usuaria: str
    pediu_acrescimo: bool


class RespostaIA(BaseModel):
    mensagem: str
    paragrafos: list[ParagrafoIA]
    remover: list[str]


class ItemVerificacao(BaseModel):
    id: str
    faltou: list[str]
    sem_apoio: list[str]


class RespostaVerificacao(BaseModel):
    itens: list[ItemVerificacao]


class ErroGemini(Exception):
    pass


# Segundos de espera antes de cada nova tentativa, quando a IA está sobrecarregada.
ESPERAS = [5, 15, 30]


def provedor():
    return (settings.IA_PROVEDOR or "gemini").strip().lower()


def modelo(verificacao=False):
    if provedor() != "openai":
        return settings.GEMINI_MODEL
    return settings.OPENAI_MODEL_VERIFICACAO if verificacao else settings.OPENAI_MODEL


def raciocinio(verificacao=False):
    """Esforço de raciocínio da OpenAI para a etapa. Vazio = modelo sem raciocínio."""
    valor = settings.OPENAI_RACIOCINIO_VERIFICACAO if verificacao else settings.OPENAI_RACIOCINIO
    return (valor or "").strip().lower()


def escolha_valida(modelo_pedido, pensar):
    """Modelo e esforço de raciocínio escolhidos na tela, só entre os permitidos em IA_MODELOS.

    Devolve (modelo, raciocínio); vazio no modelo quer dizer usar o padrão do .env.
    Pensamento desligado vira "none", que os modelos de raciocínio aceitam.
    """
    permitidos = {m for m, _ in settings.IA_MODELOS}
    modelo_escolhido = modelo_pedido if modelo_pedido in permitidos else ""
    return modelo_escolhido, (raciocinio() or "medium") if pensar else "none"


def _chamar_gemini(sistema, conteudo, esquema, temperatura, verificacao, escolha=None):
    from google import genai
    from google.genai import types

    cliente = genai.Client(api_key=settings.GEMINI_API_KEY)
    config = types.GenerateContentConfig(
        system_instruction=sistema,
        response_mime_type="application/json",
        response_schema=esquema,
        temperature=temperatura,
        http_options=types.HttpOptions(timeout=settings.IA_TIMEOUT * 1000),  # em milissegundos
    )
    return cliente.models.generate_content(model=settings.GEMINI_MODEL, contents=conteudo, config=config).text


def _chamar_openai(sistema, conteudo, esquema, temperatura, verificacao, escolha=None):
    from openai import BadRequestError, OpenAI

    # Sem retries do SDK: as tentativas são as de `chamar`, o que limita o tempo total da geração.
    cliente = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=float(settings.IA_TIMEOUT), max_retries=0)
    modelo_escolhido, esforco = escolha or ("", raciocinio(verificacao))
    pedido = dict(
        model=modelo_escolhido or modelo(verificacao),
        messages=[{"role": "system", "content": sistema}, {"role": "user", "content": conteudo}],
        response_format=esquema,
    )
    try:
        if esforco:
            # Modelos de raciocínio não aceitam temperatura: o "modo de pensar" substitui.
            resposta = cliente.chat.completions.parse(reasoning_effort=esforco, **pedido)
        else:
            resposta = cliente.chat.completions.parse(temperature=temperatura, **pedido)
    except BadRequestError as erro:
        # Modelo sem raciocínio que recebeu reasoning_effort, ou de raciocínio que recebeu temperatura.
        texto = str(erro)
        if "reasoning" in texto:
            resposta = cliente.chat.completions.parse(temperature=temperatura, **pedido)
        elif "temperature" in texto:
            resposta = cliente.chat.completions.parse(**pedido)
        else:
            raise
    mensagem = resposta.choices[0].message
    if getattr(mensagem, "refusal", None):
        raise ErroGemini("A IA se recusou a responder a este pedido. Tente reformular a mensagem.")
    return mensagem.content


def _sem_chave():
    if provedor() == "openai":
        return "" if settings.OPENAI_API_KEY else "A IA não está configurada. Falta OPENAI_API_KEY no arquivo .env."
    if provedor() != "gemini":
        return "A IA não está configurada. IA_PROVEDOR no arquivo .env tem um valor inválido."
    return "" if settings.GEMINI_API_KEY else (
        "A IA não está configurada. Falta GEMINI_API_KEY no arquivo .env."
    )


def _classificar(erro):
    """Devolve (sem_cota, passageiro) a partir do erro de qualquer provedor."""
    texto = str(erro)
    status = getattr(erro, "status_code", None) or getattr(erro, "code", None)
    sem_cota = "limit: 0" in texto or "insufficient_quota" in texto
    # Conexão que caiu no caminho (sem status HTTP) também é passageira. Tempo esgotado não: já esperou demais.
    tempo_esgotado = "Timeout" in type(erro).__name__
    conexao = not tempo_esgotado and (
        isinstance(erro, ConnectionError) or type(erro).__name__ in ("APIConnectionError", "ConnectError", "RemoteProtocolError")
    )
    passageiro = conexao or status in (429, 500, 502, 503, 504) or any(
        c in texto for c in ("503", "UNAVAILABLE", "500", "INTERNAL", "429", "RESOURCE_EXHAUSTED", "overloaded")
    )
    return sem_cota, passageiro and not sem_cota


def chamar(sistema, conteudo, esquema, temperatura, verificacao=False, escolha=None):
    falta = _sem_chave()
    if falta:
        raise ErroGemini(falta)
    chamada = _chamar_openai if provedor() == "openai" else _chamar_gemini
    for tentativa, espera in enumerate(ESPERAS + [None], 1):
        try:
            texto = chamada(sistema, conteudo, esquema, temperatura, verificacao, escolha)
            break
        except ErroGemini:
            raise
        except Exception as erro:  # os SDKs levantam vários tipos; mostramos a mensagem para a usuária
            sem_cota, passageiro = _classificar(erro)
            if passageiro and espera is not None:
                time.sleep(espera)
                continue
            logger.error("Falha na chamada à IA (%s, %s): %s", provedor(), modelo(verificacao), erro)
            raise ErroGemini(_mensagem_de_erro(str(erro), sem_cota, passageiro, tentativa)) from erro
    if not texto:
        raise ErroGemini("A IA devolveu uma resposta vazia. Tente enviar a mensagem de novo.")
    try:
        return esquema.model_validate_json(texto)
    except Exception as erro:
        logger.error("Resposta fora do formato: %s", erro)
        raise ErroGemini("A resposta da IA veio incompleta. Tente enviar a mensagem de novo.") from erro


def _mensagem_de_erro(texto, sem_cota, passageiro, tentativas):
    if sem_cota:
        return "A IA está indisponível no momento por falta de crédito ou de cota. Avise o responsável pelo sistema."
    if passageiro:
        return (
            f"A IA está sobrecarregada agora. O sistema tentou {tentativas} vezes sem sucesso. "
            "Espere alguns minutos e envie de novo."
        )
    return "A IA não conseguiu responder. Tente enviar a mensagem de novo e, se o erro continuar, avise o responsável pelo sistema."


@lru_cache(maxsize=None)
def esquema_resposta(chave_secao):
    """Formato de resposta em que o tema só aceita os tipos de bloco da seção."""
    secao = secoes.secao(chave_secao)
    nome = "S" + chave_secao.replace(".", "_")
    Tipo = enum.Enum(f"Tipo{nome}", {c: c for c in secao.chaves_tipos}, type=str)
    Paragrafo = create_model(
        f"Paragrafo{nome}",
        id=(str, ...), tema=(Tipo, ...), texto=(str, ...), trechos_origem=(list[str], ...),
        modo=(Modo, ...), texto_base_usuaria=(str, ...), pediu_acrescimo=(bool, ...),
    )
    return create_model(f"Resposta{nome}", mensagem=(str, ...), paragrafos=(list[Paragrafo], ...), remover=(list[str], ...))


def gerar(sistema, conteudo, chave_secao="4.2", escolha=None):
    """`escolha` = (modelo, raciocínio) vindos da tela; None usa o padrão do .env."""
    especifica = chamar(
        sistema, conteudo, esquema_resposta(chave_secao), temperatura=settings.GEMINI_TEMPERATURA, escolha=escolha
    )
    return RespostaIA.model_validate(especifica.model_dump(mode="json"))


def verificar(sistema, conteudo):
    return chamar(sistema, conteudo, RespostaVerificacao, temperatura=0.0, verificacao=True)
