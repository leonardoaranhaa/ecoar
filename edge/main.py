"""Ponto de entrada do nó de campo.

    # operação normal, com o array real
    python -m edge.main --config config/no-01.yaml

    # bancada, sem hardware e sem backend: a cadeia inteira em cena sintética
    python -m edge.main --fonte sintetica --duracao 30 --sem-uplink

    # rodando uma gravação de campo pela cadeia
    python -m edge.main --arquivo docs/field-notes/audio/ponte-01.wav

O log detalha cada etapa por evento — é por ele que se descobre qual módulo
falhou quando a cadeia quebra no poste.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from dataclasses import replace

from edge.config import ConfiguracaoInvalida, ConfigNo, carregar
from edge.no import No


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

    config = replace(config, audio=replace(config.audio, fonte=fonte))
    if args.backend:
        config = replace(config, uplink=replace(config.uplink, url=args.backend))

    config.validar()
    return config


def executar(args: argparse.Namespace) -> int:
    config = _config_com_sobrescritas(args)

    print(f"nó ............ {config.id}")
    print(f"modo .......... {config.modo}")
    print(f"fonte ......... {config.audio.fonte.tipo}")
    print(f"gatilho ....... SPL >= {config.gatilho.spl_db_minimo:.0f} dB estimado, "
          f"score >= {config.gatilho.score_aciona:.2f} ({config.gatilho.versao_politica})")
    print(f"uplink ........ {'desligado' if args.sem_uplink else config.uplink.url}")
    print()

    no = No(config)
    no.iniciar(com_uplink=not args.sem_uplink)

    encerrar = {"pedido": False}

    def ao_sinal(*_):
        encerrar["pedido"] = True

    signal.signal(signal.SIGINT, ao_sinal)
    signal.signal(signal.SIGTERM, ao_sinal)

    try:
        if not no.captura.aguardar_primeiro_bloco(timeout=10.0):
            print("nenhum áudio chegou em 10 s", file=sys.stderr)
            return 1

        inicio = time.time()
        while not encerrar["pedido"]:
            if args.duracao and time.time() - inicio >= args.duracao:
                break
            if no.captura.fonte_terminou and no._picos.empty():
                break
            no.captura.verificar_saude()
            time.sleep(0.2)

        # Dá tempo de a cadeia terminar o que já detectou antes de descer.
        no.aguardar_ocioso(timeout=45.0)
    finally:
        estado = no.estado()
        no.parar()

    print("\nresumo da sessão")
    for chave, valor in no.contadores.como_dict().items():
        print(f"  {chave.replace('_', ' '):24s} {valor}")
    print(f"  {'fila de envio':24s} {estado['fila_uplink']}")
    return 0


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ecoar-no", description="Nó de campo do ECOAR."
    )
    parser.add_argument("--config", default="config/no.exemplo.yaml")
    parser.add_argument("--duracao", type=float, default=0.0, help="0 = até Ctrl-C")
    parser.add_argument("--fonte", choices=("i2s", "wav", "sintetica"))
    parser.add_argument("--arquivo", help="gravação .wav multicanal (implica --fonte wav)")
    parser.add_argument("--perfil", help="perfil da cena sintética")
    parser.add_argument("--azimute", type=float, help="azimute da fonte sintética")
    parser.add_argument("--backend", help="sobrescreve uplink.url")
    parser.add_argument("--sem-uplink", action="store_true", help="não envia nada")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
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
