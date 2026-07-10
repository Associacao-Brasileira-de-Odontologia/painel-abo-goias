"""E-mails transacionais do fluxo de solicitação de acesso.

A aprovação já dispara e-mail reaproveitando o fluxo de redefinição de
senha (ver contas/admin.py::_enviar_email_definir_senha) — este módulo
cobre as outras duas pontas: avisar o administrador quando chega um
pedido novo, e avisar quem pediu quando o pedido é rejeitado.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.urls import reverse

from .models import SolicitacaoCadastro

logger = logging.getLogger(__name__)


def notificar_admin_nova_solicitacao(
    request: HttpRequest, solicitacao: SolicitacaoCadastro
) -> None:
    """Avisa os administradores configurados (DJANGO_ADMINS_EMAIL) sobre um
    novo pedido de acesso pendente de revisão.

    Chamada a partir da tela pública de solicitação de acesso — uma falha
    aqui não pode derrubar o pedido do usuário, que já foi salvo antes
    desta chamada. Por isso o erro só é logado, nunca propagado.
    """

    destinatarios = [email for _, email in settings.ADMINS]
    if not destinatarios:
        return

    link_revisao = request.build_absolute_uri(
        reverse("admin:contas_solicitacaocadastro_change", args=[solicitacao.pk])
    )
    contexto = {"solicitacao": solicitacao, "link_revisao": link_revisao}

    try:
        assunto = render_to_string(
            "auth/solicitacao_nova_subject.txt", contexto
        ).strip()
        corpo = render_to_string("auth/solicitacao_nova_email.html", contexto)
        send_mail(assunto, corpo, settings.DEFAULT_FROM_EMAIL, destinatarios)
    except Exception:
        logger.exception(
            "notificar_admin_nova_solicitacao: falha ao enviar e-mail "
            "(solicitacao=%s)",
            solicitacao.pk,
        )


def notificar_usuario_rejeitado(solicitacao: SolicitacaoCadastro) -> None:
    """Avisa por e-mail quem solicitou acesso que o pedido foi rejeitado.

    Chamada a partir da ação "Rejeitar" no Django Admin (contexto de
    staff autenticado) — ao contrário da notificação ao administrador,
    aqui uma falha de envio propaga normalmente, mesmo padrão já usado
    por _enviar_email_definir_senha na aprovação: o staff vê o erro na
    hora e sabe que precisa checar a configuração de e-mail.
    """

    contexto = {"solicitacao": solicitacao}
    assunto = render_to_string(
        "auth/solicitacao_rejeitada_subject.txt", contexto
    ).strip()
    corpo = render_to_string("auth/solicitacao_rejeitada_email.html", contexto)
    send_mail(assunto, corpo, settings.DEFAULT_FROM_EMAIL, [solicitacao.email])
