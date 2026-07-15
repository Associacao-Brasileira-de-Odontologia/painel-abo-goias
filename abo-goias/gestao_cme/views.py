from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Page, Paginator
from django.db import transaction
from django.db.models import Count, Max, ProtectedError, Q, Sum
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
    EditarMovimentacaoForm,
    EmprestimoForm,
    EntradaForm,
    KitForm,
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
from .utils import normalizar_texto

REGISTROS_POR_PAGINA = 10

# Teto de itens exibidos no autocomplete de aluno — mesmo valor do
# equivalente na Gestao de Laboratorio (_LIMITE_RESULTADOS).
LIMITE_RESULTADOS_BUSCA = 20


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
    # Documentos assinados que não chegaram ao Dental Office (falha ou pendente)
    # — precisam de atenção para não se perderem por falha de integração.
    contratos_envio_dental_pendente = (
        ContratoGerado.objects.filter(status="assinado")
        .filter(Q(status_envio_dental="erro") | Q(status_envio_dental="nao_enviado"))
        .count()
    )

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
    if contratos_envio_dental_pendente:
        tarefas_pendentes.append(
            {
                "texto": (
                    f"{contratos_envio_dental_pendente} contrato(s) assinado(s)"
                    " sem envio ao Dental Office"
                ),
                "url_name": "contrato_envios_dental",
                "urgente": True,
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
    aluno_id = request.GET.get("aluno", "").strip()

    movimentacoes = (
        Movimentacao.objects.exclude(origem=OrigemDados.EXEMPLO)
        .select_related("aluno", "turma", "material")
        .order_by("-data_hora", "-id")
    )

    # Filtro por aluno específico — usado ao clicar no total de movimentações
    # de um aluno na tela de alunos por turma. Precede a busca textual porque é
    # um vínculo exato (FK), não um termo aproximado.
    aluno_filtrado = None
    if aluno_id.isdigit():
        aluno_filtrado = (
            Aluno.objects.select_related("turma").filter(pk=aluno_id).first()
        )
        if aluno_filtrado:
            movimentacoes = movimentacoes.filter(aluno=aluno_filtrado)

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
            "aluno_filtrado": aluno_filtrado,
            "movimentacoes": page_obj.object_list,
            "metricas": metricas,
            "page_obj": page_obj,
            "query_string": query_string,
        },
    )


@login_required
def alunos_por_turma(request: HttpRequest) -> HttpResponse:
    """Exibe alunos agrupados por turma com filtros, abrigo e contagem de movimentacoes.

    A view lista cadastros academicos ativos com o abrigo associado a cada aluno
    (editavel inline) e o total de movimentacoes registradas.
    """

    busca = request.GET.get("q", "").strip()
    turma_id = request.GET.get("turma", "").strip()
    status_aluno = request.GET.get("status", "ativo").strip()

    alunos = (
        Aluno.objects.exclude(origem=OrigemDados.EXEMPLO)
        .exclude(turma__origem=OrigemDados.EXEMPLO)
        .select_related("turma", "abrigo")
        .annotate(
            total_movimentacoes=Count(
                "movimentacoes",
                filter=~Q(movimentacoes__origem=OrigemDados.EXEMPLO),
            )
        )
        .order_by("turma__nome", "nome")
    )

    if status_aluno == "ativo":
        alunos = alunos.filter(ativo=True)
    elif status_aluno == "inativo":
        alunos = alunos.filter(ativo=False)

    if turma_id.isdigit():
        alunos = alunos.filter(turma_id=turma_id)
    if busca:
        alunos = alunos.filter(
            Q(nome_normalizado__icontains=normalizar_texto(busca))
            | Q(matricula__icontains=busca)
            | Q(email__icontains=busca)
            | Q(turma__nome_normalizado__icontains=normalizar_texto(busca))
            | Q(turma__codigo__icontains=busca)
        )

    page_obj, query_string = paginar_queryset(request, alunos)

    turmas = Turma.objects.exclude(origem=OrigemDados.EXEMPLO).order_by("nome")
    abrigos = Abrigo.objects.filter(ativo=True).order_by("identificador")

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
        d for d in (ultima_sincronizacao_alunos, ultima_sincronizacao_turmas) if d
    ]
    ultima_sincronizacao = max(datas_sincronizacao) if datas_sincronizacao else None

    sem_abrigo = alunos_base.filter(ativo=True, abrigo__isnull=True).count()

    return render(
        request,
        "gestao_cme/alunos_por_turma.html",
        {
            "usuario_logado": request.user,
            "busca": busca,
            "turma_id": turma_id,
            "status_aluno": status_aluno,
            "turmas": turmas,
            "turma_selecionada": turma_selecionada,
            "abrigos": abrigos,
            "page_obj": page_obj,
            "query_string": query_string,
            "ultima_sincronizacao": ultima_sincronizacao,
            "total_alunos": alunos_base.count(),
            "total_turmas": turmas_base.count(),
            "total_ativos": alunos_base.filter(ativo=True).count(),
            "sem_abrigo": sem_abrigo,
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
        },
    )


def _sincronizar_ocupacao_abrigo(abrigo: Abrigo | None) -> None:
    """Recalcula o campo ``ocupado`` de um abrigo a partir dos alunos vinculados.

    Um abrigo é considerado ocupado quando há ao menos um aluno ativo com
    ``aluno.abrigo`` apontando para ele. Mantém a coluna OCUPAÇÃO da tabela de
    abrigos coerente com as atribuições feitas na tela de alunos por turma.
    """

    if abrigo is None:
        return
    ocupado_atual = abrigo.alunos.filter(ativo=True).exists()
    if abrigo.ocupado != ocupado_atual:
        abrigo.ocupado = ocupado_atual
        abrigo.save(update_fields=["ocupado", "atualizado_em"])


@login_required
@require_POST
def atribuir_abrigo(request: HttpRequest, aluno_id: int) -> HttpResponse:
    """Atribui ou remove o abrigo de um aluno diretamente na listagem.

    Além de gravar o vínculo no aluno, sincroniza a ocupação dos abrigos
    envolvidos (o novo e o anterior), para que a coluna OCUPAÇÃO da tabela de
    abrigos reflita automaticamente o novo status.
    """

    aluno = get_object_or_404(
        Aluno.objects.exclude(origem=OrigemDados.EXEMPLO), pk=aluno_id
    )
    abrigo_id = request.POST.get("abrigo_id", "").strip()
    abrigo_anterior = aluno.abrigo

    if abrigo_id:
        abrigo = get_object_or_404(Abrigo, pk=abrigo_id, ativo=True)
        aluno.abrigo = abrigo
        messages.success(
            request, f"Abrigo {abrigo.identificador} atribuído a {aluno.nome}."
        )
    else:
        aluno.abrigo = None
        messages.success(request, f"Abrigo removido de {aluno.nome}.")

    with transaction.atomic():
        aluno.save(update_fields=["abrigo"])
        # O anterior pode ter ficado livre; o novo passa a ocupado.
        _sincronizar_ocupacao_abrigo(abrigo_anterior)
        _sincronizar_ocupacao_abrigo(aluno.abrigo)

    next_url = request.POST.get("next") or reverse("alunos_por_turma")
    return redirect(next_url)


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


@login_required
def cadastrar_kit(request: HttpRequest) -> HttpResponse:
    """Cria um novo kit manualmente, com composição opcional de materiais.

    Habilita o cadastro de kits pela própria tela de kits (antes só era
    possível pelo Django Admin). A seleção de materiais gera os itens do kit
    com quantidade 1; ajustes de quantidade por material seguem no Admin.
    """

    form = KitForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        kit = form.save(commit=False)
        kit.origem = OrigemDados.MANUAL
        with transaction.atomic():
            kit.save()
            form._salvar_materiais(kit)
        messages.success(request, f"Kit {kit.nome} cadastrado com sucesso.")
        return redirect("kits")

    return render(
        request,
        "gestao_cme/form_kit.html",
        {
            "usuario_logado": request.user,
            "titulo": "Cadastrar kit",
            "is_edit": False,
            "form": form,
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
    Os codigos seguem a sequencia numerica global: max(codigos numericos) + n.
    Avisa quando o aluno nao tem abrigo cadastrado, mas nao bloqueia o registro.
    """
    form = EntradaForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        aluno: Aluno = form.cleaned_data["aluno"]
        quantidade: int = form.cleaned_data["quantidade"]
        data_hora = form.cleaned_data["data_hora"]
        observacoes = form.cleaned_data.get("observacoes", "")

        # Continua a sequencia numerica global dos pacotes existentes
        codigos_existentes = Movimentacao.objects.values_list(
            "pacote_codigo", flat=True
        )
        max_seq = 0
        for codigo in codigos_existentes:
            if str(codigo).isdigit():
                max_seq = max(max_seq, int(codigo))

        codigos_gerados = [str(max_seq + i) for i in range(1, quantidade + 1)]

        with transaction.atomic():
            for codigo in codigos_gerados:
                Movimentacao.objects.create(
                    data_hora=data_hora,
                    tipo=Movimentacao.Tipo.ENTRADA,
                    aluno=aluno,
                    turma=aluno.turma,
                    aluno_nome=aluno.nome,
                    aluno_codigo_externo=aluno.matricula,
                    turma_nome=aluno.turma.nome if aluno.turma else "",
                    pacote_codigo=codigo,
                    retirado=False,
                    arquivo_origem="painel",
                    row_hash=_gerar_row_hash(),
                    origem=OrigemDados.MANUAL,
                    observacoes=observacoes,
                )

        # A confirmação com os códigos gerados precisa sobreviver ao
        # redirect (post/redirect/get) e ficar visível até o operador
        # etiquetar os pacotes — por isso sessão, e não messages.
        request.session["cme_entrada_confirmada"] = {
            "codigos": codigos_gerados,
            "aluno_nome": aluno.nome,
            "abrigo": aluno.abrigo.identificador if aluno.abrigo else "",
            "quantidade": quantidade,
            "data_hora": timezone.localtime(data_hora).strftime("%d/%m/%Y %H:%M"),
        }
        return redirect("registrar_entrada")

    # Preserva o aluno escolhido no autocomplete quando o formulario volta com erro.
    aluno_selecionado = None
    aluno_pk = form["aluno"].value()
    if aluno_pk:
        aluno_selecionado = (
            Aluno.objects.select_related("turma", "abrigo").filter(pk=aluno_pk).first()
        )

    confirmacao = request.session.pop("cme_entrada_confirmada", None)

    return render(
        request,
        "gestao_cme/registrar_entrada.html",
        {
            "usuario_logado": request.user,
            "form": form,
            "aluno_selecionado": aluno_selecionado,
            "confirmacao": confirmacao,
            # Com a confirmação na tela, o foco não deve pular direto para a
            # busca — o operador precisa ler os códigos gerados primeiro.
            "autofocus_busca": not confirmacao,
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
            # Com um aluno já escolhido, o foco fica nos pacotes (passo 2).
            "sem_aluno": aluno is None,
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
    """Remove permanentemente uma movimentacao do sistema.

    Quando a movimentacao excluida e do tipo SAIDA, restaura o registro de
    ENTRADA correspondente (mesmo aluno e mesmo pacote_codigo) para retirado=False,
    sinalizando que o pacote voltou a aguardar retirada.
    """

    try:
        mov = Movimentacao.objects.select_related("aluno").get(pk=pk)
    except Movimentacao.DoesNotExist:
        messages.error(request, "Movimentação não encontrada.")
        return redirect("cme_home")

    nome = mov.aluno_nome or "Aluno não informado"
    pacote = mov.pacote_codigo
    tipo = mov.tipo

    if tipo == Movimentacao.Tipo.SAIDA:
        # Restaura entradas correspondentes para "nao retirado"
        restauradas = Movimentacao.objects.filter(
            pacote_codigo=pacote,
            aluno=mov.aluno,
            tipo=Movimentacao.Tipo.ENTRADA,
            retirado=True,
        ).update(retirado=False)
        mov.delete()
        msg = f"Saída do pacote {pacote} de {nome} excluída."
        if restauradas:
            msg += " O registro de entrada voltou para 'Não retirado'."
        messages.warning(request, msg)
    else:
        mov.delete()
        messages.success(request, f"Registro do pacote {pacote} de {nome} excluído.")

    next_url = request.POST.get("next", "")
    if next_url.startswith("/"):
        return HttpResponseRedirect(next_url)
    return redirect("cme_home")


@login_required
def editar_movimentacao(request: HttpRequest, pk: int) -> HttpResponse:
    """Exibe e processa o formulario de edicao de uma movimentacao."""

    mov = get_object_or_404(
        Movimentacao.objects.select_related("aluno", "turma"), pk=pk
    )

    if request.method == "POST":
        form = EditarMovimentacaoForm(request.POST, instance=mov)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f"Registro do pacote {mov.pacote_codigo} atualizado.",
            )
            return redirect("cme_home")
    else:
        form = EditarMovimentacaoForm(instance=mov)

    if mov.retirado is True:
        status_label, status_classe = "Retirado", "devolvido"
    elif mov.retirado is False:
        status_label, status_classe = "Não retirado", "atrasado"
    else:
        status_label, status_classe = "Sem status", "emprestado"

    return render(
        request,
        "gestao_cme/editar_movimentacao.html",
        {
            "usuario_logado": request.user,
            "form": form,
            "mov": mov,
            "status_label": status_label,
            "status_classe": status_classe,
            "breadcrumbs": [
                {"label": "Movimentações", "url": reverse("cme_home")},
                {"label": "Editar registro", "url": None},
            ],
        },
    )


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
            "form": form,
        },
    )


@login_required
def editar_abrigo(request: HttpRequest, pk: int) -> HttpResponse:
    """Atualiza os dados de um abrigo existente.

    A tela exibe um resumo dos alunos atualmente vinculados ao abrigo, usado
    para montar a confirmação obrigatória antes de salvar (dupla checagem):
    quem ocupa o abrigo hoje fica explícito para quem está alterando.
    """

    abrigo = get_object_or_404(Abrigo, pk=pk)
    form = AbrigoEditForm(request.POST or None, instance=abrigo)
    if request.method == "POST" and form.is_valid():
        form.save()
        # Se a edição desmarcou "ocupado" mas ainda há alunos vinculados (ou
        # vice-versa), a origem da verdade continua sendo o vínculo dos alunos.
        _sincronizar_ocupacao_abrigo(abrigo)
        messages.success(
            request, f"Abrigo {abrigo.identificador} atualizado com sucesso."
        )
        return redirect("abrigos")

    alunos_associados = list(
        abrigo.alunos.filter(ativo=True).select_related("turma").order_by("nome")
    )

    return render(
        request,
        "gestao_cme/form_abrigo.html",
        {
            "usuario_logado": request.user,
            "titulo": f"Editar abrigo {abrigo.identificador}",
            "is_edit": True,
            "objeto": abrigo,
            "form": form,
            "alunos_associados": alunos_associados,
        },
    )


@login_required
@require_POST
def excluir_abrigo(request: HttpRequest, pk: int) -> HttpResponse:
    """Exclui um abrigo permanentemente.

    Os alunos vinculados têm ``abrigo`` definido como nulo automaticamente
    (FK com ``on_delete=SET_NULL``), então nenhum cadastro de aluno é perdido —
    apenas deixam de apontar para o abrigo excluído.
    """

    abrigo = get_object_or_404(Abrigo, pk=pk)
    identificador = abrigo.identificador
    abrigo.delete()
    messages.warning(request, f"Abrigo {identificador} excluído permanentemente.")
    return redirect("abrigos")


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

    # Unidades deste material atualmente em emprestimo (emprestado ou atrasado),
    # usado para avisar antes da exclusao irreversivel.
    em_emprestimo = (
        ItemEmprestimo.objects.filter(
            material=material,
            emprestimo__status__in=[
                Emprestimo.Status.EMPRESTADO,
                Emprestimo.Status.ATRASADO,
            ],
        ).aggregate(total=Sum("quantidade"))["total"]
        or 0
    )

    return render(
        request,
        "gestao_cme/form_material.html",
        {
            "usuario_logado": request.user,
            "titulo": f"Editar {material.nome}",
            "is_edit": True,
            "objeto": material,
            "form": form,
            "em_emprestimo": em_emprestimo,
        },
    )


@login_required
def buscar_alunos(request: HttpRequest) -> HttpResponse:
    """Fragmento HTMX com alunos filtrados por nome ou matricula (autocomplete).

    Espelha o autocomplete da Gestao de Laboratorio (ver
    ``gestao_lab.views._buscar_unificado``): mesmo componente ``[data-ac]``, mesmo
    contrato de resultados e o mesmo aviso de "ha mais resultados" quando a busca
    e ampla demais para o limite exibido.

    Diferenca deliberada: no laboratorio a lista mistura a base local com a busca
    do Dental Office; aqui a busca e **so local**, porque o Eduq nao oferece
    consulta de aluno por nome (so ``listar_alunos`` por turma) — nao ha o que
    consultar ao vivo nem o que materializar no clique. A base local e alimentada
    pela sincronizacao do Eduq (rotina diaria + botao "Atualizar lista de alunos").

    Usado nos registros de entrada, retirada e emprestimo. Com ``pendencias=1``
    restringe aos alunos que possuem pacotes de entrada aguardando retirada
    (fluxo de saida).
    """

    q = request.GET.get("q", "").strip()
    alunos = Aluno.objects.exclude(origem=OrigemDados.EXEMPLO).filter(ativo=True)
    if request.GET.get("pendencias") == "1":
        alunos = alunos.filter(
            movimentacoes__tipo=Movimentacao.Tipo.ENTRADA,
            movimentacoes__retirado=False,
        ).distinct()
    alunos = alunos.select_related("turma", "abrigo").order_by("nome")
    if q:
        alunos = alunos.filter(
            Q(nome_normalizado__icontains=normalizar_texto(q))
            | Q(matricula__icontains=q)
        )

    # Busca um a mais que o limite para saber se houve corte, sem um count().
    encontrados = list(alunos[: LIMITE_RESULTADOS_BUSCA + 1])
    ha_mais = len(encontrados) > LIMITE_RESULTADOS_BUSCA

    return render(
        request,
        "gestao_cme/partials/_aluno_results.html",
        {
            "alunos": encontrados[:LIMITE_RESULTADOS_BUSCA],
            "busca": q,
            "ha_mais": ha_mais,
        },
    )


@login_required
@require_POST
def atualizar_alunos_eduq(request: HttpRequest) -> HttpResponse:
    """Sincroniza turmas e alunos com o Eduq e volta para a tela de origem."""

    try:
        resultado = sincronizar_eduq(
            sincronizar_turmas=True,
            sincronizar_alunos=True,
        )
    except EduqAPIError as exc:
        messages.error(request, f"Não foi possível atualizar os alunos: {exc}")
    else:
        messages.success(
            request,
            "Lista de alunos atualizada: "
            f"{resultado.alunos.criados} novo(s), "
            f"{resultado.alunos.atualizados} atualizado(s).",
        )

    next_url = request.POST.get("next", "")
    if next_url.startswith("/"):
        return HttpResponseRedirect(next_url)
    return redirect("registrar_entrada")


@login_required
@require_POST
def excluir_material(request: HttpRequest, pk: int) -> HttpResponse:
    """Exclui um material do catalogo permanentemente.

    Quando o material tem vinculos protegidos (emprestimos, kits ou estoques), a
    exclusao e bloqueada e a view orienta a inativar o material em vez de excluir.
    """

    material = get_object_or_404(Material, pk=pk)
    nome = material.nome
    try:
        material.delete()
    except ProtectedError:
        messages.error(
            request,
            (
                f"Não foi possível excluir o material {nome}: há empréstimos, kits "
                "ou estoques vinculados. Marque-o como indisponível/inativo em vez "
                "de excluir."
            ),
        )
        return redirect("editar_material", pk=pk)

    messages.success(request, f"Material {nome} excluído permanentemente.")
    return redirect("materiais")


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
            Q(aluno__nome_normalizado__icontains=normalizar_texto(busca))
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

    # Preserva o aluno escolhido no autocomplete quando o form volta com erro
    # (mesmo padrão de registrar_entrada — ver melhoria de padronização).
    aluno_selecionado = None
    aluno_pk = form["aluno"].value()
    if aluno_pk:
        aluno_selecionado = (
            Aluno.objects.select_related("turma", "abrigo").filter(pk=aluno_pk).first()
        )

    return render(
        request,
        "gestao_cme/criar_emprestimo.html",
        {
            "usuario_logado": request.user,
            "titulo": "Novo empréstimo",
            "kits": form.fields["kit"].queryset,
            "form": form,
            "aluno_selecionado": aluno_selecionado,
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

    data_inicio_str = request.GET.get("data_inicio", "").strip()
    data_fim_str = request.GET.get("data_fim", "").strip()

    # Padrão: mês atual quando nenhum filtro é informado
    if not data_inicio_str and not data_fim_str:
        data_inicio_str = hoje.replace(day=1).strftime("%d/%m/%Y")
        data_fim_str = hoje.strftime("%d/%m/%Y")

    data_inicio = None
    data_fim = None

    if data_inicio_str:
        try:
            data_inicio = timezone.make_aware(
                datetime.strptime(data_inicio_str, "%d/%m/%Y")
            )
        except ValueError:
            data_inicio_str = ""

    if data_fim_str:
        try:
            dt_fim = datetime.strptime(data_fim_str, "%d/%m/%Y").replace(
                hour=23, minute=59, second=59
            )
            data_fim = timezone.make_aware(dt_fim)
        except ValueError:
            data_fim_str = ""

    mov_base = Movimentacao.objects.exclude(origem=OrigemDados.EXEMPLO)

    if data_inicio:
        mov_base = mov_base.filter(data_hora__gte=data_inicio)
    if data_fim:
        mov_base = mov_base.filter(data_hora__lte=data_fim)

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
            "hoje": hoje,
            "data_inicio_str": data_inicio_str,
            "data_fim_str": data_fim_str,
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "filtro_ativo": bool(
                request.GET.get("data_inicio") or request.GET.get("data_fim")
            ),
            "metricas_mov": metricas_mov,
            "pacotes_aguardando": pacotes_aguardando,
            "atividade_recente": atividade_recente,
        },
    )
