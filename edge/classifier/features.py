"""Extração de características de áudio.

Duas saídas, para dois consumidores:

- `log_mel()` — espectrograma mel, entrada do classificador de rede neural;
- `Descritores` — um punhado de números com significado físico (frequência
  fundamental, força harmônica, modulação de amplitude, impulsividade), que é o
  que o classificador de referência usa e o que permite explicar uma decisão em
  português para quem não é da área.

Tudo em numpy: o nó de campo é um Raspberry Pi, e arrastar uma biblioteca de
áudio pesada para lá custa mais do que as cem linhas de FFT que dão o mesmo
resultado.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

VERSAO_FEATURES = "features/1.0"

EPS = 1e-12

N_FFT = 1024
SALTO = 512
N_MELS = 48
MEL_MIN_HZ = 40.0
MEL_MAX_HZ = 8000.0

# Envelope com salto curto: a modulação que caracteriza escapamento chega a
# 60 Hz, e um envelope amostrado a 94 Hz (salto de 512) não a enxergaria.
SALTO_ENVELOPE = 128
JANELA_ENVELOPE = 256

SEGUNDOS_ANALISE = 3.0


def mono(amostras: np.ndarray) -> np.ndarray:
    """Mistura os canais. A classificação é do som, não da direção."""
    x = np.asarray(amostras, dtype=np.float64)
    return x.mean(axis=1) if x.ndim == 2 else x


def trecho_central(amostras: np.ndarray, taxa_amostragem: int, segundos: float) -> np.ndarray:
    """Recorta o trecho mais energético — onde o evento está."""
    x = mono(amostras)
    n = int(segundos * taxa_amostragem)
    if len(x) <= n:
        return x
    janela = max(1, n // 16)
    suavizada = np.convolve(x**2, np.ones(janela) / janela, mode="same")
    centro = int(np.argmax(suavizada))
    inicio = int(np.clip(centro - n // 2, 0, len(x) - n))
    return x[inicio : inicio + n]


def hz_para_mel(hz: np.ndarray | float) -> np.ndarray | float:
    return 2595.0 * np.log10(1.0 + np.asarray(hz) / 700.0)


def mel_para_hz(mel: np.ndarray | float) -> np.ndarray | float:
    return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)


def banco_mel(
    taxa_amostragem: int,
    n_fft: int = N_FFT,
    n_mels: int = N_MELS,
    f_min: float = MEL_MIN_HZ,
    f_max: float | None = None,
) -> np.ndarray:
    """Banco de filtros triangulares na escala mel, (n_mels, n_fft//2+1)."""
    f_max = min(f_max or MEL_MAX_HZ, taxa_amostragem / 2)
    pontos_mel = np.linspace(hz_para_mel(f_min), hz_para_mel(f_max), n_mels + 2)
    pontos_hz = mel_para_hz(pontos_mel)
    frequencias = np.fft.rfftfreq(n_fft, d=1.0 / taxa_amostragem)

    banco = np.zeros((n_mels, len(frequencias)))
    for i in range(n_mels):
        esquerda, centro, direita = pontos_hz[i], pontos_hz[i + 1], pontos_hz[i + 2]
        subida = (frequencias - esquerda) / max(centro - esquerda, EPS)
        descida = (direita - frequencias) / max(direita - centro, EPS)
        banco[i] = np.clip(np.minimum(subida, descida), 0.0, None)
    return banco


def enquadrar(sinal: np.ndarray, tamanho: int, salto: int) -> np.ndarray:
    """Divide em quadros sobrepostos, (n_quadros, tamanho)."""
    if len(sinal) < tamanho:
        sinal = np.pad(sinal, (0, tamanho - len(sinal)))
    n_quadros = 1 + (len(sinal) - tamanho) // salto
    indices = np.arange(tamanho)[None, :] + salto * np.arange(n_quadros)[:, None]
    return sinal[indices]


def log_mel(
    amostras: np.ndarray,
    taxa_amostragem: int,
    n_fft: int = N_FFT,
    salto: int = SALTO,
    n_mels: int = N_MELS,
) -> np.ndarray:
    """Espectrograma mel em dB, (n_quadros, n_mels), normalizado pelo próprio pico.

    A normalização pelo pico é deliberada: o classificador precisa reconhecer a
    assinatura, não o volume. Volume é assunto do SPL e do instrumento de
    medição, e um escapamento longe continua sendo um escapamento.
    """
    x = mono(amostras)
    quadros = enquadrar(x, n_fft, salto) * np.hanning(n_fft)[None, :]
    potencia = np.abs(np.fft.rfft(quadros, axis=1)) ** 2
    mel = potencia @ banco_mel(taxa_amostragem, n_fft, n_mels).T
    em_db = 10.0 * np.log10(mel + EPS)
    return em_db - em_db.max()


def envelope(sinal: np.ndarray, salto: int = SALTO_ENVELOPE, janela: int = JANELA_ENVELOPE):
    """Envoltória de energia e a taxa em que ela foi amostrada."""
    quadros = enquadrar(sinal, janela, salto)
    return np.sqrt(np.mean(quadros**2, axis=1)), salto


@dataclass(frozen=True)
class Descritores:
    """Números com significado físico, não coeficientes opacos.

    É o que permite escrever no relatório "o classificador decidiu por
    escapamento porque o som tem fundamental de 78 Hz, série harmônica forte e
    modulação de 39 Hz" — e não "o modelo deu 0,91".
    """

    f0_hz: float
    forca_harmonica: float  # 0..1 — energia nas harmônicas de f0
    centroide_hz: float
    planicidade: float  # 0..1 — 1 é ruído branco, 0 é tom puro
    energia_grave: float  # fração abaixo de 200 Hz
    energia_aguda: float  # fração acima de 2 kHz
    modulacao_hz: float  # frequência dominante da envoltória
    profundidade_modulacao: float  # 0..1
    crista: float  # pico/RMS da envoltória
    taxa_impulsos_hz: float
    duracao_ativa_s: float
    versao: str = VERSAO_FEATURES

    def como_dict(self) -> dict[str, float | str]:
        return {
            chave: (round(valor, 4) if isinstance(valor, float) else valor)
            for chave, valor in asdict(self).items()
        }


def _f0_por_espectro(
    espectro: np.ndarray,
    frequencias: np.ndarray,
    f_min: float = 25.0,
    f_max: float = 1200.0,
) -> float:
    """Fundamental pela raia forte de menor frequência.

    Escapamento adulterado vive entre 60 e 120 Hz (rotação do motor dividida
    pelo número de tempos). Buzina, bem acima. É um dos separadores mais úteis
    do sistema, e é medível sem modelo nenhum.

    Por que a raia espectral e não a autocorrelação, que seria o caminho óbvio:
    a autocorrelação também é alta no período do *batimento* entre duas notas
    próximas. As duas notas de uma buzina (440 e 554 Hz) batem em 114 Hz — e a
    buzina passaria por escapamento, que é exatamente o falso positivo que este
    módulo existe para evitar.

    A exigência de proeminência sobre a vizinhança é o que impede ruído de
    banda larga de produzir uma fundamental inventada: em ruído, nenhuma raia se
    destaca das vizinhas.
    """
    faixa = (frequencias >= f_min) & (frequencias <= f_max)
    if not np.any(faixa) or espectro.max() <= 0:
        return 0.0

    indices = np.flatnonzero(faixa)
    vizinhanca = max(8, len(espectro) // 200)
    limiar_global = 0.02 * float(espectro.max())

    for i in indices:
        if espectro[i] < limiar_global:
            continue
        if i == 0 or i + 1 >= len(espectro):
            continue
        if not (espectro[i] >= espectro[i - 1] and espectro[i] >= espectro[i + 1]):
            continue
        janela = espectro[max(0, i - vizinhanca) : i + vizinhanca + 1]
        if espectro[i] >= 10.0 * (float(np.median(janela)) + EPS):
            return float(frequencias[i])
    return 0.0


def _forca_harmonica(espectro: np.ndarray, frequencias: np.ndarray, f0: float) -> float:
    if f0 <= 0:
        return 0.0
    largura = max(2.0, f0 * 0.06)
    total = float(np.sum(espectro)) + EPS
    harmonicas = 0.0
    for ordem in range(1, 13):
        alvo = ordem * f0
        if alvo > frequencias[-1]:
            break
        perto = np.abs(frequencias - alvo) <= largura
        harmonicas += float(np.sum(espectro[perto]))
    return float(np.clip(harmonicas / total, 0.0, 1.0))


def extrair_descritores(
    amostras: np.ndarray, taxa_amostragem: int, segundos: float = SEGUNDOS_ANALISE
) -> Descritores:
    x = trecho_central(amostras, taxa_amostragem, segundos)
    if len(x) < 512 or np.allclose(x, 0):
        return Descritores(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    janela = np.hanning(len(x))
    espectro = np.abs(np.fft.rfft(x * janela)) ** 2
    frequencias = np.fft.rfftfreq(len(x), d=1.0 / taxa_amostragem)
    total = float(np.sum(espectro)) + EPS

    f0 = _f0_por_espectro(espectro, frequencias)
    centroide = float(np.sum(frequencias * espectro) / total)
    planicidade = float(
        np.exp(np.mean(np.log(espectro + EPS))) / (np.mean(espectro) + EPS)
    )

    env, salto = envelope(x)
    taxa_env = taxa_amostragem / salto
    env_media = float(np.mean(env)) + EPS
    crista = float(np.max(env) / env_media)

    env_centrado = env - env.mean()
    espectro_env = np.abs(np.fft.rfft(env_centrado * np.hanning(len(env_centrado))))
    freq_env = np.fft.rfftfreq(len(env_centrado), d=1.0 / taxa_env)
    faixa_mod = (freq_env >= 4.0) & (freq_env <= min(120.0, taxa_env / 2 - 1))
    if np.any(faixa_mod) and np.max(espectro_env[faixa_mod]) > 0:
        indice = int(np.argmax(np.where(faixa_mod, espectro_env, 0.0)))
        modulacao = float(freq_env[indice])
        profundidade = float(
            np.clip(espectro_env[indice] / (np.sum(espectro_env[faixa_mod]) + EPS), 0.0, 1.0)
        )
    else:
        modulacao, profundidade = 0.0, 0.0

    limiar = 0.5 * float(np.max(env))
    acima = env > limiar
    cruzamentos = int(np.sum(np.diff(acima.astype(int)) == 1))
    duracao = len(env) / taxa_env
    taxa_impulsos = cruzamentos / max(duracao, EPS)
    duracao_ativa = float(np.sum(env > 0.25 * np.max(env)) / taxa_env)

    return Descritores(
        f0_hz=f0,
        forca_harmonica=_forca_harmonica(espectro, frequencias, f0),
        centroide_hz=centroide,
        planicidade=planicidade,
        energia_grave=float(np.sum(espectro[frequencias < 200.0]) / total),
        energia_aguda=float(np.sum(espectro[frequencias > 2000.0]) / total),
        modulacao_hz=modulacao,
        profundidade_modulacao=profundidade,
        crista=crista,
        taxa_impulsos_hz=taxa_impulsos,
        duracao_ativa_s=duracao_ativa,
    )
