"""Quem é gestor, quem é analista e o que cada um alcança.

Gestor é quem avalia: os likes, deslikes e edições dele formam o padrão que a IA
segue para todo mundo. Analista escreve os laudos sem avaliar. O gestor abre,
avalia e edita os laudos dos analistas vinculados a ele, mas a conversa com a IA
e a montagem da seção (inserir, excluir) são só de quem é dono do laudo.
"""

from django.contrib.auth import get_user_model
from django.db.models import Q

from .models import Papel


def eh_gestor(usuario):
    # Sem registro de papel, o acesso reverso levanta um erro que o getattr trata como ausência.
    papel = getattr(usuario, "papel", None)
    return papel is not None and papel.tipo == Papel.GESTOR


def gestores():
    """Todos os gestores: é o conjunto das avaliações deles que vira o padrão da IA."""
    return get_user_model().objects.filter(papel__tipo=Papel.GESTOR)


def analistas_de(usuario):
    """Analistas vinculados a este gestor. Quem deixou de ser gestor não alcança mais ninguém."""
    User = get_user_model()
    if not eh_gestor(usuario):
        return User.objects.none()
    return User.objects.filter(papel__tipo=Papel.ANALISTA, papel__gestor=usuario)


def alcanca(usuario, prefixo=""):
    """Filtro dos laudos que a pessoa pode abrir: os dela e os dos analistas dela.

    `prefixo` é o caminho até o laudo a partir do modelo consultado, por exemplo "paragrafo__laudo__".
    """
    return Q(**{f"{prefixo}dono": usuario}) | Q(**{f"{prefixo}dono__in": analistas_de(usuario)})
