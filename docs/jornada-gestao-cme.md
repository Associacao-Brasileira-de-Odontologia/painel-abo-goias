# Jornada do Usuário — Gestão de CME

> Aplicação: `gestao_cme` (Central de Material e Esterilização). Documento
> complementar à documentação técnica (`docs/documentacao-gestao-cme.md`)
> — aqui o foco é contar a experiência de quem usa o sistema no dia a dia, do início ao
> fim de cada fluxo.

## Quem é o usuário

- **Coordenador da CME**, o operador do dia a dia: recebe pacotes de instrumentais dos
  alunos, controla devoluções, cadastra materiais e empréstimos.
- **Aluno de pós-graduação**, que entrega e retira pacotes e pode pegar kits
  emprestados — não acessa o sistema, mas é o "cliente" de quase todo fluxo.
- Ao fundo, o **Eduq** (sistema acadêmico da instituição) mantém turmas e alunos
  sempre atualizados, sem que ninguém precise digitar esse cadastro manualmente.

---

## Jornada 1 — Um pacote de instrumentais para esterilizar

1. Um aluno chega à CME com pacotes de instrumentais para esterilizar.
2. O coordenador abre "Registrar entrada", busca o aluno pelo nome ou matrícula (o
   campo já entende os alunos sincronizados do Eduq) e informa quantos pacotes estão
   sendo entregues.
3. Confirma o registro. O sistema gera, na hora, um código sequencial para cada
   pacote — são esses códigos que o coordenador etiqueta fisicamente em cada pacote
   antes de mandá-los para a esterilização.
4. Se esse aluno ainda não tem um abrigo (compartimento físico) atribuído, o sistema
   avisa, mas não impede o registro — a atribuição de abrigo pode ser feita depois.
5. Dias (ou horas) depois, o mesmo aluno volta para buscar os pacotes já
   esterilizados. O coordenador abre "Registrar saída"; a tela já mostra, de cara,
   uma lista de alunos com pendências, sem precisar buscar do zero.
6. Ao escolher o aluno, aparecem só os pacotes ainda pendentes dele, em ordem de
   entrada. O coordenador marca os que estão sendo retirados naquele momento e
   confirma.
7. O pacote passa a aparecer como concluído no histórico de Movimentações — que
   mostra a entrada e a saída de cada pacote como uma única linha, com data de cada
   etapa.

## Jornada 2 — Emprestando um kit de material

1. Um aluno precisa de um kit de instrumentos para um procedimento e não tem o
   próprio material.
2. O coordenador abre "Novo empréstimo", busca o aluno, escolhe o kit disponível e
   define uma data prevista de devolução.
3. Ao confirmar, o sistema já copia automaticamente, para o registro do empréstimo,
   a lista de materiais que compõem aquele kit — o coordenador não precisa
   redigitar item por item.
4. O aluno some com o kit; a listagem de Empréstimos mostra o status "Emprestado".
5. Se a data prevista passar sem devolução, o próprio sistema muda o status para
   "Atrasado" sozinho — todo dia de manhã, e também sempre que alguém abre a tela de
   Empréstimos. O coordenador nunca precisa lembrar de marcar isso manualmente.
6. Quando o aluno devolve o kit, o coordenador clica em "Devolver" na linha
   correspondente — pronto, o ciclo do empréstimo está fechado.
7. Cada coordenador só vê os empréstimos que ele mesmo registrou (um superusuário
   vê todos) — evita um coordenador mexer no empréstimo de outro por engano.

## Jornada 3 — Mantendo o cadastro de alunos em dia

1. Todos os dias, de madrugada, o sistema conversa sozinho com o Eduq e atualiza a
   lista de turmas e alunos — ninguém no dia a dia precisa cadastrar isso na mão.
2. Se um aluno muito recém-matriculado ainda não aparece (a sincronização diária
   ainda não rodou), o coordenador pode forçar uma atualização na hora, direto da
   tela de alunos.
3. Ocasionalmente, o coordenador atribui um abrigo físico a um aluno (ou remove um
   vínculo antigo) — a tela de abrigos sempre mostra, em tempo real, quem está
   ocupando cada um.

## Jornada 4 — Cuidando do que dá suporte a tudo isso

- De vez em quando, o coordenador cadastra um **material** novo no catálogo, monta
  um **kit** combinando materiais e quantidades, ou cadastra um **abrigo** físico
  novo.
- Excluir um material ou kit que já tem histórico de empréstimo é bloqueado pelo
  sistema — em vez disso, a tela orienta a apenas "inativar" o item, preservando o
  histórico.

---

## O que fica de fora dessa jornada

- Não existe hoje um fluxo de cadastro de aluno "do zero" como caminho principal —
  o cadastro manual é só uma exceção para cobrir uma eventual falha da
  sincronização com o Eduq.
- Assim como no Portal, não há diferenciação de permissão por papel: qualquer
  coordenador autenticado acessa todas as telas do CME.
