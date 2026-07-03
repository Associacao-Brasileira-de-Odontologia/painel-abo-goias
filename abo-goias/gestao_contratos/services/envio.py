"""Serviços de envio de contratos por e-mail e WhatsApp."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import quote

from django.core.mail import EmailMessage
from django.utils import timezone

from .documentos import obter_melhor_pdf_bytes

if TYPE_CHECKING:
    from gestao_contratos.models import ContratoGerado

logger = logging.getLogger(__name__)

_CORPO_EMAIL = (
    "Prezado(a) {nome},\n\n"
    "Segue em anexo o Termo de Consentimento referente ao procedimento "
    "{tipo}, emitido pela Associação Brasileira de Odontologia — Seção de "
    "Goiás (ABO Goiás).\n\n"
    "Por favor, leia o documento com atenção, assine e nos envie uma cópia "
    "assinada.\n\n"
    "Em caso de dúvidas, entre em contato conosco.\n\n"
    "Atenciosamente,\n"
    "ABO Goiás"
)

_MENSAGEM_WHATSAPP = (
    "Olá! Segue seu Termo de Consentimento ({tipo}) da ABO Goiás. "
    "Por favor, baixe, assine e envie de volta."
)


_CONTENT_TYPE_DOCX = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _ler_anexo_contrato(contrato: "ContratoGerado") -> tuple[bytes, str, str] | None:
    """Retorna (conteudo, extensao, content_type) do melhor anexo disponível.

    Prefere o PDF (assinado, se houver, sobre o original); usa o DOCX como
    último recurso. Retorna None se nenhum arquivo puder ser lido.
    """

    pdf_bytes = obter_melhor_pdf_bytes(contrato)
    if pdf_bytes is not None:
        return pdf_bytes, "pdf", "application/pdf"

    if contrato.arquivo:
        try:
            contrato.arquivo.open("rb")
            conteudo = contrato.arquivo.read()
            contrato.arquivo.close()
            return conteudo, "docx", _CONTENT_TYPE_DOCX
        except Exception as exc:
            logger.warning(
                "enviar_contrato_email: erro ao ler docx (contrato_pk=%s): %s",
                contrato.pk,
                exc,
            )
    return None


def enviar_contrato_email(contrato: "ContratoGerado", destinatario: str) -> bool:
    """Envia o contrato por e-mail (PDF; DOCX como fallback) e atualiza o status.

    Retorna True em caso de sucesso ou False se ocorrer qualquer erro.
    """

    paciente = contrato.paciente
    tipo_display = contrato.get_tipo_display()

    assunto = f"Termo de Consentimento — {tipo_display} — ABO Goiás"
    corpo = _CORPO_EMAIL.format(nome=paciente.nome, tipo=tipo_display)

    email = EmailMessage(
        subject=assunto,
        body=corpo,
        to=[destinatario],
    )

    anexo = _ler_anexo_contrato(contrato)
    if anexo is None:
        logger.warning(
            "enviar_contrato_email: contrato %s sem arquivo salvo.", contrato.pk
        )
        return False

    conteudo, extensao, content_type = anexo
    nome_arquivo = (
        f"termo_{contrato.tipo}_{paciente.nome.split()[0].lower()}"
        f"_{paciente.id_dental}.{extensao}"
    )
    email.attach(nome_arquivo, conteudo, content_type)

    try:
        email.send(fail_silently=False)
    except Exception as exc:
        logger.error(
            "enviar_contrato_email: falha no envio (contrato_pk=%s, dest=%s): %s",
            contrato.pk,
            destinatario,
            exc,
        )
        return False

    contrato.status_envio = "enviado_email"
    contrato.enviado_em = timezone.now()
    contrato.save(update_fields=["status_envio", "enviado_em", "atualizado_em"])
    return True


def normalizar_celular(celular: str) -> str:
    """Normaliza um celular para dígitos com DDI 55 (padrão E.164 sem '+').

    Remove não-dígitos e adiciona o 55 se ausente. Retorna string vazia se
    não houver nenhum dígito. Compartilhado entre o link wa.me e o envio
    automático via Meta Cloud API — ambos precisam do mesmo formato.
    """

    digitos = re.sub(r"\D", "", celular)
    if not digitos:
        return ""
    if not digitos.startswith("55"):
        digitos = "55" + digitos
    return digitos


def calcular_link_whatsapp(celular: str, tipo_display: str) -> str:
    """Calcula o link wa.me sem efeitos colaterais no banco de dados.

    Normaliza o número (remove não-dígitos, adiciona 55 se necessário).
    Retorna string vazia se o número for inválido.
    """

    digitos = normalizar_celular(celular)
    if not digitos:
        return ""
    mensagem = _MENSAGEM_WHATSAPP.format(tipo=tipo_display)
    return f"https://wa.me/{digitos}?text={quote(mensagem)}"


def gerar_link_whatsapp(celular: str, contrato: "ContratoGerado") -> str:
    """Gera o link wa.me e atualiza o status do contrato para enviado_whatsapp.

    Retorna string vazia se o número for inválido — nesse caso o contrato
    NÃO é marcado como enviado, já que nada foi de fato encaminhado.
    """

    link = calcular_link_whatsapp(celular, contrato.get_tipo_display())
    if not link:
        return ""

    contrato.status_envio = "enviado_whatsapp"
    contrato.enviado_em = timezone.now()
    contrato.save(update_fields=["status_envio", "enviado_em", "atualizado_em"])

    return link
