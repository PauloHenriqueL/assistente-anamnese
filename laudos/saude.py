"""Checagem de saúde para o Render saber se o servidor está de pé.

Fica num middleware no topo da lista para responder sem login, sem redirecionar
para HTTPS e sem conferir o host: a checagem do Render vem por dentro da rede.

Não toca no banco de propósito. O Render bate aqui a cada poucos segundos, o
dia inteiro; um `SELECT 1` em cada batida impedia o Neon de dormir (ele só
suspende depois de 5 min sem consulta) e o banco ficava acordado 24/7, pago.
"""

from django.http import JsonResponse

CAMINHO = "/saude/"


class SaudeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != CAMINHO:
            return self.get_response(request)
        return JsonResponse({"ok": True})
