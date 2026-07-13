"""Campo hash_arquivo_assinado + backfill para contratos já assinados.

hash_arquivo_assinado guarda o SHA-256 do arquivo assinado final
(arquivo_pdf_assinado), incluindo o carimbo de tempo embutido quando
houver. É a impressão digital que a página pública de validação confere
contra o PDF enviado pelo usuário. Para contratos já assinados, calcula o
hash a partir do arquivo salvo; se o arquivo não estiver mais no storage,
cai para hash_sha256 (equivalente quando não há carimbo embutido).
"""

import hashlib

from django.db import migrations, models


def backfill(apps, schema_editor):
    ContratoGerado = apps.get_model("gestao_contratos", "ContratoGerado")

    assinados = ContratoGerado.objects.exclude(arquivo_pdf_assinado="")
    for contrato in assinados.iterator():
        digest = ""
        try:
            contrato.arquivo_pdf_assinado.open("rb")
            conteudo = contrato.arquivo_pdf_assinado.read()
            contrato.arquivo_pdf_assinado.close()
            digest = hashlib.sha256(conteudo).hexdigest()
        except Exception:
            # Arquivo ausente do storage — cai para hash_sha256, que
            # coincide com o hash do arquivo quando não há carimbo embutido.
            digest = contrato.hash_sha256 or ""

        if digest:
            contrato.hash_arquivo_assinado = digest
            contrato.save(update_fields=["hash_arquivo_assinado"])


class Migration(migrations.Migration):

    dependencies = [
        ("gestao_contratos", "0015_terminalassinatura_ativado_em"),
    ]

    operations = [
        migrations.AddField(
            model_name="contratogerado",
            name="hash_arquivo_assinado",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text=(
                    "SHA-256 do arquivo assinado final (arquivo_pdf_assinado), "
                    "já incluindo o carimbo de tempo embutido quando houver — é "
                    "a impressão digital conferida pela página pública de "
                    "validação. Difere de hash_sha256 quando um carimbo de tempo "
                    "é embutido após a assinatura, pois isso reescreve os bytes "
                    "do PDF."
                ),
                max_length=64,
            ),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
