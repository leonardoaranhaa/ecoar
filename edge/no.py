"""Orquestrador do nó: do som ao pacote na fila de envio.

    captura → detecção de pico → janela do evento
        → localização → classificação → decisão → câmera
        → pacote de evidência → fila de uplink

Duas separações de thread que não são detalhe de implementação:

**A captura nunca espera pelo processamento.** Localizar, classificar e montar
o pacote leva centenas de milissegundos; fazer isso na thread que lê o áudio
perderia blocos, e blocos perdidos são evidência perdida. A detecção só empurra
o instante do pico para uma fila; quem processa é outra thread.

**O envio nunca espera pela captura.** O uplink roda sozinho, esvaziando a fila
persistente no ritmo que o 4G permitir.

Nada aqui decide se houve infração — isso é do `camera_trigger`, com política
versionada. Este módulo só encadeia.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from edge.audio_capture.captura import CapturaAudio
from edge.audio_capture.fontes import BlocoAudio
from edge.audio_capture.spl import EstimativaSPL
from edge.camera_trigger import AcionadorCamera
from edge.classifier import ClassificadorIndisponivel, criar_classificador
from edge.config import ConfigNo
from edge.evidence_packager import montar_pacote
from edge.geometria import ArrayCircular
from edge.localization import Localizador
from edge.uplink import ClienteBackend, FilaEnvio, Heartbeat, Remetente

log = logging.getLogger("ecoar.no")

# Tempo mínimo entre dois eventos. Sem isso, uma única passagem barulhenta
# geraria uma dezena de eventos sobrepostos com o mesmo áudio.
JANELA_MORTA_S = 4.0


@dataclass
class Contadores:
    picos: int = 0
    processados: int = 0
    acionados: int = 0
    ambiguos: int = 0
    descartados: int = 0
    falhas: int = 0
    detalhes: dict = field(default_factory=dict)

    def como_dict(self) -> dict:
        return {
            "picos_detectados": self.picos,
            "eventos_processados": self.processados,
            "acionados": self.acionados,
            "ambiguos": self.ambiguos,
            "descartados": self.descartados,
            "falhas": self.falhas,
        }


class No:
    """Um nó de campo em operação."""

    def __init__(self, config: ConfigNo, fila: FilaEnvio | None = None) -> None:
        self.config = config
        self.contadores = Contadores()

        self.captura = CapturaAudio(config, ao_bloco=self._ao_bloco)
        self.localizador = Localizador(ArrayCircular.de_config(config.array))
        self.classificador = criar_classificador(config)
        self.acionador = AcionadorCamera(config)

        self.fila = fila or FilaEnvio(
            config.uplink.fila, tentativas_maximas=config.uplink.tentativas_maximas
        )
        self.diretorio_pacotes = Path(config.uplink.diretorio_pacotes)

        self._picos: queue.Queue[float] = queue.Queue(maxsize=64)
        self._parar = threading.Event()
        self._thread_eventos: threading.Thread | None = None
        self._ultimo_pico = 0.0
        self._sequencial = 0
        self._remetente: Remetente | None = None
        self._heartbeat: Heartbeat | None = None

    # -- ciclo de vida ---------------------------------------------------

    def iniciar(self, com_uplink: bool = True) -> None:
        log.info(
            "nó %s subindo em modo=%s · classificador=%s %s",
            self.config.id,
            self.config.modo,
            self.classificador.nome,
            self.classificador.versao,
        )
        self.acionador.abrir()
        self.captura.iniciar()

        self._parar.clear()
        self._thread_eventos = threading.Thread(
            target=self._laco_eventos, name="ecoar-eventos", daemon=True
        )
        self._thread_eventos.start()

        if com_uplink:
            cliente = ClienteBackend(self.config.uplink)
            self._remetente = Remetente(
                self.fila,
                cliente,
                intervalo_s=self.config.uplink.intervalo_s,
                apagar_apos_envio=self.config.uplink.apagar_apos_envio,
            )
            self._remetente.iniciar()
            self._heartbeat = Heartbeat(
                self.fila, self.config.uplink.heartbeat_s, self.estado
            )
            self._heartbeat.iniciar()

    def parar(self) -> None:
        self._parar.set()
        if self._thread_eventos is not None:
            self._thread_eventos.join(timeout=40.0)
            self._thread_eventos = None
        if self._heartbeat is not None:
            self._heartbeat.parar()
            self._heartbeat = None
        if self._remetente is not None:
            self._remetente.parar()
            self._remetente = None
        self.captura.parar()
        self.acionador.fechar()
        log.info("nó encerrado: %s", self.contadores.como_dict())

    def __enter__(self) -> "No":
        self.iniciar()
        return self

    def __exit__(self, *_) -> None:
        self.parar()

    def estado(self) -> dict:
        return {
            "no_id": self.config.id,
            "modo": self.config.modo,
            "captura": self.captura.estado(),
            "classificador": self.classificador.identificacao(),
            "fila_uplink": self.fila.estado(),
            **self.contadores.como_dict(),
        }

    # -- detecção --------------------------------------------------------

    def _ao_bloco(self, bloco: BlocoAudio, spl: EstimativaSPL) -> None:
        """Pré-gatilho barato, rodando na thread de captura.

        O SPL não decide se houve infração — ele decide se vale a pena gastar
        processamento classificando. A decisão de verdade é do `camera_trigger`.
        """
        if spl.db < self.config.gatilho.spl_db_minimo:
            return

        instante = bloco.timestamp + bloco.duracao_s / 2.0
        if instante - self._ultimo_pico < JANELA_MORTA_S:
            return
        self._ultimo_pico = instante
        self.contadores.picos += 1

        try:
            self._picos.put_nowait(instante)
        except queue.Full:
            # Fila cheia significa processamento mais lento que a chegada de
            # eventos. Perder o pico é ruim; travar a captura é pior.
            self.contadores.falhas += 1
            log.warning("fila de eventos cheia: pico em %.3f descartado", instante)

    # -- processamento ---------------------------------------------------

    def _laco_eventos(self) -> None:
        while not self._parar.is_set():
            try:
                instante = self._picos.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.processar_evento(instante)
            except Exception:  # noqa: BLE001 — um evento ruim não derruba o nó
                self.contadores.falhas += 1
                log.exception("falha ao processar evento em %.3f", instante)

    def processar_evento(self, instante_pico: float) -> str | None:
        """Percorre a cadeia inteira para um pico. Devolve o id do evento."""
        evento_id = self._novo_id(instante_pico)
        log.info("[%s] pico detectado, aguardando janela do evento", evento_id)

        evento = self.captura.janela_evento(
            instante_pico,
            antes=self.config.gatilho.janela_antes_s,
            depois=self.config.gatilho.janela_depois_s,
        )
        log.info(
            "[%s] janela de %.1f s recuperada · SPL estimado %.1f dB",
            evento_id,
            evento.janela.duracao_s,
            evento.spl.db,
        )

        doa = self.localizador.estimar_janela(evento.janela)
        log.info(
            "[%s] ângulo %.1f° ±%.1f° (confiança %.2f)",
            evento_id,
            doa.azimute_graus,
            doa.margem_graus,
            doa.confianca,
        )

        try:
            predicao = self.classificador.classificar(
                evento.amostras, evento.taxa_amostragem
            )
            log.info(
                "[%s] classe %s · score do alvo %.2f [%s]",
                evento_id,
                predicao.classe,
                predicao.score_alvo,
                predicao.versao_modelo,
            )
        except ClassificadorIndisponivel as erro:
            # Fail-closed: sem classificador, o evento vira ambíguo — nunca
            # descartado em silêncio nem acionado por precaução.
            predicao = None
            log.error("[%s] classificador indisponível: %s", evento_id, erro)

        acionamento = self.acionador.processar(evento_id, predicao, doa, evento.spl)
        decisao = acionamento.decisao
        log.info("[%s] decisão: %s — %s", evento_id, decisao.acao.value, decisao.motivo)

        self.contadores.processados += 1
        if decisao.acao.value == "acionar":
            self.contadores.acionados += 1
        elif decisao.acao.value == "ambiguo":
            self.contadores.ambiguos += 1
        else:
            self.contadores.descartados += 1
            log.info("[%s] descartado: nenhum pacote gerado", evento_id)
            return evento_id

        caminho = montar_pacote(
            config=self.config,
            evento_id=evento_id,
            evento=evento,
            doa=doa,
            predicao=predicao,
            acionamento=acionamento,
            destino=self.diretorio_pacotes / f"{evento_id}.ecoar",
        )
        self.fila.enfileirar_evento(caminho)
        log.info(
            "[%s] pacote %s na fila de envio (%d pendentes)",
            evento_id,
            caminho.name,
            self.fila.pendentes(),
        )
        return evento_id

    def _novo_id(self, instante: float) -> str:
        self._sequencial += 1
        marca = datetime.fromtimestamp(instante, tz=timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"{self.config.id}-{marca}-{self._sequencial:04d}"

    # -- apoio para bancada ----------------------------------------------

    def aguardar_ocioso(self, timeout: float = 60.0) -> bool:
        """Espera a fila de picos esvaziar. Usado em ensaio, não em operação."""
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            if self._picos.empty():
                time.sleep(0.2)
                if self._picos.empty():
                    return True
            time.sleep(0.1)
        return False
