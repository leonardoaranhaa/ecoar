"""Configuração do backend.

Segredo não mora no arquivo: os tokens dos nós vêm de variável de ambiente,
declaradas no YAML como `${ECOAR_TOKEN_NO_01}`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from edge.config import ConfiguracaoInvalida, _percorrer


@dataclass(frozen=True)
class ConfigBackend:
    banco: Path = Path("dados/ecoar.db")
    armazenamento: Path = Path("dados/pacotes")
    tokens: dict[str, str] = field(default_factory=dict)
    tokens_operador: dict[str, str] = field(default_factory=dict)
    tamanho_maximo_pacote_mb: float = 64.0

    def validar(self) -> None:
        if not self.tokens:
            raise ConfiguracaoInvalida(
                "backend.tokens vazio: nenhum nó poderia enviar evento. Declare ao "
                "menos um par no_id/token (o valor vindo de variável de ambiente)."
            )
        for no_id, token in self.tokens.items():
            if not token or len(token) < 16:
                raise ConfiguracaoInvalida(
                    f"token do nó {no_id!r} ausente ou curto demais (mínimo 16 caracteres)"
                )
        for operador, token in self.tokens_operador.items():
            if not token or len(token) < 16:
                raise ConfiguracaoInvalida(
                    f"token do operador {operador!r} ausente ou curto demais"
                )

    @property
    def tamanho_maximo_bytes(self) -> int:
        return int(self.tamanho_maximo_pacote_mb * 1024 * 1024)


def de_dict(dados: dict) -> ConfigBackend:
    dados = _percorrer(dados or {})
    conhecidos = {
        "banco",
        "armazenamento",
        "tokens",
        "tokens_operador",
        "tamanho_maximo_pacote_mb",
    }
    desconhecidos = set(dados) - conhecidos
    if desconhecidos:
        raise ConfiguracaoInvalida(
            f"backend: chave(s) desconhecida(s) {sorted(desconhecidos)}"
        )

    config = ConfigBackend(
        banco=Path(dados.get("banco", "dados/ecoar.db")),
        armazenamento=Path(dados.get("armazenamento", "dados/pacotes")),
        tokens=dict(dados.get("tokens") or {}),
        tokens_operador=dict(dados.get("tokens_operador") or {}),
        tamanho_maximo_pacote_mb=float(dados.get("tamanho_maximo_pacote_mb", 64.0)),
    )
    config.validar()
    return config


def carregar(caminho: str | Path) -> ConfigBackend:
    caminho = Path(caminho)
    if not caminho.exists():
        raise ConfiguracaoInvalida(f"configuração do backend não encontrada: {caminho}")
    with caminho.open(encoding="utf-8") as arquivo:
        dados = yaml.safe_load(arquivo)
    if not isinstance(dados, dict):
        raise ConfiguracaoInvalida(f"{caminho}: esperava um mapa YAML no topo")
    return de_dict(dados)
