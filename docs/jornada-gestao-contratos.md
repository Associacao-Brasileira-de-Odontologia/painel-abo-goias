# Jornada do Usuário — Gerador de Contratos

> Aplicação: `gestao_contratos`. Documento complementar ao registro técnico
> (`docs/auditoria-gestao-contratos.md`) e ao `docs/Ferramentas-Painel-ABO-Goias.docx`
> (que detalha a base jurídica da assinatura) — aqui o foco é contar a experiência de
> quem usa o sistema, do início ao fim de cada fluxo.

## Quem é o usuário

- **Colaborador da recepção/clínica**, que gera o contrato e conduz o atendimento.
- **Paciente** (ou responsável legal, se for menor de idade), que efetivamente assina
  o documento — pelo próprio celular ou num terminal dedicado da clínica.

---

## Jornada 1 — Gerando o contrato, do lado do colaborador

1. O colaborador busca o paciente (base local ou, se ainda não existir, importado do
   Dental Office na hora).
2. Confirma os dados clínicos do atendimento — profissional responsável, CRO,
   observações — e escolhe qual modelo de contrato ou termo de consentimento se
   aplica ao procedimento.
3. Ao gerar, o sistema monta o documento (DOCX e PDF) já preenchido com os dados do
   paciente e do procedimento — sem precisar editar nada manualmente.
4. Na tela seguinte ("pós-geração"), o colaborador decide como o paciente vai
   assinar:
   - **Pelo próprio celular:** o sistema mostra um **QR Code**; o paciente aponta a
     câmera e é levado direto para a página de assinatura.
   - **Num terminal dedicado da clínica** (por exemplo, um tablet na recepção): o
     colaborador direciona o paciente para aquele equipamento, que já está com a
     sessão de assinatura pronta.
5. Enquanto o paciente assina (em outro dispositivo), a tela do colaborador
   atualiza sozinha o status — não precisa ficar atualizando a página manualmente.

## Jornada 2 — Assinando, do lado do paciente

1. O paciente abre o link (via QR Code ou no terminal). Antes de qualquer coisa, o
   sistema pede uma confirmação de identidade: a própria data de nascimento (se for
   o paciente) ou o CPF do responsável (se o paciente for menor de idade) — com um
   limite de tentativas, para não virar uma tentativa de adivinhação.
2. Confirmada a identidade, aparece o conteúdo do contrato e uma área para assinar
   — o paciente desenha a própria assinatura na tela com o dedo (ou o mouse, se for
   pelo computador).
3. Ao confirmar, o sistema aplica essa assinatura sobre o documento, registra a
   data, hora e uma trilha de evidências (sem expor isso ao paciente), e mostra uma
   tela de "assinatura concluída".
4. Opcionalmente, um colaborador pode presencialmente confirmar a identidade do
   paciente também — um reforço a mais, sem ser obrigatório.

## Jornada 3 — Depois de assinado

1. Assim que a assinatura é concluída, o sistema calcula uma "impressão digital"
   (hash) do PDF final — é o que garante, depois, que ninguém alterou o documento.
2. Se configurado, o sistema também solicita um carimbo de tempo (RFC 3161) a uma
   autoridade externa — uma prova independente de quando o documento passou a
   existir.
3. Em segundo plano (sem o colaborador precisar esperar na tela), o sistema tenta:
   - Enviar o contrato assinado ao Dental Office.
   - Enviar o contrato assinado por WhatsApp ao paciente.
4. O colaborador acompanha esses envios na própria tela do contrato — se algum
   falhar (ex.: WhatsApp desconectado), o sistema mostra o erro e permite tentar de
   novo, ou usar o link manual (`wa.me`) como alternativa.
5. O contrato (DOCX, PDF e PDF assinado) pode ser baixado a qualquer momento pela
   tela do contrato.

## Jornada 4 — Validando um documento (qualquer pessoa, a qualquer momento)

1. Alguém que recebeu um PDF assinado (o próprio paciente, um advogado, um
   auditor) pode acessar a página pública de validação, sem precisar de login.
2. Envia o PDF; o sistema recalcula a impressão digital do arquivo recebido e
   compara com a que foi registrada no momento da assinatura.
3. O resultado aparece na hora: um selo verde confirma que o documento é o mesmo
   que foi assinado (autêntico e íntegro); um selo vermelho indica que o arquivo
   foi alterado ou não veio desta plataforma.

## Jornada 5 — Gerenciando os terminais dedicados

- A recepção mantém uma pequena lista de terminais (tablets) cadastrados — cada um
  com seu próprio link fixo. O colaborador pode ativar, desativar ou gerar um novo
  token de segurança para um terminal, sem precisar reinstalar nada no
  equipamento.

---

## O que fica de fora dessa jornada

- Não há edição de um contrato já gerado — se algo estiver errado antes da
  assinatura, o caminho é cancelar aquela sessão e gerar um novo contrato.
- A base jurídica da assinatura (por que ela é válida, como o hash funciona, e
  quando valeria a pena considerar uma plataforma de terceiros) está detalhada à
  parte em `docs/Ferramentas-Painel-ABO-Goias.docx`.
