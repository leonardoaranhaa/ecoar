"""A camada de adaptação do instrumento — decisão D5, docs/legal/inmetro.md."""

import pytest

from edge.audio_capture.sonometro import (
    InstrumentoIndisponivel,
    SonometroAusente,
    SonometroMock,
    SonometroReader,
    criar_sonometro,
)
from edge.config import de_dict
from tests.conftest import config_base
from tests.test_config import BLOCO_AUTUACAO, INSTRUMENTO_CLASSE_1


def test_ausente_falha_em_vez_de_inventar_valor():
    leitor = SonometroAusente()

    assert leitor.info().valor_legal is False
    with pytest.raises(InstrumentoIndisponivel, match="nenhum instrumento"):
        leitor.ler_db()


def test_mock_devolve_a_sequencia_configurada():
    leitor = SonometroMock(valores=[71.2, 68.4, 90.1])

    assert [leitor.ler_db().db for _ in range(4)] == [71.2, 68.4, 90.1, 71.2]


def test_mock_nunca_tem_valor_legal():
    assert SonometroMock().ler_db().valor_legal is False


def test_triagem_aceita_instrumento_ausente():
    leitor = criar_sonometro(de_dict(config_base()))
    assert isinstance(leitor, SonometroAusente)


def test_autuacao_recusa_instrumento_simulado_mesmo_sem_o_carregador():
    """A trava vale mesmo se alguém montar a configuração na mão."""
    from dataclasses import replace

    config = de_dict(config_base())
    config_burlada = replace(config, modo="autuacao")

    with pytest.raises(InstrumentoIndisponivel, match="valor legal"):
        criar_sonometro(config_burlada)


def test_autuacao_aceita_instrumento_classe_1_declarado():
    dados = config_base()
    dados["modo"] = "autuacao"
    dados["sonometro"] = dict(INSTRUMENTO_CLASSE_1)
    dados["autuacao"] = BLOCO_AUTUACAO

    leitor = criar_sonometro(de_dict(dados))

    assert leitor.info().valor_legal is True
    assert leitor.info().classe == 1


def test_leitura_carrega_a_identificacao_do_instrumento():
    leitura = SonometroMock(valores=[80.0]).ler_db()
    dados = leitura.como_dict()

    assert dados["db"] == 80.0
    assert dados["valor_legal"] is False
    assert dados["instrumento"]["tipo"] == "mock"


def test_instrumento_novo_so_precisa_implementar_a_interface():
    """Prova executável de que trocar de modelo não toca em mais nada."""

    class SonometroDeFabricanteNovo(SonometroReader):
        def info(self):
            from edge.audio_capture.sonometro import InfoInstrumento

            return InfoInstrumento(tipo="rede", modelo="NMT-XYZ", classe=1, valor_legal=True)

        def _ler(self):
            return 83.7

    leitura = SonometroDeFabricanteNovo().ler_db()

    assert leitura.db == 83.7
    assert leitura.valor_legal is True
