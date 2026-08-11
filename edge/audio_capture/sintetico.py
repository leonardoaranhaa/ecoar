"""Cena acústica sintética, para bancada.

Serve para exercitar a cadeia inteira sem microfone, sem placa e sem gravação de
campo: gera 4 canais coerentes, com a diferença de tempo de chegada correta para
um azimute escolhido.

O QUE ISTO NÃO É: dado de treino. Um classificador treinado nestes sinais
aprende a reconhecer estes sinais, não escapamento adulterado de verdade. O
modelo só vale depois de gravação de campo real (decisão D13, README do
`edge/classifier`). Aqui é encanamento, não acústica.

Modelo de sinal: a fonte é coerente e chega a cada microfone com o atraso da
geometria; o ruído de fundo é independente por canal — que é como um campo
difuso e o ruído próprio de cada sensor de fato se comportam.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from edge.geometria import ArrayCircular

PERFIS = ("escapamento", "buzina", "obra", "trovao", "ambiente")


def _escapamento(t: np.ndarray) -> np.ndarray:
    """Passagem de moto com escapamento adulterado, a cada 8 s.

    Assinatura imitada: fundamental grave de explosão, muitos harmônicos fortes,
    estalo pulsado na frequência de disparo e leve subida de rotação na
    aproximação.
    """
    periodo = 8.0
    fase = np.mod(t, periodo)
    envelope = np.exp(-0.5 * ((fase - 4.0) / 0.7) ** 2)

    f0, taxa_subida = 72.0, 3.0
    ph = 2 * np.pi * (f0 * fase + 0.5 * taxa_subida * fase**2)

    amplitudes = np.array([1.0, 0.85, 0.72, 0.6, 0.5, 0.42, 0.35, 0.3, 0.25, 0.2, 0.16, 0.13])
    soma = np.zeros_like(t)
    for ordem, amp in enumerate(amplitudes, start=1):
        soma += amp * np.sin(ordem * ph + 0.7 * ordem)
    soma /= amplitudes.sum()

    estalo = np.clip(np.sin(ph / 2.0), 0.0, 1.0) ** 8
    return envelope * soma * (0.55 + 0.75 * estalo)


def _buzina(t: np.ndarray) -> np.ndarray:
    """Buzina: duas notas estáveis, poucos harmônicos, sem estalo."""
    periodo = 6.0
    fase = np.mod(t, periodo)
    envelope = ((fase > 2.0) & (fase < 2.7)).astype(float)
    envelope = envelope * np.minimum(1.0, (fase - 2.0) * 20.0) * np.minimum(1.0, (2.7 - fase) * 20.0)
    envelope = np.clip(envelope, 0.0, 1.0)

    soma = np.zeros_like(t)
    for base in (440.0, 554.0):
        for ordem, amp in ((1, 1.0), (2, 0.35), (3, 0.18)):
            soma += amp * np.sin(2 * np.pi * base * ordem * t)
    return envelope * soma / 3.06


def _obra(t: np.ndarray) -> np.ndarray:
    """Rompedor pneumático: impactos repetidos, ressonância metálica aguda."""
    periodo_impacto = 1.0 / 12.0
    fase = np.mod(t, periodo_impacto)
    decaimento = np.exp(-fase * 55.0)
    corpo = np.sin(2 * np.pi * 900.0 * t) + 0.6 * np.sin(2 * np.pi * 1750.0 * t)
    envelope_longo = 0.5 + 0.5 * np.sin(2 * np.pi * t / 30.0)
    return decaimento * corpo * envelope_longo / 1.6


def _trovao(t: np.ndarray) -> np.ndarray:
    """Trovão: energia muito grave, ataque suave, cauda longa, raro."""
    periodo = 20.0
    fase = np.mod(t, periodo)
    envelope = np.where(fase < 4.0, np.exp(-fase * 0.8) * (1 - np.exp(-fase * 6.0)), 0.0)
    corpo = (
        np.sin(2 * np.pi * 28.0 * t)
        + 0.7 * np.sin(2 * np.pi * 41.0 * t + 1.2)
        + 0.4 * np.sin(2 * np.pi * 63.0 * t + 2.4)
    )
    return envelope * corpo / 2.1


def _ambiente(t: np.ndarray) -> np.ndarray:
    """Tráfego distante: rumor grave contínuo, sem estrutura de evento."""
    return 0.25 * (
        np.sin(2 * np.pi * 47.0 * t) + 0.6 * np.sin(2 * np.pi * 73.0 * t + 0.9)
    ) / 1.6


_GERADORES = {
    "escapamento": _escapamento,
    "buzina": _buzina,
    "obra": _obra,
    "trovao": _trovao,
    "ambiente": _ambiente,
}


@dataclass
class CenaSintetica:
    """Gera blocos contínuos de uma cena, como função do tempo absoluto."""

    array: ArrayCircular
    taxa_amostragem: int
    perfil: str = "escapamento"
    azimute_graus: float = 45.0
    ganho_fonte: float = 0.35
    ruido_fundo: float = 0.02
    semente: int = 20260817

    def __post_init__(self) -> None:
        if self.perfil not in PERFIS:
            raise ValueError(f"perfil desconhecido: {self.perfil!r}; use um de {PERFIS}")
        self._gerador = _GERADORES[self.perfil]
        self._rng = np.random.default_rng(self.semente)
        self._atrasos = self.array.atrasos(self.azimute_graus)

    def bloco(self, n_amostras: int, indice_inicial: int) -> np.ndarray:
        """Bloco (n, canais) começando na amostra global `indice_inicial`."""
        t = (indice_inicial + np.arange(n_amostras)) / self.taxa_amostragem
        canais = self.array.n_microfones
        saida = np.empty((n_amostras, canais), dtype=np.float32)

        for canal in range(canais):
            # Atrasar a fonte = amostrar o sinal num tempo anterior. Como o
            # gerador é função analítica do tempo, o atraso sai exato, sem
            # interpolação e sem descontinuidade na fronteira do bloco.
            coerente = self._gerador(t - self._atrasos[canal]) * self.ganho_fonte
            difuso = self._rng.normal(0.0, self.ruido_fundo, n_amostras)
            saida[:, canal] = (coerente + difuso).astype(np.float32)

        return saida
