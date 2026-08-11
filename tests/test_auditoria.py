"""Trilha de auditoria: qualquer adulteração do histórico é detectável."""

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.aplicacao import criar_app
from backend.audit_log import (
    ACESSO_EVIDENCIA,
    EVENTO_RECEBIDO,
    EVENTO_REJEITADO,
    REVISAO,
    TrilhaAuditoria,
)
from backend.config import ConfigBackend
from tests.conftest_backend import gerar_pacote

TOKEN_NO = "token-do-no-auditoria-0123456789"
TOKEN_OPERADOR = "token-operador-auditoria-012345"
TOKEN_ADMIN = "token-admin-auditoria-0123456789"


@pytest.fixture
def trilha(tmp_path):
    conexao = db.conectar(tmp_path / "ecoar.db")
    return TrilhaAuditoria(conexao), conexao


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


# -- hash-chain --------------------------------------------------------


def test_cadeia_vazia_e_integra(trilha):
    tr, _ = trilha
    relatorio = tr.verificar()
    assert relatorio.integra
    assert relatorio.total == 0


def test_entradas_encadeiam_uma_na_outra(trilha):
    tr, _ = trilha
    primeira = tr.registrar(EVENTO_RECEBIDO, ator="no-1", evento_id="e1")
    segunda = tr.registrar(REVISAO, ator="op-1", evento_id="e1")

    from backend.audit_log import GENESE

    assert primeira.hash_anterior == GENESE
    assert segunda.hash_anterior == primeira.hash
    assert tr.verificar().integra


def test_alterar_o_conteudo_de_uma_entrada_quebra_a_cadeia(trilha):
    tr, conexao = trilha
    tr.registrar(EVENTO_RECEBIDO, ator="no-1", evento_id="e1")
    tr.registrar(REVISAO, ator="op-1", evento_id="e1", detalhe={"decisao": "confirmar"})
    conexao.commit()

    # Alguém edita o banco por fora: muda uma decisão de rejeitar para confirmar.
    conexao.execute(
        "UPDATE auditoria SET detalhe = ? WHERE seq = 2",
        ('{"decisao":"rejeitar"}',),
    )
    conexao.commit()

    relatorio = tr.verificar()
    assert not relatorio.integra
    assert any("hash não confere" in p for p in relatorio.problemas)


def test_remover_uma_entrada_do_meio_e_detectado(trilha):
    tr, conexao = trilha
    for i in range(3):
        tr.registrar(EVENTO_RECEBIDO, ator="no-1", evento_id=f"e{i}")
    conexao.commit()

    conexao.execute("DELETE FROM auditoria WHERE seq = 2")
    conexao.commit()

    relatorio = tr.verificar()
    assert not relatorio.integra
    assert any("sequência" in p or "elo quebrado" in p for p in relatorio.problemas)


def test_reordenar_hashes_e_detectado(trilha):
    tr, conexao = trilha
    tr.registrar(EVENTO_RECEBIDO, ator="no-1", evento_id="e1")
    tr.registrar(EVENTO_RECEBIDO, ator="no-1", evento_id="e2")
    conexao.commit()

    # Troca o hash_anterior de uma entrada: o elo deixa de fechar.
    conexao.execute("UPDATE auditoria SET hash_anterior = 'sha256:falso' WHERE seq = 2")
    conexao.commit()

    assert not tr.verificar().integra


# -- conteúdo (D6) -----------------------------------------------------


def test_dado_pessoal_no_detalhe_e_recusado(trilha):
    tr, _ = trilha
    for proibido in ("placa", "numero_placa", "condutor", "cpf"):
        with pytest.raises(ValueError, match="não pode entrar"):
            tr.registrar(EVENTO_RECEBIDO, ator="no-1", detalhe={proibido: "ABC1D23"})


# -- integração com a ingestão e a revisão -----------------------------


def test_ingestao_e_revisao_alimentam_a_trilha(ambiente):
    cliente, conexao, tmp_path = ambiente
    pacote = gerar_pacote(tmp_path / "evt.ecoar")

    with open(pacote, "rb") as arquivo:
        identificador = cliente.post(
            "/v1/eventos", files={"pacote": (pacote.name, arquivo)}, headers=como(TOKEN_NO)
        ).json()["id"]

    cliente.post(
        f"/v1/eventos/{identificador}/revisao",
        json={"decisao": "confirmar"},
        headers=como(TOKEN_OPERADOR),
    )
    cliente.get(f"/v1/eventos/{identificador}/midia/placa.png", headers=como(TOKEN_OPERADOR))

    tr = TrilhaAuditoria(conexao)
    tipos = [entrada.tipo for entrada in tr.listar()]

    assert EVENTO_RECEBIDO in tipos
    assert REVISAO in tipos
    assert ACESSO_EVIDENCIA in tipos
    assert tr.verificar().integra


def test_pacote_rejeitado_entra_na_trilha(ambiente):
    cliente, conexao, tmp_path = ambiente
    lixo = tmp_path / "lixo.ecoar"
    lixo.write_bytes(b"nao e um zip")

    with open(lixo, "rb") as arquivo:
        resposta = cliente.post(
            "/v1/eventos", files={"pacote": (lixo.name, arquivo)}, headers=como(TOKEN_NO)
        )
    assert resposta.status_code == 422

    tr = TrilhaAuditoria(conexao)
    assert any(e.tipo == EVENTO_REJEITADO for e in tr.listar())


def test_evento_recebido_na_trilha_nao_carrega_placa(ambiente):
    """A trilha registra que o evento chegou, nunca a identificação do veículo."""
    import json

    cliente, conexao, tmp_path = ambiente
    pacote = gerar_pacote(tmp_path / "evt.ecoar")
    with open(pacote, "rb") as arquivo:
        cliente.post("/v1/eventos", files={"pacote": (pacote.name, arquivo)}, headers=como(TOKEN_NO))

    bruto = json.dumps([e.como_dict() for e in TrilhaAuditoria(conexao).listar()]).lower()
    for proibido in ("placa", "condutor", "cpf"):
        assert proibido not in bruto


# -- rotas -------------------------------------------------------------


def test_auditoria_e_restrita_a_admin(ambiente):
    cliente, _, _ = ambiente
    assert cliente.get("/v1/auditoria", headers=como(TOKEN_OPERADOR)).status_code == 403
    assert cliente.get("/v1/auditoria", headers=como(TOKEN_ADMIN)).status_code == 200


def test_endpoint_de_verificacao_confirma_integridade(ambiente):
    cliente, conexao, tmp_path = ambiente
    pacote = gerar_pacote(tmp_path / "evt.ecoar")
    with open(pacote, "rb") as arquivo:
        cliente.post("/v1/eventos", files={"pacote": (pacote.name, arquivo)}, headers=como(TOKEN_NO))

    corpo = cliente.get("/v1/auditoria/verificar", headers=como(TOKEN_ADMIN)).json()

    assert corpo["integra"] is True
    assert corpo["total"] >= 1


def test_endpoint_de_verificacao_denuncia_adulteracao(ambiente):
    cliente, conexao, tmp_path = ambiente
    pacote = gerar_pacote(tmp_path / "evt.ecoar")
    with open(pacote, "rb") as arquivo:
        cliente.post("/v1/eventos", files={"pacote": (pacote.name, arquivo)}, headers=como(TOKEN_NO))

    conexao.execute("UPDATE auditoria SET ator = 'outro' WHERE seq = 1")
    conexao.commit()

    corpo = cliente.get("/v1/auditoria/verificar", headers=como(TOKEN_ADMIN)).json()
    assert corpo["integra"] is False
    assert corpo["problemas"]
