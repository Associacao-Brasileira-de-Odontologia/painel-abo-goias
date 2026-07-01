from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao_contratos", "0001_inicial"),
    ]

    operations = [
        migrations.AddField(
            model_name="contratogerado",
            name="local_assinatura",
            field=models.CharField(default="Goiânia - GO", max_length=100),
        ),
        migrations.AddField(
            model_name="contratogerado",
            name="status_envio_dental",
            field=models.CharField(
                choices=[
                    ("nao_enviado", "Não enviado"),
                    ("enviado", "Enviado"),
                    ("erro", "Erro no envio"),
                ],
                default="nao_enviado",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="contratogerado",
            name="enviado_dental_em",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
