"""Consultas das telas de Movimentações e Visão Geral.

Segue o mesmo arranjo que `gestao_contratos` já usava (`services/` por
responsabilidade): aqui mora o que monta e recorta querysets, deixando as views
com o papel de ler o request, chamar daqui e entregar ao template.

Fora daqui ficam de propósito: leitura de `request.GET` (parsing de request) e
rótulos/classes de CSS (texto de interface) — os dois continuam nas views.
"""

from __future__ import annotations

from datetime import date, datetime

from django.db.models import Count, Min, Q
from django.db.models.query import QuerySet
from django.utils import timezone

from comum.datas import filtrar_por_intervalo
from gestao_cme.models import Aluno, Movimentacao, OrigemDados
from gestao_cme.utils import normalizar_texto


def linhas_de_pacote() -> QuerySet[Movimentacao]:
    """Queryset base da listagem de movimentacoes: uma linha por pacote.

    Fonte unica da verdade compartilhada entre a listagem (``home``) e os KPIs da
    visao geral (``cme_dashboard``) — os KPIs sao links para esta listagem, entao
    os dois PRECISAM contar exatamente o mesmo conjunto. Calcular em cada lugar
    faria o numero do card divergir da tela que ele abre.

    Exclui as SAIDAs ja vinculadas a uma ENTRADA: elas nao sao linha, sao a
    coluna "Saida" da linha da entrada (ver ``preparar_datas_do_pacote``).
    """

    return Movimentacao.objects.exclude(origem=OrigemDados.EXEMPLO).exclude(
        tipo=Movimentacao.Tipo.SAIDA, entrada_origem__isnull=False
    )


def listagem_de_pacotes() -> QuerySet[Movimentacao]:
    """A base acima, já com os relacionamentos que a listagem renderiza.

    O ``prefetch_related("saidas")`` é o que permite a ``preparar_datas_do_pacote``
    achar a retirada de cada pacote sem uma query por linha.
    """

    return (
        linhas_de_pacote()
        .select_related("aluno", "turma", "material")
        .prefetch_related("saidas")
        .order_by("-data_hora", "-id")
    )


def filtrar_pacotes(
    queryset: QuerySet[Movimentacao],
    *,
    data_inicio: datetime | None = None,
    data_fim: datetime | None = None,
    aluno: Aluno | None = None,
    status: str = "",
    busca: str = "",
) -> QuerySet[Movimentacao]:
    """Aplica os filtros da tela de Movimentações.

    A ordem é a mesma de antes: período, aluno, status e por último a busca
    textual. O filtro por aluno precede a busca porque é um vínculo exato (FK),
    não um termo aproximado.
    """

    queryset = filtrar_por_intervalo(queryset, "data_hora", data_inicio, data_fim)

    if aluno is not None:
        queryset = queryset.filter(aluno=aluno)

    if status == "retirado":
        queryset = queryset.filter(retirado=True)
    elif status == "pendente":
        queryset = queryset.filter(retirado=False)
    elif status == "sem_status":
        queryset = queryset.filter(retirado__isnull=True)

    if busca:
        queryset = queryset.filter(
            # `aluno_nome`/`turma_nome` sao copias textuais do momento do
            # registro (podem existir sem FK, ex.: dados legados); o campo
            # normalizado do aluno cobre a busca sem acento quando ha vinculo.
            Q(aluno_nome__icontains=busca)
            | Q(aluno__nome_normalizado__icontains=normalizar_texto(busca))
            | Q(aluno_codigo_externo__icontains=busca)
            | Q(turma_nome__icontains=busca)
            | Q(pacote_codigo__icontains=busca)
            | Q(arquivo_origem__icontains=busca)
            | Q(material__nome__icontains=busca)
            | Q(material__codigo__icontains=busca)
            | Q(aluno__matricula__icontains=busca)
        ).distinct()

    return queryset


def preparar_datas_do_pacote(registro: Movimentacao) -> None:
    """Define, para uma linha da listagem, as datas de entrada e de saida.

    Anota no proprio objeto (usado so na renderizacao):
      ``data_entrada``      — data da ENTRADA, ou None numa saida legada solta.
      ``data_saida``        — data da retirada, quando conhecida.
      ``saida_sem_registro``— True quando a entrada esta marcada como retirada
                              mas nao existe SAIDA vinculada. Acontece em dados
                              LEGADO (onde o par nao e reconstituivel) e em
                              entradas marcadas manualmente pela edicao. A
                              retirada aconteceu; a data e que nao foi guardada —
                              a tabela mostra isso em vez de fingir uma data.
      ``entrada_sem_registro`` — True numa SAIDA legada sem entrada vinculada.
    """

    registro.saida_sem_registro = False
    registro.entrada_sem_registro = False

    if registro.tipo == Movimentacao.Tipo.SAIDA:
        # Só chega aqui a saída sem vínculo (as vinculadas viram coluna da
        # entrada). Sem entrada conhecida, a linha carrega apenas a saída.
        registro.data_entrada = None
        registro.data_saida = registro.data_hora
        registro.entrada_sem_registro = True
        return

    registro.data_entrada = registro.data_hora
    # `saidas` vem do prefetch; ordena em Python para nao disparar nova query.
    saidas = sorted(registro.saidas.all(), key=lambda s: s.data_hora)
    if saidas:
        registro.data_saida = saidas[0].data_hora
    else:
        registro.data_saida = None
        registro.saida_sem_registro = registro.retirado is True


def contar_pacotes(
    data_inicio: datetime | None, data_fim: datetime | None
) -> dict[str, int]:
    """Totais do período para o rótulo ao lado de "N registros".

    Só o recorte de datas entra aqui: o número precisa descrever o período
    exibido, não o subconjunto que os demais filtros da tela deixaram na tabela.
    """

    return filtrar_por_intervalo(
        linhas_de_pacote(), "data_hora", data_inicio, data_fim
    ).aggregate(
        total=Count("id"),
        pendentes=Count("id", filter=Q(retirado=False)),
        retirados=Count("id", filter=Q(retirado=True)),
    )


def periodo_padrao(hoje: date) -> tuple[str, str]:
    """Intervalo inicial da Visão Geral: do primeiro registro até hoje.

    Abre mostrando todo o histórico, em vez de recortar no mês atual (que
    escondia o passado sem o usuário pedir). Banco vazio: cai para hoje→hoje.
    """

    primeiro = linhas_de_pacote().aggregate(Min("data_hora"))["data_hora__min"]
    inicio = timezone.localtime(primeiro).date() if primeiro else hoje
    return inicio.strftime("%Y-%m-%d"), hoje.strftime("%Y-%m-%d")


def metricas_por_status(
    data_inicio: datetime | None, data_fim: datetime | None
) -> dict[str, int]:
    """KPIs da Visão Geral, mutuamente exclusivos e exaustivos.

    Total = retirados + pendentes + sem_status. Usa a mesma base da listagem
    para que cada card abra exatamente os registros que contou.
    """

    return filtrar_por_intervalo(
        linhas_de_pacote(), "data_hora", data_inicio, data_fim
    ).aggregate(
        total=Count("id"),
        retirados=Count("id", filter=Q(retirado=True)),
        pendentes=Count("id", filter=Q(retirado=False)),
        sem_status=Count("id", filter=Q(retirado__isnull=True)),
    )


def pacotes_aguardando(
    data_inicio: datetime | None, data_fim: datetime | None, limite: int = 10
) -> list[Movimentacao]:
    """Entradas ainda não retiradas, das mais antigas para as mais novas."""

    base = filtrar_por_intervalo(
        linhas_de_pacote(), "data_hora", data_inicio, data_fim
    )
    return list(
        base.filter(tipo=Movimentacao.Tipo.ENTRADA, retirado=False)
        .select_related("aluno", "aluno__turma", "aluno__abrigo")
        .order_by("data_hora")[:limite]
    )


def eventos_recentes(
    data_inicio: datetime | None, data_fim: datetime | None, limite: int = 12
) -> list[dict]:
    """Feed de atividade da Visão Geral.

    É um feed de EVENTOS, não de pacotes: parte de todas as movimentações
    (inclusive as SAIDAs que a listagem absorve na linha da entrada), senão a
    retirada apareceria datada pela data de entrada.
    """

    base = filtrar_por_intervalo(
        Movimentacao.objects.exclude(origem=OrigemDados.EXEMPLO),
        "data_hora",
        data_inicio,
        data_fim,
    )

    eventos: list[dict] = []
    for mov in base.select_related("material").order_by("-data_hora", "-id")[:limite]:
        material = mov.material.nome if mov.material else f"pacote {mov.pacote_codigo}"
        aluno = mov.aluno_nome or "Aluno não informado"
        if mov.tipo == Movimentacao.Tipo.ENTRADA and mov.retirado is False:
            categoria, titulo = "alerta", "Entrada para esterilização"
            descricao = f"{aluno} entregou {material} para esterilização."
        elif mov.tipo == Movimentacao.Tipo.ENTRADA and mov.retirado is True:
            categoria, titulo = "devolucao", "Material retirado"
            descricao = f"{aluno} retirou {material}."
        elif mov.tipo == Movimentacao.Tipo.SAIDA:
            categoria, titulo = "exportacao", "Saída registrada"
            descricao = f"{material} saiu para {aluno}."
        else:
            categoria, titulo = "alerta", "Movimentação"
            descricao = f"{material} — {aluno}."
        eventos.append(
            {
                "categoria": categoria,
                "titulo": titulo,
                "descricao": descricao,
                "data": mov.data_hora,
            }
        )

    return sorted(eventos, key=lambda evento: evento["data"], reverse=True)[:limite]
