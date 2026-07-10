# **Auditoria de Arquitetura e UX - Painel da ABO Goiás**

https://claude.ai/code/artifact/97714b13-b63e-4710-a1c7-d036ce15fe08?via=auto_preview

# **Alteração da integração com WhatsApp**

Você atuará como um **Arquiteto de Software Sênior especializado em Python, Django, Integrações REST, Clean Architecture e Engenharia de Software**.

Sua missão é realizar uma **refatoração arquitetural completa da camada de integração com o WhatsApp**, substituindo a utilização da **API Oficial do WhatsApp (Meta WhatsApp Cloud API)** pela **Z-API**, preservando toda a lógica de negócio existente na aplicação.

A implementação deve seguir princípios de baixo acoplamento, alta coesão e facilidade de manutenção, permitindo que novos provedores de mensageria possam ser adicionados futuramente com alterações mínimas.

---

# Contexto

O projeto é desenvolvido em:

* Python
* Django
* Templates Django
* Arquitetura baseada em Apps
* Integrações via APIs REST

Anteriormente, toda a arquitetura foi planejada para utilizar a API Oficial do WhatsApp.

Entretanto, houve uma mudança de decisão técnica e toda a integração deverá utilizar exclusivamente a **Z-API**.

O objetivo não é apenas trocar endpoints, mas revisar toda a arquitetura relacionada ao envio de mensagens.

---

# Objetivos

Realize uma análise completa do projeto para identificar todos os pontos onde a API Oficial do WhatsApp é utilizada ou preparada para utilização.

Mapeie:

* imports
* services
* helpers
* adapters
* utilitários
* configurações
* variáveis de ambiente
* models
* signals
* tasks
* views
* formulários
* comandos
* templates
* documentação
* comentários
* constantes
* testes automatizados

Liste todos os arquivos impactados antes de iniciar qualquer modificação.

---

# Refatoração da Arquitetura

Substitua toda a dependência da API Oficial do WhatsApp por uma camada de abstração.

Implemente uma arquitetura semelhante a:

```
MessagingProvider (Interface)

        ▲

        │

ZApiProvider

        │

MessagingService

        │

Aplicação Django
```

Nenhuma View, Model ou Template deverá conhecer diretamente a Z-API.

Toda comunicação deverá ocorrer através da camada de serviços.

---

# Serviço de Mensageria

Crie um serviço central responsável por:

* envio de mensagens de texto;
* envio de documentos PDF;
* envio de imagens;
* envio de arquivos;
* envio de mensagens com legenda;
* verificação de disponibilidade do serviço;
* tratamento de erros;
* registro de logs;
* padronização das respostas.

Toda interação com o WhatsApp deverá ocorrer exclusivamente por esse serviço.

---

# Configuração

Remova todas as configurações relacionadas à API Oficial do WhatsApp.

Substitua por configurações específicas da Z-API.

Utilize variáveis de ambiente para armazenar:

* URL base da API;
* Instance ID;
* Token de segurança;
* Client Token (quando aplicável);
* Timeouts;
* Configurações de retry.

Nenhuma credencial deve permanecer fixa no código.

---

# Estrutura Recomendada

Organize a integração em uma estrutura semelhante a:

```
services/

    messaging/

        provider.py

        base.py

        zapi.py

        exceptions.py

        serializers.py

        validators.py

        responses.py

        utils.py
```

Caso exista outra estrutura mais adequada ao projeto atual, adapte mantendo o mesmo nível de organização.

---

# Tratamento de Erros

Implemente tratamento para:

* timeout;
* autenticação inválida;
* instância desconectada;
* QR Code pendente;
* número inválido;
* mensagem rejeitada;
* limite de requisições;
* falhas temporárias;
* erros internos da API.

As exceções devem ser encapsuladas e convertidas em mensagens padronizadas para a aplicação.

---

# Logs

Implemente logs estruturados contendo:

* horário;
* endpoint utilizado;
* destinatário;
* tipo da mensagem;
* tempo de resposta;
* código HTTP;
* resultado;
* mensagem retornada pela API.

Nunca registrar tokens ou credenciais.

---

# Retry

Implemente mecanismo de retry para erros transitórios.

Evite reenviar mensagens em situações onde isso possa gerar duplicidade.

Utilize estratégia de backoff exponencial quando apropriado.

---

# Preparação para Filas

Mesmo que o envio continue síncrono neste momento, organize o código para futura integração com filas assíncronas (como Celery, RQ ou Django Q), mantendo a separação entre a lógica de negócio e o mecanismo de envio.

---

# Atualização das Funcionalidades Existentes

Revise todos os fluxos onde há envio ou previsão de envio de mensagens via WhatsApp, como:

* envio de contratos;
* envio de documentos PDF;
* notificações automáticas;
* confirmação de procedimentos;
* lembretes;
* mensagens administrativas;
* qualquer outro fluxo identificado durante a análise.

Garanta que todos passem a utilizar exclusivamente a nova camada de mensageria.

---

# Limpeza do Projeto

Após a migração:

* remova código morto relacionado à API Oficial do WhatsApp;
* elimine dependências não utilizadas;
* remova configurações obsoletas;
* exclua comentários e documentação desatualizados;
* elimine imports redundantes.

Certifique-se de que não permaneçam referências à implementação anterior.

---

# Testes

Atualize ou crie testes para validar:

* envio de mensagem de texto;
* envio de PDF;
* envio de imagem;
* tratamento de falhas;
* autenticação;
* comportamento em caso de indisponibilidade da API;
* validação de números;
* respostas padronizadas do serviço.

Utilize mocks para chamadas externas.

---

# Documentação

Atualize toda a documentação técnica do projeto para refletir a nova arquitetura, incluindo:

* diagrama da camada de mensageria;
* fluxo de envio de mensagens;
* variáveis de ambiente necessárias;
* instruções de configuração da Z-API;
* exemplos de uso do serviço de mensageria;
* orientações para adicionar novos provedores no futuro.

---

# Critérios de Qualidade

Durante toda a implementação:

* preserve integralmente a lógica de negócio existente;
* minimize alterações nas Views, Models e Templates;
* concentre as mudanças na camada de serviços;
* siga os princípios SOLID, DRY e Clean Architecture;
* mantenha baixo acoplamento entre a aplicação e a Z-API;
* evite duplicação de código;
* utilize tipagem estática (`typing`) sempre que possível;
* documente classes e métodos públicos com docstrings.

---

# Entregáveis

Ao final da implementação, apresente:

1. Um relatório dos arquivos modificados e a justificativa de cada alteração.
2. Um resumo da nova arquitetura da integração com a Z-API.
3. As variáveis de ambiente necessárias para configuração.
4. Um checklist confirmando que todas as referências à API Oficial do WhatsApp foram removidas.
5. Recomendações para futuras evoluções, como suporte a múltiplos provedores de mensageria ou envio assíncrono por filas.

# **Auditoria na implementação da API do Dental Office**

Você atuará como um **Arquiteto de Software Sênior especializado em Python, Django, Integrações REST, Engenharia de Software e APIs de terceiros**.

Sua missão é realizar uma **auditoria completa da integração entre a aplicação Django e a API do Dental Office**, identificando a causa da limitação na busca de pacientes e implementando uma solução robusta para recuperação de todos os registros disponíveis.

Antes de qualquer alteração, compreenda integralmente o funcionamento atual da integração e valide a capacidade da API em trabalhar com paginação, filtros e recuperação de grandes volumes de dados.

---

# Contexto

A aplicação utiliza a API do Dental Office para pesquisar pacientes cadastrados.

Atualmente, quando uma pesquisa é realizada, a API retorna **no máximo 60 pacientes** por requisição.

Esse comportamento faz com que, em pesquisas que retornam mais de 60 resultados, apenas a primeira página seja utilizada pela aplicação, ocultando os demais pacientes existentes.

O sistema deve ser capaz de recuperar **100% dos registros disponíveis**, independentemente da quantidade de páginas retornadas pela API.

---

# Objetivos

Realize uma análise completa da implementação atual da integração.

Identifique:

* onde ocorre a chamada da API;
* quais endpoints são utilizados;
* como a pesquisa de pacientes é realizada;
* como os parâmetros da requisição são enviados;
* quais filtros são utilizados;
* como a resposta da API é tratada;
* se existe suporte nativo à paginação;
* se existem parâmetros como:

  * page;
  * pageNumber;
  * currentPage;
  * offset;
  * skip;
  * limit;
  * per_page;
  * page_size;
  * next_page;
  * total_pages;
  * total_records;
  * has_next;
  * cursor;
  * qualquer outro mecanismo de paginação disponível.

---

# Auditoria da API

Analise detalhadamente a documentação da API do Dental Office e valide:

* método HTTP utilizado;
* parâmetros aceitos;
* estrutura do JSON de resposta;
* metadados de paginação;
* limites de registros por requisição;
* limites de taxa (rate limit);
* comportamento quando existem centenas ou milhares de pacientes.

Caso a API possua diferentes estratégias de paginação, escolha a mais eficiente e compatível com a arquitetura da aplicação.

---

# Auditoria da Implementação

Analise o código existente.

Identifique:

* Services
* Views
* Helpers
* Clients HTTP
* Requests
* Repositories
* Serializers
* DTOs
* Models
* Utilitários

Verifique se atualmente:

* apenas a primeira página é consumida;
* existe lógica incompleta de paginação;
* existem limitações artificiais no código;
* existem filtros incorretos;
* existe tratamento inadequado das respostas.

---

# Implementação da Paginação

Implemente uma solução capaz de recuperar automaticamente todas as páginas disponibilizadas pela API.

A implementação deverá:

* iniciar na primeira página;
* identificar automaticamente a existência de novas páginas;
* realizar as requisições necessárias;
* consolidar todos os pacientes em uma única coleção;
* eliminar registros duplicados (caso existam);
* preservar a ordenação original da API quando aplicável.

A solução deve funcionar independentemente da quantidade de páginas.

Exemplos:

* 20 pacientes
* 60 pacientes
* 61 pacientes
* 130 pacientes
* 500 pacientes
* 5.000 pacientes

O comportamento deve permanecer consistente.

---

# Performance

Avalie o impacto da paginação.

Caso necessário:

* implemente carregamento incremental;
* minimize chamadas desnecessárias;
* reutilize conexões HTTP;
* evite consultas duplicadas;
* implemente timeout adequado;
* implemente retry para falhas temporárias;
* respeite limites da API.

Caso a API permita alterar a quantidade de registros por página, utilize o maior valor suportado para reduzir o número de requisições.

---

# Tratamento de Erros

Implemente tratamento para:

* timeout;
* autenticação inválida;
* falhas de rede;
* página inexistente;
* resposta inválida;
* JSON malformado;
* limite de requisições;
* erros internos da API;
* interrupção durante a paginação.

A aplicação deve retornar mensagens padronizadas sem interromper o funcionamento do sistema.

---

# Logs

Implemente logs estruturados contendo:

* página consultada;
* quantidade de registros retornados;
* quantidade total de páginas;
* quantidade total de pacientes recuperados;
* tempo de resposta;
* endpoint utilizado;
* código HTTP;
* eventuais erros encontrados.

Nunca registre informações sensíveis ou credenciais.

---

# Compatibilidade

A nova implementação não deve alterar a lógica de negócio da aplicação.

Os componentes consumidores da busca de pacientes devem continuar funcionando exatamente como antes, porém recebendo agora todos os registros disponíveis.

Caso existam outras funcionalidades que utilizem o mesmo mecanismo de paginação, adapte-as para reutilizar a nova implementação.

---

# Qualidade da Arquitetura

Durante a implementação:

* preserve a arquitetura atual do projeto;
* concentre a lógica de paginação na camada de serviços;
* evite duplicação de código;
* siga os princípios SOLID e DRY;
* utilize tipagem (`typing`) sempre que possível;
* documente métodos públicos com docstrings;
* mantenha baixo acoplamento entre a aplicação e a API do Dental Office.

---

# Testes

Crie ou atualize testes para validar cenários como:

* retorno com menos de 60 pacientes;
* retorno com exatamente 60 pacientes;
* retorno com múltiplas páginas;
* retorno vazio;
* falhas durante a navegação entre páginas;
* duplicidade de registros;
* perda de conexão durante a paginação.

Utilize mocks para simular diferentes respostas da API.

---

# Relatório Final

Ao concluir a análise e a implementação, apresente um relatório contendo:

1. Como a paginação da API do Dental Office funciona.
2. Quais limitações foram encontradas na implementação atual.
3. Quais arquivos foram modificados.
4. Como a solução foi implementada.
5. Impactos na arquitetura da aplicação.
6. Evidências de que todos os pacientes passam a ser recuperados, independentemente da quantidade de páginas.
7. Recomendações para futuras otimizações, como cache de consultas, sincronização incremental e processamento assíncrono para grandes volumes de dados.
