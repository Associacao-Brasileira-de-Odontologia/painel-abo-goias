# Auditoria — Gestão de CME (`gestao_cme`)

> Data da auditoria: 2026-07-13 · Ambiente: desenvolvimento (Windows, SQLite local).
> Integrações validadas ao vivo: **Eduq OK** (43 turmas no `sincronizar_eduq --dry-run`).
> **Re-auditado após `git pull` (HEAD `8e91a28`):** templates migraram para a base
> compartilhada (`layouts/painel.html`, `components.css`); a **autenticação saiu para o app
> `contas`** (o `gestao_cme` ainda hospeda o portal `/`); o pull adicionou
> `excluir_movimentacao` (bom modelo de exclusão com modal `data-confirm`).

## 1. Visão geral

Aplicação central de **Central de Material e Esterilização**. Controla cadastros
acadêmicos (turmas/alunos sincronizados do Eduq), materiais, kits, armários/abrigos,
estoques, empréstimos e movimentações (entrada/saída de pacotes). Também serve o **portal**
inicial e as telas de autenticação.

Nota técnica herdada: o app usa `label = "core"` em `apps.py` por compatibilidade com
migrations/fixtures/admin legados (`/admin/core/...`), conforme documentado no README.

Principais telas (rotas em `gestao_cme/urls.py`):
`/` portal · `/gestao-cme/movimentacoes/` · `/gestao-cme/visao-geral/` (dashboard) ·
`/alunos-por-turma/` · `/materiais/` (+ novo/editar) · `/kits/` · `/abrigos/` (+ novo/editar) ·
`/gestao-cme/nova-entrada/` · `/gestao-cme/nova-saida/` · `/emprestimos/` (+ novo/devolver) ·
`/turmas/nova/` · sincronizações Eduq.

## 2. Fluxos testados e resultado

| Fluxo | Método | Resultado |
|---|---|---|
| `manage.py check` | system check | ✅ 0 issues |
| Sincronização Eduq (turmas/alunos) | `sincronizar_eduq --dry-run` | ✅ API responde (43 turmas) |
| Cadastro material / edição | leitura de `MaterialForm`/`MaterialEditForm` + views | ✅ validação de código único OK |
| Registrar entrada (lote de pacotes) | `EntradaForm` + `registrar_entrada` | ✅ gera sequência numérica global; avisa aluno sem abrigo |
| Registrar saída (2 passos) | `registrar_saida` | ✅ lista pendentes por aluno e baixa `retirado=True` |
| Empréstimos (criar/devolver/atrasar) | views + `EmprestimoForm` | ✅ cria itens a partir do kit |
| Busca/paginação nas listagens | `materiais`, `kits`, `emprestimos`, `alunos_por_turma` | ✅ busca por múltiplos campos + paginação 10/pág |
| Suíte automatizada (projeto todo) | `manage.py test` (após `collectstatic`) | ✅ **541 testes, todos passam**. Sem `collectstatic`: erros por **A-01** |

## 3. Bugs / inconsistências encontrados

### A-01 · Suíte de testes quebra sem `collectstatic` — **moderado** (global)
Ver detalhamento em `auditoria-identificadores.md#a-01`. **Pós-pull:** a suíte completa tem
**541 testes** e fica **100% verde após `manage.py collectstatic --noinput`**. Sem
`collectstatic`, os testes que renderizam `{% static %}` quebram com
`Missing staticfiles manifest entry` (manifest storage do whitenoise ativo em teste). Ou
seja: não é bug de produto, é uma pegadinha de fluxo de validação.

### A-05 · Seleção de aluno por `<select>` massivo em entrada/saída/empréstimo — **leve** (escopo 3.2)
`registrar_entrada.html`, `registrar_saida` e `criar_emprestimo.html` renderizam **todos**
os alunos ativos num `<select>` (com `optgroup` por turma). Com o volume real de alunos
(dezenas/centenas por turma × 43 turmas) isso fica pesado e difícil de usar. → feature 3.2
(autocomplete).

### A-06 · Sem indicador de carregamento nas buscas — **leve** (escopo 2.1)
As buscas (`materiais`, `kits`, `emprestimos`, `alunos_por_turma`, movimentações) são forms
GET com reload de página inteira e **nenhum feedback visual** durante o carregamento.

### A-07 · Botões de ação quebrados por vazamento de CSS + alocação — **moderado** (revisto)
> Reclassificado após varredura visual (screenshot do usuário em `cadastrar_turma`). A
> conclusão inicial ("resolvido pelo refactor") estava **errada**.

Formulários com a classe `form-stack` sofrem duas regras de `components.css` que vazam para a
barra de ações `.form-actions`: `.form-stack .button{width:100%}` (primário estica na largura
toda) e `.form-stack .secondary{border:0;background:transparent;color:muted}` ("Cancelar" vira
**link de texto apagado**, empurrado para baixo e à esquerda). Afeta 8 forms do `gestao_cme`
(`cadastrar_aluno`, `cadastrar_turma`, `criar_emprestimo`, `editar_movimentacao`, `form_abrigo`,
`form_material`, `registrar_entrada`, `registrar_saida`). Há também **navegação duplicada**
("Voltar à listagem" no `panel_actions` + "Cancelar" no rodapé, para a mesma URL). Os forms de
`gestao_contratos` usam só `form-stack-wide` (sem `form-stack`) e renderizam certo — padrão de
referência. → Fix CSS-first na Fase 2.2 (ver plano).

### A-08 · Material não tem exclusão pela UI — **leve** (escopo 3.2)
`editar_material` só edita/inativa (`MaterialEditForm` expõe `ativo`). Não há ação de
**excluir** material. `Material` é `PROTECT` por `ItemEmprestimo`, `KitMaterial`,
`EstoqueArmario` → a exclusão precisa tratar `ProtectedError` e informar quantas unidades
estão em empréstimo.

## 4. Necessidades de alteração (identificadas nesta auditoria)

- **Feature 3.2** (planejada): autocomplete de aluno em entrada/saída; botão "atualizar
  alunos" (sync Eduq) nessas telas; exclusão de material com confirmação (irreversível +
  contagem de unidades em empréstimo = `Σ ItemEmprestimo.quantidade` com
  `Emprestimo.status ∈ {EMPRESTADO, ATRASADO}`).
- **Fase 2**: spinner de busca (A-06) e padronização de botões (A-07).
- **A-01**: tornar a suíte verde sem passo manual (backlog B-01, ver Identificadores).

## 5. Backlog de melhorias futuras (não prioritário)

- **B-05**: remover a criação automática do usuário `coordenador.teste` por migration antes
  de produção (já apontado no README) — substituir por management command de dev.
- **B-06**: revisitar o `label = "core"` legado — decidir renomear app label/tabelas/admin
  ou manter permanentemente (já apontado no README).
- **B-07**: `pacote_codigo` da entrada usa `max(codigos numéricos)+n` varrendo **todas** as
  movimentações a cada registro — indexar/otimizar quando o histórico crescer.
- **B-08**: logs estruturados para erros de integração Eduq (já apontado no README).

## 6. Implementado nesta rodada (Fases 2 e 3)

**Fase 2.2 — barra de ações padronizada (A-07):**
- Fix único em `static/css/components.css` escopado a `.form-stack .form-actions` /
  `.form-stack-wide .form-actions`: alinhado à direita, separador acima, botões lado a lado;
  corrigido o vazamento que deixava o primário full-width e o secundário como link fraco.
  Não afeta fragmentos HTMX nem o modal de confirmação.
- Removida a navegação duplicada ("Voltar à listagem"/"Voltar ao histórico" no topo) em
  `cadastrar_aluno`, `cadastrar_turma`, `criar_emprestimo`, `form_abrigo`, `form_material`,
  `registrar_entrada`, `editar_movimentacao` — mantido o "Cancelar" na barra de ações.
  (`registrar_saida` mantém o "Voltar" do topo por não ter Cancelar no rodapé.)
- Verificado no navegador (`cadastrar_turma`) — alinha com o mockup aprovado.
### Sincronização em segundo plano (item 4) — implementada
O Eduq **não oferece busca de aluno por nome** (só `listar_alunos` por turma), então as telas
do CME pesquisam apenas o que já está no banco. Sem uma rotina automática, a completude
dependia de alguém apertar "Atualizar lista de alunos" — o operador tendo que saber que existe
uma sincronização.

**Implementado:** `gestao_cme/tasks.py::sincronizar_eduq_task`, agendada no Celery Beat
(`CELERY_BEAT_SCHEDULE`) às **04:00** — fora do horário de atendimento, porque percorre todas
as turmas. Retry com backoff (até 3): a janela é diária, então sem retry uma falha pontual de
rede deixaria a base parada por 24h. Par no lab: `sincronizar_dental_task` às **04:30**
(escalonada para não bater nas duas APIs ao mesmo tempo), reusando `executar_sync_e_registrar`
— as execuções automáticas alimentam o mesmo `RegistroSync` já exibido na interface.

> **O botão manual continua.** O brief da Fase 3.2 pede explicitamente "um botão/ação para
> atualizar a listagem de alunos" nas telas de entrada/saída, e ele resolve o caso real de um
> aluno matriculado hoje que não pode esperar até as 04:00. Com o agendamento, deixou de ser
> o caminho normal e virou exceção.
>
> **Se houver um cron externo** chamando `/laboratorio/sincronizar-agendado/`, desative-o: o
> Beat agora cobre isso e os dois juntos sincronizam em duplicidade (sem estragar nada, mas
> sem necessidade).

### A-19 · Busca era sensível a acento — **crítico** (encontrado na investigação, CORRIGIDO)
Os cadastros chegam do Eduq/Dental com grafia mista e o operador digita sem acento — mas a
busca era acento-sensível (`nome__icontains`). Medido nos 378 alunos reais:

| Digitando | Antes | Depois |
|---|---|---|
| `HONORIO` | **0** | 1 |
| `GONCALVES` | 1 | **7** |
| `GONÇALVES` | 6 | **7** |
| `ARAUJO` / `ARAÚJO` | 2 / 3 | **5 / 5** |

Ou seja: quem digitava "Honorio" **não achava ninguém**, e as duas grafias devolviam conjuntos
diferentes. **Correção:** campo derivado `nome_normalizado` (sem acento, caixa alta, indexado)
em `Aluno`, `Turma`, `Paciente` e `AlunoLab` via `NomeNormalizadoMixin` — recalculado no
`save()` (cobre cadastro manual, sincronização e admin, inclusive com `update_fields`) — mais
migrations com backfill dos registros existentes (378 alunos + 43 turmas). As buscas por nome
passaram a casar pelo campo normalizado; matrícula/código/celular seguem como estavam.
Normalização centralizada em `gestao_cme/utils.py::normalizar_texto` (o `eduq_sync` reusa a
mesma função). Escolhido campo derivado em vez do `unaccent` do PostgreSQL para funcionar
igual no SQLite de dev/testes.

**Fase 2.1 — spinner de busca:** `static/js/app.js` estendido para aplicar `.button.is-loading`
+ desabilitar o botão no submit de `.filter-bar` (todas as listagens com busca) e
`.js-loading-submit`. Verificado no navegador (`materiais`).
- Nota operacional: após o pull foi necessário `manage.py migrate` (migrations `0011`,
  `0015`, `0016`); a `0011` remove o usuário `coordenador.teste`.

**Fase 3.2 — Controle de materiais (implementada e verificada no navegador):**
- **Autocomplete de aluno** em `registrar_entrada` e `registrar_saida` (HTMX → nova view
  `buscar_alunos`, por nome/matrícula; `hidden` com o pk alimenta o form). Na saída, a busca
  usa `pendencias=1` (só alunos com pacotes aguardando retirada) e navega ao selecionar.
- **Botão "Atualizar alunos (Eduq)"** nas duas telas (`.sync-form` → nova view
  `atualizar_alunos_eduq` = `sincronizar_eduq(turmas+alunos)`; loading pela 2.1).
- **Exclusão de material**: nova view `excluir_material` (POST, espelha `excluir_movimentacao`)
  + "Zona de exclusão" no `form_material` (edição) com botão `.danger-button` + `data-confirm`
  informando irreversibilidade e **N unidades em empréstimo** (`Σ ItemEmprestimo.quantidade`
  com status EMPRESTADO/ATRASADO). `ProtectedError` tratado → mensagem clara + redireciona.
- Arquivos: `gestao_cme/{views,urls}.py`, `registrar_entrada.html`, `registrar_saida.html`,
  `form_material.html`, `partials/_aluno_results.html`, `static/css/components.css`
  (`.search-results`/`.selected-chip`). **6 testes novos** (suíte `gestao_cme` 55/55 verde).
- Verificação ao vivo: busca+seleção de aluno, POST de entrada, filtro de pendências na saída,
  exclusão de material livre (OK) e bloqueio de material em empréstimo (ProtectedError).
- Backlog (novo): a "Atualizar alunos" roda o sync do Eduq **síncrono** no request (pode ser
  lento com muitas turmas) → mover para rotina assíncrona (Celery) — mesmo ponto do A-03.**


**Novas inconsistências auditadas no sistema**

- Adicionar na tela de listagem de kits de materiais um botão para cadastro dos kits (primeiro validar a real necessidade do botão e documentar)
- Adicionar pop-up de confirmação 'obrigando' o usuário a fazer dupla checagem no momento de alterar as informações do abrigo. Para o pop-up adicionar uma mensagem com informações relevantes como, abrigo ocupado por material de 'fulano', abrigo já cadastrado para 'ciclano' e etc.
- Acrescentar uma mensagem informativa ao campo 'STATUS' na tabela de listagem de alunos. Como o campo status tem ambiguidade, pois, trata-se da situação do aluno cadastradado ou não em turmas ativas, é necessário adicionar uma mensagem informativa quando o usuário passar o mouse por cima do campo. Adicionar também um ícone de atenção (!) indicando a mensagem.
-  Atualize o estilo aplicado ao botão 'Limpar tudo' para o design pré-definido no plano
- Corrija a correspondência entre as chaves da tabela de abrigos e a listagem de alunos por turma. Quando o usuário realiza a atualização do abrigo na tabela de alunos, automaticamente, os campos de 'OCUPACAO' da tabela abrigos deve ser atualizado com a informação de ocupado. 
- Na tabela de listagem de alunos por turma, na coluna 'MOVIMENTACAO' o usuário deve ter a opção de clicar sobre o número de movimentação(ões) e, consequentemente, o sistema deve retornar a listagem de todas as movimentações daquele aluno.
- Para o formulário de cadastro de empréstimos, corrija a implementação do campo de seleção de alunos para a mesma do formulário de cadastro de entrada.
- Verifique todos os templates que possuem a opção de 'Editar' dentro de alguma listagem. Troque os textos dos botões por um ícone que corresponda a ação de editar.
- Para o formulário de edição de abrigo, adicione o botão de exclusão do item e pop-up de confirmação.