"""Monta a Opção A: a MESMA tela da B, self-contained, sem servidor.

Em vez de reescrever o painel (foi de onde vieram os bugs visuais), este script
pega o dashboard REAL — dashboard/index.html, estilo.css, painel.js — e troca só
a camada de rede: as chamadas `fetch` viram leitura do retrato congelado em
demo/dados-demo.js. O resto do painel é byte a byte o mesmo da B.

Gera:
  demo/index.html                     — página standalone (abre no navegador)
  <scratchpad>/demo-artifact.html     — versão só-conteúdo, para publicar Artifact

Rode scripts/exportar_demo.py antes, para ter demo/dados-demo.js atualizado.
"""

from __future__ import annotations

import sys
from pathlib import Path

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
  }
  if ((m = caminhoBase.match(/^\\/v1\\/eventos\\/(\\d+)$/))) return D.detalhes[m[1]];
  if ((m = caminhoBase.match(/^\\/v1\\/eventos\\/(\\d+)\\/revisao$/)) && metodo === "POST")
    return _revisar(m[1], JSON.parse(opcoes.body || "{}"));
  if ((m = caminhoBase.match(/^\\/v1\\/violacoes\\/(\\d+)\\/atender$/)) && metodo === "POST")
    return _atender(m[1]);
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

INIT_DEMO = '''/* DEMONSTRAÇÃO: pré-preenche o token e explica que qualquer valor entra. */
$("token").value = "admin-studio-cerne";
$("token").type = "text";
const dica = document.createElement("p");
dica.className = "rodape-acesso";
dica.innerHTML = "<strong>Demonstração.</strong> Qualquer token entra. " +
  "Use um token com <em>operador</em> para ver o painel sem as telas de " +
  "admin (Modelo e Auditoria).";
$("form-acesso").insertBefore(dica, $("erro-acesso"));'''

CSS_DEMO_EXTRA = '''
/* -- demonstração: faixa e sobreposição do relatório --------------- */
.faixa-demo {
  position: fixed; top: 0; right: 0; z-index: 50;
  background: var(--laranja); color: #17110d; font-family: var(--mono);
  font-size: 10.5px; letter-spacing: 0.08em; text-transform: uppercase;
  padding: 4px 12px; border-bottom-left-radius: 6px; font-weight: 600;
}
.sobreposicao-relatorio {
  position: fixed; inset: 0; z-index: 100; background: rgba(0,0,0,0.72);
  display: grid; place-items: center; padding: 24px;
}
.janela-relatorio {
  width: min(900px, 100%); height: min(90vh, 100%);
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


def montar(standalone: bool) -> str:
    css = (RAIZ / "dashboard" / "estilo.css").read_text(encoding="utf-8") + CSS_DEMO_EXTRA
    dados = (RAIZ / "demo" / "dados-demo.js").read_text(encoding="utf-8")
    # `</` dentro do JSON quebraria o <script>. Escapar mantém o valor idêntico em JS.
    dados = dados.replace("</", "<\\/")
    painel = transformar_painel()
    corpo = corpo_do_painel()

    partes = [
        f"<style>{css}</style>",
        FAIXA_DEMO,
        corpo,
        f"<script>{dados}</script>",
        f"<script>{painel}</script>",
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

    standalone = montar(standalone=True)
    (RAIZ / "demo" / "index.html").write_text(standalone, encoding="utf-8")

    scratch = None
    for arg in sys.argv[1:]:
        if arg.startswith("--artifact="):
            scratch = Path(arg.split("=", 1)[1])
    if scratch:
        scratch.write_text(montar(standalone=False), encoding="utf-8")

    kb = len(standalone.encode("utf-8")) / 1024
    print(f"gerado demo/index.html ({kb:.0f} KB, self-contained)")
    if scratch:
        print(f"gerado {scratch} (só-conteúdo, para Artifact)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
