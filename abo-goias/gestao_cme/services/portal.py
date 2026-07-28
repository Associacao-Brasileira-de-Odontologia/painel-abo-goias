"""O que a Gestão de CME entrega ao Portal (ver `comum.portal`)."""

from __future__ import annotations

from comum.portal import Evento, FontePortal, Tarefa

from ..models import Material, Movimentacao, OrigemDados, Turma

# Quantos eventos esta app põe no feed antes do corte final. As apps contribuem
# com quantidades diferentes de propósito: a CME é a mais movimentada.
LIMITE_EVENTOS = 6


def _movimentacoes():
    return Movimentacao.objects.exclude(origem=OrigemDados.EXEMPLO)


def resumo() -> dict[str, int]:
    return {
        "pacotes_pendentes": _movimentacoes()
        .filter(tipo=Movimentacao.Tipo.ENTRADA, retirado=False)
        .count(),
        "materiais": Material.objects.exclude(origem=OrigemDados.EXEMPLO).count(),
        "turmas": Turma.objects.exclude(origem=OrigemDados.EXEMPLO).count(),
    }


def tarefas(resumo: dict[str, int]) -> list[Tarefa]:
    pendentes = resumo.get("pacotes_pendentes", 0)
    if not pendentes:
        return []
    return [
        Tarefa(
            texto=f"{pendentes} pacote(s) aguardando retirada",
            url_name="registrar_saida",
        )
    ]


def eventos() -> list[Evento]:
    lista: list[Evento] = []
    for mov in (
        _movimentacoes().select_related("material").order_by("-data_hora", "-id")
    )[:LIMITE_EVENTOS]:
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
        lista.append(
            Evento(
                categoria=categoria,
                titulo=titulo,
                descricao=descricao,
                data=mov.data_hora,
            )
        )
    return lista


FONTE = FontePortal(
    nome="cme", ordem=10, resumo=resumo, tarefas=tarefas, eventos=eventos
)
