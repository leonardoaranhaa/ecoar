"""Acesso a dados, isolado.

SQLite no MVP. Todo SQL do sistema mora neste arquivo, para que trocar por
Postgres na operação contratada não toque nenhum módulo de negócio.

Migrações são versionadas e aplicadas em ordem. Alteração manual de schema não
existe: o banco de um piloto em produção precisa poder ser reconstruído a partir
do código.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class _Conexao(sqlite3.Connection):
    """Conexão com um lock de escrita próprio.

    `sqlite3.Connection` não aceita atributos nem weakref; uma subclasse aceita.
    O lock serializa as transações porque o uvicorn compartilha esta conexão
    entre as threads do seu pool.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.lock_escrita = threading.RLock()


def _lock_de(conexao: sqlite3.Connection) -> threading.RLock | None:
    return getattr(conexao, "lock_escrita", None)

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
    (
        2,
        # Canal separado dos eventos acústicos (D14): violação é ocorrência
        # patrimonial, não fiscalização.
        """
        CREATE TABLE violacoes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            no_id       TEXT NOT NULL,
            tipo        TEXT NOT NULL,
            recebido_em TEXT NOT NULL,
            ocorrido_em TEXT NOT NULL,
            atendido    INTEGER NOT NULL DEFAULT 0,
            detalhe     TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX idx_violacoes_no ON violacoes(no_id, recebido_em);
        CREATE INDEX idx_violacoes_atendido ON violacoes(atendido);
        """,
    ),
]


def conectar(caminho: str | Path) -> sqlite3.Connection:
    caminho = Path(caminho)
    if str(caminho) != ":memory:":
        caminho.parent.mkdir(parents=True, exist_ok=True)
    # O uvicorn atende endpoints síncronos num pool de threads, todas
    # compartilhando esta conexão. Sem serialização, dois pedidos concorrentes
    # leem o mesmo "último seq" da trilha de auditoria e colidem na inserção. A
    # subclasse traz um lock que serializa as transações de escrita — volume de
    # piloto municipal não sente, e a corrida deixa de existir.
    conexao = sqlite3.connect(caminho, check_same_thread=False, factory=_Conexao)
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
    """Transação serializada entre threads.

    O lock precisa envolver a leitura e a escrita: a trilha de auditoria calcula
    o próximo `seq` lendo o último, e liberar o lock entre a leitura e o commit
    deixaria dois pedidos concorrentes escolherem o mesmo número.
    """
    lock = _lock_de(conexao)
    if lock is not None:
        lock.acquire()
    try:
        yield conexao
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    finally:
        if lock is not None:
            lock.release()


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


# -- violações (canal patrimonial, D14) --------------------------------


def registrar_violacao(
    conexao: sqlite3.Connection,
    no_id: str,
    tipo: str,
    ocorrido_em: str,
    detalhe: str,
) -> int:
    cursor = conexao.execute(
        "INSERT INTO violacoes (no_id, tipo, recebido_em, ocorrido_em, detalhe) "
        "VALUES (?, ?, datetime('now'), ?, ?)",
        (no_id, tipo, ocorrido_em, detalhe),
    )
    return int(cursor.lastrowid)


def listar_violacoes(
    conexao: sqlite3.Connection, apenas_pendentes: bool = False, limite: int = 100
) -> list[sqlite3.Row]:
    onde = "WHERE atendido = 0" if apenas_pendentes else ""
    return list(
        conexao.execute(
            f"SELECT * FROM violacoes {onde} ORDER BY recebido_em DESC LIMIT ?", (limite,)
        )
    )


def atender_violacao(conexao: sqlite3.Connection, violacao_id: int) -> bool:
    cursor = conexao.execute("UPDATE violacoes SET atendido = 1 WHERE id = ?", (violacao_id,))
    return cursor.rowcount > 0


# -- priorização e métricas (modo=triagem) -----------------------------

# Só evento CONFIRMADO por humano entra na priorização (D2): um evento
# pendente ou rejeitado não é ocorrência comprovada, e priorizar sobre ele
# mandaria a fiscalização para o lugar errado.
_STATUS_CONFIRMADOS = (STATUS_CONFIRMADO, STATUS_CONFIRMADO_MULTA)


def priorizacao_hora_dia(conexao: sqlite3.Connection) -> list[dict]:
    """Mapa de calor: quantos eventos confirmados por dia da semana × hora.

    É o entregável central em modo de triagem — responde "onde e quando",
    para a prefeitura mandar a blitz na hora que rende.
    """
    marcadores = ",".join("?" * len(_STATUS_CONFIRMADOS))
    linhas = conexao.execute(
        f"""
        SELECT CAST(strftime('%w', capturado_em) AS INTEGER) AS dia,
               CAST(strftime('%H', capturado_em) AS INTEGER) AS hora,
               COUNT(*) AS total
          FROM eventos
         WHERE status IN ({marcadores})
         GROUP BY dia, hora
        """,
        _STATUS_CONFIRMADOS,
    )
    return [dict(linha) for linha in linhas]


def priorizacao_por_no(conexao: sqlite3.Connection) -> list[dict]:
    """Ranking de pontos por eventos confirmados, com a geolocalização do nó."""
    marcadores = ",".join("?" * len(_STATUS_CONFIRMADOS))
    linhas = conexao.execute(
        f"""
        SELECT e.no_id AS no_id,
               n.descricao AS descricao,
               n.latitude AS latitude,
               n.longitude AS longitude,
               COUNT(*) AS confirmados,
               MAX(e.capturado_em) AS ultimo
          FROM eventos e
          LEFT JOIN nos n ON n.no_id = e.no_id
         WHERE e.status IN ({marcadores})
         GROUP BY e.no_id
         ORDER BY confirmados DESC
        """,
        _STATUS_CONFIRMADOS,
    )
    return [dict(linha) for linha in linhas]


def eventos_por_dia(conexao: sqlite3.Connection, dias: int = 30) -> list[dict]:
    linhas = conexao.execute(
        """
        SELECT date(capturado_em) AS dia,
               SUM(CASE WHEN status IN ('confirmado','confirmado_multa') THEN 1 ELSE 0 END) AS confirmados,
               SUM(CASE WHEN status = 'rejeitado' THEN 1 ELSE 0 END) AS rejeitados,
               COUNT(*) AS total
          FROM eventos
         GROUP BY dia
         ORDER BY dia DESC
         LIMIT ?
        """,
        (dias,),
    )
    return [dict(linha) for linha in linhas]


def taxa_de_rejeicao(conexao: sqlite3.Connection) -> dict:
    """Rejeitados sobre decididos — a taxa de falso positivo do sistema.

    Só conta o que já foi revisado: um evento pendente ainda não é acerto nem
    erro. Dividir pelo total incluindo pendentes subestimaria a taxa.
    """
    linha = conexao.execute(
        """
        SELECT
            SUM(CASE WHEN status IN ('confirmado','confirmado_multa') THEN 1 ELSE 0 END) AS confirmados,
            SUM(CASE WHEN status = 'rejeitado' THEN 1 ELSE 0 END) AS rejeitados,
            SUM(CASE WHEN status = 'pendente_revisao' THEN 1 ELSE 0 END) AS pendentes
          FROM eventos
        """
    ).fetchone()
    confirmados = linha["confirmados"] or 0
    rejeitados = linha["rejeitados"] or 0
    decididos = confirmados + rejeitados
    return {
        "confirmados": confirmados,
        "rejeitados": rejeitados,
        "pendentes": linha["pendentes"] or 0,
        "decididos": decididos,
        "taxa_rejeicao": round(rejeitados / decididos, 4) if decididos else None,
    }


def versoes_de_modelo(conexao: sqlite3.Connection) -> list[dict]:
    """Versões de classificador vistas nos eventos, com quantos eventos cada uma.

    Enquanto o pipeline de re-treino (etapa 9) não existe, esta é a visão
    honesta de "quais modelos rodaram": derivada do que a evidência registrou,
    não de um catálogo inventado.
    """
    linhas = conexao.execute(
        """
        SELECT versao_modelo AS versao, COUNT(*) AS eventos,
               MIN(capturado_em) AS primeiro, MAX(capturado_em) AS ultimo
          FROM eventos
         WHERE versao_modelo IS NOT NULL
         GROUP BY versao_modelo
         ORDER BY ultimo DESC
        """
    )
    return [dict(linha) for linha in linhas]
