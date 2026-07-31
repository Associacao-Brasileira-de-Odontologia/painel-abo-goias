# Painel ABO Goiás

Sistema web que centraliza a gestão operacional da Associação Brasileira de Odontologia de Goiás (ABO Goiás). Um único projeto Django (`abo_goias`) reúne quatro módulos funcionais — Gestão de CME, Gestão de Laboratório, Gestão de Contratos e Identificadores de Bancada — sobre uma base de autenticação e dados compartilhada.

Este documento é o ponto de entrada técnico do repositório: arquitetura, como rodar localmente, como o deploy funciona hoje e o que avaliar antes de integrar o sistema a outra infraestrutura (ex.: uma intranet institucional). Documentação funcional detalhada (casos de uso, jornadas do usuário, decisões de negócio) vive em [`docs/`](#referências) — este README não duplica esse conteúdo, só aponta para ele.

## Sumário

- [Arquitetura](#arquitetura)
- [Módulos do sistema](#módulos-do-sistema)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Como executar em desenvolvimento](#como-executar-em-desenvolvimento)
- [Configuração por ambiente](#configuração-por-ambiente)
- [Processamento assíncrono (Celery + Redis)](#processamento-assíncrono-celery--redis)
- [Deploy e infraestrutura](#deploy-e-infraestrutura)
- [Segurança, dados e conformidade (LGPD)](#segurança-dados-e-conformidade-lgpd)
- [Guia para avaliação de integração](#guia-para-avaliação-de-integração)
- [Status e pendências conhecidas](#status-e-pendências-conhecidas)
- [Referências](#referências)

## Arquitetura

### Stack técnica

| Camada | Tecnologia |
|---|---|
| Aplicação | Django 6.0.6 (Python), servido por **Gunicorn** (WSGI) |
| Estáticos | **Whitenoise** — servidos pelo próprio processo Django, sem CDN/nginx separado |
| Banco de dados | **PostgreSQL** em produção (`psycopg`); **SQLite** em desenvolvimento local |
| Fila assíncrona | **Redis** (broker/result backend) + **Celery** (worker + beat) |
| Front-end | Server-side rendering (Django Templates) + **HTMX** vendorizado localmente (sem CDN) para polling/fragmentos — sem SPA, sem build de JS |
| Documentos | `python-docx`, `reportlab`, `pypdf`, `qrcode` — geração de contratos (DOCX/PDF) e QR Code inteiramente em código, sem depender de LibreOffice/Word |
| Deploy atual | **Railway** (`railway.toml`), com serviço web + worker + beat |

Não é "só um app Django": o envio automático de contratos, notificações por WhatsApp e limpeza de sessões dependem de um **worker Celery rodando à parte**, com Redis como intermediário. Isso é relevante para qualquer decisão de infraestrutura (ver [Guia para avaliação de integração](#guia-para-avaliação-de-integração)).

### Como as apps se relacionam

Um único projeto Django (`abo_goias`) registra as apps abaixo em `INSTALLED_APPS`. Todas compartilham o mesmo banco, a mesma sessão de autenticação e o mesmo design system (`static/css/`):

| App (label Python) | Prefixo de URL | Função |
|---|---|---|
| `contas` | `/` (login, perfil, solicitação de acesso) | Autenticação, controle de acesso, portal inicial |
| `gestao_cme` (label legado `core`) | `/gestao-cme/` | Esterilização de materiais (CME) |
| `gestao_lab` | `/laboratorio/` | Pedidos a laboratórios externos |
| `gestao_contratos` | `/contratos/` | Contratos digitais com assinatura eletrônica |
| `identificadores` | `/identificadores/` | Geração de identificadores de bancada (PPTX) |

Além das apps Django, dois **pacotes Python compartilhados** (sem models/templates/migrations, não registrados em `INSTALLED_APPS`) evitam duplicação de código entre apps:

- **`comum/`**: helpers reutilizados por mais de uma app — parsing/filtro de datas (`datas.py`), requisições HTTP com retry (`http.py`), paginação (`paginacao.py`) e agregação de métricas do portal (`portal.py`).
- **`mensageria/`**: camada de envio de WhatsApp desacoplada de provedor (`MessagingProvider` como interface, `ZApiProvider` como implementação atual da Z-API) — usada hoje por `gestao_contratos` e pela cobrança automática de `gestao_lab`, pronta para outros usos futuros sem criar dependência entre apps.

## Módulos do sistema

Descrição curta de cada módulo — para casos de uso completos e fluxo do usuário, siga os links.

### Gestão de CME

Controle de movimentações de esterilização de materiais: entrada, retirada, kits, armários, abrigos e empréstimos, com dashboard de KPIs e exportação de relatório por turma. Alunos e turmas são sincronizados da API do Eduq (`manage.py sincronizar_eduq`).

📄 [`docs/documentacao-gestao-cme.md`](docs/documentacao-gestao-cme.md) · 🚶 [`docs/jornada-gestao-cme.md`](docs/jornada-gestao-cme.md)

### Gestão de Laboratório

Controla o ciclo de pedidos de material a laboratórios externos (moldagem → pedido → envio → entrega → faturamento), com sincronização de pacientes/alunos a partir do Dental Office e cobrança automática por WhatsApp de pedidos atrasados.

📄 [`docs/documentacao-gestao-lab.md`](docs/documentacao-gestao-lab.md) · 🚶 [`docs/jornada-gestao-lab.md`](docs/jornada-gestao-lab.md)

### Gestão de Contratos

Gera termos de consentimento a partir dos dados do paciente (Dental Office), com assinatura remota (QR Code ou terminal dedicado/tablet), verificação de identidade, carimbo de tempo (RFC 3161) e envio automático ao Dental Office e por WhatsApp. É o módulo com maior peso de conformidade jurídica do sistema — ver [Segurança, dados e conformidade](#segurança-dados-e-conformidade-lgpd).

📄 [`docs/documentacao-gestao-contratos.md`](docs/documentacao-gestao-contratos.md) · 🚶 [`docs/jornada-gestao-contratos.md`](docs/jornada-gestao-contratos.md)

### Identificadores de Bancada

Gera arquivos PPTX com identificadores por turma (nome e local do aluno), a partir dos mesmos dados sincronizados do Eduq.

📄 [`docs/documentacao-identificadores.md`](docs/documentacao-identificadores.md) · 🚶 [`docs/jornada-identificadores.md`](docs/jornada-identificadores.md)

### Portal e Contas (autenticação)

Login, logout, reset de senha e portal inicial com métricas agregadas dos demais módulos. Cadastro de usuário é sempre mediado: alguém sem conta solicita acesso publicamente (`/solicitar-acesso/`) e um administrador aprova ou rejeita pelo Django Admin (com e-mails automáticos em cada etapa); o mesmo admin também pode convidar um usuário diretamente. Hoje o controle de acesso é binário — qualquer usuário autenticado tem acesso igual a todo o sistema (ver [Status e pendências conhecidas](#status-e-pendências-conhecidas)).

📄 [`docs/documentacao-portal-contas.md`](docs/documentacao-portal-contas.md) · 🚶 [`docs/jornada-portal-acesso.md`](docs/jornada-portal-acesso.md)

## Estrutura do projeto

```text
abo-goias/
├── abo_goias/          # Configurações Django do projeto principal + bootstrap do Celery
├── contas/             # Autenticação (login, senha, perfil, solicitação de acesso)
├── gestao_cme/         # Gestão de CME
├── gestao_lab/         # Gestão de Laboratório (sincronização Dental Office)
├── gestao_contratos/   # Gestão de Contratos (geração, assinatura, envio)
├── identificadores/    # Identificador de Bancadas
├── comum/              # Pacote compartilhado (datas, HTTP, paginação, portal) — não é app Django
├── mensageria/         # Pacote compartilhado de WhatsApp/Z-API — não é app Django
├── static/css/         # Design system (tokens + componentes) compartilhado entre apps
├── manage.py
└── db.sqlite3          # Banco local de desenvolvimento
```

## Como executar em desenvolvimento

```powershell
pip install -r requirements.txt
python abo-goias\manage.py migrate
python abo-goias\manage.py runserver
```

Rotas principais em desenvolvimento:

| Rota | Módulo |
|---|---|
| `/` | Portal |
| `/gestao-cme/` | Gestão de CME |
| `/laboratorio/` | Gestão de Laboratório |
| `/contratos/` | Gestão de Contratos |
| `/identificadores/` | Identificadores de Bancada |
| `/admin/` | Django Admin |
| `/healthz/` | Health check (usado pelo Railway) |

Para rodar o fluxo completo de Gestão de Contratos localmente (geração, assinatura, envio automático) sem precisar de Redis, defina `CELERY_TASK_ALWAYS_EAGER=true` — ver [Processamento assíncrono](#processamento-assíncrono-celery--redis).

### Validação antes de commitar/publicar

```powershell
python abo-goias\manage.py check
python abo-goias\manage.py test
```

Cobertura de testes (referência: `gestao_contratos` está em ~100% da lógica de negócio):

```powershell
pip install coverage
python -m coverage run --source=. --omit="*/migrations/*,manage.py,*/settings.py,*/wsgi.py,*/asgi.py,*/celery.py,*/__init__.py" abo-goias\manage.py test
python -m coverage report -m
```

### Comandos de gestão relevantes

| Comando | App | Função |
|---|---|---|
| `sincronizar_eduq` | `gestao_cme` | Sincroniza turmas/alunos do Eduq |
| `sincronizar_eduq_lab` | `gestao_lab` | Idem, para o contexto de laboratório |
| `sincronizar_dental` | `gestao_lab` | Sincroniza pacientes do Dental Office |
| `criar_grupos_padrao` | `gestao_cme` | Cria os grupos `recepcao`/`coordenacao`/`gestao` (idempotente; ainda não usado por nenhuma view) |
| `migrar_dados_legado` | `gestao_cme` | Migração única de planilhas/CSV legados |
| `importar_planilhas` / `importar_legado` / `importar_pedidos_legado` | `gestao_cme` / `gestao_lab` | Importações pontuais de dados legados |
| `testar_envio_dental` | `gestao_contratos` | Diagnóstico manual do envio ao Dental Office (auth, leitura de arquivo, chamada de API) |

## Configuração por ambiente

Variáveis de ambiente carregadas do sistema operacional e, se existir, de um arquivo `.env`. Use `abo-goias/.env.example` como referência (ver observação em [Status e pendências conhecidas](#status-e-pendências-conhecidas) sobre 3 nomes desatualizados nesse arquivo) — **nunca versionar segredos reais**.

### Django core

| Variável | Função |
|---|---|
| `DJANGO_DEBUG` | `true` em dev, `false` em produção |
| `DJANGO_SECRET_KEY` | Obrigatória em produção |
| `DJANGO_ALLOWED_HOSTS` | Domínios/IPs permitidos, separados por vírgula |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Origens confiáveis para CSRF (com protocolo), ex.: `https://sistemas.exemplo.com` |
| `DATABASE_URL` | Conexão do banco, ex.: `postgresql://usuario:senha@host:5432/abo_goias` |
| `DJANGO_STATIC_ROOT` | Pasta de destino do `collectstatic` |
| `DJANGO_MEDIA_ROOT` | Pasta de arquivos de mídia (contratos, assinaturas) — ver nota de armazenamento efêmero abaixo |

### Segurança e sessão

| Variável | Função |
|---|---|
| `DJANGO_SECURE_SSL_REDIRECT` | Redireciona HTTP → HTTPS (recomendado `true` em produção) |
| `DJANGO_SESSION_COOKIE_SECURE` / `DJANGO_CSRF_COOKIE_SECURE` | Restringe cookies a HTTPS |
| `DJANGO_SECURE_HSTS_SECONDS` | Tempo de HSTS — só ativar com HTTPS já validado |
| `DJANGO_SECURE_PROXY_SSL_HEADER` | Ative com `true` quando o app estiver atrás de proxy reverso que envia `X-Forwarded-Proto` — **relevante para integração com intranet**, ver [Guia para avaliação de integração](#guia-para-avaliação-de-integração) |
| `DJANGO_SESSION_COOKIE_AGE` | Duração da sessão em segundos (padrão 8h) |
| `DJANGO_SESSION_EXPIRE_AT_BROWSER_CLOSE` | Expira sessão ao fechar o navegador (padrão `true`) |

### E-mail

| Variável | Função |
|---|---|
| `DJANGO_EMAIL_HOST`, `DJANGO_EMAIL_PORT`, `DJANGO_EMAIL_HOST_USER`, `DJANGO_EMAIL_HOST_PASSWORD`, `DJANGO_EMAIL_USE_TLS`/`_USE_SSL` | Credenciais SMTP. **Sem `DJANGO_EMAIL_HOST`, o backend cai para console mesmo em produção** — e-mails de reset de senha e aprovação de acesso não chegam a ninguém, só ficam no log |
| `DJANGO_DEFAULT_FROM_EMAIL` | Remetente de todos os e-mails da aplicação |
| `DJANGO_ADMINS_EMAIL` | Destinatários da notificação de nova solicitação de acesso |

### Integrações externas

| Integração | Variáveis | Observação |
|---|---|---|
| **Eduq** (turmas/alunos) | `EDUQ_DOMINIO`, `EDUQ_USUARIO`, `EDUQ_SENHA`, `EDUQ_AUTH_URL`, `EDUQ_DATA_URL`, `EDUQ_CONSULTA_TURMAS_ID`, `EDUQ_CONSULTA_DETALHES_TURMA_ID`, `EDUQ_VERIFY_TLS`, `EDUQ_USE_PROXY` | Usada por `gestao_cme` e `identificadores` |
| **Dental Office** (pacientes) | `DENTAL_CLIENT_ID`, `DENTAL_SECRET`, `DENTAL_CLINIC_ID`, `DENTAL_AUTH_URL`, `DENTAL_BASE_URL`, `DENTAL_VERIFY_TLS`, `DENTAL_TIMEOUT`, `DENTAL_MAX_RETRIES`, `DENTAL_SYNC_TOKEN` | Cliente compartilhado por `gestao_lab` e `gestao_contratos`; documentos enviados via `multipart/form-data` |
| **WhatsApp (Z-API)** | `ZAPI_INSTANCE_ID`, `ZAPI_TOKEN`, `ZAPI_CLIENT_TOKEN`, `ZAPI_BASE_URL`, `ZAPI_TIMEOUT`, `ZAPI_MAX_RETRIES` | Opcional — sem essas variáveis, o envio automático fica desativado e só o link manual `wa.me` funciona. Exige uma instância conectada via QR Code no painel da Z-API (fora deste repositório) |
| **Carimbo de tempo (TSA, RFC 3161)** | `CARIMBO_TEMPO_TSA_URL`, `CARIMBO_TEMPO_TSA_USERNAME`/`_PASSWORD`, `CARIMBO_TEMPO_TIMEOUT` | Opcional — desativado por padrão. TSA pública sugerida para testes (`https://freetsa.org/tsr`) **não é credenciada pela ICP-Brasil** |

Exemplo mínimo para produção:

```powershell
$env:DJANGO_DEBUG="false"
$env:DJANGO_SECRET_KEY="uma-chave-longa-e-aleatoria"
$env:DJANGO_ALLOWED_HOSTS="sistemas.seudominio.com.br"
$env:DJANGO_CSRF_TRUSTED_ORIGINS="https://sistemas.seudominio.com.br"
$env:DATABASE_URL="postgresql://usuario:senha@localhost:5432/abo_goias"
```

## Processamento assíncrono (Celery + Redis)

Três fluxos do sistema dependem de tarefas em segundo plano, sempre de forma independente entre si (falha em uma não afeta as outras, e Redis indisponível nunca bloqueia a ação síncrona do usuário):

- **Envio de contrato** ao Dental Office (com retry) e por WhatsApp, após a assinatura.
- **Carimbo de tempo (RFC 3161)** sobre o hash do PDF assinado.
- **Limpeza periódica** (Celery Beat): sessões de assinatura expiradas (a cada 5 min) e terminais de assinatura ativos há mais de 12h (a cada 30 min).
- **Cobrança automática** (Celery Beat, diária às 9h): mensagem por WhatsApp a laboratórios com pedidos de material atrasados (`gestao_lab`).

**Desenvolvimento local sem Redis**: `CELERY_TASK_ALWAYS_EAGER=true` roda as tarefas de forma síncrona no mesmo processo — os testes automatizados já fazem isso automaticamente.

**Produção**: exige, além do serviço web, um serviço **worker** (`celery -A abo_goias worker`) e um serviço **beat** (`celery -A abo_goias beat`) rodando separadamente, mais um Redis acessível por ambos — ver comandos exatos em [Deploy e infraestrutura](#deploy-e-infraestrutura).

## Deploy e infraestrutura

Hoje o deploy roda no **Railway**, orientado por `railway.toml`:

- **Build**: instala dependências e roda `collectstatic`.
- **Pre-deploy**: roda `migrate --noinput` antes de cada nova versão.
- **Start**: `gunicorn abo_goias.wsgi:application` (4 workers, 2 threads cada).
- **Health check**: `/healthz/`.

Três serviços Railway compõem o ambiente de produção completo:

| Serviço | Comando | Observação |
|---|---|---|
| **web** | comando padrão do `railway.toml` (gunicorn) | Serve HTTP; usa `/healthz/` |
| **worker** | `bash -c "cd abo-goias && celery -A abo_goias worker --loglevel=info --concurrency=2"` | Precisa de *Custom Start Command* nas Settings do serviço — **não** herda do `railway.toml` |
| **beat** | `bash -c "cd abo-goias && celery -A abo_goias beat --loglevel=info"` | Idem. **Desative o Healthcheck Path herdado** nesses dois serviços — nenhum dos dois serve HTTP |

Web, worker e beat compartilham as mesmas variáveis de ambiente (banco, Redis, credenciais de integrações) — use "Connect" no Railway para propagar entre serviços do mesmo projeto.

Um plugin **PostgreSQL** e um plugin **Redis** do Railway completam a infraestrutura — o Redis injeta `REDIS_URL` automaticamente nos serviços conectados.

**Armazenamento de arquivos**: contratos (DOCX/PDF) e imagens de assinatura são salvos em `DJANGO_MEDIA_ROOT`. O filesystem do container Railway é **efêmero** — sem um Volume persistente montado e apontado por essa variável, os documentos assinados somem a cada novo deploy.

## Segurança, dados e conformidade (LGPD)

- O sistema armazena dados clínicos e contratuais sensíveis (CPF, RG, endereço, prontuário de atendimento, assinatura e imagem biométrica simples) — sujeitos à LGPD.
- Autenticação por sessão Django, CSRF ativo em todos os formulários, cabeçalhos de segurança (`SECURE_*`) configuráveis por ambiente.
- Cadastro de usuário sempre mediado por aprovação humana (nunca automático) — ver [Portal e Contas](#portal-e-contas-autenticação).
- Controle de acesso hoje é binário (qualquer usuário autenticado acessa tudo) — RBAC por grupo já modelado, mas não aplicado nas views (ver [Status e pendências conhecidas](#status-e-pendências-conhecidas)).
- Assinatura eletrônica de contratos tem reforços específicos de validade jurídica: confirmação de identidade presencial pelo colaborador, verificação de identidade do próprio paciente/responsável legal, carimbo de tempo de terceiro (RFC 3161) e trilha de auditoria completa (`EventoContrato`) — detalhes em [`docs/documentacao-gestao-contratos.md`](docs/documentacao-gestao-contratos.md).
- Política de privacidade pública em `/contratos/politica-privacidade/`.
- Pendências jurídicas conhecidas (prazo de retenção de auditoria, contato do encarregado de dados, TSA não credenciada pela ICP-Brasil): ver [Status e pendências conhecidas](#status-e-pendências-conhecidas).

## Guia para avaliação de integração

Pontos relevantes para quem for avaliar como conectar este sistema a **outra infraestrutura** (ex.: uma intranet institucional administrada por outro time):

- **Autenticação hoje é independente**: sessão própria do Django, sem SSO. Uma integração por link simples não exige nenhuma mudança; SSO (SAML/OIDC/LDAP) ou proxy reverso exigem trabalho nos dois lados — o suporte a `X-Forwarded-Proto` já existe (`DJANGO_SECURE_PROXY_SSL_HEADER`), mas login único não vem de graça junto com o proxy.
- **Não é uma aplicação de processo único**: além do serviço web, há um **worker Celery** e um **beat** (agendador) rodando separadamente, com **Redis** como intermediário. Qualquer novo ambiente de hospedagem precisa suportar (ou continuar tendo acesso a) esses três processos — ver [Processamento assíncrono](#processamento-assíncrono-celery--redis).
- **Armazenamento de arquivo não pode ser efêmero**: contratos assinados (documentos legais) são salvos em disco via `DJANGO_MEDIA_ROOT`. Um ambiente de deploy sem volume persistente perde esses arquivos a cada implantação.
- **Dependências de rede externas**: Dental Office, Eduq e Z-API são APIs de terceiros chamadas pelo servidor — a nova infraestrutura precisa permitir tráfego de saída (egress) para esses serviços, e as credenciais (`DENTAL_*`, `EDUQ_*`, `ZAPI_*`, TSA) precisam continuar geridas com o mesmo nível de segurança.
- **Banco de dados**: Postgres em produção — uma migração de hospedagem deve preservar (ou migrar) esse banco, não recriar do zero.
- **Health check já existe**: `/healthz/`, hoje consumido pelo Railway — reaproveitável por qualquer monitoramento externo.
- **Dados sensíveis (LGPD)**: qualquer novo ambiente que passe a hospedar ou expor este sistema herda a responsabilidade sobre os dados de pacientes — ver [Segurança, dados e conformidade](#segurança-dados-e-conformidade-lgpd).

## Status e pendências conhecidas

| Categoria | Item | Observação |
|---|---|---|
| Segurança | `DEBUG` inseguro por padrão | `DJANGO_DEBUG` assume `True` quando a variável não é definida — todo ambiente não-dev precisa declará-la explicitamente como `false` |
| Segurança | Sem `LOGGING` configurado | Só o logging default do Django; sem `ADMINS`/`MANAGERS` para notificação de erro 500 |
| Segurança | Controle de acesso binário | Grupos `recepcao`/`coordenacao`/`gestao` já existem (`criar_grupos_padrao`), mas nenhuma view os aplica ainda — qualquer usuário autenticado acessa tudo |
| Segurança | Senha de conta de teste exposta no histórico do Git | A conta (`coordenador.teste`) já foi removida por migration, mas a senha usada segue no histórico de commits — tratar como comprometida; só sai com reescrita de histórico (fora do escopo de uma atualização normal de código) |
| Infraestrutura | E-mail cai para console mesmo em produção | Sem `DJANGO_EMAIL_HOST`, e-mails de reset de senha/aprovação de acesso são só logados, nunca entregues — sem erro visível |
| Infraestrutura | Armazenamento efêmero no Railway | Sem Volume persistente + `DJANGO_MEDIA_ROOT` apontado para ele, documentos assinados somem a cada deploy |
| Infraestrutura | Sem cache compartilhado | `CACHES` não configurado — usa `LocMemCache` por processo, não compartilhado entre workers do Gunicorn |
| Infraestrutura | Dois `railway.toml` divergentes | Um na raiz do repositório, outro em `abo-goias/`, com comandos diferentes — qual é usado depende do *Root Directory* configurado no serviço Railway |
| Infraestrutura | `.env.example` com nomes desatualizados | `abo-goias/.env.example` usa `SECRET_KEY`/`DEBUG`/`ALLOWED_HOSTS` (sem prefixo); `settings.py` lê `DJANGO_SECRET_KEY`/`DJANGO_DEBUG`/`DJANGO_ALLOWED_HOSTS` — copiar o arquivo literalmente não configura essas três variáveis |
| Qualidade | Sem pipeline de CI | Nenhum workflow automatizado rodando `manage.py check`/`test`/`pre-commit` a cada push ou PR — depende de execução manual |
| Qualidade | Cobertura de testes desigual | `gestao_contratos` cobre ~100% da lógica de negócio; `identificadores` tem cobertura bem mais fraca |
| Qualidade | Sem checagem de vulnerabilidades de dependências | `pip-audit`/`safety` não configurado contra `requirements.txt` |
| Estrutura | Label legado `core` em `gestao_cme` | Mantido por compatibilidade com migrations/fixtures/URLs do admin existentes (`/admin/core/...`) — decisão pendente sobre renomear ou manter permanentemente |
| Jurídico/LGPD | Prazo de retenção da auditoria não definido | Dados de auditoria de assinatura (IP, user-agent, imagem, carimbo de tempo) sem prazo formal — sugestão: alinhar ao prazo prescricional civil (art. 206 do Código Civil) |
| Jurídico/LGPD | Contato do encarregado de dados pendente | Placeholder na política de privacidade ainda não preenchido |
| Jurídico/LGPD | TSA padrão não credenciada pela ICP-Brasil | `https://freetsa.org/tsr` é pública e compatível com RFC 3161, mas sem peso jurídico formal equivalente a uma ACT credenciada — trocável via `CARIMBO_TEMPO_TSA_URL` |

## Referências

Documentação funcional completa (casos de uso, decisões de negócio e histórico de auditoria) por módulo:

- [`docs/documentacao-gestao-cme.md`](docs/documentacao-gestao-cme.md) · [`docs/jornada-gestao-cme.md`](docs/jornada-gestao-cme.md)
- [`docs/documentacao-gestao-lab.md`](docs/documentacao-gestao-lab.md) · [`docs/jornada-gestao-lab.md`](docs/jornada-gestao-lab.md)
- [`docs/documentacao-gestao-contratos.md`](docs/documentacao-gestao-contratos.md) · [`docs/jornada-gestao-contratos.md`](docs/jornada-gestao-contratos.md)
- [`docs/documentacao-identificadores.md`](docs/documentacao-identificadores.md) · [`docs/jornada-identificadores.md`](docs/jornada-identificadores.md)
- [`docs/documentacao-portal-contas.md`](docs/documentacao-portal-contas.md) · [`docs/jornada-portal-acesso.md`](docs/jornada-portal-acesso.md)

Planos e auditorias de evolução do projeto:

- [`docs/plano-limpeza-codigo.md`](docs/plano-limpeza-codigo.md) — levantamento completo de estrutura, código e segurança, com plano de execução em etapas.
- [`docs/avaliacao-visual-padronizacao-frontend.md`](docs/avaliacao-visual-padronizacao-frontend.md) — auditoria comparativa de front-end entre as 5 aplicações.
- [`docs/plano-melhorias-visuais-e-faturamento.md`](docs/plano-melhorias-visuais-e-faturamento.md) — plano em etapas para padronização visual e faturamento por orçamento.

Material de apoio adicional em [`docs/assets/`](docs/assets/) e [`docs/Ferramentas-Painel-ABO-Goias.docx`](docs/Ferramentas-Painel-ABO-Goias.docx).
