"""Views da aplicacao de gestao de material de laboratorio."""

from __future__ import annotations

import secrets as _secrets
from datetime import date as date_type

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Page, Paginator
from django.db.models import Q
from django.db.models.query import QuerySet
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import (
    EquipeForm,
    LaboratorioForm,
    MoldagemForm,
    PedidoEntregaForm,
    PedidoEnvioForm,
    PedidoFaturamentoForm,
    PedidoMaterialForm,
)
from .models import (
    AlunoLab,
    Equipe,
    Laboratorio,
    Moldagem,
    Paciente,
    PedidoMaterial,
    RegistroSync,
)

REGISTROS_POR_PAGINA = 10

STATUS_OPCOES = [
    (PedidoMaterial.Status.EM_DIA, "Em dia"),
    (PedidoMaterial.Status.A_CONFIRMAR, "A confirmar"),
    (PedidoMaterial.Status.ATRASADO, "Atrasado"),
]

STATUS_LABELS = {v: l for v, l in STATUS_OPCOES}


def _selecionado(form, campo: str, model):
    """Objeto escolhido num campo de autocomplete, para exibir o "chip".

    Aceita tanto o valor cru enviado no POST (pk) quanto o objeto vindo de
    ``initial`` (ex.: pedido pre-preenchido a partir de uma moldagem).
    """

    valor = form[campo].value()
    if not valor:
        return None
    if isinstance(valor, model):
        return valor
    return model.objects.filter(pk=valor).first()


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
    metricas["total"] = (
        metricas["em_dia"] + metricas["a_confirmar"] + metricas["atrasado"]
    )

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
            "metricas": metricas,
            "hoje": hoje,
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
            "paciente_sel": _selecionado(form, "paciente", Paciente),
            "aluno_sel": _selecionado(form, "aluno", AlunoLab),
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


@login_required
@require_POST
def alternar_faturado_paciente(request: HttpRequest, pk: int) -> HttpResponse:
    pedido = get_object_or_404(PedidoMaterial, pk=pk)
    pedido.faturado_paciente = not pedido.faturado_paciente
    pedido.save(update_fields=["faturado_paciente", "status", "atualizado_em"])
    next_url = request.POST.get("next") or "lab_pedidos_faturamento"
    return redirect(next_url)


@login_required
@require_POST
def alternar_faturado_lab(request: HttpRequest, pk: int) -> HttpResponse:
    pedido = get_object_or_404(PedidoMaterial, pk=pk)
    pedido.faturado_lab = not pedido.faturado_lab
    pedido.save(update_fields=["faturado_lab", "status", "atualizado_em"])
    next_url = request.POST.get("next") or "lab_pedidos_faturamento"
    return redirect(next_url)


@login_required
@require_POST
def excluir_pedido(request: HttpRequest, pk: int) -> HttpResponse:
    """Remove permanentemente um pedido de material.

    Se o pedido tiver vindo de uma moldagem, o vinculo e desfeito (SET_NULL) e a
    moldagem volta a figurar como nao convertida.
    """

    pedido = get_object_or_404(
        PedidoMaterial.objects.select_related("paciente"), pk=pk
    )
    identificacao = f"#{pedido.pk} — {pedido.paciente.nome}"
    tinha_moldagem = Moldagem.objects.filter(pedido_material=pedido).exists()
    pedido.delete()

    msg = f"Pedido {identificacao} excluído permanentemente."
    if tinha_moldagem:
        msg += " A moldagem de origem voltou para 'não convertida'."
    messages.success(request, msg)

    next_url = request.POST.get("next", "")
    if next_url.startswith("/"):
        return HttpResponseRedirect(next_url)
    return redirect("lab_pedidos")


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

    return render(
        request,
        "gestao_lab/pedidos_faturamento.html",
        {
            "pedidos": page_obj,
            "page_obj": page_obj,
            "query_string": query_string,
            "busca": busca,
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

FILTRO_MOLDAGEM_LABELS = dict(FILTRO_MOLDAGEM_OPCOES)


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
            "filtro_label": FILTRO_MOLDAGEM_LABELS.get(filtro, "Todas"),
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

    return render(
        request,
        "gestao_lab/form_moldagem.html",
        {
            "form": form,
            "paciente_sel": _selecionado(form, "paciente", Paciente),
            "aluno_sel": _selecionado(form, "aluno", AlunoLab),
        },
    )


@login_required
@require_POST
def converter_moldagem(request: HttpRequest, pk: int) -> HttpResponse:
    moldagem = get_object_or_404(Moldagem, pk=pk, ativo=True)
    if moldagem.convertida:
        messages.warning(request, f"Moldagem #{pk} já foi convertida em pedido.")
        return redirect("lab_moldagens")
    return redirect(reverse("lab_criar_pedido") + f"?moldagem={moldagem.pk}")


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
    busca = request.GET.get("q", "").strip()
    qs = (
        Laboratorio.objects.filter(ativo=True)
        .prefetch_related("equipes")
        .order_by("nome")
    )
    if busca:
        qs = qs.filter(
            Q(nome__icontains=busca)
            | Q(cnpj__icontains=busca)
            | Q(equipes__nome__icontains=busca)
        ).distinct()

    page_obj, query_string = _paginar(request, qs)
    return render(
        request,
        "gestao_lab/laboratorios.html",
        {
            "laboratorios": page_obj,
            "page_obj": page_obj,
            "query_string": query_string,
            "busca": busca,
            "total": Laboratorio.objects.filter(ativo=True).count(),
        },
    )


@login_required
def criar_laboratorio(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = LaboratorioForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Laboratório cadastrado com sucesso.")
            return redirect("lab_laboratorios")
    else:
        form = LaboratorioForm()
    return render(
        request,
        "gestao_lab/form_laboratorio.html",
        {"form": form, "editando": False},
    )


@login_required
def editar_laboratorio(request: HttpRequest, pk: int) -> HttpResponse:
    lab = get_object_or_404(Laboratorio, pk=pk)
    if request.method == "POST":
        form = LaboratorioForm(request.POST, instance=lab)
        if form.is_valid():
            form.save()
            messages.success(request, "Laboratório atualizado com sucesso.")
            return redirect("lab_laboratorios")
    else:
        form = LaboratorioForm(instance=lab)
    return render(
        request,
        "gestao_lab/form_laboratorio.html",
        {"form": form, "editando": True, "laboratorio": lab},
    )


# ---------------------------------------------------------------------------
# Equipes
# ---------------------------------------------------------------------------


@login_required
def equipes(request: HttpRequest) -> HttpResponse:
    busca = request.GET.get("q", "").strip()
    qs = Equipe.objects.filter(ativo=True).order_by("nome")
    if busca:
        qs = qs.filter(Q(nome__icontains=busca) | Q(coordenador__icontains=busca))

    page_obj, query_string = _paginar(request, qs)
    return render(
        request,
        "gestao_lab/equipes.html",
        {
            "equipes": page_obj,
            "page_obj": page_obj,
            "query_string": query_string,
            "busca": busca,
            "total": Equipe.objects.filter(ativo=True).count(),
        },
    )


@login_required
def criar_equipe(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = EquipeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Equipe cadastrada com sucesso.")
            return redirect("lab_equipes")
    else:
        form = EquipeForm()
    return render(
        request,
        "gestao_lab/form_equipe.html",
        {"form": form, "editando": False},
    )


@login_required
def editar_equipe(request: HttpRequest, pk: int) -> HttpResponse:
    equipe = get_object_or_404(Equipe, pk=pk)
    if request.method == "POST":
        form = EquipeForm(request.POST, instance=equipe)
        if form.is_valid():
            form.save()
            messages.success(request, "Equipe atualizada com sucesso.")
            return redirect("lab_equipes")
    else:
        form = EquipeForm(instance=equipe)
    return render(
        request,
        "gestao_lab/form_equipe.html",
        {"form": form, "editando": True, "equipe": equipe},
    )


@login_required
@require_POST
def excluir_moldagem(request: HttpRequest, pk: int) -> HttpResponse:
    """Remove permanentemente uma moldagem.

    Nao afeta o pedido de material gerado a partir dela, quando existir.
    """

    moldagem = get_object_or_404(Moldagem.objects.select_related("paciente"), pk=pk)
    identificacao = f"#{moldagem.pk} — {moldagem.paciente.nome}"
    moldagem.delete()
    messages.success(request, f"Moldagem {identificacao} excluída permanentemente.")

    next_url = request.POST.get("next", "")
    if next_url.startswith("/"):
        return HttpResponseRedirect(next_url)
    return redirect("lab_moldagens")


# ---------------------------------------------------------------------------
# Busca com selecao (autocomplete) de paciente e aluno
# ---------------------------------------------------------------------------


def _pacientes_locais(q: str):
    itens = Paciente.objects.filter(ativo=True).order_by("nome")
    if q:
        itens = itens.filter(Q(nome__icontains=q) | Q(celular__icontains=q))
    return itens


def _alunos_locais(q: str):
    itens = AlunoLab.objects.filter(ativo=True).order_by("nome")
    if q:
        itens = itens.filter(Q(nome__icontains=q) | Q(celular__icontains=q))
    return itens


@login_required
def buscar_pacientes(request: HttpRequest) -> HttpResponse:
    """Fragmento HTMX com pacientes ja sincronizados, filtrados por nome/celular.

    A base local costuma ter so uma fatia dos pacientes do Dental Office, entao o
    fragmento tambem oferece a busca direta na API (``lab_buscar_pacientes_dental``).
    """

    q = request.GET.get("q", "").strip()
    itens = _pacientes_locais(q)

    return render(
        request,
        "gestao_lab/partials/_ac_results.html",
        {
            "itens": itens[:20],
            "total": itens.count(),
            "busca": q,
            "url_dental": reverse("lab_buscar_pacientes_dental"),
        },
    )


@login_required
def buscar_alunos_lab(request: HttpRequest) -> HttpResponse:
    """Fragmento HTMX com alunos ja sincronizados, filtrados por nome/celular."""

    q = request.GET.get("q", "").strip()
    itens = _alunos_locais(q)

    return render(
        request,
        "gestao_lab/partials/_ac_results.html",
        {
            "itens": itens[:20],
            "total": itens.count(),
            "busca": q,
            "url_dental": reverse("lab_buscar_alunos_lab_dental"),
        },
    )


@login_required
def buscar_pacientes_dental(request: HttpRequest) -> HttpResponse:
    """Busca pacientes direto no Dental Office, importa e devolve o fragmento.

    Necessario porque o pedido referencia um ``Paciente`` local: os registros
    encontrados na API sao importados para obter um pk utilizavel no formulario.
    """

    from django.conf import settings
    from gestao_lab.integrations.dental import DentalAPIError
    from gestao_lab.services.dental_sync import buscar_e_importar_pacientes

    q = request.GET.get("q", "").strip()
    erro = ""
    importados = 0

    if q:
        clinic_id = getattr(settings, "DENTAL_CLINIC_ID", None)
        if not clinic_id:
            erro = "DENTAL_CLINIC_ID não configurado no ambiente."
        else:
            try:
                resultado = buscar_e_importar_pacientes(q=q, clinic_id=clinic_id)
                importados = resultado["criados"] + resultado["atualizados"]
            except DentalAPIError as exc:
                erro = f"Erro na API Dental Office: {exc}"

    itens = _pacientes_locais(q)
    return render(
        request,
        "gestao_lab/partials/_ac_results.html",
        {
            "itens": itens[:20],
            "total": itens.count(),
            "busca": q,
            "url_dental": reverse("lab_buscar_pacientes_dental"),
            "importados": importados,
            "erro_dental": erro,
            "veio_do_dental": True,
        },
    )


@login_required
def buscar_alunos_lab_dental(request: HttpRequest) -> HttpResponse:
    """Busca alunos direto no Dental Office, importa e devolve o fragmento."""

    from django.conf import settings
    from gestao_lab.integrations.dental import DentalAPIError
    from gestao_lab.services.dental_sync import buscar_e_importar_alunos

    q = request.GET.get("q", "").strip()
    erro = ""
    importados = 0

    if q:
        user_group = getattr(settings, "DENTAL_USER_GROUP_ALUNO", 8)
        try:
            resultado = buscar_e_importar_alunos(q=q, user_group=user_group)
            importados = resultado["criados"] + resultado["atualizados"]
        except DentalAPIError as exc:
            erro = f"Erro na API Dental Office: {exc}"

    itens = _alunos_locais(q)
    return render(
        request,
        "gestao_lab/partials/_ac_results.html",
        {
            "itens": itens[:20],
            "total": itens.count(),
            "busca": q,
            "url_dental": reverse("lab_buscar_alunos_lab_dental"),
            "importados": importados,
            "erro_dental": erro,
            "veio_do_dental": True,
        },
    )


# ---------------------------------------------------------------------------
# Alunos e pacientes (Dental Office)
# ---------------------------------------------------------------------------


@login_required
def alunos_lab(request: HttpRequest) -> HttpResponse:
    from django.db.models import Max

    qs = AlunoLab.objects.filter(ativo=True).order_by("nome")
    busca = request.GET.get("q", "").strip()
    if busca:
        qs = qs.filter(Q(nome__icontains=busca) | Q(celular__icontains=busca))

    total = AlunoLab.objects.filter(ativo=True).count()
    ultima_sync = AlunoLab.objects.aggregate(s=Max("ultima_sincronizacao"))["s"]
    historico_sync = RegistroSync.objects.all()[:5]

    page_obj, query_string = _paginar(request, qs)
    return render(
        request,
        "gestao_lab/alunos.html",
        {
            "alunos": page_obj,
            "page_obj": page_obj,
            "query_string": query_string,
            "busca": busca,
            "total": total,
            "ultima_sync": ultima_sync,
            "historico_sync": historico_sync,
        },
    )


@login_required
def pacientes(request: HttpRequest) -> HttpResponse:
    from django.db.models import Max

    qs = Paciente.objects.filter(ativo=True).order_by("nome")
    busca = request.GET.get("q", "").strip()
    processo = request.GET.get("processo", "").strip()
    if busca:
        qs = qs.filter(Q(nome__icontains=busca) | Q(celular__icontains=busca))
    if processo == "aberto":
        qs = qs.filter(processo_aberto=True)

    total = Paciente.objects.filter(ativo=True).count()
    total_abertos = Paciente.objects.filter(ativo=True, processo_aberto=True).count()
    ultima_sync = Paciente.objects.aggregate(s=Max("ultima_sincronizacao"))["s"]
    historico_sync = RegistroSync.objects.all()[:5]

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
            "total": total,
            "total_abertos": total_abertos,
            "ultima_sync": ultima_sync,
            "historico_sync": historico_sync,
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
    from gestao_lab.services.dental_sync import executar_sync_e_registrar

    clinic_id = getattr(settings, "DENTAL_CLINIC_ID", None)
    user_group = getattr(settings, "DENTAL_USER_GROUP_ALUNO", 8)

    # Volta para a listagem de origem (alunos ou pacientes), quando informada.
    next_url = request.POST.get("next", "")
    destino = (
        HttpResponseRedirect(next_url)
        if next_url.startswith("/")
        else redirect("lab_pacientes")
    )

    if not clinic_id:
        messages.error(request, "DENTAL_CLINIC_ID não configurado no ambiente.")
        return destino

    try:
        registro = executar_sync_e_registrar(
            clinic_id=clinic_id,
            user_group=user_group,
            disparado_por=request.user.username,
            tipo=RegistroSync.Tipo.COMPLETA,
        )
        messages.success(
            request,
            f"Sincronização concluída em {registro.duracao_segundos}s — "
            f"Pacientes: {registro.pacientes_criados} criado(s), "
            f"{registro.pacientes_atualizados} atualizado(s). "
            f"Alunos: {registro.alunos_criados} criado(s), "
            f"{registro.alunos_atualizados} atualizado(s).",
        )
    except DentalAPIError as exc:
        messages.error(request, f"Erro na API Dental Office: {exc}")

    return destino


# ---------------------------------------------------------------------------
# Busca direcionada Dental Office (importação pontual durante cadastro)
# ---------------------------------------------------------------------------

_DESTINOS_VALIDOS = frozenset(
    {"lab_criar_pedido", "lab_criar_moldagem", "lab_pacientes", "lab_alunos"}
)


@login_required
def buscar_paciente_dental(request: HttpRequest) -> HttpResponse:
    from django.conf import settings
    from gestao_lab.integrations.dental import DentalAPIError
    from gestao_lab.services.dental_sync import buscar_e_importar_pacientes

    q = request.GET.get("q", "").strip()
    next_name = request.GET.get("next", "lab_criar_pedido")
    if next_name not in _DESTINOS_VALIDOS:
        next_name = "lab_criar_pedido"

    if not q:
        messages.warning(request, "Informe um nome para buscar o paciente.")
        return redirect(next_name)

    clinic_id = getattr(settings, "DENTAL_CLINIC_ID", None)
    if not clinic_id:
        messages.error(request, "DENTAL_CLINIC_ID não configurado no ambiente.")
        return redirect(next_name)

    try:
        resultado = buscar_e_importar_pacientes(q=q, clinic_id=clinic_id)
        total = resultado["criados"] + resultado["atualizados"]
        if total == 0:
            messages.warning(
                request,
                f'Nenhum paciente encontrado para "{q}" no Dental Office.',
            )
        else:
            messages.success(
                request,
                f'{resultado["criados"]} novo(s) paciente(s) importado(s) para "{q}". '
                "Selecione o paciente na lista abaixo.",
            )
    except DentalAPIError as exc:
        messages.error(request, f"Erro na API Dental Office: {exc}")

    return redirect(next_name)


@login_required
def buscar_aluno_dental(request: HttpRequest) -> HttpResponse:
    from django.conf import settings
    from gestao_lab.integrations.dental import DentalAPIError
    from gestao_lab.services.dental_sync import buscar_e_importar_alunos

    q = request.GET.get("q", "").strip()
    next_name = request.GET.get("next", "lab_criar_pedido")
    if next_name not in _DESTINOS_VALIDOS:
        next_name = "lab_criar_pedido"

    if not q:
        messages.warning(request, "Informe um nome para buscar o aluno.")
        return redirect(next_name)

    user_group = getattr(settings, "DENTAL_USER_GROUP_ALUNO", 8)

    try:
        resultado = buscar_e_importar_alunos(q=q, user_group=user_group)
        total = resultado["criados"] + resultado["atualizados"]
        if total == 0:
            messages.warning(
                request,
                f'Nenhum aluno encontrado para "{q}" no Dental Office.',
            )
        else:
            messages.success(
                request,
                f'{resultado["criados"]} novo(s) aluno(s) importado(s) para "{q}". '
                "Selecione o aluno na lista abaixo.",
            )
    except DentalAPIError as exc:
        messages.error(request, f"Erro na API Dental Office: {exc}")

    return redirect(next_name)


# ---------------------------------------------------------------------------
# Sincronização agendada — endpoint com token (Railway Cron / GitHub Actions)
# ---------------------------------------------------------------------------


@csrf_exempt
def sincronizar_agendado(request: HttpRequest) -> JsonResponse:
    """Endpoint de sincronização agendada autenticado por token secreto.

    Uso com Railway Cron ou qualquer serviço externo:
        POST /laboratorio/sincronizar-agendado/
        Header: X-Sync-Token: <DENTAL_SYNC_TOKEN>

    Retorna JSON com o resultado da sincronização.
    Requer DENTAL_SYNC_TOKEN configurado nas variáveis de ambiente.
    """
    if request.method != "POST":
        return JsonResponse({"erro": "Método não permitido."}, status=405)

    from django.conf import settings
    from gestao_lab.integrations.dental import DentalAPIError
    from gestao_lab.services.dental_sync import executar_sync_e_registrar

    token_esperado = getattr(settings, "DENTAL_SYNC_TOKEN", "")
    token_recebido = request.headers.get("X-Sync-Token") or request.POST.get(
        "token", ""
    )

    if not token_esperado or not _secrets.compare_digest(
        token_recebido, token_esperado
    ):
        return JsonResponse({"erro": "Token inválido ou ausente."}, status=403)

    clinic_id = getattr(settings, "DENTAL_CLINIC_ID", None)
    user_group = getattr(settings, "DENTAL_USER_GROUP_ALUNO", 8)

    if not clinic_id:
        return JsonResponse({"erro": "DENTAL_CLINIC_ID não configurado."}, status=500)

    try:
        registro = executar_sync_e_registrar(
            clinic_id=clinic_id,
            user_group=user_group,
            disparado_por="cron",
            tipo=RegistroSync.Tipo.AGENDADA,
        )
        return JsonResponse(
            {
                "sucesso": True,
                "pacientes_criados": registro.pacientes_criados,
                "pacientes_atualizados": registro.pacientes_atualizados,
                "alunos_criados": registro.alunos_criados,
                "alunos_atualizados": registro.alunos_atualizados,
                "duracao_segundos": registro.duracao_segundos,
            }
        )
    except DentalAPIError as exc:
        return JsonResponse({"sucesso": False, "erro": str(exc)}, status=502)
    except Exception as exc:
        return JsonResponse({"sucesso": False, "erro": str(exc)}, status=500)
