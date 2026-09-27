import json
from pathlib import Path

from django.core.management.base import BaseCommand

from laudos.models import Exemplo

PASTA = Path(__file__).resolve().parents[2] / "seeds"
# laudos_base.json tem a 4.2 de laudos reais aprovados e nunca vai para o repositório.
# Sem ele, o sistema usa o exemplo fictício, que existe só para demonstração.
ARQUIVO_REAL = PASTA / "laudos_base.json"
ARQUIVO_EXEMPLO = PASTA / "laudos_base.exemplo.json"
NOMES = {
    "laudo_adulto_caio": "Laudo de adulto",
    "laudo_crianca_tiago": "Laudo de criança",
    "laudo_ficticio_demonstracao": "Laudo fictício de demonstração",
}


class Command(BaseCommand):
    help = "Carrega a 4.2 dos laudos aprovados como exemplos de estilo. Pode rodar mais de uma vez."

    def handle(self, *args, **opcoes):
        arquivo = ARQUIVO_REAL if ARQUIVO_REAL.exists() else ARQUIVO_EXEMPLO
        if arquivo is ARQUIVO_EXEMPLO:
            self.stdout.write(self.style.WARNING("Usando o exemplo fictício. Coloque laudos_base.json em laudos/seeds/ para usar os laudos reais."))
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        Exemplo.objects.filter(fonte=Exemplo.LAUDO_BASE).delete()
        total = 0
        for chave, paragrafos in dados.items():
            for posicao, p in enumerate(paragrafos):
                Exemplo.objects.create(
                    tema=p["tema"], texto=p["texto"], fonte=Exemplo.LAUDO_BASE, grupo=NOMES.get(chave, chave), posicao=posicao
                )
                total += 1
        self.stdout.write(self.style.SUCCESS(f"{total} parágrafos de laudos base carregados."))
