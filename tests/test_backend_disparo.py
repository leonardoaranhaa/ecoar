"""Disparo de arma de fogo (protótipo conceitual, D16): canal separado, nunca
'disparo confirmado'."""

import pytest
from fastapi.testclient import TestClient

from backend.aplicacao import criar_app
from backend.audit_log import ALERTA_DISPARO_CONCEITO, TrilhaAuditoria
from backend.config import ConfigBackend

TOKEN_NO = "token-do-no-disparo-01234567890"
TOKEN_OPERADOR = "token-operador-disparo-01234567"


@pytest.fixture
def ambiente(tmp_path):
    config = ConfigBackend(
        banco=tmp_path / "ecoar.db",
        armazenamento=tmp_path / "pacotes",
        tokens={"no-teste-01": TOKEN_NO},
        tokens_operador={"operador-teste": TOKEN_OPERADOR},
    )
    app = criar_app(config)
    with TestClient(app) as cliente:
        yield cliente, app.state.conexao


def como(token):
    return {"Authorization": f"Bearer {token}"}


def _enviar_alerta(cliente, pico_relativo_db=45.0):
    return cliente.post(
        "/v1/alertas-disparo-conceito",
        json={"pico_relativo_db": pico_relativo_db, "instante_relativo_s": 0.4},
        headers=como(TOKEN_NO),
    )


def test_no_registra_alerta_e_entra_na_trilha(ambiente):
    cliente, conexao = ambiente

    resposta = _enviar_alerta(cliente)

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["status"] == "registrado"
    assert corpo["validado"] is False

    tipos = [e.tipo for e in TrilhaAuditoria(conexao).listar()]
    assert ALERTA_DISPARO_CONCEITO in tipos


def test_operador_le_alertas_com_aviso_de_nao_validado(ambiente):
    cliente, _ = ambiente
    _enviar_alerta(cliente, pico_relativo_db=52.3)

    resposta = cliente.get("/v1/alertas-disparo-conceito", headers=como(TOKEN_OPERADOR))

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo["alertas"]) == 1
    assert corpo["alertas"][0]["pico_relativo_db"] == pytest.approx(52.3)
    assert corpo["alertas"][0]["validado"] is False
    assert "não há validação" in corpo["aviso"]


def test_atender_muda_status(ambiente):
    cliente, _ = ambiente
    identificador = _enviar_alerta(cliente).json()["id"]

    resposta = cliente.post(
        f"/v1/alertas-disparo-conceito/{identificador}/atender", headers=como(TOKEN_OPERADOR)
    )
    assert resposta.status_code == 200

    pendentes = cliente.get(
        "/v1/alertas-disparo-conceito?apenas_pendentes=true", headers=como(TOKEN_OPERADOR)
    ).json()
    assert pendentes["alertas"] == []


def test_atender_alerta_inexistente_e_recusado(ambiente):
    cliente, _ = ambiente
    resposta = cliente.post(
        "/v1/alertas-disparo-conceito/999/atender", headers=como(TOKEN_OPERADOR)
    )
    assert resposta.status_code == 404


def test_disparo_nao_aparece_na_fila_de_eventos_nem_em_violacoes(ambiente):
    """Canal separado (D14) tanto do de eventos acústicos quanto do de
    violação patrimonial."""
    cliente, _ = ambiente
    _enviar_alerta(cliente)

    fila = cliente.get("/v1/eventos", headers=como(TOKEN_OPERADOR)).json()
    assert fila["total"] == 0

    violacoes = cliente.get("/v1/violacoes", headers=como(TOKEN_OPERADOR)).json()
    assert violacoes["violacoes"] == []


def test_envio_exige_token_de_no(ambiente):
    cliente, _ = ambiente
    resposta = cliente.post(
        "/v1/alertas-disparo-conceito",
        json={"pico_relativo_db": 45.0, "instante_relativo_s": 0.4},
    )
    assert resposta.status_code == 401


def test_leitura_exige_token_de_operador(ambiente):
    cliente, _ = ambiente
    assert cliente.get("/v1/alertas-disparo-conceito").status_code == 401
    assert cliente.get("/v1/alertas-disparo-conceito", headers=como(TOKEN_NO)).status_code == 401
