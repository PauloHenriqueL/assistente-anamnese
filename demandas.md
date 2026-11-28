# Demandas — sistema_anamnese

## Objetivo atual
—

## Em andamento

### D-004 Seções 4.3 e 4.4 do laudo
- Branch: d004-secoes-4-3-e-4-4 · PR: —
- Pedido: criar a 4.3 "Dados complementares e entrevistas clínicas" (resumo do que informou um familiar ou profissional que acompanha o paciente) e a 4.4 "Dados da observação clínica" (como o paciente se apresentou nas sessões, com o texto padrão dela).
- Critérios de aceite:
  - CA1: dado um laudo, quando ela abre a 4.3 e envia as anotações de uma entrevista ou de um relatório, então a seção ganha um bloco por fonte e aparece entre a 4.2 e a 4.4 na visão geral, no menu e no texto do laudo.
  - CA2: dado um laudo, quando ela gera a 4.4 sem escrever nada, então o pedido registrado manda usar o texto padrão e a IA recebe esse texto como modelo; quando ela conta o que observou, o pedido leva o que ela contou.
  - CA3: dado um laudo com a 4.3 ou a 4.4 escrita, quando ela gera a 5.1, a 5.2 ou a 6, então o texto delas vai como base; sem elas, as seções seguintes não avisam que falta base.
- Feito: levantamento nos nove laudos base (a observação existe neles como "4.2 Observações do comportamento", um parágrafo de 37 a 72 palavras; dados complementares só aparecem num laudo, como blocos "- Relatório ... de [data]:").
- **Próximo passo:** escrever as duas seções em `laudos/secoes.py`, o contexto opcional e os testes.
- Bloqueio: —

## Fila (em ordem)
- D-001 LGPD: formalizar retenção, backup e registro de quem acessa o quê (dados de saúde) (antigo: Próximas etapas)
- D-002 Contratos de módulos e checagem de ciclos (import-linter) quando os módulos forem definidos
- D-003 Busca por semelhança com pgvector — só quando houver centenas de pares aprovados (antigo: Próximas etapas)

## Bloqueado (precisa do Paulo)
—

## Bugs
—

## Feito
- B-001 Teste usa httpx2, CI com tblib e lint "não piorar" — PR #3 — 2026-11-27
- D-000 Adoção do kit — PR #2 — 2026-11-27 (mergeado com CI vermelho por falta de proteção de branch; corrigido em B-001)

## Decisões
- 2026-11-27 Decisões da entrevista original (escopo, like/deslike, verificação, modo revisão, banco, acesso, segurança, provedores) seguem valendo: ver `historico.md` → "Decisões da entrevista" e "Decisões tomadas por mim".
- 2026-11-27 Testes nunca usam o Neon: `DATABASE_URL=` vazio no checar-rapido e no CI.
