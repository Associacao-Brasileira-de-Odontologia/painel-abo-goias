"""Validação de prontidão dos dados do paciente para geração de contratos.

Garante que campos obrigatórios — documento, endereço, data de nascimento e,
quando o paciente for menor de idade, dados do responsável legal — estejam
preenchidos antes de permitir a geração do DOCX.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gestao_lab.models import Paciente


@dataclass(frozen=True)
class ItemChecklist:
    rotulo: str
    valor: str
    status: str  # "ok" | "pendente"
    mensagem: str
    obrigatorio: bool = True


def gerar_checklist(paciente: "Paciente") -> list[ItemChecklist]:
    """Valida os dados do paciente para preenchimento do contrato.

    Retorna uma lista de itens indicando quais campos estão preenchidos e
    quais estão pendentes (bloqueiam geração). Os itens de responsável legal
    só entram na lista quando o paciente é menor de 18 anos — para um
    paciente maior, o campo fica oculto na tela de qualquer forma, então
    incluí-lo aqui só geraria um aviso sobre algo que nunca será preenchido.
    """

    menor = eh_menor_de_idade(paciente.data_nascimento)
    documento = _formatar_documento(paciente)
    endereco = _formatar_endereco_resumido(paciente)

    itens: list[ItemChecklist] = [
        _item("Nome completo", paciente.nome),
        _item("Data de nascimento", _formatar_data(paciente.data_nascimento)),
        _item("Documento (CPF ou RG)", documento),
        _item("Cidade/Endereço", endereco),
    ]

    if menor is True:
        itens.extend(
            [
                _item("Responsável legal — nome", paciente.nome_responsavel),
                _item("Responsável legal — CPF", paciente.cpf_responsavel),
            ]
        )

    return itens


def pendencias_obrigatorias(paciente: "Paciente") -> list[ItemChecklist]:
    """Retorna apenas os itens obrigatórios com status pendente."""

    return [
        item
        for item in gerar_checklist(paciente)
        if item.obrigatorio and item.status == "pendente"
    ]


def bloqueado(paciente: "Paciente") -> bool:
    """True se o paciente tem pendências obrigatórias que impedem a geração."""

    return bool(pendencias_obrigatorias(paciente))


# ── Helpers internos ──────────────────────────────────────────────────────────


def _item(rotulo: str, valor: str) -> ItemChecklist:
    valor_limpo = (valor or "").strip()
    if valor_limpo:
        return ItemChecklist(
            rotulo=rotulo,
            valor=valor_limpo,
            status="ok",
            mensagem="Preenchido.",
        )
    return ItemChecklist(
        rotulo=rotulo,
        valor="Não informado",
        status="pendente",
        mensagem=(
            "Dado ausente no Dental Office. "
            "Verifique a ficha do paciente e sincronize novamente."
        ),
    )


def _formatar_documento(paciente: "Paciente") -> str:
    if paciente.cpf:
        return f"CPF {paciente.cpf}"
    if paciente.rg:
        return f"RG {paciente.rg}"
    return ""


def _formatar_endereco_resumido(paciente: "Paciente") -> str:
    partes = [p for p in (paciente.endereco_logradouro, paciente.endereco_cidade) if p]
    return ", ".join(partes)


def _formatar_data(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def eh_menor_de_idade(data_nascimento: date | None) -> bool | None:
    """Retorna True se menor de 18 anos, False se maior, None se data desconhecida."""

    if data_nascimento is None:
        return None
    hoje = date.today()
    idade = hoje.year - data_nascimento.year
    if (hoje.month, hoje.day) < (data_nascimento.month, data_nascimento.day):
        idade -= 1
    return idade < 18
