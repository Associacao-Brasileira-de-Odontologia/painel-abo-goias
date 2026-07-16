"""Preenche data_faturamento para pedidos ja totalmente faturados.

O campo passou a ser derivado no save() (paciente E lab -> data de hoje), mas os
pedidos historicos ja concluidos ficariam com o campo nulo. Sem uma data real de
quando o faturamento foi fechado, usa-se ``atualizado_em`` (ultima alteracao do
registro) como melhor aproximacao disponivel — e melhor que deixar em branco na
nova coluna. Reversivel.
"""

from __future__ import annotations

from django.db import migrations


def preencher(apps, schema_editor):
    PedidoMaterial = apps.get_model("gestao_lab", "PedidoMaterial")
    pendentes = PedidoMaterial.objects.filter(
        faturado_paciente=True,
        faturado_lab=True,
        data_faturamento__isnull=True,
    )
    for pedido in pendentes:
        # atualizado_em existe em todo registro (ModeloBase, auto_now).
        pedido.data_faturamento = pedido.atualizado_em.date()
        pedido.save(update_fields=["data_faturamento"])


def limpar(apps, schema_editor):
    PedidoMaterial = apps.get_model("gestao_lab", "PedidoMaterial")
    PedidoMaterial.objects.update(data_faturamento=None)


class Migration(migrations.Migration):
    dependencies = [
        ("gestao_lab", "0008_pedido_data_faturamento"),
    ]

    operations = [
        migrations.RunPython(preencher, limpar),
    ]
