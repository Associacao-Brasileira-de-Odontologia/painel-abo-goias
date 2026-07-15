# Auditoria — Gestão de Laboratório (`gestao_lab`)

> Data da auditoria: 2026-07-13 · Ambiente: desenvolvimento (Windows, SQLite local).
> Integrações validadas ao vivo: **Dental Office OK** (autenticação bem-sucedida —
> token obtido em `testar_envio_dental --apenas-auth`).
> **Re-auditado após `git pull` (HEAD `8e91a28`):** templates na base compartilhada; o cliente
> Dental (`integrations/dental.py`) foi bastante refatorado (paginação/retry/limites — visto
> nos logs de teste); e foi adicionada uma **feature de cobrança automática por WhatsApp**
> (ver A-16). Suíte de `gestao_lab` cresceu (+590 linhas de testes).

## 1. Visão geral

Controla o fluxo de **pedidos de material a laboratórios externos** (moldagem → pedido →
envio → entrega → faturamento) e sincroniza **pacientes e alunos do Dental Office**.

Modelos: `Paciente`, `AlunoLab`, `Laboratorio`, `Equipe`, `Moldagem`, `PedidoMaterial`
(status calculado automaticamente: EM_DIA / A_CONFIRMAR / ATRASADO / CONCLUIDO),
`RegistroSync` (auditoria de cada sincronização). Estende o design system compartilhado
(`layouts/painel.html`, `components.css`).

Rotas (`gestao_lab/urls.py`): dashboard · pedidos (acompanhamento/novo/detalhe/envio/
entrega/faturamento) · moldagens (nova/converter/faturar/entregar) · laboratórios · equipes ·
alunos · pacientes · `sincronizar/` (Dental) · `buscar-paciente/` e `buscar-aluno/`
(importação pontual do Dental) · `sincronizar-agendado/` (endpoint por token para cron).

## 2. Fluxos testados e resultado

| Fluxo | Método | Resultado |
|---|---|---|
| `manage.py check` | system check | ✅ 0 issues |
| Autenticação Dental Office | `testar_envio_dental --apenas-auth` | ✅ token JWT obtido |
| Suíte automatizada (projeto todo) | `manage.py test` (após `collectstatic`) | ✅ **541 testes, todos passam** (inclui os novos de `gestao_lab`) |
| Criar pedido (paciente/aluno/lab/equipe) | `PedidoMaterialForm` + `criar_pedido` | ✅ status calculado no `save()` |
| Converter moldagem → pedido | `converter_moldagem` | ✅ pré-preenche paciente/aluno via `?moldagem=` |
| Busca direcionada Dental (importar) | `buscar_paciente_dental`/`buscar_aluno_dental` | ✅ valida `next` contra allowlist; importa e redireciona |
| Sincronização completa Dental | `sincronizar_dental` (view POST) | ✅ registra `RegistroSync` com contadores/duração |
| Busca/paginação nas listagens | pedidos, moldagens, labs, equipes, alunos, pacientes | ✅ busca por múltiplos campos + paginação 10/pág |

Observação factual: banco local com **1 paciente** e 0 pedidos/moldagens/labs/equipes — os
fluxos foram validados por código + testes; um exercício ponta-a-ponta com dados reais
exige uma sincronização Dental completa.

## 3. Bugs / inconsistências encontrados

### A-09 · Paciente/Aluno por `<select>` no formulário de pedido/moldagem — **leve** (escopo 3.3)
`form_pedido.html` e `form_moldagem.html` iteram **toda** a queryset de pacientes/alunos num
`<select>`. Com a base real do Dental (potencialmente milhares de pacientes) fica
inutilizável. → feature 3.3 (busca com seleção). A busca direta no Dental já existe
(`partials/busca_dental.html`), mas seleciona por reload, não por autocomplete.

### A-10 · Sem exclusão de pedidos/moldagens pela UI — **leve** (escopo 3.3)
As listagens (`acompanhamento_pedidos.html`, `moldagens.html`) não oferecem excluir
registro. `PedidoMaterial`/`Moldagem` não são protegidos por FKs de entrada (apenas
`Moldagem.pedido_material` é `SET_NULL`), então a exclusão é segura — falta a ação + a
confirmação.

### A-11 · Sincronização Dental só acessível pela tela de pacientes — **leve** (escopo 3.3)
`sincronizar_dental` sempre redireciona para `lab_pacientes`. A listagem de **alunos**
(`alunos.html`) mostra "última sync" e histórico, mas não expõe o botão de sincronizar. →
feature 3.3 (expor sync nas listagens de alunos e pacientes).

### A-06 · Sem spinner de busca — **leve** (escopo 2.1)
Buscas GET ainda sem feedback visual → Fase 2.1.

### A-07 · Botões de ação quebrados por vazamento de CSS — **moderado** (revisto)
Mesmo defeito global do `gestao_cme` (ver `auditoria-gestao-cme.md#a-07`): `form_pedido.html`,
`form_moldagem.html`, `form_equipe.html` e `form_laboratorio.html` usam `form-stack` +
`form-actions`, então o primário fica full-width e o "Cancelar" vira link fraco. Além disso,
os botões "Importar paciente/aluno" da busca lateral (`partials/busca_dental.html`) também são
esmaecidos pela mesma regra. → Fix CSS-first na Fase 2.2.

### A-12 · `sincronizar_agendado` é `@csrf_exempt` e público (token-based) — **leve (informativo)**
Correto por design (endpoint para cron externo, autenticado por `X-Sync-Token` com
`compare_digest`). Registrado apenas para rastreabilidade de segurança; sem ação necessária
desde que `DENTAL_SYNC_TOKEN` seja forte e secreto.

### A-16 · Cobrança automática por WhatsApp (Z-API) — **informativo (feature nova do pull)**
`services/cobranca.py` + `tasks.py::cobrar_pedidos_atrasados_task` (Celery Beat): agrega por
laboratório os `PedidoMaterial` com status `ATRASADO` ainda não cobrados no dia e envia **uma**
mensagem por lab via `mensageria` (Z-API), marcando `cobranca_whatsapp_enviada_em`. Desativa
graciosamente sem credenciais Z-API. Bem desenhado; sem ação. Depende de worker+beat Celery em
produção (mesma pendência operacional do envio de contratos).

## 4. Necessidades de alteração (identificadas nesta auditoria)

- **Feature 3.3** (planejada): busca com seleção para Paciente e Aluno em pedido/moldagem;
  exclusão de pedidos/moldagens com confirmação; botão de sincronizar Dental nas listagens
  de alunos e pacientes.
- **Fase 2**: spinner de busca (A-06) e padronização de botões (A-07).

## 5. Backlog de melhorias futuras (não prioritário)

- **B-09**: autocomplete que busca **direto no Dental Office** (não só na base local
  sincronizada) a partir do mesmo campo, unificando `busca_dental` + seleção.
- **B-10**: paginação/limite nos autocompletes e debounce configurável.
- **B-11**: página de histórico completo de `RegistroSync` (hoje só os 5 últimos aparecem
  nas listagens).
- **B-12**: agendar a sincronização Dental via Celery Beat (já há infra) em vez de depender
  só de cron externo.

## 6. Implementado nesta rodada (Fases 2 e 3)

**Fase 2.2 — barra de ações padronizada (A-07):** o fix de CSS (ver
`auditoria-gestao-cme.md#6`) também corrige `form_pedido`, `form_moldagem`, `form_equipe`,
`form_laboratorio`; navegação duplicada ("Voltar" no topo) removida nesses quatro. Verificado
no navegador (`form_pedido`).

**Fase 2.1 + busca lateral:** os botões "Importar paciente/aluno" da `busca_dental.html` viraram
botão real (compacto, com borda/fundo) e ganharam o spinner de carregamento no submit (a
importação bate na API do Dental). Verificado no navegador.

**Fase 3.3 — Pedidos e moldagens (implementada e verificada no navegador):**
- **Busca com seleção (A-09 resolvido):** os `<select>` de **Paciente** e **Aluno** em
  `form_pedido` e `form_moldagem` viraram autocomplete (HTMX → novas views `buscar_pacientes`
  e `buscar_alunos_lab`, por nome/celular). Implementado com um partial reutilizável
  (`partials/_ac_field.html` + `_ac_results.html`) e um handler genérico `[data-ac]` em
  `app.js` — os dois campos funcionam de forma independente na mesma tela, com chip do
  selecionado e botão "Trocar". `Laboratório`/`Equipe` seguem como `<select>` (listas curtas).
  A seleção é preservada quando o formulário volta com erro (helper `_selecionado`).
- **Exclusão (A-10 resolvido):** novas views `excluir_pedido`/`excluir_moldagem` (POST + `next`)
  + botão `.danger-button` com `data-confirm-danger` nas listagens. Ao excluir um pedido vindo
  de moldagem, o vínculo é desfeito (SET_NULL) e a moldagem volta a "não convertida" — avisado
  na confirmação.
- **Sincronização nas listagens (A-11 resolvido):** o botão já existia (`partials/sync_dental.html`
  em `alunos.html` e `pacientes.html`, trazido pelo refactor); o que faltava era o
  `sincronizar_dental` **sempre redirecionar para pacientes** — agora honra `next` e volta para
  a listagem de origem. Loading já coberto pela 2.1 (`.sync-form`).
- Arquivos: `gestao_lab/{views,urls,tests}.py`, `form_pedido.html`, `form_moldagem.html`,
  `acompanhamento_pedidos.html`, `moldagens.html`, `partials/{_ac_field,_ac_results,sync_dental}.html`,
  `static/js/app.js`. **8 testes novos** (suíte `gestao_lab` 114/114 verde).
- Verificação ao vivo: busca de paciente/aluno, seleção nos dois campos, "Trocar", criação de
  pedido pelos pks do autocomplete, exclusão de pedido e de moldagem.

### Sincronização em segundo plano (item 4) — implementada
`gestao_lab/tasks.py::sincronizar_dental_task`, agendada no Celery Beat às **04:30**
(escalonada em relação à do Eduq, às 04:00 — são rotinas longas e não convém bater nas duas
APIs ao mesmo tempo). Reusa `executar_sync_e_registrar`, então as execuções automáticas
alimentam o mesmo `RegistroSync` exibido em "Histórico de atualizações". Retry com backoff
(até 3) porque a janela é diária. Sem `DENTAL_CLINIC_ID`, não faz nada e loga um aviso —
mesmo padrão das demais integrações opcionais.

Com a busca unificada (item 3) consultando a API ao vivo, esta rotina serve às **telas de
consulta** (listagens de pacientes/alunos) e ao trabalho sobre a base local — não é mais o que
sustenta a busca dos formulários.

> **Atenção operacional:** se houver um cron externo chamando
> `/laboratorio/sincronizar-agendado/`, desative-o — o Beat agora cobre isso e os dois juntos
> sincronizam em duplicidade.
>
> **Não executado contra a API real:** diferente da task do Eduq, esta percorre *todos* os
> pacientes da clínica; rodá-la aqui encheria a base de desenvolvimento com milhares de
> registros para provar um caminho (`executar_sync_e_registrar`) que já existia e já era
> exercitado pelo endpoint de cron. A task em si é um invólucro fino, coberto por testes com
> mock (sucesso, histórico e ausência de configuração).

### Busca unificada (item 3) — implementada
Fecha o que a correção do A-18 tinha deixado como paliativo (o botão "Procurar em todos os
cadastros", que levava ~9s e importava todos os resultados).

**Como ficou:** um campo só. Ao digitar, a view consulta **a base local e a API em conjunto**
e devolve **uma lista única, sem dizer de onde veio cada resultado** — o operador não precisa
saber que existe um Dental Office atrás. O registro só é gravado **quando ele escolhe**.

| | Antes (A-18) | Agora |
|---|---|---|
| Ação | botão "Procurar em todos os cadastros" | automático ao digitar |
| Tempo | ~9s | **~1,4s** |
| Gravações por busca | **149** | **0** |
| Gravações por escolha | 0 (já tinha importado tudo) | **1** (~0,7s) |

**Peças:** `procurar_pacientes`/`procurar_alunos` (leem só a 1ª página, sem gravar) e
`materializar_paciente`/`materializar_aluno` (gravam o escolhido). Os dados gravados vêm
sempre da API — o navegador só informa **qual id** foi escolhido, nunca o conteúdo do
registro. Paciente usa `GET /customers/{id}` (e já aproveita para trazer CPF/endereço, úteis
em contratos); aluno refaz a busca e casa pelo id, porque a API não expõe `GET /users/{id}`.
Endpoint `POST /laboratorio/selecionar/<tipo>/` devolve o pk em JSON; itens que já existem
no banco resolvem direto, sem ida à API.

**Degradação suave:** se a API cair, os resultados locais continuam aparecendo com o aviso
"alguns cadastros podem não aparecer agora" — a tela não quebra.

**Bug encontrado ao testar:** com o corte em 20 itens, uma página cheia da API (nomes que vêm
antes no alfabeto) **empurrava para fora** registros que já estavam no banco — buscar "Maria"
escondia a paciente local. Corrigido: os locais nunca são descartados na truncagem; os remotos
só preenchem as vagas restantes. Coberto por teste.

### A-18 · Busca do autocomplete não filtrava — **crítico** (reportado pelo usuário, corrigido)
Sintoma relatado: ao pesquisar "Gustavo" a listagem **não era atualizada**, tornando o
mecanismo inútil para selecionar o paciente. Duas causas somadas:

1. **O termo nunca era enviado.** Os inputs de busca do autocomplete não tinham o atributo
   `name`. O HTMX só envia o valor de um elemento que tenha `name` — sem ele, a view recebia
   `q=""` e devolvia **sempre a lista inteira, sem filtrar**, independentemente do que fosse
   digitado. Afetava `registrar_entrada`/`registrar_saida` (3.2) e `form_pedido`/`form_moldagem`
   (3.3). **Corrigido** com `name="q"` nos campos.
2. **A busca só olhava a base local.** O brief pede seleção "a partir dos resultados retornados
   pela API correspondente"; a base local tinha 2 pacientes, enquanto o Dental Office retorna
   **149** para "Gustavo". **Corrigido**: os resultados agora oferecem a ação **"Buscar no
   Dental Office"** (novas views `buscar_pacientes_dental`/`buscar_alunos_lab_dental`), que
   consulta a API, importa os registros (necessário: o pedido referencia um `Paciente` local
   com pk) e devolve o fragmento já selecionável. Mantida como ação **explícita** — cada busca
   na API importa todos os matches e leva ~9s, então dispará-la a cada tecla poluiria a base e
   travaria a digitação. A busca local segue instantânea.

> **Por que os testes não pegaram:** havia teste dos *endpoints* (passando `?q=` direto), mas
> nenhum da *ligação do template*. Pior: os testes interativos passaram por coincidência — o
> primeiro item da lista não-filtrada por acaso batia com o termo buscado (ADRYELLE, Joao).
> Adicionados testes de regressão que verificam `name="q"` + `hx-get` nos campos — validados
> reintroduzindo o bug (falham) e corrigindo (passam).

### A-17 · Atributo `hidden` era anulado pelo CSS — **moderado** (encontrado e corrigido aqui)
Descoberto por inspeção visual durante a 3.3: o chip "Trocar" aparecia mesmo sem nada
selecionado. Causa: não havia regra `[hidden]` no CSS do projeto, então
`.selected-chip{display:flex}` e `.field{display:grid}` **venciam** o `[hidden]{display:none}`
do navegador — qualquer elemento com o atributo `hidden` continuava visível. Afetava os chips
da 3.2 (`registrar_entrada`) e da 3.3. **Corrigido** com `[hidden]{display:none !important}` em
`static/css/base.css` (regra global de reset). Verificado no navegador (chips voltam a
`display:none`). Lição: a verificação por propriedade do DOM (`el.hidden === true`) não pega
esse caso — só o estilo computado/screenshot pega.
