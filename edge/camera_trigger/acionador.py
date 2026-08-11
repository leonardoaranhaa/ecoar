"""Junta a decisão à câmera: avalia, e aciona se for o caso."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from edge.audio_capture.spl import EstimativaSPL
from edge.camera_trigger.camera import (
    PANORAMICA,
    PLACA,
    Camera,
    CameraIndisponivel,
    CapturaImagem,
    criar_camera,
)
from edge.camera_trigger.decisao import Acao, Decisao, decidir
from edge.classifier.base import Predicao
from edge.config import ConfigNo
from edge.localization.doa import EstimativaDOA

log = logging.getLogger("ecoar.camera_trigger")


@dataclass(frozen=True)
class ResultadoAcionamento:
    decisao: Decisao
    capturas: tuple[CapturaImagem, ...] = ()
    falha_de_captura: str | None = None
    extras: dict[str, object] = field(default_factory=dict)

    def como_dict(self) -> dict[str, object]:
        return {
            "decisao": self.decisao.como_dict(),
            "capturas": [captura.como_dict() for captura in self.capturas],
            "falha_de_captura": self.falha_de_captura,
        }


class AcionadorCamera:
    def __init__(
        self,
        config: ConfigNo,
        camera: Camera | None = None,
        diretorio: Path | None = None,
    ) -> None:
        self.config = config
        self.camera = camera if camera is not None else criar_camera(config.camera)
        self.diretorio = Path(diretorio or config.camera.diretorio)

    def abrir(self) -> None:
        self.camera.abrir()

    def fechar(self) -> None:
        self.camera.fechar()

    def __enter__(self) -> "AcionadorCamera":
        self.abrir()
        return self

    def __exit__(self, *_) -> None:
        self.fechar()

    def processar(
        self,
        evento_id: str,
        predicao: Predicao | None,
        doa: EstimativaDOA | None,
        spl: EstimativaSPL | None,
    ) -> ResultadoAcionamento:
        decisao = decidir(predicao, doa, spl, self.config.gatilho)

        if decisao.acao is not Acao.ACIONAR:
            log.info("evento %s: %s — %s", evento_id, decisao.acao.value, decisao.motivo)
            return ResultadoAcionamento(decisao=decisao)

        pasta = self.diretorio / evento_id
        try:
            capturas = (
                self.camera.capturar(pasta / f"{PLACA}.png", PLACA),
                self.camera.capturar(pasta / f"{PANORAMICA}.png", PANORAMICA),
            )
        except CameraIndisponivel as erro:
            # A câmera falhar não pode apagar o evento: o áudio, o ângulo e o
            # score continuam valendo, e a falha entra na evidência.
            log.error("evento %s: câmera falhou (%s) — evento segue sem imagem", evento_id, erro)
            return ResultadoAcionamento(decisao=decisao, falha_de_captura=str(erro))

        log.info(
            "evento %s: acionado — %d imagens em %s", evento_id, len(capturas), pasta
        )
        return ResultadoAcionamento(decisao=decisao, capturas=capturas)
