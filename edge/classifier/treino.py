"""Treino do classificador neural.

Roda numa máquina de desenvolvimento, nunca no nó. O nó recebe o `.pt` pronto.

    python -m edge.classifier.treino --dados acervo/ --saida modelos/2026-09.pt

O acervo é uma pasta por classe:

    acervo/
    ├── escapamento_adulterado/*.wav
    ├── buzina/*.wav
    ├── obra/*.wav
    ├── trovao/*.wav
    └── ambiente/*.wav

Regras que este script aplica, e que não são negociáveis (D13):

- **separação por arquivo de origem**, não por amostra: as variações geradas por
  aumento de dados a partir do mesmo áudio ficam todas do mesmo lado da divisão.
  Sem isso, a validação vê uma cópia processada do que o treino já viu e
  devolve uma acurácia que não existe;
- **o conjunto de validação nunca recebe aumento** — ele precisa representar o
  que o modelo vai encontrar, não o que foi inventado a partir dele;
- **o relatório sai junto do modelo**, com quantas amostras de cada classe
  entraram. Modelo sem essa ficha não deveria ir para produção.
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from edge.classifier.augment import gerar_variacoes
from edge.classifier.base import CLASSES
from edge.classifier.cnn import (
    JANELA_QUADROS,
    MetadadosModelo,
    construir_modelo,
    importar_torch,
    preparar_entrada,
    salvar_modelo,
)
from edge.classifier.features import N_MELS


@dataclass
class Amostra:
    entrada: np.ndarray
    classe: int
    origem: str


def _ler_wav(caminho: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(caminho), "rb") as arquivo:
        canais = arquivo.getnchannels()
        largura = arquivo.getsampwidth()
        taxa = arquivo.getframerate()
        bruto = arquivo.readframes(arquivo.getnframes())

    from edge.audio_capture.fontes import _bytes_para_float32

    return _bytes_para_float32(bruto, largura, canais), taxa


def carregar_acervo(
    raiz: Path, variacoes: int, semente: int
) -> tuple[list[Amostra], list[Amostra], dict[str, dict[str, int]]]:
    """Lê o acervo e divide por arquivo de origem, com aumento só no treino."""
    rng = np.random.default_rng(semente)
    treino: list[Amostra] = []
    validacao: list[Amostra] = []
    ficha: dict[str, dict[str, int]] = {}

    for indice, classe in enumerate(CLASSES):
        pasta = raiz / classe
        arquivos = sorted(pasta.glob("*.wav")) if pasta.exists() else []
        if not arquivos:
            print(f"aviso: nenhuma amostra em {pasta}", file=sys.stderr)
            ficha[classe] = {"arquivos": 0, "treino": 0, "validacao": 0}
            continue

        embaralhados = list(arquivos)
        rng.shuffle(embaralhados)
        corte = max(1, int(round(0.2 * len(embaralhados))))
        arquivos_validacao = embaralhados[:corte]
        arquivos_treino = embaralhados[corte:] or embaralhados[:1]

        for caminho in arquivos_validacao:
            amostras, taxa = _ler_wav(caminho)
            validacao.append(Amostra(preparar_entrada(amostras, taxa), indice, caminho.name))

        for caminho in arquivos_treino:
            amostras, taxa = _ler_wav(caminho)
            treino.append(Amostra(preparar_entrada(amostras, taxa), indice, caminho.name))
            if variacoes > 0:
                mono = amostras.mean(axis=1) if amostras.ndim == 2 else amostras
                for variante, _ in gerar_variacoes(mono, taxa, variacoes, semente=semente):
                    treino.append(
                        Amostra(preparar_entrada(variante, taxa), indice, caminho.name)
                    )

        ficha[classe] = {
            "arquivos": len(arquivos),
            "treino": len(arquivos_treino) * (1 + variacoes),
            "validacao": len(arquivos_validacao),
        }

    return treino, validacao, ficha


def _tensores(amostras: list[Amostra]):
    torch = importar_torch()
    entradas = torch.from_numpy(np.stack([a.entrada for a in amostras]))[:, None, :, :]
    alvos = torch.from_numpy(np.array([a.classe for a in amostras], dtype=np.int64))
    return entradas, alvos


def treinar(
    treino: list[Amostra],
    validacao: list[Amostra],
    epocas: int,
    taxa_aprendizado: float,
    semente: int,
):
    torch = importar_torch()
    torch.manual_seed(semente)

    modelo = construir_modelo(n_classes=len(CLASSES))
    otimizador = torch.optim.Adam(modelo.parameters(), lr=taxa_aprendizado)
    perda = torch.nn.CrossEntropyLoss()

    x_treino, y_treino = _tensores(treino)
    x_val, y_val = _tensores(validacao) if validacao else (None, None)

    historico = []
    for epoca in range(epocas):
        modelo.train()
        ordem = torch.randperm(len(x_treino))
        total = 0.0
        for inicio in range(0, len(ordem), 16):
            lote = ordem[inicio : inicio + 16]
            otimizador.zero_grad()
            saida = modelo(x_treino[lote])
            erro = perda(saida, y_treino[lote])
            erro.backward()
            otimizador.step()
            total += float(erro.detach()) * len(lote)

        acuracia = avaliar(modelo, x_val, y_val) if x_val is not None else float("nan")
        historico.append(
            {"epoca": epoca + 1, "perda": total / len(ordem), "acuracia_validacao": acuracia}
        )
        print(
            f"época {epoca + 1:3d}/{epocas}  perda {total / len(ordem):.4f}  "
            f"acurácia na validação {acuracia:.3f}"
        )

    return modelo, historico


def avaliar(modelo, entradas, alvos) -> float:
    torch = importar_torch()
    modelo.eval()
    with torch.no_grad():
        previsto = modelo(entradas).argmax(dim=1)
        return float((previsto == alvos).float().mean())


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ecoar-treino",
        description="Treina o classificador neural de assinatura acústica.",
    )
    parser.add_argument("--dados", required=True, type=Path, help="raiz do acervo rotulado")
    parser.add_argument("--saida", required=True, type=Path, help="arquivo .pt de destino")
    parser.add_argument("--variacoes", type=int, default=6, help="aumentos por áudio de treino")
    parser.add_argument("--epocas", type=int, default=30)
    parser.add_argument("--taxa-aprendizado", type=float, default=1e-3)
    parser.add_argument("--semente", type=int, default=20260817)
    parser.add_argument(
        "--observacao",
        default="",
        help="de onde veio o acervo — vai gravada junto do modelo",
    )
    args = parser.parse_args(argv)

    treino, validacao, ficha = carregar_acervo(args.dados, args.variacoes, args.semente)
    if not treino:
        print("acervo vazio: nada a treinar", file=sys.stderr)
        return 1

    print(f"treino: {len(treino)} amostras · validação: {len(validacao)} amostras")
    for classe, numeros in ficha.items():
        print(f"  {classe:24s} {numeros['arquivos']:4d} arquivos")

    modelo, historico = treinar(
        treino, validacao, args.epocas, args.taxa_aprendizado, args.semente
    )

    metadados = MetadadosModelo(
        versao=f"cnn/{date.today().isoformat()}",
        classes=CLASSES,
        n_mels=N_MELS,
        quadros=JANELA_QUADROS,
        taxa_amostragem=48000,
        treinado_em=date.today().isoformat(),
        observacao=args.observacao,
    )
    caminho = salvar_modelo(modelo, metadados, args.saida)

    relatorio = {
        "modelo": metadados.como_dict(),
        "acervo": ficha,
        "historico": historico,
        "acuracia_final": historico[-1]["acuracia_validacao"] if historico else None,
    }
    caminho.with_name(caminho.stem + "-relatorio.json").write_text(
        json.dumps(relatorio, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nmodelo salvo em {caminho}")
    print("Antes de promover a produção: comparar com o modelo atual no conjunto de")
    print("validação fixo. Modelo novo só entra se não piorar (docs/DECISIONS.md, D13).")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
