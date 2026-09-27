"""Temas da seção 4.2, na ordem em que aparecem no laudo.

A ordem segue os dois laudos aprovados: primeiro a trajetória e a cognição,
depois rotina e comportamento, vida social e afetiva, e por fim humor,
ansiedade, alimentação e sono. As quatro linhas de dados fecham a seção.
"""

TEMAS = [
    ("trajetoria_escolar", "Trajetória escolar e acadêmica"),
    ("cognicao", "Memória, atenção e aprendizagem"),
    ("rotina", "Rotina, organização, rigidez e perfeccionismo"),
    ("comportamento", "Hiperatividade, impulsividade e comportamento"),
    ("interesses", "Interesses e lazer"),
    ("sensorial", "Sensibilidade sensorial"),
    ("social", "Vida social"),
    ("relacionamentos", "Relacionamentos afetivos e familiares"),
    ("humor", "Humor e regulação emocional"),
    ("ansiedade", "Ansiedade"),
    ("alimentacao", "Alimentação e imagem corporal"),
    ("sono", "Sono"),
    ("outro", "Outro tema"),
    # Linhas de dados, sempre no fim e sempre nesta ordem.
    ("saude", "- Saúde"),
    ("medicacao", "- Uso de Medicação"),
    ("historico_familiar", "- Histórico Familiar"),
    ("profissionais", "- Profissional que acompanha"),
]

CHAVES = [chave for chave, _ in TEMAS]
ORDEM = {chave: i for i, chave in enumerate(CHAVES)}
ROTULOS = dict(TEMAS)

# Temas que são linhas curtas de dados e não têm tamanho mínimo.
LINHAS_DE_DADOS = {"saude", "medicacao", "historico_familiar", "profissionais"}

# Abaixo disso, o parágrafo recebe um alerta de possível resumo excessivo.
MINIMO_PALAVRAS = 80
