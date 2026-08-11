"""Teste de bancada da captura — checkpoint 2 de docs/hardware/README.md.

Uso típico, com o array já conectado:

    python -m edge.audio_capture.main --config config/no.exemplo.yaml --duracao 10

O teste da palma: bata palma perto de UM microfone e confira se o pico aparece
no canal correspondente. Se todos os canais reagem igual, os microfones estão
somados em vez de separados; se um canal fica mudo, é montagem elétrica ou
conflito de configuração de canal — não é o software.

Sem hardware, o mesmo comando roda com `--fonte sintetica` ou `--fonte wav`.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

from edge.audio_capture.captura import CapturaAudio
from edge.audio_capture.fontes import escrever_wav
from edge.config import ConfiguracaoInvalida, ConfigNo, carregar


def _config_com_sobrescritas(args: argparse.Namespace) -> ConfigNo:
    config = carregar(args.config)
    fonte = config.audio.fonte
    if args.fonte:
        fonte = replace(fonte, tipo=args.fonte)
    if args.arquivo:
        fonte = replace(fonte, tipo="wav", caminho=args.arquivo)
    if args.perfil:
        fonte = replace(fonte, perfil=args.perfil)
    if args.azimute is not None:
        fonte = replace(fonte, azimute_graus=args.azimute)
    if args.dispositivo:
        fonte = replace(fonte, dispositivo=args.dispositivo)

    config = replace(config, audio=replace(config.audio, fonte=fonte))
    config.validar()
    return config


def executar(args: argparse.Namespace) -> int:
    config = _config_com_sobrescritas(args)

    print(f"nó ......... {config.id}  (modo={config.modo})")
    print(f"fonte ...... {config.audio.fonte.tipo}")
    print(
        f"formato .... {config.audio.canais} canais a {config.audio.taxa_amostragem} Hz, "
        f"buffer de {config.audio.buffer_segundos:.0f} s"
    )
    print(
        f"calibração . offset {config.audio.calibracao.offset_db:+.1f} dB, "
        f"ponderação {config.audio.calibracao.ponderacao} "
        f"({config.audio.calibracao.referencia})"
    )
    print("SPL do array é estimativa relativa — não tem valor legal.\n")

    captura = CapturaAudio(config)
    captura.iniciar()
    try:
        if not captura.aguardar_primeiro_bloco(timeout=5.0):
            print("nenhum áudio chegou em 5 s — confira o dispositivo de captura", file=sys.stderr)
            return 1

        cabecalho = "  ".join(f"mic{i}" for i in range(config.audio.canais))
        print(f"{'t':>6}  {'dB(est)':>8}  {cabecalho}   dominante")

        inicio = time.time()
        while time.time() - inicio < args.duracao:
            captura.verificar_saude()
            if captura.fonte_terminou:
                print("(fonte terminou antes do tempo pedido)")
                break
            spl = captura.spl_atual()
            if spl is not None:
                canais = "  ".join(f"{v:5.1f}" for v in spl.db_por_canal)
                marca = "*" * (1 + spl.canal_dominante)
                print(
                    f"{time.time() - inicio:6.1f}  {spl.db:8.1f}  {canais}   "
                    f"mic{spl.canal_dominante} {marca}"
                )
            time.sleep(args.intervalo)

        leitura, motivo = captura.ler_sonometro()
        if leitura is not None:
            print(
                f"\ninstrumento: {leitura.db:.1f} dB "
                f"(valor legal: {'sim' if leitura.valor_legal else 'não'})"
            )
        else:
            print(f"\ninstrumento: sem leitura — {motivo}")

        if args.salvar:
            janela = captura.ultimos(args.duracao)
            destino = escrever_wav(args.salvar, janela.amostras, janela.taxa_amostragem)
            print(f"gravado: {destino} ({janela.duracao_s:.1f} s, {janela.canais} canais)")
    finally:
        captura.parar()

    return 0


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ecoar-captura",
        description="Teste de bancada da captura de áudio do nó ECOAR.",
    )
    parser.add_argument("--config", default="config/no.exemplo.yaml", help="arquivo de configuração do nó")
    parser.add_argument("--duracao", type=float, default=10.0, help="segundos de captura")
    parser.add_argument("--intervalo", type=float, default=0.5, help="intervalo entre linhas na tela")
    parser.add_argument("--fonte", choices=("i2s", "wav", "sintetica"), help="sobrescreve audio.fonte.tipo")
    parser.add_argument("--arquivo", help="arquivo .wav multicanal (implica --fonte wav)")
    parser.add_argument("--perfil", help="perfil da cena sintética")
    parser.add_argument("--azimute", type=float, help="azimute da fonte sintética, em graus")
    parser.add_argument("--dispositivo", help="dispositivo ALSA de captura")
    parser.add_argument("--salvar", type=Path, help="grava o trecho capturado num .wav")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    try:
        return executar(args)
    except ConfiguracaoInvalida as erro:
        print(f"configuração recusada: {erro}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(cli())
