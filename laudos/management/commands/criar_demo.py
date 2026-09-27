"""Cria um laudo de demonstração com paciente e anotações fictícios.

Serve para ver as telas sem chamar a IA. Nenhum dado é de paciente real.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from laudos.models import Avaliacao, Laudo, Mensagem, Paragrafo, Versao

PACIENTE = "Paciente fictício — demonstração"

ANAMNESE = """Bruno - 29a - demonstração
Queixa: procurou avaliação por conta própria após sugestão da psicóloga; quer entender a dificuldade de concluir tarefas.
Escola: sempre teve notas boas até o ensino médio; na faculdade de engenharia começou a atrasar trabalhos; trancou um semestre.
Atenção: se distrai com o celular durante reuniões; perde o fio das conversas longas; esquece compromissos se não anotar.
Rotina: usa alarmes para tudo; mesmo assim chega atrasado com frequência; a mesa de trabalho fica bagunçada.
Social: tem um grupo pequeno de amigos da escola; prefere encontros em casa; se cansa em festas grandes.
Sono: dorme por volta de 1h; acorda cansado; toma café três vezes ao dia.
Saúde: rinite.
Medicação: não faz uso.
HF: pai com diagnóstico de TDAH na vida adulta.
Profissionais: psicóloga há cerca de oito meses."""

PARAGRAFOS = [
    ("trajetoria_escolar",
     "No que se refere à trajetória acadêmica, Bruno relata que manteve bom desempenho escolar até o ensino médio, sem "
     "queixas de aprendizagem. Ao ingressar na faculdade de engenharia, passou a atrasar a entrega de trabalhos, "
     "acumulando pendências ao longo dos períodos. Informa que chegou a trancar um semestre diante dessa dificuldade.",
     ["sempre teve notas boas até o ensino médio", "na faculdade de engenharia começou a atrasar trabalhos", "trancou um semestre"],
     "like"),
    ("cognicao",
     "Em relação à atenção, descreve distrações frequentes com o celular durante reuniões de trabalho, perdendo o fio de "
     "conversas mais longas. Acrescenta que esquece compromissos quando não os registra.",
     ["se distrai com o celular durante reuniões", "perde o fio das conversas longas", "esquece compromissos se não anotar"],
     None),
    ("rotina",
     "Quanto à organização cotidiana, Bruno menciona utilizar alarmes para lembrar das atividades do dia. Ainda assim, "
     "refere atrasos frequentes e pontua que a mesa de trabalho costuma ficar desorganizada.",
     ["usa alarmes para tudo", "chega atrasado com frequência", "a mesa de trabalho fica bagunçada"],
     "deslike"),
    ("social",
     "Referente à socialização, mantém um grupo pequeno de amigos desde a época escolar, com quem prefere se encontrar em "
     "casa. Destaca que se cansa em festas grandes, optando por ambientes mais tranquilos.",
     ["tem um grupo pequeno de amigos da escola", "prefere encontros em casa", "se cansa em festas grandes"],
     None),
    ("sono",
     "Por fim, sobre o sono, relata que costuma se deitar por volta de uma hora da manhã e acorda cansado. Consome café "
     "três vezes ao dia.",
     ["dorme por volta de 1h", "acorda cansado", "toma café três vezes ao dia"],
     None),
    ("saude", "- Saúde: Refere ter rinite.", ["Saúde: rinite."], None),
    ("medicacao", "- Uso de Medicação: Não faz uso.", ["Medicação: não faz uso."], None),
    ("historico_familiar", "- Histórico Familiar: De acordo com Bruno, o pai recebeu diagnóstico de Transtorno do Déficit de "
     "Atenção e Hiperatividade (TDAH) na vida adulta.", ["HF: pai com diagnóstico de TDAH na vida adulta."], None),
    ("profissionais", "- Profissional que acompanha: Psicóloga (atendimento há cerca de oito meses).",
     ["Profissionais: psicóloga há cerca de oito meses."], None),
]


class Command(BaseCommand):
    help = "Cria um laudo de demonstração com dados fictícios, sem chamar a IA."

    @transaction.atomic
    def handle(self, *args, **opcoes):
        Laudo.objects.filter(paciente=PACIENTE).delete()
        laudo = Laudo.objects.create(paciente=PACIENTE, anamnese=ANAMNESE, arquivo_nome="anamnese_demonstracao.txt")
        Mensagem.objects.create(laudo=laudo, papel=Mensagem.USUARIA, texto="Gere a seção 4.2 completa a partir da anamnese acima.")
        resposta = Mensagem.objects.create(laudo=laudo, papel=Mensagem.IA, texto="Gerei a 4.2 com um parágrafo por tema e as linhas de dados no fim.")
        for posicao, (tema, texto, trechos, avaliacao) in enumerate(PARAGRAFOS):
            paragrafo = Paragrafo.objects.create(laudo=laudo, tema=tema, posicao=0)
            versao = Versao.objects.create(
                paragrafo=paragrafo, numero=1, texto=texto, trechos_origem=trechos,
                origem=Versao.GERACAO, mensagem=resposta,
            )
            if avaliacao == "like":
                Avaliacao.objects.create(versao=versao, tipo=Avaliacao.LIKE)
            elif avaliacao == "deslike":
                Avaliacao.objects.create(versao=versao, tipo=Avaliacao.DESLIKE, motivos=["curto", "faltou"])
        self.stdout.write(self.style.SUCCESS(f"Laudo de demonstração criado: /laudos/{laudo.id}/"))
