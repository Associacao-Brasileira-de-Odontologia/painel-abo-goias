from __future__ import annotations

from django import forms
from django.utils import timezone

from .models import (
    Abrigo,
    Aluno,
    Kit,
    Material,
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
