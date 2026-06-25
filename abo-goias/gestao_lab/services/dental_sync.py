"""Servico de sincronizacao de dados entre Dental Office e banco local."""

from __future__ import annotations

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
