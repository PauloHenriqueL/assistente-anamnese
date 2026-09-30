"""As seções do laudo que o sistema escreve, na ordem numérica.

Cada seção tem uma conversa própria. A IA recebe a anamnese, o texto atual
das seções de que ela depende e a conversa daquela seção, onde a psicóloga
conta os resultados dos testes e as decisões clínicas.
"""

from dataclasses import dataclass, field

from . import temas


@dataclass(frozen=True)
class Secao:
    chave: str
    titulo: str
    rotulo: str
    descricao: str
    tipos: list
    contexto: list = field(default_factory=list)
    conferir_faltou: bool = False
    minimo_palavras: int = 0
    sem_minimo: frozenset = frozenset()
    pedido_inicial: str = ""
    regras: str = ""
    regras_verificacao: str = ""

    @property
    def chaves_tipos(self):
        return [chave for chave, _ in self.tipos]

    @property
    def ordem_tipos(self):
        return {chave: i for i, chave in enumerate(self.chaves_tipos)}

    def rotulo_tipo(self, tipo):
        return dict(self.tipos).get(tipo, tipo)


DEMANDA = Secao(
    chave="2",
    titulo="2. DESCRIÇÃO DA DEMANDA",
    rotulo="Descrição da demanda",
    descricao="Quem pediu a avaliação, o que se investiga e o que se espera entender.",
    tipos=[("demanda", "Descrição da demanda")],
    minimo_palavras=40,
    pedido_inicial="Escreva a descrição da demanda a partir da anamnese.",
    regras="""
Esta seção é um parágrafo único, de três a seis frases. Diga quem solicitou a avaliação, o motivo, o que se busca investigar, diagnósticos ou tratamentos anteriores e o que o paciente ou a família espera entender. A fonte é a queixa registrada na anamnese.
Abra com A avaliação neuropsicológica foi solicitada por, seguido de quem pediu. Se ela disser na conversa quem solicitou, use exatamente isso.
Não escreva hipóteses diagnósticas que estão só na anotação interna da psicóloga. Só cite suspeitas ou diagnósticos que aparecem na queixa do paciente, da família ou de quem encaminhou.
Em criança, quem relata costuma ser a mãe ou o pai; atribua a queixa a quem a trouxe.
""",
    regras_verificacao="Aceite a frase de abertura sobre quem solicitou quando a psicóloga tiver dito isso na conversa.",
)

ANAMNESE = Secao(
    chave="4.2",
    titulo="4.2 DADOS DA ENTREVISTA DE ANAMNESE",
    rotulo="Dados da entrevista de anamnese",
    descricao="Um parágrafo por tema, na ordem do laudo, e as linhas de dados no fim.",
    tipos=temas.TEMAS,
    conferir_faltou=True,
    minimo_palavras=temas.MINIMO_PALAVRAS,
    sem_minimo=frozenset(temas.LINHAS_DE_DADOS),
    pedido_inicial="Gere a seção 4.2 completa a partir da anamnese, com um parágrafo por tema e as quatro linhas de dados no fim.",
    regras="""
O que ela mais reclama nesta seção:
1. Parágrafos curtos, que perdem a complexidade do caso. Cada parágrafo carrega todas as informações que as anotações trazem sobre o tema, com os exemplos concretos. Nos laudos dela, um parágrafo de tema tem entre 90 e 200 palavras. Não encha linguiça: o tamanho vem do conteúdo das anotações.
2. Informação cortada. Tudo o que está nas anotações aparece em algum parágrafo, a não ser que ela peça para tirar ou marque como pessoal.
3. Pontos jogados sem ligação. Ligue as frases com conectivos para formar uma narrativa.
4. Falta de ordem. Dentro de cada parágrafo, siga a linha do tempo: infância, adolescência, fase adulta e, por último, como é atualmente.

Cada parágrafo abre anunciando o tema, e as aberturas variam: No que se refere a, Em relação a, Quanto a, No que tange a, No que concerne a, Referente a, No âmbito de, Acerca de, Sobre. O último parágrafo de tema costuma abrir com Por fim.

A seção termina com quatro linhas curtas, cada uma começando pelo rótulo: - Saúde:, - Uso de Medicação:, - Histórico Familiar: e - Profissional que acompanha:. Medicamentos e doses ficam como nas anotações. Familiares aparecem pelo parentesco.
""",
)

RELACAO = Secao(
    chave="5.1",
    titulo="5.1 CONCLUSÃO: RELAÇÃO ENTRE OS INSTRUMENTOS E OS RELATOS",
    rotulo="Relação entre instrumentos e relatos",
    descricao="Cruza os resultados dos testes com o que aparece na rotina do paciente.",
    tipos=[
        ("abertura", "Abertura"),
        ("contraste", "Testes e rotina"),
        ("comportamental_emocional", "Aspectos comportamentais e emocionais"),
        ("social", "Aspectos sociais"),
        ("outro", "Outro ponto"),
    ],
    contexto=["2", "4.2"],
    minimo_palavras=50,
    pedido_inicial="Escreva a seção 5.1 com o que já temos na conversa.",
    regras="""
Esta seção cruza os resultados dos testes com a vida real do paciente. Os resultados vêm do que a psicóloga contar na conversa; os relatos vêm da anamnese e da seção 4.2.
Se a conversa ainda não trouxer nenhum resultado de teste, não escreva parágrafos: peça os resultados na mensagem.
Sequência dos laudos dela:
1. Abertura: o perfil foi construído integrando os testes, as observações e os relatos; quais habilidades ficaram adequadas nos testes; e o lembrete de que o desempenho em ambiente controlado nem sempre reflete a rotina, por isso os escores são interpretados junto com os relatos.
2. Contrastes: quando o teste foi bom, mas o relato mostra dificuldade, ou o contrário, diga isso de forma direta e com o exemplo concreto da rotina, como Apesar do desempenho satisfatório no teste de atenção concentrada, os relatos indicam...
3. Consonâncias: quando teste e relato apontam na mesma direção, descreva o prejuízo com o exemplo da rotina.
4. Aspectos comportamentais e emocionais: o que as escalas e entrevistas apontaram.
5. Aspectos sociais, quando houver, abrindo com Por fim ou Em relação às interações sociais.
Use só os nomes de testes, escores e classificações que ela informou. Nunca invente resultado.
""",
    regras_verificacao="Os resultados de testes vêm das mensagens da psicóloga nesta seção. A frase geral sobre a validade ecológica dos testes é padrão do laudo e não precisa de apoio.",
)

HIPOTESES = Secao(
    chave="5.2",
    titulo="5.2 CONCLUSÃO: HIPÓTESES DIAGNÓSTICAS",
    rotulo="Hipóteses diagnósticas",
    descricao="Diagnósticos que ela decidiu, com os critérios do caso, e as hipóteses descartadas.",
    tipos=[
        ("abertura", "Abertura"),
        ("diagnostico", "Diagnóstico ou hipótese"),
        ("integracao", "Integração dos achados"),
        ("hipotese_descartada", "Hipótese descartada"),
        ("fechamento", "Fechamento"),
    ],
    contexto=["2", "4.2", "5.1"],
    minimo_palavras=40,
    sem_minimo=frozenset({"fechamento", "abertura"}),
    pedido_inicial="Escreva a seção 5.2 com os diagnósticos e as hipóteses que eu indiquei na conversa.",
    regras="""
O diagnóstico é decisão da psicóloga. Escreva só os diagnósticos e as hipóteses descartadas que ela indicar na conversa. Se ela ainda não disse qual é o diagnóstico ou o que foi descartado, não escreva parágrafos: pergunte na mensagem. Nunca sugira um diagnóstico por conta própria no texto do laudo. Se ela pedir sua opinião, responda só na mensagem, com base no material do caso, e deixe a decisão com ela.

Estrutura dos laudos dela:
- Abertura padrão: Esta avaliação neuropsicológica constitui um exame clínico complementar e seus resultados devem ser interpretados de forma integrada aos dados históricos e demais avaliações multidisciplinares. Diante da análise integrada das entrevistas clínicas, observações comportamentais e resultados de testagens padronizadas, em conformidade com os critérios do DSM-5-TR (Manual Diagnóstico e Estatístico de Transtornos Mentais) e CID-11 (Classificação Internacional de Doenças), este documento atua como um importante auxílio no diagnóstico.
- Um parágrafo por diagnóstico ou hipótese: o nome do transtorno, a especificação quando houver, os códigos do DSM-5-TR e da CID-11, a definição do DSM-5-TR e a frase Durante a avaliação de [nome], foi possível analisar manifestações compatíveis com esse perfil, incluindo:, seguida dos critérios. Cada critério leva um exemplo do próprio caso entre parênteses, começando com p. ex. Os critérios ficam na mesma frase, separados por ponto e vírgula. Os exemplos mostram como o sintoma aparece na vida do paciente; números de teste não entram neles. Critério sem exemplo no material não ganha exemplo inventado.
- O segundo diagnóstico em diante pode abrir com Concomitantemente ou Do mesmo modo.
- Quando ela disser que não há segurança para fechar o diagnóstico, escreva como hipótese e explique os fatores que impedem o fechamento, como fez em laudos anteriores.
- Um parágrafo por hipótese descartada, abrindo com A hipótese de... não se sustenta ou Descarta-se a hipótese de..., explicando com os dados do caso por que os sinais são mais bem explicados por outra condição. O argumento mais forte fica por último.
- Fechamento: o diagnóstico como processo dinâmico, o acompanhamento da evolução e, se ela indicar, a reavaliação em um prazo.
Use os códigos que ela informar. Se não informar, use o código que você considera correto e peça conferência na mensagem.
""",
    regras_verificacao=(
        "Nesta seção, os nomes dos transtornos, as definições do DSM-5-TR, os códigos e as frases padrão de abertura e "
        "fechamento não precisam de apoio no material. Marque como sem apoio: um diagnóstico ou hipótese que a psicóloga "
        "não indicou na conversa e todo exemplo de critério entre parênteses que não aparece no material do caso."
    ),
)

RECOMENDACOES = Secao(
    chave="6",
    titulo="6. RECOMENDAÇÕES E ENCAMINHAMENTOS",
    rotulo="Recomendações e encaminhamentos",
    descricao="Psiquiatria, psicologia com os focos de intervenção, outras áreas, escola e observação final.",
    tipos=[
        ("psiquiatria", "Psiquiatria"),
        ("outras_medicas", "Outras especialidades médicas"),
        ("psicologia", "Psicologia"),
        ("outras_especialidades", "Outros profissionais"),
        ("escola", "Escola"),
        ("atividades", "Atividades do dia a dia"),
        ("reavaliacao", "Reavaliação"),
        ("observacao", "Observação final"),
    ],
    contexto=["4.2", "5.1", "5.2"],
    minimo_palavras=0,
    pedido_inicial="Escreva as recomendações e os encaminhamentos a partir das seções anteriores e do que eu indicar.",
    regras="""
Cada encaminhamento é um bloco que abre com o rótulo da área seguido de dois-pontos, como Psiquiatria:, Psicologia:, Psicopedagogia: ou Escola:.
- Psiquiatria usa o texto padrão: Sugere-se o acompanhamento psiquiátrico para definição das estratégias terapêuticas sob competência desta especialidade. A interlocução entre as áreas é fundamental para subsidiar decisões e a análise sobre o manejo farmacológico.
- Psicologia: frase de abertura com continuidade do acompanhamento psicoterapêutico, se o paciente já faz terapia, ou início, se não faz, com a abordagem que ela indicar, terminando em dois-pontos. Depois, de quatro a seis focos de intervenção, cada um numa linha própria do mesmo bloco, ligados às dificuldades deste paciente. Cada foco começa com um substantivo de ação diferente, como Fortalecimento, Estratégias voltadas ao aprimoramento, Implementação de recursos, Desenvolvimento de técnicas, Exploração e consolidação ou Adoção de técnicas direcionadas, seguido do objetivo, com o objetivo de, visando ou com o intuito de. Cada foco termina com ponto e vírgula, e o último com ponto. Os focos saem das dificuldades descritas nas seções 4.2, 5.1 e 5.2.
- Outras áreas, como neuropediatria, psicopedagogia, fonoaudiologia, terapia ocupacional ou professora particular, só quando ela pedir ou quando as seções anteriores indicarem claramente a necessidade; nesse caso, pergunte na mensagem antes de incluir.
- Escola, em criança e adolescente: orientações práticas em linhas próprias, cada uma com um título curto seguido de dois-pontos, como Posicionamento estratégico: ou Adaptação em avaliações:.
- Atividades do dia a dia, quando ela pedir: ações concretas e viáveis que o paciente consegue fazer sozinho, no mesmo formato dos focos da psicologia.
- Reavaliação: Recomenda-se o acompanhamento longitudinal e a atualização desta avaliação em [prazo]. O objetivo é realizar o acompanhamento dos sintomas e validar a persistência dos critérios diagnósticos. Use o prazo que ela indicar; no modelo dela, 2 anos.
- Observação final, texto padrão: Observação: Os achados deste laudo refletem o estado neuropsicológico atual do paciente. Considerando a natureza dinâmica do desenvolvimento cognitivo, emocional e comportamental, bem como os potenciais efeitos de intervenções, estes resultados possuem caráter temporal e não devem ser interpretados como imutáveis. Cabe ressaltar que a utilização deste documento para finalidades diferentes daquela descrita em sua identificação é de inteira responsabilidade de quem o detém.
Nesta seção não use marcadores de tópico. Itens ficam em linhas próprias dentro do bloco.
""",
    regras_verificacao=(
        "Recomendações, focos de intervenção e textos padrão são sugestões clínicas e não precisam de apoio no material. "
        "Marque como sem apoio só afirmações sobre o paciente que não aparecem no material, como uma dificuldade, um "
        "diagnóstico ou um tratamento atual que ninguém mencionou."
    ),
)

SECOES = [DEMANDA, ANAMNESE, RELACAO, HIPOTESES, RECOMENDACOES]
POR_CHAVE = {s.chave: s for s in SECOES}
ORDEM = {s.chave: i for i, s in enumerate(SECOES)}
CHAVES = [s.chave for s in SECOES]

# Todos os tipos de bloco de todas as seções, para as escolhas do banco.
TODOS_OS_TIPOS = sorted({chave: rotulo for s in SECOES for chave, rotulo in s.tipos}.items())


def secao(chave):
    return POR_CHAVE[chave]
