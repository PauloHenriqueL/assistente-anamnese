"""Fluxo de cada mensagem da psicóloga.

1. O Gemini responde com os parágrafos criados ou alterados, em formato fixo.
2. Uma segunda chamada confere o que faltou das anotações e o que não tem apoio.
3. Se houver problema, o Gemini reescreve só os parágrafos afetados, uma única vez.
4. A reescrita é conferida de novo, e o que ainda sobrar vira aviso no parágrafo.
5. Cada parágrafo ganha uma nova versão; os demais ficam como estavam.
"""

import difflib
import json

from django.db import transaction

from . import exemplos, gemini, prompt
from .models import Mensagem, Paragrafo, Versao

HISTORICO_MAXIMO = 12  # mensagens recentes enviadas como contexto
LIMITE_MUDANCA_REVISAO = 0.75  # abaixo disso, a revisão mudou demais o texto dela

ORIGEM_POR_MODO = {"geracao": Versao.GERACAO, "ajuste": Versao.AJUSTE, "revisao": Versao.REVISAO}

PEDIDO_INICIAL = "Gere a seção 4.2 completa a partir da anamnese acima, com um parágrafo por tema e as quatro linhas de dados no fim."


def _estado_atual(laudo):
    linhas = []
    for p in laudo.paragrafos_atuais():
        v = p.versao_atual()
        if v:
            linhas.append(f"[P{p.id}] tema {p.tema}\n{v.texto}")
    return "\n\n".join(linhas)


def _historico(laudo, excluir_id):
    mensagens = list(laudo.mensagens.exclude(id=excluir_id).order_by("-criado_em", "-id")[:HISTORICO_MAXIMO])
    linhas = []
    for m in reversed(mensagens):
        if m.papel == Mensagem.USUARIA:
            linhas.append(f"Psicóloga: {m.texto}")
        elif m.texto:
            linhas.append(f"Você: {m.texto}")
    return "\n".join(linhas)


def _conteudo(laudo, texto_usuaria, mensagem_id):
    estado = _estado_atual(laudo)
    partes = [f"# Anamnese anotada de {laudo.paciente}\n{laudo.anamnese}"]
    partes.append("# Seção 4.2 atual\n" + (estado or "Ainda não há parágrafos. Esta é a primeira geração."))
    historico = _historico(laudo, mensagem_id)
    if historico:
        partes.append("# Conversa recente\n" + historico)
    partes.append(f"# Nova mensagem da psicóloga\n{texto_usuaria}")
    return "\n\n".join(partes)


def _mudanca(base, texto):
    return difflib.SequenceMatcher(None, base.split(), texto.split()).ratio()


def _secao_resultante(laudo, paragrafos):
    """Texto da 4.2 como ficaria com esta resposta, para a verificação ver o todo."""
    novos = {p.id: p for p in paragrafos}
    blocos = []
    for p in laudo.paragrafos_atuais():
        chave = f"P{p.id}"
        if chave in novos:
            continue
        v = p.versao_atual()
        if v:
            blocos.append(f"[{chave}] tema {p.tema}\n{v.texto}")
    for p in paragrafos:
        blocos.append(f"[{p.id}] tema {p.tema.value}\n{p.texto}")
    return "\n\n".join(blocos)


def _verificar(laudo, paragrafos):
    """Devolve {id: {faltou, sem_apoio, mudou_demais}} só para quem tem problema."""
    problemas = {}
    for p in paragrafos:
        if p.modo.value == "revisao" and p.texto_base_usuaria and not p.pediu_acrescimo:
            if _mudanca(p.texto_base_usuaria, p.texto) < LIMITE_MUDANCA_REVISAO:
                problemas.setdefault(p.id, {"faltou": [], "sem_apoio": [], "mudou_demais": False})["mudou_demais"] = True

    conferir_faltou = {p.id for p in paragrafos if p.modo.value == "geracao" or p.pediu_acrescimo}
    conteudo = (
        f"# Anotações de anamnese\n{laudo.anamnese}\n\n"
        f"# Seção 4.2 escrita\n{_secao_resultante(laudo, paragrafos)}\n\n"
        "# Parágrafos a conferir\n"
        + "\n".join(
            f"- {p.id}: tema {p.tema.value}; conferir o que faltou: {'sim' if p.id in conferir_faltou else 'não'}"
            for p in paragrafos
        )
    )
    resultado = gemini.verificar(prompt.VERIFICACAO, conteudo)
    ids = {p.id for p in paragrafos}
    for item in resultado.itens:
        if item.id not in ids:
            continue
        faltou = item.faltou if item.id in conferir_faltou else []
        if faltou or item.sem_apoio:
            registro = problemas.setdefault(item.id, {"faltou": [], "sem_apoio": [], "mudou_demais": False})
            registro["faltou"] = faltou
            registro["sem_apoio"] = item.sem_apoio
    return problemas


def _pedido_reescrita(conteudo, resposta, problemas):
    afetados = [p for p in resposta.paragrafos if p.id in problemas]
    linhas = []
    for p in afetados:
        pr = problemas[p.id]
        linhas.append(f"## {p.id}")
        if pr["faltou"]:
            linhas.append("Acrescente o que faltou das anotações: " + "; ".join(pr["faltou"]))
        if pr["sem_apoio"]:
            linhas.append("Retire ou corrija o que não está nas anotações: " + "; ".join(pr["sem_apoio"]))
        if pr["mudou_demais"]:
            linhas.append("Você mudou demais o texto dela. Volte ao texto dela e corrija só gramática e ligação entre frases.")
    anterior = json.dumps([p.model_dump(mode="json") for p in afetados], ensure_ascii=False, indent=1)
    return (
        f"{conteudo}\n\n# Sua resposta anterior para estes parágrafos\n{anterior}\n\n"
        "# Problemas encontrados na revisão\n" + "\n".join(linhas) + "\n\n"
        "Reescreva apenas estes parágrafos, mantendo o mesmo id, tema e modo de cada um. "
        "Mantenha o estilo e a ordem cronológica. Deixe mensagem vazia e remover vazio."
    )


def _aplicar(laudo, resposta, avisos, mensagem_ia):
    existentes = {f"P{p.id}": p for p in laudo.paragrafos.filter(ativo=True)}
    for chave in resposta.remover:
        if chave in existentes:
            existentes[chave].ativo = False
            existentes[chave].save(update_fields=["ativo"])
    for p in resposta.paragrafos:
        paragrafo = existentes.get(p.id)
        tema = p.tema.value
        if paragrafo is None:
            posicao = laudo.paragrafos.filter(tema=tema).count()
            paragrafo = Paragrafo.objects.create(laudo=laudo, tema=tema, posicao=posicao)
        elif paragrafo.tema != tema:
            paragrafo.tema = tema
            paragrafo.save(update_fields=["tema"])
        numero = (paragrafo.versoes.order_by("-numero").values_list("numero", flat=True).first() or 0) + 1
        aviso = avisos.get(p.id, {})
        Versao.objects.create(
            paragrafo=paragrafo,
            numero=numero,
            texto=p.texto.strip(),
            trechos_origem=p.trechos_origem,
            origem=ORIGEM_POR_MODO.get(p.modo.value, Versao.AJUSTE),
            faltou=aviso.get("faltou", []),
            sem_apoio=aviso.get("sem_apoio", []),
            mensagem=mensagem_ia,
        )


def _ids_unicos(resposta):
    """Dá um id próprio a cada parágrafo novo, para a verificação e a reescrita saberem de quem se fala."""
    contador = 0
    for p in resposta.paragrafos:
        if not p.id.startswith("P") or not p.id[1:].isdigit():
            contador += 1
            p.id = f"N{contador}"


def processar_mensagem(laudo, texto_usuaria):
    texto_usuaria = (texto_usuaria or "").strip() or PEDIDO_INICIAL
    mensagem_usuaria = Mensagem.objects.create(laudo=laudo, papel=Mensagem.USUARIA, texto=texto_usuaria)
    try:
        temas_presentes = sorted({p.tema for p in laudo.paragrafos.filter(ativo=True)}) or None
        sistema = prompt.instrucao_sistema(exemplos.estilo(), exemplos.pares(temas_presentes), exemplos.reforcos())
        conteudo = _conteudo(laudo, texto_usuaria, mensagem_usuaria.id)

        resposta = gemini.gerar(sistema, conteudo)
        _ids_unicos(resposta)
        avisos = {}
        if resposta.paragrafos:
            problemas = _verificar(laudo, resposta.paragrafos)
            if problemas:
                reescrita = gemini.gerar(sistema, _pedido_reescrita(conteudo, resposta, problemas))
                por_id = {p.id: p for p in reescrita.paragrafos if p.id in problemas}
                resposta.paragrafos = [por_id.get(p.id, p) for p in resposta.paragrafos]
                refeitos = [p for p in resposta.paragrafos if p.id in por_id]
                if refeitos:
                    avisos = _verificar(laudo, refeitos)
                for chave in problemas:
                    if chave not in por_id:
                        avisos[chave] = problemas[chave]

        with transaction.atomic():
            mensagem_ia = Mensagem.objects.create(laudo=laudo, papel=Mensagem.IA, texto=resposta.mensagem.strip())
            _aplicar(laudo, resposta, avisos, mensagem_ia)
        return mensagem_ia
    except gemini.ErroGemini as erro:
        return Mensagem.objects.create(laudo=laudo, papel=Mensagem.IA, erro=str(erro))


def editar_versao(versao, texto):
    """Edição feita pela própria psicóloga na tela, sem passar pelo Gemini."""
    paragrafo = versao.paragrafo
    numero = (paragrafo.versoes.order_by("-numero").values_list("numero", flat=True).first() or 0) + 1
    return Versao.objects.create(
        paragrafo=paragrafo,
        numero=numero,
        texto=texto.strip(),
        trechos_origem=versao.trechos_origem,
        origem=Versao.EDICAO,
    )

