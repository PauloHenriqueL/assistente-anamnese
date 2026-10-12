import json
from pathlib import Path

from django.core.management.base import BaseCommand

from laudos.models import Exemplo

PASTA = Path(__file__).resolve().parents[2] / "seeds"
# laudos_base.json tem seções de laudos reais aprovados (gerado por extrair_laudos) e nunca vai para o repositório.
# Sem ele, o sistema usa o exemplo fictício, que existe só para demonstração.
ARQUIVO_REAL = PASTA / "laudos_base.json"
ARQUIVO_EXEMPLO = PASTA / "laudos_base.exemplo.json"
NOMES = {
    "laudo_adulto_caio": "Laudo de adulto",
    "laudo_crianca_tiago": "Laudo de criança",
    "laudo_ficticio_demonstracao": "Laudo fictício de demonstração",
}


class Command(BaseCommand):
    help = "Carrega as seções dos laudos aprovados como exemplos de estilo. Pode rodar mais de uma vez."

    def handle(self, *args, **opcoes):
        arquivo = ARQUIVO_REAL if ARQUIVO_REAL.exists() else ARQUIVO_EXEMPLO
        if arquivo is ARQUIVO_EXEMPLO:
            self.stdout.write(self.style.WARNING("Usando o exemplo fictício. Coloque laudos_base.json em laudos/seeds/ para usar os laudos reais."))
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        Exemplo.objects.filter(fonte=Exemplo.LAUDO_BASE).delete()
        for kwargs in blocos_do_arquivo(dados):
            Exemplo.objects.create(**kwargs)
        self.stdout.write(self.style.SUCCESS(f"{Exemplo.objects.filter(fonte=Exemplo.LAUDO_BASE).count()} blocos de laudos base carregados."))


def blocos_do_arquivo(dados):
    """Campos de cada Exemplo de laudo base a partir do conteúdo de um laudos_base.json.

    Formatos aceitos:
    - antigo: lista de parágrafos da 4.2;
    - por seção: {seção: [blocos]};
    - atual (extrair_laudos): {"nome", "perfil", "secoes": {seção: [blocos]}}.
    """
    for chave, conteudo in dados.items():
        perfil, grupo = {}, NOMES.get(chave, chave)
        if isinstance(conteudo, list):
            por_secao = {"4.2": conteudo}
        elif "secoes" in conteudo:
            por_secao, perfil, grupo = conteudo["secoes"], conteudo.get("perfil", {}), conteudo.get("nome", grupo)
        else:
            por_secao = conteudo
        for secao, blocos in por_secao.items():
            for posicao, p in enumerate(blocos):
                yield dict(
                    secao=secao, tema=p.get("tema", ""), texto=p["texto"], fonte=Exemplo.LAUDO_BASE,
                    grupo=grupo, posicao=posicao, perfil=perfil,
                )
