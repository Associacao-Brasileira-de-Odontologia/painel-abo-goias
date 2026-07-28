# Plano — padronização visual e faturamento por orçamento

> Plano de implementação e impacto para as 7 modificações solicitadas em 2026-07-28.
> Escrito **antes** de qualquer alteração de código: o levantamento abaixo foi feito
> lendo o código atual e medindo estilos computados no navegador, não a partir de
> memória ou dos documentos existentes.
>
> Documentos relacionados: [`plano-limpeza-codigo.md`](plano-limpeza-codigo.md)
> (concluído até a etapa 8), [`avaliacao-visual-padronizacao-frontend.md`](avaliacao-visual-padronizacao-frontend.md)
> (auditoria visual, com decisões em aberto que este plano encosta),
> [`documentacao-gestao-lab.md`](documentacao-gestao-lab.md).

## 1. Resumo executivo

As 7 modificações se dividem em dois blocos de natureza bem diferente:

| Bloco | Itens | Natureza | Risco |
|---|---|---|---|
| **A — Aparência** | 1, 2, 3, 4 | CSS + templates. Nenhuma regra de negócio, nenhum modelo, nenhuma URL. | Baixo — verificável por comparação visual e por diff de HTML |
| **B — Faturamento** | 5, 6, 7 | Views, serviços, integração externa e (no item 6) modelo de dados. | Médio a alto — o item 6 depende de um endpoint do Dental Office que **ainda não existe** |

A ordem proposta **não** é a ordem em que os itens foram listados. Ela é ditada por
dependências reais (detalhadas em §3) e pelo princípio de deixar o bloco A inteiro
concluído antes de abrir o bloco B, para que uma eventual pausa no meio do trabalho
deixe o sistema num estado coerente.

**Sequência recomendada:**

```
Etapa 1  (item 1)  Paleta ABO no menu das 3 apps restantes
Etapa 2  (item 2)  KPIs coloridos na Visão Geral do CME
Etapa 3  (item 4)  Baseline único de tabelas nas 4 apps
Etapa 4  (item 3)  Botões de ícone nas ações das tabelas do Lab
──────── fim do bloco A: aparência padronizada ────────
Etapa 5  (item 5)  Remover o filtro "faturado pelo paciente"
Etapa 6  (item 7)  Relatório de faturamento por laboratório
Etapa 7  (item 6)  Orçamento do Dental Office como pré-requisito do pedido
```

A etapa 3 vem antes da 4 de propósito: os botões de ícone vivem dentro da coluna
"Ações" das tabelas. Padronizar a tabela primeiro dá uma linha de base estável para
medir o efeito dos ícones; na ordem inversa as duas mudanças se misturariam no mesmo
diff e ficaria difícil saber qual causou o quê.

A etapa 7 (item 6) vem por último porque é a única cujo escopo **não pode ser fechado
hoje** — ver §3.3.

---

## 2. Levantamento — o que existe hoje

Esta seção é evidência, não proposta. Cada afirmação tem arquivo e linha.

### 2.1 Cores do menu (item 1)

O design system usa *tokens* de acento em `abo-goias/static/css/tokens.css`. O `:root`
define o azul padrão (`--accent-text: #27baff`, `--accent-soft`, `--accent-strong`,
`--accent-focus`, `--accent-ring`) e existe **exatamente um** override por app:

```css
.app-lab {
    --accent-text: #67f9e0;
    --accent-soft: rgba(18, 227, 199, 0.14);
    --accent-strong: #d9fdf6;
    --accent-focus: rgba(18, 227, 199, 0.7);
    --accent-ring: rgba(18, 227, 199, 0.12);
}
```

O item ativo do menu lateral consome esses tokens:
`components.css:1669` → `.side-link.active { background: var(--accent-soft); color: var(--accent-strong) }`.

A classe no `<body>` vem de `{% block body_class %}`, declarado em `templates/base.html:16`.
Estado atual das quatro apps:

| App | `body_class` | Tokens de acento em vigor |
|---|---|---|
| Gestão de Pedidos de Laboratório | `app-lab` (`gestao_lab/templates/gestao_lab/base.html:9`) | **turquesa (paleta ABO)** |
| Gestão de Contratos | `gestao-contratos` (`gestao_contratos/templates/gestao_contratos/base.html:13`) | azul do `:root` |
| Gestão de CME | *nenhuma* nas telas internas; `portal-body` só no Portal (`portal.html:5`) | azul do `:root` |
| Identificadores de Bancada | *nenhuma* (`identificadores/templates/identificadores/index.html` estende `layouts/painel.html` direto) | azul do `:root` |

**Conclusão:** o mecanismo já existe e está correto; só a app Lab foi ligada a ele. A
mudança é adicionar a classe (ou reapontar os tokens) nas outras três — não é
reescrever CSS.

### 2.2 KPIs da Visão Geral (item 2)

Os quatro modificadores de cor **já existem** em `components.css` e já estão dentro da
paleta ABO:

| Classe | Linha | Cor |
|---|---|---|
| `.metric-card.metric-blue` | 919 | azul |
| `.metric-card.metric-success` | 927 | turquesa |
| `.metric-card.metric-warn` | 939 | âmbar |
| `.metric-card.metric-neutral` | 933 | cinza |
| `.danger-metric` | 895 | vermelho |

Uso atual:

- **Lab** (`gestao_lab/templates/gestao_lab/dashboard.html:33-51`) — `metric-success`,
  `danger-metric`, `metric-warn`, `metric-neutral`. Quatro cores distintas.
- **CME** (`gestao_cme/templates/gestao_cme/dashboard_cme.html:35-53`) — três cards com
  `metric-card metric-card--link` (sem cor nenhuma) e **um** com `danger-metric`.
- **Identificadores** (`index.html:19`) — já usa `metric-blue` na barra lateral.

Há ainda uma divergência secundária que vale registrar: o CME usa `metric-card--link`
(hover com deslocamento, `components.css:880`) e o Lab **não**, embora os cards do Lab
também sejam `<a href>`. Ou seja, os dois dashboards têm KPIs clicáveis, mas só um dá
retorno visual ao passar o mouse.

**Conclusão:** a mudança é de template (trocar/adicionar classes), não de CSS. É a
etapa de menor risco do plano inteiro.

### 2.3 Botões de texto nas tabelas do Lab (item 3)

Botões de ação **por linha de tabela** (os que o item pede para virar ícone). Os botões
de formulário — "Buscar", "Limpar tudo", "Salvar", "Cancelar" — **ficam como texto**:
são ações de página, não de linha, e transformá-los em ícone prejudicaria a clareza.

| Template | Linha | Rótulo hoje | Ícone proposto |
|---|---|---|---|
| `acompanhamento_pedidos.html` | 164 | Registrar envio | novo `i-enviar` |
| `acompanhamento_pedidos.html` | 171 | Registrar entrega | novo `i-entregar` |
| `acompanhamento_pedidos.html` | 175 | *(link secundário)* | a confirmar na etapa |
| `acompanhamento_pedidos.html` | 183 | Ver | novo `i-ver` |
| `acompanhamento_pedidos.html` | 187 | *(exclusão)* | novo `i-excluir` |
| `moldagens.html` | 156 | *(ir ao pedido)* | `i-ver` |
| `moldagens.html` | 169 | Converter em pedido | novo `i-converter` |
| `moldagens.html` | 179 | *(exclusão)* | `i-excluir` |
| `pedidos_faturamento.html` | 146 | *(link)* | a confirmar na etapa |
| `pedidos_faturamento.html` | 153 | Preencher | `i-editar` (já existe) |
| `pacientes.html` | 155 | Importar | novo `i-importar` |
| `laboratorios.html` | 94 | WhatsApp | novo `i-whatsapp` |
| `detalhe_pedido.html` | 104, 129 | Registrar envio / entrega | `i-enviar` / `i-entregar` |

A infraestrutura necessária **já existe**:

- `.icon-button` em `components.css` (criado na rodada anterior, com
  `aspect-ratio: 1`, `padding: 0` e `svg { margin: 0 }` para centralizar).
- O sprite `templates/partials/icons.html` com 22 símbolos; `i-editar`, `i-alerta`,
  `i-seta`, `i-sincronizar` já em uso.
- O padrão de tooltip por `title=` já aplicado no botão de sincronizar das 4 telas.

Faltam **6 símbolos novos**: `i-ver`, `i-excluir`, `i-enviar`, `i-entregar`,
`i-importar`, `i-converter`, `i-whatsapp` (7, se o WhatsApp entrar).

### 2.4 Propriedades das tabelas (item 4)

Todos os 16 templates com `<table>` já usam `.data-table` dentro de
`.table-wrap.data-table-wrap`. A base compartilhada está em `components.css:1329-1470`:

```
table          width:100%; border-collapse:collapse
th, td         padding:12px 16px; border-bottom:1px solid var(--line); text-align:left
th             font-size:11px; font-weight:500; letter-spacing:0.05em; text-transform:uppercase
td             color:#d8e2f1
.data-table    min-width:920px
.data-table thead th   position:sticky; top:0
```

Medição de estilos computados no navegador (CME/Movimentações, CME/Alunos por turma,
Lab/Acompanhamento, Lab/Faturamento): **idênticos** em `min-width`, família, tamanho,
peso, padding, `line-height`, `text-transform` e `letter-spacing`.

A medição registrou também uma aparente divergência na cor do `td` (CME
`rgb(216,226,241)` vs. Lab `rgb(139,167,204)`) — **e ela não existe**. `rgb(139,167,204)`
é exatamente `--muted: #8ba7cc`, ou seja, a célula amostrada no Lab tinha o texto dentro
de um `<span class="cell-muted">` (`components.css:1430`). A auditoria do CSS confirma:
`td { color: #d8e2f1 }` (`components.css:1359`) é a **única** regra de cor de `td` em
todo o projeto — não há nenhum override por app. Falso positivo de medição, descartado.

As duas apps que faltavam medir não renderizam tabela na URL raiz (por isso a primeira
passagem retornou "sem `.data-table` na tela"):

- **Contratos** — a tabela só aparece **depois de uma busca** de paciente
  (`contratos.html:87`) e na tela de envios pendentes (`envios_dental.html:27`).
- **Identificadores** — a tabela está num parcial carregado sob demanda e nasce
  `hidden` (`partials/_turma_alunos.html:38-39`).

Lendo o CSS das duas:

- `identificadores.css` (443 linhas) **não tem nenhuma regra de tabela**. Herda a base
  integralmente.
- `contratos.css` (942 linhas) tem overrides deliberados, todos escopados a
  `body.gestao-contratos`:
  - `.gc-tabela-pacientes { min-width: 620px; font-size: 0.86rem }` (linha 597) — com
    comentário justificando: 4 colunas só, e 920px forçaria rolagem horizontal em
    desktop de 1280px depois da barra lateral.
  - `.gc-tabela-pacientes td, th { padding: 10px 12px }` (612) — padding reduzido.
  - `.gc-acao-fixa { width: 172px; position: sticky }` (663) — coluna de ação fixa
    própria, escopada para **não** afetar a tabela de envios da mesma app.
  - `body.gestao-contratos td { font-family: var(--gc-mono) }` (68) — **e
    `--gc-mono` é um alias de `var(--font-body)`**, ou seja, esta regra hoje não muda
    nada. É código morto por evolução.

Inventário completo de arquivos CSS do projeto (fora de `staticfiles/`, que é build):
`static/css/{tokens,base,components,portal,auth}.css`,
`gestao_contratos/static/.../contratos.css`, `.../assinatura.css` (telas públicas de
assinatura, sem `data-table`) e `identificadores/.../identificadores.css`. **As apps
`gestao_cme` e `gestao_lab` não têm nenhum CSS próprio.**

**Conclusão importante, e ela contraria a premissa do pedido:** as tabelas **não** estão
"totalmente diferentes para cada tabela". Elas já compartilham uma base única, e as
medições batem. Existem exatamente **duas** divergências no projeto inteiro:

1. `body.gestao-contratos td { font-family: var(--gc-mono) }` — regra morta (`--gc-mono`
   é alias de `--font-body`), deve ser removida;
2. `min-width`/`font-size`/`padding`/coluna fixa em `.gc-tabela-pacientes` (Contratos) —
   divergência **intencional e documentada em comentário**, com justificativa técnica
   válida.

Isto reduz drasticamente o escopo do item 4: de "reescrever as tabelas" para "remover uma
regra morta e transformar a variante compacta num modificador nomeado e reutilizável".
Ver etapa 3 — e, sobretudo, a decisão D-3 em §7, que passa a ser a pergunta central deste
item.

### 2.5 Filtro de faturamento do paciente (item 5)

- Campo no template: `pedidos_faturamento.html:18-22`.
- Leitura e aplicação: `gestao_lab/views.py:465-470`.
- Contexto: `views.py:513`.
- *Chips* de filtro ativo: `pedidos_faturamento.html:43, 54-62, 65, 74, 160`.
- Testes que travam este comportamento: `gestao_lab/tests.py:751`, `:760`, `:781`.

O campo `PedidoMaterial.faturado_paciente` (`models.py:262`) continua existindo e
continua alimentando: o *toggle* por linha (`pedidos_faturamento.html:120-126`), o
formulário de detalhe (`detalhe_pedido.html:155`), a coluna "Faturamento" da listagem
(`acompanhamento_pedidos.html:148`), o `admin.py:83,89` e — crítico —
`calcular_status()` (`models.py:300-307`), que só devolve `CONCLUIDO` quando
`entregue and faturado_paciente and faturado_lab`.

### 2.6 Faturamento condicionado ao orçamento (item 6)

Lógica atual: o faturamento é **liberado pela entrega**. `calcular_status()` devolve
`ENTREGUE_NAO_FATURADO` assim que `entregue=True`, e `save()` (`models.py:308-319`)
deriva `data_faturamento` das duas flags.

Integração atual com o Dental Office (`gestao_lab/integrations/dental.py`) — a classe
`DentalClient` expõe **três** operações:

- `listar_pacientes()` (linha 163)
- `buscar_detalhes_paciente()` (171)
- `enviar_documento_paciente()` (184)

**Não há nenhum endpoint de orçamento ou de pagamento.** Isso confere exatamente com o
que foi dito no pedido ("ainda não foi verificado na API do Dental Office o endpoint que
irá alimentar essa informação"). Ver §3.3 para como isso condiciona a etapa.

### 2.7 Relatório de faturamento por laboratório (item 7)

O modelo a espelhar é o relatório por turma do CME, entregue na rodada anterior:

- `gestao_cme/views.py` → `_exportar_relatorio_alunos_turma(request)`,
  `_gerar_csv_relatorio_turma(...)`, `_status_envio_aluno(...)`.
- `gestao_cme/templates/gestao_cme/alunos_por_turma.html` → painel `<details class="report-panel">`
  com recorte obrigatório (turma), busca por nome, período De/Até e botão de download.
- `components.css` → `.report-panel`, `.report-panel-heading`, `.report-form`, com
  *overrides* na media query de 620px.

Todo esse CSS é genérico e **reutilizável sem alteração**.

---

## 3. Dependências e riscos transversais

### 3.1 O item 2 depende do item 1

Os KPIs do CME vão receber `metric-success` / `metric-warn` / `metric-neutral`. Essas
classes usam cores fixas (turquesa, âmbar, cinza), **não** os tokens `--accent-*`. Ainda
assim, o resultado percebido muda conforme o menu ao lado: aplicar cor aos KPIs antes de
acertar a paleta do menu significa julgar a harmonia contra um fundo que vai mudar em
seguida. Fazer 1 antes de 2 evita refazer o julgamento.

### 3.2 O item 5 é preparação do item 6, não uma limpeza isolada

A justificativa dada para remover o filtro é que o campo "será preenchido
automaticamente e, por consequência, todos os pedidos deverão ter sido faturados para os
pacientes". Isto é uma consequência direta da lógica do item 6: se o pedido só pode ser
aberto contra um orçamento **pago**, então `faturado_paciente` deixa de ser um estado a
acompanhar e vira um invariante.

Consequência prática: **a etapa 5 remove o filtro, mas não deve remover o campo, nem o
toggle, nem alterar `calcular_status()`.** Enquanto a etapa 7 (item 6) não estiver no ar,
existem pedidos legados com `faturado_paciente=False`, e mexer no cálculo de status
agora mudaria retroativamente o status de pedidos históricos. Isso é uma alteração de
regra de negócio disfarçada de limpeza de interface — fora de escopo aqui.

### 3.3 O item 6 não pode ser concluído nesta rodada — e isso é do enunciado

O pedido é explícito: *"Ainda não foi verificado na API do Dental Office o endpoint que
irá alimentar essa informação de orçamento, porém, é necessário começar a elaboração
dessa lógica dentro do sistema."*

O plano trata isso desenhando a etapa em **duas fases separadas por uma fronteira de
adaptador**:

- **Fase A (executável agora)** — todo o desenho interno: um `Orcamento` como estrutura
  de dados própria da aplicação, um protocolo `FonteDeOrcamentos` com uma implementação
  *stub* configurável, a regra de bloqueio na abertura do pedido, a mensagem de
  indisponibilidade, os testes. Nada disso depende do endpoint real.
- **Fase B (bloqueada)** — a implementação concreta que fala com o Dental Office. Um
  único arquivo, escrito quando o endpoint for conhecido.

O risco a nomear: **o formato do orçamento real pode não caber no modelo desenhado na
fase A.** Mitigação — manter a estrutura interna mínima (identificador, descrição, valor,
data, *pago sim/não*) e converter no adaptador, nunca deixar o formato da API vazar para
as views. Se o endpoint devolver algo estruturalmente diferente (por exemplo, parcelas em
vez de um booleano de pagamento), a fase A continua válida e só o adaptador muda.

**Recomendação:** não colocar a fase A em produção com o *stub* ligado. Ela entra atrás
de um interruptor de configuração desligado por padrão, para que o comportamento
observado hoje pelos colaboradores não mude até a fase B existir.

### 3.4 O item 4 parte de uma premissa que a auditoria não confirmou

O pedido descreve "diferenças claras no layout, fonte, tamanho de fonte e outras
propriedades que são totalmente diferentes para cada tabela". A auditoria de §2.4 não
encontra isso: as 16 tabelas compartilham uma base única em `components.css`, as apps
CME e Lab não têm CSS próprio, Identificadores não tem regra de tabela nenhuma, e a
única app com override é Contratos — com duas regras, uma delas morta.

Duas leituras possíveis, e elas levam a trabalhos diferentes:

- **(i) A percepção vem de outra coisa que não o CSS da tabela.** Número de colunas,
  densidade de informação por célula (o Lab empilha `<strong>` + `.cell-muted` em quase
  toda célula; Identificadores tem três colunas de texto simples), presença ou não de
  *badges* e de coluna de ações. Nesse caso o problema é de **composição das tabelas**,
  não de propriedades CSS — e a solução é padronizar como a informação é montada dentro
  da célula, não os valores de `font-size`.
- **(ii) A expectativa é uma reforma de legibilidade** — densidade, hierarquia, telas
  estreitas. Trabalho legítimo e maior, já catalogado como decisão em aberto em
  `avaliacao-visual-padronizacao-frontend.md`.

A etapa 3 como está escrita entrega o que é literalmente verificável hoje. **Vale decidir
D-3 antes de iniciá-la**, porque nas leituras (i) e (ii) o conteúdo da etapa muda por
completo.

### 3.5 Restrições permanentes do projeto (valem para todas as etapas)

- Não alterar regra de negócio nem fluxo funcional em etapas de aparência.
- Não alterar contratos de URL nem nomes de rota.
- Preferir reuso a duplicação.
- **Código cujo uso não puder ser confirmado é marcado para revisão, nunca excluído
  automaticamente.** (A regra `--gc-mono` em `td` é uma exceção confirmada: é
  demonstravelmente um alias de `--font-body`, portanto sem efeito.)

---

## 4. As etapas

Cada etapa é um commit revisável, com verificação própria. Nenhuma depende de uma etapa
posterior.

### Etapa 1 — Paleta ABO no menu (item 1)

**Objetivo.** As quatro apps usarem a mesma paleta de acento no menu lateral, tomando a
Gestão de Pedidos de Laboratório como referência.

**Mudança.** Aplicar os tokens de acento hoje escopados em `.app-lab` a Contratos, CME e
Identificadores. Duas rotas possíveis:

- *(a)* promover os cinco tokens turquesa para o `:root` de `tokens.css` e remover o
  bloco `.app-lab`, ficando a paleta ABO como padrão do painel inteiro;
- *(b)* manter o bloco e adicioná-lo às demais classes de body, criando `body_class`
  onde falta.

**Recomendação: (a).** Se a paleta ABO é a correta para todas as apps, um override por
app é justamente a duplicação que o projeto vem eliminando. A rota (b) preserva a
possibilidade de cores por app — mas essa possibilidade é exatamente o que o item pede
para acabar.

**Arquivos.** `static/css/tokens.css`; possivelmente
`gestao_lab/templates/gestao_lab/base.html:9` (remover a classe, se rota (a)).

**Impacto.** Os tokens `--accent-*` são consumidos em mais lugares que o menu (foco de
formulário, links, anéis de destaque). A mudança **é global e proposital**, mas precisa
ser inspecionada além do menu.

**Verificação.** Levantar todos os consumidores de `--accent-*` no CSS antes de mudar;
capturar tela do menu e de um formulário com foco nas quatro apps, antes e depois.

**Risco.** Baixo. Reversível num commit. **Esforço:** pequeno.

---

### Etapa 2 — KPIs coloridos na Visão Geral do CME (item 2)

**Objetivo.** Os KPIs do CME usarem a mesma variação de cores do Lab, em vez de só o
vermelho.

**Mudança.** Em `dashboard_cme.html:35-53`, atribuir a cada card a classe cuja semântica
corresponda ao que ele conta:

| Card | Hoje | Proposto | Semântica |
|---|---|---|---|
| Total | *(sem cor)* | `metric-blue` | informativo |
| Retirados | *(sem cor)* | `metric-success` | fluxo concluído |
| Aguardando | `danger-metric` | `metric-warn` | requer ação, não é falha |
| Sem status | *(sem cor)* | `metric-neutral` | registro antigo, sem valor operacional |

A troca de `danger-metric` por `metric-warn` em "Aguardando" merece confirmação: no Lab,
o vermelho é reservado a **atrasado** (prazo vencido) e o âmbar a "falta faturar". Um
pacote aguardando retirada é mais próximo do segundo caso. Se a coordenação entende
"aguardando" como situação crítica, mantém-se o vermelho — é uma decisão de leitura, não
técnica. **Na ausência de resposta, aplico `metric-warn`** e registro a suposição.

Aproveitar para resolver a divergência de §2.2: acrescentar `metric-card--link` aos
quatro cards do Lab, já que também são links.

**Arquivos.** `gestao_cme/templates/gestao_cme/dashboard_cme.html`,
`gestao_lab/templates/gestao_lab/dashboard.html`.

**Impacto.** Nenhum no backend. Nenhuma classe CSS nova.

**Verificação.** Captura de tela lado a lado das duas Visões Gerais.

**Risco.** Muito baixo. **Esforço:** muito pequeno.

---

### Etapa 3 — Baseline único de tabelas (item 4)

**Objetivo.** Uma única definição de tabela para as quatro apps, com as divergências
restantes explícitas, nomeadas e justificadas.

> **Leia §2.4 e a decisão D-3 antes de começar.** A auditoria mostrou que a base já é
> comum e que só existem duas divergências reais em todo o projeto. Esta etapa entrega
> a padronização pedida, mas ela é pequena — se o esperado era uma reforma de leitura
> das tabelas, isso é outro trabalho, descrito na variante ampliada abaixo.

**Mudança (escopo confirmado).**

1. **Remover `body.gestao-contratos td { font-family: var(--gc-mono) }`**
   (`contratos.css:68`), comprovadamente sem efeito por `--gc-mono` ser alias de
   `--font-body`. Confirmar a equivalência no navegador antes de remover, e manter os
   demais seletores da mesma regra (`.gc-mono`, `.info-chip strong`, `.cell-muted`
   etc.), que **têm** efeito.
2. **Promover a variante compacta de Contratos a modificador nomeado.** Substituir
   `body.gestao-contratos .gc-tabela-pacientes` por `.data-table--compacta` em
   `components.css` (min-width 620px, fonte 0.86rem, padding 10px 12px), disponível para
   qualquer app com tabela de poucas colunas. A coluna fixa (`.gc-acao-fixa`) permanece
   em `contratos.css` — é específica daquela tela, e o comentário existente já explica
   por quê.
3. **Documentar o baseline** numa seção de `components.css`, listando as propriedades
   canônicas (as de §2.4) e os modificadores permitidos, para que a próxima tabela nasça
   padronizada em vez de acumular um override novo.

**Variante ampliada (só se D-3 apontar para reforma).** Além do acima: revisão da
densidade (padding 12px/16px), da hierarquia visual entre a informação principal do `td`
e a `.cell-muted` secundária, e do comportamento em telas estreitas — hoje resolvido por
rolagem horizontal (`min-width: 720px` abaixo de 980px), que é a decisão em aberto
registrada em `avaliacao-visual-padronizacao-frontend.md`. Isso triplicaria o esforço e a
superfície de risco, e por isso **não** está incluído por padrão.

**Arquivos.** `static/css/components.css`,
`gestao_contratos/static/gestao_contratos/css/contratos.css`,
`gestao_contratos/templates/gestao_contratos/contratos.html` (troca de nome de classe).

**Impacto.** No escopo confirmado, o impacto **visual** é praticamente nulo — as duas
mudanças são uma regra sem efeito e uma renomeação de classe. O ganho é de manutenção:
uma variante reutilizável em vez de um override escondido, e um baseline documentado.
Isso deve ser dito com clareza para que o resultado não decepcione.

**Verificação.** Medir os estilos computados de `th`/`td` nas 16 telas antes e depois —
mesmo método que produziu §2.4, **amostrando o `td` e não o `span` interno**, que foi o
erro corrigido em §2.4 — e conferir que nada mudou. Para Contratos e Identificadores,
lembrar que é preciso **executar a busca / selecionar a turma** para a tabela existir.

**Risco.** Baixo. **Esforço:** pequeno (escopo confirmado) / grande (variante ampliada).

---

### Etapa 4 — Botões de ícone nas tabelas do Lab (item 3)

**Objetivo.** Ações por linha viram botões de ícone com o rótulo revelado no *hover*,
reduzindo a largura da coluna "Ações".

**Mudança.**

1. Acrescentar 6-7 símbolos a `templates/partials/icons.html` (§2.3), no mesmo traço dos
   existentes (24×24, `stroke`, sem preenchimento).
2. Converter os botões listados em §2.3 para `.icon-button`, cada um com `title=` (mesmo
   mecanismo de *tooltip* dos botões de sincronizar) **e** `aria-label=` — um ícone sem
   nome acessível é invisível para leitor de tela.
3. Manter como texto os botões de formulário ("Buscar", "Limpar tudo", "Salvar",
   "Cancelar", "Registrar pedido") — são ações de página.
4. Para o botão de exclusão, manter `.danger-button` combinado a `.icon-button`, e
   preservar a confirmação existente.

**Arquivos.** `templates/partials/icons.html`; 6 templates do `gestao_lab`;
`static/css/components.css` apenas se aparecer um ajuste de agrupamento
(`.actions-group` já existe, linha 1462).

**Impacto.** Nenhum no backend — os `<form>` e as URLs continuam idênticos.
Perda de legibilidade para quem não conhece os ícones é o risco real de usabilidade;
o *tooltip* mitiga, mas não elimina.

**Verificação.** Comparar a largura da coluna "Ações" antes/depois em cada tela;
conferir que todo ícone tem `aria-label`; percorrer as 6 telas no navegador acionando
cada botão convertido, para garantir que nenhum `type=submit` ou `formaction` se perdeu
na conversão.

**Risco.** Baixo tecnicamente, médio em usabilidade. **Esforço:** médio.

**Sugestão:** aplicar primeiro em `acompanhamento_pedidos.html`, revisar o resultado, e
só então replicar nas outras cinco — a tela de acompanhamento tem a maior variedade de
ações e serve de piloto.

---

### Etapa 5 — Remover o filtro "faturado pelo paciente" (item 5)

**Objetivo.** Retirar da tela de faturamento o filtro que deixará de fazer sentido
quando o campo for preenchido automaticamente.

**Mudança.**

- Remover o `<select name="faturado_paciente">` (`pedidos_faturamento.html:18-22`).
- Remover a leitura e a aplicação em `views.py:465-470` e a chave de contexto em `:513`.
- Remover o *chip* correspondente e ajustar as condições de "Limpar tudo" e os `href`
  dos demais *chips*, que hoje repassam `faturado_paciente` (linhas 43, 47, 54-62, 65,
  74, 160).
- Remover os testes `test_filtra_por_faturado_paciente_sim` (`tests.py:751`) e
  `..._nao` (`:760`), e ajustar o teste combinado em `:781`.

**Explicitamente fora de escopo** (ver §3.2): o campo `faturado_paciente`, o *toggle* por
linha, o formulário de detalhe, a coluna "Faturamento" da listagem, o `admin.py` e
`calcular_status()` — tudo permanece.

**Arquivos.** `gestao_lab/templates/gestao_lab/pedidos_faturamento.html`,
`gestao_lab/views.py`, `gestao_lab/tests.py`.

**Impacto.** Um parâmetro de *query string* deixa de ser interpretado. Links salvos que
o contenham continuam abrindo a página, agora sem o recorte — degradação silenciosa,
aceitável para um filtro de tela interna.

**Verificação.** Suíte completa do `gestao_lab`; abrir a tela com
`?faturado_paciente=sim` na URL e confirmar que não quebra.

**Risco.** Baixo. **Esforço:** pequeno.

---

### Etapa 6 — Relatório de faturamento por laboratório (item 7)

**Objetivo.** O colaborador baixar um relatório completo dos faturamentos de um
laboratório, em aberto ou não — espelhando o relatório por turma do CME.

**Mudança.** Reproduzir a estrutura de §2.7 no `gestao_lab`:

- Painel `<details class="report-panel">` na tela de faturamento, com **laboratório
  obrigatório** (o recorte, equivalente à turma), busca por paciente/aluno e período
  De/Até com seletor de campo de data — a tela de faturamento já tem os três campos de
  data (registro, entrega, vencimento) e o widget `partials/filtro_periodo.html`
  suporta isso.
- Uma rota de exportação e as funções de geração do CSV, no mesmo padrão de
  `_exportar_relatorio_alunos_turma`. Como a rodada de limpeza criou
  `gestao_lab/services/consultas.py`, a montagem das linhas vai **para lá**, não para a
  view — corrigindo, de saída, o débito que o CME ainda carrega (lá as funções ficaram
  em `views.py`).

**Decisão de escopo a registrar:** "todos os faturamentos (em aberto ou não)" é mais
amplo do que a tela de faturamento mostra hoje — ela filtra
`entregue=True` e exclui os já totalmente faturados (`views.py:450-452`). O relatório
deve consultar **todos** os pedidos do laboratório no período, incluindo os concluídos,
com uma coluna de situação. Ou seja: o relatório não é "exportar a listagem visível", é
uma consulta própria. **Sigo com essa interpretação**, que é a leitura literal do pedido.

**Arquivos.** `gestao_lab/urls.py` (uma rota nova), `gestao_lab/views.py`,
`gestao_lab/services/consultas.py`, `gestao_lab/templates/gestao_lab/pedidos_faturamento.html`,
`gestao_lab/tests.py`. **Nenhum CSS novo** — `.report-panel` e `.report-form` já existem.

**Impacto.** Aditivo. Nenhuma rota ou comportamento existente muda.

**Verificação.** Testes cobrindo: laboratório obrigatório; recorte por período;
inclusão dos pedidos já concluídos; cabeçalho e codificação do CSV; comportamento com
laboratório sem pedidos no período.

**Risco.** Baixo. **Esforço:** médio.

---

### Etapa 7 — Orçamento do Dental Office como pré-requisito do pedido (item 6)

**Objetivo.** Trocar o gatilho do faturamento: em vez de a entrega liberar os campos, o
pedido só pode ser aberto contra um orçamento **pago** do paciente no Dental Office.

Executada em duas fases (ver §3.3). **Só a fase A é executável nesta rodada.**

#### Fase A — desenho interno (executável)

1. **Estrutura de dados própria.** Um `Orcamento` (dataclass) com o mínimo:
   identificador, descrição, valor, data e situação de pagamento. Formato interno da
   aplicação, deliberadamente independente do que a API vier a devolver.
2. **Fronteira de adaptador.** Um protocolo `FonteDeOrcamentos` com um único método —
   listar os orçamentos de um paciente — e duas implementações: um *stub* configurável
   (para desenvolvimento e testes) e, na fase B, a real. A escolha vem de configuração.
3. **Regra de negócio.** Na seleção do paciente durante a abertura do pedido
   (`form_pedido.html` / `criar_pedido`), consultar a fonte e apresentar os orçamentos.
   Orçamento pago → permite abrir o pedido vinculado a ele. Não pago → bloqueia, com
   mensagem explicando o motivo. Sem orçamento algum ou fonte indisponível → mensagem
   distinta (indisponibilidade ≠ negativa).
4. **Vínculo persistido.** Um campo no `PedidoMaterial` guardando o identificador do
   orçamento de origem (migração aditiva, `null=True` — os pedidos existentes não têm
   orçamento e precisam continuar válidos).
5. **Interruptor de configuração**, desligado por padrão. Com ele desligado, o fluxo de
   abertura de pedido é **byte-a-byte o de hoje**.
6. **Testes** da regra contra o *stub*: pago, não pago, sem orçamento, fonte fora do ar,
   interruptor desligado.

#### Fase B — adaptador real (bloqueada)

Escrita quando o endpoint for conhecido: um método novo em `DentalClient` seguindo o
padrão dos existentes (`_get_autenticado`, retry, a hierarquia de `DentalAPIError`), mais
a conversão para `Orcamento`. Um arquivo, mais testes de conversão.

**Impacto.** É a etapa mais invasiva do plano: toca modelo (migração), fluxo de abertura
de pedido e integração externa. O interruptor desligado é o que a torna segura de
implantar.

**Questões que precisam de resposta antes da fase B** (registradas, sem bloquear a
fase A):

- Um pedido corresponde a **um** orçamento, ou um orçamento pode gerar vários pedidos?
- Pagamento parcelado conta como "pago"?
- Com a regra ativa, `faturado_paciente` passa a nascer `True` — e o que acontece com os
  pedidos legados que estão `False`? (Ligado ao §3.2.)
- O bloqueio é rígido, ou existe uma exceção autorizada para casos excepcionais?

**Risco.** Alto (fase A: médio). **Esforço:** grande.

---

## 5. Impacto consolidado

| Área | Etapas que tocam | Observação |
|---|---|---|
| `tokens.css` | 1 | Tokens globais — atinge as 4 apps |
| `components.css` | 3, 4 | Baseline de tabela + modificador compacto |
| `contratos.css` | 3 | Remoção de regra morta + migração de classe |
| Templates CME | 2 | Só classes de KPI |
| Templates Lab | 2, 4, 5, 6 | Maior concentração de mudanças |
| Templates Contratos | 3 | Só troca de nome de classe |
| Templates Identificadores | 1 | Só `body_class` |
| `gestao_lab/views.py` | 5, 6, 7 | — |
| `gestao_lab/services/` | 6, 7 | Consultas e nova fonte de orçamentos |
| `gestao_lab/models.py` | 7 | **Única migração do plano** |
| `gestao_lab/integrations/dental.py` | 7 (fase B) | Bloqueado |
| `gestao_lab/tests.py` | 5, 6, 7 | — |

**Nenhuma etapa altera contrato de URL existente.** A etapa 6 acrescenta uma rota; a
etapa 5 deixa de interpretar um parâmetro de *query string*.

**Uma única migração** em todo o plano (etapa 7, aditiva e anulável).

## 6. Verificação por etapa

| Etapa | Método |
|---|---|
| 1 | Levantamento dos consumidores de `--accent-*` + capturas antes/depois nas 4 apps |
| 2 | Captura lado a lado das duas Visões Gerais |
| 3 | Medição de estilos computados nas 16 telas com tabela, antes e depois |
| 4 | Largura da coluna Ações antes/depois; auditoria de `aria-label`; acionamento manual de cada botão convertido |
| 5 | Suíte `gestao_lab` + URL legada com o parâmetro removido |
| 6 | Testes novos de exportação (5 cenários) |
| 7 | Testes da regra contra o *stub* (5 cenários) + confirmação de que, com o interruptor desligado, o fluxo atual não muda |

Em todas as etapas: `ruff` comparado antes/depois pelo método de `git stash` (rodar fora
do projeto altera a resolução de módulos de primeira parte e produz comparação falsa) e a
suíte completa antes do commit.

## 7. Decisões pendentes

Registradas para resposta; nenhuma bloqueia o início do plano.

| # | Decisão | Etapa | Se não houver resposta |
|---|---|---|---|
| D-1 | Paleta ABO vira padrão do `:root` (rota (a)) ou continua como override por app (rota (b))? | 1 | Sigo com (a) |
| D-2 | "Aguardando" no CME é crítico (vermelho) ou requer ação (âmbar)? | 2 | Sigo com âmbar |
| D-3 | **A mais importante.** O item 4 parte de uma premissa que a auditoria não confirmou (§3.4). O esperado é a padronização descrita, a padronização da *composição* das células, ou uma reforma de legibilidade? | 3 | Sigo com a padronização descrita, e sinalizo que o efeito visual será mínimo |
| D-4 | O botão de WhatsApp em Laboratórios vira ícone? (é a ação mais reconhecível por texto) | 4 | Converto, com `title` e `aria-label` |
| D-5 | As quatro perguntas de negócio sobre orçamento (§ etapa 7) | 7, fase B | Fase A não depende delas |

Pendências herdadas de rodadas anteriores, ainda em aberto e **não** endereçadas por este
plano: o conflito de nomenclatura "sincronizar" vs. "atualizar"
(`documentacao-portal-contas.md` §2.2); a rota `contrato_baixar` (DOCX) órfã; a
manutenção de `contrato_baixar_carimbo_tempo`.
