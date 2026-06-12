from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_marcar_academicos_exemplo"),
    ]

    operations = [
        migrations.AlterField(
            model_name="aluno",
            name="cpf",
            field=models.CharField(blank=True, max_length=14, null=True),
        ),
    ]
