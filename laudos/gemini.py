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

from . import temas

logger = logging.getLogger(__name__)

Tema = enum.Enum("Tema", {chave: chave for chave in temas.CHAVES}, type=str)


class Modo(str, enum.Enum):
    geracao = "geracao"
    ajuste = "ajuste"
    revisao = "revisao"


class ParagrafoIA(BaseModel):
    id: str
    tema: Tema
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


def modelo():
    return settings.OPENAI_MODEL if provedor() == "openai" else settings.GEMINI_MODEL


def _chamar_gemini(sistema, conteudo, esquema, temperatura):
    from google import genai
    from google.genai import types

    cliente = genai.Client(api_key=settings.GEMINI_API_KEY)
    config = types.GenerateContentConfig(
        system_instruction=sistema,
        response_mime_type="application/json",
        response_schema=esquema,
        temperature=temperatura,
    )
    return cliente.models.generate_content(model=settings.GEMINI_MODEL, contents=conteudo, config=config).text


def _chamar_openai(sistema, conteudo, esquema, temperatura):
    from openai import BadRequestError, OpenAI

    cliente = OpenAI(api_key=settings.OPENAI_API_KEY)
    pedido = dict(
        model=settings.OPENAI_MODEL,
        messages=[{"role": "system", "content": sistema}, {"role": "user", "content": conteudo}],
        response_format=esquema,
    )
    try:
        resposta = cliente.chat.completions.parse(temperature=temperatura, **pedido)
    except BadRequestError as erro:
        # Modelos de raciocínio da OpenAI não aceitam temperatura; tenta sem ela.
        if "temperature" not in str(erro):
            raise
        resposta = cliente.chat.completions.parse(**pedido)
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
    passageiro = status in (429, 500, 502, 503, 504) or any(
        c in texto for c in ("503", "UNAVAILABLE", "500", "INTERNAL", "429", "RESOURCE_EXHAUSTED", "overloaded")
    )
    return sem_cota, passageiro and not sem_cota


def chamar(sistema, conteudo, esquema, temperatura):
    falta = _sem_chave()
    if falta:
        raise ErroGemini(falta)
    chamada = _chamar_openai if provedor() == "openai" else _chamar_gemini
    for tentativa, espera in enumerate(ESPERAS + [None], 1):
        try:
            texto = chamada(sistema, conteudo, esquema, temperatura)
            break
        except ErroGemini:
            raise
        except Exception as erro:  # os SDKs levantam vários tipos; mostramos a mensagem para a usuária
            sem_cota, passageiro = _classificar(erro)
            if passageiro and espera is not None:
                time.sleep(espera)
                continue
            logger.error("Falha na chamada à IA (%s, %s): %s", provedor(), modelo(), erro)
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


def gerar(sistema, conteudo):
    return chamar(sistema, conteudo, RespostaIA, temperatura=settings.GEMINI_TEMPERATURA)


def verificar(sistema, conteudo):
    return chamar(sistema, conteudo, RespostaVerificacao, temperatura=0.0)
