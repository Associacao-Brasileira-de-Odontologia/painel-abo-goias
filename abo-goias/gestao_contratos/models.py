"""Modelos de auditoria para geração de contratos e termos de consentimento."""

from django.contrib.auth.models import User
from django.db import models

from gestao_cme.models import ModeloBase

TIPOS_CONTRATO = [
    ("bichectomia", "Bichectomia"),
    ("toxina_botulinica", "Toxina Botulínica"),
    ("odontopediatria", "Odontopediatria"),
    ("endodontia", "Endodontia"),
]


class ContratoGerado(ModeloBase):
    """Registro de auditoria de cada contrato gerado para um paciente.

    Não armazena o arquivo em si (gerado sob demanda a cada download),
    apenas os metadados necessários para rastrear quem gerou o quê e quando.
    """

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
    gerado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contratos_gerados",
    )

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "contrato gerado"
        verbose_name_plural = "contratos gerados"

    def __str__(self) -> str:
        return (
            f"{self.get_tipo_display()} — {self.paciente.nome}"
            f" ({self.criado_em:%d/%m/%Y})"
        )
