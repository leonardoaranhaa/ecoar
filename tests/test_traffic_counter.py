"""Contagem de tráfego: agregação, classificador simulado, orquestração."""

import pytest

from edge.camera_trigger.camera import CameraSimulada
from edge.config import ConfiguracaoInvalida, de_dict
from edge.traffic_counter import (
    NENHUM,
    TIPOS_VEICULO,
    AgregadorTrafego,
    ClassificacaoVeiculo,
    ContadorTrafego,
    criar_classificador,
)
from edge.traffic_counter.classificador import ClassificadorSimulado
from tests.conftest import config_base


class _ClassificadorFixo:
    """Sempre devolve o mesmo tipo — para testes determinísticos."""

    def __init__(self, tipo: str) -> None:
        self._tipo = tipo

    def classificar(self, quadro=None) -> ClassificacaoVeiculo:
        return ClassificacaoVeiculo(tipo=self._tipo, confianca=0.9, simulado=True)


# -- agregador -----------------------------------------------------------


def test_agregador_soma_por_dia_hora_tipo():
    agregador = AgregadorTrafego()
    instante = 1_770_000_000.0  # instante fixo, qualquer um

    agregador.somar("moto", instante=instante)
    agregador.somar("moto", instante=instante)
    agregador.somar("carro", instante=instante)

    agregados = {(a.tipo): a.contagem for a in agregador.drenar()}
    assert agregados == {"moto": 2, "carro": 1}


def test_drenar_zera_o_agregador():
    agregador = AgregadorTrafego()
    agregador.somar("moto")

    primeira = agregador.drenar()
    segunda = agregador.drenar()

    assert len(primeira) == 1
    assert segunda == []
    assert agregador.total() == 0


def test_total_soma_tudo_pendente():
    agregador = AgregadorTrafego()
    agregador.somar("moto")
    agregador.somar("carro")
    agregador.somar("carro")

    assert agregador.total() == 3


# -- classificador simulado ----------------------------------------------


def test_classificador_simulado_e_deterministico_por_semente():
    a = ClassificadorSimulado(semente=42)
    b = ClassificadorSimulado(semente=42)

    resultado_a = [a.classificar().tipo for _ in range(20)]
    resultado_b = [b.classificar().tipo for _ in range(20)]

    assert resultado_a == resultado_b


def test_classificador_simulado_so_produz_tipos_conhecidos():
    classificador = ClassificadorSimulado(semente=7)
    for _ in range(50):
        classificacao = classificador.classificar()
        assert classificacao.tipo in (*TIPOS_VEICULO, NENHUM)
        assert classificacao.simulado is True


def test_nenhum_veiculo_tem_confianca_zero():
    classificador = ClassificadorSimulado(semente=7)
    for _ in range(200):
        classificacao = classificador.classificar()
        if classificacao.tipo == NENHUM:
            assert classificacao.confianca == 0.0
            return
    pytest.fail("nenhuma amostra de 'nenhum' em 200 tentativas — ajustar semente do teste")


def test_criar_classificador_modelo_ainda_nao_implementado():
    config = de_dict(config_base(trafego={"classificador": "modelo"})).trafego
    with pytest.raises(NotImplementedError):
        criar_classificador(config)


# -- configuração ----------------------------------------------------------


def test_trafego_desligado_por_padrao():
    config = de_dict(config_base()).trafego
    assert config.habilitado is False


def test_cadencia_invalida_e_recusada():
    with pytest.raises(ConfiguracaoInvalida, match="cadencia_s"):
        de_dict(config_base(trafego={"cadencia_s": 0}))


def test_classificador_invalido_e_recusado():
    with pytest.raises(ConfiguracaoInvalida, match="classificador"):
        de_dict(config_base(trafego={"classificador": "inventado"}))


# -- contador (orquestração) -----------------------------------------------


def test_amostrar_um_soma_no_agregador_quando_ha_veiculo(tmp_path):
    config = de_dict(config_base(trafego={"habilitado": True}))
    contador = ContadorTrafego(
        config=config,
        camera=CameraSimulada(),
        classificador=_ClassificadorFixo("moto"),
        diretorio_quadros=tmp_path,
    )

    contador.amostrar_um()

    agregados = contador.agregador.drenar()
    assert len(agregados) == 1
    assert agregados[0].tipo == "moto"
    assert agregados[0].contagem == 1


def test_amostrar_um_nao_soma_quando_nenhum_veiculo(tmp_path):
    config = de_dict(config_base(trafego={"habilitado": True}))
    contador = ContadorTrafego(
        config=config,
        camera=CameraSimulada(),
        classificador=_ClassificadorFixo(NENHUM),
        diretorio_quadros=tmp_path,
    )

    contador.amostrar_um()

    assert contador.agregador.total() == 0


def test_amostrar_um_nao_deixa_quadro_no_disco(tmp_path):
    config = de_dict(config_base(trafego={"habilitado": True}))
    contador = ContadorTrafego(
        config=config,
        camera=CameraSimulada(),
        classificador=_ClassificadorFixo("carro"),
        diretorio_quadros=tmp_path,
    )

    contador.amostrar_um()

    assert list(tmp_path.glob("*.png")) == [], "contagem não deve guardar imagem"


def test_iniciar_nao_sobe_thread_se_desabilitado(tmp_path):
    config = de_dict(config_base())  # trafego.habilitado é False por padrão
    contador = ContadorTrafego(
        config=config,
        camera=CameraSimulada(),
        classificador=_ClassificadorFixo("moto"),
        diretorio_quadros=tmp_path,
    )

    contador.iniciar()

    assert contador._thread is None
    contador.parar()
