# Remove, em qualquer banco onde exista, a conta "coordenador.teste" criada
# pela antiga migration 0003_emprestimo_coordenador_usuario com senha fixa
# (credencial exposta no historico do repositorio). Esta migration roda uma
# unica vez por banco e nao recria a conta em bancos onde ela nunca existiu.

from django.conf import settings
from django.db import migrations


def remover_usuario_coordenador_teste(apps, schema_editor):
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(app_label, model_name)
    Emprestimo = apps.get_model("core", "Emprestimo")

    usuario = User.objects.filter(username="coordenador.teste").first()
    if usuario:
        Emprestimo.objects.filter(coordenador_usuario=usuario).update(
            coordenador_usuario=None
        )
        usuario.delete()


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0010_aluno_abrigo_fk"),
    ]

    operations = [
        migrations.RunPython(
            remover_usuario_coordenador_teste, migrations.RunPython.noop
        ),
    ]
