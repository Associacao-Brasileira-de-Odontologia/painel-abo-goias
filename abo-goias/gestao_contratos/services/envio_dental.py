"""Serviço de envio de contratos gerados para a ficha do paciente no Dental Office."""

from __future__ import annotations

import logging
from datetime import date

from django.utils import timezone
from gestao_lab.integrations.dental import DentalAPIError, DentalClient

from .documentos import gerar_contrato

logger = logging.getLogger(__name__)


def enviar_contrato_ao_dental(contrato) -> tuple[bool, str]:
    """Regenera o DOCX do contrato e envia para a ficha do paciente no Dental Office.

    Retorna (True, "") em caso de sucesso ou (False, mensagem_de_erro) em falha.
    Atualiza contrato.status_envio_dental e contrato.enviado_dental_em
    conforme resultado.
    """

    paciente = contrato.paciente

    try:
        docx_bytes = gerar_contrato(
            paciente=paciente,
            tipo=contrato.tipo,
            observacoes_clinicas=contrato.observacoes_clinicas,
            profissional_nome=contrato.profissional_nome,
            profissional_cro=contrato.profissional_cro,
            local_assinatura=contrato.local_assinatura,
        )
    except FileNotFoundError as exc:
        erro = f"Modelo de documento não encontrado: {exc}"
        logger.error(
            "enviar_contrato_ao_dental: %s (contrato_pk=%s)", erro, contrato.pk
        )
        _marcar_erro(contrato)
        return False, erro

    data_geracao = (
        contrato.criado_em.strftime("%d/%m/%Y")
        if contrato.criado_em
        else date.today().strftime("%d/%m/%Y")
    )
    nome_arquivo = (
        f"Termo {contrato.get_tipo_display()} — "
        f"{paciente.nome.split()[0].title()} — {data_geracao}"
    )
    descricao = (
        f"Termo de consentimento ({contrato.get_tipo_display()}) "
        f"gerado em {data_geracao} via ABO Goiás."
    )

    try:
        client = DentalClient()
        client.enviar_documento_paciente(
            id_dental=paciente.id_dental,
            arquivo_bytes=docx_bytes,
            nome=nome_arquivo,
            descricao=descricao,
            tag_list="contrato",
        )
    except DentalAPIError as exc:
        erro = str(exc)
        logger.error(
            "enviar_contrato_ao_dental: erro na API (contrato_pk=%s): %s",
            contrato.pk,
            erro,
        )
        _marcar_erro(contrato)
        return False, erro

    contrato.status_envio_dental = "enviado"
    contrato.enviado_dental_em = timezone.now()
    contrato.save(
        update_fields=["status_envio_dental", "enviado_dental_em", "atualizado_em"]
    )
    return True, ""


def _marcar_erro(contrato) -> None:
    contrato.status_envio_dental = "erro"
    contrato.save(update_fields=["status_envio_dental", "atualizado_em"])
