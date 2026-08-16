"""Tráfego (roadmap modular): dado operacional agregado, sem placa, sem fila
de revisão (não há decisão de infração para validar)."""

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.aplicacao import criar_app
from backend.config import ConfigBackend

TOKEN_NO = "token-do-no-trafego-0123456789"
TOKEN_OPERADOR = "token-operador-trafego-01234567"


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


def test_no_envia_agregados_e_backend_soma(ambiente):
    cliente, conexao = ambiente

    resposta = cliente.post(
        "/v1/trafego",
        json={"agregados": [
            {"dia": "2026-08-16", "hora": 10, "tipo": "moto", "contagem": 3},
            {"dia": "2026-08-16", "hora": 10, "tipo": "carro", "contagem": 5},
        ]},
        headers=como(TOKEN_NO),
    )

    assert resposta.status_code == 202
    assert resposta.json() == {"status": "ok", "recebidos": 2}
    assert db.trafego_por_tipo(conexao) == [
        {"tipo": "carro", "total": 5},
        {"tipo": "moto", "total": 3},
    ]


def test_reenvio_do_mesmo_balde_soma_em_vez_de_substituir(ambiente):
    """O nó drena e envia a cada cadência — o mesmo balde de hora/tipo pode
    chegar várias vezes ao longo da hora corrente."""
    cliente, conexao = ambiente
    corpo = {"agregados": [{"dia": "2026-08-16", "hora": 10, "tipo": "moto", "contagem": 2}]}

    cliente.post("/v1/trafego", json=corpo, headers=como(TOKEN_NO))
    cliente.post("/v1/trafego", json=corpo, headers=como(TOKEN_NO))

    assert db.trafego_por_tipo(conexao) == [{"tipo": "moto", "total": 4}]


def test_operador_le_trafego_agregado(ambiente):
    cliente, _ = ambiente
    cliente.post(
        "/v1/trafego",
        json={"agregados": [{"dia": "2026-08-16", "hora": 14, "tipo": "onibus", "contagem": 1}]},
        headers=como(TOKEN_NO),
    )

    resposta = cliente.get("/v1/trafego", headers=como(TOKEN_OPERADOR))

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["por_tipo"] == [{"tipo": "onibus", "total": 1}]
    assert corpo["por_hora"] == [{"hora": 14, "total": 1}]
    assert corpo["por_no"] == [{"no_id": "no-teste-01", "total": 1}]
    assert "planejamento de mobilidade" in corpo["observacao"]


def test_trafego_nao_aparece_na_fila_de_eventos(ambiente):
    """Não é evidência de infração — não deve entrar na fila de revisão."""
    cliente, _ = ambiente
    cliente.post(
        "/v1/trafego",
        json={"agregados": [{"dia": "2026-08-16", "hora": 10, "tipo": "moto", "contagem": 1}]},
        headers=como(TOKEN_NO),
    )

    fila = cliente.get("/v1/eventos", headers=como(TOKEN_OPERADOR)).json()
    assert fila["total"] == 0


def test_envio_exige_token_de_no(ambiente):
    cliente, _ = ambiente
    resposta = cliente.post(
        "/v1/trafego",
        json={"agregados": [{"dia": "2026-08-16", "hora": 10, "tipo": "moto", "contagem": 1}]},
    )
    assert resposta.status_code == 401


def test_leitura_exige_token_de_operador(ambiente):
    cliente, _ = ambiente
    assert cliente.get("/v1/trafego").status_code == 401
    assert cliente.get("/v1/trafego", headers=como(TOKEN_NO)).status_code == 401


def test_hora_fora_do_intervalo_e_recusada(ambiente):
    cliente, _ = ambiente
    resposta = cliente.post(
        "/v1/trafego",
        json={"agregados": [{"dia": "2026-08-16", "hora": 24, "tipo": "moto", "contagem": 1}]},
        headers=como(TOKEN_NO),
    )
    assert resposta.status_code == 422


def test_contagem_nao_positiva_e_recusada(ambiente):
    cliente, _ = ambiente
    resposta = cliente.post(
        "/v1/trafego",
        json={"agregados": [{"dia": "2026-08-16", "hora": 10, "tipo": "moto", "contagem": 0}]},
        headers=como(TOKEN_NO),
    )
    assert resposta.status_code == 422
