"""Simulação de condição de rua sobre áudio limpo.

Para que serve: uma gravação de escapamento feita de perto, com o celular a dois
metros, não se parece com o que o array vai ouvir a 12 metros de altura, com
tráfego ao fundo e reflexão em fachada. Treinar no áudio limpo e operar na rua
é a receita conhecida para um modelo que funciona na bancada e falha no poste.

O que se aplica, na ordem em que a física aplica:

1. **distância** — o som perde 6 dB a cada dobro de distância, e o ar absorve
   mais agudo do que grave, então o timbre muda além do volume;
2. **reverberação** — fachada, muro e asfalto devolvem cópias atrasadas;
3. **ruído de fundo** — tráfego, vento, o rumor da cidade.

Isto **não substitui** gravação de campo. Serve para multiplicar as amostras
reais que existirem e para pré-treinar antes de haver acervo próprio. Um modelo
treinado só com áudio aumentado é um modelo não validado.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DISTANCIA_REFERENCIA_M = 7.0  # a mesma da Res. 418/09 do Conama


def ruido_urbano(
    n_amostras: int, taxa_amostragem: int, rng: np.random.Generator
) -> np.ndarray:
    """Ruído com espectro decrescente, parecido com rumor de tráfego.

    Ruído branco soa como chuvisco e não engana modelo nenhum. O ruído de rua
    tem muito mais energia no grave, e é essa forma que precisa estar presente
    no treino.
    """
    branco = rng.normal(0.0, 1.0, n_amostras)
    espectro = np.fft.rfft(branco)
    frequencias = np.fft.rfftfreq(n_amostras, d=1.0 / taxa_amostragem)
    forma = 1.0 / np.sqrt(np.maximum(frequencias, 20.0))
    ruidoso = np.fft.irfft(espectro * forma, n=n_amostras)
    return ruidoso / (np.std(ruidoso) + 1e-12)


def adicionar_ruido(
    sinal: np.ndarray, taxa_amostragem: int, snr_db: float, rng: np.random.Generator
) -> np.ndarray:
    ruido = ruido_urbano(len(sinal), taxa_amostragem, rng)
    potencia_sinal = float(np.mean(sinal**2)) + 1e-12
    escala = np.sqrt(potencia_sinal / (10.0 ** (snr_db / 10.0)))
    return sinal + escala * ruido


PROPORCAO_REVERBERANTE = 0.35


def resposta_impulsiva(
    taxa_amostragem: int,
    t60_s: float,
    rng: np.random.Generator,
    proporcao_reverberante: float = PROPORCAO_REVERBERANTE,
) -> np.ndarray:
    """Reverberação sintética: som direto mais cauda de ruído com decaimento.

    Não é a resposta de uma rua específica — para isso seria preciso medir em
    campo. É o suficiente para o modelo deixar de assumir que o som chega limpo.

    `proporcao_reverberante` é a energia da cauda em relação à do som direto, e
    precisa ser explícita: normalizar a resposta inteira pela energia total
    afundaria o som direto e simularia uma catedral, não uma rua com fachadas.
    Em via aberta o som direto domina — daí o padrão de 0,35.
    """
    n = max(64, int(t60_s * taxa_amostragem))
    decaimento = np.exp(-6.9 * np.arange(1, n) / n)  # -60 dB ao fim
    cauda = rng.normal(0.0, 1.0, n - 1) * decaimento
    cauda *= np.sqrt(proporcao_reverberante) / (np.linalg.norm(cauda) + 1e-12)
    return np.concatenate(([1.0], cauda))


def reverberar(
    sinal: np.ndarray, taxa_amostragem: int, t60_s: float, rng: np.random.Generator
) -> np.ndarray:
    """Aplica reverberação mantendo o som direto no lugar.

    Convolução centralizada (`mode="same"`) adiantaria o sinal em metade da
    resposta impulsiva — o eco chegaria antes do som que o produziu. Aqui a
    convolução completa é truncada no fim: o som direto fica alinhado e a cauda
    que passar do trecho é descartada, como aconteceria numa janela de captura.
    """
    impulso = resposta_impulsiva(taxa_amostragem, t60_s, rng)
    return np.convolve(sinal, impulso)[: len(sinal)]


def atenuar_distancia(
    sinal: np.ndarray,
    taxa_amostragem: int,
    distancia_m: float,
    referencia_m: float = DISTANCIA_REFERENCIA_M,
) -> np.ndarray:
    """Perda por divergência esférica mais absorção do ar no agudo."""
    if distancia_m <= 0:
        raise ValueError("distância precisa ser positiva")
    ganho = referencia_m / distancia_m

    espectro = np.fft.rfft(sinal)
    frequencias = np.fft.rfftfreq(len(sinal), d=1.0 / taxa_amostragem)
    # Absorção do ar cresce com a frequência e com a distância percorrida.
    # Coeficiente de ordem de grandeza para ar seco em temperatura ambiente.
    absorcao_db = 0.0002 * (frequencias / 1000.0) ** 1.7 * distancia_m * 100.0
    return np.fft.irfft(espectro * ganho * 10.0 ** (-absorcao_db / 20.0), n=len(sinal))


@dataclass(frozen=True)
class Variacao:
    distancia_m: float
    t60_s: float
    snr_db: float

    def como_dict(self) -> dict[str, float]:
        return {"distancia_m": self.distancia_m, "t60_s": self.t60_s, "snr_db": self.snr_db}


def aplicar(
    sinal: np.ndarray, taxa_amostragem: int, variacao: Variacao, rng: np.random.Generator
) -> np.ndarray:
    saida = atenuar_distancia(sinal, taxa_amostragem, variacao.distancia_m)
    saida = reverberar(saida, taxa_amostragem, variacao.t60_s, rng)
    saida = adicionar_ruido(saida, taxa_amostragem, variacao.snr_db, rng)
    pico = float(np.max(np.abs(saida))) + 1e-12
    return (saida / pico * 0.9) if pico > 1.0 else saida


def sortear_variacao(rng: np.random.Generator) -> Variacao:
    """Faixas escolhidas para cobrir a instalação real: nó a 4,5–5 m de altura,
    veículo passando a até 15 m, em via com fachadas dos dois lados."""
    return Variacao(
        distancia_m=float(rng.uniform(5.0, 18.0)),
        t60_s=float(rng.uniform(0.15, 0.9)),
        snr_db=float(rng.uniform(-3.0, 18.0)),
    )


def gerar_variacoes(
    sinal: np.ndarray,
    taxa_amostragem: int,
    quantidade: int,
    semente: int = 0,
) -> list[tuple[np.ndarray, Variacao]]:
    rng = np.random.default_rng(semente)
    return [
        (aplicar(sinal, taxa_amostragem, variacao, rng), variacao)
        for variacao in (sortear_variacao(rng) for _ in range(quantidade))
    ]
