"""Servico de sincronizacao de dados entre Dental Office e banco local."""

from __future__ import annotations

import time

from django.utils import timezone
from gestao_lab.integrations.dental import (
    DentalClient,
    normalizar_aluno_lab,
    normalizar_paciente,
)
from gestao_lab.models import AlunoLab, OrigemDados, Paciente

ResultadoSync = dict[str, int]


def sincronizar_pacientes(clinic_id: int) -> ResultadoSync:
    """Busca todos os pacientes do Dental Office e faz upsert no banco local.

    Itera todas as paginas do endpoint /customers, cria ou atualiza cada
    registro usando id_dental como chave. Retorna criados, atualizados e ignorados.
    """
    client = DentalClient()
    criados = atualizados = ignorados = 0
    agora = timezone.now()

    page = 1
    total_pages = 1

    while page <= total_pages:
        resposta = client.listar_pacientes(clinic_id=clinic_id, page=page)
        total_pages = int(resposta.get("total_pages") or 1)

        for item in resposta.get("results") or []:
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

        page += 1

    return {"criados": criados, "atualizados": atualizados, "ignorados": ignorados}


def sincronizar_alunos(user_group: int) -> ResultadoSync:
    """Busca todos os alunos (usuarios do grupo especificado) e faz upsert local.

    Itera todas as paginas do endpoint /users filtrando por user_group,
    cria ou atualiza cada AlunoLab usando id_dental como chave.
    """
    client = DentalClient()
    criados = atualizados = ignorados = 0
    agora = timezone.now()

    page = 1
    total_pages = 1

    while page <= total_pages:
        resposta = client.listar_usuarios(user_group=user_group, page=page)
        total_pages = int(resposta.get("total_pages") or 1)

        for item in resposta.get("results") or []:
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

        page += 1

    return {"criados": criados, "atualizados": atualizados, "ignorados": ignorados}


def buscar_e_importar_pacientes(q: str, clinic_id: int) -> ResultadoSync:
    """Busca pacientes no Dental Office pelo nome e faz upsert apenas dos resultados.

    Usa apenas a primeira página da API com filtro por nome — adequado para
    importação pontual durante o cadastro de pedidos.
    """
    client = DentalClient()
    criados = atualizados = ignorados = 0
    agora = timezone.now()

    resposta = client.listar_pacientes(clinic_id=clinic_id, page=1, q=q)
    for item in resposta.get("results") or []:
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
    """Busca alunos no Dental Office pelo nome e faz upsert apenas dos resultados.

    Usa apenas a primeira página da API com filtro por nome — adequado para
    importação pontual durante o cadastro de pedidos e moldagens.
    """
    client = DentalClient()
    criados = atualizados = ignorados = 0
    agora = timezone.now()

    resposta = client.listar_usuarios(user_group=user_group, page=1, q=q)
    for item in resposta.get("results") or []:
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
