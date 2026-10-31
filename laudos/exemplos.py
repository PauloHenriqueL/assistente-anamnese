"""Escolha dos exemplos que entram no prompt e dos reforços vindos dos deslikes.

Sem banco vetorial por enquanto. Os exemplos de estilo são seções inteiras dos
laudos base, escolhidas pelo perfil do caso (faixa etária e queixas). Os pares
aprovados são escolhidos pelo tema, preferindo os da mesma faixa etária. As
correções são textos da IA que ela reescreveu, mostrados como antes e depois.
O laudo que está sendo escrito nunca serve de exemplo para si mesmo.
"""

import difflib
from collections import Counter, defaultdict
from dataclasses import dataclass

from django.conf import settings

from . import perfil as perfis
from .models import Avaliacao, Exemplo, Paragrafo, Versao

# Laudos base cujas seções inteiras entram no prompt de cada chamada.
MAXIMO_LAUDOS_BASE = 4
# Edição que mudou menos que isso do texto da IA (uma vírgula, uma palavra) não vira correção.
MUDANCA_MINIMA_CORRECAO = 0.05
ORIGENS_DA_IA = [Versao.GERACAO, Versao.AJUSTE, Versao.REVISAO]


@dataclass(frozen=True)
class Configuracao:
    """Quanto dos exemplos dela entra no prompt.

    Com rodízio, todo tema presente ganha um exemplo antes de algum ganhar o segundo.
    Sem rodízio, os mais recentes ocupam as vagas, até `por_tema` cada.
    """

    por_tema: int
    maximo: int
    rodizio: bool
    correcoes: int


# Comparadas com avaliar_geracao --config. "A" é o comportamento original.
CONFIGURACOES = {
    "A": Configuracao(por_tema=2, maximo=16, rodizio=False, correcoes=0),
    "B": Configuracao(por_tema=3, maximo=40, rodizio=True, correcoes=0),
    "C": Configuracao(por_tema=3, maximo=40, rodizio=True, correcoes=8),
    "D": Configuracao(por_tema=5, maximo=60, rodizio=True, correcoes=8),
}


def configuracao(nome=None):
    return CONFIGURACOES[nome or settings.EXEMPLOS_CONFIG]


def semelhanca(a, b):
    """De 0 (nada em comum) a 1 (mesmas palavras na mesma ordem)."""
    return difflib.SequenceMatcher(None, a.split(), b.split()).ratio()

REFORCOS = {
    "curto": "Ela tem achado os parágrafos curtos. Escreva cada parágrafo com todo o material das anotações sobre o tema.",
    "faltou": "Ela tem notado informação faltando. Confira se cada item das anotações entrou em algum parágrafo.",
    "inventou": "Ela tem notado invenções. Escreva só o que está nas anotações, sem acrescentar época, causa ou intensidade.",
    "sem_ligacao": "Ela tem achado as frases soltas. Ligue as ideias com conectivos e gerúndios, formando uma narrativa.",
    "rebuscado": "Ela tem achado o texto rebuscado. Prefira palavras simples e não troque palavras por sinônimos formais.",
    "fora_de_ordem": "Ela tem achado o texto fora de ordem. Siga a linha do tempo dentro de cada parágrafo.",
    "mudou_meu_texto": "Ela tem reclamado de mudanças no texto dela. Ao revisar, altere o mínimo possível.",
}


def estilo(secao="4.2", perfil=None, candidatos=None):
    """Seções inteiras dos laudos base, dos casos mais parecidos com o perfil dado.

    `candidatos` permite passar exemplos fora do banco (o comando de avaliação usa).
    """
    if candidatos is None:
        candidatos = Exemplo.objects.filter(fonte=Exemplo.LAUDO_BASE, ativo=True, secao=secao).order_by("grupo", "posicao")
    grupos, perfil_do_grupo = defaultdict(list), {}
    for ex in candidatos:
        if ex.secao != secao:
            continue
        grupos[ex.grupo].append(ex.texto)
        perfil_do_grupo.setdefault(ex.grupo, ex.perfil or {})
    nomes = list(grupos)
    if perfil:
        # sorted é estável: em empate, fica a ordem original dos laudos.
        nomes.sort(key=lambda g: -perfis.semelhanca(perfil, perfil_do_grupo[g]))
    return {g: grupos[g] for g in nomes[:MAXIMO_LAUDOS_BASE]}


def pares(dono, secao="4.2", temas_presentes=None, faixa="", laudo=None, config=None):
    """Pares aprovados pela própria usuária nesta seção. Exemplos de uma nunca entram no prompt de outra."""
    config = config or configuracao()
    consulta = (
        Exemplo.objects.filter(fonte__in=Exemplo.FONTES_DE_PARES, ativo=True, dono=dono, secao=secao)
        .exclude(trecho_origem="")
        .order_by("-criado_em")
    )
    if laudo is not None:
        consulta = consulta.exclude(versao__paragrafo__laudo=laudo)
    if temas_presentes:
        consulta = consulta.filter(tema__in=temas_presentes)
    candidatos = list(consulta)
    if faixa:
        # Os da mesma faixa etária primeiro; dentro de cada grupo, os mais recentes.
        candidatos.sort(key=lambda ex: (ex.perfil or {}).get("faixa") != faixa)
    if config.rodizio:
        fila = defaultdict(list)
        for ex in candidatos:
            fila[ex.tema].append(ex)
        ordem = [lista[rodada] for rodada in range(config.por_tema) for lista in fila.values() if rodada < len(lista)]
    else:
        ordem, por_tema = [], Counter()
        for ex in candidatos:
            if por_tema[ex.tema] < config.por_tema:
                por_tema[ex.tema] += 1
                ordem.append(ex)
    return [{"tema": ex.tema, "trecho_origem": ex.trecho_origem, "texto": ex.texto} for ex in ordem[: config.maximo]]


def _texto_da_ia_e_edicao(versoes):
    """(última versão da IA, última edição dela depois dela) de um parágrafo, ou None se ela não editou."""
    da_ia = [v for v in versoes if v.origem in ORIGENS_DA_IA]
    if not da_ia:
        return None
    ia = max(da_ia, key=lambda v: v.numero)
    editadas = [v for v in versoes if v.origem == Versao.EDICAO and v.numero > ia.numero]
    return ia, max(editadas, key=lambda v: v.numero) if editadas else None


def correcoes(dono, secao="4.2", temas_presentes=None, laudo=None, maximo=8):
    """Textos da IA que ela reescreveu: o mais recente de cada tema, com os rótulos dos motivos que ela marcou."""
    rotulos = dict(Avaliacao.MOTIVOS)
    paragrafos = (
        Paragrafo.objects.filter(laudo__dono=dono, secao=secao, versoes__origem=Versao.EDICAO)
        .distinct()
        .prefetch_related("versoes__avaliacoes")
    )
    if laudo is not None:
        paragrafos = paragrafos.exclude(laudo=laudo)
    if temas_presentes:
        paragrafos = paragrafos.filter(tema__in=temas_presentes)
    candidatas = []
    for p in paragrafos:
        par = _texto_da_ia_e_edicao(list(p.versoes.all()))
        if not par or not par[1]:
            continue
        ia, ela = par
        if 1 - semelhanca(ia.texto, ela.texto) < MUDANCA_MINIMA_CORRECAO:
            continue
        motivos = [rotulos.get(m, m) for av in ia.avaliacoes.all() if av.tipo == Avaliacao.DESLIKE for m in av.motivos]
        candidatas.append((ela.criado_em, {"tema": p.tema, "ia": ia.texto, "ela": ela.texto, "motivos": motivos}))
    candidatas.sort(key=lambda c: c[0], reverse=True)
    escolhidas, temas = [], set()
    for _, c in candidatas:
        if c["tema"] not in temas:
            temas.add(c["tema"])
            escolhidas.append(c)
    return escolhidas[:maximo]


def edicoes_por_mes(dono):
    """Por mês do texto da IA: [(mês, parágrafos, editados, % editados, % médio do texto mudado nas edições)].

    Se a IA aprende o padrão dela, ela edita menos parágrafos e muda menos em cada um.
    """
    meses = defaultdict(lambda: [0, 0, 0.0])
    for p in Paragrafo.objects.filter(laudo__dono=dono).prefetch_related("versoes"):
        par = _texto_da_ia_e_edicao(list(p.versoes.all()))
        if not par:
            continue
        ia, ela = par
        mes = meses[ia.criado_em.strftime("%Y-%m")]
        mes[0] += 1
        if ela:
            mes[1] += 1
            mes[2] += 1 - semelhanca(ia.texto, ela.texto)
    return [
        (chave, total, editados, round(100 * editados / total), round(100 * soma / editados) if editados else 0)
        for chave, (total, editados, soma) in sorted(meses.items(), reverse=True)
    ]


def contagem_motivos(dono, secao=None, ultimos=None):
    # Deslike sem motivo (comum quando ela só reescreve o texto) não entra: diluiria os motivos reais.
    consulta = Avaliacao.objects.filter(tipo=Avaliacao.DESLIKE, versao__paragrafo__laudo__dono=dono).exclude(motivos=[])
    if secao:
        consulta = consulta.filter(versao__paragrafo__secao=secao)
    consulta = consulta.order_by("-criado_em")
    if ultimos:
        consulta = consulta[:ultimos]
    contagem = Counter()
    total = 0
    for av in consulta:
        total += 1
        contagem.update(av.motivos)
    return contagem, total


def reforcos(dono, secao="4.2"):
    """Regras extras para os motivos que aparecem em boa parte dos deslikes recentes da usuária na seção."""
    contagem, total = contagem_motivos(dono, secao=secao, ultimos=30)
    if total == 0:
        return ""
    linhas = [
        REFORCOS[motivo]
        for motivo, vezes in contagem.most_common()
        if motivo in REFORCOS and vezes >= 3 and vezes / total >= 0.3
    ]
    return "\n".join(f"- {linha}" for linha in linhas)
