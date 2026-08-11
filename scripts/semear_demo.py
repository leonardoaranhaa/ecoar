"""Semeia o backend real com dado realista de três cidades — a Opção B da
reunião de produto.

Não é um mock de tela. É o sistema de verdade: cada evento aqui é um pacote
`.ecoar` montado pelo mesmo código do nó, enviado pela API de ingestão real
(o hash é revalidado na entrada), e decidido pela fila de revisão real (a
trilha de auditoria encadeia cada decisão). Ao final, o banco em
`dados/demo/ecoar.db` contém eventos confirmados, rejeitados e pendentes,
heartbeats, e uma violação patrimonial — prontos para o painel exibir.

Uso:

    python -m scripts.semear_demo --config config/backend.demo.yaml

Depois:

    python -m backend.cli --config config/backend.demo.yaml
    # abra http://127.0.0.1:8000/  (token operador ou admin da config)

O que a demonstra: UM backend atendendo VÁRIAS instalações (oito nós, três
cidades) — a fundação do multi-tenant. O isolamento por município (login por
cidade) é a fase seguinte, planejada em docs/arquitetura-multicidade.md.
"""

from __future__ import annotations

import argparse
import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from backend import db
from backend.aplicacao import criar_app
from backend.config import ConfigBackend, carregar
from edge.audio_capture.buffer import Janela
from edge.audio_capture.captura import JanelaEvento
from edge.audio_capture.spl import estimar
from edge.camera_trigger import AcionadorCamera
from edge.classifier.base import CLASSE_ALVO, CLASSES, Predicao
from edge.config import ConfigCalibracao, ConfigNo, de_dict
from edge.evidence_packager import montar_pacote
from edge.localization.doa import EstimativaDOA

TAXA = 16000
SEMENTE = 20260811  # demo reprodutível: mesma semente, mesmo banco


# ---------------------------------------------------------------------------
# As oito instalações. Um backend, três cidades — a fundação do multi-tenant.
# lat/long aproximados de pontos reais; descrição só para o painel ficar legível.
# ---------------------------------------------------------------------------
class No:
    def __init__(self, no_id, cidade, descricao, lat, lon, token, volume, azimute_base):
        self.id = no_id
        self.cidade = cidade
        self.descricao = descricao
        self.lat = lat
        self.lon = lon
        self.token = token
        self.volume = volume  # quantos eventos este nó gerou no período
        self.azimute_base = azimute_base


NOS = [
    No("bauru-ponte-sao-joao-01", "Bauru", "Ponte da Rua São João, sentido centro",
       -22.3145, -49.0600, None, 46, 35.0),
    No("bauru-batalha-centro-02", "Bauru", "Av. Nações Unidas, altura da Batalha",
       -22.3260, -49.0700, None, 38, 120.0),
    No("bauru-jardim-europa-03", "Bauru", "Jardim Europa, corredor residencial",
       -22.3020, -49.0410, None, 17, 210.0),
    No("piracicaba-beira-rio-01", "Piracicaba", "Beira-Rio, próximo à Rua do Porto",
       -22.7253, -47.6492, None, 41, 60.0),
    No("piracicaba-av-independencia-02", "Piracicaba", "Av. Independência, viaduto",
       -22.7340, -47.6480, None, 29, 150.0),
    No("piracicaba-vila-rezende-03", "Piracicaba", "Vila Rezende, ponte do Mirante",
       -22.7110, -47.6510, None, 13, 300.0),
    No("marilia-sampaio-vidal-01", "Marília", "Av. Sampaio Vidal, área central",
       -22.2130, -49.9460, None, 34, 90.0),
    No("marilia-esplanada-02", "Marília", "Esplanada, saída para a SP-294",
       -22.2000, -49.9600, None, 21, 20.0),
]


def _config_no(no: No) -> ConfigNo:
    """Configuração mínima válida do nó, com id e geolocalização reais."""
    dados = {
        "no": {
            "id": no.id,
            "descricao": no.descricao,
            "geolocalizacao": {"latitude": no.lat, "longitude": no.lon},
        },
        "modo": "triagem",
        "audio": {
            "taxa_amostragem": TAXA,
            "canais": 4,
            "buffer_segundos": 8,
            "bloco_amostras": 1024,
            "fonte": {"tipo": "sintetica", "tempo_real": False, "perfil": "escapamento"},
            # Offset mais alto que o exemplo só para a faixa de dB da demo cobrir
            # 74–94 dBA (o array é peaky; sem isso o teto satura em ~78). É
            # calibração de demonstração, sem valor legal como todo SPL do array.
            "calibracao": {"offset_db": 110.0, "ponderacao": "A", "referencia": "demo"},
        },
        "array": {"raio_m": 0.045, "n_microfones": 4},
        "gatilho": {"janela_antes_s": 2.0, "janela_depois_s": 2.0},
        "sonometro": {"tipo": "ausente"},
    }
    return de_dict(dados)


def _janela_evento(instante_pico: float, spl_db: float) -> JanelaEvento:
    """Dois segundos de nota de escapamento, quatro canais — o pacote real.

    Escapamento é rico em harmônicos, não um tom puro: a série harmônica de um
    fundamental de motor (~92 Hz) tem energia no meio do espectro, onde a
    ponderação A pesa. Um seno de 92 Hz sozinho perderia ~30 dB na ponderação e
    nunca cruzaria o piso do nó. Com os harmônicos, o nível estimado bate com o
    alvo do evento — o que faz o dB na tela e a decisão de acionamento serem
    plausíveis.
    """
    t = np.arange(TAXA * 2) / TAXA
    onda = np.zeros_like(t)
    for n in range(1, 17):
        onda += (1.0 / n) * np.sin(2 * np.pi * 92.0 * n * t)
    onda /= np.max(np.abs(onda))

    # Mesmo offset da calibração do nó (110), para o SPL estimado cobrir a faixa
    # 74–94 dBA em vez de saturar em ~78. Sem valor legal, como todo array MEMS.
    calib = ConfigCalibracao(offset_db=110.0)
    ganho = _ganho_para_spl(onda, spl_db, calib)
    amostras = (ganho * onda)[:, None].repeat(4, axis=1).astype(np.float32)
    return JanelaEvento(
        janela=Janela(amostras, TAXA, instante_pico - 1.0, instante_pico + 1.0),
        spl=estimar(amostras, TAXA, calib),
        instante_pico=instante_pico,
        sonometro=None,
        motivo_sem_sonometro="sem instrumento em modo de triagem",
    )


def _ganho_para_spl(onda, alvo_db, calib) -> float:
    """Busca o ganho que faz o SPL estimado (ponderado A) bater com o alvo.

    estimar() aplica ponderação e offset; resolver o ganho de forma fechada
    daria conta, mas uma busca binária de meia dúzia de passos é mais simples e
    à prova de mudança na cadeia de estimativa.
    """
    baixo, alto = 1e-4, 0.98
    for _ in range(24):
        meio = (baixo + alto) / 2.0
        amostras = (meio * onda)[:, None].repeat(4, axis=1).astype(np.float32)
        if estimar(amostras, TAXA, calib).db < alvo_db:
            baixo = meio
        else:
            alto = meio
    return (baixo + alto) / 2.0


def _predicao(score: float) -> Predicao:
    resto = (1.0 - score) / (len(CLASSES) - 1)
    scores = {c: resto for c in CLASSES}
    scores[CLASSE_ALVO] = score
    return Predicao(
        classe=CLASSE_ALVO if score >= 0.5 else "ambiente",
        score=max(scores.values()),
        scores=scores,
        modelo="heuristico",
        versao_modelo="heuristico/1.0-bancada",
        explicacao="fundamental de motor, série harmônica forte",
        descritores={"f0_hz": 88.0},
    )


def _gerar_pacote(config, no_id, evento_id, score, azimute, spl_db, instante_pico, destino):
    evento = _janela_evento(instante_pico, spl_db)
    predicao = _predicao(score)
    doa = EstimativaDOA(
        azimute_graus=azimute,
        confianca=round(random.uniform(0.72, 0.97), 2),
        margem_graus=round(random.uniform(1.2, 4.5), 1),
        residuo_us=3.0,
        qualidade_media=0.98,
        tdoas_us={"0-1": 120.0},
    )
    acionador = AcionadorCamera(config, diretorio=Path(destino).parent / "capturas")
    acionamento = acionador.processar(evento_id, predicao, doa, evento.spl)
    return montar_pacote(
        config=config,
        evento_id=evento_id,
        evento=evento,
        doa=doa,
        predicao=predicao,
        acionamento=acionamento,
        destino=Path(destino),
    )


def _instante(rng: random.Random, base: datetime) -> float:
    """Um instante nos últimos 21 dias, pesado para a noite e o fim de semana.

    Escapamento adulterado é fenômeno de fim de tarde/madrugada e de fim de
    semana; concentrar aí faz o mapa de calor contar a história que a prefeitura
    reconhece — sem isso o painel mostra ruído uniforme, que não é o real.
    """
    dia = rng.randint(0, 20)
    data = base - timedelta(days=dia)
    # Horas prováveis: começo da madrugada e fim de tarde/noite.
    horas = [0, 1, 2, 19, 20, 21, 22, 22, 23, 23, 18, 17, 12]
    hora = rng.choice(horas)
    minuto = rng.randint(0, 59)
    momento = data.replace(hour=hora, minute=minuto, second=rng.randint(0, 59),
                           microsecond=0, tzinfo=timezone.utc)
    return momento.timestamp()


def semear(config: ConfigBackend, cliente) -> dict:
    rng = random.Random(SEMENTE)
    base = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)

    tokens_por_no = config.tokens
    operador = config.tokens_operador["operador-transito"]

    total_enviados = 0
    total_confirmados = 0
    total_rejeitados = 0
    total_pendentes = 0

    tmp = Path(tempfile.mkdtemp(prefix="semear-ecoar-"))
    try:
        for no in NOS:
            token = tokens_por_no[no.id]
            config_no = _config_no(no)

            ids_backend = []
            for i in range(no.volume):
                # ~40% dos eventos passam de frente para a câmera (fonte perto do
                # eixo, score alto): esses acionam a câmera e carregam imagem. O
                # resto vem de ângulo lateral ou score menor e entra como
                # ambíguo, sem imagem — os dois estados que o operador revisa.
                em_frente = rng.random() < 0.40
                if em_frente:
                    score = round(rng.uniform(0.85, 0.97), 3)
                    azimute = rng.uniform(-35, 35) % 360
                    spl_db = round(rng.uniform(80.0, 94.0), 1)
                else:
                    score = round(rng.uniform(0.62, 0.84), 3)
                    azimute = (no.azimute_base + rng.uniform(-25, 25)) % 360
                    spl_db = round(rng.uniform(74.0, 90.0), 1)
                instante = _instante(rng, base)
                evento_id = f"{no.id}-evt-{i:04d}"

                caminho = _gerar_pacote(
                    config_no, no.id, evento_id, score, azimute, spl_db, instante,
                    tmp / f"{evento_id}.ecoar",
                )
                with caminho.open("rb") as arquivo:
                    resposta = cliente.post(
                        "/v1/eventos",
                        headers={"Authorization": f"Bearer {token}"},
                        files={"pacote": (caminho.name, arquivo, "application/octet-stream")},
                    )
                caminho.unlink(missing_ok=True)
                if resposta.status_code not in (201, 200):
                    raise RuntimeError(
                        f"ingestão recusou {evento_id}: {resposta.status_code} {resposta.text}"
                    )
                ids_backend.append(resposta.json()["id"])
                total_enviados += 1

            # Revisão humana: ~72% confirma, ~15% rejeita, o resto fica pendente.
            for identificador in ids_backend:
                sorte = rng.random()
                if sorte < 0.72:
                    decisao = "confirmar"
                elif sorte < 0.87:
                    decisao = "rejeitar"
                else:
                    total_pendentes += 1
                    continue
                resp = cliente.post(
                    f"/v1/eventos/{identificador}/revisao",
                    headers={"Authorization": f"Bearer {operador}"},
                    json={"decisao": decisao, "observacao": ""},
                )
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"revisão recusou {identificador}: {resp.status_code} {resp.text}"
                    )
                if decisao == "confirmar":
                    total_confirmados += 1
                else:
                    total_rejeitados += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return {
        "enviados": total_enviados,
        "confirmados": total_confirmados,
        "rejeitados": total_rejeitados,
        "pendentes": total_pendentes,
    }


def _heartbeats_e_violacao(config: ConfigBackend, conexao, cliente) -> None:
    """Estado operacional dos nós e um alerta patrimonial.

    Um nó fica de fora do heartbeat de propósito: o painel precisa mostrar
    'sem sinal' para provar que o monitoramento funciona.
    """
    rng = random.Random(SEMENTE + 1)
    sem_sinal = "piracicaba-vila-rezende-03"

    for no in NOS:
        # descrição só entra por aqui: a ingestão não a carrega (não vai na
        # evidência), mas o painel de nós fica ilegível sem ela.
        with db.transacao(conexao):
            db.registrar_no(
                conexao,
                no_id=no.id,
                descricao=no.descricao,
                latitude=no.lat,
                longitude=no.lon,
                modo="triagem",
            )
        if no.id == sem_sinal:
            continue
        token = config.tokens[no.id]
        cliente.post(
            "/v1/heartbeat",
            headers={"Authorization": f"Bearer {token}"},
            json={"bateria_pct": round(rng.uniform(63.0, 99.0), 1), "detalhe": {"rssi_dbm": -rng.randint(70, 105)}},
        )

    # Canal patrimonial (D14): uma tentativa de violação de gabinete.
    cliente.post(
        "/v1/alertas",
        headers={"Authorization": f"Bearer {config.tokens['bauru-batalha-centro-02']}"},
        json={
            "tipo": "abertura_gabinete",
            "capturado_em": datetime.now(tz=timezone.utc).isoformat(),
            "detalhe": {"sensor": "reed", "duracao_s": 4.2},
        },
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="semear-demo")
    parser.add_argument("--config", default="config/backend.demo.yaml")
    parser.add_argument("--recriar", action="store_true",
                        help="apaga o banco e os pacotes da demo antes de semear")
    args = parser.parse_args(argv)

    config = carregar(args.config)

    if args.recriar:
        if config.banco.exists():
            config.banco.unlink()
        if config.armazenamento.exists():
            shutil.rmtree(config.armazenamento, ignore_errors=True)

    if config.banco.exists():
        print(f"banco já existe em {config.banco}. Use --recriar para começar do zero.",
              file=sys.stderr)
        return 2

    config.banco.parent.mkdir(parents=True, exist_ok=True)
    config.armazenamento.mkdir(parents=True, exist_ok=True)

    app = criar_app(config)
    from fastapi.testclient import TestClient

    with TestClient(app) as cliente:
        conexao = app.state.conexao
        resumo = semear(config, cliente)
        _heartbeats_e_violacao(config, conexao, cliente)

    print("\nSemeadura concluída — sistema real, dado de três cidades.\n")
    print(f"  eventos enviados ..... {resumo['enviados']}")
    print(f"  confirmados .......... {resumo['confirmados']}  (entram na priorização)")
    print(f"  rejeitados ........... {resumo['rejeitados']}")
    print(f"  pendentes ............ {resumo['pendentes']}  (esperando o operador)")
    print(f"\n  banco ................ {config.banco}")
    print(f"  pacotes .............. {config.armazenamento}")
    print("\nSuba o painel com:")
    print(f"    python -m backend.cli --config {args.config}")
    print("    # http://127.0.0.1:8000/  — token operador ou admin da config\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
