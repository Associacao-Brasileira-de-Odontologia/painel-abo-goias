from django.conf import settings
from django.db import models
from django.utils import timezone


class ModeloBase(models.Model):
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        abstract = True


class OrigemDados(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    EDUQ = "EDUQ", "Eduq"
    LEGADO = "LEGADO", "Legado"
    EXEMPLO = "EXEMPLO", "Exemplo"


class Turma(ModeloBase):
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

    def __str__(self):
        return f"{self.codigo} - {self.nome}"


class Aluno(ModeloBase):
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

    class Meta:
        ordering = ["nome"]
        verbose_name = "aluno"
        verbose_name_plural = "alunos"

    def __str__(self):
        return self.nome


class Material(ModeloBase):
    class UnidadeMedida(models.TextChoices):
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

    def __str__(self):
        return self.nome


class Kit(ModeloBase):
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

    def __str__(self):
        return self.nome


class KitMaterial(models.Model):
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

    def __str__(self):
        return f"{self.quantidade} x {self.material}"


class Armario(ModeloBase):
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

    def __str__(self):
        return self.identificacao


class Abrigo(ModeloBase):
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

    def __str__(self):
        return self.identificador


class EstoqueArmario(models.Model):
    armario = models.ForeignKey(Armario, on_delete=models.CASCADE, related_name="estoques")
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

    def __str__(self):
        return f"{self.armario} - {self.material}: {self.quantidade}"


class Emprestimo(ModeloBase):
    class Status(models.TextChoices):
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

    def __str__(self):
        return f"Emprestimo #{self.pk} - {self.aluno}"


class ItemEmprestimo(models.Model):
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

    def __str__(self):
        return f"{self.quantidade} x {self.material}"


class Movimentacao(ModeloBase):
    class Tipo(models.TextChoices):
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

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.pacote_codigo} - {self.aluno_nome}"
