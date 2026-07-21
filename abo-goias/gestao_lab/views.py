"""Views da aplicacao de gestao de material de laboratorio."""

from __future__ import annotations

import logging
import secrets as _secrets
from datetime import date as date_type
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Page, Paginator
from django.db.models import Min, Q
from django.db.models.query import QuerySet
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from gestao_cme.utils import normalizar_texto

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

logger = logging.getLogger(__name__)

REGISTROS_POR_PAGINA = 10

STATUS_OPCOES = [
    (PedidoMaterial.Status.EM_DIA, "Em dia"),
    (PedidoMaterial.Status.ATRASADO, "Atrasado"),
    (PedidoMaterial.Status.ENTREGUE_NAO_FATURADO, "Entregue — não faturado"),
    (PedidoMaterial.Status.CONCLUIDO, "Concluído"),
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


def _parse_data_br(valor: str, fim_do_dia: bool = False) -> datetime | None:
    """Converte "dd/mm/aaaa" em datetime aware, ou None se invalido.

    Mesmo contrato do helper homonimo em gestao_cme.views — o filtro de periodo
    do acompanhamento espelha o comportamento do CME.
    """

    if not valor:
        return None
    try:
        dt = datetime.strptime(valor, "%d/%m/%Y")
    except ValueError:
        return None
    if fim_do_dia:
        dt = dt.replace(hour=23, minute=59, second=59)
    return timezone.make_aware(dt)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    hoje = date_type.today()
    qs = PedidoMaterial.objects.all()

    metricas = {
        "em_dia": qs.filter(status=PedidoMaterial.Status.EM_DIA).count(),
        "atrasado": qs.filter(status=PedidoMaterial.Status.ATRASADO).count(),
        "entregue_nao_faturado": qs.filter(
            status=PedidoMaterial.Status.ENTREGUE_NAO_FATURADO
        ).count(),
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

    # Antes só os pedidos em aberto apareciam. Agora os concluídos também entram
    # (default → todos), senão as novas colunas de entrega/faturamento nunca
    # teriam conteúdo: o pedido some da tela no instante em que é faturado.
    qs = PedidoMaterial.objects.select_related(
        "paciente", "aluno", "laboratorio", "equipe"
    ).order_by("-criado_em")

    busca = request.GET.get("q", "").strip()
    status_filtro = request.GET.get("status", "").strip()
    data_inicio_str = request.GET.get("data_inicio", "").strip()
    data_fim_str = request.GET.get("data_fim", "").strip()

    if busca:
        qs = qs.filter(
            Q(paciente__nome_normalizado__icontains=normalizar_texto(busca))
            | Q(aluno__nome_normalizado__icontains=normalizar_texto(busca))
            | Q(laboratorio__nome__icontains=busca)
            | Q(descricao_servico__icontains=busca)
        )

    if status_filtro:
        qs = qs.filter(status=status_filtro)

    # Filtro de período (mesmo comportamento do CME) — recorta pela data de
    # registro do pedido. Default: 1º registro → hoje (todo o histórico).
    if not data_inicio_str and not data_fim_str:
        primeiro = PedidoMaterial.objects.aggregate(Min("criado_em"))["criado_em__min"]
        inicio_padrao = timezone.localtime(primeiro).date() if primeiro else hoje
        data_inicio_str = inicio_padrao.strftime("%d/%m/%Y")
        data_fim_str = hoje.strftime("%d/%m/%Y")

    data_inicio = _parse_data_br(data_inicio_str)
    data_fim = _parse_data_br(data_fim_str, fim_do_dia=True)
    if data_inicio_str and data_inicio is None:
        data_inicio_str = ""
    if data_fim_str and data_fim is None:
        data_fim_str = ""
    if data_inicio:
        qs = qs.filter(criado_em__gte=data_inicio)
    if data_fim:
        qs = qs.filter(criado_em__lte=data_fim)

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
            "data_inicio_str": data_inicio_str,
            "data_fim_str": data_fim_str,
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
    pedido.save(
        update_fields=[
            "faturado_paciente",
            "data_faturamento",
            "status",
            "atualizado_em",
        ]
    )
    next_url = request.POST.get("next") or "lab_pedidos_faturamento"
    return redirect(next_url)


@login_required
@require_POST
def alternar_faturado_lab(request: HttpRequest, pk: int) -> HttpResponse:
    pedido = get_object_or_404(PedidoMaterial, pk=pk)
    pedido.faturado_lab = not pedido.faturado_lab
    pedido.save(
        update_fields=[
            "faturado_lab",
            "data_faturamento",
            "status",
            "atualizado_em",
        ]
    )
    next_url = request.POST.get("next") or "lab_pedidos_faturamento"
    return redirect(next_url)


@login_required
@require_POST
def excluir_pedido(request: HttpRequest, pk: int) -> HttpResponse:
    """Remove permanentemente um pedido de material.

    Se o pedido tiver vindo de uma moldagem, o vinculo e desfeito (SET_NULL) e a
    moldagem volta a figurar como nao convertida.
    """

    pedido = get_object_or_404(PedidoMaterial.objects.select_related("paciente"), pk=pk)
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
            Q(paciente__nome_normalizado__icontains=normalizar_texto(busca))
            | Q(aluno__nome_normalizado__icontains=normalizar_texto(busca))
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
            Q(paciente__nome_normalizado__icontains=normalizar_texto(busca))
            | Q(aluno__nome_normalizado__icontains=normalizar_texto(busca))
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
        itens = itens.filter(
            Q(nome_normalizado__icontains=normalizar_texto(q)) | Q(celular__icontains=q)
        )
    return itens


def _alunos_locais(q: str):
    itens = AlunoLab.objects.filter(ativo=True).order_by("nome")
    if q:
        itens = itens.filter(
            Q(nome_normalizado__icontains=normalizar_texto(q)) | Q(celular__icontains=q)
        )
    return itens


_LIMITE_RESULTADOS = 20


def _unificar(locais, remotos, limite: int = 20) -> list[dict]:
    """Junta o que ja esta no banco com o que a API devolveu, sem duplicar.

    A lista sai ordenada por nome, mas o corte pelo ``limite`` nunca descarta um
    registro local em favor de um remoto: uma pagina cheia da API tem nomes que
    vem antes no alfabeto e escondia quem ja estava cadastrado. Os remotos so
    preenchem as vagas que sobram, e vao sem ``pk`` — sinal de que precisam ser
    gravados no clique.
    """

    vistos = {str(obj.id_dental) for obj in locais}

    itens_locais = [
        {
            "pk": obj.pk,
            "id_dental": obj.id_dental,
            "nome": obj.nome,
            "celular": obj.celular,
        }
        for obj in locais
    ]

    itens_remotos = []
    for remoto in remotos:
        id_dental = str(remoto.id)
        if id_dental in vistos:
            continue
        vistos.add(id_dental)
        itens_remotos.append(
            {
                "pk": None,
                "id_dental": id_dental,
                "nome": remoto.nome,
                "celular": remoto.celular,
            }
        )

    vagas = max(0, limite - len(itens_locais))
    itens = itens_locais[:limite] + itens_remotos[:vagas]
    itens.sort(key=lambda item: item["nome"])
    return itens


def _buscar_unificado(request: HttpRequest, tipo: str) -> HttpResponse:
    """Fragmento HTMX do autocomplete de paciente/aluno.

    Mostra numa lista so o que ja esta no banco e o que a busca no Dental Office
    devolve (primeira pagina, sem gravar) — o operador nao precisa saber de onde
    veio cada resultado. Se a API falhar, os resultados locais continuam
    aparecendo com um aviso de que a lista pode estar incompleta.
    """

    from django.conf import settings
    from gestao_lab.integrations.dental import DentalAPIError
    from gestao_lab.services.dental_sync import procurar_alunos, procurar_pacientes

    q = request.GET.get("q", "").strip()
    if not q:
        return render(request, "gestao_lab/partials/_ac_results.html", {"busca": ""})

    e_paciente = tipo == "paciente"
    locais = list(
        (_pacientes_locais(q) if e_paciente else _alunos_locais(q))[:_LIMITE_RESULTADOS]
    )

    remotos: list = []
    parcial = False
    ha_mais = False

    try:
        if e_paciente:
            clinic_id = getattr(settings, "DENTAL_CLINIC_ID", None)
            if not clinic_id:
                raise DentalAPIError("clinic_id não configurado")
            remotos, total_paginas = procurar_pacientes(q=q, clinic_id=clinic_id)
        else:
            user_group = getattr(settings, "DENTAL_USER_GROUP_ALUNO", 8)
            remotos, total_paginas = procurar_alunos(q=q, user_group=user_group)
        ha_mais = total_paginas > 1
    except DentalAPIError as exc:
        # Degradacao suave: sem a API a busca ainda vale para quem ja esta no banco.
        logger.warning("autocomplete %s: busca externa indisponivel (%s)", tipo, exc)
        parcial = True

    itens = _unificar(locais, remotos, limite=_LIMITE_RESULTADOS)
    truncou = len(locais) + len(remotos) > len(itens)

    return render(
        request,
        "gestao_lab/partials/_ac_results.html",
        {
            "itens": itens,
            "busca": q,
            "ha_mais": bool(itens) and (ha_mais or truncou),
            "parcial": parcial,
        },
    )


@login_required
def buscar_pacientes(request: HttpRequest) -> HttpResponse:
    """Autocomplete de paciente (base local + Dental Office, sem gravar)."""

    return _buscar_unificado(request, "paciente")


@login_required
def buscar_alunos_lab(request: HttpRequest) -> HttpResponse:
    """Autocomplete de aluno (base local + Dental Office, sem gravar)."""

    return _buscar_unificado(request, "aluno")


@login_required
@require_POST
def materializar(request: HttpRequest, tipo: str) -> JsonResponse:
    """Grava o registro escolhido no autocomplete e devolve o pk para o formulario.

    E aqui — e so aqui — que um resultado vindo da API vira registro local: um
    write, do item que o operador realmente escolheu, em vez de importar a busca
    inteira. Para itens que ja existiam, resolve direto no banco.
    """

    from django.conf import settings
    from gestao_lab.integrations.dental import DentalAPIError
    from gestao_lab.services.dental_sync import (
        materializar_aluno,
        materializar_paciente,
    )

    id_dental = request.POST.get("id_dental", "").strip()
    nome_hint = request.POST.get("nome", "").strip()
    if tipo not in {"paciente", "aluno"} or not id_dental:
        return JsonResponse({"erro": "Requisição inválida."}, status=400)

    try:
        if tipo == "paciente":
            clinic_id = getattr(settings, "DENTAL_CLINIC_ID", None)
            if not clinic_id:
                return JsonResponse(
                    {"erro": "A busca não está configurada. Avise o suporte técnico."},
                    status=503,
                )
            obj = materializar_paciente(id_dental=id_dental, clinic_id=clinic_id)
        else:
            user_group = getattr(settings, "DENTAL_USER_GROUP_ALUNO", 8)
            obj = materializar_aluno(
                id_dental=id_dental, nome_hint=nome_hint, user_group=user_group
            )
    except DentalAPIError as exc:
        logger.warning("materializar %s %s: %s", tipo, id_dental, exc)
        return JsonResponse(
            {"erro": "Não foi possível concluir a seleção agora. Tente de novo."},
            status=502,
        )

    if obj is None:
        return JsonResponse({"erro": "Registro não encontrado."}, status=404)

    return JsonResponse({"pk": obj.pk, "nome": obj.nome})


# ---------------------------------------------------------------------------
# Alunos e pacientes (Dental Office)
# ---------------------------------------------------------------------------


@login_required
def alunos_lab(request: HttpRequest) -> HttpResponse:
    from django.db.models import Max

    qs = AlunoLab.objects.filter(ativo=True).order_by("nome")
    busca = request.GET.get("q", "").strip()
    if busca:
        qs = qs.filter(
            Q(nome_normalizado__icontains=normalizar_texto(busca))
            | Q(celular__icontains=busca)
        )

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
    """Lista pacientes com busca unificada (base local + Dental Office ao vivo).

    Segue o mesmo padrão da app de contratos: em vez de um botão de "Atualizar
    lista" (que sincroniza tudo e pode demorar muito), a busca consulta a base
    local e, havendo termo, também o Dental Office ao vivo — avisando quando há
    mais resultados do que os exibidos, para o usuário refinar a busca.

    A coluna de "processo em aberto" foi trocada por "pedido em aberto": se o
    paciente tem algum PedidoMaterial ainda não concluído (ver
    PedidoMaterial.Status).
    """

    from django.conf import settings
    from gestao_lab.integrations.dental import DentalAPIError
    from gestao_lab.services.dental_sync import procurar_pacientes

    busca = request.GET.get("q", "").strip()
    pedido_filtro = request.GET.get("pedido", "").strip()

    qs = Paciente.objects.filter(ativo=True).order_by("nome")
    if busca:
        qs = qs.filter(
            Q(nome_normalizado__icontains=normalizar_texto(busca))
            | Q(celular__icontains=busca)
        )

    # "Pedido em aberto" = existe pedido do paciente que não está concluído.
    pacientes_com_pedido_aberto = set(
        PedidoMaterial.objects.exclude(
            status=PedidoMaterial.Status.CONCLUIDO
        ).values_list("paciente_id", flat=True)
    )
    if pedido_filtro == "aberto":
        qs = qs.filter(pk__in=pacientes_com_pedido_aberto)

    total = Paciente.objects.filter(ativo=True).count()
    total_abertos = len(pacientes_com_pedido_aberto)

    page_obj, query_string = _paginar(request, qs)
    for paciente in page_obj.object_list:
        paciente.tem_pedido_aberto = paciente.pk in pacientes_com_pedido_aberto

    # Busca ao vivo no Dental Office (só na 1ª página, só com termo) — traz quem
    # ainda não está na base local, sem gravar nada. Ver contratos.views.
    pacientes_dental: list[dict] = []
    erro_dental = ""
    dental_ha_mais = False
    primeira_pagina = request.GET.get("page") in (None, "", "1")
    if busca and primeira_pagina:
        clinic_id = getattr(settings, "DENTAL_CLINIC_ID", None)
        if clinic_id:
            try:
                remotos, total_paginas = procurar_pacientes(
                    q=busca, clinic_id=clinic_id
                )
                dental_ha_mais = total_paginas > 1
                ids_locais = set(
                    Paciente.objects.filter(ativo=True).values_list(
                        "id_dental", flat=True
                    )
                )
                for pac in remotos:
                    if str(pac.id) in ids_locais:
                        continue
                    pacientes_dental.append(
                        {
                            "id_dental": str(pac.id),
                            "nome": pac.nome,
                            "celular": pac.celular,
                        }
                    )
            except DentalAPIError as exc:
                erro_dental = str(exc)
        else:
            erro_dental = "A busca no Dental Office não está configurada."

    return render(
        request,
        "gestao_lab/pacientes.html",
        {
            "pacientes": page_obj,
            "page_obj": page_obj,
            "query_string": query_string,
            "busca": busca,
            "pedido_filtro": pedido_filtro,
            "hoje": date_type.today(),
            "total": total,
            "total_abertos": total_abertos,
            "pacientes_dental": pacientes_dental,
            "erro_dental": erro_dental,
            "dental_ha_mais": dental_ha_mais,
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
        messages.error(
            request,
            "A atualização da lista não está configurada. Avise o suporte técnico.",
        )
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
        messages.error(request, f"Não foi possível atualizar a lista agora: {exc}")

    return destino


@login_required
@require_POST
def sincronizar_alunos_dental(request: HttpRequest) -> HttpResponse:
    """Atualiza somente a lista de alunos com o Dental Office.

    Usada pelos formulários de pedido e moldagem: um botão explícito de
    "Atualizar alunos", em vez dos antigos campos de busca na sidebar. É mais
    leve que ``sincronizar_dental`` (que também varre os pacientes), então serve
    bem ao caso em que o operador só precisa que um aluno recém-cadastrado
    apareça no seletor.
    """

    from django.conf import settings
    from gestao_lab.integrations.dental import DentalAPIError
    from gestao_lab.services.dental_sync import sincronizar_alunos

    user_group = getattr(settings, "DENTAL_USER_GROUP_ALUNO", 8)

    next_url = request.POST.get("next", "")
    destino = (
        HttpResponseRedirect(next_url)
        if next_url.startswith("/")
        else redirect("lab_criar_pedido")
    )

    try:
        resultado = sincronizar_alunos(user_group=user_group)
    except DentalAPIError as exc:
        messages.error(request, f"Não foi possível atualizar os alunos agora: {exc}")
    else:
        messages.success(
            request,
            "Lista de alunos atualizada: "
            f"{resultado['criados']} novo(s), "
            f"{resultado['atualizados']} atualizado(s).",
        )

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
        messages.error(
            request,
            "A atualização da lista não está configurada. Avise o suporte técnico.",
        )
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
        messages.error(request, f"Não foi possível atualizar a lista agora: {exc}")

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
        messages.error(request, f"Não foi possível atualizar a lista agora: {exc}")

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
