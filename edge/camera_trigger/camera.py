"""Câmera do nó: interface, implementação real e simulada.

`cv2` é importado dentro do driver. Sem ele — e sem câmera — a cadeia inteira
continua rodando com a câmera simulada (D11).
"""

from __future__ import annotations

import struct
import time
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from edge.config import ConfigCamera

PLACA = "placa"
PANORAMICA = "panoramica"


class CameraIndisponivel(RuntimeError):
    """A câmera não respondeu.

    Não impede o evento de existir: o pacote de evidência registra a falha de
    captura, e o evento vai para revisão sem imagem. Perder o áudio por causa da
    câmera seria perder o evento inteiro.
    """


@dataclass(frozen=True)
class CapturaImagem:
    caminho: Path
    timestamp: float
    tipo: str  # PLACA ou PANORAMICA
    largura: int
    altura: int
    camera: str
    simulada: bool

    def como_dict(self) -> dict[str, object]:
        return {
            "arquivo": self.caminho.name,
            "timestamp": self.timestamp,
            "tipo": self.tipo,
            "resolucao": f"{self.largura}x{self.altura}",
            "camera": self.camera,
            "simulada": self.simulada,
        }


class Camera(ABC):
    nome: str = "abstrata"
    simulada: bool = True

    @abstractmethod
    def capturar(self, destino: Path, tipo: str) -> CapturaImagem: ...

    def abrir(self) -> None:
        return None

    def fechar(self) -> None:
        return None

    def descricao(self) -> dict[str, object]:
        return {"camera": self.nome, "simulada": self.simulada}

    def __enter__(self) -> "Camera":
        self.abrir()
        return self

    def __exit__(self, *_) -> None:
        self.fechar()


def escrever_png(caminho: Path, imagem: np.ndarray) -> Path:
    """Grava (altura, largura, 3) uint8 como PNG, sem dependência externa.

    São trinta linhas de zlib e CRC contra arrastar uma biblioteca de imagem
    inteira para dentro do nó só para salvar a captura simulada.
    """
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    altura, largura, canais = imagem.shape
    if canais != 3:
        raise ValueError("esperava imagem RGB de 3 canais")

    linhas = b"".join(
        b"\x00" + imagem[y].astype(np.uint8).tobytes() for y in range(altura)
    )

    def bloco(tipo: bytes, dados: bytes) -> bytes:
        return (
            struct.pack(">I", len(dados))
            + tipo
            + dados
            + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF)
        )

    cabecalho = struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0)
    conteudo = (
        b"\x89PNG\r\n\x1a\n"
        + bloco(b"IHDR", cabecalho)
        + bloco(b"IDAT", zlib.compress(linhas, 6))
        + bloco(b"IEND", b"")
    )
    caminho.write_bytes(conteudo)
    return caminho


class CameraSimulada(Camera):
    """Padrão de teste sintético, deliberadamente artificial.

    A imagem NÃO imita uma fotografia de veículo com placa. Uma captura
    simulada que parece real é um problema: ela pode acabar num relatório, numa
    demonstração ou num pacote de evidência sem que ninguém perceba que é
    inventada. O padrão gerado aqui se identifica como sintético à primeira
    vista, e o campo `simulada: true` viaja junto no manifesto.
    """

    nome = "simulada"
    simulada = True

    def __init__(self, largura: int = 640, altura: int = 360) -> None:
        self.largura = largura
        self.altura = altura

    def capturar(self, destino: Path, tipo: str) -> CapturaImagem:
        instante = time.time()
        largura = self.largura if tipo == PANORAMICA else self.largura // 2
        altura = self.altura if tipo == PANORAMICA else self.altura // 2

        y, x = np.mgrid[0:altura, 0:largura]
        imagem = np.zeros((altura, largura, 3), dtype=np.uint8)
        imagem[..., 0] = (x * 255 // max(largura - 1, 1)).astype(np.uint8)
        imagem[..., 1] = (y * 255 // max(altura - 1, 1)).astype(np.uint8)
        # Faixas diagonais marcam a imagem como padrão de teste.
        imagem[..., 2] = np.where(((x + y) // 16) % 2 == 0, 200, 40)

        escrever_png(destino, imagem)
        return CapturaImagem(
            caminho=destino,
            timestamp=instante,
            tipo=tipo,
            largura=largura,
            altura=altura,
            camera=self.nome,
            simulada=True,
        )


class CameraOpenCV(Camera):
    """Câmera USB ou CSI via OpenCV.

    Os quadros de aquecimento não são superstição: sensor recém-aberto entrega
    os primeiros quadros com exposição e ganho errados, e é exatamente neles
    que a placa sai ilegível.
    """

    nome = "opencv"
    simulada = False

    def __init__(self, config: ConfigCamera) -> None:
        self.config = config
        self._captura = None

    def abrir(self) -> None:  # pragma: no cover - depende do nó
        try:
            import cv2  # noqa: PLC0415 — driver de hardware, import sob demanda
        except Exception as erro:
            raise CameraIndisponivel(
                "opencv não está instalado. No nó de campo: "
                "pip install -r requirements-hardware.txt"
            ) from erro

        captura = cv2.VideoCapture(self.config.dispositivo)
        if not captura.isOpened():
            raise CameraIndisponivel(
                f"não consegui abrir a câmera {self.config.dispositivo!r}"
            )
        captura.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.largura)
        captura.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.altura)
        self._captura = captura

    def fechar(self) -> None:  # pragma: no cover - depende do nó
        if self._captura is not None:
            self._captura.release()
            self._captura = None

    def capturar(self, destino: Path, tipo: str) -> CapturaImagem:  # pragma: no cover
        import cv2

        if self._captura is None:
            raise CameraIndisponivel("câmera não foi aberta")

        for _ in range(max(0, self.config.aquecimento_quadros)):
            self._captura.read()

        instante = time.time()
        ok, quadro = self._captura.read()
        if not ok or quadro is None:
            raise CameraIndisponivel("a câmera não entregou quadro")

        destino.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(destino), quadro):
            raise CameraIndisponivel(f"falha ao gravar {destino}")

        altura, largura = quadro.shape[:2]
        return CapturaImagem(
            caminho=destino,
            timestamp=instante,
            tipo=tipo,
            largura=int(largura),
            altura=int(altura),
            camera=self.nome,
            simulada=False,
        )


def criar_camera(config: ConfigCamera) -> Camera:
    if config.tipo == "opencv":
        return CameraOpenCV(config)
    return CameraSimulada(largura=min(config.largura, 640), altura=min(config.altura, 360))
