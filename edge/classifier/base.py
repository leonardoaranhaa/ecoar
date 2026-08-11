"""Contrato do classificador de assinatura acústica."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

CLASSE_ALVO = "escapamento_adulterado"

CLASSES = (
    CLASSE_ALVO,
    "buzina",
    "obra",
    "trovao",
    "ambiente",
)


class ClassificadorIndisponivel(RuntimeError):
    """O classificador não pôde decidir.

    Fail-closed (D8): quem chama trata isso como evento ambíguo — registra sem
    acionar a câmera. Nunca como "provavelmente não era nada".
    """


@dataclass(frozen=True)
class Predicao:
    classe: str
    score: float
    scores: dict[str, float]
    modelo: str
    versao_modelo: str
    explicacao: str = ""
    descritores: dict[str, float | str] = field(default_factory=dict)

    @property
    def e_alvo(self) -> bool:
        return self.classe == CLASSE_ALVO

    @property
    def score_alvo(self) -> float:
        """O que importa para a decisão: quanto o som parece com o que se procura.

        Não é o mesmo que `score`. Um evento classificado como buzina com 0,9 de
        certeza tem score alto e score_alvo baixo — e é o segundo que decide se
        a câmera dispara.
        """
        return float(self.scores.get(CLASSE_ALVO, 0.0))

    def como_dict(self) -> dict[str, object]:
        return {
            "classe": self.classe,
            "score": round(self.score, 4),
            "score_alvo": round(self.score_alvo, 4),
            "scores": {classe: round(valor, 4) for classe, valor in self.scores.items()},
            "modelo": self.modelo,
            "versao_modelo": self.versao_modelo,
            "explicacao": self.explicacao,
            "descritores": self.descritores,
        }


class Classificador(ABC):
    """Interface única. O `camera_trigger` não sabe qual implementação está rodando."""

    nome: str = "abstrato"
    versao: str = "0"

    @abstractmethod
    def classificar(self, amostras: np.ndarray, taxa_amostragem: int) -> Predicao: ...

    def identificacao(self) -> dict[str, str]:
        return {"modelo": self.nome, "versao_modelo": self.versao}


def normalizar_scores(brutos: dict[str, float]) -> dict[str, float]:
    """Converte pontuações em algo que soma 1, sem esconder empate.

    Empate importa: dois scores próximos é exatamente o caso em que a decisão
    deve ser "ambíguo", e achatar isso num vencedor artificial destruiria a
    informação de que o sistema estava em dúvida.
    """
    total = sum(max(valor, 0.0) for valor in brutos.values())
    if total <= 0:
        return {classe: 1.0 / len(CLASSES) for classe in CLASSES}
    return {classe: max(valor, 0.0) / total for classe, valor in brutos.items()}
