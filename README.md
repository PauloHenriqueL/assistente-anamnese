# Anamnese 4.2

Assistente de escrita clínica que gera a seção de anamnese de laudos neuropsicológicos com IA, confere o texto contra as anotações da psicóloga e aprende com as avaliações dela.

> **In English:** a Django app that drafts the anamnesis section of neuropsychological reports with an LLM. Every draft is checked by a second model call for missing facts and unsupported claims, rewritten once if needed, and versioned. The psychologist rates each paragraph; approved paragraphs are stored with their source notes and fed back as few-shot examples, while the reasons behind rejections become prompt reinforcements.

## O problema

Uma neuropsicóloga usava um chat de IA para transformar anotações de entrevista em texto de laudo. O resultado variava de uma conversa para outra. Ela reclamava de três coisas: parágrafos curtos que perdiam detalhes, informações inventadas e texto sem ordem cronológica. Revendo conversas reais, apareceram mais dois padrões: a IA enfeitava o texto quando só devia revisá-lo, e trocava o nome da paciente por apelidos para não repetir palavras.

O critério de um bom parágrafo é dela. Por isso o sistema não tenta adivinhar a qualidade: ele confere o que dá para conferir e aprende o resto com as avaliações.

## Como funciona

1. A psicóloga cria o laudo e envia a anamnese anotada em PDF, Word ou texto.
2. A IA gera a seção inteira, com um parágrafo por tema e numa ordem fixa. A resposta vem num formato estruturado, em que cada parágrafo traz o tema e os trechos das anotações que o sustentam.
3. Uma segunda chamada confere cada parágrafo contra as anotações. Ela lista o que ficou de fora e as frases sem apoio.
4. Se houver problema, só os parágrafos afetados são reescritos, uma única vez. O que ainda sobrar aparece como aviso na tela.
5. Ela pede ajustes em conversa livre. Cada ajuste vira uma nova versão do parágrafo, sem mexer nos outros.
6. Quando ela cola um texto próprio para revisar, o sistema mede quanto a IA mudou. Se a revisão alterar demais as palavras dela sem pedido de acréscimo, o texto é refeito.
7. Cada parágrafo pode ser marcado como bom ou ruim. Um parágrafo aprovado vira par de exemplo, junto com as anotações de origem. Um reprovado pede o motivo, e os motivos frequentes viram regras extras no prompt.

## Decisões técnicas

- **Resposta estruturada em vez de texto solto.** Os parágrafos são identificados de forma confiável, podem ser versionados e ligados à anotação de origem.
- **Verificação por uma segunda chamada.** A completude e a falta de invenção são conferidas pelo sistema, e não pela usuária.
- **Exemplos escolhidos por tema, sem banco vetorial.** Com poucas dezenas de pares aprovados, uma consulta comum resolve. A busca vetorial com pgvector fica para quando houver centenas.
- **Contexto curto e fixo.** Cada chamada leva a anamnese, a versão atual da seção e as últimas mensagens. Isso evita que a IA se afaste das regras em conversas longas.
- **Provedor intercambiável.** OpenAI ou Gemini, escolhidos por uma variável de ambiente, com novas tentativas automáticas quando o serviço está sobrecarregado.
- **Sigilo.** Nenhum dado de paciente real está no repositório. Os laudos de referência ficam só na máquina local, e o repositório traz exemplos fictícios.

A entrevista de requisitos e todas as decisões estão em [demandas.md](demandas.md).

## Tecnologias

Python 3.12, Django 5, SDKs da OpenAI e do Google Gen AI, Pydantic para os formatos de resposta, pypdf e python-docx para ler as anotações. O front-end é HTML e CSS puros com um pouco de JavaScript, sem etapa de build.

## Estrutura

| Arquivo | Papel |
|---|---|
| `laudos/servico.py` | fluxo de geração, verificação, reescrita e versões |
| `laudos/prompt.py` | prompt fixo da seção e da verificação |
| `laudos/gemini.py` | chamadas à IA, formatos de resposta e novas tentativas |
| `laudos/exemplos.py` | escolha de exemplos e reforços vindos das avaliações |
| `laudos/temas.py` | temas, ordem e tamanho mínimo dos parágrafos |
| `laudos/tests.py` | testes com a IA simulada, que nunca chamam a rede |

## Rodar localmente

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # coloque a chave da OpenAI em OPENAI_API_KEY
.venv/bin/python manage.py migrate
.venv/bin/python manage.py carregar_exemplos
.venv/bin/python manage.py criar_demo       # laudo fictício para ver as telas sem gastar a chave
.venv/bin/python manage.py runserver
```

Abra http://127.0.0.1:8000. Para ver os modelos que a chave libera, rode `.venv/bin/python manage.py listar_modelos`.

## Testes

```bash
.venv/bin/python manage.py test laudos
```

Os testes simulam a IA. Uma trava faz qualquer teste falhar se tentar chamar a API de verdade.
