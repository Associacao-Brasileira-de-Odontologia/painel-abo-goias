"""Validação pública de um PDF assinado pelo próprio sistema.

Confere a autenticidade e a integridade de um documento sem depender de
software de terceiro: recalcula o SHA-256 do arquivo enviado e procura um
contrato assinado com a mesma impressão digital
(``ContratoGerado.hash_arquivo_assinado``). Se bater, o documento é
idêntico, bit a bit, ao que o sistema emitiu — qualquer alteração
posterior (mesmo de um único byte) muda o hash e derruba a conferência.

Não há consulta a nenhum serviço externo aqui: o hash é a própria prova.
O carimbo de tempo RFC 3161 (quando presente) é uma evidência adicional,
verificável de forma independente com o certificado público da TSA.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gestao_contratos.models import ContratoGerado, SessaoAssinatura

# Assinaturas geram PDFs pequenos (poucas páginas). 20 MB é folga larga e
# ainda protege contra upload abusivo na página pública.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

_PDF_MAGIC = b"%PDF-"


class ArquivoInvalido(Exception):
    """Upload ausente, grande demais ou que não é um PDF."""


@dataclass(frozen=True)
class ResultadoValidacao:
    """Resultado da conferência de um PDF enviado à página de validação."""

    autentico: bool
    hash_sha256: str
    contrato: "ContratoGerado | None" = None
    sessao: "SessaoAssinatura | None" = None


def validar_pdf(conteudo: bytes) -> ResultadoValidacao:
    """Confere um PDF enviado contra os documentos assinados pelo sistema.

    Levanta ArquivoInvalido para upload vazio, grande demais ou que não seja
    um PDF. Caso contrário, retorna sempre um ResultadoValidacao — com
    ``autentico=True`` e o contrato correspondente quando o hash bate, ou
    ``autentico=False`` (documento adulterado ou não emitido aqui) quando
    nenhum contrato assinado tem aquela impressão digital.
    """

    from gestao_contratos.models import ContratoGerado, SessaoAssinatura

    if not conteudo:
        raise ArquivoInvalido("Nenhum arquivo foi enviado.")
    if len(conteudo) > MAX_UPLOAD_BYTES:
        raise ArquivoInvalido("Arquivo muito grande (máximo de 20 MB).")
    if not conteudo.startswith(_PDF_MAGIC):
        raise ArquivoInvalido("O arquivo enviado não é um PDF.")

    digest = hashlib.sha256(conteudo).hexdigest()

    contrato = (
        ContratoGerado.objects.filter(hash_arquivo_assinado=digest, status="assinado")
        .select_related("paciente")
        .first()
    )
    # Fallback: contratos assinados antes deste campo existir e que, por
    # não terem carimbo de tempo embutido, têm o hash do arquivo final
    # igual a hash_sha256.
    if contrato is None:
        contrato = (
            ContratoGerado.objects.filter(hash_sha256=digest, status="assinado")
            .select_related("paciente")
            .first()
        )

    if contrato is None:
        return ResultadoValidacao(autentico=False, hash_sha256=digest)

    sessao = (
        SessaoAssinatura.objects.filter(contrato=contrato, status="assinada")
        .order_by("-assinada_em")
        .first()
    )
    return ResultadoValidacao(
        autentico=True,
        hash_sha256=digest,
        contrato=contrato,
        sessao=sessao,
    )
