# REVIEW — sistema_anamnese

Checklist do revisor. Cada item nasce de um bug que chegou à produção ou quase.
O revisor confere **só os itens cujo gatilho o diff aciona** e ignora estilo.

Formato: `- [gatilho] → conferir: ... (origem: B-xxx / PR #nn)`

## Itens

- [mexeu em migrations/] → conferir: migração reversível e sem perda de dado; backup antes se destrutiva (origem: kit)
- [mexeu em laudos/acesso.py, views ou papeis.py] → conferir: analista não vê laudo de outro; fora do alcance responde 404; só gestor avalia (origem: kit)
- [mexeu em laudos/saude.py ou /saude/] → conferir: a rota não toca no banco (o Neon precisa dormir) (origem: CLAUDE.md)
- [teste novo que chama a IA] → conferir: usa mock de gemini.gerar/verificar; nunca rede (origem: CLAUDE.md)
- [dado de paciente em seed, teste, log, screenshot ou PR] → conferir: só dados fictícios (origem: LGPD)
