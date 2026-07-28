"""Helpers de HTTP compartilhados entre as aplicações.

Hoje só o destino de redirecionamento pós-POST, que era reimplementado em 22
views de três apps.
"""

from __future__ import annotations

from django.http import HttpRequest
from django.utils.http import url_has_allowed_host_and_scheme


def destino_seguro(request: HttpRequest, padrao: str) -> str:
    """Devolve o ``next`` enviado no POST, ou ``padrao`` se ele não for confiável.

    Vários formulários mandam um campo ``next`` para o operador voltar à tela de
    onde veio, preservando os filtros da URL. Como esse valor chega do cliente,
    ele não pode ir direto para ``redirect()``: um ``next`` apontando para fora
    do site transforma qualquer uma dessas views num open redirect — o link sai
    do domínio real da instituição e leva a vítima para onde o atacante quiser
    (achado A-01/S-01).

    A checagem anterior mais comum era ``next.startswith("/")``, que **não**
    basta: ``//host-externo`` começa com "/" e é uma URL protocol-relative, ou
    seja, o navegador a resolve como um endereço externo. ``\\host-externo``
    também escapa em alguns navegadores. Por isso a validação usa
    ``url_has_allowed_host_and_scheme``, do próprio Django — a mesma que o
    ``LoginView`` aplica ao ``next`` dele.

    ``padrao`` pode ser um caminho ou um nome de rota: o retorno é sempre
    passado a ``redirect()``, que aceita os dois.
    """

    next_url = request.POST.get("next", "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return padrao
