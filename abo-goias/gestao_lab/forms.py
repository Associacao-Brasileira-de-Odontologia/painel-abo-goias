from __future__ import annotations

from django import forms

from .models import AlunoLab, Equipe, Laboratorio, Moldagem, Paciente, PedidoMaterial


class PedidoMaterialForm(forms.ModelForm):
    """Valida o cadastro e edicao de um pedido de material para laboratorio."""

    class Meta:
        model = PedidoMaterial
        fields = [
            "paciente",
            "aluno",
            "laboratorio",
            "equipe",
            "previsao_entrega",
            "descricao_servico",
        ]
        error_messages = {
            "paciente": {"required": "Selecione o paciente."},
            "aluno": {"required": "Selecione o aluno."},
            "laboratorio": {"required": "Selecione o laboratório."},
            "equipe": {"required": "Selecione a equipe."},
            "previsao_entrega": {
                "required": "Informe a previsão de entrega.",
                "invalid": "Data inválida.",
            },
            "descricao_servico": {"required": "Descreva o serviço solicitado."},
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["paciente"].queryset = Paciente.objects.filter(ativo=True).order_by(
            "nome"
        )
        self.fields["paciente"].empty_label = "— Selecione o paciente —"
        self.fields["aluno"].queryset = AlunoLab.objects.filter(ativo=True).order_by(
            "nome"
        )
        self.fields["aluno"].empty_label = "— Selecione o aluno —"
        self.fields["laboratorio"].queryset = Laboratorio.objects.filter(
            ativo=True
        ).order_by("nome")
        self.fields["laboratorio"].empty_label = "— Selecione o laboratório —"
        self.fields["equipe"].queryset = Equipe.objects.filter(ativo=True).order_by(
            "nome"
        )
        self.fields["equipe"].empty_label = "— Selecione a equipe —"
        self.fields["equipe"].label_from_instance = (
            lambda equipe: f"{equipe.nome} — {equipe.coordenador}"
        )
        self.fields["previsao_entrega"].widget = forms.DateInput(
            attrs={"type": "date"}, format="%Y-%m-%d"
        )
        self.fields["previsao_entrega"].input_formats = ["%Y-%m-%d"]
        self.fields["descricao_servico"].widget = forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": (
                    "Descreva o procedimento, especificações e observações relevantes..."
                ),
            }
        )


class PedidoEnvioForm(forms.Form):
    """Registra a data em que o material foi enviado ao laboratorio."""

    data_envio = forms.DateField(
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        error_messages={
            "required": "Informe a data de envio ao laboratório.",
            "invalid": "Data inválida.",
        },
    )


class PedidoEntregaForm(forms.Form):
    """Registra a data em que o laboratorio devolveu o material finalizado."""

    data_entrega = forms.DateField(
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        error_messages={
            "required": "Informe a data de entrega do laboratório.",
            "invalid": "Data inválida.",
        },
    )


class PedidoFaturamentoForm(forms.ModelForm):
    """Atualiza as informacoes financeiras de um pedido entregue."""

    class Meta:
        model = PedidoMaterial
        fields = [
            "faturado_paciente",
            "faturado_lab",
            "numero_nota_fiscal",
            "data_vencimento",
        ]

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["numero_nota_fiscal"].required = False
        self.fields["data_vencimento"].required = False
        self.fields["data_vencimento"].widget = forms.DateInput(
            attrs={"type": "date"}, format="%Y-%m-%d"
        )
        self.fields["data_vencimento"].input_formats = ["%Y-%m-%d"]


class MoldagemForm(forms.ModelForm):
    """Valida o cadastro de uma moldagem vinculada a paciente e aluno."""

    class Meta:
        model = Moldagem
        fields = ["paciente", "aluno", "faturado", "entregue"]
        error_messages = {
            "paciente": {"required": "Selecione o paciente."},
            "aluno": {"required": "Selecione o aluno."},
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["paciente"].queryset = Paciente.objects.filter(ativo=True).order_by(
            "nome"
        )
        self.fields["paciente"].empty_label = "— Selecione o paciente —"
        self.fields["aluno"].queryset = AlunoLab.objects.filter(ativo=True).order_by(
            "nome"
        )
        self.fields["aluno"].empty_label = "— Selecione o aluno —"
        self.fields["faturado"].required = False
        self.fields["entregue"].required = False


class EquipeForm(forms.ModelForm):
    """Valida o cadastro e edicao de uma equipe de coordenacao."""

    class Meta:
        model = Equipe
        fields = ["nome", "coordenador", "whatsapp"]
        error_messages = {
            "nome": {"required": "Informe o nome da equipe."},
            "coordenador": {"required": "Informe o nome do coordenador."},
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["whatsapp"].required = False


class LaboratorioForm(forms.ModelForm):
    """Valida o cadastro e edicao de um laboratorio externo."""

    class Meta:
        model = Laboratorio
        fields = ["nome", "telefone", "whatsapp", "email", "cnpj", "equipes"]
        error_messages = {
            "nome": {"required": "Informe o nome do laboratório."},
        }
        widgets = {
            "equipes": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["telefone"].required = False
        self.fields["whatsapp"].required = False
        self.fields["email"].required = False
        self.fields["cnpj"].required = False
        self.fields["equipes"].required = False
        self.fields["equipes"].queryset = Equipe.objects.filter(ativo=True).order_by(
            "nome"
        )
