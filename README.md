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
- Aplicação Gestão de Contratos completa: seleção/confirmação de dados do paciente, geração de termos, assinatura remota via QR Code, envio assíncrono ao Dental Office e por WhatsApp — detalhes na [seção dedicada](#gestão-de-contratos).
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

Aplicação `gestao_contratos` — gera termos de consentimento a partir dos dados do paciente (sincronizados do Dental Office), permite assinatura remota do paciente via QR Code e envia o documento assinado automaticamente ao Dental Office e por WhatsApp.

### Fluxo completo

```text
Selecionar paciente (lista local + busca no Dental Office)
    ↓
Confirmar dados do paciente (edição manual + convênio, campo local)
    ↓
Gerar contrato (DOCX + PDF, preenchidos automaticamente)
    ↓
Gerar QR Code de assinatura
    ↓
Paciente assina no próprio celular/tablet (página pública, sem login)
    ↓
PDF assinado salvo (nunca sobrescreve o original)
    ↓ (em paralelo, assíncrono via Celery)
Envio automático ao Dental Office        Envio automático por WhatsApp
    (com retry)                              (Meta Cloud API, se configurada)
```

Cada etapa relevante fica registrada em `EventoContrato`, alimentando tanto a auditoria quanto o painel de status em tempo real (polling HTMX) na tela de pós-geração — sem necessidade de recarregar a página para saber se o paciente já assinou ou se o envio automático já foi concluído.

### Modelos e ciclo de vida

- **`ContratoGerado`**: um registro por documento gerado. Campos-chave:
  - `status`: `gerado` → `aguardando_assinatura` → `assinado` (ou `cancelado`).
  - `versao`: sequencial por paciente + tipo de contrato.
  - `hash_sha256`: hash do PDF vigente — recalculado após a assinatura.
  - `arquivo` (DOCX), `arquivo_pdf` (PDF original), `arquivo_pdf_assinado` (PDF definitivo, com a assinatura mesclada — nunca sobrescreve `arquivo_pdf`).
  - `status_envio_dental` / `status_envio` (e-mail/WhatsApp manual): canais de envio, independentes do `status` de ciclo de vida do contrato.
- **`SessaoAssinatura`**: sessão temporária de assinatura remota. Token da URL pública assinado criptograficamente (`django.core.signing`, HMAC com a `SECRET_KEY` do Django) — nenhum segredo fica armazenado em banco. Expira em 30 minutos (configurável), permite apenas uma assinatura (transição de status atômica no banco) e é expirada tanto sob demanda (quando alguém acessa o link ou a tela de status) quanto por uma limpeza periódica via Celery Beat.
- **`EventoContrato`**: trilha de eventos (sessão criada/aberta, assinatura concluída, envio ao Dental/WhatsApp iniciado-concluído-erro etc.) — auditoria completa com timestamp e payload livre em JSON.

Os quatro modelos de contrato disponíveis (`Modelo 1`–`Modelo 4`) são gerados **inteiramente em código** (via `python-docx` e `reportlab`, ver `services/documentos.py`) — não dependem de nenhum arquivo de template externo, nem de LibreOffice/Microsoft Word para a conversão a PDF.

### Assinatura remota

O paciente nunca assina no computador do colaborador. Ao clicar em "Gerar QR Code de assinatura" na tela de pós-geração:

1. O sistema cria uma `SessaoAssinatura` e exibe um QR Code apontando para uma URL pública (`/contratos/assinar/<token>/`) — sem exigir login.
2. O paciente escaneia com o próprio celular (ou usa um tablet da recepção) e assina num canvas HTML5 (aceita touch e mouse).
3. Ao confirmar, o servidor valida a imagem (formato PNG, dimensões mínimas, tamanho máximo), faz um *claim* atômico da sessão (evita dupla assinatura em caso de corrida) e mescla a assinatura sobre o PDF original, numa posição fixa reservada para isso.
4. O PDF resultante é salvo em `arquivo_pdf_assinado`, com um carimbo de auditoria (data/hora, IP) no rodapé.

A tela de pós-geração do staff atualiza sozinha (polling HTMX a cada 3s) enquanto aguarda a assinatura, parando automaticamente assim que o status muda — sem JavaScript adicional além do HTMX (vendorizado localmente, sem CDN).

### Processamento assíncrono (Celery + Redis)

Após a assinatura, dois envios são agendados em segundo plano, de forma independente entre si — uma falha num não afeta o outro, e nenhuma falha de agendamento (ex.: Redis indisponível) pode quebrar a confirmação de assinatura do paciente:

- `enviar_dental_task`: reenvia ao Dental Office, com retry automático (backoff exponencial, até 5 tentativas).
- `enviar_whatsapp_task`: envia o PDF por WhatsApp via Meta Cloud API — **só é agendada se a Meta estiver configurada** (ver variáveis abaixo) e o paciente tiver celular cadastrado.
- `expirar_sessoes_vencidas_task` (Celery Beat, a cada 5 min): limpeza em lote de sessões de assinatura abandonadas.

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
| `/contratos/contrato/<id>/pos-geracao/` | Download, e-mail, WhatsApp, assinatura, envio ao Dental |
| `/contratos/assinar/<token>/` | Página pública de assinatura (sem login) |
| `/contratos/contrato/<id>/status-assinatura/` | Fragmento de status usado pelo polling HTMX |

Veja `gestao_contratos/urls.py` para a lista completa.

## Configuracao por ambiente

O projeto carrega variaveis de ambiente a partir do sistema operacional e, quando existir, dos arquivos `.env` na raiz do repositorio ou dentro da pasta Django `abo-goias/`. Use `.env.example` como referencia e nunca versionar segredos reais.

Variaveis principais:

- `DJANGO_DEBUG`: use `true` em desenvolvimento e `false` em producao.
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
