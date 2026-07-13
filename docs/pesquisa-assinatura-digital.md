# Pesquisa: Assinatura Digital — Plataformas de Mercado × Solução Própria

> Documento de apoio à decisão para o Painel ABO Goiás.
> Data: 13/07/2026.

---

## 1. Como o sistema assina hoje (diagnóstico da solução atual)

Antes de comparar com o mercado, é preciso entender exatamente o que a aplicação já faz. Isso está implementado em `abo-goias/gestao_contratos/services/` (`assinatura.py`, `assinatura_pdf.py`, `carimbo_tempo.py`).

**Fluxo atual:**

1. **Sessão remota com token assinado** — o link público é gerado com `django.core.signing` (HMAC sobre a `SECRET_KEY`). Nenhum segredo é gravado no banco; a validade é controlada por `expira_em` e o uso único por uma transição de status atômica.
2. **Confirmação de identidade** — antes de liberar o canvas, o signatário confirma a **data de nascimento** (paciente maior) ou o **CPF do responsável** (menor de idade). Há limite de tentativas (anti-brute force) e opção de confirmação presencial por um colaborador.
3. **Assinatura manuscrita digitalizada** — o paciente desenha a assinatura num canvas HTML5; o PNG é validado e mesclado sobre a linha de assinatura do PDF.
4. **Carimbo de auditoria** — rodapé do PDF com data/hora e IP; trilha de eventos completa em `EventoContrato` (abertura, identidade, IP, user-agent, timestamps).
5. **Integridade por hash** — `SHA-256` do PDF assinado é calculado e armazenado.
6. **Carimbo de tempo RFC 3161 (opcional)** — se uma TSA estiver configurada, solicita um token de tempo de terceiro sobre o hash e o embute no próprio PDF.

**Classificação jurídica (Lei 14.063/2020):** a solução atual é uma **Assinatura Eletrônica Simples — porém com trilha de evidências robusta**. Ela identifica o signatário e associa dados a ele (requisito da simples), e ainda garante integridade (hash + carimbo de tempo). O que a impede de ser "avançada" é que a autoria **não está vinculada criptograficamente a uma chave sob controle exclusivo do signatário** (certificado próprio, biometria forte, etc.) — a identidade é confirmada por um dado conhecido (data de nascimento/CPF), que é um controle mais fraco. Ver seção 4.

---

## 2. Tipos de assinatura eletrônica no Brasil

A **Lei nº 14.063/2020** (com base na **MP 2.200-2/2001**, que criou a ICP-Brasil) define três níveis:

| Nível | O que é | Vínculo de identidade | Validade jurídica |
|---|---|---|---|
| **Simples** | Identifica o signatário e associa dados a ele. Ex.: clique em "aceito", assinatura desenhada, confirmação por e-mail/SMS. | Fraco a médio (e-mail, SMS, dado pessoal). | Válida para atos de **baixo/médio risco** e entre partes que a aceitem. Prova pode exigir evidências adicionais (logs, IP). |
| **Avançada** | Usa **certificado não-ICP-Brasil** *ou outros meios* que comprovem autoria e integridade, aceitos pelas partes. Detecta alterações posteriores e vincula unicamente ao signatário. | Médio a forte (certificado próprio, biometria, gov.br). | Válida e com boa força probatória; aceita inclusive em interações com o poder público (salvo exceções). |
| **Qualificada** | Usa **certificado digital ICP-Brasil** (e-CPF/e-CNPJ, A1/A3/nuvem). | Forte (chave privada + certificado emitido por AC credenciada). | **Presunção legal de autenticidade** (art. 10, §1º, MP 2.200-2). Equivale à assinatura de próprio punho; substitui o papel integralmente. |

**Paralelo internacional (eIDAS, União Europeia):** SES (*Simple*) ≈ simples, AES (*Advanced*) ≈ avançada, QES (*Qualified*) ≈ qualificada. A lógica é a mesma.

**Onde cada uma é exigida:**
- **Simples/Avançada** já bastam para a **maioria** dos documentos entre particulares: contratos de prestação de serviço, orçamentos, **termos de consentimento** (TCLE) odontológicos.
- **Qualificada** é obrigatória em casos específicos — por exemplo, **prescrição/receita eletrônica** e documentos que exijam presunção legal plena ou interação formal com órgãos que a exijam.

### 2.1. Em qual categoria seu sistema está?

**→ Assinatura Eletrônica Simples (com trilha de evidências reforçada).**

Pontos que **já** aproximam a solução de uma "avançada" em termos de integridade:
- Hash SHA-256 do documento (detecta alteração).
- Carimbo de tempo RFC 3161 de terceiro (prova de data/hora independente do servidor).
- Trilha de auditoria detalhada (IP, user-agent, eventos, tentativas de identidade).

O que **falta** para ser formalmente "avançada":
- Vínculo da autoria a um fator sob controle exclusivo do signatário (certificado próprio, biometria facial *liveness*, ou identidade gov.br).
- A verificação de identidade atual (data de nascimento/CPF) é um "segredo compartilhado" relativamente fraco.

Para **TCLE e contratos odontológicos** entre a clínica e o paciente, a assinatura **simples já tem validade jurídica** (Lei 14.063/2020; CC art. 219; MP 2.200-2 art. 10, §2º). O sistema atual, com hash + carimbo de tempo + trilha, é inclusive **mais robusto que muitas implementações de "simples" do mercado**.

---

## 3. Plataformas do mercado — comparação plataforma por plataforma

> Preços coletados em jul/2026, sujeitos a alteração. Onde há "anual", é o preço/mês na cobrança anual.

### ClickSign
- **Planos:** Start R$ 39/mês (20–200 docs, 5 usuários, certificado digital, API) · Plus R$ 59 (WhatsApp, biometria, Click.AI, marca própria) · Automação R$ 85 (geração por template, envio em lote) · Avançado (sob consulta, White Label API, logs de auditoria, backup, SLA). Trial de 14 dias.
- **Diferenciais:** empresa brasileira mais consolidada do segmento; **única certificada ISO 27001 e ISO 27701**; forte no corporativo; APIs maduras.
- **Perfil:** quem prioriza compliance/segurança e integração corporativa.

### ZapSign
- **Planos:** Gratuito (5 docs/mês, 1 usuário) · Profissional R$ 29,90/mês (240 docs/ano, 6 usuários) · Completo R$ 79,90 (ilimitado, 11 usuários) · Customizado (sob contrato).
- **Diferenciais:** **melhor custo-benefício** para PME; preços em real; certificado A1 ICP-Brasil no documento final; recursos por **créditos** (WhatsApp 5, biometria facial 15, validação de CPF na Receita 10); 2.000+ integrações via Zapier/Make/Pluga.
- **Perfil:** pequenas e médias operações, entrada barata, forte em WhatsApp.

### Assinadoc
- **Planos:** Básico R$ 35/mês (R$ 26,25 anual) · Automação R$ 75 · Profissional R$ 95 (mais popular) · IA Premium R$ 135. **Documentos e assinaturas ilimitados em todos os planos.**
- **Diferenciais:** **API RESTful com 30+ endpoints**, webhooks, exemplos no GitHub e documentação completa (bom para integração via [/desenvolvedores](https://assinadoc.com/desenvolvedores)); planos superiores com automação de WhatsApp, renovação de contrato e IA.
- **Perfil:** quem quer volume ilimitado por preço fixo e boa API.

### TOTVS Assinatura Eletrônica
- **Planos:** por **pacotes de envelopes** (um envelope agrupa vários docs de um mesmo processo, consumindo 1 crédito). A partir de **R$ 78,84/mês** (2 pacotes de 10 envelopes); pacotes de 20 envelopes a partir de R$ 624/mês; 50 envelopes a partir de R$ 1.190/mês. Usuários e signatários ilimitados.
- **Diferenciais:** suporta **avançada e qualificada ICP-Brasil (A1/A3/A3 nuvem)** + carimbo do tempo; API RESTful; integração nativa com o **ecossistema TOTVS (Protheus, RM, etc.)**.
- **Perfil:** empresas que já usam ERP TOTVS ou precisam de assinatura qualificada corporativa. Mais caro e "enterprise".

### Autentique
- **Planos:** Free (10 docs/mês) · Profissional R$ 99/mês (ilimitado) · Corporativo a partir de R$ 2.000/mês (white-label, SLA, suporte prioritário). 15% de desconto no anual.
- **API (pay-per-use, ótimo para embutir no seu sistema):** criar documento **R$ 0,06** · assinatura por e-mail **R$ 0,013** · WhatsApp **R$ 0,12** · SMS **R$ 0,16** · consulta de documento R$ 0,001 · webhook R$ 0,0002. Sandbox gratuito.
- **Diferenciais:** autenticação por certificado A1/A3/nuvem, **biometria facial**, validação de CPF, e-mail/SMS/WhatsApp; base de 60 mil empresas e 4 mil órgãos públicos.
- **Perfil:** **melhor modelo de custo por API** para quem tem volume variável — você paga por documento, não assinatura mensal. Forte candidata para o seu caso.

### ContraktorSign
- **Planos:** Free (5 docs/mês) · Light R$ 19,90/mês (15 docs, 6 usuários) · Essential R$ 47,40 (50 docs, 10 usuários, 5 envios WhatsApp) · Unlimited R$ 142,40 (ilimitado, 15 envios WhatsApp).
- **Diferenciais:** foco em **gestão do ciclo de vida de contratos** (não só assinatura); signatários ilimitados em todos os planos. API não destacada na página de planos (confirmar disponibilidade).
- **Perfil:** quem quer gestão contratual + assinatura no mesmo lugar.

### SuperSign
- **Planos:** Free (3 docs/mês) · Essencial R$ 38,90 (20 docs) · Profissional R$ 58,90 (60 docs, templates) · Elite R$ 83,90 (100 docs, **selfie + documento**) · Avançado ~R$ 109 (250 docs) · Enterprise (sob consulta). Também modelo **pré-pago por créditos** (50/100/300/500/1000+).
- **Diferenciais:** autenticação por e-mail/WhatsApp/SMS/selfie+documento; armazenamento ilimitado; **API a partir de 100 envios**; infra Google Cloud.
- **Perfil:** flexível (assinatura mensal ou pré-pago), bom para volume irregular.

### Resumo comparativo

| Plataforma | Entrada (R$/mês) | Modelo | API forte? | Destaque |
|---|---|---|---|---|
| **ZapSign** | 0 / 29,90 | Assinatura + créditos | Sim | Custo-benefício, WhatsApp |
| **Autentique** | 0 / 99 | Assinatura **ou pay-per-use** | **Sim (por doc)** | Melhor p/ embutir via API |
| **ClickSign** | 39 | Assinatura | Sim | ISO 27001/27701, corporativo |
| **Assinadoc** | 35 | Ilimitado fixo | Sim (30+ endpoints) | Volume ilimitado barato |
| **SuperSign** | 0 / 38,90 | Assinatura ou pré-pago | Sim (≥100) | Flexibilidade, selfie |
| **ContraktorSign** | 0 / 19,90 | Assinatura | A confirmar | Ciclo de vida de contrato |
| **TOTVS** | 78,84 | Envelopes | Sim | ICP-Brasil + ERP TOTVS |

---

## 4. Benefícios de adotar uma plataforma de terceiros

1. **Transferência de responsabilidade jurídica** — a validade da prova passa a ser sustentada por um terceiro especializado e testado em juízo, não pela sua implementação interna.
2. **Trilha de auditoria e PAdES padronizados** — relatórios de assinatura reconhecidos, log de eventos completo, página de validação pública.
3. **Identidade mais forte pronta de fábrica** — biometria facial com *liveness*, validação de CPF na Receita, SMS, gov.br — sem você desenvolver nada.
4. **Assinatura qualificada (ICP-Brasil)** — caminho pronto caso algum documento passe a exigir presunção legal plena (ex.: prescrição).
5. **Menos superfície de manutenção e risco** — carimbo de tempo, criptografia, armazenamento e conformidade viram problema do fornecedor (muitos com ISO 27001, LGPD).
6. **Confiança percebida pelo paciente** — selo de uma marca conhecida no e-mail/WhatsApp.

## 5. Contras / custos de adotar uma plataforma

1. **Custo recorrente por documento/mês** — hoje seu custo marginal por assinatura é ~zero; passa a ter mensalidade ou preço por documento.
2. **Dependência de fornecedor (vendor lock-in)** — fluxo de assinatura, links, webhooks e armazenamento passam a depender de um terceiro; migrar depois tem custo.
3. **Dados sensíveis (LGPD) saem do seu ambiente** — PDFs de saúde e dados do paciente trafegam/ficam num terceiro; exige contrato de tratamento de dados e avaliação de risco.
4. **Retrabalho de integração** — refazer o fluxo atual (que já funciona bem: QR Code, terminal, WhatsApp, envio ao Dental Office) para a API do fornecedor.
5. **Menos controle sobre a UX** — hoje você controla 100% da tela de assinatura (canvas, identidade presencial, menor de idade). Plataformas impõem seu próprio fluxo.
6. **Dependência de disponibilidade externa** — uma indisponibilidade do fornecedor pode travar assinaturas.

## 6. Qual é a real necessidade?

**Curto/médio prazo: não é obrigatória.** Para **TCLE e contratos odontológicos entre a clínica e o paciente**, a assinatura **eletrônica simples já tem validade jurídica**, e a sua implementação é mais robusta que a média (hash + carimbo de tempo RFC 3161 + trilha de auditoria + confirmação de identidade + confirmação presencial opcional). Você **não depende** de uma plataforma para ter documentos válidos.

**Quando passa a valer a pena / a ser necessária:**
- Se surgir a exigência de **assinatura qualificada ICP-Brasil** (ex.: receita/prescrição eletrônica) — aí uma plataforma vira o caminho mais rápido.
- Se você quiser **reduzir seu risco probatório** com um terceiro reconhecido em juízo e relatório PAdES padronizado.
- Se quiser **identidade forte** (biometria facial/validação de CPF) sem desenvolver.
- Se o **volume crescer** a ponto de a manutenção/conformidade internas custarem mais que uma assinatura.

## 7. Recomendação

1. **Manter a solução própria como base** — ela é válida e bem construída. Um reforço barato e de alto impacto é **garantir que o carimbo de tempo RFC 3161 esteja sempre ativo** (já implementado, hoje opcional) e documentar a política de evidências.
2. **Se decidir por plataforma, avaliar em modelo de API pay-per-use**, que combina com seu fluxo já existente (você orquestra; a plataforma só assina/carimba):
   - **Autentique** — melhor custo por documento via API (~R$ 0,06/doc + centavos por canal), sandbox gratuito, biometria e ICP-Brasil disponíveis. **Primeira opção a testar.**
   - **Assinadoc** — se preferir preço fixo com documentos ilimitados e API rica (30+ endpoints).
   - **ZapSign** — se o foco for custo baixo + WhatsApp para PME.
   - **TOTVS** — só se for necessária **assinatura qualificada ICP-Brasil** corporativa ou integração com ERP TOTVS.
3. **Caminho híbrido ideal:** manter seu fluxo (QR Code, terminal, identidade presencial, envio ao Dental Office) e **plugar a assinatura qualificada/biometria de uma plataforma via API apenas nos casos que exigirem** — sem jogar fora o que já funciona.

---

## Fontes

- [Lei nº 14.063/2020 — Planalto](https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2020/lei/l14063.htm) · [Cap. II (normas.leg.br)](https://normas.leg.br/?urn=urn%3Alex%3Abr%3Afederal%3Alei%3A2020-09-23%3B14063%21cap2)
- [Gov.br — Saiba mais sobre a assinatura eletrônica](https://www.gov.br/governodigital/pt-br/identidade/assinatura-eletronica/saiba-mais-sobre-a-assinatura-eletronica)
- [DocuSign — Validade da assinatura eletrônica no Brasil](https://www.docusign.com/pt-br/blog/assinatura-eletronica-lei)
- [Jusbrasil — Assinaturas eletrônicas, gov.br e Lei 14.063/2020](https://www.jusbrasil.com.br/artigos/assinaturas-eletronicas-e-digitais-no-brasil-plataforma-govbr-lei-14063-2020-e-validade-judicial/5827838853)
- [ClickSign — Preços](https://www.clicksign.com/preco) · [Tabela comparativa](https://www.clicksign.com/en/tabela-comparativa)
- [ZapSign — Planos (blog)](https://blog.zapsign.com.br/zapsign-planos/)
- [Assinadoc — Planos](https://assinadoc.com/planos) · [Desenvolvedores](https://assinadoc.com/desenvolvedores)
- [TOTVS — Assinatura Eletrônica](https://www.totvs.com/assinatura-eletronica/) · [Ficha técnica](https://produtos.totvs.com/ficha-tecnica/tudo-sobre-o-totvs-assinatura-eletronica/)
- [Autentique — Planos](https://www.autentique.com.br/#plans) · [Preços via API](https://docs.autentique.com.br/api/2/precos-para-uso-via-api)
- [ContraktorSign — Planos e preços](https://contraktorsign.com.br/planos-e-precos/)
- [SuperSign — Preços e planos](https://supersign.com.br/precos-e-planos/) · [Comparativo de plataformas](https://supersign.com.br/blog/plataformas-de-assinatura-eletronica-10-alternativas-supersign/)
- [Simples Dental — Assinatura eletrônica para dentista](https://www.simplesdental.com/blog/assinatura-eletronica-para-dentista/)
- [CFO — Manual do Prontuário do Paciente em Odontologia](https://website.cfo.org.br/wp-content/uploads/2026/03/CFO_Manual_do_Prontuario_Ebook.pdf)
