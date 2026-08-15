"""Configuração do backend: fail-closed em tudo que a autenticação depende."""

from pathlib import Path

import pytest

from backend.config import ConfigBackend, de_dict
from edge.config import ConfiguracaoInvalida

TOKEN_A = "token-de-dezesseis-caracteres-a"
TOKEN_B = "token-de-dezesseis-caracteres-b"


def _base(**extra) -> dict:
    dados = {
        "tokens": {"no-01": TOKEN_A},
        "tokens_operador": {"operador-01": TOKEN_B},
    }
    dados.update(extra)
    return dados


def test_config_minima_valida():
    config = de_dict(_base())
    assert config.tokens == {"no-01": TOKEN_A}
    assert config.banco == Path("dados/ecoar.db")


def test_sem_nenhum_token_de_no_e_recusado():
    with pytest.raises(ConfiguracaoInvalida, match="tokens vazio"):
        de_dict(_base(tokens={}))


def test_token_de_no_curto_demais_e_recusado():
    with pytest.raises(ConfiguracaoInvalida, match="curto demais"):
        de_dict(_base(tokens={"no-01": "curto"}))


def test_token_de_operador_curto_demais_e_recusado():
    with pytest.raises(ConfiguracaoInvalida, match="curto demais"):
        de_dict(_base(tokens_operador={"operador-01": "curto"}))


def test_token_de_no_vazio_e_recusado():
    with pytest.raises(ConfiguracaoInvalida, match="curto demais"):
        de_dict(_base(tokens={"no-01": ""}))


def test_chave_desconhecida_e_recusada():
    with pytest.raises(ConfiguracaoInvalida, match="desconhecida"):
        de_dict(_base(chave_inventada=True))


# -- tokens duplicados ---------------------------------------------------
#
# Autenticação resolve um token para UM nome (backend/seguranca.py); dois
# nomes cadastrados no mesmo token nunca são distinguíveis um do outro. Para
# um operador, isso significaria uma revisão entrando na trilha de auditoria
# em nome de outra pessoa — um erro de copiar/colar no YAML não pode passar
# batido.


def test_dois_nos_com_o_mesmo_token_e_recusado():
    with pytest.raises(ConfiguracaoInvalida, match="tokens.*mesmo token"):
        de_dict(_base(tokens={"no-01": TOKEN_A, "no-02": TOKEN_A}))


def test_dois_operadores_com_o_mesmo_token_e_recusado():
    with pytest.raises(ConfiguracaoInvalida, match="tokens_operador.*mesmo token"):
        de_dict(
            _base(tokens_operador={"operador-01": TOKEN_B, "operador-02": TOKEN_B})
        )


def test_no_e_operador_podem_compartilhar_valor_de_token():
    """Domínios de autenticação diferentes (autenticar_no vs autenticar_operador):
    não há confusão de identidade possível entre os dois grupos."""
    config = de_dict(_base(tokens={"no-01": TOKEN_A}, tokens_operador={"operador-01": TOKEN_A}))
    assert config.tokens["no-01"] == config.tokens_operador["operador-01"]


def test_config_backend_direta_tambem_valida_duplicidade():
    with pytest.raises(ConfiguracaoInvalida, match="mesmo token"):
        ConfigBackend(tokens={"no-01": TOKEN_A, "no-02": TOKEN_A}).validar()
