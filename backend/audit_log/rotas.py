"""Rotas da trilha de auditoria — só admin."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.audit_log.trilha import TrilhaAuditoria
from backend.config import ConfigBackend
from backend.seguranca import Identidade, autenticar_operador, exigir_admin


def criar_rotas(config: ConfigBackend, trilha: TrilhaAuditoria) -> APIRouter:
    rotas = APIRouter(prefix="/v1/auditoria", tags=["auditoria"])
    operador_autenticado = autenticar_operador(config)

    @rotas.get("")
    def listar(
        limite: int = Query(default=100, le=1000),
        evento_id: str | None = None,
        identidade: Identidade = Depends(operador_autenticado),
    ):
        exigir_admin(identidade)
        return {
            "total": trilha.total(),
            "entradas": [entrada.como_dict() for entrada in trilha.listar(limite, evento_id)],
        }

    @rotas.get("/verificar")
    def verificar(identidade: Identidade = Depends(operador_autenticado)):
        exigir_admin(identidade)
        relatorio = trilha.verificar()
        return {
            "integra": relatorio.integra,
            "total": relatorio.total,
            "problemas": list(relatorio.problemas),
            "resumo": str(relatorio),
        }

    return rotas
