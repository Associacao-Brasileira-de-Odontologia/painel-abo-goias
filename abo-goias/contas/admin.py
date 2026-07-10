"""Administracao da aplicacao de contas.

A conta em si e o ``django.contrib.auth.models.User`` padrao, ja
administravel pelo admin nativo. Este modulo registra apenas
:class:`~contas.models.SolicitacaoCadastro`, com acoes para o
administrador aprovar (criando o usuario e enviando o e-mail de definicao
de senha) ou rejeitar pedidos de acesso.
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.contrib.auth.forms import PasswordResetForm
from django.http import HttpRequest

from .emails import notificar_usuario_rejeitado
from .models import SolicitacaoCadastro


def _enviar_email_definir_senha(request: HttpRequest, email: str) -> None:
    """Dispara o e-mail de definição de senha reutilizando o fluxo de reset.

    Usa os mesmos templates do 'esqueci minha senha' — o usuário recém-criado
    tem senha aleatória e define a própria pelo link recebido.
    """

    form = PasswordResetForm({"email": email})
    if form.is_valid():
        form.save(
            request=request,
            use_https=request.is_secure(),
            email_template_name="auth/password_reset_email.html",
            subject_template_name="auth/password_reset_subject.txt",
        )


@admin.register(SolicitacaoCadastro)
class SolicitacaoCadastroAdmin(admin.ModelAdmin):
    list_display = (
        "nome_completo",
        "username",
        "email",
        "cargo",
        "status",
        "criado_em",
    )
    list_filter = ("status", "criado_em")
    search_fields = ("nome_completo", "username", "email", "cargo")
    readonly_fields = (
        "criado_em",
        "revisado_em",
        "revisado_por",
        "usuario_criado",
    )
    actions = ("aprovar_solicitacoes", "rejeitar_solicitacoes")

    @admin.action(description="Aprovar solicitações selecionadas (cria o usuário)")
    def aprovar_solicitacoes(self, request: HttpRequest, queryset) -> None:
        aprovadas = ignoradas = 0
        for solicitacao in queryset:
            usuario = solicitacao.aprovar(revisor=request.user)
            if usuario is None:
                ignoradas += 1
                continue
            _enviar_email_definir_senha(request, usuario.email)
            aprovadas += 1

        if aprovadas:
            self.message_user(
                request,
                f"{aprovadas} solicitação(ões) aprovada(s) — usuário criado e "
                "e-mail de definição de senha enviado.",
                messages.SUCCESS,
            )
        if ignoradas:
            self.message_user(
                request,
                f"{ignoradas} solicitação(ões) ignorada(s) (não estavam pendentes).",
                messages.WARNING,
            )

    @admin.action(description="Rejeitar solicitações selecionadas")
    def rejeitar_solicitacoes(self, request: HttpRequest, queryset) -> None:
        rejeitadas = ignoradas = 0
        for solicitacao in queryset:
            if solicitacao.rejeitar(revisor=request.user):
                notificar_usuario_rejeitado(solicitacao)
                rejeitadas += 1
            else:
                ignoradas += 1

        if rejeitadas:
            self.message_user(
                request,
                f"{rejeitadas} solicitação(ões) rejeitada(s) — e-mail enviado "
                "a quem solicitou.",
                messages.SUCCESS,
            )
        if ignoradas:
            self.message_user(
                request,
                f"{ignoradas} solicitação(ões) ignorada(s) (não estavam pendentes).",
                messages.WARNING,
            )
