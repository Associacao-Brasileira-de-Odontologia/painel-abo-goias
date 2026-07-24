# Jornada do Usuário — Gerador de Identificadores de Bancada

> Aplicação: `identificadores`. Documento complementar ao registro técnico
> (`docs/auditoria-identificadores.md`) — aqui o foco é contar a experiência de quem usa
> o sistema, do início ao fim do fluxo.

## Quem é o usuário

- **Coordenação acadêmica**, que precisa imprimir os identificadores (crachás) de
  bancada de uma turma inteira, geralmente no começo de um período letivo.

---

## Jornada única — Da turma ao arquivo pronto para imprimir

1. A coordenação abre o Gerador de Identificadores. A tela mostra um painorama
   rápido: quantas turmas existem, quantas estão ativas ou finalizadas, quantos
   alunos já estão sincronizados e quantos modelos de identificador estão
   disponíveis.
2. No campo "Pesquisar turma", a coordenação digita o nome ou o código da turma
   procurada — a lista de resultados se abre automaticamente conforme ela digita.
   Se preferir ver todas as turmas de uma vez, basta clicar na seta ao lado do
   campo de busca para abrir a lista completa (filtrada pela aba
   Ativas/Finalizadas/Todas escolhida acima).
3. Ao clicar na turma desejada, a lista se fecha e aparece um resumo dela: nome,
   código, quantos alunos ela tem, data de início e término. Se quiser conferir
   quem são os alunos antes de gerar o arquivo, basta clicar em "Ver alunos" — a
   lista completa (nome, matrícula, cidade/UF) aparece sob demanda, sem poluir a
   tela por padrão.
4. Logo abaixo, a coordenação escolhe o modelo visual do identificador entre os
   disponíveis (cada instituição parceira tem o seu).
5. Com turma e modelo escolhidos, o botão "Gerar identificadores" fica liberado.
   Ao clicar, o sistema:
   - Confere se algum aluno da turma está sem cidade/UF cadastrada e, se estiver,
     tenta atualizar essa localização automaticamente com o Eduq antes de gerar o
     arquivo.
   - Monta um arquivo de apresentação (PowerPoint) já paginado, com um identificador
     por aluno.
6. A tela mostra o resultado: quantos alunos entraram, quantas páginas o arquivo
   tem, e um botão para baixar o PPTX pronto — já é só abrir, revisar rapidamente e
   mandar para impressão e recorte.

## Antes de tudo isso — mantendo turmas e alunos atualizados

- Se a turma procurada ainda não aparece (por exemplo, um aluno muito recém-
  matriculado), a coordenação clica em "Atualizar turmas e alunos", no topo da
  tela — o sistema busca a lista mais recente direto do Eduq antes de repetir a
  busca.

---

## O que fica de fora dessa jornada

- O sistema não faz nenhuma edição do conteúdo do identificador além do que já vem
  no modelo escolhido — é puramente "escolher turma + escolher modelo + gerar".
- Assim como nas demais ferramentas, não há diferenciação de permissão por papel.
