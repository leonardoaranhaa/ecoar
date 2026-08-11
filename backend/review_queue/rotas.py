"""Fila de revisão humana — a etapa que o desenho inteiro protege.

Nenhum evento vira estatística de priorização, dado de treino ou rascunho de
autuação sem passar por aqui (D2).

Duas regras de operação que estão no código, não só no processo:

- **`confirmado_multa` só existe em `modo=autuacao`.** O evento carrega o modo
  vigente no momento da captura; se ele foi capturado em triagem, confirmar
  como multa é recusado. Sem isso, um evento antigo poderia ser reclassificado
  depois que o modo mudasse.
- **Decisão não se apaga.** Corrigir é registrar uma nova revisão por cima; o
  histórico de quem decidiu o quê fica inteiro.
"""

from __future__ import annotations

import io
import logging
import wave
from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from backend import db
from backend.armazenamento import Armazenamento, MidiaNaoEncontrada
from backend.config import ConfigBackend
from backend.seguranca import Identidade, autenticar_operador
from edge.evidence_packager import ler_manifesto

log = logging.getLogger("ecoar.revisao")

CONFIRMAR = "confirmar"
REJEITAR = "rejeitar"
CONFIRMAR_MULTA = "confirmar_multa"


class PedidoRevisao(BaseModel):
    decisao: Literal["confirmar", "rejeitar", "confirmar_multa"]
    observacao: str = Field(default="", max_length=2000)


class RespostaRevisao(BaseModel):
    id: int
    status: str
    operador: str


def criar_rotas(config: ConfigBackend, conexao, armazenamento: Armazenamento) -> APIRouter:
    rotas = APIRouter(prefix="/v1", tags=["revisão"])
    operador_autenticado = autenticar_operador(config)

    @rotas.get("/eventos")
    def listar(
        status_filtro: str | None = Query(default=None, alias="status"),
        no_id: str | None = None,
        limite: int = Query(default=50, le=500),
        identidade: Identidade = Depends(operador_autenticado),
    ):
        if status_filtro and status_filtro not in db.STATUS_VALIDOS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"status inválido; use um de {list(db.STATUS_VALIDOS)}",
            )
        linhas = db.listar_eventos(conexao, status_filtro, no_id, limite)
        return {
            "total": len(linhas),
            "contagem": db.contar_por_status(conexao),
            "eventos": [_resumo(linha) for linha in linhas],
        }

    @rotas.get("/eventos/{identificador}")
    def detalhar(
        identificador: int, identidade: Identidade = Depends(operador_autenticado)
    ):
        linha = _exigir_evento(conexao, identificador)
        try:
            manifesto = ler_manifesto(linha["caminho_pacote"])
        except FileNotFoundError:
            manifesto = {}
            log.error("pacote ausente no disco: %s", linha["caminho_pacote"])

        return {
            **_resumo(linha),
            "manifesto": manifesto,
            "revisoes": [
                {
                    "operador": revisao["operador"],
                    "decisao": revisao["decisao"],
                    "observacao": revisao["observacao"],
                    "decidido_em": revisao["decidido_em"],
                }
                for revisao in db.listar_revisoes(conexao, identificador)
            ],
        }

    @rotas.post("/eventos/{identificador}/revisao", response_model=RespostaRevisao)
    def revisar(
        identificador: int,
        pedido: PedidoRevisao,
        identidade: Identidade = Depends(operador_autenticado),
    ):
        linha = _exigir_evento(conexao, identificador)

        if pedido.decisao == CONFIRMAR_MULTA and linha["modo"] != "autuacao":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "este evento foi capturado em modo=triagem: ele alimenta "
                    "priorização de fiscalização e não pode virar autuação. "
                    "Ver docs/legal/inmetro.md"
                ),
            )

        novo_status = {
            CONFIRMAR: db.STATUS_CONFIRMADO,
            CONFIRMAR_MULTA: db.STATUS_CONFIRMADO_MULTA,
            REJEITAR: db.STATUS_REJEITADO,
        }[pedido.decisao]

        with db.transacao(conexao):
            db.registrar_revisao(
                conexao,
                evento=identificador,
                operador=identidade.nome,
                decisao=pedido.decisao,
                observacao=pedido.observacao,
                novo_status=novo_status,
            )

        log.info(
            "evento %s: %s por %s", identificador, pedido.decisao, identidade.nome
        )
        return RespostaRevisao(
            id=identificador, status=novo_status, operador=identidade.nome
        )

    @rotas.get("/eventos/{identificador}/midia/{nome}")
    def midia(
        identificador: int,
        nome: str,
        identidade: Identidade = Depends(operador_autenticado),
    ):
        """Serve a mídia de dentro do pacote, sem nunca desempacotar para disco.

        Só nomes declarados no manifesto são servidos: o parâmetro vem da URL, e
        aceitar qualquer nome deixaria a leitura do zip escolher o arquivo.
        """
        linha = _exigir_evento(conexao, identificador)
        caminho = f"midia/{nome}"

        try:
            manifesto = ler_manifesto(linha["caminho_pacote"])
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="pacote não encontrado no disco")

        declarados = {(manifesto.get("audio") or {}).get("arquivo")} | {
            imagem.get("arquivo") for imagem in manifesto.get("imagens") or []
        }
        if caminho not in declarados:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="mídia não declarada no manifesto deste evento",
            )

        try:
            conteudo = armazenamento.ler_midia(linha["caminho_pacote"], caminho)
        except MidiaNaoEncontrada as erro:
            raise HTTPException(status_code=404, detail=str(erro))

        tipos = {".png": "image/png", ".jpg": "image/jpeg", ".wav": "audio/wav"}
        tipo = tipos.get(caminho[caminho.rfind(".") :], "application/octet-stream")
        return Response(content=conteudo, media_type=tipo)

    @rotas.get("/eventos/{identificador}/audio-audicao.wav")
    def audio_para_audicao(
        identificador: int, identidade: Identidade = Depends(operador_autenticado)
    ):
        """Versão mono de 16 bits, só para tocar no navegador.

        NÃO é a evidência: o áudio da evidência é o de 24 bits e 4 canais dentro
        do pacote, e é ele que o hash protege. Esta conversão existe porque o
        operador precisa ouvir o evento sem baixar e abrir um arquivo à parte.
        """
        linha = _exigir_evento(conexao, identificador)
        try:
            bruto = armazenamento.ler_midia(linha["caminho_pacote"], "midia/audio.wav")
        except (MidiaNaoEncontrada, FileNotFoundError) as erro:
            raise HTTPException(status_code=404, detail=str(erro))
        return Response(content=_para_audicao(bruto), media_type="audio/wav")

    @rotas.get("/nos")
    def nos(identidade: Identidade = Depends(operador_autenticado)):
        return {
            "nos": [
                {
                    "no_id": linha["no_id"],
                    "descricao": linha["descricao"],
                    "latitude": linha["latitude"],
                    "longitude": linha["longitude"],
                    "modo": linha["modo"],
                    "ultimo_contato": linha["ultimo_contato"],
                    "ultimo_heartbeat": linha["ultimo_heartbeat"],
                    "bateria_pct": linha["bateria_pct"],
                    "eventos": linha["eventos"],
                    "pendentes": linha["pendentes"],
                }
                for linha in db.listar_nos(conexao)
            ]
        }

    return rotas


def _exigir_evento(conexao, identificador: int):
    linha = db.buscar_evento(conexao, identificador)
    if linha is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="evento não encontrado")
    return linha


def _resumo(linha) -> dict:
    return {
        "id": linha["id"],
        "evento_id": linha["evento_id"],
        "no_id": linha["no_id"],
        "status": linha["status"],
        "modo": linha["modo"],
        "acao": linha["acao"],
        "capturado_em": linha["capturado_em"],
        "recebido_em": linha["recebido_em"],
        "classe": linha["classe"],
        "score_alvo": linha["score_alvo"],
        "versao_modelo": linha["versao_modelo"],
        "versao_politica": linha["versao_politica"],
        "azimute_graus": linha["azimute_graus"],
        "margem_graus": linha["margem_graus"],
        "confianca_doa": linha["confianca_doa"],
        "spl_db": linha["spl_db"],
        "spl_valor_legal": bool(linha["spl_valor_legal"]),
        "instrumento_db": linha["instrumento_db"],
        "instrumento_legal": bool(linha["instrumento_legal"]),
        "n_imagens": linha["n_imagens"],
        "hash_manifesto": linha["hash_manifesto"],
    }


def _para_audicao(bruto: bytes) -> bytes:
    """Converte o WAV multicanal de 24 bits em mono de 16 bits."""
    with wave.open(io.BytesIO(bruto), "rb") as entrada:
        canais = entrada.getnchannels()
        largura = entrada.getsampwidth()
        taxa = entrada.getframerate()
        quadros = entrada.readframes(entrada.getnframes())

    from edge.audio_capture.fontes import _bytes_para_float32

    amostras = _bytes_para_float32(quadros, largura, canais).mean(axis=1)
    pico = float(np.max(np.abs(amostras))) or 1.0
    inteiros = np.clip(amostras / pico * 0.9, -1.0, 1.0)
    dados = (inteiros * 32767).astype("<i2").tobytes()

    saida = io.BytesIO()
    with wave.open(saida, "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(taxa)
        arquivo.writeframes(dados)
    return saida.getvalue()
