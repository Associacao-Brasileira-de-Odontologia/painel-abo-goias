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
