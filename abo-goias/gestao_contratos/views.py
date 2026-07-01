"""Views da app de gestão de contratos e termos de consentimento."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from gestao_lab.integrations.dental import (
    DentalAPIError,
    DentalClient,
    normalizar_paciente,
    normalizar_paciente_detalhado,
)
from gestao_lab.models import Paciente

from .models import TIPOS_CONTRATO, ContratoGerado
from .services.checklist import gerar_checklist, pendencias_obrigatorias
from .services.documentos import gerar_contrato
from .services.envio_dental import enviar_contrato_ao_dental

_PACIENTES_POR_PAGINA = 25


@login_required
def contratos(request: HttpRequest) -> HttpResponse:
    """Lista pacientes locais e, quando a busca retorna zero, consulta a API."""

    busca = request.GET.get("q", "").strip()
    pacientes_qs = Paciente.objects.filter(ativo=True).order_by("nome")

    if busca:
        pacientes_qs = pacientes_qs.filter(nome__icontains=busca)

    pacientes_api: list[dict] = []
    erro_api: str = ""

    # Busca na API apenas quando DB retornou zero resultados com um termo ativo.
    if busca and not pacientes_qs.exists():
        clinic_id = getattr(settings, "DENTAL_CLINIC_ID", None)
        if clinic_id:
            try:
                client = DentalClient()
                resposta = client.listar_pacientes(clinic_id=clinic_id, q=busca)
                ids_locais = set(
                    Paciente.objects.filter(ativo=True).values_list(
                        "id_dental", flat=True
                    )
                )
                for item in resposta.get("results") or []:
                    pac = normalizar_paciente(item)
                    if pac:
                        pacientes_api.append(
                            {
                                "id_dental": str(pac.id),
                                "nome": pac.nome,
                                "celular": pac.celular,
                                "ja_existe": str(pac.id) in ids_locais,
                            }
                        )
            except DentalAPIError as exc:
                erro_api = str(exc)
        else:
            erro_api = "DENTAL_CLINIC_ID não configurado no ambiente."

    # Paginação — aplicada depois da verificação de existência para o fallback API.
    total = pacientes_qs.count()
    params = request.GET.copy()
    params.pop("page", None)
    paginator = Paginator(pacientes_qs, _PACIENTES_POR_PAGINA)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "gestao_contratos/contratos.html",
        {
            "pacientes": page_obj,
            "page_obj": page_obj,
            "query_string": params.urlencode(),
            "pacientes_api": pacientes_api,
            "busca": busca,
            "total": total,
            "erro_api": erro_api,
        },
    )


@login_required
def importar_e_gerar(request: HttpRequest, id_dental: str) -> HttpResponse:
    """Importa (ou atualiza) um paciente do Dental Office e abre a tela de contrato.

    Busca dados detalhados via GET /customers/{id}. Se o paciente já existir
    no banco local, atualiza os campos enriquecidos antes de redirecionar.
    Caso contrário, cria o registro completo e redireciona.
    """

    try:
        client = DentalClient()
        dados = client.buscar_detalhes_paciente(id_dental)
    except DentalAPIError as exc:
        messages.error(
            request, f"Não foi possível buscar os dados no Dental Office: {exc}"
        )
        return redirect("contratos")

    nome = (dados.get("name") or "").strip()
    if not nome:
        messages.error(
            request, "O paciente selecionado não possui nome no Dental Office."
        )
        return redirect("contratos")

    celular = ""
    contatos = dados.get("contacts_attributes") or []
    if contatos:
        celular = (
            contatos[0].get("cellphone") or contatos[0].get("phone") or ""
        ).strip()

    campos_detalhados = normalizar_paciente_detalhado(dados)

    paciente, criado = Paciente.objects.get_or_create(
        id_dental=str(id_dental),
        defaults={
            "nome": nome,
            "celular": celular,
            "ativo": bool(dados.get("active", True)),
            "ultima_sincronizacao": timezone.now(),
            **campos_detalhados,
        },
    )

    if not criado:
        # Atualiza nome, celular e campos enriquecidos em um único save.
        paciente.nome = nome
        paciente.celular = celular
        paciente.ativo = bool(dados.get("active", True))
        paciente.ultima_sincronizacao = timezone.now()
        for campo, valor in campos_detalhados.items():
            setattr(paciente, campo, valor)
        paciente.save(
            update_fields=[
                "nome",
                "celular",
                "ativo",
                "ultima_sincronizacao",
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

    acao = "importado" if criado else "atualizado"
    messages.success(request, f"Paciente {nome} {acao} com sucesso.")
    return redirect("contrato_gerar", paciente_pk=paciente.pk)


@login_required
def gerar_contrato_view(request: HttpRequest, paciente_pk: int) -> HttpResponse:
    """Exibe o formulário e processa a geração do contrato DOCX.

    GET: Busca os dados completos do paciente via API Dental Office (se ausentes
    ou se ``?sincronizar=1`` for passado). Gera o checklist de prontidão e
    exibe o formulário. A geração fica bloqueada se houver campos obrigatórios
    não preenchidos.

    POST: Revalida o checklist, gera o DOCX e retorna o arquivo para download.
    Rejeita a solicitação se o paciente ainda tiver pendências obrigatórias.
    """

    paciente = get_object_or_404(Paciente, pk=paciente_pk, ativo=True)

    forcar_sincronizacao = request.GET.get("sincronizar") == "1"

    if forcar_sincronizacao or not paciente.dados_contrato_completos:
        try:
            client = DentalClient()
            dados_api = client.buscar_detalhes_paciente(paciente.id_dental)
            campos = normalizar_paciente_detalhado(dados_api)
            for campo, valor in campos.items():
                setattr(paciente, campo, valor)
            paciente.ultima_sincronizacao = timezone.now()
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
                    "ultima_sincronizacao",
                    "atualizado_em",
                ]
            )
            if forcar_sincronizacao:
                messages.success(
                    request,
                    "Dados atualizados com sucesso a partir do Dental Office.",
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
        local_assinatura=local,
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


@login_required
def enviar_ao_dental_view(request: HttpRequest, contrato_pk: int) -> HttpResponse:
    """Regenera o DOCX e envia para a ficha do paciente no Dental Office.

    Aceita apenas POST para evitar envios acidentais por GET. Regenera o
    documento a partir dos metadados gravados em ContratoGerado e chama
    a API do Dental Office via DentalClient.enviar_documento_paciente().
    """

    if request.method != "POST":
        return redirect("contratos")

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)
    paciente = contrato.paciente

    ok, erro = enviar_contrato_ao_dental(contrato)

    if ok:
        messages.success(
            request,
            f"Contrato '{contrato.get_tipo_display()}' enviado com sucesso "
            f"para a ficha de {paciente.nome} no Dental Office.",
        )
    else:
        messages.error(
            request,
            f"Falha ao enviar o contrato ao Dental Office: {erro}",
        )

    return redirect("contrato_gerar", paciente_pk=paciente.pk)
