from __future__ import annotations

import hashlib
import uuid
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Page, Paginator
from django.db import transaction
from django.db.models import Count, Max, Q
from django.db.models.query import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    AbrigoEditForm,
    AbrigoForm,
    CadastrarAlunoForm,
    CadastrarTurmaForm,
    EmprestimoForm,
    EntradaForm,
    MaterialEditForm,
    MaterialForm,
    MovimentacaoForm,
)
from .integrations.eduq import EduqAPIError
from .models import (
    Abrigo,
    Aluno,
    Emprestimo,
    ItemEmprestimo,
    Kit,
    Material,
    Movimentacao,
    OrigemDados,
    Turma,
)
from .services.eduq_sync import sincronizar_eduq

REGISTROS_POR_PAGINA = 10


def _gerar_row_hash() -> str:
    """Gera um hash unico para movimentacoes criadas manualmente pelo painel."""
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


STATUS_MOVIMENTACAO_OPCOES = (
    ("retirado", "Retirado"),
    ("pendente", "Não retirado"),
    ("sem_status", "Sem status"),
)


def healthcheck(request: HttpRequest) -> HttpResponse:
    """Retorna uma resposta simples para verificacao de disponibilidade.

    Usada por infraestrutura, monitoramento ou plataforma de deploy para
    confirmar que a aplicacao Django esta respondendo requisicoes HTTP.
    """

    return HttpResponse("ok", content_type="text/plain")


def paginar_queryset(
    request: HttpRequest, queryset: QuerySet[Any]
) -> tuple[Page[Any], str]:
    """Pagina um queryset preservando os filtros atuais da query string.

    Remove apenas o parametro ``page`` antes de reconstruir a query string,
    permitindo que templates de paginacao mantenham busca e filtros ativos ao
    navegar entre paginas.
    """

    query_params = request.GET.copy()
    query_params.pop("page", None)
    paginator = Paginator(queryset, REGISTROS_POR_PAGINA)
    page_obj = paginator.get_page(request.GET.get("page"))

    return page_obj, query_params.urlencode()


def emprestimos_visiveis(request: HttpRequest) -> QuerySet[Emprestimo]:
    """Retorna emprestimos que o usuario logado pode visualizar.

    Superusuarios veem todos os emprestimos reais, enquanto coordenadores veem
    somente registros vinculados ao proprio usuario. Dados de exemplo sao
    removidos para nao interferir nos indicadores operacionais.
    """

    queryset = Emprestimo.objects.exclude(
        Q(aluno__origem=OrigemDados.EXEMPLO)
        | Q(aluno__turma__origem=OrigemDados.EXEMPLO)
    )
    if request.user.is_superuser:
        return queryset
    return queryset.filter(coordenador_usuario=request.user)


@login_required
def portal(request: HttpRequest) -> HttpResponse:
    """Renderiza o painel inicial com atividade recente e tarefas pendentes."""

    from gestao_contratos.models import ContratoGerado
    from gestao_lab.models import Moldagem, PedidoMaterial

    movimentacoes_base = Movimentacao.objects.exclude(origem=OrigemDados.EXEMPLO)

    pacotes_pendentes = movimentacoes_base.filter(
        tipo=Movimentacao.Tipo.ENTRADA, retirado=False
    ).count()
    lab_pedidos_ativos = PedidoMaterial.objects.exclude(
        status=PedidoMaterial.Status.CONCLUIDO
    ).count()
    lab_faturamento_pendente = (
        PedidoMaterial.objects.filter(entregue=True)
        .exclude(faturado_paciente=True, faturado_lab=True)
        .count()
    )
    lab_moldagens_pendentes = Moldagem.objects.filter(
        ativo=True, pedido_material=None
    ).count()
    contratos_gerados = ContratoGerado.objects.count()

    resumo = {
        "pacotes_pendentes": pacotes_pendentes,
        "materiais": Material.objects.exclude(origem=OrigemDados.EXEMPLO).count(),
        "turmas": Turma.objects.exclude(origem=OrigemDados.EXEMPLO).count(),
        "lab_pedidos_ativos": lab_pedidos_ativos,
        "lab_pendentes_faturamento": lab_faturamento_pendente,
        "lab_moldagens_pendentes": lab_moldagens_pendentes,
        "contratos_gerados": contratos_gerados,
    }

    # Tarefas que requerem atenção imediata
    tarefas_pendentes = []
    if pacotes_pendentes:
        tarefas_pendentes.append(
            {
                "texto": f"{pacotes_pendentes} pacote(s) aguardando retirada",
                "url_name": "registrar_saida",
                "urgente": False,
            }
        )
    if lab_faturamento_pendente:
        tarefas_pendentes.append(
            {
                "texto": (
                    f"{lab_faturamento_pendente} pedido(s) de lab"
                    " aguardando faturamento"
                ),
                "url_name": "lab_pedidos_faturamento",
                "urgente": False,
            }
        )
    if lab_moldagens_pendentes:
        tarefas_pendentes.append(
            {
                "texto": (
                    f"{lab_moldagens_pendentes} moldagem(ns) sem"
                    " pedido de lab vinculado"
                ),
                "url_name": "lab_moldagens",
                "urgente": False,
            }
        )

    # Atividade recente — agrega dados de todos os módulos
    atividade_recente: list[dict] = []

    for mov in movimentacoes_base.select_related("material").order_by(
        "-data_hora", "-id"
    )[:6]:
        material = mov.material.nome if mov.material else f"pacote {mov.pacote_codigo}"
        aluno = mov.aluno_nome or "Aluno não informado"
        if mov.tipo == Movimentacao.Tipo.ENTRADA:
            categoria, titulo = "devolucao", "Devolução registrada"
            descricao = f"{aluno} devolveu {material}."
        elif mov.retirado is False:
            categoria, titulo = "alerta", "Retirada pendente"
            descricao = f"{aluno} ainda não retirou {material}."
        else:
            categoria, titulo = "alerta", "Saída de material"
            descricao = f"{material} separado para {aluno}."
        atividade_recente.append(
            {
                "categoria": categoria,
                "titulo": titulo,
                "descricao": descricao,
                "data": mov.data_hora,
            }
        )

    for pedido in PedidoMaterial.objects.select_related(
        "paciente", "laboratorio"
    ).order_by("-criado_em")[:5]:
        atividade_recente.append(
            {
                "categoria": "exportacao",
                "titulo": "Pedido de laboratório",
                "descricao": (f"{pedido.paciente.nome} → {pedido.laboratorio.nome}."),
                "data": pedido.criado_em,
            }
        )

    for contrato in ContratoGerado.objects.select_related("paciente").order_by(
        "-criado_em"
    )[:4]:
        atividade_recente.append(
            {
                "categoria": "devolucao",
                "titulo": "Contrato gerado",
                "descricao": (
                    f"{contrato.get_tipo_display()} — {contrato.paciente.nome}."
                ),
                "data": contrato.criado_em,
            }
        )

    atividade_recente = sorted(
        atividade_recente, key=lambda a: a["data"], reverse=True
    )[:8]

    # Ponto único de controle de visibilidade dos apps no portal.
    # Quando grupos de permissão forem implementados, basta filtrar este set
    # com base em request.user.groups — o template não precisa mudar.
    apps_disponiveis = {"cme", "lab", "bancadas", "contratos"}

    return render(
        request,
        "gestao_cme/portal.html",
        {
            "usuario_logado": request.user,
            "resumo": resumo,
            "tarefas_pendentes": tarefas_pendentes,
            "atividade_recente": atividade_recente,
            "apps_disponiveis": apps_disponiveis,
        },
    )


@login_required
def home(request: HttpRequest) -> HttpResponse:
    """Lista movimentacoes de materiais com busca, filtros e metricas.

    Permite filtrar por status de retirada, tipo de movimentacao e texto livre
    em campos de aluno, turma, pacote, arquivo e material. Tambem prepara
    labels de status usados na tabela renderizada.
    """

    busca = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    movimentacao = request.GET.get("movimentacao", "").strip()

    movimentacoes = (
        Movimentacao.objects.exclude(origem=OrigemDados.EXEMPLO)
        .select_related("aluno", "turma", "material")
        .order_by("-data_hora", "-id")
    )

    if status == "retirado":
        movimentacoes = movimentacoes.filter(retirado=True)
    elif status == "pendente":
        movimentacoes = movimentacoes.filter(retirado=False)
    elif status == "sem_status":
        movimentacoes = movimentacoes.filter(retirado__isnull=True)

    if movimentacao in Movimentacao.Tipo.values:
        movimentacoes = movimentacoes.filter(tipo=movimentacao)

    if busca:
        movimentacoes = movimentacoes.filter(
            Q(aluno_nome__icontains=busca)
            | Q(aluno_codigo_externo__icontains=busca)
            | Q(turma_nome__icontains=busca)
            | Q(pacote_codigo__icontains=busca)
            | Q(arquivo_origem__icontains=busca)
            | Q(material__nome__icontains=busca)
            | Q(material__codigo__icontains=busca)
            | Q(aluno__matricula__icontains=busca)
        ).distinct()

    page_obj, query_string = paginar_queryset(request, movimentacoes)
    status_label = dict(STATUS_MOVIMENTACAO_OPCOES).get(status, "Todos")
    movimentacao_label = dict(Movimentacao.Tipo.choices).get(movimentacao, "Todas")

    for registro in page_obj.object_list:
        if registro.retirado is True:
            registro.status_label = "Retirado"
            registro.status_classe = "devolvido"
        elif registro.retirado is False:
            registro.status_label = "Não retirado"
            registro.status_classe = "atrasado"
        else:
            registro.status_label = "Sem status"
            registro.status_classe = "emprestado"
        registro.material_resumo = (
            registro.material.nome if registro.material else "Pacote"
        )

    metricas = Movimentacao.objects.exclude(origem=OrigemDados.EXEMPLO).aggregate(
        total=Count("id"),
        saidas=Count("id", filter=Q(tipo=Movimentacao.Tipo.SAIDA)),
        entradas=Count("id", filter=Q(tipo=Movimentacao.Tipo.ENTRADA)),
        pendentes=Count("id", filter=Q(retirado=False)),
    )

    return render(
        request,
        "gestao_cme/home.html",
        {
            "usuario_logado": request.user,
            "busca": busca,
            "status_atual": status,
            "status_label": status_label,
            "status_opcoes": STATUS_MOVIMENTACAO_OPCOES,
            "movimentacao_atual": movimentacao,
            "movimentacao_label": movimentacao_label,
            "movimentacao_opcoes": Movimentacao.Tipo.choices,
            "movimentacoes": page_obj.object_list,
            "metricas": metricas,
            "page_obj": page_obj,
            "query_string": query_string,
        },
    )


@login_required
def alunos_por_turma(request: HttpRequest) -> HttpResponse:
    """Exibe alunos agrupados por turma com filtros e acao de sincronizacao.

    A view lista cadastros academicos ativos, respeitando a visibilidade do
    usuario logado. Tambem calcula metricas da listagem, turmas disponiveis
    para filtro e a data mais recente de sincronizacao com fontes externas.
    """

    busca = request.GET.get("q", "").strip()
    turma_id = request.GET.get("turma", "").strip()

    alunos = (
        Aluno.objects.exclude(origem=OrigemDados.EXEMPLO)
        .exclude(turma__origem=OrigemDados.EXEMPLO)
        .select_related("turma")
        .order_by("turma__nome", "nome")
    )
    if turma_id.isdigit():
        alunos = alunos.filter(turma_id=turma_id)
    if busca:
        alunos = alunos.filter(
            Q(nome__icontains=busca)
            | Q(matricula__icontains=busca)
            | Q(email__icontains=busca)
            | Q(turma__nome__icontains=busca)
            | Q(turma__codigo__icontains=busca)
        )

    page_obj, query_string = paginar_queryset(request, alunos)
    rows = [
        {
            "cells": [
                {
                    "primary": aluno.turma.nome if aluno.turma else "Sem turma",
                    "secondary": aluno.turma.codigo if aluno.turma else "",
                },
                {"primary": aluno.nome, "secondary": aluno.matricula},
                {"primary": aluno.email or "-", "secondary": aluno.telefone or ""},
                {
                    "badge": "Ativo" if aluno.ativo else "Inativo",
                    "badge_class": (
                        "badge-devolvido" if aluno.ativo else "badge-atrasado"
                    ),
                },
            ]
        }
        for aluno in page_obj.object_list
    ]

    turmas = Turma.objects.exclude(origem=OrigemDados.EXEMPLO).order_by("nome")

    # Resolve turma selecionada para habilitar sincronizacao por turma
    turma_selecionada = None
    if turma_id.isdigit():
        try:
            turma_selecionada = Turma.objects.exclude(origem=OrigemDados.EXEMPLO).get(
                pk=turma_id
            )
        except Turma.DoesNotExist:
            pass

    alunos_base = Aluno.objects.exclude(origem=OrigemDados.EXEMPLO)
    turmas_base = Turma.objects.exclude(origem=OrigemDados.EXEMPLO)

    ultima_sincronizacao_alunos = alunos_base.aggregate(
        ultima=Max("ultima_sincronizacao")
    )["ultima"]
    ultima_sincronizacao_turmas = turmas_base.aggregate(
        ultima=Max("ultima_sincronizacao")
    )["ultima"]
    datas_sincronizacao = [
        data
        for data in (ultima_sincronizacao_alunos, ultima_sincronizacao_turmas)
        if data
    ]
    ultima_sincronizacao = max(datas_sincronizacao) if datas_sincronizacao else None

    metricas = [
        {"label": "Alunos", "value": alunos_base.count()},
        {"label": "Turmas", "value": turmas_base.count()},
        {"label": "Ativos", "value": alunos_base.filter(ativo=True).count()},
        {"label": "Filtrados", "value": page_obj.paginator.count},
    ]

    return render(
        request,
        "gestao_cme/listagem.html",
        {
            "usuario_logado": request.user,
            "titulo": "Alunos por turma",
            "subtitulo": "Consulte os alunos vinculados a cada turma da pós-graduação.",
            "section_label": "Cadastros acadêmicos",
            "active_page": "alunos",
            "busca": busca,
            "metricas": metricas,
            "table_headers": ["Turma", "Aluno", "Contato", "Status"],
            "rows": rows,
            "page_obj": page_obj,
            "query_string": query_string,
            "empty_message": "Nenhum aluno encontrado.",
            "sync_action_url": "sincronizar_turmas_eduq",
            "sync_alunos_url": (
                reverse(
                    "sincronizar_alunos_turma",
                    kwargs={"turma_id": turma_selecionada.pk},
                )
                if turma_selecionada and turma_selecionada.origem == OrigemDados.EDUQ
                else None
            ),
            "sync_alunos_label": (
                f"Sincronizar alunos de {turma_selecionada.nome}"
                if turma_selecionada
                else None
            ),
            "cadastrar_aluno_url": reverse("cadastrar_aluno"),
            "cadastrar_turma_url": reverse("cadastrar_turma"),
            "ultima_sincronizacao": ultima_sincronizacao,
            "filter_select": {
                "name": "turma",
                "label": "Turma",
                "value": turma_id,
                "options": [
                    {"value": str(turma.pk), "label": f"{turma.codigo} - {turma.nome}"}
                    for turma in turmas
                ],
            },
        },
    )


@login_required
@require_POST
def sincronizar_turmas_eduq(request: HttpRequest) -> HttpResponse:
    """Executa a sincronizacao manual de turmas com o Eduq.

    Processa apenas turmas, registra mensagens de sucesso ou erro para a
    interface e redireciona o usuario de volta para a listagem de alunos por
    turma.
    """

    try:
        resultado = sincronizar_eduq(
            sincronizar_turmas=True,
            sincronizar_alunos=False,
        )
    except EduqAPIError as exc:
        messages.error(request, f"Não foi possível sincronizar turmas: {exc}")
    else:
        messages.success(
            request,
            "Turmas sincronizadas: "
            f"{resultado.turmas.criados} criadas, "
            f"{resultado.turmas.atualizados} atualizadas, "
            f"{len(resultado.turmas.erros)} erro(s).",
        )

    return redirect("alunos_por_turma")


@login_required
def armarios(request: HttpRequest) -> HttpResponse:
    """Lista abrigos controlados pela CME com filtros de ocupacao.

    Permite buscar por identificador, filtrar por abrigos ocupados ou livres e
    apresentar metricas de ocupacao para apoiar a gestao fisica dos espacos.
    """

    busca = request.GET.get("q", "").strip()
    ocupacao = request.GET.get("ocupacao", "").strip()

    abrigos = Abrigo.objects.exclude(origem=OrigemDados.EXEMPLO).order_by(
        "identificador"
    )
    if ocupacao == "ocupado":
        abrigos = abrigos.filter(ocupado=True)
    elif ocupacao == "livre":
        abrigos = abrigos.filter(ocupado=False)
    if busca:
        abrigos = abrigos.filter(identificador__icontains=busca)

    page_obj, query_string = paginar_queryset(request, abrigos)
    abrigos_base = Abrigo.objects.exclude(origem=OrigemDados.EXEMPLO)
    metricas = {
        "total": abrigos_base.count(),
        "ocupados": abrigos_base.filter(ocupado=True).count(),
        "livres": abrigos_base.filter(ocupado=False).count(),
        "filtrados": page_obj.paginator.count,
    }

    return render(
        request,
        "gestao_cme/armarios.html",
        {
            "usuario_logado": request.user,
            "busca": busca,
            "ocupacao_atual": ocupacao,
            "ocupacao_label": {"ocupado": "Ocupados", "livre": "Livres"}.get(
                ocupacao, "Todos"
            ),
            "metricas": metricas,
            "abrigos": page_obj.object_list,
            "page_obj": page_obj,
            "query_string": query_string,
        },
    )


@login_required
def materiais(request: HttpRequest) -> HttpResponse:
    """Lista materiais cadastrados com busca e filtro de disponibilidade.

    Consulta materiais reais, permite busca por codigo, nome, descricao,
    identificacao e kit relacionado, e calcula indicadores de total, ativos,
    disponiveis e itens filtrados.
    """

    busca = request.GET.get("q", "").strip()
    disponibilidade = request.GET.get("disponibilidade", "").strip()

    materiais_queryset = (
        Material.objects.exclude(origem=OrigemDados.EXEMPLO)
        .prefetch_related("kits")
        .order_by("nome", "identificacao")
    )
    if disponibilidade == "disponivel":
        materiais_queryset = materiais_queryset.filter(disponivel=True)
    elif disponibilidade == "indisponivel":
        materiais_queryset = materiais_queryset.filter(disponivel=False)
    if busca:
        materiais_queryset = materiais_queryset.filter(
            Q(nome__icontains=busca)
            | Q(codigo__icontains=busca)
            | Q(descricao__icontains=busca)
            | Q(identificacao__icontains=busca)
            | Q(rotulo_kit__icontains=busca)
            | Q(kits__nome__icontains=busca)
        ).distinct()

    page_obj, query_string = paginar_queryset(request, materiais_queryset)
    materiais_base = Material.objects.exclude(origem=OrigemDados.EXEMPLO)
    metricas = {
        "total": materiais_base.count(),
        "ativos": materiais_base.filter(ativo=True).count(),
        "disponiveis": materiais_base.filter(disponivel=True).count(),
        "filtrados": page_obj.paginator.count,
    }

    return render(
        request,
        "gestao_cme/materiais.html",
        {
            "usuario_logado": request.user,
            "busca": busca,
            "disponibilidade_atual": disponibilidade,
            "disponibilidade_label": {
                "disponivel": "Disponíveis",
                "indisponivel": "Indisponíveis",
            }.get(disponibilidade, "Todos"),
            "metricas": metricas,
            "materiais": page_obj.object_list,
            "page_obj": page_obj,
            "query_string": query_string,
        },
    )


@login_required
def kits(request: HttpRequest) -> HttpResponse:
    """Lista kits de materiais com resumo dos itens que os compoem.

    Permite busca por dados do kit e de seus materiais, prepara informacoes de
    resumo para exibicao no template e calcula metricas gerais de kits ativos e
    quantidade operacional.
    """

    busca = request.GET.get("q", "").strip()

    kits_queryset = (
        Kit.objects.exclude(origem=OrigemDados.EXEMPLO)
        .prefetch_related("itens__material")
        .order_by("nome")
    )
    if busca:
        kits_queryset = kits_queryset.filter(
            Q(nome__icontains=busca)
            | Q(codigo__icontains=busca)
            | Q(descricao__icontains=busca)
            | Q(itens__material__nome__icontains=busca)
            | Q(itens__material__identificacao__icontains=busca)
        ).distinct()

    page_obj, query_string = paginar_queryset(request, kits_queryset)
    for kit in page_obj.object_list:
        itens = list(kit.itens.all())
        kit.total_materiais = len(itens)
        kit.materiais_disponiveis = sum(1 for item in itens if item.material.disponivel)
        kit.materiais_resumo = ", ".join(
            item.material.identificacao or item.material.nome for item in itens[:4]
        )
        if len(itens) > 4:
            kit.materiais_resumo += f" +{len(itens) - 4}"

    kits_base = Kit.objects.exclude(origem=OrigemDados.EXEMPLO)
    metricas = {
        "total": kits_base.count(),
        "ativos": kits_base.filter(ativo=True).count(),
        "quantidade": sum(kit.quantidade for kit in kits_base),
        "filtrados": page_obj.paginator.count,
    }

    return render(
        request,
        "gestao_cme/kits.html",
        {
            "usuario_logado": request.user,
            "busca": busca,
            "metricas": metricas,
            "kits": page_obj.object_list,
            "page_obj": page_obj,
            "query_string": query_string,
        },
    )


def _contexto_movimentacao(
    request: HttpRequest,
    tipo: str,
    form: MovimentacaoForm,
) -> dict[str, Any]:
    """Monta o contexto compartilhado entre registrar_saida e registrar_entrada."""

    tipo_label = "Saída" if tipo == Movimentacao.Tipo.SAIDA else "Entrada"
    return {
        "usuario_logado": request.user,
        "tipo": tipo,
        "tipo_label": tipo_label,
        "titulo": f"Registrar {tipo_label.lower()}",
        "subtitulo": (
            "Registre a entrega de um pacote ao aluno."
            if tipo == Movimentacao.Tipo.SAIDA
            else "Registre a devolução de um pacote pelo aluno."
        ),
        "submit_label": f"Registrar {tipo_label.lower()}",
        "active_page": (
            "nova_saida" if tipo == Movimentacao.Tipo.SAIDA else "nova_entrada"
        ),
        "alunos": form.fields["aluno"].queryset,
        "materiais": form.fields["material"].queryset,
        "form": form,
    }


def _salvar_movimentacao(
    form: MovimentacaoForm,
    tipo: str,
    retirado: bool | None,
) -> Movimentacao:
    """Persiste uma movimentacao a partir de um form já validado."""

    aluno: Aluno = form.cleaned_data["aluno"]
    return Movimentacao.objects.create(
        data_hora=form.cleaned_data["data_hora"],
        tipo=tipo,
        aluno=aluno,
        turma=aluno.turma,
        material=form.cleaned_data.get("material"),
        aluno_nome=aluno.nome,
        aluno_codigo_externo=aluno.matricula,
        turma_nome=aluno.turma.nome if aluno.turma else "",
        pacote_codigo=form.cleaned_data["pacote_codigo"],
        retirado=retirado,
        arquivo_origem="painel",
        row_hash=_gerar_row_hash(),
        origem=OrigemDados.MANUAL,
        observacoes=form.cleaned_data.get("observacoes", ""),
    )


@login_required
def registrar_entrada(request: HttpRequest) -> HttpResponse:
    """Registra em lote a entrada de N pacotes de um aluno para esterilizacao.

    Cria um registro Movimentacao(ENTRADA, retirado=False) para cada pacote.
    Os codigos sao gerados automaticamente no formato AAAAMMDD-{aluno_pk}-{n}.
    Avisa quando o aluno nao tem abrigo cadastrado, mas nao bloqueia o registro.
    """
    form = EntradaForm(request.POST or None)
    aluno_sem_abrigo = False

    if request.method == "POST" and form.is_valid():
        aluno: Aluno = form.cleaned_data["aluno"]
        quantidade: int = form.cleaned_data["quantidade"]
        data_hora = form.cleaned_data["data_hora"]
        observacoes = form.cleaned_data.get("observacoes", "")

        if not aluno.abrigo:
            aluno_sem_abrigo = True

        # Conta pacotes existentes do aluno na mesma data para gerar sequencia
        existentes = Movimentacao.objects.filter(
            aluno=aluno,
            tipo=Movimentacao.Tipo.ENTRADA,
            data_hora__date=data_hora.date(),
        ).count()

        prefixo = f"{data_hora.strftime('%Y%m%d')}-{aluno.pk}"
        with transaction.atomic():
            for i in range(1, quantidade + 1):
                seq = existentes + i
                Movimentacao.objects.create(
                    data_hora=data_hora,
                    tipo=Movimentacao.Tipo.ENTRADA,
                    aluno=aluno,
                    turma=aluno.turma,
                    aluno_nome=aluno.nome,
                    aluno_codigo_externo=aluno.matricula,
                    turma_nome=aluno.turma.nome if aluno.turma else "",
                    pacote_codigo=f"{prefixo}-{seq:02d}",
                    retirado=False,
                    arquivo_origem="painel",
                    row_hash=_gerar_row_hash(),
                    origem=OrigemDados.MANUAL,
                    observacoes=observacoes,
                )

        msg = f"{quantidade} pacote(s) de entrada registrado(s) para {aluno.nome}."
        if aluno_sem_abrigo:
            messages.warning(
                request,
                f"{msg} Atenção: {aluno.nome} não tem abrigo cadastrado — "
                "defina o abrigo na ficha do aluno.",
            )
        else:
            messages.success(
                request,
                f"{msg} Abrigo: {aluno.abrigo.identificador}.",
            )
        return redirect("cme_home")

    alunos = (
        Aluno.objects.exclude(origem=OrigemDados.EXEMPLO)
        .filter(ativo=True)
        .select_related("turma", "abrigo")
        .order_by("turma__nome", "nome")
    )
    return render(
        request,
        "gestao_cme/registrar_entrada.html",
        {
            "usuario_logado": request.user,
            "form": form,
            "alunos": alunos,
            "active_page": "nova_entrada",
        },
    )


@login_required
def registrar_saida(request: HttpRequest) -> HttpResponse:
    """Registra a retirada de pacotes esterilizados baseada nas entradas pendentes.

    Fluxo em dois passos:
      GET sem aluno_id  → exibe seletor de aluno.
      GET com aluno_id  → exibe pacotes pendentes do aluno para confirmacao.
      POST              → cria Movimentacao(SAIDA) para cada pacote selecionado
                          e marca o ENTRADA correspondente como retirado=True.
    """
    aluno_id = request.GET.get("aluno_id") or request.POST.get("aluno_id")
    aluno: Aluno | None = None
    pacotes_pendentes: list[Movimentacao] = []

    if aluno_id:
        aluno = get_object_or_404(
            Aluno.objects.select_related("turma", "abrigo"),
            pk=aluno_id,
        )
        pacotes_pendentes = list(
            Movimentacao.objects.filter(
                aluno=aluno,
                tipo=Movimentacao.Tipo.ENTRADA,
                retirado=False,
            ).order_by("data_hora")
        )

    if request.method == "POST" and aluno:
        ids_selecionados = request.POST.getlist("entradas")
        if not ids_selecionados:
            messages.error(
                request, "Selecione ao menos um pacote para registrar a saída."
            )
        else:
            agora = timezone.now()
            entradas_confirmadas = Movimentacao.objects.filter(
                pk__in=ids_selecionados,
                aluno=aluno,
                tipo=Movimentacao.Tipo.ENTRADA,
                retirado=False,
            )
            count = 0
            with transaction.atomic():
                for entrada in entradas_confirmadas:
                    Movimentacao.objects.create(
                        data_hora=agora,
                        tipo=Movimentacao.Tipo.SAIDA,
                        aluno=aluno,
                        turma=aluno.turma,
                        aluno_nome=aluno.nome,
                        aluno_codigo_externo=aluno.matricula,
                        turma_nome=aluno.turma.nome if aluno.turma else "",
                        pacote_codigo=entrada.pacote_codigo,
                        retirado=True,
                        arquivo_origem="painel",
                        row_hash=_gerar_row_hash(),
                        origem=OrigemDados.MANUAL,
                    )
                    entrada.retirado = True
                    entrada.save(update_fields=["retirado"])
                    count += 1

            messages.success(
                request,
                f"{count} pacote(s) retirado(s) por {aluno.nome} — "
                f"registrado em {agora.strftime('%d/%m/%Y %H:%M')}.",
            )
            return redirect("cme_home")

    alunos_com_pendencias = (
        Aluno.objects.filter(
            movimentacoes__tipo=Movimentacao.Tipo.ENTRADA,
            movimentacoes__retirado=False,
        )
        .exclude(origem=OrigemDados.EXEMPLO)
        .distinct()
        .select_related("turma")
        .order_by("nome")
    )
    return render(
        request,
        "gestao_cme/registrar_saida.html",
        {
            "usuario_logado": request.user,
            "alunos_com_pendencias": alunos_com_pendencias,
            "aluno": aluno,
            "aluno_id": aluno_id or "",
            "pacotes_pendentes": pacotes_pendentes,
            "active_page": "nova_saida",
        },
    )


@login_required
@require_POST
def alternar_retirado(request: HttpRequest, pk: int) -> HttpResponse:
    """Alterna o campo retirado de uma movimentacao entre os tres estados possiveis."""

    try:
        mov = Movimentacao.objects.get(pk=pk)
    except Movimentacao.DoesNotExist:
        messages.error(request, "Movimentação não encontrada.")
        return redirect("cme_home")

    if mov.retirado is None:
        mov.retirado = True
    elif mov.retirado is True:
        mov.retirado = False
    else:
        mov.retirado = None
    mov.save()

    next_url = request.POST.get("next", "")
    if next_url.startswith("/"):
        return HttpResponseRedirect(next_url)
    return redirect("cme_home")


@login_required
@require_POST
def excluir_movimentacao(request: HttpRequest, pk: int) -> HttpResponse:
    """Remove permanentemente uma movimentacao do sistema."""

    try:
        mov = Movimentacao.objects.get(pk=pk)
    except Movimentacao.DoesNotExist:
        messages.error(request, "Movimentação não encontrada.")
        return redirect("cme_home")

    nome = mov.aluno_nome or "Aluno não informado"
    pacote = mov.pacote_codigo
    mov.delete()
    messages.success(request, f"Movimentação de {nome} — pacote {pacote} — excluída.")

    next_url = request.POST.get("next", "")
    if next_url.startswith("/"):
        return HttpResponseRedirect(next_url)
    return redirect("cme_home")


# ── Fase 2: cadastros manuais e sincronização por turma ──────────────────────


@login_required
@require_POST
def sincronizar_alunos_turma(request: HttpRequest, turma_id: int) -> HttpResponse:
    """Sincroniza alunos de uma turma especifica com o Eduq."""

    try:
        turma = Turma.objects.get(pk=turma_id)
    except Turma.DoesNotExist:
        messages.error(request, "Turma não encontrada.")
        return redirect("alunos_por_turma")

    try:
        resultado = sincronizar_eduq(
            sincronizar_turmas=False,
            sincronizar_alunos=True,
            turma_codigos=[turma.codigo],
        )
    except EduqAPIError as exc:
        messages.error(
            request, f"Não foi possível sincronizar alunos de {turma.nome}: {exc}"
        )
    else:
        erros = len(resultado.alunos.erros)
        messages.success(
            request,
            f"Alunos de {turma.nome} sincronizados: "
            f"{resultado.alunos.criados} criados, "
            f"{resultado.alunos.atualizados} atualizados"
            + (f", {erros} erro(s)." if erros else "."),
        )

    next_url = request.POST.get("next", "")
    if next_url.startswith("/"):
        return HttpResponseRedirect(next_url)
    return redirect(f"{reverse('alunos_por_turma')}?turma={turma_id}")


@login_required
def cadastrar_aluno(request: HttpRequest) -> HttpResponse:
    """Cria um novo aluno manualmente no sistema."""

    form = CadastrarAlunoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        aluno = form.save(commit=False)
        aluno.origem = OrigemDados.MANUAL
        aluno.save()
        messages.success(request, f"Aluno {aluno.nome} cadastrado com sucesso.")
        return redirect("alunos_por_turma")

    return render(
        request,
        "gestao_cme/cadastrar_aluno.html",
        {
            "usuario_logado": request.user,
            "titulo": "Cadastrar aluno",
            "active_page": "alunos",
            "turmas": form.fields["turma"].queryset,
            "form": form,
        },
    )


@login_required
def cadastrar_turma(request: HttpRequest) -> HttpResponse:
    """Cria uma nova turma manualmente no sistema."""

    form = CadastrarTurmaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        turma = form.save(commit=False)
        turma.origem = OrigemDados.MANUAL
        turma.save()
        messages.success(request, f"Turma {turma.nome} cadastrada com sucesso.")
        return redirect("alunos_por_turma")

    return render(
        request,
        "gestao_cme/cadastrar_turma.html",
        {
            "usuario_logado": request.user,
            "titulo": "Cadastrar turma",
            "active_page": "alunos",
            "form": form,
        },
    )


# ── Cadastros de Abrigo e Material ───────────────────────────────────────────


@login_required
def cadastrar_abrigo(request: HttpRequest) -> HttpResponse:
    """Cria um novo abrigo manualmente no sistema."""

    form = AbrigoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        abrigo = form.save(commit=False)
        abrigo.origem = OrigemDados.MANUAL
        abrigo.save()
        messages.success(
            request, f"Abrigo {abrigo.identificador} cadastrado com sucesso."
        )
        return redirect("abrigos")

    return render(
        request,
        "gestao_cme/form_abrigo.html",
        {
            "usuario_logado": request.user,
            "titulo": "Cadastrar abrigo",
            "is_edit": False,
            "active_page": "armarios",
            "form": form,
        },
    )


@login_required
def editar_abrigo(request: HttpRequest, pk: int) -> HttpResponse:
    """Atualiza os dados de um abrigo existente."""

    abrigo = get_object_or_404(Abrigo, pk=pk)
    form = AbrigoEditForm(request.POST or None, instance=abrigo)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(
            request, f"Abrigo {abrigo.identificador} atualizado com sucesso."
        )
        return redirect("abrigos")

    return render(
        request,
        "gestao_cme/form_abrigo.html",
        {
            "usuario_logado": request.user,
            "titulo": f"Editar abrigo {abrigo.identificador}",
            "is_edit": True,
            "objeto": abrigo,
            "active_page": "armarios",
            "form": form,
        },
    )


@login_required
def cadastrar_material(request: HttpRequest) -> HttpResponse:
    """Cria um novo material manualmente no sistema."""

    form = MaterialForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        material = form.save(commit=False)
        material.origem = OrigemDados.MANUAL
        material.save()
        messages.success(request, f"Material {material.nome} cadastrado com sucesso.")
        return redirect("materiais")

    return render(
        request,
        "gestao_cme/form_material.html",
        {
            "usuario_logado": request.user,
            "titulo": "Cadastrar material",
            "is_edit": False,
            "active_page": "materiais",
            "form": form,
        },
    )


@login_required
def editar_material(request: HttpRequest, pk: int) -> HttpResponse:
    """Atualiza os dados de um material existente."""

    material = get_object_or_404(Material, pk=pk)
    form = MaterialEditForm(request.POST or None, instance=material)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Material {material.nome} atualizado com sucesso.")
        return redirect("materiais")

    return render(
        request,
        "gestao_cme/form_material.html",
        {
            "usuario_logado": request.user,
            "titulo": f"Editar {material.nome}",
            "is_edit": True,
            "objeto": material,
            "active_page": "materiais",
            "form": form,
        },
    )


# ── Fase 3: fluxo de empréstimos ─────────────────────────────────────────────

_STATUS_EMPRESTIMO_OPCOES = (
    (Emprestimo.Status.EMPRESTADO, "Emprestado"),
    (Emprestimo.Status.DEVOLVIDO, "Devolvido"),
    (Emprestimo.Status.ATRASADO, "Atrasado"),
)


@login_required
def emprestimos(request: HttpRequest) -> HttpResponse:
    """Lista emprestimos com filtros de status e busca."""

    busca = request.GET.get("q", "").strip()
    status_filtro = request.GET.get("status", "").strip()

    queryset = (
        emprestimos_visiveis(request)
        .select_related("aluno", "aluno__turma", "kit", "coordenador_usuario")
        .prefetch_related("itens")
    )

    if status_filtro in Emprestimo.Status.values:
        queryset = queryset.filter(status=status_filtro)

    if busca:
        queryset = queryset.filter(
            Q(aluno__nome__icontains=busca)
            | Q(aluno__matricula__icontains=busca)
            | Q(kit__nome__icontains=busca)
            | Q(kit__codigo__icontains=busca)
            | Q(coordenador__icontains=busca)
            | Q(observacoes__icontains=busca)
        ).distinct()

    page_obj, query_string = paginar_queryset(request, queryset)

    base = emprestimos_visiveis(request)
    metricas = base.aggregate(
        total=Count("id"),
        emprestados=Count("id", filter=Q(status=Emprestimo.Status.EMPRESTADO)),
        devolvidos=Count("id", filter=Q(status=Emprestimo.Status.DEVOLVIDO)),
        atrasados=Count("id", filter=Q(status=Emprestimo.Status.ATRASADO)),
    )

    return render(
        request,
        "gestao_cme/emprestimos.html",
        {
            "usuario_logado": request.user,
            "busca": busca,
            "status_filtro": status_filtro,
            "status_opcoes": _STATUS_EMPRESTIMO_OPCOES,
            "status_label": dict(_STATUS_EMPRESTIMO_OPCOES).get(status_filtro, "Todos"),
            "emprestimos": page_obj.object_list,
            "metricas": metricas,
            "page_obj": page_obj,
            "query_string": query_string,
        },
    )


@login_required
def criar_emprestimo(request: HttpRequest) -> HttpResponse:
    """Cria um novo emprestimo vinculando aluno, kit e itens automaticamente."""

    form = EmprestimoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        aluno: Aluno = form.cleaned_data["aluno"]
        kit: Kit | None = form.cleaned_data.get("kit")
        with transaction.atomic():
            emp = Emprestimo.objects.create(
                aluno=aluno,
                kit=kit,
                coordenador=request.user.get_full_name() or request.user.username,
                coordenador_usuario=request.user,
                data_prevista_devolucao=form.cleaned_data.get(
                    "data_prevista_devolucao"
                ),
                status=Emprestimo.Status.EMPRESTADO,
                observacoes=form.cleaned_data.get("observacoes", ""),
            )
            if kit:
                for item_kit in kit.itens.all():
                    ItemEmprestimo.objects.create(
                        emprestimo=emp,
                        material=item_kit.material,
                        quantidade=item_kit.quantidade,
                    )
        kit_info = f" — kit {kit.nome}" if kit else ""
        messages.success(
            request,
            f"Empréstimo #{emp.pk} criado para {aluno.nome}{kit_info}.",
        )
        return redirect("emprestimos")

    return render(
        request,
        "gestao_cme/criar_emprestimo.html",
        {
            "usuario_logado": request.user,
            "titulo": "Novo empréstimo",
            "active_page": "emprestimos",
            "alunos": form.fields["aluno"].queryset,
            "kits": form.fields["kit"].queryset,
            "form": form,
        },
    )


@login_required
@require_POST
def devolver_emprestimo(request: HttpRequest, pk: int) -> HttpResponse:
    """Registra a devolucao de um emprestimo, marcando-o como devolvido."""

    try:
        emp = emprestimos_visiveis(request).get(pk=pk)
    except Emprestimo.DoesNotExist:
        messages.error(request, "Empréstimo não encontrado.")
        return redirect("emprestimos")

    if emp.status == Emprestimo.Status.DEVOLVIDO:
        messages.error(request, f"Empréstimo #{emp.pk} já foi devolvido.")
        return redirect("emprestimos")

    emp.status = Emprestimo.Status.DEVOLVIDO
    emp.data_devolucao = timezone.now()
    emp.save()
    messages.success(
        request, f"Devolução do empréstimo #{emp.pk} de {emp.aluno.nome} registrada."
    )

    next_url = request.POST.get("next", "")
    if next_url.startswith("/"):
        return HttpResponseRedirect(next_url)
    return redirect("emprestimos")


@login_required
@require_POST
def marcar_emprestimo_atrasado(request: HttpRequest, pk: int) -> HttpResponse:
    """Marca um emprestimo em aberto como atrasado."""

    try:
        emp = emprestimos_visiveis(request).get(pk=pk)
    except Emprestimo.DoesNotExist:
        messages.error(request, "Empréstimo não encontrado.")
        return redirect("emprestimos")

    if emp.status != Emprestimo.Status.EMPRESTADO:
        messages.error(
            request,
            "Apenas empréstimos com status 'Emprestado' "
            "podem ser marcados como atrasados.",
        )
        return redirect("emprestimos")

    emp.status = Emprestimo.Status.ATRASADO
    emp.save()
    messages.success(
        request, f"Empréstimo #{emp.pk} de {emp.aluno.nome} marcado como atrasado."
    )

    next_url = request.POST.get("next", "")
    if next_url.startswith("/"):
        return HttpResponseRedirect(next_url)
    return redirect("emprestimos")


@login_required
def cme_dashboard(request: HttpRequest) -> HttpResponse:
    """Exibe metricas consolidadas e atividade recente da gestao de CME."""

    hoje = timezone.now().date()
    mov_base = Movimentacao.objects.exclude(origem=OrigemDados.EXEMPLO)

    metricas_mov = {
        "total": mov_base.count(),
        "saidas": mov_base.filter(tipo=Movimentacao.Tipo.SAIDA).count(),
        "entradas": mov_base.filter(tipo=Movimentacao.Tipo.ENTRADA).count(),
        "pendentes": mov_base.filter(
            tipo=Movimentacao.Tipo.ENTRADA, retirado=False
        ).count(),
    }

    pacotes_aguardando = list(
        mov_base.filter(
            tipo=Movimentacao.Tipo.ENTRADA,
            retirado=False,
        )
        .select_related("aluno", "aluno__turma", "aluno__abrigo")
        .order_by("data_hora")[:10]
    )

    atividade_recente: list[dict] = []
    for mov in mov_base.select_related("material").order_by("-data_hora", "-id")[:12]:
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
        atividade_recente.append(
            {
                "categoria": categoria,
                "titulo": titulo,
                "descricao": descricao,
                "data": mov.data_hora,
            }
        )

    atividade_recente = sorted(
        atividade_recente, key=lambda x: x["data"], reverse=True
    )[:12]

    return render(
        request,
        "gestao_cme/dashboard_cme.html",
        {
            "usuario_logado": request.user,
            "active_page": "dashboard",
            "hoje": hoje,
            "metricas_mov": metricas_mov,
            "pacotes_aguardando": pacotes_aguardando,
            "atividade_recente": atividade_recente,
        },
    )
