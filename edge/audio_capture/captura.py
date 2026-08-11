"""Serviço de captura — o que os módulos seguintes consomem.

Junta fonte de áudio, buffer circular, estimativa de SPL e instrumento de
medição atrás de uma interface só. `localization`, `classifier` e
`evidence_packager` falam com esta classe e não sabem se o áudio veio de um
array no poste, de um `.wav` de campo ou de uma cena sintética de bancada.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from edge.audio_capture.buffer import BufferCircular, Janela, JanelaIndisponivel
from edge.audio_capture.fontes import BlocoAudio, FonteAudio, criar_fonte
from edge.audio_capture.sonometro import (
    InstrumentoIndisponivel,
    LeituraSonometro,
    SonometroReader,
    criar_sonometro,
)
from edge.audio_capture.spl import EstimativaSPL, estimar
from edge.config import ConfigNo

log = logging.getLogger("ecoar.audio_capture")

ANTES_PADRAO_S = 10.0
DEPOIS_PADRAO_S = 10.0


@dataclass(frozen=True)
class JanelaEvento:
    """Trecho de áudio de um evento, com tudo que o pacote de evidência precisa."""

    janela: Janela
    spl: EstimativaSPL
    instante_pico: float
    sonometro: LeituraSonometro | None
    motivo_sem_sonometro: str | None
    antes_pedido_s: float = ANTES_PADRAO_S
    depois_pedido_s: float = DEPOIS_PADRAO_S

    @property
    def antes_obtido_s(self) -> float:
        return self.instante_pico - self.janela.inicio

    @property
    def truncado(self) -> bool:
        """Faltou pré-registro — normal logo após o nó subir, e declarado."""
        return self.antes_obtido_s < self.antes_pedido_s - 0.05

    @property
    def amostras(self) -> np.ndarray:
        return self.janela.amostras

    @property
    def taxa_amostragem(self) -> int:
        return self.janela.taxa_amostragem

    def como_dict(self) -> dict[str, object]:
        return {
            "instante_pico": self.instante_pico,
            "inicio": self.janela.inicio,
            "fim": self.janela.fim,
            "duracao_s": round(self.janela.duracao_s, 3),
            "taxa_amostragem": self.janela.taxa_amostragem,
            "canais": self.janela.canais,
            "pre_registro_s": {
                "pedido": round(self.antes_pedido_s, 2),
                "obtido": round(self.antes_obtido_s, 2),
                "truncado": self.truncado,
            },
            "spl_estimado": self.spl.como_dict(),
            "medicao_instrumento": (
                self.sonometro.como_dict() if self.sonometro else None
            ),
            "motivo_sem_instrumento": self.motivo_sem_sonometro,
        }


class CapturaAudio:
    """Captura contínua em segundo plano, com janela recuperável do passado."""

    def __init__(
        self,
        config: ConfigNo,
        fonte: FonteAudio | None = None,
        sonometro: SonometroReader | None = None,
        ao_bloco: Callable[[BlocoAudio, EstimativaSPL], None] | None = None,
    ) -> None:
        self.config = config
        self.fonte = fonte if fonte is not None else criar_fonte(config)
        self.sonometro = sonometro if sonometro is not None else criar_sonometro(config)
        self._ao_bloco = ao_bloco

        self.buffer = BufferCircular(
            canais=config.audio.canais,
            taxa_amostragem=config.audio.taxa_amostragem,
            segundos=config.audio.buffer_segundos,
        )

        self._thread: threading.Thread | None = None
        self._parar = threading.Event()
        self._spl_atual: EstimativaSPL | None = None
        self._falha: BaseException | None = None
        self._fonte_terminou = False
        self._blocos = 0
        self._lock = threading.Lock()

    # -- ciclo de vida ---------------------------------------------------

    def iniciar(self) -> None:
        if self._thread is not None:
            raise RuntimeError("captura já está rodando")
        self.fonte.abrir()
        self.sonometro.abrir()
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name="ecoar-captura", daemon=True)
        self._thread.start()
        log.info(
            "captura iniciada: %s, %d canais a %d Hz, buffer de %.0f s",
            type(self.fonte).__name__,
            self.config.audio.canais,
            self.config.audio.taxa_amostragem,
            self.config.audio.buffer_segundos,
        )

    def parar(self, timeout: float = 5.0) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        self.fonte.fechar()
        self.sonometro.fechar()
        log.info("captura encerrada após %d blocos", self._blocos)

    def __enter__(self) -> "CapturaAudio":
        self.iniciar()
        return self

    def __exit__(self, *_) -> None:
        self.parar()

    def _laco(self) -> None:
        try:
            while not self._parar.is_set():
                bloco = self.fonte.ler()
                if bloco is None:
                    self._fonte_terminou = True
                    log.info("fonte de áudio terminou")
                    return
                self.buffer.escrever(bloco.amostras, bloco.timestamp)
                spl = estimar(
                    bloco.amostras,
                    bloco.taxa_amostragem,
                    self.config.audio.calibracao,
                )
                with self._lock:
                    self._spl_atual = spl
                    self._blocos += 1
                if self._ao_bloco is not None:
                    self._ao_bloco(bloco, spl)
        except BaseException as erro:  # noqa: BLE001 — a falha precisa sobreviver à thread
            self._falha = erro
            log.exception("captura falhou")

    # -- estado ----------------------------------------------------------

    @property
    def rodando(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def fonte_terminou(self) -> bool:
        return self._fonte_terminou

    def verificar_saude(self) -> None:
        """Propaga falha da thread de captura. Fail-closed: quem chama precisa saber."""
        if self._falha is not None:
            raise RuntimeError("thread de captura falhou") from self._falha

    def spl_atual(self) -> EstimativaSPL | None:
        with self._lock:
            return self._spl_atual

    def aguardar_primeiro_bloco(self, timeout: float = 5.0) -> bool:
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            self.verificar_saude()
            with self._lock:
                if self._blocos > 0:
                    return True
            if self._fonte_terminou:
                return False
            time.sleep(0.01)
        return False

    def estado(self) -> dict[str, object]:
        """Resumo para log de inicialização e para o heartbeat do nó."""
        spl = self.spl_atual()
        return {
            "rodando": self.rodando,
            "blocos_lidos": self._blocos,
            "fonte": self.fonte.descricao(),
            "instrumento": self.sonometro.info().como_dict(),
            "spl_estimado_db": round(spl.db, 2) if spl else None,
            "falha": repr(self._falha) if self._falha else None,
        }

    # -- leitura ---------------------------------------------------------

    def ler_sonometro(self) -> tuple[LeituraSonometro | None, str | None]:
        """(leitura, motivo da ausência). Nunca inventa um valor.

        Em `modo=triagem` a ausência é o caso normal: não há instrumento
        certificado instalado, e a evidência registra isso explicitamente.
        """
        try:
            return self.sonometro.ler_db(), None
        except InstrumentoIndisponivel as erro:
            return None, str(erro)

    def janela_evento(
        self,
        instante_pico: float,
        antes: float = ANTES_PADRAO_S,
        depois: float = DEPOIS_PADRAO_S,
        timeout: float = 30.0,
    ) -> JanelaEvento:
        """Recupera o trecho em volta do pico, esperando o "depois" ser capturado.

        `antes` só é recuperável porque o buffer circular já guardava o passado
        — é a razão de o módulo existir.
        """
        fim = instante_pico + depois
        if not self.buffer.aguardar_ate(fim, timeout=timeout):
            self.verificar_saude()
            raise JanelaIndisponivel(
                f"o áudio posterior ao pico não chegou em {timeout:.0f} s "
                f"(faltavam {depois:.1f} s após o pico)"
            )

        # Trunca em vez de perder: um pré-registro menor que o pedido continua
        # sendo evidência, e o quanto faltou vai declarado no pacote.
        janela = self.buffer.janela(instante_pico - antes, fim, truncar=True)
        spl = estimar(janela.amostras, janela.taxa_amostragem, self.config.audio.calibracao)
        leitura, motivo = self.ler_sonometro()

        evento = JanelaEvento(
            janela=janela,
            spl=spl,
            instante_pico=instante_pico,
            sonometro=leitura,
            motivo_sem_sonometro=motivo,
            antes_pedido_s=antes,
            depois_pedido_s=depois,
        )
        if evento.truncado:
            log.warning(
                "evento em %.3f: pré-registro de %.1f s em vez dos %.1f s pedidos",
                instante_pico,
                evento.antes_obtido_s,
                antes,
            )
        return evento

    def ultimos(self, segundos: float) -> Janela:
        return self.buffer.ultimos(segundos)
