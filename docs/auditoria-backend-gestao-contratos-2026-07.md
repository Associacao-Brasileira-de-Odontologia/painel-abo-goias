# Auditoria de backend — Gestão de Contratos

> Data: 2026-07-15 · Escopo: `gestao_contratos` (views, services, models, tasks).
> Método: leitura do código + **reprodução em teste automatizado** de cada achado
> de segurança. Nenhuma correção foi aplicada — este documento é o diagnóstico.
> Achados marcados **[PROVADO]** foram reproduzidos executando o código.

A aplicação é madura e bem estruturada: separação clara entre views/services,
trilha de auditoria por evento (`EventoContrato`), claim atômico da sessão de
assinatura, degradação suave quando a API externa cai, e boa cobertura de testes.
Os achados abaixo são pontuais — nenhum invalida a arquitetura.

---

## CRÍTICO

### C-01 · PDF do contrato é entregue sem a verificação de identidade **[PROVADO]**

`views_assinatura.assinar_view` protege o conteúdo do contrato atrás da
confirmação de identidade (data de nascimento do paciente, ou CPF do responsável
quando menor) — enquanto `sessao.identidade_confirmada_em` for nulo, só a tela de
verificação é exibida.

**`assinar_pdf_view` (rota `assinar/<token>/pdf/`) não faz essa checagem.** Chama
apenas `resolver_token()` e devolve o PDF:

```python
def assinar_pdf_view(request, token):
    if _excedeu_rate_limit(request, "pdf"): ...
    try:
        sessao = resolver_token(token)      # valida só o token/estado da sessão
    except SessaoInvalida:
        raise Http404
    conteudo = _obter_pdf_original(sessao.contrato)   # ← sem checar identidade
    return HttpResponse(conteudo, content_type="application/pdf")
```

Reprodução (sessão recém-criada, identidade **não** confirmada):

```
>>> STATUS PDF SEM IDENTIDADE: 200
>>> CONTENT-TYPE: application/pdf
>>> TAMANHO: 2099
>>> identidade_confirmada_em: None
```

**Impacto:** quem obtiver o link/QR Code (print encaminhado, tablet compartilhado,
histórico do navegador, mensagem reencaminhada) baixa o termo completo — que
contém **nome, CPF, RG, endereço e informações de saúde** do paciente, exatamente
os dados que a política de privacidade da própria app declara tratar. O portão de
identidade vira decorativo: basta trocar a URL de `/assinar/<token>/` para
`/assinar/<token>/pdf/`. Relevante para a LGPD.

**Correção sugerida:** exigir `sessao.identidade_confirmada_em` antes de servir o
arquivo (404/410 caso contrário), espelhando a regra de `assinar_view`.

---

## ALTO

### A-01 · Open redirect pelo parâmetro `next` **[PROVADO]**

Dois padrões inseguros, em **10 pontos de 3 apps** (`grep 'startswith("/")'`):

1. **Sem validação nenhuma** — `gestao_cme.views.atribuir_abrigo:529`:
   ```python
   next_url = request.POST.get("next") or reverse("alunos_por_turma")
   return redirect(next_url)          # aceita URL absoluta externa
   ```
   Reprodução: `next=https://evil.example.com/phish` →
   `Location: https://evil.example.com/phish`.

2. **Validação insuficiente** — demais pontos usam `next_url.startswith("/")`,
   que **aceita `//host`** (URL protocolo-relativa → host externo):
   ```
   >>> [contratos] enviar_dental LOCATION: //evil.example.com/phish
   >>> [cme] alternar_retirado LOCATION: //evil.example.com/phish
   ```

**Impacto:** phishing — um link para o domínio legítimo (usuário já autenticado,
confiando no host) redireciona para um site externo, ex.: uma cópia da tela de
login. `django.utils.http.url_has_allowed_host_and_scheme` **não é usado em lugar
nenhum** do projeto.

**Correção sugerida:** helper único compartilhado:
```python
from django.utils.http import url_has_allowed_host_and_scheme

def _next_seguro(request, padrao):
    nxt = request.POST.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return padrao
```

> Transparência: um desses 10 pontos (`enviar_ao_dental_view`) **fui eu que
> introduzi** nesta rodada, copiando o padrão `startswith("/")` já existente. Os
> outros 9 são anteriores.

### A-02 · IP gravado no documento assinado é forjável pelo próprio signatário **[PROVADO]**

```python
def _ip_do_request(request):
    encadeado = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if encadeado:
        return encadeado.split(",")[0].strip()   # ← primeiro valor = enviado pelo cliente
    return request.META.get("REMOTE_ADDR")
```

O primeiro elemento do `X-Forwarded-For` é o que o **cliente** enviou; o proxy
apenas acrescenta o IP real ao final. Reprodução com header forjado:

```
>>> IP resolvido a partir de XFF forjado: 1.2.3.4
>>> REMOTE_ADDR real era: 10.0.0.1
```

**Impacto:** esse IP não é telemetria — ele é **impresso no rodapé do PDF
assinado** ("Assinado eletronicamente pelo paciente em ... — IP x.x.x.x", ver
`_texto_carimbo`) e gravado em `SessaoAssinatura.ip_assinatura` e nos eventos de
auditoria. Ou seja: uma evidência que o próprio signatário controla, num documento
cuja finalidade é justamente comprovar quem assinou. Também permite contornar o
rate-limit por IP (basta variar o header).

**Correção sugerida:** derivar o IP do número conhecido de proxies à frente (no
Railway, o último valor confiável), ou usar `REMOTE_ADDR` quando não houver proxy
confiável configurado.

---

## MÉDIO

### M-01 · Rate-limit sem backend de cache compartilhado

`settings.py` **não define `CACHES`** → Django usa `LocMemCache`, que é **por
processo** e some a cada deploy. `_excedeu_rate_limit` protege as rotas públicas
(`assinar`, `pdf`, `validar`) e depende disso.

**Impacto:** com N workers do gunicorn, o teto efetivo é ~`30 × N` req/min por IP,
e o contador zera a cada restart. Atenuante: o limite de tentativas de identidade
(`LIMITE_TENTATIVAS_IDENTIDADE = 5`) é **persistido no banco**, então a força bruta
sobre a data de nascimento continua barrada — o enfraquecimento é do rate-limit
genérico, não do controle de identidade.

**Correção sugerida:** apontar `CACHES` para o Redis que já existe para o Celery.

### M-02 · O PDF assinado pode ser perdido ao embutir o carimbo de tempo

`carimbo_tempo._embutir_carimbo_no_pdf_assinado`:
```python
contrato.arquivo_pdf_assinado.delete(save=False)          # apaga do storage
contrato.arquivo_pdf_assinado.save(nome_arquivo, ...)     # e só então grava o novo
```
Se o `save()` falhar (disco cheio, storage indisponível), o documento assinado —
o artefato de maior valor jurídico do sistema — **já foi apagado** e não há
substituto. A função é "melhor esforço" e engole exceções, então a falha ficaria
só no log.

**Correção sugerida:** gravar o novo arquivo primeiro e só apagar o antigo depois
de confirmado (ou não apagar, deixando a limpeza para uma rotina).

### M-03 · `versao` do contrato tem corrida e não tem constraint

`documentos.gerar_e_salvar_contrato`:
```python
versao = ContratoGerado.objects.filter(paciente=paciente, tipo=tipo).count() + 1
```
Duas gerações concorrentes do mesmo tipo para o mesmo paciente produzem a **mesma
versão**. Não há `UniqueConstraint(paciente, tipo, versao)` no modelo para barrar.

### M-04 · Sem escopo de autorização entre usuários

Todas as views de staff usam apenas `@login_required` + `get_object_or_404(pk=...)`,
**sem filtrar por usuário**. Qualquer conta autenticada lê, baixa e reenvia
qualquer contrato de qualquer paciente informando o pk na URL.

Isso contrasta com o `gestao_cme`, que escopa empréstimos por coordenador
(`emprestimos_visiveis`). Pode ser intencional (todo mundo é staff da mesma
clínica), mas, dado que contratos carregam CPF/RG/endereço/saúde, merece uma
decisão explícita do time — hoje é um default silencioso.

### M-05 · Geração de contrato sem transação

`gerar_e_salvar_contrato` grava DOCX + PDF + registro sem `transaction.atomic()`.
Não há `transaction.atomic` nem `select_for_update` em **nenhum** ponto de
`gestao_contratos`. Uma falha no meio deixa arquivos órfãos no storage.

---

## Carimbo de tempo — auditoria dedicada da etapa de embutir

> Validação do achado **B-14** já registrado em `auditoria-gestao-contratos.md`
> ("embutir o carimbo antes do envio automático — hoje as cópias automáticas
> costumam sair sem o carimbo por ordenação assíncrona").
> **Veredito: o problema continua presente.** Reproduzido com a TSA e o Dental
> Office mockados, em `CELERY_TASK_ALWAYS_EAGER` (ordem determinística).

### CT-01 · A cópia arquivada no Dental Office sai sem o carimbo **[PROVADO]**

`processar_assinatura` despacha as três tarefas em sequência, **sem dependência
entre elas**: `enviar_dental_task` → `enviar_whatsapp_task` →
`solicitar_carimbo_tempo_task`. O envio é disparado **primeiro**; o carimbo, que
ainda depende de um round-trip à TSA, chega **por último**. Resultado medido:

```
status_carimbo_tempo : concluido
status_envio_dental  : enviado
anexos no PDF ENVIADO ao Dental : []                      ← sem carimbo
anexos no PDF FINAL salvo       : ['carimbo_tempo.tsr']   ← com carimbo
Enviado == arquivo final? : False
```

O hash da cópia enviada é exatamente `hash_sha256` (versão pré-carimbo); o arquivo
final é `hash_arquivo_assinado`. Ou seja: **o documento que fica arquivado no
prontuário — a cópia oficial — é a única que não carrega a prova de data/hora.**
O carimbo só existe na cópia local. O mesmo vale para a cópia do WhatsApp
(despachada em 2º lugar, também antes do carimbo).

Atenuante: a cópia sem carimbo **continua validando** como autêntica na página
pública, porque `validar_pdf` tem um fallback por `hash_sha256`. Mas isso é
acidental — o fallback foi escrito para "contratos assinados antes deste campo
existir", e acaba cobrindo também a versão pré-carimbo.

Agravante (não determinístico): se o envio ao Dental falhar e for **retentado**
depois que o carimbo terminar, aí a cópia arquivada **terá** o carimbo. Então o
acervo fica inconsistente — alguns contratos arquivados com carimbo, outros sem,
dependendo de quem ganhou a corrida.

**Correção sugerida:** encadear — o envio ao Dental/WhatsApp deve ser disparado
**pelo** `solicitar_carimbo_tempo_task` ao concluir (Celery `chain`), com fallback
para disparo imediato quando a TSA não estiver configurada.

### CT-02 · Falha ao embutir é silenciosa e sem caminho de recuperação **[PROVADO]**

`_embutir_carimbo_no_pdf_assinado` é "melhor esforço": engole a exceção e só
loga. Mas `solicitar_carimbo` **retorna sucesso mesmo assim** e marca
`status_carimbo_tempo = "concluido"`. Cenário TSA-OK/embutir-falha:

```
solicitar_carimbo retornou ok? -> True | erro: ''
status_carimbo_tempo          -> concluido
token .tsr salvo avulso?      -> True
anexos no PDF assinado        -> []        ← o PDF não tem o carimbo
>>> UI mostra botao de retentar? -> False  ← (só aparece se status == "erro")
```

Ou seja: a tela exibe o selo verde **"Carimbo de tempo obtido"**, o PDF não tem
carimbo nenhum, e **não há botão para tentar de novo** (o botão só aparece com
status `"erro"`). O token existe apenas como `.tsr` avulso — e
`contrato_baixar_carimbo_tempo` **não é linkado por nenhum template** (confirmado
por grep), justamente porque o download avulso foi removido de propósito da tela.
A prova fica inalcançável pela interface, e a interface afirma o contrário.

**Correção sugerida:** distinguir os dois estados — o token foi obtido, mas o
embutir falhou (ex.: `status_carimbo_tempo = "concluido_sem_embutir"`, ou um
booleano `carimbo_embutido`) — e permitir retentar só o passo de embutir, sem
pedir um novo token à TSA.

### CT-03 · Re-carimbar invalida a cópia carimbada já distribuída **[PROVADO]**

`solicitar_carimbo` não verifica se o contrato **já tem** carimbo. Uma segunda
chamada pede um novo token, reescreve o PDF e atualiza `hash_arquivo_assinado`:

```
Cópia nº1 valida ANTES do re-carimbo?  -> True
Cópia nº1 valida DEPOIS do re-carimbo? -> False   ← documento legítimo rejeitado
Novo arquivo valida? -> True
```

A cópia carimbada nº1 (que o paciente pode ter baixado, e que pode estar no
Dental Office) passa a ser reportada pela página pública como **NÃO AUTÊNTICA** —
o pior desfecho possível para um sistema de validação: declarar falso um
documento genuíno emitido por ele mesmo. Ela não cai no fallback porque seu hash
não é nem `hash_sha256` (pré-carimbo) nem o novo `hash_arquivo_assinado`.

**Alcance real:** a UI **esconde** o botão quando o status é `"concluido"`, então
não é alcançável por clique normal. É alcançável por **POST direto**. Vale notar
que a app já adota explicitamente o padrão oposto em `enviar_ao_dental_view`
("A UI desabilita o botão; esta guarda cobre POST direto") — aqui a guarda
equivalente está faltando.

**Correção sugerida:** retornar cedo em `solicitar_carimbo` quando
`status_carimbo_tempo == "concluido"` e já houver token, a menos que um
`forcar=True` explícito seja passado.

### CT-04 · O carimbo de tempo não é visível no documento

Apenas o texto de auditoria da assinatura é impresso no rodapé (`_texto_carimbo`),
e a data/hora dele vem do **relógio do servidor** — não da TSA. O carimbo RFC 3161
entra só como **anexo invisível**. Quem recebe ou imprime o PDF não tem como ver
que existe uma prova de data/hora, nem qual é o instante atestado
(`carimbo_tempo_em`). Não é um bug, mas reduz bastante o valor prático do recurso.

**Sugestão:** imprimir no rodapé algo como "Carimbo de tempo RFC 3161: 15/07/2026
12:00 UTC — <TSA>", já que a informação existe em `carimbo_tempo_em`/`_tsa`.

### O que está correto nesta etapa

- O token é pedido sobre `hash_sha256` (o hash do PDF **assinado**, pré-anexo) —
  correto: é exatamente esse digest que a TSA atesta.
- `hash_sha256` é deliberadamente **não** recalculado após o anexo, e
  `hash_arquivo_assinado` passa a apontar para o arquivo final — a separação entre
  "hash coberto pela TSA" e "hash do arquivo distribuído" está bem modelada e bem
  comentada.
- `genTime` do token é convertido corretamente para UTC (`replace(tzinfo=utc)`).
- Sem TSA configurada, nada é chamado e o fluxo segue intacto.

---

## BAIXO / melhorias

- **B-01** · `_validar_png` chama `imagem.verify()` e depois lê `.size`/`.format`
  da mesma instância. A documentação do Pillow diz que, após `verify()`, a imagem
  precisa ser reaberta para ser usada. Funciona hoje, mas é frágil a upgrades.
- **B-02** · Comparação de CPF do responsável com `==` simples (não é
  constant-time). Impacto prático baixo — 5 tentativas e o CPF não é segredo
  criptográfico —, mas é um detalhe de higiene.
- **B-03** · `paciente.nome.split()[0]` (em `documentos`, `baixar_contrato_view`,
  `envio_dental`) levanta `IndexError` se o nome for vazio/só espaços. Hoje o nome
  é validado na importação; é uma suposição não declarada.
- **B-04** · `resolver_token` usa `max_age` de 24h enquanto a sessão real vale 30
  min (`expira_em`). Não é bug (a validade real é a do banco), mas os dois números
  não conversam — vale um comentário ou alinhar.
- **B-05** · `sessao_ativa()` altera `contrato.status` como efeito colateral e
  obriga o chamador a um `refresh_from_db` (já documentado em
  `contexto_status_assinatura`). Efeito colateral escondido num getter.

---

## O que está bem resolvido (para não regredir)

- **Claim atômico** da assinatura via `UPDATE ... WHERE status IN (...)` — a
  corrida de duas assinaturas simultâneas está corretamente tratada.
- **Reversão do claim** quando a geração do PDF falha, permitindo nova tentativa.
- O enfileiramento Celery (`.delay`) é envolvido em `try/except` para **nunca**
  derrubar a confirmação já dada ao paciente — decisão acertada e bem comentada.
- Validação da imagem de assinatura (formato, tamanho mínimo e máximo).
- Envio ao Dental Office bloqueado enquanto o contrato não está assinado, com
  guarda no POST além da UI.
- Validação pública por hash, sem depender de terceiros.

---

## Prioridade sugerida

| # | Achado | Esforço | Risco se adiar |
|---|---|---|---|
| 1 | **C-01** PDF sem verificação de identidade | Baixo (1 `if`) | Exposição de dados pessoais (LGPD) |
| 2 | **A-01** Open redirect (10 pontos) | Baixo (1 helper) | Phishing com domínio legítimo |
| 3 | **CT-03** Re-carimbo invalida cópia entregue | Baixo (1 guarda) | Documento genuíno declarado falso |
| 4 | **CT-02** Falha silenciosa ao embutir | Baixo/Médio | Selo verde mentindo, sem recuperação |
| 5 | **CT-01** Cópia do Dental sai sem carimbo | Médio (chain) | Prova de data/hora ausente no arquivo oficial |
| 6 | **A-02** IP forjável no PDF assinado | Médio | Evidência jurídica frágil |
| 7 | **M-02** Perda do PDF assinado | Baixo | Perda de documento assinado |
| 8 | **M-01** `CACHES` compartilhado | Baixo | Rate-limit fraco |
| 9 | **M-04** Escopo de autorização | — | Decisão de negócio |

Posso implementar as correções — sugiro começar por C-01 e A-01, que são pequenas,
de baixo risco e cobrem os dois impactos mais sérios.
