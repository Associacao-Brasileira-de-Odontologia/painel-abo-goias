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
