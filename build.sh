#!/usr/bin/env bash
# Roda no deploy do Render. Para tudo se qualquer passo falhar.
set -o errexit

pip install -r requirements.txt

# Junta os arquivos estáticos para o WhiteNoise servir.
python manage.py collectstatic --no-input

# Cria a tabela de cache usada pelo bloqueio de tentativas de login.
python manage.py createcachetable

# Aplica as migrações no banco do Neon.
python manage.py migrate

# Garante o usuário administrador só quando as credenciais estão no ambiente.
# Sem elas, o deploy segue normal (o admin já foi criado direto no banco).
if [ -n "$ADMIN_USUARIO" ] && [ -n "$ADMIN_SENHA" ]; then
  python manage.py garantir_admin
fi
