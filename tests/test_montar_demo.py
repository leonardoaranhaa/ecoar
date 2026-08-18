"""Portão de acesso e marca da demonstração (scripts/montar_demo.py).

Não substitui verificação em navegador (o portão depende de crypto.subtle e
sessionStorage, que não existem fora de um navegador de verdade) — cobre a
parte que dá para travar sem um: a página nunca deve conter a senha em texto
claro, e as peças que blindam o conteúdo real precisam estar presentes.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not (RAIZ / "demo" / "dados-demo.js").exists(),
    reason="demo/dados-demo.js não existe — rode scripts/exportar_demo antes",
)


@pytest.fixture
def montar():
    import sys

    sys.path.insert(0, str(RAIZ))
    from scripts import montar_demo

    return montar_demo


def test_senha_em_texto_claro_nao_aparece_na_pagina(montar):
    expira = datetime.now(tz=timezone.utc) + timedelta(days=3)
    pagina = montar.montar(standalone=True, senha="segredo-de-teste-123", expira_em=expira)

    assert "segredo-de-teste-123" not in pagina


def test_hash_da_senha_aparece_no_lugar_do_texto(montar):
    import hashlib

    expira = datetime.now(tz=timezone.utc) + timedelta(days=3)
    pagina = montar.montar(standalone=True, senha="segredo-de-teste-123", expira_em=expira)

    hash_esperado = hashlib.sha256(b"segredo-de-teste-123").hexdigest()
    assert hash_esperado in pagina


def test_conteudo_real_fica_escondido_ate_o_portao_liberar(montar):
    expira = datetime.now(tz=timezone.utc) + timedelta(days=3)
    pagina = montar.montar(standalone=True, senha="x", expira_em=expira)

    assert 'id="portao"' not in pagina  # o portão é montado via JS, não no HTML estático
    assert "body:not(.portao-liberado) #acesso" in pagina
    assert "body:not(.portao-liberado) #painel" in pagina


def test_data_de_expiracao_vai_para_a_pagina_em_utc(montar):
    expira = datetime.now(tz=timezone.utc) + timedelta(days=3)
    pagina = montar.montar(standalone=True, senha="x", expira_em=expira)

    assert expira.isoformat() in pagina


def test_marca_ecoar_aparece_no_rodape(montar):
    expira = datetime.now(tz=timezone.utc) + timedelta(days=3)
    pagina = montar.montar(standalone=True, senha="x", expira_em=expira)

    assert "ECOAR" in pagina
    assert "rodape-marca" in pagina
    assert "confidencial" in pagina.lower()


def test_senha_padrao_nao_e_trivial_demais():
    from scripts import montar_demo

    assert len(montar_demo.SENHA_PADRAO) >= 8


def test_validade_padrao_e_de_poucos_dias():
    from scripts import montar_demo

    assert 1 <= montar_demo.VALIDADE_DIAS_PADRAO <= 7
