import numpy as np
import pytest

from edge.audio_capture.spl import dbfs_por_canal, estimar, pesos_a
from edge.config import ConfigCalibracao

TAXA = 48000


def seno(frequencia: float, amplitude: float = 1.0, segundos: float = 1.0, canais: int = 4):
    t = np.arange(int(TAXA * segundos)) / TAXA
    onda = amplitude * np.sin(2 * np.pi * frequencia * t)
    return np.repeat(onda[:, None], canais, axis=1)


def test_ponderacao_a_e_neutra_em_1_khz():
    assert 20 * np.log10(pesos_a(np.array([1000.0]))[0]) == pytest.approx(0.0, abs=0.05)


def test_ponderacao_a_segue_a_tabela_da_norma():
    # Valores de referência da IEC 61672 para a curva A.
    esperado = {31.5: -39.4, 100.0: -19.1, 1000.0: 0.0, 4000.0: 1.0, 8000.0: -1.1}
    for frequencia, db in esperado.items():
        obtido = 20 * np.log10(pesos_a(np.array([frequencia]))[0])
        assert obtido == pytest.approx(db, abs=0.3), f"{frequencia} Hz"


def test_dbfs_de_seno_de_fundo_de_escala():
    """Seno de amplitude 1,0 tem RMS 0,707 — ou seja, -3,01 dBFS."""
    valores = dbfs_por_canal(seno(1000.0), TAXA, ponderacao="Z")
    assert np.allclose(valores, -3.01, atol=0.05)


def test_ponderacao_a_derruba_o_grave():
    """Um ronco grave mede alto sem ponderação e pouco com ela — é o ponto dela."""
    grave_z = dbfs_por_canal(seno(100.0), TAXA, ponderacao="Z")[0]
    grave_a = dbfs_por_canal(seno(100.0), TAXA, ponderacao="A")[0]

    assert grave_z - grave_a == pytest.approx(19.1, abs=0.5)


def test_estimativa_identifica_o_canal_dominante():
    amostras = seno(1000.0, amplitude=0.05)
    amostras[:, 2] *= 6.0  # microfone mais perto da fonte

    estimativa = estimar(amostras, TAXA, ConfigCalibracao(offset_db=94.0, referencia="teste"))

    assert estimativa.canal_dominante == 2
    assert estimativa.db == pytest.approx(estimativa.dbfs + 94.0)


def test_estimativa_nunca_tem_valor_legal():
    """Decisão D3: o array não produz medição com valor de prova."""
    estimativa = estimar(seno(1000.0), TAXA, ConfigCalibracao())

    assert estimativa.valor_legal is False
    assert estimativa.como_dict()["valor_legal"] is False
    assert "sem valor de prova" in estimativa.como_dict()["origem"]


def test_silencio_nao_gera_infinito():
    estimativa = estimar(np.zeros((1000, 4), dtype=np.float32), TAXA, ConfigCalibracao())
    assert np.isfinite(estimativa.dbfs)
