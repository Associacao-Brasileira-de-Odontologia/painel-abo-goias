"""Agregação do Portal — o resumo cross-app da tela inicial.

Antes, `gestao_cme.views.portal` importava models de `gestao_lab` e
`gestao_contratos` para montar essa tela. Isso dava a um app operacional o papel
de agregador: para acrescentar um número de outro módulo era preciso mexer no
CME, e o CME quebrava se um dos outros mudasse um campo interno.

Aqui a direção se inverte. Este módulo não conhece nenhuma app: ele mantém um
registro de **fontes**, e cada app declara a sua em `services/portal.py`,
registrando-a no `ready()` do próprio `AppConfig`. Uma app nova entra no Portal
sem que nada aqui — nem no CME — precise mudar; uma app removida some do resumo
junto com o próprio registro.

O que uma fonte entrega:
  ``resumo``   — números dos cartões, como um dicionário de chaves próprias.
  ``tarefas``  — pendências que pedem ação, derivadas do resumo já calculado.
  ``eventos``  — atividade recente da app, já limitada por ela mesma.

``tarefas`` recebe o resumo consolidado de propósito: as pendências são frases
sobre números que o resumo já contou ("N pacotes aguardando retirada"), e
recontá-las custaria uma query a mais por tarefa sem mudar o resultado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable


@dataclass(frozen=True)
class Tarefa:
    """Pendência exibida na lista de "tarefas que requerem atenção"."""

    texto: str
    url_name: str
    urgente: bool = False


@dataclass(frozen=True)
class Evento:
    """Item do feed de atividade recente."""

    categoria: str
    titulo: str
    descricao: str
    data: datetime


@dataclass(frozen=True)
class FontePortal:
    """O que uma app entrega ao Portal.

    ``ordem`` decide o desempate: o feed é ordenado por data (mais recente
    primeiro) e a ordenação do Python é estável, então dois eventos com a mesma
    data saem na ordem em que as fontes foram lidas. Deixar isso explícito num
    campo evita que o resultado passe a depender da ordem de `INSTALLED_APPS`,
    que ninguém espera que seja significativa.

    Cada fonte limita os próprios eventos: as apps contribuem com quantidades
    diferentes de propósito (a mais movimentada entrega mais), e o corte final
    acontece depois, sobre o conjunto já ordenado.
    """

    nome: str
    ordem: int
    resumo: Callable[[], dict[str, int]] = dict
    tarefas: Callable[[dict[str, int]], list[Tarefa]] = lambda resumo: []
    eventos: Callable[[], list[Evento]] = list


_FONTES: dict[str, FontePortal] = {}


def registrar(fonte: FontePortal) -> None:
    """Inscreve (ou substitui) a fonte de uma app.

    Chamado no `ready()` de cada `AppConfig`. Substituir em vez de acumular
    torna a chamada idempotente — o `ready()` pode rodar mais de uma vez em
    alguns cenários de teste sem duplicar o resumo.
    """

    _FONTES[fonte.nome] = fonte


def fontes() -> list[FontePortal]:
    """Fontes registradas, na ordem declarada por elas."""

    return sorted(_FONTES.values(), key=lambda fonte: (fonte.ordem, fonte.nome))


def montar_resumo() -> dict[str, int]:
    """Junta os números de todas as fontes num único dicionário."""

    resumo: dict[str, int] = {}
    for fonte in fontes():
        resumo.update(fonte.resumo())
    return resumo


def montar_tarefas(resumo: dict[str, int]) -> list[Tarefa]:
    """Pendências de todas as fontes, na ordem das fontes.

    Recebe o resumo de ``montar_resumo()`` — cada fonte lê dali os números que
    já foram contados, em vez de consultar o banco de novo.
    """

    tarefas: list[Tarefa] = []
    for fonte in fontes():
        tarefas.extend(fonte.tarefas(resumo))
    return tarefas


def montar_atividade(limite: int = 8) -> list[Evento]:
    """Feed unificado: junta os eventos das fontes e corta os mais recentes."""

    eventos: list[Evento] = []
    for fonte in fontes():
        eventos.extend(fonte.eventos())
    return sorted(eventos, key=lambda evento: evento.data, reverse=True)[:limite]
