"""Garante que o administrador do sistema exista.

Lê ADMIN_USUARIO e ADMIN_SENHA do ambiente, nunca do código, porque o
repositório é público. Roda em todo deploy e pode rodar mais de uma vez:
se o administrador já existe, a senha só é trocada com --redefinir-senha,
para não desfazer uma troca feita pela tela.
"""

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from laudos.models import Laudo


class Command(BaseCommand):
    help = "Cria o superusuário a partir de ADMIN_USUARIO e ADMIN_SENHA, se ainda não existir."

    def add_arguments(self, parser):
        parser.add_argument("--redefinir-senha", action="store_true", help="Troca a senha de um administrador que já existe.")

    def handle(self, *args, **opcoes):
        usuario = os.environ.get("ADMIN_USUARIO", "").strip()
        senha = os.environ.get("ADMIN_SENHA", "")
        if not usuario or not senha:
            raise CommandError("Defina ADMIN_USUARIO e ADMIN_SENHA no ambiente ou no arquivo .env.")

        User = get_user_model()
        admin = User.objects.filter(username__iexact=usuario).first()
        if admin is None or opcoes["redefinir_senha"]:
            try:
                validate_password(senha, user=admin or User(username=usuario))
            except ValidationError as erro:
                raise CommandError("A senha do administrador é fraca: " + " ".join(erro.messages))

        if admin is None:
            admin = User.objects.create_superuser(username=usuario, password=senha)
            self.stdout.write(self.style.SUCCESS(f"Administrador {usuario} criado."))
        else:
            mudou = not (admin.is_superuser and admin.is_staff and admin.is_active)
            admin.is_superuser = admin.is_staff = admin.is_active = True
            if opcoes["redefinir_senha"]:
                admin.set_password(senha)
                mudou = True
            admin.save()
            self.stdout.write(f"Administrador {admin.username} já existia{'; dados atualizados' if mudou else ''}.")

        sem_dono = Laudo.objects.filter(dono__isnull=True).update(dono=admin)
        if sem_dono:
            self.stdout.write(f"{sem_dono} laudo(s) sem dono atribuído(s) a {admin.username}.")
