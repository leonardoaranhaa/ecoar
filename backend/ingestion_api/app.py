"""Porta de entrada: recebe pacotes de evidência e heartbeats dos nós.

O que este módulo garante, e que o resto do sistema depende:

1. **O hash é revalidado aqui.** Confiar no que o nó afirma sobre a própria
   evidência esvaziaria a cadeia de custódia. Pacote que não bate é recusado.
2. **Todo evento entra como `pendente_revisao`.** Não existe parâmetro para
   entrar diferente (D2).
3. **Rejeição não é silenciosa.** Pacote recusado fica registrado com o motivo.
4. **Reenvio é idempotente.** O nó só apaga o pacote da fila local depois da
   confirmação; se a confirmação se perder no 4G, ele reenvia — e reenvio não
   pode virar evento duplicado na fila do operador.
"""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from backend import db
from backend.armazenamento import Armazenamento
from backend.audit_log import (
    ALERTA_VIOLACAO,
    EVENTO_RECEBIDO,
    EVENTO_REJEITADO,
    TrilhaAuditoria,
)
from backend.config import ConfigBackend
from backend.seguranca import autenticar_no
from edge.evidence_packager import verificar_pacote

log = logging.getLogger("ecoar.ingestao")


class RespostaIngestao(BaseModel):
    status: str = Field(description="recebido | ja_recebido")
    id: int
    evento_id: str
    situacao: str


class Heartbeat(BaseModel):
    bateria_pct: float | None = None
    detalhe: dict = Field(default_factory=dict)


class AlertaViolacao(BaseModel):
    tipo: str
    timestamp: float | None = None
    capturado_em: str | None = None
    detalhe: dict = Field(default_factory=dict)
    imagem: str | None = None
    canal: str | None = None


def criar_rotas(
    config: ConfigBackend,
    conexao,
    armazenamento: Armazenamento,
    trilha: TrilhaAuditoria,
) -> APIRouter:
    rotas = APIRouter(prefix="/v1", tags=["ingestão"])
    no_autenticado = autenticar_no(config)

    @rotas.post(
        "/eventos",
        response_model=RespostaIngestao,
        status_code=status.HTTP_201_CREATED,
    )
    async def receber_evento(
        request: Request,
        pacote: UploadFile = File(description="arquivo .ecoar gerado pelo nó"),
        no_id: str = Depends(no_autenticado),
    ):
        conteudo = await pacote.read()
        if len(conteudo) > config.tamanho_maximo_bytes:
            with db.transacao(conexao):
                db.registrar_rejeicao(conexao, no_id, None, "pacote acima do tamanho máximo")
                trilha.registrar(
                    EVENTO_REJEITADO, ator=no_id, detalhe={"motivo": "acima do tamanho máximo"}
                )
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"pacote acima de {config.tamanho_maximo_pacote_mb} MB",
            )

        with tempfile.NamedTemporaryFile(suffix=".ecoar", delete=False) as temporario:
            temporario.write(conteudo)
            caminho_temporario = Path(temporario.name)

        try:
            relatorio = verificar_pacote(caminho_temporario)
            manifesto = relatorio.manifesto or {}
            evento_id = manifesto.get("evento_id")

            if not relatorio.valido:
                motivo = "; ".join(relatorio.problemas)
                with db.transacao(conexao):
                    db.registrar_rejeicao(conexao, no_id, evento_id, motivo)
                    trilha.registrar(
                        EVENTO_REJEITADO,
                        ator=no_id,
                        evento_id=evento_id,
                        detalhe={"motivo": "pacote não íntegro", "problemas": list(relatorio.problemas)},
                    )
                log.warning("pacote recusado do nó %s: %s", no_id, motivo)
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"erro": "pacote não íntegro", "problemas": relatorio.problemas},
                )

            no_do_manifesto = (manifesto.get("no") or {}).get("no_id")
            if no_do_manifesto != no_id:
                motivo = (
                    f"o token autentica o nó {no_id!r} mas o manifesto declara "
                    f"{no_do_manifesto!r}"
                )
                with db.transacao(conexao):
                    db.registrar_rejeicao(conexao, no_id, evento_id, motivo)
                    trilha.registrar(
                        EVENTO_REJEITADO,
                        ator=no_id,
                        evento_id=evento_id,
                        detalhe={"motivo": "nó do token difere do manifesto"},
                    )
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=motivo)

            existente = db.buscar_evento_por_chave(conexao, no_id, evento_id)
            if existente is not None:
                return RespostaIngestao(
                    status="ja_recebido",
                    id=int(existente["id"]),
                    evento_id=evento_id,
                    situacao=existente["status"],
                )

            # `instante_pico_epoch` vira ano/mês/dia no caminho de guarda
            # (armazenamento.caminho_de). Um valor absurdo — relógio de RTC
            # corrompido no campo é a causa mais provável, não só um manifesto
            # malicioso — faz datetime.fromtimestamp() estourar OverflowError/
            # OSError, e isso não pode virar 500 sem registro: a garantia #3
            # deste módulo é que toda rejeição fica registrada com o motivo.
            try:
                instante = float(manifesto.get("instante_pico_epoch") or 0.0)
                datetime.fromtimestamp(instante, tz=timezone.utc)  # só valida o intervalo
            except (TypeError, ValueError, OverflowError, OSError) as erro:
                motivo = f"instante_pico_epoch inválido no manifesto: {erro}"
                with db.transacao(conexao):
                    db.registrar_rejeicao(conexao, no_id, evento_id, motivo)
                    trilha.registrar(
                        EVENTO_REJEITADO,
                        ator=no_id,
                        evento_id=evento_id,
                        detalhe={"motivo": "instante_pico_epoch inválido"},
                    )
                log.warning("pacote recusado do nó %s: %s", no_id, motivo)
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"erro": "pacote não íntegro", "problemas": [motivo]},
                ) from erro

            destino = armazenamento.guardar(conteudo, no_id, evento_id, instante)

            decisao = manifesto.get("decisao") or {}
            with db.transacao(conexao):
                geo = (manifesto.get("no") or {}).get("geolocalizacao") or {}
                db.registrar_no(
                    conexao,
                    no_id=no_id,
                    latitude=geo.get("latitude"),
                    longitude=geo.get("longitude"),
                    modo=manifesto.get("modo"),
                )
                identificador = db.inserir_evento(
                    conexao, _campos_do_manifesto(manifesto, no_id, instante, destino)
                )
                # Metadado, nunca conteúdo de placa (D6). O que amarra a
                # evidência à trilha é o hash do manifesto.
                trilha.registrar(
                    EVENTO_RECEBIDO,
                    ator=no_id,
                    evento_id=evento_id,
                    detalhe={
                        "acao": decisao.get("acao"),
                        "versao_politica": decisao.get("versao_politica"),
                        "hash_manifesto": manifesto.get("hash_manifesto"),
                        "modo": manifesto.get("modo"),
                    },
                )

            log.info(
                "evento %s do nó %s recebido (%s)",
                evento_id,
                no_id,
                decisao.get("acao"),
            )
            return RespostaIngestao(
                status="recebido",
                id=identificador,
                evento_id=evento_id,
                situacao=db.STATUS_PENDENTE,
            )
        finally:
            caminho_temporario.unlink(missing_ok=True)

    @rotas.post("/alertas", status_code=status.HTTP_201_CREATED)
    def receber_alerta(dados: AlertaViolacao, no_id: str = Depends(no_autenticado)):
        """Canal patrimonial (D14), separado dos eventos acústicos.

        Não passa pela fila de revisão de fiscalização: é ocorrência
        operacional. E vai para a trilha de auditoria como `alerta_violacao`.
        """
        # A trilha registra que houve violação, com o tipo e o nó — nunca placa.
        detalhe = {k: v for k, v in dados.detalhe.items() if k.lower() not in ("placa", "condutor")}
        with db.transacao(conexao):
            db.registrar_no(conexao, no_id=no_id)
            identificador = db.registrar_violacao(
                conexao,
                no_id=no_id,
                tipo=dados.tipo,
                ocorrido_em=dados.capturado_em or _agora_iso(),
                detalhe=json.dumps(detalhe, ensure_ascii=False),
            )
            trilha.registrar(
                ALERTA_VIOLACAO,
                ator=no_id,
                detalhe={"tipo": dados.tipo, **detalhe},
            )
        log.warning("VIOLAÇÃO no nó %s: %s", no_id, dados.tipo)
        return {"status": "registrado", "id": identificador, "tipo": dados.tipo}

    @rotas.post("/heartbeat", status_code=status.HTTP_202_ACCEPTED)
    def receber_heartbeat(dados: Heartbeat, no_id: str = Depends(no_autenticado)):
        with db.transacao(conexao):
            db.registrar_no(conexao, no_id=no_id)
            db.registrar_heartbeat(
                conexao,
                no_id,
                dados.bateria_pct,
                json.dumps(dados.detalhe, ensure_ascii=False),
            )
        return {"status": "ok"}

    return rotas


def _campos_do_manifesto(
    manifesto: dict, no_id: str, instante: float, destino: Path
) -> dict:
    decisao = manifesto.get("decisao") or {}
    classificacao = manifesto.get("classificacao") or {}
    localizacao = manifesto.get("localizacao") or {}
    spl = manifesto.get("spl_estimado") or {}
    instrumento = manifesto.get("medicao_instrumento") or {}

    return {
        "evento_id": manifesto.get("evento_id"),
        "no_id": no_id,
        "modo": manifesto.get("modo"),
        "recebido_em": _agora_iso(),
        "capturado_em": manifesto.get("capturado_em"),
        "instante_pico_epoch": instante,
        "acao": decisao.get("acao"),
        "versao_politica": decisao.get("versao_politica"),
        "classe": classificacao.get("classe"),
        "score_alvo": classificacao.get("score_alvo"),
        "versao_modelo": classificacao.get("versao_modelo"),
        "azimute_graus": localizacao.get("azimute_graus"),
        "margem_graus": localizacao.get("margem_graus"),
        "confianca_doa": localizacao.get("confianca"),
        "spl_db": spl.get("db"),
        "spl_valor_legal": int(bool(spl.get("valor_legal"))),
        "instrumento_db": instrumento.get("db"),
        "instrumento_legal": int(bool(instrumento.get("valor_legal"))),
        "n_imagens": len(manifesto.get("imagens") or []),
        "hash_manifesto": manifesto.get("hash_manifesto"),
        "caminho_pacote": str(destino),
    }


def _agora_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
