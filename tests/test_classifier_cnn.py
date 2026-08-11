"""Caminho neural: preparo de entrada, treino, salvamento e inferência.

Os testes que exigem torch são pulados onde ele não está instalado — que é o
caso do nó de campo, por desenho (o nó recebe o modelo pronto, não treina).
"""

import numpy as np
import pytest

from edge.audio_capture.fontes import escrever_wav
from edge.classifier.base import CLASSES, ClassificadorIndisponivel
from edge.classifier.cnn import (
    JANELA_QUADROS,
    ClassificadorCNN,
    padronizar,
    preparar_entrada,
)
from edge.classifier.features import N_MELS
from edge.config import de_dict
from tests.conftest import config_base
from tests.test_classifier import ANCORAS, ARRAY, TAXA, cena

torch = pytest.importorskip("torch", reason="torch só é necessário para treinar")


def test_preparar_entrada_tem_sempre_o_mesmo_formato():
    curto = preparar_entrada(cena("escapamento", segundos=0.5), TAXA)
    longo = preparar_entrada(cena("escapamento", segundos=6.0), TAXA)

    assert curto.shape == (N_MELS, JANELA_QUADROS)
    assert longo.shape == (N_MELS, JANELA_QUADROS)
    assert curto.dtype == np.float32


def test_padronizar_recorta_no_trecho_mais_energetico():
    espectrograma = np.full((400, N_MELS), -80.0)
    espectrograma[300:320] = 0.0  # evento no fim

    recortado = padronizar(espectrograma, quadros=64)

    assert len(recortado) == 64
    assert recortado.max() == 0.0


def test_modelo_cabe_no_raspberry():
    """Orçamento de parâmetros: a rede divide o CM4 com captura e localização."""
    from edge.classifier.cnn import construir_modelo

    total = sum(p.numel() for p in construir_modelo().parameters())
    assert total < 100_000, f"{total} parâmetros é grande demais para o nó"


def test_treino_completo_salva_modelo_que_carrega_e_classifica(tmp_path):
    """Ensaio de ponta a ponta do caminho neural, com acervo minúsculo.

    Não prova acurácia — prova que o pipeline fecha: acervo em pastas, aumento
    de dados, divisão por arquivo de origem, treino, salvamento com metadados,
    carregamento no nó e inferência.
    """
    from edge.classifier.treino import carregar_acervo, cli

    acervo = tmp_path / "acervo"
    perfis = {
        "escapamento_adulterado": "escapamento",
        "buzina": "buzina",
        "obra": "obra",
        "trovao": "trovao",
        "ambiente": "ambiente",
    }
    for classe, perfil in perfis.items():
        pasta = acervo / classe
        for indice in range(3):
            deslocamento = (indice - 1) * 0.15
            geradora_inicio = int((ANCORAS[perfil] - 1.5 + deslocamento) * TAXA)
            from edge.audio_capture.sintetico import CenaSintetica

            geradora = CenaSintetica(
                ARRAY, taxa_amostragem=TAXA, perfil=perfil, azimute_graus=45.0 + indice * 10
            )
            amostras = geradora.bloco(int(2 * TAXA), geradora_inicio)
            escrever_wav(pasta / f"{classe}-{indice}.wav", amostras, TAXA)

    treino, validacao, ficha = carregar_acervo(acervo, variacoes=1, semente=1)
    assert len(treino) > len(validacao)
    assert all(numeros["arquivos"] == 3 for numeros in ficha.values())

    origens_treino = {a.origem for a in treino}
    origens_validacao = {a.origem for a in validacao}
    assert not (origens_treino & origens_validacao), (
        "variação aumentada do mesmo áudio vazou para a validação — a acurácia "
        "medida seria fictícia"
    )

    destino = tmp_path / "modelo.pt"
    codigo = cli(
        [
            "--dados", str(acervo),
            "--saida", str(destino),
            "--variacoes", "1",
            "--epocas", "2",
            "--observacao", "cena de bancada, teste",
        ]
    )

    assert codigo == 0
    assert destino.exists()
    assert destino.with_suffix(".json").exists()
    assert destino.with_name("modelo-relatorio.json").exists()

    classificador = ClassificadorCNN(destino).carregar()
    predicao = classificador.classificar(cena("escapamento"), TAXA)

    assert predicao.modelo == "cnn"
    assert predicao.versao_modelo.startswith("cnn/")
    assert set(predicao.scores) == set(CLASSES)
    assert sum(predicao.scores.values()) == pytest.approx(1.0, abs=1e-5)
    assert predicao.descritores["f0_hz"] > 0


def test_modelo_nao_carregado_falha_em_vez_de_devolver_palpite(tmp_path):
    classificador = ClassificadorCNN(tmp_path / "qualquer.pt")
    with pytest.raises(ClassificadorIndisponivel, match="não carregado"):
        classificador.classificar(cena("escapamento"), TAXA)


def test_fabrica_usa_a_rede_quando_o_modelo_existe(tmp_path):
    from edge.classifier import criar_classificador
    from edge.classifier.cnn import MetadadosModelo, construir_modelo, salvar_modelo

    destino = tmp_path / "modelo.pt"
    salvar_modelo(
        construir_modelo(),
        MetadadosModelo(
            versao="cnn/teste",
            classes=CLASSES,
            n_mels=N_MELS,
            quadros=JANELA_QUADROS,
            taxa_amostragem=TAXA,
            treinado_em="2026-08-17",
        ),
        destino,
    )

    dados = config_base()
    dados["classificador"] = {"tipo": "cnn", "modelo": str(destino)}
    classificador = criar_classificador(de_dict(dados))

    assert isinstance(classificador, ClassificadorCNN)
    assert classificador.versao == "cnn/teste"
