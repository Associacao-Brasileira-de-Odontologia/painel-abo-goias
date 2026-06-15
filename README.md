Repositório para desenvolvimento do painel gestão do cme por coordenadores

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
python gestao_cme\manage.py sincronizar_eduq --somente-turmas
```

Para simular a sincronizacao sem salvar alteracoes:

```powershell
python gestao_cme\manage.py sincronizar_eduq --somente-turmas --dry-run
```

Para sincronizar alunos de uma turma especifica:

```powershell
python gestao_cme\manage.py sincronizar_eduq --somente-alunos --turma-codigo 50057
```

Para sincronizar alunos de todas as turmas ja cadastradas:

```powershell
python gestao_cme\manage.py sincronizar_eduq --somente-alunos
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
python gestao_cme\manage.py migrar_dados_legado --dry-run
```

Para gravar os dados legados no banco local:

```powershell
python gestao_cme\manage.py migrar_dados_legado
```

Para usar outra pasta:

```powershell
python gestao_cme\manage.py migrar_dados_legado --diretorio "C:\caminho\para\csvs"
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
python gestao_cme\manage.py loaddata dados_exemplo
```
## Configuracao por ambiente

O projeto carrega variaveis de ambiente a partir do sistema operacional e, quando existir, dos arquivos `.env` na raiz do repositorio ou dentro da pasta `gestao_cme/`. Use `.env.example` como referencia e nunca versionar segredos reais.

Variaveis principais:

- `DJANGO_DEBUG`: use `true` em desenvolvimento e `false` em producao.
- `DJANGO_SECRET_KEY`: chave secreta do Django. Obrigatoria em producao.
- `DJANGO_ALLOWED_HOSTS`: dominios/IPs permitidos, separados por virgula. Obrigatorio em producao.
- `DJANGO_CSRF_TRUSTED_ORIGINS`: origens confiaveis para CSRF, separadas por virgula, incluindo protocolo. Exemplo: `https://cme.exemplo.com`.
- `DATABASE_URL`: conexao do banco. Exemplo PostgreSQL: `postgresql://usuario:senha@localhost:5432/gestao_cme`.
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
$env:DJANGO_ALLOWED_HOSTS="cme.seudominio.com.br"
$env:DJANGO_CSRF_TRUSTED_ORIGINS="https://cme.seudominio.com.br"
$env:DATABASE_URL="postgresql://usuario:senha@localhost:5432/gestao_cme"
```

Antes de publicar, execute:

```powershell
python gestao_cme\manage.py check --deploy
python gestao_cme\manage.py collectstatic
```

## Deploy no Railway

O repositorio inclui `railway.toml`, `requirements.txt` e uma rota publica de saude em `/healthz/`.

O Railway usa o `railway.toml` para:

- instalar dependencias Python a partir do `requirements.txt`;
- executar `python gestao_cme/manage.py collectstatic --noinput` no build;
- executar `python gestao_cme/manage.py migrate --noinput` antes de iniciar uma nova versao;
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
DJANGO_ALLOWED_HOSTS=cme.seudominio.com.br
DJANGO_CSRF_TRUSTED_ORIGINS=https://cme.seudominio.com.br
```

Para PostgreSQL, o sistema usa `DATABASE_URL` quando ela existir. O Railway tambem disponibiliza `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGHOST` e `PGPORT`, que sao aceitos como alternativa.
