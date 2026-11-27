# Demandas — sistema_anamnese

## Objetivo atual
—

## Em andamento
### D-000 Adoção do kit
- Branch: d000-adocao-kit · PR: —
- Feito: historico.md, demandas.md, REVIEW.md, scripts/checar-rapido, CI, .gitignore
- **Próximo passo:** abrir o PR e fazer merge com o CI verde
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
—

## Decisões
- 2026-11-27 Decisões da entrevista original (escopo, like/deslike, verificação, modo revisão, banco, acesso, segurança, provedores) seguem valendo: ver `historico.md` → "Decisões da entrevista" e "Decisões tomadas por mim".
- 2026-11-27 Testes nunca usam o Neon: `DATABASE_URL=` vazio no checar-rapido e no CI.
