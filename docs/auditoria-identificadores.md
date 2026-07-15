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

### A-01 · ~~Suíte de testes quebra sem `collectstatic`~~ — **CORRIGIDO**
`manage.py test` (sem `collectstatic` prévio) falhava com
`ValueError: Missing staticfiles manifest entry for '.../...css'` em todos os testes que
renderizam templates com `{% static %}`. Causa: `settings.py` ativava
`whitenoise.storage.CompressedManifestStaticFilesStorage` **também no ambiente de teste**.

**Correção:** o storage com manifesto passou a ser aplicado apenas fora dos testes
(`TESTANDO = "test" in sys.argv[1:2]`, em `abo_goias/settings.py`). Produção e dev seguem com
o manifesto e a **checagem estrita** (erro alto se faltar arquivo); a suíte deixa de depender
de `collectstatic`. **Verificado apagando o diretório `staticfiles/` por completo: 561 testes,
verde.** O passo de validação do README (`manage.py test`) agora funciona num checkout limpo.
Resolve também o backlog B-01/B-18.

### A-02 · Índice não distinguia turma ativa de finalizada — **moderado** (CORRIGIDO na 3.1)
> Correção do achado: uma leitura mais atenta de `eduq.py` mostrou que os dados **já vêm**
> do Eduq — `_turma_ativa()` deriva `ativo` de "Matrículas ativas > 0" e `data_fim` é mapeado
> de "Data de Finalização" (`normalizar_turma`). A afirmação inicial ("ativo nunca vira
> False / Eduq não alimenta") estava **errada**.

O problema real: o `index` filtrava só `ativo=True` e **não expunha** nenhuma distinção
ativa/finalizada nem usava `data_fim`. Com dados reais (sync de 43 turmas), `ativo`
(matrículas) e `data_fim<hoje` **divergem** (ex.: turma com data de término passada mas ainda
com matrículas). Para "ativa vs finalizada" o critério semântico correto é `data_fim`
(curso encerrado). → Resolvido na 3.1 (filtro por `data_fim`), sem precisar tocar no
`eduq_sync.py`.

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

**Fase 3.1 — Identificadores (implementada e verificada no navegador com dados reais do Eduq):**
- **Busca de turma → alunos:** o `<select>` virou um campo de pesquisa com autocomplete
  (HTMX → nova view `buscar_turmas`). Ao selecionar a turma, um fragmento (view `turma_alunos`)
  exibe os alunos sincronizados com cidade/UF (Eduq), datas e "matrículas ativas", além do
  campo oculto `turma` que alimenta a geração.
- **Filtro ativa/finalizada:** chips `.status-seg` (Ativas / Finalizadas / Todas) com contagem,
  no padrão GET. Critério: *finalizada* = `data_fim < hoje`; *ativa* = sem data ou data futura.
- **Dashboard (sidebar):** Turmas sincronizadas · Ativas · Finalizadas · Alunos sincronizados
  · Modelos disponíveis (reusa `.metric-grid`).
- **Geração:** passou a aceitar qualquer turma selecionada (inclusive finalizada), não só ativas.
- Arquivos: `identificadores/{views,urls}.py`, `templates/identificadores/index.html` +
  `partials/_turma_results.html` + `partials/_turma_alunos.html`, `identificadores.css`. HTMX
  carregado por página (`static/js/htmx.min.js`).
- **Testes:** 6 novos casos (busca por texto/situação, contagens do painel, alunos por turma,
  badge finalizada) — suíte de `identificadores` em 9 testes, verde.
- Verificação: busca, seleção, exibição de 23 alunos (turma 50174) e geração de PPTX validadas
  ao vivo (servidor local + Eduq real).
