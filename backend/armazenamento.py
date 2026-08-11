"""Guarda dos pacotes de evidência.

Disco local no MVP, com a estrutura de caminhos já pensada para virar object
storage sem redesenho: `AAAA/MM/DD/no_id/evento_id.ecoar` é chave de bucket
tanto quanto é caminho de arquivo.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class MidiaNaoEncontrada(LookupError):
    pass


@dataclass(frozen=True)
class Armazenamento:
    raiz: Path

    def caminho_de(self, no_id: str, evento_id: str, instante: float) -> Path:
        data = datetime.fromtimestamp(instante, tz=timezone.utc)
        return (
            self.raiz
            / f"{data.year:04d}"
            / f"{data.month:02d}"
            / f"{data.day:02d}"
            / _seguro(no_id)
            / f"{_seguro(evento_id)}.ecoar"
        )

    def guardar(self, conteudo: bytes, no_id: str, evento_id: str, instante: float) -> Path:
        destino = self.caminho_de(no_id, evento_id, instante)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(conteudo)
        return destino

    def ler_midia(self, caminho_pacote: str | Path, nome: str) -> bytes:
        """Extrai um arquivo de mídia de dentro do pacote.

        A mídia nunca é desempacotada para disco: ela sai do zip direto para a
        resposta. Cópia solta fora do pacote é cópia sem hash — e a primeira
        coisa que uma contestação pergunta é de onde veio aquele arquivo.
        """
        caminho_pacote = Path(caminho_pacote)
        if not caminho_pacote.exists():
            raise MidiaNaoEncontrada(f"pacote não encontrado: {caminho_pacote}")
        with zipfile.ZipFile(caminho_pacote) as pacote:
            nomes = set(pacote.namelist())
            if nome not in nomes:
                raise MidiaNaoEncontrada(f"{nome} não existe neste pacote")
            return pacote.read(nome)


def _seguro(texto: str) -> str:
    """Impede que um identificador vindo do nó escape do diretório."""
    limpo = "".join(c if c.isalnum() or c in "-_." else "-" for c in texto)
    return limpo.strip(".-") or "sem-id"
