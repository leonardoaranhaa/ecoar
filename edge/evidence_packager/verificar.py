"""Verificação independente de um pacote de evidência.

    python -m edge.evidence_packager.verificar evento.ecoar

Este comando existe para ser rodado por quem NÃO é nós: a prefeitura, o
advogado do autuado, um perito. Ele não consulta banco, não acessa rede e não
depende de chave nossa — lê o arquivo e recalcula os hashes.

Saída 0 = íntegro. Saída 1 = alterado depois de gerado.
"""

from __future__ import annotations

import argparse
import json
import sys

from edge.evidence_packager.pacote import verificar_pacote


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ecoar-verificar",
        description="Confere a integridade de um pacote de evidência .ecoar.",
    )
    parser.add_argument("pacote", help="arquivo .ecoar")
    parser.add_argument("--json", action="store_true", help="imprime o manifesto inteiro")
    args = parser.parse_args(argv)

    relatorio = verificar_pacote(args.pacote)

    if args.json:
        print(json.dumps(relatorio.manifesto, indent=2, ensure_ascii=False))
        return 0 if relatorio.valido else 1

    manifesto = relatorio.manifesto
    if manifesto:
        print(f"evento ......... {manifesto.get('evento_id')}")
        print(f"nó ............. {(manifesto.get('no') or {}).get('no_id')}")
        print(f"modo ........... {manifesto.get('modo')}")
        print(f"capturado em ... {manifesto.get('capturado_em')}")

        decisao = manifesto.get("decisao") or {}
        print(f"decisão ........ {decisao.get('acao')} ({decisao.get('versao_politica')})")

        classificacao = manifesto.get("classificacao") or {}
        if classificacao:
            print(
                f"classificação .. {classificacao.get('classe')} "
                f"score {classificacao.get('score_alvo')} "
                f"[{classificacao.get('modelo')} {classificacao.get('versao_modelo')}]"
            )

        localizacao = manifesto.get("localizacao") or {}
        if localizacao:
            print(
                f"ângulo ......... {localizacao.get('azimute_graus')}° "
                f"±{localizacao.get('margem_graus')}° "
                f"(confiança {localizacao.get('confianca')})"
            )

        spl = manifesto.get("spl_estimado") or {}
        print(
            f"SPL estimado ... {spl.get('db')} dB — valor legal: "
            f"{'sim' if spl.get('valor_legal') else 'NÃO'}"
        )

        instrumento = manifesto.get("medicao_instrumento")
        if instrumento:
            print(
                f"instrumento .... {instrumento.get('db')} dB — valor legal: "
                f"{'sim' if instrumento.get('valor_legal') else 'NÃO'}"
            )
        else:
            print(f"instrumento .... sem leitura ({manifesto.get('motivo_sem_instrumento')})")

        print(f"imagens ........ {len(manifesto.get('imagens') or [])}")
        print(f"hash ........... {manifesto.get('hash_manifesto')}")
        print()

    if relatorio.valido:
        print("INTEGRIDADE: íntegro — nenhum byte foi alterado desde a geração")
        return 0

    print("INTEGRIDADE: FALHOU", file=sys.stderr)
    for problema in relatorio.problemas:
        print(f"  - {problema}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(cli())
