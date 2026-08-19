"""Detector de transiente (protótipo conceitual) — nunca classifica disparo.

Cobre só o que o módulo realmente faz: achar um pico de energia acima do piso
local. Não existe teste de "acerta disparo" porque o módulo não tenta acertar
disparo — ver edge/gunshot_detection/README.md.
"""

import numpy as np
import pytest

from edge.config import ConfiguracaoInvalida, de_dict
from edge.gunshot_detection import CANDIDATO_TRANSIENTE, DetectorTransiente
from tests.conftest import config_base

TAXA = 16000


def _config(**disparo):
    dados = config_base(disparo={"habilitado": True, **disparo})
    return de_dict(dados)


def _silencio(segundos: float = 1.0) -> np.ndarray:
    rng = np.random.default_rng(0)
    return (rng.standard_normal(int(TAXA * segundos)) * 1e-4).astype(np.float32)


def _com_pico(segundos: float = 1.0, posicao_s: float = 0.5, amplitude: float = 1.0) -> np.ndarray:
    sinal = _silencio(segundos)
    indice = int(posicao_s * TAXA)
    largura = int(0.01 * TAXA)  # 10 ms — transiente curto
    sinal[indice : indice + largura] += amplitude
    return sinal


# -- desligado por padrão -------------------------------------------------


def test_detector_desligado_nao_detecta_nada():
    config = de_dict(config_base())  # disparo.habilitado é False por padrão
    detector = DetectorTransiente(config)

    resultado = detector.detectar(_com_pico(amplitude=5.0), TAXA)

    assert resultado is None


# -- detecção de transiente -----------------------------------------------


def test_pico_muito_acima_do_piso_e_detectado():
    config = _config(limiar_energia_db=20.0)
    detector = DetectorTransiente(config)

    resultado = detector.detectar(_com_pico(amplitude=5.0), TAXA)

    assert resultado is not None
    assert resultado.tipo == CANDIDATO_TRANSIENTE
    assert resultado.validado is False
    assert resultado.pico_relativo_db >= 20.0


def test_silencio_nao_dispara():
    config = _config(limiar_energia_db=20.0)
    detector = DetectorTransiente(config)

    resultado = detector.detectar(_silencio(), TAXA)

    assert resultado is None


def test_resultado_carrega_aviso_de_nao_validado():
    config = _config(limiar_energia_db=10.0)
    detector = DetectorTransiente(config)

    resultado = detector.detectar(_com_pico(amplitude=5.0), TAXA)

    assert resultado is not None
    corpo = resultado.como_dict()
    assert "não há validação" in corpo["aviso"]
    assert corpo["validado"] is False


def test_limiar_alto_nao_dispara_para_pico_pequeno():
    # Ruído de fundo tem amplitude ~1e-4; um pico só um pouco acima disso é
    # um relativo pequeno (poucos dB), bem abaixo de um limiar exigente.
    config = _config(limiar_energia_db=80.0)
    detector = DetectorTransiente(config)

    resultado = detector.detectar(_com_pico(amplitude=3e-4), TAXA)

    assert resultado is None


def test_estereo_usa_primeiro_canal():
    config = _config(limiar_energia_db=20.0)
    detector = DetectorTransiente(config)
    mono = _com_pico(amplitude=5.0)
    multi = np.stack([mono, np.zeros_like(mono)], axis=1)

    resultado = detector.detectar(multi, TAXA)

    assert resultado is not None


# -- configuração ------------------------------------------------------


def test_disparo_desligado_por_padrao():
    config = de_dict(config_base()).disparo
    assert config.habilitado is False


def test_limiar_energia_invalido_e_recusado():
    with pytest.raises(ConfiguracaoInvalida, match="limiar_energia_db"):
        de_dict(config_base(disparo={"limiar_energia_db": 0}))


def test_janela_analise_invalida_e_recusada():
    with pytest.raises(ConfiguracaoInvalida, match="janela_analise_ms"):
        de_dict(config_base(disparo={"janela_analise_ms": -1}))
