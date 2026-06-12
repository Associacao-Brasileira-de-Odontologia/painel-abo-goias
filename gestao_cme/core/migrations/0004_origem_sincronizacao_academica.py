from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_emprestimo_coordenador_usuario"),
    ]

    operations = [
        migrations.AddField(
            model_name="turma",
            name="origem",
            field=models.CharField(
                choices=[
                    ("MANUAL", "Manual"),
                    ("EDUQ", "Eduq"),
                    ("EXEMPLO", "Exemplo"),
                ],
                default="MANUAL",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="turma",
            name="ultima_sincronizacao",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="aluno",
            name="origem",
            field=models.CharField(
                choices=[
                    ("MANUAL", "Manual"),
                    ("EDUQ", "Eduq"),
                    ("EXEMPLO", "Exemplo"),
                ],
                default="MANUAL",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="aluno",
            name="ultima_sincronizacao",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
