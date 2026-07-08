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

Abaixo estão prompts prontos para você usar com um agente de código/design. Estruturei seguindo a ideia do artigo da Anthropic: dar contexto estético reutilizável, evitar visual genérico, orientar por eixos implementáveis como hierarquia, layout, copy, movimento e consistência, sem especificar detalhes excessivamente baixos como hex codes rígidos. Fonte: [Improving frontend design through Skills](https://claude.com/blog/improving-frontend-design-through-skills).

**Prompt Mestre**

```text
Você é um especialista em frontend para sistemas operacionais internos feitos em Python/Django. 
Refatore os templates da aplicação de geração de contratos odontológicos com foco em clareza operacional, redução de redundância, hierarquia visual e velocidade de uso.

Contexto do produto:
- O usuário provavelmente é recepcionista, administrativo ou operador de clínica.
- A interface deve parecer confiável, limpa e profissional, não uma landing page.
- Priorize formulários bem alinhados, ações primárias evidentes, feedback visual claro e textos objetivos.
- Evite estética genérica de IA: não use layouts previsíveis demais, excesso de cards, gradientes roxos, fontes genéricas como Inter/Roboto/Arial quando houver liberdade visual.
- Use uma identidade visual sóbria para saúde/serviço: contraste bom, espaçamento consistente, botões com hierarquia clara, campos de formulário densos porém confortáveis.
- Preserve a lógica Django existente, nomes de campos, rotas, CSRF, validações, mensagens e includes. Altere backend apenas se for estritamente necessário para suportar o novo fluxo.
- Não crie uma nova aplicação. Trabalhe sobre os templates existentes.

Objetivo:
Reorganizar as telas do fluxo de contratos para que cada etapa tenha uma ação principal clara, menos texto redundante e melhor alinhamento dos campos e botões.
```

**Prompt 1 — Tela De Busca De Contratos**

```text
Refatore a tela de contratos onde o usuário realiza a busca.

Mudanças obrigatórias:
- Remover a existência visual de dois botões de busca.
- A interface deve apresentar somente uma ação principal: “Buscar”.
- A busca deve comunicar que o sistema consulta primeiro os cadastros locais e, em seguida, o Dental Office automaticamente.
- Remover ou esconder o botão “Buscar no Dental Office” da experiência principal.
- Reposicionar o botão “Limpar busca” para ficar na mesma linha do campo de busca e do botão “Buscar”, nunca abaixo do botão principal.
- O alinhamento deve funcionar bem em desktop e mobile: em telas largas, campo + Buscar + Limpar na mesma linha; em telas pequenas, os controles podem empilhar, mas mantendo ordem lógica.

Direção de design:
- Faça a área de busca parecer uma ferramenta de trabalho rápida, não um bloco explicativo.
- Use uma hierarquia clara: campo de busca dominante, botão “Buscar” como ação primária, “Limpar busca” como ação secundária discreta.
- Se houver texto auxiliar, use algo curto, por exemplo: “A busca consulta o cadastro local e o Dental Office automaticamente.”
- Preserve a lógica de busca existente, ajustando apenas o fluxo visual e, se necessário, a chamada para que uma única submissão execute a busca combinada.
```

**Prompt 2 — Tela De Confirmação Dos Dados Do Paciente**

```text
Refatore a tela de confirmação dos dados do paciente com foco em copy mais objetiva.

Mudança obrigatória:
Substituir o texto:
“Os campos abaixo preencherão o contrato. Corrija o que for necessário e clique em Confirmar dados para liberar a geração. O convênio é um dado local — não vem do Dental Office.”

Por:
“Os campos abaixo preencherão o contrato. Corrija o que for necessário e clique em Confirmar dados para liberar a geração.”

Direção de design:
- Mantenha a tela com aparência de revisão de dados antes de gerar contrato.
- Destaque a ação “Confirmar dados” como etapa de avanço.
- Evite textos explicativos redundantes.
- Preserve todos os campos, validações e mensagens já existentes.
```

**Prompt 3 — Tela Para Gerar Contrato**

```text
Refatore a tela de geração do contrato.

Mudanças obrigatórias:
- Remover temporariamente os campos “Nome do profissional” e “CRO” da interface.
- Ao lado do campo “E-mail para envio”, adicionar o campo “WhatsApp”.
- O campo “WhatsApp” deve permitir ao usuário revisar ou confirmar o número que será usado para envio.
- Em desktop, “E-mail para envio” e “WhatsApp” devem ficar lado a lado.
- Em mobile, os campos devem empilhar com espaçamento confortável.
- Existe um botão que atualmente sugere “enviar novamente as informações ao Dental Office”, mas na prática volta para a página de confirmação/edição dos dados do paciente.
- Renomear e redesenhar esse botão para deixar claro que ele leva à edição dos dados do paciente.
- Sugestões de texto para o botão: “Editar dados do paciente”, “Voltar para editar dados” ou “Revisar dados do paciente”.
- Escolha o texto mais claro para o contexto da tela.

Direção de design:
- A tela deve parecer uma etapa final de preparação antes da geração.
- A ação principal deve continuar sendo gerar contrato.
- A ação de edição deve ser secundária, visualmente menos forte que a geração.
- Não deixe o usuário pensar que está sincronizando/enviando dados ao Dental Office se o botão apenas volta para edição.
- Preserve nomes de campos esperados pelo backend ou adapte cuidadosamente o template sem quebrar o POST.
```

**Prompt 4 — Tela De Contrato Gerado**

```text
Refatore a tela de contrato gerado. Esta é a tela que precisa da maior melhoria de usabilidade.

Seção de assinatura:
- Substituir o texto atual:
“Gere um QR Code para o paciente assinar o contrato no próprio celular ou tablet — sem login e sem baixar nada.”

Por uma versão mais informativa e natural, por exemplo:
“Gere um QR Code para o paciente assinar o contrato no próprio celular ou no tablet da recepção.”
- O select de método de assinatura deve iniciar com uma opção placeholder clara:
“Selecione o método de assinatura”
- Essa opção placeholder deve estar selecionada por padrão e não deve iniciar assinatura.
- O botão “Iniciar assinatura” deve ficar ao lado do select de método de assinatura em telas largas.
- Em telas pequenas, select e botão podem empilhar, mantendo o select antes do botão.
- A ação só deve ficar visualmente habilitada quando houver método selecionado, se a lógica atual permitir.

Seção de envio/compartilhamento:
- Remover textos explicativos redundantes.
- Remover o botão “Compartilhar arquivo”.
- Renomear o botão “Abrir WhatsApp” para “Compartilhar via WhatsApp”.
- Os botões de envio/compartilhamento devem ficar ao lado dos respectivos campos de preenchimento.
- Para WhatsApp: campo de número + botão “Compartilhar via WhatsApp” na mesma linha em desktop.
- Para e-mail: campo de e-mail + botão de envio por e-mail na mesma linha em desktop.
- Em mobile, cada campo e seu botão podem empilhar, mas devem continuar agrupados visualmente.

Remoções:
- Remover a seção/campos/botões de baixar documento.
- Remover a seção/campos/botões de enviar documento ao Dental Office.

Direção de design:
- Organize a tela por tarefas reais: assinatura, envio por WhatsApp, envio por e-mail.
- Evite cards em excesso. Use seções limpas, títulos curtos e alinhamento consistente.
- Faça os botões parecerem ações diretas e específicas.
- Reduza ruído visual: se uma ação não está disponível ou não deve ser usada agora, remova da interface.
- Preserve o acesso ao contrato gerado se ele for necessário para visualização, mas não ofereça download se a exigência atual é remover essa ação.
```

**Prompt 5 — Revisão Final / QA Visual**

```text
Depois de aplicar as mudanças, revise os templates alterados com os seguintes critérios:

- Não deve existir mais a duplicidade de busca com “Busca” e “Buscar no Dental Office”.
- O botão “Limpar busca” deve estar alinhado com o campo de busca e o botão “Buscar”.
- A frase da confirmação dos dados do paciente deve estar exatamente sem a menção ao convênio/Dental Office.
- A tela de gerar contrato não deve exibir “Nome do profissional” nem “CRO”.
- A tela de gerar contrato deve exibir “E-mail para envio” e “WhatsApp” lado a lado em desktop.
- O botão que volta para confirmação/edição deve ter texto coerente, como “Editar dados do paciente”.
- A tela de contrato gerado deve ter placeholder “Selecione o método de assinatura”.
- O botão de iniciar assinatura deve ficar ao lado do select em desktop.
- Não deve existir botão “Compartilhar arquivo”.
- “Abrir WhatsApp” deve virar “Compartilhar via WhatsApp”.
- Botões de compartilhamento devem ficar próximos aos campos correspondentes.
- Não deve existir seção para baixar documento.
- Não deve existir seção para enviar documento ao Dental Office.
- Verifique responsividade em mobile e desktop.
- Verifique se nenhum formulário Django perdeu CSRF, name, value, action ou method necessário.
```

Eu também ajustaria a frase sugerida de assinatura para “no tablet da recepção”, porque “reflita no tablet” soa como erro de digitação e pode confundir o usuário final.

Você é um especialista em frontend para sistemas operacionais internos feitos em Python/Django. 
Pense minuciosamente sobre a aplicação de gestão de laboratórios (gestao_lab) e elabore melhorias visuais que devem ser aplicadas na aplicação com foco em clareza operacional, redução de redundância, hierarquia visual e velocidade de uso.

<context>
A aplicação para gestao de materiais em laboratórios tem como finalidade realizar a gestão de todos os materiais que forem emprestados para laboratórios parceiros. É necessário realizar o controle dos materiais entregues tanto os que estão em dia, os atrasados e os a confirmar. Também é necessário que o sistema aponte visualmente os materiais que estão em atraso e a confirmar. Também é necessário realizar o controle sobre o que foi faturado, os laboratórios parceiros, as equipes responsáveis, os pacientes que são sincronizados do Dental Office (não confundir com a aplicação de gestão de contratos) e  os alunos que são responsavéis pelos procedimentos (retornados da API do EDUQ).
</context>

<frontend_aesthetics>
Você tende a convergir para resultados genéricos, típicos de distribuições padrão. No design de frontend, isso
cria o que os usuários chamam de estética de "tralha de IA" (*AI slop*). Evite isso: crie frontends
criativos e distintos que surpreendam e encantem.

Foque em:
- Tipografia: Escolha fontes que sejam bonitas, únicas e interessantes. Evite fontes genéricas
como Arial e Inter; opte por escolhas distintas que elevem a
estética do frontend.
- Cor e Tema: Comprometa-se com uma estética coesa. Use variáveis ​​CSS para garantir consistência.
Cores dominantes com detalhes de destaque marcantes funcionam melhor do que paletas tímidas e distribuídas uniformemente.
Busque inspiração em temas de IDEs e estéticas culturais.
- Movimento: Use animações para efeitos e microinterações. Priorize soluções apenas em CSS
para HTML. Use bibliotecas de movimento para React quando disponíveis. Foque em momentos de alto impacto:
um carregamento de página bem orquestrado com revelações escalonadas (*animation-delay*)
gera mais encantamento do que microinterações dispersas.
- Planos de fundo: Crie atmosfera e profundidade em vez de recorrer a cores sólidas padrão.
Sobreponha gradientes CSS, use padrões geométricos ou adicione efeitos contextuais
que combinem com a estética geral.

Evite estéticas genéricas geradas por IA:
- Famílias de fontes usadas em excesso (Inter, Roboto, Arial, fontes do sistema)
- Esquemas de cores clichês (particularmente gradientes roxos em fundos brancos)
- Layouts e padrões de componentes previsíveis
- Design padronizado e repetitivo, sem personalidade específica para o contexto

Interprete de forma criativa e faça escolhas inesperadas que pareçam genuinamente projetadas para o
contexto. Varie entre temas claros e escuros, fontes diferentes e estéticas distintas. Você
ainda tende a convergir para escolhas comuns (Space Grotesk, por exemplo) entre
as gerações. Evite isso: é fundamental pensar fora da caixa!
</frontend_aesthetics>