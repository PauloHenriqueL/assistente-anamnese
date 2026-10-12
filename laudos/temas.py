"""Rótulos dos blocos da seção de anamnese (a História Clínica dos laudos dela).

A seção tem três partes, como nos laudos aprovados:
1. Abertura: gestação, marcos do desenvolvimento e percurso escolar, quando o
   material traz essas informações.
2. Queixas principais: os parágrafos de tema. A ordem deles não é fixa: segue os
   títulos das anotações da psicóloga, e o tema é só um rótulo do bloco.
3. Linhas de dados, sempre no fim e sempre na mesma ordem.
"""

ABERTURA = [
    ("gestacao", "- Gestação/Parto"),
    ("marcos", "- Marcos do Desenvolvimento"),
    ("percurso_escolar", "- Percurso Escolar"),
]

TEMAS_DE_QUEIXA = [
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
    ("substancias", "Uso de substâncias"),
    ("trabalho", "Vida laboral"),
    ("alimentacao", "Alimentação e imagem corporal"),
    ("sono", "Sono"),
    ("outro", "Outro tema"),
]

LINHAS = [
    ("saude", "- Saúde"),
    ("medicacao", "- Uso de Medicação"),
    ("historico_familiar", "- Histórico Familiar"),
    ("profissionais", "- Profissional que acompanha"),
]

TEMAS = ABERTURA + TEMAS_DE_QUEIXA + LINHAS

CHAVES = [chave for chave, _ in TEMAS]
ORDEM = {chave: i for i, chave in enumerate(CHAVES)}
ROTULOS = dict(TEMAS)

CHAVES_ABERTURA = frozenset(chave for chave, _ in ABERTURA)
# Temas que são linhas curtas de dados e não têm tamanho mínimo.
LINHAS_DE_DADOS = frozenset(chave for chave, _ in LINHAS)

# Abaixo disso, o parágrafo recebe um alerta de possível resumo excessivo.
MINIMO_PALAVRAS = 80
