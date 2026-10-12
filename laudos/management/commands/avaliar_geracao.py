import difflib
import json
import re
import time
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from laudos import secoes, servico
from laudos.management.commands.carregar_exemplos import ARQUIVO_REAL, blocos_do_arquivo
from laudos.models import Exemplo, Laudo

VERBOS_DE_RELATO = [
    "relata", "informa", "refere", "menciona", "descreve", "destaca", "afirma", "cita", "explica", "recorda",
    "ressalta", "reconhece", "pontua", "acrescenta", "conta", "observa", "aponta", "declara", "esclarece", "enfatiza",
]
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

    def handle(self, *args, laudo, secao, saida, exemplos, **opcoes):
        s = secoes.secao(secao)
        candidatos = self._candidatos(exemplos) if exemplos else None
        partes = [f"# Avaliação da geração da seção {s.titulo}", ""]
        for laudo_id in laudo:
            try:
                obj = Laudo.objects.get(id=laudo_id)
            except Laudo.DoesNotExist:
                raise CommandError(f"Laudo {laudo_id} não existe neste banco.")
            self.stdout.write(f"Gerando a seção {s.chave} do laudo {laudo_id}...")
            inicio = time.monotonic()
            sistema, conteudo = servico.preparar(obj, s, s.pedido_inicial, do_zero=True, candidatos_estilo=candidatos)
            resposta, avisos = servico.executar(obj, s, sistema, conteudo, do_zero=True)
            segundos = time.monotonic() - inicio
            blocos = sorted(
                enumerate(resposta.paragrafos), key=lambda par: s.chave_ordem(par[1].tema, par[0], par[0])
            )
            novo = [(p.tema, p.texto.strip(), avisos.get(p.id, {})) for _, p in blocos]
            atual = [(p.tema, p.versao_atual().texto) for p in obj.paragrafos_atuais(s.chave) if p.versao_atual()]
            partes += self._relatorio(obj, novo, atual, segundos, len(sistema) + len(conteudo))
        Path(saida).write_text("\n".join(partes), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Relatório em {saida}"))

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

    def _relatorio(self, laudo, novo, atual, segundos, tamanho_prompt):
        titulos = [m.group(1).strip() for m in map(TITULO_DE_ANOTACAO.match, laudo.anamnese.splitlines()) if m]
        texto_novo = "\n\n".join(t for _, t, _ in novo)
        texto_atual = "\n\n".join(t for _, t in atual)
        semelhanca = difflib.SequenceMatcher(None, texto_novo.split(), texto_atual.split()).ratio() if atual else 0
        m_novo, m_atual = self._metricas([t for _, t, _ in novo]), self._metricas([t for _, t in atual])
        linhas = [
            f"## Laudo {laudo.id}",
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
        return linhas
