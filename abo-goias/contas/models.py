"""Modelos da aplicacao de contas.

A autenticacao em si (login, logout, troca/reset de senha, perfil) usa o
``django.contrib.auth.models.User`` padrao, sem tabela propria. A unica
tabela deste app e :class:`SolicitacaoCadastro`, que registra pedidos de
acesso feitos por pessoas que ainda nao tem conta — o cadastro efetivo
nunca e automatico: um administrador revisa e aprova (ou rejeita) o
pedido, e so entao o ``User`` e criado. Isso preserva o controle de quem
entra num sistema que manipula dados de pacientes.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone


class SolicitacaoCadastro(models.Model):
    """Pedido de acesso feito por alguem que ainda nao tem conta no sistema.

    Fica ``PENDENTE`` ate um administrador aprovar (o que cria o ``User``
    correspondente e dispara o e-mail de definicao de senha) ou rejeitar.
    """

    class Status(models.TextChoices):
        PENDENTE = "PENDENTE", "Pendente"
        APROVADA = "APROVADA", "Aprovada"
        REJEITADA = "REJEITADA", "Rejeitada"

    nome_completo = models.CharField(max_length=150)
    email = models.EmailField()
    username = models.CharField(
        "usuário desejado",
        max_length=150,
        help_text="Nome de usuário que deseja usar para entrar no sistema.",
    )
    cargo = models.CharField(
        max_length=120,
        blank=True,
        help_text="Função/cargo na instituição — ajuda o administrador a decidir.",
    )
    justificativa = models.TextField(
        blank=True,
        help_text="Motivo do pedido de acesso (opcional).",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDENTE,
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    revisado_em = models.DateTimeField(null=True, blank=True)
    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="solicitacoes_revisadas",
    )
    usuario_criado = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="solicitacao_origem",
        help_text="Usuário criado quando esta solicitação foi aprovada.",
    )
    observacao_revisao = models.TextField(
        blank=True,
        help_text="Observação do administrador ao aprovar/rejeitar.",
    )

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "solicitação de cadastro"
        verbose_name_plural = "solicitações de cadastro"

    def __str__(self) -> str:
        return f"{self.nome_completo} ({self.username}) — {self.get_status_display()}"

    @property
    def pendente(self) -> bool:
        return self.status == self.Status.PENDENTE

    def aprovar(self, revisor=None, observacao: str = ""):
        """Cria o ``User`` correspondente e marca a solicitação como aprovada.

        Define uma senha aleatória (o usuário definirá a própria via o
        e-mail de redefinição enviado pelo chamador) e retorna o ``User``
        criado. Não faz nada se a solicitação não estiver pendente —
        retorna ``None`` nesse caso, para o chamador tratar como ignorada.
        """

        if not self.pendente:
            return None

        User = get_user_model()
        partes = self.nome_completo.split()
        first_name = partes[0] if partes else ""
        last_name = " ".join(partes[1:])[:150]

        usuario = User.objects.create_user(
            username=self.username,
            email=self.email,
            password=secrets.token_urlsafe(32),
            first_name=first_name[:150],
            last_name=last_name,
            is_active=True,
        )

        self.status = self.Status.APROVADA
        self.usuario_criado = usuario
        self.revisado_por = revisor
        self.revisado_em = timezone.now()
        if observacao:
            self.observacao_revisao = observacao
        self.save(
            update_fields=[
                "status",
                "usuario_criado",
                "revisado_por",
                "revisado_em",
                "observacao_revisao",
            ]
        )
        return usuario

    def rejeitar(self, revisor=None, observacao: str = "") -> bool:
        """Marca a solicitação como rejeitada. Retorna False se não estava pendente."""

        if not self.pendente:
            return False

        self.status = self.Status.REJEITADA
        self.revisado_por = revisor
        self.revisado_em = timezone.now()
        if observacao:
            self.observacao_revisao = observacao
        self.save(
            update_fields=[
                "status",
                "revisado_por",
                "revisado_em",
                "observacao_revisao",
            ]
        )
        return True
