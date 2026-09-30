"""Entrada, saída e troca de senha.

O login bloqueia por 15 minutos depois de 5 senhas erradas para o mesmo
usuário vindas do mesmo endereço, o que torna inviável adivinhar a senha.
"""

from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy

LIMITE_TENTATIVAS = 5
BLOQUEIO_SEGUNDOS = 15 * 60


def _ip(request):
    encaminhado = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return encaminhado.split(",")[0].strip() if encaminhado else request.META.get("REMOTE_ADDR", "")


def _chave(request, usuario):
    return f"login-falhas:{_ip(request)}:{(usuario or '').strip().lower()}"


class FormularioEntrada(AuthenticationForm):
    error_messages = {
        "invalid_login": "Usuário ou senha incorretos.",
        "inactive": "Este acesso está desativado.",
        "bloqueado": "Muitas tentativas erradas. Espere 15 minutos e tente de novo.",
    }

    def clean(self):
        chave = _chave(self.request, self.data.get("username"))
        if cache.get(chave, 0) >= LIMITE_TENTATIVAS:
            raise ValidationError(self.error_messages["bloqueado"], code="bloqueado")
        try:
            dados = super().clean()
        except ValidationError:
            cache.set(chave, cache.get(chave, 0) + 1, BLOQUEIO_SEGUNDOS)
            raise
        cache.delete(chave)
        return dados


class Entrar(auth_views.LoginView):
    template_name = "laudos/entrar.html"
    authentication_form = FormularioEntrada
    redirect_authenticated_user = True


class TrocarSenha(auth_views.PasswordChangeView):
    template_name = "laudos/senha.html"
    success_url = reverse_lazy("senha_pronta")


class SenhaPronta(auth_views.PasswordChangeDoneView):
    template_name = "laudos/senha_pronta.html"
