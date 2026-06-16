from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_origem_legado_planilhas"),
    ]

    operations = [
        migrations.AddField(
            model_name="aluno",
            name="cidade",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="aluno",
            name="uf",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
