"""Semeia o backend real com o cenário de Piracicaba — a Opção B da
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

O cenário é **Piracicaba**: cinco pontos tirados do levantamento documental em
docs/field-notes/piracicaba.md (operação real da Semuttran, requerimentos da
Câmara, polo de lazer noturno), com perfil horário próprio por ponto.

Os volumes e horários são **construídos** a partir desse levantamento — não são
medição. Nenhuma gravação foi feita em Piracicaba até aqui; o que o cenário
mostra é a forma do produto sobre pontos reais, não o volume real da cidade.
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
# Cinco pontos em Piracicaba. Não são endereços sorteados: cada um sai do
# levantamento documental em docs/field-notes/piracicaba.md — operação real da
# Semuttran, requerimentos da Câmara, polo de lazer noturno. A descrição carrega
# a razão do ponto, porque ela aparece na coluna "Local" do painel: quem abre a
# tela vê por que aquele ponto foi escolhido.
#
# O `perfil` define QUANDO os eventos acontecem naquele ponto. É o que faz o
# mapa de calor ter forma reconhecível para quem mora na cidade — corredor de
# tráfego satura no fim de tarde, polo de lazer satura na madrugada de sábado.
#
# ATENÇÃO: os volumes são construídos, não medidos. Nenhuma gravação foi feita
# em Piracicaba. Ver a seção "O que este documento NÃO estabelece" da nota.
# ---------------------------------------------------------------------------
class No:
    def __init__(self, no_id, cidade, descricao, lat, lon, token, volume,
                 azimute_base, perfil="corredor"):
        self.id = no_id
        self.cidade = cidade
        self.descricao = descricao
        self.lat = lat
        self.lon = lon
        self.token = token
        self.volume = volume  # quantos eventos este nó gerou no período
        self.azimute_base = azimute_base
        self.perfil = perfil


CIDADE = "Piracicaba"

NOS = [
    No("piracicaba-kennedy-01", CIDADE,
       "Av. Presidente Kennedy, Centro",
       -22.7180, -47.6390, None, 52, 35.0, perfil="corredor"),
    No("piracicaba-centro-hospitalar-02", CIDADE,
       "Área central, entorno hospitalar",
       -22.7253, -47.6492, None, 44, 120.0, perfil="centro"),
    No("piracicaba-joao-conceicao-03", CIDADE,
       "Av. Dr. João Conceição, Paulista",
       -22.7412, -47.6301, None, 33, 150.0, perfil="corredor"),
    No("piracicaba-sao-dimas-04", CIDADE,
       "São Dimas, área residencial",
       -22.7096, -47.6605, None, 26, 210.0, perfil="residencial"),
    No("piracicaba-rua-do-porto-05", CIDADE,
       "Rua do Porto, Beira-Rio",
       -22.7305, -47.6553, None, 38, 60.0, perfil="lazer"),
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
    # A explicação acompanha a força do sinal: um score alto tem série harmônica
    # e estalos claros; um score médio é o caso que o operador precisa julgar.
    # O "porquê" varia por evento em vez de repetir a mesma frase.
    if score >= 0.88:
        explicacao = ("fundamental grave de motor (cerca de 88 Hz), série harmônica "
                      "forte e estalos de escape repetidos, assinatura típica de "
                      "escapamento aberto")
    elif score >= 0.80:
        explicacao = ("harmônicos de motor presentes e nível acima do piso do ponto, "
                      "porém com ruído de fundo. Fica dentro do limiar de acionamento")
    else:
        explicacao = ("traços de escapamento presentes, mas com série harmônica fraca "
                      "e intermitente. Abaixo do limiar de acionamento, segue para revisão")
    return Predicao(
        classe=CLASSE_ALVO if score >= 0.5 else "ambiente",
        score=max(scores.values()),
        scores=scores,
        modelo="acustico",
        versao_modelo="acustico/1.2",
        explicacao=explicacao,
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


# Quando o problema acontece, por tipo de ponto. Cada perfil é uma lista de
# horas prováveis (repetição = mais peso) e o peso relativo de fim de semana.
#
# A forma importa mais que o número: um corredor de tráfego satura no fim de
# tarde de dia útil; um polo de lazer satura na madrugada de sexta e sábado. Se
# todos os pontos tivessem o mesmo perfil, o mapa de calor viraria uma mancha
# uniforme — que é justamente o que a prefeitura já tem hoje, e não ajuda a
# escalar equipe. Os perfis são hipóteses de forma, não medição.
PERFIS = {
    # Corredor arterial: pico de deslocamento no fim de tarde, cauda à noite.
    "corredor": {"horas": [17, 18, 18, 19, 19, 20, 20, 21, 22, 12, 7, 8],
                 "peso_fim_de_semana": 1.0},
    # Área central/comercial: fluxo espalhado no dia, ainda forte no início da noite.
    "centro": {"horas": [10, 11, 12, 13, 14, 16, 17, 18, 18, 19, 19, 20, 21],
               "peso_fim_de_semana": 0.7},
    # Residencial: o incômodo que gera requerimento é o da noite e da madrugada.
    "residencial": {"horas": [20, 21, 22, 22, 23, 23, 0, 1, 2],
                    "peso_fim_de_semana": 1.6},
    # Polo de lazer: madrugada, concentrada em sexta e sábado.
    "lazer": {"horas": [22, 23, 23, 0, 0, 1, 1, 2, 3, 19, 20],
              "peso_fim_de_semana": 3.2},
}


def _instante(rng: random.Random, base: datetime, perfil: str) -> float:
    """Um instante nos últimos 21 dias, seguindo o perfil horário do ponto."""
    cfg = PERFIS[perfil]
    peso_fds = cfg["peso_fim_de_semana"]

    # Sorteia o dia com o fim de semana pesado conforme o perfil do ponto.
    candidatos = []
    for dia in range(21):
        data = base - timedelta(days=dia)
        # weekday(): 4=sex, 5=sáb, 6=dom
        peso = peso_fds if data.weekday() in (4, 5) else 1.0
        candidatos.append((data, peso))
    total = sum(p for _, p in candidatos)
    sorteio = rng.random() * total
    acumulado = 0.0
    data = candidatos[0][0]
    for candidato, peso in candidatos:
        acumulado += peso
        if sorteio <= acumulado:
            data = candidato
            break

    hora = rng.choice(cfg["horas"])
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
                instante = _instante(rng, base, no.perfil)
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
    sem_sinal = "piracicaba-sao-dimas-04"

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
        headers={"Authorization": f"Bearer {config.tokens['piracicaba-centro-hospitalar-02']}"},
        json={
            "tipo": "abertura_gabinete",
            "capturado_em": datetime.now(tz=timezone.utc).isoformat(),
            "detalhe": {"sensor": "reed", "duracao_s": 4.2},
        },
    )


def _trafego_e_disparo_conceito(config: ConfigBackend, cliente) -> None:
    """Roadmap modular (docs/DECISIONS.md D15, D16) — dado de demonstração
    para os dois recursos adicionais mediante acionamento no dashboard.

    Reaproveita o perfil horário de PERFIS (mesma lógica dos eventos
    acústicos) em vez de inventar outro — volume de VEÍCULOS totais é ordem de
    grandeza maior que volume de EVENTOS de escapamento, então usa uma escala
    própria, não `no.volume`.

    O de disparo é UM candidato só, de propósito: é protótipo conceitual, não
    o volume de um recurso de produção validado.
    """
    rng = random.Random(SEMENTE + 2)
    tipos_pesos = {"moto": 0.38, "carro": 0.48, "onibus": 0.05, "caminhao": 0.07}
    escala_veiculos_hora = 900  # ordem de grandeza de um corredor urbano — não é medição
    hoje = datetime.now(tz=timezone.utc)

    for no in NOS:
        token = config.tokens[no.id]
        peso_por_hora: dict[int, int] = {}
        for hora in PERFIS[no.perfil]["horas"]:
            peso_por_hora[hora] = peso_por_hora.get(hora, 0) + 1
        pico = max(peso_por_hora.values())

        agregados = []
        for dia_offset in range(7):
            dia = (hoje - timedelta(days=dia_offset)).strftime("%Y-%m-%d")
            for hora, peso in peso_por_hora.items():
                total_hora = int(escala_veiculos_hora * (peso / pico) * rng.uniform(0.7, 1.0))
                for tipo, peso_tipo in tipos_pesos.items():
                    contagem = round(total_hora * peso_tipo)
                    if contagem:
                        agregados.append(
                            {"dia": dia, "hora": hora, "tipo": tipo, "contagem": contagem}
                        )
        if not agregados:
            continue
        resposta = cliente.post(
            "/v1/trafego",
            headers={"Authorization": f"Bearer {token}"},
            json={"agregados": agregados},
        )
        if resposta.status_code != 202:
            raise RuntimeError(
                f"envio de tráfego recusado para {no.id}: {resposta.status_code} {resposta.text}"
            )

    # Disparo (conceito): só um candidato, no nó do polo de lazer noturno —
    # o ponto onde esse tipo de ocorrência faria sentido mencionar.
    no_disparo = next(no for no in NOS if no.perfil == "lazer")
    resposta = cliente.post(
        "/v1/alertas-disparo-conceito",
        headers={"Authorization": f"Bearer {config.tokens[no_disparo.id]}"},
        json={
            "pico_relativo_db": round(rng.uniform(38.0, 52.0), 1),
            "instante_relativo_s": round(rng.uniform(0.1, 0.6), 2),
            "ocorrido_em": (hoje - timedelta(hours=6)).isoformat(),
        },
    )
    if resposta.status_code != 201:
        raise RuntimeError(
            f"alerta de disparo (conceito) recusado: {resposta.status_code} {resposta.text}"
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
        _trafego_e_disparo_conceito(config, cliente)

    print("\nSemeadura concluída — sistema real, cenário de Piracicaba.\n")
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
