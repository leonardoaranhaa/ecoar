"""Sobe o backend.

    ECOAR_TOKEN_NO_01=... python -m backend.cli --config config/backend.exemplo.yaml
"""

from __future__ import annotations

import argparse
import logging
import sys

from backend.aplicacao import criar_app
from backend.config import carregar
from edge.config import ConfiguracaoInvalida


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ecoar-backend")
    parser.add_argument("--config", default="config/backend.exemplo.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--porta", type=int, default=8000)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    try:
        config = carregar(args.config)
    except ConfiguracaoInvalida as erro:
        print(f"configuração recusada: {erro}", file=sys.stderr)
        return 2

    import uvicorn

    print(f"banco .......... {config.banco}")
    print(f"pacotes ........ {config.armazenamento}")
    print(f"nós cadastrados  {', '.join(sorted(config.tokens)) or '(nenhum)'}")
    print(f"painel ......... http://{args.host}:{args.porta}/\n")

    uvicorn.run(criar_app(config), host=args.host, port=args.porta, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
