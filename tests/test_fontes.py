import numpy as np
import pytest

from edge.audio_capture.fontes import (
    FonteSintetica,
    FonteWav,
    criar_fonte,
    escrever_wav,
)
from edge.config import de_dict
from edge.geometria import ArrayCircular
from tests.conftest import config_base

ARRAY = ArrayCircular(raio_m=0.045, n_microfones=4)


def test_fonte_sintetica_entrega_blocos_contiguos():
    fonte = FonteSintetica(ARRAY, taxa_amostragem=16000, bloco_amostras=512, tempo_real=False)

    with fonte:
        primeiro = fonte.ler()
        segundo = fonte.ler()

    assert primeiro.amostras.shape == (512, 4)
    assert primeiro.amostras.dtype == np.float32
    esperado = primeiro.timestamp + 512 / 16000
    assert segundo.timestamp == pytest.approx(esperado, abs=1e-9)


def test_fonte_sintetica_aplica_atraso_de_chegada_por_canal():
    """Sem TDOA no sinal, a etapa de localização não teria o que estimar."""
    from edge.audio_capture.sintetico import CenaSintetica

    taxa = 48000
    cena = CenaSintetica(ARRAY, taxa_amostragem=taxa, perfil="escapamento", azimute_graus=0.0)
    # A passagem da moto acontece perto de t=4 s no ciclo do perfil.
    amostras = cena.bloco(taxa, indice_inicial=int(3.5 * taxa))

    # Azimute 0° aponta para o microfone 0: ele recebe antes do microfone 2,
    # que está do lado oposto do círculo.
    correlacao = np.correlate(
        amostras[:, 0] - amostras[:, 0].mean(),
        amostras[:, 2] - amostras[:, 2].mean(),
        mode="full",
    )
    atraso_amostras = int(np.argmax(correlacao)) - (len(amostras) - 1)
    esperado = ARRAY.atraso_maximo_s * taxa

    assert atraso_amostras == pytest.approx(-esperado, abs=1.5)


def test_wav_de_quatro_canais_volta_igual(tmp_path):
    original = np.random.default_rng(7).uniform(-0.5, 0.5, size=(4096, 4)).astype(np.float32)
    caminho = escrever_wav(tmp_path / "campo.wav", original, 16000)

    fonte = FonteWav(caminho, bloco_amostras=1024, tempo_real=False, canais_esperados=4)
    with fonte:
        lido = np.concatenate([bloco.amostras for bloco in fonte.blocos()])

    assert fonte.taxa_amostragem == 16000
    assert lido.shape == original.shape
    np.testing.assert_allclose(lido, original, atol=1e-6)


def test_wav_termina_e_a_fonte_avisa(tmp_path):
    caminho = escrever_wav(tmp_path / "curto.wav", np.zeros((100, 4), np.float32), 16000)
    fonte = FonteWav(caminho, bloco_amostras=1024, tempo_real=False)

    with fonte:
        assert fonte.ler() is not None
        assert fonte.ler() is None


def test_wav_em_laco_nao_termina(tmp_path):
    caminho = escrever_wav(tmp_path / "laco.wav", np.zeros((100, 4), np.float32), 16000)
    fonte = FonteWav(caminho, bloco_amostras=64, laco=True, tempo_real=False)

    with fonte:
        blocos = [fonte.ler() for _ in range(5)]

    assert all(bloco is not None for bloco in blocos)


def test_wav_com_numero_de_canais_errado_e_recusado(tmp_path):
    caminho = escrever_wav(tmp_path / "mono.wav", np.zeros((100, 1), np.float32), 16000)

    with pytest.raises(ValueError, match="um canal por microfone"):
        FonteWav(caminho, canais_esperados=4)


def test_criar_fonte_segue_a_configuracao(tmp_path):
    config = de_dict(config_base())
    assert type(criar_fonte(config)).__name__ == "FonteSintetica"

    caminho = escrever_wav(tmp_path / "campo.wav", np.zeros((100, 4), np.float32), 16000)
    dados = config_base()
    dados["audio"]["fonte"] = {"tipo": "wav", "caminho": str(caminho), "tempo_real": False}
    assert type(criar_fonte(de_dict(dados))).__name__ == "FonteWav"


def test_fonte_i2s_nao_importa_hardware_no_topo_do_modulo():
    """Decisão D11: importar o pacote não pode exigir biblioteca de hardware."""
    import sys

    import edge.audio_capture.fontes as modulo

    assert "sounddevice" not in sys.modules
    assert "sounddevice" not in dir(modulo)
