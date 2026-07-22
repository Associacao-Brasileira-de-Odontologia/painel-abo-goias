"""Remove os alunos sincronizados do Dental Office — nenhum é um aluno real.

O Dental Office nunca foi a fonte correta de alunos (essa informação vive no
Eduq, mesma fonte já usada pelo gestao_cme) — o cadastro de AlunoLab feito a
partir da API do Dental trouxe registros que não correspondem a nenhum aluno
de fato. Remove também qualquer PedidoMaterial/Moldagem vinculado a esses
alunos (também não correspondem a pedidos/moldagens reais, já que o aluno
associado não existe). Irreversível — os dados apagados não podem ser
recuperados pela migração reversa.
"""

from __future__ import annotations

from django.db import migrations

ORIGEM_DENTAL = "DENTAL"


def remover_alunos_dental(apps, schema_editor):
    AlunoLab = apps.get_model("gestao_lab", "AlunoLab")
    Moldagem = apps.get_model("gestao_lab", "Moldagem")
    PedidoMaterial = apps.get_model("gestao_lab", "PedidoMaterial")

    alunos_dental = AlunoLab.objects.filter(origem=ORIGEM_DENTAL)
    Moldagem.objects.filter(aluno__in=alunos_dental).delete()
    PedidoMaterial.objects.filter(aluno__in=alunos_dental).delete()
    alunos_dental.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("gestao_lab", "0010_reformular_status_pedido"),
    ]

    operations = [
        migrations.RunPython(remover_alunos_dental, migrations.RunPython.noop),
    ]
