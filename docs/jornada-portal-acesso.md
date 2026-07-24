# Jornada do Usuário — Portal e Acesso

> Aplicação: `contas` (autenticação e solicitação de acesso) + `gestao_cme.views.portal`
> (tela inicial). Documento complementar aos casos de uso técnicos já existentes
> (`docs/auditoria-portal-contas-mensageria.md`) — aqui o foco é contar a experiência do
> usuário do começo ao fim, não listar telas e regras.

## Quem é o usuário

- **Colaborador novo**, que ainda não tem conta e precisa pedir acesso.
- **Colaborador do dia a dia**, que já tem login e usa o Portal como primeira tela de
  todo dia de trabalho.
- **Administrador**, que aprova ou recusa pedidos de acesso.

---

## Jornada 1 — Pedindo acesso pela primeira vez

1. Um novo colaborador da ABO Goiás recebe o link do sistema, mas ainda não tem conta.
   Na tela de login, ele encontra a opção "Solicitar acesso".
2. Preenche um formulário simples: nome, e-mail, e uma justificativa curta de por que
   precisa de acesso.
3. Ao enviar, vê uma tela de confirmação ("Solicitação enviada") — nenhuma conta é
   criada ainda.
4. Nos bastidores, um e-mail é disparado para os administradores cadastrados,
   avisando que há um novo pedido pendente. O colaborador também recebe um e-mail
   confirmando que o pedido foi recebido.
5. Um administrador abre a solicitação (hoje pelo Django Admin), avalia o pedido e:
   - **Aprova** → uma conta de usuário é criada; o colaborador passa a poder fazer
     login normalmente.
   - **Recusa** → o colaborador recebe um e-mail avisando que o pedido não foi aceito.
6. Se nada for feito, o pedido simplesmente fica pendente — não há um prazo que o
   cancele automaticamente.

## Jornada 2 — O dia a dia de quem já tem conta

1. O colaborador acessa o sistema e faz login com usuário e senha.
2. Cai direto no **Portal** — a tela inicial, comum a todos os sistemas do Painel.
   Nela, encontra:
   - Um resumo em números (quantos pedidos de laboratório em aberto, quantos
     empréstimos de kit atrasados, quantos contratos aguardando assinatura etc.).
   - Um feed com a atividade mais recente entre as aplicações.
   - Um atalho para cada uma das ferramentas (Gestão de CME, Gestão de Laboratório,
     Identificadores de Bancada, Gerador de Contratos).
3. A partir daqui, o colaborador clica na ferramenta que precisa usar naquele
   momento — a navegação lateral de cada ferramenta sempre tem um link para "Voltar
   ao portal".
4. Ao final do expediente (ou de qualquer sessão), o colaborador faz logout pelo menu
   do próprio nome, no canto superior da tela.

## Jornada 3 — Esqueci minha senha

1. Na tela de login, o colaborador clica em "Esqueci minha senha".
2. Informa o e-mail cadastrado; o sistema envia um link de redefinição.
3. Pelo link, o colaborador escolhe uma nova senha e volta a conseguir fazer login
   normalmente.

---

## O que fica de fora dessa jornada

- Não existe hoje diferenciação de permissão por papel/grupo — qualquer colaborador
  com conta aprovada tem acesso completo a todas as ferramentas do Painel.
- O Portal é só leitura: nenhuma ação de negócio (registrar pedido, gerar contrato
  etc.) acontece por ali — ele apenas resume e direciona para a ferramenta certa.
