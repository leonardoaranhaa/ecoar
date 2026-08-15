"""Fila de revisão humana: a etapa que o desenho inteiro protege (D2)."""

import wave
import io

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.aplicacao import criar_app
from backend.config import ConfigBackend
from tests.conftest_backend import config_no, gerar_pacote

TOKEN_NO = "token-do-no-de-teste-0123456789"
TOKEN_OPERADOR = "token-operador-0123456789abcd"
TOKEN_ADMIN = "token-admin-0123456789abcdefgh"


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


def como_operador(token=TOKEN_OPERADOR):
    return {"Authorization": f"Bearer {token}"}


def ingerir(cliente, tmp_path, evento_id="evt-0001", **extras):
    pacote = gerar_pacote(tmp_path / f"{evento_id}.ecoar", evento_id=evento_id, **extras)
    with open(pacote, "rb") as arquivo:
        resposta = cliente.post(
            "/v1/eventos",
            files={"pacote": (pacote.name, arquivo)},
            headers={"Authorization": f"Bearer {TOKEN_NO}"},
        )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["id"]


# -- listagem ----------------------------------------------------------


def test_fila_lista_apenas_pendentes_quando_filtrada(ambiente):
    cliente, _, tmp_path = ambiente
    primeiro = ingerir(cliente, tmp_path, "evt-a")
    ingerir(cliente, tmp_path, "evt-b")

    cliente.post(
        f"/v1/eventos/{primeiro}/revisao",
        json={"decisao": "rejeitar"},
        headers=como_operador(),
    )

    fila = cliente.get("/v1/eventos?status=pendente_revisao", headers=como_operador()).json()

    assert fila["total"] == 1
    assert fila["eventos"][0]["evento_id"] == "evt-b"
    assert fila["contagem"]["rejeitado"] == 1


def test_listagem_exige_token_de_operador(ambiente):
    cliente, _, _ = ambiente
    assert cliente.get("/v1/eventos").status_code == 401
    assert cliente.get("/v1/eventos", headers={"Authorization": f"Bearer {TOKEN_NO}"}).status_code == 401


def test_status_invalido_e_recusado(ambiente):
    cliente, _, _ = ambiente
    resposta = cliente.get("/v1/eventos?status=inventado", headers=como_operador())
    assert resposta.status_code == 400


# -- detalhe -----------------------------------------------------------


def test_detalhe_traz_o_manifesto_inteiro(ambiente):
    cliente, _, tmp_path = ambiente
    identificador = ingerir(cliente, tmp_path)

    detalhe = cliente.get(f"/v1/eventos/{identificador}", headers=como_operador()).json()

    assert detalhe["manifesto"]["evento_id"] == "evt-0001"
    assert detalhe["manifesto"]["decisao"]["regras"], "o operador precisa ver por quê"
    assert detalhe["manifesto"]["spl_estimado"]["valor_legal"] is False
    assert detalhe["revisoes"] == []


def test_evento_inexistente_devolve_404(ambiente):
    cliente, _, _ = ambiente
    assert cliente.get("/v1/eventos/999", headers=como_operador()).status_code == 404


# -- decisão -----------------------------------------------------------


def test_confirmar_muda_status_e_registra_quem_decidiu(ambiente):
    cliente, conexao, tmp_path = ambiente
    identificador = ingerir(cliente, tmp_path)

    resposta = cliente.post(
        f"/v1/eventos/{identificador}/revisao",
        json={"decisao": "confirmar", "observacao": "moto com escapamento cortado"},
        headers=como_operador(),
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == db.STATUS_CONFIRMADO

    linha = db.buscar_evento(conexao, identificador)
    assert linha["status"] == db.STATUS_CONFIRMADO

    revisoes = db.listar_revisoes(conexao, identificador)
    assert len(revisoes) == 1
    assert revisoes[0]["operador"] == "operador-teste"
    assert "escapamento cortado" in revisoes[0]["observacao"]


def test_rejeitar_muda_status(ambiente):
    cliente, conexao, tmp_path = ambiente
    identificador = ingerir(cliente, tmp_path)

    cliente.post(
        f"/v1/eventos/{identificador}/revisao",
        json={"decisao": "rejeitar", "observacao": "era ônibus"},
        headers=como_operador(),
    )

    assert db.buscar_evento(conexao, identificador)["status"] == db.STATUS_REJEITADO


def test_evento_de_triagem_nao_pode_virar_multa(ambiente):
    """Trava de modo: o evento carrega o modo vigente na captura.

    Sem isso, um evento capturado hoje poderia ser reclassificado como autuação
    depois que o modo mudasse — e a evidência não sustentaria isso.
    """
    cliente, conexao, tmp_path = ambiente
    identificador = ingerir(cliente, tmp_path)

    resposta = cliente.post(
        f"/v1/eventos/{identificador}/revisao",
        json={"decisao": "confirmar_multa"},
        headers=como_operador(TOKEN_ADMIN),
    )

    assert resposta.status_code == 409
    assert "triagem" in resposta.json()["detail"]
    assert db.buscar_evento(conexao, identificador)["status"] == db.STATUS_PENDENTE


def test_correcao_e_nova_revisao_e_o_historico_fica_inteiro(ambiente):
    cliente, conexao, tmp_path = ambiente
    identificador = ingerir(cliente, tmp_path)

    cliente.post(
        f"/v1/eventos/{identificador}/revisao",
        json={"decisao": "confirmar"},
        headers=como_operador(),
    )
    cliente.post(
        f"/v1/eventos/{identificador}/revisao",
        json={"decisao": "rejeitar", "observacao": "revisto: era buzina"},
        headers=como_operador(TOKEN_ADMIN),
    )

    assert db.buscar_evento(conexao, identificador)["status"] == db.STATUS_REJEITADO
    revisoes = db.listar_revisoes(conexao, identificador)
    assert [r["decisao"] for r in revisoes] == ["confirmar", "rejeitar"]
    assert [r["operador"] for r in revisoes] == ["operador-teste", "admin-teste"]


def test_decisao_invalida_e_recusada(ambiente):
    cliente, _, tmp_path = ambiente
    identificador = ingerir(cliente, tmp_path)

    resposta = cliente.post(
        f"/v1/eventos/{identificador}/revisao",
        json={"decisao": "arquivar"},
        headers=como_operador(),
    )

    assert resposta.status_code == 422


# -- mídia -------------------------------------------------------------


def test_imagem_e_servida_de_dentro_do_pacote(ambiente):
    cliente, _, tmp_path = ambiente
    identificador = ingerir(cliente, tmp_path)

    resposta = cliente.get(
        f"/v1/eventos/{identificador}/midia/placa.png", headers=como_operador()
    )

    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "image/png"
    assert resposta.content.startswith(b"\x89PNG")


def test_midia_nao_declarada_no_manifesto_e_recusada(ambiente):
    """O nome vem da URL: aceitar qualquer um deixaria a URL escolher o arquivo."""
    cliente, _, tmp_path = ambiente
    identificador = ingerir(cliente, tmp_path)

    for nome in ("../evento.json", "evento.json", "qualquer.png"):
        resposta = cliente.get(
            f"/v1/eventos/{identificador}/midia/{nome}", headers=como_operador()
        )
        assert resposta.status_code == 404, nome


def test_audio_de_audicao_e_mono_16_bits(ambiente):
    cliente, _, tmp_path = ambiente
    identificador = ingerir(cliente, tmp_path)

    resposta = cliente.get(
        f"/v1/eventos/{identificador}/audio-audicao.wav", headers=como_operador()
    )

    assert resposta.status_code == 200
    with wave.open(io.BytesIO(resposta.content), "rb") as arquivo:
        assert arquivo.getnchannels() == 1
        assert arquivo.getsampwidth() == 2
        assert arquivo.getnframes() > 0


def test_ouvir_audio_de_audicao_tambem_registra_acesso_a_evidencia(ambiente):
    """A conversão para audição lê o áudio original de dentro do pacote — o
    mesmo tipo de acesso que /midia/{nome} já registra na trilha."""
    from backend.audit_log import ACESSO_EVIDENCIA, TrilhaAuditoria

    cliente, conexao, tmp_path = ambiente
    identificador = ingerir(cliente, tmp_path)

    cliente.get(
        f"/v1/eventos/{identificador}/audio-audicao.wav", headers=como_operador()
    )

    entradas = TrilhaAuditoria(conexao).listar()
    acessos = [e for e in entradas if e.tipo == ACESSO_EVIDENCIA]
    assert len(acessos) == 1
    assert acessos[0].detalhe["midia"] == "audio-audicao.wav"


def test_audio_da_evidencia_continua_de_quatro_canais(ambiente):
    """A conversão para audição não substitui a evidência."""
    cliente, _, tmp_path = ambiente
    identificador = ingerir(cliente, tmp_path)

    resposta = cliente.get(
        f"/v1/eventos/{identificador}/midia/audio.wav", headers=como_operador()
    )

    with wave.open(io.BytesIO(resposta.content), "rb") as arquivo:
        assert arquivo.getnchannels() == 4
        assert arquivo.getsampwidth() == 3


# -- nós ---------------------------------------------------------------


def test_lista_de_nos_mostra_pendencia_e_bateria(ambiente):
    cliente, _, tmp_path = ambiente
    ingerir(cliente, tmp_path)
    cliente.post(
        "/v1/heartbeat",
        json={"bateria_pct": 64.0},
        headers={"Authorization": f"Bearer {TOKEN_NO}"},
    )

    nos = cliente.get("/v1/nos", headers=como_operador()).json()["nos"]

    assert len(nos) == 1
    assert nos[0]["pendentes"] == 1
    assert nos[0]["bateria_pct"] == pytest.approx(64.0)
    assert nos[0]["ultimo_heartbeat"]


# -- painel ------------------------------------------------------------


def test_painel_e_servido_na_raiz(ambiente):
    cliente, _, _ = ambiente
    resposta = cliente.get("/")

    assert resposta.status_code == 200
    assert "ECOAR" in resposta.text


def test_painel_nao_engole_as_rotas_da_api(ambiente):
    cliente, _, _ = ambiente
    assert cliente.get("/v1/saude").json()["status"] == "ok"
