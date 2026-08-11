"""Ingestão: o hash é revalidado aqui, e todo evento entra pendente de revisão."""

import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.aplicacao import criar_app
from backend.config import ConfigBackend
from edge.config import ConfiguracaoInvalida
from edge.evidence_packager import NOME_MANIFESTO, canonico
from tests.conftest_backend import gerar_pacote

TOKEN_NO = "token-do-no-de-teste-0123456789"
TOKEN_OUTRO = "token-de-outro-no-0123456789abc"


@pytest.fixture
def ambiente(tmp_path):
    config = ConfigBackend(
        banco=tmp_path / "ecoar.db",
        armazenamento=tmp_path / "pacotes",
        tokens={"no-teste-01": TOKEN_NO, "no-teste-02": TOKEN_OUTRO},
        tokens_operador={"operador-teste": "token-operador-0123456789abcd"},
    )
    app = criar_app(config)
    with TestClient(app) as cliente:
        yield cliente, app.state.conexao, tmp_path


def enviar(cliente, caminho, token=TOKEN_NO):
    with open(caminho, "rb") as arquivo:
        return cliente.post(
            "/v1/eventos",
            files={"pacote": (caminho.name, arquivo, "application/octet-stream")},
            headers={"Authorization": f"Bearer {token}"},
        )


# -- caminho feliz -----------------------------------------------------


def test_evento_valido_e_aceito_como_pendente_de_revisao(ambiente):
    cliente, conexao, tmp_path = ambiente
    pacote = gerar_pacote(tmp_path / "evt.ecoar")

    resposta = enviar(cliente, pacote)

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["status"] == "recebido"
    assert corpo["situacao"] == db.STATUS_PENDENTE

    linha = db.buscar_evento(conexao, corpo["id"])
    assert linha["status"] == db.STATUS_PENDENTE
    assert linha["no_id"] == "no-teste-01"
    assert linha["classe"] == "escapamento_adulterado"
    assert linha["acao"] == "acionar"
    assert linha["n_imagens"] == 2


def test_pacote_e_guardado_por_data_e_no(ambiente):
    cliente, conexao, tmp_path = ambiente
    pacote = gerar_pacote(tmp_path / "evt.ecoar")

    identificador = enviar(cliente, pacote).json()["id"]
    guardado = db.buscar_evento(conexao, identificador)["caminho_pacote"]

    partes = guardado.split("/")
    assert "no-teste-01" in partes
    assert partes[-1] == "evt-0001.ecoar"
    assert len(partes[-5]) == 4, "esperava AAAA/MM/DD na estrutura de pastas"


def test_no_e_registrado_com_a_geolocalizacao_do_manifesto(ambiente):
    cliente, conexao, tmp_path = ambiente
    enviar(cliente, gerar_pacote(tmp_path / "evt.ecoar"))

    nos = db.listar_nos(conexao)
    assert len(nos) == 1
    assert nos[0]["no_id"] == "no-teste-01"
    assert nos[0]["latitude"] == pytest.approx(-22.31)
    assert nos[0]["pendentes"] == 1


def test_evento_ambiguo_tambem_entra_na_fila(ambiente):
    cliente, conexao, tmp_path = ambiente
    pacote = gerar_pacote(tmp_path / "amb.ecoar", evento_id="evt-amb", score=0.60)

    identificador = enviar(cliente, pacote).json()["id"]
    linha = db.buscar_evento(conexao, identificador)

    assert linha["acao"] == "ambiguo"
    assert linha["status"] == db.STATUS_PENDENTE
    assert linha["n_imagens"] == 0


# -- integridade -------------------------------------------------------


def test_pacote_adulterado_e_recusado_e_a_recusa_fica_registrada(ambiente):
    cliente, conexao, tmp_path = ambiente
    pacote = gerar_pacote(tmp_path / "evt.ecoar")

    with zipfile.ZipFile(pacote) as origem:
        conteudo = {nome: origem.read(nome) for nome in origem.namelist()}
    manifesto = json.loads(conteudo[NOME_MANIFESTO])
    manifesto["classificacao"]["score_alvo"] = 0.99
    conteudo[NOME_MANIFESTO] = canonico(manifesto)

    adulterado = tmp_path / "adulterado.ecoar"
    with zipfile.ZipFile(adulterado, "w") as saida:
        for nome, dados in conteudo.items():
            saida.writestr(nome, dados)

    resposta = enviar(cliente, adulterado)

    assert resposta.status_code == 422
    assert "não íntegro" in resposta.json()["detail"]["erro"]

    rejeicoes = list(conexao.execute("SELECT * FROM rejeicoes"))
    assert len(rejeicoes) == 1
    assert "hash do manifesto" in rejeicoes[0]["motivo"]
    assert list(conexao.execute("SELECT COUNT(*) c FROM eventos"))[0]["c"] == 0


def test_arquivo_que_nao_e_pacote_e_recusado(ambiente):
    cliente, conexao, tmp_path = ambiente
    lixo = tmp_path / "lixo.ecoar"
    lixo.write_bytes(b"isto nao e um zip")

    assert enviar(cliente, lixo).status_code == 422
    assert list(conexao.execute("SELECT COUNT(*) c FROM rejeicoes"))[0]["c"] == 1


def test_no_nao_pode_enviar_evento_em_nome_de_outro(ambiente):
    """O token autentica um nó; o manifesto declara outro. Recusado."""
    cliente, conexao, tmp_path = ambiente
    pacote = gerar_pacote(tmp_path / "evt.ecoar", no_id="no-teste-01")

    resposta = enviar(cliente, pacote, token=TOKEN_OUTRO)

    assert resposta.status_code == 403
    assert "manifesto declara" in resposta.json()["detail"]
    assert list(conexao.execute("SELECT COUNT(*) c FROM eventos"))[0]["c"] == 0


# -- autenticação ------------------------------------------------------


def test_sem_token_nao_entra(ambiente):
    cliente, _, tmp_path = ambiente
    pacote = gerar_pacote(tmp_path / "evt.ecoar")

    with open(pacote, "rb") as arquivo:
        resposta = cliente.post("/v1/eventos", files={"pacote": ("e.ecoar", arquivo)})

    assert resposta.status_code == 401


def test_token_invalido_nao_entra(ambiente):
    cliente, _, tmp_path = ambiente
    resposta = enviar(cliente, gerar_pacote(tmp_path / "evt.ecoar"), token="errado")
    assert resposta.status_code == 401


# -- reenvio -----------------------------------------------------------


def test_reenvio_do_mesmo_evento_e_idempotente(ambiente):
    """O nó só apaga o pacote depois da confirmação; se ela se perder, reenvia.

    Reenvio não pode virar evento duplicado na fila do operador.
    """
    cliente, conexao, tmp_path = ambiente
    pacote = gerar_pacote(tmp_path / "evt.ecoar")

    primeira = enviar(cliente, pacote)
    segunda = enviar(cliente, pacote)

    assert primeira.json()["status"] == "recebido"
    assert segunda.json()["status"] == "ja_recebido"
    assert segunda.json()["id"] == primeira.json()["id"]
    assert list(conexao.execute("SELECT COUNT(*) c FROM eventos"))[0]["c"] == 1


def test_eventos_diferentes_do_mesmo_no_convivem(ambiente):
    cliente, conexao, tmp_path = ambiente
    enviar(cliente, gerar_pacote(tmp_path / "a.ecoar", evento_id="evt-a"))
    enviar(cliente, gerar_pacote(tmp_path / "b.ecoar", evento_id="evt-b"))

    assert list(conexao.execute("SELECT COUNT(*) c FROM eventos"))[0]["c"] == 2


# -- heartbeat e saúde -------------------------------------------------


def test_heartbeat_atualiza_o_no(ambiente):
    cliente, conexao, _ = ambiente

    resposta = cliente.post(
        "/v1/heartbeat",
        json={"bateria_pct": 87.5, "detalhe": {"blocos_lidos": 1200}},
        headers={"Authorization": f"Bearer {TOKEN_NO}"},
    )

    assert resposta.status_code == 202
    no = db.listar_nos(conexao)[0]
    assert no["bateria_pct"] == pytest.approx(87.5)
    assert no["ultimo_heartbeat"] is not None


def test_saude_resume_a_fila(ambiente):
    cliente, _, tmp_path = ambiente
    enviar(cliente, gerar_pacote(tmp_path / "evt.ecoar"))

    corpo = cliente.get("/v1/saude").json()

    assert corpo["status"] == "ok"
    assert corpo["eventos"][db.STATUS_PENDENTE] == 1
    assert corpo["eventos"][db.STATUS_CONFIRMADO] == 0


# -- banco e configuração ----------------------------------------------


def test_migracoes_sao_idempotentes(tmp_path):
    conexao = db.conectar(tmp_path / "x.db")
    assert db.aplicar_migracoes(conexao) == []


def test_inserir_evento_ignora_status_forcado(tmp_path):
    """Não existe caminho de código que crie um evento já confirmado (D2)."""
    conexao = db.conectar(tmp_path / "x.db")
    db.registrar_no(conexao, "no-1")

    identificador = db.inserir_evento(
        conexao,
        {
            "evento_id": "e1",
            "no_id": "no-1",
            "status": db.STATUS_CONFIRMADO,  # tentativa de burlar
            "modo": "triagem",
            "recebido_em": "2026-08-17T00:00:00Z",
            "capturado_em": "2026-08-17T00:00:00Z",
            "instante_pico_epoch": 1.0,
            "acao": "acionar",
            "versao_politica": "politica/1.0",
            "hash_manifesto": "sha256:x",
            "caminho_pacote": "/tmp/x.ecoar",
        },
    )

    assert db.buscar_evento(conexao, identificador)["status"] == db.STATUS_PENDENTE


def test_backend_sem_token_de_no_e_recusado():
    with pytest.raises(ConfiguracaoInvalida, match="nenhum nó poderia enviar"):
        ConfigBackend(tokens={}).validar()


def test_token_curto_e_recusado():
    with pytest.raises(ConfiguracaoInvalida, match="curto demais"):
        ConfigBackend(tokens={"no-1": "curto"}).validar()


def test_identificador_de_no_nao_escapa_do_diretorio(tmp_path):
    from backend.armazenamento import Armazenamento

    armazenamento = Armazenamento(raiz=tmp_path)
    caminho = armazenamento.caminho_de("../../etc", "../passwd", 1_770_000_000.0)

    assert ".." not in str(caminho)
    assert str(caminho).startswith(str(tmp_path))
