import numpy as np
import pytest

from edge.audio_capture.captura import CapturaAudio
from edge.audio_capture.fontes import FonteSintetica, FonteWav, escrever_wav
from edge.audio_capture.sonometro import SonometroMock
from edge.config import de_dict
from edge.geometria import ArrayCircular
from tests.conftest import config_base


def _config_wav(caminho, **audio) -> object:
    dados = config_base()
    dados["audio"].update(audio)
    dados["audio"]["fonte"] = {"tipo": "wav", "caminho": str(caminho), "tempo_real": False}
    return de_dict(dados)


def test_captura_preenche_o_buffer_e_estima_spl(config):
    captura = CapturaAudio(config)
    with captura:
        assert captura.aguardar_primeiro_bloco(timeout=5.0)
        spl = captura.spl_atual()

    assert spl is not None
    assert np.isfinite(spl.db)
    assert spl.valor_legal is False


def test_janela_de_evento_recupera_antes_e_depois_do_pico(tmp_path):
    taxa = 16000
    amostras = np.zeros((taxa * 8, 4), dtype=np.float32)
    amostras[taxa * 4 : taxa * 4 + 800] = 0.6  # pico no quarto segundo
    caminho = escrever_wav(tmp_path / "evento.wav", amostras, taxa)

    config = _config_wav(caminho, buffer_segundos=10, bloco_amostras=1024)
    captura = CapturaAudio(config)
    with captura:
        inicio, _ = _aguardar_intervalo(captura)
        pico = inicio + 4.0
        evento = captura.janela_evento(pico, antes=2.0, depois=2.0, timeout=10.0)

    assert evento.janela.duracao_s == pytest.approx(4.0, abs=0.01)
    assert evento.instante_pico == pytest.approx(pico)
    # O trecho anterior ao pico só existe porque o buffer guardava o passado.
    meio = len(evento.amostras) // 2
    assert np.abs(evento.amostras[:meio]).max() < np.abs(evento.amostras[meio:]).max()


def test_evento_registra_ausencia_de_instrumento_sem_inventar_valor(config):
    captura = CapturaAudio(config)
    with captura:
        captura.aguardar_primeiro_bloco(timeout=5.0)
        leitura, motivo = captura.ler_sonometro()

    assert leitura is None
    assert "nenhum instrumento" in motivo


def test_evento_inclui_leitura_quando_ha_instrumento(tmp_path):
    taxa = 16000
    caminho = escrever_wav(tmp_path / "curto.wav", np.zeros((taxa * 3, 4), np.float32), taxa)
    config = _config_wav(caminho, buffer_segundos=5, bloco_amostras=1024)

    captura = CapturaAudio(config, sonometro=SonometroMock(valores=[77.5]))
    with captura:
        inicio, _ = _aguardar_intervalo(captura)
        evento = captura.janela_evento(inicio + 1.5, antes=1.0, depois=1.0, timeout=10.0)

    assert evento.sonometro is not None
    assert evento.sonometro.db == 77.5
    assert evento.como_dict()["medicao_instrumento"]["valor_legal"] is False


def test_fonte_finita_marca_o_fim(tmp_path):
    caminho = escrever_wav(tmp_path / "fim.wav", np.zeros((2000, 4), np.float32), 16000)
    captura = CapturaAudio(_config_wav(caminho))

    with captura:
        captura.aguardar_primeiro_bloco(timeout=5.0)
        _esperar(lambda: captura.fonte_terminou, timeout=5.0)

    assert captura.fonte_terminou


def test_estado_serve_de_diagnostico(config):
    captura = CapturaAudio(config)
    with captura:
        captura.aguardar_primeiro_bloco(timeout=5.0)
        estado = captura.estado()

    assert estado["rodando"] is True
    assert estado["blocos_lidos"] > 0
    assert estado["instrumento"]["valor_legal"] is False
    assert estado["falha"] is None


def test_captura_aceita_fonte_injetada(config):
    fonte = FonteSintetica(
        ArrayCircular.de_config(config.array),
        taxa_amostragem=config.audio.taxa_amostragem,
        bloco_amostras=256,
        tempo_real=False,
        perfil="buzina",
    )
    captura = CapturaAudio(config, fonte=fonte)

    with captura:
        assert captura.aguardar_primeiro_bloco(timeout=5.0)

    assert captura.estado()["fonte"]["perfil"] == "buzina"


def _aguardar_intervalo(captura, timeout: float = 5.0):
    assert captura.aguardar_primeiro_bloco(timeout=timeout)
    return captura.buffer.intervalo_disponivel()


def _esperar(condicao, timeout: float) -> None:
    import time

    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicao():
            return
        time.sleep(0.01)
    raise AssertionError("condição não ocorreu no tempo esperado")


def test_fonte_wav_direta_tem_a_taxa_do_arquivo(tmp_path):
    caminho = escrever_wav(tmp_path / "taxa.wav", np.zeros((100, 4), np.float32), 44100)
    fonte = FonteWav(caminho, tempo_real=False)
    assert fonte.taxa_amostragem == 44100
