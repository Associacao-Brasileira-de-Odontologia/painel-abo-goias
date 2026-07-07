Prompts de Implementação
Os prompts estão ordenados por dependência — cada etapa é pré-requisito da seguinte.

Prompt 1 — Fundação: armazenar o arquivo + campo e-mail

No app Django gestao_contratos do projeto em abo-goias/:

1. Em gestao_lab/models.py, adicione o campo `email = models.EmailField(blank=True, default="")`
   ao modelo Paciente. Crie e aplique a migration correspondente.

2. Em gestao_contratos/models.py, atualize ContratoGerado adicionando:
   - `arquivo` (FileField, upload_to="contratos/", blank=True) — armazena o DOCX gerado
   - `status_envio` (CharField, choices: nao_enviado/enviado_email/enviado_whatsapp, default "nao_enviado")
   - `enviado_em` (DateTimeField, null=True, blank=True)
   Crie e aplique a migration.

3. Em gestao_contratos/services/documentos.py, a função `gerar_contrato()` atualmente retorna bytes.
   Adicione uma variante `gerar_e_salvar_contrato(paciente, tipo, ...) -> ContratoGerado` que:
   - Chama `gerar_contrato()` para obter os bytes
   - Salva o arquivo no campo `arquivo` do ContratoGerado
   - Retorna a instância salva

4. Em gestao_contratos/views.py, atualize `_processar_geracao()` para usar
   `gerar_e_salvar_contrato()`, mantendo o retorno como download DOCX (comportamento atual).

5. Na view de detalhes do paciente (gerar_contrato_view), após a geração bem-sucedida,
   exiba o campo de e-mail editável no formulário. Se o Dental Office retornar e-mail
   no payload de `buscar_detalhes_paciente()` em gestao_lab/integrations/dental.py,
   mapeie e salve esse campo no Paciente também.
Prompt 2 — Envio por e-mail e link WhatsApp

No app gestao_contratos (abo-goias/gestao_contratos/), implemente envio do contrato
após a geração. Este prompt depende do Prompt 1 (campo arquivo e email no Paciente).

ENVIO POR E-MAIL:
1. Configure Django email backend via variáveis de ambiente: EMAIL_HOST, EMAIL_PORT,
   EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL. Adicione ao settings.py
   usando os.environ.get() com fallback para console backend em DEBUG.

2. Crie gestao_contratos/services/envio.py com a função:
   `enviar_contrato_email(contrato: ContratoGerado, destinatario: str) -> bool`
   - Usa django.core.mail.EmailMessage
   - Assunto: "Termo de Consentimento — {tipo} — ABO Goiás"
   - Corpo: mensagem informando que o documento está em anexo para leitura e assinatura
   - Anexa o arquivo DOCX salvo em contrato.arquivo
   - Em caso de erro, loga e retorna False
   - Atualiza contrato.status_envio = "enviado_email" e contrato.enviado_em = timezone.now()

LINK WHATSAPP:
3. No mesmo arquivo de serviços, crie:
   `gerar_link_whatsapp(celular: str, contrato: ContratoGerado) -> str`
   - Normaliza o número removendo caracteres não numéricos e adicionando +55 se necessário
   - Retorna "https://wa.me/{numero}?text={mensagem_codificada}"
   - Mensagem padrão: "Olá! Segue seu Termo de Consentimento ({tipo}) da ABO Goiás.
     Por favor, baixe, assine e envie de volta."
   - Também atualiza contrato.status_envio = "enviado_whatsapp"

INTERFACE:
4. Em gestao_contratos/views.py, após a geração bem-sucedida (atualmente retorna download):
   - Salve o contrato (usa Prompt 1) e redirecione para uma nova view `post_geracao_view`
     que exibe:
     a. Botão "Baixar contrato" (mantém o download original)
     b. Campo e-mail (pré-preenchido de paciente.email, editável) + botão "Enviar por e-mail"
     c. Campo telefone (pré-preenchido de paciente.celular, editável) + botão "Abrir WhatsApp"
        (o link WhatsApp abre em nova aba com o link gerado)

5. Adicione a URL correspondente em gestao_contratos/urls.py.
   Crie o template gestao_contratos/pos_geracao.html seguindo o padrão visual existente
   (layout-grid, panel config-panel / results-panel, botões .button.primary/.secondary).
Prompt 3 — Assinatura digital com notificação em sistema

No app gestao_contratos (abo-goias/gestao_contratos/), implemente assinatura digital
usando o serviço D4Sign (https://d4sign.com.br) que é brasileiro, tem API REST e suporta
webhooks. Este prompt depende dos Prompts 1 e 2.

DEPENDÊNCIA: adicione `requests` ao requirements.txt se não estiver.
Adicione as variáveis de ambiente: D4SIGN_API_TOKEN, D4SIGN_CRYPT_KEY, D4SIGN_SAFE_UUID
(obtidos no painel D4Sign).

1. Em gestao_contratos/models.py, adicione ao ContratoGerado:
   - `status_assinatura` (CharField, choices: pendente/aguardando/assinado/recusado,
     default "pendente")
   - `d4sign_uuid` (CharField, max_length=100, blank=True) — ID do documento no D4Sign
   - `assinado_em` (DateTimeField, null=True, blank=True)
   - `arquivo_assinado` (FileField, upload_to="contratos/assinados/", blank=True)
   Crie e aplique migration.

2. Crie gestao_contratos/integrations/d4sign.py com a classe D4SignClient:
   - `__init__(self)`: lê token e chave de os.environ
   - `fazer_upload(nome_arquivo: str, arquivo_bytes: bytes) -> str`: POST /documents/{safe_uuid}/upload
     — retorna o UUID do documento no D4Sign
   - `adicionar_signatario(doc_uuid: str, email: str, nome: str) -> None`: POST /documents/{uuid}/createsigner
   - `enviar_para_assinatura(doc_uuid: str) -> None`: POST /documents/{uuid}/sendtosigner
   - `baixar_documento_assinado(doc_uuid: str) -> bytes`: GET /documents/{uuid}/download
   - A autenticação usa header `tokenAPI` + `cryptKey` conforme documentação D4Sign v2

3. Em gestao_contratos/services/envio.py, adicione:
   `enviar_para_assinatura_digital(contrato: ContratoGerado, email_signatario: str,
    nome_signatario: str) -> bool`
   - Converte o DOCX em PDF usando subprocess com LibreOffice:
     `subprocess.run(["libreoffice", "--headless", "--convert-to", "pdf", arquivo_path])`
     OU se LibreOffice não estiver disponível, faça o upload do DOCX diretamente
     (D4Sign aceita DOCX)
   - Chama D4SignClient.fazer_upload() → obtém doc_uuid
   - Chama D4SignClient.adicionar_signatario() com o email do paciente
   - Chama D4SignClient.enviar_para_assinatura()
   - Atualiza contrato.d4sign_uuid = doc_uuid e contrato.status_assinatura = "aguardando"
   - Retorna True/False

4. Crie o webhook em gestao_contratos/views.py (view sem @login_required, validando
   assinatura HMAC ou token fixo por variável de ambiente):
   `def webhook_d4sign(request) → HttpResponse`
   - Aceita POST com JSON do D4Sign
   - Quando `type_post == "signed"`: busca ContratoGerado pelo uuid_doc,
     atualiza status_assinatura = "assinado", assinado_em = agora,
     baixa o PDF assinado e salva em arquivo_assinado
   - Registre em gestao_contratos/urls.py:
     `path("webhook/d4sign/", views.webhook_d4sign, name="webhook_d4sign")`
     também em abo_goias/urls.py sem o prefixo de autenticação

5. Modelo de notificação — em gestao_contratos/models.py, crie:
   `class NotificacaoContrato(ModeloBase):`
   - `contrato` (FK ContratoGerado)
   - `mensagem` (CharField)
   - `lida` (BooleanField, default False)
   - `usuario` (FK User)
   Crie migration.

6. No webhook (passo 4), após atualizar o status, crie um NotificacaoContrato para o
   campo `gerado_por` do contrato com a mensagem:
   "O contrato de {paciente.nome} ({tipo}) foi assinado digitalmente."

7. No base.html do projeto, adicione um indicador de notificações (contador em badge)
   que consulta via AJAX GET /contratos/notificacoes/ quantas notificações não lidas
   existem para o usuário logado. Crie essa view em gestao_contratos/views.py.
   Crie também a view `marcar_notificacoes_lidas` (POST).
Prompt 4 — Envio ao Dental Office após assinatura

ATENÇÃO: antes de implementar este prompt, verifique se a API do Dental Office suporta
upload de documentos. Em gestao_lab/integrations/dental.py, o DentalClient só faz
requisições GET. Consulte a documentação da API do Dental Office para os endpoints:
- POST /customers/{id}/documents ou similar
- POST /customers/{id}/attachments

Se o endpoint existir, implemente:

1. Em gestao_lab/integrations/dental.py, adicione ao DentalClient:
   `def enviar_documento_paciente(self, id_dental: str, arquivo_bytes: bytes,
    nome_arquivo: str, descricao: str) -> dict`
   - POST para o endpoint de upload identificado na documentação
   - Content-Type: multipart/form-data
   - Retorna o JSON de resposta ou lança DentalAPIError em caso de falha

2. Em gestao_contratos/services/envio.py, adicione:
   `def enviar_ao_dental_office(contrato: ContratoGerado) -> bool`
   - Lê o arquivo_assinado do contrato
   - Instancia DentalClient e chama enviar_documento_paciente() com o PDF assinado
   - Nome do arquivo: "Termo_{tipo}_{data}.pdf"
   - Em caso de sucesso, registra log; em falha, lança exceção tratada

3. No webhook de assinatura (Prompt 3, passo 4), após salvar o arquivo assinado,
   chame enviar_ao_dental_office(contrato) em try/except — falha no envio ao Dental
   não deve impedir o registro da assinatura no sistema.

4. Na view de detalhes do contrato, exiba o status do envio ao Dental Office
   com botão "Reenviar ao Dental Office" para reprocessamento manual em caso de falha.

Se o endpoint de upload NÃO existir na API do Dental Office, implemente somente:
- Um botão "Baixar contrato assinado" que retorna o arquivo_assinado
- Instruções em tela orientando o usuário a anexar manualmente na ficha do paciente
Ordem de execução recomendada

Prompt 1 → Prompt 2 → Prompt 3 → Prompt 4
   ↑              ↑              ↑              ↑
fundação      envio       assinatura     Dental Office
(obrigatório)  (rápido)    (D4Sign)      (condicional)
O Prompt 1 é pré-requisito de todos os demais. O Prompt 2 já entrega valor sem integração paga. Os Prompts 3 e 4 requerem conta no D4Sign e confirmação da API do Dental Office respectivamente.


-- Funcionalidades para adicionar --
- Fazer o espelhamento do PC e tablet 
- Fazer o cadastro dos templates necessários 
- Todo o processo de anexar e enviar os documentos ao Dental Office de forma automática (via Webhooks de assinatura)
- Validar o envio do documento para Intranet 
- Quando o usuário realizar a assinatura do documento, uma cópia deve ser enviada automaticamente para o WhatsApp ou e-mail do paciente.

A fazer: 

- Fazer o levantamento sobre quais as informações são necessárias para preenchimento do contrato
- Pesquisar sobre a legimitidade da implementação e assinatura pelo forma fornecida
- Explorar outras possibilidades de implementação da aplicação de assinatura
- Fazer a refatoração do frontend todas as aplicações retirando a estética AI
- Avaliar possíveis melhorias a serem implementadas nas outras aplicações
- Realizar a implementação da aplicação para produção
- Fazer o levantamento técnico de todas as aplicações para possível integração com a intranet
- Pesquisar e documentar os custos totais associados para funcionamento da aplicação
- Explorar quantos usuários estarão acessando a aplicação diariamente

Atue como especialista em front-end para aplicações Django.

<context>
- Sistema modular para instituição de ensino em saúde (foco: Odontologia, graduação e pós)
- Stack: [Django templates]
- Público da app de contratos: [equipe administrativa / alunos / ambos]

TAREFA:
Refatorar apenas a aplicação de "gestão de contratos" (telas: listagem, 
detalhe, criação/edição, [outras]) antes de expandir para o restante do sistema.

RESTRIÇÕES:
- Preservar toda lógica de backend e comportamento funcional existente
- Seguir WCAG AA de acessibilidade (contraste, foco, leitura por teclado)
- Interface em pt-BR, formatos de data/moeda brasileiros
- Respeitar identidade visual: [cores/logo institucional]

Antes de propor código, explore os templates/arquivos atuais em [caminho] 
para entender a estrutura existente.
</context>

<frontend_aesthetics>
Você tende a convergir para resultados genéricos e padronizados. No design de frontend, isso cria o que os usuários chamam de estética de "conteúdo genérico de IA" (*AI slop*). Evite isso: crie frontends criativos e distintos que surpreendam e encantem.

Foque em:
- Tipografia: Escolha fontes que sejam bonitas, únicas e interessantes. Evite fontes genéricas como Arial e Inter; opte por escolhas distintas que elevem a estética do frontend.
- Cores e Tema: Comprometa-se com uma estética coesa. Use variáveis ​​CSS para garantir consistência. Cores dominantes com detalhes de destaque (*accents*) funcionam melhor do que paletas tímidas e distribuídas de forma uniforme. Busque inspiração em temas de IDEs e estéticas culturais.
- Movimento: Use animações para efeitos e microinterações. Priorize soluções apenas com CSS para HTML. Use bibliotecas de movimento disponíveis para o projeto atual. Concentre-se em momentos de alto impacto: um carregamento de página bem orquestrado, com revelações escalonadas (*animation-delay*), gera mais encantamento do que microinterações dispersas.
- Planos de fundo: Crie atmosfera e profundidade em vez de recorrer apenas a cores sólidas. Sobreponha gradientes CSS, use padrões geométricos ou adicione efeitos contextuais que combinem com a estética geral.

Evite estéticas genéricas geradas por IA:
- Famílias de fontes muito utilizadas (Inter, Roboto, Arial, fontes do sistema)
- Esquemas de cores clichês (particularmente gradientes roxos em fundos brancos)
- Layouts e padrões de componentes previsíveis
- Design padronizado e repetitivo, sem personalidade específica para o contexto

Interprete de forma criativa e faça escolhas inesperadas que pareçam genuinamente projetadas para o contexto. Alterne entre temas claros e escuros, fontes diferentes e estéticas variadas. Você ainda tende a convergir para escolhas comuns (como Space Grotesk, por exemplo) entre as gerações. Evite isso: é fundamental pensar fora da caixa!
</frontend_aesthetics>