"""Apoio comum aos testes de backend: gera pacotes de evidência de verdade.

Os testes de ingestão não usam JSON inventado à mão. Eles montam pacotes com o
mesmo código do nó, porque é isso que o backend vai receber em campo — e porque
um teste que constrói o pacote à mão deixa de detectar divergência entre as duas
pontas.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from edge.audio_capture.buffer import Janela
from edge.audio_capture.captura import JanelaEvento
from edge.audio_capture.spl import estimar
from edge.camera_trigger import AcionadorCamera
from edge.classifier.base import CLASSE_ALVO, CLASSES, Predicao
from edge.config import ConfigCalibracao, ConfigNo, de_dict
from edge.evidence_packager import montar_pacote
from edge.localization.doa import EstimativaDOA
from tests.conftest import config_base

TAXA = 16000


def config_no(no_id: str = "no-teste-01", **extras) -> ConfigNo:
    dados = config_base()
    dados["no"]["id"] = no_id
    dados["no"]["geolocalizacao"] = {"latitude": -22.31, "longitude": -49.06}
    dados.update(extras)
    return de_dict(dados)


def _janela(instante_pico: float) -> JanelaEvento:
    t = np.arange(TAXA * 2) / TAXA
    amostras = (0.5 * np.sin(2 * np.pi * 1000 * t))[:, None].repeat(4, axis=1)
    amostras = amostras.astype(np.float32)
    return JanelaEvento(
        janela=Janela(amostras, TAXA, instante_pico - 1.0, instante_pico + 1.0),
        spl=estimar(amostras, TAXA, ConfigCalibracao()),
        instante_pico=instante_pico,
        sonometro=None,
        motivo_sem_sonometro="sem instrumento em modo de triagem",
    )


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
        descritores={"f0_hz": 84.0},
    )


def gerar_pacote(
    destino: Path,
    no_id: str = "no-teste-01",
    evento_id: str = "evt-0001",
    score: float = 0.93,
    azimute: float = 12.0,
    instante_pico: float = 1_770_000_000.0,
    config: ConfigNo | None = None,
) -> Path:
    config = config or config_no(no_id)
    evento = _janela(instante_pico)
    predicao = _predicao(score)
    doa = EstimativaDOA(
        azimute_graus=azimute,
        confianca=0.95,
        margem_graus=2.0,
        residuo_us=3.0,
        qualidade_media=0.99,
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
