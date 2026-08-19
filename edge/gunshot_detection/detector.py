"""Detector de transiente — PROTÓTIPO CONCEITUAL, não um classificador de
disparo de arma de fogo.

O que este módulo faz de verdade: detecta um pico de energia muito acima do
piso de ruído local da janela — DSP estabelecido, a mesma família de técnica
usada em detecção de onset. O que ele NÃO faz: discriminar esse pico de outros
transientes urbanos (rojão, escapamento estourando, porta batendo, buzina
curta). Não existe validação de que o array de 4 microfones do ECOAR permite
essa discriminação, nem dataset de treino, nem o sistema de multilateração
entre nós que a localização exigiria — ver docs/projeto/prompts-claude-code.md
(Prompt 16, estudo de viabilidade) e docs/DECISIONS.md (D16).

Por isso a saída daqui nunca se chama "disparo" nem carrega um score de
confiança de arma de fogo: é sempre `candidato_transiente_nao_classificado`,
rotulado como candidato para revisão humana imediata — nunca confirmação.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from edge.classifier.features import envelope
from edge.config import ConfigNo

log = logging.getLogger("ecoar.disparo")

CANDIDATO_TRANSIENTE = "candidato_transiente_nao_classificado"

AVISO_NAO_VALIDADO = (
    "protótipo conceitual — não há validação de que este detector discrimina "
    "disparo de arma de fogo de outros transientes urbanos. Ver "
    "docs/DECISIONS.md D16 e docs/projeto/prompts-claude-code.md Prompt 16."
)


@dataclass(frozen=True)
class CandidatoTransiente:
    """Um pico de energia acima do piso local. Não é uma classificação."""

    tipo: str = CANDIDATO_TRANSIENTE
    pico_relativo_db: float = 0.0
    instante_relativo_s: float = 0.0
    validado: bool = False

    def como_dict(self) -> dict:
        return {
            "tipo": self.tipo,
            "pico_relativo_db": round(self.pico_relativo_db, 1),
            "instante_relativo_s": round(self.instante_relativo_s, 3),
            "validado": self.validado,
            "aviso": AVISO_NAO_VALIDADO,
        }


class DetectorTransiente:
    """Detecta pico de energia >= limiar acima do piso local da janela.

    O piso é a mediana da envoltória (robusta a um único pico, ao contrário da
    média) — o limiar é relativo a ele, nunca um valor absoluto de dB, porque o
    piso de ruído varia por ponto de instalação (avenida vs. rua residencial).
    """

    def __init__(self, config: ConfigNo) -> None:
        self.config = config.disparo

    def detectar(
        self, amostras: np.ndarray, taxa_amostragem: int
    ) -> CandidatoTransiente | None:
        if not self.config.habilitado:
            return None

        canal = amostras[:, 0] if amostras.ndim > 1 else amostras
        env, taxa_env = envelope(canal, taxa_amostragem)
        if env.size == 0 or taxa_env <= 0:
            return None

        piso_db = 20 * np.log10(np.median(env) + 1e-9)
        pico_idx = int(np.argmax(env))
        pico_db = 20 * np.log10(env[pico_idx] + 1e-9)
        relativo_db = float(pico_db - piso_db)

        if relativo_db < self.config.limiar_energia_db:
            return None

        log.warning(
            "candidato a transiente não classificado: %.1f dB acima do piso local "
            "(NÃO é confirmação de disparo — ver README do módulo)",
            relativo_db,
        )
        return CandidatoTransiente(
            pico_relativo_db=relativo_db,
            instante_relativo_s=float(pico_idx / taxa_env),
        )
