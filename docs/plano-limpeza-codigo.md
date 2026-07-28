# Plano de Limpeza de Código — Painel ABO Goiás

> Levantamento completo da árvore do projeto (`abo-goias/`), cobrindo estrutura de
> arquivos, código Python, templates, estáticos, views, models, forms, URLs, migrations,
> arquitetura, performance e segurança. Todos os achados abaixo foram **verificados
> diretamente no código atual** (grep, AST, `ruff`), não apenas inferidos — quando um
> item não pôde ser confirmado com certeza, ele é listado como "candidato" e marcado
> para revisão manual, nunca como remoção automática. Nenhuma alteração foi feita neste
> documento — é só o levantamento e o plano; a execução acontece nas etapas descritas em
> §16, uma de cada vez, com revisão entre elas.

---

## 1. Limpeza da estrutura do projeto

**Resultado principal: a árvore de arquivos está bem mais limpa do que o normal para um
projeto deste tamanho.** Não há telas duplicadas, versões antigas de arquivos, scripts
temporários commitados, nem imagens/CSS/JS órfãos — foram verificados um a um.

### 1.1 Arquivos não utilizados (verificado)

| Item | Status |
|---|---|
| Templates de cada app (`gestao_cme`, `gestao_lab`, `gestao_contratos`, `contas`) | ✅ Nenhum órfão — todos os `.html` são referenciados por `render()`, `{% extends %}` ou `{% include %}` |
| Templates compartilhados (`templates/partials/*`, `templates/layouts/*`, `templates/base.html`) | ✅ Todos usados (14 a 27 referências cada) |
| CSS (`static/css/*.css`, CSS próprio de `gestao_contratos`/`identificadores`) | ✅ Nenhum arquivo órfão; sobreposição de seletores com o design system compartilhado é mínima (achei 1 só: `.status-seg`) |
| JavaScript (`app.js`, `htmx.min.js`, `contratos.js`) | ✅ Todos referenciados |
| Imagens (`logo.png`, único arquivo de imagem do projeto) | ✅ Usado em 3 lugares |
| Ícones/fontes | Não há arquivos próprios — ícones são SVG inline (`partials/icons.html`), fontes vêm de variáveis CSS já centralizadas |
| Migrations | Nenhuma vazia/no-op suspeita; contagem por app é razoável para o volume de mudanças já feito (`gestao_cme`: 15, `gestao_lab`: 12, `gestao_contratos`: 16, `contas`: 1, `identificadores`: 0) |
| Arquivos temporários/scripts soltos no repo | Nenhum encontrado (`__pycache__`, `db.sqlite3`, `staticfiles/` corretamente no `.gitignore`, nada commitado) |
| Nomes suspeitos (`*old*`, `*backup*`, `*_v2*`, `*copy*`) | Nenhum — só falsos positivos (ex.: `templates_pptx`, `carimbo_tempo.py`) |

### 1.2 Candidatos à remoção (revisar antes de excluir)

Nenhum **arquivo inteiro** é candidato a remoção — o achado real de "código morto" está
em nível de **função/rota específica**, não de arquivo (ver §2.1). A única observação de
estrutura é cosmética: 12 arquivos `.py` têm um BOM (`\xEF\xBB\xBF`) no início, enquanto
os demais não têm — inconsistência de encoding sem efeito funcional (Python 3 lida com
BOM automaticamente), mas vale normalizar por padronização:
`gestao_cme/{views,tests,apps,urls}.py`, `gestao_cme/services/{migracao_legado,eduq_sync}.py`,
`gestao_cme/management/commands/{migrar_dados_legado,sincronizar_eduq}.py`,
`gestao_contratos/tests.py`, `identificadores/views.py`, `abo_goias/{settings,urls}.py`.

---

## 2. Limpeza do código Python

`ruff check` (imports não usados, variáveis mortas, redefinições) encontrou **um único
apontamento em todo o projeto** (`gestao_lab/views.py:61`, nome de variável ambíguo `l`).
Isso confirma que não há imports órfãos, variáveis mortas ou redefinições acumuladas —
acho que vale destacar isso porque é incomum e é um sinal de que as rodadas de auditoria
anteriores já fizeram esse trabalho de base.

### 2.1 Funções/rotas nunca chamadas (verificado, candidatos à remoção)

| Função/rota | App | Evidência | Desfecho (Etapa 3) |
|---|---|---|---|
| `alternar_retirado` (`/gestao-cme/<pk>/alternar-retirado/`) | `gestao_cme` | Nenhum template menciona a rota nem a palavra "alternar"; nenhum teste cobre a view | **Removida** — o histórico do repositório confirma que nunca esteve em template nenhum |
| `baixar_contrato_pdf_view` (`contrato_baixar_pdf`) | `gestao_contratos` | Só aparece em testes (`reverse(...)`); nenhum `redirect()` ou template usa | **Removida** (com seus 2 testes) |
| `buscar_paciente_dental` (`lab_buscar_paciente`, singular) | `gestao_lab` | Já documentado (achado S-02); confirmado que só a versão unificada (`lab_buscar_pacientes`) é usada | **Removida** (com seus 2 testes e a constante `_DESTINOS_VALIDOS`, que só ela usava) |
| `contrato_baixar_carimbo_tempo` | `gestao_contratos` | Já documentado (CT-02); download avulso removido de propósito da tela, rota/view continuam existindo | **Mantida** — ver justificativa abaixo |

**Correção de uma evidência deste levantamento:** a linha do `contrato_baixar_pdf` dizia
que "a versão DOCX é a única linkada na tela". Isso está errado — o que a tela linka é
`contrato_baixar_assinado` (o contrato **assinado**). A rota da DOCX
(`contrato_baixar`) está tão órfã quanto a do PDF: também só aparece em testes. Ela
**não** foi removida por não constar da lista aprovada; fica como candidata para a
próxima rodada, junto com a decisão de manter ou não um caminho de download do documento
original (pré-assinatura), hoje inacessível pela interface em ambos os formatos.

**Por que `contrato_baixar_carimbo_tempo` ficou:** o botão saiu da tela em `7098d8f` com
uma justificativa específica — "o colaborador da recepção não tem como avaliar a
validade/uso desse arquivo isoladamente". Isso é um argumento para tirar da recepção, não
necessariamente do sistema. E o achado **CT-02 segue aberto**: a falha ao embutir o
carimbo no PDF é silenciosa, e é exatamente nesse cenário que o `.tsr` avulso passa a ser
a única evidência do carimbo. Como o arquivo é material probatório de um contrato
assinado, manter a rota (17 linhas já testadas) custa pouco perto de perder o acesso
prático a ele. Reavaliar depois que CT-02 for corrigido.

### 2.2 Duplicação de lógica entre apps (verificado)

**Prioridade alta — padrão de redirect inseguro copiado em 22 pontos, sem helper
compartilhado** (`gestao_cme`: 7, `gestao_lab`: 13, `gestao_contratos`: 2). Cada view
reimplementa `request.POST.get("next")` à sua moda — algumas sem validação nenhuma,
outras com `.startswith("/")` (que não bloqueia `//host-externo`, uma URL
protocol-relative). Já documentado como achado de segurança (A-01/S-01) em três
documentos — é ao mesmo tempo o maior problema de segurança pendente **e** a maior
duplicação de código do projeto. Uma função utilitária única baseada em
`django.utils.http.url_has_allowed_host_and_scheme` resolve os 22 pontos de uma vez, sem
mudar o comportamento de nenhuma view (mesma assinatura, só passa a validar antes de
redirecionar).

**Prioridade média — helpers de data/paginação duplicados entre CME e Laboratório:**
- `_parse_data_iso`: código **idêntico**, copiado literalmente entre `gestao_cme/views.py`
  e `gestao_lab/views.py` (o docstring da cópia em `gestao_lab` admite: "Mesmo contrato
  do helper homônimo em `gestao_cme.views`").
- `_filtrar_por_intervalo` (CME) vs `_filtrar_por_campo_data` (Lab): mesmo conceito,
  implementado em paralelo, sem reuso.
- `paginar_queryset` (CME, pública) vs `_paginar` (Lab, privada): mesma lógica de
  paginação sob nomes diferentes.

**Prioridade baixa:**
- Enum `OrigemDados`: definido separadamente em `gestao_cme/models.py` e
  `gestao_lab/models.py`, com membros em comum (`MANUAL`, `EDUQ`) e membros próprios
  (`LEGADO`/`EXEMPLO` só CME, `DENTAL` só Lab) — não é cópia exata, então a unificação
  exigiria desenhar um enum comum mais genérico (decisão de modelagem, não uma extração
  mecânica).
- `clean_codigo`: três validadores quase idênticos dentro do próprio `gestao_cme/forms.py`
  (Turma, Kit, Material) — candidato a um mixin de validação de código único, mesmo
  dentro do mesmo app.

**Confirmado como já bem resolvido (não duplicado):** `NomeNormalizadoMixin`/`ModeloBase`
são definidos uma vez em `gestao_cme/models.py` e importados por `gestao_lab/models.py` —
prova que reuso entre apps já é um padrão aceito neste projeto, o que dá respaldo técnico
para fazer o mesmo com os itens acima.

### 2.3 Funções grandes (candidatas a extrair para services)

Medido por linhas de corpo (AST), as maiores funções do projeto:

| Função | App | Linhas | Observação |
|---|---|---|---|
| `portal` | `gestao_cme/views.py` | 153 | Importa models de `gestao_lab` e `gestao_contratos` diretamente na view, agregando métricas de 3 apps — acopla `gestao_cme` ao conhecimento interno dos outros dois (ver §11) |
| `index` | `identificadores/views.py` | 144 | Concentra busca, sincronização de localização e geração de arquivo no mesmo fluxo |
| `home` | `gestao_cme/views.py` | 126 | Listagem de Movimentações — filtros, paginação e montagem de linhas por pacote no mesmo corpo |
| `cme_dashboard` | `gestao_cme/views.py` | 116 | KPIs + atividade recente + filtro de período |
| `pacientes` | `gestao_lab/views.py` | 114 | Busca unificada (local + Dental Office ao vivo) + importação |
| `contratos` | `gestao_contratos/views.py` | 111 | Mesma ideia de busca unificada, paralela à de `pacientes` acima |
| `acompanhamento_pedidos` | `gestao_lab/views.py` | 91 | Múltiplos filtros (status, busca, período, campo de data) |

Nenhuma delas está "errada" — são bem comentadas e testadas —, mas concentram lógica de
consulta/filtro que poderia virar funções de serviço reutilizáveis (`services/`), deixando
a view só orquestrando request → serviço → template. Ver §6 e §11 para a proposta.

### 2.4 Código comentado / débito técnico avulso

Não há blocos de código comentado (código morto entre `#`), nem `print()`/`console.log`
de depuração esquecidos, nem marcadores `TODO`/`FIXME`/`XXX` pendentes em código de
produção — busca cobriu todos os apps.

---

## 3. Limpeza dos templates HTML

Sem páginas duplicadas nem templates órfãos (ver §1.1). Os componentes reutilizáveis já
esperados (filtro de período, paginação, mini-menu, autocomplete, modal de confirmação,
breadcrumb, ícones) já estão extraídos em `templates/partials/` e usados por todos os
apps — este é o principal motivo de o projeto estar tão mais limpo do que o levantamento
inicial fazia supor.

**Pontos abertos (não verificados a fundo nesta rodada, candidatos a uma etapa
dedicada):** CSS inline e JavaScript inline dentro de templates específicos (`assinatura.html`,
`portal.html`) não foram auditados linha a linha — como são telas com necessidades
visuais próprias (canvas de assinatura, cards de métricas), pode haver estilo inline
justificado ou não. Recomendo uma etapa específica de leitura desses templates antes de
generalizar uma regra.

---

## 4. Organização dos arquivos estáticos

Já coberto em §1.1 — nenhum arquivo duplicado, órfão ou não utilizado. Não há
bibliotecas de terceiros além do HTMX (`htmx.min.js`, vendorizado localmente, sem
gerenciador de pacotes JS no projeto) — não há dependências JS "antigas" para atualizar
porque não há versionamento de dependências JS nenhum (é um único arquivo estático).
Estrutura de diretórios (`static/css`, `static/js`, `static/img`, mais o CSS/JS próprio
de cada app em `<app>/static/<app>/...`) já segue o padrão Django recomendado — nada a
reorganizar aqui.

---

## 5. Padronização do front-end

Não fiz uma varredura visual (Playwright) nesta rodada — o levantamento foi 100% estático
(código/CSS). Pelo que já está documentado nas rodadas de auditoria visual anteriores
(CME: 13 + 4 itens; Laboratório: itens de padronização com o CME), botões, tabelas,
filtros, paginação, modais e mini-menus **já convergiram** para os mesmos componentes
compartilhados nos três apps principais. As exceções conhecidas e já registradas:

- `gestao_contratos`: telas públicas de assinatura (`assinatura.css`) mantêm tipografia
  própria (Fraunces/IBM Plex Mono) deliberadamente, por serem uma experiência do
  paciente, não do colaborador — decisão de negócio pendente de confirmação (ver
  `documentacao-gestao-contratos.md`, §3.2).
- `identificadores`: único app sem filtro de período/paginação compartilhados — não
  precisa, sua única listagem é a busca de turma.

Não encontrei inconsistência não documentada de botões/cores/tipografia nas telas de
staff — mas recomendo uma auditoria visual dedicada (mesmo roteiro já usado antes) se
quiser confirmação com capturas de tela, já que esta rodada foi só leitura de código.

---

## 6. Organização das views

Ver §2.3 para as views mais extensas. Padrão observado: a lógica de **consulta** (montar
querysets com filtros) está toda dentro da view, sem uma camada de serviço — diferente de
`gestao_contratos`, que já usa `services/` para assinatura, geração de documento, envio e
carimbo de tempo. `gestao_cme` e `gestao_lab` não têm pasta `services/` para suas
consultas de listagem (só para sincronização externa — `eduq_sync.py`,
`eduq_lab_sync.py`, `dental_sync.py`).

**Recomendação:** extrair as consultas mais complexas (`home`/`cme_dashboard` no CME,
`pacientes`/`acompanhamento_pedidos` no Lab) para módulos `services/consultas.py` (ou
nome equivalente) em cada app, seguindo o padrão que `gestao_contratos` já usa. Isso não
muda nenhum comportamento — só move onde o código mora.

---

## 7. Organização dos models

Não encontrei métodos duplicados, propriedades repetidas nem campos comprovadamente não
utilizados nos models principais (`Movimentacao`, `Emprestimo`, `PedidoMaterial`,
`Moldagem`, `ContratoGerado`) — a maior duplicação de nível "model" é o enum
`OrigemDados` (ver §2.2). Relacionamentos (`PROTECT`/`SET_NULL`) são usados de forma
consistente e já documentados por app (`documentacao-gestao-cme.md`/`-lab`/`-contratos`,
seção de regras transversais). Não fiz uma varredura campo a campo de cada model neste
levantamento — se quiser essa profundidade, recomendo uma etapa dedicada rodando
`manage.py graph_models` ou revisão manual guiada pelos casos de uso já documentados.

---

## 8. Organização dos forms

`gestao_cme/forms.py` concentra 12 forms (o maior volume do projeto); `gestao_lab` tem 7,
`gestao_contratos` 1, `contas` 2. Único achado de duplicação: três métodos `clean_codigo`
quase idênticos dentro do mesmo arquivo (`gestao_cme/forms.py`, para Turma/Kit/Material) —
candidato a um mixin de validação (`CodigoUnicoMixin` ou similar). Não há widgets
duplicados nem configuração repetida entre os forms dos diferentes apps (cada um valida
seu próprio domínio, sem sobreposição real).

---

## 9. URLs

Achados já cobertos em §2.1 (rotas sem uso). Além deles: `catalog_redirect` (`/catalog/`)
e `cme_entrada` (`/gestao-cme/`) em `gestao_cme/urls.py` são redirects de compatibilidade
com URLs antigas — não é código morto por definição (servem quem ainda tem o link
salvo), mas não há como confirmar pelo código se ainda são acessados; **marcado para
revisão manual** (confirmar com o time antes de remover). Não encontrei nomes de rota
inconsistentes nem rotas duplicadas apontando para a mesma view com o mesmo propósito.

---

## 10. Banco de dados

Contagem de migrations por app já está em §1.1 — nenhuma indicação de acúmulo
problemático que justifique squash agora (squash de migrations é uma operação arriscada
e só compensa quando há dor real, como suíte de testes lenta para recriar o schema; não é
o caso aqui). Não identifiquei tabelas ou models sem uso. Índices: não fiz uma auditoria
de índices ausentes nesta rodada (exigiria rodar `EXPLAIN` nas consultas mais frequentes
em produção) — recomendo tratar isso junto da etapa de performance (§12), não
isoladamente, já que índice sem consulta real que o justifique é otimização prematura.

---

## 11. Organização da arquitetura

O projeto já usa bem `services/` (principalmente em `gestao_contratos`), `mixins`
(`NomeNormalizadoMixin`), `management/commands` e um `mensageria` compartilhado — a
lacuna real está em `gestao_cme.views.portal` (§2.3), que conhece diretamente os models
internos de `gestao_lab` e `gestao_contratos` para montar o resumo do Portal. Isso
acopla um app "operacional" (CME) ao papel de "agregador cross-app", que
conceitualmente não é dele. Duas opções, para decidir com o time antes de mexer:

1. Extrair a agregação para um serviço neutro (ex.: `services/portal_resumo.py` num
   novo local, ou um app leve `portal/` sem models) que os três apps alimentam.
2. Manter a função em `gestao_cme` (já que é hoje o "dono" da tela de portal), mas mover
   o corpo para `gestao_cme/services/portal.py`, só para reduzir o tamanho da view —
   sem resolver o acoplamento entre apps, só a organização de arquivo.

Não hesitei em não decidir isso sozinho porque envolve uma escolha de arquitetura, não
uma refatoração mecânica.

---

## 12. Performance

Verificação pontual: as três maiores views de listagem (`portal`, `moldagens`,
`pacientes`) já usam `select_related` corretamente nos relacionamentos acessados no
template — não encontrei um N+1 óbvio nelas. Não fiz uma auditoria exaustiva de todas as
~90 views do projeto (exigiria rodar a suíte com `django-debug-toolbar`/`nplusone` e
captura real de queries) — o que fiz foi amostragem nas views mais complexas e mais
usadas. **Recomendo, como parte da etapa de performance, rodar a suíte com contagem de
queries ativada** (`assertNumQueries` já é um padrão comum em testes Django) nas telas
de listagem que ainda não foram verificadas manualmente.

---

## 13. Segurança

- **Open redirect (22 pontos, 3 apps)** — já detalhado em §2.2; é o achado mais sério e
  mais espalhado.
- **PDF do contrato sem checagem de identidade** (`assinar_pdf_view`, `gestao_contratos`) —
  já documentado como achado crítico (C-01) em `documentacao-gestao-contratos.md`,
  reverificado nesta sessão anterior como ainda presente no código.
- **IP forjável no documento assinado** (`_ip_do_request` usa o primeiro valor de
  `X-Forwarded-For` sem validar proxy confiável) — já documentado (A-02), ainda presente.
- **`@csrf_exempt`**: usado uma única vez no projeto inteiro
  (`gestao_lab.views.sincronizar_agendado`), protegido por comparação de token em tempo
  constante (`secrets.compare_digest`) — uso justificado e já documentado, não é um
  problema.
- **Validação de upload de imagem de assinatura**: já implementada (formato, tamanho
  mínimo/máximo), com uma fragilidade de baixo risco já documentada (B-01, uso de
  `Image.verify()` sem reabrir o arquivo depois).
- **Escopo de autorização entre usuários** (`gestao_contratos`): nenhuma view de staff
  filtra por usuário — qualquer conta autenticada acessa qualquer contrato pelo `pk` na
  URL (M-04, já documentado, decisão de negócio pendente).

Todos os achados de segurança aqui já estavam registrados nos documentos técnicos
consolidados na etapa anterior (`documentacao-gestao-contratos.md`,
`documentacao-gestao-lab.md`) — este levantamento não encontrou nenhum problema novo de
segurança além do que já estava mapeado, o que é um bom sinal de que a base de
conhecimento está atualizada.

---

## 14. Qualidade de código

- **PEP 8 / lint:** `ruff check` retornou 1 único apontamento em todo o projeto (nome de
  variável ambíguo). Prático já está no nível esperado.
- **DRY:** as duplicações reais estão listadas em §2.2 — concentradas, não espalhadas.
- **SOLID / Separation of Concerns:** a maior oportunidade é a separação
  view/serviço discutida em §6 e §11; não há violação grave de responsabilidade em
  models ou forms.
- **KISS:** as funções grandes de §2.3 não são complexas por acidente — fazem muita
  coisa em sequência (buscar, filtrar, paginar, montar contexto), o que é exatamente o
  padrão que uma extração para serviço resolveria.

---

## 15. Relatório final (resumo)

### Estrutura
- **Arquivos removidos nesta rodada:** nenhum (levantamento apenas).
- **Candidatos à remoção** (aguardando confirmação, ver §9 e §2.1): `alternar_retirado`,
  `baixar_contrato_pdf_view`/`contrato_baixar_pdf`, `buscar_paciente_dental`/`lab_buscar_paciente`,
  `contrato_baixar_carimbo_tempo`, e os redirects legados `catalog_redirect`/`cme_entrada`.
- **Templates consolidados:** nenhum necessário — já estão consolidados desde as rodadas
  anteriores.
- **Componentes reutilizados:** confirmados todos em uso (`filtro_periodo`, `paginacao`,
  `side_link`/`side_link_group`, `confirm_dialog`, `form_errors`, `breadcrumb`, `icons`).

### Python
- **Funções removidas:** nenhuma ainda (candidatas listadas acima).
- **Métodos/lógica a refatorar:** helper de redirect inseguro (22 pontos),
  `_parse_data_iso`/`_filtrar_por_intervalo`/`paginar_queryset` (CME × Lab), `clean_codigo`
  (3× em `gestao_cme/forms.py`).
- **Duplicidades eliminadas:** nenhuma ainda — plano na §16.
- **Imports removidos:** nenhum necessário (`ruff` não encontrou nenhum).
- **Código simplificado:** views grandes candidatas à extração de serviço (§2.3, §6).

### HTML
- **Páginas consolidadas:** nenhuma necessária — sem duplicação encontrada.
- **Componentes criados:** nenhum novo necessário — os existentes já cobrem os padrões
  usados.
- **Includes/herança:** já implementados consistentemente em todos os apps.

### CSS/JS
- **Arquivos removidos:** nenhum necessário — nenhum arquivo órfão encontrado.
- **Estilos consolidados:** já consolidados (`components.css`/`tokens.css`); única
  sobreposição encontrada (`.status-seg`) é uma variação pequena, não duplicação.
- **Scripts reutilizados:** `app.js`/`htmx.min.js` já usados de forma compartilhada.

### Performance
- **Consultas otimizadas:** amostragem das views mais complexas não encontrou N+1 —
  cobertura parcial, não exaustiva (ver §12).
- **Pontos de melhoria:** auditoria de queries com contagem ativada nas listagens ainda
  não verificadas manualmente.

### Arquitetura
- **Sugestão de reorganização:** extrair lógica de consulta das views mais extensas para
  `services/` em `gestao_cme` e `gestao_lab` (padrão já usado por `gestao_contratos`).
- **Responsabilidades a redistribuir:** decidir o destino da agregação cross-app hoje
  dentro de `gestao_cme.views.portal` (§11).

### Pendências (precisam de validação manual antes de qualquer remoção definitiva)
1. Confirmar se `alternar_retirado`, `baixar_contrato_pdf_view`, `buscar_paciente_dental`
   e `contrato_baixar_carimbo_tempo` podem ser removidos com segurança, ou se algum é
   usado por integração externa não visível no grep.
2. Confirmar se `catalog_redirect`/`cme_entrada` (redirects de URL legada) ainda são
   necessários.
3. Decidir o destino da agregação cross-app do Portal (extrair para serviço neutro, ou
   só mover para dentro de `gestao_cme/services/`).
4. Decidir se vale unificar o enum `OrigemDados` (CME × Lab) — é uma escolha de
   modelagem, não uma extração mecânica.
5. Confirmar se a tipografia própria das telas públicas de assinatura
   (`gestao_contratos`) deve ou não ser alcançada pela padronização visual — já é uma
   pendência de negócio registrada, só reforçando aqui.

---

## 16. Plano de execução em etapas (incrementais, cada uma com commit + revisão)

Cada etapa é pequena o suficiente para revisar isoladamente, na ordem sugerida (impacto ×
risco). Nenhuma etapa muda regra de negócio, fluxo funcional ou contrato de URL/API —
só correção de segurança, remoção de código morto confirmado, e reorganização interna.

| Etapa | Conteúdo | Risco | Reversível |
|---|---|---|---|
| **1** | ✅ **Concluída** — redirect inseguro corrigido nos 22 pontos com `comum.http.destino_seguro` | Baixo — mesma assinatura de função, só passa a validar antes de redirecionar | Sim |
| **2** | ✅ **Concluída** — C-01 (PDF sem checagem de identidade) e A-02 (IP forjável) corrigidos em `gestao_contratos` | Baixo — 1 `if` e 1 ajuste de leitura de header | Sim |
| **3** | ✅ **Concluída** — removidas `alternar_retirado`, `baixar_contrato_pdf_view` e `buscar_paciente_dental`; `contrato_baixar_carimbo_tempo` mantida (ver §2.1) | Baixo, mas depende de confirmação prévia | Sim (git) |
| **4** | ✅ **Concluída** — `_parse_data_iso`/`_filtrar_por_intervalo`/`paginar_queryset` unificados em `comum/datas.py` e `comum/paginacao.py` | Baixo — comportamento idêntico, só muda onde mora | Sim |
| **5** | Extrair mixin de validação `clean_codigo` em `gestao_cme/forms.py` | Baixo | Sim |
| **6** | Extrair lógica de consulta das views mais extensas (`home`, `cme_dashboard`, `pacientes`, `acompanhamento_pedidos`) para `services/` em cada app | Médio — mexe em várias views, precisa rodar a suíte completa a cada app | Sim |
| **7** | Decidir e implementar o destino da agregação cross-app do Portal | Médio — depende de decisão de arquitetura (§11) | Sim |
| **8** | Normalizar encoding (remover BOM dos 12 arquivos) | Muito baixo, cosmético | Sim |
| **9** | ✅ **Concluída** — Auditoria visual dedicada de padronização de front-end (screenshots), ver `avaliacao-visual-padronizacao-frontend.md` | — | — |
| **10** *(opcional, sob demanda)* | Auditoria de performance com contagem de queries nas listagens ainda não verificadas | — | — |

A Etapa 9 encontrou 5 achados (nenhum bloqueante): o sistema de cor por aplicação
("wayfinding") só está implementado em `gestao_lab`; o rótulo acima do título diverge em
2 das 4 apps; um texto do stepper de Contratos aparece truncado no desktop; tabelas de
listagem não se adaptam bem a telas estreitas (achado comum, não uma inconsistência); e a
navegação lateral agrupa itens por seção só no Laboratório. Detalhes e evidências em
`avaliacao-visual-padronizacao-frontend.md`.

A **Etapa 1** foi concluída em 2026-07-28. Os 22 pontos passaram a usar
`comum.http.destino_seguro`, que valida o `next` com
`url_has_allowed_host_and_scheme` (a mesma checagem que o `LoginView` do Django
aplica ao `next` dele) antes de redirecionar. A checagem anterior mais comum,
`next.startswith("/")`, deixava passar `//host-externo` — uma URL
protocol-relative, que o navegador resolve como endereço externo; era por ali que
o open redirect entrava. Oito dos 22 pontos não validavam nada.

Nenhuma view mudou de comportamento para um `next` legítimo: o destino interno
continua sendo respeitado, e o fallback de cada view é o mesmo de antes. O que
mudou é que um `next` apontando para fora do site agora cai no fallback em vez de
levar o operador para outro domínio.

O pacote `comum/` criado aqui é o destino natural dos helpers de data e paginação
da **Etapa 4**.

A **Etapa 2** foi concluída em 2026-07-28, fechando os dois achados de segurança
restantes de `gestao_contratos`:

- **C-01** — `assinar_pdf_view` entregava o PDF completo (CPF, RG, endereço, dados
  de saúde) a quem tivesse o link ou fotografasse o QR Code, sem passar pela
  verificação de identidade — o que anulava, na prática, a tela que `assinar_view`
  impõe. Passa a exigir `identidade_confirmada_em`, o mesmo gate da tela de
  assinatura, e responde 404 (não 403) para não revelar que o token é válido. O
  link para essa rota só existe dentro de `assinar.html`, renderizado apenas
  depois da confirmação, então nenhum acesso legítimo é afetado.
- **A-02** — `_ip_do_request` lia a primeira entrada do `X-Forwarded-For`, que é
  justamente a que o cliente envia. Qualquer um escolhia o IP gravado no rodapé do
  PDF assinado e na trilha de auditoria — e também furava o rate-limit das rotas
  públicas, que usa o mesmo IP como chave. Passa a ler a entrada acrescentada pelo
  último proxy confiável, com a contagem em `PROXIES_CONFIAVEIS` (padrão 1, que
  vale para o Railway; 0 ignora o cabeçalho, para conexões diretas).

Com isso, dos achados priorizados pela auditoria original só restam os do carimbo
de tempo. Um teste que existia (`test_pdf_publico_acessivel`) codificava o
comportamento vulnerável e foi ajustado para confirmar a identidade antes de
esperar o PDF.

A **Etapa 3** foi concluída em 2026-07-28. Três das quatro rotas candidatas saíram
(view + rota + testes); a quarta ficou, com a justificativa registrada em §2.1.

Sobre a ressalva original de "confirmar com o time se algum deles é usado por
integração externa": as três removidas eram rotas de staff (`@login_required`), o
que limita o risco a um bookmark interno ou script com credenciais. Nenhuma delas
tinha link na interface, e a remoção é reversível por git — os commits estão
isolados justamente para permitir voltar atrás caso alguém reclame de um atalho
que usava.

Dois desvios entre a documentação e o código apareceram no caminho e foram
corrigidos:

- **UC-08** (`documentacao-gestao-cme.md`) descrevia a alternância manual de status
  como ação de linha da listagem, e o UC-05 a listava entre as ações disponíveis —
  mas o histórico mostra que a rota nunca esteve em template nenhum. A seção virou
  um registro histórico e as referências (diagrama, matriz de rastreabilidade,
  backlog de usabilidade) passaram a apontar para a edição (UC-06), que é o caminho
  real.
- A evidência da linha do `contrato_baixar_pdf` estava incorreta neste próprio
  documento (ver §2.1).

A **Etapa 4** foi concluída em 2026-07-28. Os três helpers duplicados passaram
para `comum/datas.py` (`parse_data_iso`, `filtrar_por_intervalo`) e
`comum/paginacao.py` (`paginar`). As duas apps chamam os mesmos.

Duas decisões de forma:

- **A paginação continua com um adaptador de uma linha em cada app**
  (`paginar_queryset` no CME, `_paginar` no Lab). O algoritmo mora num lugar só;
  o adaptador existe apenas para amarrar o `REGISTROS_POR_PAGINA` da app, que é
  legitimamente uma decisão de cada listagem (hoje 10 nas duas, mas nada obriga
  a continuar assim).
- **O filtro de data foi chamado direto**, sem adaptador: era o único cuja
  assinatura divergia entre as apps (o `campo` vinha por último no CME e em
  segundo no Lab), então convergir os pontos de chamada era o próprio objetivo.

**Achado no caminho — uma lista que nunca precisou existir.** O Lab mantinha
`_CAMPOS_DATA_DATETIME` para saber quando comparar com `.date()` em vez do
datetime completo. Comparando o SQL gerado nos dois casos, ele sai **idêntico**:
o `DateField.to_python` do Django já converte um datetime aware para o fuso local
e reduz à data antes de montar a query. A lista e o ramo condicional foram
removidos em vez de reproduzidos no módulo compartilhado, com o motivo registrado
na docstring de `filtrar_por_intervalo` para ninguém trazê-los de volta.

Isso também derrubou uma afirmação do primeiro teste que escrevi aqui: ele dizia
cobrir "o caso que exige o `.date()`", mas continuou passando com a lógica
sabotada de propósito — porque não havia o que discriminar. O teste foi mantido
(a fronteira do último dia é contrato que vale fixar), com a descrição corrigida.

Próxima recomendada: **Etapa 8** (remover o BOM de 12 arquivos) — cosmética e de
risco mínimo, boa para fechar o bloco mecânico. Depois dela sobram a **Etapa 6**
(extrair consultas das views extensas para `services/`, a de maior esforço) e a
**Etapa 7**, que depende de uma decisão de arquitetura sobre o Portal (§11).
