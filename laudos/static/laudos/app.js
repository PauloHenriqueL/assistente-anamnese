(function () {
  const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value;

  const SEM_CONEXAO =
    "Não conseguimos falar com o servidor. Verifique a internet e tente de novo; o seu texto continua aqui.";
  // Segundos de espera antes de cada nova tentativa quando a conexão cai ou o servidor está reiniciando.
  const ESPERAS = [2, 4, 8, 15];
  const esperar = (segundos) => new Promise((pronto) => setTimeout(pronto, segundos * 1000));

  // Recado no canto da tela, no lugar do alert(): não trava a página e some sozinho ou no X.
  function recado(texto, tipo = "erro") {
    let caixa = document.getElementById("recado");
    if (!caixa) {
      caixa = document.createElement("div");
      caixa.id = "recado";
      caixa.className = "recado";
      caixa.setAttribute("role", "alert");
      caixa.innerHTML = '<p></p><button type="button" class="fechar" aria-label="Fechar">×</button>';
      caixa.querySelector(".fechar").addEventListener("click", () => caixa.remove());
      document.body.appendChild(caixa);
    }
    caixa.dataset.tipo = tipo;
    caixa.querySelector("p").textContent = texto;
    clearTimeout(caixa.prazo);
    caixa.prazo = setTimeout(() => caixa.remove(), 12000);
  }

  // POST com novas tentativas. Falha de rede ou servidor reiniciando (502, 503, 504) espera e tenta de novo;
  // o servidor ignora o reenvio de algo que já tinha chegado. `aoTentarDeNovo` avisa a tela da espera.
  async function enviar(url, dados, aoTentarDeNovo) {
    for (let tentativa = 0; ; tentativa++) {
      let resposta;
      try {
        resposta = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
          body: JSON.stringify(dados || {}),
        });
      } catch (e) {
        resposta = null;
      }
      const passageiro = !resposta || [502, 503, 504].includes(resposta.status);
      if (passageiro && tentativa < ESPERAS.length) {
        if (aoTentarDeNovo) aoTentarDeNovo();
        await esperar(ESPERAS[tentativa]);
        continue;
      }
      if (!resposta) throw new Error(SEM_CONEXAO);
      let corpo = {};
      try { corpo = await resposta.json(); } catch (e) { corpo = { ok: false }; }
      if (resposta.redirected || (resposta.status === 403 && !corpo.erro)) {
        // Redirecionou para a tela de entrada, ou o token do formulário venceu.
        throw new Error("A sua sessão expirou. Recarregue a página e entre de novo; o seu texto continua aqui.");
      }
      if (!resposta.ok || !corpo.ok) {
        const erro = new Error(corpo.erro || (passageiro ? SEM_CONEXAO : "Algo deu errado. Tente de novo."));
        erro.status = resposta.status;
        throw erro;
      }
      return corpo;
    }
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

    // Rascunho da mensagem guardado neste navegador: uma queda ou um recarregar não apaga o que ela escreveu.
    const chaveRascunho = "rascunho:" + laudo.dataset.urlMensagem;
    const rascunho = {
      guardar() { try { localStorage.setItem(chaveRascunho, campo.value); } catch (e) {} },
      limpar() { try { localStorage.removeItem(chaveRascunho); } catch (e) {} },
    };
    try {
      const salvo = localStorage.getItem(chaveRascunho);
      if (salvo && !campo.value) campo.value = salvo;
    } catch (e) {}
    campo.addEventListener("input", rascunho.guardar);

    // A IA responde em segundo plano: a tela pergunta o andamento até a resposta ficar pronta.
    let intervalo = null;
    function aguardar() {
      botao.disabled = true;
      campo.disabled = true;
      const textoBase = "Estamos construindo o texto. Pode levar alguns minutos";
      let pontos = 0;
      estado.classList.remove("apagado");
      estado.classList.add("aguardando");
      estado.textContent = textoBase;
      clearInterval(intervalo);
      intervalo = setInterval(() => {
        pontos = (pontos + 1) % 4;
        const base = estado.dataset.reconectando ? "Reconectando ao servidor. O texto segue sendo escrito" : textoBase;
        estado.textContent = base + ".".repeat(pontos);
      }, 600);
      let falhas = 0;
      const consultar = async () => {
        try {
          const resposta = await fetch(laudo.dataset.urlAndamento, { cache: "no-store" });
          if (!resposta.ok) throw new Error(resposta.status);
          const corpo = await resposta.json();
          if (!corpo.pendente) {
            clearInterval(intervalo);
            rascunho.limpar();
            window.location.reload();
            return;
          }
          falhas = 0;
        } catch (e) {
          // Falha de rede ou servidor reiniciando: a geração continua (ou é retomada) do lado do servidor.
          falhas++;
        }
        if (falhas >= 3) estado.dataset.reconectando = "1";
        else delete estado.dataset.reconectando;
        setTimeout(consultar, falhas ? Math.min(4000 * falhas, 20000) : 4000);
      };
      setTimeout(consultar, 4000);
    }

    if (laudo.dataset.pendente) aguardar();

    // Modelo e modo de pensar escolhidos por ela, lembrados neste navegador.
    const modelo = document.getElementById("modelo");
    const pensar = document.getElementById("pensar");
    try {
      const salvo = JSON.parse(localStorage.getItem("escolha-ia") || "{}");
      if (salvo.modelo && [...modelo.options].some((o) => o.value === salvo.modelo)) modelo.value = salvo.modelo;
      if (typeof salvo.pensar === "boolean") pensar.checked = salvo.pensar;
    } catch (e) {}
    const lembrar = () => {
      try { localStorage.setItem("escolha-ia", JSON.stringify({ modelo: modelo.value, pensar: pensar.checked })); } catch (e) {}
    };
    modelo.addEventListener("change", lembrar);
    pensar.addEventListener("change", lembrar);

    caixa.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      if (botao.disabled) return;
      botao.disabled = true;  // antes do envio: um clique duplo não manda duas vezes
      rascunho.guardar();
      const textoOriginal = estado.textContent;
      try {
        await enviar(
          laudo.dataset.urlMensagem,
          { texto: campo.value, modelo: modelo.value, pensar: pensar.checked },
          () => { estado.classList.add("aguardando"); estado.textContent = "Sem conexão. Tentando de novo..."; },
        );
        rascunho.limpar();
        aguardar();
      } catch (erro) {
        if (erro.status === 409) {
          // Já há uma geração em curso (talvez esta mesma, se a primeira tentativa chegou): só acompanhar.
          aguardar();
          return;
        }
        estado.classList.remove("aguardando");
        estado.textContent = textoOriginal;
        botao.disabled = false;
        recado(erro.message);
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
        form.texto.value = cartao.querySelector(".texto").innerText.trim();
        if ((await abrir(dialogoEditar)) !== "ok") return;
        await enviar(`/versoes/${id}/editar/`, { texto: form.texto.value });
      }
      window.location.reload();
    } catch (erro) {
      recado(erro.message);
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
      setTimeout(() => (rotulo.textContent = copiar.dataset.rotulo || "Copiar"), 2000);
    });
  }
})();
