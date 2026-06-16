from django.db import migrations


TURMAS_EXEMPLO = [
    "IMP-2026-1",
    "END-2026-1",
    "PER-2026-1",
    "PRO-2026-1",
]

ALUNOS_EXEMPLO = [
    "20260001",
    "20260002",
    "20260003",
    "20260004",
    "20260005",
    "20260006",
    "20260007",
    "20260008",
    "20260009",
    "20260010",
    "20260011",
    "20260012",
]


def marcar_exemplos(apps, schema_editor):
    Turma = apps.get_model("core", "Turma")
    Aluno = apps.get_model("core", "Aluno")

    Turma.objects.filter(codigo__in=TURMAS_EXEMPLO).update(origem="EXEMPLO")
    Aluno.objects.filter(matricula__in=ALUNOS_EXEMPLO).update(origem="EXEMPLO")


def desmarcar_exemplos(apps, schema_editor):
    Turma = apps.get_model("core", "Turma")
    Aluno = apps.get_model("core", "Aluno")

    Turma.objects.filter(codigo__in=TURMAS_EXEMPLO, origem="EXEMPLO").update(
        origem="MANUAL"
    )
    Aluno.objects.filter(matricula__in=ALUNOS_EXEMPLO, origem="EXEMPLO").update(
        origem="MANUAL"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_origem_sincronizacao_academica"),
    ]

    operations = [
        migrations.RunPython(marcar_exemplos, desmarcar_exemplos),
    ]
