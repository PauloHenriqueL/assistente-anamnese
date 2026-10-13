# Lido sozinho pelo Gunicorn na pasta do projeto.
# Um processo com várias threads: enquanto uma requisição espera (upload, banco),
# as outras (consulta do andamento, like) seguem atendidas. A IA roda em threads à parte.
workers = 1
worker_class = "gthread"
threads = 8
timeout = 600
# No deploy, dá tempo para as requisições em curso terminarem antes de desligar.
graceful_timeout = 30
keepalive = 5
