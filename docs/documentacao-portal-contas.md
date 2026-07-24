# Documentação — Portal, Contas (autenticação/acesso) e Mensageria (Z-API)

> Documento único e atual desta área. Consolida a auditoria original (2026-07-13,
> re-auditada após um refactor grande) e a rodada de padronização de linguagem feita
> desde então, organizado em duas partes: o que já foi documentado e solucionado, e o
> que ainda está pendente. Ver também
> [`jornada-portal-acesso.md`](jornada-portal-acesso.md) para a experiência do usuário.

## 1. Visão geral

- **Portal** (`/`, `gestao_cme.views.portal`): página inicial com acesso aos sistemas,
  estatísticas e feed de atividade, sob a base compartilhada (`templates/base.html`).
- **`contas`** (app registrado em `INSTALLED_APPS`): centraliza login/logout, reset e
  troca de senha, e o fluxo de solicitação de acesso — `SolicitacaoCadastro`
  (pendente/aprovado/rejeitado, revisor, usuário criado), `views.solicitar_acesso`/
  `perfil`, e e-mails (`emails.py`: `notificar_admin_nova_solicitacao`,
  `confirmar_recebimento_solicitacao`, `notificar_usuario_rejeitado`).
- **`mensageria`** (pacote compartilhado, **não** é um Django app em `INSTALLED_APPS`):
  cliente Z-API de WhatsApp (`zapi.py`, `provider.py`, `base.py`, `serializers.py`,
  `validators.py`, `utils.py`, `exceptions.py`). Usado pela cobrança automática do
  `gestao_lab` e pelo envio de contratos assinados do `gestao_contratos`.
- **Design system compartilhado**: `static/css/{tokens,base,components,portal,auth}.css`
  + `static/js/app.js` (modal `data-confirm`, dropdown de usuário, loading de
  `.sync-form`) + `templates/{base.html, layouts/painel.html, partials/*}` + páginas de
  erro 403/404/500.
- **Healthcheck**: `/healthz/` (Railway).

`INSTALLED_APPS`: `contas`, `gestao_cme`, `gestao_lab`, `gestao_contratos`,
`identificadores`.

## 2. O que foi documentado e solucionado

### 2.1 Auditoria inicial e refactor (2026-07-13)

Um refactor entre a primeira leitura e a re-auditoria mudou substancialmente esta área —
`contas` deixou de ser um diretório órfão e passou a ser o app de autenticação e
solicitação de acesso; `mensageria` passou a ser o pacote Z-API com código-fonte próprio.
Achados fechados nessa auditoria:

- **Apps órfãs `contas`/`mensageria`** — resolvidas pelo refactor (ambas passaram a ter
  código-fonte e propósito claro).
- **Arquivo lixo `abo-goias/=4.0`** (saída de `pip install` capturada por engano num
  redirecionamento de shell) — removido.
- **`.env` com credenciais** — verificado: `.gitignore` ignora `.env`/`.env.*`, e
  `git ls-files` confirma que não está versionado. Sem vazamento.
- **Suíte de testes dependia de `collectstatic`** — mesma correção aplicada em
  `abo_goias/settings.py` (ver `documentacao-identificadores.md`); suíte completa (581
  testes) verde.
- Fluxos testados na época (`manage.py check`, login/logout/reset/troca de senha,
  solicitação de acesso + e-mails, portal, modal de confirmação global, suíte completa) —
  todos ✅.

### 2.2 Padronização de linguagem operacional (implementado)

A UI expunha a arquitetura interna nas telas de operação ("Buscar no Dental Office",
"Sincronizar com Dental Office (Eduq)", seção de menu "Dental Office / EDUQ") — o
operador só precisa achar a pessoa, não saber de onde vem o dado. Regra adotada e
aplicada em todas as telas operacionais (menu, busca, listagens, mensagens de erro):

- Telas de operação usam linguagem neutra: "Importar paciente" → "Procurar paciente";
  "Sincronizar com Dental Office" → "Atualizar lista"; "Atualizar alunos (Eduq)" →
  "Atualizar lista de alunos"; menu "Dental Office / EDUQ" → "Pessoas".
- A noção de atualização é preservada, só a palavra muda: "Última sincronização" →
  "Última atualização"; "Histórico de sincronizações" → "Histórico de atualizações".
- Mensagens de erro neutralizadas para o operador ("Erro na API Dental Office: X" → "Não
  foi possível atualizar a lista agora: X"), mantendo o detalhe técnico nos logs.
- Mantido como está, deliberadamente: `/admin/` (área técnica) e os *docstrings* do
  código — ali nomear Eduq/Dental Office é correto e necessário para quem dá manutenção.

## 3. O que está pendente

- **Testes automatizados do fluxo de solicitação de acesso** — criação de
  `SolicitacaoCadastro`, disparo de e-mails, aprovação/rejeição — cobertura ainda não
  confirmada como completa.
- **Settings de teste dedicado** — permitiria isolar storage sem manifesto e fixtures de
  teste do restante da configuração de produção; hoje resolvido de forma pontual
  (variável `TESTANDO`), não como uma configuração de teste separada.
- **Limitação assumida, não um bug:** a padronização de linguagem (2.2) é cosmética — o
  botão "Procurar em todos os cadastros" continua levando ~9s e importando todos os
  resultados de uma vez; otimizar essa busca é um item à parte, não coberto aqui.
- Nenhuma diferenciação de permissão por papel/grupo existe hoje — qualquer colaborador
  com conta aprovada acessa todas as ferramentas do Painel (decisão de negócio já
  registrada, não uma pendência técnica).

## 4. Documentos substituídos por este arquivo

Este documento consolida e substitui `auditoria-portal-contas-mensageria.md`
(2026-07-13), cujo conteúdo foi incorporado acima.
