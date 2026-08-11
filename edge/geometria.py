"""Geometria do array de microfones.

Fato do nó, não detalhe de um módulo: a captura sintética, a localização e o
pacote de evidência precisam concordar sobre onde cada microfone está. Um só
lugar define isso.

Convenção de ângulo, usada em todo o sistema:

- azimute em graus, 0° na direção do microfone 0 mais o offset de instalação;
- sentido anti-horário, visto de cima;
- azimute é de onde o som VEM (direção da fonte), não para onde ele vai.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from edge.config import ConfigArray


@dataclass(frozen=True)
class ArrayCircular:
    raio_m: float
    n_microfones: int
    azimute_offset_graus: float = 0.0
    velocidade_som_ms: float = 343.0

    @classmethod
    def de_config(cls, config: ConfigArray) -> "ArrayCircular":
        return cls(
            raio_m=config.raio_m,
            n_microfones=config.n_microfones,
            azimute_offset_graus=config.azimute_offset_graus,
            velocidade_som_ms=config.velocidade_som_ms,
        )

    def posicoes(self) -> np.ndarray:
        """Coordenadas (x, y) de cada microfone, em metros, origem no centro."""
        indices = np.arange(self.n_microfones)
        angulos = np.deg2rad(self.azimute_offset_graus + 360.0 * indices / self.n_microfones)
        return self.raio_m * np.stack([np.cos(angulos), np.sin(angulos)], axis=1)

    def atrasos(self, azimute_graus: float) -> np.ndarray:
        """Atraso de chegada por microfone, em segundos, para fonte distante.

        Campo distante (onda plana): a fonte está longe o bastante para que a
        frente de onda chegue reta ao array. Vale para os 15 m de alcance do
        projeto com um array de poucos centímetros.

        O menor atraso é zerado — só a diferença entre microfones importa.
        """
        direcao = np.array(
            [np.cos(np.deg2rad(azimute_graus)), np.sin(np.deg2rad(azimute_graus))]
        )
        projecao = self.posicoes() @ direcao
        atrasos = -projecao / self.velocidade_som_ms
        return atrasos - atrasos.min()

    @property
    def atraso_maximo_s(self) -> float:
        """Maior diferença de tempo fisicamente possível entre dois microfones."""
        return 2.0 * self.raio_m / self.velocidade_som_ms
