"""Estimativa de azimute a partir dos atrasos entre microfones.

Como se chega ao ângulo, em três passos:

1. cada par de microfones dá uma diferença de tempo de chegada (GCC-PHAT);
2. para cada ângulo candidato, a geometria do array diz qual seria a diferença
   esperada em cada par;
3. o ângulo escolhido é o que melhor explica as seis diferenças medidas ao mesmo
   tempo — não o que casa com um par sozinho.

Usar os seis pares juntos é o que resolve a ambiguidade frente/trás que um único
par de microfones nunca resolve, e o que dá uma medida honesta de incerteza:
quando as diferenças não se explicam por nenhum ângulo, o resíduo sobe e a
confiança cai, em vez de o sistema apontar com falsa precisão.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from edge.audio_capture.buffer import Janela
from edge.geometria import ArrayCircular
from edge.localization.gcc_phat import gcc_phat

VERSAO_ALGORITMO = "gcc-phat/1.0"

BANDA_PADRAO_HZ = (150.0, 3500.0)
AMOSTRAS_ANALISE = 8192
PASSO_GRADE_GRAUS = 1.0
PASSO_REFINO_GRAUS = 0.05


@dataclass(frozen=True)
class EstimativaDOA:
    """Ângulo de chegada, com o quanto se pode confiar nele."""

    azimute_graus: float
    confianca: float  # 0..1
    margem_graus: float
    residuo_us: float
    qualidade_media: float
    tdoas_us: dict[str, float]
    instante_analise: float | None = None
    algoritmo: str = VERSAO_ALGORITMO

    @property
    def confiavel(self) -> bool:
        """Critério grosseiro para uso direto; a política de decisão fina é do
        `camera_trigger`, que é quem versiona limiar."""
        return self.confianca >= 0.5 and self.margem_graus <= 15.0

    def como_dict(self) -> dict[str, object]:
        return {
            "azimute_graus": round(self.azimute_graus, 2),
            "confianca": round(self.confianca, 3),
            "margem_graus": round(self.margem_graus, 2),
            "residuo_us": round(self.residuo_us, 2),
            "qualidade_media": round(self.qualidade_media, 3),
            "tdoas_us": {par: round(valor, 2) for par, valor in self.tdoas_us.items()},
            "algoritmo": self.algoritmo,
        }


class Localizador:
    """Estimador de azimute amarrado à geometria de um nó."""

    def __init__(
        self,
        array: ArrayCircular,
        banda_hz: tuple[float, float] | None = None,
        interpolacao: int = 16,
        amostras_analise: int = AMOSTRAS_ANALISE,
    ) -> None:
        self.array = array
        self.interpolacao = interpolacao
        self.amostras_analise = amostras_analise

        # Acima da frequência de ambiguidade do array a fase se repete e o par
        # mais afastado passa a mentir. Limitar a banda custa pouco e evita
        # estimativa deslocada em som agudo.
        limite_alto = min(
            (banda_hz or BANDA_PADRAO_HZ)[1], 0.9 * array.frequencia_ambiguidade_hz
        )
        self.banda_hz = ((banda_hz or BANDA_PADRAO_HZ)[0], limite_alto)

        self._grade = np.arange(0.0, 360.0, PASSO_GRADE_GRAUS)
        self._tdoas_grade = np.array(
            [array.tdoas_teoricos(angulo) for angulo in self._grade]
        )

    def estimar(self, amostras: np.ndarray, taxa_amostragem: int) -> EstimativaDOA:
        amostras = np.asarray(amostras, dtype=np.float64)
        if amostras.ndim != 2 or amostras.shape[1] != self.array.n_microfones:
            raise ValueError(
                f"esperava (n, {self.array.n_microfones}) canais, recebi {amostras.shape}"
            )

        trecho, deslocamento = _trecho_de_analise(amostras, self.amostras_analise)

        pares = self.array.pares()
        tdoas = np.zeros(len(pares))
        qualidades = np.zeros(len(pares))
        posicoes = self.array.posicoes()

        for indice, (i, j) in enumerate(pares):
            distancia = float(np.linalg.norm(posicoes[i] - posicoes[j]))
            resultado = gcc_phat(
                trecho[:, i],
                trecho[:, j],
                taxa_amostragem=taxa_amostragem,
                interpolacao=self.interpolacao,
                atraso_maximo_s=distancia / self.array.velocidade_som_ms,
                banda_hz=self.banda_hz,
            )
            tdoas[indice] = resultado.tdoa_s
            qualidades[indice] = resultado.qualidade

        azimute, custo_min, custos = self._buscar_azimute(tdoas, qualidades)
        residuo = self._residuo(tdoas, qualidades, azimute)
        margem = self._margem(custos, custo_min, residuo, qualidades)
        confianca = self._confianca(residuo, qualidades, margem)

        return EstimativaDOA(
            azimute_graus=float(azimute % 360.0),
            confianca=confianca,
            margem_graus=margem,
            residuo_us=residuo * 1e6,
            qualidade_media=float(np.mean(qualidades)),
            tdoas_us={f"{i}-{j}": tdoas[k] * 1e6 for k, (i, j) in enumerate(pares)},
            instante_analise=float(deslocamento / taxa_amostragem),
        )

    def estimar_janela(self, janela: Janela) -> EstimativaDOA:
        estimativa = self.estimar(janela.amostras, janela.taxa_amostragem)
        if estimativa.instante_analise is None:
            return estimativa
        return replace(
            estimativa, instante_analise=janela.inicio + estimativa.instante_analise
        )

    # -- internos --------------------------------------------------------

    def _custos(self, tdoas: np.ndarray, pesos: np.ndarray) -> np.ndarray:
        erros = self._tdoas_grade - tdoas[None, :]
        return np.sum(pesos[None, :] * erros**2, axis=1)

    def _buscar_azimute(
        self, tdoas: np.ndarray, qualidades: np.ndarray
    ) -> tuple[float, float, np.ndarray]:
        pesos = qualidades if qualidades.sum() > 0 else np.ones_like(qualidades)
        custos = self._custos(tdoas, pesos)
        melhor = float(self._grade[int(np.argmin(custos))])

        # Refino local: a grade de 1° não chega nos ±5° de precisão-alvo.
        vizinhanca = np.arange(
            melhor - PASSO_GRADE_GRAUS, melhor + PASSO_GRADE_GRAUS, PASSO_REFINO_GRAUS
        )
        finos = np.array(
            [
                np.sum(pesos * (self.array.tdoas_teoricos(angulo) - tdoas) ** 2)
                for angulo in vizinhanca
            ]
        )
        indice = int(np.argmin(finos))
        return float(vizinhanca[indice]), float(finos[indice]), custos

    def _residuo(self, tdoas: np.ndarray, qualidades: np.ndarray, azimute: float) -> float:
        erros = self.array.tdoas_teoricos(azimute) - tdoas
        pesos = qualidades if qualidades.sum() > 0 else np.ones_like(qualidades)
        return float(np.sqrt(np.sum(pesos * erros**2) / max(pesos.sum(), 1e-12)))

    def _margem(
        self,
        custos: np.ndarray,
        custo_min: float,
        residuo: float,
        qualidades: np.ndarray,
    ) -> float:
        """Largura angular do conjunto de ângulos igualmente plausíveis.

        Não é desvio-padrão de estatística: é a resposta a "que faixa de ângulos
        explicaria essas medições tão bem quanto a melhor?". É o número que vai
        para a evidência, porque é o que uma contestação vai questionar.
        """
        pesos = qualidades if qualidades.sum() > 0 else np.ones_like(qualidades)
        tolerancia = max(residuo, 1e-6) ** 2 * pesos.sum()
        limiar = custo_min + tolerancia

        dentro = custos <= limiar
        if dentro.all():
            return 180.0
        # A grade é circular: procura a extensão contígua em volta do mínimo.
        melhor = int(np.argmin(custos))
        n = len(custos)
        largura = 1
        for passo in range(1, n // 2 + 1):
            if not dentro[(melhor + passo) % n] and not dentro[(melhor - passo) % n]:
                break
            largura += 1
        return float(min(180.0, largura * PASSO_GRADE_GRAUS))

    def _confianca(self, residuo: float, qualidades: np.ndarray, margem: float) -> float:
        """Combina três coisas que precisam valer ao mesmo tempo.

        Pico de correlação destacado (o som é localizável), resíduo pequeno (um
        único ângulo explica todos os pares) e margem estreita (não há uma faixa
        larga de ângulos igualmente plausíveis). Qualquer uma falhando derruba a
        confiança — é a versão acústica do "verificado vs. inferido".
        """
        qualidade = float(np.mean(qualidades))
        tolerancia = 0.25 * self.array.atraso_maximo_s
        ajuste_residuo = float(np.exp(-((residuo / tolerancia) ** 2)))
        ajuste_margem = float(np.clip(1.0 - (margem - 2.0) / 30.0, 0.0, 1.0))
        return float(np.clip(qualidade * ajuste_residuo * ajuste_margem, 0.0, 1.0))


def _trecho_de_analise(amostras: np.ndarray, n: int) -> tuple[np.ndarray, int]:
    """Recorta o trecho mais energético — é onde o evento está.

    Rodar GCC-PHAT sobre os 20 s inteiros do pacote de evidência seria caro e
    pior: diluiria o instante da passagem no meio de silêncio e de outros sons.
    """
    total = len(amostras)
    if total <= n:
        return amostras, 0

    energia = np.mean(amostras**2, axis=1)
    janela = max(1, n // 8)
    suavizada = np.convolve(energia, np.ones(janela) / janela, mode="same")
    centro = int(np.argmax(suavizada))

    inicio = int(np.clip(centro - n // 2, 0, total - n))
    return amostras[inicio : inicio + n], inicio
