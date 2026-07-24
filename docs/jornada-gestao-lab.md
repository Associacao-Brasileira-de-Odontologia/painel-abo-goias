# Jornada do Usuário — Gestão de Laboratório

> Aplicação: `gestao_lab`. Documento complementar à documentação técnica
> (`docs/documentacao-gestao-lab.md`) — aqui o foco é contar a experiência de quem usa
> o sistema no dia a dia, do início ao fim de cada fluxo.

## Quem é o usuário

- **Coordenador de laboratório**, o operador do dia a dia: registra pedidos e
  moldagens, acompanha prazos de entrega e fecha o faturamento.
- **Aluno de pós-graduação**, que realiza a moldagem do paciente — não acessa o
  sistema, mas é quem "origina" o pedido.
- **Paciente**, titular do pedido — também não acessa o sistema.
- **Laboratório parceiro externo**, que recebe o material e devolve a peça
  finalizada — recebe cobranças automáticas por WhatsApp quando está atrasado.

---

## Jornada 1 — Do consultório ao laboratório

1. Um aluno faz a moldagem do paciente. O coordenador registra essa moldagem no
   sistema — busca o paciente e o aluno pelo campo de busca (que já entende nome,
   ou, no caso do aluno, também matrícula e turma).
2. Quando a moldagem está pronta para seguir para um laboratório, o coordenador
   clica em "Encaminhar" — o sistema já leva paciente e aluno pré-preenchidos para
   o formulário de novo pedido, sem precisar buscar de novo.
3. O coordenador escolhe o laboratório parceiro e a equipe responsável, informa a
   previsão de entrega e descreve o serviço. Ao confirmar, o pedido nasce com o
   status "Em dia".
4. Alguns pedidos nascem direto, sem passar por uma moldagem prévia (ex.: um
   aparelho) — o fluxo é o mesmo formulário, só sem o passo de conversão.
5. Conforme o prazo passa, o coordenador acompanha a Visão Geral e o
   Acompanhamento: o próprio sistema muda o pedido para "Atrasado" quando o prazo
   vence sem entrega — ninguém precisa marcar isso manualmente.
6. Quando o material é enviado ao laboratório, o coordenador registra o envio (data
   de envio); quando a peça pronta chega, registra a entrega.

## Jornada 2 — Fechando o financeiro

1. Assim que um pedido é marcado como entregue, ele aparece automaticamente na fila
   de Faturamento — não é preciso ir buscá-lo, ele já está lá esperando.
2. O coordenador acompanha, para cada pedido, se o **paciente** já pagou e se o
   **laboratório** já foi pago — dois controles independentes, cada um com seu
   próprio toggle na listagem.
3. Assim que as duas partes estiverem quitadas, o pedido sai da fila de faturamento
   sozinho e passa a constar como "Concluído" no histórico.
4. Se um laboratório demora a entregar, o sistema já sabe: uma vez por dia, ele
   soma todos os pedidos atrasados de cada laboratório e dispara **uma única
   mensagem de WhatsApp** cobrando aquele laboratório — sem que o coordenador
   precise cobrar um por um manualmente.

## Jornada 3 — Encontrando paciente ou aluno na hora de registrar

1. No formulário de pedido (ou moldagem), o coordenador começa a digitar o nome do
   paciente: o campo busca ao mesmo tempo na base local e, ao vivo, no Dental
   Office — sem precisar sincronizar nada antes. Se o paciente aparecer só na busca
   externa, escolher o resultado já grava esse paciente no sistema na hora.
2. Para o aluno, a busca é só local (o Eduq — fonte de alunos — não permite buscar
   por nome). Se o aluno não aparecer, o próprio campo oferece um atalho:
   escolher a turma dele e sincronizar na hora, sem precisar sair da tela nem
   atualizar a base inteira.
3. Uma vez por dia, o sistema também sincroniza sozinho os pacientes (do Dental
   Office) e os alunos/turmas (do Eduq) — o botão manual só cobre o caso de alguém
   muito recém-cadastrado que ainda não apareceu.

## Jornada 4 — Cadastros de apoio

- De vez em quando, o coordenador cadastra um **laboratório parceiro** novo
  (telefone, WhatsApp, quais equipes atendem) ou uma **equipe** de coordenação —
  ambos acessíveis por um pequeno submenu na navegação lateral, sem tirar espaço da
  tela principal.

---

## O que fica de fora dessa jornada

- Hoje não existe edição de um pedido ou moldagem já criado pela interface
  operacional — só criação, alternância de status (enviado/entregue/faturado) e
  exclusão. Corrigir um dado errado exige excluir e recriar o registro.
- Assim como nas demais ferramentas, não há diferenciação de permissão por papel.
