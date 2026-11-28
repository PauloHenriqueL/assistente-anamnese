# Demandas — sistema_anamnese

## Objetivo atual
—

## Em andamento
—

## Fila (em ordem)
- D-001 LGPD: formalizar retenção, backup e registro de quem acessa o quê (dados de saúde) (antigo: Próximas etapas)
- D-002 Contratos de módulos e checagem de ciclos (import-linter) quando os módulos forem definidos
- D-003 Busca por semelhança com pgvector — só quando houver centenas de pares aprovados (antigo: Próximas etapas)
- D-005 E2E Playwright no projeto: escolher o framework (o kit prevê Playwright Test em TS) e criar uma IA simulada para rodar sem rede; depois, um E2E por critério de aceite da D-004

## Bloqueado (precisa do Paulo)
—

## Bugs
- B-002 Rolagem horizontal no celular nas telas de seção que já têm conversa ou blocos — /laudos/<id>/secao/<chave>/ em 390px — entrar no celular, abrir uma seção com blocos e rolar até o campo de mensagem: o botão Enviar e o painel de blocos ficam cortados (já acontecia na 4.2)
- B-003 /favicon.ico responde 404 — qualquer tela — abrir o console do navegador

## Feito
- D-004 Seções 4.3 e 4.4 do laudo — PR #4 — 2026-11-27 (sem deploy: falta o Manual Deploy no Render; IA de verdade não testada, chave local recusada)
- B-001 Teste usa httpx2, CI com tblib e lint "não piorar" — PR #3 — 2026-11-27
- D-000 Adoção do kit — PR #2 — 2026-11-27 (mergeado com CI vermelho por falta de proteção de branch; corrigido em B-001)

## Decisões
- 2026-11-27 Seções 4.3 e 4.4 são opcionais como base (sem texto, não avisam nem entram no material); o padrão da 4.4 é o texto que o Paulo passou, e a observação dos laudos antigos não vira exemplo (redação antiga do padrão).
- 2026-11-27 Decisões da entrevista original (escopo, like/deslike, verificação, modo revisão, banco, acesso, segurança, provedores) seguem valendo: ver `historico.md` → "Decisões da entrevista" e "Decisões tomadas por mim".
- 2026-11-27 Testes nunca usam o Neon: `DATABASE_URL=` vazio no checar-rapido e no CI.
