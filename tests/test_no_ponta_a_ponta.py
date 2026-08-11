"""Ensaio da cadeia inteira: som sintético até o evento na fila do operador.

É o teste que responde "o sistema funciona?" — os outros respondem "esta peça
funciona?". Roda sem hardware, sem rede externa e sem servidor separado: o nó
fala com o backend por um transporte em memória.
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.aplicacao import criar_app
from backend.config import ConfigBackend
from edge.audio_capture.buffer import Janela
from edge.audio_capture.captura import JanelaEvento
from edge.audio_capture.spl import estimar
from edge.config import ConfigCalibracao, de_dict
from edge.geometria import ArrayCircular
from edge.evidence_packager import verificar_pacote
from edge.no import No
from edge.uplink import ClienteBackend, FilaEnvio, Remetente
from tests.conftest import config_base

TOKEN_NO = "token-do-no-ponta-a-ponta-01234"
TOKEN_OPERADOR = "token-operador-ponta-a-ponta-01"
NO_ID = "no-ensaio-01"


def config_do_no(tmp_path, **extras):
    dados = config_base()
    dados["no"]["id"] = NO_ID
    dados["no"]["geolocalizacao"] = {"latitude": -22.31, "longitude": -49.06}
    dados["audio"]["taxa_amostragem"] = 16000
    dados["audio"]["buffer_segundos"] = 20
    dados["audio"]["bloco_amostras"] = 2048
    dados["audio"]["fonte"] = {
        "tipo": "sintetica",
        "perfil": "escapamento",
        "azimute_graus": 20.0,
        "tempo_real": False,
    }
    dados["gatilho"] = {
        "spl_db_minimo": 40.0,
        "score_aciona": 0.80,
        "score_ambiguo": 0.45,
        # Janela curta para o ensaio ser rápido; em campo são 10 s + 10 s.
        "janela_antes_s": 2.0,
        "janela_depois_s": 2.0,
    }
    dados["uplink"] = {
        "url": "http://127.0.0.1:8000",
        "token": TOKEN_NO,
        "fila": str(tmp_path / "fila.db"),
        "diretorio_pacotes": str(tmp_path / "pacotes"),
    }
    dados["camera"] = {"tipo": "mock", "diretorio": str(tmp_path / "capturas")}
    dados.update(extras)
    return de_dict(dados)


@pytest.fixture
def backend(tmp_path):
    config = ConfigBackend(
        banco=tmp_path / "ecoar.db",
        armazenamento=tmp_path / "guardados",
        tokens={NO_ID: TOKEN_NO},
        tokens_operador={"operador-ensaio": TOKEN_OPERADOR},
    )
    app = criar_app(config)
    with TestClient(app) as cliente:
        yield cliente, app.state.conexao


def evento_sintetico(config, instante_pico=1_770_000_000.0, ganho=1.0):
    """Janela de evento pronta, para exercitar a cadeia sem esperar captura.

    Usa a mesma cena sintética da fonte de bancada, e não um tom puro: um tom
    de 1 kHz não é escapamento para o classificador — e não deveria ser mesmo.
    """
    from edge.audio_capture.sintetico import CenaSintetica

    taxa = config.audio.taxa_amostragem
    cena = CenaSintetica(
        ArrayCircular.de_config(config.array),
        taxa_amostragem=taxa,
        perfil="escapamento",
        azimute_graus=20.0,
    )
    amostras = cena.bloco(taxa * 3, indice_inicial=int(2.5 * taxa)) * ganho
    amostras = amostras.astype(np.float32)
    duracao = len(amostras) / taxa
    return JanelaEvento(
        janela=Janela(amostras, taxa, instante_pico - duracao / 2, instante_pico + duracao / 2),
        spl=estimar(amostras, taxa, ConfigCalibracao()),
        instante_pico=instante_pico,
        sonometro=None,
        motivo_sem_sonometro="sem instrumento em modo de triagem",
    )


def test_cadeia_completa_do_som_ate_a_fila_do_operador(backend, tmp_path, monkeypatch):
    cliente_http, conexao = backend
    config = config_do_no(tmp_path)

    no = No(config)
    no.acionador.abrir()

    # A captura é substituída pela janela pronta: o que este teste exercita é o
    # encadeamento (localização → classificação → decisão → pacote → fila), não
    # a leitura do microfone, que tem teste próprio.
    monkeypatch.setattr(no.captura, "janela_evento", lambda *a, **k: evento_sintetico(config))

    evento_id = no.processar_evento(1_770_000_000.0)

    assert evento_id.startswith(NO_ID)
    assert no.fila.pendentes() == 1

    pacote = next((tmp_path / "pacotes").glob("*.ecoar"))
    assert verificar_pacote(pacote).valido

    # O nó envia pelo transporte do TestClient — sem servidor separado.
    remetente = Remetente(
        no.fila,
        ClienteBackend(config.uplink, cliente_http=_cliente_do_teste(cliente_http)),
    )
    assert remetente.despachar_tudo() == 1
    assert no.fila.pendentes() == 0

    linhas = db.listar_eventos(conexao)
    assert len(linhas) == 1
    assert linhas[0]["no_id"] == NO_ID
    assert linhas[0]["status"] == db.STATUS_PENDENTE

    fila = cliente_http.get(
        "/v1/eventos?status=pendente_revisao",
        headers={"Authorization": f"Bearer {TOKEN_OPERADOR}"},
    ).json()
    assert fila["total"] == 1
    assert fila["eventos"][0]["evento_id"] == evento_id

    no.acionador.fechar()
    no.fila.fechar()


def test_som_fraco_nao_gera_evento(backend, tmp_path, monkeypatch):
    """O caminho de "não deveria acionar" também precisa ser exercitado."""
    cliente_http, conexao = backend
    config = config_do_no(tmp_path)

    no = No(config)
    no.acionador.abrir()
    monkeypatch.setattr(
        no.captura,
        "janela_evento",
        lambda *a, **k: evento_sintetico(config, ganho=0.0005),
    )

    no.processar_evento(1_770_000_000.0)

    assert no.contadores.acionados == 0
    assert no.fila.pendentes() == 0 or no.contadores.ambiguos == 1

    no.acionador.fechar()
    no.fila.fechar()


def test_classificador_fora_do_ar_gera_ambiguo_e_nao_perde_o_evento(
    backend, tmp_path, monkeypatch
):
    """Fail-closed de ponta a ponta: o evento chega ao operador sem imagem."""
    cliente_http, conexao = backend
    config = config_do_no(tmp_path)

    no = No(config)
    no.acionador.abrir()
    monkeypatch.setattr(no.captura, "janela_evento", lambda *a, **k: evento_sintetico(config))

    from edge.classifier.base import ClassificadorIndisponivel

    def cair(*_, **__):
        raise ClassificadorIndisponivel("modelo não carregou")

    monkeypatch.setattr(no.classificador, "classificar", cair)

    no.processar_evento(1_770_000_000.0)

    assert no.contadores.ambiguos == 1
    assert no.fila.pendentes() == 1

    remetente = Remetente(
        no.fila,
        ClienteBackend(config.uplink, cliente_http=_cliente_do_teste(cliente_http)),
    )
    remetente.despachar_tudo()

    linha = db.listar_eventos(conexao)[0]
    assert linha["acao"] == "ambiguo"
    assert linha["n_imagens"] == 0
    assert linha["status"] == db.STATUS_PENDENTE

    no.acionador.fechar()
    no.fila.fechar()


def test_no_detecta_pico_sozinho_e_enfileira(tmp_path):
    """Sem substituir nada: cena sintética entra, evento sai na fila.

    Em tempo real de propósito. Com a fonte correndo solta, a captura consome o
    anel de 20 s em fração de segundo e a janela do evento já teria saído
    quando o processamento fosse buscá-la — o ensaio mediria o simulador, não o
    sistema.
    """
    config = config_do_no(tmp_path)
    from dataclasses import replace

    config = replace(
        config,
        audio=replace(
            config.audio, fonte=replace(config.audio.fonte, tempo_real=True)
        ),
    )
    no = No(config)
    no.iniciar(com_uplink=False)
    try:
        assert no.captura.aguardar_primeiro_bloco(timeout=10.0)
        # Espera um evento que sobreviva à decisão. O primeiro pico depois de
        # subir costuma vir com pré-registro truncado e pontuar baixo — é
        # comportamento correto, mas não é o que este ensaio quer medir.
        _esperar(
            lambda: no.contadores.acionados + no.contadores.ambiguos >= 1,
            timeout=45.0,
        )
    finally:
        estado = no.estado()
        no.parar()

    assert estado["picos_detectados"] >= 1
    assert estado["eventos_processados"] >= 1
    assert no.fila.pendentes() >= 1

    for pacote in (tmp_path / "pacotes").glob("*.ecoar"):
        assert verificar_pacote(pacote).valido


def test_reenvio_apos_queda_de_rede_nao_duplica(backend, tmp_path, monkeypatch):
    """4G caiu no meio do ACK: o nó reenvia, e o operador vê um evento só."""
    cliente_http, conexao = backend
    config = config_do_no(tmp_path)

    no = No(config)
    no.acionador.abrir()
    monkeypatch.setattr(no.captura, "janela_evento", lambda *a, **k: evento_sintetico(config))
    no.processar_evento(1_770_000_000.0)

    caminho = next((tmp_path / "pacotes").glob("*.ecoar"))

    # Primeiro envio chega ao backend, mas a confirmação se perde.
    import httpx

    transporte_real = cliente_http._transport

    class TransporteQueEngoleOAck(httpx.BaseTransport):
        def __init__(self):
            self.chamadas = 0

        def handle_request(self, pedido):
            self.chamadas += 1
            resposta = transporte_real.handle_request(pedido)
            if self.chamadas == 1:
                resposta.read()
                raise httpx.ReadTimeout("ack perdido")
            return resposta

    transporte = TransporteQueEngoleOAck()
    cliente = ClienteBackend(
        config.uplink,
        cliente_http=httpx.Client(
            base_url="http://testserver",
            transport=transporte,
            headers={"Authorization": f"Bearer {TOKEN_NO}"},
        ),
    )
    remetente = Remetente(no.fila, cliente)

    remetente.despachar_um()  # falha: o item continua na fila
    assert no.fila.pendentes() == 1
    assert caminho.exists()

    from edge.uplink.fila import SITUACAO_PENDENTE

    no.fila._conexao.execute(
        "UPDATE envios SET proxima_tentativa = 0 WHERE situacao = ?", (SITUACAO_PENDENTE,)
    )
    no.fila._conexao.commit()

    remetente.despachar_um()  # reenvio: o backend responde 'ja_recebido'

    assert no.fila.pendentes() == 0
    assert len(db.listar_eventos(conexao)) == 1, "reenvio não pode duplicar evento"

    no.acionador.fechar()
    no.fila.fechar()


def _cliente_do_teste(cliente_http: TestClient):
    """Reaproveita o transporte do TestClient como se fosse a rede."""
    import httpx

    return httpx.Client(
        base_url="http://testserver",
        transport=cliente_http._transport,
        headers={"Authorization": f"Bearer {TOKEN_NO}"},
    )


def _esperar(condicao, timeout: float) -> None:
    import time

    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicao():
            return
        time.sleep(0.05)
    raise AssertionError("condição não ocorreu no tempo esperado")
