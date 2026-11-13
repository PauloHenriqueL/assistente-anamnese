from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .models import Avaliacao, Exemplo, Laudo, Mensagem, Paragrafo, Papel, Versao

User = get_user_model()


class PapelInline(admin.StackedInline):
    """Papel e gestor responsável, na própria página do usuário. Sem preencher, a pessoa é analista sem gestor."""

    model = Papel
    fk_name = "usuario"
    can_delete = False
    min_num = 1
    max_num = 1


class UsuarioAdmin(UserAdmin):
    inlines = [PapelInline]
    list_display = ("username", "first_name", "last_name", "papel_na_lista", "gestor_na_lista", "is_active", "is_superuser")
    list_select_related = ("papel__gestor",)

    @admin.display(description="Papel")
    def papel_na_lista(self, usuario):
        papel = getattr(usuario, "papel", None)
        return papel.get_tipo_display() if papel else "Analista"

    @admin.display(description="Gestor responsável")
    def gestor_na_lista(self, usuario):
        papel = getattr(usuario, "papel", None)
        return papel.gestor if papel and papel.gestor_id else "—"

    def get_inlines(self, request, obj):
        # Na criação o Django pede só usuário e senha; o papel aparece ao salvar e continuar.
        return self.inlines if obj else []


admin.site.unregister(User)
admin.site.register(User, UsuarioAdmin)


class VersaoInline(admin.TabularInline):
    model = Versao
    extra = 0
    fields = ("numero", "origem", "texto", "faltou", "sem_apoio")


@admin.register(Laudo)
class LaudoAdmin(admin.ModelAdmin):
    list_display = ("paciente", "criado_em")


@admin.register(Paragrafo)
class ParagrafoAdmin(admin.ModelAdmin):
    list_display = ("laudo", "tema", "posicao", "ativo")
    list_filter = ("tema", "ativo")
    inlines = [VersaoInline]


@admin.register(Avaliacao)
class AvaliacaoAdmin(admin.ModelAdmin):
    list_display = ("versao", "tipo", "motivos", "autor", "criado_em")
    list_filter = ("tipo",)


@admin.register(Exemplo)
class ExemploAdmin(admin.ModelAdmin):
    list_display = ("tema", "fonte", "dono", "grupo", "ativo", "criado_em")
    list_filter = ("fonte", "tema", "ativo")


admin.site.register(Mensagem)
