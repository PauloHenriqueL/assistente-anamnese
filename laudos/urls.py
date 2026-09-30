from django.contrib.auth.views import LogoutView
from django.urls import path

from . import acesso, views

urlpatterns = [
    path("entrar/", acesso.Entrar.as_view(), name="entrar"),
    path("sair/", LogoutView.as_view(), name="sair"),
    path("senha/", acesso.TrocarSenha.as_view(), name="senha"),
    path("senha/pronta/", acesso.SenhaPronta.as_view(), name="senha_pronta"),
    path("", views.lista, name="lista"),
    path("laudos/novo/", views.novo, name="novo"),
    path("laudos/<int:laudo_id>/", views.laudo, name="laudo"),
    path("laudos/<int:laudo_id>/texto/", views.texto_completo, name="texto_completo"),
    path("laudos/<int:laudo_id>/secao/<str:chave>/", views.secao, name="secao"),
    path("laudos/<int:laudo_id>/secao/<str:chave>/mensagem/", views.mensagem, name="mensagem"),
    path("laudos/<int:laudo_id>/secao/<str:chave>/texto/", views.texto_secao, name="texto_secao"),
    path("versoes/<int:versao_id>/avaliar/", views.avaliar, name="avaliar"),
    path("versoes/<int:versao_id>/editar/", views.editar, name="editar"),
    path("estatisticas/", views.estatisticas, name="estatisticas"),
]
