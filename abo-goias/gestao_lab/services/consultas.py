"""Consultas das telas de Acompanhamento de pedidos e Pacientes.

Mesmo arranjo adotado em `gestao_cme/services/consultas.py`: aqui mora o que
monta e recorta querysets, e as views ficam com ler o request, chamar daqui e
entregar ao template.

Fora daqui ficam de propósito a leitura de `request.GET` e os rótulos de
interface — os dois continuam nas views.
"""

from __future__ import annotations

from datetime import date, datetime

from django.conf import settings
from django.db.models import Min, Q
from django.db.models.query import QuerySet
from django.utils import timezone

from comum.datas import filtrar_por_intervalo
from gestao_cme.utils import normalizar_texto
from gestao_lab.integrations.dental import DentalAPIError
from gestao_lab.models import Paciente, PedidoMaterial

# Importado como módulo, e não como `from ... import procurar_pacientes`: os
# testes substituem `gestao_lab.services.dental_sync.procurar_pacientes`, e um
# nome ligado no momento do import ficaria preso à função original.
from gestao_lab.services import dental_sync

# ---------------------------------------------------------------------------
# Acompanhamento de pedidos
# ---------------------------------------------------------------------------


def listagem_de_pedidos() -> QuerySet[PedidoMaterial]:
    """Base da listagem, com os relacionamentos que a tela renderiza.

    Traz também os concluídos (não só os em aberto): sem eles, as colunas de
    entrega e faturamento nunca teriam conteúdo, porque o pedido sai da tela no
    instante em que é faturado.
    """

    return PedidoMaterial.objects.select_related(
        "paciente", "aluno", "laboratorio", "equipe"
    ).order_by("-criado_em")


def filtrar_pedidos(
    queryset: QuerySet[PedidoMaterial],
    *,
    busca: str = "",
    status: str = "",
    campo_data: str = "criado_em",
    data_inicio: datetime | None = None,
    data_fim: datetime | None = None,
) -> QuerySet[PedidoMaterial]:
    """Aplica os filtros da tela, na ordem de antes: busca, status e período.

    ``campo_data`` é o nome do campo no modelo (já resolvido pela view a partir
    da opção escolhida na tela), porque o período recorta pela data que o
    usuário selecionou — registro, previsão, entrega, faturamento.
    """

    if busca:
        queryset = queryset.filter(
            Q(paciente__nome_normalizado__icontains=normalizar_texto(busca))
            | Q(aluno__nome_normalizado__icontains=normalizar_texto(busca))
            | Q(laboratorio__nome__icontains=busca)
            | Q(descricao_servico__icontains=busca)
        )

    if status:
        queryset = queryset.filter(status=status)

    return filtrar_por_intervalo(queryset, campo_data, data_inicio, data_fim)


def periodo_padrao(hoje: date) -> tuple[str, str]:
    """Intervalo inicial: do primeiro pedido registrado até hoje.

    Mesmo comportamento do CME — abre com todo o histórico em vez de recortar no
    mês atual. Banco vazio: cai para hoje→hoje.
    """

    primeiro = PedidoMaterial.objects.aggregate(Min("criado_em"))["criado_em__min"]
    inicio = timezone.localtime(primeiro).date() if primeiro else hoje
    return inicio.strftime("%Y-%m-%d"), hoje.strftime("%Y-%m-%d")


def metricas_de_pedidos() -> dict[str, int]:
    """Contagem por status dos pedidos que ainda demandam ação.

    Não segue o filtro de período da tela de propósito: descreve a situação
    corrente da operação, não o recorte que o usuário está olhando. "Total" é a
    soma dos três — concluídos ficam de fora.
    """

    metricas = {
        "em_dia": PedidoMaterial.objects.filter(
            status=PedidoMaterial.Status.EM_DIA
        ).count(),
        "atrasado": PedidoMaterial.objects.filter(
            status=PedidoMaterial.Status.ATRASADO
        ).count(),
        "entregue_nao_faturado": PedidoMaterial.objects.filter(
            status=PedidoMaterial.Status.ENTREGUE_NAO_FATURADO
        ).count(),
    }
    metricas["total"] = (
        metricas["em_dia"] + metricas["atrasado"] + metricas["entregue_nao_faturado"]
    )
    return metricas


# ---------------------------------------------------------------------------
# Pacientes — listagem unificada (base local + Dental Office ao vivo)
# ---------------------------------------------------------------------------


def ids_com_pedido_aberto() -> set[int]:
    """Pacientes com algum pedido ainda não concluído."""

    return set(
        PedidoMaterial.objects.exclude(
            status=PedidoMaterial.Status.CONCLUIDO
        ).values_list("paciente_id", flat=True)
    )


def filtrar_pacientes(
    busca: str = "", pedido_filtro: str = "", abertos: set[int] | None = None
) -> QuerySet[Paciente]:
    """Pacientes ativos da base local, com busca por nome ou celular."""

    queryset = Paciente.objects.filter(ativo=True).order_by("nome")
    if busca:
        queryset = queryset.filter(
            Q(nome_normalizado__icontains=normalizar_texto(busca))
            | Q(celular__icontains=busca)
        )
    if pedido_filtro == "aberto":
        queryset = queryset.filter(pk__in=abertos or set())
    return queryset


def linhas_locais(pacientes, abertos: set[int]) -> list[dict]:
    """Converte os pacientes da página em linhas da tabela unificada."""

    return [
        {
            "nome": paciente.nome,
            "celular": paciente.celular,
            "no_sistema": True,
            "tem_pedido_aberto": paciente.pk in abertos,
            "data_previsao_retorno": paciente.data_previsao_retorno,
            "ultima_sincronizacao": paciente.ultima_sincronizacao,
            "id_dental": None,
        }
        for paciente in pacientes
    ]


def linhas_do_dental(busca: str) -> tuple[list[dict], bool, str]:
    """Busca ao vivo no Dental Office, para a mesma tabela da listagem local.

    Traz quem ainda não existe na base local, sem gravar nada — a linha ganha a
    ação "Importar" no template. Quem já existe localmente é descartado para não
    aparecer duas vezes.

    Devolve ``(linhas, ha_mais, erro)``: ``ha_mais`` avisa que a consulta tem
    mais páginas do que a exibida (o usuário deve refinar a busca), e ``erro``
    traz a mensagem quando a integração falha ou não está configurada — nesses
    casos a listagem local continua sendo exibida normalmente.
    """

    clinic_id = getattr(settings, "DENTAL_CLINIC_ID", None)
    if not clinic_id:
        return [], False, "A busca no Dental Office não está configurada."

    try:
        remotos, total_paginas = dental_sync.procurar_pacientes(
            q=busca, clinic_id=clinic_id
        )
    except DentalAPIError as exc:
        return [], False, str(exc)

    ids_locais = set(
        Paciente.objects.filter(ativo=True).values_list("id_dental", flat=True)
    )
    linhas = [
        {
            "nome": pac.nome,
            "celular": pac.celular,
            "no_sistema": False,
            "tem_pedido_aberto": False,
            "data_previsao_retorno": None,
            "ultima_sincronizacao": None,
            "id_dental": str(pac.id),
        }
        for pac in remotos
        if str(pac.id) not in ids_locais
    ]
    return linhas, total_paginas > 1, ""
