"""Acesso a dados, isolado.

SQLite no MVP. Todo SQL do sistema mora neste arquivo, para que trocar por
Postgres na operação contratada não toque nenhum módulo de negócio.

Migrações são versionadas e aplicadas em ordem. Alteração manual de schema não
existe: o banco de um piloto em produção precisa poder ser reconstruído a partir
do código.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

STATUS_PENDENTE = "pendente_revisao"
STATUS_CONFIRMADO = "confirmado"
STATUS_CONFIRMADO_MULTA = "confirmado_multa"
STATUS_REJEITADO = "rejeitado"

STATUS_VALIDOS = (
    STATUS_PENDENTE,
    STATUS_CONFIRMADO,
    STATUS_CONFIRMADO_MULTA,
    STATUS_REJEITADO,
)

MIGRACOES: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE nos (
            no_id            TEXT PRIMARY KEY,
            descricao        TEXT NOT NULL DEFAULT '',
            latitude         REAL,
            longitude        REAL,
            modo             TEXT,
            primeiro_contato TEXT NOT NULL,
            ultimo_contato   TEXT NOT NULL,
            ultimo_heartbeat TEXT,
            bateria_pct      REAL
        );

        CREATE TABLE eventos (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_id           TEXT NOT NULL,
            no_id               TEXT NOT NULL REFERENCES nos(no_id),
            status              TEXT NOT NULL,
            modo                TEXT NOT NULL,
            recebido_em         TEXT NOT NULL,
            capturado_em        TEXT NOT NULL,
            instante_pico_epoch REAL NOT NULL,
            acao                TEXT NOT NULL,
            versao_politica     TEXT NOT NULL,
            classe              TEXT,
            score_alvo          REAL,
            versao_modelo       TEXT,
            azimute_graus       REAL,
            margem_graus        REAL,
            confianca_doa       REAL,
            spl_db              REAL,
            spl_valor_legal     INTEGER NOT NULL DEFAULT 0,
            instrumento_db      REAL,
            instrumento_legal   INTEGER NOT NULL DEFAULT 0,
            n_imagens           INTEGER NOT NULL DEFAULT 0,
            hash_manifesto      TEXT NOT NULL,
            caminho_pacote      TEXT NOT NULL,
            UNIQUE (no_id, evento_id)
        );

        CREATE INDEX idx_eventos_status ON eventos(status);
        CREATE INDEX idx_eventos_no ON eventos(no_id, instante_pico_epoch);

        CREATE TABLE revisoes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            evento      INTEGER NOT NULL REFERENCES eventos(id),
            operador    TEXT NOT NULL,
            decisao     TEXT NOT NULL,
            observacao  TEXT NOT NULL DEFAULT '',
            decidido_em TEXT NOT NULL
        );

        CREATE INDEX idx_revisoes_evento ON revisoes(evento);

        CREATE TABLE rejeicoes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            no_id       TEXT,
            evento_id   TEXT,
            motivo      TEXT NOT NULL,
            recebido_em TEXT NOT NULL
        );

        CREATE TABLE heartbeats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            no_id       TEXT NOT NULL,
            recebido_em TEXT NOT NULL,
            bateria_pct REAL,
            detalhe     TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX idx_heartbeats_no ON heartbeats(no_id, recebido_em);
        """,
    ),
]


def conectar(caminho: str | Path) -> sqlite3.Connection:
    caminho = Path(caminho)
    if str(caminho) != ":memory:":
        caminho.parent.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(caminho, check_same_thread=False)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    conexao.execute("PRAGMA journal_mode = WAL")
    aplicar_migracoes(conexao)
    return conexao


def aplicar_migracoes(conexao: sqlite3.Connection) -> list[int]:
    conexao.execute(
        """
        CREATE TABLE IF NOT EXISTS migracoes (
            versao     INTEGER PRIMARY KEY,
            aplicada_em TEXT NOT NULL
        )
        """
    )
    ja_aplicadas = {
        linha["versao"] for linha in conexao.execute("SELECT versao FROM migracoes")
    }
    aplicadas: list[int] = []
    for versao, sql in MIGRACOES:
        if versao in ja_aplicadas:
            continue
        conexao.executescript(sql)
        conexao.execute(
            "INSERT INTO migracoes (versao, aplicada_em) VALUES (?, datetime('now'))",
            (versao,),
        )
        aplicadas.append(versao)
    conexao.commit()
    return aplicadas


@contextmanager
def transacao(conexao: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conexao
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise


# -- nós ---------------------------------------------------------------


def registrar_no(
    conexao: sqlite3.Connection,
    no_id: str,
    descricao: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    modo: str | None = None,
) -> None:
    conexao.execute(
        """
        INSERT INTO nos (no_id, descricao, latitude, longitude, modo,
                         primeiro_contato, ultimo_contato)
        VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(no_id) DO UPDATE SET
            ultimo_contato = datetime('now'),
            descricao = COALESCE(NULLIF(excluded.descricao, ''), nos.descricao),
            latitude  = COALESCE(excluded.latitude, nos.latitude),
            longitude = COALESCE(excluded.longitude, nos.longitude),
            modo      = COALESCE(excluded.modo, nos.modo)
        """,
        (no_id, descricao, latitude, longitude, modo),
    )


def listar_nos(conexao: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conexao.execute(
            """
            SELECT n.*,
                   (SELECT COUNT(*) FROM eventos e WHERE e.no_id = n.no_id) AS eventos,
                   (SELECT COUNT(*) FROM eventos e
                     WHERE e.no_id = n.no_id AND e.status = ?) AS pendentes
              FROM nos n
             ORDER BY n.no_id
            """,
            (STATUS_PENDENTE,),
        )
    )


def registrar_heartbeat(
    conexao: sqlite3.Connection, no_id: str, bateria_pct: float | None, detalhe: str
) -> None:
    conexao.execute(
        "INSERT INTO heartbeats (no_id, recebido_em, bateria_pct, detalhe) "
        "VALUES (?, datetime('now'), ?, ?)",
        (no_id, bateria_pct, detalhe),
    )
    conexao.execute(
        "UPDATE nos SET ultimo_heartbeat = datetime('now'), bateria_pct = ?, "
        "ultimo_contato = datetime('now') WHERE no_id = ?",
        (bateria_pct, no_id),
    )


# -- eventos -----------------------------------------------------------


def buscar_evento_por_chave(
    conexao: sqlite3.Connection, no_id: str, evento_id: str
) -> sqlite3.Row | None:
    return conexao.execute(
        "SELECT * FROM eventos WHERE no_id = ? AND evento_id = ?", (no_id, evento_id)
    ).fetchone()


def inserir_evento(conexao: sqlite3.Connection, campos: dict) -> int:
    """Insere sempre como pendente_revisao.

    O status não é parâmetro de propósito: não existe caminho de código que crie
    um evento já confirmado (D2). Confirmar é ação de operador, registrada em
    `revisoes`.
    """
    colunas = (
        "evento_id",
        "no_id",
        "status",
        "modo",
        "recebido_em",
        "capturado_em",
        "instante_pico_epoch",
        "acao",
        "versao_politica",
        "classe",
        "score_alvo",
        "versao_modelo",
        "azimute_graus",
        "margem_graus",
        "confianca_doa",
        "spl_db",
        "spl_valor_legal",
        "instrumento_db",
        "instrumento_legal",
        "n_imagens",
        "hash_manifesto",
        "caminho_pacote",
    )
    # Colunas NOT NULL ganham valor de partida: passar None explicitamente para
    # elas (o caso de um manifesto sem imagem, ou sem instrumento) quebraria a
    # inserção por um motivo que não é erro de dado.
    valores = {
        "spl_valor_legal": 0,
        "instrumento_legal": 0,
        "n_imagens": 0,
        **{chave: valor for chave, valor in campos.items() if valor is not None},
        "status": STATUS_PENDENTE,
    }
    cursor = conexao.execute(
        f"INSERT INTO eventos ({', '.join(colunas)}) "
        f"VALUES ({', '.join(':' + c for c in colunas)})",
        {coluna: valores.get(coluna) for coluna in colunas},
    )
    return int(cursor.lastrowid)


def registrar_rejeicao(
    conexao: sqlite3.Connection, no_id: str | None, evento_id: str | None, motivo: str
) -> None:
    """Pacote recusado não some: fica registrado com o motivo.

    Rejeição silenciosa esconderia exatamente o caso que mais interessa
    investigar — pacote corrompido em trânsito ou tentativa de adulteração.
    """
    conexao.execute(
        "INSERT INTO rejeicoes (no_id, evento_id, motivo, recebido_em) "
        "VALUES (?, ?, ?, datetime('now'))",
        (no_id, evento_id, motivo),
    )


def listar_eventos(
    conexao: sqlite3.Connection,
    status: str | None = None,
    no_id: str | None = None,
    limite: int = 50,
    desde: str | None = None,
    ate: str | None = None,
) -> list[sqlite3.Row]:
    condicoes, parametros = [], []
    if status:
        condicoes.append("status = ?")
        parametros.append(status)
    if no_id:
        condicoes.append("no_id = ?")
        parametros.append(no_id)
    if desde:
        condicoes.append("capturado_em >= ?")
        parametros.append(desde)
    if ate:
        condicoes.append("capturado_em <= ?")
        parametros.append(ate)

    onde = ("WHERE " + " AND ".join(condicoes)) if condicoes else ""
    parametros.append(limite)
    return list(
        conexao.execute(
            f"SELECT * FROM eventos {onde} ORDER BY instante_pico_epoch DESC LIMIT ?",
            parametros,
        )
    )


def buscar_evento(conexao: sqlite3.Connection, identificador: int) -> sqlite3.Row | None:
    return conexao.execute(
        "SELECT * FROM eventos WHERE id = ?", (identificador,)
    ).fetchone()


def contar_por_status(conexao: sqlite3.Connection) -> dict[str, int]:
    linhas = conexao.execute(
        "SELECT status, COUNT(*) AS total FROM eventos GROUP BY status"
    )
    return {status: 0 for status in STATUS_VALIDOS} | {
        linha["status"]: linha["total"] for linha in linhas
    }


# -- revisão -----------------------------------------------------------


def registrar_revisao(
    conexao: sqlite3.Connection,
    evento: int,
    operador: str,
    decisao: str,
    observacao: str,
    novo_status: str,
) -> None:
    conexao.execute(
        "INSERT INTO revisoes (evento, operador, decisao, observacao, decidido_em) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (evento, operador, decisao, observacao),
    )
    conexao.execute("UPDATE eventos SET status = ? WHERE id = ?", (novo_status, evento))


def listar_revisoes(conexao: sqlite3.Connection, evento: int) -> list[sqlite3.Row]:
    return list(
        conexao.execute(
            "SELECT * FROM revisoes WHERE evento = ? ORDER BY id", (evento,)
        )
    )
