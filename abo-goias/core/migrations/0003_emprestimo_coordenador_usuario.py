# Generated manually for coordinator authentication bootstrap.

import django.db.models.deletion
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import migrations, models


def criar_usuario_coordenador(apps, schema_editor):
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(app_label, model_name)
    Emprestimo = apps.get_model("core", "Emprestimo")

    usuario, created = User.objects.get_or_create(
        username="coordenador.teste",
        defaults={
            "first_name": "Coordenador",
            "last_name": "Teste",
            "email": "coordenador.teste@example.com",
            "is_staff": True,
            "is_active": True,
            "password": make_password("Coordenador@123"),
        },
    )

    if not created:
        usuario.first_name = usuario.first_name or "Coordenador"
        usuario.last_name = usuario.last_name or "Teste"
        usuario.email = usuario.email or "coordenador.teste@example.com"
        usuario.is_staff = True
        usuario.is_active = True
        usuario.save(update_fields=["first_name", "last_name", "email", "is_staff", "is_active"])

    Emprestimo.objects.filter(coordenador="Mariana Lopes").update(
        coordenador_usuario=usuario
    )


def remover_usuario_coordenador(apps, schema_editor):
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
        ("core", "0002_emprestimo_itememprestimo"),
    ]

    operations = [
        migrations.AddField(
            model_name="emprestimo",
            name="coordenador_usuario",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="emprestimos_realizados",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(criar_usuario_coordenador, remover_usuario_coordenador),
    ]
