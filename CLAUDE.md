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

# Checagem rápida (lint dos .py alterados + testes em paralelo, ~2 min; roda no Stop do Claude)
scripts/checar-rapido

# Testes (todos) — sempre com DATABASE_URL= para não usar o Neon do .env
.venv/bin/python manage.py test laudos
# Um teste específico
.venv/bin/python manage.py test laudos.tests.FluxoTestes.test_primeira_geracao_cria_paragrafos_ordenados

# Comandos úteis
.venv/bin/python manage.py criar_demo         # laudo fictício para ver as telas sem gastar a chave da IA
.venv/bin/python manage.py extrair_laudos     # PDFs de laudos_exemplos/ → laudos_base.json anonimizado + revisao_laudos_base.md
.venv/bin/python manage.py carregar_exemplos  # carrega as seções dos laudos base como exemplos de estilo (idempotente)
.venv/bin/python manage.py importar_gemini ARQ.jsonl --usuario X  # textos aprovados nas conversas com o Gemini → pares
.venv/bin/python manage.py avaliar_geracao --laudo 2 --saida rel.md  # gera de novo sem gravar e compara com o texto dela
.venv/bin/python manage.py avaliar_geracao --laudo 2 --laudo 3 --config A --config C --rodadas 2 --saida rel.md  # compara configurações de exemplos
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

**Inserir tema pela tela** (`Mensagem.insercao` = {tema, titulo, depois_de}) usa o mesmo fluxo, mas o código garante um bloco só: `_so_o_bloco_inserido` descarta o resto da resposta e pula a junção de temas, e `_criar_inserido` cria o parágrafo logo depois de `depois_de` (renumerando os temas seguintes), com o nome próprio em `Paragrafo.titulo`. Excluir um bloco só o desativa (`ativo=False`), para o Desfazer da tela.

A tela não espera esse fluxo: `iniciar_mensagem` grava a mensagem com `pendente=True` e roda `responder` numa thread (`IA_EM_SEGUNDO_PLANO`); a tela consulta `andamento/` até a resposta ou o erro serem gravados. A mensagem pendente é a fila: a thread grava um sinal de vida (`Mensagem.vivo_em`, a cada `BATIMENTO`); se o servidor reiniciar no meio, o sinal para e a próxima consulta do `andamento/` retoma a geração do zero (`_retomar`, até `TENTATIVAS_MAXIMAS`). Nada vai para o laudo antes do fim, então recomeçar não duplica texto. Pendência mais velha que `PRAZO_DA_GERACAO` vira erro. `preparar`/`executar` só leem o banco e são reaproveitados por `avaliar_geracao`.

O "material do caso" montado para a IA = anamnese + texto atual das seções de base (`secao.contexto`) + conversa recente daquela seção. Contexto curto e fixo por design.

### Chamadas à IA — `laudos/gemini.py`
Na OpenAI há dois modelos: `OPENAI_MODEL` gera e reescreve, `OPENAI_MODEL_VERIFICACAO` confere; cada etapa tem seu "modo de pensar" (`OPENAI_RACIOCINIO`, `OPENAI_RACIOCINIO_VERIFICACAO` → `reasoning_effort`; vazio = modelo sem raciocínio, que recebe temperatura). Na conversa, ela escolhe o modelo (lista `IA_MODELOS`) e liga ou desliga o pensamento; a escolha vai na `Mensagem` (`modelo`, `raciocinio`) e vale para gerar e reescrever. Toda chamada passa por `chamar(...)`, que: escolhe o provedor por `IA_PROVEDOR` (`openai` ou `gemini`), faz retries com espera (`ESPERAS`) em erros passageiros (429/5xx/overloaded), traduz erros para mensagens amigáveis (`ErroGemini`), e valida a resposta contra um schema Pydantic. **O nome do módulo é histórico** (Gemini foi o provedor original); hoje atende os dois. `esquema_resposta(chave_secao)` monta dinamicamente, com `create_model`, um schema cujo campo `tema` só aceita os tipos de bloco daquela seção.

### Seções e temas — `laudos/secoes.py` e `laudos/temas.py`
`SECOES` define as 5 seções do laudo (`2`, `4.2`, `5.1`, `5.2`, `6`). Nos laudos finais dela a numeração é outra (a anamnese é "4.1 HISTÓRIA CLÍNICA"): tudo que lê laudo localiza seção **pelo título**, nunca pelo número. Cada `Secao` (dataclass congelada) carrega suas próprias **regras de prompt** (`regras`, `regras_verificacao`), seus tipos de bloco e ordem, mínimo de palavras, de quais seções anteriores depende (`contexto`) e se confere o que faltou (`conferir_faltou`, só a 4.2). A 4.2 tem `ordem_livre`: blocos de abertura (gestação, marcos, percurso escolar) primeiro, linhas de dados no fim e, no meio, os parágrafos na ordem em que a IA os escreveu — que segue os títulos das anotações dela. `Paragrafo.posicao` guarda essa ordem; o tema é só rótulo. Os temas estão em `temas.py`. **Adicionar/alterar uma seção é editar `secoes.py`** — o resto se adapta.

### Prompt — `laudos/prompt.py`
`BASE` é o prompt fixo do sistema (fidelidade ao material, estilo da psicóloga, formato da resposta). `instrucao_sistema(...)` concatena BASE + regras da seção + reforços dos deslikes + blocos de exemplo. `instrucao_verificacao(...)` monta o prompt do revisor.

### Aprendizado com as avaliações — `laudos/exemplos.py`
**Sem banco vetorial** (por enquanto): `estilo()` põe no prompt seções **inteiras** de até 4 laudos base, escolhidos pelo perfil do caso (`perfil.py`: faixa etária e queixas). `pares()`, `correcoes()` e `reforcos()` recebem `autores`, as pessoas cujas avaliações contam: no prompt são **os gestores** (`papeis.gestores()`), seja de quem for o laudo que está sendo escrito. `pares()` escolhe exemplos few-shot por **tema**, só os aprovados pelos autores (likes e textos aprovados nas conversas com o Gemini), preferindo a mesma faixa etária. `correcoes()` mostra textos da IA que eles reescreveram, como antes → depois com os motivos (ignora edições abaixo de 5%). Quantos de cada entram, e se há rodízio entre os temas, é uma `Configuracao` nomeada (`CONFIGURACOES`, escolhida por `EXEMPLOS_CONFIG`; `A` é o comportamento original). O laudo que está sendo escrito **nunca serve de exemplo para si mesmo** (o texto atual da seção já vai à IA), o que também impede o `avaliar_geracao` de colar a resposta. `edicoes_por_mes()` alimenta a tabela de `/estatisticas/` que mostra se ela está precisando corrigir menos a IA. `reforcos()` olha os deslikes recentes dos autores e, quando um motivo aparece com frequência, injeta uma regra extra no prompt (dicionário `REFORCOS`). pgvector fica para quando houver centenas de pares.

### Modelo de dados — `laudos/models.py`
`Laudo` → `Paragrafo` (um por tema/bloco, com `ativo` e `posicao`) → `Versao` (histórico; `versao_atual()` é a de maior `numero`). `Mensagem` guarda a conversa por seção. `Avaliacao` (like/deslike com motivos) pendura numa `Versao` e guarda o `autor`; um like cria/atualiza um `Exemplo` few-shot em nome de quem aprovou (`Exemplo.dono`), um deslike desativa o exemplo correspondente (`servico.avaliar_versao`). Para gestor, editar também avalia (`servico.editar_versao`): a versão dele ganha like e o texto da IA que ele substituiu ganha deslike com os motivos opcionais do diálogo; reeditar um texto que já era de uma pessoa só troca o exemplo. A edição de analista só cria a versão. `Versao.autor` diz quem editou na tela (vazio nos textos da IA). Deslike sem motivo não entra na conta dos reforços. `Exemplo` tem três fontes: `laudo_base` (estilo, de todos), `like` e `gemini` (pares de quem aprovou).

### Gestores e analistas — `laudos/papeis.py`
`Papel` (um por usuário) diz se a pessoa é **gestor** ou **analista** e, para analista, quem é o gestor responsável; quem não tem registro é analista sem gestor. Edita-se na página do usuário em `/admin/`. **Só gestor avalia** (like, deslike e edição que vira exemplo), e o conjunto das avaliações de todos os gestores é o padrão da IA para todo mundo. O gestor abre, avalia e edita os laudos dos analistas vinculados a ele; conversar com a IA, inserir e excluir bloco são só da dona do laudo. A migração `0009` deixou como gestor quem já usava o sistema.

### Acesso e isolamento — `laudos/acesso.py`, `config/settings.py`
`LoginRequiredMiddleware` exige login em tudo. Todo laudo tem `dono`; as views têm dois alcances: `_laudo_da_usuaria`/`_paragrafo_da_usuaria` (só a dona: conversa, inserir, excluir) e `_laudo_ao_alcance`/`_versao_ao_alcance` (a dona ou o gestor dela: abrir, avaliar, editar). Fora do alcance, a resposta é **404** (não revela que o recurso existe); analista que tenta avaliar recebe 403. Login bloqueia por 15 min após 5 senhas erradas, usando o cache no banco (daí `createcachetable`). Em produção (`DEBUG=0`) ligam-se HTTPS obrigatório, cookies seguros e HSTS.

## Testes

`laudos/tests.py` **nunca chama a rede**: `setUpModule` instala uma trava (`_SemRede`) que faz qualquer teste falhar se tentar instanciar `openai.OpenAI` ou `google.genai.Client`. Os testes simulam a IA com `mock.patch.object(gemini, "gerar"/"verificar", ...)`. Ao escrever testes novos, siga esse padrão — use os helpers `resposta()`, `par()`, `verificacao()` em vez de chamar a IA de verdade.

## Produção

Deploy no Render, plano pago (`render.yaml` + `build.sh`), com Postgres do Neon via `DATABASE_URL` (sem ela, cai no SQLite local). Gunicorn com um processo e várias threads (`gunicorn.conf.py`). `/saude/` (middleware `laudos/saude.py`, no topo da lista) responde sem login, sem HTTPS e sem conferir o host, para a checagem do Render — e **sem tocar no banco**: o Render bate nela o tempo todo, e qualquer consulta ali impede o Neon de dormir (5 min sem consulta) e cobra compute 24/7. Conexões com o banco usam `conn_health_checks` e keepalive, porque o Neon fecha conexões paradas enquanto a IA pensa. No front, `enviar()` em `app.js` tenta de novo em falha de rede ou 502/503/504 e mostra erro num recado, nunca em `alert()`; por isso editar e avaliar ignoram reenvio repetido. WhiteNoise serve os estáticos (`collectstatic`). `garantir_admin` só roda no deploy quando `ADMIN_USUARIO`/`ADMIN_SENHA` estão no ambiente.

## Sigilo

Nenhum dado de paciente real entra no repositório. `laudos/seeds/laudos_base.json` (laudos reais que viram exemplos de estilo) e `db.sqlite3` estão no `.gitignore`; o versionado é `laudos_base.exemplo.json`, fictício. `laudos_exemplos/` (PDFs, `substituicoes.txt` da anonimização) e `gemini/` (export do Takeout) ficam só na máquina local. Testes: rode com `DATABASE_URL=` para não usar o Neon do `.env`.

## Requisitos não funcionais

- pt-BR em código, UI e mensagens.
- Dados de saúde (LGPD): nenhum dado real de paciente no repositório, testes, seeds, logs, screenshots ou PRs.
- Isolamento por dona do laudo e gestor; fora do alcance responde 404.
- `/saude/` nunca toca no banco; geração resiliente a queda do servidor.

## Documentos

- `demandas.md` — backlog e "onde parei" (formato do kit)
- `historico.md` — plano e decisões originais do sistema
- `REVIEW.md` — checklist do revisor
