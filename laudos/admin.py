from django.contrib import admin

from .models import Avaliacao, Exemplo, Laudo, Mensagem, Paragrafo, Versao


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
    list_display = ("versao", "tipo", "motivos", "criado_em")
    list_filter = ("tipo",)


@admin.register(Exemplo)
class ExemploAdmin(admin.ModelAdmin):
    list_display = ("tema", "fonte", "grupo", "ativo", "criado_em")
    list_filter = ("fonte", "tema", "ativo")


admin.site.register(Mensagem)
