"""Classificador de tipo de veículo por quadro.

Confirma moto/carro/ônibus/caminhão — nunca lê placa. Isso é
`vision/plate_ocr` (D10), roda no backend, e continua desligado em
`modo=triagem`. Este módulo não tem nenhuma relação com aquele: não recebe a
imagem para OCR, só para contagem por tipo.

Diferente do classificador acústico de escapamento (`edge/classifier`), aqui
existe modelo pré-treinado público de detecção de veículo por tipo — não é
preciso treinar do zero quando o modelo real for integrado (ver seção
"Próximo passo" abaixo). O que roda hoje é o classificador simulado, no mesmo
espírito da `CameraSimulada` (`edge/camera_trigger/camera.py`): saída
deliberadamente sintética, nunca confundível com uma detecção real.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass

TIPOS_VEICULO = ("moto", "carro", "onibus", "caminhao")
NENHUM = "nenhum"


@dataclass(frozen=True)
class ClassificacaoVeiculo:
    tipo: str  # um de TIPOS_VEICULO, ou NENHUM
    confianca: float
    simulado: bool

    def como_dict(self) -> dict:
        return {
            "tipo": self.tipo,
            "confianca": round(self.confianca, 2),
            "simulado": self.simulado,
        }


class ClassificadorVeiculo(ABC):
    nome: str = "abstrato"
    simulado: bool = True

    @abstractmethod
    def classificar(self, quadro=None) -> ClassificacaoVeiculo: ...


class ClassificadorSimulado(ClassificadorVeiculo):
    """Distribuição plausível de tipos de veículo, sem olhar o quadro de verdade.

    Serve para desenvolver e demonstrar o pipeline inteiro (agregação, envio,
    dashboard) antes de existir um modelo real integrado. `confianca` também é
    sintética — nunca deve ser lida como probabilidade calibrada.
    """

    nome = "simulado"
    simulado = True

    # Mistura de tráfego urbano plausível — não é medição, é só o que faz a
    # demonstração parecer uma via real em vez de sorteio uniforme entre tipos.
    _PESOS = {"moto": 0.38, "carro": 0.48, "onibus": 0.05, "caminhao": 0.07, NENHUM: 0.02}

    def __init__(self, semente: int | None = None) -> None:
        self._rng = random.Random(semente)

    def classificar(self, quadro=None) -> ClassificacaoVeiculo:
        tipo = self._rng.choices(
            list(self._PESOS), weights=list(self._PESOS.values()), k=1
        )[0]
        confianca = 0.0 if tipo == NENHUM else round(self._rng.uniform(0.72, 0.97), 2)
        return ClassificacaoVeiculo(tipo=tipo, confianca=confianca, simulado=True)


def criar_classificador(config) -> ClassificadorVeiculo:
    if config.classificador == "modelo":
        raise NotImplementedError(
            "trafego.classificador='modelo' ainda não tem implementação real "
            "integrada — ver edge/traffic_counter/README.md"
        )
    return ClassificadorSimulado()
