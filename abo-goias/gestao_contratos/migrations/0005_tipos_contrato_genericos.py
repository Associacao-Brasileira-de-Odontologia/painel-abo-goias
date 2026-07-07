from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao_contratos", "0004_contrato_arquivo_pdf"),
    ]

    operations = [
        migrations.AlterField(
            model_name="contratogerado",
            name="tipo",
            field=models.CharField(
                choices=[
                    ("modelo_1", "Modelo 1"),
                    ("modelo_2", "Modelo 2"),
                    ("modelo_3", "Modelo 3"),
                    ("modelo_4", "Modelo 4"),
                ],
                max_length=30,
            ),
        ),
    ]
