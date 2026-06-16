# Generated manually for the initial core domain models.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Armario",
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
                ("identificacao", models.CharField(max_length=60, unique=True)),
                ("localizacao", models.CharField(blank=True, max_length=120)),
                ("descricao", models.TextField(blank=True)),
            ],
            options={
                "verbose_name": "armario",
                "verbose_name_plural": "armarios",
                "ordering": ["identificacao"],
            },
        ),
        migrations.CreateModel(
            name="Kit",
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
                ("nome", models.CharField(max_length=120)),
                ("codigo", models.CharField(max_length=40, unique=True)),
                ("descricao", models.TextField(blank=True)),
            ],
            options={
                "verbose_name": "kit",
                "verbose_name_plural": "kits",
                "ordering": ["nome"],
            },
        ),
        migrations.CreateModel(
            name="Material",
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
                ("nome", models.CharField(max_length=120)),
                ("codigo", models.CharField(max_length=40, unique=True)),
                ("descricao", models.TextField(blank=True)),
                (
                    "unidade_medida",
                    models.CharField(
                        choices=[
                            ("UN", "Unidade"),
                            ("CX", "Caixa"),
                            ("PC", "Pacote"),
                            ("FR", "Frasco"),
                            ("PAR", "Par"),
                        ],
                        default="UN",
                        max_length=5,
                    ),
                ),
                ("quantidade_minima", models.PositiveIntegerField(default=0)),
            ],
            options={
                "verbose_name": "material",
                "verbose_name_plural": "materiais",
                "ordering": ["nome"],
            },
        ),
        migrations.CreateModel(
            name="Turma",
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
                ("nome", models.CharField(max_length=120)),
                ("codigo", models.CharField(max_length=30, unique=True)),
                ("curso", models.CharField(blank=True, max_length=120)),
                ("data_inicio", models.DateField(blank=True, null=True)),
                ("data_fim", models.DateField(blank=True, null=True)),
                ("observacoes", models.TextField(blank=True)),
            ],
            options={
                "verbose_name": "turma",
                "verbose_name_plural": "turmas",
                "ordering": ["nome"],
            },
        ),
        migrations.CreateModel(
            name="Aluno",
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
                ("nome", models.CharField(max_length=150)),
                ("matricula", models.CharField(max_length=40, unique=True)),
                (
                    "cpf",
                    models.CharField(blank=True, max_length=14, null=True, unique=True),
                ),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("telefone", models.CharField(blank=True, max_length=20)),
                (
                    "turma",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="alunos",
                        to="core.turma",
                    ),
                ),
            ],
            options={
                "verbose_name": "aluno",
                "verbose_name_plural": "alunos",
                "ordering": ["nome"],
            },
        ),
        migrations.CreateModel(
            name="EstoqueArmario",
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
                ("quantidade", models.PositiveIntegerField(default=0)),
                ("observacoes", models.TextField(blank=True)),
                (
                    "armario",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="estoques",
                        to="core.armario",
                    ),
                ),
                (
                    "material",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="core.material",
                    ),
                ),
            ],
            options={
                "verbose_name": "estoque do armario",
                "verbose_name_plural": "estoques dos armarios",
                "ordering": ["armario", "material"],
            },
        ),
        migrations.CreateModel(
            name="KitMaterial",
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
                ("quantidade", models.PositiveIntegerField(default=1)),
                (
                    "kit",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="itens",
                        to="core.kit",
                    ),
                ),
                (
                    "material",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="core.material",
                    ),
                ),
            ],
            options={
                "verbose_name": "material do kit",
                "verbose_name_plural": "materiais do kit",
                "ordering": ["kit", "material"],
            },
        ),
        migrations.AddField(
            model_name="armario",
            name="materiais",
            field=models.ManyToManyField(
                blank=True,
                related_name="armarios",
                through="core.EstoqueArmario",
                to="core.material",
            ),
        ),
        migrations.AddField(
            model_name="kit",
            name="materiais",
            field=models.ManyToManyField(
                blank=True,
                related_name="kits",
                through="core.KitMaterial",
                to="core.material",
            ),
        ),
        migrations.AddConstraint(
            model_name="estoquearmario",
            constraint=models.UniqueConstraint(
                fields=("armario", "material"),
                name="estoque_armario_material_unico",
            ),
        ),
        migrations.AddConstraint(
            model_name="kitmaterial",
            constraint=models.UniqueConstraint(
                fields=("kit", "material"),
                name="kit_material_unico",
            ),
        ),
    ]
