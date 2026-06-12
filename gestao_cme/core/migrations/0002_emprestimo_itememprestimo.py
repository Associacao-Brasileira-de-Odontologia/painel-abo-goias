# Generated manually for loan tracking models.

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Emprestimo",
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
                ("coordenador", models.CharField(blank=True, max_length=120)),
                (
                    "data_emprestimo",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("data_prevista_devolucao", models.DateField(blank=True, null=True)),
                ("data_devolucao", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("EMPRESTADO", "Emprestado"),
                            ("DEVOLVIDO", "Devolvido"),
                            ("ATRASADO", "Atrasado"),
                        ],
                        default="EMPRESTADO",
                        max_length=20,
                    ),
                ),
                ("observacoes", models.TextField(blank=True)),
                (
                    "aluno",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="emprestimos",
                        to="core.aluno",
                    ),
                ),
                (
                    "kit",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="emprestimos",
                        to="core.kit",
                    ),
                ),
            ],
            options={
                "verbose_name": "emprestimo",
                "verbose_name_plural": "emprestimos",
                "ordering": ["-data_emprestimo", "-id"],
            },
        ),
        migrations.CreateModel(
            name="ItemEmprestimo",
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
                    "armario",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="itens_emprestados",
                        to="core.armario",
                    ),
                ),
                (
                    "emprestimo",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="itens",
                        to="core.emprestimo",
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
                "verbose_name": "item do emprestimo",
                "verbose_name_plural": "itens do emprestimo",
                "ordering": ["emprestimo", "material"],
            },
        ),
        migrations.AddConstraint(
            model_name="itememprestimo",
            constraint=models.UniqueConstraint(
                fields=("emprestimo", "material", "armario"),
                name="item_emprestimo_material_armario_unico",
            ),
        ),
    ]
