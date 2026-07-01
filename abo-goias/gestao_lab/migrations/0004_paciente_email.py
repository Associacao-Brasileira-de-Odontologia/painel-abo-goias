from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestao_lab", "0003_enriquecimento_paciente"),
    ]

    operations = [
        migrations.AddField(
            model_name="paciente",
            name="email",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
    ]
