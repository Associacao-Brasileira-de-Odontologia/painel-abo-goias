"""Views da app de gestão de contratos e termos de consentimento."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from gestao_lab.integrations.dental import (
    DentalAPIError,
    DentalClient,
    normalizar_paciente_detalhado,
)
from gestao_lab.models import Paciente

from .models import TIPOS_CONTRATO, ContratoGerado
from .services.checklist import gerar_checklist, pendencias_obrigatorias
from .services.documentos import gerar_contrato


@login_required
def contratos(request: HttpRequest) -> HttpResponse:
    """Lista pacientes disponíveis para geração de contratos."""

    busca = request.GET.get("q", "").strip()
    pacientes_qs = Paciente.objects.filter(ativo=True).order_by("nome")

    if busca:
        pacientes_qs = pacientes_qs.filter(nome__icontains=busca)

    return render(
        request,
        "gestao_contratos/contratos.html",
        {
            "pacientes": pacientes_qs,
            "busca": busca,
            "total": pacientes_qs.count(),
        },
    )


@login_required
def gerar_contrato_view(request: HttpRequest, paciente_pk: int) -> HttpResponse:
    """Exibe o formulário e processa a geração do contrato DOCX.

    GET: Busca os dados completos do paciente via API Dental Office (se ausentes),
    gera o checklist de prontidão e exibe o formulário. A geração fica bloqueada
    se houver campos obrigatórios não preenchidos.

    POST: Revalida o checklist, gera o DOCX e retorna o arquivo para download.
    Rejeita a solicitação se o paciente ainda tiver pendências obrigatórias.
    """

    paciente = get_object_or_404(Paciente, pk=paciente_pk, ativo=True)

    # Tenta enriquecer dados via Dental Office se campos de contrato estiverem vazios.
    if not paciente.dados_contrato_completos:
        try:
            client = DentalClient()
            dados_api = client.buscar_detalhes_paciente(paciente.id_dental)
            campos = normalizar_paciente_detalhado(dados_api)
            for campo, valor in campos.items():
                setattr(paciente, campo, valor)
            paciente.save(
                update_fields=[
                    "cpf",
                    "rg",
                    "data_nascimento",
                    "endereco_logradouro",
                    "endereco_numero",
                    "endereco_complemento",
                    "endereco_bairro",
                    "endereco_cidade",
                    "endereco_estado",
                    "endereco_cep",
                    "nome_responsavel",
                    "cpf_responsavel",
                    "atualizado_em",
                ]
            )
        except DentalAPIError as exc:
            messages.warning(
                request,
                f"Não foi possível buscar dados no Dental Office: {exc}. "
                "O checklist abaixo indica quais campos estão faltando.",
            )

    if request.method == "POST":
        return _processar_geracao(request, paciente)

    checklist = gerar_checklist(paciente)
    pendencias = pendencias_obrigatorias(paciente)
    historico = ContratoGerado.objects.filter(paciente=paciente).order_by("-criado_em")[
        :5
    ]

    return render(
        request,
        "gestao_contratos/gerar_contrato.html",
        {
            "paciente": paciente,
            "tipos_contrato": TIPOS_CONTRATO,
            "historico": historico,
            "checklist": checklist,
            "pendencias": pendencias,
            "gerado_bloqueado": bool(pendencias),
        },
    )


def _processar_geracao(request: HttpRequest, paciente: Paciente) -> HttpResponse:
    """Gera o DOCX e retorna como download, registrando o contrato.

    Rejeita a geração se o paciente ainda tiver pendências obrigatórias,
    garantindo que o bloqueio do checklist seja respeitado mesmo em POST direto.
    """

    # Revalida no servidor — não confia apenas no estado do formulário HTML.
    pendencias = pendencias_obrigatorias(paciente)
    if pendencias:
        nomes = ", ".join(item.rotulo for item in pendencias)
        messages.error(
            request,
            f"Não é possível gerar o contrato: dados obrigatórios ausentes — {nomes}. "
            "Complete as informações no Dental Office e tente novamente.",
        )
        return redirect("contrato_gerar", paciente_pk=paciente.pk)

    tipo = request.POST.get("tipo", "").strip()
    observacoes = request.POST.get("observacoes_clinicas", "").strip()
    prof_nome = request.POST.get("profissional_nome", "").strip()
    prof_cro = request.POST.get("profissional_cro", "").strip()
    local = request.POST.get("local_assinatura", "Goiânia - GO").strip()

    tipos_validos = {t[0] for t in TIPOS_CONTRATO}
    if tipo not in tipos_validos:
        messages.error(request, "Selecione um tipo de contrato válido.")
        return redirect("contrato_gerar", paciente_pk=paciente.pk)

    try:
        conteudo = gerar_contrato(
            paciente=paciente,
            tipo=tipo,
            observacoes_clinicas=observacoes,
            profissional_nome=prof_nome,
            profissional_cro=prof_cro,
            local_assinatura=local,
        )
    except FileNotFoundError as exc:
        messages.error(request, str(exc))
        return redirect("contrato_gerar", paciente_pk=paciente.pk)

    ContratoGerado.objects.create(
        paciente=paciente,
        tipo=tipo,
        observacoes_clinicas=observacoes,
        profissional_nome=prof_nome,
        profissional_cro=prof_cro,
        gerado_por=request.user,
    )

    nome_arquivo = (
        f"termo_{tipo}_{paciente.nome.split()[0].lower()}" f"_{paciente.id_dental}.docx"
    )
    response = HttpResponse(
        conteudo,
        content_type=(
            "application/vnd.openxmlformats-officedocument" ".wordprocessingml.document"
        ),
    )
    response["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    return response
