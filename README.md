# Sistemas internos ABO Goiás

Repositório para desenvolvimento dos sistemas internos da Associação Brasileira de Odontologia de Goiás.

O projeto Django principal usa o pacote `abo_goias` e funciona como portal para múltiplas aplicações internas. Atualmente ele reúne:

- Gestão de CME: controle de movimentações, materiais, kits e abrigos.
- Identificador de Bancadas: geração de arquivos PPTX com identificadores por turma.

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
- Refatoração de nomenclatura:
  - `abo_goias`: projeto/plataforma principal.
  - `gestao_cme`: aplicação de Gestão de CME.
  - `identificadores`: aplicação de Identificador de Bancadas.

Pontos de atenção:

- O app `gestao_cme` ainda usa `label = "core"` em `gestao_cme/apps.py` para manter compatibilidade com migrations, fixtures, tabelas existentes e URLs do admin.
- Por causa desse label legado, fixtures e migrations ainda referenciam modelos como `core.material`, `core.aluno`, etc.
- URLs do admin também continuam no formato `/admin/core/...`.
- O arquivo `.env.example` deve servir apenas como modelo. Não versionar credenciais reais.
- Existe uma migration que cria um usuário de teste (`coordenador.teste`). Antes de produção, recomenda-se remover essa criação automática ou substituir por um comando/fixture exclusivo de desenvolvimento.
- A geração de identificadores ainda faz tentativa de atualização de localização pelo Eduq durante o request. Para produção, o ideal é separar sincronização e geração, ou mover a sincronização para uma rotina assíncrona.

## Estrutura do projeto

```text
abo-goias/
├── abo_goias/          # Configurações Django do projeto principal
├── gestao_cme/         # Aplicação Gestão de CME
├── identificadores/    # Aplicação Identificador de Bancadas
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
- Admin: `http://127.0.0.1:8000/admin/`

## Validação recomendada

Antes de abrir merge ou publicar uma versão, execute:

```powershell
python abo-goias\manage.py check
python abo-goias\manage.py test
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
