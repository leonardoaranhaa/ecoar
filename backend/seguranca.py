"""Autenticação entre nó e backend, e entre operador e painel.

Token estático é suficiente para o MVP e **não** é suficiente para operação
contratada: antes do contrato, migrar o canal nó↔backend para certificado por
nó (mTLS). Está registrado aqui e no README do backend para não virar dívida
esquecida.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import Header, HTTPException, status

from backend.config import ConfigBackend

PERFIL_OPERADOR = "operador"
PERFIL_ADMIN = "admin"


@dataclass(frozen=True)
class Identidade:
    nome: str
    perfil: str

    @property
    def e_admin(self) -> bool:
        return self.perfil == PERFIL_ADMIN


def _token_do_cabecalho(autorizacao: str | None) -> str:
    if not autorizacao or not autorizacao.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="autenticação ausente: envie 'Authorization: Bearer <token>'",
        )
    return autorizacao.split(" ", 1)[1].strip()


def _conferir(token: str, cadastrados: dict[str, str]) -> str | None:
    """Comparação em tempo constante contra todos os cadastrados.

    Percorrer a lista inteira mesmo depois de achar é deliberado: sair na
    primeira coincidência vaza, pelo tempo de resposta, quantos tokens foram
    testados antes.
    """
    encontrado = None
    for nome, esperado in cadastrados.items():
        if secrets.compare_digest(token, esperado):
            encontrado = nome
    return encontrado


def autenticar_no(config: ConfigBackend):
    def dependencia(authorization: str | None = Header(default=None)) -> str:
        no_id = _conferir(_token_do_cabecalho(authorization), config.tokens)
        if no_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="token de nó inválido"
            )
        return no_id

    return dependencia


def autenticar_operador(config: ConfigBackend):
    def dependencia(authorization: str | None = Header(default=None)) -> Identidade:
        token = _token_do_cabecalho(authorization)
        nome = _conferir(token, config.tokens_operador)
        if nome is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="token de operador inválido",
            )
        perfil = PERFIL_ADMIN if nome.startswith("admin") else PERFIL_OPERADOR
        return Identidade(nome=nome, perfil=perfil)

    return dependencia


def exigir_admin(identidade: Identidade) -> Identidade:
    if not identidade.e_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ação restrita ao perfil admin",
        )
    return identidade
