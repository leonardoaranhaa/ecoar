"""Trilha de auditoria encadeada por hash.

Cada entrada carrega o hash da entrada anterior. Alterar ou remover qualquer
entrada do histórico quebra a cadeia a partir dali, e a quebra é detectável por
qualquer pessoa que rode a verificação — inclusive a defesa de um autuado.

É isto que separa "temos um log" de "temos uma trilha que resiste a
contestação". Um log comum pode ser editado sem deixar rastro; uma hash-chain
não: o rastro é a própria matemática.

## O que registra

- cada evento recebido pela ingestão, e cada pacote rejeitado com o motivo;
- cada ação de revisão humana (quem confirmou/rejeitou, quando);
- cada acesso ao pacote de evidência de um evento;
- cada alerta de violação patrimonial;
- cada troca de modo de operação;
- cada ciclo de re-treino (quando a etapa 9 existir).

## Regra de conteúdo

Registra QUE algo aconteceu, com identificador de evento, operador e timestamp.
Nunca conteúdo de mídia, nunca texto de placa (D6). O que entra no detalhe é
metadado — score, ângulo, versão de política —, jamais o dado pessoal.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

# Tipos de evento de auditoria. Strings estáveis: elas viram parte do hash e
# aparecem em relatório — renomear quebraria a cadeia de bancos existentes.
EVENTO_RECEBIDO = "evento_recebido"
EVENTO_REJEITADO = "evento_rejeitado"
REVISAO = "revisao"
ACESSO_EVIDENCIA = "acesso_evidencia"
ALERTA_VIOLACAO = "alerta_violacao"
# Candidato de transiente do protótipo conceitual de disparo — NUNCA
# "disparo confirmado" (docs/DECISIONS.md D16). O nome do próprio tipo de
# evento carrega o aviso de que não é uma classificação validada.
ALERTA_DISPARO_CONCEITO = "alerta_disparo_conceito_nao_validado"
TROCA_DE_MODO = "troca_de_modo"
RETREINO = "retreino"

# Âncora da cadeia: o hash "anterior" da primeira entrada. Fixo e conhecido,
# para que a verificação saiba onde a cadeia começa.
GENESE = "sha256:" + "0" * 64


ESQUEMA = """
CREATE TABLE IF NOT EXISTS auditoria (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    registrado_em TEXT NOT NULL,
    tipo         TEXT NOT NULL,
    ator         TEXT NOT NULL,
    evento_id    TEXT,
    detalhe      TEXT NOT NULL DEFAULT '{}',
    hash_anterior TEXT NOT NULL,
    hash         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auditoria_evento ON auditoria(evento_id);
"""


@dataclass(frozen=True)
class Entrada:
    seq: int
    registrado_em: str
    tipo: str
    ator: str
    evento_id: str | None
    detalhe: dict
    hash_anterior: str
    hash: str

    def como_dict(self) -> dict:
        return {
            "seq": self.seq,
            "registrado_em": self.registrado_em,
            "tipo": self.tipo,
            "ator": self.ator,
            "evento_id": self.evento_id,
            "detalhe": self.detalhe,
            "hash_anterior": self.hash_anterior,
            "hash": self.hash,
        }


@dataclass(frozen=True)
class RelatorioAuditoria:
    integra: bool
    total: int
    problemas: tuple[str, ...] = ()

    def __str__(self) -> str:
        if self.integra:
            return f"cadeia íntegra: {self.total} entradas encadeadas"
        return "CADEIA QUEBRADA: " + "; ".join(self.problemas)


def _hash_entrada(
    seq: int,
    registrado_em: str,
    tipo: str,
    ator: str,
    evento_id: str | None,
    detalhe: dict,
    hash_anterior: str,
) -> str:
    """Hash canônico da entrada, incluindo o hash da anterior.

    A ordem e o conteúdo dos campos fazem parte do hash. Serialização canônica
    (chaves ordenadas, sem espaço) para que o mesmo conteúdo produza sempre o
    mesmo hash — condição para a verificação ser reproduzível por terceiros.
    """
    corpo = {
        "seq": seq,
        "registrado_em": registrado_em,
        "tipo": tipo,
        "ator": ator,
        "evento_id": evento_id,
        "detalhe": detalhe,
        "hash_anterior": hash_anterior,
    }
    bruto = json.dumps(corpo, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(bruto.encode("utf-8")).hexdigest()


class TrilhaAuditoria:
    """Trilha encadeada sobre a mesma conexão SQLite do backend."""

    def __init__(self, conexao: sqlite3.Connection) -> None:
        self._conexao = conexao
        self._conexao.executescript(ESQUEMA)
        self._conexao.commit()

    def registrar(
        self,
        tipo: str,
        ator: str,
        evento_id: str | None = None,
        detalhe: dict | None = None,
    ) -> Entrada:
        """Acrescenta uma entrada, encadeada à última.

        Não faz commit próprio: quando chamado dentro de uma transação de
        negócio (ingestão, revisão), a entrada de auditoria e a mudança de
        estado precisam ser atômicas — ou as duas acontecem, ou nenhuma.
        """
        detalhe = _sanitizar(detalhe or {})
        registrado_em = datetime.now(tz=timezone.utc).isoformat()

        ultima = self._conexao.execute(
            "SELECT seq, hash FROM auditoria ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        seq = (ultima["seq"] + 1) if ultima else 1
        hash_anterior = ultima["hash"] if ultima else GENESE

        detalhe_json = json.dumps(detalhe, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        hash_atual = _hash_entrada(
            seq, registrado_em, tipo, ator, evento_id, detalhe, hash_anterior
        )

        self._conexao.execute(
            "INSERT INTO auditoria (seq, registrado_em, tipo, ator, evento_id, "
            "detalhe, hash_anterior, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (seq, registrado_em, tipo, ator, evento_id, detalhe_json, hash_anterior, hash_atual),
        )
        return Entrada(
            seq=seq,
            registrado_em=registrado_em,
            tipo=tipo,
            ator=ator,
            evento_id=evento_id,
            detalhe=detalhe,
            hash_anterior=hash_anterior,
            hash=hash_atual,
        )

    def verificar(self) -> RelatorioAuditoria:
        """Recalcula a cadeia inteira e devolve o primeiro ponto de quebra.

        Não depende de nada externo: lê as entradas em ordem, refaz cada hash e
        confere que cada uma aponta para a anterior. Qualquer alteração,
        remoção ou reordenação aparece.
        """
        linhas = list(
            self._conexao.execute(
                "SELECT * FROM auditoria ORDER BY seq ASC"
            )
        )
        problemas: list[str] = []
        hash_anterior = GENESE
        seq_esperada = 1

        for linha in linhas:
            if linha["seq"] != seq_esperada:
                problemas.append(
                    f"salto na sequência: esperava {seq_esperada}, achei {linha['seq']} "
                    "(entrada removida ou reordenada)"
                )
            if linha["hash_anterior"] != hash_anterior:
                problemas.append(
                    f"entrada {linha['seq']}: elo quebrado — aponta para "
                    f"{linha['hash_anterior'][:16]}…, esperado {hash_anterior[:16]}…"
                )
            detalhe = json.loads(linha["detalhe"])
            recalculado = _hash_entrada(
                linha["seq"],
                linha["registrado_em"],
                linha["tipo"],
                linha["ator"],
                linha["evento_id"],
                detalhe,
                linha["hash_anterior"],
            )
            if recalculado != linha["hash"]:
                problemas.append(
                    f"entrada {linha['seq']}: conteúdo alterado depois de registrado "
                    "(o hash não confere)"
                )
            hash_anterior = linha["hash"]
            seq_esperada = linha["seq"] + 1
            if problemas:
                # Uma quebra invalida tudo a partir dali: parar no primeiro
                # ponto evita despejar uma cascata de erros derivados.
                break

        return RelatorioAuditoria(
            integra=not problemas, total=len(linhas), problemas=tuple(problemas)
        )

    def listar(self, limite: int = 100, evento_id: str | None = None) -> list[Entrada]:
        if evento_id:
            linhas = self._conexao.execute(
                "SELECT * FROM auditoria WHERE evento_id = ? ORDER BY seq DESC LIMIT ?",
                (evento_id, limite),
            )
        else:
            linhas = self._conexao.execute(
                "SELECT * FROM auditoria ORDER BY seq DESC LIMIT ?", (limite,)
            )
        return [
            Entrada(
                seq=linha["seq"],
                registrado_em=linha["registrado_em"],
                tipo=linha["tipo"],
                ator=linha["ator"],
                evento_id=linha["evento_id"],
                detalhe=json.loads(linha["detalhe"]),
                hash_anterior=linha["hash_anterior"],
                hash=linha["hash"],
            )
            for linha in linhas
        ]

    def total(self) -> int:
        return int(
            self._conexao.execute("SELECT COUNT(*) AS c FROM auditoria").fetchone()["c"]
        )


# Campos que nunca podem entrar no detalhe da auditoria — barreira contra dado
# pessoal vazar para a trilha por descuido de quem chama (D6).
_PROIBIDOS = {"placa", "placa_lida", "numero_placa", "ocr", "condutor", "cpf", "proprietario"}


def _sanitizar(detalhe: dict) -> dict:
    """Recusa dado pessoal no detalhe da auditoria.

    A trilha registra que um evento ocorreu, não quem era o veículo. Um campo
    proibido aqui é erro de programação, não dado a ser guardado — por isso
    levanta, em vez de mascarar em silêncio.
    """
    for chave in detalhe:
        if chave.lower() in _PROIBIDOS:
            raise ValueError(
                f"campo {chave!r} não pode entrar na trilha de auditoria: ela registra "
                "que um evento ocorreu, nunca a identificação do veículo (D6)"
            )
    return detalhe
