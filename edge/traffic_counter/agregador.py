"""Agregação de contagem de tráfego por hora e tipo de veículo.

Não guarda quadro a quadro nem placa (D10 é sobre placa especificamente, mas o
princípio de minimização de docs/legal/lgpd.md vale aqui também) — só soma.
Isso é o que mantém este dado fora da fila de revisão (D2 exige validação
humana para virar estatística de priorização ou dado de treino; contagem de
tráfego não é nenhum dos dois, é dado operacional de mobilidade).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Agregado:
    dia: str  # AAAA-MM-DD
    hora: int  # 0-23
    tipo: str
    contagem: int

    def como_dict(self) -> dict:
        return {"dia": self.dia, "hora": self.hora, "tipo": self.tipo, "contagem": self.contagem}


class AgregadorTrafego:
    """Soma contagens em memória por (dia, hora, tipo).

    Um produtor (o laço de captura) e um consumidor (o envio periódico ao
    backend) — não precisa de lock: cada `drenar()` esvazia o que já foi
    somado, e a próxima soma começa um agregado novo.
    """

    def __init__(self) -> None:
        self._contagens: dict[tuple[str, int, str], int] = defaultdict(int)

    def somar(self, tipo: str, instante: float | None = None) -> None:
        momento = (
            datetime.fromtimestamp(instante, tz=timezone.utc)
            if instante is not None
            else datetime.now(tz=timezone.utc)
        )
        chave = (momento.strftime("%Y-%m-%d"), momento.hour, tipo)
        self._contagens[chave] += 1

    def drenar(self) -> list[Agregado]:
        """Devolve os agregados acumulados desde o último drenar e zera."""
        agregados = [
            Agregado(dia=dia, hora=hora, tipo=tipo, contagem=contagem)
            for (dia, hora, tipo), contagem in self._contagens.items()
        ]
        self._contagens.clear()
        return agregados

    def total(self) -> int:
        return sum(self._contagens.values())
