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
    validacao_url: str | None = None,
) -> bytes:
    """Retorna um novo PDF com a assinatura mesclada na última página.

    ``carimbo`` é a linha de auditoria impressa no rodapé (data/hora, IP).
    ``validacao_url``, quando informada, é impressa como uma segunda linha
    no rodapé, orientando qualquer pessoa a conferir a autenticidade do
    documento na página pública de validação.
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
    if validacao_url:
        c.setFont("Helvetica", 6.5)
        c.drawString(
            PDF_MARGEM_ESQUERDA,
            1.15 * cm,
            f"Confira a autenticidade deste documento em: {validacao_url}",
        )
        _desenhar_qr_validacao(c, validacao_url)
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


def _desenhar_qr_validacao(c: "rl_canvas.Canvas", url: str) -> None:
    """Desenha, no canto inferior direito do rodapé, um QR Code que abre a
    página pública de validação — atalho de conferência para quem tem o
    documento impresso em mãos (a mesma URL também é impressa em texto).
    """

    import qrcode

    qr_lado = 1.9 * cm
    qr_x = A4[0] - PDF_MARGEM_ESQUERDA - qr_lado
    qr_y = 0.9 * cm

    imagem = qrcode.make(url, box_size=6, border=1)
    buf = io.BytesIO()
    imagem.save(buf, format="PNG")
    buf.seek(0)

    c.drawImage(ImageReader(buf), qr_x, qr_y, width=qr_lado, height=qr_lado)
    c.setFont("Helvetica", 5.5)
    c.setFillGray(0.45)
    c.drawCentredString(qr_x + qr_lado / 2, qr_y + qr_lado + 3, "Validar documento")


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
