"""Modelos de auditoria para geração de contratos e termos de consentimento."""

import secrets

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

STATUS_CARIMBO_TEMPO = [
    ("nao_solicitado", "Não solicitado"),
    ("concluido", "Concluído"),
    ("erro", "Erro ao solicitar"),
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
    carimbo_tempo = models.FileField(
        upload_to="contratos/carimbos/",
        blank=True,
        help_text=(
            "Token RFC 3161 (TSR) emitido por uma autoridade de carimbo do "
            "tempo sobre o hash do PDF assinado — evidência independente "
            "do relógio do servidor de que o documento já existia naquele "
            "momento."
        ),
    )
    carimbo_tempo_em = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Data/hora atestada pela autoridade de carimbo do tempo.",
    )
    carimbo_tempo_tsa = models.CharField(
        max_length=255,
        blank=True,
        help_text="URL da autoridade de carimbo do tempo que emitiu o token.",
    )
    status_carimbo_tempo = models.CharField(
        max_length=20,
        choices=STATUS_CARIMBO_TEMPO,
        default="nao_solicitado",
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


class TerminalAssinatura(ModeloBase):
    """Dispositivo dedicado (ex.: tablet da recepção) para o paciente
    assinar no local, sem precisar de QR Code/link no próprio celular.

    O ``token`` é a única credencial de acesso à URL pública do terminal
    — longo e aleatório (não um segredo assinado como o das sessões),
    porque o terminal fica com o navegador aberto indefinidamente, sem
    login. Deve ser tratado como sensível (não divulgado publicamente),
    da mesma forma que o link de assinatura de um paciente.
    """

    nome = models.CharField(max_length=100)
    token = models.CharField(max_length=64, unique=True, editable=False)

    class Meta:
        ordering = ["nome"]
        verbose_name = "terminal de assinatura"
        verbose_name_plural = "terminais de assinatura"

    def __str__(self) -> str:
        return self.nome

    def save(self, *args, **kwargs) -> None:
        if not self.token:
            self.token = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)


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
    entregue via QR Code ou espelhada em um TerminalAssinatura) em seu
    próprio dispositivo ou no terminal dedicado da clínica, e assina no
    canvas. Uma sessão permite apenas uma assinatura e expira
    automaticamente.
    """

    contrato = models.ForeignKey(
        ContratoGerado,
        on_delete=models.CASCADE,
        related_name="sessoes_assinatura",
    )
    terminal = models.ForeignKey(
        TerminalAssinatura,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sessoes",
        help_text="Terminal dedicado para o qual esta sessão foi enviada, se houver.",
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
    identidade_confirmada_em = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Momento em que a identidade de quem assina foi confirmada — "
            "obrigatório antes de liberar o canvas de assinatura."
        ),
    )
    identidade_confirmada_como = models.CharField(
        max_length=20,
        blank=True,
        choices=[
            ("paciente", "Paciente"),
            ("responsavel_legal", "Responsável legal"),
        ],
        help_text=(
            "Quem confirmou a identidade nesta sessão — o próprio paciente "
            "(data de nascimento) ou o responsável legal (CPF), quando o "
            "paciente é menor de idade. Fixado no momento da confirmação, "
            "independente de mudanças posteriores no cadastro."
        ),
    )
    tentativas_identidade = models.PositiveSmallIntegerField(default=0)
    identidade_presencial_confirmada_em = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Momento em que o colaborador (criado_por) atestou ter "
            "verificado presencialmente a identidade de quem vai assinar, "
            "antes de iniciar a sessão — relevante quando o dispositivo de "
            "assinatura é compartilhado (ex.: tablet da recepção)."
        ),
    )

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

    @property
    def identidade_confirmada(self) -> bool:
        return self.identidade_confirmada_em is not None

    @property
    def identidade_presencial_confirmada(self) -> bool:
        return self.identidade_presencial_confirmada_em is not None

    @property
    def assinado_por_responsavel(self) -> bool:
        return self.identidade_confirmada_como == "responsavel_legal"


TIPOS_EVENTO_CONTRATO = [
    ("sessao_criada", "Sessão de assinatura criada"),
    ("contrato_aberto", "Contrato aberto pelo paciente"),
    ("assinatura_concluida", "Assinatura concluída"),
    ("documento_assinado_salvo", "Documento assinado salvo"),
    ("sessao_expirada", "Sessão expirada"),
    ("sessao_cancelada", "Sessão cancelada"),
    ("identidade_confirmada", "Identidade do paciente confirmada"),
    (
        "identidade_bloqueada",
        "Verificação de identidade bloqueada por excesso de tentativas",
    ),
    (
        "identidade_presencial_confirmada",
        "Identidade confirmada presencialmente pelo colaborador",
    ),
    ("envio_dental_iniciado", "Envio ao Dental Office iniciado"),
    ("envio_dental_concluido", "Envio ao Dental Office concluído"),
    ("envio_dental_erro", "Erro no envio ao Dental Office"),
    ("whatsapp_iniciado", "Envio por WhatsApp iniciado"),
    ("whatsapp_concluido", "Envio por WhatsApp concluído"),
    ("whatsapp_erro", "Erro no envio por WhatsApp"),
    ("carimbo_tempo_iniciado", "Solicitação de carimbo de tempo iniciada"),
    ("carimbo_tempo_concluido", "Carimbo de tempo obtido"),
    ("carimbo_tempo_erro", "Erro ao obter carimbo de tempo"),
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
    tipo = models.CharField(max_length=40, choices=TIPOS_EVENTO_CONTRATO)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["criado_em", "pk"]
        verbose_name = "evento de contrato"
        verbose_name_plural = "eventos de contrato"

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} — contrato {self.contrato_id}"
