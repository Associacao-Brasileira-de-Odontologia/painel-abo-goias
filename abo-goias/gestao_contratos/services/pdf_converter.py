"""Conversão de DOCX para PDF.

Tenta, na ordem:
1. docx2pdf — usa Microsoft Word no Windows, LibreOffice no Linux/macOS
2. LibreOffice headless via subprocess

Ambos os métodos precisam de uma instalação externa (Word ou LibreOffice).
No Railway, o LibreOffice é provisionado via nixpacks.toml.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def _executavel_libreoffice() -> str | None:
    """Localiza o executável do LibreOffice no sistema via PATH ou caminhos padrão."""
    for candidato in ("libreoffice", "soffice"):
        caminho = shutil.which(candidato)
        if caminho:
            return caminho
    for caminho in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ):
        if Path(caminho).exists():
            return caminho
    return None


def pdf_converter_disponivel() -> bool:
    """Retorna True se algum método de conversão DOCX→PDF estiver disponível."""
    if _executavel_libreoffice() is not None:
        return True
    try:
        import docx2pdf  # noqa: F401

        return True
    except ImportError:
        return False


# Mantém o nome antigo como alias para compatibilidade com o código existente.
libreoffice_disponivel = pdf_converter_disponivel


def _via_docx2pdf(docx_bytes: bytes) -> bytes:
    """Converte DOCX→PDF via docx2pdf (Word no Windows, LibreOffice no Linux)."""
    import docx2pdf

    with tempfile.TemporaryDirectory() as tmpdir:
        docx_path = Path(tmpdir) / "contrato.docx"
        pdf_path = Path(tmpdir) / "contrato.pdf"
        docx_path.write_bytes(docx_bytes)
        docx2pdf.convert(str(docx_path), str(pdf_path))
        if not pdf_path.exists():
            raise RuntimeError("docx2pdf não gerou o arquivo PDF.")
        return pdf_path.read_bytes()


def _via_libreoffice(docx_bytes: bytes, executavel: str) -> bytes:
    """Converte DOCX→PDF via LibreOffice headless subprocess."""
    with tempfile.TemporaryDirectory() as tmpdir:
        docx_path = Path(tmpdir) / "contrato.docx"
        docx_path.write_bytes(docx_bytes)

        resultado = subprocess.run(
            [
                executavel,
                "--headless",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                tmpdir,
                str(docx_path),
            ],
            capture_output=True,
            timeout=60,
        )

        if resultado.returncode != 0:
            stderr = resultado.stderr.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"LibreOffice falhou (código {resultado.returncode}): {stderr}"
            )

        pdf_path = Path(tmpdir) / "contrato.pdf"
        if not pdf_path.exists():
            raise RuntimeError("LibreOffice não gerou o PDF — verifique a instalação.")

        return pdf_path.read_bytes()


def docx_para_pdf(docx_bytes: bytes) -> bytes:
    """Converte bytes de um DOCX em bytes PDF.

    Tenta docx2pdf primeiro (usa Word no Windows), depois LibreOffice subprocess.

    Raises:
        RuntimeError: se nenhum método disponível ou se a conversão falhar.
    """
    erros: list[str] = []

    try:
        return _via_docx2pdf(docx_bytes)
    except ImportError:
        pass
    except Exception as exc:
        erros.append(f"docx2pdf: {exc}")

    executavel = _executavel_libreoffice()
    if executavel:
        try:
            return _via_libreoffice(docx_bytes, executavel)
        except RuntimeError as exc:
            erros.append(f"LibreOffice: {exc}")

    detalhe = ("; ".join(erros) + ". ") if erros else ""
    raise RuntimeError(
        f"{detalhe}Nenhum método de conversão DOCX→PDF disponível. "
        "Instale o LibreOffice (linux) ou o Microsoft Word (windows)."
    )
