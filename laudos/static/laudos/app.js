(function () {
  const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value;

  async function enviar(url, dados) {
    const resposta = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(dados || {}),
    });
    let corpo = {};
    try { corpo = await resposta.json(); } catch (e) { corpo = { ok: false, erro: "Resposta inválida do servidor." }; }
    if (!resposta.ok || !corpo.ok) throw new Error(corpo.erro || "Algo deu errado.");
    return corpo;
  }

  // Conversa
  const laudo = document.querySelector(".laudo");
  const caixa = document.getElementById("caixa");
  if (laudo && caixa) {
    const campo = document.getElementById("texto");
    const estado = document.getElementById("estado");
    const botao = caixa.querySelector("button[type=submit]");
    const lista = document.getElementById("mensagens");
    lista.scrollTop = lista.scrollHeight;

    caixa.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      botao.disabled = true;
      campo.disabled = true;
      estado.textContent = "A IA está escrevendo e conferindo com as anotações. Pode levar um ou dois minutos.";
      try {
        await enviar(laudo.dataset.urlMensagem, { texto: campo.value });
        window.location.reload();
      } catch (erro) {
        estado.textContent = "";
        alert(erro.message);
        window.location.reload();
      }
    });

    campo.addEventListener("keydown", (evento) => {
      if (evento.key === "Enter" && (evento.ctrlKey || evento.metaKey)) caixa.requestSubmit();
    });
  }

  // Like, deslike e edição
  const dialogoDeslike = document.getElementById("dialogo-deslike");
  const dialogoEditar = document.getElementById("dialogo-editar");

  function abrir(dialogo) {
    return new Promise((resolver) => {
      dialogo.addEventListener("close", () => resolver(dialogo.returnValue), { once: true });
      dialogo.showModal();
    });
  }

  document.addEventListener("click", async (evento) => {
    const botao = evento.target.closest("button[data-acao]");
    if (!botao) return;
    const cartao = botao.closest("[data-versao]");
    const id = cartao.dataset.versao;
    try {
      if (botao.dataset.acao === "like") {
        await enviar(`/versoes/${id}/avaliar/`, { tipo: "like" });
      } else if (botao.dataset.acao === "deslike") {
        const form = dialogoDeslike.querySelector("form");
        form.reset();
        if ((await abrir(dialogoDeslike)) !== "ok") return;
        const motivos = [...form.querySelectorAll("[name=motivo]:checked")].map((c) => c.value);
        await enviar(`/versoes/${id}/avaliar/`, { tipo: "deslike", motivos, comentario: form.comentario.value });
      } else if (botao.dataset.acao === "editar") {
        const form = dialogoEditar.querySelector("form");
        form.texto.value = cartao.querySelector(".texto").textContent.trim();
        if ((await abrir(dialogoEditar)) !== "ok") return;
        await enviar(`/versoes/${id}/editar/`, { texto: form.texto.value });
      }
      window.location.reload();
    } catch (erro) {
      alert(erro.message);
    }
  });

  // Tema claro e escuro, lembrado neste navegador
  const tema = document.getElementById("alternar-tema");
  if (tema) {
    tema.addEventListener("click", () => {
      const novo = document.documentElement.dataset.tema === "escuro" ? "claro" : "escuro";
      document.documentElement.dataset.tema = novo;
      try { localStorage.setItem("tema", novo); } catch (e) {}
    });
  }

  // Copiar a 4.2 inteira
  const copiar = document.getElementById("copiar");
  if (copiar) {
    copiar.addEventListener("click", async () => {
      const texto = await (await fetch(copiar.dataset.url)).text();
      await navigator.clipboard.writeText(texto);
      const rotulo = copiar.querySelector("span") || copiar;
      rotulo.textContent = "Copiado";
      setTimeout(() => (rotulo.textContent = "Copiar 4.2"), 2000);
    });
  }
})();
