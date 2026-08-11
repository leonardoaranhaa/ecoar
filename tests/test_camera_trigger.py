"""A tabela de decisão é o módulo de maior peso jurídico do sistema."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from edge.audio_capture.spl import estimar
from edge.camera_trigger import (
    Acao,
    AcionadorCamera,
    CameraIndisponivel,
    CameraSimulada,
    decidir,
    diferenca_angular,
    escrever_png,
)
from edge.classifier.base import CLASSE_ALVO, CLASSES, Predicao
from edge.config import ConfigCalibracao, ConfigGatilho, ConfiguracaoInvalida, de_dict
from edge.localization.doa import EstimativaDOA
from tests.conftest import config_base

POLITICA = ConfigGatilho()


def predicao(score_alvo: float, classe: str = CLASSE_ALVO) -> Predicao:
    resto = (1.0 - score_alvo) / (len(CLASSES) - 1)
    scores = {c: resto for c in CLASSES}
    scores[CLASSE_ALVO] = score_alvo
    return Predicao(
        classe=classe,
        score=max(scores.values()),
        scores=scores,
        modelo="heuristico",
        versao_modelo="teste/1.0",
    )


def doa(confianca: float = 0.9, margem: float = 3.0, azimute: float = 10.0) -> EstimativaDOA:
    return EstimativaDOA(
        azimute_graus=azimute,
        confianca=confianca,
        margem_graus=margem,
        residuo_us=3.0,
        qualidade_media=0.98,
        tdoas_us={"0-1": 100.0},
    )


def spl(db: float = 88.0):
    amostras = np.zeros((1000, 4), dtype=np.float32)
    estimativa = estimar(amostras, 48000, ConfigCalibracao())
    return replace(estimativa, db=db, dbfs=db - 94.0)


# -- os três desfechos -------------------------------------------------


def test_evento_completo_aciona():
    decisao = decidir(predicao(0.92), doa(), spl(), POLITICA)

    assert decisao.acao is Acao.ACIONAR
    assert decisao.aciona_camera
    assert decisao.gera_evento
    assert decisao.versao_politica == POLITICA.versao_politica


def test_score_intermediario_fica_ambiguo_sem_acionar():
    """A faixa que existe de propósito: registrar a dúvida como dúvida."""
    decisao = decidir(predicao(0.60), doa(), spl(), POLITICA)

    assert decisao.acao is Acao.AMBIGUO
    assert not decisao.aciona_camera
    assert decisao.gera_evento, "ambíguo continua sendo evento, só que sem imagem"


def test_score_baixo_descarta():
    decisao = decidir(predicao(0.10, classe="buzina"), doa(), spl(), POLITICA)

    assert decisao.acao is Acao.DESCARTAR
    assert not decisao.gera_evento


# -- fail-closed -------------------------------------------------------


def test_classificador_indisponivel_vira_ambiguo_nunca_descarte():
    decisao = decidir(None, doa(), spl(), POLITICA)

    assert decisao.acao is Acao.AMBIGUO
    assert "classificador indisponível" in decisao.motivo
    assert not decisao.aciona_camera


def test_sem_angulo_nao_aciona_mesmo_com_score_altissimo():
    """Sem ângulo não há como associar o som a um veículo específico."""
    decisao = decidir(predicao(0.99), None, spl(), POLITICA)

    assert decisao.acao is Acao.AMBIGUO
    assert "veículo" in decisao.motivo


def test_localizacao_incerta_nao_aciona():
    decisao = decidir(predicao(0.95), doa(confianca=0.2, margem=40.0), spl(), POLITICA)
    assert decisao.acao is Acao.AMBIGUO


def test_fonte_fora_do_campo_de_visao_nao_aciona_mas_registra():
    """A câmera não cobre aquele ângulo: fotografar não provaria nada."""
    decisao = decidir(predicao(0.95), doa(azimute=170.0), spl(), POLITICA)

    assert decisao.acao is Acao.AMBIGUO
    assert not decisao.dentro_do_campo_de_visao
    assert "campo de visão" in decisao.motivo


def test_nivel_sonoro_baixo_nao_aciona():
    decisao = decidir(predicao(0.95), doa(), spl(db=60.0), POLITICA)
    assert decisao.acao is Acao.AMBIGUO


# -- determinismo e rastreabilidade ------------------------------------


def test_mesma_entrada_mesma_saida():
    entrada = (predicao(0.83), doa(), spl(), POLITICA)
    primeira, segunda = decidir(*entrada), decidir(*entrada)

    assert primeira == segunda


def test_decisao_registra_todas_as_regras_avaliadas():
    decisao = decidir(predicao(0.92), doa(), spl(), POLITICA)
    nomes = {regra.nome for regra in decisao.regras}

    assert "score da classe alvo acima do limiar de acionamento" in nomes
    assert "confiança da localização" in nomes
    assert "fonte dentro do campo de visão da câmera" in nomes
    for regra in decisao.regras:
        assert regra.esperado and regra.medido, f"regra {regra.nome} sem rastro"


def test_serializacao_leva_regras_para_a_evidencia():
    dados = decidir(predicao(0.30), doa(), spl(), POLITICA).como_dict()

    assert dados["acao"] == "descartar"
    assert dados["versao_politica"] == "politica/1.0"
    assert len(dados["regras"]) >= 3


def test_limiar_no_ponto_exato_aciona():
    """Fronteira explícita: >= aciona. Não deixar isso ao acaso."""
    politica = ConfigGatilho(score_aciona=0.80)
    assert decidir(predicao(0.80), doa(), spl(), politica).acao is Acao.ACIONAR
    assert decidir(predicao(0.7999), doa(), spl(), politica).acao is Acao.AMBIGUO


def test_politica_invertida_e_recusada_na_configuracao():
    dados = config_base()
    dados["gatilho"] = {"score_aciona": 0.3, "score_ambiguo": 0.8}
    with pytest.raises(ConfiguracaoInvalida, match="score_ambiguo < score_aciona"):
        de_dict(dados)


def test_diferenca_angular_e_circular():
    assert diferenca_angular(350.0, 10.0) == pytest.approx(20.0)
    assert diferenca_angular(10.0, 350.0) == pytest.approx(20.0)
    assert diferenca_angular(0.0, 180.0) == pytest.approx(180.0)


# -- câmera ------------------------------------------------------------


def test_png_gerado_e_legivel(tmp_path):
    imagem = np.random.default_rng(3).integers(0, 255, (32, 48, 3), dtype=np.uint8)
    caminho = escrever_png(tmp_path / "teste.png", imagem)

    conteudo = caminho.read_bytes()
    assert conteudo.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IHDR" in conteudo and b"IEND" in conteudo


def test_captura_simulada_se_declara_simulada(tmp_path):
    captura = CameraSimulada().capturar(tmp_path / "placa.png", "placa")

    assert captura.simulada is True
    assert captura.como_dict()["simulada"] is True
    assert captura.caminho.exists()


def test_acionamento_grava_duas_imagens(tmp_path):
    config = de_dict(config_base())
    acionador = AcionadorCamera(config, diretorio=tmp_path)

    with acionador:
        resultado = acionador.processar("evt-001", predicao(0.95), doa(), spl())

    assert resultado.decisao.acao is Acao.ACIONAR
    assert len(resultado.capturas) == 2
    assert {c.tipo for c in resultado.capturas} == {"placa", "panoramica"}
    assert all(c.caminho.exists() for c in resultado.capturas)


def test_ambiguo_nao_grava_imagem(tmp_path):
    config = de_dict(config_base())
    acionador = AcionadorCamera(config, diretorio=tmp_path)

    with acionador:
        resultado = acionador.processar("evt-002", predicao(0.60), doa(), spl())

    assert resultado.capturas == ()
    assert not (Path(tmp_path) / "evt-002").exists()


def test_falha_de_camera_nao_apaga_o_evento(tmp_path):
    """Áudio, ângulo e score continuam valendo; a falha entra na evidência."""

    class CameraQuebrada(CameraSimulada):
        def capturar(self, destino, tipo):
            raise CameraIndisponivel("sensor não respondeu")

    config = de_dict(config_base())
    acionador = AcionadorCamera(config, camera=CameraQuebrada(), diretorio=tmp_path)

    resultado = acionador.processar("evt-003", predicao(0.95), doa(), spl())

    assert resultado.decisao.acao is Acao.ACIONAR
    assert resultado.capturas == ()
    assert "sensor não respondeu" in resultado.falha_de_captura
    assert resultado.como_dict()["falha_de_captura"]
