"""Portão de acesso e marca da demonstração (scripts/montar_demo.py).

Não substitui verificação em navegador (o portão depende de crypto.subtle e
sessionStorage, que não existem fora de um navegador de verdade) — cobre a
parte que dá para travar sem um: a página nunca deve conter a senha em texto
claro, e as peças que blindam o conteúdo real precisam estar presentes.
"""

from datetime import datetime, timedelta, timezone

import pytest

from scripts.montar_demo import RAIZ

pytestmark = pytest.mark.skipif(
    not (RAIZ / "demo" / "dados-demo.js").exists(),
    reason="demo/dados-demo.js não existe — rode scripts/exportar_demo antes",
)


@pytest.fixture
def montar():
    from scripts import montar_demo

    return montar_demo


def _janela(dias=3):
    inicio = datetime.now(tz=timezone.utc)
    return inicio, inicio + timedelta(days=dias)


def test_senha_em_texto_claro_nao_aparece_na_pagina(montar):
    inicio, expira = _janela()
    pagina = montar.montar(
        standalone=True,
        senha="segredo-de-teste-123",
        inicio_em=inicio,
        expira_em=expira,
        minificar=False,
    )

    assert "segredo-de-teste-123" not in pagina


def test_hash_da_senha_aparece_no_lugar_do_texto(montar):
    import hashlib

    inicio, expira = _janela()
    pagina = montar.montar(
        standalone=True,
        senha="segredo-de-teste-123",
        inicio_em=inicio,
        expira_em=expira,
        minificar=False,
    )

    hash_esperado = hashlib.sha256(b"segredo-de-teste-123").hexdigest()
    assert hash_esperado in pagina


def test_conteudo_real_fica_escondido_ate_o_portao_liberar(montar):
    inicio, expira = _janela()
    pagina = montar.montar(
        standalone=True, senha="x", inicio_em=inicio, expira_em=expira, minificar=False
    )

    assert 'id="portao"' not in pagina  # o portão é montado via JS, não no HTML estático
    assert "body:not(.portao-liberado) #acesso" in pagina
    assert "body:not(.portao-liberado) #painel" in pagina


def test_inicio_e_expiracao_vao_para_a_pagina_em_utc(montar):
    inicio, expira = _janela()
    pagina = montar.montar(
        standalone=True, senha="x", inicio_em=inicio, expira_em=expira, minificar=False
    )

    assert inicio.isoformat() in pagina
    assert expira.isoformat() in pagina


def test_portao_avisa_que_e_demonstracao_com_dados_ficticios(montar):
    """Quem recebe o link precisa saber, antes de digitar a senha, que é uma
    página estática de demonstração e que nada ali é dado real."""
    inicio, expira = _janela()
    pagina = montar.montar(
        standalone=True, senha="x", inicio_em=inicio, expira_em=expira, minificar=False
    )

    assert "aviso-portao" in pagina
    assert "dados fictícios" in pagina.lower() or "dados ficticios" in pagina.lower()
    assert "demonstra" in pagina.lower()


def test_marca_ecoar_aparece_no_rodape(montar):
    inicio, expira = _janela()
    pagina = montar.montar(
        standalone=True, senha="x", inicio_em=inicio, expira_em=expira, minificar=False
    )

    assert "ECOAR" in pagina
    assert "rodape-marca" in pagina
    assert "confidencial" in pagina.lower()


def test_senha_padrao_nao_e_trivial_demais():
    from scripts import montar_demo

    assert len(montar_demo.SENHA_PADRAO) >= 8


def test_validade_padrao_e_de_poucos_dias():
    from scripts import montar_demo

    assert 1 <= montar_demo.VALIDADE_DIAS_PADRAO <= 7


def test_inicio_no_horario_de_brasilia_converte_para_utc_corretamente():
    from scripts.montar_demo import _parse_inicio

    inicio = _parse_inicio("2026-08-19T08:00")

    # 08:00 em Brasília (UTC-3, sem horário de verão desde 2019) é 11:00 UTC.
    assert inicio.astimezone(timezone.utc).isoformat() == "2026-08-19T11:00:00+00:00"


def _tem_ferramentas_de_minificacao():
    import shutil

    return shutil.which("npx") is not None


@pytest.mark.skipif(
    not _tem_ferramentas_de_minificacao(),
    reason="npx não disponível — sem como baixar terser/clean-css-cli",
)
def test_versao_minificada_mantem_as_pecas_criticas_do_portao(montar):
    """A minificação (terser/clean-css) não pode apagar nem embaralhar o que o
    portão depende: hash da senha, janela de validade e as regras de CSS que
    escondem o conteúdo real até a liberação."""
    import hashlib

    inicio, expira = _janela()
    pagina = montar.montar(
        standalone=True,
        senha="segredo-de-teste-123",
        inicio_em=inicio,
        expira_em=expira,
        minificar=True,
    )

    assert "segredo-de-teste-123" not in pagina
    assert hashlib.sha256(b"segredo-de-teste-123").hexdigest() in pagina
    assert inicio.isoformat() in pagina
    assert expira.isoformat() in pagina
    assert "body:not(.portao-liberado) #acesso" in pagina
    assert "aviso-portao" in pagina
    assert "ECOAR" in pagina
    assert "confidencial" in pagina.lower()

    pagina_sem_minificar = montar.montar(
        standalone=True,
        senha="segredo-de-teste-123",
        inicio_em=inicio,
        expira_em=expira,
        minificar=False,
    )
    assert len(pagina) < len(pagina_sem_minificar)
