"""Contador de tráfego: amostra a câmera em intervalo fixo, classifica por
tipo, agrega.

Diferente de `edge/camera_trigger`, este módulo não espera um evento de som —
roda em paralelo ao pipeline acústico, sempre ligado quando habilitado,
independente de haver ou não escapamento adulterado passando.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from edge.camera_trigger.camera import PANORAMICA, Camera, CameraIndisponivel
from edge.config import ConfigNo
from edge.traffic_counter.agregador import AgregadorTrafego
from edge.traffic_counter.classificador import NENHUM, ClassificadorVeiculo

log = logging.getLogger("ecoar.trafego")


class ContadorTrafego:
    """Vigia a câmera em segundo plano e soma no agregador.

    O quadro capturado é descartado logo depois da classificação — este
    módulo nunca guarda imagem além do instante em que ela é usada para
    contar, e nunca guarda quadro a quadro nem placa.
    """

    def __init__(
        self,
        config: ConfigNo,
        camera: Camera,
        classificador: ClassificadorVeiculo,
        diretorio_quadros: Path | str = "dados/trafego-tmp",
    ) -> None:
        self.config = config.trafego
        self.no_id = config.id
        self._camera = camera
        self._classificador = classificador
        self._diretorio = Path(diretorio_quadros)
        self.agregador = AgregadorTrafego()

        self._parar = threading.Event()
        self._thread: threading.Thread | None = None

    # -- ciclo de vida -----------------------------------------------------

    def iniciar(self) -> None:
        if not self.config.habilitado:
            log.info("contador de tráfego desligado por configuração no nó %s", self.no_id)
            return
        self._camera.abrir()
        self._parar.clear()
        self._thread = threading.Thread(
            target=self._laco, name="ecoar-trafego", daemon=True
        )
        self._thread.start()
        log.info(
            "contador de tráfego ativo no nó %s (cadência %.0f s)",
            self.no_id,
            self.config.cadencia_s,
        )

    def parar(self) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._camera.fechar()

    def __enter__(self) -> "ContadorTrafego":
        self.iniciar()
        return self

    def __exit__(self, *_) -> None:
        self.parar()

    # -- laço de amostragem --------------------------------------------

    def _laco(self) -> None:
        while not self._parar.is_set():
            try:
                self.amostrar_um()
            except Exception:  # noqa: BLE001 — contagem não pode derrubar o nó
                log.exception("falha ao amostrar quadro de tráfego")
            self._parar.wait(self.config.cadencia_s)

    def amostrar_um(self) -> None:
        """Captura um quadro, classifica, soma no agregador."""
        destino = self._diretorio / f"quadro-{int(time.time() * 1000)}.png"
        try:
            captura = self._camera.capturar(destino, PANORAMICA)
        except CameraIndisponivel as erro:
            log.warning("câmera indisponível para contagem de tráfego: %s", erro)
            return
        finally:
            Path(destino).unlink(missing_ok=True)

        classificacao = self._classificador.classificar(captura)
        if classificacao.tipo != NENHUM:
            self.agregador.somar(classificacao.tipo, instante=captura.timestamp)
