"""Geração de contratos genéricos em DOCX.

Os documentos são gerados programaticamente com python-docx, preenchidos
apenas com informações pessoais do paciente. Nenhum arquivo de modelo
externo é necessário.
"""

from __future__ import annotations

import io
from datetime import date
from typing import TYPE_CHECKING

from django.core.files.base import ContentFile
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from gestao_contratos.models import ContratoGerado
    from gestao_lab.models import Paciente


_CLINICA = "Associação Brasileira de Odontologia — Seção Goiás"


def gerar_e_salvar_contrato(
    paciente: "Paciente",
    tipo: str,
    observacoes_clinicas: str = "",
    profissional_nome: str = "",
    profissional_cro: str = "",
    local_assinatura: str = "Goiânia - GO",
    gerado_por: "User | None" = None,
) -> "ContratoGerado":
    """Gera DOCX e PDF (se conversor disponível), persiste e retorna ContratoGerado."""
    import logging

    from gestao_contratos.models import ContratoGerado
    from gestao_contratos.services.pdf_converter import (
        docx_para_pdf,
        libreoffice_disponivel,
    )

    logger = logging.getLogger(__name__)

    conteudo_docx = gerar_contrato(
        paciente=paciente,
        tipo=tipo,
        profissional_nome=profissional_nome,
        profissional_cro=profissional_cro,
        local_assinatura=local_assinatura,
    )

    base_nome = (
        f"contrato_{tipo}_{paciente.nome.split()[0].lower()}_{paciente.id_dental}"
    )

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
    """Gera e retorna os bytes do DOCX com dados pessoais do paciente."""
    numero = tipo.replace("modelo_", "")
    return _gerar_documento(
        numero_modelo=numero,
        paciente=paciente,
        profissional_nome=profissional_nome,
        profissional_cro=profissional_cro,
        local_assinatura=local_assinatura,
    )


def _gerar_documento(
    numero_modelo: str,
    paciente: "Paciente",
    profissional_nome: str,
    profissional_cro: str,
    local_assinatura: str,
) -> bytes:
    doc = Document()

    for secao in doc.sections:
        secao.top_margin = Cm(2.5)
        secao.bottom_margin = Cm(2.5)
        secao.left_margin = Cm(3.0)
        secao.right_margin = Cm(2.5)

    # ── Cabeçalho ──────────────────────────────────────────────────────
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(_CLINICA.upper())
    r.bold = True
    r.font.size = Pt(10)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(f"MODELO {numero_modelo} — DECLARAÇÃO DE CONSENTIMENTO")
    r.bold = True
    r.font.size = Pt(13)

    doc.add_paragraph()

    # ── Dados pessoais ─────────────────────────────────────────────────
    _titulo_secao(doc, "DADOS DO PACIENTE")
    _campo(doc, "Nome completo", paciente.nome)
    _campo(doc, "Data de nascimento", _fmt_data(paciente.data_nascimento))

    if paciente.cpf:
        _campo(doc, "CPF", paciente.cpf)
    elif paciente.rg:
        _campo(doc, "RG", paciente.rg)

    endereco = _fmt_endereco(paciente)
    if endereco:
        _campo(doc, "Endereço", endereco)

    # ── Responsável legal ──────────────────────────────────────────────
    if paciente.nome_responsavel:
        doc.add_paragraph()
        _titulo_secao(doc, "RESPONSÁVEL LEGAL")
        _campo(doc, "Nome", paciente.nome_responsavel)
        if paciente.cpf_responsavel:
            _campo(doc, "CPF", paciente.cpf_responsavel)

    doc.add_paragraph()

    # ── Declaração ─────────────────────────────────────────────────────
    p = doc.add_paragraph(
        "Declaro que fui devidamente informado(a) e autorizo a realização "
        "do procedimento, estando ciente dos riscos e benefícios inerentes."
    )
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    doc.add_paragraph()

    _campo(
        doc,
        "Local e data",
        f"{local_assinatura}, {date.today().strftime('%d/%m/%Y')}",
    )

    doc.add_paragraph()
    doc.add_paragraph()

    # ── Assinaturas ────────────────────────────────────────────────────
    _linha_assinatura(doc, "Paciente ou responsável legal")

    doc.add_paragraph()

    prof = profissional_nome or "Profissional responsável"
    if profissional_cro:
        prof += f" — CRO: {profissional_cro}"
    _linha_assinatura(doc, prof)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _titulo_secao(doc: Document, texto: str) -> None:
    p = doc.add_paragraph()
    r = p.add_run(texto)
    r.bold = True
    r.font.size = Pt(10)
    p.paragraph_format.space_after = Pt(4)


def _campo(doc: Document, rotulo: str, valor: str) -> None:
    p = doc.add_paragraph()
    r_rotulo = p.add_run(f"{rotulo}: ")
    r_rotulo.bold = True
    r_rotulo.font.size = Pt(11)
    r_valor = p.add_run(valor or "—")
    r_valor.font.size = Pt(11)
    p.paragraph_format.space_after = Pt(2)


def _linha_assinatura(doc: Document, descricao: str) -> None:
    p = doc.add_paragraph("_" * 52)
    p.paragraph_format.space_after = Pt(2)
    p2 = doc.add_paragraph(descricao)
    p2.paragraph_format.space_after = Pt(6)


def _fmt_data(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def _fmt_endereco(paciente: "Paciente") -> str:
    partes: list[str] = []
    logradouro = paciente.endereco_logradouro or ""
    if paciente.endereco_numero:
        logradouro = f"{logradouro}, {paciente.endereco_numero}"
    if paciente.endereco_complemento:
        logradouro = f"{logradouro} — {paciente.endereco_complemento}"
    if logradouro:
        partes.append(logradouro)
    if paciente.endereco_bairro:
        partes.append(paciente.endereco_bairro)
    cidade_estado = " - ".join(
        p for p in [paciente.endereco_cidade, paciente.endereco_estado] if p
    )
    if cidade_estado:
        partes.append(cidade_estado)
    if paciente.endereco_cep:
        partes.append(f"CEP {paciente.endereco_cep}")
    return " | ".join(partes)
