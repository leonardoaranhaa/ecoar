"""Classificação de assinatura acústica."""

from __future__ import annotations

import logging

from edge.classifier.base import (
    CLASSE_ALVO,
    CLASSES,
    Classificador,
    ClassificadorIndisponivel,
    Predicao,
)
from edge.classifier.features import Descritores, extrair_descritores, log_mel
from edge.classifier.heuristico import ClassificadorHeuristico
from edge.config import ConfigNo

log = logging.getLogger("ecoar.classifier")

__all__ = [
    "CLASSES",
    "CLASSE_ALVO",
    "Classificador",
    "ClassificadorHeuristico",
    "ClassificadorIndisponivel",
    "Descritores",
    "Predicao",
    "criar_classificador",
    "extrair_descritores",
    "log_mel",
]


def criar_classificador(config: ConfigNo) -> Classificador:
    """Instancia o classificador declarado, com degradação registrada.

    Em `auto`, a falha de carregar o modelo neural não derruba o nó — mas
    aparece no log e, o que importa mais, aparece na evidência: cada predição
    carrega qual modelo a produziu. Ninguém descobre seis meses depois que o
    nó rodou o tempo todo no classificador de referência sem saber.
    """
    escolha = config.classificador

    if escolha.tipo == "heuristico":
        return ClassificadorHeuristico()

    if escolha.tipo in ("cnn", "auto") and escolha.modelo:
        from edge.classifier.cnn import ClassificadorCNN

        try:
            return ClassificadorCNN(escolha.modelo).carregar()
        except ClassificadorIndisponivel as erro:
            if escolha.tipo == "cnn":
                raise
            log.warning(
                "modelo neural indisponível (%s); operando com o classificador "
                "de referência — a evidência registrará isso",
                erro,
            )

    if escolha.tipo == "cnn":
        raise ClassificadorIndisponivel("classificador.tipo='cnn' exige classificador.modelo")

    return ClassificadorHeuristico()
