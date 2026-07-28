"""O que a Gestão de Contratos entrega ao Portal (ver `comum.portal`)."""

from __future__ import annotations

from django.db.models import Q

from comum.portal import Evento, FontePortal, Tarefa

from ..models import ContratoGerado

LIMITE_EVENTOS = 4


def resumo() -> dict[str, int]:
    return {
        "contratos_gerados": ContratoGerado.objects.count(),
        # Documentos assinados que não chegaram ao Dental Office (falha ou
        # pendente) — precisam de atenção para não se perderem por falha de
        # integração. Fica no resumo, e não só na tarefa, para que a contagem
        # aconteça uma vez só (ver comum.portal).
        "contratos_envio_dental_pendente": (
            ContratoGerado.objects.filter(status="assinado")
            .filter(
                Q(status_envio_dental="erro") | Q(status_envio_dental="nao_enviado")
            )
            .count()
        ),
    }


def tarefas(resumo: dict[str, int]) -> list[Tarefa]:
    pendentes = resumo.get("contratos_envio_dental_pendente", 0)
    if not pendentes:
        return []
    return [
        Tarefa(
            texto=(
                f"{pendentes} contrato(s) assinado(s) sem envio ao Dental Office"
            ),
            url_name="contrato_envios_dental",
            urgente=True,
        )
    ]


def eventos() -> list[Evento]:
    return [
        Evento(
            categoria="devolucao",
            titulo="Contrato gerado",
            descricao=f"{contrato.get_tipo_display()} — {contrato.paciente.nome}.",
            data=contrato.criado_em,
        )
        for contrato in ContratoGerado.objects.select_related("paciente").order_by(
            "-criado_em"
        )[:LIMITE_EVENTOS]
    ]


FONTE = FontePortal(
    nome="contratos", ordem=30, resumo=resumo, tarefas=tarefas, eventos=eventos
)
