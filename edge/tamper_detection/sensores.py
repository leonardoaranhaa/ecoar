"""Sensores de violação, atrás de interface, com implementação simulada.

`smbus2` (MPU-6050 via I2C) e `gpiozero` (reed switch, alimentação) são
importados dentro do driver, nunca no topo. Sem eles, o modo de simulação
mantém a cadeia de alerta inteira testável (D11).
"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class LeituraInercial:
    """Amostra do acelerômetro/giroscópio, já em unidades físicas."""

    ax: float  # aceleração em g
    ay: float
    az: float
    gx: float  # rotação em °/s
    gy: float
    gz: float
    timestamp: float

    @property
    def magnitude_g(self) -> float:
        return math.sqrt(self.ax**2 + self.ay**2 + self.az**2)

    @property
    def inclinacao_graus(self) -> float:
        """Ângulo entre o vetor de gravidade medido e o eixo vertical.

        Com o nó parado, o acelerômetro só mede a gravidade. O ângulo desse
        vetor em relação ao eixo z é a inclinação do gabinete — muda quando
        alguém torce o suporte.
        """
        horizontal = math.sqrt(self.ax**2 + self.ay**2)
        return math.degrees(math.atan2(horizontal, abs(self.az) + 1e-9))


class SensorInercial(ABC):
    @abstractmethod
    def ler(self) -> LeituraInercial: ...

    def abrir(self) -> None:
        return None

    def fechar(self) -> None:
        return None


class SensorInercialSimulado(SensorInercial):
    """Nó parado, apoiado na vertical, com micro-ruído.

    Os eventos de violação (impacto, inclinação, movimento) são injetados pelos
    métodos `simular_*`, para exercitar a cadeia de alerta sem o hardware.
    """

    def __init__(self, semente: int = 7) -> None:
        import random

        self._rng = random.Random(semente)
        self._inclinacao_base = 0.0
        self._impacto_ate = 0.0
        self._movimento_ate = 0.0

    def simular_impacto(self, duracao_s: float = 0.3) -> None:
        self._impacto_ate = time.time() + duracao_s

    def simular_inclinacao(self, graus: float) -> None:
        self._inclinacao_base = graus

    def simular_movimento(self, duracao_s: float = 2.0) -> None:
        self._movimento_ate = time.time() + duracao_s

    def ler(self) -> LeituraInercial:
        agora = time.time()
        ruido = lambda escala: self._rng.uniform(-escala, escala)  # noqa: E731

        inclinacao = math.radians(self._inclinacao_base)
        ax = math.sin(inclinacao) + ruido(0.02)
        ay = ruido(0.02)
        az = math.cos(inclinacao) + ruido(0.02)
        gx = gy = gz = 0.0

        if agora < self._impacto_ate:
            ax += ruido(4.0)
            ay += ruido(4.0)
            az += ruido(4.0)
        if agora < self._movimento_ate:
            gx, gy, gz = ruido(80.0), ruido(80.0), ruido(80.0)
            ax += ruido(0.5)

        return LeituraInercial(ax, ay, az, gx, gy, gz, agora)


class SensorMPU6050(SensorInercial):
    """MPU-6050 real via I2C. Só roda no nó de campo."""

    ENDERECO = 0x68

    def __init__(self, barramento: int = 1, endereco: int = ENDERECO) -> None:
        self._barramento_id = barramento
        self._endereco = endereco
        self._bus = None

    def abrir(self) -> None:  # pragma: no cover - depende do nó
        try:
            import smbus2  # noqa: PLC0415 — driver de hardware, import sob demanda
        except Exception as erro:
            raise RuntimeError(
                "smbus2 não está instalado. No nó: pip install -r requirements-hardware.txt"
            ) from erro
        self._bus = smbus2.SMBus(self._barramento_id)
        self._bus.write_byte_data(self._endereco, 0x6B, 0)  # acorda o sensor

    def fechar(self) -> None:  # pragma: no cover - depende do nó
        if self._bus is not None:
            self._bus.close()
            self._bus = None

    def _palavra(self, reg: int) -> int:  # pragma: no cover - depende do nó
        alto = self._bus.read_byte_data(self._endereco, reg)
        baixo = self._bus.read_byte_data(self._endereco, reg + 1)
        valor = (alto << 8) | baixo
        return valor - 65536 if valor >= 0x8000 else valor

    def ler(self) -> LeituraInercial:  # pragma: no cover - depende do nó
        if self._bus is None:
            raise RuntimeError("sensor não foi aberto")
        return LeituraInercial(
            ax=self._palavra(0x3B) / 16384.0,
            ay=self._palavra(0x3D) / 16384.0,
            az=self._palavra(0x3F) / 16384.0,
            gx=self._palavra(0x43) / 131.0,
            gy=self._palavra(0x45) / 131.0,
            gz=self._palavra(0x47) / 131.0,
            timestamp=time.time(),
        )


class SensorAbertura(ABC):
    """Chave magnética (reed switch) na tampa do gabinete."""

    @abstractmethod
    def aberto(self) -> bool: ...

    def abrir(self) -> None:
        return None

    def fechar(self) -> None:
        return None


class SensorAberturaSimulado(SensorAbertura):
    def __init__(self) -> None:
        self._aberto = False

    def simular_abertura(self, aberto: bool = True) -> None:
        self._aberto = aberto

    def aberto(self) -> bool:
        return self._aberto


class SensorAberturaGPIO(SensorAbertura):  # pragma: no cover - depende do nó
    def __init__(self, pino: int) -> None:
        self._pino = pino
        self._botao = None

    def abrir(self) -> None:
        try:
            from gpiozero import Button  # noqa: PLC0415 — driver de hardware
        except Exception as erro:
            raise RuntimeError(
                "gpiozero não está instalado. No nó: pip install -r requirements-hardware.txt"
            ) from erro
        self._botao = Button(self._pino, pull_up=True)

    def aberto(self) -> bool:
        return self._botao is not None and not self._botao.is_pressed


class SensorAlimentacao(ABC):
    """Detecta queda da alimentação principal (transição para bateria)."""

    @abstractmethod
    def na_bateria(self) -> bool: ...

    @abstractmethod
    def bateria_pct(self) -> float | None: ...

    def abrir(self) -> None:
        return None

    def fechar(self) -> None:
        return None


class SensorAlimentacaoSimulado(SensorAlimentacao):
    def __init__(self, bateria_pct: float = 100.0) -> None:
        self._na_bateria = False
        self._bateria = bateria_pct

    def simular_queda_de_energia(self, na_bateria: bool = True) -> None:
        self._na_bateria = na_bateria

    def definir_bateria(self, pct: float) -> None:
        self._bateria = pct

    def na_bateria(self) -> bool:
        return self._na_bateria

    def bateria_pct(self) -> float | None:
        return self._bateria
