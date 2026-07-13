"""Administracao da aplicacao de contas.

A conta em si e o ``django.contrib.auth.models.User`` padrao, ja
administravel pelo admin nativo. Este modulo registra apenas
:class:`~contas.models.SolicitacaoCadastro`, com acoes para o
administrador aprovar (criando o usuario e enviando o e-mail de boas-vindas)
ou rejeitar pedidos de acesso, alem da tela de convite direto ("Convidar
usuario"), que cria e aprova numa unica acao — o caminho inverso da
solicitacao publica.
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.contrib.auth.forms import PasswordResetForm
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import path

from .emails import notificar_usuario_rejeitado
from .forms import ConviteUsuarioForm
from .models import SolicitacaoCadastro


def _enviar_email_definir_senha(request: HttpRequest, email: str) -> None:
    """Dispara o e-mail de boas-vindas com o link de definição de senha.

    Reutiliza o mecanismo do fluxo de reset (PasswordResetForm gera o link
    seguro uidb64+token), mas com templates próprios de conta criada — o
    texto do reset ("recebemos uma solicitação para redefinir a senha")
    confundia quem nunca teve senha nem pediu redefinição.
    """

    form = PasswordResetForm({"email": email})
    if form.is_valid():
        form.save(
            request=request,
            use_https=request.is_secure(),
            email_template_name="auth/conta_criada_email.html",
            subject_template_name="auth/conta_criada_subject.txt",
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
    change_list_template = "admin/contas/solicitacaocadastro/change_list.html"

    def get_urls(self):
        return [
            path(
                "convidar/",
                self.admin_site.admin_view(self.convidar_view),
                name="contas_solicitacaocadastro_convidar",
            ),
            *super().get_urls(),
        ]

    def convidar_view(self, request: HttpRequest) -> HttpResponse:
        """Convite direto: cria a solicitação já aprovada numa única ação.

        Caminho inverso da solicitação pública — o administrador preenche
        nome, e-mail e usuário; o sistema cria o ``User`` (via
        ``SolicitacaoCadastro.aprovar()``, preservando a trilha de quem
        convidou/quando) e envia o mesmo e-mail de boas-vindas com o link
        de definição de senha usado na aprovação.
        """

        if not self.has_add_permission(request):
            raise PermissionDenied

        if request.method == "POST":
            form = ConviteUsuarioForm(request.POST)
            if form.is_valid():
                solicitacao = form.save()
                usuario = solicitacao.aprovar(
                    revisor=request.user,
                    observacao="Convite direto pelo administrador.",
                )
                _enviar_email_definir_senha(request, usuario.email)
                self.message_user(
                    request,
                    f'Usuário "{usuario.username}" convidado — e-mail de '
                    f"boas-vindas enviado para {usuario.email}.",
                    messages.SUCCESS,
                )
                return redirect("admin:contas_solicitacaocadastro_changelist")
        else:
            form = ConviteUsuarioForm()

        contexto = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Convidar usuário",
            "form": form,
        }
        return render(
            request, "admin/contas/solicitacaocadastro/convidar.html", contexto
        )

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
