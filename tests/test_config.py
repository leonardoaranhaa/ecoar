"""A configuração é a primeira trava do sistema: fail-closed, decisão D1/D8."""

import pytest

from edge.config import MODO_AUTUACAO, ConfiguracaoInvalida, de_dict
from tests.conftest import config_base

INSTRUMENTO_CLASSE_1 = {
    "tipo": "serial",
    "porta": "/dev/ttyUSB0",
    "modelo": "NMT Classe 1",
    "classe": 1,
    "certificado": "RBC-0000/2026",
    "validade_calibracao": "2027-08-01",
}

BLOCO_AUTUACAO = {
    "habilitada_por": "encarregado de dados do município",
    "base_normativa": "norma federal hipotética",
    "instrumento_certificado": {
        "modelo": "NMT Classe 1",
        "classe": 1,
        "certificado": "RBC-0000/2026",
        "validade_calibracao": "2027-08-01",
    },
}


def test_configuracao_minima_carrega_em_triagem():
    config = de_dict(config_base())
    assert config.em_triagem
    assert config.sonometro.tem_valor_legal is False


def test_id_do_no_e_obrigatorio():
    dados = config_base()
    dados["no"]["id"] = "  "
    with pytest.raises(ConfiguracaoInvalida, match="no.id"):
        de_dict(dados)


def test_canais_precisam_bater_com_numero_de_microfones():
    dados = config_base()
    dados["audio"]["canais"] = 2
    with pytest.raises(ConfiguracaoInvalida, match="difere de array.n_microfones"):
        de_dict(dados)


def test_chave_desconhecida_e_recusada_em_vez_de_ignorada():
    dados = config_base()
    dados["audio"]["bufer_segundos"] = 30
    with pytest.raises(ConfiguracaoInvalida, match="desconhecida"):
        de_dict(dados)


def test_autuacao_sem_bloco_de_declaracao_e_recusada():
    dados = config_base()
    dados["modo"] = MODO_AUTUACAO
    dados["sonometro"] = dict(INSTRUMENTO_CLASSE_1)
    with pytest.raises(ConfiguracaoInvalida, match="bloco 'autuacao'"):
        de_dict(dados)


def test_autuacao_com_instrumento_simulado_e_recusada():
    dados = config_base()
    dados["modo"] = MODO_AUTUACAO
    dados["sonometro"] = {"tipo": "mock"}
    dados["autuacao"] = BLOCO_AUTUACAO
    with pytest.raises(ConfiguracaoInvalida, match="SonometroReader real"):
        de_dict(dados)


def test_autuacao_com_instrumento_classe_2_e_recusada():
    dados = config_base()
    dados["modo"] = MODO_AUTUACAO
    dados["sonometro"] = {**INSTRUMENTO_CLASSE_1, "classe": 2}
    dados["autuacao"] = {
        **BLOCO_AUTUACAO,
        "instrumento_certificado": {
            **BLOCO_AUTUACAO["instrumento_certificado"],
            "classe": 2,
        },
    }
    with pytest.raises(ConfiguracaoInvalida, match="Classe 1"):
        de_dict(dados)


def test_autuacao_completa_carrega():
    dados = config_base()
    dados["modo"] = MODO_AUTUACAO
    dados["sonometro"] = dict(INSTRUMENTO_CLASSE_1)
    dados["autuacao"] = BLOCO_AUTUACAO

    config = de_dict(dados)

    assert config.modo == MODO_AUTUACAO
    assert config.sonometro.tem_valor_legal is True
    assert config.autuacao is not None
    assert config.autuacao.habilitada_por


def test_arquivo_de_exemplo_do_repositorio_e_valido():
    from edge.config import carregar

    config = carregar("config/no.exemplo.yaml")

    assert config.em_triagem, "o exemplo versionado nunca pode vir em modo de autuação"
    assert config.sonometro.tipo == "ausente"


def test_variavel_de_ambiente_com_padrao_e_expandida(monkeypatch):
    dados = config_base()
    dados["no"]["id"] = "${ECOAR_NO_ID:-no-de-fabrica}"
    assert de_dict(dados).id == "no-de-fabrica"

    monkeypatch.setenv("ECOAR_NO_ID", "bauru-centro-02")
    assert de_dict(dados).id == "bauru-centro-02"
