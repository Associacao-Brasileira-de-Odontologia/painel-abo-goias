# Auditoria — Portal, Contas (autenticação/acesso) e Mensageria (Z-API)

> Data: 2026-07-13 · **Re-auditado após `git pull` (HEAD `8e91a28`)**. O refactor mudou
> substancialmente esta área: `contas` deixou de ser diretório órfão e passou a ser o **app
> de autenticação e solicitação de acesso**; `mensageria` passou a ser o **pacote Z-API de
> WhatsApp** (com código-fonte). Os achados anteriores A-13/A-15 (apps órfãs / `.env`) foram
> **revistos** abaixo.

## 1. Visão geral

- **Portal** (`/`, `gestao_cme.views.portal`): página inicial com acesso aos sistemas,
  estatísticas e feed de atividade. Renderiza sob a nova base compartilhada
  (`templates/base.html`).
- **`contas`** (app registrado em `INSTALLED_APPS`): centraliza **login/logout, reset e troca
  de senha** (movidos do `gestao_cme`) e adiciona um **fluxo de solicitação de acesso** —
  `SolicitacaoCadastro` (status pendente/aprovado/rejeitado, revisor, usuário criado),
  `views.solicitar_acesso`/`perfil`, e e-mails (`emails.py`:
  `notificar_admin_nova_solicitacao`, `confirmar_recebimento_solicitacao`,
  `notificar_usuario_rejeitado`). Templates de auth em `abo-goias/*/templates/auth/`.
- **`mensageria`** (pacote compartilhado, **não** é um Django app em `INSTALLED_APPS`):
  cliente **Z-API** de WhatsApp (`zapi.py`, `provider.py`, `base.py`, `serializers.py`,
  `validators.py`, `utils.py`, `exceptions.py`). Usado pela nova feature de cobrança de
  `gestao_lab` e pelo envio de `gestao_contratos`.
- **Design system compartilhado**: `static/css/{tokens,base,components,portal,auth}.css` +
  `static/js/app.js` (modal `data-confirm`, dropdown de usuário, dispensa de toasts, loading
  de `.sync-form`) + `templates/{base.html, layouts/painel.html, partials/*}` +
  páginas de erro `403/404/500`.
- **Healthcheck**: `/healthz/` (Railway).

`INSTALLED_APPS`: `contas`, `gestao_cme`, `gestao_lab`, `gestao_contratos`, `identificadores`.

## 2. Fluxos testados e resultado

| Fluxo | Método | Resultado |
|---|---|---|
| `manage.py check` | system check | ✅ 0 issues |
| Login/logout/reset/troca de senha | `contas/urls.py` (auth views do Django) | ✅ rotas e templates configurados |
| Solicitação de acesso + e-mails | `contas/views.py` + `emails.py` + `SolicitacaoCadastro` | ✅ fluxo presente (cobrir com teste manual de envio) |
| Portal `/` | `views.portal` + `portal.html` | ✅ renderiza sob a nova base |
| Modal de confirmação global | `partials/confirm_dialog.html` + `app.js` (`data-confirm`) | ✅ padrão reutilizável ativo |
| Suíte automatizada (projeto todo) | `manage.py test` (após `collectstatic`) | ✅ **541 testes, todos passam** |

## 3. Bugs / inconsistências encontrados

### A-13 · ~~Apps órfãs `contas`/`mensageria`~~ — **RESOLVIDO pelo pull**
Ambos passaram a ter código-fonte: `contas` é app de autenticação/acesso; `mensageria` é o
pacote Z-API. Achado anterior **encerrado** — não há mais apps órfãs.

### A-14 · ~~Arquivo lixo `abo-goias/=4.0`~~ — **RESOLVIDO pelo pull**
Era saída de um `pip install` capturada por engano num redirecionamento de shell. **Verificado
pós-pull:** não está mais rastreado pelo git nem existe no disco — foi removido em algum dos 47
commits. Achado encerrado.

### A-15 · `.env` com credenciais — **OK, sem ação** (verificado)
`.gitignore` ignora `.env`/`.env.*` e o `git ls-files` confirma que **não está versionado**.
Sem vazamento. Mantido como confirmação positiva.

### A-01 · Suíte depende de `collectstatic` — **moderado** (global)
`ManifestStaticFilesStorage` (whitenoise) ativo em teste (`settings.py`), sem manifesto sem
`collectstatic` → `{% static %}` quebra. Afeta toda a suíte. Detalhe em
`auditoria-identificadores.md#a-01`.

## 4. Necessidades de alteração (identificadas nesta auditoria)

- **A-14**: ✅ resolvido pelo pull (arquivo `=4.0` removido).
- **A-01**: storage de estáticos sem manifesto em teste (backlog B-18).
- **Fase 2**: a padronização de botões/spinner também percorre portal e telas de auth
  (`contas`), reusando `components.css`/`app.js`.

## 5. Backlog de melhorias futuras (não prioritário)

- **B-16**: unificação de tokens de design já **realizada** pelo refactor (`tokens.css`
  compartilhado). `gestao_contratos`/`identificadores` mantêm CSS próprio só para o que é
  específico — ok.
- **B-18**: `settings` de teste dedicado (resolve A-01) — permite storage sem manifesto e
  fixtures de teste.
- **B-19** (novo): cobrir o fluxo de `solicitar_acesso` (criação de `SolicitacaoCadastro`,
  e-mails, aprovação/rejeição) com testes automatizados, se ainda não coberto.

## 6. Implementado nesta rodada (Fases 2 e 3)

_A preencher — a Fase 2 (spinner de busca / conformidade de botões) afeta portal e auth._
