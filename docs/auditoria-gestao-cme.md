# Auditoria — Gestão de CME (`gestao_cme`)

> Data da auditoria: 2026-07-13 · Ambiente: desenvolvimento (Windows, SQLite local).
> Integrações validadas ao vivo: **Eduq OK** (43 turmas no `sincronizar_eduq --dry-run`).
> **Re-auditado após `git pull` (HEAD `8e91a28`):** templates migraram para a base
> compartilhada (`layouts/painel.html`, `components.css`); a **autenticação saiu para o app
> `contas`** (o `gestao_cme` ainda hospeda o portal `/`); o pull adicionou
> `excluir_movimentacao` (bom modelo de exclusão com modal `data-confirm`).

## 1. Visão geral

Aplicação central de **Central de Material e Esterilização**. Controla cadastros
acadêmicos (turmas/alunos sincronizados do Eduq), materiais, kits, armários/abrigos,
estoques, empréstimos e movimentações (entrada/saída de pacotes). Também serve o **portal**
inicial e as telas de autenticação.

Nota técnica herdada: o app usa `label = "core"` em `apps.py` por compatibilidade com
migrations/fixtures/admin legados (`/admin/core/...`), conforme documentado no README.

Principais telas (rotas em `gestao_cme/urls.py`):
`/` portal · `/gestao-cme/movimentacoes/` · `/gestao-cme/visao-geral/` (dashboard) ·
`/alunos-por-turma/` · `/materiais/` (+ novo/editar) · `/kits/` · `/abrigos/` (+ novo/editar) ·
`/gestao-cme/nova-entrada/` · `/gestao-cme/nova-saida/` · `/emprestimos/` (+ novo/devolver) ·
`/turmas/nova/` · sincronizações Eduq.

## 2. Fluxos testados e resultado

| Fluxo | Método | Resultado |
|---|---|---|
| `manage.py check` | system check | ✅ 0 issues |
| Sincronização Eduq (turmas/alunos) | `sincronizar_eduq --dry-run` | ✅ API responde (43 turmas) |
| Cadastro material / edição | leitura de `MaterialForm`/`MaterialEditForm` + views | ✅ validação de código único OK |
| Registrar entrada (lote de pacotes) | `EntradaForm` + `registrar_entrada` | ✅ gera sequência numérica global; avisa aluno sem abrigo |
| Registrar saída (2 passos) | `registrar_saida` | ✅ lista pendentes por aluno e baixa `retirado=True` |
| Empréstimos (criar/devolver/atrasar) | views + `EmprestimoForm` | ✅ cria itens a partir do kit |
| Busca/paginação nas listagens | `materiais`, `kits`, `emprestimos`, `alunos_por_turma` | ✅ busca por múltiplos campos + paginação 10/pág |
| Suíte automatizada (projeto todo) | `manage.py test` (após `collectstatic`) | ✅ **541 testes, todos passam**. Sem `collectstatic`: erros por **A-01** |

## 3. Bugs / inconsistências encontrados

### A-01 · Suíte de testes quebra sem `collectstatic` — **moderado** (global)
Ver detalhamento em `auditoria-identificadores.md#a-01`. **Pós-pull:** a suíte completa tem
**541 testes** e fica **100% verde após `manage.py collectstatic --noinput`**. Sem
`collectstatic`, os testes que renderizam `{% static %}` quebram com
`Missing staticfiles manifest entry` (manifest storage do whitenoise ativo em teste). Ou
seja: não é bug de produto, é uma pegadinha de fluxo de validação.

### A-05 · Seleção de aluno por `<select>` massivo em entrada/saída/empréstimo — **leve** (escopo 3.2)
`registrar_entrada.html`, `registrar_saida` e `criar_emprestimo.html` renderizam **todos**
os alunos ativos num `<select>` (com `optgroup` por turma). Com o volume real de alunos
(dezenas/centenas por turma × 43 turmas) isso fica pesado e difícil de usar. → feature 3.2
(autocomplete).

### A-06 · Sem indicador de carregamento nas buscas — **leve** (escopo 2.1)
As buscas (`materiais`, `kits`, `emprestimos`, `alunos_por_turma`, movimentações) são forms
GET com reload de página inteira e **nenhum feedback visual** durante o carregamento.

### A-07 · Botões de ação quebrados por vazamento de CSS + alocação — **moderado** (revisto)
> Reclassificado após varredura visual (screenshot do usuário em `cadastrar_turma`). A
> conclusão inicial ("resolvido pelo refactor") estava **errada**.

Formulários com a classe `form-stack` sofrem duas regras de `components.css` que vazam para a
barra de ações `.form-actions`: `.form-stack .button{width:100%}` (primário estica na largura
toda) e `.form-stack .secondary{border:0;background:transparent;color:muted}` ("Cancelar" vira
**link de texto apagado**, empurrado para baixo e à esquerda). Afeta 8 forms do `gestao_cme`
(`cadastrar_aluno`, `cadastrar_turma`, `criar_emprestimo`, `editar_movimentacao`, `form_abrigo`,
`form_material`, `registrar_entrada`, `registrar_saida`). Há também **navegação duplicada**
("Voltar à listagem" no `panel_actions` + "Cancelar" no rodapé, para a mesma URL). Os forms de
`gestao_contratos` usam só `form-stack-wide` (sem `form-stack`) e renderizam certo — padrão de
referência. → Fix CSS-first na Fase 2.2 (ver plano).

### A-08 · Material não tem exclusão pela UI — **leve** (escopo 3.2)
`editar_material` só edita/inativa (`MaterialEditForm` expõe `ativo`). Não há ação de
**excluir** material. `Material` é `PROTECT` por `ItemEmprestimo`, `KitMaterial`,
`EstoqueArmario` → a exclusão precisa tratar `ProtectedError` e informar quantas unidades
estão em empréstimo.

## 4. Necessidades de alteração (identificadas nesta auditoria)

- **Feature 3.2** (planejada): autocomplete de aluno em entrada/saída; botão "atualizar
  alunos" (sync Eduq) nessas telas; exclusão de material com confirmação (irreversível +
  contagem de unidades em empréstimo = `Σ ItemEmprestimo.quantidade` com
  `Emprestimo.status ∈ {EMPRESTADO, ATRASADO}`).
- **Fase 2**: spinner de busca (A-06) e padronização de botões (A-07).
- **A-01**: tornar a suíte verde sem passo manual (backlog B-01, ver Identificadores).

## 5. Backlog de melhorias futuras (não prioritário)

- **B-05**: remover a criação automática do usuário `coordenador.teste` por migration antes
  de produção (já apontado no README) — substituir por management command de dev.
- **B-06**: revisitar o `label = "core"` legado — decidir renomear app label/tabelas/admin
  ou manter permanentemente (já apontado no README).
- **B-07**: `pacote_codigo` da entrada usa `max(codigos numéricos)+n` varrendo **todas** as
  movimentações a cada registro — indexar/otimizar quando o histórico crescer.
- **B-08**: logs estruturados para erros de integração Eduq (já apontado no README).

## 6. Implementado nesta rodada (Fases 2 e 3)

**Fase 2.2 — barra de ações padronizada (A-07):**
- Fix único em `static/css/components.css` escopado a `.form-stack .form-actions` /
  `.form-stack-wide .form-actions`: alinhado à direita, separador acima, botões lado a lado;
  corrigido o vazamento que deixava o primário full-width e o secundário como link fraco.
  Não afeta fragmentos HTMX nem o modal de confirmação.
- Removida a navegação duplicada ("Voltar à listagem"/"Voltar ao histórico" no topo) em
  `cadastrar_aluno`, `cadastrar_turma`, `criar_emprestimo`, `form_abrigo`, `form_material`,
  `registrar_entrada`, `editar_movimentacao` — mantido o "Cancelar" na barra de ações.
  (`registrar_saida` mantém o "Voltar" do topo por não ter Cancelar no rodapé.)
- Verificado no navegador (`cadastrar_turma`) — alinha com o mockup aprovado.
**Fase 2.1 — spinner de busca:** `static/js/app.js` estendido para aplicar `.button.is-loading`
+ desabilitar o botão no submit de `.filter-bar` (todas as listagens com busca) e
`.js-loading-submit`. Verificado no navegador (`materiais`).
- Nota operacional: após o pull foi necessário `manage.py migrate` (migrations `0011`,
  `0015`, `0016`); a `0011` remove o usuário `coordenador.teste`.

**Fase 3.2 — Controle de materiais (implementada e verificada no navegador):**
- **Autocomplete de aluno** em `registrar_entrada` e `registrar_saida` (HTMX → nova view
  `buscar_alunos`, por nome/matrícula; `hidden` com o pk alimenta o form). Na saída, a busca
  usa `pendencias=1` (só alunos com pacotes aguardando retirada) e navega ao selecionar.
- **Botão "Atualizar alunos (Eduq)"** nas duas telas (`.sync-form` → nova view
  `atualizar_alunos_eduq` = `sincronizar_eduq(turmas+alunos)`; loading pela 2.1).
- **Exclusão de material**: nova view `excluir_material` (POST, espelha `excluir_movimentacao`)
  + "Zona de exclusão" no `form_material` (edição) com botão `.danger-button` + `data-confirm`
  informando irreversibilidade e **N unidades em empréstimo** (`Σ ItemEmprestimo.quantidade`
  com status EMPRESTADO/ATRASADO). `ProtectedError` tratado → mensagem clara + redireciona.
- Arquivos: `gestao_cme/{views,urls}.py`, `registrar_entrada.html`, `registrar_saida.html`,
  `form_material.html`, `partials/_aluno_results.html`, `static/css/components.css`
  (`.search-results`/`.selected-chip`). **6 testes novos** (suíte `gestao_cme` 55/55 verde).
- Verificação ao vivo: busca+seleção de aluno, POST de entrada, filtro de pendências na saída,
  exclusão de material livre (OK) e bloqueio de material em empréstimo (ProtectedError).
- Backlog (novo): a "Atualizar alunos" roda o sync do Eduq **síncrono** no request (pode ser
  lento com muitas turmas) → mover para rotina assíncrona (Celery) — mesmo ponto do A-03.
