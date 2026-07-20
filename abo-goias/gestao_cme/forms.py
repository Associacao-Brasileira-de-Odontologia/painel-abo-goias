from __future__ import annotations

from django import forms
from django.utils import timezone

from .models import (
    Abrigo,
    Aluno,
    Emprestimo,
    Kit,
    KitMaterial,
    Material,
    Movimentacao,
    OrigemDados,
    Turma,
)


class MovimentacaoForm(forms.Form):
    """Valida entradas de saída e entrada de materiais/pacotes."""

    aluno = forms.ModelChoiceField(
        queryset=Aluno.objects.none(),
        empty_label="Selecione um aluno...",
        error_messages={
            "required": "Selecione um aluno.",
            "invalid_choice": "Aluno inválido.",
        },
    )
    pacote_codigo = forms.CharField(
        max_length=80,
        strip=True,
        error_messages={"required": "Informe o código do pacote."},
    )
    material = forms.ModelChoiceField(
        queryset=Material.objects.none(),
        required=False,
        empty_label="Nenhum material específico",
    )
    data_hora = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        error_messages={"invalid": "Data e hora inválidas."},
    )
    observacoes = forms.CharField(required=False, strip=True)

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["aluno"].queryset = (
            Aluno.objects.exclude(origem=OrigemDados.EXEMPLO)
            .filter(ativo=True)
            .select_related("turma")
            .order_by("turma__nome", "nome")
        )
        self.fields["material"].queryset = (
            Material.objects.exclude(origem=OrigemDados.EXEMPLO)
            .filter(ativo=True)
            .order_by("nome")
        )

    def clean_data_hora(self) -> object:
        data_hora = self.cleaned_data.get("data_hora")
        if not data_hora:
            return timezone.now()
        if timezone.is_naive(data_hora):
            return timezone.make_aware(data_hora)
        return data_hora


class CadastrarAlunoForm(forms.ModelForm):
    """Valida o cadastro manual de um aluno."""

    turma = forms.ModelChoiceField(
        queryset=Turma.objects.none(),
        empty_label="Selecione uma turma...",
        error_messages={
            "required": "Selecione uma turma.",
            "invalid_choice": "Turma inválida.",
        },
    )

    class Meta:
        model = Aluno
        fields = ["nome", "matricula", "turma", "cpf", "email", "telefone"]
        error_messages = {
            "nome": {"required": "Informe o nome do aluno."},
            "matricula": {"required": "Informe a matrícula."},
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["turma"].queryset = (
            Turma.objects.exclude(origem=OrigemDados.EXEMPLO)
            .filter(ativo=True)
            .order_by("nome")
        )

    def clean_matricula(self) -> str:
        matricula = self.cleaned_data.get("matricula", "")
        qs = Aluno.objects.filter(matricula=matricula)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                f"Já existe um aluno com a matrícula {matricula!r}."
            )
        return matricula

    def clean_cpf(self) -> str | None:
        return self.cleaned_data.get("cpf") or None


class CadastrarTurmaForm(forms.ModelForm):
    """Valida o cadastro manual de uma turma."""

    class Meta:
        model = Turma
        fields = ["nome", "codigo", "curso", "data_inicio", "data_fim", "observacoes"]
        error_messages = {
            "nome": {"required": "Informe o nome da turma."},
            "codigo": {"required": "Informe o código da turma."},
        }

    def clean_codigo(self) -> str:
        codigo = self.cleaned_data.get("codigo", "")
        qs = Turma.objects.filter(codigo=codigo)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"Já existe uma turma com o código {codigo!r}.")
        return codigo


class AbrigoForm(forms.ModelForm):
    """Valida o cadastro de um abrigo."""

    class Meta:
        model = Abrigo
        fields = ["identificador", "ocupado"]
        error_messages = {
            "identificador": {"required": "Identificador é obrigatório."},
        }

    def clean_identificador(self) -> str:
        identificador = self.cleaned_data.get("identificador", "")
        qs = Abrigo.objects.filter(identificador=identificador)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Já existe um abrigo com esse identificador.")
        return identificador


class AbrigoEditForm(AbrigoForm):
    """Estende AbrigoForm com o campo ativo para edição."""

    class Meta(AbrigoForm.Meta):
        fields = [*AbrigoForm.Meta.fields, "ativo"]


class KitForm(forms.ModelForm):
    """Valida o cadastro manual de um kit e sua composição de materiais.

    O painel só permitia criar kits pelo Django Admin; este form habilita o
    cadastro pela própria tela de kits. Cada material selecionado tem sua
    própria quantidade (campo ``quantidade_<pk do material>`` no POST, lido
    diretamente de ``self.data`` porque não há como declarar um campo por
    material sem conhecer o catálogo de antemão) — decisão de negócio: o
    ajuste de quantidade > 1 acontece já na criação, pela própria tela.

    ``Kit.quantidade`` é o estoque cadastrado do kit (quantas unidades físicas
    desse kit existem) — informado manualmente aqui, independente da
    disponibilidade dos materiais que compõem o kit (ver coluna "Disponíveis"
    na listagem, calculada à parte).
    """

    materiais = forms.ModelMultipleChoiceField(
        queryset=Material.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Materiais do kit",
    )

    class Meta:
        model = Kit
        fields = ["nome", "codigo", "descricao", "quantidade"]
        error_messages = {
            "nome": {"required": "Nome é obrigatório."},
            "codigo": {"required": "Código é obrigatório."},
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["materiais"].queryset = (
            Material.objects.exclude(origem=OrigemDados.EXEMPLO)
            .filter(ativo=True)
            .order_by("nome")
        )
        # Em edição, pré-marca os materiais já vinculados ao kit.
        if self.instance.pk:
            self.fields["materiais"].initial = self.instance.materiais.all()

    def clean_codigo(self) -> str:
        codigo = self.cleaned_data.get("codigo", "")
        qs = Kit.objects.filter(codigo=codigo)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Já existe um kit com esse código.")
        return codigo

    def save(self, commit: bool = True) -> Kit:
        kit = super().save(commit=commit)
        if commit:
            self._salvar_materiais(kit)
        return kit

    def _quantidade_informada(self, material_pk: int) -> int:
        """Lê a quantidade digitada para um material, com piso de 1.

        O campo não é declarado no form (não há como saber o catálogo de
        materiais antes de instanciar), então é lido diretamente do POST
        bruto pelo nome de convenção ``quantidade_<pk>``.
        """

        bruto = self.data.get(f"quantidade_{material_pk}", "1")
        try:
            valor = int(bruto)
        except (TypeError, ValueError):
            return 1
        return max(1, valor)

    def _salvar_materiais(self, kit: Kit) -> None:
        """Sincroniza os itens do kit com os materiais e quantidades do form.

        Cria/atualiza um ``KitMaterial`` por material selecionado (com a
        quantidade informada) e remove os itens de materiais que ficaram
        desmarcados — necessário para a edição funcionar (não só a criação).
        """

        selecionados_pks: set[int] = set()
        for material in self.cleaned_data.get("materiais", []):
            quantidade = self._quantidade_informada(material.pk)
            KitMaterial.objects.update_or_create(
                kit=kit,
                material=material,
                defaults={"quantidade": quantidade},
            )
            selecionados_pks.add(material.pk)
        kit.itens.exclude(material_id__in=selecionados_pks).delete()


class KitEditForm(KitForm):
    """Estende KitForm com o campo ativo para edição."""

    class Meta(KitForm.Meta):
        fields = [*KitForm.Meta.fields, "ativo"]


class MaterialForm(forms.ModelForm):
    """Valida o cadastro de um material."""

    class Meta:
        model = Material
        fields = [
            "nome",
            "codigo",
            "descricao",
            "identificacao",
            "rotulo_kit",
            "disponivel",
            "unidade_medida",
            "quantidade_minima",
        ]
        error_messages = {
            "nome": {"required": "Nome é obrigatório."},
            "codigo": {"required": "Código é obrigatório."},
        }

    def clean_codigo(self) -> str:
        codigo = self.cleaned_data.get("codigo", "")
        qs = Material.objects.filter(codigo=codigo)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Já existe um material com esse código.")
        return codigo


class MaterialEditForm(MaterialForm):
    """Estende MaterialForm com o campo ativo para edição."""

    class Meta(MaterialForm.Meta):
        fields = [*MaterialForm.Meta.fields, "ativo"]


class EditarMovimentacaoForm(forms.ModelForm):
    """Permite editar campos de uma movimentacao existente."""

    data_hora = forms.DateTimeField(
        required=True,
        input_formats=["%Y-%m-%dT%H:%M"],
        error_messages={
            "invalid": "Data e hora inválidas.",
            "required": "Informe a data e hora.",
        },
    )

    class Meta:
        model = Movimentacao
        fields = ["pacote_codigo", "data_hora", "observacoes"]
        error_messages = {
            "pacote_codigo": {
                "required": "Informe o código do pacote.",
                "max_length": "O código do pacote deve ter no máximo 40 caracteres.",
            },
        }

    def clean_data_hora(self) -> object:
        data_hora = self.cleaned_data.get("data_hora")
        if data_hora and timezone.is_naive(data_hora):
            return timezone.make_aware(data_hora)
        return data_hora


class EntradaForm(forms.Form):
    """Valida o registro em lote de pacotes de entrada para esterilização."""

    aluno = forms.ModelChoiceField(
        queryset=Aluno.objects.none(),
        empty_label="Selecione um aluno...",
        error_messages={
            "required": "Selecione um aluno.",
            "invalid_choice": "Aluno inválido.",
        },
    )
    quantidade = forms.IntegerField(
        min_value=1,
        max_value=50,
        initial=1,
        error_messages={
            "required": "Informe a quantidade de pacotes.",
            "min_value": "A quantidade mínima é 1.",
            "max_value": "A quantidade máxima por registro é 50.",
        },
    )
    data_hora = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        error_messages={"invalid": "Data e hora inválidas."},
    )
    observacoes = forms.CharField(required=False, strip=True)

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["aluno"].queryset = (
            Aluno.objects.exclude(origem=OrigemDados.EXEMPLO)
            .filter(ativo=True)
            .select_related("turma", "abrigo")
            .order_by("turma__nome", "nome")
        )

    def clean_data_hora(self) -> object:
        data_hora = self.cleaned_data.get("data_hora")
        if not data_hora:
            return timezone.now()
        if timezone.is_naive(data_hora):
            return timezone.make_aware(data_hora)
        return data_hora


class EmprestimoForm(forms.Form):
    """Valida a criação de um empréstimo de kit para um aluno."""

    aluno = forms.ModelChoiceField(
        queryset=Aluno.objects.none(),
        empty_label="— Selecione o aluno —",
        error_messages={
            "required": "Selecione um aluno.",
            "invalid_choice": "Aluno inválido.",
        },
    )
    kit = forms.ModelChoiceField(
        queryset=Kit.objects.none(),
        required=False,
        empty_label="— Sem kit vinculado —",
    )
    data_prevista_devolucao = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d"],
        error_messages={"invalid": "Data prevista de devolução inválida."},
    )
    observacoes = forms.CharField(required=False, strip=True)

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["aluno"].queryset = (
            Aluno.objects.exclude(origem=OrigemDados.EXEMPLO)
            .filter(ativo=True)
            .select_related("turma")
            .order_by("turma__nome", "nome")
        )
        self.fields["kit"].queryset = (
            Kit.objects.exclude(origem=OrigemDados.EXEMPLO)
            .filter(ativo=True)
            .prefetch_related("itens__material")
            .order_by("nome")
        )


class EditarEmprestimoForm(forms.ModelForm):
    """Permite editar um empréstimo já registrado.

    Aluno e kit não entram aqui de propósito: trocá-los depois de criado o
    empréstimo deixaria os itens já retirados (ver ItemEmprestimo) fora de
    sincronia com o novo kit — mesma lógica de editar_movimentacao, que
    também não permite editar o aluno de um registro existente.
    """

    data_prevista_devolucao = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d"],
        error_messages={"invalid": "Data prevista de devolução inválida."},
    )

    class Meta:
        model = Emprestimo
        fields = ["data_prevista_devolucao", "observacoes"]
