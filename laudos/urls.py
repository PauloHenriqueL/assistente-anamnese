from django.urls import path

from . import views

urlpatterns = [
    path("", views.lista, name="lista"),
    path("laudos/novo/", views.novo, name="novo"),
    path("laudos/<int:laudo_id>/", views.laudo, name="laudo"),
    path("laudos/<int:laudo_id>/mensagem/", views.mensagem, name="mensagem"),
    path("laudos/<int:laudo_id>/texto/", views.texto_42, name="texto_42"),
    path("versoes/<int:versao_id>/avaliar/", views.avaliar, name="avaliar"),
    path("versoes/<int:versao_id>/editar/", views.editar, name="editar"),
    path("estatisticas/", views.estatisticas, name="estatisticas"),
]
