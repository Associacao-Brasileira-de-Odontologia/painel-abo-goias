# Documentação — Gerador de Identificadores de Bancada (`identificadores`)

> Documento único e atual do módulo `identificadores`. Consolida a auditoria original
> (2026-07-13) e as rodadas de implementação/ajuste feitas desde então em um só lugar,
> organizado em duas partes: o que já foi documentado e solucionado, e o que ainda está
> pendente. Ver também [`jornada-identificadores.md`](jornada-identificadores.md) para a
> experiência do usuário, contada do ponto de vista de quem opera a tela.

## 1. Visão geral

Aplicação que gera arquivos **PPTX de identificadores de bancada** por turma. Fluxo
(`identificadores/views.py`):

1. A coordenação busca a turma (autocomplete) ou abre a lista completa filtrada por
   Ativas/Finalizadas/Todas.
2. Ao selecionar, vê um resumo da turma e, sob demanda, a lista de alunos (nome,
   matrícula, cidade/UF — vindos do Eduq).
3. Escolhe o modelo visual do identificador entre os disponíveis
   (`services/modelos.py::listar_modelos`).
4. Ao gerar, o sistema tenta atualizar a localização dos alunos sem cidade/UF via Eduq
   (`sincronizar_localizacao_alunos_turma`) e monta o arquivo
   (`gerar_arquivo_identificadores`), oferecido para download.

Há também uma sincronização manual de turmas e alunos (`views.sincronizar`), que chama
`sincronizar_eduq(sincronizar_turmas=True, sincronizar_alunos=True)`. A app reaproveita o
design system compartilhado (`layouts/painel.html`, `components.css`) e um CSS próprio
(`identificadores.css`).

## 2. O que foi documentado e solucionado

### 2.1 Auditoria inicial (2026-07-13)

A auditoria de backend cobriu os fluxos principais (`manage.py check`, sincronização Eduq,
seleção turma+modelo, suíte automatizada) — todos ✅ na época. Os achados abertos naquele
momento já foram todos resolvidos:

- **Suíte de testes dependia de `collectstatic`** — corrigido em `abo_goias/settings.py`
  (o storage com manifesto do whitenoise passou a ser aplicado só fora dos testes); suíte
  completa (581 testes) verde sem passo manual.
- **Índice não distinguia turma ativa de finalizada** — corrigido junto da feature de
  busca (abaixo): o critério semântico correto (`data_fim < hoje`) passou a alimentar o
  filtro.
- **Campo de turma era um `<select>` sem busca, e os alunos da turma nunca apareciam na
  tela** — era o principal ponto em aberto da auditoria; virou a feature de busca
  descrita a seguir.

### 2.2 Busca de turma, filtro por situação e dashboard (implementado e verificado com dados reais do Eduq)

- **Busca de turma → alunos:** o antigo `<select>` virou um campo de pesquisa com
  autocomplete (view `buscar_turmas`); ao selecionar a turma, um fragmento (`turma_alunos`)
  exibe os alunos sincronizados (cidade/UF, datas, matrículas ativas) — sob demanda, sem
  poluir a tela por padrão.
- **Filtro ativa/finalizada:** chips com contagem (Ativas / Finalizadas / Todas); critério:
  *finalizada* = `data_fim < hoje`, *ativa* = sem data ou data futura.
- **Dashboard:** turmas sincronizadas, ativas, finalizadas, alunos sincronizados e modelos
  disponíveis, num painel de métricas.
- **Geração:** passou a aceitar qualquer turma selecionada, inclusive finalizada (histórico).
- Testes: 9 casos na suíte de `identificadores`, verde.

### 2.3 Ajustes visuais posteriores (busca como combobox de verdade)

Em rodadas seguintes, a busca de turma foi refinada para se comportar como um combobox
completo: abrir a lista ao digitar, fechar ao clicar fora ou pressionar Escape, chevron
para abrir/fechar a lista completa, e correção de estouro (overflow) da tabela de alunos
e do corte no seletor de modelo. Esse comportamento é o descrito em
[`jornada-identificadores.md`](jornada-identificadores.md).

## 3. O que está pendente

Nenhum item crítico em aberto. Backlog de melhorias futuras, sem prioridade definida:

- **Sincronização de localização acoplada ao request de geração** — ao gerar o PPTX, se
  houver alunos sem cidade/UF, a view chama o Eduq de forma síncrona dentro do próprio
  request; uma indisponibilidade do Eduq atrasa (ou avisa, sem bloquear) o download.
  Candidato a mover para uma rotina assíncrona (Celery, já usado por `gestao_contratos`).
- **Cache/paginação de turmas quando o volume crescer** (hoje ~43 turmas via Eduq, tende
  a subir).
- Nenhum outro achado de segurança ou inconsistência funcional permanece em aberto desta
  aplicação.

## 4. Documentos substituídos por este arquivo

Este documento consolida e substitui `auditoria-identificadores.md` (2026-07-13), cujo
conteúdo foi incorporado acima.
