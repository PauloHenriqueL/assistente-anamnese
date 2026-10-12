import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from laudos import laudos_base, perfil
from laudos.management.commands.carregar_exemplos import ARQUIVO_REAL

PASTA_PADRAO = Path(__file__).resolve().parents[3] / "laudos_exemplos"


class Command(BaseCommand):
    help = (
        "Extrai dos laudos finais em PDF (pasta laudos_exemplos/) as seções que o sistema escreve, anonimizadas, "
        "e grava laudos_base.json. Gera um relatório para revisão antes de rodar carregar_exemplos."
    )

    def add_arguments(self, parser):
        parser.add_argument("--pasta", default=str(PASTA_PADRAO))
        parser.add_argument("--saida", default=str(ARQUIVO_REAL))
        parser.add_argument(
            "--substituicoes", default=None,
            help="Arquivo com trocas extras, uma por linha: Nome que sobrou => substituto. "
                 "Padrão: substituicoes.txt dentro da pasta, se existir.",
        )

    def handle(self, *args, pasta, saida, substituicoes, **opcoes):
        pasta = Path(pasta)
        pdfs = sorted(pasta.glob("*.pdf"))
        if not pdfs:
            raise CommandError(f"Nenhum PDF em {pasta}.")
        extras = self._substituicoes(Path(substituicoes) if substituicoes else pasta / "substituicoes.txt")
        dados, relatorio, usados = {}, ["# Revisão da anonimização dos laudos base", ""], {"F": 0, "M": 0}
        for i, pdf in enumerate(pdfs, 1):
            paginas = laudos_base.ler_pdf(pdf)
            # A primeira página costuma ser uma capa em imagem, sem texto.
            ident = laudos_base.identificacao([l for pagina in paginas[:3] for l in pagina])
            lista = laudos_base.PSEUDONIMOS[ident["sexo"]]
            pseudonimo = lista[usados[ident["sexo"]] % len(lista)]
            usados[ident["sexo"]] += 1
            secoes = laudos_base.secoes(paginas)
            chaves = list(secoes)
            textos, trocas = laudos_base.anonimizar(["\n\n".join(secoes[c]) for c in chaves], ident, pseudonimo, extras)
            anonimas = dict(zip(chaves, textos))
            idade = ident["idade"]
            faixa = "" if idade is None else ("adulto" if idade >= 18 else "crianca")
            caso = {"faixa": faixa, "queixas": perfil.queixas(anonimas.get("2", "") + "\n" + anonimas.get("4.2", ""))}
            chave = f"laudo_{i:02d}"
            nome = f"Laudo {i} ({'adulto' if faixa == 'adulto' else 'criança ou adolescente' if faixa else 'idade não lida'})"
            dados[chave] = {
                "nome": nome,
                "perfil": caso,
                "secoes": {c: [{"tema": "", "texto": t}] for c, t in anonimas.items()},
            }
            relatorio += self._relatorio(pdf, nome, caso, ident, pseudonimo, trocas, anonimas)
        Path(saida).write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        caminho = pasta / "revisao_laudos_base.md"
        caminho.write_text("\n".join(relatorio), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"{len(dados)} laudos extraídos para {saida}."))
        self.stdout.write(
            f"Revise {caminho} antes de rodar carregar_exemplos. Nomes que sobraram vão para "
            f"{pasta / 'substituicoes.txt'} (Nome => substituto) e o comando roda de novo."
        )

    def _substituicoes(self, caminho):
        if not caminho.exists():
            return {}
        trocas = {}
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if "=>" in linha and not linha.lstrip().startswith("#"):
                alvo, substituto = (p.strip() for p in linha.split("=>", 1))
                if alvo:
                    trocas[alvo] = substituto
        return trocas

    def _relatorio(self, pdf, nome, caso, ident, pseudonimo, trocas, anonimas):
        linhas = [f"## {nome} — arquivo {pdf.name}", ""]
        linhas.append(f"- Perfil: faixa {caso['faixa'] or '?'}, queixas {', '.join(caso['queixas']) or 'nenhuma detectada'}")
        linhas.append(f"- Paciente → {pseudonimo} (sexo {ident['sexo']}, idade {ident['idade']})")
        for alvo, substituto in sorted(trocas.items()):
            linhas.append(f"  - troca: {alvo} → {substituto}")
        for chave in ("2", "4.2", "5.1", "5.2", "6"):
            texto = anonimas.get(chave)
            linhas.append(f"- Seção {chave}: " + (f"{len(texto.split())} palavras" if texto else "NÃO ENCONTRADA"))
        achados = laudos_base.suspeitos(anonimas.values())
        if achados:
            linhas.append("- Possíveis nomes que sobraram (confira; se for nome, ponha em substituicoes.txt):")
            linhas += [f"  - **{palavra}**: …{contexto}…" for palavra, contexto in sorted(achados.items())]
        linhas.append("")
        return linhas
