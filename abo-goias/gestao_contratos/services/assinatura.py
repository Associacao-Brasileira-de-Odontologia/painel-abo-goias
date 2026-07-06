"""Sessões de assinatura remota: tokens, ciclo de vida e processamento.

O token da URL pública é gerado com django.core.signing (HMAC com a
SECRET_KEY) — nenhum segredo é armazenado em banco, e o token pode ser
regenerado a qualquer momento para reexibir o QR Code. A validade real é
controlada por SessaoAssinatura.expira_em; o uso único é garantido por
uma transição de status atômica no banco.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import logging
from datetime import date
from typing import TYPE_CHECKING

from django.core import signing
from django.core.files.base import ContentFile
from django.utils import timezone

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from gestao_contratos.models import ContratoGerado, SessaoAssinatura

logger = logging.getLogger(__name__)

_SALT_TOKEN = "gestao_contratos.assinatura"

VALIDADE_SESSAO_MINUTOS = 30

# Tentativas permitidas para confirmar a data de nascimento antes de a
# sessão ser cancelada — limita a adivinhação por força bruta (soma-se ao
# rate-limit por IP já aplicado nas views públicas).
LIMITE_TENTATIVAS_IDENTIDADE = 5

# Limites da imagem de assinatura enviada pelo canvas
_ASSINATURA_MAX_BYTES = 800_000
_ASSINATURA_MIN_LARGURA = 80
_ASSINATURA_MIN_ALTURA = 30


class SessaoInvalida(Exception):
    """Sessão inexistente, expirada, cancelada ou já utilizada.

    ``motivo`` é um código estável para a interface: "invalida",
    "expirada", "cancelada" ou "ja_assinada".
    """

    def __init__(self, motivo: str) -> None:
        self.motivo = motivo
        super().__init__(motivo)


class AssinaturaInvalida(Exception):
    """Imagem de assinatura ausente, corrompida ou fora dos limites."""


# ── Tokens ────────────────────────────────────────────────────────────────────


def gerar_token(sessao: "SessaoAssinatura") -> str:
    """Gera o token assinado da URL pública para a sessão."""

    return signing.dumps(sessao.pk, salt=_SALT_TOKEN)


def resolver_token(token: str) -> "SessaoAssinatura":
    """Resolve o token e valida o estado da sessão.

    Marca a sessão como expirada (com evento) se o prazo venceu.
    Raises SessaoInvalida com o motivo em caso de qualquer problema.
    """

    from gestao_contratos.models import SessaoAssinatura

    try:
        pk = signing.loads(token, salt=_SALT_TOKEN, max_age=60 * 60 * 24)
    except signing.BadSignature:
        raise SessaoInvalida("invalida")

    try:
        sessao = SessaoAssinatura.objects.select_related(
            "contrato", "contrato__paciente"
        ).get(pk=pk)
    except SessaoAssinatura.DoesNotExist:
        raise SessaoInvalida("invalida")

    if sessao.status == "assinada":
        raise SessaoInvalida("ja_assinada")
    if sessao.status == "cancelada":
        raise SessaoInvalida("cancelada")
    if sessao.status == "expirada":
        raise SessaoInvalida("expirada")

    if expirar_se_vencida(sessao):
        raise SessaoInvalida("expirada")

    return sessao


def expirar_se_vencida(sessao: "SessaoAssinatura") -> bool:
    """Marca a sessão como expirada (e registra o evento) se o prazo já passou.

    Idempotente e seguro de chamar repetidamente — usado tanto na resolução
    do token público quanto no polling de status da tela de staff, para que
    a expiração seja refletida mesmo sem o paciente acessar o link.
    Retorna True se a sessão estava (e foi marcada como) vencida.
    """

    if sessao.status not in ("pendente", "aberta"):
        return False
    if timezone.now() < sessao.expira_em:
        return False

    sessao.status = "expirada"
    sessao.save(update_fields=["status", "atualizado_em"])
    registrar_evento(sessao.contrato, "sessao_expirada", sessao=sessao)

    # Sem sessão ativa restante, o contrato volta a "gerado" — evita polling
    # indefinido na tela de staff e libera a geração de um novo QR Code.
    contrato = sessao.contrato
    if contrato.status == "aguardando_assinatura":
        contrato.status = "gerado"
        contrato.save(update_fields=["status", "atualizado_em"])

    return True


# ── Ciclo de vida ─────────────────────────────────────────────────────────────


def criar_sessao(
    contrato: "ContratoGerado",
    criado_por: "User | None" = None,
    validade_minutos: int = VALIDADE_SESSAO_MINUTOS,
) -> "SessaoAssinatura":
    """Cria uma sessão de assinatura, cancelando sessões ativas anteriores."""

    from gestao_contratos.models import SessaoAssinatura

    cancelar_sessoes_ativas(contrato)

    sessao = SessaoAssinatura.objects.create(
        contrato=contrato,
        criado_por=criado_por,
        expira_em=timezone.now() + timezone.timedelta(minutes=validade_minutos),
    )
    contrato.status = "aguardando_assinatura"
    contrato.save(update_fields=["status", "atualizado_em"])
    registrar_evento(
        contrato,
        "sessao_criada",
        sessao=sessao,
        validade_minutos=validade_minutos,
    )
    return sessao


def cancelar_sessoes_ativas(contrato: "ContratoGerado") -> int:
    """Cancela todas as sessões pendentes/abertas do contrato."""

    from gestao_contratos.models import SessaoAssinatura

    sessoes = SessaoAssinatura.objects.filter(
        contrato=contrato, status__in=["pendente", "aberta"]
    )
    canceladas = 0
    for sessao in sessoes:
        sessao.status = "cancelada"
        sessao.save(update_fields=["status", "atualizado_em"])
        registrar_evento(contrato, "sessao_cancelada", sessao=sessao)
        canceladas += 1
    return canceladas


def sessao_ativa(contrato: "ContratoGerado") -> "SessaoAssinatura | None":
    """Retorna a sessão ativa (pendente/aberta e no prazo) do contrato.

    Antes de consultar, expira lazy qualquer sessão pendente/aberta vencida,
    para que o status refletido na tela de staff fique correto mesmo que
    ninguém tenha visitado esta tela desde o vencimento — redundante com
    (mas independente de) a limpeza periódica do Celery Beat.
    """

    from gestao_contratos.models import SessaoAssinatura

    for pendente in SessaoAssinatura.objects.filter(
        contrato=contrato, status__in=["pendente", "aberta"]
    ):
        expirar_se_vencida(pendente)

    return (
        SessaoAssinatura.objects.filter(
            contrato=contrato,
            status__in=["pendente", "aberta"],
            expira_em__gt=timezone.now(),
        )
        .order_by("-criado_em")
        .first()
    )


def eventos_recentes(contrato: "ContratoGerado", limite: int = 8) -> list:
    """Retorna os últimos eventos do contrato, mais recente primeiro."""

    return list(contrato.eventos.order_by("-criado_em", "-pk")[:limite])


def expirar_sessoes_globalmente() -> int:
    """Expira, em lote, todas as sessões pendentes/abertas vencidas do sistema.

    Executado periodicamente pelo Celery Beat como rede de segurança —
    o polling da tela de staff já expira sob demanda (função acima), mas
    esta tarefa garante a limpeza mesmo que ninguém volte a abrir a tela.
    Retorna quantas sessões foram expiradas.
    """

    from gestao_contratos.models import SessaoAssinatura

    vencidas = SessaoAssinatura.objects.filter(
        status__in=["pendente", "aberta"], expira_em__lte=timezone.now()
    )
    return sum(1 for sessao in vencidas if expirar_se_vencida(sessao))


def registrar_abertura(sessao: "SessaoAssinatura") -> None:
    """Marca a primeira abertura da página de assinatura pelo paciente."""

    if sessao.status != "pendente":
        return
    sessao.status = "aberta"
    sessao.aberta_em = timezone.now()
    sessao.save(update_fields=["status", "aberta_em", "atualizado_em"])
    registrar_evento(sessao.contrato, "contrato_aberto", sessao=sessao)


def confirmar_identidade(
    sessao: "SessaoAssinatura", data_informada: date | None
) -> bool:
    """Confirma a data de nascimento informada pelo paciente antes de assinar.

    Retorna True se a data confere com o cadastro do paciente no Dental
    Office (``Paciente.data_nascimento``, obrigatório para gerar qualquer
    contrato — ver services/checklist.py). Em caso de erro, incrementa o
    contador de tentativas da sessão e, ao atingir o limite, cancela a
    sessão e levanta SessaoInvalida("identidade_bloqueada") — impede
    adivinhação por força bruta (a data de nascimento tem baixa entropia).
    """

    nascimento = sessao.contrato.paciente.data_nascimento
    if nascimento is not None and data_informada == nascimento:
        sessao.identidade_confirmada_em = timezone.now()
        sessao.save(update_fields=["identidade_confirmada_em", "atualizado_em"])
        registrar_evento(sessao.contrato, "identidade_confirmada", sessao=sessao)
        return True

    sessao.tentativas_identidade += 1
    sessao.save(update_fields=["tentativas_identidade", "atualizado_em"])

    if sessao.tentativas_identidade >= LIMITE_TENTATIVAS_IDENTIDADE:
        sessao.status = "cancelada"
        sessao.save(update_fields=["status", "atualizado_em"])
        registrar_evento(
            sessao.contrato,
            "identidade_bloqueada",
            sessao=sessao,
            tentativas=sessao.tentativas_identidade,
        )
        contrato = sessao.contrato
        if contrato.status == "aguardando_assinatura":
            contrato.status = "gerado"
            contrato.save(update_fields=["status", "atualizado_em"])
        raise SessaoInvalida("identidade_bloqueada")

    return False


def processar_assinatura(
    sessao: "SessaoAssinatura",
    assinatura_data_url: str,
    ip: str | None,
    user_agent: str,
) -> "ContratoGerado":
    """Valida a imagem, faz o claim atômico da sessão e gera o PDF assinado.

    Raises AssinaturaInvalida (imagem ruim) ou SessaoInvalida (corrida com
    outra assinatura / sessão não mais ativa).
    """

    from gestao_contratos.models import SessaoAssinatura

    from .assinatura_pdf import aplicar_assinatura_no_pdf

    png_bytes = _validar_png(assinatura_data_url)

    # Claim atômico: apenas uma requisição consegue a transição → assinada.
    agora = timezone.now()
    claimed = SessaoAssinatura.objects.filter(
        pk=sessao.pk,
        status__in=["pendente", "aberta"],
        expira_em__gt=agora,
    ).update(
        status="assinada",
        assinada_em=agora,
        ip_assinatura=ip,
        user_agent=user_agent[:2000],
    )
    if not claimed:
        raise SessaoInvalida("ja_assinada")

    sessao.refresh_from_db()
    contrato = sessao.contrato
    registrar_evento(sessao.contrato, "assinatura_concluida", sessao=sessao, ip=ip)

    try:
        pdf_original = _obter_pdf_original(contrato)
        carimbo = (
            f"Assinado eletronicamente pelo paciente em "
            f"{agora.astimezone().strftime('%d/%m/%Y %H:%M')}"
            f"{f' — IP {ip}' if ip else ''} — ABO Goiás"
        )
        pdf_assinado = aplicar_assinatura_no_pdf(pdf_original, png_bytes, carimbo)
    except Exception:
        # Reverte o claim para permitir nova tentativa do paciente.
        sessao.status = "aberta"
        sessao.assinada_em = None
        sessao.save(update_fields=["status", "assinada_em", "atualizado_em"])
        logger.exception(
            "processar_assinatura: falha ao gerar PDF assinado (sessao=%s)",
            sessao.pk,
        )
        raise

    base_nome = contrato.arquivo_pdf.name.rsplit("/", 1)[-1].removesuffix(".pdf")
    if not base_nome:
        base_nome = f"contrato_{contrato.pk}"

    hash_original = contrato.hash_sha256
    sessao.assinatura_imagem.save(
        f"assinatura_sessao_{sessao.pk}.png", ContentFile(png_bytes), save=True
    )
    contrato.arquivo_pdf_assinado.save(
        f"{base_nome}_assinado.pdf", ContentFile(pdf_assinado), save=False
    )
    contrato.status = "assinado"
    contrato.hash_sha256 = hashlib.sha256(pdf_assinado).hexdigest()
    contrato.save()

    registrar_evento(
        contrato,
        "documento_assinado_salvo",
        sessao=sessao,
        hash_original=hash_original,
        hash_assinado=contrato.hash_sha256,
    )

    # Dispara o upload ao Dental Office em segundo plano (Celery), com
    # retry automático — o paciente não espera por isso, e uma falha
    # temporária de rede não perde o documento assinado.
    #
    # O enfileiramento em si (.delay) roda de forma síncrona nesta mesma
    # requisição e pode falhar se o broker/Redis estiver indisponível —
    # isso NUNCA pode derrubar a confirmação de assinatura do paciente,
    # que já foi salva com sucesso acima. Em caso de falha, registra o
    # evento e segue: o envio manual ("Enviar para o Dental Office")
    # continua disponível para o staff.
    if contrato.paciente.id_dental:
        try:
            from gestao_contratos.tasks import enviar_dental_task

            enviar_dental_task.delay(contrato.pk)
        except Exception as exc:
            logger.exception(
                "processar_assinatura: falha ao agendar envio ao Dental "
                "Office (contrato=%s)",
                contrato.pk,
            )
            registrar_evento(
                contrato,
                "envio_dental_erro",
                erro=f"Falha ao agendar envio automático: {exc}",
            )
    else:
        logger.info(
            "processar_assinatura: paciente sem id_dental — upload ao "
            "Dental Office não agendado (contrato=%s)",
            contrato.pk,
        )

    # Dispara o envio por WhatsApp em segundo plano, independente do envio
    # ao Dental Office — o paciente deve receber sua cópia mesmo que a
    # integração com o Dental falhe. Só é agendado quando a Meta Cloud API
    # está configurada (sem credenciais, o fluxo manual — link wa.me na
    # tela de pós-geração — continua sendo o único caminho) e o paciente
    # tem celular cadastrado.
    from .whatsapp import whatsapp_configurado

    if whatsapp_configurado() and contrato.paciente.celular:
        try:
            from gestao_contratos.tasks import enviar_whatsapp_task

            enviar_whatsapp_task.delay(contrato.pk)
        except Exception as exc:
            logger.exception(
                "processar_assinatura: falha ao agendar envio por WhatsApp "
                "(contrato=%s)",
                contrato.pk,
            )
            registrar_evento(
                contrato,
                "whatsapp_erro",
                erro=f"Falha ao agendar envio automático: {exc}",
            )

    return contrato


def _obter_pdf_original(contrato: "ContratoGerado") -> bytes:
    """Lê o PDF salvo do contrato ou o regenera a partir dos metadados."""

    from .documentos import gerar_pdf

    if contrato.arquivo_pdf:
        try:
            contrato.arquivo_pdf.open("rb")
            conteudo = contrato.arquivo_pdf.read()
            contrato.arquivo_pdf.close()
            return conteudo
        except Exception:
            logger.warning(
                "assinatura: PDF salvo ilegível (contrato=%s), regenerando",
                contrato.pk,
            )

    return gerar_pdf(
        paciente=contrato.paciente,
        tipo=contrato.tipo,
        profissional_nome=contrato.profissional_nome,
        profissional_cro=contrato.profissional_cro,
        local_assinatura=contrato.local_assinatura,
    )


# ── Eventos ───────────────────────────────────────────────────────────────────


def registrar_evento(
    contrato: "ContratoGerado",
    tipo: str,
    sessao: "SessaoAssinatura | None" = None,
    **payload,
) -> None:
    """Grava um evento na trilha do contrato (auditoria + status na UI)."""

    from gestao_contratos.models import EventoContrato

    EventoContrato.objects.create(
        contrato=contrato,
        sessao=sessao,
        tipo=tipo,
        payload=payload,
    )


# ── Validação da imagem ───────────────────────────────────────────────────────


def _validar_png(data_url: str) -> bytes:
    """Decodifica e valida o PNG do canvas; retorna os bytes da imagem."""

    if not data_url:
        raise AssinaturaInvalida("Nenhuma assinatura foi enviada.")

    conteudo = data_url
    if conteudo.startswith("data:"):
        _, _, conteudo = conteudo.partition(",")

    try:
        png_bytes = base64.b64decode(conteudo, validate=True)
    except (binascii.Error, ValueError):
        raise AssinaturaInvalida("Assinatura em formato inválido.")

    if len(png_bytes) > _ASSINATURA_MAX_BYTES:
        raise AssinaturaInvalida("Imagem de assinatura muito grande.")

    try:
        from PIL import Image

        imagem = Image.open(io.BytesIO(png_bytes))
        imagem.verify()
        formato = imagem.format
        largura, altura = imagem.size
    except Exception:
        raise AssinaturaInvalida("Imagem de assinatura corrompida.")

    if formato != "PNG":
        raise AssinaturaInvalida("A assinatura deve ser uma imagem PNG.")
    if largura < _ASSINATURA_MIN_LARGURA or altura < _ASSINATURA_MIN_ALTURA:
        raise AssinaturaInvalida("Assinatura muito pequena — tente novamente.")

    return png_bytes
