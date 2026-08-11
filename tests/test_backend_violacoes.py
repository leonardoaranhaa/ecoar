"""Canal patrimonial no backend: separado da fila de fiscalização (D14)."""

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.aplicacao import criar_app
from backend.audit_log import ALERTA_VIOLACAO, TrilhaAuditoria
from backend.config import ConfigBackend

TOKEN_NO = "token-do-no-violacoes-01234567"
TOKEN_OPERADOR = "token-operador-violacoes-012345"


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


def test_alerta_entra_no_canal_patrimonial_e_na_trilha(ambiente):
    cliente, conexao = ambiente

    resposta = cliente.post(
        "/v1/alertas",
        json={
            "tipo": "abertura_gabinete",
            "capturado_em": "2026-08-17T03:00:00+00:00",
            "detalhe": {"origem": "reed switch"},
            "imagem": "abertura.png",
        },
        headers=como(TOKEN_NO),
    )

    assert resposta.status_code == 201
    assert resposta.json()["tipo"] == "abertura_gabinete"

    violacoes = db.listar_violacoes(conexao)
    assert len(violacoes) == 1
    assert violacoes[0]["tipo"] == "abertura_gabinete"
    assert violacoes[0]["atendido"] == 0

    assert any(e.tipo == ALERTA_VIOLACAO for e in TrilhaAuditoria(conexao).listar())


def test_violacao_nao_aparece_na_fila_de_eventos(ambiente):
    """Ocorrência patrimonial não é evento de fiscalização."""
    cliente, conexao = ambiente
    cliente.post("/v1/alertas", json={"tipo": "impacto"}, headers=como(TOKEN_NO))

    fila = cliente.get("/v1/eventos", headers=como(TOKEN_OPERADOR)).json()
    assert fila["total"] == 0

    violacoes = cliente.get("/v1/violacoes", headers=como(TOKEN_OPERADOR)).json()
    assert len(violacoes["violacoes"]) == 1


def test_operador_atende_violacao(ambiente):
    cliente, conexao = ambiente
    cliente.post("/v1/alertas", json={"tipo": "impacto"}, headers=como(TOKEN_NO))
    violacao_id = db.listar_violacoes(conexao)[0]["id"]

    cliente.post(f"/v1/violacoes/{violacao_id}/atender", headers=como(TOKEN_OPERADOR))

    pendentes = cliente.get(
        "/v1/violacoes?apenas_pendentes=true", headers=como(TOKEN_OPERADOR)
    ).json()
    assert pendentes["violacoes"] == []


def test_alerta_exige_token_de_no(ambiente):
    cliente, _ = ambiente
    assert cliente.post("/v1/alertas", json={"tipo": "impacto"}).status_code == 401


def test_trilha_do_alerta_nao_carrega_placa(ambiente):
    import json

    cliente, conexao = ambiente
    cliente.post(
        "/v1/alertas",
        json={"tipo": "impacto", "detalhe": {"placa": "ABC1D23", "magnitude_g": 3.1}},
        headers=como(TOKEN_NO),
    )

    bruto = json.dumps([e.como_dict() for e in TrilhaAuditoria(conexao).listar()]).lower()
    assert "abc1d23" not in bruto
    assert "placa" not in bruto
