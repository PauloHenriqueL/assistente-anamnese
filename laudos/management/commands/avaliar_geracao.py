import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from laudos import exemplos as exemplos_ia
from laudos import secoes, servico
from laudos.conferencia import VERBOS_DE_RELATO
from laudos.management.commands.carregar_exemplos import ARQUIVO_REAL, blocos_do_arquivo
from laudos.models import Exemplo, Laudo

PALAVRAS_A_EVITAR = [
    "paixão", "genitora", "genitor", "descendente", "significativo", "significativa", "severo", "severa", "extremo",
    "extrema", "imprescindível", "inúmeras", "perfeitamente", "total ausência", "estado anímico", "atípicos",
    "o que sugere", "o que evidencia", "o que reflete", "a investigação",
]
TITULO_DE_ANOTACAO = re.compile(r"^\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇa-záéíóúâêôãõç ,/]{3,40}):\s*$")


class Command(BaseCommand):
    help = (
        "Gera de novo uma seção de laudos existentes, sem gravar nada no banco, e compara com o texto atual "
        "(as versões que a psicóloga editou). Chama a IA de verdade: usa a chave e os modelos do .env."
    )

    def add_arguments(self, parser):
        parser.add_argument("--laudo", type=int, action="append", required=True, help="Id do laudo; pode repetir.")
        parser.add_argument("--secao", default="4.2")
        parser.add_argument("--saida", required=True, help="Arquivo .md do relatório. Contém dados do paciente: fora do repositório.")
        parser.add_argument(
            "--exemplos", default=str(ARQUIVO_REAL),
            help="laudos_base.json usado como exemplos de estilo no lugar dos do banco. Use --exemplos '' para os do banco.",
        )
        parser.add_argument(
            "--config", action="append", choices=sorted(exemplos_ia.CONFIGURACOES),
            help="Configuração de exemplos (laudos/exemplos.py); pode repetir para comparar. Padrão: EXEMPLOS_CONFIG.",
        )
        parser.add_argument("--rodadas", type=int, default=1, help="Gerações por laudo e configuração; a IA varia de uma para outra.")

    def handle(self, *args, laudo, secao, saida, exemplos, config, rodadas, **opcoes):
        s = secoes.secao(secao)
        candidatos = self._candidatos(exemplos) if exemplos else None
        configs = config or [settings.EXEMPLOS_CONFIG]
        laudos = []
        for laudo_id in laudo:
            try:
                laudos.append(Laudo.objects.get(id=laudo_id))
            except Laudo.DoesNotExist:
                raise CommandError(f"Laudo {laudo_id} não existe neste banco.")
        detalhes, resultados = [], defaultdict(list)
        for nome in configs:
            for obj in laudos:
                for rodada in range(1, rodadas + 1):
                    self.stdout.write(f"Config {nome}, laudo {obj.id}, rodada {rodada}: gerando a seção {s.chave}...")
                    inicio = time.monotonic()
                    sistema, conteudo = servico.preparar(
                        obj, s, s.pedido_inicial, do_zero=True, candidatos_estilo=candidatos, config=nome
                    )
                    resposta, avisos = servico.executar(obj, s, sistema, conteudo, do_zero=True)
                    segundos = time.monotonic() - inicio
                    blocos = sorted(
                        enumerate(resposta.paragrafos), key=lambda par: s.chave_ordem(par[1].tema, par[0], par[0])
                    )
                    novo = [(p.tema, p.texto.strip(), avisos.get(p.id, {})) for _, p in blocos]
                    atual = [(p.tema, p.versao_atual().texto) for p in obj.paragrafos_atuais(s.chave) if p.versao_atual()]
                    linhas, medidas = self._relatorio(
                        obj, novo, atual, segundos, len(sistema) + len(conteudo), f"config {nome}, rodada {rodada}"
                    )
                    detalhes += linhas
                    resultados[nome].append(medidas)
        partes = [f"# Avaliação da geração da seção {s.titulo}", ""] + self._resumo(resultados) + detalhes
        Path(saida).write_text("\n".join(partes), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Relatório em {saida}"))

    def _resumo(self, resultados):
        """Média por configuração. Melhor = semelhança maior sem mais itens sem apoio."""
        linhas = [
            "## Resumo por configuração",
            "",
            "| Config | Gerações | Semelhança média | Sem apoio por geração | Pode ter faltado por geração | Prompt (caracteres) | Tempo médio |",
            "|---|---|---|---|---|---|---|",
        ]
        for nome, medidas in resultados.items():
            n = len(medidas)
            media = lambda chave: sum(m[chave] for m in medidas) / n
            linhas.append(
                f"| {nome} | {n} | {media('semelhanca'):.3f} | {media('sem_apoio'):.1f} | {media('faltou'):.1f} "
                f"| {media('prompt'):.0f} | {media('segundos'):.0f} s |"
            )
        return linhas + [""]

    def _candidatos(self, caminho):
        caminho = Path(caminho)
        if not caminho.exists():
            raise CommandError(f"{caminho} não existe. Rode extrair_laudos ou use --exemplos ''.")
        return [Exemplo(**kwargs) for kwargs in blocos_do_arquivo(json.loads(caminho.read_text(encoding="utf-8")))]

    def _metricas(self, textos):
        junto = "\n".join(textos).lower()
        verbos = Counter({v: len(re.findall(rf"\b{v}\b", junto)) for v in VERBOS_DE_RELATO})
        evitar = {p: junto.count(p) for p in PALAVRAS_A_EVITAR if p in junto}
        tamanhos = [len(t.split()) for t in textos]
        return {
            "parágrafos": len(textos),
            "palavras": sum(tamanhos),
            "palavras por parágrafo": f"{min(tamanhos, default=0)} a {max(tamanhos, default=0)}",
            "verbos de relato mais usados": ", ".join(f"{v} {n}" for v, n in verbos.most_common(5) if n),
            "palavras a evitar": ", ".join(f"{p} {n}" for p, n in evitar.items()) or "nenhuma",
            "aspas": junto.count('"') + junto.count("“"),
        }

    def _relatorio(self, laudo, novo, atual, segundos, tamanho_prompt, rotulo):
        """(linhas do relatório, medidas para o resumo) de uma geração."""
        titulos = [m.group(1).strip() for m in map(TITULO_DE_ANOTACAO.match, laudo.anamnese.splitlines()) if m]
        texto_novo = "\n\n".join(t for _, t, _ in novo)
        texto_atual = "\n\n".join(t for _, t in atual)
        semelhanca = exemplos_ia.semelhanca(texto_novo, texto_atual) if atual else 0
        m_novo, m_atual = self._metricas([t for _, t, _ in novo]), self._metricas([t for _, t in atual])
        medidas = {
            "semelhanca": semelhanca,
            "sem_apoio": sum(len(a.get("sem_apoio", [])) for _, _, a in novo),
            "faltou": sum(len(a.get("faltou", [])) for _, _, a in novo),
            "prompt": tamanho_prompt,
            "segundos": segundos,
        }
        linhas = [
            f"## Laudo {laudo.id} ({rotulo})",
            "",
            f"- Tempo total (gerar, verificar, reescrever): {segundos:.0f} s; prompt com {tamanho_prompt} caracteres",
            f"- Semelhança com o texto atual dela: {semelhanca:.2f}",
            f"- Títulos nas anotações, na ordem: {' → '.join(titulos) or 'nenhum detectado'}",
            f"- Ordem dos blocos gerados: {' → '.join(t for t, _, _ in novo)}",
            f"- Ordem do texto atual dela: {' → '.join(t for t, _ in atual) or 'vazio'}",
            "",
            "| Métrica | Gerado agora | Texto atual dela |",
            "|---|---|---|",
        ]
        linhas += [f"| {k} | {m_novo[k]} | {m_atual[k]} |" for k in m_novo]
        linhas += ["", "### Texto gerado agora", ""]
        for tema, texto, aviso in novo:
            linhas.append(f"**[{tema}]** {texto}")
            if aviso.get("faltou"):
                linhas.append(f"> Pode ter faltado: {'; '.join(aviso['faltou'])}")
            if aviso.get("sem_apoio"):
                linhas.append(f"> Sem apoio: {'; '.join(aviso['sem_apoio'])}")
            linhas.append("")
        linhas += ["### Texto atual dela", ""] + [f"**[{tema}]** {texto}\n" for tema, texto in atual]
        return linhas, medidas
