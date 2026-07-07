"""Formulários da app de gestão de contratos."""

from __future__ import annotations

from django import forms
from gestao_lab.models import Paciente


class PacienteConfirmacaoForm(forms.ModelForm):
    """Edição e confirmação dos dados do paciente antes da geração do contrato.

    O campo convenio é exclusivamente local — o Dental Office não fornece
    essa informação, portanto ela só é alimentada por este formulário.
    """

    class Meta:
        model = Paciente
        fields = [
            "nome",
            "cpf",
            "rg",
            "data_nascimento",
            "celular",
            "email",
            "convenio",
            "endereco_logradouro",
            "endereco_numero",
            "endereco_complemento",
            "endereco_bairro",
            "endereco_cidade",
            "endereco_estado",
            "endereco_cep",
            "nome_responsavel",
            "cpf_responsavel",
        ]
        widgets = {
            "data_nascimento": forms.DateInput(
                attrs={"type": "date"}, format="%Y-%m-%d"
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nome"].required = True
        placeholders = {
            "cpf": "000.000.000-00",
            "rg": "0000000",
            "celular": "(62) 9 0000-0000",
            "email": "email@exemplo.com",
            "convenio": "Ex.: Particular, Unimed, Amil...",
            "endereco_logradouro": "Rua / Avenida",
            "endereco_numero": "Nº",
            "endereco_complemento": "Apto, sala...",
            "endereco_bairro": "Bairro",
            "endereco_cidade": "Cidade",
            "endereco_estado": "UF",
            "endereco_cep": "00000-000",
            "nome_responsavel": "Obrigatório para menores de 18 anos",
            "cpf_responsavel": "CPF do responsável",
        }
        for campo, texto in placeholders.items():
            self.fields[campo].widget.attrs.setdefault("placeholder", texto)
