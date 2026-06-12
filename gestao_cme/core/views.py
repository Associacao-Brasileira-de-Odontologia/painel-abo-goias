from django.db.models import Count, Q
from django.shortcuts import render

from .models import Emprestimo


def home(request):
    busca = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    emprestimos = (
        Emprestimo.objects.select_related("aluno", "aluno__turma", "kit")
        .prefetch_related("itens__material", "itens__armario")
        .all()
    )

    if status in Emprestimo.Status.values:
        emprestimos = emprestimos.filter(status=status)

    if busca:
        emprestimos = emprestimos.filter(
            Q(aluno__nome__icontains=busca)
            | Q(aluno__matricula__icontains=busca)
            | Q(aluno__turma__nome__icontains=busca)
            | Q(kit__nome__icontains=busca)
            | Q(kit__codigo__icontains=busca)
            | Q(coordenador__icontains=busca)
            | Q(itens__material__nome__icontains=busca)
            | Q(itens__material__codigo__icontains=busca)
        ).distinct()

    emprestimos = list(emprestimos[:15])
    status_label = dict(Emprestimo.Status.choices).get(status, "Todos")

    for emprestimo in emprestimos:
        itens = list(emprestimo.itens.all())
        emprestimo.total_itens = sum(item.quantidade for item in itens)
        emprestimo.materiais_resumo = ", ".join(
            f"{item.quantidade}x {item.material.nome}" for item in itens[:3]
        )
        if len(itens) > 3:
            emprestimo.materiais_resumo += f" +{len(itens) - 3}"
        emprestimo.status_classe = emprestimo.status.lower()

    metricas = Emprestimo.objects.aggregate(
        total=Count("id"),
        emprestados=Count("id", filter=Q(status=Emprestimo.Status.EMPRESTADO)),
        atrasados=Count("id", filter=Q(status=Emprestimo.Status.ATRASADO)),
        devolvidos=Count("id", filter=Q(status=Emprestimo.Status.DEVOLVIDO)),
    )

    return render(
        request,
        "core/home.html",
        {
            "busca": busca,
            "status_atual": status,
            "status_label": status_label,
            "status_opcoes": Emprestimo.Status.choices,
            "emprestimos": emprestimos,
            "metricas": metricas,
        },
    )
