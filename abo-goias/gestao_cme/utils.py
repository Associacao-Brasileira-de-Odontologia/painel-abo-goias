"""Utilitarios compartilhados entre as aplicacoes do painel."""

from __future__ import annotations

import unicodedata


def normalizar_texto(valor: str | None) -> str:
    """Remove acentos, normaliza a caixa e compacta espacos de um texto.

    Base das buscas por nome: os cadastros chegam do Eduq/Dental Office com
    grafia mista (uns acentuados, outros nao) e o operador quase sempre digita
    sem acento. Guardando e comparando a forma normalizada, um mesmo termo
    encontra as duas grafias -- sem isto, buscar "Honorio" nao acha "Honorio"
    escrito com acento.
    """

    sem_acento = unicodedata.normalize("NFKD", str(valor or ""))
    ascii_texto = sem_acento.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_texto.upper().split())
