# Auditoria Visual — Padronização de Front-end (todas as aplicações)

> Etapa 9 do plano de limpeza de código (`docs/plano-limpeza-codigo.md`). Diferente das
> auditorias visuais anteriores (focadas em uma única aplicação, ex.:
> `documentacao-gestao-cme.md` §11.1/§11.2), esta rodada compara as **5 aplicações entre
> si** — Portal, Gestão de CME, Gestão de Laboratório, Gestão de Contratos e
> Identificadores de Bancada — procurando inconsistências de botões, cores, tipografia,
> espaçamento, tabelas e navegação entre telas equivalentes.
>
> Metodologia: Playwright autenticado (usuário `visualqa`), capturas de tela inteira em
> desktop (1440×900) e mobile (390×844), 12 telas por viewport (24 capturas no total).
> Cada achado abaixo foi confirmado tanto pela captura de tela quanto pelo código-fonte
> (CSS/template) correspondente — não é uma impressão visual isolada. Evidências em
> `docs/assets/avaliacao-visual-frontend/`.

## Resumo

A base visual do projeto está sólida e consistente na maior parte — tipografia, cores de
fundo, botões, tabelas e formulários usam o mesmo design system (`tokens.css`/
`components.css`) em todas as telas comparadas. Os achados abaixo são pontuais, não
estruturais, e nenhum deles quebra o uso do sistema.

## Achados

### 1 · Sistema de "acento por aplicação" (wayfinding) só está implementado em 1 de 4 apps

`static/css/tokens.css` já prevê, deliberadamente, uma cor de destaque diferente por
aplicação para ajudar o usuário a perceber em qual sistema está — o próprio CSS tem o
comentário `/* Acento por aplicação (wayfinding entre sistemas) */` e uma classe
`.app-lab` que troca a cor de destaque padrão (azul, `#27baff`) para um turquesa
(`#67f9e0`). Na prática:

- **`gestao_lab`** aplica `body_class = "app-lab"` (`gestao_lab/templates/gestao_lab/base.html`)
  → recebe o acento turquesa corretamente (item de menu ativo, foco do campo de busca).
- **`gestao_contratos`** define `body_class = "gestao-contratos"`
  (`gestao_contratos/templates/gestao_contratos/base.html`), mas **não existe nenhuma
  regra `.gestao-contratos` em `tokens.css`** — a classe está no HTML sem efeito nenhum,
  então o app usa o azul padrão do `:root`.
- **`gestao_cme`** e **`identificadores`** nunca definem `body_class` — também caem no
  azul padrão.

Ou seja: a intenção de "wayfinding por cor" existe no design system, mas só 1 das 4
aplicações de fato a usa. Evidência: `docs/assets/avaliacao-visual-frontend/2-acento-cme-vs-lab.png`
(item de menu ativo e campo de busca, CME em azul × Laboratório em turquesa).

**Recomendação:** decidir com o time se o wayfinding por cor deve continuar (e então
definir uma cor para Contratos e Identificadores, e corrigir a classe órfã
`gestao-contratos`) ou ser abandonado (e então remover `.app-lab`/`body_class="app-lab"`
para que todos os apps fiquem visualmente iguais, de propósito). Qualquer uma das duas
opções resolve a inconsistência — hoje ela não foi decidida, só ficou pela metade.

### 2 · Rótulo acima do título da página ("eyebrow") não segue a mesma convenção

Comparando o cabeçalho das quatro aplicações
(`docs/assets/avaliacao-visual-frontend/1-eyebrow-comparacao.png`):

| App | Texto do eyebrow |
|---|---|
| Gestão de CME | `CONTROLE DE MATERIAIS` |
| Gestão de Laboratório | `GESTÃO DE LABORATÓRIO` |
| Gestão de Contratos | `ABO GOIÁS` |
| Identificadores | `ABO GOIÁS` |

CME e Laboratório nomeiam o próprio módulo (reforça onde o usuário está); Contratos e
Identificadores repetem o nome da instituição, perdendo essa informação. Não é um erro
visual (a hierarquia e a cor do texto são idênticas nos quatro), só uma inconsistência de
conteúdo — fácil de padronizar trocando o texto de duas páginas.

### 3 · Texto do indicador de progresso (stepper) truncado em Gestão de Contratos

Na tela `/contratos/` (raiz), o passo 2 do indicador "Buscar → Confirmar e gerar →
Assinar → Enviar" aparece cortado como **"Confirm…"** no desktop
(`docs/assets/avaliacao-visual-frontend/3-stepper-truncado-contratos.png`). Causa
confirmada em `gestao_contratos/static/gestao_contratos/css/contratos.css`:
`.step-label` tem `white-space: nowrap; overflow: hidden; text-overflow: ellipsis`, mas a
largura reservada para o rótulo não acomoda "Confirmar e gerar" (17 caracteres) como
acomoda os demais rótulos, mais curtos (7–8 caracteres). No mobile o problema não aparece
porque os rótulos de texto são ocultados por completo, restando só os números — o que
mascara o bug em vez de resolvê-lo.

**Recomendação:** aumentar a largura reservada ao rótulo do passo 2 (ou reduzir levemente
o `font-size`/`letter-spacing` só nesse breakpoint), sem mudar a lógica do stepper.

### 4 · Tabelas de listagem não se adaptam bem a telas estreitas (achado comum às apps testadas)

Em telas de 390px (mobile), tanto `gestao_cme` (`Movimentações`) quanto `gestao_lab`
(`Acompanhamento`) mostram a mesma limitação: as colunas da tabela encolhem e o texto
quebra em várias linhas dentro de células estreitas, dificultando a leitura (nomes de
aluno cortados em 2-3 linhas, coluna de Ações espremida na borda) — sem um scroll
horizontal percebido nem um layout alternativo (cards empilhados) para a tela pequena.
Evidências: `docs/assets/avaliacao-visual-frontend/4-mobile-tabela-cme.png` e
`5-mobile-tabela-lab.png`.

Isso **não é uma inconsistência entre apps** — o comportamento é igual nas duas, porque
usam o mesmo componente de tabela compartilhado (`components.css`). É uma limitação de
responsividade do componente em si, que afeta todas as listagens do projeto igualmente.

**Recomendação:** tratar como um item de UX à parte (não uma inconsistência de
padronização) — vale decidir entre duas linhas: (a) scroll horizontal explícito da
tabela em telas estreitas (mantendo as colunas do tamanho normal), ou (b) um layout de
cards empilhados para mobile, específico para listagens. Qualquer uma das duas exige
CSS novo no componente compartilhado, beneficiando todos os apps de uma vez.

### 5 · Agrupamento da navegação lateral inconsistente entre apps

A barra lateral de `gestao_lab` agrupa os itens em três seções com cabeçalho
("OPERAÇÃO", "CADASTROS", "PESSOAS"); as barras laterais de `gestao_cme`,
`gestao_contratos` e `identificadores` usam uma lista simples, sem agrupamento. Isso não
chega a atrapalhar a navegação (os apps têm poucos itens cada), mas é uma diferença de
padrão perceptível ao alternar entre sistemas.

**Recomendação:** decidir se o agrupamento por seção deve virar o padrão de todos os apps
com navegação mais longa (CME, com 7 itens, é a candidata mais óbvia), ou se
`gestao_lab` deve voltar à lista simples por consistência — de novo, qualquer escolha
resolve, o que falta é decidir.

## O que já está bem padronizado (confirmado, não precisa de ação)

- Cabeçalho (logo, eyebrow, título, menu do usuário): estrutura, tamanho e alinhamento
  idênticos nas quatro aplicações — só o texto do eyebrow diverge (achado 2).
- Botões primário/secundário, cards, badges de status, chips de filtro, modais de
  confirmação e paginação: mesmo componente, mesmo visual, em todas as telas
  comparadas.
- Mini-menu de cadastro (`Cadastrar kit`, submenu expansível): funciona de forma
  idêntica em CME e Laboratório.
- Rodapé ("Associação Brasileira de Odontologia de Goiás"): idêntico em todas as
  páginas testadas, desktop e mobile.
- Adaptação geral mobile (empilhamento de sidebar acima do conteúdo, botões de largura
  total): consistente nas quatro aplicações — a única lacuna real de mobile é a tabela
  (achado 4), não o layout geral da página.

## Pendências (decisões antes de implementar)

1. Manter ou abandonar o wayfinding por cor entre apps (achado 1) — decide se Contratos e
   Identificadores ganham cor própria, ou se o acento único de Laboratório é removido.
2. Confirmar o texto de eyebrow para Contratos e Identificadores (achado 2) — sugestão:
   "GESTÃO DE CONTRATOS" e "IDENTIFICADORES DE BANCADA", espelhando o padrão de CME/Lab.
3. Decidir a estratégia de tabela em mobile (achado 4) — scroll horizontal ou cards
   empilhados — antes de tocar no componente compartilhado, já que afeta todas as
   listagens do projeto de uma vez.
4. Decidir se o agrupamento por seção da navegação lateral (achado 5) vira padrão do
   projeto ou é revertido em `gestao_lab`.

Nenhuma correção foi aplicada nesta rodada — é levantamento, como as demais etapas do
plano de limpeza. O achado 3 (stepper truncado) é o único puramente técnico, sem
decisão de produto pendente — pode ser corrigido a qualquer momento sem validação
adicional.
