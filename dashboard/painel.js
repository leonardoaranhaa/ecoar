/* ECOAR — plataforma de gestão do operador.
   Sem framework e sem etapa de build: o piloto precisa subir num servidor
   simples, e uma dependência de node no município é atrito que não paga.

   O token fica em sessionStorage, não em localStorage: fechou o navegador,
   perdeu a sessão. É um terminal compartilhado de repartição. */

const ARMAZEM = "ecoar.token";
const estado = {
  token: null,
  eu: null,
  tela: "priorizacao",
  contagem: {},
  selecionado: null,
  filtroHistorico: "",
  blobs: [],
};

const $ = (id) => document.getElementById(id);

/* Telas. `admin: true` só aparece para o perfil admin (RBAC no cliente; o
   backend recusa de novo, que é onde a garantia mora). */
const TELAS = [
  { id: "priorizacao", nome: "Priorização", render: telaPriorizacao },
  { id: "revisao", nome: "Fila de revisão", render: telaRevisao, badge: "pendente_revisao" },
  { id: "nos", nome: "Nós", render: telaNos },
  { id: "violacoes", nome: "Violações", render: telaViolacoes },
  { id: "historico", nome: "Histórico", render: telaHistorico },
  { id: "metricas", nome: "Métricas", render: telaMetricas },
  { id: "modelo", nome: "Modelo", render: telaModelo, admin: true },
  { id: "auditoria", nome: "Auditoria", render: telaAuditoria, admin: true },
  { id: "config", nome: "Configurações", render: telaConfig },
];

/* -- rede --------------------------------------------------------- */

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

/* <img>/<audio> não enviam cabeçalho de autenticação: a mídia voltaria 401.
   Busca por fetch com o token e entrega como blob. Assinar a URL colocaria
   credencial no histórico do navegador e no log do servidor. */
async function carregarMidia(elemento) {
  const origem = elemento.dataset.src;
  if (!origem) return;
  try {
    const resposta = await fetch(origem, { headers: { Authorization: `Bearer ${estado.token}` } });
    if (!resposta.ok) throw new Error(`${resposta.status}`);
    const url = URL.createObjectURL(await resposta.blob());
    estado.blobs.push(url);
    elemento.src = url;
  } catch (erro) {
    elemento.replaceWith(Object.assign(document.createElement("p"), {
      className: "aviso-audio", textContent: `mídia indisponível (${erro.message})`,
    }));
  }
}
function liberarMidia() {
  estado.blobs.forEach((url) => URL.revokeObjectURL(url));
  estado.blobs = [];
}

/* -- acesso ------------------------------------------------------- */

$("form-acesso").addEventListener("submit", async (evento) => {
  evento.preventDefault();
  estado.token = $("token").value.trim();
  try {
    estado.eu = await api("/v1/eu");
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
  estado.eu = null;
  $("painel").hidden = true;
  $("acesso").hidden = false;
}
$("sair").addEventListener("click", sair);

function abrirPainel() {
  $("acesso").hidden = true;
  $("painel").hidden = false;
  $("quem").textContent = `${estado.eu.nome} · ${estado.eu.perfil}`;
  desenharNavegacao();
  irPara("priorizacao");
}

/* -- navegação ---------------------------------------------------- */

function telasVisiveis() {
  return TELAS.filter((tela) => !tela.admin || estado.eu.admin);
}

function desenharNavegacao() {
  $("navegacao").innerHTML = telasVisiveis()
    .map(
      (tela) => `<button class="item-nav ${tela.admin ? "so-admin" : ""}" data-tela="${tela.id}">
        <span>${tela.nome}</span>
        ${tela.badge ? `<span class="contagem" data-badge="${tela.badge}" hidden></span>` : ""}
      </button>`
    )
    .join("");
  $("navegacao").querySelectorAll(".item-nav").forEach((botao) => {
    botao.addEventListener("click", () => irPara(botao.dataset.tela));
  });
}

async function irPara(id) {
  estado.tela = id;
  liberarMidia();
  $("navegacao").querySelectorAll(".item-nav").forEach((b) => {
    b.classList.toggle("ativo", b.dataset.tela === id);
  });
  const tela = TELAS.find((t) => t.id === id);
  $("conteudo").innerHTML = `<div class="placeholder">Carregando ${tela.nome.toLowerCase()}…</div>`;
  try {
    await tela.render();
  } catch (erro) {
    $("conteudo").innerHTML = `<div class="mensagem falha">${texto(erro.message)}</div>`;
  }
  atualizarBadges();
}

async function atualizarBadges() {
  try {
    const dados = await api("/v1/eventos?limite=1");
    estado.contagem = dados.contagem;
    document.querySelectorAll("[data-badge]").forEach((elemento) => {
      const valor = estado.contagem[elemento.dataset.badge] || 0;
      elemento.textContent = valor;
      elemento.hidden = valor === 0;
    });
  } catch { /* silencioso: badge é secundário */ }
}

/* -- tela: priorização (home) ------------------------------------- */

const DIAS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];

async function telaPriorizacao() {
  const dados = await api("/v1/priorizacao");
  const grade = {};
  let maximo = 0;
  dados.hora_dia.forEach((c) => {
    grade[`${c.dia}-${c.hora}`] = c.total;
    maximo = Math.max(maximo, c.total);
  });

  const linhas = [];
  for (let hora = 0; hora < 24; hora++) {
    const celulas = DIAS.map((_, dia) => {
      const total = grade[`${dia}-${hora}`] || 0;
      const i = maximo ? total / maximo : 0;
      const fundo = total ? `background: rgba(245,166,35,${(0.12 + 0.88 * i).toFixed(2)}); color:#14181b` : "";
      return `<td style="${fundo}" title="${DIAS[dia]} ${hora}h: ${total}">${total || ""}</td>`;
    }).join("");
    linhas.push(`<tr><td class="hora">${String(hora).padStart(2, "0")}h</td>${celulas}</tr>`);
  }

  const ranking = dados.por_no.length
    ? dados.por_no
        .map(
          (no) => `<tr>
            <td>${texto(no.no_id)}</td>
            <td>${texto(no.descricao || "—")}</td>
            <td class="num">${no.confirmados}</td>
            <td><span class="barra-mini" style="width:${maxBarra(no.confirmados, dados.por_no)}px"></span></td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="4" class="vazio">Nenhum evento confirmado ainda. O mapa
        se preenche conforme o operador confirma ocorrências.</td></tr>`;

  $("conteudo").innerHTML = `
    <div class="topo-tela">
      <div><h1>Priorização de fiscalização</h1>
        <div class="sub">Onde e quando o problema é pior — para direcionar a blitz</div></div>
      <div class="acoes-topo">
        <button class="secundario" id="btn-relatorio">Exportar relatório</button>
      </div>
    </div>
    <div class="aviso-tela">${texto(dados.observacao)}</div>

    <div class="bloco">
      <h3>Quando — eventos confirmados por dia da semana × hora</h3>
      <table class="heatmap">
        <tr><th></th>${DIAS.map((d) => `<th>${d}</th>`).join("")}</tr>
        ${linhas.join("")}
      </table>
      <div class="legenda-heat"><span>menos</span><span class="escala"></span><span>mais</span></div>
    </div>

    <div class="bloco">
      <h3>Onde — pontos por eventos confirmados</h3>
      <table class="tabela">
        <tr><th>Nó</th><th>Local</th><th class="num">Confirmados</th><th></th></tr>
        ${ranking}
      </table>
    </div>`;

  $("btn-relatorio").addEventListener("click", exportarRelatorio);
}

function maxBarra(valor, lista) {
  const max = Math.max(...lista.map((n) => n.confirmados), 1);
  return Math.round((valor / max) * 120);
}

async function exportarRelatorio() {
  /* O relatório é HTML pronto para imprimir. Busca com token, abre numa aba e
     dispara a impressão do navegador — que o operador salva como PDF. */
  try {
    const resposta = await fetch("/v1/priorizacao/relatorio", {
      headers: { Authorization: `Bearer ${estado.token}` },
    });
    const html = await resposta.text();
    const aba = window.open("", "_blank");
    aba.document.write(html);
    aba.document.close();
    aba.focus();
    setTimeout(() => aba.print(), 400);
  } catch (erro) {
    alert("Falha ao gerar o relatório: " + erro.message);
  }
}

/* -- tela: fila de revisão ---------------------------------------- */

async function telaRevisao() {
  const dados = await api("/v1/eventos?status=pendente_revisao&limite=200");
  estado.eventos = dados.eventos;
  $("conteudo").innerHTML = `
    <div class="topo-tela"><div><h1>Fila de revisão</h1>
      <div class="sub">Todo evento passa por decisão humana antes de virar dado de priorização</div></div></div>
    <div class="revisao">
      <div class="coluna-fila"><ul class="lista-eventos" id="lista"></ul>
        <p class="vazio" id="vazio" hidden>Fila vazia. Nada pendente.</p></div>
      <div id="detalhe"><div class="placeholder"><p>Selecione um evento na fila.</p>
        <p class="dica">Nenhum evento é contado sozinho: a priorização se alimenta
        do que você confirmar aqui.</p></div></div>
    </div>`;
  desenharListaRevisao();
}

function desenharListaRevisao() {
  const lista = $("lista");
  $("vazio").hidden = estado.eventos.length > 0;
  lista.innerHTML = estado.eventos
    .map((evento) => {
      const score = evento.score_alvo == null ? "—" : evento.score_alvo.toFixed(2);
      const ang = evento.azimute_graus == null ? "—" : `${evento.azimute_graus.toFixed(0)}°`;
      return `<li class="item ${estado.selecionado === evento.id ? "selecionado" : ""}" data-id="${evento.id}">
        <div class="item-topo"><span class="item-classe">${texto(evento.classe) || "—"}</span>
          <span class="item-score">${score}</span></div>
        <div class="item-meta">${quando(evento.capturado_em)} · ${evento.no_id} · ${ang}</div>
        <span class="etiqueta ${evento.acao}">${evento.acao}</span>
      </li>`;
    })
    .join("");
  lista.querySelectorAll(".item").forEach((el) => {
    el.addEventListener("click", () => abrirEvento(Number(el.dataset.id)));
  });
}

async function abrirEvento(id) {
  liberarMidia();
  estado.selecionado = id;
  desenharListaRevisao();
  const evento = await api(`/v1/eventos/${id}`);
  desenharDetalhe(evento);
}

function desenharDetalhe(evento) {
  const manifesto = evento.manifesto || {};
  const decisao = manifesto.decisao || {};
  const classificacao = manifesto.classificacao || {};
  const pendente = evento.status === "pendente_revisao";

  $("detalhe").innerHTML = `
    <div class="topo-tela"><div><h1 style="font-size:19px">${texto(evento.classe) || "evento"}</h1>
      <div class="sub">${evento.evento_id} · ${evento.no_id} · ${quando(evento.capturado_em)}</div></div>
      <span class="etiqueta ${evento.status}">${rotuloStatus(evento.status)}</span></div>
    <div id="mensagem"></div>
    <div class="grade-medidas">
      ${medida("Score do alvo", numero(evento.score_alvo, 2), evento.versao_modelo)}
      ${medida("Ângulo", evento.azimute_graus == null ? "—" : `${numero(evento.azimute_graus, 1)}°`,
        evento.margem_graus == null ? "" : `±${numero(evento.margem_graus, 1)}° · conf. ${numero(evento.confianca_doa, 2)}`)}
      ${medida("Nível estimado", evento.spl_db == null ? "—" : `${numero(evento.spl_db, 1)} dB`, "sem valor legal — array MEMS", true)}
      ${medida("Decisão do nó", evento.acao, evento.versao_politica)}
    </div>
    <div class="bloco"><h3>Áudio do evento</h3>
      <audio controls preload="none" data-src="/v1/eventos/${evento.id}/audio-audicao.wav"></audio>
      <p class="aviso-audio">Mono 16 bits, só para audição. A evidência é o áudio de 4 canais dentro do pacote.</p></div>
    ${imagensBloco(evento, manifesto)}
    ${classificacao.explicacao ? `<div class="bloco"><h3>Por que o classificador decidiu assim</h3>
      <div class="explicacao">${texto(classificacao.explicacao)}</div></div>` : ""}
    ${regrasBloco(decisao)}
    <div class="bloco"><h3>Integridade</h3><p class="hash">${texto(evento.hash_manifesto)}</p></div>
    ${pendente ? `<div class="decisao"><h3>Sua decisão</h3>
      <textarea id="observacao" placeholder="Observação (opcional) — fica registrada com o seu nome"></textarea>
      <div class="botoes-decisao">
        <button class="confirmar" id="btn-confirmar">Confirmar ocorrência</button>
        <button class="rejeitar" id="btn-rejeitar">Rejeitar</button>
      </div></div>` : ""}
    ${historicoBloco(evento.revisoes)}`;

  document.querySelectorAll("[data-src]").forEach(carregarMidia);
  if (pendente) {
    $("btn-confirmar").addEventListener("click", () => decidir(evento.id, "confirmar"));
    $("btn-rejeitar").addEventListener("click", () => decidir(evento.id, "rejeitar"));
  }
}

function imagensBloco(evento, manifesto) {
  const imagens = manifesto.imagens || [];
  if (!imagens.length) {
    return `<div class="bloco"><h3>Imagens</h3><p class="dica">Sem imagem: a câmera
      não foi acionada — o evento ficou ambíguo e entrou na fila mesmo assim.</p></div>`;
  }
  const figuras = imagens.map((im) => {
    const nome = (im.arquivo || "").replace("midia/", "");
    const sim = im.simulada ? " · CAPTURA SIMULADA" : "";
    return `<figure><img data-src="/v1/eventos/${evento.id}/midia/${nome}" alt="${texto(im.tipo)}">
      <figcaption>${texto(im.tipo)} · ${texto(im.resolucao)}${sim}</figcaption></figure>`;
  }).join("");
  return `<div class="bloco"><h3>Imagens</h3><div class="imagens">${figuras}</div></div>`;
}

function regrasBloco(decisao) {
  const regras = decisao.regras || [];
  if (!regras.length) return "";
  const itens = regras.map((r) => `<li>
    <span class="${r.atendida ? "marca-ok" : "marca-nao"}">${r.atendida ? "✓" : "✗"}</span>
    <span class="nome">${texto(r.nome)}</span><span class="medido">${texto(r.medido)}</span></li>`).join("");
  return `<div class="bloco"><h3>Regras avaliadas pelo nó — ${texto(decisao.versao_politica)}</h3>
    <ul class="regras">${itens}</ul></div>`;
}

function historicoBloco(revisoes) {
  if (!revisoes || !revisoes.length) return "";
  const itens = revisoes.map((r) => `<li><div class="quem">${texto(r.operador)} · ${texto(r.decidido_em)}</div>
    <div>${texto(r.decisao)}${r.observacao ? " — " + texto(r.observacao) : ""}</div></li>`).join("");
  return `<div class="bloco"><h3>Histórico de revisão</h3><ul class="historico">${itens}</ul></div>`;
}

async function decidir(id, decisao) {
  const observacao = $("observacao")?.value || "";
  try {
    await api(`/v1/eventos/${id}/revisao`, { method: "POST", body: JSON.stringify({ decisao, observacao }) });
    await telaRevisao();
    await abrirEvento(id);
    const alvo = $("mensagem");
    if (alvo) alvo.innerHTML = `<div class="mensagem ok">Evento ${decisao === "confirmar" ? "confirmado" : "rejeitado"}.</div>`;
  } catch (erro) {
    const alvo = $("mensagem");
    if (alvo) alvo.innerHTML = `<div class="mensagem falha">${texto(erro.message)}</div>`;
  }
}

/* -- tela: nós ---------------------------------------------------- */

async function telaNos() {
  const dados = await api("/v1/nos");
  const agora = Date.now();
  const linhas = dados.nos.map((no) => {
    const hb = no.ultimo_heartbeat ? new Date(no.ultimo_heartbeat + "Z").getTime() : null;
    const online = hb && agora - hb < 15 * 60 * 1000;
    return `<tr>
      <td>${texto(no.no_id)}</td>
      <td>${texto(no.descricao || "—")}</td>
      <td><span class="etiqueta ${online ? "online" : "offline"}">${online ? "online" : "sem sinal"}</span></td>
      <td class="num">${no.bateria_pct == null ? "—" : no.bateria_pct.toFixed(0) + "%"}</td>
      <td class="num">${no.pendentes}</td>
      <td>${no.ultimo_heartbeat ? quando(no.ultimo_heartbeat + "Z") : "—"}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="6" class="vazio">Nenhum nó registrou contato ainda.</td></tr>`;

  $("conteudo").innerHTML = `
    <div class="topo-tela"><div><h1>Nós instalados</h1>
      <div class="sub">Um nó é considerado sem sinal após 15 min sem heartbeat</div></div></div>
    <table class="tabela">
      <tr><th>Nó</th><th>Local</th><th>Estado</th><th class="num">Bateria</th>
          <th class="num">Pendentes</th><th>Último heartbeat</th></tr>
      ${linhas}
    </table>`;
}

/* -- tela: violações (canal patrimonial) -------------------------- */

async function telaViolacoes() {
  const dados = await api("/v1/violacoes");
  const linhas = dados.violacoes.map((v) => `<tr>
      <td><span class="etiqueta ${v.atendido ? "rejeitado" : "offline"}">${v.tipo}</span></td>
      <td>${texto(v.no_id)}</td>
      <td>${quando(v.recebido_em + "Z")}</td>
      <td>${v.atendido ? "atendido" : `<button class="secundario" data-atender="${v.id}">Marcar atendido</button>`}</td>
    </tr>`).join("") || `<tr><td colspan="4" class="vazio">Nenhuma violação registrada. Bom sinal.</td></tr>`;

  $("conteudo").innerHTML = `
    <div class="topo-tela"><div><h1>Violações patrimoniais</h1>
      <div class="sub">Canal separado da fiscalização — furto e violação de gabinete</div></div></div>
    <div class="aviso-tela">Ocorrência operacional, não evento de fiscalização.
      O alerta chega antes da remoção do equipamento, com prioridade máxima.</div>
    <table class="tabela">
      <tr><th>Tipo</th><th>Nó</th><th>Recebido</th><th></th></tr>${linhas}</table>`;

  $("conteudo").querySelectorAll("[data-atender]").forEach((botao) => {
    botao.addEventListener("click", async () => {
      await api(`/v1/violacoes/${botao.dataset.atender}/atender`, { method: "POST" });
      telaViolacoes();
    });
  });
}

/* -- tela: histórico ---------------------------------------------- */

async function telaHistorico() {
  $("conteudo").innerHTML = `
    <div class="topo-tela"><div><h1>Histórico</h1>
      <div class="sub">Eventos já decididos — para recuperar evidência específica</div></div></div>
    <div class="filtros">
      <select id="filtro-status">
        <option value="">Todos os status</option>
        <option value="confirmado">Confirmados</option>
        <option value="rejeitado">Rejeitados</option>
        <option value="pendente_revisao">Pendentes</option>
      </select>
    </div>
    <table class="tabela" id="tabela-historico"><tbody></tbody></table>`;
  $("filtro-status").value = estado.filtroHistorico;
  $("filtro-status").addEventListener("change", (e) => {
    estado.filtroHistorico = e.target.value;
    carregarHistorico();
  });
  await carregarHistorico();
}

async function carregarHistorico() {
  const q = estado.filtroHistorico ? `?status=${estado.filtroHistorico}&limite=300` : "?limite=300";
  const dados = await api(`/v1/eventos${q}`);
  const corpo = dados.eventos.map((e) => `<tr>
    <td>${quando(e.capturado_em)}</td><td>${texto(e.no_id)}</td>
    <td>${texto(e.classe) || "—"}</td><td class="num">${numero(e.score_alvo, 2)}</td>
    <td>${e.azimute_graus == null ? "—" : e.azimute_graus.toFixed(0) + "°"}</td>
    <td><span class="etiqueta ${e.status}">${rotuloStatus(e.status)}</span></td>
  </tr>`).join("") || `<tr><td colspan="6" class="vazio">Nenhum evento nesse filtro.</td></tr>`;
  $("tabela-historico").innerHTML = `<thead><tr><th>Capturado</th><th>Nó</th><th>Classe</th>
    <th class="num">Score</th><th>Ângulo</th><th>Status</th></tr></thead><tbody>${corpo}</tbody>`;
}

/* -- tela: métricas ----------------------------------------------- */

async function telaMetricas() {
  const dados = await api("/v1/metricas");
  const r = dados.rejeicao;
  const taxa = r.taxa_rejeicao == null ? "—" : (r.taxa_rejeicao * 100).toFixed(1) + "%";

  const dias = dados.por_dia.slice().reverse();
  const maxDia = Math.max(...dias.map((d) => d.total), 1);
  const barras = dias.map((d) => {
    const h = 132;
    return `<div class="barra-dia" title="${d.dia}: ${d.confirmados} conf., ${d.rejeitados} rej.">
      <div class="seg-rej" style="height:${(d.rejeitados / maxDia) * h}px"></div>
      <div class="seg-conf" style="height:${(d.confirmados / maxDia) * h}px"></div></div>`;
  }).join("");
  const rotulos = dias.map((d) => `<span>${d.dia.slice(5)}</span>`).join("");

  $("conteudo").innerHTML = `
    <div class="topo-tela"><div><h1>Métricas</h1>
      <div class="sub">Volume operacional e taxa de rejeição na revisão</div></div></div>
    <div class="grade-cartoes">
      ${cartao("confirmado", r.confirmados, "Confirmados")}
      ${cartao("", r.rejeitados, "Rejeitados")}
      ${cartao("pendente", r.pendentes, "Pendentes")}
      ${cartao("", taxa, "Taxa de rejeição")}
    </div>
    <div class="bloco"><h3>Eventos por dia — confirmados (verde) e rejeitados (cinza)</h3>
      ${dias.length ? `<div class="barras">${barras}</div><div class="barra-rotulos">${rotulos}</div>`
        : `<p class="vazio">Sem eventos ainda.</p>`}</div>
    <div class="aviso-tela">${texto(dados.nota_custo)}</div>`;
}

/* -- tela: modelo (admin) ----------------------------------------- */

async function telaModelo() {
  const dados = await api("/v1/modelo/versoes");
  const linhas = dados.versoes.map((v) => `<tr>
    <td>${texto(v.versao)}</td><td class="num">${v.eventos}</td>
    <td>${quando(v.primeiro)}</td><td>${quando(v.ultimo)}</td></tr>`).join("")
    || `<tr><td colspan="4" class="vazio">Nenhuma versão registrada ainda.</td></tr>`;
  $("conteudo").innerHTML = `
    <div class="topo-tela"><div><h1>Versões de modelo</h1>
      <div class="sub">Derivadas do que a evidência registrou</div></div></div>
    <div class="aviso-tela">${texto(dados.observacao)}</div>
    <table class="tabela"><tr><th>Versão</th><th class="num">Eventos</th>
      <th>Primeiro</th><th>Último</th></tr>${linhas}</table>`;
}

/* -- tela: auditoria (admin) -------------------------------------- */

async function telaAuditoria() {
  const [verif, lista] = await Promise.all([
    api("/v1/auditoria/verificar"),
    api("/v1/auditoria?limite=200"),
  ]);
  const linhas = lista.entradas.map((e) => `<tr>
    <td class="num">${e.seq}</td><td>${quando(e.registrado_em)}</td>
    <td>${texto(e.tipo)}</td><td>${texto(e.ator)}</td><td>${texto(e.evento_id || "—")}</td>
    <td class="hash">${texto((e.hash || "").slice(0, 20))}…</td></tr>`).join("");

  $("conteudo").innerHTML = `
    <div class="topo-tela"><div><h1>Trilha de auditoria</h1>
      <div class="sub">Cadeia encadeada por hash — qualquer alteração do histórico é detectável</div></div></div>
    <div class="grade-cartoes">
      <div class="cartao"><div class="valor ${verif.integra ? "pilula-integra" : "pilula-quebrada"}">
        ${verif.integra ? "íntegra" : "QUEBRADA"}</div>
        <div class="rotulo">Integridade da cadeia</div></div>
      ${cartao("", verif.total, "Entradas")}
    </div>
    ${verif.integra ? "" : `<div class="mensagem falha">${texto(verif.problemas.join("; "))}</div>`}
    <table class="tabela"><tr><th class="num">#</th><th>Quando</th><th>Tipo</th>
      <th>Ator</th><th>Evento</th><th>Hash</th></tr>${linhas}</table>`;
}

/* -- tela: configurações ------------------------------------------ */

async function telaConfig() {
  const modos = await api("/v1/nos/modos");
  const linhas = modos.nos.map((n) => `<tr><td>${texto(n.no_id)}</td>
    <td><span class="etiqueta ${n.modo === "autuacao" ? "rejeitado" : "pendente_revisao"}">${texto(n.modo || "—")}</span></td></tr>`).join("")
    || `<tr><td colspan="2" class="vazio">Nenhum nó registrado.</td></tr>`;

  $("conteudo").innerHTML = `
    <div class="topo-tela"><div><h1>Configurações</h1>
      <div class="sub">Limiares e calibração vivem na configuração de cada nó</div></div></div>

    <div class="bloco"><h3>Modo de operação por nó</h3>
      <table class="tabela"><tr><th>Nó</th><th>Modo</th></tr>${linhas}</table></div>

    <div class="aviso-tela">
      <strong>Modo de autuação: ${modos.autuacao_liberada ? "liberado" : "bloqueado"}.</strong><br>
      ${texto(modos.motivo_autuacao_bloqueada)}
    </div>

    <div class="bloco"><h3>Onde ficam as demais configurações</h3>
      <p class="dica">Limiar de confiança, calibração de SPL por sensor, política de
      retenção e geometria do array vivem na configuração de cada nó
      (<span class="hash">config/no-*.yaml</span>), não neste painel. São por nó
      porque uma via de tráfego pesado tem piso de ruído diferente de uma rua
      residencial — e mudá-las remotamente sem registro quebraria a
      reprodutibilidade da decisão.</p></div>`;
}

/* -- utilidades --------------------------------------------------- */

function cartao(classe, valor, rotulo) {
  return `<div class="cartao ${classe}"><div class="valor">${texto(valor)}</div>
    <div class="rotulo">${texto(rotulo)}</div></div>`;
}
function medida(rotulo, valor, nota = "", alerta = false) {
  return `<div class="medida"><div class="rotulo">${texto(rotulo)}</div>
    <div class="valor">${texto(valor)}</div>
    ${nota ? `<div class="nota ${alerta ? "alerta" : ""}">${texto(nota)}</div>` : ""}</div>`;
}
function numero(valor, casas) { return valor == null ? "—" : Number(valor).toFixed(casas); }
function quando(iso) {
  if (!iso) return "—";
  const data = new Date(iso);
  return Number.isNaN(data.getTime()) ? iso
    : data.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}
function rotuloStatus(s) {
  return { pendente_revisao: "pendente", confirmado: "confirmado",
    confirmado_multa: "confirmado (multa)", rejeitado: "rejeitado" }[s] || s;
}
/* Escapa tudo que vem da API antes de entrar no HTML: campos passam pelo nó e
   por observação de operador, e nenhum dos dois é lugar de confiar cegamente. */
function texto(valor) {
  if (valor == null) return "";
  return String(valor).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* -- início ------------------------------------------------------- */

const salvo = sessionStorage.getItem(ARMAZEM);
if (salvo) {
  estado.token = salvo;
  api("/v1/eu").then((eu) => { estado.eu = eu; abrirPainel(); }).catch(() => sair());
}
