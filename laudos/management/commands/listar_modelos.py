from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from laudos import gemini


class Command(BaseCommand):
    help = "Lista os modelos disponíveis para a chave do provedor configurado em IA_PROVEDOR."

    def handle(self, *args, **opcoes):
        falta = gemini._sem_chave()
        if falta:
            raise CommandError(falta)
        if gemini.provedor() == "openai":
            from openai import OpenAI

            nomes = sorted(m.id for m in OpenAI(api_key=settings.OPENAI_API_KEY).models.list())
            for nome in nomes:
                if nome.startswith(("gpt", "o1", "o3", "o4", "chatgpt")):
                    self.stdout.write(nome)
        else:
            from google import genai

            cliente = genai.Client(api_key=settings.GEMINI_API_KEY)
            for modelo in cliente.models.list():
                if "generateContent" in (getattr(modelo, "supported_actions", None) or []):
                    self.stdout.write(modelo.name.removeprefix("models/"))
        self.stdout.write(f"\nProvedor: {gemini.provedor()} · modelo em uso agora: {gemini.modelo()}")
