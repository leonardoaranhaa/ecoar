"""Monta a Opção A: a MESMA tela da B, self-contained, sem servidor.

Em vez de reescrever o painel (foi de onde vieram os bugs visuais), este script
pega o dashboard REAL — dashboard/index.html, estilo.css, painel.js — e troca só
a camada de rede: as chamadas `fetch` viram leitura do retrato congelado em
demo/dados-demo.js. O resto do painel é byte a byte o mesmo da B.

Gera:
  demo/index.html                     — página standalone (abre no navegador)
  <scratchpad>/demo-artifact.html     — versão só-conteúdo, para publicar Artifact

Rode scripts/exportar_demo.py antes, para ter demo/dados-demo.js atualizado.

Opções:
  --senha=FRASE           senha do portão de acesso (padrão: ver SENHA_PADRAO)
  --validade-dias=N       dias até o link expirar (padrão: 3)
  --artifact=CAMINHO      também grava a versão só-conteúdo nesse caminho

O portão de acesso e a validade são proteção do lado do cliente (quem souber
ler o código-fonte da página contorna) — o objetivo é impedir compartilhamento
casual do link puro, não resistir a alguém tecnicamente determinado.
"""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SENHA_PADRAO = "piracicaba2026"
VALIDADE_DIAS_PADRAO = 3

RAIZ = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Trechos do painel.js real que dependem de servidor. Cada um é substituído por
# uma versão que lê o retrato embutido. O texto de origem é copiado exato do
# arquivo — se o painel mudar, o build falha alto (melhor que gerar tela quebrada).
# ---------------------------------------------------------------------------

API_ORIG = '''async function api(caminho, opcoes = {}) {
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
}'''

API_DEMO = '''/* DEMONSTRAÇÃO: no lugar da rede, lê o retrato congelado da B (window.DEMO).
   Mesma assinatura de api(): o resto do painel não sabe que não há servidor. */
const D = window.DEMO;
function _contagem() {
  const c = { pendente_revisao: 0, confirmado: 0, confirmado_multa: 0, rejeitado: 0 };
  D.eventos.eventos.forEach((e) => { c[e.status] = (c[e.status] || 0) + 1; });
  return c;
}
function _listarEventos(p) {
  const status = p.get("status");
  const noId = p.get("no_id");
  const limite = Number(p.get("limite") || 50);
  let evs = D.eventos.eventos.slice();
  if (status) evs = evs.filter((e) => e.status === status);
  if (noId) evs = evs.filter((e) => e.no_id === noId);
  evs.sort((a, b) => (a.capturado_em < b.capturado_em ? 1 : -1));
  return { total: evs.length, contagem: _contagem(), eventos: evs.slice(0, limite) };
}
function _revisar(id, corpo) {
  const novo = corpo.decisao === "confirmar" ? "confirmado" : "rejeitado";
  const ev = D.eventos.eventos.find((e) => String(e.id) === String(id));
  if (ev) ev.status = novo;
  const det = D.detalhes[id];
  if (det) {
    det.status = novo;
    (det.revisoes = det.revisoes || []).push({
      operador: estado.eu.nome, decisao: corpo.decisao,
      observacao: corpo.observacao || "",
      decidido_em: new Date().toISOString(),
    });
  }
  return { id: Number(id), status: novo, operador: estado.eu.nome };
}
function _atender(id) {
  const v = D.violacoes.violacoes.find((x) => String(x.id) === String(id));
  if (v) v.atendido = true;
  return { status: "atendido", id: Number(id) };
}
function _atenderDisparo(id) {
  const a = D.alertas_disparo.alertas.find((x) => String(x.id) === String(id));
  if (a) a.atendido = true;
  return { status: "atendido", id: Number(id) };
}
async function api(caminho, opcoes = {}) {
  await new Promise((r) => setTimeout(r, 45)); // leve latência: parece a rede real
  const metodo = (opcoes.method || "GET").toUpperCase();
  const [caminhoBase, consulta] = caminho.split("?");
  const p = new URLSearchParams(consulta || "");
  let m;
  switch (caminhoBase) {
    case "/v1/eu": return estado.eu;
    case "/v1/priorizacao": return D.priorizacao;
    case "/v1/nos": return D.nos;
    case "/v1/violacoes": return D.violacoes;
    case "/v1/metricas": return D.metricas;
    case "/v1/modelo/versoes": return D.modelo;
    case "/v1/nos/modos": return D.modos;
    case "/v1/auditoria/verificar": return D.auditoria_verif;
    case "/v1/auditoria": return D.auditoria;
    case "/v1/eventos": return _listarEventos(p);
    case "/v1/trafego": return D.trafego;
    case "/v1/alertas-disparo-conceito": return D.alertas_disparo;
  }
  if ((m = caminhoBase.match(/^\\/v1\\/eventos\\/(\\d+)$/))) return D.detalhes[m[1]];
  if ((m = caminhoBase.match(/^\\/v1\\/eventos\\/(\\d+)\\/revisao$/)) && metodo === "POST")
    return _revisar(m[1], JSON.parse(opcoes.body || "{}"));
  if ((m = caminhoBase.match(/^\\/v1\\/violacoes\\/(\\d+)\\/atender$/)) && metodo === "POST")
    return _atender(m[1]);
  if ((m = caminhoBase.match(/^\\/v1\\/alertas-disparo-conceito\\/(\\d+)\\/atender$/)) && metodo === "POST")
    return _atenderDisparo(m[1]);
  throw new Error("rota de demonstração desconhecida: " + caminhoBase);
}'''

MIDIA_ORIG = '''async function carregarMidia(elemento) {
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
}'''

MIDIA_DEMO = '''async function carregarMidia(elemento) {
  const origem = elemento.dataset.src || "";
  const url = origem.includes("/audio-audicao") ? D.midia_audio
    : origem.includes("/midia/") ? D.midia_imagem : null;
  if (url) { elemento.src = url; return; }
  elemento.replaceWith(Object.assign(document.createElement("p"), {
    className: "aviso-audio", textContent: "mídia de exemplo indisponível",
  }));
}'''

LOGIN_ORIG = '''$("form-acesso").addEventListener("submit", async (evento) => {
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
});'''

LOGIN_DEMO = '''$("form-acesso").addEventListener("submit", (evento) => {
  evento.preventDefault();
  /* DEMONSTRAÇÃO: qualquer token entra. Um token com "operador" entra com o
     perfil de operador (sem Modelo e Auditoria); o resto entra como admin, para
     a apresentação poder mostrar todas as telas. */
  const valor = ($("token").value || "").trim().toLowerCase();
  estado.token = "demo";
  estado.eu = valor.includes("operador") ? D.eu_operador : D.eu_admin;
  abrirPainel();
  setTimeout(() => window.__ecoarTour && window.__ecoarTour.aoEntrar(), 400);
});'''

RELATORIO_ORIG = '''async function exportarRelatorio() {
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
}'''

RELATORIO_DEMO = '''function exportarRelatorio() {
  /* DEMONSTRAÇÃO: abre o relatório real (capturado da B) numa sobreposição com
     botão de imprimir — sem depender de janela nova, que o sandbox pode bloquear. */
  const fundo = document.createElement("div");
  fundo.className = "sobreposicao-relatorio";
  fundo.innerHTML = `
    <div class="janela-relatorio">
      <div class="barra-relatorio">
        <button class="secundario" id="fechar-rel">Fechar</button>
        <button id="imprimir-rel">Imprimir / salvar PDF</button>
      </div>
      <iframe id="quadro-rel"></iframe>
    </div>`;
  document.body.appendChild(fundo);
  fundo.style.height = document.documentElement.scrollHeight + "px";
  window.scrollTo({ top: 0, behavior: "instant" });
  document.getElementById("quadro-rel").srcdoc = D.relatorio;
  document.getElementById("fechar-rel").onclick = () => fundo.remove();
  document.getElementById("imprimir-rel").onclick = () => {
    const q = document.getElementById("quadro-rel");
    q.contentWindow.focus();
    q.contentWindow.print();
  };
}'''

INIT_ORIG = '''const salvo = sessionStorage.getItem(ARMAZEM);
if (salvo) {
  estado.token = salvo;
  api("/v1/eu").then((eu) => { estado.eu = eu; abrirPainel(); }).catch(() => sair());
}'''

INIT_DEMO = '''/* DEMONSTRAÇÃO: pré-preenche o token, já que não há servidor para validar. */
$("token").value = "admin-studio-cerne";
$("token").type = "text";
const dica = document.createElement("p");
dica.className = "rodape-acesso";
dica.innerHTML = "<strong>Ambiente de demonstração.</strong> Cinco pontos de " +
  "Piracicaba, com dados ilustrativos para apresentação do sistema.";
$("form-acesso").insertBefore(dica, $("erro-acesso"));'''

CSS_DEMO_EXTRA = '''
/* -- demonstração: layout à prova de iframe e de celular ----------- */
/* O painel real assume a página inteira: usa 100vh e position:fixed, o que é
   correto quando ele é o documento. A demo, não — ela roda dentro do iframe do
   Artifact (que se redimensiona à altura do conteúdo) e em tela de celular. Nos
   dois casos 100vh e fixed desmontam o layout: o painel encolhe para uma faixa,
   o conteúdo é cortado e as camadas fixas escapam por cima do host.
   Aqui o layout volta a ser fluxo de documento. Vale só para a demo — o
   dashboard real continua intacto. */
html, body { height: auto; }
#painel { min-height: 0; grid-template-columns: 220px minmax(0, 1fr); }
.lateral { position: static; height: auto; }
.conteudo { max-height: none; overflow-y: visible; }
.coluna-fila { max-height: none; }

/* `1fr` é `minmax(auto, 1fr)`: a faixa não encolhe abaixo do min-content, então
   uma tabela larga empurrava o painel inteiro para fora da tela (o texto saía
   cortado no celular). `minmax(0, 1fr)` deixa encolher; quem é largo de verdade
   — o mapa de calor, as tabelas — rola dentro do próprio bloco. */
.lateral, .principal, .conteudo, .revisao > *, .topo-tela > * { min-width: 0; }

/* Empilha de verdade no celular: a lateral vira topo, e o item ativo é marcado
   embaixo (a borda à esquerda some quando a navegação é horizontal). */
@media (max-width: 860px) {
  #painel { grid-template-columns: 1fr; }
  .lateral { flex-direction: column; }
  .marca-lateral, .rodape-lateral { width: 100%; }
  .navegacao { display: flex; flex-direction: row; flex-wrap: wrap; padding: 6px; gap: 2px; }
  .item-nav {
    width: auto; flex: 0 0 auto; padding: 8px 12px;
    border-left: none; border-bottom: 3px solid transparent; border-radius: 6px;
  }
  .item-nav.ativo { border-left-color: transparent; border-bottom-color: var(--laranja); }
  .conteudo { padding: 18px 14px; }
  .topo-tela h1 { font-size: 19px; }

  /* Mapa de calor: sem `width:100%` + `table-layout:fixed` a tabela usava só o
     que o conteúdo pedia (~220px) e sobrava metade da tela vazia. Com layout
     fixo, só a largura da 1ª linha (os <th>) importa — a coluna da hora fica
     estreita, o resto do espaço se reparte igual entre os 7 dias. */
  .heatmap { width: 100%; table-layout: fixed; font-size: 10px; }
  .heatmap th:first-child, .heatmap td.hora { width: 30px; }

  /* Toda tabela de dados: um nó/hash/id sem espaço (ex.: `sha256:19b6…`,
     `piracicaba-centro-hospitalar-02`) não tem onde quebrar linha por padrão, e
     isso empurrava a PÁGINA INTEIRA para o lado — era a causa do "vazando".
     `overflow-wrap:anywhere` dá à célula onde quebrar; a tabela continua com
     `table-layout:auto` (proporcional ao conteúdo, como no desktop) — testado
     `table-layout:fixed` aqui e ficou pior: colunas curtas (ESTADO, BATERIA)
     ganhavam a mesma largura da coluna de texto longo (LOCAL), quebrando
     palavra por letra. Auto deixa a coluna curta ficar curta. */
  .tabela { width: 100%; }
  .tabela td, .tabela th {
    padding: 8px 6px; font-size: 12.5px;
    overflow-wrap: anywhere; word-break: break-word;
  }

  /* -- fila de revisão: lista OU detalhe, nunca as duas empilhadas --
     Empilhado (lista longa, depois o detalhe embaixo) obrigava a rolar a
     página inteira para ver o que acabou de ser clicado — confuso numa
     apresentação, onde quem está vendo espera a resposta na hora. Aqui a
     lista some quando um evento é aberto, e um botão "Voltar" retorna a ela;
     o script (ver .voltar-fila abaixo) cuida de trocar a classe e rolar ao
     topo. */
  .revisao { grid-template-columns: 1fr; }
  .coluna-fila { border-right: none; padding-right: 0; }
  .revisao.detalhe-aberto .coluna-fila { display: none; }
  .revisao:not(.detalhe-aberto) #detalhe { display: none; }
  .voltar-fila { margin-bottom: 16px; }

  /* O que ainda assim for largo por natureza rola dentro do próprio bloco. */
  .bloco, .grade-medidas, .filtros { overflow-x: auto; }
}

/* -- demonstração: faixa e sobreposição do relatório --------------- */
.faixa-demo {
  position: absolute; top: 0; right: 0; z-index: 50;
  background: var(--laranja); color: #17110d; font-family: var(--mono);
  font-size: 10.5px; letter-spacing: 0.08em; text-transform: uppercase;
  padding: 4px 12px; border-bottom-left-radius: 6px; font-weight: 600;
}
.sobreposicao-relatorio {
  /* absolute + altura do documento: dentro do iframe do Artifact, `fixed`
     ancorava na viewport da página hospedeira e a janela saía do lugar. */
  position: absolute; left: 0; top: 0; width: 100%; z-index: 100;
  background: rgba(0,0,0,0.82); display: grid; place-items: start center; padding: 24px;
}
.janela-relatorio {
  width: min(900px, 100%); height: min(90vh, 720px);
  background: #fff; border-radius: 10px; overflow: hidden;
  display: flex; flex-direction: column;
}
.barra-relatorio {
  display: flex; gap: 8px; justify-content: flex-end;
  padding: 10px 12px; background: var(--superficie); border-bottom: 1px solid var(--borda);
}
.barra-relatorio button { font-size: 13px; }
.barra-relatorio #imprimir-rel { background: var(--laranja); color: #17110d; font-weight: 600; }
.janela-relatorio iframe { border: 0; width: 100%; flex: 1; background: #fff; }
'''

FAIXA_DEMO = ('<div class="faixa-demo" title="Dados de exemplo — não é captura de campo">'
              'demonstração · dados de exemplo</div>')

# ---------------------------------------------------------------------------
# Tour guiado — só na demo, só no primeiro acesso (guardado no localStorage).
# É o "modo TV de loja": explica cada tela e o porquê de cada coisa, ajudando o
# apresentador. Fica por cima do painel real, como a faixa — não toca o dashboard.
# ---------------------------------------------------------------------------
TOUR_CSS = '''
/* -- tour guiado (demonstração) ---------------------------------- */
.tour-hi {
  position: absolute; z-index: 200; border-radius: 8px; pointer-events: none;
  box-shadow: 0 0 0 4px var(--laranja), 0 0 0 9999px rgba(6,8,10,0.74);
  transition: all 0.25s ease;
}
.tour-card {
  position: absolute; z-index: 201; width: min(340px, calc(100vw - 32px));
  background: var(--superficie-alta); border: 1px solid var(--borda);
  border-radius: 12px; padding: 18px 18px 16px; box-shadow: 0 16px 50px rgba(0,0,0,0.5);
}
.tour-card h4 { margin: 0 0 8px; font-family: var(--titulo); font-size: 16px; }
.tour-card p { margin: 0 0 14px; font-size: 13.5px; color: var(--texto); line-height: 1.55; }
.tour-card .passo-n { font-family: var(--mono); font-size: 11px; color: var(--texto-fraco); }
.tour-botoes { display: flex; align-items: center; gap: 8px; }
.tour-botoes .espaco { flex: 1; }
.tour-botoes button { font-size: 13px; padding: 7px 14px; border-radius: 7px; }
.tour-prox { background: var(--laranja); color: #17110d; font-weight: 700; border: none; }
.tour-ant { background: transparent; border: 1px solid var(--borda); color: var(--texto-fraco); }
.tour-pular { background: transparent; border: none; color: var(--texto-fraco); font-size: 12px; }
.tour-pular:hover { color: var(--texto); }
.tour-ajuda { color: var(--ambar); font-size: 12.5px; padding: 7px 10px; }
.tour-ajuda:hover { border-color: var(--ambar); color: var(--ambar); }
@media (prefers-reduced-motion: reduce) { .tour-hi { transition: none; } }
'''

TOUR_JS = r'''
(function () {
  "use strict";
  const CHAVE = "ecoar-demo-tour-v1";
  const $ = (id) => document.getElementById(id);

  const passos = [
    { alvo: ".marca-lateral", titulo: "ECOAR",
      corpo: "Plataforma de fiscalização sonora operando em <b>modo de triagem</b>. Os sensores ouvem, localizam e registram ocorrências de escapamento adulterado, e o painel mostra onde e quando o problema se concentra. Esta demonstração usa cinco pontos de Piracicaba." },
    { tela: "priorizacao", alvo: ".heatmap", titulo: "Quando o problema é pior",
      corpo: "Mapa de calor por dia da semana e hora, montado apenas com eventos <b>confirmados por operador</b>. É o material que a equipe de fiscalização usa para definir dia e horário de blitz." },
    { tela: "priorizacao", alvo: ".bloco:last-of-type .tabela", titulo: "Onde o problema é pior",
      corpo: "Os pontos monitorados, ordenados por ocorrências confirmadas. Em modo de triagem o sistema responde <b>onde e quando</b>, nunca <b>quem</b>: a placa não é lida nem armazenada." },
    { tela: "revisao", alvo: ".coluna-fila", titulo: "Toda ocorrência passa por um operador",
      corpo: "Nenhum evento entra na estatística sozinho. Cada um é revisado antes de contar, e é isso que sustenta a evidência em caso de contestação." },
    { tela: "revisao", abrir: true, alvo: ".grade-medidas", titulo: "O que o sensor registrou",
      corpo: "Score do classificador, ângulo da fonte com margem de erro, e nível sonoro. O nível vem do array de microfones e é uma <b>estimativa sem valor legal</b>, o que fica declarado na própria tela." },
    { tela: "revisao", abrir: true, alvo: ".porque", titulo: "O porquê do resultado",
      corpo: "Em uma frase: por que o evento foi classificado como <b>acionar</b>, <b>ambíguo</b> ou <b>descartar</b>, e por que ainda está <b>pendente</b>. A decisão do sensor é determinística e versionada." },
    { tela: "revisao", abrir: true, alvo: ".regras", titulo: "As regras, uma a uma",
      corpo: "A decisão não é caixa-preta. São regras explícitas, cada uma mostrando o que se esperava e o que foi medido, de modo que a conclusão possa ser reconstruída depois." },
    { tela: "revisao", abrir: true, alvo: ".decisao", titulo: "A validação humana",
      corpo: "Confirmar ou rejeitar, com observação registrada em nome do operador. Só o que for confirmado entra na priorização, e a decisão nunca é apagada: correção se faz com um novo registro por cima." },
    { tela: "auditoria", alvo: ".grade-cartoes", titulo: "À prova de adulteração", admin: true,
      corpo: "Recebimento, acesso à evidência e decisão ficam encadeados por hash. Qualquer alteração no histórico quebra a cadeia, e o painel aponta na hora." },
    { alvo: ".marca-lateral", titulo: "Pronto",
      corpo: "Explore o painel à vontade. Os dados desta demonstração são ilustrativos: a campanha de gravação em campo é a etapa que consolida os números reais da cidade. O botão <b>?</b> no canto reabre este guia." },
  ];

  let idx = 0, hi = null, card = null, ativo = false;

  function esperar(sel, tentativas) {
    return new Promise((resolve) => {
      let n = tentativas || 40;
      (function tenta() {
        const el = document.querySelector(sel);
        if (el) return resolve(el);
        if (--n <= 0) return resolve(null);
        setTimeout(tenta, 50);
      })();
    });
  }

  async function prepararTela(passo) {
    if (passo.tela && typeof irPara === "function") {
      irPara(passo.tela);
      await esperar(".conteudo .topo-tela", 40);
    }
    if (passo.abrir) {
      const item = document.querySelector(".lista-eventos .item");
      if (item && typeof abrirEvento === "function") {
        abrirEvento(Number(item.dataset.id));
        await esperar("#detalhe .grade-medidas", 60);
      }
    }
  }

  function limpar() {
    hi && hi.remove(); card && card.remove(); hi = null; card = null;
  }

  async function mostrar(i, dir) {
    dir = dir || 1;
    if (i < 0 || i >= passos.length) return finalizar();
    const passo = passos[i];
    // pula o passo de admin quando o acesso é de operador (sem a aba Auditoria);
    // a presença da aba no menu é o sinal de RBAC, sem depender de estado interno.
    if (passo.admin && !document.querySelector('[data-tela="auditoria"]')) {
      return mostrar(i + dir, dir);
    }
    idx = i;
    await prepararTela(passo);
    let alvo = await esperar(passo.alvo, 40);
    if (!alvo) alvo = document.querySelector(".marca-lateral");
    alvo.scrollIntoView({ block: "center", behavior: "instant" });
    await new Promise((r) => setTimeout(r, 160));
    posicionar(alvo, i);
  }

  function posicionar(alvo, i) {
    limpar();
    /* Coordenadas de DOCUMENTO, não de viewport: as camadas do tour são
       position:absolute porque a demo roda dentro do iframe do Artifact, que se
       redimensiona à altura do conteúdo. Com position:fixed elas escapavam por
       cima da página hospedeira. */
    const sx = window.pageXOffset, sy = window.pageYOffset;
    const r = alvo.getBoundingClientRect();
    const pad = 6;
    const larguraDoc = document.documentElement.clientWidth;
    hi = document.createElement("div");
    hi.className = "tour-hi";
    hi.style.left = Math.max(4, r.left + sx - pad) + "px";
    hi.style.top = Math.max(4, r.top + sy - pad) + "px";
    hi.style.width = Math.min(larguraDoc - 8, r.width + pad * 2) + "px";
    hi.style.height = (r.height + pad * 2) + "px";
    document.body.appendChild(hi);

    const passo = passos[i];
    card = document.createElement("div");
    card.className = "tour-card";
    card.innerHTML =
      `<div class="passo-n">${i + 1} de ${passos.length}</div>
       <h4>${passo.titulo}</h4><p>${passo.corpo}</p>
       <div class="tour-botoes">
         <button class="tour-pular">Pular</button><span class="espaco"></span>
         ${i > 0 ? '<button class="tour-ant">Anterior</button>' : ""}
         <button class="tour-prox">${i === passos.length - 1 ? "Concluir" : "Próximo"}</button>
       </div>`;
    document.body.appendChild(card);

    /* Posiciona o cartão abaixo do alvo se couber na janela visível, senão
       acima; e sempre dentro da largura do documento. Tudo convertido para
       coordenadas de documento no fim. */
    const cr = card.getBoundingClientRect();
    const alturaVisivel = window.innerHeight;
    let top = r.bottom + 12;
    if (top + cr.height > alturaVisivel - 12) {
      const acima = r.top - cr.height - 12;
      top = acima >= 12 ? acima : Math.max(12, alturaVisivel - cr.height - 12);
    }
    let left = r.left;
    if (left + cr.width > larguraDoc - 12) left = larguraDoc - cr.width - 12;
    if (left < 12) left = 12;
    card.style.top = (top + sy) + "px";
    card.style.left = (left + sx) + "px";

    card.querySelector(".tour-prox").onclick = () => mostrar(i + 1, 1);
    const ant = card.querySelector(".tour-ant");
    if (ant) ant.onclick = () => mostrar(i - 1, -1);
    card.querySelector(".tour-pular").onclick = finalizar;
  }

  function finalizar() {
    limpar();
    ativo = false;
    try { localStorage.setItem(CHAVE, "1"); } catch (e) {}
  }

  function iniciar() {
    if (ativo) return;
    ativo = true;
    mostrar(0);
  }

  function montarBotao() {
    if ($("tour-ajuda")) return;
    const b = document.createElement("button");
    b.id = "tour-ajuda";
    b.className = "tour-ajuda secundario";
    b.title = "Rever o guia";
    b.textContent = "? Rever o guia";
    b.onclick = iniciar;
    /* No rodapé da lateral, junto do "Sair": flutuando sobre o conteúdo ele
       cobria a tabela no celular. */
    const rodape = document.querySelector(".rodape-lateral");
    (rodape || document.body).appendChild(b);
  }

  window.addEventListener("resize", () => { if (ativo) posicionar(document.querySelector(passos[idx].alvo) || document.querySelector(".marca-lateral"), idx); });

  window.__ecoarTour = {
    aoEntrar() {
      montarBotao();
      let visto = false;
      try { visto = !!localStorage.getItem(CHAVE); } catch (e) {}
      if (!visto) iniciar();
    },
    iniciar,
  };
})();
'''

FAIXA_DEMO_FIM = ""  # marcador

# ---------------------------------------------------------------------------
# Portão de acesso (demonstração): senha + validade por data. Proteção do
# lado do cliente — quem souber ler o código-fonte da página contorna — o
# objetivo é impedir que o link puro circule sem controle, não resistir a
# alguém tecnicamente determinado. O conteúdo real (#acesso, #painel) fica
# escondido por CSS até o portão liberar, então não há flash do painel antes
# da checagem.
# ---------------------------------------------------------------------------

PORTAO_CSS = '''
/* -- portão de acesso (demonstração) ------------------------------- */
body:not(.portao-liberado) #acesso,
body:not(.portao-liberado) #painel { display: none !important; }

#portao {
  min-height: 100vh; display: grid; place-items: center; padding: 24px;
}
#portao .cartao-acesso { text-align: left; }
#portao .marca { font-size: 26px; }
#portao p.explicacao {
  color: var(--texto-fraco); font-size: 13px; line-height: 1.6; margin: 4px 0 24px;
}
#portao .erro-portao {
  color: var(--vermelho); font-size: 12.5px; margin: -10px 0 16px; min-height: 1em;
}
#portao .selo-expirado {
  display: inline-block; margin-bottom: 14px; padding: 4px 10px;
  border-radius: 20px; background: rgba(224,82,82,0.14); color: var(--vermelho);
  font-family: var(--mono); font-size: 11px; letter-spacing: 0.06em;
}
'''

RODAPE_MARCA_CSS = '''
/* -- rodapé de marca e confidencialidade (demonstração) ------------ */
.rodape-marca {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 60;
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 6px 12px; font-size: 10.5px; color: var(--texto-fraco);
  background: rgba(14,17,19,0.88); border-top: 1px solid var(--borda);
  font-family: var(--mono); letter-spacing: 0.02em; text-align: center;
}
.rodape-marca strong { color: var(--texto); font-weight: 600; }
@media (max-width: 640px) { .rodape-marca { font-size: 9.5px; padding: 5px 8px; } }
'''

RODAPE_MARCA_HTML = (
    '<div class="rodape-marca">'
    "<strong>ECOAR&trade;</strong> · Studio Cerne · material confidencial de "
    "demonstração, não distribuir"
    "</div>"
)


PORTAO_JS_MODELO = r'''
(function () {
  "use strict";
  var HASH_SENHA = "__HASH_SENHA__";
  var EXPIRA_EM = "__EXPIRA_EM__";
  var CHAVE_SESSAO = "ecoar-demo-portao-v1";
  var $ = function (id) { return document.getElementById(id); };

  function expirado() { return new Date() > new Date(EXPIRA_EM); }

  async function sha256(texto) {
    var buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(texto));
    return Array.from(new Uint8Array(buf))
      .map(function (b) { return b.toString(16).padStart(2, "0"); }).join("");
  }

  function liberar() {
    try { sessionStorage.setItem(CHAVE_SESSAO, "1"); } catch (e) {}
    document.body.classList.add("portao-liberado");
    var p = $("portao");
    if (p) p.remove();
  }

  function montarExpirado() {
    var raiz = document.createElement("div");
    raiz.id = "portao";
    raiz.innerHTML =
      '<div class="cartao-acesso" style="text-align:center">' +
      '<span class="selo-expirado">link expirado</span>' +
      '<h1 class="marca">ECOAR</h1>' +
      '<p class="explicacao">O acesso a esta demonstração venceu. ' +
      'Peça um novo link a quem compartilhou este material.</p>' +
      '</div>';
    document.body.insertBefore(raiz, document.body.firstChild);
  }

  function montarSenha() {
    var raiz = document.createElement("div");
    raiz.id = "portao";
    raiz.innerHTML =
      '<form class="cartao-acesso" id="form-portao">' +
      '<h1 class="marca">ECOAR</h1>' +
      '<p class="explicacao">Demonstração de acesso restrito. ' +
      'Informe a senha combinada para continuar.</p>' +
      '<label for="senha-portao">Senha de acesso</label>' +
      '<input id="senha-portao" type="password" autocomplete="off" required>' +
      '<p class="erro-portao" id="erro-portao" hidden>Senha incorreta.</p>' +
      '<button type="submit">Entrar</button>' +
      '</form>';
    document.body.insertBefore(raiz, document.body.firstChild);
    $("form-portao").addEventListener("submit", async function (ev) {
      ev.preventDefault();
      var valor = $("senha-portao").value || "";
      var hash = await sha256(valor);
      if (hash === HASH_SENHA) { liberar(); }
      else {
        $("erro-portao").hidden = false;
        $("senha-portao").value = "";
        $("senha-portao").focus();
      }
    });
  }

  if (expirado()) { montarExpirado(); return; }
  var jaLiberado = false;
  try { jaLiberado = sessionStorage.getItem(CHAVE_SESSAO) === "1"; } catch (e) {}
  if (jaLiberado) { document.body.classList.add("portao-liberado"); }
  else { montarSenha(); }
})();
'''


def _portao_js(hash_senha: str, expira_iso: str) -> str:
    return PORTAO_JS_MODELO.replace("__HASH_SENHA__", hash_senha).replace(
        "__EXPIRA_EM__", expira_iso
    )

# ---------------------------------------------------------------------------
# Fila de revisão no celular — lista OU detalhe, nunca as duas empilhadas.
#
# Na tela larga a fila e o detalhe ficam lado a lado (.revisao é grid de duas
# colunas); no celular a regra em CSS_DEMO_EXTRA empilha as duas embaixo uma
# da outra — o que force rolar a lista inteira para ver o que acabou de ser
# clicado. Numa apresentação isso é falha visível: quem está assistindo espera
# a resposta na hora do clique. Este script troca embaixo por alternância: a
# lista some quando um evento abre, mostra o detalhe do topo, e um botão
# "Voltar" restaura a lista. Só na demo — o dashboard real não empilha porque
# tem a viewport larga do desktop.
# ---------------------------------------------------------------------------
MESTRE_DETALHE_JS = r'''
(function () {
  "use strict";

  function ehMobile() {
    return window.matchMedia("(max-width: 860px)").matches;
  }

  const PLACEHOLDER =
    '<div class="placeholder"><p>Selecione um evento na fila.</p>' +
    '<p class="dica">Nenhum evento é contado sozinho: a priorização se ' +
    "alimenta do que você confirmar aqui.</p></div>";

  function aplicar() {
    const revisao = document.querySelector(".revisao");
    const detalhe = document.getElementById("detalhe");
    if (!revisao || !detalhe) return;

    if (!ehMobile()) {
      revisao.classList.remove("detalhe-aberto");
      return;
    }

    const temSelecao = !!detalhe.querySelector(".topo-tela");

    if (temSelecao && !detalhe.querySelector(".voltar-fila")) {
      const botao = document.createElement("button");
      botao.type = "button";
      botao.className = "secundario voltar-fila";
      botao.textContent = "← Voltar à fila";
      botao.addEventListener("click", () => {
        detalhe.innerHTML = PLACEHOLDER;
        revisao.classList.remove("detalhe-aberto");
        if (typeof estado !== "undefined") estado.selecionado = null;
        if (typeof desenharListaRevisao === "function") desenharListaRevisao();
        window.scrollTo({ top: 0, behavior: "instant" });
      });
      detalhe.prepend(botao);
    }

    revisao.classList.toggle("detalhe-aberto", temSelecao);
    if (temSelecao) window.scrollTo({ top: 0, behavior: "instant" });
  }

  const observador = new MutationObserver(aplicar);
  const alvo = document.getElementById("conteudo") || document.body;
  observador.observe(alvo, { childList: true, subtree: true });
  window.addEventListener("resize", aplicar);
})();
'''


def transformar_painel() -> str:
    js = (RAIZ / "dashboard" / "painel.js").read_text(encoding="utf-8")
    trocas = [
        (API_ORIG, API_DEMO),
        (MIDIA_ORIG, MIDIA_DEMO),
        (LOGIN_ORIG, LOGIN_DEMO),
        (RELATORIO_ORIG, RELATORIO_DEMO),
        (INIT_ORIG, INIT_DEMO),
    ]
    for origem, novo in trocas:
        if origem not in js:
            raise SystemExit(
                "montar_demo: trecho do painel.js não encontrado — o painel mudou.\n"
                "Atualize o trecho correspondente em scripts/montar_demo.py.\n"
                f"Procurava por:\n{origem[:120]}..."
            )
        js = js.replace(origem, novo)
    return js


def corpo_do_painel() -> str:
    """Extrai o conteúdo do <body> do index.html do dashboard (as divs de tela)."""
    html = (RAIZ / "dashboard" / "index.html").read_text(encoding="utf-8")
    inicio = html.index("<body>") + len("<body>")
    fim = html.index("</body>")
    corpo = html[inicio:fim]
    # tira os <script>/<link> externos: tudo vira inline.
    for marca in ('<script src="/painel.js"></script>',):
        corpo = corpo.replace(marca, "")
    return corpo.strip()


def montar(standalone: bool, senha: str, expira_em: datetime) -> str:
    css = (
        (RAIZ / "dashboard" / "estilo.css").read_text(encoding="utf-8")
        + CSS_DEMO_EXTRA
        + TOUR_CSS
        + PORTAO_CSS
        + RODAPE_MARCA_CSS
    )
    dados = (RAIZ / "demo" / "dados-demo.js").read_text(encoding="utf-8")
    # `</` dentro do JSON quebraria o <script>. Escapar mantém o valor idêntico em JS.
    dados = dados.replace("</", "<\\/")
    painel = transformar_painel()
    corpo = corpo_do_painel()

    hash_senha = hashlib.sha256(senha.encode("utf-8")).hexdigest()
    expira_iso = expira_em.astimezone(timezone.utc).isoformat()
    portao_js = _portao_js(hash_senha, expira_iso)

    partes = [
        f"<style>{css}</style>",
        f"<script>{portao_js}</script>",
        RODAPE_MARCA_HTML,
        FAIXA_DEMO,
        corpo,
        f"<script>{dados}</script>",
        f"<script>{painel}</script>",
        f"<script>{TOUR_JS}</script>",
        f"<script>{MESTRE_DETALHE_JS}</script>",
    ]
    conteudo = "\n".join(partes)

    if not standalone:
        return conteudo  # só-conteúdo: o Artifact embrulha em html/head/body

    favicon = ('data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 '
               'viewBox=%220 0 32 32%22%3E%3Ccircle cx=%2216%22 cy=%2216%22 r=%224%22 '
               'fill=%22%23FF6B35%22/%3E%3Ccircle cx=%2216%22 cy=%2216%22 r=%2210%22 '
               'fill=%22none%22 stroke=%22%23F5A623%22 stroke-width=%222%22/%3E%3C/svg%3E')
    return (
        "<!doctype html>\n<html lang=\"pt-BR\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>ECOAR — demonstração</title>\n"
        f"<link rel=\"icon\" href=\"{favicon}\">\n"
        "<style>*{box-sizing:border-box}html,body{margin:0}</style>\n"
        "</head>\n<body>\n" + conteudo + "\n</body>\n</html>\n"
    )


def main() -> int:
    if not (RAIZ / "demo" / "dados-demo.js").exists():
        raise SystemExit("falta demo/dados-demo.js — rode antes: python -m scripts.exportar_demo")

    senha = SENHA_PADRAO
    dias = VALIDADE_DIAS_PADRAO
    scratch = None
    for arg in sys.argv[1:]:
        if arg.startswith("--artifact="):
            scratch = Path(arg.split("=", 1)[1])
        elif arg.startswith("--senha="):
            senha = arg.split("=", 1)[1]
        elif arg.startswith("--validade-dias="):
            dias = int(arg.split("=", 1)[1])

    expira_em = datetime.now(tz=timezone.utc) + timedelta(days=dias)

    standalone = montar(standalone=True, senha=senha, expira_em=expira_em)
    (RAIZ / "demo" / "index.html").write_text(standalone, encoding="utf-8")

    if scratch:
        conteudo_artifact = montar(standalone=False, senha=senha, expira_em=expira_em)
        scratch.write_text(conteudo_artifact, encoding="utf-8")

    kb = len(standalone.encode("utf-8")) / 1024
    print(f"gerado demo/index.html ({kb:.0f} KB, self-contained)")
    if scratch:
        print(f"gerado {scratch} (só-conteúdo, para Artifact)")
    print(f"\nsenha de acesso ...... {senha}")
    print(f"expira em ............ {expira_em.astimezone().strftime('%d/%m/%Y %H:%M')} "
          f"(horário local, {dias} dia(s) a partir de agora)")
    print("\nPasse a senha separadamente de quem receber o link (mensagem, verbalmente).")
    print("Proteção do lado do cliente: impede compartilhamento casual do link, não é")
    print("resistente a alguém tecnicamente determinado a ler o código-fonte da página.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
