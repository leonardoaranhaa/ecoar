"""Antifurto: detectar violação e fazer o alerta sair antes da remoção."""

import json

import pytest

from edge.config import ConfiguracaoInvalida, de_dict
from edge.tamper_detection import (
    ABERTURA,
    IMPACTO,
    INCLINACAO,
    MOVIMENTO,
    QUEDA_ENERGIA,
    DetectorViolacao,
    SensorAberturaSimulado,
    SensorAlimentacaoSimulado,
    SensorInercialSimulado,
    criar_detector,
)
from tests.conftest import config_base


def _detector(config=None, **kwargs):
    config = config or de_dict(config_base())
    alertas = []
    imagens = []
    detector = DetectorViolacao(
        config=config,
        inercial=SensorInercialSimulado(),
        abertura=SensorAberturaSimulado(),
        alimentacao=SensorAlimentacaoSimulado(),
        ao_alerta=alertas.append,
        capturar_imagem=lambda tipo: imagens.append(tipo) or f"{tipo}.png",
        **kwargs,
    )
    detector._calibrar_referencia()
    return detector, alertas, imagens


# -- detecção por tipo -------------------------------------------------


def test_impacto_dispara_alerta():
    detector, alertas, _ = _detector()
    detector._inercial.simular_impacto()

    disparados = detector.verificar_uma_vez()

    assert any(a.tipo == IMPACTO for a in disparados)
    assert any(a.tipo == IMPACTO for a in alertas)


def test_inclinacao_sustentada_dispara():
    detector, alertas, _ = _detector()
    detector._inercial.simular_inclinacao(35.0)

    disparados = detector.verificar_uma_vez()

    assert any(a.tipo == INCLINACAO for a in disparados)


def test_movimento_continuo_dispara():
    detector, _, _ = _detector()
    detector._inercial.simular_movimento()

    disparados = detector.verificar_uma_vez()

    assert any(a.tipo == MOVIMENTO for a in disparados)


def test_abertura_da_tampa_dispara_uma_vez_na_borda():
    """Uma tampa aberta gera um alerta, não um a cada leitura."""
    detector, alertas, _ = _detector()
    detector._abertura.simular_abertura(True)

    detector.verificar_uma_vez()
    detector.verificar_uma_vez()
    detector.verificar_uma_vez()

    aberturas = [a for a in alertas if a.tipo == ABERTURA]
    assert len(aberturas) == 1


def test_queda_de_energia_dispara_na_transicao():
    detector, alertas, _ = _detector()
    detector._alimentacao.simular_queda_de_energia(True)

    detector.verificar_uma_vez()

    assert any(a.tipo == QUEDA_ENERGIA for a in alertas)


def test_no_parado_nao_dispara_nada():
    detector, alertas, _ = _detector()

    for _ in range(10):
        detector.verificar_uma_vez()

    assert alertas == []


def test_no_montado_torto_nao_dispara_por_inclinacao():
    """A referência é a posição de instalação, não a vertical absoluta."""
    detector, alertas, _ = _detector()
    detector._inercial.simular_inclinacao(15.0)  # montado inclinado
    detector._calibrar_referencia()  # calibra nessa posição

    disparados = detector.verificar_uma_vez()

    assert not any(a.tipo == INCLINACAO for a in disparados)


# -- ordem de ação -----------------------------------------------------


def test_captura_acontece_antes_do_alerta():
    """A tentativa de furto vira a própria evidência: foto primeiro."""
    detector, alertas, imagens = _detector()
    detector._inercial.simular_impacto()

    detector.verificar_uma_vez()

    assert imagens, "deveria ter fotografado"
    assert alertas[0].imagem is not None


def test_alerta_e_registrado_localmente(tmp_path):
    """Se a transmissão falhar, o alerta ainda está no disco."""
    registro = tmp_path / "violacoes.jsonl"
    detector, _, _ = _detector(registro_local=registro)
    detector._inercial.simular_impacto()

    detector.verificar_uma_vez()

    assert registro.exists()
    linhas = registro.read_text().strip().splitlines()
    assert any(json.loads(linha)["tipo"] == IMPACTO for linha in linhas)


def test_falha_na_captura_nao_impede_o_alerta():
    config = de_dict(config_base())
    alertas = []

    def camera_quebrada(tipo):
        raise RuntimeError("câmera arrancada junto")

    detector = DetectorViolacao(
        config=config,
        inercial=SensorInercialSimulado(),
        abertura=SensorAberturaSimulado(),
        alimentacao=SensorAlimentacaoSimulado(),
        ao_alerta=alertas.append,
        capturar_imagem=camera_quebrada,
    )
    detector._calibrar_referencia()
    detector._inercial.simular_impacto()

    detector.verificar_uma_vez()

    assert alertas, "o alerta precisa sair mesmo sem imagem"
    assert alertas[0].imagem is None


# -- modo manutenção ---------------------------------------------------


def test_manutencao_suspende_alertas():
    detector, alertas, _ = _detector()
    detector.entrar_manutencao(60.0)
    detector._inercial.simular_impacto()

    detector.verificar_uma_vez()

    assert alertas == [], "em manutenção, nada dispara"


def test_manutencao_expira_sozinha():
    """Não existe forma de deixar o alarme desligado por esquecimento."""
    import time

    detector, alertas, _ = _detector()
    detector.entrar_manutencao(0.05)
    assert detector.em_manutencao

    time.sleep(0.1)
    assert not detector.em_manutencao

    detector._inercial.simular_impacto()
    detector.verificar_uma_vez()
    assert alertas, "expirada a manutenção, o alarme volta"


def test_manutencao_expirada_com_tampa_ainda_aberta_dispara():
    """Sem isso, uma tampa aberta durante a manutenção fica muda para sempre
    depois que a manutenção expira — a borda foi consumida em silêncio."""
    import time

    detector, alertas, _ = _detector()
    detector.entrar_manutencao(0.05)
    detector._abertura.simular_abertura(True)
    detector.verificar_uma_vez()
    assert alertas == [], "em manutenção, a abertura não deve disparar"

    time.sleep(0.1)
    assert not detector.em_manutencao

    disparados = detector.verificar_uma_vez()
    assert any(a.tipo == ABERTURA for a in disparados), (
        "manutenção expirou com a tampa ainda aberta — isso precisa soar"
    )


def test_manutencao_explicita_com_tampa_ainda_aberta_dispara():
    """Mesma garantia quando a manutenção é encerrada por sair_manutencao()
    (não só por o prazo estourar)."""
    detector, alertas, _ = _detector()
    detector.entrar_manutencao(60.0)
    detector._abertura.simular_abertura(True)
    detector.verificar_uma_vez()
    assert alertas == []

    detector.sair_manutencao()

    disparados = detector.verificar_uma_vez()
    assert any(a.tipo == ABERTURA for a in disparados)


def test_manutencao_nao_passa_do_teto_configurado():
    detector, _, _ = _detector()
    fim = detector.entrar_manutencao(999999.0)
    import time

    assert fim - time.time() <= detector.config.manutencao_max_s + 1


def test_alerta_serializa_com_canal_separado():
    detector, alertas, _ = _detector()
    detector._inercial.simular_impacto()
    detector.verificar_uma_vez()

    dados = alertas[0].como_dict()
    assert dados["canal"] == "violacao_patrimonial"
    assert dados["tipo"] == IMPACTO
    assert "capturado_em" in dados


# -- configuração ------------------------------------------------------


def test_impacto_menor_que_gravidade_e_recusado():
    dados = config_base()
    dados["tamper"] = {"impacto_g": 0.8}
    with pytest.raises(ConfiguracaoInvalida, match="1 g"):
        de_dict(dados)


def test_sensor_desconhecido_e_recusado():
    dados = config_base()
    dados["tamper"] = {"inercial": "inventado"}
    with pytest.raises(ConfiguracaoInvalida, match="tamper.inercial"):
        de_dict(dados)


def test_fabrica_usa_simulado_por_padrao():
    detector = criar_detector(de_dict(config_base()), ao_alerta=lambda a: None)
    assert type(detector._inercial).__name__ == "SensorInercialSimulado"


def test_sensores_nao_importam_hardware_no_topo():
    """D11: importar o módulo não pode exigir smbus2 ou gpiozero."""
    import sys

    import edge.tamper_detection.sensores  # noqa: F401

    assert "smbus2" not in sys.modules
    assert "gpiozero" not in sys.modules
