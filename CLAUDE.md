# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é

Assistente de escrita clínica (Django 5, Python 3.12) que ajuda uma neuropsicóloga a redigir laudos **seção por seção** com IA. Cada seção gerada passa por uma segunda chamada que confere o texto contra as anotações, é reescrita uma vez quando há problema, e versionada. As avaliações da psicóloga realimentam o prompt: likes viram exemplos few-shot; deslikes viram reforços de regra. O código, os comentários e o domínio estão em português do Brasil — mantenha isso ao escrever código novo.

## Comandos

```bash
# Setup
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env            # defina IA_PROVEDOR e a chave (OPENAI_API_KEY ou GEMINI_API_KEY)
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createcachetable   # tabela de cache que sustenta o bloqueio de login
.venv/bin/python manage.py garantir_admin     # cria superusuário de ADMIN_USUARIO/ADMIN_SENHA
.venv/bin/python manage.py runserver          # http://127.0.0.1:8000

# Testes (todos)
.venv/bin/python manage.py test laudos
# Um teste específico
.venv/bin/python manage.py test laudos.tests.FluxoTestes.test_primeira_geracao_cria_paragrafos_ordenados

# Comandos úteis
.venv/bin/python manage.py criar_demo         # laudo fictício para ver as telas sem gastar a chave da IA
.venv/bin/python manage.py extrair_laudos     # PDFs de laudos_exemplos/ → laudos_base.json anonimizado + revisao_laudos_base.md
.venv/bin/python manage.py carregar_exemplos  # carrega as seções dos laudos base como exemplos de estilo (idempotente)
.venv/bin/python manage.py importar_gemini ARQ.jsonl --usuario X  # textos aprovados nas conversas com o Gemini → pares
.venv/bin/python manage.py avaliar_geracao --laudo 2 --saida rel.md  # gera de novo sem gravar e compara com o texto dela
.venv/bin/python manage.py listar_modelos     # modelos que a chave do provedor configurado libera
```

Não há etapa de build de front-end nem linter configurado: o front é HTML/CSS/JS puros em `laudos/static/` e `laudos/templates/`.

## Arquitetura

Projeto Django `config/`, app único `laudos/`. O fluxo de IA está isolado em alguns módulos; views e models são finos em torno deles.

### O pipeline de uma mensagem — `laudos/servico.py`
`processar_mensagem(laudo, texto, chave_secao)` é o coração do sistema. Para cada mensagem da psicóloga:
1. **Gera** (`gemini.gerar`): a IA devolve só os blocos criados/alterados, em formato estruturado.
2. **Verifica** (`_verificar` → `gemini.verificar`): uma segunda chamada confere cada bloco contra o material do caso e lista o que **faltou** e o que está **sem apoio**. Para blocos em modo `revisao`, mede com `difflib` se a IA mudou demais o texto da psicóloga (`LIMITE_MUDANCA_REVISAO`).
3. **Reescreve uma vez** só os blocos com problema; a reescrita é verificada de novo e o que ainda sobrar vira **aviso** no bloco (campos `faltou`/`sem_apoio` da `Versao`).
4. **Aplica** (`_aplicar`) em transação: cria uma nova `Versao` por bloco afetado, sem tocar nos demais.

A tela não espera esse fluxo: `iniciar_mensagem` grava a mensagem com `pendente=True` e roda `responder` numa thread (`IA_EM_SEGUNDO_PLANO`); a tela consulta `andamento/` até a resposta ou o erro serem gravados. Pendência mais velha que `PRAZO_DA_GERACAO` vira erro. `preparar`/`executar` só leem o banco e são reaproveitados por `avaliar_geracao`.

O "material do caso" montado para a IA = anamnese + texto atual das seções de base (`secao.contexto`) + conversa recente daquela seção. Contexto curto e fixo por design.

### Chamadas à IA — `laudos/gemini.py`
Na OpenAI há dois modelos: `OPENAI_MODEL` gera e reescreve, `OPENAI_MODEL_VERIFICACAO` confere; cada etapa tem seu "modo de pensar" (`OPENAI_RACIOCINIO`, `OPENAI_RACIOCINIO_VERIFICACAO` → `reasoning_effort`; vazio = modelo sem raciocínio, que recebe temperatura). Na conversa, ela escolhe o modelo (lista `IA_MODELOS`) e liga ou desliga o pensamento; a escolha vai na `Mensagem` (`modelo`, `raciocinio`) e vale para gerar e reescrever. Toda chamada passa por `chamar(...)`, que: escolhe o provedor por `IA_PROVEDOR` (`openai` ou `gemini`), faz retries com espera (`ESPERAS`) em erros passageiros (429/5xx/overloaded), traduz erros para mensagens amigáveis (`ErroGemini`), e valida a resposta contra um schema Pydantic. **O nome do módulo é histórico** (Gemini foi o provedor original); hoje atende os dois. `esquema_resposta(chave_secao)` monta dinamicamente, com `create_model`, um schema cujo campo `tema` só aceita os tipos de bloco daquela seção.

### Seções e temas — `laudos/secoes.py` e `laudos/temas.py`
`SECOES` define as 5 seções do laudo (`2`, `4.2`, `5.1`, `5.2`, `6`). Nos laudos finais dela a numeração é outra (a anamnese é "4.1 HISTÓRIA CLÍNICA"): tudo que lê laudo localiza seção **pelo título**, nunca pelo número. Cada `Secao` (dataclass congelada) carrega suas próprias **regras de prompt** (`regras`, `regras_verificacao`), seus tipos de bloco e ordem, mínimo de palavras, de quais seções anteriores depende (`contexto`) e se confere o que faltou (`conferir_faltou`, só a 4.2). A 4.2 tem `ordem_livre`: blocos de abertura (gestação, marcos, percurso escolar) primeiro, linhas de dados no fim e, no meio, os parágrafos na ordem em que a IA os escreveu — que segue os títulos das anotações dela. `Paragrafo.posicao` guarda essa ordem; o tema é só rótulo. Os temas estão em `temas.py`. **Adicionar/alterar uma seção é editar `secoes.py`** — o resto se adapta.

### Prompt — `laudos/prompt.py`
`BASE` é o prompt fixo do sistema (fidelidade ao material, estilo da psicóloga, formato da resposta). `instrucao_sistema(...)` concatena BASE + regras da seção + reforços dos deslikes + blocos de exemplo. `instrucao_verificacao(...)` monta o prompt do revisor.

### Aprendizado com as avaliações — `laudos/exemplos.py`
**Sem banco vetorial** (por enquanto): `estilo()` põe no prompt seções **inteiras** de até 4 laudos base, escolhidos pelo perfil do caso (`perfil.py`: faixa etária e queixas). `pares()` escolhe exemplos few-shot por **tema**, só os aprovados **da própria dona** (likes e textos aprovados nas conversas com o Gemini), preferindo a mesma faixa etária. `reforcos()` olha os deslikes recentes da dona e, quando um motivo aparece com frequência, injeta uma regra extra no prompt (dicionário `REFORCOS`). pgvector fica para quando houver centenas de pares.

### Modelo de dados — `laudos/models.py`
`Laudo` → `Paragrafo` (um por tema/bloco, com `ativo` e `posicao`) → `Versao` (histórico; `versao_atual()` é a de maior `numero`). `Mensagem` guarda a conversa por seção. `Avaliacao` (like/deslike com motivos) pendura numa `Versao`; um like cria/atualiza um `Exemplo` few-shot, um deslike desativa o exemplo correspondente. `Exemplo` tem três fontes: `laudo_base` (estilo, de todos), `like` e `gemini` (pares da dona).

### Acesso e isolamento — `laudos/acesso.py`, `config/settings.py`
`LoginRequiredMiddleware` exige login em tudo. Todo laudo/exemplo tem `dono`; as views usam `_laudo_da_usuaria`/`_versao_da_usuaria`, que respondem **404 para recurso de outra pessoa** (não revelam que existe). Login bloqueia por 15 min após 5 senhas erradas, usando o cache no banco (daí `createcachetable`). Em produção (`DEBUG=0`) ligam-se HTTPS obrigatório, cookies seguros e HSTS.

## Testes

`laudos/tests.py` **nunca chama a rede**: `setUpModule` instala uma trava (`_SemRede`) que faz qualquer teste falhar se tentar instanciar `openai.OpenAI` ou `google.genai.Client`. Os testes simulam a IA com `mock.patch.object(gemini, "gerar"/"verificar", ...)`. Ao escrever testes novos, siga esse padrão — use os helpers `resposta()`, `par()`, `verificacao()` em vez de chamar a IA de verdade.

## Produção

Deploy no Render (`render.yaml` + `build.sh`) com Postgres do Neon via `DATABASE_URL` (sem ela, cai no SQLite local). WhiteNoise serve os estáticos (`collectstatic`). `garantir_admin` só roda no deploy quando `ADMIN_USUARIO`/`ADMIN_SENHA` estão no ambiente.

## Sigilo

Nenhum dado de paciente real entra no repositório. `laudos/seeds/laudos_base.json` (laudos reais que viram exemplos de estilo) e `db.sqlite3` estão no `.gitignore`; o versionado é `laudos_base.exemplo.json`, fictício. `laudos_exemplos/` (PDFs, `substituicoes.txt` da anonimização) e `gemini/` (export do Takeout) ficam só na máquina local. Testes: rode com `DATABASE_URL=` para não usar o Neon do `.env`.
