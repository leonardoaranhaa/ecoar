"""Fila de envio: prioridade, persistência e confirmação antes de apagar."""

import json
import threading
from pathlib import Path

import httpx
import pytest

from edge.config import ConfigUplink, ConfiguracaoInvalida
from edge.uplink import (
    PRIORIDADE_ALERTA,
    PRIORIDADE_EVENTO,
    ClienteBackend,
    EnvioFalhou,
    EnvioRecusado,
    FilaEnvio,
    Remetente,
)
from edge.uplink.fila import TIPO_ALERTA, TIPO_EVENTO, TIPO_HEARTBEAT


@pytest.fixture
def fila(tmp_path) -> FilaEnvio:
    return FilaEnvio(tmp_path / "fila.db")


# -- ordem -------------------------------------------------------------


def test_alerta_de_violacao_fura_a_fila_de_eventos(fila, tmp_path):
    """Quando alguém está arrancando o equipamento, o alerta é que precisa sair."""
    fila.enfileirar_evento(tmp_path / "a.ecoar")
    fila.enfileirar_evento(tmp_path / "b.ecoar")
    fila.enfileirar_alerta(json.dumps({"tipo": "abertura_de_gabinete"}))

    proximo = fila.proximo()

    assert proximo.tipo == TIPO_ALERTA
    assert proximo.prioridade == PRIORIDADE_ALERTA


def test_eventos_saem_em_ordem_de_chegada(fila, tmp_path):
    primeiro = fila.enfileirar_evento(tmp_path / "a.ecoar")
    fila.enfileirar_evento(tmp_path / "b.ecoar")

    assert fila.proximo().id == primeiro


def test_heartbeat_antigo_e_substituido(fila):
    """Cem heartbeats de uma noite sem sinal não dizem mais que o último."""
    fila.enfileirar_heartbeat(json.dumps({"bateria_pct": 90}))
    fila.enfileirar_heartbeat(json.dumps({"bateria_pct": 80}))
    fila.enfileirar_heartbeat(json.dumps({"bateria_pct": 70}))

    assert fila.pendentes() == 1
    assert json.loads(fila.proximo().corpo)["bateria_pct"] == 70


# -- concorrência --------------------------------------------------------


def test_escritas_concorrentes_na_fila_nao_colidem(tmp_path):
    """No nó de verdade, eventos, tamper, heartbeat e o remetente enfileiram
    ou drenam a mesma fila ao mesmo tempo, o tempo todo — não é um caso raro.

    Sem lock em volta da conexão, isso derrubava ~10% das operações
    (`OperationalError`, `SystemError`, `lastrowid` vindo `None`) e podia
    perder evidência sem nenhum aviso além de uma linha de log."""
    fila = FilaEnvio(tmp_path / "fila.db", tentativas_maximas=99)
    erros: list[Exception] = []

    def enfileirar_eventos(n: int) -> None:
        for i in range(n):
            try:
                fila.enfileirar_evento(f"/tmp/evt-{i}.ecoar")
            except Exception as erro:  # noqa: BLE001 — captura para o teste falhar com detalhe
                erros.append(erro)

    def enfileirar_heartbeats(n: int) -> None:
        for i in range(n):
            try:
                fila.enfileirar_heartbeat(json.dumps({"n": i}))
            except Exception as erro:  # noqa: BLE001
                erros.append(erro)

    def drenar(n: int) -> None:
        for _ in range(n):
            try:
                item = fila.proximo()
                if item is None:
                    continue
                if item.id % 2 == 0:
                    fila.confirmar(item.id)
                else:
                    fila.adiar(item.id, "erro simulado", agora=0.0)
            except Exception as erro:  # noqa: BLE001
                erros.append(erro)

    threads = (
        [threading.Thread(target=enfileirar_eventos, args=(150,)) for _ in range(3)]
        + [threading.Thread(target=enfileirar_heartbeats, args=(150,)) for _ in range(2)]
        + [threading.Thread(target=drenar, args=(250,)) for _ in range(3)]
    )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert erros == [], f"{len(erros)} operação(ões) concorrente(s) falharam: {erros[:3]}"


# -- persistência e retentativa ----------------------------------------


def test_fila_sobrevive_a_reboot(tmp_path):
    caminho = tmp_path / "fila.db"
    primeira = FilaEnvio(caminho)
    primeira.enfileirar_evento(tmp_path / "a.ecoar")
    primeira.fechar()

    segunda = FilaEnvio(caminho)

    assert segunda.pendentes() == 1


def test_espera_cresce_a_cada_falha(fila, tmp_path):
    item = fila.enfileirar_evento(tmp_path / "a.ecoar")

    fila.adiar(item, "sem rede", agora=1000.0)
    assert fila.proximo(agora=1001.0) is None, "deveria estar aguardando"
    assert fila.proximo(agora=1003.0) is not None

    fila.adiar(item, "sem rede", agora=1003.0)
    assert fila.proximo(agora=1006.0) is None
    assert fila.proximo(agora=1008.0) is not None


def test_desiste_depois_do_limite_de_tentativas(tmp_path):
    fila = FilaEnvio(tmp_path / "fila.db", tentativas_maximas=3)
    item = fila.enfileirar_evento(tmp_path / "a.ecoar")

    assert fila.adiar(item, "erro") is True
    assert fila.adiar(item, "erro") is True
    assert fila.adiar(item, "erro") is False

    assert fila.pendentes() == 0
    assert fila.mortos() == 1


def test_item_so_sai_da_fila_com_confirmacao(fila, tmp_path):
    item = fila.enfileirar_evento(tmp_path / "a.ecoar")
    fila.adiar(item, "sem rede")

    assert fila.pendentes() == 1

    fila.confirmar(item)
    assert fila.pendentes() == 0


# -- cliente -----------------------------------------------------------


def _cliente(manipulador, **extras) -> ClienteBackend:
    config = ConfigUplink(url="http://127.0.0.1:9999", token="t" * 20, **extras)
    transporte = httpx.MockTransport(manipulador)
    http = httpx.Client(base_url=config.url, transport=transporte)
    return ClienteBackend(config, cliente_http=http)


def test_sucesso_devolve_corpo(tmp_path):
    pacote = tmp_path / "a.ecoar"
    pacote.write_bytes(b"conteudo")

    cliente = _cliente(
        lambda pedido: httpx.Response(201, json={"status": "recebido", "id": 7})
    )
    resposta = cliente.enviar_evento(pacote)

    assert resposta.corpo["id"] == 7


def test_erro_de_rede_e_temporario(tmp_path):
    pacote = tmp_path / "a.ecoar"
    pacote.write_bytes(b"x")

    def cair(pedido):
        raise httpx.ConnectError("sem rota para o host")

    with pytest.raises(EnvioFalhou):
        _cliente(cair).enviar_evento(pacote)


def test_erro_do_servidor_e_temporario(tmp_path):
    pacote = tmp_path / "a.ecoar"
    pacote.write_bytes(b"x")

    with pytest.raises(EnvioFalhou):
        _cliente(lambda p: httpx.Response(503)).enviar_evento(pacote)


def test_recusa_do_backend_e_definitiva(tmp_path):
    """422 significa que o pacote não é íntegro: reenviar daria o mesmo."""
    pacote = tmp_path / "a.ecoar"
    pacote.write_bytes(b"x")

    with pytest.raises(EnvioRecusado):
        _cliente(lambda p: httpx.Response(422, json={"detail": "não íntegro"})).enviar_evento(
            pacote
        )


def test_excesso_de_requisicoes_e_temporario_apesar_de_ser_4xx(tmp_path):
    pacote = tmp_path / "a.ecoar"
    pacote.write_bytes(b"x")

    with pytest.raises(EnvioFalhou):
        _cliente(lambda p: httpx.Response(429)).enviar_evento(pacote)


# -- remetente ---------------------------------------------------------


def test_pacote_confirmado_e_apagado_do_disco(fila, tmp_path):
    pacote = tmp_path / "a.ecoar"
    pacote.write_bytes(b"conteudo")
    fila.enfileirar_evento(pacote)

    remetente = Remetente(
        fila, _cliente(lambda p: httpx.Response(201, json={"status": "recebido"}))
    )
    assert remetente.despachar_um() is True

    assert fila.pendentes() == 0
    assert not pacote.exists(), "o pacote só é apagado depois da confirmação"


def test_pacote_nao_confirmado_permanece_no_disco(fila, tmp_path):
    pacote = tmp_path / "a.ecoar"
    pacote.write_bytes(b"conteudo")
    fila.enfileirar_evento(pacote)

    remetente = Remetente(fila, _cliente(lambda p: httpx.Response(503)))
    remetente.despachar_um()

    assert pacote.exists()
    assert fila.pendentes() == 1


def test_pacote_recusado_sai_da_fila_mas_fica_no_disco(fila, tmp_path):
    """Recusa definitiva não pode travar a fila atrás de si."""
    pacote = tmp_path / "a.ecoar"
    pacote.write_bytes(b"corrompido")
    fila.enfileirar_evento(pacote)
    fila.enfileirar_evento(tmp_path / "b.ecoar")

    remetente = Remetente(fila, _cliente(lambda p: httpx.Response(422)))
    remetente.despachar_um()

    assert fila.mortos() == 1
    assert pacote.exists(), "o arquivo fica para inspeção"
    assert fila.proximo() is not None, "a fila continua andando"


def test_despachar_tudo_esvazia_a_fila(fila, tmp_path):
    for nome in ("a", "b", "c"):
        caminho = tmp_path / f"{nome}.ecoar"
        caminho.write_bytes(b"x")
        fila.enfileirar_evento(caminho)

    remetente = Remetente(fila, _cliente(lambda p: httpx.Response(201, json={})))

    assert remetente.despachar_tudo() == 3
    assert fila.pendentes() == 0


# -- configuração ------------------------------------------------------


def test_http_sem_tls_para_endereco_publico_e_recusado():
    with pytest.raises(ConfiguracaoInvalida, match="não trafega em claro"):
        ConfigUplink(url="http://ecoar.exemplo.br").validar()


def test_http_local_e_aceito_para_desenvolvimento():
    ConfigUplink(url="http://127.0.0.1:8000").validar()
    ConfigUplink(url="http://192.168.0.10:8000").validar()


def test_https_publico_e_aceito():
    ConfigUplink(url="https://ecoar.exemplo.br").validar()


def test_heartbeat_curto_demais_e_recusado():
    with pytest.raises(ConfiguracaoInvalida, match="gasta rádio"):
        ConfigUplink(heartbeat_s=5).validar()
