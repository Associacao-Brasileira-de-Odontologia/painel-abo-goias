# Sistemas internos ABO Goiás

Repositório para desenvolvimento dos sistemas internos da Associação Brasileira de Odontologia de Goiás.

O projeto Django principal usa o pacote `abo_goias` e funciona como portal para múltiplas aplicações internas. Atualmente ele reúne:

- **Gestão de CME**: controle de movimentações, materiais, kits e abrigos.
- **Identificador de Bancadas**: geração de arquivos PPTX com identificadores por turma.
- **Gestão de Laboratório**: sincronização de pacientes e alunos com o Dental Office e controle de pedidos de material a laboratórios externos.
- **Gestão de Contratos**: geração, confirmação de dados, assinatura remota e envio automático de termos de consentimento — ver [seção dedicada](#gestão-de-contratos) mais abaixo.

## Status atual

O projeto está em fase de implementação e integração. As principais bases funcionais já existem, mas ainda há pontos técnicos que devem ser revisados antes de considerar o sistema pronto para produção.

Implementado até o momento:

- Portal inicial da ABO Goiás com acesso aos sistemas disponíveis.
- Aplicação Gestão de CME com listagens de movimentações, alunos por turma, materiais, kits e abrigos.
- Paginação de listagens com 10 registros por página.
- Busca e filtros nas telas principais.
- Autenticação com login, logout e reset de senha.
- Restrição de visualização de movimentações por coordenador.
- Migração de dados legados a partir de planilhas/CSVs.
- Integração com a API do Eduq para turmas e alunos.
- Registro de localização dos alunos a partir dos campos reais `Descricao` e `UF` retornados pelo Eduq.
- Aplicação Identificador de Bancadas com seleção de turma, seleção de modelo, geração de PPTX e download do arquivo.
- Substituição de placeholders no PPTX para preencher nome e local dos alunos.
- Aplicação Gestão de Laboratório com sincronização de pacientes/alunos do Dental Office e controle de pedidos de material.
- Aplicação Gestão de Contratos completa: seleção/confirmação de dados do paciente, geração de termos, assinatura remota via QR Code ou terminal dedicado (tablet), verificação de identidade (paciente ou responsável legal), confirmação presencial do colaborador, carimbo de tempo (RFC 3161), política de privacidade e envio assíncrono ao Dental Office e por WhatsApp — detalhes na [seção dedicada](#gestão-de-contratos).
- Refatoração de nomenclatura:
  - `abo_goias`: projeto/plataforma principal.
  - `gestao_cme`: aplicação de Gestão de CME.
  - `identificadores`: aplicação de Identificador de Bancadas.
  - `gestao_lab`: aplicação de Gestão de Laboratório.
  - `gestao_contratos`: aplicação de Gestão de Contratos.

Pontos de atenção:

- O app `gestao_cme` ainda usa `label = "core"` em `gestao_cme/apps.py` para manter compatibilidade com migrations, fixtures, tabelas existentes e URLs do admin.
- Por causa desse label legado, fixtures e migrations ainda referenciam modelos como `core.material`, `core.aluno`, etc.
- URLs do admin também continuam no formato `/admin/core/...`.
- O arquivo `.env.example` deve servir apenas como modelo. Não versionar credenciais reais.
- Existe uma migration que cria um usuário de teste (`coordenador.teste`). Antes de produção, recomenda-se remover essa criação automática ou substituir por um comando/fixture exclusivo de desenvolvimento.
- A geração de identificadores ainda faz tentativa de atualização de localização pelo Eduq durante o request. Para produção, o ideal é separar sincronização e geração, ou mover a sincronização para uma rotina assíncrona.
- **Pendência operacional (Gestão de Contratos)**: o envio assíncrono ao Dental Office e por WhatsApp depende de um worker Celery + Redis rodando em produção. Sem esses dois serviços configurados no Railway, o envio automático não funciona — mas a aplicação não trava por causa disso (ver [Processamento assíncrono](#processamento-assíncrono-celery--redis)).
- **Pendência operacional (WhatsApp)**: o envio automático via Meta Cloud API exige verificação de conta Business e um template de mensagem aprovado. Sem isso configurado, o envio automático fica desativado e o fluxo manual (link `wa.me`) continua funcionando normalmente.
- **Pendência operacional (armazenamento)**: o filesystem do container no Railway é efêmero — sem um Volume persistente configurado, os PDFs/DOCX gerados são perdidos a cada deploy.
- **Pendências de validade jurídica (Gestão de Contratos)**: ver [Pendências (validade jurídica)](#pendências-validade-jurídica) na seção dedicada — prazo de retenção da auditoria ainda não definido, contato do encarregado de dados pendente de preenchimento, TSA padrão não credenciada pela ICP-Brasil.
- **Controle de acesso**: o comando `python abo-goias\manage.py criar_grupos_padrao` cria os grupos `recepcao`, `coordenacao` e `gestao` (idempotente), mas nenhuma view ainda os utiliza — hoje qualquer usuário autenticado tem acesso igual a todo o sistema (`@login_required` é o único portão). O decorator `gestao_cme.permissoes.requer_grupo` está pronto para uso futuro quando as regras de quem pode fazer o quê forem definidas.
- Credenciais do WhatsApp (Meta Cloud API) e do carimbo de tempo (TSA) agora são lidas centralmente em `abo_goias/settings.py` (mesmo padrão já usado para Dental Office e e-mail), em vez de cada serviço ler `os.environ` diretamente. Os nomes das variáveis de ambiente não mudaram.

## Estrutura do projeto

```text
abo-goias/
├── abo_goias/          # Configurações Django do projeto principal + bootstrap do Celery
├── gestao_cme/         # Aplicação Gestão de CME
├── identificadores/    # Aplicação Identificador de Bancadas
├── gestao_lab/          # Aplicação Gestão de Laboratório (sincronização Dental Office)
├── gestao_contratos/    # Aplicação Gestão de Contratos (geração, assinatura, envio)
├── manage.py
└── db.sqlite3          # Banco local de desenvolvimento
```

## Como executar em desenvolvimento

Instale as dependências:

```powershell
pip install -r requirements.txt
```

Execute as migrations:

```powershell
python abo-goias\manage.py migrate
```

Inicie o servidor local:

```powershell
python abo-goias\manage.py runserver
```

Rotas principais:

- Portal: `http://127.0.0.1:8000/`
- Gestão de CME: `http://127.0.0.1:8000/gestao-cme/`
- Identificador de Bancadas: `http://127.0.0.1:8000/identificadores/`
- Gestão de Laboratório: `http://127.0.0.1:8000/laboratorio/`
- Gestão de Contratos: `http://127.0.0.1:8000/contratos/`
- Admin: `http://127.0.0.1:8000/admin/`

Para rodar o fluxo completo de Gestão de Contratos localmente (geração, assinatura remota, envio automático) sem precisar de um Redis local, veja [Processamento assíncrono](#processamento-assíncrono-celery--redis).

## Validação recomendada

Antes de abrir merge ou publicar uma versão, execute:

```powershell
python abo-goias\manage.py check
python abo-goias\manage.py test
```

Para medir a cobertura de testes (referência: `gestao_contratos` está em 100% na lógica de negócio — models, services, tasks e views; o comando de diagnóstico `testar_envio_dental` fica de fora de propósito, como os demais management commands do projeto):

```powershell
pip install coverage
python -m coverage run --source=. --omit="*/migrations/*,manage.py,*/settings.py,*/wsgi.py,*/asgi.py,*/celery.py,*/__init__.py" abo-goias\manage.py test
python -m coverage report -m
```

Para produção, execute também:

```powershell
python abo-goias\manage.py check --deploy
python abo-goias\manage.py collectstatic
```

## Sincronizacao Eduq

A integracao com a API do Eduq usa variaveis de ambiente:

- `EDUQ_DOMINIO`: dominio da instituicao no Eduq.
- `EDUQ_USUARIO`: usuario usado na autenticacao da API.
- `EDUQ_SENHA`: senha usada na autenticacao da API.
- `EDUQ_AUTH_URL`: endpoint de login. Padrao: API oficial do Eduq.
- `EDUQ_DATA_URL`: endpoint de consulta personalizada. Padrao: API oficial do Eduq.
- `EDUQ_CONSULTA_TURMAS_ID`: ID da consulta personalizada de turmas. Padrao: `4`.
- `EDUQ_CONSULTA_DETALHES_TURMA_ID`: ID da consulta personalizada de detalhes da turma/alunos. Padrao: `5`.
- `EDUQ_VERIFY_TLS`: ativa validacao TLS quando definido como `true`, `1`, `yes`, `sim` ou `on`.
- `EDUQ_USE_PROXY`: usa os proxies do ambiente quando definido como `true`, `1`, `yes`, `sim` ou `on`. Por padrao fica desativado para evitar falhas com proxies locais invalidos.

Campos reais observados na API:

- Turmas: `Identificador da Turma`, `Sigla`, `Descrição`, `TurmaId`, `Matrículas Ativas`, `Data de Início`, `Data de Finalização`.
- Alunos: `Id`, `Identificador`, `Nome`, `CPF`, `CelularSMS`, `Email`, `Descricao`, `UF`.

Para consultar a API e gravar turmas/alunos no banco local:

```powershell
python abo-goias\manage.py sincronizar_eduq --somente-turmas
```

Para simular a sincronizacao sem salvar alteracoes:

```powershell
python abo-goias\manage.py sincronizar_eduq --somente-turmas --dry-run
```

Para sincronizar alunos de uma turma especifica:

```powershell
python abo-goias\manage.py sincronizar_eduq --somente-alunos --turma-codigo 50057
```

Para sincronizar alunos de todas as turmas ja cadastradas:

```powershell
python abo-goias\manage.py sincronizar_eduq --somente-alunos
```

Nos testes reais, chamadas sequenciais para turmas diferentes funcionaram sem intervalo. A API so retornou limite minimo quando o mesmo payload foi repetido imediatamente com o mesmo token.

## Migracao dos dados legados

Os dados operacionais que estavam controlados em planilhas devem ser migrados uma vez para o banco Django. As planilhas sao tratadas apenas como fonte do sistema legado; depois da migracao, a aplicacao passa a trabalhar com os modelos do banco.

Arquivos de origem esperados:

- `Abrigos.csv`
- `Kits.csv`
- `Materiais para empréstimo.csv`
- `Relatório de movimentação.csv`
- `Itens não retirados.csv`

Para simular a migracao sem salvar alteracoes:

```powershell
python abo-goias\manage.py migrar_dados_legado --dry-run
```

Para gravar os dados legados no banco local:

```powershell
python abo-goias\manage.py migrar_dados_legado
```

Para usar outra pasta:

```powershell
python abo-goias\manage.py migrar_dados_legado --diretorio "C:\caminho\para\csvs"
```

Essa migracao alimenta `Abrigo`, `Kit`, `Material` e `Movimentacao` com origem `LEGADO`. O campo `Pacote` das movimentacoes e preservado como codigo bruto porque a exportacao atual usa codigos numericos que nao correspondem diretamente aos codigos dos materiais.

## Dados de exemplo

A fixture `dados_exemplo` mantem apenas dados operacionais de exemplo:

- materiais
- kits
- armarios
- estoques

Ela nao cria `Turma`, `Aluno`, `Emprestimo` ou `ItemEmprestimo`, pois turmas e alunos devem vir do Eduq e emprestimos dependem desses registros reais.

Para carregar os dados operacionais de exemplo:

```powershell
python abo-goias\manage.py loaddata dados_exemplo
```

## Gestão de Laboratório

Aplicação `gestao_lab` — sincroniza pacientes e alunos do Dental Office e controla o fluxo de pedidos de material para laboratórios externos (moldagem → pedido → entrega → faturamento).

Modelos principais: `Paciente`, `AlunoLab`, `Laboratorio`, `Equipe`, `Moldagem`, `PedidoMaterial`, `RegistroSync` (auditoria de cada sincronização).

A integração com o Dental Office (`gestao_lab/integrations/dental.py`) é a base compartilhada por `gestao_contratos` — mesmo cliente HTTP, mesmas credenciais (`DENTAL_*`, ver [Sincronização com o Dental Office](#sincronização-com-o-dental-office) abaixo).

Sincronização manual:

```powershell
python abo-goias\manage.py sincronizar_dental
```

Um endpoint autenticado por token (`/laboratorio/sincronizar-agendado/`) permite acionar a sincronização via cron externo (ex.: Railway Cron) — token configurado em `DENTAL_SYNC_TOKEN`.

## Gestão de Contratos

Aplicação `gestao_contratos` — gera termos de consentimento a partir dos dados do paciente (sincronizados do Dental Office), permite assinatura remota do paciente (celular próprio via QR Code, ou tablet dedicado da clínica) e envia o documento assinado automaticamente ao Dental Office e por WhatsApp. Inclui um conjunto de reforços voltados especificamente à validade jurídica da assinatura eletrônica — verificação de identidade, confirmação presencial do colaborador, carimbo de tempo de terceiro e política de privacidade — ver [Assinatura remota e validade jurídica](#assinatura-remota-e-validade-jurídica).

### Fluxo completo

```text
Selecionar paciente (lista local + busca no Dental Office)
    ↓
Confirmar dados do paciente (edição manual + convênio, campo local)
    ↓
Gerar contrato (DOCX + PDF, preenchidos automaticamente)
    ↓
Colaborador confirma identidade presencial do paciente e escolhe o destino:
    QR Code (celular do paciente)         Terminal dedicado (tablet, se cadastrado)
         ↓                                          ↓
    Paciente escaneia e assina         Tablet detecta a sessão sozinho (polling)
                                           e abre a assinatura automaticamente
         └───────────────────┬──────────────────────┘
                             ↓
       Verificação de identidade (data de nascimento do paciente,
          ou CPF do responsável legal se o paciente é menor)
                             ↓
                Assinatura no canvas HTML5
                             ↓
        PDF assinado salvo (nunca sobrescreve o original)
                             ↓ (em paralelo, assíncrono via Celery)
   Envio ao Dental Office     Envio por WhatsApp      Carimbo de tempo (RFC 3161)
      (com retry)           (Meta Cloud API,         sobre o hash do PDF assinado —
                              se configurada)         embutido de volta no PDF
```

Cada etapa relevante fica registrada em `EventoContrato`, alimentando tanto a auditoria quanto o painel de status em tempo real (polling HTMX) na tela de pós-geração — sem necessidade de recarregar a página para saber se o paciente já assinou ou se o envio automático já foi concluído.

### Modelos e ciclo de vida

- **`ContratoGerado`**: um registro por documento gerado. Campos-chave:
  - `status`: `gerado` → `aguardando_assinatura` → `assinado` (ou `cancelado`).
  - `versao`: sequencial por paciente + tipo de contrato.
  - `hash_sha256`: hash do PDF vigente — recalculado após a assinatura. É este hash que é submetido ao carimbo de tempo (ver abaixo) e **não** é recalculado depois de o token ser embutido no PDF.
  - `arquivo` (DOCX), `arquivo_pdf` (PDF original), `arquivo_pdf_assinado` (PDF definitivo — assinatura mesclada e, assim que disponível, o carimbo de tempo embutido como anexo — nunca sobrescreve `arquivo_pdf`).
  - `status_envio_dental` / `status_envio` (e-mail/WhatsApp manual): canais de envio, independentes do `status` de ciclo de vida do contrato.
  - `carimbo_tempo`, `carimbo_tempo_em`, `carimbo_tempo_tsa`, `status_carimbo_tempo`: ver [Carimbo de tempo](#carimbo-de-tempo-rfc-3161).
- **`SessaoAssinatura`**: sessão temporária de assinatura remota. Token da URL pública assinado criptograficamente (`django.core.signing`, HMAC com a `SECRET_KEY` do Django) — nenhum segredo fica armazenado em banco. Expira em 30 minutos (configurável), permite apenas uma assinatura (transição de status atômica no banco) e é expirada tanto sob demanda quanto por limpeza periódica via Celery Beat.
  - `identidade_confirmada_em` / `identidade_confirmada_como`: quando e como a identidade de quem assina foi verificada (`paciente` ou `responsavel_legal`) — obrigatório antes de liberar o canvas.
  - `tentativas_identidade`: contador que bloqueia a sessão (cancela e exige nova sessão) após 5 tentativas erradas.
  - `identidade_presencial_confirmada_em`: quando o colaborador (`criado_por`) atestou ter verificado presencialmente a identidade do paciente, antes de criar a sessão.
  - `terminal`: quando não nulo, indica que a sessão foi enviada a um `TerminalAssinatura` em vez de gerar um QR Code.
- **`TerminalAssinatura`**: representa um dispositivo dedicado (tablet). Ver [Terminal de assinatura dedicado](#terminal-de-assinatura-dedicado-tablet).
- **`EventoContrato`**: trilha de eventos completa (sessão criada/aberta, identidade confirmada/bloqueada, identidade presencial confirmada, assinatura concluída, envio ao Dental/WhatsApp/carimbo de tempo iniciado-concluído-erro etc.) — auditoria com timestamp e payload livre em JSON.

Os quatro modelos de contrato disponíveis (`Modelo 1`–`Modelo 4`) são gerados **inteiramente em código** (via `python-docx` e `reportlab`, ver `services/documentos.py`) — não dependem de nenhum arquivo de template externo, nem de LibreOffice/Microsoft Word para a conversão a PDF.

### Assinatura remota e validade jurídica

O paciente nunca assina no computador do colaborador. Na tela de pós-geração, antes de criar a sessão de assinatura:

1. O colaborador **confirma, por checkbox obrigatório, que verificou presencialmente a identidade do paciente** — sem essa confirmação, nenhuma sessão é criada (`iniciar_assinatura_view`). É o controle de identidade mais forte quando o dispositivo de assinatura é compartilhado (tablet), e fica registrado em `EventoContrato` com o nome do colaborador.
2. O colaborador escolhe entre gerar um QR Code (celular do próprio paciente) ou enviar a sessão para um terminal dedicado, se houver algum cadastrado (ver seção abaixo).

Do lado do paciente:

3. Antes de exibir o contrato e liberar o canvas, a página pública (`/contratos/assinar/<token>/`) exige confirmar a **própria data de nascimento** — ou, se o paciente é menor de idade, quem assina é o **responsável legal**, que confirma o **CPF cadastrado** em vez disso. Até 5 tentativas erradas; depois a sessão é bloqueada e é preciso gerar uma nova.
4. Ao confirmar a assinatura no canvas HTML5 (aceita touch e mouse), o servidor valida a imagem (formato PNG, dimensões mínimas, tamanho máximo), faz um *claim* atômico da sessão (evita dupla assinatura em corrida) e mescla a assinatura sobre o PDF original, numa posição fixa reservada para isso.
5. O PDF resultante é salvo em `arquivo_pdf_assinado`, com um carimbo de auditoria no rodapé (data/hora, IP e, quando aplicável, o nome do responsável legal) — e o hash SHA-256 é recalculado.
6. Em paralelo, assíncrono, um **carimbo de tempo de terceiro (RFC 3161)** é solicitado sobre esse hash e embutido de volta no PDF (ver [Carimbo de tempo](#carimbo-de-tempo-rfc-3161)).

Uma [política de privacidade](/contratos/politica-privacidade/) (`/contratos/politica-privacidade/`) é linkada na própria tela de assinatura, detalhando quais dados são coletados, a finalidade, com quem são compartilhados (Dental Office, Meta WhatsApp, TSA) e os direitos do titular sob a LGPD.

A tela de pós-geração do staff atualiza sozinha (polling HTMX a cada 3s) enquanto aguarda a assinatura, parando automaticamente assim que o status muda — sem JavaScript adicional além do HTMX (vendorizado localmente, sem CDN).

### Terminal de assinatura dedicado (tablet)

Alternativa ao QR Code para clínicas que preferem um tablet fixo na recepção em vez de depender do celular do paciente. O tablet fica com o navegador aberto indefinidamente numa URL própria e privada (`/contratos/terminal/<token>/`), sem login. Quando o colaborador envia uma sessão para aquele terminal, a tela do tablet detecta sozinha (polling HTMX a cada 3s + cabeçalho `HX-Redirect`) e navega automaticamente para a assinatura — reaproveitando 100% do mesmo fluxo público de assinatura, sem nenhum código duplicado.

Para configurar um terminal:

1. Acesse `/admin/gestao_contratos/terminalassinatura/` (usuário staff/superuser).
2. Crie um novo terminal com um nome (ex.: "Tablet Recepção") — o token de acesso é gerado automaticamente.
3. Copie o link exibido no admin (coluna "Link do terminal") e deixe-o aberto no navegador do tablet — idealmente em modo quiosque.
4. Na tela de pós-geração, ao iniciar a assinatura, escolha o terminal no lugar de "QR Code" no seletor exibido (só aparece quando há ao menos um terminal ativo cadastrado).

Depois de assinar, a tela de conclusão volta sozinha (em ~8s, via `<meta http-equiv="refresh">`) para a tela de espera do terminal, pronta para o próximo paciente.

O token do terminal deve ser tratado como sensível (não divulgado publicamente) — é longo e aleatório (`secrets.token_urlsafe`), mas quem tiver acesso a ele veria o mesmo fluxo de assinatura que o tablet mostra.

### Carimbo de tempo (RFC 3161)

Reforço de validade jurídica: logo após a assinatura, o sistema solicita a uma Autoridade de Carimbo do Tempo (TSA) um token RFC 3161 sobre o hash do PDF assinado — uma evidência independente do relógio do servidor de que o documento já existia naquele momento. O token é embutido de volta no PDF como arquivo anexado (o PDF passa a ser autocontido, sem depender de um `.tsr` avulso) e também fica salvo separadamente em `ContratoGerado.carimbo_tempo`.

**Desativado por padrão** — sem `CARIMBO_TEMPO_TSA_URL` configurada, nenhuma chamada externa é feita e o restante do fluxo de assinatura permanece inalterado.

Variáveis de ambiente:

- `CARIMBO_TEMPO_TSA_URL`: URL da TSA. Para começar sem custo: `https://freetsa.org/tsr` (pública, compatível com RFC 3161, mas **não** credenciada pela ICP-Brasil).
- `CARIMBO_TEMPO_TSA_USERNAME`, `CARIMBO_TEMPO_TSA_PASSWORD`: opcionais — para TSAs pagas que exigem autenticação HTTP básica (ex.: uma ACT credenciada pela ICP-Brasil).
- `CARIMBO_TEMPO_TIMEOUT`: padrão 30s.

Se a TSA falhar, o staff pode tentar novamente manualmente na tela de pós-geração ("Tentar novamente"); isso nunca bloqueia nem desfaz a assinatura já confirmada. O token bruto pode ser baixado separadamente (`.tsr`) pela mesma tela.

### Processamento assíncrono (Celery + Redis)

Após a assinatura, três tarefas são agendadas em segundo plano, de forma independente entre si — uma falha numa não afeta as outras, e nenhuma falha de agendamento (ex.: Redis indisponível) pode quebrar a confirmação de assinatura do paciente:

- `enviar_dental_task`: reenvia ao Dental Office, com retry automático (backoff exponencial, até 5 tentativas).
- `enviar_whatsapp_task`: envia o PDF por WhatsApp via Meta Cloud API — **só é agendada se a Meta estiver configurada** (ver variáveis abaixo) e o paciente tiver celular cadastrado.
- `solicitar_carimbo_tempo_task`: solicita o carimbo de tempo (RFC 3161) — **só é agendada se `CARIMBO_TEMPO_TSA_URL` estiver configurada**.
- `expirar_sessoes_vencidas_task` (Celery Beat, a cada 5 min): limpeza em lote de sessões de assinatura abandonadas.

Como essas tarefas rodam em paralelo e o carimbo de tempo depende de uma chamada de rede externa à TSA, **o envio automático ao Dental Office/WhatsApp normalmente é concluído antes do carimbo terminar** — ou seja, a cópia enviada automaticamente por esses dois canais costuma não ter o carimbo embutido ainda; só a versão baixada depois pela recepção ("Baixar contrato assinado") já estará completa. Isso não compromete a validade (hash e token continuam corretos e acessíveis), é só uma questão de ordenação.

**Desenvolvimento local sem Redis**: defina `CELERY_TASK_ALWAYS_EAGER=true` no `.env` — as tarefas rodam de forma síncrona, no mesmo processo do `runserver`, sem precisar de Redis instalado. Os testes automatizados já fazem isso automaticamente.

**Produção (Railway)**: além do serviço web, são necessários:

1. O plugin **Redis** do Railway adicionado ao projeto (injeta `REDIS_URL` automaticamente).
2. Um serviço **worker**, apontando para este mesmo repositório, com *Start Command*:
   ```
   celery -A abo_goias worker --loglevel=info --concurrency=2
   ```
3. Um serviço **beat** (agendador), com *Start Command*:
   ```
   celery -A abo_goias beat --loglevel=info
   ```

Ambos precisam das mesmas variáveis de ambiente do serviço web (banco de dados, Dental Office, Redis) — use "Connect" no Railway para compartilhar variáveis entre serviços do mesmo projeto.

### Sincronização com o Dental Office

O envio de documentos usa `multipart/form-data` (não JSON+Base64, apesar do que a documentação oficial da API sugere — foi validado empiricamente que o endpoint `POST /customers/{id}/docs` só aceita multipart). Sempre envia a versão mais completa disponível do PDF: assinado > original salvo > gerado na hora.

Variáveis de ambiente:

- `DENTAL_CLIENT_ID`, `DENTAL_SECRET`: credenciais da API.
- `DENTAL_CLINIC_ID`: ID da clínica usado na busca de pacientes.
- `DENTAL_AUTH_URL`, `DENTAL_BASE_URL`: endpoints da API (padrão aponta para o ambiente demo).
- `DENTAL_VERIFY_TLS`, `DENTAL_TIMEOUT`, `DENTAL_USE_PROXY`: opções avançadas de conexão.
- `DENTAL_SYNC_TOKEN`: token do endpoint de sincronização agendada de `gestao_lab`.

Para diagnosticar problemas de envio manualmente (autenticação, leitura do arquivo, chamada à API, análise da resposta):

```powershell
python abo-goias\manage.py testar_envio_dental
python abo-goias\manage.py testar_envio_dental --contrato 5
python abo-goias\manage.py testar_envio_dental --apenas-auth
```

### Envio automático por WhatsApp (Meta Cloud API)

Opcional e desativado por padrão — sem as variáveis abaixo configuradas, nada muda: o botão manual "Encaminhar pelo WhatsApp" (link `wa.me`, com opção de compartilhamento direto de arquivo via Web Share API em navegadores compatíveis) continua sendo o único caminho.

Pré-requisitos (fora deste repositório, no Meta Business Suite):

1. Conta WhatsApp Business verificada, com número dedicado.
2. Um access token (temporário para teste; permanente via *System User* para produção).
3. Um **template de mensagem aprovado pela Meta**, com cabeçalho do tipo Documento e uma variável no corpo (nome do paciente) — obrigatório pela política do WhatsApp Business para conversas iniciadas pela clínica fora de uma janela de atendimento de 24h, que é o caso normal aqui.

Variáveis de ambiente:

- `WHATSAPP_META_TOKEN`, `WHATSAPP_META_PHONE_NUMBER_ID`: credenciais obrigatórias — sem elas, o envio automático fica desativado.
- `WHATSAPP_META_API_VERSION`: padrão `v21.0`.
- `WHATSAPP_META_TEMPLATE_NAME`, `WHATSAPP_META_TEMPLATE_LANG`: nome e idioma do template aprovado. Sem template configurado, o envio tenta uma mensagem de sessão livre — só funciona se o paciente tiver escrito para o número da clínica nas últimas 24h, portanto normalmente insuficiente para o envio automático pós-assinatura.

### Armazenamento de arquivos

Contratos (DOCX/PDF) e imagens de assinatura são salvos via `DJANGO_MEDIA_ROOT`. Em produção, o filesystem do container Railway é **efêmero** — configure um Volume persistente e aponte `DJANGO_MEDIA_ROOT` para ele antes de operar com pacientes reais, sob risco de perder os documentos assinados a cada deploy.

### Endpoints principais

| Rota | Descrição |
|---|---|
| `/contratos/` | Lista de pacientes (local + busca no Dental Office) |
| `/contratos/paciente/<id>/confirmar-dados/` | Confirmação/edição dos dados antes de gerar o contrato |
| `/contratos/paciente/<id>/gerar/` | Formulário e geração do contrato |
| `/contratos/contrato/<id>/pos-geracao/` | Download, e-mail, WhatsApp, assinatura, envio ao Dental, carimbo de tempo |
| `/contratos/contrato/<id>/iniciar-assinatura/` | Confirma identidade presencial e cria a sessão (QR Code ou terminal) |
| `/contratos/assinar/<token>/` | Página pública de assinatura — verificação de identidade + canvas (sem login) |
| `/contratos/politica-privacidade/` | Política de privacidade pública |
| `/contratos/terminal/<token>/` | Tela de espera do terminal dedicado (tablet), sem login |
| `/contratos/contrato/<id>/status-assinatura/` | Fragmento de status usado pelo polling HTMX |
| `/contratos/contrato/<id>/carimbo-tempo/solicitar/` | Solicita (ou tenta novamente) o carimbo de tempo |
| `/contratos/contrato/<id>/carimbo-tempo/baixar/` | Baixa o token de carimbo de tempo (.tsr) avulso |

Veja `gestao_contratos/urls.py` para a lista completa.

### Pendências (validade jurídica)

- **Prazo de retenção dos dados de auditoria** (IP, user-agent, imagem da assinatura, carimbo de tempo) ainda não está formalmente definido — sugestão levantada: alinhar ao prazo prescricional da responsabilidade civil (art. 206 do Código Civil).
- **Contato do encarregado de dados (DPO)** na política de privacidade está com um placeholder (`[e-mail ou telefone do encarregado de dados — a preencher]`) — precisa ser preenchido antes de publicar em produção.
- **TSA pública, não credenciada pela ICP-Brasil**, usada por padrão (`https://freetsa.org/tsr`) — considerar migrar para uma Autoridade de Carimbo do Tempo credenciada (ex.: Certisign, Soluti, Serasa Experian) se for necessário maior peso jurídico formal no Brasil; basta trocar `CARIMBO_TEMPO_TSA_URL` (e usuário/senha, se exigido pelo provedor).
- **Envio automático ao Dental Office/WhatsApp sem o carimbo de tempo embutido**: por rodarem em paralelo, essas cópias costumam sair antes de o carimbo terminar (ver [Processamento assíncrono](#processamento-assíncrono-celery--redis)) — não compromete a validade, mas é uma limitação de ordenação assumida, não corrigida.
- **Tutela/curatela fora do padrão simples**: o checklist já exige nome/CPF do responsável legal para pacientes menores de idade antes de gerar o contrato, mas não cobre casos de curatela de maiores incapazes — avaliação jurídica adicional recomendada se esse cenário for relevante para a associação.

## Configuracao por ambiente

O projeto carrega variaveis de ambiente a partir do sistema operacional e, quando existir, dos arquivos `.env` na raiz do repositorio ou dentro da pasta Django `abo-goias/`. Use `.env.example` como referencia e nunca versionar segredos reais.

Variaveis principais:

- `DJANGO_DEBUG`: use `true` em desenvolvimento e `false` em producao.
- `DJANGO_SESSION_COOKIE_AGE`: duracao da sessao em segundos. Padrao: 8h (`28800`).
- `DJANGO_SESSION_EXPIRE_AT_BROWSER_CLOSE`: expira a sessao ao fechar o navegador. Padrao: `true`.
- `DJANGO_SECRET_KEY`: chave secreta do Django. Obrigatoria em producao.
- `DJANGO_ALLOWED_HOSTS`: dominios/IPs permitidos, separados por virgula. Obrigatorio em producao.
- `DJANGO_CSRF_TRUSTED_ORIGINS`: origens confiaveis para CSRF, separadas por virgula, incluindo protocolo. Exemplo: `https://cme.exemplo.com`.
- `DATABASE_URL`: conexao do banco. Exemplo PostgreSQL: `postgresql://usuario:senha@localhost:5432/abo_goias`.
- `DJANGO_STATIC_ROOT`: pasta onde `collectstatic` grava os arquivos estaticos.
- `DJANGO_SECURE_SSL_REDIRECT`: redireciona HTTP para HTTPS. Recomendado `true` em producao.
- `DJANGO_SESSION_COOKIE_SECURE`: restringe cookie de sessao a HTTPS. Recomendado `true` em producao.
- `DJANGO_CSRF_COOKIE_SECURE`: restringe cookie CSRF a HTTPS. Recomendado `true` em producao.
- `DJANGO_SECURE_HSTS_SECONDS`: tempo de HSTS. Recomendado apenas quando HTTPS estiver validado.
- `DJANGO_SECURE_PROXY_SSL_HEADER`: use `true` quando a aplicacao estiver atras de proxy reverso que envia `X-Forwarded-Proto`.
- `DJANGO_EMAIL_BACKEND`, `DJANGO_EMAIL_HOST`, `DJANGO_EMAIL_PORT`, `DJANGO_EMAIL_HOST_USER`, `DJANGO_EMAIL_HOST_PASSWORD`, `DJANGO_EMAIL_USE_TLS`, `DJANGO_EMAIL_USE_SSL`: configuracoes de e-mail.

Exemplo minimo para producao:

```powershell
$env:DJANGO_DEBUG="false"
$env:DJANGO_SECRET_KEY="uma-chave-longa-e-aleatoria"
$env:DJANGO_ALLOWED_HOSTS="sistemas.seudominio.com.br"
$env:DJANGO_CSRF_TRUSTED_ORIGINS="https://sistemas.seudominio.com.br"
$env:DATABASE_URL="postgresql://usuario:senha@localhost:5432/abo_goias"
```

Antes de publicar, execute:

```powershell
python abo-goias\manage.py check --deploy
python abo-goias\manage.py collectstatic
```

## Deploy no Railway

O repositorio inclui `railway.toml`, `requirements.txt` e uma rota publica de saude em `/healthz/`.

O Railway usa o `railway.toml` para:

- instalar dependencias Python a partir do `requirements.txt`;
- executar `python abo-goias/manage.py collectstatic --noinput` no build;
- executar `python abo-goias/manage.py migrate --noinput` antes de iniciar uma nova versao;
- iniciar a aplicacao com Gunicorn usando a porta definida por `$PORT`;
- verificar saude da aplicacao em `/healthz/`.

Passos recomendados no Railway:

1. Criar um novo projeto a partir do repositorio GitHub.
2. Adicionar um servico PostgreSQL ao projeto.
3. No servico da aplicacao Django, configurar as variaveis:

```text
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=<gere-uma-chave-longa-e-segura>
DJANGO_SECURE_PROXY_SSL_HEADER=true
DJANGO_SECURE_HSTS_PRELOAD=true
EDUQ_DOMINIO=<dominio-da-instituicao>
EDUQ_USUARIO=<usuario-da-api>
EDUQ_SENHA=<senha-da-api>
EDUQ_VERIFY_TLS=true
```

O Railway fornece `RAILWAY_PUBLIC_DOMAIN` automaticamente quando um dominio publico e gerado. O sistema adiciona esse dominio em `ALLOWED_HOSTS` e em `CSRF_TRUSTED_ORIGINS`. Se usar dominio proprio, configure tambem:

```text
DJANGO_ALLOWED_HOSTS=sistemas.seudominio.com.br
DJANGO_CSRF_TRUSTED_ORIGINS=https://sistemas.seudominio.com.br
```

Para PostgreSQL, o sistema usa `DATABASE_URL` quando ela existir. O Railway tambem disponibiliza `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGHOST` e `PGPORT`, que sao aceitos como alternativa.

## Recomendações antes de produção

- Remover credenciais reais de `.env.example`, caso existam, e rotacionar senhas já compartilhadas.
- Criar usuários por fluxo administrativo, comando de setup ou painel admin, não por migration.
- Decidir se o label legado `core` será mantido permanentemente ou se haverá uma migration planejada para renomear app label/tabelas/admin.
- Separar sincronização Eduq da geração de PPTX para evitar lentidão ou falha externa durante o download.
- Adicionar logs estruturados para erros de integração Eduq e processamento de PPTX.
- Rodar a suíte de testes completa após as refatorações de nomenclatura.
- Configurar um Volume persistente no Railway e `DJANGO_MEDIA_ROOT` antes de gerar contratos com pacientes reais — sem isso, os documentos assinados são perdidos a cada deploy.
- Adicionar os serviços `worker` e `beat` do Celery no Railway (mais o plugin Redis) para que o envio automático ao Dental Office e por WhatsApp de fato funcione em produção — sem eles, os contratos continuam sendo assinados normalmente, mas o envio automático fica só registrado como pendente/erro, exigindo reenvio manual pelo staff.
- Verificar a conta WhatsApp Business e aprovar o template de mensagem no Meta Business Suite antes de configurar `WHATSAPP_META_*` — sem template aprovado, a Meta rejeita a maioria dos envios automáticos.
- Preencher o contato do encarregado de dados na política de privacidade e decidir o prazo de retenção da auditoria antes de assinar contratos com pacientes reais — ver [Pendências (validade jurídica)](#pendências-validade-jurídica).
