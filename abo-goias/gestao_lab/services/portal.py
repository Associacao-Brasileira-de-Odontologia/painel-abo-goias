"""O que a Gestão de Laboratório entrega ao Portal (ver `comum.portal`)."""

from __future__ import annotations

from comum.portal import Evento, FontePortal, Tarefa

from ..models import Moldagem, PedidoMaterial

LIMITE_EVENTOS = 5


def resumo() -> dict[str, int]:
    return {
        "lab_pedidos_ativos": PedidoMaterial.objects.exclude(
            status=PedidoMaterial.Status.CONCLUIDO
        ).count(),
        "lab_pendentes_faturamento": PedidoMaterial.objects.filter(
            status=PedidoMaterial.Status.ENTREGUE_NAO_FATURADO
        ).count(),
        "lab_moldagens_pendentes": Moldagem.objects.filter(
            ativo=True, pedido_material=None
        ).count(),
    }


def tarefas(resumo: dict[str, int]) -> list[Tarefa]:
    lista: list[Tarefa] = []
    faturamento = resumo.get("lab_pendentes_faturamento", 0)
    if faturamento:
        lista.append(
            Tarefa(
                texto=f"{faturamento} pedido(s) de lab aguardando faturamento",
                url_name="lab_pedidos_faturamento",
            )
        )
    moldagens = resumo.get("lab_moldagens_pendentes", 0)
    if moldagens:
        lista.append(
            Tarefa(
                texto=f"{moldagens} moldagem(ns) sem pedido de lab vinculado",
                url_name="lab_moldagens",
            )
        )
    return lista


def eventos() -> list[Evento]:
    return [
        Evento(
            categoria="exportacao",
            titulo="Pedido de laboratório",
            descricao=f"{pedido.paciente.nome} → {pedido.laboratorio.nome}.",
            data=pedido.criado_em,
        )
        for pedido in PedidoMaterial.objects.select_related(
            "paciente", "laboratorio"
        ).order_by("-criado_em")[:LIMITE_EVENTOS]
    ]


FONTE = FontePortal(
    nome="lab", ordem=20, resumo=resumo, tarefas=tarefas, eventos=eventos
)
