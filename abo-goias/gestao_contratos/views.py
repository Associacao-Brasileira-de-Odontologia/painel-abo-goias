"""Views da app de gestão de contratos e termos de consentimento."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
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
from .models import (
    TERMINAL_ATIVO_TTL_HORAS,
    TIPOS_CONTRATO,
    ContratoGerado,
    EventoContrato,
    TerminalAssinatura,
    expirar_terminais_vencidos,
)
from .services.carimbo_tempo import solicitar_carimbo
from .services.checklist import (
    eh_menor_de_idade,
    gerar_checklist,
    pendencias_obrigatorias,
)
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
                                # CPF/nascimento só vêm no endpoint de detalhe;
                                # aproveitamos se a listagem já os trouxer.
                                "cpf": _cpf_do_item_lista(item),
                                "nascimento": _nascimento_do_item_lista(item),
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

    # ── Listagem unificada ────────────────────────────────────────────
    # Uma única lista para a tela, em vez de duas tabelas separadas
    # (local + Dental Office). Cada linha carrega os dados mínimos para
    # localizar o paciente e a ação correta (gerar direto ou importar).
    pacientes_unificados: list[dict] = []
    for pac in page_obj.object_list:
        pacientes_unificados.append(
            {
                "nome": pac.nome,
                "nascimento": pac.data_nascimento,
                "cpf": pac.cpf,
                "celular": pac.celular,
                "no_sistema": True,
                "dados_completos": pac.dados_contrato_completos,
                "acao_url": reverse("contrato_gerar", args=[pac.pk]),
                "acao_label": "Gerar contrato",
            }
        )
    # Só na primeira página anexamos os do Dental Office ainda não importados
    # (os "já no sistema" já aparecem acima como registros locais).
    for pac in pacientes_api:
        if pac["ja_existe"]:
            continue
        pacientes_unificados.append(
            {
                "nome": pac["nome"],
                "nascimento": pac["nascimento"],
                "cpf": pac["cpf"],
                "celular": pac["celular"],
                "id_dental": pac["id_dental"],
                "no_sistema": False,
                "dados_completos": None,
                "acao_url": reverse("contrato_importar", args=[pac["id_dental"]]),
                "acao_label": "Importar e gerar",
            }
        )

    return render(
        request,
        "gestao_contratos/contratos.html",
        {
            "pacientes": page_obj,
            "page_obj": page_obj,
            "query_string": params.urlencode(),
            "pacientes_api": pacientes_api,
            "pacientes_unificados": pacientes_unificados,
            "busca": busca,
            "total": total,
            "erro_api": erro_api,
            "dental_pesquisado": dental_pesquisado,
            "etapa_atual": 0,
        },
    )


def _cpf_do_item_lista(item: dict) -> str:
    """Extrai o CPF de um item da listagem do Dental Office, se presente.

    A listagem costuma ser enxuta (sem documento); retorna string vazia
    quando o campo não vem, sem custo de chamada extra à API.
    """

    doc = item.get("document_attributes") or {}
    return (doc.get("cpf") or "").strip()


def _nascimento_do_item_lista(item: dict) -> str:
    """Extrai a data de nascimento (ISO) de um item da listagem, se presente."""

    return (item.get("birth_date") or "").strip()


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
    return redirect("contrato_gerar", paciente_pk=paciente.pk)


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
    """Alias de compatibilidade — a tela de confirmação foi unificada com a
    de geração do contrato (ver ``gerar_contrato_view``). Mantido para não
    quebrar links/favoritos antigos que ainda apontem para esta URL."""

    return redirect("contrato_gerar", paciente_pk=paciente_pk)


@login_required
def gerar_contrato_view(request: HttpRequest, paciente_pk: int) -> HttpResponse:
    """Tela única de revisão, confirmação e geração do contrato.

    Reúne o que antes eram duas telas e duas navegações (confirmar dados →
    gerar contrato) em uma só: o mesmo POST salva os dados do paciente,
    registra a confirmação e — se não houver pendências obrigatórias no
    checklist — já gera o contrato, sem exigir uma segunda ida à tela
    seguinte quando está tudo certo.

    GET: sincroniza automaticamente com o Dental Office quando os dados
    mínimos estão ausentes ou quando ``?sincronizar=1`` é passado — o que
    invalida uma confirmação anterior (sinalizado ao template via
    ``sincronizacao_invalidou_confirmacao`` para destacar o aviso).
    """

    paciente = get_object_or_404(Paciente, pk=paciente_pk, ativo=True)
    sincronizacao_invalidou_confirmacao = False

    if request.method == "POST":
        form = PacienteConfirmacaoForm(request.POST, instance=paciente)
        if form.is_valid():
            paciente = form.save(commit=False)
            paciente.dados_confirmados_em = timezone.now()
            paciente.dados_confirmados_por = request.user
            paciente.save()

            if not pendencias_obrigatorias(paciente):
                return _processar_geracao(request, paciente)

            messages.error(
                request,
                "Dados salvos, mas ainda há campos obrigatórios pendentes — "
                "veja o checklist abaixo antes de gerar o contrato.",
            )
    else:
        forcar_sincronizacao = request.GET.get("sincronizar") == "1"
        if forcar_sincronizacao or not paciente.dados_contrato_completos:
            estava_confirmado = paciente.dados_confirmados
            try:
                _sincronizar_do_dental(paciente)
                sincronizacao_invalidou_confirmacao = estava_confirmado
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
            "form": form,
            "tipos_contrato": TIPOS_CONTRATO,
            "historico": historico,
            "checklist": checklist,
            "pendencias": pendencias,
            "gerado_bloqueado": bool(pendencias),
            "menor_de_idade": bool(eh_menor_de_idade(paciente.data_nascimento)),
            "sincronizacao_invalidou_confirmacao": sincronizacao_invalidou_confirmacao,
            "etapa_atual": 1,
            "breadcrumbs": [
                {"label": "Contratos", "url": reverse("contratos")},
                {"label": paciente.nome, "url": None},
                {"label": "Confirmar e gerar contrato", "url": None},
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
        # Etapa 2 ("Assinar") enquanto o documento aguarda assinatura;
        # etapa 3 ("Enviar") depois que o paciente já assinou — esta
        # mesma tela cobre as duas fases do stepper.
        "etapa_atual": 3 if contrato.status == "assinado" else 2,
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

    next_url = request.POST.get("next", "")
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)


def _contratos_envio_dental_pendentes() -> "list[ContratoGerado]":
    """Contratos assinados cujo envio ao Dental Office falhou ou está pendente.

    Cobre dois riscos de "documento assinado perdido por falha de integração":
      * ``erro``      — o envio (manual ou automático via Celery) falhou;
      * ``nao_enviado`` de um contrato já ``assinado`` — nunca chegou ao Dental.

    Cada item recebe ``ultimo_erro`` com a mensagem do evento de falha mais
    recente, para exibição direta no painel sem consulta extra por linha.
    """

    contratos = list(
        ContratoGerado.objects.filter(status="assinado")
        .filter(Q(status_envio_dental="erro") | Q(status_envio_dental="nao_enviado"))
        .select_related("paciente")
        .order_by("-atualizado_em")
    )

    ids = [c.pk for c in contratos]
    ultimo_erro: dict[int, str] = {}
    if ids:
        # Última mensagem de erro por contrato, em uma única consulta.
        eventos = EventoContrato.objects.filter(
            contrato_id__in=ids, tipo="envio_dental_erro"
        ).order_by("contrato_id", "-criado_em", "-pk")
        for evento in eventos:
            ultimo_erro.setdefault(evento.contrato_id, evento.payload.get("erro", ""))

    for contrato in contratos:
        contrato.ultimo_erro = ultimo_erro.get(contrato.pk, "")

    return contratos


@login_required
def envios_dental_pendentes_view(request: HttpRequest) -> HttpResponse:
    """Painel de envios ao Dental Office com falha ou pendentes.

    Torna visíveis os documentos assinados que não chegaram ao Dental Office,
    para que nenhum se perca silenciosamente por falha de integração. Permite
    reenviar cada um (mesma ação da tela de pós-geração).
    """

    contratos = _contratos_envio_dental_pendentes()

    return render(
        request,
        "gestao_contratos/envios_dental.html",
        {
            "contratos": contratos,
            "total": len(contratos),
            "breadcrumbs": [
                {"label": "Contratos", "url": reverse("contratos")},
                {"label": "Envios ao Dental Office", "url": None},
            ],
        },
    )


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


# ── Terminais de assinatura dedicados (ex.: tablet da recepção) ─────────────
#
# Gerenciados aqui (staff logado) em vez de restritos ao Django Admin: quem
# cuida da recepção no dia a dia precisa poder cadastrar um terminal novo,
# gerar um novo link (ex.: link antigo compartilhado por engano, tablet
# trocado) ou trocar qual terminal está recebendo sessões, sem depender de
# alguém com acesso de administrador.
#
# Regra: só um terminal pode ficar ativo por vez (ver
# TerminalAssinatura.clean/outro_terminal_ativo) — evita que a recepção
# envie uma sessão sem saber qual dos tablets vai de fato recebê-la.


@login_required
def terminais_view(request: HttpRequest) -> HttpResponse:
    """Lista os terminais de assinatura cadastrados e permite criar novos."""

    if request.method == "POST":
        nome = request.POST.get("nome", "").strip()
        if nome:
            # Novo terminal sempre começa inativo — ativar é uma ação
            # explícita (ver terminal_alternar_ativo_view), nunca implícita
            # na criação, para não competir com o terminal já ativo.
            TerminalAssinatura.objects.create(nome=nome, ativo=False)
            messages.success(
                request,
                f'Terminal "{nome}" criado. Ative-o na lista abaixo quando '
                "estiver pronto para receber sessões.",
            )
        else:
            messages.error(request, "Informe um nome para o terminal.")
        return redirect("contrato_terminais")

    expirar_terminais_vencidos()

    terminais = TerminalAssinatura.objects.all()
    ja_existe_ativo = terminais.filter(ativo=True).exists()
    return render(
        request,
        "gestao_contratos/terminais.html",
        {
            "terminais": [
                {
                    "obj": terminal,
                    "link": request.build_absolute_uri(
                        reverse("terminal_assinatura", args=[terminal.token])
                    ),
                    "pode_ativar": terminal.ativo or not ja_existe_ativo,
                    "expira_em": (
                        terminal.ativado_em + timedelta(hours=TERMINAL_ATIVO_TTL_HORAS)
                        if terminal.ativado_em
                        else None
                    ),
                }
                for terminal in terminais
            ],
            "breadcrumbs": [
                {"label": "Contratos", "url": reverse("contratos")},
                {"label": "Terminais de assinatura", "url": None},
            ],
        },
    )


@login_required
def terminal_regenerar_token_view(
    request: HttpRequest, terminal_pk: int
) -> HttpResponse:
    """Gera um novo link para o terminal, invalidando o anterior na hora.

    Uso típico: o link atual vazou ou foi compartilhado por engano, ou o
    tablet foi trocado/perdido. Depois de gerar, é preciso abrir o novo link
    no navegador do tablet — o link antigo passa a responder 404.
    """

    if request.method != "POST":
        return redirect("contrato_terminais")

    terminal = get_object_or_404(TerminalAssinatura, pk=terminal_pk)
    terminal.regenerar_token()
    messages.success(
        request,
        f'Novo link gerado para "{terminal.nome}". '
        "Abra o novo link no navegador do tablet — o link antigo não funciona mais.",
    )
    return redirect("contrato_terminais")


@login_required
def terminal_alternar_ativo_view(
    request: HttpRequest, terminal_pk: int
) -> HttpResponse:
    """Ativa ou desativa um terminal sem excluí-lo.

    Só permite ativar se nenhum outro terminal estiver ativo — o sistema
    aceita apenas um terminal ativo por vez, para que a recepção sempre
    saiba, sem ambiguidade, qual tablet está de fato recebendo sessões.
    Desativar nunca é bloqueado.
    """

    if request.method != "POST":
        return redirect("contrato_terminais")

    terminal = get_object_or_404(TerminalAssinatura, pk=terminal_pk)

    if not terminal.ativo:
        ativo_atual = terminal.outro_terminal_ativo()
        if ativo_atual is not None:
            messages.error(
                request,
                f"Só é possível ter um terminal ativo por vez. Desative "
                f'"{ativo_atual.nome}" antes de ativar "{terminal.nome}".',
            )
            return redirect("contrato_terminais")

    terminal.ativo = not terminal.ativo
    terminal.save(update_fields=["ativo", "atualizado_em"])
    estado = "ativado" if terminal.ativo else "desativado"
    messages.success(request, f'Terminal "{terminal.nome}" {estado}.')
    return redirect("contrato_terminais")


@login_required
def terminal_excluir_view(request: HttpRequest, terminal_pk: int) -> HttpResponse:
    """Exclui definitivamente um terminal.

    Sessões de assinatura que já apontavam para este terminal não são
    afetadas — ``SessaoAssinatura.terminal`` usa ``on_delete=SET_NULL``,
    então o histórico/auditoria permanece intacto, só perde a referência
    a qual terminal físico foi usado.
    """

    if request.method != "POST":
        return redirect("contrato_terminais")

    terminal = get_object_or_404(TerminalAssinatura, pk=terminal_pk)
    nome = terminal.nome
    terminal.delete()
    messages.success(request, f'Terminal "{nome}" excluído.')
    return redirect("contrato_terminais")
