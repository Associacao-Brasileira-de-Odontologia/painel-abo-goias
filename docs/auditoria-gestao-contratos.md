# Auditoria — Gestão de Contratos (`gestao_contratos`)

> Data da auditoria: 2026-07-13 · Ambiente: desenvolvimento (Windows, SQLite local).
> Integração compartilhada: **Dental Office OK** (mesmo cliente HTTP de `gestao_lab`,
> autenticação validada). Escopo das Fases 2/3 do brief **não** inclui alterações
> funcionais aqui — auditoria documental + eventual padronização visual (Fase 2).
> **Re-auditado após `git pull` (HEAD `8e91a28`):** o pull trouxe features novas —
> **QR Code de validação no rodapé do PDF assinado** (`services/validacao.py`,
> `views_validacao.py`, rota pública de validação) e a **migração do envio WhatsApp** do
> antigo `services/whatsapp/meta_cloud.py` (removido) para o pacote `mensageria` (Z-API).
> A suíte de `gestao_contratos` cresceu muito (+1386 linhas de testes).

## 1. Visão geral

Gera termos de consentimento (DOCX + PDF, 100% em código via `python-docx`/`reportlab`),
conduz **assinatura remota** (QR Code no celular do paciente **ou** terminal dedicado),
com verificação de identidade (data de nascimento do paciente ou CPF do responsável legal),
confirmação presencial do colaborador, **carimbo de tempo RFC 3161** e envio assíncrono
(Celery) ao Dental Office e por WhatsApp (via `mensageria`/Z-API pós-pull; o antigo
`meta_cloud.py` foi removido).

Modelos: `ContratoGerado`, `SessaoAssinatura`, `TerminalAssinatura`, `EventoContrato`.
Serviços: `documentos`, `assinatura`, `assinatura_pdf`, `carimbo_tempo`, `checklist`,
`envio`, `envio_dental`. Tasks Celery: envio Dental (retry), WhatsApp, carimbo de tempo,
expiração de sessões (Beat). É a app mais madura do projeto (README documenta o fluxo em
detalhe e cita 100% de cobertura na lógica de negócio).

## 2. Fluxos testados e resultado

| Fluxo | Método | Resultado |
|---|---|---|
| `manage.py check` | system check | ✅ 0 issues |
| Suíte automatizada (projeto todo) | `manage.py test` | ✅ **581 testes, todos passam** (inclui os novos de validação QR / Z-API) |
| Verificação de identidade (paciente/menor) | testes `VerificarIdentidade*Tests` | ✅ bloqueio após 5 tentativas; papel do responsável registrado |
| Validação da imagem de assinatura | `ValidarPngEdgeCasesTests` | ✅ rejeita não-PNG, muito pequena, acima do limite, base64 inválido |
| Terminal dedicado (polling/redirect) | `TerminalStatusFragmentViewTests` | ✅ fragmento de espera + 404 em token inválido |

> O achado global **A-01** (manifest de estáticos sem `collectstatic`) está **corrigido** —
> a suíte roda num checkout limpo, sem passo prévio. Basta executá-la de dentro de
> `abo-goias/`.

## 3. Bugs / inconsistências encontrados

Nenhum bug funcional novo identificado nesta auditoria — a app está madura e bem testada.
Os pontos abaixo são **pendências já conhecidas** (documentadas no README) e uma observação
de consistência visual:

### A-01 · ~~Suíte global depende de `collectstatic`~~ — **CORRIGIDO**
Idem demais apps. Ver `auditoria-identificadores.md#a-01`. **Reverificado em 2026-07-15**
com `staticfiles/` removido: 581 testes, verde, sem passo manual.

### A-07 · Padronização visual de botões — **leve** (escopo 2.2)
`gestao_contratos` tem CSS próprio (`css/contratos.css`, `css/assinatura.css`). Ao aplicar a
padronização da Fase 2, alinhar as classes de botão/ordem também aqui (sem tocar na lógica
de assinatura). As telas públicas de assinatura têm requisitos próprios (UX de canvas) e
devem ser tratadas com cuidado.

## 4. Necessidades de alteração (identificadas nesta auditoria)

- **Fase 2** (visual apenas): revisar botões/ordem nas telas de staff
  (`contratos.html`, `confirmar_dados.html`, `gerar_contrato.html`, `pos_geracao.html`) e o
  spinner de busca em `contratos.html`. **Não** alterar as telas públicas de assinatura sem
  validação dedicada.
- **Pendências operacionais** (README, fora do escopo de código desta rodada): worker+beat
  Celery + Redis em produção; verificação da conta WhatsApp Business + template aprovado;
  Volume persistente + `DJANGO_MEDIA_ROOT` (filesystem efêmero no Railway).

## 5. Backlog de melhorias futuras (não prioritário)

- **B-13 (jurídico)**: definir prazo de retenção da auditoria; preencher contato do
  encarregado de dados (DPO) na política de privacidade; avaliar migrar para TSA credenciada
  pela ICP-Brasil (hoje `freetsa.org`, não credenciada). — todos já listados no README.
- ~~**B-14**: embutir o carimbo de tempo **antes** do envio automático ao Dental/WhatsApp
  (hoje as cópias automáticas costumam sair sem o carimbo por ordenação assíncrona).~~
  **Implementado em 2026-07-15** — ver `melhorias-cme-contratos-2026-07.md`.
- **B-15**: cobrir curatela de maiores incapazes no checklist de responsável legal.

## 6. Implementado nesta rodada (Fases 2 e 3)

_A preencher ao concluir a Fase 2 (apenas ajustes visuais, se aplicáveis)._

**Correções a serem aplicadas**
- Corrija os textos com nomenclatura dos sistemas "Dental Office" e "EDUQ". 
- Na tela principal onde o usuário realiza a busca pelo paciente, temos duas listagens porém quero apenas uma com as informações necessárias. 
- Na lisatagem de pacientes retirar o campo de 'ORIGEM' e deixar por outra informação do próprio paciente, assim, facilitar o usuário identificar o paciente por outra informação adicional;
- Quando o usuário clica no campo de 'Validar documento' é necessário que o sistema abra uma nova guia para essa aba;
- Para validar o usuário tem que realizar 
- Avaliar as fontes que foram utilizadas no sistema e padronizar com as outras aplicações;
- Quando o sistema não conseguir realizar o envio do documento ao Dental Office, o usuário deve ser notificado com alguma pop-up ou essas informações devem estar possíveis de visualização. Assim, será possível que o usuário não perca um documento assinado porém não encaminhado ao Dental Office;
- 