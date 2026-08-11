"""Validação da localização com sinal sintético de ângulo conhecido.

Meta do projeto: ±5° de precisão angular. Os testes cobram isso.
"""

import numpy as np
import pytest

from edge.audio_capture.sintetico import CenaSintetica
from edge.geometria import ArrayCircular
from edge.localization import Localizador, gcc_phat

TAXA = 48000
ARRAY = ArrayCircular(raio_m=0.045, n_microfones=4)


def cena(azimute: float, perfil: str = "escapamento", ruido: float = 0.02) -> np.ndarray:
    geradora = CenaSintetica(
        ARRAY, taxa_amostragem=TAXA, perfil=perfil, azimute_graus=azimute
    )
    geradora.ruido_fundo = ruido
    geradora.__post_init__()
    # Trecho em volta da passagem, que é onde o perfil tem energia.
    return geradora.bloco(TAXA, indice_inicial=int(3.6 * TAXA))


def sinal_atrasado(atraso_amostras: int, n: int = 4096) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(3)
    base = rng.normal(0, 1, n + 2 * abs(atraso_amostras))
    referencia = base[abs(atraso_amostras) : abs(atraso_amostras) + n]
    inicio = abs(atraso_amostras) - atraso_amostras
    return base[inicio : inicio + n], referencia


def test_gcc_phat_recupera_atraso_conhecido():
    for atraso in (-12, -3, 0, 5, 17):
        sinal, referencia = sinal_atrasado(atraso)
        resultado = gcc_phat(sinal, referencia, TAXA, interpolacao=16)
        assert resultado.tdoa_s * TAXA == pytest.approx(atraso, abs=0.2), f"atraso {atraso}"


def test_gcc_phat_marca_qualidade_baixa_em_ruido_independente():
    rng = np.random.default_rng(11)
    resultado = gcc_phat(rng.normal(0, 1, 4096), rng.normal(0, 1, 4096), TAXA)
    assert resultado.qualidade < 0.3


def test_gcc_phat_recusa_canais_de_tamanhos_diferentes():
    with pytest.raises(ValueError, match="mesmo número de amostras"):
        gcc_phat(np.zeros(100), np.zeros(80), TAXA)


@pytest.mark.parametrize("azimute", [0.0, 37.0, 90.0, 145.0, 180.0, 233.0, 300.0, 351.0])
def test_azimute_estimado_bate_com_o_real(azimute):
    estimativa = Localizador(ARRAY).estimar(cena(azimute), TAXA)

    erro = abs((estimativa.azimute_graus - azimute + 180.0) % 360.0 - 180.0)
    assert erro <= 5.0, f"erro de {erro:.1f}° em {azimute}° (est. {estimativa.azimute_graus:.1f}°)"
    assert estimativa.confianca > 0.4
    assert estimativa.confiavel


def test_quatro_microfones_resolvem_frente_e_tras():
    """Um par sozinho confunde 60° com 300°; o círculo de quatro não."""
    frente = Localizador(ARRAY).estimar(cena(60.0), TAXA)
    tras = Localizador(ARRAY).estimar(cena(300.0), TAXA)

    assert abs(frente.azimute_graus - 60.0) <= 5.0
    assert abs(tras.azimute_graus - 300.0) <= 5.0


def test_ruido_puro_derruba_a_confianca():
    """Fail-closed: sem fonte localizável, o sistema precisa declarar que não sabe."""
    rng = np.random.default_rng(5)
    amostras = rng.normal(0, 0.05, size=(TAXA // 2, 4))

    estimativa = Localizador(ARRAY).estimar(amostras, TAXA)

    assert estimativa.confianca < 0.4
    assert not estimativa.confiavel


def test_margem_cresce_quando_a_estimativa_piora():
    limpa = Localizador(ARRAY).estimar(cena(120.0, ruido=0.005), TAXA)
    suja = Localizador(ARRAY).estimar(cena(120.0, ruido=0.5), TAXA)

    assert limpa.margem_graus <= suja.margem_graus
    assert limpa.confianca > suja.confianca


def test_raio_errado_derruba_a_confianca_em_vez_de_mentir():
    """Erro de raio escala todos os TDOAs por igual: não gira a estimativa.

    O ângulo continua apontando para o lado certo, mas nenhum ângulo explica as
    medições, o resíduo estoura e a confiança vai a zero. É o comportamento
    desejado — o sistema declara que não sabe em vez de inventar precisão.
    """
    correta = Localizador(ARRAY).estimar(cena(90.0), TAXA)
    raio_dobrado = Localizador(ArrayCircular(raio_m=0.09, n_microfones=4)).estimar(
        cena(90.0), TAXA
    )

    assert correta.confianca > 0.5
    assert correta.residuo_us < 10.0

    assert raio_dobrado.residuo_us > 10 * correta.residuo_us
    assert raio_dobrado.confianca < 0.1
    assert not raio_dobrado.confiavel


def test_array_girado_sem_offset_configurado_desloca_todos_os_angulos():
    """A causa real de "o ângulo está sempre errado, e sempre pelo mesmo tanto".

    O array foi montado girado no poste e a configuração não sabe disso. O
    resíduo continua baixo — as medições são consistentes — e por isso o erro
    passa despercebido: só a comparação com a via real denuncia.
    """
    montado_girado = ArrayCircular(raio_m=0.045, n_microfones=4, azimute_offset_graus=30.0)
    geradora = CenaSintetica(montado_girado, taxa_amostragem=TAXA, azimute_graus=100.0)
    amostras = geradora.bloco(TAXA, indice_inicial=int(3.6 * TAXA))

    sem_offset = Localizador(ARRAY).estimar(amostras, TAXA)

    assert sem_offset.residuo_us < 10.0
    assert sem_offset.confianca > 0.5
    # O deslocamento tem o tamanho do giro e o sinal invertido: o array girou
    # +30°, então o mundo, visto por ele, girou -30°.
    erro = (sem_offset.azimute_graus - 100.0 + 180.0) % 360.0 - 180.0
    assert abs(erro + 30.0) <= 5.0


def test_offset_de_instalacao_gira_a_referencia():
    """O array montado girado no poste é corrigido por configuração, não por régua."""
    girado = ArrayCircular(raio_m=0.045, n_microfones=4, azimute_offset_graus=30.0)
    geradora = CenaSintetica(girado, taxa_amostragem=TAXA, azimute_graus=100.0)
    amostras = geradora.bloco(TAXA, indice_inicial=int(3.6 * TAXA))

    estimativa = Localizador(girado).estimar(amostras, TAXA)

    assert abs(estimativa.azimute_graus - 100.0) <= 5.0


def test_estimativa_serializa_com_tudo_que_a_evidencia_precisa():
    dados = Localizador(ARRAY).estimar(cena(45.0), TAXA).como_dict()

    assert set(dados) >= {
        "azimute_graus",
        "confianca",
        "margem_graus",
        "residuo_us",
        "tdoas_us",
        "algoritmo",
    }
    assert len(dados["tdoas_us"]) == 6  # os seis pares de quatro microfones


def test_trecho_longo_e_recortado_no_evento():
    """20 s de pacote não vão inteiros para a FFT — só o trecho com energia."""
    silencio = np.zeros((TAXA * 4, 4))
    evento = cena(210.0)
    amostras = np.concatenate([silencio, evento, silencio])

    estimativa = Localizador(ARRAY).estimar(amostras, TAXA)

    assert abs(estimativa.azimute_graus - 210.0) <= 5.0


def test_numero_de_canais_errado_e_recusado():
    with pytest.raises(ValueError, match="canais"):
        Localizador(ARRAY).estimar(np.zeros((1000, 2)), TAXA)
