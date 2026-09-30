"""Fluxo de cada mensagem da psicóloga, dentro de uma seção do laudo.

1. A IA responde com os blocos criados ou alterados, em formato fixo.
2. Uma segunda chamada confere o que faltou do material e o que não tem apoio.
3. Se houver problema, a IA reescreve só os blocos afetados, uma única vez.
4. A reescrita é conferida de novo, e o que ainda sobrar vira aviso no bloco.
5. Cada bloco ganha uma nova versão; os demais ficam como estavam.

O material do caso é a anamnese, o texto atual das seções de que esta seção
depende e as mensagens da psicóloga na conversa desta seção.
"""

import difflib
import json

from django.db import transaction

from . import exemplos, gemini, prompt, secoes
from .models import Mensagem, Paragrafo, Versao

HISTORICO_MAXIMO = 12  # mensagens recentes enviadas como contexto
LIMITE_MUDANCA_REVISAO = 0.75  # abaixo disso, a revisão mudou demais o texto dela

ORIGEM_POR_MODO = {"geracao": Versao.GERACAO, "ajuste": Versao.AJUSTE, "revisao": Versao.REVISAO}

PEDIDO_INICIAL = secoes.ANAMNESE.pedido_inicial


def _estado_atual(laudo, secao):
    linhas = []
    for p in laudo.paragrafos_atuais(secao.chave):
        v = p.versao_atual()
        if v:
            linhas.append(f"[P{p.id}] tipo {p.tema}\n{v.texto}")
    return "\n\n".join(linhas)


def _secoes_de_contexto(laudo, secao):
    partes = []
    for chave in secao.contexto:
        texto = laudo.texto_secao(chave)
        titulo = secoes.secao(chave).titulo
        partes.append(f"## {titulo}\n{texto or 'Ainda não escrita.'}")
    return "\n\n".join(partes)


def _mensagens_da_psicologa(laudo, secao):
    return "\n".join(
        f"- {m.texto}" for m in laudo.mensagens.filter(secao=secao.chave, papel=Mensagem.USUARIA).order_by("criado_em", "id")
    )


def _historico(laudo, secao, excluir_id):
    mensagens = list(
        laudo.mensagens.filter(secao=secao.chave).exclude(id=excluir_id).order_by("-criado_em", "-id")[:HISTORICO_MAXIMO]
    )
    linhas = []
    for m in reversed(mensagens):
        if m.papel == Mensagem.USUARIA:
            linhas.append(f"Psicóloga: {m.texto}")
        elif m.texto:
            linhas.append(f"Você: {m.texto}")
    return "\n".join(linhas)


def _conteudo(laudo, secao, texto_usuaria, mensagem_id):
    partes = [f"# Anamnese anotada de {laudo.paciente}\n{laudo.anamnese}"]
    if secao.contexto:
        partes.append("# Seções anteriores do laudo, já aprovadas\n" + _secoes_de_contexto(laudo, secao))
    estado = _estado_atual(laudo, secao)
    partes.append(f"# {secao.titulo}, texto atual\n" + (estado or "Ainda não há blocos. Esta é a primeira geração da seção."))
    historico = _historico(laudo, secao, mensagem_id)
    if historico:
        partes.append("# Conversa recente desta seção\n" + historico)
    partes.append(f"# Nova mensagem da psicóloga\n{texto_usuaria}")
    return "\n\n".join(partes)


def _material(laudo, secao):
    partes = [f"# Anamnese\n{laudo.anamnese}"]
    if secao.contexto:
        partes.append("# Seções anteriores\n" + _secoes_de_contexto(laudo, secao))
    mensagens = _mensagens_da_psicologa(laudo, secao)
    if mensagens:
        partes.append("# Mensagens da psicóloga nesta seção\n" + mensagens)
    return "\n\n".join(partes)


def _mudanca(base, texto):
    return difflib.SequenceMatcher(None, base.split(), texto.split()).ratio()


def _secao_resultante(laudo, secao, paragrafos):
    """Texto da seção como ficaria com esta resposta, para a verificação ver o todo."""
    novos = {p.id for p in paragrafos}
    blocos = []
    for p in laudo.paragrafos_atuais(secao.chave):
        chave = f"P{p.id}"
        v = p.versao_atual()
        if chave not in novos and v:
            blocos.append(f"[{chave}] tipo {p.tema}\n{v.texto}")
    for p in paragrafos:
        blocos.append(f"[{p.id}] tipo {p.tema}\n{p.texto}")
    return "\n\n".join(blocos)


def _verificar(laudo, secao, paragrafos):
    """Devolve {id: {faltou, sem_apoio, mudou_demais}} só para quem tem problema."""
    problemas = {}
    for p in paragrafos:
        if p.modo.value == "revisao" and p.texto_base_usuaria and not p.pediu_acrescimo:
            if _mudanca(p.texto_base_usuaria, p.texto) < LIMITE_MUDANCA_REVISAO:
                problemas.setdefault(p.id, {"faltou": [], "sem_apoio": [], "mudou_demais": False})["mudou_demais"] = True

    conferir_faltou = {
        p.id for p in paragrafos if secao.conferir_faltou and (p.modo.value == "geracao" or p.pediu_acrescimo)
    }
    conteudo = (
        f"{_material(laudo, secao)}\n\n"
        f"# {secao.titulo}, texto escrito\n{_secao_resultante(laudo, secao, paragrafos)}\n\n"
        "# Blocos a conferir\n"
        + "\n".join(
            f"- {p.id}: tipo {p.tema}; conferir o que faltou: {'sim' if p.id in conferir_faltou else 'não'}"
            for p in paragrafos
        )
    )
    resultado = gemini.verificar(prompt.instrucao_verificacao(secao), conteudo)
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
            linhas.append("Acrescente o que faltou do material: " + "; ".join(pr["faltou"]))
        if pr["sem_apoio"]:
            linhas.append("Retire ou corrija o que não está no material: " + "; ".join(pr["sem_apoio"]))
        if pr["mudou_demais"]:
            linhas.append("Você mudou demais o texto dela. Volte ao texto dela e corrija só gramática e ligação entre frases.")
    anterior = json.dumps([p.model_dump(mode="json") for p in afetados], ensure_ascii=False, indent=1)
    return (
        f"{conteudo}\n\n# Sua resposta anterior para estes blocos\n{anterior}\n\n"
        "# Problemas encontrados na revisão\n" + "\n".join(linhas) + "\n\n"
        "Reescreva apenas estes blocos, mantendo o mesmo id, tipo e modo de cada um. "
        "Mantenha o estilo e a estrutura da seção. Deixe mensagem vazia e remover vazio."
    )


def _tipo_valido(secao, tipo):
    if tipo in secao.chaves_tipos:
        return tipo
    return "outro" if "outro" in secao.chaves_tipos else secao.chaves_tipos[-1]


def _aplicar(laudo, secao, resposta, avisos, mensagem_ia):
    existentes = {f"P{p.id}": p for p in laudo.paragrafos.filter(ativo=True, secao=secao.chave)}
    for chave in resposta.remover:
        if chave in existentes:
            existentes[chave].ativo = False
            existentes[chave].save(update_fields=["ativo"])
    for p in resposta.paragrafos:
        paragrafo = existentes.get(p.id)
        tipo = _tipo_valido(secao, p.tema)
        if paragrafo is None:
            posicao = laudo.paragrafos.filter(secao=secao.chave, tema=tipo).count()
            paragrafo = Paragrafo.objects.create(laudo=laudo, secao=secao.chave, tema=tipo, posicao=posicao)
        elif paragrafo.tema != tipo:
            paragrafo.tema = tipo
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
    """Dá um id próprio a cada bloco novo, para a verificação e a reescrita saberem de quem se fala."""
    contador = 0
    for p in resposta.paragrafos:
        if not p.id.startswith("P") or not p.id[1:].isdigit():
            contador += 1
            p.id = f"N{contador}"


def processar_mensagem(laudo, texto_usuaria, chave_secao="4.2"):
    secao = secoes.secao(chave_secao)
    texto_usuaria = (texto_usuaria or "").strip() or secao.pedido_inicial
    mensagem_usuaria = Mensagem.objects.create(laudo=laudo, secao=secao.chave, papel=Mensagem.USUARIA, texto=texto_usuaria)
    try:
        tipos_presentes = sorted({p.tema for p in laudo.paragrafos.filter(ativo=True, secao=secao.chave)}) or None
        sistema = prompt.instrucao_sistema(
            secao,
            exemplos.estilo(secao.chave),
            exemplos.pares(laudo.dono, secao.chave, tipos_presentes),
            exemplos.reforcos(laudo.dono, secao.chave),
        )
        conteudo = _conteudo(laudo, secao, texto_usuaria, mensagem_usuaria.id)

        resposta = gemini.gerar(sistema, conteudo, secao.chave)
        _ids_unicos(resposta)
        avisos = {}
        if resposta.paragrafos:
            problemas = _verificar(laudo, secao, resposta.paragrafos)
            if problemas:
                reescrita = gemini.gerar(sistema, _pedido_reescrita(conteudo, resposta, problemas), secao.chave)
                por_id = {p.id: p for p in reescrita.paragrafos if p.id in problemas}
                resposta.paragrafos = [por_id.get(p.id, p) for p in resposta.paragrafos]
                refeitos = [p for p in resposta.paragrafos if p.id in por_id]
                if refeitos:
                    avisos = _verificar(laudo, secao, refeitos)
                for chave in problemas:
                    if chave not in por_id:
                        avisos[chave] = problemas[chave]

        with transaction.atomic():
            mensagem_ia = Mensagem.objects.create(
                laudo=laudo, secao=secao.chave, papel=Mensagem.IA, texto=resposta.mensagem.strip()
            )
            _aplicar(laudo, secao, resposta, avisos, mensagem_ia)
        return mensagem_ia
    except gemini.ErroGemini as erro:
        return Mensagem.objects.create(laudo=laudo, secao=secao.chave, papel=Mensagem.IA, erro=str(erro))


def editar_versao(versao, texto):
    """Edição feita pela própria psicóloga na tela, sem passar pela IA."""
    paragrafo = versao.paragrafo
    numero = (paragrafo.versoes.order_by("-numero").values_list("numero", flat=True).first() or 0) + 1
    return Versao.objects.create(
        paragrafo=paragrafo,
        numero=numero,
        texto=texto.strip(),
        trechos_origem=versao.trechos_origem,
        origem=Versao.EDICAO,
    )


def situacao_das_secoes(laudo):
    """Para a visão geral: quantos blocos cada seção tem e o que falta das seções de base."""
    contagem = {s.chave: 0 for s in secoes.SECOES}
    for p in laudo.paragrafos.filter(ativo=True).values("secao"):
        contagem[p["secao"]] = contagem.get(p["secao"], 0) + 1
    resultado = []
    for s in secoes.SECOES:
        faltando = [secoes.secao(c).titulo for c in s.contexto if contagem.get(c, 0) == 0]
        resultado.append({"secao": s, "blocos": contagem[s.chave], "faltando": faltando})
    return resultado
