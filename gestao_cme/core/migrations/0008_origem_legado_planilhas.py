from django.db import migrations, models


ORIGEM_CHOICES = [
    ("MANUAL", "Manual"),
    ("EDUQ", "Eduq"),
    ("LEGADO", "Legado"),
    ("EXEMPLO", "Exemplo"),
]


def migrar_origem_csv_para_legado(apps, schema_editor):
    Abrigo = apps.get_model("core", "Abrigo")
    Kit = apps.get_model("core", "Kit")
    Material = apps.get_model("core", "Material")
    Movimentacao = apps.get_model("core", "Movimentacao")

    for model in (Abrigo, Kit, Material, Movimentacao):
        model.objects.filter(origem="CSV").update(origem="LEGADO")

    for kit in Kit.objects.filter(codigo__startswith="KITCSV-"):
        kit.codigo = kit.codigo.replace("KITCSV-", "KITLEG-", 1)
        kit.save(update_fields=["codigo"])

    for material in Material.objects.filter(codigo__startswith="MATCSV-"):
        material.codigo = material.codigo.replace("MATCSV-", "MATLEG-", 1)
        material.save(update_fields=["codigo"])


def reverter_origem_legado_para_csv(apps, schema_editor):
    Abrigo = apps.get_model("core", "Abrigo")
    Kit = apps.get_model("core", "Kit")
    Material = apps.get_model("core", "Material")
    Movimentacao = apps.get_model("core", "Movimentacao")

    for kit in Kit.objects.filter(codigo__startswith="KITLEG-"):
        kit.codigo = kit.codigo.replace("KITLEG-", "KITCSV-", 1)
        kit.save(update_fields=["codigo"])

    for material in Material.objects.filter(codigo__startswith="MATLEG-"):
        material.codigo = material.codigo.replace("MATLEG-", "MATCSV-", 1)
        material.save(update_fields=["codigo"])

    for model in (Abrigo, Kit, Material, Movimentacao):
        model.objects.filter(origem="LEGADO").update(origem="CSV")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_dados_operacionais_reais"),
    ]

    operations = [
        migrations.RunPython(
            migrar_origem_csv_para_legado,
            reverse_code=reverter_origem_legado_para_csv,
        ),
        migrations.AlterField(
            model_name="aluno",
            name="origem",
            field=models.CharField(choices=ORIGEM_CHOICES, default="MANUAL", max_length=20),
        ),
        migrations.AlterField(
            model_name="abrigo",
            name="origem",
            field=models.CharField(choices=ORIGEM_CHOICES, default="MANUAL", max_length=20),
        ),
        migrations.AlterField(
            model_name="kit",
            name="origem",
            field=models.CharField(choices=ORIGEM_CHOICES, default="MANUAL", max_length=20),
        ),
        migrations.AlterField(
            model_name="material",
            name="origem",
            field=models.CharField(choices=ORIGEM_CHOICES, default="MANUAL", max_length=20),
        ),
        migrations.AlterField(
            model_name="movimentacao",
            name="origem",
            field=models.CharField(choices=ORIGEM_CHOICES, default="LEGADO", max_length=20),
        ),
        migrations.AlterField(
            model_name="turma",
            name="origem",
            field=models.CharField(choices=ORIGEM_CHOICES, default="MANUAL", max_length=20),
        ),
    ]
