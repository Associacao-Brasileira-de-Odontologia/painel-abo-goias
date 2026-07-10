"""Views da app de gestão de contratos e termos de consentimento."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from gestao_lab.integrations.dental import (
    DentalAPIError,
    DentalClient,
    normalizar_paciente,
    normalizar_paciente_detalhado,
)
from gestao_lab.models import Paciente
from gestao_lab.services.dental_sync import listar_todas_paginas

from .forms import PacienteConfirmacaoForm
from .models import TIPOS_CONTRATO, ContratoGerado
from .services.carimbo_tempo import solicitar_carimbo
from .services.checklist import gerar_checklist, pendencias_obrigatorias
from .services.documentos import gerar_e_salvar_contrato
from .services.envio import (
    calcular_link_whatsapp,
    enviar_contrato_email,
    gerar_link_whatsapp,
)
from .services.envio_dental import enviar_contrato_ao_dental

_PACIENTES_POR_PAGINA = 25


@login_required
def contratos(request: HttpRequest) -> HttpResponse:
    """Lista pacientes locais e, havendo busca, consulta também a API."""

    busca = request.GET.get("q", "").strip()
    pacientes_qs = Paciente.objects.filter(ativo=True).order_by("nome")

    if busca:
        pacientes_qs = pacientes_qs.filter(nome__icontains=busca)

    pacientes_api: list[dict] = []
    erro_api: str = ""
    dental_pesquisado: bool = False
    primeira_pagina = request.GET.get("page") in (None, "", "1")

    # Toda busca consulta também o Dental Office, mas só na primeira
    # página — paginar os resultados locais não deve repetir a chamada.
    if busca and primeira_pagina:
        clinic_id = getattr(settings, "DENTAL_CLINIC_ID", None)
        if clinic_id:
            try:
                client = DentalClient()
                itens = listar_todas_paginas(
                    lambda page: client.listar_pacientes(
                        clinic_id=clinic_id, page=page, q=busca
                    ),
                    contexto="pacientes:busca_contratos",
                )
                dental_pesquisado = True
                ids_locais = set(
                    Paciente.objects.filter(ativo=True).values_list(
                        "id_dental", flat=True
                    )
                )
                for item in itens:
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
            "dental_pesquisado": dental_pesquisado,
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
                "email",
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
    messages.success(
        request,
        f"Paciente {nome} {acao} com sucesso. Revise e confirme os dados "
        "antes de gerar o contrato.",
    )
    return redirect("contrato_confirmar_dados", paciente_pk=paciente.pk)


def _sincronizar_do_dental(paciente: Paciente) -> None:
    """Atualiza os campos enriquecidos do paciente a partir do Dental Office.

    A sincronização invalida a confirmação anterior — os dados mudaram e
    precisam ser revisados novamente. O campo convenio não é tocado (é
    exclusivamente local; o Dental Office não fornece essa informação).

    Raises DentalAPIError em falha de comunicação.
    """

    client = DentalClient()
    dados_api = client.buscar_detalhes_paciente(paciente.id_dental)
    campos = normalizar_paciente_detalhado(dados_api)
    for campo, valor in campos.items():
        setattr(paciente, campo, valor)
    paciente.ultima_sincronizacao = timezone.now()
    paciente.dados_confirmados_em = None
    paciente.dados_confirmados_por = None
    paciente.save(
        update_fields=[
            "email",
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
            "dados_confirmados_em",
            "dados_confirmados_por",
            "atualizado_em",
        ]
    )


@login_required
def confirmar_dados_view(request: HttpRequest, paciente_pk: int) -> HttpResponse:
    """Tela de revisão, edição e confirmação dos dados do paciente.

    GET: Sincroniza automaticamente com o Dental Office quando os dados
    mínimos estão ausentes ou quando ``?sincronizar=1`` é passado, e exibe
    o formulário de edição. A sincronização invalida confirmações anteriores.

    POST: Salva as edições, registra quem confirmou e quando, e redireciona
    para a tela de geração do contrato.
    """

    paciente = get_object_or_404(Paciente, pk=paciente_pk, ativo=True)

    if request.method == "POST":
        form = PacienteConfirmacaoForm(request.POST, instance=paciente)
        if form.is_valid():
            paciente = form.save(commit=False)
            paciente.dados_confirmados_em = timezone.now()
            paciente.dados_confirmados_por = request.user
            paciente.save()
            messages.success(
                request, f"Dados de {paciente.nome} confirmados com sucesso."
            )
            return redirect("contrato_gerar", paciente_pk=paciente.pk)
    else:
        forcar_sincronizacao = request.GET.get("sincronizar") == "1"
        if forcar_sincronizacao or not paciente.dados_contrato_completos:
            try:
                _sincronizar_do_dental(paciente)
                if forcar_sincronizacao:
                    messages.success(
                        request,
                        "Dados atualizados a partir do Dental Office. "
                        "Revise e confirme antes de gerar o contrato.",
                    )
            except DentalAPIError as exc:
                messages.warning(
                    request,
                    f"Não foi possível buscar dados no Dental Office: {exc}. "
                    "Preencha manualmente os campos faltantes.",
                )
        form = PacienteConfirmacaoForm(instance=paciente)

    return render(
        request,
        "gestao_contratos/confirmar_dados.html",
        {
            "paciente": paciente,
            "form": form,
            "breadcrumbs": [
                {"label": "Contratos", "url": reverse("contratos")},
                {"label": paciente.nome, "url": None},
                {"label": "Confirmar dados", "url": None},
            ],
        },
    )


@login_required
def gerar_contrato_view(request: HttpRequest, paciente_pk: int) -> HttpResponse:
    """Exibe o formulário e processa a geração do contrato.

    Exige que os dados do paciente tenham sido confirmados previamente na
    tela de confirmação — caso contrário, redireciona para lá. A geração
    também fica bloqueada enquanto houver campos obrigatórios pendentes
    (checklist).
    """

    paciente = get_object_or_404(Paciente, pk=paciente_pk, ativo=True)

    if not paciente.dados_confirmados:
        messages.info(
            request,
            "Revise e confirme os dados do paciente antes de gerar o contrato.",
        )
        return redirect("contrato_confirmar_dados", paciente_pk=paciente.pk)

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
            "breadcrumbs": [
                {"label": "Contratos", "url": reverse("contratos")},
                {
                    "label": paciente.nome,
                    "url": reverse("contrato_confirmar_dados", args=[paciente.pk]),
                },
                {"label": "Gerar contrato", "url": None},
            ],
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
    email_form = request.POST.get("email_paciente", "").strip()
    whatsapp_form = request.POST.get("whatsapp_paciente", "").strip()

    # Salva e-mail e WhatsApp preenchidos no formulário de volta ao paciente.
    # O WhatsApp alimenta paciente.celular, que é o número usado pelo link
    # de envio na tela de pós-geração.
    campos_alterados = []
    if email_form and email_form != paciente.email:
        paciente.email = email_form
        campos_alterados.append("email")
    if whatsapp_form and whatsapp_form != paciente.celular:
        paciente.celular = whatsapp_form
        campos_alterados.append("celular")
    if campos_alterados:
        paciente.save(update_fields=[*campos_alterados, "atualizado_em"])

    tipos_validos = {t[0] for t in TIPOS_CONTRATO}
    if tipo not in tipos_validos:
        messages.error(request, "Selecione um tipo de contrato válido.")
        return redirect("contrato_gerar", paciente_pk=paciente.pk)

    try:
        contrato = gerar_e_salvar_contrato(
            paciente=paciente,
            tipo=tipo,
            observacoes_clinicas=observacoes,
            profissional_nome=prof_nome,
            profissional_cro=prof_cro,
            local_assinatura=local,
            gerado_por=request.user,
        )
    except FileNotFoundError as exc:
        messages.error(request, str(exc))
        return redirect("contrato_gerar", paciente_pk=paciente.pk)

    return redirect("contrato_pos_geracao", contrato_pk=contrato.pk)


@login_required
def pos_geracao_view(request: HttpRequest, contrato_pk: int) -> HttpResponse:
    """Exibe opções pós-geração: assinatura, baixar, e-mail, WhatsApp, Dental."""

    from .views_assinatura import contexto_status_assinatura

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)
    paciente = contrato.paciente

    link_whatsapp = calcular_link_whatsapp(
        paciente.celular or "", contrato.get_tipo_display()
    )

    contexto = {
        "paciente": paciente,
        "link_whatsapp": link_whatsapp,
        "whatsapp_automatico_configurado": settings.ZAPI_CONFIGURADO,
        "breadcrumbs": [
            {"label": "Contratos", "url": reverse("contratos")},
            {
                "label": paciente.nome,
                "url": reverse("contrato_gerar", args=[paciente.pk]),
            },
            {"label": "Enviar contrato", "url": None},
        ],
    }
    contexto.update(contexto_status_assinatura(request, contrato))

    return render(request, "gestao_contratos/pos_geracao.html", contexto)


@login_required
def baixar_contrato_view(request: HttpRequest, contrato_pk: int) -> HttpResponse:
    """Retorna o DOCX do contrato como download."""

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)
    paciente = contrato.paciente

    if not contrato.arquivo:
        messages.error(request, "Arquivo do contrato não encontrado.")
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    contrato.arquivo.open("rb")
    conteudo = contrato.arquivo.read()
    contrato.arquivo.close()

    nome_arquivo = (
        f"termo_{contrato.tipo}_{paciente.nome.split()[0].lower()}"
        f"_{paciente.id_dental}.docx"
    )
    response = HttpResponse(
        conteudo,
        content_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )
    response["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    return response


@login_required
def baixar_contrato_pdf_view(request: HttpRequest, contrato_pk: int) -> HttpResponse:
    """Retorna o PDF do contrato como download."""

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)
    paciente = contrato.paciente

    if not contrato.arquivo_pdf:
        messages.error(request, "PDF do contrato não disponível. Baixe a versão DOCX.")
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    contrato.arquivo_pdf.open("rb")
    conteudo = contrato.arquivo_pdf.read()
    contrato.arquivo_pdf.close()

    nome_arquivo = (
        f"termo_{contrato.tipo}_{paciente.nome.split()[0].lower()}"
        f"_{paciente.id_dental}.pdf"
    )
    response = HttpResponse(conteudo, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    return response


@login_required
def enviar_email_view(request: HttpRequest, contrato_pk: int) -> HttpResponse:
    """Envia o contrato por e-mail ao destinatário informado no formulário."""

    if request.method != "POST":
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)
    paciente = contrato.paciente
    destinatario = request.POST.get("email_destinatario", "").strip()

    if not destinatario:
        messages.error(request, "Informe um e-mail válido para o envio.")
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    # Atualiza email no paciente se diferente
    if destinatario != paciente.email:
        paciente.email = destinatario
        paciente.save(update_fields=["email", "atualizado_em"])

    ok = enviar_contrato_email(contrato, destinatario)

    if ok:
        messages.success(
            request,
            f"Contrato enviado com sucesso para {destinatario}.",
        )
    else:
        messages.error(
            request,
            "Não foi possível enviar o e-mail. Verifique as configurações de SMTP "
            "e tente novamente.",
        )

    return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)


@login_required
def whatsapp_status_view(request: HttpRequest, contrato_pk: int) -> HttpResponse:
    """Atualiza status de envio para WhatsApp e redireciona para pós-geração."""

    if request.method != "POST":
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)
    paciente = contrato.paciente
    celular = request.POST.get("celular", "").strip() or paciente.celular or ""

    link = gerar_link_whatsapp(celular, contrato)

    if link:
        messages.success(
            request,
            f"WhatsApp marcado como enviado para {celular}.",
        )
    else:
        messages.warning(request, "Número de telefone inválido.")

    return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)


@login_required
def enviar_ao_dental_view(request: HttpRequest, contrato_pk: int) -> HttpResponse:
    """Envia o contrato para a ficha do paciente no Dental Office.

    Usa o arquivo já salvo em ContratoGerado.arquivo (ou regenera caso ausente).
    Redireciona para pos_geracao_view com mensagem de sucesso ou erro.
    """

    if request.method != "POST":
        return redirect("contratos")

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)

    # Só o documento assinado pelo paciente vai para a ficha no Dental
    # Office — sem assinatura, o serviço cairia no PDF sem assinatura
    # (fallback de obter_melhor_pdf_bytes), arquivando um documento
    # sem valor. A UI desabilita o botão; esta guarda cobre POST direto.
    if contrato.status != "assinado":
        messages.error(
            request,
            "O contrato ainda não foi assinado pelo paciente — só o "
            "documento assinado pode ser enviado ao Dental Office.",
        )
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    ok, erro = enviar_contrato_ao_dental(contrato)

    if ok:
        messages.success(
            request,
            f"Contrato '{contrato.get_tipo_display()}' enviado com sucesso "
            f"para a ficha de {contrato.paciente.nome} no Dental Office.",
        )
    else:
        messages.error(
            request,
            f"Falha ao enviar o contrato ao Dental Office: {erro}",
        )

    return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)


@login_required
def solicitar_carimbo_tempo_view(
    request: HttpRequest, contrato_pk: int
) -> HttpResponse:
    """Solicita (ou tenta novamente) o carimbo de tempo do contrato assinado.

    Chamada de forma síncrona — ao contrário do disparo automático pós-
    assinatura (assíncrono via Celery), aqui é a própria recepção que
    aciona e espera o resultado, então uma chamada direta é aceitável.
    """

    if request.method != "POST":
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)

    ok, erro = solicitar_carimbo(contrato)

    if ok:
        messages.success(request, "Carimbo de tempo obtido com sucesso.")
    else:
        messages.error(request, f"Falha ao obter o carimbo de tempo: {erro}")

    return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)


@login_required
def baixar_carimbo_tempo_view(request: HttpRequest, contrato_pk: int) -> HttpResponse:
    """Retorna o token de carimbo de tempo (.tsr) do contrato como download."""

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)

    if not contrato.carimbo_tempo:
        messages.error(request, "Este contrato ainda não possui carimbo de tempo.")
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    contrato.carimbo_tempo.open("rb")
    conteudo = contrato.carimbo_tempo.read()
    contrato.carimbo_tempo.close()

    nome_arquivo = f"carimbo_tempo_contrato_{contrato.pk}.tsr"
    response = HttpResponse(conteudo, content_type="application/timestamp-reply")
    response["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    return response
