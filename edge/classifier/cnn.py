"""Classificador neural sobre espectrograma mel — o caminho de produção.

Rede pequena de propósito: precisa rodar em tempo real num Raspberry Pi CM4,
junto com a captura e a localização, sem acelerador. São ~40 mil parâmetros,
três blocos convolucionais sobre uma imagem de 48 × 128 (mel × tempo).

`torch` é importado sob demanda e **não** é dependência do nó: o treino acontece
numa máquina de desenvolvimento, e o nó recebe o modelo já treinado. Sem torch
instalado, o sistema opera com o classificador de referência e registra que
degradou — nunca fica sem classificar (D8).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from edge.classifier.base import (
    CLASSES,
    Classificador,
    ClassificadorIndisponivel,
    Predicao,
)
from edge.classifier.features import N_MELS, extrair_descritores, log_mel

JANELA_QUADROS = 128  # ~1,4 s a 48 kHz com salto de 512


def importar_torch():
    try:
        import torch  # noqa: PLC0415 — dependência de treino, não do nó

        return torch
    except Exception as erro:
        raise ClassificadorIndisponivel(
            "torch não está instalado. Para treinar: pip install torch. "
            "No nó, o classificador de referência assume automaticamente."
        ) from erro


def padronizar(espectrograma: np.ndarray, quadros: int = JANELA_QUADROS) -> np.ndarray:
    """Recorta ou preenche para tamanho fixo, centrado no quadro mais energético."""
    n = len(espectrograma)
    if n == quadros:
        return espectrograma
    if n < quadros:
        falta = quadros - n
        antes = falta // 2
        return np.pad(
            espectrograma,
            ((antes, falta - antes), (0, 0)),
            mode="constant",
            constant_values=float(espectrograma.min()),
        )
    energia = espectrograma.mean(axis=1)
    centro = int(np.argmax(energia))
    inicio = int(np.clip(centro - quadros // 2, 0, n - quadros))
    return espectrograma[inicio : inicio + quadros]


def preparar_entrada(amostras: np.ndarray, taxa_amostragem: int) -> np.ndarray:
    """Áudio bruto → matriz (n_mels, quadros) na escala que a rede espera."""
    espectrograma = padronizar(log_mel(amostras, taxa_amostragem))
    # log_mel já vem normalizado pelo pico (0 dB no máximo); mapeia -80..0 dB
    # para -1..0, que é uma faixa confortável para a rede.
    return np.clip(espectrograma / 80.0, -1.0, 0.0).T.astype(np.float32)


def construir_modelo(n_classes: int = len(CLASSES), n_mels: int = N_MELS):
    """CNN pequena o suficiente para o CM4, funda o suficiente para servir.

    `n_mels` fica na assinatura por documentação de interface (é o formato que
    `preparar_entrada` produz), mas a arquitetura não usa o valor: o
    `AdaptiveAvgPool2d(1)` colapsa a dimensão espacial para 1×1 antes da camada
    linear, então o mesmo modelo aceita qualquer n_mels/quadros sem mudar.
    """
    nn = importar_torch().nn

    def bloco(entrada: int, saida: int) -> "nn.Sequential":
        return nn.Sequential(
            nn.Conv2d(entrada, saida, kernel_size=3, padding=1),
            nn.BatchNorm2d(saida),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
        )

    return nn.Sequential(
        bloco(1, 16),
        bloco(16, 32),
        bloco(32, 48),
        nn.AdaptiveAvgPool2d(1),
        nn.Flatten(),
        nn.Dropout(0.3),
        nn.Linear(48, n_classes),
    )


@dataclass
class MetadadosModelo:
    versao: str
    classes: tuple[str, ...]
    n_mels: int
    quadros: int
    taxa_amostragem: int
    treinado_em: str
    observacao: str = ""

    def como_dict(self) -> dict[str, object]:
        return {
            "versao": self.versao,
            "classes": list(self.classes),
            "n_mels": self.n_mels,
            "quadros": self.quadros,
            "taxa_amostragem": self.taxa_amostragem,
            "treinado_em": self.treinado_em,
            "observacao": self.observacao,
        }


def salvar_modelo(modelo, metadados: MetadadosModelo, caminho: str | Path) -> Path:
    torch = importar_torch()
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": modelo.state_dict(), "metadados": metadados.como_dict()}, caminho)
    caminho.with_suffix(".json").write_text(
        json.dumps(metadados.como_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return caminho


class ClassificadorCNN(Classificador):
    nome = "cnn"

    def __init__(self, caminho_modelo: str | Path) -> None:
        self.caminho = Path(caminho_modelo)
        self.versao = "não carregado"
        self._modelo = None
        self._classes: tuple[str, ...] = CLASSES

    def carregar(self) -> "ClassificadorCNN":
        torch = importar_torch()
        if not self.caminho.exists():
            raise ClassificadorIndisponivel(f"modelo não encontrado: {self.caminho}")

        pacote = torch.load(self.caminho, map_location="cpu", weights_only=False)
        metadados = pacote.get("metadados", {})
        self._classes = tuple(metadados.get("classes", CLASSES))
        self.versao = str(metadados.get("versao", self.caminho.stem))

        modelo = construir_modelo(n_classes=len(self._classes))
        modelo.load_state_dict(pacote["state_dict"])
        modelo.eval()
        self._modelo = modelo
        return self

    def classificar(self, amostras: np.ndarray, taxa_amostragem: int) -> Predicao:
        if self._modelo is None:
            raise ClassificadorIndisponivel("modelo não carregado — chame carregar() antes")
        torch = importar_torch()

        entrada = preparar_entrada(amostras, taxa_amostragem)
        with torch.no_grad():
            tensor = torch.from_numpy(entrada)[None, None, :, :]
            probabilidades = torch.softmax(self._modelo(tensor)[0], dim=0).numpy()

        scores = {
            classe: float(p)
            for classe, p in zip(self._classes, probabilidades, strict=True)
        }
        vencedora = max(scores, key=scores.get)
        descritores = extrair_descritores(amostras, taxa_amostragem)

        return Predicao(
            classe=vencedora,
            score=scores[vencedora],
            scores=scores,
            modelo=self.nome,
            versao_modelo=self.versao,
            explicacao=(
                f"rede neural sobre espectrograma mel, versão {self.versao}; "
                f"medidas do trecho: fundamental {descritores.f0_hz:.0f} Hz, "
                f"harmônicas {descritores.forca_harmonica:.2f}, "
                f"{descritores.taxa_impulsos_hz:.0f} impulsos/s"
            ),
            descritores=descritores.como_dict(),
        )
