# Documentação — Gerador de Contratos e Termos de Consentimento (`gestao_contratos`)

> Documento único e atual do módulo `gestao_contratos`. Consolida a auditoria geral, a
> auditoria de segurança de backend e as rodadas de melhoria feitas até aqui, organizado
> em duas partes: o que já foi documentado e solucionado, e o que ainda está pendente
> (inclusive achados de segurança ainda não corrigidos, verificados diretamente no
> código nesta consolidação). Ver também
> [`jornada-gestao-contratos.md`](jornada-gestao-contratos.md) para a experiência do
> usuário e `Ferramentas-Painel-ABO-Goias.docx` para a base jurídica da assinatura em
> linguagem não técnica.

## 1. Visão geral

Gera termos de consentimento (DOCX + PDF, 100% em código via `python-docx`/`reportlab`),
conduz assinatura remota (QR Code no celular do paciente ou terminal dedicado), com
verificação de identidade (data de nascimento do paciente ou CPF do responsável legal),
confirmação presencial opcional do colaborador, carimbo de tempo RFC 3161 e envio
assíncrono (Celery) ao Dental Office e por WhatsApp (`mensageria`/Z-API).

Modelos: `ContratoGerado`, `SessaoAssinatura`, `TerminalAssinatura`, `EventoContrato`.
Serviços: `documentos`, `assinatura`, `assinatura_pdf`, `carimbo_tempo`, `checklist`,
`envio`, `envio_dental`. Tasks Celery: envio Dental (retry), WhatsApp, carimbo de tempo,
expiração de sessões (Beat). É a app mais madura do projeto — README documenta o fluxo
em detalhe e cita cobertura ampla de testes na lógica de negócio.

## 2. O que foi documentado e solucionado

### 2.1 Auditoria geral (2026-07-13)

Fluxos testados e validados: `manage.py check` limpo, suíte completa (581 testes,
depois ampliada), verificação de identidade (bloqueio após 5 tentativas), validação da
imagem de assinatura (rejeita não-PNG, tamanho fora dos limites, base64 inválido),
terminal dedicado (polling/fragmento/404 em token inválido). A suíte de testes deixou de
depender de `collectstatic` (mesma correção aplicada em todas as apps do Painel).

### 2.2 Melhorias implementadas (2026-07-15)

- **Nomenclatura dos sistemas integrados** — "Dental" padronizado para "Dental Office"
  nos textos da interface.
- **Listagem única de busca de paciente** — antes eram duas tabelas (locais + Dental
  Office); unificada em uma só, com a ação por linha distinguindo "Gerar contrato"
  (paciente local) de "Importar e gerar" (Dental Office ainda não importado).
- **Campo "Origem" removido da listagem** — substituído por data de nascimento e CPF
  (quando disponíveis) como identificação do paciente.
- **"Validar documento" abre em nova guia.**
- **Tipografia padronizada** nas telas de staff (Fraunces/IBM Plex Mono → fontes do
  design system compartilhado).
- **Notificação de falha no envio ao Dental Office** — painel dedicado
  ("Envios ao Dental Office") lista contratos assinados com envio em erro ou pendente,
  com botão de reenviar por linha; alerta proativo no Portal contando quantos contratos
  assinados ainda não foram enviados.
- **Carimbo de tempo antes do envio automático (B-14)** — antes, o envio ao Dental
  Office e por WhatsApp podia sair sem o carimbo por ordenação assíncrona (as três
  tarefas Celery disparavam em paralelo). Corrigido: com TSA configurada, o envio ao
  Dental/WhatsApp passou a ser encadeado **depois** da tarefa de carimbo de tempo
  concluir — **verificado no código atual** (`agendar_envios_automaticos` é chamado a
  partir de `solicitar_carimbo_tempo_task`, em `gestao_contratos/tasks.py`).

## 3. O que está pendente

### 3.1 Achados de segurança do backend (auditoria de 2026-07-15)

A auditoria de backend classificou os achados por severidade. Além do carimbo de
tempo (CT-01, confirmado corrigido em 2.2), **C-01, A-01 e A-02 foram corrigidos em
2026-07-28** nas etapas 1 e 2 do plano de limpeza (ver `plano-limpeza-codigo.md`);
os demais seguem pendentes. A verificação abaixo foi feita lendo o código atual, não
apenas o documento original.

| # | Achado | Severidade | Status verificado |
|---|---|---|---|
| C-01 | PDF do contrato (`assinar/<token>/pdf/`) é entregue **sem checar identidade confirmada** — quem obtém o link/QR Code baixa o termo completo (CPF, RG, endereço, dados de saúde) sem passar pela verificação | Crítico | **Corrigido** (2026-07-28) — `assinar_pdf_view` exige `identidade_confirmada_em` e responde 404 sem ela |
| A-01 | Open redirect pelo parâmetro `next` (22 pontos no levantamento completo, 3 apps): oito sem validação nenhuma, os demais só checam `startswith("/")` — que aceita `//host` (URL protocolo-relativa) | Alto | **Corrigido** (2026-07-28) — `comum.http.destino_seguro` valida com `url_has_allowed_host_and_scheme` nos 22 pontos |
| A-02 | IP gravado no PDF assinado (rodapé + auditoria) é forjável: `_ip_do_request` usa o **primeiro** valor de `X-Forwarded-For`, que é enviado pelo próprio cliente | Alto | **Corrigido** (2026-07-28) — passa a ler a entrada acrescentada pelo último proxy confiável (`PROXIES_CONFIAVEIS`) |
| CT-01 | Cópia arquivada no Dental Office/WhatsApp podia sair sem o carimbo de tempo (ordenação assíncrona) | — | **Corrigido** (ver 2.2) |
| CT-02 | Falha ao embutir o carimbo é silenciosa — o status marca "concluído" mesmo sem o carimbo entrar no PDF, e a UI não oferece botão de retentar nesse caso | Médio/Alto | **Pendente** |
| CT-03 | Re-carimbar um contrato já carimbado invalida a cópia anterior já distribuída (ela passa a ser reportada como não autêntica na validação pública) | Médio/Alto | **Pendente** |
| CT-04 | O carimbo de tempo não aparece no texto impresso do documento, só como anexo invisível | Baixo | **Pendente** |
| M-01 | Rate-limit das rotas públicas usa cache por processo (`LocMemCache`) — enfraquece com múltiplos workers e some a cada deploy | Médio | **Pendente** — `settings.py` não define `CACHES` |
| M-02 | Ao embutir o carimbo, o PDF assinado é apagado do storage antes de o novo ser gravado — uma falha no meio perde o documento | Médio | **Pendente** |
| M-03 | Cálculo de `versao` do contrato tem corrida (sem `UniqueConstraint`) | Médio | **Pendente** |
| M-04 | Nenhuma view de staff escopa por usuário — qualquer conta autenticada acessa qualquer contrato pelo `pk` na URL | Médio (decisão de negócio) | **Pendente** — pode ser intencional (equipe única), mas nunca foi confirmado explicitamente |
| M-05 | Geração de contrato (DOCX + PDF + registro) sem `transaction.atomic` | Médio | **Pendente** |
| B-01 a B-05 | Itens de baixo risco/higiene (reuso de imagem após `verify()`, comparação de CPF não constant-time, `IndexError` em nome vazio, `max_age` do token dessincronizado da validade real da sessão, efeito colateral escondido em `sessao_ativa()`) | Baixo | **Pendentes** |

**Prioridade sugerida pela auditoria original** (mantida): C-01 e A-01 primeiro (baixo
esforço, cobrem os impactos mais sérios — exposição de dados pessoais e phishing),
seguidos por CT-03, CT-02, CT-01 (já corrigido), A-02, M-02, M-01, M-04. Desses,
C-01, A-01, A-02 e CT-01 já estão corrigidos — **a fila agora começa em CT-03 e
CT-02** (carimbo de tempo), os de maior severidade ainda abertos.

### 3.2 Decisões de negócio pendentes

- **Colunas "realmente necessárias"** na listagem unificada de pacientes — confirmar o
  conjunto final (hoje: nome, nascimento, celular, ação).
- **Identificador preferido na listagem** — CPF ou data de nascimento? Para pacientes do
  Dental Office ainda não importados, o endpoint de listagem não traz CPF/nascimento
  (só o de detalhe) — exigir CPF implicaria uma chamada extra por linha, com custo de
  performance a avaliar.
- **Padronizar tipografia também nas telas públicas de assinatura** — hoje só as telas
  de staff foram migradas para o design system; `assinatura.css` ainda usa
  Fraunces/IBM Plex Mono, mantido deliberadamente sem alteração por ser uma tela de UX
  própria (canvas de assinatura) que a auditoria recomendou não tocar sem validação
  dedicada.
- **Prazo de retenção da auditoria e contato do DPO** — pendentes de preenchimento na
  política de privacidade; avaliar migrar a TSA de `freetsa.org` (não credenciada) para
  uma TSA credenciada pela ICP-Brasil.
- **Cobrir curatela de maiores incapazes** no checklist de responsável legal (hoje cobre
  menores de idade).

### 3.3 Pendências operacionais (infraestrutura, fora do código)

- Worker + beat do Celery e Redis em produção (necessários para envio assíncrono,
  carimbo de tempo e expiração de sessões).
- Verificação da conta WhatsApp Business e template de mensagem aprovado.
- Volume persistente para os arquivos gerados — o filesystem do Railway é efêmero, e
  `DJANGO_MEDIA_ROOT` precisa apontar para um volume persistente.

## 4. Documentos substituídos por este arquivo

Este documento consolida e substitui `auditoria-gestao-contratos.md` (2026-07-13) e
`auditoria-backend-gestao-contratos-2026-07.md` (2026-07-15), além da seção "Sistema de
Gestão de Contratos" de `melhorias-cme-contratos-2026-07.md` (2026-07-15). O conteúdo
relevante de todos foi incorporado acima; os achados de segurança foram reverificados
diretamente no código atual (não apenas reproduzidos do texto original).
