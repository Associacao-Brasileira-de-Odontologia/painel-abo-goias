"""Serviço de envio de contratos gerados para a ficha do paciente no Dental Office."""

from __future__ import annotations

import logging
from datetime import date

from django.utils import timezone
from gestao_lab.integrations.dental import DentalAPIError, DentalClient

from .documentos import gerar_contrato

logger = logging.getLogger(__name__)


def enviar_contrato_ao_dental(contrato) -> tuple[bool, str]:
    """Envia o contrato para a ficha do paciente no Dental Office.

    Prefere PDF (arquivo_pdf) em relação ao DOCX (arquivo). Se nenhum arquivo
    salvo estiver disponível, regenera o DOCX a partir dos metadados do contrato
    e tenta converter para PDF se LibreOffice estiver disponível.
    Retorna (True, "") em caso de sucesso ou (False, mensagem_de_erro) em falha.
    """

    paciente = contrato.paciente

    if not paciente.id_dental:
        erro = "Paciente sem id_dental — não é possível enviar ao Dental Office."
        logger.error(
            "enviar_contrato_ao_dental: %s (contrato_pk=%s)", erro, contrato.pk
        )
        _marcar_erro(contrato)
        return False, erro

    # --- Obter os bytes do documento (preferência: PDF; fallback: DOCX) ---
    arquivo_bytes: bytes | None = None
    extensao = "pdf"

    if contrato.arquivo_pdf:
        try:
            contrato.arquivo_pdf.open("rb")
            arquivo_bytes = contrato.arquivo_pdf.read()
            contrato.arquivo_pdf.close()
        except Exception as exc:
            logger.warning(
                "enviar_contrato_ao_dental: falha ao ler PDF salvo "
                "(contrato_pk=%s), tentando DOCX: %s",
                contrato.pk,
                exc,
            )
            arquivo_bytes = None

    if not arquivo_bytes and contrato.arquivo:
        extensao = "docx"
        try:
            contrato.arquivo.open("rb")
            arquivo_bytes = contrato.arquivo.read()
            contrato.arquivo.close()
        except Exception as exc:
            logger.warning(
                "enviar_contrato_ao_dental: falha ao ler DOCX salvo "
                "(contrato_pk=%s), regenerando: %s",
                contrato.pk,
                exc,
            )
            arquivo_bytes = None

    if not arquivo_bytes:
        # Último recurso: regenera DOCX e tenta converter para PDF
        extensao = "docx"
        try:
            arquivo_bytes = gerar_contrato(
                paciente=paciente,
                tipo=contrato.tipo,
                observacoes_clinicas=contrato.observacoes_clinicas,
                profissional_nome=contrato.profissional_nome,
                profissional_cro=contrato.profissional_cro,
                local_assinatura=contrato.local_assinatura,
            )
            from gestao_contratos.services.pdf_converter import (
                docx_para_pdf,
                libreoffice_disponivel,
            )

            if libreoffice_disponivel():
                try:
                    arquivo_bytes = docx_para_pdf(arquivo_bytes)
                    extensao = "pdf"
                except RuntimeError as exc:
                    logger.warning(
                        "enviar_contrato_ao_dental: conversão PDF falhou, "
                        "enviando DOCX (contrato_pk=%s): %s",
                        contrato.pk,
                        exc,
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
        f"{paciente.nome.split()[0].title()} — {data_geracao}.{extensao}"
    )
    descricao = (
        f"Termo de consentimento ({contrato.get_tipo_display()}) "
        f"gerado em {data_geracao} via ABO Goiás."
    )

    try:
        client = DentalClient()
        resposta = client.enviar_documento_paciente(
            id_dental=paciente.id_dental,
            arquivo_bytes=arquivo_bytes,
            nome=nome_arquivo,
            descricao=descricao,
            tag_list="contrato",
        )
    except DentalAPIError as exc:
        erro = str(exc)
        logger.error(
            "enviar_contrato_ao_dental: erro na API (contrato_pk=%s, "
            "id_dental=%s): %s",
            contrato.pk,
            paciente.id_dental,
            erro,
        )
        _marcar_erro(contrato)
        return False, erro

    logger.info(
        "enviar_contrato_ao_dental: resposta da API (contrato_pk=%s, "
        "id_dental=%s): %s",
        contrato.pk,
        paciente.id_dental,
        resposta,
    )

    # Valida se o corpo indica falha (algumas APIs retornam HTTP 200 com erro no body)
    erro_corpo = _extrair_erro_resposta(resposta)
    if erro_corpo:
        logger.error(
            "enviar_contrato_ao_dental: API retornou erro no corpo "
            "(contrato_pk=%s): %s",
            contrato.pk,
            erro_corpo,
        )
        _marcar_erro(contrato)
        return False, erro_corpo

    contrato.status_envio_dental = "enviado"
    contrato.enviado_dental_em = timezone.now()
    contrato.save(
        update_fields=["status_envio_dental", "enviado_dental_em", "atualizado_em"]
    )
    return True, ""


def _extrair_erro_resposta(resposta: object) -> str:
    """Extrai mensagem de erro do corpo JSON da resposta, se houver.

    Verifica apenas as chaves 'errors' e 'error', que são o padrão Rails para
    erros. A chave 'message' é intencionalmente ignorada porque muitas APIs a
    usam tanto em respostas de sucesso quanto de erro, o que causaria falsos
    positivos — ex.: {"message": "Document created successfully"}.
    """
    if not isinstance(resposta, dict):
        return ""
    for chave in ("errors", "error"):
        valor = resposta.get(chave)
        if valor:
            if isinstance(valor, list):
                return "; ".join(str(v) for v in valor)
            return str(valor)
    return ""


def _marcar_erro(contrato) -> None:
    contrato.status_envio_dental = "erro"
    contrato.save(update_fields=["status_envio_dental", "atualizado_em"])
