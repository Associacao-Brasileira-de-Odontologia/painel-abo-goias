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
            if (form) form.requestSubmit(trigger);
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
        document.querySelectorAll(".user-menu-dropdown[open]").forEach(function (menu) {
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
    function bloco(el) {
        return el.closest("[data-ac]");
    }

    document.addEventListener("click", function (event) {
        var resultado = event.target.closest(".ac-result");
        if (resultado) {
            var b = bloco(resultado);
            if (!b) return;
            b.querySelector("[data-ac-hidden]").value = resultado.dataset.id;
            b.querySelector("[data-ac-nome]").textContent = resultado.dataset.nome;
            b.querySelector("[data-ac-selecionado]").hidden = false;
            b.querySelector("[data-ac-busca]").hidden = true;
            var lista = b.querySelector(".search-results-wrap");
            if (lista) lista.innerHTML = "";
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
