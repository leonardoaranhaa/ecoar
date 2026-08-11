"""Classificador de referência — regras explícitas sobre descritores físicos.

PARA QUE ELE EXISTE

1. **Explicabilidade.** A decisão sai em português: "fundamental de 84 Hz, série
   harmônica forte, 47 estalos por segundo". Um operador municipal, um advogado
   e um juiz conseguem seguir o raciocínio. Uma rede neural, não.
2. **Determinismo.** Mesma entrada, mesma versão de regras, mesma saída. Sempre.
3. **Piso de segurança.** Se o modelo neural não carregar no nó, o sistema não
   fica sem classificador — degrada para este, e registra que degradou.

O QUE ELE NÃO É

Não é a versão final. Os limiares abaixo foram calibrados na cena sintética de
bancada (`edge/audio_capture/sintetico.py`), que foi escrita por nós — o que
significa que ele acerta os sinais de bancada por construção, e isso **não é
evidência de acerto em campo**.

O caminho de produção é o classificador neural treinado com gravação real de
Bauru, confirmada por operador humano. Enquanto essa gravação não existe, este
módulo é o que permite a cadeia inteira funcionar e ser testada — e, quando ela
existir, os limiares aqui precisam ser recalibrados contra ela ou este
classificador vira apenas o piso de segurança do item 3.
"""

from __future__ import annotations

import numpy as np

from edge.classifier.base import CLASSES, Classificador, Predicao, normalizar_scores
from edge.classifier.features import Descritores, extrair_descritores

VERSAO_REGRAS = "heuristico/1.0-bancada"

PISO_REGRA = 0.02


def _rampa_sobe(valor: float, zero: float, um: float) -> float:
    if um == zero:
        return 1.0 if valor >= um else 0.0
    return float(np.clip((valor - zero) / (um - zero), 0.0, 1.0))


def _rampa_desce(valor: float, um: float, zero: float) -> float:
    return 1.0 - _rampa_sobe(valor, um, zero)


def _faixa(valor: float, zero_baixo: float, um_baixo: float, um_alto: float, zero_alto: float) -> float:
    """Pertinência trapezoidal: 1 dentro da faixa, caindo suave nas bordas.

    Borda suave em vez de corte seco é o que impede um valor de 139,9 Hz e outro
    de 140,1 Hz terem destinos opostos.
    """
    return float(
        min(_rampa_sobe(valor, zero_baixo, um_baixo), _rampa_desce(valor, um_alto, zero_alto))
    )


def _combinar(regras: dict[str, tuple[float, float]]) -> float:
    """Média geométrica ponderada: uma regra violada derruba o conjunto.

    Média aritmética deixaria um som com fundamental de buzina passar por
    escapamento só porque acertou as outras quatro regras. Aqui, não passa.
    """
    pesos = np.array([peso for _, peso in regras.values()])
    valores = np.array([max(valor, PISO_REGRA) for valor, _ in regras.values()])
    return float(np.exp(np.sum(pesos * np.log(valores)) / max(pesos.sum(), 1e-9)))


def _regras_escapamento(d: Descritores) -> dict[str, tuple[float, float]]:
    return {
        "fundamental grave de motor (55–140 Hz)": (_faixa(d.f0_hz, 45, 55, 140, 200), 2.0),
        "série harmônica forte": (_rampa_sobe(d.forca_harmonica, 0.20, 0.40), 1.5),
        "energia espalhada, não só grave": (_faixa(d.energia_grave, 0.10, 0.25, 0.85, 0.97), 1.0),
        "estalo rápido de explosão": (_rampa_sobe(d.taxa_impulsos_hz, 5.0, 18.0), 1.5),
        "espectro tonal, não ruidoso": (_rampa_desce(d.planicidade, 0.08, 0.25), 1.0),
        # Passagem é transitória. Rumor de tráfego distante tem fundamental
        # grave e harmônicas, e é o falso positivo mais provável deste
        # classificador — o que o separa é a duração.
        "duração de passagem, não rumor contínuo": (
            _faixa(d.duracao_ativa_s, 0.2, 0.4, 2.4, 3.0),
            1.0,
        ),
    }


def _regras_buzina(d: Descritores) -> dict[str, tuple[float, float]]:
    return {
        "tom agudo estável (300–900 Hz)": (_faixa(d.f0_hz, 250, 320, 900, 1100), 2.0),
        "poucas harmônicas, muito tonal": (_rampa_sobe(d.forca_harmonica, 0.15, 0.35), 1.0),
        "sem estalo repetido": (_rampa_desce(d.taxa_impulsos_hz, 3.0, 9.0), 1.5),
        "pouca energia grave": (_rampa_desce(d.energia_grave, 0.10, 0.35), 1.0),
    }


def _regras_obra(d: Descritores) -> dict[str, tuple[float, float]]:
    return {
        "impactos repetidos (5–25 por segundo)": (_faixa(d.taxa_impulsos_hz, 3, 5, 25, 40), 2.0),
        "envoltória de impacto, não contínua": (_rampa_sobe(d.crista, 1.8, 3.0), 1.5),
        "sem série harmônica de motor": (_rampa_desce(d.forca_harmonica, 0.30, 0.70), 1.0),
        "energia acima do grave": (_rampa_desce(d.energia_grave, 0.20, 0.60), 1.0),
    }


def _regras_trovao(d: Descritores) -> dict[str, tuple[float, float]]:
    return {
        "energia quase toda no grave": (_rampa_sobe(d.energia_grave, 0.45, 0.70), 2.0),
        "centro espectral baixo": (_rampa_desce(d.centroide_hz, 600, 1400), 1.0),
        "fundamental abaixo de motor": (_rampa_desce(d.f0_hz, 45, 90), 1.0),
        "estouro com cauda, não contínuo": (_rampa_sobe(d.crista, 2.0, 3.2), 1.5),
    }


_REGRAS = {
    "escapamento_adulterado": _regras_escapamento,
    "buzina": _regras_buzina,
    "obra": _regras_obra,
    "trovao": _regras_trovao,
}


class ClassificadorHeuristico(Classificador):
    nome = "heuristico"
    versao = VERSAO_REGRAS

    def classificar(self, amostras: np.ndarray, taxa_amostragem: int) -> Predicao:
        descritores = extrair_descritores(amostras, taxa_amostragem)
        return self.classificar_descritores(descritores)

    def classificar_descritores(self, descritores: Descritores) -> Predicao:
        avaliacoes = {
            classe: regras(descritores) for classe, regras in _REGRAS.items()
        }
        brutos = {classe: _combinar(regras) for classe, regras in avaliacoes.items()}

        # Ambiente é a ausência de assinatura, não uma assinatura própria: é o
        # que sobra quando nada específico se confirma.
        brutos["ambiente"] = float(np.clip(1.0 - max(brutos.values()), 0.0, 1.0))

        scores = normalizar_scores({classe: brutos.get(classe, 0.0) for classe in CLASSES})
        vencedora = max(scores, key=scores.get)

        return Predicao(
            classe=vencedora,
            score=scores[vencedora],
            scores=scores,
            modelo=self.nome,
            versao_modelo=self.versao,
            explicacao=_explicar(vencedora, avaliacoes.get(vencedora, {}), descritores),
            descritores=descritores.como_dict(),
        )


def _explicar(classe: str, regras: dict[str, tuple[float, float]], d: Descritores) -> str:
    if classe == "ambiente":
        return (
            "nenhuma assinatura específica se confirmou: "
            f"fundamental {d.f0_hz:.0f} Hz, força harmônica {d.forca_harmonica:.2f}, "
            f"{d.taxa_impulsos_hz:.0f} impulsos/s"
        )
    ordenadas = sorted(regras.items(), key=lambda item: item[1][0], reverse=True)
    a_favor = [nome for nome, (valor, _) in ordenadas if valor >= 0.6]
    contra = [nome for nome, (valor, _) in ordenadas if valor < 0.4]

    partes = []
    if a_favor:
        partes.append("a favor: " + "; ".join(a_favor))
    if contra:
        partes.append("contra: " + "; ".join(contra))
    medidas = (
        f"(fundamental {d.f0_hz:.0f} Hz, harmônicas {d.forca_harmonica:.2f}, "
        f"{d.taxa_impulsos_hz:.0f} impulsos/s, grave {d.energia_grave:.2f})"
    )
    return " · ".join(partes) + " " + medidas
