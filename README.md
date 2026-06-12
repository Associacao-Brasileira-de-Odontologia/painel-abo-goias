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

Campos reais observados na API:

- Turmas: `Identificador da Turma`, `Sigla`, `Descrição`, `TurmaId`, `Matrículas Ativas`, `Data de Início`, `Data de Finalização`.
- Alunos: `Id`, `Identificador`, `Nome`, `CPF`, `CelularSMS`, `Email`, `Descricao`, `UF`.

Para consultar a API e gravar turmas/alunos no banco local:

```powershell
python gestao_cme\manage.py sincronizar_eduq
```

Para simular a sincronizacao sem salvar alteracoes:

```powershell
python gestao_cme\manage.py sincronizar_eduq --dry-run
```

Para sincronizar alunos de uma turma especifica:

```powershell
python gestao_cme\manage.py sincronizar_eduq --somente-alunos --turma-codigo 50057
```

A API pode limitar consultas personalizadas repetidas a intervalos minimos de 5 minutos. Para sincronizar alunos de varias turmas em sequencia, use `--intervalo-consultas 300`.
