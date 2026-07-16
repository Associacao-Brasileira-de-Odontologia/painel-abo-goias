# Melhorias — Gestão de CME e Gestão de Contratos

> Data: 2026-07-15 · Branch: `31-melhorias-visuais-e-funcionalidades`
> Escopo: dois conjuntos de melhorias (CME e Contratos), a partir das listas
> registradas em `auditoria-gestao-cme.md` e `auditoria-gestao-contratos.md`.
> Ambiente validado: `manage.py check` sem erros; suíte completa (581 testes) verde,
> sem passo manual de `collectstatic` (ver A-01 em `auditoria-identificadores.md`).

---

## Sistema de Gestão de CME

### 1. Botão de cadastro de kits — **análise + implementado**

**Análise da necessidade (solicitada no brief):** hoje os kits só podem ser
criados pelo **Django Admin** (`KitAdmin` com inline `KitMaterial`). Não existia
nenhum fluxo de criação de kit na interface operacional, embora o fluxo de
**empréstimos dependa de kits** (ver `criar_emprestimo` / `EmprestimoForm`). Um
coordenador sem acesso de administrador ficava sem como cadastrar um kit novo.
Conclusão: a necessidade é **real** — botão implementado.

**Alterado:**
- `forms.py`: novo `KitForm` (nome, código único, descrição, quantidade) +
  campo `materiais` (multiseleção de materiais ativos). No `save`, cada material
  selecionado vira um `KitMaterial` com **quantidade 1**.
- `views.py`: nova view `cadastrar_kit` (marca `origem = MANUAL`).
- `urls.py`: rota `kits/novo/` (`cadastrar_kit`).
- `templates/gestao_cme/kits.html`: botão **"Cadastrar kit"** em `panel_actions`.
- `templates/gestao_cme/form_kit.html`: novo formulário (espelha `form_material`).

**Decisão:** a composição inicial usa quantidade 1 por material. O ajuste fino de
quantidade por material continua no Admin (evita construir agora um editor de
linhas com quantidade, fora do escopo do "botão").

**Pendência (negócio):** confirmar se o cadastro pela interface deve permitir
definir quantidade por material já na criação, ou se a quantidade 1 + ajuste no
Admin é suficiente para a operação.

### 2. Confirmação dupla ao alterar abrigo — **implementado**

- `views.py::editar_abrigo`: passa `alunos_associados` (alunos ativos vinculados
  ao abrigo) para o contexto.
- `templates/gestao_cme/form_abrigo.html`: em modo edição, o botão "Salvar
  alterações" agora abre o **modal de confirmação obrigatório** (`data-confirm`,
  reusa `templates/partials/confirm_dialog.html` + `static/js/app.js`), com a
  mensagem listando quem ocupa o abrigo (nome + matrícula) ou informando que
  nenhum aluno está vinculado. A tela também exibe esse resumo de ocupação acima
  dos botões.

**Decisão:** o modal existente só renderiza texto puro (`textContent`), então a
mensagem de contexto é montada no servidor/template. "Ocupado por material de
fulano" foi interpretado como **alunos vinculados ao abrigo** — que é o vínculo
real no modelo (`Aluno.abrigo`). Não há vínculo abrigo↔material no schema.

### 3. Tooltip explicativo no campo STATUS — **implementado**

- `templates/gestao_cme/alunos_por_turma.html`: o cabeçalho **STATUS** ganhou um
  ícone de atenção (`#i-alerta`) com `title` (tooltip) e `aria-label`,
  esclarecendo que o campo é a **situação de matrícula (Ativo/Inativo)** e **não**
  o vínculo com turmas ativas.
- `static/css/components.css`: classes `.th-with-hint` / `.th-hint`.

### 4. Padronizar botão "Limpar tudo" — **implementado**

Trocado de `.chips-clear` (link de texto apagado) para o botão padrão do design
system `button secondary compact-button` — mesma categoria de ação dos botões
"Limpar filtros"/"Limpar busca" já usados nos estados vazios. Aplicado em:
`alunos_por_turma.html`, `home.html`, `materiais.html`, `armarios.html`,
`emprestimos.html`.

### 5. Sincronização abrigos ↔ alunos por turma (coluna OCUPAÇÃO) — **implementado**

- `views.py`: novo helper `_sincronizar_ocupacao_abrigo(abrigo)` — recalcula
  `Abrigo.ocupado` como "existe ≥1 aluno ativo vinculado".
- `views.py::atribuir_abrigo`: ao atribuir/remover o abrigo de um aluno, atualiza
  a ocupação do **abrigo novo** e do **abrigo anterior** (transação atômica).
- `views.py::editar_abrigo`: também resincroniza a ocupação após salvar (o vínculo
  dos alunos é a fonte da verdade).

**Decisão:** "ocupado" = há aluno vinculado. A FK `Aluno.abrigo` não é única, então
um abrigo pode ter mais de um aluno; ele fica livre só quando **nenhum** aluno
ativo aponta para ele.

### 6. Detalhamento de movimentações (coluna MOVIMENTAÇÃO clicável) — **implementado**

- `views.py::home`: novo filtro `?aluno=<id>` (vínculo exato por FK), com chip de
  filtro ativo e link "Ver todas".
- `templates/gestao_cme/alunos_por_turma.html`: o número da coluna MOVIMENTAÇÕES
  virou link para `cme_home?aluno=<pk>`.
- `templates/gestao_cme/home.html`: chip do aluno filtrado.
- `static/css/components.css`: `.mov-link`.

### 7. Padronizar seleção de aluno no formulário de empréstimos — **implementado**

- `templates/gestao_cme/criar_emprestimo.html`: o `<select>` massivo de alunos foi
  substituído pelo **mesmo autocomplete** do formulário de entrada (busca HTMX via
  `buscar_alunos` + chip do selecionado + campo oculto `aluno`).
- `views.py::criar_emprestimo`: passa `aluno_selecionado` para preservar a escolha
  quando o form volta com erro (mesmo padrão de `registrar_entrada`).

### 8. Ícones no lugar de texto nos botões "Editar" — **implementado**

Trocado o texto "Editar" pelo ícone `#i-editar` (`.icon-action`) mantendo
acessibilidade (`title="Editar"` + `aria-label`). Templates: `home.html`
(movimentação), `materiais.html`, `armarios.html`.

### 9. Exclusão no formulário de edição de abrigo — **implementado**

- `views.py`: nova view `excluir_abrigo` (POST). `Aluno.abrigo` é
  `on_delete=SET_NULL`, então excluir um abrigo apenas **desvincula** os alunos —
  nenhum cadastro é perdido.
- `urls.py`: rota `abrigos/<pk>/excluir/`.
- `templates/gestao_cme/form_abrigo.html`: "Zona de exclusão" com botão perigoso e
  **modal de confirmação** (`data-confirm-danger`), avisando quantos alunos serão
  desvinculados.

---

## Sistema de Gestão de Contratos

### 1. Corrigir nomenclatura dos sistemas integrados — **implementado**

Padronizados os textos que abreviavam "Dental Office" como apenas "Dental":
- `gerar_contrato.html`: "Enviado ao Dental" → "Enviado ao Dental Office";
  "Registro Dental" → "Registro Dental Office".
- `pos_geracao.html`: "Enviado ao Dental" → "Enviado ao Dental Office".

**Observação / pendência:** a app de Contratos **não integra o EDUQ** — não há
menção a "EDUQ" na sua interface, então não houve o que corrigir nesse ponto. A
grafia "Eduq" (título) aparece na app **Gestão de CME**. Se o time quiser a grafia
"EDUQ" (caixa alta) padronizada em todo o ecossistema, é uma alteração transversal
à parte (fora do escopo desta app) — **confirmar antes**.

### 2. Unificar as duas listagens da busca de paciente — **implementado**

Antes a tela mostrava **duas tabelas** (pacientes locais + resultados do Dental
Office). Agora há **uma única listagem** (`pacientes_unificados`, montada em
`views.py::contratos`): registros locais primeiro e, na primeira página, os do
Dental Office ainda **não importados** (os "já no sistema" são omitidos para não
duplicar). A ação por linha distingue os casos: **"Gerar contrato"** (local) ou
**"Importar e gerar"** (Dental Office).

Colunas mínimas: **Paciente · Nascimento · Celular · Ação**.

**Pendência (negócio — solicitada no brief):** confirmar o conjunto de colunas
"realmente necessárias". A proposta acima privilegia identificação (nome +
CPF/ID + nascimento) e ação. Se quiserem manter um indicador explícito de origem
(sistema vs Dental Office), ele pode voltar como coluna ou selo — hoje isso está
implícito no rótulo do botão de ação.

### 3. Substituir o campo "ORIGEM" da listagem — **implementado (com ressalva de dados)**

A coluna "Origem" (selo "Já no sistema"/"Dental Office") foi **removida**. No lugar,
a identificação do paciente usa:
- **Data de nascimento** (coluna dedicada) e **CPF** (linha secundária sob o nome),
  quando disponíveis.

**Ressalva técnica importante:** o **endpoint de listagem** do Dental Office
(`listar_pacientes`) retorna apenas `id`, `name`, `celular` — **não** traz CPF nem
nascimento (esses só vêm no endpoint de **detalhe**, `buscar_detalhes_paciente`).
Portanto, para pacientes ainda **não importados**, essas colunas aparecem vazias
("—") a menos que a listagem passe a incluir esses campos. A view já lê, em
best-effort, `document_attributes.cpf` e `birth_date` do item bruto caso a API os
forneça (`_cpf_do_item_lista` / `_nascimento_do_item_lista`).

**Pendência (negócio/técnica):** confirmar **qual identificador** é preferido
(CPF vs nascimento). Se o CPF for obrigatório na listagem para os pacientes do
Dental Office não importados, será necessário um **detalhe por linha** (custo de N
chamadas à API) — decisão de produto por causa do impacto de performance.

### 4. "Validar documento" em nova guia — **implementado**

- `templates/partials/side_link.html`: novo parâmetro opcional `new_tab` →
  `target="_blank" rel="noopener noreferrer"`.
- `gestao_contratos/base.html`: o link "Validar documento" passa `new_tab=True`.

### 5. Padronizar tipografia — **implementado (staff) / ressalva (telas públicas)**

A camada visual "Termo & Selo" usava **Fraunces** (títulos) e **IBM Plex Mono**
(rótulos/dados), carregadas do Google Fonts. Padronizado com o design system:
- `contratos.css`: `--gc-serif` → `var(--font-display)` (Syne) e `--gc-mono` →
  `var(--font-body)` (DM Sans). Estrutura visual preservada; só as famílias mudaram.
- `base.html`: removido o `<link>` do Google Fonts (Fraunces/IBM Plex Mono).

**Ressalva:** as **telas públicas de assinatura** (`assinar.html` /
`assinatura.css`) têm UX própria e a auditoria orienta não alterá-las sem
validação dedicada — **não** foram tocadas. `assinatura.css` ainda referencia
Fraunces/IBM Plex Mono hardcoded.

**Pendência (negócio/design):** confirmar se a padronização deve alcançar também
as telas públicas de assinatura (fluxo do paciente), que hoje seguem a identidade
"Termo & Selo".

### 6. Notificação de falha no envio ao Dental Office — **implementado**

- **Notificação imediata:** o envio manual (`enviar_ao_dental_view`) já exibe
  `messages.error` na falha (mantido). O envio automático (Celery
  `enviar_dental_task`) persiste o estado `status_envio_dental="erro"` +
  `EventoContrato("envio_dental_erro")` com a mensagem no payload.
- **Painel de consulta posterior:** nova tela **"Envios ao Dental Office"**
  (`envios_dental_pendentes_view` → `envios_dental.html`, rota
  `contrato_envios_dental`) listando os contratos **assinados** com envio em
  **falha** (`erro`) ou **pendente** (`nao_enviado`), com a última mensagem de erro
  e um botão de **reenviar** por linha (redireciona de volta ao painel via `next`).
  Link adicionado à navegação lateral de Contratos.
- **Alerta proativo:** o **portal** (`gestao_cme::portal`) passou a exibir uma
  tarefa pendente **urgente** com a contagem de contratos assinados sem envio ao
  Dental Office, linkando para o painel.

**Decisão:** não foi criado um novo campo no modelo para a mensagem de erro — ela é
lida do `EventoContrato` mais recente (uma consulta agregada, sem N+1). Assim
evita-se migration e mudança em `_marcar_erro`.

---

## Backlog implementado

### B-14 — Carimbo de tempo antes do envio automático — **implementado**

**O problema:** `processar_assinatura` disparava as três tarefas Celery em paralelo
(`enviar_dental_task`, `enviar_whatsapp_task`, `solicitar_carimbo_tempo_task`). Como o
carimbo **reescreve** o PDF assinado para embutir o token TSR
(`carimbo_tempo._embutir_carimbo_no_pdf_assinado`), os envios quase sempre liam o arquivo
antes dessa reescrita — as cópias no prontuário e no WhatsApp do paciente saíam **sem** a
prova de data/hora, enquanto só a cópia guardada no sistema a tinha.

**Alterado:**
- `services/assinatura.py`: o disparo de Dental + WhatsApp virou o helper
  `agendar_envios_automaticos(contrato)` (mesmas condições de antes: `id_dental` presente,
  Z-API configurada + celular; falha de `.delay` vira evento e não propaga).
  `processar_assinatura` agora **encadeia**: com TSA configurada agenda **só** o carimbo;
  sem TSA, mantém o comportamento antigo (envios direto).
- `tasks.py::solicitar_carimbo_tempo_task`: ao concluir, chama
  `agendar_envios_automaticos` — depois de o token estar embutido.

**Decisão (a que importa):** se a TSA falhar, os envios acontecem **assim mesmo**, após as
tentativas se esgotarem. Reter um documento assinado é pior que entregá-lo sem carimbo — a
mesma lógica que já rege o resto do fluxo ("uma falha temporária de rede não perde o
documento assinado"). O atraso máximo é o do backoff (~30s de espera + timeouts da TSA),
não os 15 min de `retry_backoff_max`, porque são só 5 tentativas a partir de 1s.

**Fallback:** se o próprio enfileiramento do carimbo falhar (broker/Redis fora do ar),
ninguém encadearia os envios — nesse caso `processar_assinatura` os dispara ela mesma.

**Sem efeito prático hoje:** `CARIMBO_TEMPO_TSA_URL` não está configurada, então o caminho
novo só entra em ação quando a TSA for ligada em produção. Até lá o fluxo é bit a bit o
anterior.

**Testes:** 5 novos (`CarimboAntesDoEnvioTests` + 2 em `ProcessarAssinaturaCarimboTempoTests`),
sendo o principal um ponta a ponta que captura os bytes entregues ao `DentalClient` e afirma
que o PDF carrega o anexo `carimbo_tempo.tsr`. **Confirmado que ele falha no código
anterior** (`'carimbo_tempo.tsr' not found`) e passa com a correção. Suíte completa: 581
testes verdes.

---

## Integrações (verificação pós-alteração)

- **Eduq (CME):** nenhuma alteração tocou o cliente/serviço do Eduq
  (`integrations/eduq.py`, `services/eduq_sync.py`) nem as views de sincronização.
  As mudanças de abrigo/ocupação operam sobre dados já locais.
- **Dental Office (Contratos):** a listagem unificada continua usando
  `listar_pacientes` + `normalizar_paciente` (sem mudança de contrato de API); a
  leitura best-effort de CPF/nascimento é defensiva (`.get`), sem quebrar quando os
  campos não vêm. O envio (`enviar_contrato_ao_dental`) não foi alterado.

---

## Padronização da busca de aluno (CME ↔ Laboratório)

### Como a busca funciona no Laboratório (mapeamento)

| Peça | Arquivo | Papel |
|---|---|---|
| Campo | `gestao_lab/partials/_ac_field.html` | Monta o bloco `[data-ac]`: input HTMX, spinner, chip do selecionado, `<input type=hidden>` com o pk |
| Resultados | `gestao_lab/partials/_ac_results.html` | Fragmento com botões `.ac-result` (`data-id`, `data-id-dental`, `data-nome`) |
| View de busca | `gestao_lab/views.py::_buscar_unificado` | Junta base local + Dental Office; avisos `parcial` / `ha_mais` |
| Junção | `gestao_lab/views.py::_unificar` | Dedup por `id_dental`; locais nunca perdem vaga para remotos; limite 20 |
| Gravação | `gestao_lab/views.py::materializar` | POST que grava o item remoto escolhido e devolve `{pk, nome}` |
| Comportamento | `static/js/app.js` (handler `[data-ac]`) | Clique → preenche o hidden e mostra o chip; sem pk → materializa antes; "Trocar" desfaz |

Fluxo: digita → HTMX (300 ms) → lista única (local + API, sem dizer a origem) →
clique → se o item não tem pk, é gravado na hora (um write, só do escolhido) →
pk vai para o campo oculto do formulário.

### O que foi reproduzido no CME

- **Componente compartilhado**: `_ac_field.html` promovido para
  `templates/partials/_ac_field.html`, usado agora pelas **duas** apps. O
  `data-ac-materializar` deixou de ser fixo no `lab_materializar` e passou a ser
  o parâmetro opcional `ac_materializar_url`. Novos parâmetros: `ac_placeholder`,
  `ac_hint`, `ac_autofocus`, `ac_vals` e `ac_navegar`.
- **Contrato de resultados**: `gestao_cme/partials/_aluno_results.html` agora usa
  `.ac-result` + `data-id`/`data-nome` (antes `.aluno-result`), com os mesmos
  estados vazios e o aviso **"Há mais resultados"**.
- **View**: `buscar_alunos` ganhou o limite compartilhado
  (`LIMITE_RESULTADOS_BUSCA = 20`, igual ao `_LIMITE_RESULTADOS` do lab) e a flag
  `ha_mais` (busca `limite+1` para detectar corte sem `count()`).
- **JS unificado**: as três telas do CME (`registrar_entrada`, `criar_emprestimo`,
  `registrar_saida`) tinham **JS inline duplicado** para selecionar/trocar aluno.
  Todo esse código foi **removido** — passam a usar o handler genérico `[data-ac]`
  de `static/js/app.js`, o mesmo do laboratório.
- **`data-ac-navegar`** (novo, em `app.js`): `registrar_saida` precisa recarregar
  a tela ao escolher o aluno (para listar os pacotes pendentes) em vez de
  preencher um formulário. Virou uma opção do componente genérico, em vez de um
  script próprio da tela.

### Diferença deliberada: no CME a busca é só local

O ponto central do autocomplete do laboratório — **misturar base local com uma
busca ao vivo na API** e gravar o escolhido no clique (`materializar`) — **não
tem equivalente possível no CME hoje**:

- Os alunos do CME vêm do **Eduq**, e o cliente do Eduq (`integrations/eduq.py`)
  expõe apenas `listar_turmas()` e `listar_alunos(codigo_turma)` — **não existe
  busca de aluno por nome**. Não há endpoint para consultar ao vivo, e portanto
  nada a materializar.
- O laboratório consulta o **Dental Office**, que tem busca por nome
  (`procurar_pacientes` / `procurar_alunos`).

Logo, no CME a lista continua vindo da base local, alimentada pela sincronização
do Eduq (rotina diária às 04:00 + botão "Atualizar lista de alunos"). Foi
reproduzido **tudo o que não depende desse endpoint**: componente, contrato,
comportamento, limite, avisos e acessibilidade. A limitação já constava da
auditoria do CME e está registrada no docstring de `buscar_alunos`.

**Pendência (negócio/técnica):** se for necessário encontrar no CME um aluno que
ainda não foi sincronizado, as opções são (a) sincronizar a turma sob demanda
antes de buscar, ou (b) verificar com o fornecedor do Eduq se existe/pode existir
um endpoint de busca de aluno por nome. Hoje nenhuma das duas está implementada.

---

## Rodada 2 — listagem por pacote e atualização de turmas

### 10. Listagem de movimentações: uma linha por pacote — **implementado**

**Antes:** cada pacote gerava **duas linhas** na listagem (a ENTRADA e, depois da
retirada, a SAIDA). **Agora:** uma linha por pacote, com as colunas **Entrada**
(sempre presente) e **Saída** (preenchida na retirada).

**O problema que precisou ser resolvido primeiro.** O vínculo entrada↔saída era
apenas **implícito**: a SAIDA copiava o `pacote_codigo` da ENTRADA, e o par só
podia ser reconstruído por coincidência de string. Isso não é confiável:

- `pacote_codigo` **não tem constraint de unicidade**, e a geração usa
  `max(códigos numéricos)+n` **sem lock** (B-07 da auditoria) → duas entradas
  concorrentes podem repetir o código;
- nos dados **LEGADO**, `pacote_codigo` é o **código do material**, não do pacote
  — `migracao_legado.py` faz `materiais_por_codigo.get(pacote_codigo)`. O mesmo
  código se repete entre alunos e datas. **Parear por ele cruzaria registros de
  pessoas diferentes.**

**Decisão:** tornar o vínculo explícito. `registrar_saida` **já conhecia** o
objeto exato da entrada e o descartava; agora grava em `Movimentacao.entrada_origem`
(self-FK, nulo, só em SAIDA). Alternativa rejeitada: parear por string no view —
construiria a feature sobre o mesmo dado frágil.

**Alterado:**
- `models.py`: campo `entrada_origem` (self-FK, `SET_NULL`, `related_name="saidas"`)
  + docstring explicando por que o pareamento por `pacote_codigo` não serve.
- `migrations/0013`: adiciona o campo.
- `migrations/0014`: backfill dos dados já existentes — **só `origem=MANUAL`**, e
  **pula códigos ambíguos** (>1 entrada com mesmo código/aluno). Reversível.
- `views.py::registrar_saida`: grava `entrada_origem=entrada`.
- `views.py::home`: linhas = ENTRADAs + SAIDAs sem vínculo; `prefetch_related("saidas")`
  evita N+1; novo helper `_preparar_datas_do_pacote`.
- `templates/gestao_cme/home.html`: colunas **Entrada** e **Saída**.

**Decisão — legado não é pareado, mas também não some.** Sem vínculo real no dado,
uma SAIDA legada aparece como linha própria com entrada **"Não registrada"**, e uma
ENTRADA legada marcada como retirada mostra **"Retirado — sem data"**. Preferimos
mostrar a lacuna a inventar um par (que cruzaria alunos).

**Decisão — filtro "Movimentação" removido.** Filtrar por Entrada/Saída deixou de
selecionar linhas distintas (cada linha tem as duas datas). O filtro de **Status**
(Retirado / Não retirado) cobre a mesma intenção. Busca, filtro por aluno e
paginação seguem iguais.

**Verificado** (testes temporários, depois removidos):
- fluxo real do painel: 2 entradas + 1 saída → **3 registros viram 2 linhas**; a
  retirada com as duas datas, a pendente só com entrada;
- legado com `pacote_codigo="CX-01"` em **alunos diferentes**: os 2 registros
  continuam visíveis e **não são pareados** entre si;
- backfill: pareia o par MANUAL simples, **ignora** o legado e **recusa** o código
  ambíguo;
- na tela (dados semeados): 4 registros → 3 linhas, exatamente como projetado.

**Pendência (negócio):** confirmar o tratamento do legado. Se o time souber que,
nas planilhas antigas, entrada e saída de um mesmo material para o mesmo aluno
sempre se sucedem em ordem, dá para parear por proximidade cronológica — mas isso
é uma **inferência**, não um dado, e não fizemos por conta própria.

### 11. Botão "Atualizar turmas" no formulário de empréstimos — **implementado**

- `views.py`: nova view `atualizar_turmas_eduq` (POST) — chama
  `sincronizar_eduq(sincronizar_turmas=True, sincronizar_alunos=False)`.
- `urls.py`: rota `turmas/atualizar/`.
- `templates/gestao_cme/criar_emprestimo.html`: bloco `panel_actions` com o botão.

**Decisão:** view **dedicada** a turmas em vez de reusar `atualizar_alunos_eduq`.
Esta já sincroniza turmas **e** alunos (apesar do rótulo "Atualizar lista de
alunos"), e é bem mais lenta — varre os alunos de cada turma. O pedido era turmas,
então a ação nova faz só isso.

**Verificado:** clicado na tela, contra o **Eduq real** → *"Turmas atualizadas: 0
nova(s), 43 atualizada(s)"*, com retorno ao formulário via `next`.

**Observação (fora do escopo, não alterado):** o rótulo "Atualizar lista de alunos"
das telas de entrada/retirada é impreciso — aquela ação também atualiza turmas.
Vale renomear para "Atualizar alunos e turmas" numa próxima rodada.

---

## Rodada 3 — KPIs clicáveis, período padrão e ícone de editar

### 12. Ícone do botão "Editar" invisível — **corrigido (bug meu)**

**Diagnóstico.** O botão existia, o `<svg>` estava no DOM e o símbolo `#i-editar`
existia no sprite — mas nada aparecia. A causa está no contrato do sprite,
declarado no topo de `partials/icons.html`: *"Os símbolos não carregam fill/stroke
próprios: herdam do elemento pai"*. Os símbolos são desenhados **só com traço**.

`.icon-action svg` tinha `fill: none` e **nenhum `stroke`** → sem preenchimento e
sem traço, não se desenha nada. Também faltava `width`/`height`. Comparado ao
`.side-icon svg`, que funciona:

| | `.side-icon svg` (ok) | `.icon-action svg` (antes) |
|---|---|---|
| `fill` | `none` | `none` |
| `stroke` | `currentColor` | **ausente** |
| `width/height` | `16px` | **ausente** |

Foi introduzido por mim na rodada 1 (item 8, "Ícones no lugar de texto"). O
`.th-hint svg` (tooltip do STATUS, mesma rodada) foi escrito **com** o stroke —
a inconsistência ficou só no `.icon-action`.

**Alterado:** `static/css/components.css` — `.icon-action svg` ganhou
`stroke: currentColor`, `stroke-width: 2`, `linecap/linejoin` e `16px`.

**Verificado no navegador (computed style):** `stroke: rgb(139, 167, 204)`,
`stroke-width: 2px`, `16×16px`. Varredura confirmou que `.icon-action` era o
**único** consumidor do sprite sem stroke.

### 13. KPIs da Visão Geral viraram links — **implementado**

Cada card abre a listagem **com o mesmo recorte que usou para contar**.

**Dois problemas que precisaram ser resolvidos antes.**

1. **A listagem não tinha filtro de data.** Os KPIs são recortados por período;
   sem o mesmo recorte no destino, clicar num card abriria outro conjunto e o
   número não bateria. Então `home` passou a aceitar `data_inicio`/`data_fim`
   (preservados em hidden no form e com chip removível).
2. **Os KPIs contavam registros; a listagem agora conta pacotes** (rodada 2). Um
   card "Total: 100 registros" abriria uma tela com ~60 linhas. Essa
   inconsistência **já existia** desde a rodada 2 — tornar os KPIs clicáveis
   apenas a expôs.

**Decisão:** alinhar os KPIs à listagem (passaram a ser por pacote), com uma
**fonte única da verdade**: o novo helper `views.linhas_de_pacote()`, usado pela
listagem **e** pelos KPIs — assim os dois não podem divergir.

| Antes (registros) | Agora (pacotes) | Link |
|---|---|---|
| Total / registros | **Total** / pacotes | `?<datas>` |
| Entradas | *(absorvido em Total — todo pacote é uma entrada)* | — |
| Retiradas | **Retirados** | `?status=retirado&<datas>` |
| Aguardando | **Aguardando** | `?status=pendente&<datas>` |
| — | **Sem status** (novo) | `?status=sem_status&<datas>` |

Os quatro são disjuntos e exaustivos: **Total = Retirados + Aguardando + Sem
status**. "Sem status" cobre os registros legados sem `retirado` definido.

**Alterado:** `views.py` (`linhas_de_pacote`, `_parse_data_br`,
`_filtrar_por_intervalo`, `home`, `cme_dashboard`), `dashboard_cme.html`,
`home.html`, `components.css` (`.metric-card--link`).

**Correção de rota:** a "atividade recente" passou a usar uma base própria (todos
os registros), não a de pacotes — é um feed de **eventos**. Com a base de pacotes,
as saídas sumiriam e a retirada apareceria datada pela data de **entrada**.

### 14. Período padrão da Visão Geral — **implementado**

Era **mês atual → hoje**; agora é **data do primeiro registro → hoje**, abrindo
com todo o histórico em vez de esconder o passado sem o usuário pedir.

- `views.py::cme_dashboard`: `linhas_de_pacote().aggregate(Min("data_hora"))`,
  convertido com `timezone.localtime()`. Banco vazio: cai para hoje→hoje.
- `dashboard_cme.html`: o botão de reset virou **"Todo o período"** (era "Mês
  atual", que deixou de descrever o padrão).

**Verificado na tela** (dados semeados, depois removidos): padrão veio
`11/06/2025 → 16/07/2026` (1º registro → hoje); cards `12 / 6 / 5 / 1` somando 12;
clicar em **Aguardando (5)** abriu a listagem com **exatamente 5 linhas**, com o
período preservado; **Total (12)** → "12 registros".

**Pendência (negócio):** com o histórico inteiro como padrão, a Visão Geral passa
a varrer toda a tabela a cada carga. Hoje o volume é pequeno, mas se o histórico
crescer muito vale um índice em `data_hora` (relacionado ao B-07 da auditoria) ou
voltar a um padrão mais curto.

## Pendências consolidadas para o time de negócio

1. **CME-1:** cadastro de kit pela interface deve permitir quantidade por material?
2. **Contratos-1:** padronizar "Eduq" → "EDUQ" também na app de CME (transversal)?
3. **Contratos-2:** confirmar as colunas "realmente necessárias" na listagem.
4. **Contratos-3:** identificador preferido (CPF vs nascimento)? Se CPF for
   obrigatório para pacientes não importados, aceitar o custo de detalhe por linha?
5. **Contratos-5:** padronizar tipografia também nas telas públicas de assinatura?
6. **Busca CME:** como encontrar aluno ainda não sincronizado do Eduq — sincronizar
   a turma sob demanda, ou solicitar ao fornecedor um endpoint de busca por nome?
