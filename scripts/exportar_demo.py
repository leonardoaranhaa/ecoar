"""Congela um retrato dos dados da B num arquivo JS, para a Opção A.

A Opção A é a mesma tela da B (dashboard/), mas sem servidor: para apresentar
sem subir nada. Em vez de reescrever um mock à mão — que foi de onde vieram os
bugs visuais —, este script sobe o backend real, semeia o cenário de Piracicaba e
captura a RESPOSTA REAL de cada endpoint. O painel da demo lê esse retrato no
lugar da rede. Fiel por construção: é o mesmo dado que a B serve.

    python -m scripts.exportar_demo

Gera demo/dados-demo.js. O demo/index.html embute dashboard + esse retrato.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend.aplicacao import criar_app
from backend.config import carregar
from scripts.semear_demo import _heartbeats_e_violacao, _trafego_e_disparo_conceito, semear


def exportar() -> dict:
    config = carregar("config/backend.demo.yaml")
    tmp = Path(tempfile.mkdtemp(prefix="exportar-demo-"))
    config = dataclasses.replace(
        config, banco=tmp / "ecoar.db", armazenamento=tmp / "pacotes"
    )
    config.banco.parent.mkdir(parents=True, exist_ok=True)
    config.armazenamento.mkdir(parents=True, exist_ok=True)

    app = criar_app(config)
    from fastapi.testclient import TestClient

    operador = config.tokens_operador["operador-transito"]
    admin = config.tokens_operador["admin-studio-cerne"]
    cab_op = {"Authorization": f"Bearer {operador}"}
    cab_adm = {"Authorization": f"Bearer {admin}"}

    with TestClient(app) as cliente:
        conexao = app.state.conexao
        semear(config, cliente)
        _heartbeats_e_violacao(config, conexao, cliente)
        _trafego_e_disparo_conceito(config, cliente)

        def pegar(caminho, cab=cab_adm):
            resposta = cliente.get(caminho, headers=cab)
            resposta.raise_for_status()
            return resposta.json()

        retrato = {
            "eu_operador": pegar("/v1/eu", cab_op),
            "eu_admin": pegar("/v1/eu", cab_adm),
            "priorizacao": pegar("/v1/priorizacao"),
            "nos": pegar("/v1/nos"),
            "violacoes": pegar("/v1/violacoes"),
            "metricas": pegar("/v1/metricas"),
            "modelo": pegar("/v1/modelo/versoes"),
            "modos": pegar("/v1/nos/modos"),
            "auditoria_verif": pegar("/v1/auditoria/verificar"),
            "auditoria": pegar("/v1/auditoria?limite=300"),
            "eventos": pegar("/v1/eventos?limite=300"),
            # Roadmap modular (D15, D16) — recursos adicionais mediante
            # acionamento, desligados por padrão no painel.
            "trafego": pegar("/v1/trafego", cab_op),
            "alertas_disparo": pegar("/v1/alertas-disparo-conceito", cab_op),
        }

        # Detalhe de cada pendente (é o que a fila de revisão abre) e a mídia de
        # um deles, embutida como data URL — sem servidor para servir o blob.
        pendentes = [
            e for e in retrato["eventos"]["eventos"]
            if e["status"] == "pendente_revisao"
        ]
        detalhes = {}
        audio_url = None
        imagem_url = None
        for evento in pendentes:
            ident = evento["id"]
            detalhes[str(ident)] = pegar(f"/v1/eventos/{ident}")
            if audio_url is None:
                r = cliente.get(
                    f"/v1/eventos/{ident}/audio-audicao.wav", headers=cab_op
                )
                if r.status_code == 200:
                    audio_url = _data_url(r.content, "audio/wav")
            if imagem_url is None:
                imagens = (detalhes[str(ident)].get("manifesto") or {}).get("imagens") or []
                if imagens:
                    nome = imagens[0]["arquivo"].replace("midia/", "")
                    r = cliente.get(
                        f"/v1/eventos/{ident}/midia/{nome}", headers=cab_op
                    )
                    if r.status_code == 200:
                        imagem_url = _data_url(r.content, "image/png")

        retrato["detalhes"] = detalhes
        retrato["midia_audio"] = audio_url
        retrato["midia_imagem"] = imagem_url

        # O relatório imprimível, capturado como HTML pronto.
        rel = cliente.get("/v1/priorizacao/relatorio", headers=cab_op)
        retrato["relatorio"] = rel.text if rel.status_code == 200 else ""

    return retrato


def _data_url(conteudo: bytes, tipo: str) -> str:
    return f"data:{tipo};base64," + base64.b64encode(conteudo).decode("ascii")


def main() -> int:
    retrato = exportar()
    destino = RAIZ / "demo" / "dados-demo.js"
    corpo = json.dumps(retrato, ensure_ascii=False, separators=(",", ":"))
    cabecalho = (
        "/* Retrato dos dados da B, congelado por scripts/exportar_demo.py.\n"
        "   NÃO editar à mão: rode o script de novo para atualizar.\n"
        "   É a resposta real de cada endpoint do backend semeado com o cenário\n"
        "   de Piracicaba — a demo lê daqui no lugar da rede. */\n"
    )
    destino.write_text(cabecalho + "window.DEMO = " + corpo + ";\n", encoding="utf-8")

    tamanho = destino.stat().st_size / 1024
    print(f"gerado {destino} ({tamanho:.0f} KB)")
    print(f"  eventos ....... {retrato['eventos']['total']}")
    print(f"  pendentes ..... {len(retrato['detalhes'])}")
    print(f"  auditoria ..... {retrato['auditoria_verif']['total']} entradas, "
          f"{'íntegra' if retrato['auditoria_verif']['integra'] else 'QUEBRADA'}")
    print(f"  áudio embutido  {'sim' if retrato['midia_audio'] else 'não'}")
    print(f"  imagem embutida {'sim' if retrato['midia_imagem'] else 'não'}")
    print(f"  tráfego (tipo)  {len(retrato['trafego']['por_tipo'])} tipos agregados")
    print(f"  disparo (conc.) {len(retrato['alertas_disparo']['alertas'])} candidato(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
