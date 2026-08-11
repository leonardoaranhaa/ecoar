"""Plataforma de gestão: priorização, métricas, modelo, exportação e RBAC."""

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.aplicacao import criar_app
from backend.config import ConfigBackend
from tests.conftest_backend import gerar_pacote

TOKEN_NO = "token-do-no-gestao-01234567890"
TOKEN_OPERADOR = "token-operador-gestao-012345678"
TOKEN_ADMIN = "token-admin-gestao-01234567890a"


@pytest.fixture
def ambiente(tmp_path):
    config = ConfigBackend(
        banco=tmp_path / "ecoar.db",
        armazenamento=tmp_path / "pacotes",
        tokens={"no-teste-01": TOKEN_NO},
        tokens_operador={"operador-teste": TOKEN_OPERADOR, "admin-teste": TOKEN_ADMIN},
    )
    app = criar_app(config)
    with TestClient(app) as cliente:
        yield cliente, app.state.conexao, tmp_path


def como(token):
    return {"Authorization": f"Bearer {token}"}


def ingerir_e_confirmar(cliente, tmp_path, evento_id, instante, confirmar=True, operador=TOKEN_OPERADOR):
    pacote = gerar_pacote(tmp_path / f"{evento_id}.ecoar", evento_id=evento_id, instante_pico=instante)
    with open(pacote, "rb") as arquivo:
        ident = cliente.post("/v1/eventos", files={"pacote": (pacote.name, arquivo)}, headers=como(TOKEN_NO)).json()["id"]
    if confirmar is not None:
        cliente.post(
            f"/v1/eventos/{ident}/revisao",
            json={"decisao": "confirmar" if confirmar else "rejeitar"},
            headers=como(operador),
        )
    return ident


# -- RBAC --------------------------------------------------------------


def test_eu_diz_quem_esta_logado(ambiente):
    cliente, _, _ = ambiente
    operador = cliente.get("/v1/eu", headers=como(TOKEN_OPERADOR)).json()
    admin = cliente.get("/v1/eu", headers=como(TOKEN_ADMIN)).json()

    assert operador["perfil"] == "operador" and operador["admin"] is False
    assert admin["perfil"] == "admin" and admin["admin"] is True


def test_priorizacao_e_metricas_sao_do_operador(ambiente):
    cliente, _, _ = ambiente
    assert cliente.get("/v1/priorizacao", headers=como(TOKEN_OPERADOR)).status_code == 200
    assert cliente.get("/v1/metricas", headers=como(TOKEN_OPERADOR)).status_code == 200


def test_modelo_e_restrito_a_admin_no_dashboard_mas_endpoint_e_do_operador(ambiente):
    # O endpoint em si não é sensível; a restrição de admin é a tela.
    cliente, _, _ = ambiente
    assert cliente.get("/v1/modelo/versoes", headers=como(TOKEN_OPERADOR)).status_code == 200


# -- priorização -------------------------------------------------------


def test_priorizacao_so_conta_confirmados(ambiente):
    """Priorizar sobre evento pendente ou rejeitado mandaria a blitz errado."""
    cliente, conexao, tmp_path = ambiente
    # segunda-feira 04h  (2026-02-02T04:40:00Z já é usado como base)
    ingerir_e_confirmar(cliente, tmp_path, "conf-1", 1_770_007_200.0, confirmar=True)
    ingerir_e_confirmar(cliente, tmp_path, "rej-1", 1_770_010_800.0, confirmar=False)
    ingerir_e_confirmar(cliente, tmp_path, "pend-1", 1_770_014_400.0, confirmar=None)

    dados = cliente.get("/v1/priorizacao", headers=como(TOKEN_OPERADOR)).json()

    total = sum(c["total"] for c in dados["hora_dia"])
    assert total == 1, "só o confirmado entra na priorização"
    assert dados["por_no"][0]["confirmados"] == 1


def test_priorizacao_agrupa_por_hora_e_dia(ambiente):
    cliente, conexao, tmp_path = ambiente
    ingerir_e_confirmar(cliente, tmp_path, "e1", 1_770_007_200.0, confirmar=True)

    dados = cliente.get("/v1/priorizacao", headers=como(TOKEN_OPERADOR)).json()
    assert dados["hora_dia"]
    celula = dados["hora_dia"][0]
    assert 0 <= celula["dia"] <= 6
    assert 0 <= celula["hora"] <= 23


# -- métricas ----------------------------------------------------------


def test_taxa_de_rejeicao_ignora_pendentes(ambiente):
    cliente, conexao, tmp_path = ambiente
    ingerir_e_confirmar(cliente, tmp_path, "c1", 1_770_007_200.0, confirmar=True)
    ingerir_e_confirmar(cliente, tmp_path, "c2", 1_770_010_800.0, confirmar=True)
    ingerir_e_confirmar(cliente, tmp_path, "r1", 1_770_014_400.0, confirmar=False)
    ingerir_e_confirmar(cliente, tmp_path, "p1", 1_770_018_000.0, confirmar=None)

    dados = cliente.get("/v1/metricas", headers=como(TOKEN_OPERADOR)).json()
    r = dados["rejeicao"]

    assert r["confirmados"] == 2
    assert r["rejeitados"] == 1
    assert r["pendentes"] == 1
    # 1 rejeitado / 3 decididos — o pendente não conta
    assert r["taxa_rejeicao"] == pytest.approx(1 / 3, abs=0.01)


def test_metricas_sem_eventos_nao_quebra(ambiente):
    cliente, _, _ = ambiente
    dados = cliente.get("/v1/metricas", headers=como(TOKEN_OPERADOR)).json()
    assert dados["rejeicao"]["taxa_rejeicao"] is None
    assert dados["por_dia"] == []


def test_metricas_nao_inventa_custo(ambiente):
    """Sem números de custo fabricados: a economia é calculada pelo município."""
    cliente, _, _ = ambiente
    dados = cliente.get("/v1/metricas", headers=como(TOKEN_OPERADOR)).json()
    assert "custo" in dados["nota_custo"].lower()
    # não há nenhum campo numérico de custo/economia
    assert "economia" not in dados
    assert "custo_estimado" not in dados


# -- modo / configurações ----------------------------------------------


def test_modos_dos_nos_deixa_autuacao_bloqueada(ambiente):
    cliente, conexao, tmp_path = ambiente
    ingerir_e_confirmar(cliente, tmp_path, "e1", 1_770_007_200.0, confirmar=None)

    dados = cliente.get("/v1/nos/modos", headers=como(TOKEN_OPERADOR)).json()

    assert dados["autuacao_liberada"] is False
    assert "inmetro" in dados["motivo_autuacao_bloqueada"].lower()
    assert dados["nos"][0]["modo"] == "triagem"


# -- exportação --------------------------------------------------------


def test_relatorio_de_priorizacao_e_html_imprimivel(ambiente):
    cliente, conexao, tmp_path = ambiente
    ingerir_e_confirmar(cliente, tmp_path, "e1", 1_770_007_200.0, confirmar=True)

    resposta = cliente.get("/v1/priorizacao/relatorio", headers=como(TOKEN_OPERADOR))

    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]
    corpo = resposta.text.lower()
    assert "relatório de priorização" in corpo
    assert "não constitui auto de infração" in corpo
    assert "não tem valor legal" in corpo


def test_versoes_de_modelo_vem_dos_eventos(ambiente):
    cliente, conexao, tmp_path = ambiente
    ingerir_e_confirmar(cliente, tmp_path, "e1", 1_770_007_200.0, confirmar=None)

    dados = cliente.get("/v1/modelo/versoes", headers=como(TOKEN_ADMIN)).json()
    assert any("heuristico" in v["versao"] for v in dados["versoes"])
    assert "etapa 9" in dados["observacao"]
