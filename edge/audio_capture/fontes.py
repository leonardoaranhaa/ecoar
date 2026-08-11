"""Fontes de áudio multicanal.

Uma interface, três implementações: o array I2S real, arquivos `.wav` de 4
canais, e uma cena sintética. Os módulos seguintes não sabem qual está em uso —
é o que permite desenvolver e testar a cadeia inteira sem hardware (D11).

`sounddevice` é importado dentro do driver I2S, nunca no topo deste arquivo.
"""

from __future__ import annotations

import time
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from edge.config import ConfigNo
from edge.geometria import ArrayCircular
from edge.audio_capture.sintetico import CenaSintetica


class HardwareIndisponivel(RuntimeError):
    """O driver real foi pedido mas o hardware ou a biblioteca não está lá."""


@dataclass(frozen=True)
class BlocoAudio:
    amostras: np.ndarray  # (n, canais), float32, escala -1..1
    timestamp: float  # epoch da PRIMEIRA amostra do bloco
    taxa_amostragem: int

    @property
    def duracao_s(self) -> float:
        return len(self.amostras) / self.taxa_amostragem


class FonteAudio(ABC):
    """Contrato de qualquer fonte de áudio do nó."""

    taxa_amostragem: int
    canais: int
    bloco_amostras: int

    @abstractmethod
    def abrir(self) -> None: ...

    @abstractmethod
    def fechar(self) -> None: ...

    @abstractmethod
    def ler(self) -> BlocoAudio | None:
        """Próximo bloco, ou None quando a fonte terminou (só fontes finitas)."""

    def blocos(self) -> Iterator[BlocoAudio]:
        while True:
            bloco = self.ler()
            if bloco is None:
                return
            yield bloco

    def descricao(self) -> dict[str, object]:
        return {
            "tipo": type(self).__name__,
            "taxa_amostragem": self.taxa_amostragem,
            "canais": self.canais,
            "bloco_amostras": self.bloco_amostras,
        }

    def __enter__(self) -> "FonteAudio":
        self.abrir()
        return self

    def __exit__(self, *_) -> None:
        self.fechar()


class _FonteRelogioVirtual(FonteAudio):
    """Base das fontes que não vêm de hardware.

    Mantém um relógio próprio ancorado no instante de abertura: em tempo real,
    dorme o necessário para entregar blocos no ritmo da taxa de amostragem; fora
    dele, entrega o mais rápido possível com timestamps ainda coerentes — é o
    que faz a suíte de testes rodar em milissegundos em vez de minutos.
    """

    def __init__(self, taxa_amostragem: int, canais: int, bloco_amostras: int, tempo_real: bool):
        self.taxa_amostragem = int(taxa_amostragem)
        self.canais = int(canais)
        self.bloco_amostras = int(bloco_amostras)
        self.tempo_real = tempo_real
        self._t0 = 0.0
        self._emitidas = 0
        self._aberta = False

    def abrir(self) -> None:
        self._t0 = time.time()
        self._emitidas = 0
        self._aberta = True

    def fechar(self) -> None:
        self._aberta = False

    def _timestamp_do_proximo(self) -> float:
        return self._t0 + self._emitidas / self.taxa_amostragem

    def _ritmar(self, n_amostras: int) -> None:
        if not self.tempo_real:
            return
        pronto_em = self._t0 + (self._emitidas + n_amostras) / self.taxa_amostragem
        atraso = pronto_em - time.time()
        if atraso > 0:
            time.sleep(atraso)


class FonteSintetica(_FonteRelogioVirtual):
    """Cena sintética com azimute conhecido. Bancada, nunca dado de treino."""

    def __init__(
        self,
        array: ArrayCircular,
        taxa_amostragem: int = 48000,
        bloco_amostras: int = 4096,
        perfil: str = "escapamento",
        azimute_graus: float = 45.0,
        tempo_real: bool = True,
        semente: int = 20260817,
    ) -> None:
        super().__init__(taxa_amostragem, array.n_microfones, bloco_amostras, tempo_real)
        self.azimute_graus = azimute_graus
        self.perfil = perfil
        self._cena = CenaSintetica(
            array=array,
            taxa_amostragem=taxa_amostragem,
            perfil=perfil,
            azimute_graus=azimute_graus,
            semente=semente,
        )

    def ler(self) -> BlocoAudio | None:
        if not self._aberta:
            raise RuntimeError("fonte não foi aberta")
        timestamp = self._timestamp_do_proximo()
        amostras = self._cena.bloco(self.bloco_amostras, self._emitidas)
        self._ritmar(self.bloco_amostras)
        self._emitidas += self.bloco_amostras
        return BlocoAudio(amostras, timestamp, self.taxa_amostragem)

    def descricao(self) -> dict[str, object]:
        return {
            **super().descricao(),
            "perfil": self.perfil,
            "azimute_graus": self.azimute_graus,
            "aviso": "sinal sintético de bancada — não é gravação de campo",
        }


class FonteWav(_FonteRelogioVirtual):
    """Reprodução de arquivo `.wav` multicanal.

    É o modo usado com gravação de campo real: mesma cadeia de processamento,
    entrada vinda de arquivo em vez do array.
    """

    def __init__(
        self,
        caminho: str | Path,
        bloco_amostras: int = 4096,
        laco: bool = False,
        tempo_real: bool = True,
        canais_esperados: int | None = None,
    ) -> None:
        self.caminho = Path(caminho)
        if not self.caminho.exists():
            raise FileNotFoundError(f"arquivo de áudio não encontrado: {self.caminho}")

        with wave.open(str(self.caminho), "rb") as arquivo:
            canais = arquivo.getnchannels()
            taxa = arquivo.getframerate()
            self.largura_bytes = arquivo.getsampwidth()

        if canais_esperados is not None and canais != canais_esperados:
            raise ValueError(
                f"{self.caminho.name}: arquivo tem {canais} canal(is), o nó espera "
                f"{canais_esperados} — a localização direcional precisa de um canal "
                "por microfone"
            )
        if self.largura_bytes not in (1, 2, 3, 4):
            raise ValueError(f"largura de amostra não suportada: {self.largura_bytes} bytes")

        super().__init__(taxa, canais, bloco_amostras, tempo_real)
        self.laco = laco
        self._arquivo: wave.Wave_read | None = None

    def abrir(self) -> None:
        super().abrir()
        self._arquivo = wave.open(str(self.caminho), "rb")

    def fechar(self) -> None:
        super().fechar()
        if self._arquivo is not None:
            self._arquivo.close()
            self._arquivo = None

    def ler(self) -> BlocoAudio | None:
        if self._arquivo is None:
            raise RuntimeError("fonte não foi aberta")

        bruto = self._arquivo.readframes(self.bloco_amostras)
        if not bruto:
            if not self.laco:
                return None
            self._arquivo.rewind()
            bruto = self._arquivo.readframes(self.bloco_amostras)
            if not bruto:
                return None

        amostras = _bytes_para_float32(bruto, self.largura_bytes, self.canais)
        timestamp = self._timestamp_do_proximo()
        self._ritmar(len(amostras))
        self._emitidas += len(amostras)
        return BlocoAudio(amostras, timestamp, self.taxa_amostragem)

    def descricao(self) -> dict[str, object]:
        return {**super().descricao(), "arquivo": self.caminho.name}


class FonteI2S(FonteAudio):
    """Array de microfones MEMS I2S no Raspberry Pi, via ALSA.

    Pré-requisito no nó: o overlay de I2S habilitado em `/boot/config.txt` e os
    microfones aparecendo como um dispositivo de captura de N canais. Confira
    com `arecord -l` antes de suspeitar do código — a causa mais comum de canal
    mudo é montagem elétrica, não software.
    """

    def __init__(
        self,
        taxa_amostragem: int = 48000,
        canais: int = 4,
        bloco_amostras: int = 4096,
        dispositivo: str | int | None = None,
    ) -> None:
        self.taxa_amostragem = int(taxa_amostragem)
        self.canais = int(canais)
        self.bloco_amostras = int(bloco_amostras)
        self.dispositivo = dispositivo
        self._stream = None
        self._estouros = 0

    def abrir(self) -> None:
        try:
            import sounddevice  # noqa: PLC0415 — driver de hardware, import sob demanda
        except Exception as erro:  # pragma: no cover - depende do nó
            raise HardwareIndisponivel(
                "sounddevice não está instalado. No nó de campo: "
                "pip install -r requirements-hardware.txt. Fora dele, use "
                "audio.fonte.tipo='wav' ou 'sintetica'."
            ) from erro

        try:
            self._stream = sounddevice.InputStream(
                samplerate=self.taxa_amostragem,
                channels=self.canais,
                blocksize=self.bloco_amostras,
                dtype="float32",
                device=self.dispositivo,
            )
            self._stream.start()
        except Exception as erro:  # pragma: no cover - depende do nó
            raise HardwareIndisponivel(
                f"não consegui abrir o dispositivo de captura {self.dispositivo!r} com "
                f"{self.canais} canais a {self.taxa_amostragem} Hz: {erro}"
            ) from erro

    def fechar(self) -> None:  # pragma: no cover - depende do nó
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def ler(self) -> BlocoAudio | None:  # pragma: no cover - depende do nó
        if self._stream is None:
            raise RuntimeError("fonte não foi aberta")
        amostras, estourou = self._stream.read(self.bloco_amostras)
        # O timestamp é do início do bloco: ele já foi capturado quando a
        # chamada retorna.
        timestamp = time.time() - self.bloco_amostras / self.taxa_amostragem
        if estourou:
            self._estouros += 1
        return BlocoAudio(
            np.asarray(amostras, dtype=np.float32), timestamp, self.taxa_amostragem
        )

    @property
    def estouros(self) -> int:
        """Quantos blocos a placa perdeu por não termos lido a tempo."""
        return self._estouros

    def descricao(self) -> dict[str, object]:
        return {**super().descricao(), "dispositivo": self.dispositivo, "estouros": self._estouros}


def _bytes_para_float32(bruto: bytes, largura: int, canais: int) -> np.ndarray:
    """Converte PCM entrelaçado em float32 na escala -1..1."""
    if largura == 1:
        dados = (np.frombuffer(bruto, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif largura == 2:
        dados = np.frombuffer(bruto, dtype="<i2").astype(np.float32) / 32768.0
    elif largura == 3:
        cru = np.frombuffer(bruto, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        inteiros = cru[:, 0] | (cru[:, 1] << 8) | (cru[:, 2] << 16)
        inteiros = np.where(inteiros >= 2**23, inteiros - 2**24, inteiros)
        dados = inteiros.astype(np.float32) / float(2**23)
    else:
        dados = np.frombuffer(bruto, dtype="<i4").astype(np.float32) / float(2**31)
    return np.ascontiguousarray(dados.reshape(-1, canais))


def escrever_wav(
    caminho: str | Path, amostras: np.ndarray, taxa_amostragem: int
) -> Path:
    """Grava (n, canais) float32 como PCM 24 bits — o formato nativo do ICS-43434."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    dados = np.clip(np.asarray(amostras, dtype=np.float64), -1.0, 1.0)
    inteiros = np.round(dados * (2**23 - 1)).astype(np.int32).reshape(-1)
    bytes_le = inteiros.astype("<i4").tobytes()
    # Descarta o byte mais significativo de cada amostra de 32 bits.
    tres_bytes = np.frombuffer(bytes_le, dtype=np.uint8).reshape(-1, 4)[:, :3].tobytes()

    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(int(amostras.shape[1]))
        arquivo.setsampwidth(3)
        arquivo.setframerate(int(taxa_amostragem))
        arquivo.writeframes(tres_bytes)
    return caminho


def criar_fonte(config: ConfigNo, tempo_real: bool | None = None) -> FonteAudio:
    """Instancia a fonte declarada na configuração do nó."""
    audio = config.audio
    fonte = audio.fonte
    ritmo = fonte.tempo_real if tempo_real is None else tempo_real

    if fonte.tipo == "i2s":
        return FonteI2S(
            taxa_amostragem=audio.taxa_amostragem,
            canais=audio.canais,
            bloco_amostras=audio.bloco_amostras,
            dispositivo=fonte.dispositivo,
        )
    if fonte.tipo == "wav":
        return FonteWav(
            caminho=fonte.caminho,
            bloco_amostras=audio.bloco_amostras,
            laco=fonte.laco,
            tempo_real=ritmo,
            canais_esperados=audio.canais,
        )
    return FonteSintetica(
        array=ArrayCircular.de_config(config.array),
        taxa_amostragem=audio.taxa_amostragem,
        bloco_amostras=audio.bloco_amostras,
        perfil=fonte.perfil,
        azimute_graus=fonte.azimute_graus,
        tempo_real=ritmo,
    )
