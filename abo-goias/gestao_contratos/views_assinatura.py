"""Views do fluxo de assinatura remota.

Views públicas (sem login — o paciente acessa pelo QR Code no próprio
dispositivo) são protegidas por token assinado criptograficamente e
rate-limit por IP. Views de staff gerenciam sessões e exibem o QR Code.
"""

from __future__ import annotations

import io

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from comum.http import destino_seguro

from .models import ContratoGerado, TerminalAssinatura, expirar_terminais_vencidos
from .services.assinatura import (
    LIMITE_TENTATIVAS_IDENTIDADE,
    AssinaturaInvalida,
    SessaoInvalida,
    cancelar_sessoes_ativas,
    confirmar_identidade,
    criar_sessao,
    eventos_recentes,
    gerar_token,
    processar_assinatura,
    registrar_abertura,
    resolver_token,
    sessao_ativa,
)
from .services.checklist import eh_menor_de_idade

_RATE_LIMIT_REQUISICOES = 30
_RATE_LIMIT_JANELA_SEGUNDOS = 60


def _ip_do_request(request: HttpRequest) -> str | None:
    """Extrai o IP de origem considerando os proxies confiáveis à frente da app.

    O ``X-Forwarded-For`` cresce da esquerda para a direita: cada proxy
    *acrescenta* o endereço de quem falou com ele. Logo, a entrada mais à
    esquerda é a que o próprio cliente mandou — e um cliente pode mandar o
    que quiser. Ler o primeiro valor, como era feito antes, deixava qualquer
    um escolher o IP que ficaria gravado no rodapé do PDF assinado e na
    trilha de auditoria (achado A-02), além de permitir furar o rate-limit
    abaixo trocando o valor a cada requisição.

    O valor confiável é o que o *último proxy confiável* acrescentou: com um
    proxy na frente (o caso do Railway), é a entrada mais à direita. Por isso
    a contagem vem de ``PROXIES_CONFIAVEIS`` — em outra topologia, com dois
    proxies, o endereço do cliente passa a ser o penúltimo, e assim por
    diante.

    Sem cabeçalho, ou com menos entradas do que proxies declarados (sinal de
    que a requisição não veio pelo caminho esperado), cai no ``REMOTE_ADDR``,
    que é a conexão real e não pode ser forjada.
    """

    proxies = getattr(settings, "PROXIES_CONFIAVEIS", 1)
    encadeado = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if proxies > 0 and encadeado:
        enderecos = [parte.strip() for parte in encadeado.split(",") if parte.strip()]
        if len(enderecos) >= proxies:
            return enderecos[-proxies]
    return request.META.get("REMOTE_ADDR")


def _excedeu_rate_limit(request: HttpRequest, escopo: str) -> bool:
    """Rate-limit simples por IP usando o cache do Django."""

    ip = _ip_do_request(request) or "desconhecido"
    chave = f"assinatura_rl_{escopo}_{ip}"
    atual = cache.get_or_set(chave, 0, _RATE_LIMIT_JANELA_SEGUNDOS)
    if atual >= _RATE_LIMIT_REQUISICOES:
        return True
    try:
        cache.incr(chave)
    except ValueError:
        cache.set(chave, 1, _RATE_LIMIT_JANELA_SEGUNDOS)
    return False


# ── Views públicas (paciente) ─────────────────────────────────────────────────


def assinar_view(request: HttpRequest, token: str) -> HttpResponse:
    """Página pública de assinatura acessada via QR Code.

    Antes de liberar o canvas, exige a confirmação da data de nascimento
    cadastrada (ver ``_tela_verificar_identidade``) — sem isso, nenhum POST
    chega a ``processar_assinatura``, mesmo que enviado diretamente sem
    passar pela tela.

    GET: exibe a verificação de identidade ou, já confirmada, o contrato e
    a área de assinatura (canvas).
    POST: enquanto a identidade não for confirmada, trata o POST como uma
    tentativa de verificação; depois de confirmada, recebe o PNG do canvas
    e conclui a assinatura.
    """

    if _excedeu_rate_limit(request, "assinar"):
        return HttpResponse("Muitas requisições. Aguarde um instante.", status=429)

    try:
        sessao = resolver_token(token)
    except SessaoInvalida as exc:
        return render(
            request,
            "gestao_contratos/assinatura_invalida.html",
            {"motivo": exc.motivo},
            status=410,
        )

    contrato = sessao.contrato
    paciente = contrato.paciente

    registrar_abertura(sessao)

    if not sessao.identidade_confirmada_em:
        return _tela_verificar_identidade(request, sessao, contrato, paciente, token)

    if request.method == "POST":
        try:
            processar_assinatura(
                sessao,
                request.POST.get("assinatura", ""),
                ip=_ip_do_request(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                validacao_url=request.build_absolute_uri(reverse("validar_documento")),
            )
        except AssinaturaInvalida as exc:
            return render(
                request,
                "gestao_contratos/assinar.html",
                {
                    "sessao": sessao,
                    "contrato": contrato,
                    "paciente": paciente,
                    "token": token,
                    "erro": str(exc),
                },
            )
        except SessaoInvalida as exc:
            return render(
                request,
                "gestao_contratos/assinatura_invalida.html",
                {"motivo": exc.motivo},
                status=410,
            )
        return render(
            request,
            "gestao_contratos/assinatura_concluida.html",
            {"sessao": sessao, "contrato": contrato, "paciente": paciente},
        )

    return render(
        request,
        "gestao_contratos/assinar.html",
        {
            "sessao": sessao,
            "contrato": contrato,
            "paciente": paciente,
            "token": token,
        },
    )


def _tela_verificar_identidade(
    request: HttpRequest,
    sessao,
    contrato: ContratoGerado,
    paciente,
    token: str,
) -> HttpResponse:
    """Confirma quem vai assinar antes de exibir o contrato.

    Paciente maior de idade: pede a própria data de nascimento cadastrada.
    Paciente menor de idade: quem assina é o responsável legal — pede o
    CPF do responsável cadastrado (obrigatório para gerar o contrato de
    um menor, ver services/checklist.py).

    Reforça que quem assina é a pessoa correta (e não apenas quem tem
    acesso ao link/QR Code) — ver EventoContrato "identidade_confirmada"
    e "identidade_bloqueada" para a trilha de auditoria correspondente.
    """

    menor = bool(eh_menor_de_idade(paciente.data_nascimento))
    campo = "cpf_responsavel" if menor else "nascimento"

    if request.method == "POST":
        bruto = request.POST.get(campo, "")

        try:
            confirmado = confirmar_identidade(sessao, bruto)
        except SessaoInvalida as exc:
            return render(
                request,
                "gestao_contratos/assinatura_invalida.html",
                {"motivo": exc.motivo},
                status=410,
            )

        if confirmado:
            return render(
                request,
                "gestao_contratos/assinar.html",
                {
                    "sessao": sessao,
                    "contrato": contrato,
                    "paciente": paciente,
                    "token": token,
                },
            )

        sessao.refresh_from_db()
        restantes = LIMITE_TENTATIVAS_IDENTIDADE - sessao.tentativas_identidade
        mensagem = (
            "CPF do responsável legal incorreto."
            if menor
            else "Data de nascimento incorreta."
        )
        return render(
            request,
            "gestao_contratos/verificar_identidade.html",
            {
                "sessao": sessao,
                "contrato": contrato,
                "paciente": paciente,
                "token": token,
                "menor": menor,
                "erro": f"{mensagem} Restam {restantes} tentativa(s).",
            },
        )

    return render(
        request,
        "gestao_contratos/verificar_identidade.html",
        {
            "sessao": sessao,
            "contrato": contrato,
            "paciente": paciente,
            "token": token,
            "menor": menor,
        },
    )


def assinar_pdf_view(request: HttpRequest, token: str) -> HttpResponse:
    """Serve o PDF do contrato para visualização na página pública.

    Exige a mesma confirmação de identidade que ``assinar_view`` exige antes
    de mostrar o contrato. Sem isso, quem obtivesse o link ou fotografasse o
    QR Code baixaria o termo inteiro — com CPF, RG, endereço e dados de saúde
    do paciente — sem nunca provar ser a pessoa certa, o que anulava na
    prática a verificação da tela de assinatura (achado C-01).

    O link para cá só existe dentro de ``assinar.html``, que por sua vez só é
    renderizado depois da confirmação — nenhum acesso legítimo passa por aqui
    antes disso.

    Responde 404 (e não 403) para não revelar que o token existe e é válido,
    mesma resposta dada a um token inválido logo abaixo.
    """

    if _excedeu_rate_limit(request, "pdf"):
        return HttpResponse("Muitas requisições. Aguarde um instante.", status=429)

    try:
        sessao = resolver_token(token)
    except SessaoInvalida:
        raise Http404

    if not sessao.identidade_confirmada_em:
        raise Http404

    from .services.assinatura import _obter_pdf_original

    conteudo = _obter_pdf_original(sessao.contrato)
    response = HttpResponse(conteudo, content_type="application/pdf")
    response["Content-Disposition"] = 'inline; filename="contrato.pdf"'
    return response


def politica_privacidade_view(request: HttpRequest) -> HttpResponse:
    """Política de privacidade do fluxo de assinatura eletrônica.

    Página pública e estática (sem token/sessão) — linkada a partir de
    assinar.html e acessível a qualquer momento, inclusive fora do fluxo
    de assinatura em si.
    """

    return render(request, "gestao_contratos/politica_privacidade.html")


# ── Views de staff ────────────────────────────────────────────────────────────


def contexto_status_assinatura(request: HttpRequest, contrato: ContratoGerado) -> dict:
    """Monta o contexto do bloco de status de assinatura.

    Compartilhado entre a renderização inicial da pós-geração e o fragmento
    de polling HTMX, garantindo que ambos exibam exatamente a mesma coisa.
    """

    sessao = sessao_ativa(contrato)  # já expira sessões vencidas (lazy)

    # sessao_ativa() pode ter alterado contrato.status como efeito colateral
    # (via sessao.contrato, uma instância Python distinta desta mesma linha).
    # Recarrega para refletir a mudança no objeto que a view já carregou.
    contrato.refresh_from_db(fields=["status"])

    link_assinatura = ""
    if sessao is not None:
        link_assinatura = request.build_absolute_uri(
            reverse("assinatura_publica", args=[gerar_token(sessao)])
        )

    from .services.carimbo_tempo import carimbo_tempo_configurado

    expirar_terminais_vencidos()

    return {
        "contrato": contrato,
        "sessao_assinatura": sessao,
        "link_assinatura": link_assinatura,
        "eventos_assinatura": eventos_recentes(contrato),
        "poll_status_assinatura": contrato.status == "aguardando_assinatura",
        "carimbo_tempo_configurado": carimbo_tempo_configurado(),
        "terminais_disponiveis": TerminalAssinatura.objects.filter(ativo=True),
    }


@login_required
def status_assinatura_fragment_view(
    request: HttpRequest, contrato_pk: int
) -> HttpResponse:
    """Fragmento HTML consultado via polling HTMX na tela de pós-geração.

    Retorna apenas o bloco de status de assinatura. O elemento raiz só leva
    o atributo hx-trigger enquanto o contrato aguarda assinatura — quando o
    status muda (assinado, cancelado), o fragmento seguinte já não o inclui
    e o polling para sozinho, sem JavaScript adicional.
    """

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)
    contexto = contexto_status_assinatura(request, contrato)
    contexto["incluir_documentos_oob"] = True
    return render(
        request, "gestao_contratos/_status_assinatura_fragment.html", contexto
    )


@login_required
def iniciar_assinatura_view(request: HttpRequest, contrato_pk: int) -> HttpResponse:
    """Cria (ou renova) a sessão de assinatura e volta à pós-geração.

    Exige que o colaborador confirme ter verificado presencialmente a
    identidade do paciente antes de iniciar a sessão — sem essa
    confirmação, nenhuma sessão é criada. Esse é o controle de identidade
    mais forte quando o dispositivo de assinatura é compartilhado (ex.:
    tablet da recepção) em vez do celular pessoal do paciente.
    """

    if request.method != "POST":
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)

    if contrato.status == "assinado":
        messages.info(request, "Este contrato já foi assinado.")
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    if request.POST.get("identidade_presencial_confirmada") != "on":
        messages.error(
            request,
            "Confirme que verificou a identidade do paciente presencialmente "
            "antes de iniciar a assinatura.",
        )
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    # O select envia "qr" (celular do paciente) ou o pk de um terminal.
    # Valor vazio é o placeholder "Selecione o método de assinatura" — não
    # inicia sessão. Sem terminais cadastrados o formulário não tem select
    # e a chave nem chega no POST (QR Code direto).
    terminal = None
    if "terminal_pk" in request.POST:
        terminal_pk = request.POST["terminal_pk"].strip()
        if not terminal_pk:
            messages.error(request, "Selecione o método de assinatura.")
            return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)
        if terminal_pk != "qr":
            terminal = get_object_or_404(TerminalAssinatura, pk=terminal_pk, ativo=True)

    criar_sessao(
        contrato,
        criado_por=request.user,
        identidade_presencial_confirmada_em=timezone.now(),
        terminal=terminal,
    )
    if terminal:
        messages.success(
            request,
            f'Sessão de assinatura enviada para o terminal "{terminal.nome}". '
            "Entregue o tablet ao paciente.",
        )
    else:
        messages.success(
            request,
            "Sessão de assinatura criada. Peça ao paciente para escanear o QR Code.",
        )
    return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)


@login_required
def cancelar_assinatura_view(request: HttpRequest, contrato_pk: int) -> HttpResponse:
    """Cancela a sessão de assinatura ativa do contrato.

    Aceita um campo opcional ``next`` no POST para redirecionar a um destino
    diferente da própria pós-geração — usado quando o cancelamento acontece
    como consequência de outra ação (ex.: voltar para editar os dados do
    paciente interrompe a sessão em andamento e já segue para lá).
    """

    if request.method != "POST":
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)
    canceladas = cancelar_sessoes_ativas(contrato)

    if canceladas and contrato.status == "aguardando_assinatura":
        contrato.status = "gerado"
        contrato.save(update_fields=["status", "atualizado_em"])

    messages.info(
        request,
        (
            "Sessão de assinatura cancelada."
            if canceladas
            else "Nenhuma sessão ativa para cancelar."
        ),
    )

    padrao = reverse("contrato_pos_geracao", kwargs={"contrato_pk": contrato_pk})
    return redirect(destino_seguro(request, padrao))


@login_required
def qr_assinatura_view(request: HttpRequest, contrato_pk: int) -> HttpResponse:
    """Retorna o PNG do QR Code apontando para a URL pública de assinatura."""

    import qrcode

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)
    sessao = sessao_ativa(contrato)
    if sessao is None:
        raise Http404("Nenhuma sessão de assinatura ativa.")

    url = request.build_absolute_uri(
        reverse("assinatura_publica", args=[gerar_token(sessao)])
    )
    imagem = qrcode.make(url, box_size=8, border=2)
    buf = io.BytesIO()
    imagem.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")


@login_required
def baixar_contrato_assinado_view(
    request: HttpRequest, contrato_pk: int
) -> HttpResponse:
    """Retorna o PDF assinado do contrato como download."""

    contrato = get_object_or_404(ContratoGerado, pk=contrato_pk)
    paciente = contrato.paciente

    if not contrato.arquivo_pdf_assinado:
        messages.error(request, "Este contrato ainda não possui versão assinada.")
        return redirect("contrato_pos_geracao", contrato_pk=contrato_pk)

    contrato.arquivo_pdf_assinado.open("rb")
    conteudo = contrato.arquivo_pdf_assinado.read()
    contrato.arquivo_pdf_assinado.close()

    nome_arquivo = (
        f"termo_{contrato.tipo}_{paciente.nome.split()[0].lower()}"
        f"_{paciente.id_dental}_assinado.pdf"
    )
    response = HttpResponse(conteudo, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    return response
