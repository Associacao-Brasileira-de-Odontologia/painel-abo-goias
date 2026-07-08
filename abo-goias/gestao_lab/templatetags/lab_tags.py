import re
from datetime import date, datetime
from urllib.parse import quote

from django import template

register = template.Library()


@register.filter
def dias_relativos(valor) -> str:
    """Distância em dias até hoje: 'há 3 dias', 'ontem', 'hoje', 'amanhã', 'em 5 dias'."""
    if not valor:
        return ""
    if isinstance(valor, datetime):
        valor = valor.date()
    delta = (valor - date.today()).days
    if delta == 0:
        return "hoje"
    if delta == 1:
        return "amanhã"
    if delta == -1:
        return "ontem"
    if delta < 0:
        return f"há {-delta} dias"
    return f"em {delta} dias"


@register.filter
def whatsapp_url(numero: str) -> str:
    """Converte um numero de telefone em URL de abertura do WhatsApp Web."""
    numero_limpo = re.sub(r"\D", "", str(numero or ""))
    if not numero_limpo:
        return "#"
    if not numero_limpo.startswith("55"):
        numero_limpo = "55" + numero_limpo
    return f"https://wa.me/{numero_limpo}"


@register.filter
def whatsapp_url_msg(numero: str, mensagem: str) -> str:
    """Converte numero e mensagem em URL do WhatsApp com texto pre-preenchido."""
    numero_limpo = re.sub(r"\D", "", str(numero or ""))
    if not numero_limpo:
        return "#"
    if not numero_limpo.startswith("55"):
        numero_limpo = "55" + numero_limpo
    return f"https://wa.me/{numero_limpo}?text={quote(str(mensagem))}"


@register.simple_tag
def status_badge_class(status: str) -> str:
    """Retorna a classe CSS do badge conforme o status do pedido."""
    mapa = {
        "EM_DIA": "badge-em-dia",
        "A_CONFIRMAR": "badge-a-confirmar",
        "ATRASADO": "badge-atrasado",
        "CONCLUIDO": "badge-neutro",
    }
    return mapa.get(status, "")


@register.simple_tag
def status_row_class(status: str) -> str:
    """Retorna a classe CSS de estado da linha da tabela conforme o status."""
    mapa = {
        "ATRASADO": "row-atrasado",
        "A_CONFIRMAR": "row-a-confirmar",
    }
    return mapa.get(status, "")
