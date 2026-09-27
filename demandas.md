# Demandas do sistema Anamnese 4.2

## Problema

A neuropsicóloga usa o Gemini para escrever a seção 4.2 DADOS DA ENTREVISTA DE ANAMNESE dos laudos. A qualidade varia de uma conversa para outra. As queixas dela são três: parágrafos curtos que perdem elementos, informação inventada e texto sem ordem cronológica. Um bom parágrafo é critério dela, e os dois laudos que ela aprovou, um de adulto e um de criança, são a referência.

Uma conversa real com o Gemini mostrou quatro falhas:

- **Cortar conteúdo.** Ela reclamou cinco vezes que faltou material que estava na anamnese: texto curto, perfeccionismo, vida social, ansiedade e sono.
- **Enfeitar ao revisar.** Ao arrumar um texto dela, ele trocou palavras por genitora, descendente e crise sanitária mundial.
- **Rodízio de apelidos.** Para não repetir palavras, alternou a avaliada, a entrevistada, a moça, a jovem e a estudante.
- **Intensidade sem apoio.** Usou significativa, expressiva e severa sem base nas anotações.

## Escopo

- O sistema faz só a 4.2. Nenhuma outra seção do laudo.
- O fluxo dela não muda. Ela envia a anamnese anotada, o Gemini gera a 4.2 completa e ela pede ajustes na conversa.
- As três mensagens de comando que ela mandava no início de toda conversa viram o prompt fixo do sistema.
- O Gemini continua sendo o modelo, porque é o que ela conhece e aprova.

## Decisões da entrevista

1. **Sem novos testes com ela.** O sistema é montado a partir das conversas e dos laudos que já existem.
2. **Conversa livre.** Ela conversa como no Gemini. A primeira mensagem gera a 4.2 inteira.
3. **Like guarda um par.** O parágrafo aprovado é salvo junto com o trecho das anotações de onde saiu.
4. **Deslike pede o motivo.** Opções de um clique: ficou curto, faltou informação, inventou coisa, sem ligação, rebuscado, fora de ordem e mudou o meu texto. Há um comentário opcional. Parágrafos reprovados nunca entram no prompt; os motivos frequentes viram reforços de regra.
5. **Resposta estruturada.** O Gemini responde em formato fixo, invisível para ela, com cada parágrafo separado, o tema, o texto e os trechos de origem.
6. **Versões.** Cada ajuste cria uma nova versão do parágrafo. A 4.2 mostra sempre a versão atual de cada tema.
7. **Exemplos por tema, sem banco vetorial.** Os pares aprovados são escolhidos pelo tema, até dois por tema. Os dois laudos base entram sempre como exemplo de estilo e tamanho.
8. **Ordem fixa de temas.** Dentro de cada parágrafo, o texto vai do passado para o presente.
9. **Completude conferida.** Uma segunda chamada lista o que faltou das anotações. Se faltar algo, o parágrafo é reescrito uma única vez. Menos de 80 palavras gera um alerta.
10. **Invenção conferida.** A mesma chamada aponta frases sem apoio nas anotações, que entram na reescrita. O que sobrar aparece como aviso no parágrafo.
11. **Modo revisão.** Quando ela cola um texto próprio, o Gemini preserva as palavras dela. Se a revisão mudar mais de 25% das palavras sem ela pedir acréscimo, o texto é refeito. A regra de não repetir palavras não vale para o nome da paciente.

## Decisões tomadas por mim

- **Banco.** SQLite no protótipo. Postgres quando for para um servidor.
- **Usuária.** Uma só, sem login no protótipo.
- **Leitura da anamnese.** PDF, Word e texto colado, lidos pelo próprio sistema. O texto lido fica visível na tela do laudo para ela conferir.
- **Contexto de cada chamada.** A anamnese inteira, a 4.2 atual e as últimas 12 mensagens. Respostas antigas completas não são reenviadas, para o Gemini não se afastar das regras em conversas longas.
- **Modelo.** Definido por `OPENAI_MODEL` ou `GEMINI_MODEL` no `.env`. Temperatura 0,4 na escrita e 0 na verificação; modelos de raciocínio da OpenAI rodam sem temperatura.
- **Edição na tela.** Ela pode editar um parágrafo direto, sem passar pelo Gemini. A edição vira uma versão de origem editado pela usuária.
- **Reforços automáticos.** Um motivo de deslike vira regra extra no prompt quando aparece em pelo menos 3 e em 30% dos últimos 30 deslikes.
- **Sigilo nos exemplos.** Os nomes de pacientes, familiares e profissionais dos laudos base foram trocados. O arquivo com esses laudos fica só na máquina local e não entra no repositório; no lugar dele, o repositório traz um exemplo fictício.
- **Provedor da IA.** O sistema aceita OpenAI e Gemini, escolhidos por IA_PROVEDOR no .env. A OpenAI é o padrão. A usuária não vê qual IA está em uso.

## Ordem dos temas

1. Trajetória escolar e acadêmica
2. Memória, atenção e aprendizagem
3. Rotina, organização, rigidez e perfeccionismo
4. Hiperatividade, impulsividade e comportamento
5. Interesses e lazer
6. Sensibilidade sensorial
7. Vida social
8. Relacionamentos afetivos e familiares
9. Humor e regulação emocional
10. Ansiedade
11. Alimentação e imagem corporal
12. Sono
13. Outro tema
14. Linhas de dados: Saúde, Uso de Medicação, Histórico Familiar e Profissional que acompanha

## Fluxo de cada mensagem

1. O sistema monta o prompt fixo com os exemplos de estilo, os pares aprovados dos temas do laudo e os reforços ativos.
2. O Gemini responde com os parágrafos criados ou alterados.
3. A verificação confere o que faltou, o que não tem apoio e, no modo revisão, quanto o texto dela mudou.
4. Havendo problema, os parágrafos afetados são reescritos uma vez e conferidos de novo.
5. Cada parágrafo ganha uma nova versão. O que ainda tiver problema aparece com aviso.

## Modelo de dados

| Tabela | Guarda |
|---|---|
| Laudo | paciente, texto da anamnese e nome do arquivo |
| Mensagem | cada fala da conversa, com o erro quando a chamada falha |
| Paragrafo | tema, posição e se continua ativo |
| Versao | texto, trechos de origem, origem da versão, o que faltou e o que ficou sem apoio |
| Avaliacao | like ou deslike, motivos e comentário |
| Exemplo | pares aprovados e parágrafos dos laudos base usados no prompt |

## Onde está cada parte

| Arquivo | Papel |
|---|---|
| `laudos/prompt.py` | prompt fixo da 4.2 e da verificação |
| `laudos/servico.py` | fluxo de geração, verificação, reescrita e versões |
| `laudos/gemini.py` | chamadas à API e formatos de resposta |
| `laudos/exemplos.py` | escolha de exemplos e reforços |
| `laudos/temas.py` | temas, ordem e tamanho mínimo |
| `laudos/seeds/laudos_base.json` | 4.2 dos dois laudos aprovados, com nomes trocados |

## Próximas etapas

- **Conversas antigas.** Importar o histórico do Gemini pelo Google Takeout, na atividade dos apps do Gemini. A exportação precisa ser feita na conta dela. O PDF de conversa compartilhada corta as mensagens dela, então não serve como fonte completa.
- **Busca por semelhança.** Quando houver centenas de pares aprovados, trocar a escolha por tema por busca vetorial com pgvector no Postgres.
- **Aprender com as edições.** Comparar o rascunho do Gemini com a versão final dela para descobrir padrões de correção e ajustar o prompt fixo.
- **Servidor.** Postgres, login e HTTPS antes de sair do localhost. Os dados são de saúde e exigem cuidado com a LGPD.
