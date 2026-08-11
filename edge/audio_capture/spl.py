"""Nível de pressão sonora estimado a partir do array MEMS.

LEIA ANTES DE USAR ESTE MÓDULO — decisão D3, docs/legal/inmetro.md:

O valor produzido aqui NÃO tem validade legal. Ele serve para dois propósitos, e
só esses dois:

1. pré-gatilho barato — decidir se vale a pena rodar o classificador;
2. contexto na evidência — "o pico estimado foi de tanto", ao lado da medição do
   instrumento certificado, quando houver.

Medição com valor de prova vem de instrumento IEC 61672 Classe 1, através de
`sonometro.py`. Por isso toda estimativa deste módulo sai com
`valor_legal = False` — o campo viaja junto com o número, para que ninguém
precise lembrar da ressalva.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from edge.config import ConfigCalibracao

PISO_DBFS = -200.0


@dataclass(frozen=True)
class EstimativaSPL:
    """Estimativa de nível sonoro do array. Nunca é prova de decibel."""

    db: float  # dBFS + offset da campanha de calibração
    dbfs: float
    ponderacao: str
    canal_dominante: int
    db_por_canal: tuple[float, ...]
    offset_calibracao: float
    referencia_calibracao: str
    valor_legal: bool = False

    def como_dict(self) -> dict[str, object]:
        return {
            "db": round(self.db, 2),
            "dbfs": round(self.dbfs, 2),
            "ponderacao": self.ponderacao,
            "canal_dominante": self.canal_dominante,
            "db_por_canal": [round(v, 2) for v in self.db_por_canal],
            "offset_calibracao": self.offset_calibracao,
            "referencia_calibracao": self.referencia_calibracao,
            "valor_legal": self.valor_legal,
            "origem": "array MEMS ICS-43434 — estimativa relativa, sem valor de prova",
        }


def pesos_a(frequencias: np.ndarray) -> np.ndarray:
    """Curva de ponderação A (IEC 61672) em ganho linear.

    A ponderação A aproxima a sensibilidade do ouvido humano: corta grave e
    agudo extremo. Sem ela, o ronco de um caminhão a 40 Hz mede alto e incomoda
    pouco, enquanto o estalo de um escapamento adulterado mede parecido e
    incomoda muito — e o pré-gatilho dispararia pelo caminhão.
    """
    f = np.asarray(frequencias, dtype=np.float64)
    f2 = f * f
    numerador = (12194.0**2) * f2 * f2
    denominador = (
        (f2 + 20.6**2)
        * np.sqrt((f2 + 107.7**2) * (f2 + 737.9**2))
        * (f2 + 12194.0**2)
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        resposta = np.where(denominador > 0, numerador / denominador, 0.0)
    # +2,00 dB normaliza a curva para ganho unitário em 1 kHz.
    return resposta * (10.0 ** (2.0 / 20.0))


def aplicar_ponderacao(amostras: np.ndarray, taxa_amostragem: int, ponderacao: str) -> np.ndarray:
    """Aplica a ponderação no domínio da frequência e volta para o tempo."""
    if ponderacao == "Z":
        return np.asarray(amostras, dtype=np.float64)
    if ponderacao != "A":
        raise ValueError(f"ponderação desconhecida: {ponderacao!r}")

    x = np.atleast_2d(np.asarray(amostras, dtype=np.float64))
    if x.ndim == 1:
        x = x[:, None]
    n = len(x)
    if n < 2:
        return x
    espectro = np.fft.rfft(x, axis=0)
    ganho = pesos_a(np.fft.rfftfreq(n, d=1.0 / taxa_amostragem))
    return np.fft.irfft(espectro * ganho[:, None], n=n, axis=0)


def rms_por_canal(amostras: np.ndarray) -> np.ndarray:
    x = np.asarray(amostras, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    return np.sqrt(np.mean(x * x, axis=0))


def dbfs_por_canal(amostras: np.ndarray, taxa_amostragem: int, ponderacao: str = "A") -> np.ndarray:
    """dB relativo a fundo de escala (amplitude 1,0), por canal."""
    ponderado = aplicar_ponderacao(amostras, taxa_amostragem, ponderacao)
    rms = rms_por_canal(ponderado)
    with np.errstate(divide="ignore"):
        valores = 20.0 * np.log10(np.maximum(rms, 1e-12))
    return np.maximum(valores, PISO_DBFS)


def estimar(
    amostras: np.ndarray,
    taxa_amostragem: int,
    calibracao: ConfigCalibracao,
) -> EstimativaSPL:
    """Estimativa de SPL do array inteiro, com o canal dominante identificado.

    O nível do array é a média de energia entre canais (não a média de dB, que
    subestimaria um pico concentrado num microfone). O canal dominante é útil
    como confirmação grosseira do lado de onde veio o som — a estimativa de
    ângulo de verdade é do módulo `localization`.
    """
    por_canal = dbfs_por_canal(amostras, taxa_amostragem, calibracao.ponderacao)
    energia_media = float(np.mean(10.0 ** (por_canal / 10.0)))
    # float() explícito: um np.float64 vazando daqui contamina toda comparação
    # rio abaixo com np.bool_, que o JSON do pacote de evidência recusa.
    dbfs = float(max(10.0 * np.log10(max(energia_media, 1e-20)), PISO_DBFS))

    return EstimativaSPL(
        db=float(dbfs + calibracao.offset_db),
        dbfs=dbfs,
        ponderacao=calibracao.ponderacao,
        canal_dominante=int(np.argmax(por_canal)),
        db_por_canal=tuple(float(v) + calibracao.offset_db for v in por_canal),
        offset_calibracao=calibracao.offset_db,
        referencia_calibracao=calibracao.referencia,
        valor_legal=False,
    )
