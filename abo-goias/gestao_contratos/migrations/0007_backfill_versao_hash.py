"""Backfill de versao e hash_sha256 para contratos existentes.

- versao: sequencial por (paciente, tipo), na ordem de criação.
- hash_sha256: calculado a partir do PDF salvo, quando o arquivo ainda
  existir no storage; contratos sem PDF legível ficam com hash em branco.
"""

import hashlib

from django.db import migrations


def backfill(apps, schema_editor):
    ContratoGerado = apps.get_model("gestao_contratos", "ContratoGerado")

    contadores: dict[tuple[int, str], int] = {}
    for contrato in ContratoGerado.objects.order_by("criado_em", "pk").iterator():
        chave = (contrato.paciente_id, contrato.tipo)
        contadores[chave] = contadores.get(chave, 0) + 1
        contrato.versao = contadores[chave]

        if contrato.arquivo_pdf:
            try:
                contrato.arquivo_pdf.open("rb")
                conteudo = contrato.arquivo_pdf.read()
                contrato.arquivo_pdf.close()
                contrato.hash_sha256 = hashlib.sha256(conteudo).hexdigest()
            except Exception:
                # Arquivo ausente do storage — mantém hash em branco.
                pass

        contrato.save(update_fields=["versao", "hash_sha256"])


class Migration(migrations.Migration):

    dependencies = [
        ("gestao_contratos", "0006_contrato_ciclo_vida"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
