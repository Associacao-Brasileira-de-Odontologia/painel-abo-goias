"""Modelos da aplicacao de gestao da CME da ABO Goias.

Este modulo concentra os cadastros academicos, materiais, kits, abrigos,
estoques, emprestimos e movimentacoes usados pelo painel operacional.
As docstrings das classes descrevem o papel de cada modelo no fluxo do
sistema e servem como referencia rapida para manutencao e integracoes.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .utils import normalizar_texto


class NomeNormalizadoMixin(models.Model):
    """Mantem uma copia do nome sem acento e em caixa alta, para busca.

    O campo e derivado: nunca e editado a mao, so recalculado a partir de
    ``nome`` a cada save. As buscas por nome usam este campo para que "Honorio"
    e "Honorio" (com acento) sejam encontrados pelo mesmo termo digitado.
    """

    nome_normalizado = models.CharField(
        max_length=200,
        blank=True,
        db_index=True,
        editable=False,
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.nome_normalizado = normalizar_texto(self.nome)
        # Quando o chamador restringe os campos gravados (ex.: update_or_create
        # da sincronizacao), o derivado precisa acompanhar o campo de origem.
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "nome" in update_fields:
            kwargs["update_fields"] = [*update_fields, "nome_normalizado"]
        super().save(*args, **kwargs)


class ModeloBase(models.Model):
    """Base abstrata com campos comuns de auditoria e ativacao.

    Deve ser herdada por modelos de dominio que precisam registrar data de
    criacao, data da ultima atualizacao e status ativo/inativo sem duplicar
    esses campos em cada tabela.
    """

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        abstract = True


class OrigemDados(models.TextChoices):
    """Origem de um registro importado ou criado no painel.

    A escolha ajuda a separar dados manuais, dados sincronizados do Eduq,
    dados migrados de planilhas legadas e registros de exemplo usados para
    demonstracao ou testes operacionais.
    """

    MANUAL = "MANUAL", "Manual"
    EDUQ = "EDUQ", "Eduq"
    LEGADO = "LEGADO", "Legado"
    EXEMPLO = "EXEMPLO", "Exemplo"


class Turma(NomeNormalizadoMixin, ModeloBase):
    """Turma academica disponivel para consulta e geracao de identificadores.

    Reune codigo externo, nome, curso, periodo e informacoes de sincronizacao.
    E usada para agrupar alunos da pos-graduacao e alimentar tanto a gestao da
    CME quanto a aplicacao de identificadores.
    """

    nome = models.CharField(max_length=120)
    codigo = models.CharField(max_length=30, unique=True)
    curso = models.CharField(max_length=120, blank=True)
    data_inicio = models.DateField(null=True, blank=True)
    data_fim = models.DateField(null=True, blank=True)
    observacoes = models.TextField(blank=True)
    origem = models.CharField(
        max_length=20,
        choices=OrigemDados.choices,
        default=OrigemDados.MANUAL,
    )
    ultima_sincronizacao = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "turma"
        verbose_name_plural = "turmas"

    def __str__(self) -> str:
        """Retorna uma identificacao curta com codigo e nome da turma."""

        return f"{self.codigo} - {self.nome}"


class Aluno(NomeNormalizadoMixin, ModeloBase):
    """Aluno vinculado a uma turma e aos fluxos de retirada de materiais.

    Guarda dados academicos, contato, localizacao e origem da informacao. O
    cadastro e usado para emprestimos, historico de movimentacoes e montagem
    de arquivos de identificadores por turma.
    """

    nome = models.CharField(max_length=150)
    matricula = models.CharField(max_length=40, unique=True)
    cpf = models.CharField(max_length=14, null=True, blank=True)
    email = models.EmailField(blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    cidade = models.CharField(max_length=120, blank=True)
    uf = models.CharField(max_length=20, blank=True)
    origem = models.CharField(
        max_length=20,
        choices=OrigemDados.choices,
        default=OrigemDados.MANUAL,
    )
    ultima_sincronizacao = models.DateTimeField(null=True, blank=True)
    turma = models.ForeignKey(
        Turma,
        on_delete=models.PROTECT,
        related_name="alunos",
        null=True,
        blank=True,
    )
    abrigo = models.ForeignKey(
        "Abrigo",
        on_delete=models.SET_NULL,
        related_name="alunos",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["nome"]
        verbose_name = "aluno"
        verbose_name_plural = "alunos"

    def __str__(self) -> str:
        """Retorna o nome do aluno para telas administrativas e seletores."""

        return self.nome


class Material(ModeloBase):
    """Item fisico controlado pela CME para emprestimo ou composicao de kits.

    Representa materiais cadastrados manualmente, sincronizados ou migrados de
    planilhas. Mantem codigo, identificacao visual, disponibilidade, unidade de
    medida e quantidade minima para apoiar estoque, kits e movimentacoes.
    """

    class UnidadeMedida(models.TextChoices):
        """Unidades aceitas para contagem operacional de materiais."""

        UNIDADE = "UN", "Unidade"
        CAIXA = "CX", "Caixa"
        PACOTE = "PC", "Pacote"
        FRASCO = "FR", "Frasco"
        PAR = "PAR", "Par"

    nome = models.CharField(max_length=120)
    codigo = models.CharField(max_length=40, unique=True)
    descricao = models.TextField(blank=True)
    identificacao = models.CharField(max_length=30, blank=True)
    rotulo_kit = models.CharField(max_length=120, blank=True)
    disponivel = models.BooleanField(default=True)
    unidade_medida = models.CharField(
        max_length=5,
        choices=UnidadeMedida.choices,
        default=UnidadeMedida.UNIDADE,
    )
    quantidade_minima = models.PositiveIntegerField(default=0)
    origem = models.CharField(
        max_length=20,
        choices=OrigemDados.choices,
        default=OrigemDados.MANUAL,
    )
    ultima_sincronizacao = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "material"
        verbose_name_plural = "materiais"

    def __str__(self) -> str:
        """Retorna o nome do material em listagens e relacionamentos."""

        return self.nome


class Kit(ModeloBase):
    """Conjunto de materiais preparado para emprestimos e controle operacional.

    O kit organiza varios materiais por meio de KitMaterial, mantendo codigo,
    nome, descricao e quantidade disponivel. E usado para agrupar itens comuns
    em fluxos de emprestimo e exibicao no painel da CME.
    """

    nome = models.CharField(max_length=120)
    codigo = models.CharField(max_length=40, unique=True)
    descricao = models.TextField(blank=True)
    quantidade = models.PositiveIntegerField(default=0)
    origem = models.CharField(
        max_length=20,
        choices=OrigemDados.choices,
        default=OrigemDados.MANUAL,
    )
    ultima_sincronizacao = models.DateTimeField(null=True, blank=True)
    materiais = models.ManyToManyField(
        Material,
        through="KitMaterial",
        related_name="kits",
        blank=True,
    )

    class Meta:
        ordering = ["nome"]
        verbose_name = "kit"
        verbose_name_plural = "kits"

    def __str__(self) -> str:
        """Retorna o nome do kit para exibicao administrativa."""

        return self.nome


class KitMaterial(models.Model):
    """Relacionamento entre um kit e os materiais que o compoem.

    Define a quantidade de cada material dentro de um kit e impede duplicidade
    do mesmo material no mesmo kit por meio de restricao unica.
    """

    kit = models.ForeignKey(Kit, on_delete=models.CASCADE, related_name="itens")
    material = models.ForeignKey(Material, on_delete=models.PROTECT)
    quantidade = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["kit", "material"]
        constraints = [
            models.UniqueConstraint(
                fields=["kit", "material"],
                name="kit_material_unico",
            ),
        ]
        verbose_name = "material do kit"
        verbose_name_plural = "materiais do kit"

    def __str__(self) -> str:
        """Retorna a quantidade seguida do material vinculado ao kit."""

        return f"{self.quantidade} x {self.material}"


class Armario(ModeloBase):
    """Local fisico de armazenamento usado para organizar estoque de materiais.

    Cada armario possui identificacao unica, localizacao e descricao opcional.
    Os materiais armazenados nele sao controlados pelo modelo EstoqueArmario.
    """

    identificacao = models.CharField(max_length=60, unique=True)
    localizacao = models.CharField(max_length=120, blank=True)
    descricao = models.TextField(blank=True)
    materiais = models.ManyToManyField(
        Material,
        through="EstoqueArmario",
        related_name="armarios",
        blank=True,
    )

    class Meta:
        ordering = ["identificacao"]
        verbose_name = "armario"
        verbose_name_plural = "armarios"

    def __str__(self) -> str:
        """Retorna a identificacao unica do armario."""

        return self.identificacao


class Abrigo(ModeloBase):
    """Espaco individual de guarda acompanhado pela gestao da CME.

    Registra o identificador do abrigo e seu estado de ocupacao. Os registros
    podem vir de cadastro manual, migracao legada ou sincronizacao operacional.
    """

    identificador = models.CharField(max_length=30, unique=True)
    ocupado = models.BooleanField(default=False)
    origem = models.CharField(
        max_length=20,
        choices=OrigemDados.choices,
        default=OrigemDados.MANUAL,
    )
    ultima_sincronizacao = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["identificador"]
        verbose_name = "abrigo"
        verbose_name_plural = "abrigos"

    def __str__(self) -> str:
        """Retorna o identificador do abrigo."""

        return self.identificador


class EstoqueArmario(models.Model):
    """Quantidade de um material armazenada em um armario especifico.

    Funciona como tabela intermediaria entre Armario e Material, com quantidade
    e observacoes. A restricao unica garante somente um saldo por material em
    cada armario.
    """

    armario = models.ForeignKey(
        Armario, on_delete=models.CASCADE, related_name="estoques"
    )
    material = models.ForeignKey(Material, on_delete=models.PROTECT)
    quantidade = models.PositiveIntegerField(default=0)
    observacoes = models.TextField(blank=True)

    class Meta:
        ordering = ["armario", "material"]
        constraints = [
            models.UniqueConstraint(
                fields=["armario", "material"],
                name="estoque_armario_material_unico",
            ),
        ]
        verbose_name = "estoque do armario"
        verbose_name_plural = "estoques dos armarios"

    def __str__(self) -> str:
        """Retorna armario, material e saldo disponivel do estoque."""

        return f"{self.armario} - {self.material}: {self.quantidade}"


class Emprestimo(ModeloBase):
    """Registro principal de emprestimo de kit ou materiais para um aluno.

    Armazena aluno, kit opcional, responsavel, datas relevantes, status e
    observacoes. Os materiais efetivamente emprestados ficam detalhados em
    ItemEmprestimo para permitir controle por item e por armario.
    """

    class Status(models.TextChoices):
        """Estados possiveis do ciclo de vida de um emprestimo."""

        EMPRESTADO = "EMPRESTADO", "Emprestado"
        DEVOLVIDO = "DEVOLVIDO", "Devolvido"
        ATRASADO = "ATRASADO", "Atrasado"

    aluno = models.ForeignKey(
        Aluno,
        on_delete=models.PROTECT,
        related_name="emprestimos",
    )
    kit = models.ForeignKey(
        Kit,
        on_delete=models.PROTECT,
        related_name="emprestimos",
        null=True,
        blank=True,
    )
    coordenador = models.CharField(max_length=120, blank=True)
    coordenador_usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="emprestimos_realizados",
        null=True,
        blank=True,
    )
    data_emprestimo = models.DateTimeField(default=timezone.now)
    data_prevista_devolucao = models.DateField(null=True, blank=True)
    data_devolucao = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.EMPRESTADO,
    )
    observacoes = models.TextField(blank=True)

    class Meta:
        ordering = ["-data_emprestimo", "-id"]
        verbose_name = "emprestimo"
        verbose_name_plural = "emprestimos"

    def __str__(self) -> str:
        """Retorna uma descricao curta com o numero e o aluno do emprestimo."""

        return f"Emprestimo #{self.pk} - {self.aluno}"


class ItemEmprestimo(models.Model):
    """Material especifico incluido em um emprestimo.

    Detalha o material retirado, o armario de origem quando informado e a
    quantidade emprestada. A restricao unica evita repetir o mesmo conjunto de
    emprestimo, material e armario.
    """

    emprestimo = models.ForeignKey(
        Emprestimo,
        on_delete=models.CASCADE,
        related_name="itens",
    )
    material = models.ForeignKey(Material, on_delete=models.PROTECT)
    armario = models.ForeignKey(
        Armario,
        on_delete=models.PROTECT,
        related_name="itens_emprestados",
        null=True,
        blank=True,
    )
    quantidade = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["emprestimo", "material"]
        constraints = [
            models.UniqueConstraint(
                fields=["emprestimo", "material", "armario"],
                name="item_emprestimo_material_armario_unico",
            ),
        ]
        verbose_name = "item do emprestimo"
        verbose_name_plural = "itens do emprestimo"

    def __str__(self) -> str:
        """Retorna a quantidade seguida do material emprestado."""

        return f"{self.quantidade} x {self.material}"


class Movimentacao(ModeloBase):
    """Historico de entradas e saidas de materiais importado ou registrado.

    Mantem a data, tipo de movimentacao, aluno, turma, material, codigo do
    pacote e arquivo de origem. Tambem preserva campos textuais do legado para
    consultas mesmo quando a vinculacao com cadastros normalizados nao existe.

    Um pacote registrado pelo painel gera DOIS registros ao longo da vida: a
    ENTRADA (material entregue para esterilizacao) e, quando o aluno retira, a
    SAIDA. ``entrada_origem`` liga a SAIDA a sua ENTRADA, permitindo exibir o
    ciclo completo em uma unica linha (ver ``views.home``).

    Esse vinculo e explicito de proposito. Parear pelo ``pacote_codigo`` nao e
    confiavel:
      - o campo NAO tem constraint de unicidade e a geracao usa
        ``max(codigos numericos)+n`` sem lock (ver B-07 na auditoria), entao
        duas entradas concorrentes podem repetir o codigo;
      - nos dados LEGADO o ``pacote_codigo`` e o **codigo do material** (ver
        services/migracao_legado.py, que faz
        ``materiais_por_codigo.get(pacote_codigo)``), repetido em varios alunos
        e datas — parear por ele cruzaria registros de pessoas diferentes.
    Por isso o legado permanece com ``entrada_origem`` nulo: sem um vinculo real
    no dado, a listagem mostra esses registros soltos em vez de inventar um par.
    """

    class Tipo(models.TextChoices):
        """Tipos de movimentacao reconhecidos pelo controle da CME."""

        SAIDA = "SAIDA", "Saida"
        ENTRADA = "ENTRADA", "Entrada"

    data_hora = models.DateTimeField()
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    aluno = models.ForeignKey(
        Aluno,
        on_delete=models.SET_NULL,
        related_name="movimentacoes",
        null=True,
        blank=True,
    )
    turma = models.ForeignKey(
        Turma,
        on_delete=models.SET_NULL,
        related_name="movimentacoes",
        null=True,
        blank=True,
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.SET_NULL,
        related_name="movimentacoes",
        null=True,
        blank=True,
    )
    aluno_codigo_externo = models.CharField(max_length=40, blank=True)
    aluno_nome = models.CharField(max_length=150)
    turma_nome = models.CharField(max_length=150, blank=True)
    pacote_codigo = models.CharField(max_length=40)
    retirado = models.BooleanField(null=True, blank=True)
    entrada_origem = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="saidas",
        null=True,
        blank=True,
        limit_choices_to={"tipo": "ENTRADA"},
        help_text=(
            "Preenchido apenas em movimentacoes de SAIDA: aponta para a ENTRADA "
            "cujo pacote foi retirado."
        ),
    )
    arquivo_origem = models.CharField(max_length=80)
    row_hash = models.CharField(max_length=64, unique=True)
    origem = models.CharField(
        max_length=20,
        choices=OrigemDados.choices,
        default=OrigemDados.LEGADO,
    )
    observacoes = models.TextField(blank=True)

    class Meta:
        ordering = ["-data_hora", "-id"]
        verbose_name = "movimentacao"
        verbose_name_plural = "movimentacoes"

    def __str__(self) -> str:
        """Retorna uma descricao resumida do evento de movimentacao."""

        return f"{self.get_tipo_display()} - {self.pacote_codigo} - {self.aluno_nome}"
