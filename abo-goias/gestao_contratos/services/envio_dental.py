"""Serviço de envio de contratos gerados para a ficha do paciente no Dental Office."""

from __future__ import annotations

import logging
from datetime import date

from django.utils import timezone
from gestao_lab.integrations.dental import DentalAPIError, DentalClient

from .assinatura import registrar_evento
from .documentos import gerar_pdf

logger = logging.getLogger(__name__)


def enviar_contrato_ao_dental(contrato) -> tuple[bool, str]:
    """Envia o contrato para a ficha do paciente no Dental Office.

    Prefere o PDF já salvo em arquivo_pdf. Se não existir, gera o PDF
    diretamente a partir dos metadados do contrato (via reportlab, sem
    conversão DOCX→PDF). Retorna (True, "") em sucesso ou (False, erro).

    Cada tentativa registra um EventoContrato (iniciado/concluído/erro),
    alimentando a trilha de auditoria e o status em tempo real da tela
    de pós-geração.
    """

    paciente = contrato.paciente
    registrar_evento(contrato, "envio_dental_iniciado")

    if not paciente.id_dental:
        erro = "Paciente sem id_dental — não é possível enviar ao Dental Office."
        logger.error(
            "enviar_contrato_ao_dental: %s (contrato_pk=%s)", erro, contrato.pk
        )
        _marcar_erro(contrato, erro)
        return False, erro

    # ── 1. Ler PDF já salvo ────────────────────────────────────────────
    arquivo_bytes: bytes | None = None

    if contrato.arquivo_pdf:
        try:
            contrato.arquivo_pdf.open("rb")
            arquivo_bytes = contrato.arquivo_pdf.read()
            contrato.arquivo_pdf.close()
        except Exception as exc:
            logger.warning(
                "enviar_contrato_ao_dental: falha ao ler PDF salvo "
                "(contrato_pk=%s): %s",
                contrato.pk,
                exc,
            )
            arquivo_bytes = None

    # ── 2. Gerar PDF diretamente se não houver arquivo salvo ──────────
    if not arquivo_bytes:
        try:
            arquivo_bytes = gerar_pdf(
                paciente=paciente,
                tipo=contrato.tipo,
                profissional_nome=contrato.profissional_nome,
                profissional_cro=contrato.profissional_cro,
                local_assinatura=contrato.local_assinatura,
            )
            logger.info(
                "enviar_contrato_ao_dental: PDF gerado on-the-fly "
                "(contrato_pk=%s, %d bytes)",
                contrato.pk,
                len(arquivo_bytes),
            )
        except Exception as exc:
            erro = f"Falha ao gerar o PDF do contrato: {exc}"
            logger.error(
                "enviar_contrato_ao_dental: %s (contrato_pk=%s)", erro, contrato.pk
            )
            _marcar_erro(contrato, erro)
            return False, erro

    # ── 3. Montar nome e descrição ─────────────────────────────────────
    data_geracao = (
        contrato.criado_em.strftime("%d/%m/%Y")
        if contrato.criado_em
        else date.today().strftime("%d/%m/%Y")
    )
    nome_arquivo = (
        f"Termo {contrato.get_tipo_display()} — "
        f"{paciente.nome.split()[0].title()} — {data_geracao}.pdf"
    )
    descricao = (
        f"Termo de consentimento ({contrato.get_tipo_display()}) "
        f"gerado em {data_geracao} via ABO Goiás."
    )

    # ── 4. Enviar à API ────────────────────────────────────────────────
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
        _marcar_erro(contrato, erro)
        return False, erro

    logger.info(
        "enviar_contrato_ao_dental: resposta da API (contrato_pk=%s, "
        "id_dental=%s): %s",
        contrato.pk,
        paciente.id_dental,
        resposta,
    )

    erro_corpo = _extrair_erro_resposta(resposta)
    if erro_corpo:
        logger.error(
            "enviar_contrato_ao_dental: API retornou erro no corpo "
            "(contrato_pk=%s): %s",
            contrato.pk,
            erro_corpo,
        )
        _marcar_erro(contrato, erro_corpo)
        return False, erro_corpo

    contrato.status_envio_dental = "enviado"
    contrato.enviado_dental_em = timezone.now()
    contrato.save(
        update_fields=["status_envio_dental", "enviado_dental_em", "atualizado_em"]
    )
    registrar_evento(contrato, "envio_dental_concluido")
    return True, ""


def _extrair_erro_resposta(resposta: object) -> str:
    """Extrai mensagem de erro do corpo JSON da resposta, se houver.

    Verifica apenas as chaves 'errors' e 'error', que são o padrão Rails para
    erros. A chave 'message' é intencionalmente ignorada porque muitas APIs a
    usam tanto em respostas de sucesso quanto de erro.
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


def _marcar_erro(contrato, erro: str) -> None:
    contrato.status_envio_dental = "erro"
    contrato.save(update_fields=["status_envio_dental", "atualizado_em"])
    registrar_evento(contrato, "envio_dental_erro", erro=erro)
