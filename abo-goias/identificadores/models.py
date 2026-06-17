"""Modelos da aplicacao de identificadores.

A aplicacao de identificadores nao possui tabelas proprias neste momento. Ela
consome os modelos academicos de ``gestao_cme`` (principalmente Turma e Aluno)
para gerar arquivos PPTX com identificadores por turma.

Este modulo permanece documentado para deixar claro que a ausencia de classes
de modelo e intencional, evitando a criacao de modelos duplicados ou paralelos
para dados que ja pertencem a gestao da CME.
"""

from django.db import models

# Reservado para modelos futuros especificos da geracao de identificadores.
