# Ajustes Visuais — Gestão de CME (rodada 2)

> **Documento histórico.** Desde 2026-07-21, o estado atual do módulo `gestao_cme` está
> consolidado em [`casos-de-uso-gestao-cme.md`](casos-de-uso-gestao-cme.md) — ver §11.2
> para o resumo destes 4 itens e como foram resolvidos (todos implementados). Mantido
> aqui como registro histórico da rodada — não reflete o comportamento atual das telas.

> Data: 2026-07-21 · Complementa `docs/avaliacao-visual-gestao-cme.md` (rodada 1, 13 itens).
> Metodologia: mesma da rodada 1 — aplicação executada localmente (Django dev server,
> SQLite) com dados sintéticos, navegada com Chromium via Playwright autenticado como
> superusuário; cada achado é confirmado no CSS/template para apontar a causa exata.
>
> Fluxo de implementação: **um item por vez** — implementar, testar (suíte + verificação
> visual), commitar, enviar e aguardar a avaliação antes de seguir para o próximo, igual à
> rodada 1.

---

## Resumo executivo

| # | Ajuste | Tipo | Onde | Estado atual |
|---|---|---|---|---|
| 1 | Remover o filtro por turma da tela Alunos por turma | Remoção | Alunos por turma | A implementar |
| 2 | Rótulo de contagem só aparece quando o filtro correspondente está ativo | Consistência | Abrigos, Materiais, Kits | **Já implementado** (commit `d6f1f2a`) — a implementação será verificar/confirmar |
| 3 | Navegação de listagem com atalho para a primeira e a última página | Navegação | Todas as listagens paginadas | **Já implementado** (`partials/paginacao.html`) — verificar e, se preciso, tornar mais explícito |
| 4 | Painel do filtro de período sobrepõe componentes e escapa da borda ao abrir | Correção de bug | Visão Geral, Movimentações, Empréstimos | A corrigir |

---

## 1 · Remover o filtro por turma da tela "Alunos por turma"

**O que se vê:** a barra de filtros de Alunos por turma tem, além da busca textual e do
filtro de status (ativos/inativos/todos), um terceiro controle: um `<select name="turma">`
com todas as turmas cadastradas. A busca textual já cobre turma (o campo pesquisa por nome
e código da turma, ver `views.alunos_por_turma`), então o dropdown dedicado é redundante e
é o que mais "engorda" a barra de filtros — inclusive é a causa de a barra dessa tela
precisar quebrar linha (ver rodada 1, item 13).

**O que fazer:**
- Remover o `<select name="turma">` da barra de filtros (`alunos_por_turma.html`).
- Remover o chip removível de "Turma" da linha de chips e o parâmetro `turma` dos `href`
  dos demais chips.
- Remover a leitura de `turma_id`/`turma_selecionada` e o `filter(turma_id=...)` da view,
  além das variáveis de contexto `turmas`/`turma_id` que só serviam ao dropdown (confirmar
  que `turmas` não é usado para nenhuma outra finalidade no template antes de remover).
- Ajustar os testes que dependam do parâmetro `turma`, se houver.

**Onde:** `gestao_cme/templates/gestao_cme/alunos_por_turma.html`, `gestao_cme/views.py`
(`alunos_por_turma`).

---

## 2 · Rótulo de contagem só aparece quando o filtro está ativo (Abrigos, Materiais, Kits)

**O que fazer:** aplicar às telas de Abrigos, Materiais e Kits o mesmo conceito já usado em
Movimentações (rodada 1, item 12): os rótulos de contagem ao lado de "N resultados" (ex.:
"N ocupados", "N disponíveis", "N de M ativos") só devem aparecer quando o filtro
correspondente estiver selecionado, com a cor do respectivo badge da coluna de status.

**Estado atual:** este ajuste **já foi implementado** no commit `d6f1f2a` ("Rótulo de
contagem só aparece com filtro ativo em Abrigos, Materiais e Kits"), que inclusive
adicionou o filtro de Status (Ativo/Inativo) que faltava em Kits. A etapa de implementação
deste item consistirá em **verificar** o comportamento nas três telas e confirmar que está
conforme o esperado. Caso a alteração não esteja visível no ambiente local, é sinal de que
o commit ainda não foi incorporado localmente (pull/rebuild de estáticos) — o mesmo
diagnóstico do item 13 da rodada 1.

**Onde:** `armarios.html`, `materiais.html`, `kits.html`, `gestao_cme/views.py`.

---

## 3 · Listagem com atalho para a primeira e a última página

**O que fazer:** nas listagens paginadas, oferecer, além de "Anterior/Próxima", um atalho
direto para a **primeira** e a **última** página.

**Estado atual:** o partial de paginação (`templates/partials/paginacao.html`), usado por
todas as listagens do módulo, **já traz** esses atalhos: o botão `«` navega para `page=1`
(primeira página) e o botão `»` navega para `page={{ num_pages }}` (última página), ambos
com `title`/`aria-label` "Primeira página"/"Última página" e ficando desabilitados quando
não aplicável. A etapa de implementação consistirá em **verificar** que os atalhos aparecem
e funcionam em todas as listagens. Se a intenção for deixá-los mais evidentes (rótulos
textuais "Primeira"/"Última" em vez de só os símbolos `«`/`»`), isso pode ser feito como um
refinamento — a confirmar na avaliação.

**Onde:** `templates/partials/paginacao.html` (compartilhado por todas as listagens).

---

## 4 · Painel do filtro de período sobrepõe componentes e escapa da borda da tabela

**O que se vê:** ao clicar em "Período" para abrir o filtro de datas (Visão Geral,
Movimentações e Empréstimos), o painel suspenso:
1. **sobrepõe** os componentes logo abaixo da barra de filtros (chips e cabeçalho/linhas da
   tabela); e
2. **ultrapassa a borda direita** do painel de resultados quando o botão "Período" está
   posicionado mais à direita da barra de filtros.

**Causa (confirmada no CSS):** `.filter-period-panel` reusa `.dropdown-panel`
(`position: absolute`) mas sobrescreve a ancoragem para `left: 0; right: auto` e usa
`min-width: max-content`. Como o botão "Período" fica perto do lado direito da barra
(logo antes de "Buscar"), o painel — ancorado pela borda esquerda e com largura de conteúdo
(dois campos de data + "Aplicar" lado a lado) — cresce para a direita e escapa da borda do
painel de resultados. Sendo `position: absolute`, ele também passa por cima do conteúdo
abaixo (comportamento de dropdown, mas que fica visualmente quebrado combinado com o
transbordo lateral).

**O que fazer:**
- Reancorar o painel para que ele permaneça **dentro dos limites** do painel de resultados
  — por exemplo, alinhar pela direita (`right: 0; left: auto`) para que cresça para a
  esquerda a partir do botão "Período", ou empilhar os campos de data verticalmente para
  reduzir a largura.
- Garantir `z-index` acima da tabela e um leve espaçamento para que a sobreposição não pareça
  um defeito.
- Verificar o comportamento nas três telas e em telas estreitas (mobile), onde a barra de
  filtros quebra em mais linhas.

**Onde:** `static/css/components.css` (`.filter-period`, `.filter-period-panel`),
`gestao_cme/templates/gestao_cme/partials/filtro_periodo.html`.

---

## Observação sobre o ambiente local

Dois dos quatro itens (2 e 3) já constam no código versionado da branch
`claude/django-esterilizacao-casos-uso-u34g71`. Se não estiverem visíveis na máquina local,
o mais provável é que faltou incorporar os commits mais recentes (`git pull`) ou recoletar
os arquivos estáticos (`python manage.py collectstatic`) / limpar o cache do navegador —
mesmo diagnóstico levantado ao final da rodada 1 (item 13).
