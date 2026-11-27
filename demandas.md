# Demandas — sistema_anamnese

## Objetivo atual
—

## Em andamento
### B-001 CI vermelho: teste importa httpx, que o openai 3.x trocou por httpx2
- Branch: b001-teste-httpx2 · PR: —
- Feito: teste usa httpx2; CI instala tblib (o runner paralelo não mostrava o erro); 129 OK num venv limpo
- **Próximo passo:** CI verde → merge
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
- D-000 Adoção do kit — PR #2 — 2026-11-27 (mergeado com CI vermelho por falta de proteção de branch; corrigido em B-001)

## Decisões
- 2026-11-27 Decisões da entrevista original (escopo, like/deslike, verificação, modo revisão, banco, acesso, segurança, provedores) seguem valendo: ver `historico.md` → "Decisões da entrevista" e "Decisões tomadas por mim".
- 2026-11-27 Testes nunca usam o Neon: `DATABASE_URL=` vazio no checar-rapido e no CI.
