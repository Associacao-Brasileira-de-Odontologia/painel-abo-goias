import django.db.models.deletion
from django.db import migrations, models


ORIGEM_CHOICES = [
    ("MANUAL", "Manual"),
    ("EDUQ", "Eduq"),
    ("CSV", "CSV"),
    ("EXEMPLO", "Exemplo"),
]


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_aluno_cpf_nao_unico"),
    ]

    operations = [
        migrations.AlterField(
            model_name="aluno",
            name="origem",
            field=models.CharField(choices=ORIGEM_CHOICES, default="MANUAL", max_length=20),
        ),
        migrations.AlterField(
            model_name="turma",
            name="origem",
            field=models.CharField(choices=ORIGEM_CHOICES, default="MANUAL", max_length=20),
        ),
        migrations.AddField(
            model_name="kit",
            name="origem",
            field=models.CharField(choices=ORIGEM_CHOICES, default="MANUAL", max_length=20),
        ),
        migrations.AddField(
            model_name="kit",
            name="quantidade",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="kit",
            name="ultima_sincronizacao",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="material",
            name="disponivel",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="material",
            name="identificacao",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="material",
            name="origem",
            field=models.CharField(choices=ORIGEM_CHOICES, default="MANUAL", max_length=20),
        ),
        migrations.AddField(
            model_name="material",
            name="rotulo_kit",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="material",
            name="ultima_sincronizacao",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="Abrigo",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                ("ativo", models.BooleanField(default=True)),
                ("identificador", models.CharField(max_length=30, unique=True)),
                ("ocupado", models.BooleanField(default=False)),
                ("origem", models.CharField(choices=ORIGEM_CHOICES, default="MANUAL", max_length=20)),
                ("ultima_sincronizacao", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "abrigo",
                "verbose_name_plural": "abrigos",
                "ordering": ["identificador"],
            },
        ),
        migrations.CreateModel(
            name="Movimentacao",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("criado_em", models.DateTimeField(auto_now_add=True)),
                ("atualizado_em", models.DateTimeField(auto_now=True)),
                ("ativo", models.BooleanField(default=True)),
                ("data_hora", models.DateTimeField()),
                (
                    "tipo",
                    models.CharField(
                        choices=[("SAIDA", "Saida"), ("ENTRADA", "Entrada")],
                        max_length=10,
                    ),
                ),
                ("aluno_codigo_externo", models.CharField(blank=True, max_length=40)),
                ("aluno_nome", models.CharField(max_length=150)),
                ("turma_nome", models.CharField(blank=True, max_length=150)),
                ("pacote_codigo", models.CharField(max_length=40)),
                ("retirado", models.BooleanField(blank=True, null=True)),
                ("arquivo_origem", models.CharField(max_length=80)),
                ("row_hash", models.CharField(max_length=64, unique=True)),
                ("origem", models.CharField(choices=ORIGEM_CHOICES, default="CSV", max_length=20)),
                ("observacoes", models.TextField(blank=True)),
                (
                    "aluno",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="movimentacoes",
                        to="core.aluno",
                    ),
                ),
                (
                    "material",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="movimentacoes",
                        to="core.material",
                    ),
                ),
                (
                    "turma",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="movimentacoes",
                        to="core.turma",
                    ),
                ),
            ],
            options={
                "verbose_name": "movimentacao",
                "verbose_name_plural": "movimentacoes",
                "ordering": ["-data_hora", "-id"],
            },
        ),
    ]
