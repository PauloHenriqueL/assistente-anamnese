import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from laudos import secoes
from laudos.models import Exemplo


class Command(BaseCommand):
    help = (
        "Carrega como pares de exemplo os textos que a psicóloga aprovou nas conversas com o Gemini, a partir do "
        "arquivo revisado (um JSON por linha, com decisao manter ou corrigir). Substitui os importados antes."
    )

    def add_arguments(self, parser):
        parser.add_argument("arquivo")
        parser.add_argument("--usuario", required=True, help="Dona dos exemplos: só entram no prompt dela.")
        parser.add_argument("--simular", action="store_true", help="Mostra o que entraria, sem gravar.")

    def handle(self, *args, arquivo, usuario, simular, **opcoes):
        try:
            dona = get_user_model().objects.get(username=usuario)
        except get_user_model().DoesNotExist:
            raise CommandError(f"Usuário {usuario} não existe neste banco.")
        itens, ignorados = [], 0
        for numero, linha in enumerate(Path(arquivo).read_text(encoding="utf-8").splitlines(), 1):
            if not linha.strip():
                continue
            item = json.loads(linha)
            if item.get("decisao") not in ("manter", "corrigir"):
                ignorados += 1
                continue
            secao = secoes.POR_CHAVE.get(item["secao"])
            if secao is None or item["tema"] not in secao.chaves_tipos or not item.get("texto", "").strip():
                raise CommandError(f"Linha {numero}: seção, tema ou texto inválido ({item.get('id')}).")
            itens.append(item)
        if simular:
            for item in itens:
                self.stdout.write(f"{item['id']}: {item['secao']} {item['tema']} ({item.get('faixa', '?')}) "
                                  f"{'com' if item.get('trecho_origem') else 'sem'} material")
            self.stdout.write(f"{len(itens)} entrariam, {ignorados} descartados na revisão.")
            return
        with transaction.atomic():
            Exemplo.objects.filter(fonte=Exemplo.GEMINI, dono=dona).delete()
            for posicao, item in enumerate(itens):
                Exemplo.objects.create(
                    dono=dona, fonte=Exemplo.GEMINI, secao=item["secao"], tema=item["tema"],
                    trecho_origem=item.get("trecho_origem", "").strip(), texto=item["texto"].strip(),
                    grupo=item.get("id", ""), posicao=posicao, perfil={"faixa": item.get("faixa", "")},
                )
        self.stdout.write(self.style.SUCCESS(f"{len(itens)} exemplos do Gemini carregados para {usuario}; {ignorados} descartados."))
