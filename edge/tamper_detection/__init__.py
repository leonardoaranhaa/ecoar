"""Detecção de violação patrimonial do nó."""

from edge.config import ConfigNo
from edge.tamper_detection.detector import (
    ABERTURA,
    IMPACTO,
    INCLINACAO,
    MOVIMENTO,
    QUEDA_ENERGIA,
    AlertaViolacao,
    DetectorViolacao,
)
from edge.tamper_detection.sensores import (
    SensorAbertura,
    SensorAberturaGPIO,
    SensorAberturaSimulado,
    SensorAlimentacao,
    SensorAlimentacaoSimulado,
    SensorInercial,
    SensorInercialSimulado,
    SensorMPU6050,
)

__all__ = [
    "ABERTURA",
    "AlertaViolacao",
    "DetectorViolacao",
    "IMPACTO",
    "INCLINACAO",
    "MOVIMENTO",
    "QUEDA_ENERGIA",
    "SensorAbertura",
    "SensorAberturaGPIO",
    "SensorAberturaSimulado",
    "SensorAlimentacao",
    "SensorAlimentacaoSimulado",
    "SensorInercial",
    "SensorInercialSimulado",
    "SensorMPU6050",
    "criar_detector",
]


def criar_detector(
    config: ConfigNo, ao_alerta, capturar_imagem=None, registro_local=None
) -> DetectorViolacao:
    """Instancia o detector com os sensores declarados na configuração."""
    cfg = config.tamper

    if cfg.inercial == "mpu6050":
        inercial: SensorInercial = SensorMPU6050()
    else:
        inercial = SensorInercialSimulado()

    if cfg.abertura == "gpio":
        abertura: SensorAbertura = SensorAberturaGPIO(cfg.pino_reed)
    else:
        abertura = SensorAberturaSimulado()

    # INA219 real ainda não implementado — cai no simulado com registro.
    alimentacao: SensorAlimentacao = SensorAlimentacaoSimulado()

    return DetectorViolacao(
        config=config,
        inercial=inercial,
        abertura=abertura,
        alimentacao=alimentacao,
        ao_alerta=ao_alerta,
        capturar_imagem=capturar_imagem,
        registro_local=registro_local,
    )
