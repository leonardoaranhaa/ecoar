"""GCC-PHAT — diferença de tempo de chegada entre dois microfones.

A ideia, sem matemática: o mesmo som chega aos dois microfones em instantes
levemente diferentes. Deslizando um sinal sobre o outro e vendo em que
deslocamento eles mais se parecem, descobre-se essa diferença.

O que o PHAT (Phase Transform) acrescenta: antes de comparar, o método joga
fora a informação de intensidade de cada frequência e mantém só a de fase.
Parece perda, mas é o contrário — o pico de correlação fica muito mais estreito,
e o resultado deixa de depender do timbre do som ou de uma frequência dominar a
conta. Em rua, com reverberação em parede e fachada, é a diferença entre uma
estimativa utilizável e uma inútil.

Referência: Knapp & Carter (1976), "The Generalized Correlation Method for
Estimation of Time Delay".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

EPS = 1e-12


@dataclass(frozen=True)
class ResultadoGCC:
    tdoa_s: float  # atraso de `sinal` em relação a `referencia` (positivo = chegou depois)
    qualidade: float  # 0..1 — quão destacado é o pico em relação ao resto
    pico: float

    @property
    def tdoa_us(self) -> float:
        return self.tdoa_s * 1e6


def gcc_phat(
    sinal: np.ndarray,
    referencia: np.ndarray,
    taxa_amostragem: int,
    interpolacao: int = 16,
    atraso_maximo_s: float | None = None,
    banda_hz: tuple[float, float] | None = None,
    piso_relativo: float = 0.02,
    expoente_phat: float = 0.75,
) -> ResultadoGCC:
    """Estima o atraso de `sinal` em relação a `referencia`.

    `interpolacao` dá resolução abaixo da amostra: a 48 kHz, uma amostra vale
    20,8 µs, e o array inteiro cabe em 260 µs — sem interpolar, a estimativa
    andaria aos trancos de vários graus.

    `atraso_maximo_s` descarta, antes de procurar o pico, qualquer deslocamento
    fisicamente impossível para a distância entre os dois microfones. É o que
    impede um eco de parede de virar um ângulo absurdo.

    `banda_hz` limita a busca a uma faixa de frequência. Acima da frequência de
    ambiguidade do array a fase se repete; abaixo de ~150 Hz o que existe é
    vento e rumor de tráfego, que não ajudam a localizar.

    `piso_relativo` e `expoente_phat` são o ajuste que faz esta implementação
    funcionar com o som que interessa. O PHAT clássico normaliza TODA raia de
    frequência para magnitude 1 — inclusive as que contêm apenas ruído. Um
    escapamento tem espectro de linhas: quase toda a energia mora em poucas
    dezenas de raias harmônicas, e as milhares restantes são rua. Normalizadas,
    elas entram na conta com o mesmo peso das harmônicas e afogam a estimativa.

    Medido com a cena de bancada: PHAT puro erra ~64 µs de TDOA; descartando as
    raias abaixo de 2% da magnitude máxima e usando expoente 0,75, o erro cai
    para ~3 µs. Numa abertura de array de 262 µs, é a diferença entre errar
    dezenas de graus e errar menos de um.
    """
    sinal = np.asarray(sinal, dtype=np.float64).ravel()
    referencia = np.asarray(referencia, dtype=np.float64).ravel()
    if len(sinal) != len(referencia):
        raise ValueError("os dois canais precisam ter o mesmo número de amostras")
    if len(sinal) < 8:
        raise ValueError("trecho curto demais para estimar atraso")

    n = len(sinal)
    n_fft = 1 << int(np.ceil(np.log2(2 * n)))  # zero-padding evita correlação circular

    espectro_sinal = np.fft.rfft(sinal - sinal.mean(), n=n_fft)
    espectro_ref = np.fft.rfft(referencia - referencia.mean(), n=n_fft)
    cruzado = espectro_sinal * np.conj(espectro_ref)

    if banda_hz is not None:
        frequencias = np.fft.rfftfreq(n_fft, d=1.0 / taxa_amostragem)
        fora = (frequencias < banda_hz[0]) | (frequencias > banda_hz[1])
        cruzado[fora] = 0.0

    magnitude = np.abs(cruzado)
    maior = float(magnitude.max())
    if maior <= EPS:
        return ResultadoGCC(tdoa_s=0.0, qualidade=0.0, pico=0.0)

    # Fora as raias que são só rua, e normalização parcial no que sobra.
    relevantes = magnitude >= piso_relativo * maior
    fases = np.angle(cruzado)
    cruzado = np.where(relevantes, cruzado / (magnitude**expoente_phat + EPS), 0.0)

    n_interp = n_fft * interpolacao
    correlacao = np.fft.irfft(cruzado, n=n_interp)

    limite = n_interp // 2
    if atraso_maximo_s is not None:
        limite = min(limite, int(np.ceil(atraso_maximo_s * taxa_amostragem * interpolacao)) + 1)
    if limite < 1:
        raise ValueError("atraso_maximo_s menor que a resolução temporal disponível")

    # Reordena para [-limite, +limite]: atrasos negativos moram no fim do vetor.
    janela = np.concatenate((correlacao[-limite:], correlacao[: limite + 1]))
    indice = int(np.argmax(janela))
    pico = float(janela[indice])

    deslocamento = _refinar_pico(janela, indice) - limite
    tdoa = float(deslocamento / (taxa_amostragem * interpolacao))

    frequencias = np.fft.rfftfreq(n_fft, d=1.0 / taxa_amostragem)
    qualidade = _coerencia(fases, frequencias, relevantes, tdoa)

    return ResultadoGCC(tdoa_s=tdoa, qualidade=qualidade, pico=pico)


def _coerencia(
    fases: np.ndarray, frequencias: np.ndarray, relevantes: np.ndarray, tdoa: float
) -> float:
    """Quanto das raias usadas concorda com o atraso estimado.

    Medir a qualidade pela altura do pico de correlação não funciona com som
    harmônico: um espectro de linhas produz correlação oscilante, com vários
    picos quase da mesma altura, mesmo quando a estimativa está certa.

    O que discrimina de verdade é a fase. Se existe uma fonte única, a fase de
    cada raia é exatamente −2πf·τ para o mesmo τ, e desfazer esse giro alinha
    todas elas. Sobra 1. Se o que existe é ruído, as fases apontam para todo
    lado e a soma se cancela. Sobra perto de 0.
    """
    if not np.any(relevantes):
        return 0.0
    alinhadas = np.exp(1j * (fases[relevantes] + 2 * np.pi * frequencias[relevantes] * tdoa))
    return float(np.clip(np.abs(np.mean(alinhadas)), 0.0, 1.0))


def _refinar_pico(valores: np.ndarray, indice: int) -> float:
    """Ajusta uma parábola nos três pontos em volta do pico, para ganhar precisão."""
    if indice <= 0 or indice >= len(valores) - 1:
        return float(indice)
    anterior, centro, seguinte = valores[indice - 1], valores[indice], valores[indice + 1]
    denominador = anterior - 2 * centro + seguinte
    if abs(denominador) < EPS:
        return float(indice)
    ajuste = 0.5 * (anterior - seguinte) / denominador
    return float(indice + np.clip(ajuste, -1.0, 1.0))
