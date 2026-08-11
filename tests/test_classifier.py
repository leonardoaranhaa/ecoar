"""Testes do classificador de assinatura acústica.

AVISO QUE VALE PARA O ARQUIVO INTEIRO: os testes de acerto por classe usam a
cena sintética de bancada, que foi escrita por nós. Eles provam que o pipeline
funciona e detectam regressão quando alguém mexer nos descritores ou nas
regras. Eles NÃO são evidência de acerto em campo — isso só vem de gravação
real de Bauru, rotulada por humano.
"""

import numpy as np
import pytest

from edge.audio_capture.sintetico import PERFIS, CenaSintetica
from edge.classifier import CLASSE_ALVO, CLASSES, criar_classificador
from edge.classifier.augment import (
    Variacao,
    adicionar_ruido,
    aplicar,
    atenuar_distancia,
    gerar_variacoes,
    reverberar,
)
from edge.classifier.base import ClassificadorIndisponivel, normalizar_scores
from edge.classifier.features import extrair_descritores, log_mel
from edge.classifier.heuristico import ClassificadorHeuristico
from edge.config import ConfiguracaoInvalida, de_dict
from edge.geometria import ArrayCircular
from tests.conftest import config_base

TAXA = 48000
ARRAY = ArrayCircular(raio_m=0.045, n_microfones=4)

ANCORAS = {
    "escapamento": 4.0,
    "buzina": 2.35,
    "obra": 10.0,
    "trovao": 1.5,
    "ambiente": 5.0,
}
CLASSE_DO_PERFIL = {
    "escapamento": CLASSE_ALVO,
    "buzina": "buzina",
    "obra": "obra",
    "trovao": "trovao",
    "ambiente": "ambiente",
}


def cena(perfil: str, segundos: float = 3.0) -> np.ndarray:
    geradora = CenaSintetica(ARRAY, taxa_amostragem=TAXA, perfil=perfil, azimute_graus=45.0)
    inicio = int((ANCORAS[perfil] - segundos / 2) * TAXA)
    return geradora.bloco(int(segundos * TAXA), inicio)


# -- descritores -------------------------------------------------------


def test_fundamental_de_escapamento_cai_na_faixa_de_motor():
    descritores = extrair_descritores(cena("escapamento"), TAXA)
    assert 55.0 <= descritores.f0_hz <= 140.0
    assert descritores.forca_harmonica > 0.5


def test_buzina_nao_e_confundida_pelo_batimento_das_duas_notas():
    """As notas de 440 e 554 Hz batem em ~114 Hz, que é faixa de motor.

    Se a fundamental viesse da autocorrelação, a buzina passaria por
    escapamento — exatamente o falso positivo que o módulo existe para evitar.
    """
    descritores = extrair_descritores(cena("buzina"), TAXA)
    assert descritores.f0_hz > 300.0


def test_ruido_branco_nao_produz_fundamental_inventada():
    rng = np.random.default_rng(1)
    descritores = extrair_descritores(rng.normal(0, 0.05, (TAXA, 4)), TAXA)
    assert descritores.forca_harmonica < 0.05
    assert descritores.planicidade > 0.3


def test_impulsos_de_obra_sao_contados():
    descritores = extrair_descritores(cena("obra"), TAXA)
    assert 5.0 <= descritores.taxa_impulsos_hz <= 25.0


def test_log_mel_tem_formato_e_normalizacao_esperados():
    espectrograma = log_mel(cena("escapamento"), TAXA)
    assert espectrograma.shape[1] == 48
    assert espectrograma.max() == pytest.approx(0.0)


def test_silencio_nao_quebra_a_extracao():
    descritores = extrair_descritores(np.zeros((TAXA, 4)), TAXA)
    assert descritores.f0_hz == 0.0


# -- classificação -----------------------------------------------------


@pytest.mark.parametrize("perfil", PERFIS)
def test_cada_perfil_de_bancada_cai_na_classe_certa(perfil):
    predicao = ClassificadorHeuristico().classificar(cena(perfil), TAXA)
    assert predicao.classe == CLASSE_DO_PERFIL[perfil]


def test_buzina_nao_aciona_o_alvo():
    """O falso positivo que derruba o sistema de referência de SJC."""
    predicao = ClassificadorHeuristico().classificar(cena("buzina"), TAXA)
    assert predicao.score_alvo < 0.25


def test_obra_e_trovao_tambem_nao_acionam_o_alvo():
    for perfil in ("obra", "trovao"):
        predicao = ClassificadorHeuristico().classificar(cena(perfil), TAXA)
        assert predicao.score_alvo < 0.25, perfil


def test_escapamento_tem_score_alvo_alto():
    predicao = ClassificadorHeuristico().classificar(cena("escapamento"), TAXA)
    assert predicao.score_alvo > 0.5
    assert predicao.e_alvo


def test_classificacao_e_deterministica():
    """D7: mesma entrada e mesma versão de regras, mesma saída. Sempre."""
    amostras = cena("escapamento")
    primeira = ClassificadorHeuristico().classificar(amostras, TAXA)
    segunda = ClassificadorHeuristico().classificar(amostras, TAXA)
    assert primeira.scores == segunda.scores
    assert primeira.classe == segunda.classe


def test_scores_somam_um_e_cobrem_todas_as_classes():
    predicao = ClassificadorHeuristico().classificar(cena("escapamento"), TAXA)
    assert set(predicao.scores) == set(CLASSES)
    assert sum(predicao.scores.values()) == pytest.approx(1.0)


def test_predicao_carrega_a_versao_do_modelo_para_a_evidencia():
    dados = ClassificadorHeuristico().classificar(cena("escapamento"), TAXA).como_dict()
    assert dados["modelo"] == "heuristico"
    assert "bancada" in dados["versao_modelo"]
    assert dados["explicacao"]
    assert dados["descritores"]["f0_hz"] > 0


def test_explicacao_cita_medidas_e_nao_so_o_score():
    predicao = ClassificadorHeuristico().classificar(cena("escapamento"), TAXA)
    assert "fundamental" in predicao.explicacao
    assert "harmônica" in predicao.explicacao or "harmônicas" in predicao.explicacao


def test_normalizar_scores_preserva_empate():
    scores = normalizar_scores({classe: 1.0 for classe in CLASSES})
    assert len(set(round(v, 6) for v in scores.values())) == 1


# -- fábrica -----------------------------------------------------------


def test_auto_sem_modelo_usa_o_classificador_de_referencia():
    classificador = criar_classificador(de_dict(config_base()))
    assert isinstance(classificador, ClassificadorHeuristico)


def test_tipo_cnn_sem_modelo_e_recusado_na_configuracao():
    dados = config_base()
    dados["classificador"] = {"tipo": "cnn"}
    with pytest.raises(ConfiguracaoInvalida, match="classificador.modelo"):
        de_dict(dados)


def test_cnn_com_modelo_inexistente_falha_explicitamente(tmp_path):
    dados = config_base()
    dados["classificador"] = {"tipo": "cnn", "modelo": str(tmp_path / "nao-existe.pt")}
    with pytest.raises(ClassificadorIndisponivel):
        criar_classificador(de_dict(dados))


def test_auto_com_modelo_inexistente_degrada_em_vez_de_derrubar_o_no(tmp_path, caplog):
    dados = config_base()
    dados["classificador"] = {"tipo": "auto", "modelo": str(tmp_path / "nao-existe.pt")}

    classificador = criar_classificador(de_dict(dados))

    assert isinstance(classificador, ClassificadorHeuristico)
    assert "indisponível" in caplog.text or "indisponivel" in caplog.text


# -- aumento de dados --------------------------------------------------


def test_atenuacao_por_distancia_reduz_amplitude_e_agudo():
    sinal = cena("escapamento")[:, 0]
    perto = atenuar_distancia(sinal, TAXA, distancia_m=7.0)
    longe = atenuar_distancia(sinal, TAXA, distancia_m=28.0)

    assert np.std(longe) < np.std(perto) / 3

    def energia_aguda(x):
        espectro = np.abs(np.fft.rfft(x)) ** 2
        freq = np.fft.rfftfreq(len(x), 1 / TAXA)
        return np.sum(espectro[freq > 4000]) / (np.sum(espectro) + 1e-12)

    assert energia_aguda(longe) < energia_aguda(perto)


def test_ruido_adicionado_respeita_a_relacao_pedida():
    sinal = cena("escapamento")[:, 0]
    rng = np.random.default_rng(3)
    com_ruido = adicionar_ruido(sinal, TAXA, snr_db=10.0, rng=rng)

    potencia_ruido = np.mean((com_ruido - sinal) ** 2)
    snr = 10 * np.log10(np.mean(sinal**2) / potencia_ruido)
    assert snr == pytest.approx(10.0, abs=1.0)


def test_reverberacao_alonga_a_cauda_sem_destruir_o_sinal():
    sinal = cena("buzina")[:, 0]
    rng = np.random.default_rng(3)
    reverberado = reverberar(sinal, TAXA, t60_s=0.5, rng=rng)

    assert len(reverberado) == len(sinal)
    correlacao = np.corrcoef(sinal, reverberado)[0, 1]
    assert 0.1 < correlacao < 0.999


def test_variacoes_sao_diferentes_entre_si_e_reprodutiveis():
    sinal = cena("escapamento")[:, 0]
    primeira = gerar_variacoes(sinal, TAXA, quantidade=3, semente=7)
    segunda = gerar_variacoes(sinal, TAXA, quantidade=3, semente=7)

    assert len(primeira) == 3
    np.testing.assert_allclose(primeira[0][0], segunda[0][0])
    assert not np.allclose(primeira[0][0], primeira[1][0])


def test_escapamento_atenuado_e_ruidoso_ainda_nao_vira_buzina():
    """Degradar não pode trocar a classe por outra específica.

    Perder confiança com a distância é aceitável e esperado — o que não pode
    acontecer é o som virar confiantemente outra coisa.
    """
    sinal = cena("escapamento")[:, 0]
    rng = np.random.default_rng(11)
    degradado = aplicar(sinal, TAXA, Variacao(distancia_m=15.0, t60_s=0.4, snr_db=6.0), rng)

    predicao = ClassificadorHeuristico().classificar(degradado[:, None], TAXA)

    assert predicao.scores["buzina"] < 0.25


@pytest.mark.parametrize("taxa", [8000, 16000, 44100, 48000])
def test_descritores_nao_dependem_da_taxa_de_amostragem(taxa):
    """Um nó a 16 kHz precisa medir o mesmo som que um nó a 48 kHz.

    Com a envoltória amostrada a um salto fixo em amostras, o mesmo escapamento
    media 47 impulsos por segundo a 48 kHz e 5 a 16 kHz — e o classificador se
    comportava de forma diferente em cada nó, sem ninguém perceber.
    """
    from edge.audio_capture.sintetico import CenaSintetica

    geradora = CenaSintetica(ARRAY, taxa_amostragem=taxa, perfil="escapamento")
    amostras = geradora.bloco(taxa * 3, indice_inicial=int(2.5 * taxa))

    descritores = extrair_descritores(amostras, taxa)
    predicao = ClassificadorHeuristico().classificar(amostras, taxa)

    assert descritores.f0_hz == pytest.approx(84.0, abs=3.0)
    assert descritores.taxa_impulsos_hz == pytest.approx(46.0, rel=0.15)
    assert descritores.crista == pytest.approx(2.6, rel=0.15)
    assert predicao.classe == CLASSE_ALVO
    assert predicao.score_alvo == pytest.approx(0.69, abs=0.05)
