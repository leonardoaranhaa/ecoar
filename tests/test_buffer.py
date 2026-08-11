import numpy as np
import pytest

from edge.audio_capture.buffer import BufferCircular, JanelaIndisponivel

TAXA = 1000
CANAIS = 4


def rampa(inicio: int, n: int, canais: int = CANAIS) -> np.ndarray:
    """Bloco onde o valor de cada amostra é o próprio índice global."""
    base = np.arange(inicio, inicio + n, dtype=np.float32)
    return np.repeat(base[:, None], canais, axis=1)


def test_janela_recupera_exatamente_o_trecho_pedido():
    buffer = BufferCircular(CANAIS, TAXA, segundos=2.0)
    buffer.escrever(rampa(0, 1000), timestamp=100.0)

    janela = buffer.janela(100.2, 100.5)

    assert len(janela.amostras) == 300
    assert janela.amostras[0, 0] == pytest.approx(200.0)
    assert janela.amostras[-1, 0] == pytest.approx(499.0)
    assert janela.inicio == pytest.approx(100.2)


def test_escrita_da_volta_no_anel_sem_perder_continuidade():
    buffer = BufferCircular(CANAIS, TAXA, segundos=1.0)
    for indice in range(5):
        buffer.escrever(rampa(indice * 400, 400), timestamp=100.0 + indice * 0.4)

    janela = buffer.ultimos(1.0)

    assert len(janela.amostras) == 1000
    esperado = np.arange(1000, 2000, dtype=np.float32)
    np.testing.assert_allclose(janela.amostras[:, 0], esperado)


def test_trecho_que_saiu_do_anel_falha_explicitamente():
    buffer = BufferCircular(CANAIS, TAXA, segundos=1.0)
    buffer.escrever(rampa(0, 1000), timestamp=100.0)
    buffer.escrever(rampa(1000, 1000), timestamp=101.0)

    with pytest.raises(JanelaIndisponivel, match="saiu do buffer"):
        buffer.janela(100.1, 100.4)


def test_trecho_ainda_nao_capturado_falha_explicitamente():
    buffer = BufferCircular(CANAIS, TAXA, segundos=2.0)
    buffer.escrever(rampa(0, 500), timestamp=100.0)

    with pytest.raises(JanelaIndisponivel, match="ainda não foi capturado"):
        buffer.janela(100.3, 100.9)


def test_janela_anterior_ao_pico_e_recuperavel():
    """A razão de o buffer circular existir: o começo do evento já passou."""
    buffer = BufferCircular(CANAIS, TAXA, segundos=30.0)
    for indice in range(30):
        buffer.escrever(rampa(indice * 1000, 1000), timestamp=100.0 + indice)

    pico = 120.0
    janela = buffer.janela(pico - 10, pico + 5)

    assert janela.duracao_s == pytest.approx(15.0)
    assert janela.inicio == pytest.approx(110.0)


def test_bloco_maior_que_o_anel_mantem_o_final():
    buffer = BufferCircular(CANAIS, TAXA, segundos=1.0)
    buffer.escrever(rampa(0, 2500), timestamp=100.0)

    janela = buffer.ultimos(1.0)

    assert janela.amostras[0, 0] == pytest.approx(1500.0)
    assert janela.amostras[-1, 0] == pytest.approx(2499.0)


def test_bloco_com_numero_de_canais_errado_e_recusado():
    buffer = BufferCircular(CANAIS, TAXA, segundos=1.0)
    with pytest.raises(ValueError, match="formato"):
        buffer.escrever(rampa(0, 100, canais=2), timestamp=100.0)


def test_aguardar_ate_retorna_falso_no_timeout():
    buffer = BufferCircular(CANAIS, TAXA, segundos=1.0)
    buffer.escrever(rampa(0, 100), timestamp=100.0)

    assert buffer.aguardar_ate(100.05, timeout=0.05) is True
    assert buffer.aguardar_ate(105.0, timeout=0.05) is False
