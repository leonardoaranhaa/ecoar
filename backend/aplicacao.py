"""Composição do backend: junta as rotas, o banco e o armazenamento."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend import db
from backend.armazenamento import Armazenamento
from backend.config import ConfigBackend, carregar
from backend.ingestion_api.app import criar_rotas as rotas_de_ingestao
from backend.review_queue.rotas import criar_rotas as rotas_de_revisao

log = logging.getLogger("ecoar.backend")

VERSAO_API = "1.0"


def criar_app(config: ConfigBackend) -> FastAPI:
    conexao = db.conectar(config.banco)
    armazenamento = Armazenamento(raiz=Path(config.armazenamento))

    app = FastAPI(
        title="ECOAR",
        version=VERSAO_API,
        description=(
            "Fiscalização sonora inteligente — ingestão de evidência e fila de "
            "revisão humana. Opera em modo de triagem: os eventos alimentam "
            "priorização de fiscalização, não autuação automática."
        ),
    )
    app.state.config = config
    app.state.conexao = conexao
    app.state.armazenamento = armazenamento

    app.include_router(rotas_de_ingestao(config, conexao, armazenamento))
    app.include_router(rotas_de_revisao(config, conexao, armazenamento))

    @app.get("/v1/saude", tags=["operação"])
    def saude():
        return {
            "status": "ok",
            "versao": VERSAO_API,
            "eventos": db.contar_por_status(conexao),
        }

    # O painel é montado por último, de propósito: um mount em "/" casa com
    # qualquer caminho, e registrado antes engoliria as rotas da API.
    painel = Path(__file__).resolve().parent.parent / "dashboard"
    if painel.exists():
        app.mount("/", StaticFiles(directory=painel, html=True), name="painel")

    return app


def app_padrao() -> FastAPI:
    """Ponto de entrada para `uvicorn backend.aplicacao:app_padrao --factory`."""
    import os

    caminho = os.environ.get("ECOAR_CONFIG_BACKEND", "config/backend.exemplo.yaml")
    return criar_app(carregar(caminho))
