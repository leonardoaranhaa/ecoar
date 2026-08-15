"""Detector de violação: vigia os sensores e dispara alerta antes da remoção.

A ordem de ação sob violação não é arbitrária — parte do princípio de que o
tempo de vida restante do equipamento pode ser de segundos:

1. dispara captura de imagem (a tentativa de furto vira a própria evidência);
2. envia alerta ao backend com **prioridade máxima**, à frente de qualquer
   pacote acústico pendente;
3. registra localmente, caso a transmissão falhe e o equipamento seja
   recuperado depois.

O alerta de violação trafega em canal separado do evento acústico (D14): é
ocorrência patrimonial, não fiscalização.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from edge.config import ConfigNo
from edge.tamper_detection.sensores import (
    SensorAbertura,
    SensorAlimentacao,
    SensorInercial,
)

log = logging.getLogger("ecoar.tamper")

IMPACTO = "impacto"
INCLINACAO = "inclinacao"
MOVIMENTO = "movimento"
ABERTURA = "abertura_gabinete"
QUEDA_ENERGIA = "queda_energia"


@dataclass(frozen=True)
class AlertaViolacao:
    tipo: str
    no_id: str
    timestamp: float
    detalhe: dict
    imagem: str | None = None

    def como_dict(self) -> dict:
        return {
            "tipo": self.tipo,
            "no_id": self.no_id,
            "timestamp": self.timestamp,
            "capturado_em": datetime.fromtimestamp(
                self.timestamp, tz=timezone.utc
            ).isoformat(),
            "detalhe": self.detalhe,
            "imagem": self.imagem,
            "canal": "violacao_patrimonial",
        }


@dataclass
class ContadoresTamper:
    alertas: dict = field(default_factory=dict)

    def somar(self, tipo: str) -> None:
        self.alertas[tipo] = self.alertas.get(tipo, 0) + 1


class DetectorViolacao:
    """Vigia os sensores em segundo plano e chama `ao_alerta` sob violação.

    `ao_alerta` é injetado pelo nó e faz a captura + enfileiramento com
    prioridade máxima. O detector não conhece a fila nem a câmera — só decide
    que houve violação e qual tipo.
    """

    def __init__(
        self,
        config: ConfigNo,
        inercial: SensorInercial,
        abertura: SensorAbertura,
        alimentacao: SensorAlimentacao,
        ao_alerta,
        capturar_imagem=None,
        registro_local: Path | str | None = None,
    ) -> None:
        self.config = config.tamper
        self.no_id = config.id
        self._inercial = inercial
        self._abertura = abertura
        self._alimentacao = alimentacao
        self._ao_alerta = ao_alerta
        self._capturar_imagem = capturar_imagem
        self._registro_local = Path(registro_local) if registro_local else None

        self.contadores = ContadoresTamper()
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None

        self._inclinacao_ref: float | None = None
        self._manutencao_ate = 0.0
        # Estado de borda: só dispara na transição, não a cada leitura enquanto
        # a condição persiste. Sem isso, uma tampa aberta geraria um alerta a
        # cada 0,1 s.
        self._aberto_antes = False
        self._na_bateria_antes = False
        self._em_manutencao_antes = False

    # -- ciclo de vida ---------------------------------------------------

    def iniciar(self) -> None:
        for sensor in (self._inercial, self._abertura, self._alimentacao):
            sensor.abrir()
        self._calibrar_referencia()
        self._parar.clear()
        self._thread = threading.Thread(
            target=self._laco, name="ecoar-tamper", daemon=True
        )
        self._thread.start()
        log.info("antifurto ativo no nó %s", self.no_id)

    def parar(self) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        for sensor in (self._inercial, self._abertura, self._alimentacao):
            sensor.fechar()

    def __enter__(self) -> "DetectorViolacao":
        self.iniciar()
        return self

    def __exit__(self, *_) -> None:
        self.parar()

    def _calibrar_referencia(self) -> None:
        """A posição de instalação é a referência de inclinação.

        O nó pode ser montado torto de propósito; o que importa é a MUDANÇA em
        relação a como foi instalado, não o desvio absoluto da vertical.
        """
        leitura = self._inercial.ler()
        self._inclinacao_ref = leitura.inclinacao_graus
        log.info("referência de inclinação: %.1f°", self._inclinacao_ref)

    # -- modo manutenção -------------------------------------------------

    def entrar_manutencao(self, segundos: float | None = None) -> float:
        """Suspende alertas por um tempo, para abrir o gabinete legitimamente.

        Expira sozinho: não existe forma de deixar o alarme desligado por
        esquecimento. O teto vem da configuração.
        """
        duracao = min(segundos or self.config.manutencao_max_s, self.config.manutencao_max_s)
        self._manutencao_ate = time.time() + duracao
        log.warning("modo manutenção ligado por %.0f s no nó %s", duracao, self.no_id)
        return self._manutencao_ate

    def sair_manutencao(self) -> None:
        self._manutencao_ate = 0.0
        self._calibrar_referencia()  # a montagem pode ter mudado durante a manutenção

    @property
    def em_manutencao(self) -> bool:
        return time.time() < self._manutencao_ate

    # -- laço de vigilância ----------------------------------------------

    def _laco(self) -> None:
        while not self._parar.is_set():
            try:
                self.verificar_uma_vez()
            except Exception:  # noqa: BLE001 — o antifurto não pode se auto-derrubar
                log.exception("falha na verificação de violação")
            self._parar.wait(self.config.intervalo_leitura_s)

    def verificar_uma_vez(self) -> list[AlertaViolacao]:
        """Uma passada por todos os sensores. Devolve os alertas disparados."""
        disparados: list[AlertaViolacao] = []
        em_manutencao = self.em_manutencao

        # A manutenção acabou de terminar (por prazo ou por sair_manutencao()):
        # rearma a detecção de borda. Sem isso, uma condição que já estava
        # ativa QUANDO a manutenção suspendia os alertas (tampa aberta, nó na
        # bateria) nunca dispararia depois — a borda foi consumida em silêncio
        # durante a supressão, e só uma nova transição (fechar e abrir de novo)
        # acionaria o alarme. Isso violaria a garantia do módulo: manutenção
        # expirada com violação em curso precisa soar, não ficar muda até
        # alguém mexer de novo no sensor.
        if self._em_manutencao_antes and not em_manutencao:
            self._aberto_antes = False
            self._na_bateria_antes = False
        self._em_manutencao_antes = em_manutencao

        leitura = self._inercial.ler()

        # Impacto: pico de aceleração acima da gravidade + limiar.
        if leitura.magnitude_g >= self.config.impacto_g:
            disparados.append(
                self._alerta(IMPACTO, {"magnitude_g": round(leitura.magnitude_g, 2)}, em_manutencao)
            )

        # Inclinação: desvio sustentado em relação à posição de instalação.
        if self._inclinacao_ref is not None:
            desvio = abs(leitura.inclinacao_graus - self._inclinacao_ref)
            if desvio >= self.config.inclinacao_graus:
                disparados.append(
                    self._alerta(
                        INCLINACAO,
                        {"desvio_graus": round(desvio, 1), "referencia_graus": round(self._inclinacao_ref, 1)},
                        em_manutencao,
                    )
                )

        # Movimento: rotação contínua — equipamento sendo carregado.
        rotacao = max(abs(leitura.gx), abs(leitura.gy), abs(leitura.gz))
        if rotacao >= self.config.rotacao_dps:
            disparados.append(
                self._alerta(MOVIMENTO, {"rotacao_dps": round(rotacao, 1)}, em_manutencao)
            )

        # Abertura da tampa — só na borda de fechado→aberto.
        aberto = self._abertura.aberto()
        if aberto and not self._aberto_antes:
            disparados.append(self._alerta(ABERTURA, {}, em_manutencao))
        self._aberto_antes = aberto

        # Queda de energia — só na transição para bateria.
        na_bateria = self._alimentacao.na_bateria()
        if na_bateria and not self._na_bateria_antes:
            disparados.append(
                self._alerta(
                    QUEDA_ENERGIA,
                    {"bateria_pct": self._alimentacao.bateria_pct()},
                    em_manutencao,
                )
            )
        self._na_bateria_antes = na_bateria

        return [a for a in disparados if a is not None]

    def _alerta(self, tipo: str, detalhe: dict, em_manutencao: bool) -> AlertaViolacao | None:
        if em_manutencao:
            log.debug("violação %s ignorada: modo manutenção", tipo)
            return None

        self.contadores.somar(tipo)
        imagem = None

        # A tentativa de furto vira a própria evidência: fotografa ANTES de tudo,
        # porque o equipamento pode não estar mais lá em seguida.
        if self._capturar_imagem is not None:
            try:
                imagem = self._capturar_imagem(tipo)
            except Exception as erro:  # noqa: BLE001
                log.error("captura sob violação falhou: %s", erro)

        alerta = AlertaViolacao(
            tipo=tipo,
            no_id=self.no_id,
            timestamp=time.time(),
            detalhe=detalhe,
            imagem=imagem,
        )

        # Registro local primeiro: se a transmissão falhar e o equipamento for
        # recuperado, o alerta ainda está no disco.
        self._registrar_local(alerta)

        try:
            self._ao_alerta(alerta)  # enfileira com prioridade máxima
        except Exception as erro:  # noqa: BLE001
            log.error("enfileiramento do alerta %s falhou: %s", tipo, erro)

        log.warning("VIOLAÇÃO no nó %s: %s %s", self.no_id, tipo, detalhe)
        return alerta

    def _registrar_local(self, alerta: AlertaViolacao) -> None:
        if self._registro_local is None:
            return
        try:
            self._registro_local.parent.mkdir(parents=True, exist_ok=True)
            with self._registro_local.open("a", encoding="utf-8") as arquivo:
                arquivo.write(json.dumps(alerta.como_dict(), ensure_ascii=False) + "\n")
        except OSError as erro:
            log.error("registro local do alerta falhou: %s", erro)
