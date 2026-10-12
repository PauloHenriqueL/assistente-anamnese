"""Fluxo de cada mensagem da psicóloga, dentro de uma seção do laudo.

1. A IA responde com os blocos criados ou alterados, em formato fixo.
2. Uma segunda chamada confere o que faltou do material e o que não tem apoio.
3. Se houver problema, a IA reescreve só os blocos afetados, uma única vez.
4. A reescrita é conferida de novo, e o que ainda sobrar vira aviso no bloco.
5. Cada bloco ganha uma nova versão; os demais ficam como estavam.

O material do caso é a anamnese, o texto atual das seções de que esta seção
depende e as mensagens da psicóloga na conversa desta seção.

Com modelos que pensam, o fluxo leva minutos. Por isso a tela chama
`iniciar_mensagem`, que responde na hora e roda o fluxo numa thread; a mensagem
da psicóloga fica pendente até a resposta (ou o erro) ser gravada.
"""

import difflib
import json
import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone

from . import exemplos, gemini, perfil, prompt, secoes
from .models import Laudo, Mensagem, Paragrafo, Versao

logger = logging.getLogger(__name__)

HISTORICO_MAXIMO = 12  # mensagens recentes enviadas como contexto
LIMITE_MUDANCA_REVISAO = 0.75  # abaixo disso, a revisão mudou demais o texto dela
# Depois disso, uma geração pendente é dada como interrompida (o servidor reiniciou no meio, por exemplo).
PRAZO_DA_GERACAO = timedelta(minutes=25)
ERRO_INTERROMPIDA = "A geração foi interrompida antes de terminar. Envie a mensagem de novo."

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


def _conteudo(laudo, secao, texto_usuaria, mensagem_id, do_zero=False):
    """Pedido à IA. `do_zero` ignora o texto atual e a conversa, como numa primeira geração."""
    partes = [f"# Anamnese anotada de {laudo.paciente}\n{laudo.anamnese}"]
    if secao.contexto:
        partes.append("# Seções anteriores do laudo, já aprovadas\n" + _secoes_de_contexto(laudo, secao))
    estado = "" if do_zero else _estado_atual(laudo, secao)
    partes.append(f"# {secao.titulo}, texto atual\n" + (estado or "Ainda não há blocos. Esta é a primeira geração da seção."))
    historico = "" if do_zero else _historico(laudo, secao, mensagem_id)
    if historico:
        partes.append("# Conversa recente desta seção\n" + historico)
    partes.append(f"# Nova mensagem da psicóloga\n{texto_usuaria}")
    return "\n\n".join(partes)


def _material(laudo, secao, do_zero=False):
    partes = [f"# Anamnese\n{laudo.anamnese}"]
    if secao.contexto:
        partes.append("# Seções anteriores\n" + _secoes_de_contexto(laudo, secao))
    mensagens = "" if do_zero else _mensagens_da_psicologa(laudo, secao)
    if mensagens:
        partes.append("# Mensagens da psicóloga nesta seção\n" + mensagens)
    return "\n\n".join(partes)


def _mudanca(base, texto):
    return difflib.SequenceMatcher(None, base.split(), texto.split()).ratio()


def _secao_resultante(laudo, secao, paragrafos, do_zero=False):
    """Texto da seção como ficaria com esta resposta, para a verificação ver o todo."""
    novos = {p.id for p in paragrafos}
    blocos = []
    for p in [] if do_zero else laudo.paragrafos_atuais(secao.chave):
        chave = f"P{p.id}"
        v = p.versao_atual()
        if chave not in novos and v:
            blocos.append(f"[{chave}] tipo {p.tema}\n{v.texto}")
    for p in paragrafos:
        blocos.append(f"[{p.id}] tipo {p.tema}\n{p.texto}")
    return "\n\n".join(blocos)


def _verificar(laudo, secao, paragrafos, do_zero=False):
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
        f"{_material(laudo, secao, do_zero)}\n\n"
        f"# {secao.titulo}, texto escrito\n{_secao_resultante(laudo, secao, paragrafos, do_zero)}\n\n"
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


def _posicoes_livres(secao, existentes, resposta):
    """Posição de cada bloco da resposta, numa seção de ordem livre.

    Na primeira geração, ou quando a IA reescreve a seção inteira em modo geracao,
    a resposta define a ordem de todos os blocos. Num ajuste ou revisão, os blocos
    existentes ficam onde estão e os novos vão para o fim.
    """
    restantes = {k: p for k, p in existentes.items() if k not in resposta.remover}
    ids = [p.id for p in resposta.paragrafos]
    regerou_tudo = set(restantes) <= set(ids) and all(p.modo.value == "geracao" for p in resposta.paragrafos)
    if not restantes or regerou_tudo:
        return {chave: i for i, chave in enumerate(ids)}
    proxima = max((p.posicao for p in restantes.values()), default=-1) + 1
    novos = [chave for chave in ids if chave not in restantes]
    return {chave: proxima + i for i, chave in enumerate(novos)}


def _aplicar(laudo, secao, resposta, avisos, mensagem_ia):
    existentes = {f"P{p.id}": p for p in laudo.paragrafos.filter(ativo=True, secao=secao.chave)}
    posicoes = _posicoes_livres(secao, existentes, resposta) if secao.ordem_livre else {}
    for chave in resposta.remover:
        if chave in existentes:
            existentes[chave].ativo = False
            existentes[chave].save(update_fields=["ativo"])
    for p in resposta.paragrafos:
        paragrafo = existentes.get(p.id)
        tipo = _tipo_valido(secao, p.tema)
        if paragrafo is None:
            if secao.ordem_livre:
                posicao = posicoes[p.id]
            else:
                posicao = laudo.paragrafos.filter(secao=secao.chave, tema=tipo).count()
            paragrafo = Paragrafo.objects.create(laudo=laudo, secao=secao.chave, tema=tipo, posicao=posicao)
        else:
            campos = []
            if paragrafo.tema != tipo:
                paragrafo.tema = tipo
                campos.append("tema")
            if p.id in posicoes and paragrafo.posicao != posicoes[p.id]:
                paragrafo.posicao = posicoes[p.id]
                campos.append("posicao")
            if campos:
                paragrafo.save(update_fields=campos)
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


def preparar(laudo, secao, texto_usuaria, mensagem_id=None, do_zero=False, candidatos_estilo=None):
    """Prompt do sistema e conteúdo do pedido para uma mensagem da psicóloga.

    `candidatos_estilo` troca os laudos base do banco por outros (o comando de avaliação usa).
    """
    caso = perfil.do_texto(laudo.anamnese)
    tipos_presentes = None if do_zero else (
        sorted({p.tema for p in laudo.paragrafos.filter(ativo=True, secao=secao.chave)}) or None
    )
    sistema = prompt.instrucao_sistema(
        secao,
        exemplos.estilo(secao.chave, caso, candidatos_estilo),
        exemplos.pares(laudo.dono, secao.chave, tipos_presentes, caso["faixa"]),
        exemplos.reforcos(laudo.dono, secao.chave),
    )
    return sistema, _conteudo(laudo, secao, texto_usuaria, mensagem_id, do_zero)


def executar(laudo, secao, sistema, conteudo, do_zero=False, escolha=None):
    """Gera, verifica e reescreve uma vez. Só lê o banco: devolve (resposta, avisos).

    `escolha` = (modelo, raciocínio) da tela; vale para gerar e reescrever. A verificação usa o padrão.
    """
    resposta = gemini.gerar(sistema, conteudo, secao.chave, escolha)
    _ids_unicos(resposta)
    avisos = {}
    if resposta.paragrafos:
        problemas = _verificar(laudo, secao, resposta.paragrafos, do_zero)
        if problemas:
            reescrita = gemini.gerar(sistema, _pedido_reescrita(conteudo, resposta, problemas), secao.chave, escolha)
            por_id = {p.id: p for p in reescrita.paragrafos if p.id in problemas}
            resposta.paragrafos = [por_id.get(p.id, p) for p in resposta.paragrafos]
            refeitos = [p for p in resposta.paragrafos if p.id in por_id]
            if refeitos:
                avisos = _verificar(laudo, secao, refeitos, do_zero)
            for chave in problemas:
                if chave not in por_id:
                    avisos[chave] = problemas[chave]
    return resposta, avisos


def _liberar(mensagem_usuaria):
    """Tira a pendência. Devolve False se ela já tinha saído (geração dada como interrompida)."""
    return Mensagem.objects.filter(id=mensagem_usuaria.id, pendente=True).update(pendente=False) == 1


def _rotulo_escolha(mensagem_usuaria):
    modelo = mensagem_usuaria.modelo or gemini.modelo()
    pensar = "sem pensar" if mensagem_usuaria.raciocinio == "none" else "pensando"
    return f"{modelo}, {pensar}"


def responder(mensagem_usuaria):
    """Roda o fluxo para uma mensagem já gravada e grava a resposta ou o erro."""
    laudo, secao = mensagem_usuaria.laudo, secoes.secao(mensagem_usuaria.secao)
    escolha = (mensagem_usuaria.modelo, mensagem_usuaria.raciocinio) if mensagem_usuaria.raciocinio else None
    try:
        sistema, conteudo = preparar(laudo, secao, mensagem_usuaria.texto, mensagem_usuaria.id)
        resposta, avisos = executar(laudo, secao, sistema, conteudo, escolha=escolha)
        with transaction.atomic():
            if not _liberar(mensagem_usuaria):
                # Passou do prazo e já virou erro na tela; ela pode ter mandado de novo. Não aplica.
                logger.warning("Resposta da mensagem %s chegou depois do prazo e foi descartada", mensagem_usuaria.id)
                return None
            mensagem_ia = Mensagem.objects.create(
                laudo=laudo, secao=secao.chave, papel=Mensagem.IA, texto=resposta.mensagem.strip(),
                modelo=_rotulo_escolha(mensagem_usuaria),
            )
            _aplicar(laudo, secao, resposta, avisos, mensagem_ia)
        return mensagem_ia
    except gemini.ErroGemini as erro:
        erro_texto = str(erro)
    except Exception:
        # Qualquer falha inesperada também vira mensagem, para ela nunca ficar sem resposta.
        logger.exception("Falha inesperada ao responder a mensagem %s", mensagem_usuaria.id)
        erro_texto = "Algo deu errado ao gerar o texto. Envie a mensagem de novo e, se continuar, avise o responsável pelo sistema."
    if not _liberar(mensagem_usuaria):
        return None
    return Mensagem.objects.create(laudo=laudo, secao=secao.chave, papel=Mensagem.IA, erro=erro_texto)


def _registrar(laudo, texto_usuaria, secao, pendente, escolha=None):
    texto_usuaria = (texto_usuaria or "").strip() or secao.pedido_inicial
    modelo, raciocinio = escolha or ("", "")
    return Mensagem.objects.create(
        laudo=laudo, secao=secao.chave, papel=Mensagem.USUARIA, texto=texto_usuaria, pendente=pendente,
        modelo=modelo, raciocinio=raciocinio,
    )


def processar_mensagem(laudo, texto_usuaria, chave_secao="4.2", escolha=None):
    """Fluxo completo na hora, sem thread. Devolve a mensagem da IA."""
    return responder(_registrar(laudo, texto_usuaria, secoes.secao(chave_secao), pendente=True, escolha=escolha))


def _responder_em_thread(mensagem_id):
    try:
        responder(Mensagem.objects.select_related("laudo").get(id=mensagem_id))
    finally:
        connections.close_all()  # a thread abre conexões próprias com o banco


def em_andamento(laudo, chave_secao):
    """A mensagem pendente desta seção, se houver. Pendências velhas viram erro."""
    pendentes = laudo.mensagens.filter(secao=chave_secao, papel=Mensagem.USUARIA, pendente=True)
    limite = timezone.now() - PRAZO_DA_GERACAO
    for velha in pendentes.filter(criado_em__lt=limite):
        # Só quem tirar a pendência grava o erro: várias abas consultando ao mesmo tempo não duplicam.
        if _liberar(velha):
            Mensagem.objects.create(laudo=laudo, secao=chave_secao, papel=Mensagem.IA, erro=ERRO_INTERROMPIDA)
    return pendentes.filter(criado_em__gte=limite).order_by("-criado_em").first()


def iniciar_mensagem(laudo, texto_usuaria, chave_secao="4.2", escolha=None):
    """Grava a mensagem e começa a responder. Devolve None se já houver uma geração em andamento."""
    secao = secoes.secao(chave_secao)
    with transaction.atomic():
        # Trava o laudo: dois envios ao mesmo tempo (duas abas, clique duplo) não começam duas gerações.
        Laudo.objects.select_for_update().filter(id=laudo.id).first()
        if em_andamento(laudo, secao.chave):
            return None
        mensagem = _registrar(laudo, texto_usuaria, secao, pendente=True, escolha=escolha)
    if settings.IA_EM_SEGUNDO_PLANO:
        threading.Thread(target=_responder_em_thread, args=(mensagem.id,), daemon=True).start()
    else:
        responder(mensagem)
    return mensagem


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
