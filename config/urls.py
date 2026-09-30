from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Anamnese 4.2 · Administração"
admin.site.site_title = "Anamnese 4.2"
admin.site.index_title = "Usuários e dados do sistema"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("laudos.urls")),
]
