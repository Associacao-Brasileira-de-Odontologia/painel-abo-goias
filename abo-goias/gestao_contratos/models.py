"""Modelos de auditoria para geração de contratos e termos de consentimento."""

from django.contrib.auth.models import User
from django.db import models

from gestao_cme.models import ModeloBase

TIPOS_CONTRATO = [
    ("modelo_1", "Modelo 1"),
    ("modelo_2", "Modelo 2"),
    ("modelo_3", "Modelo 3"),
    ("modelo_4", "Modelo 4"),
]

STATUS_CONTRATO = [
    ("gerado", "Gerado"),
    ("aguardando_assinatura", "Aguardando assinatura"),
    ("assinado", "Assinado"),
    ("cancelado", "Cancelado"),
]

STATUS_ENVIO_DENTAL = [
    ("nao_enviado", "Não enviado"),
    ("enviado", "Enviado"),
    ("erro", "Erro no envio"),
]

STATUS_ENVIO = [
    ("nao_enviado", "Não enviado"),
    ("enviado_email", "Enviado por e-mail"),
    ("enviado_whatsapp", "Enviado por WhatsApp"),
]


class ContratoGerado(ModeloBase):
    """Registro de auditoria de cada contrato gerado para um paciente."""

    paciente = models.ForeignKey(
        "gestao_lab.Paciente",
        on_delete=models.PROTECT,
        related_name="contratos",
    )
    tipo = models.CharField(
        max_length=30,
        choices=TIPOS_CONTRATO,
    )
    observacoes_clinicas = models.TextField(blank=True)
    profissional_nome = models.CharField(max_length=200, blank=True)
    profissional_cro = models.CharField(max_length=30, blank=True)
    local_assinatura = models.CharField(max_length=100, default="Goiânia - GO")
    arquivo = models.FileField(upload_to="contratos/docx/", blank=True)
    arquivo_pdf = models.FileField(upload_to="contratos/pdf/", blank=True)
    arquivo_pdf_assinado = models.FileField(
        upload_to="contratos/assinados/",
        blank=True,
        help_text="PDF definitivo com a assinatura do paciente mesclada.",
    )
    status = models.CharField(
        max_length=25,
        choices=STATUS_CONTRATO,
        default="gerado",
    )
    versao = models.PositiveIntegerField(
        default=1,
        help_text="Sequencial por paciente e tipo de contrato.",
    )
    hash_sha256 = models.CharField(
        max_length=64,
        blank=True,
        help_text="SHA-256 do PDF gerado; recalculado após a assinatura.",
    )
    status_envio = models.CharField(
        max_length=25,
        choices=STATUS_ENVIO,
        default="nao_enviado",
    )
    enviado_em = models.DateTimeField(null=True, blank=True)
    gerado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contratos_gerados",
    )
    status_envio_dental = models.CharField(
        max_length=20,
        choices=STATUS_ENVIO_DENTAL,
        default="nao_enviado",
    )
    enviado_dental_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "contrato gerado"
        verbose_name_plural = "contratos gerados"

    def __str__(self) -> str:
        return (
            f"{self.get_tipo_display()} — {self.paciente.nome}"
            f" ({self.criado_em:%d/%m/%Y})"
        )


STATUS_SESSAO_ASSINATURA = [
    ("pendente", "Pendente"),
    ("aberta", "Aberta pelo paciente"),
    ("assinada", "Assinada"),
    ("expirada", "Expirada"),
    ("cancelada", "Cancelada"),
]


class SessaoAssinatura(ModeloBase):
    """Sessão temporária de assinatura remota de um contrato.

    O paciente acessa a URL pública (token assinado criptograficamente,
    entregue via QR Code) em seu próprio dispositivo e assina no canvas.
    Uma sessão permite apenas uma assinatura e expira automaticamente.
    """

    contrato = models.ForeignKey(
        ContratoGerado,
        on_delete=models.CASCADE,
        related_name="sessoes_assinatura",
    )
    status = models.CharField(
        max_length=15,
        choices=STATUS_SESSAO_ASSINATURA,
        default="pendente",
    )
    expira_em = models.DateTimeField()
    criado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sessoes_assinatura_criadas",
    )
    aberta_em = models.DateTimeField(null=True, blank=True)
    assinada_em = models.DateTimeField(null=True, blank=True)
    ip_assinatura = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    assinatura_imagem = models.FileField(upload_to="assinaturas/", blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "sessão de assinatura"
        verbose_name_plural = "sessões de assinatura"

    def __str__(self) -> str:
        return f"Sessão #{self.pk} — {self.contrato} [{self.status}]"

    @property
    def ativa(self) -> bool:
        """True se a sessão ainda aceita assinatura (pendente/aberta e no prazo)."""
        from django.utils import timezone

        return self.status in ("pendente", "aberta") and timezone.now() < (
            self.expira_em
        )


TIPOS_EVENTO_CONTRATO = [
    ("sessao_criada", "Sessão de assinatura criada"),
    ("contrato_aberto", "Contrato aberto pelo paciente"),
    ("assinatura_concluida", "Assinatura concluída"),
    ("documento_assinado_salvo", "Documento assinado salvo"),
    ("sessao_expirada", "Sessão expirada"),
    ("sessao_cancelada", "Sessão cancelada"),
    ("envio_dental_iniciado", "Envio ao Dental Office iniciado"),
    ("envio_dental_concluido", "Envio ao Dental Office concluído"),
    ("envio_dental_erro", "Erro no envio ao Dental Office"),
]


class EventoContrato(ModeloBase):
    """Trilha de eventos do ciclo de vida do contrato.

    Alimenta a atualização de status na interface (polling/WebSocket) e
    serve como registro de auditoria: cada transição relevante fica
    gravada com carimbo de tempo e dados contextuais em payload.
    """

    contrato = models.ForeignKey(
        ContratoGerado,
        on_delete=models.CASCADE,
        related_name="eventos",
    )
    sessao = models.ForeignKey(
        SessaoAssinatura,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eventos",
    )
    tipo = models.CharField(max_length=30, choices=TIPOS_EVENTO_CONTRATO)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["criado_em", "pk"]
        verbose_name = "evento de contrato"
        verbose_name_plural = "eventos de contrato"

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} — contrato {self.contrato_id}"
