"""Cadeia de custódia: o pacote precisa denunciar qualquer alteração."""

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from edge.audio_capture.buffer import Janela
from edge.audio_capture.captura import JanelaEvento
from edge.audio_capture.sonometro import SonometroMock
from edge.audio_capture.spl import estimar
from edge.camera_trigger import AcionadorCamera
from edge.classifier.base import CLASSE_ALVO, CLASSES, Predicao
from edge.config import ConfigCalibracao, de_dict
from edge.evidence_packager import (
    CAMPO_HASH,
    NOME_MANIFESTO,
    canonico,
    ler_manifesto,
    montar_pacote,
    verificar_pacote,
)
from edge.evidence_packager.verificar import cli
from edge.localization.doa import EstimativaDOA
from tests.conftest import config_base

TAXA = 16000


def janela_evento(com_instrumento: bool = False) -> JanelaEvento:
    # Tom de 1 kHz a meia escala: com o offset de calibração padrão dá ~85 dB
    # estimados, acima do piso do nó. Um tom grave e fraco cairia como ambíguo
    # pela ponderação A, e o pacote sairia sem imagem.
    t = np.arange(TAXA * 2) / TAXA
    amostras = (0.5 * np.sin(2 * np.pi * 1000 * t))[:, None].repeat(4, axis=1).astype(np.float32)
    janela = Janela(amostras=amostras, taxa_amostragem=TAXA, inicio=1000.0, fim=1002.0)
    leitura = SonometroMock(valores=[81.4]).ler_db() if com_instrumento else None
    return JanelaEvento(
        janela=janela,
        spl=estimar(amostras, TAXA, ConfigCalibracao(referencia="campanha de teste")),
        instante_pico=1001.0,
        sonometro=leitura,
        motivo_sem_sonometro=None if com_instrumento else "sem instrumento configurado",
    )


def predicao_alvo(score: float = 0.93) -> Predicao:
    resto = (1.0 - score) / (len(CLASSES) - 1)
    scores = {c: resto for c in CLASSES}
    scores[CLASSE_ALVO] = score
    return Predicao(
        classe=CLASSE_ALVO,
        score=score,
        scores=scores,
        modelo="heuristico",
        versao_modelo="teste/1.0",
        explicacao="fundamental de motor, série harmônica forte",
        descritores={"f0_hz": 84.0},
    )


def doa_boa() -> EstimativaDOA:
    return EstimativaDOA(
        azimute_graus=12.0,
        confianca=0.95,
        margem_graus=2.0,
        residuo_us=3.1,
        qualidade_media=0.99,
        tdoas_us={"0-1": 120.0},
    )


@pytest.fixture
def pacote(tmp_path) -> Path:
    config = de_dict(config_base())
    evento = janela_evento(com_instrumento=True)
    acionador = AcionadorCamera(config, diretorio=tmp_path / "capturas")
    with acionador:
        acionamento = acionador.processar("evt-teste", predicao_alvo(), doa_boa(), evento.spl)

    return montar_pacote(
        config=config,
        evento_id="evt-teste",
        evento=evento,
        doa=doa_boa(),
        predicao=predicao_alvo(),
        acionamento=acionamento,
        destino=tmp_path / "evt-teste.ecoar",
    )


# -- conteúdo ----------------------------------------------------------


def test_pacote_recem_gerado_e_integro(pacote):
    relatorio = verificar_pacote(pacote)
    assert relatorio.valido, relatorio.problemas


def test_pacote_contem_audio_e_as_duas_imagens(pacote):
    with zipfile.ZipFile(pacote) as arquivo:
        nomes = set(arquivo.namelist())

    assert NOME_MANIFESTO in nomes
    assert "midia/audio.wav" in nomes
    assert "midia/placa.png" in nomes
    assert "midia/panoramica.png" in nomes


def test_manifesto_tem_tudo_que_a_evidencia_exige(pacote):
    manifesto = ler_manifesto(pacote)

    for campo in (
        "evento_id",
        "modo",
        "no",
        "capturado_em",
        "audio",
        "spl_estimado",
        "localizacao",
        "classificacao",
        "decisao",
        "imagens",
        "retencao",
        CAMPO_HASH,
    ):
        assert campo in manifesto, f"faltou {campo}"

    assert manifesto["decisao"]["versao_politica"]
    assert manifesto["classificacao"]["versao_modelo"]
    assert manifesto["localizacao"]["algoritmo"]


def test_spl_do_array_sai_marcado_como_sem_valor_legal(pacote):
    manifesto = ler_manifesto(pacote)
    assert manifesto["spl_estimado"]["valor_legal"] is False
    assert "sem valor legal" in manifesto["aviso_legal"]


def test_leitura_de_placa_e_negada_explicitamente(pacote):
    """A ausência é decisão de arquitetura (D10), não esquecimento."""
    manifesto = ler_manifesto(pacote)
    assert manifesto["leitura_de_placa"]["realizada"] is False
    assert "OCR" in manifesto["leitura_de_placa"]["motivo"]


def test_nenhum_texto_de_placa_no_manifesto(pacote):
    bruto = json.dumps(ler_manifesto(pacote), ensure_ascii=False).lower()
    for proibido in ("placa_lida", "numero_placa", "ocr_resultado"):
        assert proibido not in bruto


# -- integridade -------------------------------------------------------


def _reescrever(pacote: Path, destino: Path, mudanca) -> Path:
    """Reconstrói o zip aplicando uma alteração — simula adulteração."""
    with zipfile.ZipFile(pacote) as origem:
        conteudo = {nome: origem.read(nome) for nome in origem.namelist()}
    conteudo = mudanca(conteudo)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as saida:
        for nome, dados in conteudo.items():
            saida.writestr(nome, dados)
    return destino


def test_alterar_campo_do_manifesto_quebra_o_hash(pacote, tmp_path):
    def adulterar(conteudo):
        manifesto = json.loads(conteudo[NOME_MANIFESTO])
        manifesto["localizacao"]["azimute_graus"] = 999.0
        conteudo[NOME_MANIFESTO] = canonico(manifesto)
        return conteudo

    adulterado = _reescrever(pacote, tmp_path / "adulterado.ecoar", adulterar)
    relatorio = verificar_pacote(adulterado)

    assert not relatorio.valido
    assert any("hash do manifesto" in problema for problema in relatorio.problemas)


def test_alterar_um_byte_do_audio_quebra_a_verificacao(pacote, tmp_path):
    def adulterar(conteudo):
        audio = bytearray(conteudo["midia/audio.wav"])
        audio[-1] ^= 0xFF
        conteudo["midia/audio.wav"] = bytes(audio)
        return conteudo

    adulterado = _reescrever(pacote, tmp_path / "audio.ecoar", adulterar)
    relatorio = verificar_pacote(adulterado)

    assert not relatorio.valido
    assert any("audio.wav" in problema for problema in relatorio.problemas)


def test_trocar_a_imagem_quebra_a_verificacao(pacote, tmp_path):
    def adulterar(conteudo):
        conteudo["midia/placa.png"] = b"outra imagem qualquer"
        return conteudo

    adulterado = _reescrever(pacote, tmp_path / "imagem.ecoar", adulterar)
    assert not verificar_pacote(adulterado).valido


def test_remover_midia_e_detectado(pacote, tmp_path):
    def adulterar(conteudo):
        del conteudo["midia/placa.png"]
        return conteudo

    adulterado = _reescrever(pacote, tmp_path / "faltando.ecoar", adulterar)
    relatorio = verificar_pacote(adulterado)

    assert not relatorio.valido
    assert any("ausente" in problema for problema in relatorio.problemas)


def test_arquivo_extra_nao_declarado_e_detectado(pacote, tmp_path):
    """Injetar mídia depois é tão grave quanto alterar a que existe."""

    def adulterar(conteudo):
        conteudo["midia/foto-extra.png"] = b"conteudo injetado"
        return conteudo

    adulterado = _reescrever(pacote, tmp_path / "extra.ecoar", adulterar)
    relatorio = verificar_pacote(adulterado)

    assert not relatorio.valido
    assert any("não declarado" in problema for problema in relatorio.problemas)


def test_hash_do_manifesto_nao_depende_da_ordem_das_chaves(pacote):
    manifesto = ler_manifesto(pacote)
    invertido = dict(reversed(list(manifesto.items())))

    from edge.evidence_packager import calcular_hash_manifesto

    assert calcular_hash_manifesto(manifesto) == calcular_hash_manifesto(invertido)


def test_arquivo_corrompido_nao_derruba_o_verificador(tmp_path):
    lixo = tmp_path / "lixo.ecoar"
    lixo.write_bytes(b"isto nao e um zip")

    relatorio = verificar_pacote(lixo)

    assert not relatorio.valido
    assert "não é um pacote" in relatorio.problemas[0]


def test_arquivo_inexistente_e_reportado(tmp_path):
    relatorio = verificar_pacote(tmp_path / "nao-existe.ecoar")
    assert not relatorio.valido


# -- evento ambíguo ----------------------------------------------------


def test_evento_ambiguo_gera_pacote_sem_imagem(tmp_path):
    config = de_dict(config_base())
    evento = janela_evento()
    acionador = AcionadorCamera(config, diretorio=tmp_path / "capturas")
    acionamento = acionador.processar("evt-ambiguo", predicao_alvo(0.55), doa_boa(), evento.spl)

    caminho = montar_pacote(
        config=config,
        evento_id="evt-ambiguo",
        evento=evento,
        doa=doa_boa(),
        predicao=predicao_alvo(0.55),
        acionamento=acionamento,
        destino=tmp_path / "evt-ambiguo.ecoar",
    )

    manifesto = ler_manifesto(caminho)
    assert manifesto["decisao"]["acao"] == "ambiguo"
    assert manifesto["imagens"] == []
    assert manifesto["medicao_instrumento"] is None
    assert manifesto["motivo_sem_instrumento"]
    assert verificar_pacote(caminho).valido


# -- escrita atômica ----------------------------------------------------


def test_falha_no_meio_da_montagem_nao_deixa_pacote_parcial(tmp_path):
    """Cadeia de custódia (D8): ou o evento tem evidência completa, ou não tem
    nenhuma — nunca um `.ecoar` incompleto no caminho final."""
    config = de_dict(config_base())
    evento = janela_evento()
    acionador = AcionadorCamera(config, diretorio=tmp_path / "capturas")
    with acionador:
        acionamento = acionador.processar(
            "evt-falha", predicao_alvo(), doa_boa(), evento.spl
        )
    assert acionamento.capturas, "o teste precisa de uma captura para poder sumir com ela"

    # A imagem some do disco entre o acionamento e a montagem do pacote —
    # sha256_arquivo() vai estourar FileNotFoundError no meio da montagem.
    acionamento.capturas[0].caminho.unlink()

    destino = tmp_path / "evt-falha.ecoar"
    with pytest.raises(FileNotFoundError):
        montar_pacote(
            config=config,
            evento_id="evt-falha",
            evento=evento,
            doa=doa_boa(),
            predicao=predicao_alvo(),
            acionamento=acionamento,
            destino=destino,
        )

    assert not destino.exists()
    assert not destino.with_name(destino.name + ".tmp").exists()


# -- linha de comando --------------------------------------------------


def test_cli_devolve_zero_para_pacote_integro(pacote, capsys):
    assert cli([str(pacote)]) == 0
    saida = capsys.readouterr().out
    assert "íntegro" in saida
    assert "valor legal: NÃO" in saida


def test_cli_devolve_erro_para_pacote_adulterado(pacote, tmp_path, capsys):
    def adulterar(conteudo):
        manifesto = json.loads(conteudo[NOME_MANIFESTO])
        manifesto["modo"] = "autuacao"
        conteudo[NOME_MANIFESTO] = canonico(manifesto)
        return conteudo

    adulterado = _reescrever(pacote, tmp_path / "x.ecoar", adulterar)

    assert cli([str(adulterado)]) == 1
    assert "FALHOU" in capsys.readouterr().err
