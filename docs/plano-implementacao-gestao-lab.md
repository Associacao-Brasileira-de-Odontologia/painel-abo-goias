# Plano de Implementação — Gestão de Pedidos de Materiais em Laboratório (`gestao_lab`)

> Data: 2026-07-21 · Complementa `docs/casos-de-uso-gestao-lab.md` e
> `docs/plano-correcao-status-tipos-gestao-lab.md`.
> Este documento cruza os 11 itens recebidos com o que já estava documentado, resolve as
> duas confirmações pendentes e propõe a sequência de implementação (um item por vez:
> implementar, testar, commitar, enviar, aguardar aprovação — mesma disciplina já usada
> no CME).
> **Progresso:** item 4 implementado (commit `a4077e5`); item 5 fechado sem código —
> ver §4.

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

### Item 1 · Filtro de período com escolha de campo

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

### Item 2 · "Buscar"/"Limpar tudo" no Acompanhamento

Mesma correção já aplicada no CME (mover "Limpar tudo" para dentro do `.filter-bar`,
lado a lado com "Buscar").

### Item 3 · Padrão de filtro de período do CME no Acompanhamento

Reusar o mesmo componente `partials/filtro_periodo.html` do CME (ou uma cópia adaptada em
`gestao_lab`) — `<details>` colapsável, `<input type="date">` ISO, `periodo_ativo`. Isso
também resolve o item 1 para o Acompanhamento (o seletor de campo entra como mais um
controle dentro do mesmo widget colapsável).

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

### Item 6/8 · Filtro de faturamento na fila de Faturamento

`pedidos_faturamento()` ganha `?faturado_paciente=sim|nao` e `?faturado_lab=sim|nao` (ou
combinado, ex. `?faturamento=pendente_paciente|pendente_lab|pendente_ambos` — a definir
qual UI é mais clara: dois selects independentes ou um único agrupando as combinações).
Vou propor **dois selects independentes** (um por coluna, espelhando exatamente as duas
colunas "Faturado Paciente"/"Faturado Lab" já existentes na tabela) como primeira
proposta, por ser mais direto — ajusto se preferir a combinação num único filtro.

### Item 7 · Remover linguagem de "devolução"

Duas das quatro ocorrências **já foram corrigidas como efeito colateral do item 4**
(implementado): o docstring de `models.py` foi reescrito em termos de "entrega" (sem
nenhuma menção a "devolução") e o card "A confirmar" do `dashboard.html` (que tinha a
legenda "aguardando devolução") foi removido. Restam 2 arquivos:

| Arquivo | Texto atual | Novo texto proposto | Status |
|---|---|---|---|
| `models.py` (docstring da classe) | ~~"devolucao do material finalizado..."~~ | ~~"entrega do material finalizado..."~~ | ✅ Já corrigido (item 4) |
| `dashboard.html` | ~~"aguardando devolução" (legenda do card "A confirmar")~~ | — | ✅ Já removido (item 4) |
| `detalhe_pedido.html` (3 ocorrências) | "Devolução do laboratório" / "Material finalizado devolvido" | "Entrega do laboratório" / "Material entregue" | Em aberto |
| `form_pedido.html` | "Previsão de entrega (devolução)" | "Previsão de entrega" (o "(devolução)" é redundante e é o termo que queremos evitar) | Em aberto |

### Item 9 · Busca de Pacientes no padrão de Gestão de Contratos

Vou seguir exatamente `gestao_contratos/views.py::contratos` e
`contratos.html` como referência:
- Uma única tabela (`pacientes_unificados`), com selo de origem por linha ("No sistema"
  / "Dental Office") em vez de duas tabelas separadas.
- Resultados do Dental Office ainda não importados aparecem só na 1ª página, com uma
  ação **"Importar"** por linha (chamando `materializar_paciente`, já existente no
  serviço de sincronização) — isso também fecha o achado **U-05** (hoje os resultados do
  Dental Office são só leitura).
- Colunas adaptadas ao que a página de Pacientes do laboratório já mostra hoje: Paciente
  (+ selo de origem), Celular, Pedido (aberto/sem — só para quem já está no sistema),
  Previsão de retorno (idem), Atualização (idem), Ação.

### Item 10 · Busca de Alunos no padrão do CME (Alunos por turma)

A busca em si **já é** local-only com `nome_normalizado`/`icontains`, igual ao CME — o
que diverge é o **botão de sincronização**: hoje a página de Alunos usa o botão
"Atualizar lista" que aciona `lab_sincronizar` (sincronização **completa**, pacientes **e**
alunos — mais lenta do que essa tela precisa). O CME já resolveu esse tipo de imprecisão
(cada botão sincroniza exatamente o que a tela usa). Proposta: trocar, só nesta página,
para `lab_sincronizar_alunos` (a rotina já existente, mais leve, só alunos) — mantendo
"Atualizar lista" (ou renomeando para "Atualizar alunos", mais preciso).

### Item 11 · Botões secundários no menu

Reproduzir `partials/side_link_group.html` do CME para os itens que hoje têm um botão de
cadastro separado da navegação:

| Item do menu | Botão secundário a mover para o mini-menu |
|---|---|
| Acompanhamento | "Registrar pedido" (hoje é um bloco à parte, "Ações rápidas", na sidebar) |
| Moldagens | "Nova moldagem" (hoje em `panel_actions`, topo da página) |
| Laboratórios | "Novo laboratório" (hoje em `panel_actions`) |
| Equipes | "Nova equipe" (hoje em `panel_actions`) |

---

## 4 · Ordem de implementação sugerida

Prioridade pela severidade que você atribuiu, agrupando o que é tecnicamente relacionado:

1. ✅ **Item 4** — Crítico, autocontido, base para os KPIs de faturamento. **Implementado**
   (commit `a4077e5`).
2. ✅ **Item 5** — Só atualização de documentação, feito junto do item 4.
3. **Item 7** — Médio, rápido; restam só 2 arquivos (`detalhe_pedido.html`,
   `form_pedido.html`) — os outros 2 já saíram junto do item 4.
4. **Item 6/8** — Filtro de faturamento.
5. **Item 3 + item 2** — Padronizar o filtro de período do Acompanhamento e alinhar Buscar/Limpar tudo (mesma área de tela, faz sentido em sequência).
6. **Item 1** — Estender período (com seletor de campo) às demais páginas, reaproveitando o widget já ajustado no item 3.
7. **Item 9** — Busca unificada de Pacientes (Alta).
8. **Item 10** — Sincronização de Alunos (Alta).
9. **Item 11** — Mini-menu para os botões secundários (Alta, mas é o que mais toca a navegação — deixo por último para não reordenar a sidebar antes das outras mudanças de conteúdo de cada página estarem prontas).

Cada item segue o fluxo já estabelecido: implementar, rodar a suíte completa (os
partials/testes de `gestao_lab` também tocam `paginacao.html` e o design system
compartilhado), commitar, enviar e aguardar sua aprovação antes do próximo.

Pronto para seguir com o item 7 (ou outro, se preferir mudar a ordem).
