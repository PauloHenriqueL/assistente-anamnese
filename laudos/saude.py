"""Checagem de saúde para o Render saber se o servidor está de pé.

Fica num middleware no topo da lista para responder sem login, sem redirecionar
para HTTPS e sem conferir o host: a checagem do Render vem por dentro da rede.
"""

import logging

from django.db import connection
from django.http import JsonResponse

logger = logging.getLogger(__name__)

CAMINHO = "/saude/"


class SaudeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != CAMINHO:
            return self.get_response(request)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:
            logger.exception("Checagem de saúde: o banco não respondeu")
            return JsonResponse({"ok": False, "banco": False}, status=503)
        return JsonResponse({"ok": True, "banco": True})
