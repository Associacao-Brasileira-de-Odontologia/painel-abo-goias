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
- ~~Existe uma migration que cria um usuário de teste (`coordenador.teste`)~~ — **corrigido**: a migration `0003_emprestimo_coordenador_usuario` foi neutralizada (não cria mais nenhuma conta) e a migration `0011_remover_usuario_coordenador_teste` remove essa conta em qualquer banco onde ela já tenha sido criada, assim que `migrate` rodar novamente (inclusive em produção, no próximo deploy). A senha usada (`Coordenador@123`) continua exposta no **histórico do Git** — ver nota abaixo sobre reescrita de histórico.
- A geração de identificadores ainda faz tentativa de atualização de localização pelo Eduq durante o request. Para produção, o ideal é separar sincronização e geração, ou mover a sincronização para uma rotina assíncrona.
- **Pendência operacional (Gestão de Contratos)**: o envio assíncrono ao Dental Office e por WhatsApp depende de um worker Celery + Redis rodando em produção. Sem esses dois serviços configurados no Railway, o envio automático não funciona — mas a aplicação não trava por causa disso (ver [Processamento assíncrono](#processamento-assíncrono-celery--redis)).
- **Pendência operacional (WhatsApp)**: o envio automático via Z-API exige uma instância criada e conectada (QR Code lido) no painel da Z-API. Sem isso configurado, o envio automático fica desativado e o fluxo manual (link `wa.me`) continua funcionando normalmente.
- **Pendência operacional (armazenamento)**: o filesystem do container no Railway é efêmero — sem um Volume persistente configurado, os PDFs/DOCX gerados são perdidos a cada deploy.
- **Pendências de validade jurídica (Gestão de Contratos)**: ver [Pendências (validade jurídica)](#pendências-validade-jurídica) na seção dedicada — prazo de retenção da auditoria ainda não definido, contato do encarregado de dados pendente de preenchimento, TSA padrão não credenciada pela ICP-Brasil.
- **Controle de acesso**: o comando `python abo-goias\manage.py criar_grupos_padrao` cria os grupos `recepcao`, `coordenacao` e `gestao` (idempotente), mas nenhuma view ainda os utiliza — hoje qualquer usuário autenticado tem acesso igual a todo o sistema (`@login_required` é o único portão). O decorator `gestao_cme.permissoes.requer_grupo` está pronto para uso futuro quando as regras de quem pode fazer o quê forem definidas.
- **Solicitação de acesso**: a tela de login tem o link "Solicitar acesso" (`/solicitar-acesso/`, pública), onde alguém sem conta preenche nome, e-mail e usuário desejado. O cadastro **nunca é automático** — cria uma `SolicitacaoCadastro` pendente (app `contas`) que um administrador revisa pelo Django Admin: a ação "Aprovar" cria o `User`, marca a solicitação e envia um **e-mail de boas-vindas** com o link de definição de senha (templates próprios `conta_criada_email.html`/`conta_criada_subject.txt` — o mecanismo do link seguro é o mesmo do reset de senha, mas o texto é de conta criada, não de redefinição); "Rejeitar" marca a decisão **e também avisa por e-mail** quem solicitou, com o motivo informado (se houver) — ver `contas/emails.py`. Essa mediação por aprovação preserva o controle de quem entra num sistema que manipula dados de pacientes.
- **Notificação de nova solicitação por e-mail**: assim que alguém envia o formulário de "Solicitar acesso", os endereços configurados em `DJANGO_ADMINS_EMAIL` recebem um e-mail com os dados do pedido e um link direto para revisá-lo no Django Admin (`contas/emails.py::notificar_admin_nova_solicitacao`). Sem essa variável, a notificação simplesmente não é enviada — a solicitação continua visível normalmente em `/admin/contas/solicitacaocadastro/`, só sem aviso automático. Uma falha no envio (ex.: SMTP fora do ar) é só logada — nunca impede o pedido de ser salvo, já que quem está preenchendo o formulário é público e não autenticado.
- **Confirmação de recebimento ao solicitante**: logo após enviar o formulário de "Solicitar acesso", quem pediu recebe um e-mail confirmando que o pedido foi registrado e será analisado (`contas/emails.py::confirmar_recebimento_solicitacao`) — fecha o ciclo de comunicação: a pessoa é avisada quando pede, quando é aprovada (boas-vindas) ou quando é rejeitada (com motivo). Mesmo padrão fail-safe das demais notificações: falha de envio é só logada, nunca quebra o formulário público.
- **Convite direto pelo admin**: o caminho inverso da solicitação pública — em `/admin/contas/solicitacaocadastro/`, o botão **"Convidar usuário"** abre um formulário (nome, e-mail, usuário, cargo) que cria o `User` e envia o e-mail de boas-vindas com o link de definição de senha **numa única ação**, sem esperar a pessoa solicitar. Internamente reutiliza `SolicitacaoCadastro.aprovar()` — a solicitação nasce já aprovada, com `revisado_por`/`revisado_em` preenchidos e a observação "Convite direto pelo administrador", preservando a mesma trilha de auditoria do fluxo normal. As validações de duplicidade (usuário/e-mail já existentes ou com pedido pendente) são as mesmas do formulário público. Exige permissão de adicionar solicitações (staff sem essa permissão recebe 403).
- Credenciais do WhatsApp (Z-API) e do carimbo de tempo (TSA) são lidas centralmente em `abo_goias/settings.py` (mesmo padrão já usado para Dental Office e e-mail), em vez de cada serviço ler `os.environ` diretamente.
- O envio de WhatsApp é feito por uma camada de mensageria desacoplada de provedor (`mensageria/`, pacote compartilhado na raiz do projeto — não pertence a nenhuma app, para poder ser reusado por outras além de `gestao_contratos`) — `MessagingProvider` é a interface, `ZApiProvider` a implementação atual para a Z-API, e `MessagingService` é a fachada usada pelo resto da aplicação. Trocar de provedor no futuro (ex.: voltar à API oficial, ou usar outro serviço) significa implementar um novo `MessagingProvider`, sem tocar em views, models ou templates — ver [Envio automático por WhatsApp (Z-API)](#envio-automático-por-whatsapp-z-api).
- **`DEBUG` inseguro por padrão**: `DEBUG = _env_bool("DJANGO_DEBUG", True)` em `abo_goias/settings.py:147` — se a variável `DJANGO_DEBUG` não for definida em algum ambiente (erro de configuração, novo serviço no Railway sem a variável copiada, etc.), o Django sobe em modo debug por padrão, inclusive expondo a `SECRET_KEY` insegura de fallback (linha 152). O comportamento correto do lado de `ALLOWED_HOSTS`/`SECRET_KEY` em produção (falha explícita com `ImproperlyConfigured` quando `DEBUG=False`) só se aplica depois que `DJANGO_DEBUG=false` já estiver de fato configurado.
- **Sem `LOGGING` configurado**: `settings.py` não define `LOGGING` — o projeto depende do logging default do Django (sem handlers de arquivo/serviço externo, sem `ADMINS`/`MANAGERS` configurados para receber e-mail de erro 500). Módulos individuais usam `logging.getLogger` pontualmente, mas não há uma política central de log estruturado.
- **Sem cache compartilhado**: não há `CACHES` configurado — o Django usa o cache local em memória por processo (`LocMemCache`), que não é compartilhado entre os workers do Gunicorn. O Redis do projeto hoje só é usado como broker/result-backend do Celery, não como cache de aplicação.
- **E-mail cai para console se `DJANGO_EMAIL_HOST` não for definido, mesmo em produção**: sem essa variável, o backend padrão é `console.EmailBackend` (`settings.py:314-321`) mesmo com `DEBUG=false` — e-mails de reset de senha e aprovação de cadastro (`contas`) seriam apenas logados no stdout do container, nunca entregues, sem nenhum erro visível.
- **`.env.example` desatualizado nas três variáveis centrais**: `abo-goias/.env.example` usa `SECRET_KEY`, `DEBUG` e `ALLOWED_HOSTS` (sem prefixo), mas `settings.py` lê `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` e `DJANGO_ALLOWED_HOSTS`. Quem copiar o `.env.example` literalmente não configura essas três variáveis de fato — ver [Recomendações antes de produção](#recomendações-antes-de-produção).
- **Dois `railway.toml` com comandos divergentes**: existe um na raiz (`railway.toml`, comandos com prefixo `abo-goias/manage.py` e `--chdir abo-goias`) e outro em `abo-goias/railway.toml` (comandos sem esse prefixo, assumindo que o *Root Directory* do serviço já é `abo-goias/`). Qual dos dois é efetivamente usado depende de como o *Root Directory* está configurado no painel do Railway — vale consolidar em um único arquivo para evitar drift entre eles.
- **Sem CI configurado**: não há pipeline (`.github/workflows`, etc.) rodando testes/lint automaticamente a cada push ou PR — `manage.py check`, `manage.py test` e o `pre-commit` (`isort`/`black`/`flake8`) dependem de execução manual.
- **Cobertura de testes desigual entre apps**: `gestao_contratos` tem ~4074 linhas de teste (100% da lógica de negócio, por documentação própria), enquanto `identificadores` tem apenas ~40 linhas — cobertura bem mais fraca no app de geração de PPTX.
- **Senha em texto claro no histórico do Git**: a criação automática da conta `coordenador.teste` já foi neutralizada (ver item acima), mas a senha usada continua em texto claro nos commits antigos do histórico do repositório. Só sai dali com reescrita de histórico (`git filter-repo`/BFG) seguida de force-push e re-clone por todos os colaboradores — uma operação destrutiva e coordenada, fora do escopo desta atualização de código. Até lá, trate essa senha como comprometida: não a reutilize em nenhum ambiente.

## Estrutura do projeto

```text
abo-goias/
├── abo_goias/          # Configurações Django do projeto principal + bootstrap do Celery
├── contas/             # Aplicação de autenticação (login, senha, perfil)
├── gestao_cme/         # Aplicação Gestão de CME
├── identificadores/    # Aplicação Identificador de Bancadas (app independente)
├── gestao_lab/         # Aplicação Gestão de Laboratório (sincronização Dental Office)
├── gestao_contratos/   # Aplicação Gestão de Contratos (geração, assinatura, envio)
├── mensageria/         # Pacote compartilhado de mensageria (WhatsApp/Z-API) — não é uma app Django
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

### Cobrança automática de pedidos atrasados (WhatsApp)

`PedidoMaterial.status` é recalculado a cada `save()` a partir de `previsao_entrega`; quando o prazo vence sem entrega registrada, o pedido vira `ATRASADO`. A tarefa `gestao_lab.tasks.cobrar_pedidos_atrasados_task` (Celery Beat, uma vez por dia às 9h — ver `CELERY_BEAT_SCHEDULE` em `settings.py`) varre esses pedidos e envia **uma mensagem de texto por laboratório** (agregando todos os pedidos atrasados dele, em vez de uma mensagem por pedido) via `mensageria` (Z-API) — mesma camada de mensageria usada pelo envio automático de contratos, ver [Envio automático por WhatsApp (Z-API)](#envio-automático-por-whatsapp-z-api).

- Usa `Laboratorio.whatsapp` como destinatário; laboratórios sem WhatsApp cadastrado são ignorados.
- **Deduplicação**: cada `PedidoMaterial` notificado é marcado com `cobranca_whatsapp_enviada_em`. A próxima execução no mesmo dia ignora pedidos já cobrados hoje — evita notificar o mesmo laboratório repetidamente se a tarefa rodar mais de uma vez. Um pedido cobrado ontem (e ainda atrasado) volta a ser elegível hoje.
- Se o envio para um laboratório falhar (ex.: instância da Z-API desconectada), os pedidos dele **não** são marcados como cobrados — continuam elegíveis na próxima execução, sem afetar a cobrança dos demais laboratórios.
- Sem `ZAPI_*` configurado, a tarefa não faz nada (mesmo padrão do envio automático de contratos).
- Lógica de negócio em `gestao_lab/services/cobranca.py`.

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
      (com retry)              (Z-API,                sobre o hash do PDF assinado —
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

Uma [política de privacidade](/contratos/politica-privacidade/) (`/contratos/politica-privacidade/`) é linkada na própria tela de assinatura, detalhando quais dados são coletados, a finalidade, com quem são compartilhados (Dental Office, Z-API, TSA) e os direitos do titular sob a LGPD.

A tela de pós-geração do staff atualiza sozinha (polling HTMX a cada 3s) enquanto aguarda a assinatura, parando automaticamente assim que o status muda — sem JavaScript adicional além do HTMX (vendorizado localmente, sem CDN).

### Terminal de assinatura dedicado (tablet)

Alternativa ao QR Code para clínicas que preferem um tablet fixo na recepção em vez de depender do celular do paciente. O tablet fica com o navegador aberto indefinidamente numa URL própria e privada (`/contratos/terminal/<token>/`), sem login. Quando o colaborador envia uma sessão para aquele terminal, a tela do tablet detecta sozinha (polling HTMX a cada 3s + cabeçalho `HX-Redirect`) e navega automaticamente para a assinatura — reaproveitando 100% do mesmo fluxo público de assinatura, sem nenhum código duplicado.

Para configurar um terminal:

1. Acesse `/contratos/terminais/` (qualquer usuário logado — não exige acesso ao Django Admin; ver nota abaixo).
2. Crie um novo terminal com um nome (ex.: "Tablet Recepção") — o token de acesso é gerado automaticamente. **Novo terminal nasce sempre inativo** (ver regra abaixo).
3. Clique em "Ativar" no terminal recém-criado.
4. Copie o link exibido (campo somente leitura, clique para selecionar) e deixe-o aberto no navegador do tablet — idealmente em modo quiosque.
5. Na tela de pós-geração, ao iniciar a assinatura, escolha o terminal no lugar de "QR Code" no seletor exibido (só aparece quando há ao menos um terminal ativo cadastrado).

Depois de assinar, a tela de conclusão volta sozinha (em ~8s, via `<meta http-equiv="refresh">`) para a tela de espera do terminal, pronta para o próximo paciente.

**Apenas um terminal ativo por vez.** O sistema não permite dois terminais ativos simultaneamente — ao tentar ativar um segundo, o botão "Ativar" fica desabilitado (com dica explicando o motivo) e, se forçado via POST, a ação é rejeitada com uma mensagem nomeando o terminal que precisa ser desativado primeiro. A regra é reforçada em dois níveis: na view (`terminal_alternar_ativo_view`) e no próprio model (`TerminalAssinatura.clean()`), então nem uma edição direta pelo Django Admin consegue burlar. Motivo: evita a recepção enviar uma sessão sem saber ao certo qual tablet físico vai recebê-la. Desativar nunca é bloqueado, mesmo que seja o único terminal ativo no momento.

**Desativação automática após 12h.** Todo terminal ativado é desativado sozinho depois de `TERMINAL_ATIVO_TTL_HORAS` (constante em `gestao_contratos/models.py`, padrão 12h) — reduz a janela de exposição caso o link vaze e evita um tablet esquecido ligado indefinidamente. A tela `/contratos/terminais/` mostra o horário exato em que isso vai acontecer para o terminal ativo. Implementado com o mesmo padrão de "lazy-expire" já usado nas sessões de assinatura (`SessaoAssinatura.expira_em`): checado sob demanda toda vez que o link do terminal é acessado (`TerminalAssinatura.expirar_se_vencido()`) e, como rede de segurança, varrido a cada 30 minutos pelo Celery Beat (`expirar_terminais_vencidos_task`) — assim o status fica correto mesmo se o tablet ficar desligado/sem rede e ninguém abrir a tela de gestão. Ativar de novo depois de expirado é uma ação manual (não reativa sozinho).

**Excluir um terminal** ("Excluir", com confirmação) remove o cadastro e invalida o link imediatamente — sessões de assinatura já associadas a ele não são afetadas (`SessaoAssinatura.terminal` usa `on_delete=SET_NULL`, então o histórico de auditoria permanece intacto).

O token do terminal deve ser tratado como sensível (não divulgado publicamente) — é longo e aleatório (`secrets.token_urlsafe`), mas quem tiver acesso a ele veria o mesmo fluxo de assinatura que o tablet mostra, incluindo o redirecionamento automático para a sessão de assinatura no instante em que a recepção a envia para aquele terminal (o polling é por token, não por dispositivo). Por isso a tela `/contratos/terminais/` tem um botão **"Gerar novo link"** por terminal: invalida o link atual na hora (passa a responder 404) e gera um novo — use se o link vazou, foi compartilhado por engano, ou o tablet foi trocado/perdido. Como essa é uma rotina operacional (pode ser necessária a qualquer momento, sem aviso prévio), ela fica disponível para qualquer colaborador logado, sem depender de acesso de administrador — o Django Admin (`/admin/gestao_contratos/terminalassinatura/`) continua funcionando para quem tiver acesso, mas só permite visualizar o token, não regenerá-lo.

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
- `enviar_whatsapp_task`: envia o PDF por WhatsApp via Z-API — **só é agendada se a Z-API estiver configurada** (ver variáveis abaixo) e o paciente tiver celular cadastrado.
- `solicitar_carimbo_tempo_task`: solicita o carimbo de tempo (RFC 3161) — **só é agendada se `CARIMBO_TEMPO_TSA_URL` estiver configurada**.
- `expirar_sessoes_vencidas_task` (Celery Beat, a cada 5 min): limpeza em lote de sessões de assinatura abandonadas.
- `expirar_terminais_vencidos_task` (Celery Beat, a cada 30 min): desativa terminais ativos há mais de `TERMINAL_ATIVO_TTL_HORAS` (padrão 12h) — ver [Terminal de assinatura dedicado](#terminal-de-assinatura-dedicado-tablet).

Como essas tarefas rodam em paralelo e o carimbo de tempo depende de uma chamada de rede externa à TSA, **o envio automático ao Dental Office/WhatsApp normalmente é concluído antes do carimbo terminar** — ou seja, a cópia enviada automaticamente por esses dois canais costuma não ter o carimbo embutido ainda; só a versão baixada depois pela recepção ("Baixar contrato assinado") já estará completa. Isso não compromete a validade (hash e token continuam corretos e acessíveis), é só uma questão de ordenação.

**Desenvolvimento local sem Redis**: defina `CELERY_TASK_ALWAYS_EAGER=true` no `.env` — as tarefas rodam de forma síncrona, no mesmo processo do `runserver`, sem precisar de Redis instalado. Os testes automatizados já fazem isso automaticamente.

**Produção (Railway)**: além do serviço web, são necessários:

1. O plugin **Redis** do Railway adicionado ao projeto (injeta `REDIS_URL` automaticamente).
2. Um serviço **worker**, apontando para este mesmo repositório, com *Custom Start Command* (definido nas Settings do serviço, **não** herdado do `railway.toml` — o padrão do repositório é o comando do gunicorn, então é preciso sobrescrever explicitamente):
   ```
   bash -c "cd abo-goias && celery -A abo_goias worker --loglevel=info --concurrency=2"
   ```
3. Um serviço **beat** (agendador), com o mesmo tipo de *Custom Start Command*:
   ```
   bash -c "cd abo-goias && celery -A abo_goias beat --loglevel=info"
   ```

O `cd abo-goias &&` é necessário porque o pacote `abo_goias` (e o `manage.py`) fica dentro dessa subpasta — sem isso, o Celery falha com `Error: Unable to load celery application. The module abo_goias was not found.`

**Atenção ao Healthcheck Path**: nas Settings desses dois serviços (worker e beat), confira se o campo de Healthcheck Path não herdou `/healthz/` do `railway.toml` — nenhum dos dois serve HTTP, então um healthcheck ativo faria o Railway reiniciar o container em loop, achando que está com problema.

Ambos precisam das mesmas variáveis de ambiente do serviço web (banco de dados, Dental Office, Redis) — use "Connect" no Railway para compartilhar variáveis entre serviços do mesmo projeto.

### Sincronização com o Dental Office

O envio de documentos usa `multipart/form-data` (não JSON+Base64, apesar do que a documentação oficial da API sugere — foi validado empiricamente que o endpoint `POST /customers/{id}/docs` só aceita multipart). Sempre envia a versão mais completa disponível do PDF: assinado > original salvo > gerado na hora.

Variáveis de ambiente:

- `DENTAL_CLIENT_ID`, `DENTAL_SECRET`: credenciais da API.
- `DENTAL_CLINIC_ID`: ID da clínica usado na busca de pacientes.
- `DENTAL_AUTH_URL`, `DENTAL_BASE_URL`: endpoints da API (padrão aponta para o ambiente demo).
- `DENTAL_VERIFY_TLS`, `DENTAL_TIMEOUT`, `DENTAL_USE_PROXY`: opções avançadas de conexão.
- `DENTAL_MAX_RETRIES`, `DENTAL_RETRY_BACKOFF_SECONDS`: tentativas e backoff exponencial para falhas transitórias (timeout, indisponibilidade, limite de requisições) — só em chamadas de leitura (GET), nunca em POST, para não arriscar duplicar um envio de documento. Padrão: 3 tentativas, base de 1s.
- `DENTAL_SYNC_TOKEN`: token do endpoint de sincronização agendada de `gestao_lab`.

#### Paginação

Os endpoints de listagem (`GET /customers`, `GET /users`) devolvem um número fixo de registros por página (a API não expõe nenhum parâmetro para configurar isso) e informam `total_pages` no corpo da resposta. `gestao_lab/integrations/dental.py::DentalClient` busca **uma página por chamada**; consolidar todas as páginas de uma busca é responsabilidade de `gestao_lab/services/dental_sync.py::listar_todas_paginas` — usada tanto pela sincronização completa quanto pela busca por nome (`buscar_e_importar_pacientes`/`buscar_e_importar_alunos`, e pela tela de listagem de contratos), então uma busca com mais resultados do que o limite por página nunca mais fica restrita à primeira página. A consolidação preserva a ordem devolvida pela API, remove duplicatas por `id` e para com segurança (sem loop indefinido) se `total_pages` for inconsistente.

Para diagnosticar problemas de envio manualmente (autenticação, leitura do arquivo, chamada à API, análise da resposta):

```powershell
python abo-goias\manage.py testar_envio_dental
python abo-goias\manage.py testar_envio_dental --contrato 5
python abo-goias\manage.py testar_envio_dental --apenas-auth
```

### Envio automático por WhatsApp (Z-API)

Opcional e desativado por padrão — sem as variáveis abaixo configuradas, nada muda: o botão manual "Encaminhar pelo WhatsApp" (link `wa.me`, com opção de compartilhamento direto de arquivo via Web Share API em navegadores compatíveis) continua sendo o único caminho.

A [Z-API](https://www.z-api.io) opera como uma sessão comum de WhatsApp conectada via QR Code (diferente da API Oficial da Meta) — não exige verificação de conta Business nem template de mensagem pré-aprovado.

Pré-requisitos (fora deste repositório, no painel da Z-API):

1. Uma instância criada em [app.z-api.io](https://app.z-api.io), com o QR Code lido por um número de WhatsApp dedicado (sessão "conectada").
2. O **Instance ID** e o **Token** da instância (visíveis no painel).
3. Opcionalmente, o **Client-Token** de segurança da conta (Segurança > Client-Token no painel) — recomendado em produção.

Variáveis de ambiente:

- `ZAPI_INSTANCE_ID`, `ZAPI_TOKEN`: credenciais obrigatórias — sem elas, o envio automático fica desativado.
- `ZAPI_CLIENT_TOKEN`: opcional — cabeçalho `Client-Token` adicional de segurança da conta.
- `ZAPI_BASE_URL`: padrão `https://api.z-api.io`.
- `ZAPI_TIMEOUT`: timeout HTTP em segundos, padrão 30.
- `ZAPI_MAX_RETRIES`, `ZAPI_RETRY_BACKOFF_SECONDS`: tentativas e backoff exponencial para falhas transitórias (timeout, indisponibilidade, limite de requisições) na camada de mensageria — padrão 3 tentativas, base de 2s.

#### Arquitetura da camada de mensageria

O envio não fala diretamente com a Z-API em nenhum ponto da aplicação — toda a comunicação passa por `mensageria/`, um pacote **na raiz do projeto** (não dentro de nenhuma app) para poder ser reaproveitado por qualquer app que precise enviar WhatsApp — hoje `gestao_contratos`, futuramente também `gestao_lab` (cobrança de material em atraso), sem criar dependência de uma app para a outra:

```text
mensageria/                              ← pacote compartilhado, não é uma app Django
    provider.py    — MessagingProvider (interface)
            ▲
            │
    zapi.py        — ZApiProvider — implementação atual, HTTP da Z-API
            │
    base.py        — MessagingService — retry com backoff + tratamento de erro padronizado
            │
gestao_contratos/services/whatsapp/__init__.py  — regra de negócio (status do contrato, eventos)
            │
gestao_contratos/tasks.py (enviar_whatsapp_task, Celery) — chamado por services/assinatura.py
```

- `mensageria/exceptions.py`: hierarquia de erros do provedor (`MessagingConfigurationError`, `MessagingAuthenticationError`, `InstanceDisconnectedError`, `QRCodePendingError`, `InvalidRecipientError`, `MessageRejectedError`, `RateLimitExceededError`, `MessagingTimeoutError`, `ProviderUnavailableError`) — nenhum chamador vê exceções específicas da Z-API.
- `mensageria/responses.py`: `MessagingResult`/`DisponibilidadeResult` — formato de retorno padronizado (`sucesso`, `message_id`, `erro`), igual para qualquer provedor.
- `mensageria/validators.py` / `serializers.py`: validação do destinatário e montagem dos payloads HTTP da Z-API.
- `mensageria/utils.py`: retry com backoff exponencial (só para erros transitórios — configuração, autenticação, destinatário inválido e mensagem rejeitada nunca são retentados, para não duplicar envio) e logging estruturado (nunca grava token/instance id, só metadados da chamada).

**Usar a partir de outra app** (ex.: `gestao_lab` para cobrança de material em atraso): `from mensageria import get_messaging_service, messaging_configurado` — igual ao que `gestao_contratos/services/whatsapp/__init__.py` já faz. Não é preciso adicionar `mensageria` a `INSTALLED_APPS`: é um pacote Python comum, sem models/templates/migrations.

**Adicionar um novo provedor no futuro** (ex.: voltar à API oficial da Meta, ou usar outro serviço): implemente `MessagingProvider` num novo módulo dentro de `mensageria/` e troque a instância criada em `get_messaging_service()` (`mensageria/__init__.py`) — nenhuma view, model, template ou lógica de negócio de app precisa mudar.

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
| `/contratos/terminais/` | Gestão de terminais (staff logado) — criar, copiar link, gerar novo link, ativar/desativar (só um ativo por vez) e excluir |
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
- `DJANGO_EMAIL_BACKEND`, `DJANGO_EMAIL_HOST`, `DJANGO_EMAIL_PORT`, `DJANGO_EMAIL_HOST_USER`, `DJANGO_EMAIL_HOST_PASSWORD`, `DJANGO_EMAIL_USE_TLS`, `DJANGO_EMAIL_USE_SSL`: configuracoes de e-mail (SMTP). Sem `DJANGO_EMAIL_HOST`, o backend cai para `console.EmailBackend` — os e-mails (reset de senha, solicitação/aprovação/rejeição de acesso) só aparecem no log do processo, nunca chegam a ninguém.
- `DJANGO_DEFAULT_FROM_EMAIL`: remetente usado em todos os e-mails da aplicação. Padrão `noreply@abogoias.local` — troque para um endereço real do domínio configurado no provedor SMTP, senão a maioria dos provedores rejeita ou marca como spam.
- `DJANGO_ADMINS_EMAIL`: e-mails que recebem a notificação de **novas solicitações de acesso**, separados por vírgula (ex.: `admin1@abogoias.org.br,admin2@abogoias.org.br`). Sem essa variável, o pedido continua sendo criado normalmente e aparece em `/admin/contas/solicitacaocadastro/` — só não dispara notificação automática.

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

### Configuração e segredos

- Corrigir `abo-goias/.env.example`: as chaves `SECRET_KEY`, `DEBUG` e `ALLOWED_HOSTS` não têm efeito nenhum — o `settings.py` lê `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` e `DJANGO_ALLOWED_HOSTS`. Corrigir os nomes no arquivo antes que alguém configure um ambiente copiando-o literalmente.
- Definir `DJANGO_DEBUG=false` explicitamente em todo ambiente que não seja desenvolvimento local — o padrão do código é `True` quando a variável não está definida (`settings.py:147`), o que também libera a `SECRET_KEY` insegura de fallback.
- Remover credenciais reais de `.env.example`, caso existam, e rotacionar senhas já compartilhadas.
- **[Feito]** A migration `0003_emprestimo_coordenador_usuario` foi neutralizada e a migration `0011_remover_usuario_coordenador_teste` remove a conta `coordenador.teste` em qualquer banco onde `migrate` rodar de novo. **Ainda pendente**: se essa migration já rodou em algum ambiente real antes desta correção (a branch `deploy` já continha o arquivo original), confirme que o próximo deploy realmente executou `migrate` e que a conta foi removida de fato — e trate a senha `Coordenador@123` como comprometida (não reutilizar em nenhum ambiente) até o histórico do Git ser reescrito, ver [nota acima](#status-atual).
- Criar usuários por fluxo administrativo, comando de setup ou painel admin, não por migration.
- Configurar `DJANGO_EMAIL_HOST` (e demais `DJANGO_EMAIL_*`) antes de ir para produção — sem isso, e-mails de reset de senha e aprovação de cadastro (`contas`) são apenas logados no console do container, nunca entregues, mesmo com `DEBUG=false`.
- Consolidar os dois arquivos `railway.toml` (raiz e `abo-goias/`) em um só, de acordo com o *Root Directory* configurado no serviço Railway, para evitar que fiquem divergentes com o tempo.

### Observabilidade e qualidade

- Configurar `LOGGING` em `settings.py` (hoje inexistente) — pelo menos um handler estruturado para produção e, idealmente, `ADMINS`/`MANAGERS` para receber notificação de erro 500.
- Adicionar logs estruturados para erros de integração Eduq e processamento de PPTX.
- Configurar um pipeline de CI (ex.: GitHub Actions) rodando `manage.py check`, `manage.py test` e o `pre-commit` (`isort`/`black`/`flake8`) a cada push/PR — hoje essas validações dependem de execução manual.
- Reforçar a cobertura de testes do app `identificadores` (~40 linhas hoje, bem abaixo dos demais apps).
- Considerar `CACHES` com Redis (o projeto já usa Redis para o Celery) se o volume de acesso justificar cache compartilhado entre workers do Gunicorn — hoje usa o `LocMemCache` padrão, por processo.

### Estrutura e domínio

- Decidir se o label legado `core` será mantido permanentemente ou se haverá uma migration planejada para renomear app label/tabelas/admin.
- Separar sincronização Eduq da geração de PPTX para evitar lentidão ou falha externa durante o download.
- Rodar a suíte de testes completa após as refatorações de nomenclatura.
- Definir e aplicar as regras de RBAC pendentes (`recepcao`/`coordenacao`/`gestao`, ver [Controle de acesso](#status-atual)) antes de operar com dados reais de pacientes — hoje qualquer usuário autenticado tem acesso igual a todo o sistema.

### Infraestrutura operacional

- Configurar um Volume persistente no Railway e `DJANGO_MEDIA_ROOT` antes de gerar contratos com pacientes reais — sem isso, os documentos assinados são perdidos a cada deploy.
- Adicionar os serviços `worker` e `beat` do Celery no Railway (mais o plugin Redis) para que o envio automático ao Dental Office e por WhatsApp de fato funcione em produção — sem eles, os contratos continuam sendo assinados normalmente, mas o envio automático fica só registrado como pendente/erro, exigindo reenvio manual pelo staff.
- Criar e conectar (ler o QR Code) uma instância no painel da Z-API antes de configurar `ZAPI_*` — sem uma sessão conectada, os envios automáticos falham.
- Rodar `pip-audit` ou `safety check` (não configurado hoje) contra `requirements.txt` periodicamente, já que não há checagem automática de CVEs nas dependências.

### Jurídico / LGPD

- Preencher o contato do encarregado de dados na política de privacidade e decidir o prazo de retenção da auditoria antes de assinar contratos com pacientes reais — ver [Pendências (validade jurídica)](#pendências-validade-jurídica).
