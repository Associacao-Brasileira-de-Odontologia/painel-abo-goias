# Auditoria — Identificador de Bancadas (`identificadores`)

> Data da auditoria: 2026-07-13 · Ambiente: desenvolvimento (Windows, SQLite local).
> Integrações validadas ao vivo: **Eduq OK** (43 turmas retornadas no `sincronizar_eduq --dry-run`).
> **Re-auditado após `git pull` (HEAD `8e91a28`):** `index.html` migrou para
> `layouts/painel.html`, mas a lógica é a mesma (turma `<select>` só de ativas, alunos não
> exibidos, dashboard com 2 cards) → a feature 3.1 permanece integralmente necessária. O novo
> `components.css` já traz `.status-seg` (chips de status com contagem) reutilizável para o
> filtro ativa/finalizada, e `.metric-grid`/`.kpi-grid` para o dashboard.

## 1. Visão geral

Aplicação que gera arquivos **PPTX de identificadores de bancada** por turma. O fluxo
atual (`identificadores/views.py::index`):

1. Lista turmas (`Turma.objects.exclude(origem=EXEMPLO).filter(ativo=True)`) num `<select>`.
2. Lista modelos PPTX disponíveis (`services/modelos.py::listar_modelos`).
3. No POST, valida turma + modelo, tenta atualizar a localização dos alunos sem
   cidade/UF via Eduq (`sincronizar_localizacao_alunos_turma`), gera o arquivo
   (`gerar_arquivo_identificadores`) e oferece download (`baixar`).

Há ainda uma ação de **sincronizar turmas e alunos** (`views.sincronizar`) que chama
`sincronizar_eduq(sincronizar_turmas=True, sincronizar_alunos=True)`.

A app reaproveita o design system compartilhado (`{% extends "layouts/painel.html" %}`,
`components.css`) e um CSS próprio (`static/identificadores/css/identificadores.css`).

## 2. Fluxos testados e resultado

| Fluxo | Método | Resultado |
|---|---|---|
| `manage.py check` | system check | ✅ 0 issues |
| Sincronização Eduq (turmas) | `sincronizar_eduq --somente-turmas --dry-run` | ✅ 43 turmas retornadas pela API (0 no banco local hoje) |
| Seleção turma+modelo → geração PPTX | leitura de código + testes da app | ✅ lógica coberta por `identificadores/tests.py` |
| Suíte automatizada | `manage.py test` (após `collectstatic`) | ✅ projeto todo **541 testes, verde**; sem `collectstatic` falha por **A-01** |

Observação factual: o banco local está **vazio de turmas/alunos** (0 registros), então o
fluxo de geração só é exercível após uma sincronização real com o Eduq.

## 3. Bugs / inconsistências encontrados

### A-01 · Suíte de testes quebra sem `collectstatic` — **moderado** (afeta todos os apps)
`manage.py test` (sem `collectstatic` prévio) falha com
`ValueError: Missing staticfiles manifest entry for '.../...css'` em todos os testes que
renderizam templates com `{% static %}`. Causa: `settings.py` ativa
`whitenoise.storage.CompressedManifestStaticFilesStorage` **também no ambiente de teste**.
**Pós-pull, com `collectstatic --noinput` antes, a suíte completa passa: 541 testes, verde.**
O README indica `manage.py test` como passo de validação sem mencionar essa dependência.
→ Ver "Necessidades de alteração" / backlog B-01.

### A-02 · `Turma.ativo` nunca reflete a realidade do Eduq — **moderado**
`ModeloBase.ativo` tem default `True`; a sincronização (`eduq_sync.py`) cria turmas com
`ativo=True` e **preserva** o valor em atualizações (`eduq_sync.py:137`). A "Data de
Finalização"/"Matrículas Ativas" retornadas pelo Eduq **não** alimentam esse flag. Como o
`index` filtra `ativo=True`, a tela hoje lista "todas as turmas não desativadas
manualmente", **não** "turmas realmente ativas". `data_fim` também não é usado para
distinguir turma finalizada. → base para a feature 3.1 (filtro ativa/finalizada).

### A-03 · Sincronização Eduq acoplada ao request de geração — **leve**
Ao gerar o PPTX, se houver alunos sem cidade/UF, a view faz uma chamada externa síncrona
ao Eduq (`sincronizar_localizacao_alunos_turma`) dentro do request. Uma indisponibilidade
do Eduq atrasa/gera warning no fluxo de download. Já registrado como ponto de atenção no
próprio README ("separar sincronização e geração"). Severidade leve porque há `try/except`
que não bloqueia a geração.

### A-04 · Campo de turma é `<select>`, não busca — **leve** (é o escopo da feature 3.1)
O brief pede um campo de **pesquisa** de turma que, ao selecionar, exiba os alunos e as
infos do Eduq. Hoje é um `<select>` simples e os alunos da turma **nunca são exibidos** na
tela (só usados internamente na geração).

## 4. Necessidades de alteração (identificadas nesta auditoria)

- **Feature 3.1** (planejada): campo de busca de turma → exibir alunos + infos do Eduq;
  filtro ativa/finalizada (usar `data_fim < hoje`); painel com total de turmas
  sincronizadas / ativas / inativas / total de alunos.
- **A-02**: passar a derivar `ativo`/`data_fim` da finalização do Eduq durante a sync
  (corrige a base do filtro).
- **A-01**: tornar a suíte verde sem passo manual (ver backlog B-01).

## 5. Backlog de melhorias futuras (não prioritário)

- **B-01**: em `settings.py`, usar storage de estáticos **sem manifesto** quando
  `DEBUG`/testes (ou `StaticLiveServerTestCase`), evitando a dependência de `collectstatic`
  para rodar a suíte. Alternativa: um `settings` de teste dedicado.
- **B-02**: mover a sincronização de localização para rotina assíncrona (Celery, já
  presente no projeto para `gestao_contratos`) — desacoplar do request de geração (A-03).
- **B-03**: cache/lista paginada de turmas quando o volume crescer (hoje 43, tende a subir).
- **B-04**: permitir gerar identificadores para turmas finalizadas (histórico), respeitando
  o novo filtro.

## 6. Implementado nesta rodada (Fases 2 e 3)

_A preencher ao concluir as fases 2 e 3._
