"""Classificação de um trecho de áudio, na linha de comando.

    # sobre uma gravação de campo
    python -m edge.classifier.main --arquivo docs/field-notes/audio/ponte-01.wav

    # matriz de confusão sobre a cena de bancada (regressão do módulo)
    python -m edge.classifier.main --bancada
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

from edge.audio_capture.fontes import FonteWav
from edge.audio_capture.sintetico import PERFIS, CenaSintetica
from edge.classifier import CLASSES, criar_classificador
from edge.classifier.heuristico import ClassificadorHeuristico
from edge.config import ConfiguracaoInvalida, carregar
from edge.geometria import ArrayCircular

# Instante, dentro do ciclo de cada perfil, em que o evento acontece.
ANCORAS = {
    "escapamento": 4.0,
    "buzina": 2.35,
    "obra": 10.0,
    "trovao": 1.5,
    "ambiente": 5.0,
}

CLASSE_DO_PERFIL = {
    "escapamento": "escapamento_adulterado",
    "buzina": "buzina",
    "obra": "obra",
    "trovao": "trovao",
    "ambiente": "ambiente",
}


def bancada(taxa: int) -> int:
    array = ArrayCircular(raio_m=0.045, n_microfones=4)
    classificador = ClassificadorHeuristico()

    print("Cena sintética de bancada — NÃO é evidência de acerto em campo.\n")
    largura = max(len(c) for c in CLASSES) + 2
    print("perfil".ljust(14) + "".join(c[:10].rjust(12) for c in CLASSES))

    acertos = 0
    for perfil in PERFIS:
        cena = CenaSintetica(array, taxa_amostragem=taxa, perfil=perfil, azimute_graus=45.0)
        amostras = cena.bloco(int(3 * taxa), int((ANCORAS[perfil] - 1.5) * taxa))
        predicao = classificador.classificar(amostras, taxa)

        linha = "".join(f"{predicao.scores[c]:12.2f}" for c in CLASSES)
        certo = predicao.classe == CLASSE_DO_PERFIL[perfil]
        acertos += int(certo)
        print(f"{perfil.ljust(14)}{linha}   {'ok' if certo else 'ERRO -> ' + predicao.classe}")

    rng = np.random.default_rng(1)
    predicao = classificador.classificar(rng.normal(0, 0.05, (3 * taxa, 4)), taxa)
    linha = "".join(f"{predicao.scores[c]:12.2f}" for c in CLASSES)
    print(f"{'ruído branco'.ljust(14)}{linha}   -> {predicao.classe}")

    print(f"\n{acertos}/{len(PERFIS)} perfis de bancada classificados corretamente")
    del largura
    return 0 if acertos == len(PERFIS) else 1


def de_arquivo(caminho: str, caminho_config: str | None) -> int:
    fonte = FonteWav(caminho, bloco_amostras=1 << 20, tempo_real=False)
    with fonte:
        blocos = [bloco.amostras for bloco in fonte.blocos()]
    if not blocos:
        print("arquivo vazio", file=sys.stderr)
        return 1
    amostras = np.concatenate(blocos)

    if caminho_config:
        classificador = criar_classificador(carregar(caminho_config))
    else:
        classificador = ClassificadorHeuristico()

    predicao = classificador.classificar(amostras, fonte.taxa_amostragem)

    print(f"arquivo ...... {caminho}")
    print(f"duração ...... {len(amostras) / fonte.taxa_amostragem:.1f} s, {fonte.canais} canais")
    print(f"modelo ....... {predicao.modelo} {predicao.versao_modelo}\n")
    print(f"classe ....... {predicao.classe}")
    print(f"score ........ {predicao.score:.3f}")
    print(f"score do alvo  {predicao.score_alvo:.3f}\n")
    for classe, valor in sorted(predicao.scores.items(), key=lambda item: -item[1]):
        print(f"  {classe:24s} {valor:.3f}")
    print(f"\npor quê: {predicao.explicacao}")
    return 0


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ecoar-classificador",
        description="Classifica a assinatura acústica de um trecho de áudio.",
    )
    parser.add_argument("--arquivo", help="arquivo .wav a classificar")
    parser.add_argument("--config", help="configuração do nó (define qual modelo usar)")
    parser.add_argument("--bancada", action="store_true", help="roda a cena sintética inteira")
    parser.add_argument("--taxa", type=int, default=48000)
    args = parser.parse_args(argv)

    try:
        if args.bancada:
            return bancada(args.taxa)
        if not args.arquivo:
            parser.error("informe --arquivo ou --bancada")
        return de_arquivo(args.arquivo, args.config)
    except ConfiguracaoInvalida as erro:
        print(f"configuração recusada: {erro}", file=sys.stderr)
        return 2
    except FileNotFoundError as erro:
        print(erro, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
