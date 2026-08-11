"""Leitura isolada do instrumento de medição — checkpoint 3 de docs/hardware.

    python -m edge.audio_capture.read_sonometro --config config/no.exemplo.yaml -n 5

O que este comando serve para provar: o valor lido pelo código bate com o valor
que a própria plataforma do fabricante mostra, em pelo menos 5 níveis
diferentes. Enquanto isso não bater, não faz sentido integrar o instrumento à
cadeia — um erro de escala aqui contamina toda a evidência.
"""

from __future__ import annotations

import argparse
import sys
import time

from edge.audio_capture.sonometro import InstrumentoIndisponivel, criar_sonometro
from edge.config import ConfiguracaoInvalida, carregar


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ecoar-sonometro",
        description="Lê o instrumento de medição configurado, isoladamente.",
    )
    parser.add_argument("--config", default="config/no.exemplo.yaml")
    parser.add_argument("-n", "--leituras", type=int, default=5)
    parser.add_argument("--intervalo", type=float, default=2.0, help="segundos entre leituras")
    args = parser.parse_args(argv)

    try:
        config = carregar(args.config)
    except ConfiguracaoInvalida as erro:
        print(f"configuração recusada: {erro}", file=sys.stderr)
        return 2

    try:
        leitor = criar_sonometro(config)
    except InstrumentoIndisponivel as erro:
        print(f"instrumento indisponível: {erro}", file=sys.stderr)
        return 3

    info = leitor.info()
    print(f"tipo ............ {info.tipo}")
    print(f"modelo .......... {info.modelo or '—'}")
    print(f"classe IEC 61672  {info.classe or '—'}")
    print(f"certificado ..... {info.certificado or '—'}")
    print(f"calibração até .. {info.validade_calibracao or '—'}")
    print(f"valor legal ..... {'SIM' if info.valor_legal else 'NÃO'}\n")

    leitor.abrir()
    try:
        for indice in range(args.leituras):
            try:
                leitura = leitor.ler_db()
                print(f"[{indice + 1}/{args.leituras}] {leitura.db:6.1f} dB({leitura.ponderacao})")
            except InstrumentoIndisponivel as erro:
                print(f"[{indice + 1}/{args.leituras}] sem leitura — {erro}", file=sys.stderr)
                return 3
            if indice + 1 < args.leituras:
                time.sleep(args.intervalo)
    finally:
        leitor.fechar()

    if not info.valor_legal:
        print(
            "\nAtenção: este instrumento não produz medição com valor legal. "
            "Suficiente para triagem; insuficiente para autuação "
            "(docs/legal/inmetro.md)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
