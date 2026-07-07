from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao_contratos", "0002_contrato_envio_dental"),
    ]

    operations = [
        migrations.AddField(
            model_name="contratogerado",
            name="arquivo",
            field=models.FileField(blank=True, upload_to="contratos/"),
        ),
        migrations.AddField(
            model_name="contratogerado",
            name="status_envio",
            field=models.CharField(
                choices=[
                    ("nao_enviado", "Não enviado"),
                    ("enviado_email", "Enviado por e-mail"),
                    ("enviado_whatsapp", "Enviado por WhatsApp"),
                ],
                default="nao_enviado",
                max_length=25,
            ),
        ),
        migrations.AddField(
            model_name="contratogerado",
            name="enviado_em",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
