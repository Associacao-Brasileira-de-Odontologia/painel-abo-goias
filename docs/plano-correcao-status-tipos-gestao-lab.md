# Plano de Correção — Status de Pedidos e Tipos de Serviço (`gestao_lab`)

> Data: 2026-07-21 · Complementa `docs/casos-de-uso-gestao-lab.md`.
> **Atualização de 2026-07-21:** Ponto 1 (status) foi confirmado e **implementado**
> (commit `a4077e5`, branch `claude/gestao-pedidos`) — ver detalhes no final da seção 1.
> Ponto 2 (tipo de serviço) foi **decidido sem necessidade de código** — ver o final da
> seção 2. Este documento permanece como registro da análise original.

## Contexto de negócio (conforme descrito)

> "Minha aplicação funciona como um controle de materiais solicitados a laboratórios e
> devem ser acompanhados suas entregas [...] em atraso (fora do prazo de entrega),
> entregue e não faturado (pedido entregue porém as informações de faturamento não
> foram preenchidas), concluídas (pedidos entregues e faturados) e [...] em dia
> (pedidos dentro do prazo porém não entregues). [...] são solicitados vários tipos de
> materiais, a aplicação tem que suportar o cadastro de vários serviços como moldagens,
> aparelhos e etc."

Isso define **duas exigências de negócio** que a implementação atual não atende com
precisão:

1. Todo pedido deve estar em **exatamente uma** de 4 categorias: **Em dia**, **Atrasado**,
   **Entregue e não faturado**, **Concluído**.
2. A aplicação precisa tratar o **tipo de material/serviço solicitado** (moldagem,
   aparelho, e outros) como um conceito de primeira classe, não apenas como um caso
   específico do fluxo (hoje só "Moldagem" tem tratamento próprio).

---

## 1 · [Crítico] O status do pedido não representa as 4 categorias reais do negócio

### O que está implementado hoje

`PedidoMaterial.Status` tem 4 valores, mas com um recorte **diferente** do que o negócio
usa — o eixo "enviado ao laboratório" entra na conta, e não há nenhum valor para "entregue
e não faturado":

```python
# gestao_lab/models.py
class Status(models.TextChoices):
    EM_DIA = "EM_DIA", "Em dia"
    A_CONFIRMAR = "A_CONFIRMAR", "A confirmar"
    ATRASADO = "ATRASADO", "Atrasado"
    CONCLUIDO = "CONCLUIDO", "Concluido"

def calcular_status(self) -> str:
    hoje = date.today()
    if self.entregue and self.faturado_paciente and self.faturado_lab:
        return self.Status.CONCLUIDO
    if not self.entregue and hoje > self.previsao_entrega:
        return self.Status.ATRASADO
    if self.data_envio and not self.entregue:
        return self.Status.A_CONFIRMAR
    return self.Status.EM_DIA
```

### O bug concreto (verificado, não hipotético)

Percorra a função com `entregue=True` e faturamento **incompleto** (só um dos dois lados
marcado, ou nenhum) — o cenário que o negócio chama de **"entregue e não faturado"**:

1. `entregue and faturado_paciente and faturado_lab` → **False** (falta um dos dois).
2. `not entregue and hoje > previsao_entrega` → `not entregue` é **False** → condição
   inteira **False**.
3. `data_envio and not entregue` → `not entregue` é **False** → condição inteira
   **False**.
4. Cai no `return self.Status.EM_DIA`.

**Um pedido já entregue ao coordenador, aguardando só o faturamento, é rotulado como "Em
dia"** — o mesmo rótulo usado para um pedido que sequer foi enviado ao laboratório. Isso
aparece:

- na coluna **Status** do Acompanhamento (`acompanhamento_pedidos.html`, badge
  `badge-em-dia`);
- no filtro de status do Acompanhamento (`STATUS_OPCOES`, que nem lista essa categoria);
- no Django Admin (`list_filter = (..., "status", ...)`).

**A própria suíte de testes já denunciava a lacuna.** O teste que cobre esse cenário não
afirma qual é o status esperado — só que não é `CONCLUIDO`:

```python
# gestao_lab/tests.py
def test_status_nao_concluido_quando_entregue_mas_faturamento_incompleto(self) -> None:
    pedido = _pedido(..., entregue=True, faturado_paciente=True, faturado_lab=False)
    self.assertNotEqual(pedido.status, PedidoMaterial.Status.CONCLUIDO)
```

Um teste que só verifica "não é X" em vez de "é Y" é o sinal clássico de uma lacuna já
sentida por quem escreveu o teste, sem uma resposta definida — exatamente o ponto que
você está trazendo agora.

**A Visão Geral já reconhece essa categoria por fora do campo `status`**, com uma consulta
paralela e independente:

```python
# gestao_lab/views.py::dashboard
"pendentes_faturamento": qs.filter(entregue=True)
    .exclude(faturado_paciente=True, faturado_lab=True)
    .count(),
```

Ou seja: o KPI "Faturamento" da Visão Geral já mostra o número certo, mas **o campo
`status` do próprio registro (usado em toda outra tela) mostra o rótulo errado** — duas
fontes de verdade divergentes para o mesmo conceito de negócio.

### Cenário de falha concreto

Um pedido é entregue ao paciente na sexta-feira. Até o faturamento ser fechado na segunda,
qualquer coordenador que olhar o Acompanhamento vê "Em dia" — informação que sugere que o
material **ainda está no laboratório**, quando na verdade já foi devolvido. Quem depende
só dessa tela (sem checar a Visão Geral) tem uma leitura operacional errada do que precisa
ser feito a seguir.

### Correção proposta

```python
class Status(models.TextChoices):
    EM_DIA = "EM_DIA", "Em dia"
    ATRASADO = "ATRASADO", "Atrasado"
    ENTREGUE_NAO_FATURADO = "ENTREGUE_NAO_FATURADO", "Entregue — não faturado"
    CONCLUIDO = "CONCLUIDO", "Concluido"

def calcular_status(self) -> str:
    if self.entregue:
        if self.faturado_paciente and self.faturado_lab:
            return self.Status.CONCLUIDO
        return self.Status.ENTREGUE_NAO_FATURADO
    if date.today() > self.previsao_entrega:
        return self.Status.ATRASADO
    return self.Status.EM_DIA
```

Note que a nova versão também é **logicamente mais simples**: primeiro decide por
`entregue` (sim/não), depois por prazo — só 4 caminhos possíveis, cada um mapeado
diretamente a uma das 4 categorias do negócio. `A_CONFIRMAR` deixa de existir como
**status**; "Em dia" passa a cobrir tanto "ainda não enviado" quanto "enviado, aguardando
devolução, dentro do prazo" — exatamente como você descreveu ("dentro do prazo porém não
entregues", sem distinguir se já foi enviado).

**Nada se perde operacionalmente:** `data_envio` continua gravado e visível na linha do
tempo do detalhe do pedido (UC-04) — só deixa de ser, por si só, um valor de `status`.

### Decisão de negócio — confirmada e implementada (2026-07-21)

Confirmado: "A confirmar" deixou de ser status/aba separado e passou a contar dentro de
"Em dia". Implementado no commit `a4077e5` (branch `claude/gestao-pedidos`): novo status
`ENTREGUE_NAO_FATURADO`, `calcular_status()` reescrito exatamente como proposto acima,
migration `0010_reformular_status_pedido` (schema + recálculo de dados, reversível),
Visão Geral e Acompanhamento atualizados (cards/abas), badges/CSS renomeados
(`badge-a-confirmar`→`badge-entregue-pendente`), e a métrica de faturamento pendente do
Portal do CME (`gestao_cme/views.py::portal`, que fazia o mesmo cálculo ad-hoc) também
passou a usar o campo `status`. Suíte completa (634 testes) verde.

### Impacto em cascata (era o plano; já executado)

| Arquivo | Mudança necessária |
|---|---|
| `gestao_lab/models.py` | Novo valor no `Status`; `calcular_status()` reescrito (acima); nova migration |
| `gestao_lab/migrations/` | Migration de schema (novo choice) **+** migration de dados: recalcular `status` de todo `PedidoMaterial` já existente com `entregue=True` e faturamento incompleto (hoje armazenados como `EM_DIA`) |
| `gestao_lab/views.py` | `STATUS_OPCOES`/`STATUS_LABELS` (dropdown do Acompanhamento); abas do `acompanhamento_pedidos.html` passam a ser Todos/Em dia/Atrasado/Entregue-não-faturado; `dashboard()` pode **parar de duplicar a lógica** e contar direto por `status=ENTREGUE_NAO_FATURADO` — resolve também o achado sistêmico **S-05** já registrado em `casos-de-uso-gestao-lab.md` (métricas duplicadas entre Visão Geral e Acompanhamento) |
| `gestao_lab/templatetags/lab_tags.py` | `status_badge_class`/`status_row_class` — nova entrada para `ENTREGUE_NAO_FATURADO` (sugestão: mesma cor do badge "info" já usado em Pacientes para "Pedido em aberto") |
| `gestao_lab/admin.py` | Nenhuma mudança estrutural — `list_filter` já usa o enum inteiro, ganha a nova opção automaticamente |
| `gestao_lab/services/cobranca.py` | Nenhuma mudança — a cobrança automática já filtra só por `ATRASADO`, que mantém o mesmo sentido (não entregue, fora do prazo) |
| `gestao_lab/tests.py` | Reescrever `test_status_nao_concluido_quando_entregue_mas_faturamento_incompleto` para afirmar o valor certo (`ENTREGUE_NAO_FATURADO`); ajustar `AcompanhamentoPedidosTests`/`DashboardLabTests` para a nova contagem; remover/ajustar o teste de `A_CONFIRMAR` |
| `docs/casos-de-uso-gestao-lab.md` | Atualizar UC-01, UC-02, UC-07, UC-09, regra transversal 1 (§5) e o achado S-05 (§6.2, passa a "resolvido") |

---

## 2 · [Alto] Falta um campo estruturado de tipo de serviço/material

### O que está implementado hoje

- `PedidoMaterial.descricao_servico` é um `TextField` livre — não há nenhum campo
  categorizável (`choices`, FK, etc.) para o **tipo** de material/serviço solicitado.
- `Moldagem` é um modelo **próprio e hardcoded**, tratado como se fosse o único tipo de
  solicitação que precisa de uma etapa prévia ao pedido formal (aluno registra a
  moldagem → depois "encaminha" como `PedidoMaterial`). Não existe equivalente para
  "aparelho" ou qualquer outro tipo — ou esses tipos são pedidos diretamente (sem etapa
  prévia), ou simplesmente não há como registrá-los de forma distinta de uma moldagem.

### Por que isso é uma ambiguidade, não só uma limitação

Hoje é **impossível responder, sem ler manualmente cada `descricao_servico`**, perguntas
como "quantos pedidos de aparelho estão atrasados este mês?" ou "qual laboratório recebe
mais pedidos de moldagem vs. outros tipos?" — não existe um campo para filtrar/agrupar por
tipo. Ao mesmo tempo, o único tipo que **tem** tratamento estruturado (`Moldagem`) tem uma
etapa extra (pré-registro, conversão) que os demais tipos não têm — a aplicação trata
"moldagem" como uma categoria fundamentalmente diferente das outras, sem que fique claro
se isso é intencional (moldagem realmente precisa de uma etapa prévia que aparelho não
precisa) ou um acidente histórico (moldagem foi o primeiro caso implementado).

### Duas abordagens possíveis

**Opção A — mínima:** adicionar um campo `tipo_servico` (choices, ex.: `MOLDAGEM`,
`APARELHO`, `OUTRO`, extensível) diretamente em `PedidoMaterial`. `Moldagem` continua
existindo exatamente como hoje, exclusiva para o caso "moldagem".
- **Prós:** baixo esforço, não toca no fluxo de moldagem já em uso.
- **Contras:** a assimetria continua — outros tipos de serviço não teriam a etapa de
  pré-registro que moldagem tem, mesmo que o negócio precise dela igualmente para
  aparelhos.

**Opção B — generalizar:** expandir `Moldagem` para um conceito mais amplo (ex.:
`SolicitacaoServico`, com um campo `tipo`), reutilizável por qualquer tipo de material que
precise de uma etapa de registro antes de virar um `PedidoMaterial` formal.
- **Prós:** resolve a ambiguidade na raiz — um único fluxo consistente, qualquer que seja
  o tipo de serviço.
- **Contras:** refactor maior (renomear modelo e tabela, migração de dados, atualizar
  todas as views/templates/urls/testes que hoje mencionam "moldagem" explicitamente —
  são referenciados em pelo menos 8 arquivos).

### Decisão — respondida (2026-07-21): nem A, nem B

A resposta descarta as duas opções acima. `Moldagem` continua **exatamente como está**
hoje — um pré-registro específico do fluxo de moldagem (aluno registra → depois
encaminha para virar `PedidoMaterial`) — e **não** deve ser tratada como uma categoria de
"tipo de serviço". `descricao_servico` **permanece texto livre**: a capacidade de
descrever o serviço livremente é mais importante do que a de filtrar por categoria
estruturada. **Nenhuma mudança de código para este ponto** — ver
`docs/plano-implementacao-gestao-lab.md`, item 5.

---

## 3 · Resumo executivo

| # | Ponto | Severidade | Status |
|---|---|---|---|
| 1 | Status do pedido não tinha uma categoria própria para "entregue e não faturado" — caía silenciosamente em "Em dia" | **Crítico** | ✅ **Implementado** (commit `a4077e5`) — 4 categorias exatas, "A confirmar" fundido em "Em dia" |
| 2 | Falta um campo estruturado de tipo de serviço/material; `Moldagem` é hardcoded só para esse tipo | **Alto** | ✅ **Decidido, sem código** — `Moldagem` mantida como está, `descricao_servico` permanece texto livre |

---

## 4 · Sequenciamento recomendado

Seguindo a mesma disciplina já usada neste projeto (um item por vez: implementar, testar,
commitar, enviar, aguardar aprovação antes do próximo):

1. **Ponto 1 primeiro** (crítico, autocontido, sem dependência do Ponto 2) — depois da sua
   confirmação sobre "A confirmar".
2. **Ponto 2 depois**, começando pela Opção A (campo `tipo_servico`), que pode ser
   implementada independentemente da decisão sobre generalizar `Moldagem` no futuro.
