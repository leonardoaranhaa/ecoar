"""Buffer circular de áudio multicanal.

Mantém sempre os últimos N segundos em memória. É o que torna possível
recuperar o áudio de ANTES do pico: quando o sistema percebe o evento, o começo
dele já passou.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np


class JanelaIndisponivel(LookupError):
    """A janela pedida não está (ou não está mais) no buffer."""


@dataclass(frozen=True)
class Janela:
    """Trecho extraído do buffer, com o tempo real do que foi entregue."""

    amostras: np.ndarray  # (n, canais), float32
    taxa_amostragem: int
    inicio: float  # epoch do primeiro sample
    fim: float  # epoch logo após o último sample

    @property
    def duracao_s(self) -> float:
        return len(self.amostras) / self.taxa_amostragem

    @property
    def canais(self) -> int:
        return int(self.amostras.shape[1])


class BufferCircular:
    """Anel de amostras com mapeamento índice ↔ tempo.

    O relógio da placa de som e o relógio do sistema andam em ritmos levemente
    diferentes. Em vez de fingir que não, o buffer guarda uma âncora
    (índice global, instante) atualizada a cada escrita e converte tempo por
    ela — o erro fica limitado a um bloco, não acumula ao longo de horas.
    """

    def __init__(
        self,
        canais: int,
        taxa_amostragem: int,
        segundos: float,
        dtype: type = np.float32,
    ) -> None:
        if canais < 1:
            raise ValueError("canais precisa ser pelo menos 1")
        if taxa_amostragem <= 0:
            raise ValueError("taxa_amostragem precisa ser maior que zero")
        if segundos <= 0:
            raise ValueError("segundos precisa ser maior que zero")

        self.canais = int(canais)
        self.taxa_amostragem = int(taxa_amostragem)
        self.capacidade = int(round(taxa_amostragem * segundos))
        self._dados = np.zeros((self.capacidade, self.canais), dtype=dtype)
        self._total = 0  # amostras já escritas desde o início
        self._ancora_indice = 0
        self._ancora_t: float | None = None
        self._lock = threading.RLock()
        self._novo_dado = threading.Condition(self._lock)

    # -- escrita ---------------------------------------------------------

    def escrever(self, bloco: np.ndarray, timestamp: float) -> None:
        """Grava um bloco. `timestamp` é o instante da PRIMEIRA amostra dele."""
        bloco = np.asarray(bloco)
        if bloco.ndim != 2 or bloco.shape[1] != self.canais:
            raise ValueError(
                f"bloco precisa ter formato (n, {self.canais}), recebi {bloco.shape}"
            )
        if len(bloco) == 0:
            return

        with self._lock:
            # Bloco maior que o anel: só os últimos `capacidade` cabem, e o
            # começo é descartado — mas a âncora precisa apontar para a primeira
            # amostra que sobreviveu, não para a primeira que chegou.
            descartadas = max(0, len(bloco) - self.capacidade)
            gravar = bloco[descartadas:]
            indice0 = self._total + descartadas
            instante0 = timestamp + descartadas / self.taxa_amostragem

            # Invariante do anel: a amostra de índice global g mora sempre em
            # g % capacidade. Toda leitura depende disso.
            inicio = indice0 % self.capacidade
            fim = inicio + len(gravar)
            if fim <= self.capacidade:
                self._dados[inicio:fim] = gravar
            else:
                corte = self.capacidade - inicio
                self._dados[inicio:] = gravar[:corte]
                self._dados[: fim - self.capacidade] = gravar[corte:]

            self._total = indice0 + len(gravar)
            self._ancora_indice = indice0
            self._ancora_t = instante0
            self._novo_dado.notify_all()

    # -- tempo -----------------------------------------------------------

    def _tempo_de(self, indice: int) -> float:
        assert self._ancora_t is not None
        return self._ancora_t + (indice - self._ancora_indice) / self.taxa_amostragem

    def _indice_de(self, instante: float) -> int:
        assert self._ancora_t is not None
        return self._ancora_indice + int(
            round((instante - self._ancora_t) * self.taxa_amostragem)
        )

    @property
    def vazio(self) -> bool:
        with self._lock:
            return self._total == 0

    def intervalo_disponivel(self) -> tuple[float, float]:
        """(instante mais antigo retido, instante logo após a última amostra)."""
        with self._lock:
            if self._ancora_t is None:
                raise JanelaIndisponivel("buffer ainda não recebeu nenhuma amostra")
            mais_antigo = max(0, self._total - self.capacidade)
            return self._tempo_de(mais_antigo), self._tempo_de(self._total)

    def aguardar_ate(self, instante: float, timeout: float | None = None) -> bool:
        """Espera o buffer alcançar `instante`. Devolve False se estourar o timeout."""
        with self._novo_dado:
            restante = timeout
            while True:
                if self._ancora_t is not None and self._tempo_de(self._total) >= instante:
                    return True
                if restante is not None and restante <= 0:
                    return False
                antes = time.monotonic()
                self._novo_dado.wait(restante if restante is not None else 0.5)
                if restante is not None:
                    restante -= time.monotonic() - antes

    # -- leitura ---------------------------------------------------------

    def janela(self, inicio: float, fim: float) -> Janela:
        """Extrai o trecho [inicio, fim). Erro se saiu do anel ou ainda não chegou."""
        if fim <= inicio:
            raise ValueError("fim precisa ser maior que inicio")

        with self._lock:
            if self._ancora_t is None:
                raise JanelaIndisponivel("buffer ainda não recebeu nenhuma amostra")

            i0 = self._indice_de(inicio)
            i1 = self._indice_de(fim)
            mais_antigo = max(0, self._total - self.capacidade)

            if i0 < mais_antigo:
                idade = (self._tempo_de(mais_antigo) - inicio)
                raise JanelaIndisponivel(
                    f"trecho pedido saiu do buffer há {idade:.2f} s — aumente "
                    "audio.buffer_segundos ou reduza a latência da cadeia"
                )
            if i1 > self._total:
                falta = (fim - self._tempo_de(self._total))
                raise JanelaIndisponivel(
                    f"trecho pedido ainda não foi capturado (faltam {falta:.2f} s); "
                    "use aguardar_ate() antes de extrair"
                )

            posicoes = np.arange(i0, i1) % self.capacidade
            amostras = np.take(self._dados, posicoes, axis=0).copy()
            return Janela(
                amostras=amostras,
                taxa_amostragem=self.taxa_amostragem,
                inicio=self._tempo_de(i0),
                fim=self._tempo_de(i1),
            )

    def ultimos(self, segundos: float) -> Janela:
        """Os últimos `segundos` disponíveis, encurtando se o buffer ainda não encheu."""
        with self._lock:
            mais_antigo, agora = self.intervalo_disponivel()
            inicio = max(mais_antigo, agora - segundos)
            if agora - inicio < 1 / self.taxa_amostragem:
                raise JanelaIndisponivel("buffer ainda não tem uma amostra sequer")
            return self.janela(inicio, agora)
