"""Carimbo de tempo (RFC 3161) sobre o hash do PDF assinado.

Complementa a assinatura eletrônica com uma evidência independente do
relógio do servidor: uma autoridade de carimbo do tempo (TSA) de terceiros
atesta, de forma criptograficamente verificável, que aquele hash já
existia em determinado momento. O token (TSR) recebido é armazenado
integralmente — ele é a própria evidência, verificável mais tarde com o
certificado público da TSA, independente deste sistema — e também
embutido como anexo no próprio PDF assinado (ver
_embutir_carimbo_no_pdf_assinado), para que o documento baixado já leve
sua prova de data/hora, sem depender de um .tsr avulso.

Desativado por padrão: sem CARIMBO_TEMPO_TSA_URL configurada,
carimbo_tempo_configurado() retorna False e nenhuma chamada externa é
feita — o restante do fluxo de assinatura permanece inalterado.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import timezone as dt_timezone
from typing import TYPE_CHECKING

from django.core.files.base import ContentFile

if TYPE_CHECKING:
    from gestao_contratos.models import ContratoGerado

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigCarimboTempo:
    """Configuração necessária para solicitar o carimbo de tempo."""

    url: str
    username: str
    password: str
    timeout: int


def carregar_config_carimbo_tempo() -> ConfigCarimboTempo | None:
    """Carrega a configuração da TSA a partir do ambiente.

    Retorna None se CARIMBO_TEMPO_TSA_URL não estiver definida — o
    chamador deve tratar isso como "carimbo de tempo desativado", não
    como um erro.
    """

    url = os.environ.get("CARIMBO_TEMPO_TSA_URL", "").strip()
    if not url:
        return None

    return ConfigCarimboTempo(
        url=url,
        username=os.environ.get("CARIMBO_TEMPO_TSA_USERNAME", "").strip(),
        password=os.environ.get("CARIMBO_TEMPO_TSA_PASSWORD", "").strip(),
        timeout=int(os.environ.get("CARIMBO_TEMPO_TIMEOUT", "30")),
    )


def carimbo_tempo_configurado() -> bool:
    """True se há uma TSA configurada no ambiente."""

    return carregar_config_carimbo_tempo() is not None


def solicitar_carimbo(contrato: "ContratoGerado") -> tuple[bool, str]:
    """Solicita à TSA um carimbo de tempo sobre o hash do PDF assinado.

    Espera que ``contrato.hash_sha256`` já reflita o PDF assinado (ver
    services/assinatura.processar_assinatura, que salva o hash antes de
    agendar esta etapa). Retorna (True, "") em sucesso — com o token
    salvo em ``contrato.carimbo_tempo`` e a data atestada pela TSA em
    ``contrato.carimbo_tempo_em`` — ou (False, erro). Não é chamada
    quando carimbo_tempo_configurado() é False.
    """

    from .assinatura import registrar_evento

    config = carregar_config_carimbo_tempo()
    if config is None:
        erro = "Carimbo de tempo não configurado."
        return False, erro

    if not contrato.hash_sha256:
        erro = "Contrato sem hash calculado — não é possível solicitar o carimbo."
        logger.error("solicitar_carimbo: %s (contrato_pk=%s)", erro, contrato.pk)
        _marcar_erro(contrato, erro)
        return False, erro

    registrar_evento(contrato, "carimbo_tempo_iniciado", tsa=config.url)

    import rfc3161ng

    try:
        digest = bytes.fromhex(contrato.hash_sha256)
        timestamper = rfc3161ng.RemoteTimestamper(
            config.url,
            username=config.username or None,
            password=config.password or None,
            hashname="sha256",
            include_tsa_certificate=True,
            timeout=config.timeout,
        )
        token = timestamper.timestamp(digest=digest)
        # rfc3161ng retorna um datetime "naive" que representa o genTime
        # do token (GeneralizedTime, sempre em UTC pelo padrão RFC 3161).
        atestado_em_utc = rfc3161ng.get_timestamp(token).replace(tzinfo=dt_timezone.utc)
    except Exception as exc:
        erro = str(exc) or exc.__class__.__name__
        logger.error("solicitar_carimbo: %s (contrato_pk=%s)", erro, contrato.pk)
        _marcar_erro(contrato, erro)
        return False, erro

    contrato.carimbo_tempo.save(
        f"carimbo_{contrato.pk}.tsr", ContentFile(token), save=False
    )
    contrato.carimbo_tempo_em = atestado_em_utc
    contrato.carimbo_tempo_tsa = config.url
    contrato.status_carimbo_tempo = "concluido"

    _embutir_carimbo_no_pdf_assinado(contrato, token)

    contrato.save(
        update_fields=[
            "carimbo_tempo",
            "carimbo_tempo_em",
            "carimbo_tempo_tsa",
            "status_carimbo_tempo",
            "arquivo_pdf_assinado",
            "atualizado_em",
        ]
    )
    registrar_evento(
        contrato,
        "carimbo_tempo_concluido",
        tsa=config.url,
        carimbo_tempo_em=contrato.carimbo_tempo_em.isoformat(),
    )
    return True, ""


def _embutir_carimbo_no_pdf_assinado(contrato: "ContratoGerado", token: bytes) -> None:
    """Reescreve o PDF assinado embutindo o token como anexo — o arquivo
    passa a ser autocontido, sem depender do .tsr avulso para carregar a
    prova do carimbo de tempo.

    Passo de melhor esforço: uma falha aqui não desfaz o carimbo em si
    (já salvo em contrato.carimbo_tempo) nem impede solicitar_carimbo()
    de retornar sucesso — apenas fica registrada em log.
    """

    if not contrato.arquivo_pdf_assinado:
        logger.warning(
            "solicitar_carimbo: sem PDF assinado para embutir o carimbo "
            "(contrato=%s)",
            contrato.pk,
        )
        return

    from .assinatura_pdf import anexar_carimbo_tempo

    try:
        contrato.arquivo_pdf_assinado.open("rb")
        pdf_atual = contrato.arquivo_pdf_assinado.read()
        contrato.arquivo_pdf_assinado.close()
        pdf_com_carimbo = anexar_carimbo_tempo(pdf_atual, token)
    except Exception:
        logger.exception(
            "solicitar_carimbo: falha ao embutir o carimbo no PDF assinado "
            "(contrato=%s)",
            contrato.pk,
        )
        return

    nome_arquivo = contrato.arquivo_pdf_assinado.name.rsplit("/", 1)[-1]
    contrato.arquivo_pdf_assinado.delete(save=False)
    contrato.arquivo_pdf_assinado.save(
        nome_arquivo, ContentFile(pdf_com_carimbo), save=False
    )


def _marcar_erro(contrato: "ContratoGerado", erro: str) -> None:
    from .assinatura import registrar_evento

    contrato.status_carimbo_tempo = "erro"
    contrato.save(update_fields=["status_carimbo_tempo", "atualizado_em"])
    registrar_evento(contrato, "carimbo_tempo_erro", erro=erro)
