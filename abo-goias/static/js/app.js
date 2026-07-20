// JS global do painel ABO Goiás — modal de confirmação genérico e dispensa
// de mensagens (toast). Vanilla, sem dependências, carregado em toda página
// que estende templates/base.html.

(function () {
    var dialog = document.getElementById("confirm-dialog");
    if (!dialog) return;

    var titleEl = dialog.querySelector('[data-role="title"]');
    var messageEl = dialog.querySelector('[data-role="message"]');
    var acceptEl = dialog.querySelector('[data-role="accept"]');

    document.addEventListener("click", function (event) {
        var trigger = event.target.closest("[data-confirm]");
        if (!trigger) return;

        event.preventDefault();

        titleEl.textContent = trigger.dataset.confirmTitle || "Confirmar ação";
        messageEl.textContent = trigger.dataset.confirm;
        acceptEl.textContent = trigger.dataset.confirmLabel || "Confirmar";
        acceptEl.classList.toggle("danger-button", trigger.dataset.confirmDanger === "true");

        acceptEl.onclick = function () {
            dialog.close();
            var form = trigger.closest("form");
            if (form) {
                form.requestSubmit(trigger);
                return;
            }
            // Sem form ancestral: o gatilho é um link de navegação simples
            // (ex.: "Voltar à lista" avisando sobre um processo em andamento).
            if (trigger.tagName === "A" && trigger.href) {
                window.location.href = trigger.href;
            }
        };

        dialog.showModal();
    });

    // Fecha ao clicar fora do conteúdo (no próprio elemento <dialog>, que
    // ocupa a área do backdrop fora do <form> interno).
    dialog.addEventListener("click", function (event) {
        if (event.target === dialog) dialog.close();
    });
})();

(function () {
    document.addEventListener("click", function (event) {
        document.querySelectorAll(".user-menu-dropdown[open], .side-link-group[open]").forEach(function (menu) {
            if (!menu.contains(event.target)) menu.removeAttribute("open");
        });
    });
})();

(function () {
    function removerMensagem(mensagem) {
        if (mensagem) mensagem.remove();
    }

    document.addEventListener("click", function (event) {
        var botao = event.target.closest(".message-dismiss");
        if (!botao) return;
        removerMensagem(botao.closest(".message"));
    });

    document.querySelectorAll(".messages-banner .message").forEach(function (mensagem) {
        mensagem.addEventListener("animationend", function (event) {
            if (event.animationName === "message-dismiss") removerMensagem(mensagem);
        });
    });
})();

(function () {
    // Feedback de carregamento em formulários que disparam sincronizações
    // externas (Eduq, Dental Office) — a resposta é um redirect, então o
    // estado de loading fica visível até a próxima página carregar.
    document.addEventListener("submit", function (event) {
        var form = event.target.closest(".sync-form");
        if (!form) return;

        var botao = form.querySelector('button[type="submit"]');
        if (!botao || botao.disabled) return;

        botao.dataset.originalLabel = botao.textContent;
        botao.textContent = "Sincronizando…";
        botao.disabled = true;
        botao.classList.add("is-loading");
    });
})();

(function () {
    // Campos de busca com seleção (autocomplete) montados por
    // partials/_ac_field.html. Ao clicar num resultado, preenche o campo oculto
    // do formulário e troca a busca por um "chip" do item escolhido; "Trocar"
    // desfaz a seleção. Genérico: funciona para vários campos na mesma tela.
    //
    // Dois comportamentos opcionais, por bloco:
    //   data-ac-materializar — a busca mistura base local e API externa; itens
    //                          sem pk são gravados no clique (ver materializar).
    //   data-ac-navegar      — escolher o item recarrega a tela (navega para
    //                          "<valor><pk>") em vez de preencher o formulário.
    function bloco(el) {
        return el.closest("[data-ac]");
    }

    function csrf() {
        var campo = document.querySelector("[name=csrfmiddlewaretoken]");
        return campo ? campo.value : "";
    }

    function confirmar(b, pk, nome) {
        b.querySelector("[data-ac-hidden]").value = pk;
        b.querySelector("[data-ac-nome]").textContent = nome;
        b.querySelector("[data-ac-selecionado]").hidden = false;
        b.querySelector("[data-ac-busca]").hidden = true;
        var lista = b.querySelector(".search-results-wrap");
        if (lista) lista.innerHTML = "";
    }

    // A busca mostra numa lista só quem já está no banco e quem veio da API.
    // Os que já existem têm data-id e são escolhidos na hora; os que vieram da
    // API ainda não têm pk — só então o registro é gravado, um por clique.
    async function materializar(b, resultado) {
        var url = b.dataset.acMaterializar;
        var corpo = new URLSearchParams({
            id_dental: resultado.dataset.idDental,
            nome: resultado.dataset.nome,
        });
        var resposta = await fetch(url, {
            method: "POST",
            headers: { "X-CSRFToken": csrf() },
            body: corpo,
        });
        if (!resposta.ok) {
            var erro = await resposta.json().catch(function () { return {}; });
            throw new Error(erro.erro || "Não foi possível concluir a seleção agora.");
        }
        return resposta.json();
    }

    document.addEventListener("click", function (event) {
        var resultado = event.target.closest(".ac-result");
        if (resultado) {
            var b = bloco(resultado);
            if (!b) return;

            // Fluxos em que escolher o aluno recarrega a tela (ex.: registrar
            // saída, que precisa listar os pacotes pendentes dele).
            if (b.dataset.acNavegar && resultado.dataset.id) {
                window.location = b.dataset.acNavegar + encodeURIComponent(resultado.dataset.id);
                return;
            }

            if (resultado.dataset.id) {
                confirmar(b, resultado.dataset.id, resultado.dataset.nome);
                return;
            }

            // Item sem pk só pode ser gravado se o bloco souber para onde
            // mandar; sem isso a busca é apenas local e não deveria chegar aqui.
            if (!b.dataset.acMaterializar) return;

            resultado.disabled = true;
            resultado.classList.add("is-materializando");
            materializar(b, resultado)
                .then(function (dados) {
                    confirmar(b, dados.pk, dados.nome);
                })
                .catch(function (erro) {
                    var lista = b.querySelector(".search-results-wrap");
                    if (lista) {
                        var aviso = document.createElement("p");
                        aviso.className = "ac-aviso ac-aviso--erro";
                        aviso.textContent = erro.message;
                        lista.prepend(aviso);
                    }
                })
                .finally(function () {
                    resultado.disabled = false;
                    resultado.classList.remove("is-materializando");
                });
            return;
        }

        var trocar = event.target.closest("[data-ac-trocar]");
        if (trocar) {
            var alvo = bloco(trocar);
            if (!alvo) return;
            alvo.querySelector("[data-ac-hidden]").value = "";
            alvo.querySelector("[data-ac-selecionado]").hidden = true;
            var busca = alvo.querySelector("[data-ac-busca]");
            busca.hidden = false;
            var campo = busca.querySelector('input[type="search"]');
            if (campo) {
                campo.value = "";
                campo.focus();
            }
        }
    });

    // Enter num campo de busca não deve submeter o formulário do registro.
    document.addEventListener("keydown", function (event) {
        if (
            event.key === "Enter" &&
            event.target.matches('[data-ac] input[type="search"]')
        ) {
            event.preventDefault();
        }
    });
})();

(function () {
    // Feedback de carregamento nas buscas que recarregam a página: filtros de
    // listagem (.filter-bar) e importação pontual do Dental Office
    // (.js-loading-submit). Mesmo mecanismo do .sync-form, mas mantém o rótulo
    // do botão — só adiciona o spinner e desabilita até a próxima página.
    document.addEventListener("submit", function (event) {
        var form = event.target.closest(".filter-bar, .js-loading-submit");
        if (!form) return;

        var botao = form.querySelector('button[type="submit"]');
        if (!botao || botao.disabled) return;

        botao.disabled = true;
        botao.classList.add("is-loading");
    });
})();
