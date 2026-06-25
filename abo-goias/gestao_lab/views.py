"""Views da aplicacao de gestao de material de laboratorio."""

from __future__ import annotations

from datetime import date as date_type

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Page, Paginator
from django.db.models import Q
from django.db.models.query import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import (
    MoldagemForm,
    PedidoEntregaForm,
    PedidoEnvioForm,
    PedidoFaturamentoForm,
    PedidoMaterialForm,
)
from .models import (
    AlunoLab,
    Moldagem,
    Paciente,
    PedidoMaterial,
)

REGISTROS_POR_PAGINA = 10

STATUS_OPCOES = [
    (PedidoMaterial.Status.EM_DIA, "Em dia"),
    (PedidoMaterial.Status.A_CONFIRMAR, "A confirmar"),
    (PedidoMaterial.Status.ATRASADO, "Atrasado"),
]

STATUS_LABELS = {v: l for v, l in STATUS_OPCOES}


def _paginar(request: HttpRequest, queryset: QuerySet) -> tuple[Page, str]:
    params = request.GET.copy()
    params.pop("page", None)
    paginator = Paginator(queryset, REGISTROS_POR_PAGINA)
    return paginator.get_page(request.GET.get("page")), params.urlencode()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    hoje = date_type.today()
    qs = PedidoMaterial.objects.all()

    metricas = {
        "em_dia": qs.filter(status=PedidoMaterial.Status.EM_DIA).count(),
        "a_confirmar": qs.filter(status=PedidoMaterial.Status.A_CONFIRMAR).count(),
        "atrasado": qs.filter(status=PedidoMaterial.Status.ATRASADO).count(),
        "pendentes_faturamento": qs.filter(entregue=True)
        .exclude(faturado_paciente=True, faturado_lab=True)
        .count(),
        "concluidos": qs.filter(status=PedidoMaterial.Status.CONCLUIDO).count(),
    }

    proximas_entregas = (
        qs.filter(entregue=False)
        .select_related("paciente", "laboratorio")
        .order_by("previsao_entrega")[:5]
    )

    recentes = qs.select_related("paciente", "aluno", "laboratorio").order_by(
        "-criado_em"
    )[:6]

    return render(
        request,
        "gestao_lab/dashboard.html",
        {
            "metricas": metricas,
            "proximas_entregas": proximas_entregas,
            "recentes": recentes,
            "hoje": hoje,
        },
    )


# ---------------------------------------------------------------------------
# Pedidos — acompanhamento
# ---------------------------------------------------------------------------


@login_required
def acompanhamento_pedidos(request: HttpRequest) -> HttpResponse:
    hoje = date_type.today()
    qs = (
        PedidoMaterial.objects.filter(
            status__in=[
                PedidoMaterial.Status.EM_DIA,
                PedidoMaterial.Status.A_CONFIRMAR,
                PedidoMaterial.Status.ATRASADO,
            ]
        )
        .select_related("paciente", "aluno", "laboratorio", "equipe")
        .order_by("previsao_entrega")
    )

    busca = request.GET.get("q", "").strip()
    status_filtro = request.GET.get("status", "").strip()

    if busca:
        qs = qs.filter(
            Q(paciente__nome__icontains=busca)
            | Q(aluno__nome__icontains=busca)
            | Q(laboratorio__nome__icontains=busca)
            | Q(descricao_servico__icontains=busca)
        )

    if status_filtro:
        qs = qs.filter(status=status_filtro)

    metricas = {
        "em_dia": PedidoMaterial.objects.filter(
            status=PedidoMaterial.Status.EM_DIA
        ).count(),
        "a_confirmar": PedidoMaterial.objects.filter(
            status=PedidoMaterial.Status.A_CONFIRMAR
        ).count(),
        "atrasado": PedidoMaterial.objects.filter(
            status=PedidoMaterial.Status.ATRASADO
        ).count(),
    }

    page_obj, query_string = _paginar(request, qs)
    status_label = STATUS_LABELS.get(status_filtro, "Todos")

    return render(
        request,
        "gestao_lab/acompanhamento_pedidos.html",
        {
            "pedidos": page_obj,
            "page_obj": page_obj,
            "query_string": query_string,
            "busca": busca,
            "status_filtro": status_filtro,
            "status_label": status_label,
            "status_opcoes": STATUS_OPCOES,
            "metricas": metricas,
            "hoje": hoje,
            "form_envio": PedidoEnvioForm(),
        },
    )


# ---------------------------------------------------------------------------
# Pedidos — criar
# ---------------------------------------------------------------------------


@login_required
def criar_pedido(request: HttpRequest) -> HttpResponse:
    moldagem_origem = None
    initial: dict = {}

    moldagem_id = request.GET.get("moldagem")
    if moldagem_id:
        try:
            moldagem_origem = Moldagem.objects.select_related("paciente", "aluno").get(
                pk=moldagem_id, ativo=True
            )
            initial = {
                "paciente": moldagem_origem.paciente,
                "aluno": moldagem_origem.aluno,
            }
        except Moldagem.DoesNotExist:
            pass

    if request.method == "POST":
        form = PedidoMaterialForm(request.POST)
        if form.is_valid():
            pedido = form.save()
            if moldagem_origem and not moldagem_origem.pedido_material:
                moldagem_origem.pedido_material = pedido
                moldagem_origem.save(update_fields=["pedido_material", "atualizado_em"])
            messages.success(request, f"Pedido #{pedido.pk} registrado com sucesso.")
            return redirect("lab_pedidos")
    else:
        form = PedidoMaterialForm(initial=initial)

    return render(
        request,
        "gestao_lab/form_pedido.html",
        {
            "form": form,
            "moldagem_origem": moldagem_origem,
        },
    )


# ---------------------------------------------------------------------------
# Pedidos — detalhe
# ---------------------------------------------------------------------------


@login_required
def detalhe_pedido(request: HttpRequest, pk: int) -> HttpResponse:
    pedido = get_object_or_404(
        PedidoMaterial.objects.select_related(
            "paciente", "aluno", "laboratorio", "equipe"
        ),
        pk=pk,
    )
    return render(
        request,
        "gestao_lab/detalhe_pedido.html",
        {
            "pedido": pedido,
            "form_envio": PedidoEnvioForm(),
            "form_entrega": PedidoEntregaForm(),
            "form_faturamento": PedidoFaturamentoForm(instance=pedido),
            "hoje": date_type.today(),
        },
    )


# ---------------------------------------------------------------------------
# Pedidos — ações POST
# ---------------------------------------------------------------------------


@login_required
@require_POST
def marcar_envio(request: HttpRequest, pk: int) -> HttpResponse:
    pedido = get_object_or_404(PedidoMaterial, pk=pk)
    form = PedidoEnvioForm(request.POST)
    if form.is_valid():
        pedido.data_envio = form.cleaned_data["data_envio"]
        pedido.save()
        messages.success(request, f"Envio do pedido #{pedido.pk} registrado.")
    else:
        messages.error(request, "Data de envio inválida.")
    next_url = request.POST.get("next") or "lab_pedidos"
    return redirect(next_url)


@login_required
@require_POST
def marcar_entrega(request: HttpRequest, pk: int) -> HttpResponse:
    pedido = get_object_or_404(PedidoMaterial, pk=pk)
    form = PedidoEntregaForm(request.POST)
    if form.is_valid():
        pedido.entregue = True
        pedido.data_entrega = form.cleaned_data["data_entrega"]
        pedido.save()
        messages.success(request, f"Entrega do pedido #{pedido.pk} registrada.")
    else:
        messages.error(request, "Data de entrega inválida.")
    next_url = request.POST.get("next") or "lab_pedidos"
    return redirect(next_url)


@login_required
@require_POST
def atualizar_faturamento(request: HttpRequest, pk: int) -> HttpResponse:
    pedido = get_object_or_404(PedidoMaterial, pk=pk)
    form = PedidoFaturamentoForm(request.POST, instance=pedido)
    if form.is_valid():
        form.save()
        messages.success(request, f"Faturamento do pedido #{pedido.pk} atualizado.")
    else:
        messages.error(request, "Erro ao salvar informações financeiras.")
    next_url = request.POST.get("next") or "lab_pedidos_faturamento"
    return redirect(next_url)


# ---------------------------------------------------------------------------
# Pedidos — faturamento
# ---------------------------------------------------------------------------


@login_required
def pedidos_faturamento(request: HttpRequest) -> HttpResponse:
    qs = (
        PedidoMaterial.objects.filter(entregue=True)
        .exclude(faturado_paciente=True, faturado_lab=True)
        .select_related("paciente", "aluno", "laboratorio", "equipe")
        .order_by("data_entrega")
    )

    busca = request.GET.get("q", "").strip()
    if busca:
        qs = qs.filter(
            Q(paciente__nome__icontains=busca)
            | Q(aluno__nome__icontains=busca)
            | Q(laboratorio__nome__icontains=busca)
        )

    page_obj, query_string = _paginar(request, qs)

    forms_faturamento = {
        pedido.pk: PedidoFaturamentoForm(instance=pedido) for pedido in page_obj
    }

    return render(
        request,
        "gestao_lab/pedidos_faturamento.html",
        {
            "pedidos": page_obj,
            "page_obj": page_obj,
            "query_string": query_string,
            "busca": busca,
            "forms_faturamento": forms_faturamento,
        },
    )


# ---------------------------------------------------------------------------
# Moldagens
# ---------------------------------------------------------------------------

FILTRO_MOLDAGEM_OPCOES = [
    ("faturado", "Faturado"),
    ("nao_faturado", "Não faturado"),
    ("entregue", "Entregue ao lab"),
    ("nao_entregue", "Não entregue"),
    ("convertida", "Convertida em pedido"),
    ("nao_convertida", "Não convertida"),
]


@login_required
def moldagens(request: HttpRequest) -> HttpResponse:
    qs = (
        Moldagem.objects.filter(ativo=True)
        .select_related("paciente", "aluno", "pedido_material")
        .order_by("-criado_em")
    )

    busca = request.GET.get("q", "").strip()
    filtro = request.GET.get("filtro", "").strip()

    if busca:
        qs = qs.filter(
            Q(paciente__nome__icontains=busca) | Q(aluno__nome__icontains=busca)
        )

    if filtro == "faturado":
        qs = qs.filter(faturado=True)
    elif filtro == "nao_faturado":
        qs = qs.filter(faturado=False)
    elif filtro == "entregue":
        qs = qs.filter(entregue=True)
    elif filtro == "nao_entregue":
        qs = qs.filter(entregue=False)
    elif filtro == "convertida":
        qs = qs.exclude(pedido_material=None)
    elif filtro == "nao_convertida":
        qs = qs.filter(pedido_material=None)

    metricas = {
        "total": Moldagem.objects.filter(ativo=True).count(),
        "faturadas": Moldagem.objects.filter(ativo=True, faturado=True).count(),
        "entregues": Moldagem.objects.filter(ativo=True, entregue=True).count(),
        "convertidas": Moldagem.objects.filter(ativo=True)
        .exclude(pedido_material=None)
        .count(),
        "pendentes": Moldagem.objects.filter(ativo=True, pedido_material=None).count(),
    }

    page_obj, query_string = _paginar(request, qs)

    return render(
        request,
        "gestao_lab/moldagens.html",
        {
            "moldagens": page_obj,
            "page_obj": page_obj,
            "query_string": query_string,
            "busca": busca,
            "filtro": filtro,
            "filtro_opcoes": FILTRO_MOLDAGEM_OPCOES,
            "metricas": metricas,
        },
    )


@login_required
def criar_moldagem(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = MoldagemForm(request.POST)
        if form.is_valid():
            moldagem = form.save()
            messages.success(
                request, f"Moldagem #{moldagem.pk} registrada com sucesso."
            )
            return redirect("lab_moldagens")
    else:
        form = MoldagemForm()

    return render(request, "gestao_lab/form_moldagem.html", {"form": form})


@login_required
@require_POST
def converter_moldagem(request: HttpRequest, pk: int) -> HttpResponse:
    moldagem = get_object_or_404(Moldagem, pk=pk, ativo=True)
    if moldagem.convertida:
        messages.warning(request, f"Moldagem #{pk} já foi convertida em pedido.")
        return redirect("lab_moldagens")
    return redirect(f"/laboratorio/pedidos/novo/?moldagem={moldagem.pk}")


@login_required
@require_POST
def alternar_faturado_moldagem(request: HttpRequest, pk: int) -> HttpResponse:
    moldagem = get_object_or_404(Moldagem, pk=pk, ativo=True)
    moldagem.faturado = not moldagem.faturado
    moldagem.save(update_fields=["faturado", "atualizado_em"])
    estado = "faturada" if moldagem.faturado else "não faturada"
    messages.success(request, f"Moldagem #{pk} marcada como {estado}.")
    next_url = request.POST.get("next") or "lab_moldagens"
    return redirect(next_url)


@login_required
@require_POST
def alternar_entregue_moldagem(request: HttpRequest, pk: int) -> HttpResponse:
    moldagem = get_object_or_404(Moldagem, pk=pk, ativo=True)
    moldagem.entregue = not moldagem.entregue
    moldagem.save(update_fields=["entregue", "atualizado_em"])
    estado = "entregue" if moldagem.entregue else "não entregue"
    messages.success(request, f"Moldagem #{pk} marcada como {estado}.")
    next_url = request.POST.get("next") or "lab_moldagens"
    return redirect(next_url)


# ---------------------------------------------------------------------------
# Laboratórios
# ---------------------------------------------------------------------------


@login_required
def laboratorios(request: HttpRequest) -> HttpResponse:
    return render(request, "gestao_lab/laboratorios.html")


@login_required
def criar_laboratorio(request: HttpRequest) -> HttpResponse:
    return render(request, "gestao_lab/form_laboratorio.html")


@login_required
def editar_laboratorio(request: HttpRequest, pk: int) -> HttpResponse:
    return render(request, "gestao_lab/form_laboratorio.html")


# ---------------------------------------------------------------------------
# Equipes
# ---------------------------------------------------------------------------


@login_required
def equipes(request: HttpRequest) -> HttpResponse:
    return render(request, "gestao_lab/equipes.html")


@login_required
def criar_equipe(request: HttpRequest) -> HttpResponse:
    return render(request, "gestao_lab/form_equipe.html")


@login_required
def editar_equipe(request: HttpRequest, pk: int) -> HttpResponse:
    return render(request, "gestao_lab/form_equipe.html")


# ---------------------------------------------------------------------------
# Alunos e pacientes (Dental Office)
# ---------------------------------------------------------------------------


@login_required
def alunos_lab(request: HttpRequest) -> HttpResponse:
    qs = AlunoLab.objects.filter(ativo=True).order_by("nome")
    busca = request.GET.get("q", "").strip()
    if busca:
        qs = qs.filter(Q(nome__icontains=busca) | Q(celular__icontains=busca))
    page_obj, query_string = _paginar(request, qs)
    return render(
        request,
        "gestao_lab/alunos.html",
        {
            "alunos": page_obj,
            "page_obj": page_obj,
            "query_string": query_string,
            "busca": busca,
        },
    )


@login_required
def pacientes(request: HttpRequest) -> HttpResponse:
    qs = Paciente.objects.filter(ativo=True).order_by("nome")
    busca = request.GET.get("q", "").strip()
    processo = request.GET.get("processo", "").strip()
    if busca:
        qs = qs.filter(Q(nome__icontains=busca) | Q(celular__icontains=busca))
    if processo == "aberto":
        qs = qs.filter(processo_aberto=True)
    page_obj, query_string = _paginar(request, qs)
    return render(
        request,
        "gestao_lab/pacientes.html",
        {
            "pacientes": page_obj,
            "page_obj": page_obj,
            "query_string": query_string,
            "busca": busca,
            "processo_filtro": processo,
            "hoje": date_type.today(),
        },
    )


# ---------------------------------------------------------------------------
# Sincronização Dental Office
# ---------------------------------------------------------------------------


@login_required
@require_POST
def sincronizar_dental(request: HttpRequest) -> HttpResponse:
    from django.conf import settings
    from gestao_lab.integrations.dental import DentalAPIError
    from gestao_lab.services.dental_sync import (
        sincronizar_alunos,
        sincronizar_pacientes,
    )

    clinic_id = getattr(settings, "DENTAL_CLINIC_ID", None)
    user_group = getattr(settings, "DENTAL_USER_GROUP_ALUNO", 8)

    if not clinic_id:
        messages.error(request, "DENTAL_CLINIC_ID não configurado no ambiente.")
        return redirect("lab_pacientes")

    try:
        rp = sincronizar_pacientes(clinic_id=clinic_id)
        ra = sincronizar_alunos(user_group=user_group)
        messages.success(
            request,
            f"Sincronização concluída — "
            f"Pacientes: {rp['criados']} criado(s), {rp['atualizados']} atualizado(s). "
            f"Alunos: {ra['criados']} criado(s), {ra['atualizados']} atualizado(s).",
        )
    except DentalAPIError as exc:
        messages.error(request, f"Erro na API Dental Office: {exc}")

    return redirect("lab_pacientes")
