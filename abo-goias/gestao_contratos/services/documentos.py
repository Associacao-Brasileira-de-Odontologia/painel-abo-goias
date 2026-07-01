"""Geração de contratos e termos de consentimento em DOCX.

Os modelos de documento ficam em gestao_contratos/modelos/.
A substituição de marcadores usa o formato {{ campo }} herdado do
abo-gerador-contratos para compatibilidade com os templates existentes.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from django.core.files.base import ContentFile
from docx import Document

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from gestao_contratos.models import ContratoGerado
    from gestao_lab.models import Paciente


_MODELOS_DIR = Path(__file__).resolve().parent.parent / "modelos"

TIPOS_CONTRATO = [
    ("bichectomia", "Bichectomia"),
    ("toxina_botulinica", "Toxina Botulínica"),
    ("odontopediatria", "Odontopediatria"),
    ("endodontia", "Endodontia"),
]

_CLINICA = "Associação Brasileira de Odontologia Seção de Goiás"


def gerar_e_salvar_contrato(
    paciente: "Paciente",
    tipo: str,
    observacoes_clinicas: str = "",
    profissional_nome: str = "",
    profissional_cro: str = "",
    local_assinatura: str = "Goiânia - GO",
    gerado_por: "User | None" = None,
) -> "ContratoGerado":
    """Gera DOCX e PDF, persiste ambos no ContratoGerado e retorna a instância.

    O PDF é gerado via LibreOffice headless quando disponível. Se o LibreOffice
    não estiver instalado, arquivo_pdf fica em branco e pode ser gerado depois.
    Raises FileNotFoundError se o modelo DOCX não for encontrado.
    """
    import logging

    from gestao_contratos.models import ContratoGerado  # evita import circular
    from gestao_contratos.services.pdf_converter import (
        docx_para_pdf,
        libreoffice_disponivel,
    )

    logger = logging.getLogger(__name__)

    conteudo_docx = gerar_contrato(
        paciente=paciente,
        tipo=tipo,
        observacoes_clinicas=observacoes_clinicas,
        profissional_nome=profissional_nome,
        profissional_cro=profissional_cro,
        local_assinatura=local_assinatura,
    )

    base_nome = f"termo_{tipo}_{paciente.nome.split()[0].lower()}_{paciente.id_dental}"

    contrato = ContratoGerado(
        paciente=paciente,
        tipo=tipo,
        observacoes_clinicas=observacoes_clinicas,
        profissional_nome=profissional_nome,
        profissional_cro=profissional_cro,
        local_assinatura=local_assinatura,
        gerado_por=gerado_por,
    )
    contrato.arquivo.save(f"{base_nome}.docx", ContentFile(conteudo_docx), save=False)

    if libreoffice_disponivel():
        try:
            conteudo_pdf = docx_para_pdf(conteudo_docx)
            contrato.arquivo_pdf.save(
                f"{base_nome}.pdf", ContentFile(conteudo_pdf), save=False
            )
        except RuntimeError as exc:
            logger.warning("gerar_e_salvar_contrato: conversão PDF falhou: %s", exc)

    contrato.save()
    return contrato


def gerar_contrato(
    paciente: "Paciente",
    tipo: str,
    observacoes_clinicas: str = "",
    profissional_nome: str = "",
    profissional_cro: str = "",
    local_assinatura: str = "Goiânia - GO",
) -> bytes:
    """Gera o DOCX preenchido e retorna os bytes para download direto.

    Raises FileNotFoundError se o modelo DOCX não for encontrado.
    """

    arquivo_modelo = _MODELOS_DIR / f"termo_consentimento_{tipo}.docx"
    if not arquivo_modelo.exists():
        raise FileNotFoundError(
            f"Modelo de contrato não encontrado: {arquivo_modelo.name}"
        )

    doc = Document(str(arquivo_modelo))
    substituicoes = _montar_substituicoes(
        paciente=paciente,
        observacoes_clinicas=observacoes_clinicas,
        profissional_nome=profissional_nome,
        profissional_cro=profissional_cro,
        local_assinatura=local_assinatura,
    )
    _substituir_documento(doc, substituicoes)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _montar_substituicoes(
    paciente: "Paciente",
    observacoes_clinicas: str,
    profissional_nome: str,
    profissional_cro: str,
    local_assinatura: str,
) -> dict[str, str]:
    """Monta o dicionário de marcadores → valores para substituição no DOCX."""

    # Tipo e número do documento principal
    if paciente.cpf:
        tipo_doc, num_doc = "CPF", paciente.cpf
    elif paciente.rg:
        tipo_doc, num_doc = "RG", paciente.rg
    else:
        tipo_doc, num_doc = "", ""

    # Endereço formatado em linha única
    partes_end: list[str] = []
    logradouro = paciente.endereco_logradouro
    if paciente.endereco_numero:
        logradouro = f"{logradouro}, {paciente.endereco_numero}"
    if paciente.endereco_complemento:
        logradouro = f"{logradouro} - {paciente.endereco_complemento}"
    if logradouro:
        partes_end.append(logradouro)
    if paciente.endereco_bairro:
        partes_end.append(paciente.endereco_bairro)
    cidade_estado = " - ".join(
        filter(None, [paciente.endereco_cidade, paciente.endereco_estado])
    )
    if cidade_estado:
        partes_end.append(cidade_estado)
    if paciente.endereco_cep:
        partes_end.append(f"CEP {paciente.endereco_cep}")
    endereco_fmt = " | ".join(partes_end)

    # Data de nascimento formatada
    nascimento_fmt = (
        paciente.data_nascimento.strftime("%d/%m/%Y")
        if paciente.data_nascimento
        else ""
    )

    # Responsável legal
    tipo_resp = "CPF" if paciente.cpf_responsavel else ""

    return {
        "{{ paciente.nome_completo }}": paciente.nome,
        "{{ paciente.data_nascimento }}": nascimento_fmt,
        "{{ paciente.documento.tipo }}": tipo_doc,
        "{{ paciente.documento.numero }}": num_doc,
        "{{ paciente.endereco }}": endereco_fmt,
        "{{ paciente.nome_completo_responsavel }}": paciente.nome_responsavel,
        "{{ paciente.documento_responsavel.tipo }}": tipo_resp,
        "{{ paciente.documento_responsavel.numero }}": paciente.cpf_responsavel,
        "{{ paciente.clinica }}": _CLINICA,
        "{{ paciente.numero_registro }}": str(paciente.id_dental),
        "{{ paciente.data_cadastro }}": date.today().strftime("%d/%m/%Y"),
        "{{ observacoes_clinicas }}": observacoes_clinicas,
        "{{ local_assinatura }}": local_assinatura,
        "{{ data_assinatura }}": date.today().strftime("%d/%m/%Y"),
        "{{ profissional.nome_completo }}": profissional_nome,
        "{{ profissional.cro }}": profissional_cro,
    }


def _substituir_documento(doc: Document, substituicoes: dict[str, str]) -> None:
    """Aplica substituições em todos os parágrafos e tabelas do DOCX."""

    for paragrafo in doc.paragraphs:
        _substituir_em_paragrafo(paragrafo, substituicoes)

    for tabela in doc.tables:
        for linha in tabela.rows:
            for celula in linha.cells:
                for paragrafo in celula.paragraphs:
                    _substituir_em_paragrafo(paragrafo, substituicoes)

    for secao in doc.sections:
        for paragrafo in secao.header.paragraphs:
            _substituir_em_paragrafo(paragrafo, substituicoes)
        for paragrafo in secao.footer.paragraphs:
            _substituir_em_paragrafo(paragrafo, substituicoes)


def _substituir_em_paragrafo(paragrafo, substituicoes: dict[str, str]) -> None:
    """Substitui marcadores num parágrafo preservando a formatação.

    Tenta substituição run a run (preserva formatação completa). Se algum
    marcador ainda restar após essa passagem, o parágrafo é mesclado num
    único run para lidar com marcadores fragmentados pelo processador de texto.
    """

    # Passagem 1: substituição por run (preserva formatação)
    for run in paragrafo.runs:
        for marcador, valor in substituicoes.items():
            if marcador in run.text:
                run.text = run.text.replace(marcador, valor)

    # Passagem 2: fallback para marcadores que cruzam múltiplos runs
    texto_completo = "".join(run.text for run in paragrafo.runs)
    if not any(m in texto_completo for m in substituicoes):
        return

    for marcador, valor in substituicoes.items():
        texto_completo = texto_completo.replace(marcador, valor)

    if paragrafo.runs:
        paragrafo.runs[0].text = texto_completo
        for run in paragrafo.runs[1:]:
            run.text = ""
