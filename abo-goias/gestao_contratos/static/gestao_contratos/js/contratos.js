/**
 * Comportamento da tela unificada de confirmação e geração de contrato:
 * seções colapsáveis, exibição condicional do responsável legal e
 * preenchimento automático de cidade/UF a partir do CEP (ViaCEP).
 */
(function () {
    "use strict";

    function toggleCollapse(head) {
        var section = head.closest(".gc-collapsible");
        if (!section) return;
        var isOpen = section.classList.toggle("is-open");
        head.setAttribute("aria-expanded", isOpen ? "true" : "false");
    }

    document.querySelectorAll(".gc-collapsible-head").forEach(function (head) {
        head.addEventListener("click", function () {
            toggleCollapse(head);
        });
    });

    // ── Responsável legal: mostra a seção só quando a data de nascimento
    // indicar paciente menor de 18 anos. O servidor já decide o estado
    // inicial (aberta/fechada) via `menor_de_idade`; aqui só reagimos a
    // mudanças no campo enquanto o colaborador ainda está preenchendo.
    var campoNascimento = document.getElementById("id_data_nascimento");
    var secaoResponsavel = document.getElementById("gc-secao-responsavel");

    function ehMenorDeIdade(valor) {
        if (!valor) return null;
        var nascimento = new Date(valor + "T00:00:00");
        if (isNaN(nascimento.getTime())) return null;
        var hoje = new Date();
        var idade = hoje.getFullYear() - nascimento.getFullYear();
        var aniversarioJaPassou =
            hoje.getMonth() > nascimento.getMonth() ||
            (hoje.getMonth() === nascimento.getMonth() && hoje.getDate() >= nascimento.getDate());
        if (!aniversarioJaPassou) idade -= 1;
        return idade < 18;
    }

    if (campoNascimento && secaoResponsavel) {
        campoNascimento.addEventListener("change", function () {
            var menor = ehMenorDeIdade(campoNascimento.value);
            if (menor === null) return;
            secaoResponsavel.style.display = menor ? "" : "none";
            if (menor) secaoResponsavel.classList.add("is-open");
        });
    }

    // ── CEP → ViaCEP: preenche cidade/UF (e bairro/logradouro quando
    // vazios) assim que o colaborador digitar os 8 dígitos. Serviço
    // público, gratuito e sem chave — https://viacep.com.br.
    var cepInput = document.getElementById("id_endereco_cep");
    var cepWrap = document.getElementById("gc-cep-wrap");

    function marcarPreenchido(campo) {
        if (!campo) return;
        campo.classList.remove("gc-autofilled");
        // força reflow para reiniciar a animação mesmo em buscas repetidas
        void campo.offsetWidth;
        campo.classList.add("gc-autofilled");
    }

    if (cepInput) {
        cepInput.addEventListener("input", function () {
            var digitos = cepInput.value.replace(/\D/g, "").slice(0, 8);
            cepInput.value = digitos.length > 5 ? digitos.slice(0, 5) + "-" + digitos.slice(5) : digitos;

            var erroEl = document.getElementById("gc-cep-erro");
            if (erroEl) erroEl.textContent = "";

            if (digitos.length !== 8) return;

            if (cepWrap) cepWrap.classList.add("is-loading");

            fetch("https://viacep.com.br/ws/" + digitos + "/json/")
                .then(function (resposta) {
                    return resposta.json();
                })
                .then(function (dados) {
                    if (dados.erro) {
                        if (erroEl) erroEl.textContent = "CEP não encontrado — preencha o endereço manualmente.";
                        return;
                    }
                    var cidade = document.getElementById("id_endereco_cidade");
                    var uf = document.getElementById("id_endereco_estado");
                    var bairro = document.getElementById("id_endereco_bairro");
                    var logradouro = document.getElementById("id_endereco_logradouro");
                    var enderecoTag = document.getElementById("gc-endereco-tag");

                    // Sempre sobrescreve com o resultado do CEP atual — inclusive ao
                    // trocar de um CEP para outro já com os campos preenchidos. Só
                    // preserva o valor digitado quando a API não traz aquele dado
                    // para o CEP em questão (ex.: CEPs gerais, sem bairro/logradouro).
                    if (cidade) { cidade.value = dados.localidade || cidade.value; marcarPreenchido(cidade); }
                    if (uf) { uf.value = dados.uf || uf.value; marcarPreenchido(uf); }
                    if (bairro) { bairro.value = dados.bairro || bairro.value; marcarPreenchido(bairro); }
                    if (logradouro) { logradouro.value = dados.logradouro || logradouro.value; marcarPreenchido(logradouro); }
                    if (enderecoTag && cidade && cidade.value) enderecoTag.textContent = "completo";
                })
                .catch(function () {
                    if (erroEl) erroEl.textContent = "Não foi possível consultar o CEP agora — preencha manualmente.";
                })
                .finally(function () {
                    if (cepWrap) cepWrap.classList.remove("is-loading");
                });
        });
    }
})();
