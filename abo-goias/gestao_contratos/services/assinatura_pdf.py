"""Mescla a assinatura desenhada pelo paciente no PDF do contrato.

A imagem PNG (vinda do canvas HTML5) é carimbada sobre a linha de
assinatura do paciente — cuja posição é fixa e conhecida, definida em
services/documentos.py — junto com um carimbo de auditoria no rodapé.
O resultado é um novo PDF; o original nunca é sobrescrito.
"""

from __future__ import annotations

import io

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from .documentos import PDF_ASSINATURA_PACIENTE_Y, PDF_MARGEM_ESQUERDA

_ASSINATURA_LARGURA_MAX = 6.0 * cm
_ASSINATURA_ALTURA_MAX = 2.4 * cm


def aplicar_assinatura_no_pdf(
    pdf_bytes: bytes,
    assinatura_png: bytes,
    carimbo: str,
) -> bytes:
    """Retorna um novo PDF com a assinatura mesclada na última página.

    ``carimbo`` é a linha de auditoria impressa no rodapé (data/hora, IP).
    """

    imagem = ImageReader(io.BytesIO(assinatura_png))
    img_larg, img_alt = imagem.getSize()

    escala = min(
        _ASSINATURA_LARGURA_MAX / img_larg,
        _ASSINATURA_ALTURA_MAX / img_alt,
    )
    larg_final = img_larg * escala
    alt_final = img_alt * escala

    # Camada de sobreposição: assinatura sobre a linha + carimbo no rodapé
    overlay_buf = io.BytesIO()
    c = rl_canvas.Canvas(overlay_buf, pagesize=A4)
    c.drawImage(
        imagem,
        PDF_MARGEM_ESQUERDA + 0.4 * cm,
        PDF_ASSINATURA_PACIENTE_Y + 2,
        width=larg_final,
        height=alt_final,
        mask="auto",
    )
    c.setFont("Helvetica", 7)
    c.setFillGray(0.45)
    c.drawString(PDF_MARGEM_ESQUERDA, 1.5 * cm, carimbo)
    c.save()
    overlay_buf.seek(0)

    overlay_page = PdfReader(overlay_buf).pages[0]
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for pagina in reader.pages:
        writer.add_page(pagina)
    writer.pages[-1].merge_page(overlay_page)

    saida = io.BytesIO()
    writer.write(saida)
    return saida.getvalue()


def anexar_carimbo_tempo(
    pdf_bytes: bytes,
    token: bytes,
    nome_arquivo: str = "carimbo_tempo.tsr",
) -> bytes:
    """Retorna um novo PDF com o token de carimbo de tempo (RFC 3161)
    embutido como arquivo anexado — o PDF passa a carregar sua própria
    prova de data/hora, sem depender de um .tsr avulso.

    Importante: isto altera os bytes do arquivo, então o hash SHA-256
    salvo em ContratoGerado.hash_sha256 (calculado antes deste anexo, e é
    justamente o hash que a TSA atestou) deixa de corresponder ao hash do
    arquivo resultante — isso é esperado e não deve ser recalculado aqui.
    O conteúdo visível (páginas, texto, assinatura) permanece idêntico;
    apenas um anexo invisível é adicionado.
    """

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append(reader)
    writer.add_attachment(nome_arquivo, token)

    saida = io.BytesIO()
    writer.write(saida)
    return saida.getvalue()
