"""Escolha dos exemplos que entram no prompt e dos reforços vindos dos deslikes.

Sem banco vetorial por enquanto: os pares aprovados são escolhidos pelo tema.
Quando houver centenas de pares, a busca por semelhança pode entrar aqui,
com pgvector no mesmo Postgres.
"""

from collections import Counter, defaultdict

from .models import Avaliacao, Exemplo

POR_TEMA = 2
MAXIMO_PARES = 16

REFORCOS = {
    "curto": "Ela tem achado os parágrafos curtos. Escreva cada parágrafo com todo o material das anotações sobre o tema.",
    "faltou": "Ela tem notado informação faltando. Confira se cada item das anotações entrou em algum parágrafo.",
    "inventou": "Ela tem notado invenções. Escreva só o que está nas anotações, sem acrescentar época, causa ou intensidade.",
    "sem_ligacao": "Ela tem achado as frases soltas. Ligue as ideias com conectivos e gerúndios, formando uma narrativa.",
    "rebuscado": "Ela tem achado o texto rebuscado. Prefira palavras simples e não troque palavras por sinônimos formais.",
    "fora_de_ordem": "Ela tem achado o texto fora de ordem. Siga a linha do tempo dentro de cada parágrafo.",
    "mudou_meu_texto": "Ela tem reclamado de mudanças no texto dela. Ao revisar, altere o mínimo possível.",
}


def estilo(secao="4.2"):
    grupos = defaultdict(list)
    for ex in Exemplo.objects.filter(fonte=Exemplo.LAUDO_BASE, ativo=True, secao=secao).order_by("grupo", "posicao"):
        grupos[ex.grupo].append(ex.texto)
    return dict(grupos)


def pares(dono, secao="4.2", temas_presentes=None):
    """Pares aprovados pela própria usuária nesta seção. Exemplos de uma nunca entram no prompt de outra."""
    consulta = (
        Exemplo.objects.filter(fonte=Exemplo.LIKE, ativo=True, dono=dono, secao=secao)
        .exclude(trecho_origem="")
        .order_by("-criado_em")
    )
    if temas_presentes:
        consulta = consulta.filter(tema__in=temas_presentes)
    escolhidos, por_tema = [], Counter()
    for ex in consulta:
        if por_tema[ex.tema] >= POR_TEMA:
            continue
        por_tema[ex.tema] += 1
        escolhidos.append({"tema": ex.tema, "trecho_origem": ex.trecho_origem, "texto": ex.texto})
        if len(escolhidos) >= MAXIMO_PARES:
            break
    return escolhidos


def contagem_motivos(dono, secao=None, ultimos=None):
    consulta = Avaliacao.objects.filter(tipo=Avaliacao.DESLIKE, versao__paragrafo__laudo__dono=dono)
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
