"""Modelos da aplicacao de gestao de material de laboratorio da ABO Goias.

Controla o fluxo de pedidos de servico a laboratorios externos: desde a
solicitacao do material, acompanhamento de status, registro de entrega e
fechamento financeiro. Tambem gerencia o fluxo auxiliar de moldagens e os
cadastros de laboratorios, equipes, alunos e pacientes sincronizados do
Dental Office.
"""

from __future__ import annotations

from datetime import date

from django.db import models

from gestao_cme.models import ModeloBase


class OrigemDados(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    DENTAL = "DENTAL", "Dental Office"


class Equipe(ModeloBase):
    """Equipe de coordenacao responsavel por um conjunto de laboratorios.

    Agrupa o nome da equipe e o coordenador responsavel com seu contato via
    WhatsApp. Usada para vincular laboratorios e pedidos de material a uma
    estrutura de gestao especifica.
    """

    nome = models.CharField(max_length=120)
    coordenador = models.CharField(max_length=150)
    whatsapp = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "equipe"
        verbose_name_plural = "equipes"

    def __str__(self) -> str:
        return self.nome


class Laboratorio(ModeloBase):
    """Laboratorio externo que presta servicos odontologicos para a ABO.

    Armazena contatos, CNPJ e as equipes de coordenacao que esse laboratorio
    atende. Ao menos uma equipe deve ser vinculada no cadastro.
    """

    nome = models.CharField(max_length=150)
    telefone = models.CharField(max_length=20, blank=True)
    whatsapp = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    cnpj = models.CharField(max_length=18, blank=True)
    equipes = models.ManyToManyField(
        Equipe,
        related_name="laboratorios",
        blank=True,
    )

    class Meta:
        ordering = ["nome"]
        verbose_name = "laboratorio"
        verbose_name_plural = "laboratorios"

    def __str__(self) -> str:
        return self.nome


class AlunoLab(ModeloBase):
    """Aluno sincronizado do Dental Office para uso nos pedidos de laboratorio.

    Contem apenas os dados necessarios para o fluxo de pedidos: nome e celular.
    O campo id_dental garante rastreabilidade com o sistema de origem.
    """

    nome = models.CharField(max_length=150)
    celular = models.CharField(max_length=20, blank=True)
    id_dental = models.CharField(max_length=50, unique=True)
    origem = models.CharField(
        max_length=20,
        choices=OrigemDados.choices,
        default=OrigemDados.DENTAL,
    )
    ultima_sincronizacao = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "aluno (lab)"
        verbose_name_plural = "alunos (lab)"

    def __str__(self) -> str:
        return self.nome


class Paciente(ModeloBase):
    """Paciente sincronizado do Dental Office.

    Armazena dados de contato, indicador de processo em aberto e previsao de
    retorno. Vinculado aos pedidos de material e moldagens para rastreio de
    quais pacientes possuem servicos em andamento.

    Os campos de CPF, RG, data de nascimento, endereco e responsavel sao
    preenchidos sob demanda via endpoint /customers/{id} ao gerar contratos.
    """

    nome = models.CharField(max_length=200)
    celular = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True, default="")
    id_dental = models.CharField(max_length=50, unique=True)
    processo_aberto = models.BooleanField(default=False)
    data_previsao_retorno = models.DateField(null=True, blank=True)
    origem = models.CharField(
        max_length=20,
        choices=OrigemDados.choices,
        default=OrigemDados.DENTAL,
    )
    ultima_sincronizacao = models.DateTimeField(null=True, blank=True)

    # Dados enriquecidos via GET /customers/{id} — usados na geração de contratos
    cpf = models.CharField(max_length=20, blank=True)
    rg = models.CharField(max_length=30, blank=True)
    data_nascimento = models.DateField(null=True, blank=True)
    endereco_logradouro = models.CharField(max_length=200, blank=True)
    endereco_numero = models.CharField(max_length=20, blank=True)
    endereco_complemento = models.CharField(max_length=100, blank=True)
    endereco_bairro = models.CharField(max_length=100, blank=True)
    endereco_cidade = models.CharField(max_length=100, blank=True)
    endereco_estado = models.CharField(max_length=2, blank=True)
    endereco_cep = models.CharField(max_length=10, blank=True)
    nome_responsavel = models.CharField(max_length=200, blank=True)
    cpf_responsavel = models.CharField(max_length=20, blank=True)

    # Campo local — o Dental Office não expõe convênio; nunca é sobrescrito
    # pela sincronização, apenas editado manualmente na tela de confirmação.
    convenio = models.CharField(max_length=120, blank=True)

    # Confirmação explícita dos dados antes da geração de contratos.
    # Limpa ao sincronizar com o Dental Office (dados mudaram → reconfirmar).
    dados_confirmados_em = models.DateTimeField(null=True, blank=True)
    dados_confirmados_por = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pacientes_confirmados",
    )

    @property
    def dados_contrato_completos(self) -> bool:
        """True se os dados mínimos para gerar um contrato estão preenchidos."""
        return bool(self.cpf or self.rg) and bool(self.endereco_cidade)

    @property
    def dados_confirmados(self) -> bool:
        """True se um colaborador já confirmou os dados do paciente."""
        return self.dados_confirmados_em is not None

    class Meta:
        ordering = ["nome"]
        verbose_name = "paciente"
        verbose_name_plural = "pacientes"

    def __str__(self) -> str:
        return self.nome


class PedidoMaterial(ModeloBase):
    """Pedido de servico de material enviado a um laboratorio externo.

    Registra o ciclo completo: desde a abertura do pedido, envio ao laboratorio,
    devolucao do material finalizado e encerramento financeiro. O status e
    calculado automaticamente com base nos campos de data e entrega.

    Fluxo de status:
        EM_DIA      -> pedido aberto, material nao enviado, dentro do prazo
        A_CONFIRMAR -> material enviado ao lab, aguardando devolucao, no prazo
        ATRASADO    -> prazo de entrega vencido sem devolucao registrada
        CONCLUIDO   -> material devolvido e faturamento completo
    """

    class Status(models.TextChoices):
        EM_DIA = "EM_DIA", "Em dia"
        A_CONFIRMAR = "A_CONFIRMAR", "A confirmar"
        ATRASADO = "ATRASADO", "Atrasado"
        CONCLUIDO = "CONCLUIDO", "Concluido"

    paciente = models.ForeignKey(
        Paciente,
        on_delete=models.PROTECT,
        related_name="pedidos",
    )
    aluno = models.ForeignKey(
        AlunoLab,
        on_delete=models.PROTECT,
        related_name="pedidos",
    )
    laboratorio = models.ForeignKey(
        Laboratorio,
        on_delete=models.PROTECT,
        related_name="pedidos",
    )
    equipe = models.ForeignKey(
        Equipe,
        on_delete=models.PROTECT,
        related_name="pedidos",
    )
    previsao_entrega = models.DateField()
    descricao_servico = models.TextField()

    data_envio = models.DateField(
        null=True,
        blank=True,
        help_text="Data em que o material foi enviado ao laboratorio.",
    )

    entregue = models.BooleanField(default=False)
    data_entrega = models.DateField(null=True, blank=True)

    faturado_paciente = models.BooleanField(default=False)
    faturado_lab = models.BooleanField(default=False)
    numero_nota_fiscal = models.CharField(max_length=30, blank=True)
    data_vencimento = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.EM_DIA,
        editable=False,
    )

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "pedido de material"
        verbose_name_plural = "pedidos de material"

    def __str__(self) -> str:
        return f"Pedido #{self.pk} - {self.paciente} ({self.laboratorio})"

    def calcular_status(self) -> str:
        hoje = date.today()
        if self.entregue and self.faturado_paciente and self.faturado_lab:
            return self.Status.CONCLUIDO
        if not self.entregue and hoje > self.previsao_entrega:
            return self.Status.ATRASADO
        if self.data_envio and not self.entregue:
            return self.Status.A_CONFIRMAR
        return self.Status.EM_DIA

    def save(self, *args, **kwargs):
        if self.previsao_entrega:
            self.status = self.calcular_status()
        super().save(*args, **kwargs)


class Moldagem(ModeloBase):
    """Pedido de moldagem registrado antes do encaminhamento ao laboratorio.

    Representa a etapa inicial em que o aluno realiza a moldagem do paciente.
    Pode ser convertida em PedidoMaterial pelo botao de encaminhamento, que
    pre-preenche o formulario com os dados do paciente e do aluno.
    """

    paciente = models.ForeignKey(
        Paciente,
        on_delete=models.PROTECT,
        related_name="moldagens",
    )
    aluno = models.ForeignKey(
        AlunoLab,
        on_delete=models.PROTECT,
        related_name="moldagens",
    )
    faturado = models.BooleanField(
        default=False,
        help_text="Paciente ja realizou o pagamento pelo procedimento.",
    )
    entregue = models.BooleanField(
        default=False,
        help_text="Moldagem ja foi entregue ao laboratorio.",
    )
    pedido_material = models.OneToOneField(
        PedidoMaterial,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moldagem_origem",
        help_text="Pedido de material gerado a partir desta moldagem.",
    )

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "moldagem"
        verbose_name_plural = "moldagens"

    def __str__(self) -> str:
        return f"Moldagem #{self.pk} - {self.paciente} / {self.aluno}"

    @property
    def convertida(self) -> bool:
        return self.pedido_material_id is not None


class RegistroSync(ModeloBase):
    """Auditoria de cada execução de sincronização com o Dental Office.

    Registra quando a sync ocorreu, quem disparou, quantos registros foram
    afetados e se houve erro. Usado para exibir histórico na interface e
    diagnosticar falhas na sincronização agendada.
    """

    class Tipo(models.TextChoices):
        COMPLETA = "COMPLETA", "Completa (manual)"
        AGENDADA = "AGENDADA", "Agendada (automática)"

    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.COMPLETA)
    sucesso = models.BooleanField(null=True, blank=True)
    erro = models.TextField(blank=True)
    pacientes_criados = models.PositiveIntegerField(default=0)
    pacientes_atualizados = models.PositiveIntegerField(default=0)
    alunos_criados = models.PositiveIntegerField(default=0)
    alunos_atualizados = models.PositiveIntegerField(default=0)
    disparado_por = models.CharField(max_length=50, blank=True)
    duracao_segundos = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "registro de sincronização"
        verbose_name_plural = "registros de sincronização"

    def __str__(self) -> str:
        status = "OK" if self.sucesso else "ERRO"
        return f"Sync {self.criado_em:%d/%m/%Y %H:%M} [{status}]"
