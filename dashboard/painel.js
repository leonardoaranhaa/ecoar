/* ECOAR — painel do operador.
   Sem framework e sem etapa de build: o piloto precisa subir num servidor
   simples, e uma dependência de node no município é atrito que não paga.

   O token fica em sessionStorage, não em localStorage: fechou o navegador,
   perdeu a sessão. É um terminal compartilhado de repartição. */

const ARMAZEM = "ecoar.token";
const estado = {
  token: null,
  eventos: [],
  selecionado: null,
  filtro: "pendente_revisao",
  blobs: [],
};

const $ = (id) => document.getElementById(id);

/* O navegador não envia cabeçalho de autenticação em <img src> nem em
   <audio src>: a mídia voltaria 401. Por isso ela é buscada por fetch, com o
   token, e entregue ao elemento como blob. A alternativa seria assinar a URL,
   o que colocaria credencial no histórico do navegador e no log do servidor. */
async function carregarMidia(elemento) {
  const origem = elemento.dataset.src;
  if (!origem) return;
  try {
    const resposta = await fetch(origem, {
      headers: { Authorization: `Bearer ${estado.token}` },
    });
    if (!resposta.ok) throw new Error(`${resposta.status}`);
    const url = URL.createObjectURL(await resposta.blob());
    estado.blobs.push(url);
    elemento.src = url;
  } catch (erro) {
    elemento.replaceWith(
      Object.assign(document.createElement("p"), {
        className: "aviso-audio",
        textContent: `mídia indisponível (${erro.message})`,
      })
    );
  }
}

function liberarMidia() {
  estado.blobs.forEach((url) => URL.revokeObjectURL(url));
  estado.blobs = [];
}

async function api(caminho, opcoes = {}) {
  const resposta = await fetch(caminho, {
    ...opcoes,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${estado.token}`,
      ...(opcoes.headers || {}),
    },
  });
  if (resposta.status === 401) {
    sair();
    throw new Error("sessão expirada");
  }
  if (!resposta.ok) {
    const corpo = await resposta.json().catch(() => ({}));
    throw new Error(corpo.detail?.erro || corpo.detail || `erro ${resposta.status}`);
  }
  return resposta.json();
}

/* -- acesso ------------------------------------------------------- */

$("form-acesso").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  estado.token = $("token").value.trim();
  try {
    await api("/v1/eventos?limite=1");
    sessionStorage.setItem(ARMAZEM, estado.token);
    abrirPainel();
  } catch (erro) {
    $("erro-acesso").textContent = "Token não aceito.";
    $("erro-acesso").hidden = false;
    estado.token = null;
  }
});

function sair() {
  sessionStorage.removeItem(ARMAZEM);
  estado.token = null;
  $("painel").hidden = true;
  $("acesso").hidden = false;
}

$("sair").addEventListener("click", sair);
$("atualizar").addEventListener("click", () => carregar());
$("filtro-status").addEventListener("change", (evento) => {
  estado.filtro = evento.target.value;
  carregar();
});

function abrirPainel() {
  $("acesso").hidden = true;
  $("painel").hidden = false;
  carregar();
}

/* -- fila --------------------------------------------------------- */

async function carregar() {
  const consulta = estado.filtro ? `?status=${estado.filtro}&limite=200` : "?limite=200";
  const dados = await api(`/v1/eventos${consulta}`);
  estado.eventos = dados.eventos;
  desenharContadores(dados.contagem);
  desenharLista();
}

function desenharContadores(contagem) {
  const itens = [
    ["pendente", "Pendentes", contagem.pendente_revisao || 0],
    ["confirmado", "Confirmados", contagem.confirmado || 0],
    ["", "Rejeitados", contagem.rejeitado || 0],
  ];
  $("contadores").innerHTML = itens
    .map(
      ([classe, rotulo, valor]) =>
        `<div class="contador ${classe}"><span class="valor">${valor}</span>
         <span class="rotulo">${rotulo}</span></div>`
    )
    .join("");
}

function desenharLista() {
  const lista = $("lista");
  $("vazio").hidden = estado.eventos.length > 0;
  lista.innerHTML = estado.eventos
    .map((evento) => {
      const score = evento.score_alvo == null ? "—" : evento.score_alvo.toFixed(2);
      const angulo = evento.azimute_graus == null ? "—" : `${evento.azimute_graus.toFixed(0)}°`;
      return `
        <li class="item ${estado.selecionado === evento.id ? "selecionado" : ""}"
            data-id="${evento.id}">
          <div class="item-topo">
            <span class="item-classe">${texto(evento.classe) || "—"}</span>
            <span class="item-score">${score}</span>
          </div>
          <div class="item-meta">${quando(evento.capturado_em)} · ${evento.no_id} · ${angulo}</div>
          <span class="etiqueta ${evento.status}">${rotuloStatus(evento.status)}</span>
          <span class="etiqueta ${evento.acao}">${evento.acao}</span>
        </li>`;
    })
    .join("");

  lista.querySelectorAll(".item").forEach((elemento) => {
    elemento.addEventListener("click", () => abrirEvento(Number(elemento.dataset.id)));
  });
}

/* -- detalhe ------------------------------------------------------ */

async function abrirEvento(id) {
  liberarMidia();
  estado.selecionado = id;
  desenharLista();
  const evento = await api(`/v1/eventos/${id}`);
  desenharDetalhe(evento);
}

function desenharDetalhe(evento) {
  const manifesto = evento.manifesto || {};
  const decisao = manifesto.decisao || {};
  const classificacao = manifesto.classificacao || {};
  const pendente = evento.status === "pendente_revisao";

  $("detalhe").innerHTML = `
    <div class="detalhe-cabecalho">
      <div>
        <h2 class="detalhe-titulo">${texto(evento.classe) || "evento sem classe"}</h2>
        <div class="detalhe-sub">
          ${evento.evento_id} · ${evento.no_id} · ${quando(evento.capturado_em)}
        </div>
      </div>
      <span class="etiqueta ${evento.status}">${rotuloStatus(evento.status)}</span>
    </div>

    <div id="mensagem"></div>

    <div class="grade-medidas">
      ${medida("Score do alvo", numero(evento.score_alvo, 2), evento.versao_modelo)}
      ${medida(
        "Ângulo de chegada",
        evento.azimute_graus == null ? "—" : `${numero(evento.azimute_graus, 1)}°`,
        evento.margem_graus == null ? "" : `±${numero(evento.margem_graus, 1)}° · confiança ${numero(evento.confianca_doa, 2)}`
      )}
      ${medida(
        "Nível estimado",
        evento.spl_db == null ? "—" : `${numero(evento.spl_db, 1)} dB`,
        "sem valor legal — array MEMS",
        true
      )}
      ${medida(
        "Instrumento certificado",
        evento.instrumento_db == null ? "sem leitura" : `${numero(evento.instrumento_db, 1)} dB`,
        evento.instrumento_legal ? "valor legal" : "não aplicável em triagem"
      )}
      ${medida("Decisão do nó", evento.acao, evento.versao_politica)}
    </div>

    <div class="bloco">
      <h3>Áudio do evento</h3>
      <audio controls preload="none" data-src="/v1/eventos/${evento.id}/audio-audicao.wav"></audio>
      <p class="aviso-audio">
        Versão mono de 16 bits, só para audição. A evidência é o áudio de 4 canais
        dentro do pacote — é ele que o hash protege.
      </p>
    </div>

    ${imagensBloco(evento, manifesto)}

    ${
      classificacao.explicacao
        ? `<div class="bloco"><h3>Por que o classificador decidiu assim</h3>
           <div class="explicacao">${texto(classificacao.explicacao)}</div></div>`
        : ""
    }

    ${regrasBloco(decisao)}

    <div class="bloco">
      <h3>Integridade</h3>
      <p class="hash">${texto(evento.hash_manifesto)}</p>
    </div>

    ${
      pendente
        ? `<div class="decisao">
             <h3>Sua decisão</h3>
             <textarea id="observacao" placeholder="Observação (opcional) — fica registrada com o seu nome"></textarea>
             <div class="botoes-decisao">
               <button class="confirmar" id="btn-confirmar">Confirmar ocorrência</button>
               <button class="rejeitar" id="btn-rejeitar">Rejeitar</button>
             </div>
           </div>`
        : ""
    }

    ${historicoBloco(evento.revisoes)}
  `;

  document.querySelectorAll("[data-src]").forEach(carregarMidia);

  if (pendente) {
    $("btn-confirmar").addEventListener("click", () => decidir(evento.id, "confirmar"));
    $("btn-rejeitar").addEventListener("click", () => decidir(evento.id, "rejeitar"));
  }
}

function imagensBloco(evento, manifesto) {
  const imagens = manifesto.imagens || [];
  if (!imagens.length) {
    return `<div class="bloco"><h3>Imagens</h3>
      <p class="dica">Sem imagem: a câmera não foi acionada — o evento ficou marcado
      como ambíguo e entrou na fila mesmo assim.</p></div>`;
  }
  const figuras = imagens
    .map((imagem) => {
      const nome = (imagem.arquivo || "").replace("midia/", "");
      const simulada = imagem.simulada ? " · CAPTURA SIMULADA" : "";
      return `<figure>
        <img data-src="/v1/eventos/${evento.id}/midia/${nome}" alt="${texto(imagem.tipo)}">
        <figcaption>${texto(imagem.tipo)} · ${texto(imagem.resolucao)}${simulada}</figcaption>
      </figure>`;
    })
    .join("");
  return `<div class="bloco"><h3>Imagens</h3><div class="imagens">${figuras}</div></div>`;
}

function regrasBloco(decisao) {
  const regras = decisao.regras || [];
  if (!regras.length) return "";
  const itens = regras
    .map(
      (regra) => `<li>
        <span class="${regra.atendida ? "marca-ok" : "marca-nao"}">${regra.atendida ? "✓" : "✗"}</span>
        <span class="nome">${texto(regra.nome)}</span>
        <span class="medido">${texto(regra.medido)}</span>
      </li>`
    )
    .join("");
  return `<div class="bloco">
    <h3>Regras avaliadas pelo nó — ${texto(decisao.versao_politica)}</h3>
    <ul class="regras">${itens}</ul>
  </div>`;
}

function historicoBloco(revisoes) {
  if (!revisoes || !revisoes.length) return "";
  const itens = revisoes
    .map(
      (revisao) => `<li>
        <div class="quem">${texto(revisao.operador)} · ${texto(revisao.decidido_em)}</div>
        <div>${texto(revisao.decisao)}${revisao.observacao ? " — " + texto(revisao.observacao) : ""}</div>
      </li>`
    )
    .join("");
  return `<div class="bloco"><h3>Histórico de revisão</h3><ul class="historico">${itens}</ul></div>`;
}

async function decidir(id, decisao) {
  const observacao = $("observacao")?.value || "";
  try {
    await api(`/v1/eventos/${id}/revisao`, {
      method: "POST",
      body: JSON.stringify({ decisao, observacao }),
    });
    await carregar();
    await abrirEvento(id);
    mensagem(`Evento ${decisao === "confirmar" ? "confirmado" : "rejeitado"}.`, "ok");
  } catch (erro) {
    mensagem(erro.message, "falha");
  }
}

function mensagem(texto_, tipo) {
  const alvo = $("mensagem");
  if (alvo) alvo.innerHTML = `<div class="mensagem ${tipo}">${texto(texto_)}</div>`;
}

/* -- utilidades --------------------------------------------------- */

function medida(rotulo, valor, nota = "", alerta = false) {
  return `<div class="medida">
    <div class="rotulo">${rotulo}</div>
    <div class="valor">${texto(valor)}</div>
    ${nota ? `<div class="nota ${alerta ? "alerta" : ""}">${texto(nota)}</div>` : ""}
  </div>`;
}

function numero(valor, casas) {
  return valor == null ? "—" : Number(valor).toFixed(casas);
}

function quando(iso) {
  if (!iso) return "—";
  const data = new Date(iso);
  return Number.isNaN(data.getTime())
    ? iso
    : data.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

function rotuloStatus(status) {
  return (
    {
      pendente_revisao: "pendente",
      confirmado: "confirmado",
      confirmado_multa: "confirmado (multa)",
      rejeitado: "rejeitado",
    }[status] || status
  );
}

/* Escapa tudo que vem da API antes de entrar no HTML: os campos de texto
   passam pelo nó de campo e por observação de operador, e nenhum dos dois é
   lugar de confiar cegamente. */
function texto(valor) {
  if (valor == null) return "";
  return String(valor).replace(
    /[&<>"']/g,
    (caractere) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[caractere])
  );
}

/* -- início ------------------------------------------------------- */

const salvo = sessionStorage.getItem(ARMAZEM);
if (salvo) {
  estado.token = salvo;
  api("/v1/eventos?limite=1")
    .then(abrirPainel)
    .catch(() => sair());
}
