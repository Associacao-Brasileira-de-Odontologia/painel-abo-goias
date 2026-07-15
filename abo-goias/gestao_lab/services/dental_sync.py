"""Servico de sincronizacao de dados entre Dental Office e banco local."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from django.utils import timezone
from gestao_lab.integrations.dental import (
    AlunoLabDental,
    DentalAPIError,
    DentalClient,
    PacienteDental,
    normalizar_aluno_lab,
    normalizar_paciente,
    normalizar_paciente_detalhado,
)
from gestao_lab.models import AlunoLab, OrigemDados, Paciente

logger = logging.getLogger(__name__)

ResultadoSync = dict[str, int]

# Salvaguarda contra total_pages inconsistente/instavel na API — a 500
# registros por pagina (o maior ja observado), cobre ate 30 mil registros
# antes de interromper e logar um aviso, bem acima do maior volume descrito
# como cenario de uso (milhares de pacientes).
_MAX_PAGINAS_SEGURANCA = 1000


def listar_todas_paginas(
    buscar_pagina: Callable[[int], dict[str, Any]],
    *,
    contexto: str,
    max_paginas: int = _MAX_PAGINAS_SEGURANCA,
) -> list[dict[str, Any]]:
    """Consolida todos os itens de um endpoint paginado do Dental Office.

    ``buscar_pagina(page)`` deve retornar a resposta bruta da API para a
    página informada — um dict com ``results`` (lista de itens) e,
    opcionalmente, ``total_pages``. Esta função chama ``buscar_pagina``
    para as páginas de 1 até ``total_pages`` (relido a cada resposta),
    consolidando os itens de todas as páginas numa única lista, **na
    ordem devolvida pela API** e **sem duplicatas** (comparadas pelo
    campo ``id`` de cada item) — a mesma lógica serve para qualquer
    quantidade de páginas, de uma busca com poucos resultados a uma
    sincronização completa com milhares de registros.

    Uma resposta sem ``total_pages`` é tratada como página única — mesmo
    comportamento já assumido pelo restante do projeto quando a API não
    informa esse metadado. Uma página vazia interrompe a iteração como
    salvaguarda contra ``total_pages`` inconsistente; ``max_paginas``
    evita um loop indefinido caso a API sempre reporte mais páginas do
    que realmente existem.

    Uma falha de rede/API em qualquer página interrompe a consolidação e
    propaga a exceção (``DentalAPIError`` ou subtipo) — os itens já
    coletados até ali são descartados pelo chamador, que decide como
    reagir (ex.: exibir mensagem de erro, ou marcar uma sincronização
    como falha). Isso preserva o comportamento já esperado por quem
    consome esta função: um erro nunca deve ser confundido com "não há
    mais resultados".

    ``contexto`` identifica a chamada nos logs estruturados (ex.:
    ``"pacientes:busca"``, ``"alunos:sincronizacao_completa"``) — nunca
    inclui o termo de busca (pode conter nome de paciente).
    """

    itens: list[dict[str, Any]] = []
    ids_vistos: set[Any] = set()
    duplicados_ignorados = 0
    page = 1
    total_pages = 1
    inicio = time.monotonic()

    while page <= total_pages:
        if page > max_paginas:
            logger.warning(
                "dental.paginacao_limite_atingido contexto=%s max_paginas=%s "
                "total_pages_reportado=%s registros_ate_agora=%s",
                contexto,
                max_paginas,
                total_pages,
                len(itens),
            )
            break

        try:
            resposta = buscar_pagina(page)
        except DentalAPIError:
            logger.error(
                "dental.paginacao_interrompida contexto=%s pagina=%s "
                "registros_ate_agora=%s",
                contexto,
                page,
                len(itens),
            )
            raise

        resultados = resposta.get("results") or []
        total_pages = int(resposta.get("total_pages") or 1)

        logger.info(
            "dental.paginacao contexto=%s pagina=%s total_pages=%s "
            "registros_pagina=%s",
            contexto,
            page,
            total_pages,
            len(resultados),
        )

        if not resultados:
            break

        for item in resultados:
            id_item = item.get("id")
            if id_item is not None:
                if id_item in ids_vistos:
                    duplicados_ignorados += 1
                    continue
                ids_vistos.add(id_item)
            itens.append(item)

        page += 1

    logger.info(
        "dental.paginacao_concluida contexto=%s total_pages=%s total_registros=%s "
        "duplicados_ignorados=%s duracao_ms=%d",
        contexto,
        total_pages,
        len(itens),
        duplicados_ignorados,
        int((time.monotonic() - inicio) * 1000),
    )

    return itens


def sincronizar_pacientes(clinic_id: int) -> ResultadoSync:
    """Busca todos os pacientes do Dental Office e faz upsert no banco local.

    Percorre todas as páginas do endpoint /customers (ver
    :func:`listar_todas_paginas`), cria ou atualiza cada registro usando
    id_dental como chave. Retorna criados, atualizados e ignorados.
    """
    client = DentalClient()
    criados = atualizados = ignorados = 0
    agora = timezone.now()

    itens = listar_todas_paginas(
        lambda page: client.listar_pacientes(clinic_id=clinic_id, page=page),
        contexto="pacientes:sincronizacao_completa",
    )

    for item in itens:
        paciente = normalizar_paciente(item)
        if not paciente:
            ignorados += 1
            continue

        _, criado = Paciente.objects.update_or_create(
            id_dental=str(paciente.id),
            defaults={
                "nome": paciente.nome,
                "celular": paciente.celular,
                "processo_aberto": paciente.ativo,
                "ativo": paciente.ativo,
                "origem": OrigemDados.DENTAL,
                "ultima_sincronizacao": agora,
            },
        )
        if criado:
            criados += 1
        else:
            atualizados += 1

    return {"criados": criados, "atualizados": atualizados, "ignorados": ignorados}


def sincronizar_alunos(user_group: int) -> ResultadoSync:
    """Busca todos os alunos (usuarios do grupo especificado) e faz upsert local.

    Percorre todas as páginas do endpoint /users filtrando por user_group
    (ver :func:`listar_todas_paginas`), cria ou atualiza cada AlunoLab
    usando id_dental como chave.
    """
    client = DentalClient()
    criados = atualizados = ignorados = 0
    agora = timezone.now()

    itens = listar_todas_paginas(
        lambda page: client.listar_usuarios(user_group=user_group, page=page),
        contexto="alunos:sincronizacao_completa",
    )

    for item in itens:
        aluno = normalizar_aluno_lab(item)
        if not aluno:
            ignorados += 1
            continue

        _, criado = AlunoLab.objects.update_or_create(
            id_dental=str(aluno.id),
            defaults={
                "nome": aluno.nome,
                "celular": aluno.celular,
                "ativo": aluno.ativo,
                "origem": OrigemDados.DENTAL,
                "ultima_sincronizacao": agora,
            },
        )
        if criado:
            criados += 1
        else:
            atualizados += 1

    return {"criados": criados, "atualizados": atualizados, "ignorados": ignorados}


# ---------------------------------------------------------------------------
# Busca para o autocomplete: leitura sem gravar + gravacao so do escolhido
# ---------------------------------------------------------------------------
#
# O autocomplete do formulario nao pode usar `buscar_e_importar_*`: aquelas
# funcoes percorrem TODAS as paginas e gravam TODOS os resultados (uma busca por
# "Gustavo" chegou a importar 149 pacientes e levar ~9s). Aqui a busca le apenas
# a primeira pagina e nao grava nada; o registro so vai para o banco quando o
# operador escolhe um resultado (`materializar_*`) — um write, no clique.


def procurar_pacientes(
    q: str, clinic_id: int, page: int = 1
) -> tuple[list[PacienteDental], int]:
    """Procura pacientes no Dental Office sem gravar nada.

    Retorna os itens da pagina pedida e o total de paginas informado pela API
    (usado para avisar que ha mais resultados do que os exibidos).
    """

    client = DentalClient()
    resposta = client.listar_pacientes(clinic_id=clinic_id, page=page, q=q)
    itens = [
        paciente
        for paciente in (
            normalizar_paciente(item) for item in (resposta.get("results") or [])
        )
        if paciente
    ]
    return itens, int(resposta.get("total_pages") or 1)


def procurar_alunos(
    q: str, user_group: int, page: int = 1
) -> tuple[list[AlunoLabDental], int]:
    """Procura alunos no Dental Office sem gravar nada."""

    client = DentalClient()
    resposta = client.listar_usuarios(user_group=user_group, page=page, q=q)
    itens = [
        aluno
        for aluno in (
            normalizar_aluno_lab(item) for item in (resposta.get("results") or [])
        )
        if aluno
    ]
    return itens, int(resposta.get("total_pages") or 1)


def materializar_paciente(id_dental: str, clinic_id: int) -> Paciente | None:
    """Garante um Paciente local para o id informado, criando se ainda nao existe.

    Chamada quando o operador escolhe um resultado da busca. Os dados vem do
    proprio Dental Office (GET /customers/{id}), nunca do cliente — o navegador
    so informa qual id foi escolhido. Aproveita a chamada para ja trazer os
    campos enriquecidos (CPF, endereco...) usados na geracao de contratos.
    """

    existente = Paciente.objects.filter(id_dental=str(id_dental)).first()
    if existente:
        return existente

    dados = DentalClient().buscar_detalhes_paciente(id_dental)
    paciente = normalizar_paciente(dados)
    if not paciente:
        return None

    defaults: dict[str, Any] = {
        "nome": paciente.nome,
        "celular": paciente.celular,
        "processo_aberto": paciente.ativo,
        "ativo": paciente.ativo,
        "origem": OrigemDados.DENTAL,
        "ultima_sincronizacao": timezone.now(),
    }
    defaults.update(normalizar_paciente_detalhado(dados))

    obj, _ = Paciente.objects.update_or_create(
        id_dental=str(paciente.id), defaults=defaults
    )
    return obj


def materializar_aluno(
    id_dental: str, nome_hint: str, user_group: int
) -> AlunoLab | None:
    """Garante um AlunoLab local para o id informado, criando se ainda nao existe.

    A API nao expoe um GET /users/{id}, entao a busca por nome e refeita e o
    registro e localizado pelo id — ``nome_hint`` serve apenas como filtro da
    consulta; os dados gravados vem sempre da resposta da API.
    """

    existente = AlunoLab.objects.filter(id_dental=str(id_dental)).first()
    if existente:
        return existente

    itens, _ = procurar_alunos(q=nome_hint, user_group=user_group)
    alvo = next((aluno for aluno in itens if str(aluno.id) == str(id_dental)), None)
    if not alvo:
        return None

    obj, _ = AlunoLab.objects.update_or_create(
        id_dental=str(alvo.id),
        defaults={
            "nome": alvo.nome,
            "celular": alvo.celular,
            "ativo": alvo.ativo,
            "origem": OrigemDados.DENTAL,
            "ultima_sincronizacao": timezone.now(),
        },
    )
    return obj


def buscar_e_importar_pacientes(q: str, clinic_id: int) -> ResultadoSync:
    """Busca pacientes no Dental Office pelo nome e faz upsert de todos os resultados.

    Percorre **todas** as páginas retornadas pela API para o filtro de
    busca (ver :func:`listar_todas_paginas`) — antes, apenas a primeira
    página era usada, ocultando resultados quando a busca retornava mais
    pacientes do que o limite por página da API.
    """
    client = DentalClient()
    criados = atualizados = ignorados = 0
    agora = timezone.now()

    itens = listar_todas_paginas(
        lambda page: client.listar_pacientes(clinic_id=clinic_id, page=page, q=q),
        contexto="pacientes:busca",
    )

    for item in itens:
        paciente = normalizar_paciente(item)
        if not paciente:
            ignorados += 1
            continue
        _, criado = Paciente.objects.update_or_create(
            id_dental=str(paciente.id),
            defaults={
                "nome": paciente.nome,
                "celular": paciente.celular,
                "processo_aberto": paciente.ativo,
                "ativo": paciente.ativo,
                "origem": OrigemDados.DENTAL,
                "ultima_sincronizacao": agora,
            },
        )
        if criado:
            criados += 1
        else:
            atualizados += 1

    return {"criados": criados, "atualizados": atualizados, "ignorados": ignorados}


def buscar_e_importar_alunos(q: str, user_group: int) -> ResultadoSync:
    """Busca alunos no Dental Office pelo nome e faz upsert de todos os resultados.

    Percorre **todas** as páginas retornadas pela API para o filtro de
    busca (ver :func:`listar_todas_paginas`) — mesma correção aplicada a
    :func:`buscar_e_importar_pacientes`.
    """
    client = DentalClient()
    criados = atualizados = ignorados = 0
    agora = timezone.now()

    itens = listar_todas_paginas(
        lambda page: client.listar_usuarios(user_group=user_group, page=page, q=q),
        contexto="alunos:busca",
    )

    for item in itens:
        aluno = normalizar_aluno_lab(item)
        if not aluno:
            ignorados += 1
            continue
        _, criado = AlunoLab.objects.update_or_create(
            id_dental=str(aluno.id),
            defaults={
                "nome": aluno.nome,
                "celular": aluno.celular,
                "ativo": aluno.ativo,
                "origem": OrigemDados.DENTAL,
                "ultima_sincronizacao": agora,
            },
        )
        if criado:
            criados += 1
        else:
            atualizados += 1

    return {"criados": criados, "atualizados": atualizados, "ignorados": ignorados}


def executar_sync_e_registrar(
    clinic_id: int,
    user_group: int,
    disparado_por: str = "",
    tipo: str = "COMPLETA",
) -> object:
    """Executa a sincronização completa e persiste o resultado em RegistroSync.

    Registra início, fim, duração e resultado (sucesso/erro) para que o
    histórico fique disponível na interface e para diagnóstico de falhas
    na sincronização agendada.
    """
    from gestao_lab.models import RegistroSync

    registro = RegistroSync.objects.create(tipo=tipo, disparado_por=disparado_por)
    inicio = time.monotonic()

    try:
        rp = sincronizar_pacientes(clinic_id=clinic_id)
        ra = sincronizar_alunos(user_group=user_group)
        registro.pacientes_criados = rp["criados"]
        registro.pacientes_atualizados = rp["atualizados"]
        registro.alunos_criados = ra["criados"]
        registro.alunos_atualizados = ra["atualizados"]
        registro.sucesso = True
    except Exception as exc:
        registro.erro = str(exc)
        registro.sucesso = False
        raise
    finally:
        registro.duracao_segundos = round(time.monotonic() - inicio, 2)
        registro.save()

    return registro
