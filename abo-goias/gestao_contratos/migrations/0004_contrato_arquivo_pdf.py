from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao_contratos", "0003_contrato_arquivo_envio"),
    ]

    operations = [
        migrations.AlterField(
            model_name="contratogerado",
            name="arquivo",
            field=models.FileField(blank=True, upload_to="contratos/docx/"),
        ),
        migrations.AddField(
            model_name="contratogerado",
            name="arquivo_pdf",
            field=models.FileField(blank=True, upload_to="contratos/pdf/"),
        ),
    ]
