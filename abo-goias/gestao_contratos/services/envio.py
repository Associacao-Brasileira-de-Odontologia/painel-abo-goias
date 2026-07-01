"""Serviços de envio de contratos por e-mail e WhatsApp."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import quote

from django.core.mail import EmailMessage
from django.utils import timezone

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


def enviar_contrato_email(contrato: "ContratoGerado", destinatario: str) -> bool:
    """Envia o DOCX do contrato por e-mail e atualiza o status de envio.

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

    if contrato.arquivo:
        try:
            contrato.arquivo.open("rb")
            conteudo = contrato.arquivo.read()
            contrato.arquivo.close()
        except Exception as exc:
            logger.error(
                "enviar_contrato_email: erro ao ler arquivo (contrato_pk=%s): %s",
                contrato.pk,
                exc,
            )
            return False

        nome_arquivo = (
            f"termo_{contrato.tipo}_{paciente.nome.split()[0].lower()}"
            f"_{paciente.id_dental}.docx"
        )
        email.attach(
            nome_arquivo,
            conteudo,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    else:
        logger.warning(
            "enviar_contrato_email: contrato %s sem arquivo salvo.", contrato.pk
        )
        return False

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


def calcular_link_whatsapp(celular: str, tipo_display: str) -> str:
    """Calcula o link wa.me sem efeitos colaterais no banco de dados.

    Normaliza o número (remove não-dígitos, adiciona 55 se necessário).
    Retorna string vazia se o número for inválido.
    """

    digitos = re.sub(r"\D", "", celular)
    if not digitos:
        return ""
    if not digitos.startswith("55"):
        digitos = "55" + digitos
    mensagem = _MENSAGEM_WHATSAPP.format(tipo=tipo_display)
    return f"https://wa.me/{digitos}?text={quote(mensagem)}"


def gerar_link_whatsapp(celular: str, contrato: "ContratoGerado") -> str:
    """Gera o link wa.me e atualiza o status do contrato para enviado_whatsapp.

    Retorna string vazia se o número for inválido.
    """

    link = calcular_link_whatsapp(celular, contrato.get_tipo_display())

    contrato.status_envio = "enviado_whatsapp"
    contrato.enviado_em = timezone.now()
    contrato.save(update_fields=["status_envio", "enviado_em", "atualizado_em"])

    return link
