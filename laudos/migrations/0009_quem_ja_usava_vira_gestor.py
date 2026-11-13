from django.conf import settings
from django.db import migrations


def preencher(apps, schema_editor):
    """Mantém tudo como era para quem já usava o sistema.

    Até aqui toda pessoa avaliava os próprios laudos. Então quem já existe vira gestor,
    e as avaliações e edições antigas passam a ter como autor o dono do laudo.
    Quem for analista é rebaixado depois, pelo admin. Usuário novo já nasce analista.
    """
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Papel = apps.get_model("laudos", "Papel")
    Laudo = apps.get_model("laudos", "Laudo")
    Versao = apps.get_model("laudos", "Versao")
    Avaliacao = apps.get_model("laudos", "Avaliacao")

    com_papel = set(Papel.objects.values_list("usuario_id", flat=True))
    Papel.objects.bulk_create(
        Papel(usuario_id=id_, tipo="gestor") for id_ in User.objects.values_list("id", flat=True) if id_ not in com_papel
    )
    for laudo_id, dono_id in Laudo.objects.exclude(dono=None).values_list("id", "dono_id"):
        Avaliacao.objects.filter(versao__paragrafo__laudo_id=laudo_id, autor=None).update(autor_id=dono_id)
        Versao.objects.filter(paragrafo__laudo_id=laudo_id, origem="edicao_usuaria", autor=None).update(autor_id=dono_id)


class Migration(migrations.Migration):

    dependencies = [
        ("laudos", "0008_papeis_e_autoria"),
    ]

    operations = [
        migrations.RunPython(preencher, migrations.RunPython.noop),
    ]
