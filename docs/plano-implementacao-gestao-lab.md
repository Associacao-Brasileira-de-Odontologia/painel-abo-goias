# Plano de Implementação — Gestão de Pedidos de Materiais em Laboratório (`gestao_lab`)

> Data: 2026-07-21 · Complementa `docs/casos-de-uso-gestao-lab.md` e
> `docs/plano-correcao-status-tipos-gestao-lab.md`.
> Este documento cruza os 11 itens recebidos com o que já estava documentado, resolve as
> duas confirmações pendentes e propõe a sequência de implementação (um item por vez:
> implementar, testar, commitar, enviar, aguardar aprovação — mesma disciplina já usada
> no CME).
> **Progresso:** todos os 11 itens concluídos. Item 4 implementado (commit `a4077e5`);
> item 5 fechado sem código; itens 7, 6/8, 3+2, 1, 9, 10 e 11 implementados — ver §4.

---

## 1 · Confirmações recebidas (itens 4 e 5)

### Item 4 — Status do pedido → **confirmado, sem alteração ao plano já proposto**

Sua confirmação bate exatamente com a correção já detalhada em
`plano-correcao-status-tipos-gestao-lab.md` (Ponto 1): 4 categorias exatas —
**Em dia / Atrasado / Entregue-não-faturado / Concluído** —, eliminando "A confirmar"
como status separado (passa a contar como "Em dia"). Nenhum ajuste no plano técnico já
escrito; ele está pronto para implementação.

### Item 5 — Moldagem → **decisão diferente da que eu havia levantado; anotado**

Isso muda minha recomendação anterior. Eu tinha colocado duas opções (A: campo
`tipo_servico` estruturado; B: generalizar `Moldagem`). Sua resposta descarta **as duas**:

- `Moldagem` continua exatamente como está — um pré-registro específico do fluxo de
  moldagem (aluno registra → depois encaminha para virar `PedidoMaterial`), sem
  generalizar para outros tipos de serviço.
- `descricao_servico` **permanece texto livre** — não entra um campo `tipo_servico`
  estruturado. A necessidade de descrever livremente o serviço é mais importante do que
  a capacidade de filtrar por categoria.
- Ou seja: **nenhuma mudança de código para este ponto.** Vou atualizar
  `casos-de-uso-gestao-lab.md` (UC-10/UC-11 e a seção de decisões) para registrar essa
  decisão como fechada, e não deixar a pergunta em aberto no documento.

---

## 2 · Cruzamento dos 11 itens com o que já estava documentado

| # | Item | Já documentado? | Onde |
|---|---|---|---|
| 1 | Filtro de período em Visão Geral/Acompanhamento/Moldagens/Faturamento, com escolha do campo de data | **Parcial** — U-01 já apontava o formato de texto livre do filtro existente no Acompanhamento, mas **não** a ausência total de filtro nas outras 3 páginas nem a ideia de escolher o campo | `casos-de-uso-gestao-lab.md`, U-01 |
| 2 | "Buscar"/"Limpar tudo" na mesma altura (Acompanhamento) | **Sim** | `casos-de-uso-gestao-lab.md`, U-02 |
| 3 | Filtro de período do Acompanhamento no padrão do CME (widget colapsável) | **Sim** | `casos-de-uso-gestao-lab.md`, U-01 e §7 decisão 6 |
| 4 | Reformular status (4 categorias) | **Sim** | `plano-correcao-status-tipos-gestao-lab.md`, Ponto 1 |
| 5 | Moldagem não é um tipo de serviço; manter texto livre | **Sim** (era uma pergunta aberta, agora respondida) | `plano-correcao-status-tipos-gestao-lab.md`, Ponto 2 |
| 6 | Filtro por Faturado Paciente/Faturado Lab na página de Faturamento | **Não** — a página só tinha busca textual documentada, sem filtro de status/faturamento | novo |
| 7 | Remover linguagem de "devolução" | **Não** | novo |
| 8 | Filtro de status de faturamento (mesma ideia do item 6) | **Não** — mas **é a mesma solicitação do item 6** (ver observação abaixo) | novo |
| 9 | Busca de Pacientes no padrão de Gestão de Contratos (tabela única) | **Parcial** — U-05 já apontava que os resultados do Dental Office eram só leitura, mas não pedia a unificação em uma única tabela | `casos-de-uso-gestao-lab.md`, U-05 |
| 10 | Busca de Alunos no padrão do CME (Alunos por turma) | **Não** | novo |
| 11 | Botões secundários no menu (mini-menu do CME) | **Sim** | `casos-de-uso-gestao-lab.md`, U-06 (ali restrito a Laboratórios/Equipes; você amplia para "todas as páginas") |

**Observação sobre os itens 6 e 8:** pelo texto, são a **mesma solicitação** — filtrar a
fila de Faturamento por `faturado_paciente`/`faturado_lab`. Vou implementar como **um único
item** (chamarei de item 6/8 daqui em diante) para não duplicar trabalho; me avise se
havia alguma diferença que eu não capturei entre os dois.

---

## 3 · Detalhamento técnico por item

### Item 1 · Filtro de período com escolha de campo → ✅ **Implementado**

As páginas têm quantidades diferentes de campos de data — a solução não é idêntica nas
quatro:

| Página | Campos de data disponíveis | Proposta |
|---|---|---|
| Visão Geral | só `criado_em` (a view não filtra hoje) | Um filtro de período simples (padrão CME), por `criado_em` — não há mais de um campo para escolher aqui |
| Acompanhamento | `criado_em`, `previsao_entrega`, `data_envio`, `data_entrega`, `data_faturamento` | Filtro de período **com seletor de campo** (dropdown: Registro / Previsão de entrega / Entrega / Faturamento) — este é o caso real de "vários campos de data" |
| Moldagens | só `criado_em` (o modelo não tem outras datas) | Filtro de período simples por `criado_em` — sem seletor, só um campo existe |
| Faturamento | `criado_em`, `data_entrega`, `data_vencimento` (a fila já exclui quem tem `data_faturamento` preenchida) | Filtro de período **com seletor de campo** (Registro / Entrega / Vencimento) |

Ou seja: o "seletor de campo" faz sentido em **Acompanhamento** e **Faturamento**; em
Visão Geral e Moldagens seria um controle com uma única opção, então proponho um filtro
simples ali (mesmo padrão visual, sem a complexidade do seletor).

**Implementação:** `templates/partials/filtro_periodo.html` ganhou um parâmetro
opcional `campo_data_opcoes`/`campo_data_atual` — quando informado, renderiza um
`<select name="campo_data">` dentro do painel colapsável, ao lado dos campos De/Até;
quando omitido (Visão Geral, Moldagens, e os 3 usos existentes em `gestao_cme`), o
comportamento não muda. Um novo helper `_filtrar_por_campo_data()` em
`gestao_lab/views.py` recorta o queryset pelo campo escolhido, tratando corretamente a
diferença entre `criado_em` (`DateTimeField`) e os demais campos (`DateField` — comparados
só pela data, sem hora). `dashboard()` e `moldagens()` usam a versão simples (só
`criado_em`, sem seletor); `acompanhamento_pedidos()` e `pedidos_faturamento()` passaram a
ler `?campo_data=` (validado contra as opções válidas, com fallback para "registro") e
repassam o campo escolhido ao helper. Na Visão Geral, o recorte de período também passou
a refletir nas métricas dos KPIs e nos links deles para o Acompanhamento/Faturamento
(`filtro_datas_qs`). Testes novos cobrindo `periodo_ativo`, o filtro por período em cada
página e o seletor de campo em Acompanhamento/Faturamento (15 testes novos, suíte
`gestao_lab` com 150 testes verde).

### Item 2 · "Buscar"/"Limpar tudo" no Acompanhamento → ✅ **Implementado**

Mesma correção já aplicada no CME (mover "Limpar tudo" para dentro do `.filter-bar`,
lado a lado com "Buscar"). Ao verificar todas as páginas de `gestao_lab` que usam
`.filter-bar` (pedido explícito ao iniciar este item), encontrei o mesmo defeito em
**Moldagens** e **Pacientes** — corrigido nas três junto (Faturamento já tinha sido
corrigido no item 6/8). Alunos, Laboratórios e Equipes só têm um campo de busca sem
outro filtro, então não têm "Limpar tudo" — nada para corrigir ali.

### Item 3 · Padrão de filtro de período do CME no Acompanhamento → ✅ **Implementado**

Reusei o componente `partials/filtro_periodo.html` do CME **sem duplicar código**:
promovi o arquivo de `gestao_cme/templates/gestao_cme/partials/` para o diretório
compartilhado `templates/partials/` (os três includes existentes no CME —
`home.html`/`dashboard_cme.html`/`emprestimos.html` — foram atualizados para o novo
caminho) e passei a incluí-lo também em `acompanhamento_pedidos.html`. O filtro de
período do Acompanhamento deixou de ser dois campos de texto `dd/mm/aaaa` e virou
`<input type="date">` (ISO) dentro do mesmo painel colapsável, com `periodo_ativo`
calculado a partir da URL antes do preenchimento do padrão "todo o histórico" (mesmo
cuidado do CME). **Não inclui o seletor de campo de data** — isso continua sendo escopo
do item 1 (aqui só troquei o formato/UI do filtro por `criado_em`, que já existia).

### Item 4 · Status → ✅ **Implementado** (commit `a4077e5`, branch `claude/gestao-pedidos`)

Sem mudanças ao plano já escrito. `PedidoMaterial.Status` com as 4 categorias exatas,
migration `0010` (schema + recálculo de dados, reversível), Visão Geral/Acompanhamento
atualizados (cards e abas), badges/CSS renomeados, e a métrica equivalente do Portal do
CME também corrigida. Suíte completa (634 testes) verde. Documentação atualizada em
`casos-de-uso-gestao-lab.md` (UC-01, UC-02, UC-07, UC-09, §5 regra 1, S-05) e
`plano-correcao-status-tipos-gestao-lab.md`.

### Item 5 · Moldagem → ✅ **Fechado, sem código**

Só atualização de documentação (`casos-de-uso-gestao-lab.md`, UC-10, e
`plano-correcao-status-tipos-gestao-lab.md`, Ponto 2) — feita junto do item 4.

### Item 6/8 · Filtro de faturamento na fila de Faturamento → ✅ **Implementado**

`pedidos_faturamento()` ganhou `?faturado_paciente=sim|nao` e `?faturado_lab=sim|nao`,
com dois selects independentes na `.filter-bar` (mesmo padrão auto-submit já usado em
outros filtros do projeto), combináveis entre si e com a busca textual. Chips removíveis
por filtro ativo + "Limpar tudo" ao lado de "Buscar" (mesmo padrão de alinhamento já
usado no restante do app). Estado vazio diferencia "fila realmente vazia" de "nenhum
resultado para os filtros aplicados". Adicionada suíte de testes para a view
(`PedidosFaturamentoViewTests`, 6 testes) — não havia nenhum teste dela antes. Suíte
`gestao_lab` (132 testes) verde.

### Item 7 · Remover linguagem de "devolução" → ✅ **Implementado**

| Arquivo | Texto atual | Novo texto | Status |
|---|---|---|---|
| `models.py` (docstring da classe) | ~~"devolucao do material finalizado..."~~ | "entrega do material finalizado..." | ✅ Corrigido (item 4) |
| `dashboard.html` | ~~"aguardando devolução" (legenda do card "A confirmar")~~ | — (card removido) | ✅ Removido (item 4) |
| `detalhe_pedido.html` (3 ocorrências) | ~~"Devolução do laboratório" / "Material finalizado devolvido"~~ | "Entrega do laboratório" / "Material entregue" | ✅ Corrigido |
| `form_pedido.html` | ~~"Previsão de entrega (devolução)"~~ | "Previsão de entrega" | ✅ Corrigido |

Ao revisar, também encontrei duas referências desatualizadas em
`casos-de-uso-gestao-lab.md` que datavam de antes da reforma do item 4 (não tinham
relação com "devolução", mas ficaram erradas depois da mudança de status): a UC-05
ainda dizia que registrar o envio mudava o status para `A_CONFIRMAR` (não existe mais) e
o glossário ainda listava `A_CONFIRMAR` como uma das 4 categorias. Corrigidas junto.

`gestao_lab/services/dental_sync.py` menciona "ordem devolvida pela API" — termo técnico
sobre a resposta HTTP paginada, sem relação com o processo de negócio; mantido como
está. As ocorrências de "devolução" em `gestao_cme` (Empréstimos) também foram
verificadas e são de um processo diferente (devolução de kit emprestado, que existe de
fato no CME) — fora do escopo deste item.

### Item 9 · Busca de Pacientes no padrão de Gestão de Contratos → ✅ **Implementado**

Segui exatamente `gestao_contratos/views.py::contratos` e `contratos.html` como
referência:
- Uma única tabela (`pacientes_unificados`), com selo de origem por linha ("No sistema"
  / "Dental Office") em vez de duas tabelas separadas. Os novos selos reusam classes
  compartilhadas (`.badge-origin`/`.badge-local`/`.badge-dental`, adicionadas a
  `static/css/components.css` sem o escopo `body.gestao-contratos` que a versão
  original tinha, para ficarem disponíveis em qualquer app).
- Resultados do Dental Office ainda não importados aparecem só na 1ª página, com uma
  ação **"Importar"** por linha (`views.importar_paciente_dental`, POST, nova rota
  `pacientes/<id_dental>/importar/`), chamando `materializar_paciente` (já existente no
  serviço de sincronização, mesma função usada pelo autocomplete de pedido/moldagem) —
  isso também fecha o achado **U-05** (antes os resultados do Dental Office eram só
  leitura).
- Colunas mantidas exatamente como a página já mostrava: Paciente (+ selo de origem),
  Celular, Pedido (aberto/sem — "—" para quem só existe no Dental Office), Previsão de
  retorno (idem), Atualização (idem), Ação ("Importar" ou "—").
- 7 novos testes (listagem unificada sem duplicar quem já é local, badges de origem
  corretos, e a view de importação — sucesso, sem `DENTAL_CLIENT_ID`, erro da API,
  método não permitido). Verificação visual feita no navegador (Playwright): tabela
  única renderiza corretamente, e a degradação (mensagem de erro em vez de tabela
  quebrada) funciona quando o Dental Office está inacessível. Suíte completa
  (665 testes) verde.

### Item 10 · Busca de Alunos no padrão do CME (Alunos por turma) → ✅ **Implementado**

> **Superado em 2026-07-22** — este item corrigiu apenas *qual botão* sincronizava
> Alunos (completa → só-alunos), mas manteve a fonte de dados errada: a sincronização
> continuava puxando "alunos" do **Dental Office**, que é um sistema clínico e nunca
> teve esse dado — nenhum `AlunoLab` sincronizado por ali representava um aluno real.
> A correção definitiva (trocar a fonte para o **Eduq**, mesmo sistema acadêmico já
> usado pelo `gestao_cme`, com um novo `TurmaLab` e sincronização de turma sob demanda)
> está registrada em `casos-de-uso-gestao-lab.md`, §11. O texto abaixo é o registro
> histórico da implementação original deste item — não reflete mais o comportamento
> atual do botão de sincronização de Alunos.

A busca em si **já era** local-only com `nome_normalizado`/`icontains`, igual ao CME — o
que divergia era o **botão de sincronização**: a página de Alunos usava o botão
"Atualizar lista" que acionava `lab_sincronizar` (sincronização **completa**, pacientes
**e** alunos — mais lenta do que essa tela precisa). O CME já resolveu esse tipo de
imprecisão (cada botão sincroniza exatamente o que a tela usa).

**Implementação:** `partials/sync_dental.html` (usado só pela página de Alunos — a
página de Pacientes já não o usava desde o item 9) passou a apontar para
`lab_sincronizar_alunos` em vez de `lab_sincronizar`, com o botão renomeado de
"Atualizar lista" para "Atualizar alunos" (mesmo texto já usado no botão equivalente dos
formulários de pedido/moldagem, `partials/atualizar_alunos.html`). Como consequência, a
sincronização completa (`lab_sincronizar`/UC-19) deixou de ter qualquer gatilho manual na
interface — continua acionável pela tarefa agendada do Celery Beat (04:30 diária) e pelo
endpoint de cron externo (UC-21); isso também mitiga o achado sistêmico **S-04** (risco
de lentidão do botão manual síncrono), já que não há mais botão que dispare essa
execução. 1 novo teste (`test_botao_de_sincronizacao_aciona_apenas_alunos`), suíte
`gestao_lab` (158 testes) verde — não precisou da suíte completa por não tocar nenhum
partial/CSS compartilhado entre apps.

### Item 11 · Botões secundários no menu → ✅ **Implementado**

Reproduzi `partials/side_link_group.html` do CME para os itens que tinham um botão de
cadastro separado da navegação:

| Item do menu | Botão secundário movido para o mini-menu |
|---|---|
| Acompanhamento | "Registrar pedido" (era um bloco à parte, "Ações rápidas", na sidebar) |
| Moldagens | "Nova moldagem" (era em `panel_actions`, topo da página) |
| Laboratórios | "Novo laboratório" (era em `panel_actions`) |
| Equipes | "Nova equipe" (era em `panel_actions`) |

**Implementação:** `gestao_lab/templates/gestao_lab/partials/menu.html` trocou os 4
`side_link.html` desses itens por `side_link_group.html` (mesma `match` já usada antes,
mais o `action1_label`/`action1_url_name` de cada cadastro) e removeu o bloco
"Ações rápidas" (que só continha "Registrar pedido"). Cada uma das 4 páginas teve seu
`panel_actions`/bloco de botão removido, substituído por um comentário apontando para o
mini-menu (mesmo padrão dos templates do CME, ex.: `materiais.html`). 5 novos testes
(`MiniMenuBotoesSecundariosTests`), suíte `gestao_lab` (163 testes) verde. Verificação
visual no navegador (Playwright) confirmando os 4 mini-menus e a expansão automática.

**Ajuste posterior (mesmo dia):** a pedido do usuário, "Registrar pedido" e "Nova
moldagem" voltaram a ser botões de **ação rápida** na sidebar (bloco "Ações rápidas",
como antes do item 11), em vez de sub-links de mini-menu — por serem a ação de fluxo
principal de cada tela (criar o registro mais frequente da operação), não um cadastro
auxiliar, ficam em destaque em vez de escondidos atrás de um clique extra (mesmo
critério que o próprio CME já usa para "Registrar entrada"/"Registrar retirada" em
Movimentações, que nunca foram para um mini-menu). "Novo laboratório"/"Nova equipe"
continuam nos mini-menus — são cadastros auxiliares, não o fluxo principal da tela.
`partials/menu.html` voltou a usar `side_link.html` (sem grupo) para Acompanhamento e
Moldagens, com o bloco "Ações rápidas" reintroduzido com os dois botões. Testes
renomeados/ajustados (`MenuBotoesSecundariosTests`); suíte `gestao_lab` (164 testes)
verde. Não precisou de nenhuma mudança em CSS/JS em nenhuma das duas rodadas —
`side_link_group.html`, `side_link.html`, `.side-quick-actions` e o JS de abrir/fechar
submenu (`static/js/app.js`) já eram compartilhados e genéricos, sem nenhum código
específico do CME.

---

## 4 · Ordem de implementação sugerida

Prioridade pela severidade que você atribuiu, agrupando o que é tecnicamente relacionado:

1. ✅ **Item 4** — Crítico, autocontido, base para os KPIs de faturamento. **Implementado**
   (commit `a4077e5`).
2. ✅ **Item 5** — Só atualização de documentação, feito junto do item 4.
3. ✅ **Item 7** — **Implementado**. Restava corrigir 2 arquivos (`detalhe_pedido.html`,
   `form_pedido.html`) — feito, além de 2 referências desatualizadas encontradas em
   `casos-de-uso-gestao-lab.md` durante a revisão (UC-05 e glossário, ambas ainda citavam
   o status `A_CONFIRMAR` removido no item 4).
4. ✅ **Item 6/8** — **Implementado**. Filtros por Fat. paciente/Fat. laboratório na fila
   de Faturamento, combináveis com a busca; suíte de testes nova para essa view.
5. ✅ **Item 3 + item 2** — **Implementados**. Filtro de período do Acompanhamento no
   padrão do CME (widget promovido para `templates/partials/`, reusado sem duplicação);
   "Buscar"/"Limpar tudo" alinhados no Acompanhamento e, ao verificar todas as páginas
   com busca (pedido explícito), também em Moldagens e Pacientes.
6. ✅ **Item 1** — **Implementado**. Período estendido (com seletor de campo em
   Acompanhamento/Faturamento) às 4 páginas, reaproveitando o widget já ajustado no
   item 3.
7. ✅ **Item 9** — **Implementado**. Busca unificada de Pacientes (tabela única, selo de
   origem, ação "Importar" para quem só existe no Dental Office).
8. ✅ **Item 10** — **Implementado**. Botão de sincronização de Alunos trocado da rotina
   completa para a rotina só-alunos, mais rápida.
9. ✅ **Item 11** — **Implementado**. Botões secundários (Registrar pedido, Nova
   moldagem, Novo laboratório, Nova equipe) movidos para mini-menus na navegação
   lateral, mesmo padrão do CME.

Os 11 itens da lista original estão implementados. Cada um seguiu o fluxo já
estabelecido: implementar, rodar a suíte (completa quando o item tocava partials/CSS
compartilhados entre apps, só `gestao_lab` quando não tocava), commitar e enviar.
