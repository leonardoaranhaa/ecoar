"""Verificação de bancada da localização direcional.

Duas formas de usar:

    # varredura em ângulos conhecidos, sem hardware — mede o erro do algoritmo
    python -m edge.localization.main --varrer

    # estimativa contínua a partir da fonte configurada (array, .wav ou cena)
    python -m edge.localization.main --config config/no.exemplo.yaml --duracao 20

A varredura é o que se roda depois de mexer em qualquer parâmetro do
algoritmo. A estimativa contínua é o que se roda no poste, apontando uma fonte
conhecida de um ângulo conhecido, para conferir se a geometria configurada bate
com a montagem física.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

import numpy as np

from edge.audio_capture.buffer import JanelaIndisponivel
from edge.audio_capture.captura import CapturaAudio
from edge.audio_capture.sintetico import CenaSintetica
from edge.config import ConfiguracaoInvalida, carregar
from edge.geometria import ArrayCircular
from edge.localization.doa import Localizador

ANGULOS_DE_PROVA = (0.0, 23.0, 45.0, 90.0, 137.0, 180.0, 225.0, 270.0, 315.0, 351.0)


def varrer(array: ArrayCircular, taxa: int, perfil: str, ruido: float) -> int:
    localizador = Localizador(array)
    print(f"array ...... raio {array.raio_m * 100:.1f} cm, {array.n_microfones} microfones")
    print(f"ambiguidade  acima de {array.frequencia_ambiguidade_hz:.0f} Hz")
    print(f"banda usada  {localizador.banda_hz[0]:.0f}–{localizador.banda_hz[1]:.0f} Hz")
    print(f"abertura ... {array.atraso_maximo_s * 1e6:.0f} µs entre os extremos\n")
    print(f"{'real':>7} {'estimado':>9} {'erro':>7} {'margem':>8} {'conf':>6} {'resíduo':>9}")

    erros = []
    for azimute in ANGULOS_DE_PROVA:
        cena = CenaSintetica(array, taxa_amostragem=taxa, perfil=perfil, azimute_graus=azimute)
        cena.ruido_fundo = ruido
        cena.__post_init__()
        amostras = cena.bloco(taxa, indice_inicial=int(3.6 * taxa))

        estimativa = localizador.estimar(amostras, taxa)
        erro = (estimativa.azimute_graus - azimute + 180.0) % 360.0 - 180.0
        erros.append(abs(erro))
        print(
            f"{azimute:7.1f} {estimativa.azimute_graus:9.1f} {erro:+7.1f} "
            f"{estimativa.margem_graus:7.1f}° {estimativa.confianca:6.2f} "
            f"{estimativa.residuo_us:8.1f} µs"
        )

    pior = max(erros)
    print(f"\nerro médio {np.mean(erros):.2f}° · pior caso {pior:.2f}° · meta do projeto ±5°")
    if pior > 5.0:
        print("FORA DA META", file=sys.stderr)
        return 1
    return 0


def ao_vivo(caminho_config: str, duracao: float, intervalo: float) -> int:
    config = carregar(caminho_config)
    array = ArrayCircular.de_config(config.array)
    localizador = Localizador(array)

    print(f"nó {config.id} · fonte {config.audio.fonte.tipo} · array raio {array.raio_m * 100:.1f} cm")
    print("aponte uma fonte conhecida de um ângulo conhecido e compare\n")
    print(f"{'t':>6} {'azimute':>9} {'margem':>8} {'conf':>6} {'dB(est)':>8}")

    captura = CapturaAudio(config)
    captura.iniciar()
    try:
        if not captura.aguardar_primeiro_bloco(timeout=5.0):
            print("nenhum áudio chegou em 5 s", file=sys.stderr)
            return 1

        inicio = time.time()
        while time.time() - inicio < duracao:
            captura.verificar_saude()
            if captura.fonte_terminou:
                break
            try:
                janela = captura.ultimos(0.5)
            except JanelaIndisponivel:  # buffer ainda curto
                time.sleep(intervalo)
                continue

            estimativa = localizador.estimar_janela(janela)
            spl = captura.spl_atual()
            print(
                f"{time.time() - inicio:6.1f} {estimativa.azimute_graus:8.1f}° "
                f"{estimativa.margem_graus:7.1f}° {estimativa.confianca:6.2f} "
                f"{(spl.db if spl else float('nan')):8.1f}"
            )
            time.sleep(intervalo)
    finally:
        captura.parar()
    return 0


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ecoar-localizacao",
        description="Verificação da localização direcional (GCC-PHAT).",
    )
    parser.add_argument("--varrer", action="store_true", help="varredura em ângulos conhecidos")
    parser.add_argument("--config", default="config/no.exemplo.yaml")
    parser.add_argument("--duracao", type=float, default=20.0)
    parser.add_argument("--intervalo", type=float, default=0.5)
    parser.add_argument("--taxa", type=int, default=48000, help="taxa da varredura sintética")
    parser.add_argument("--raio", type=float, default=0.045, help="raio do array na varredura, em metros")
    parser.add_argument("--microfones", type=int, default=4)
    parser.add_argument("--perfil", default="escapamento")
    parser.add_argument("--ruido", type=float, default=0.02)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    try:
        if args.varrer:
            array = ArrayCircular(raio_m=args.raio, n_microfones=args.microfones)
            return varrer(array, args.taxa, args.perfil, args.ruido)
        return ao_vivo(args.config, args.duracao, args.intervalo)
    except ConfiguracaoInvalida as erro:
        print(f"configuração recusada: {erro}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(cli())
