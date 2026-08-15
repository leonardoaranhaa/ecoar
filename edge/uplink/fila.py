"""Fila de envio persistente.

O nó fica num poste, com 4G que cai, energia que oscila e reboot que acontece.
Enviar direto e torcer perderia evidência — e evidência perdida não volta.

Três propriedades que a fila garante:

**Sobrevive a reboot.** SQLite em disco, não lista em memória.

**Tem prioridade.** Alerta de violação patrimonial sai na frente de qualquer
pacote acústico pendente: quando alguém está arrancando o equipamento do poste,
o que importa é o alerta chegar, não a fila estar em ordem cronológica.

**Só apaga depois da confirmação.** O item sai da fila quando o backend
confirma o recebimento **e** a validação do hash. Confirmação parcial não apaga
nada.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

PRIORIDADE_ALERTA = 0
PRIORIDADE_EVENTO = 5
PRIORIDADE_HEARTBEAT = 9

TIPO_EVENTO = "evento"
TIPO_ALERTA = "alerta"
TIPO_HEARTBEAT = "heartbeat"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS envios (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo              TEXT NOT NULL,
    prioridade        INTEGER NOT NULL,
    caminho           TEXT,
    corpo             TEXT,
    criado_em         REAL NOT NULL,
    tentativas        INTEGER NOT NULL DEFAULT 0,
    proxima_tentativa REAL NOT NULL DEFAULT 0,
    ultimo_erro       TEXT,
    situacao          TEXT NOT NULL DEFAULT 'pendente'
);
CREATE INDEX IF NOT EXISTS idx_envios_ordem
    ON envios(situacao, prioridade, proxima_tentativa, id);
"""

SITUACAO_PENDENTE = "pendente"
SITUACAO_MORTO = "morto"


@dataclass(frozen=True)
class Item:
    id: int
    tipo: str
    prioridade: int
    caminho: str | None
    corpo: str | None
    tentativas: int
    ultimo_erro: str | None


class FilaEnvio:
    """Fila compartilhada entre quatro threads do nó (eventos, tamper,
    heartbeat, remetente) — todas enfileiram ou drenam a mesma fila ao mesmo
    tempo, o tempo todo, em operação normal.

    `sqlite3.Connection` não é segura para chamadas concorrentes vindas de
    threads diferentes, mesmo com `check_same_thread=False` (que só desliga a
    checagem, não adiciona serialização): duas execuções ao mesmo tempo podem
    embaralhar o cursor da outra. Medido sem o lock: ~10% das operações
    concorrentes falhavam (`OperationalError`, `SystemError`, `lastrowid`
    vindo `None`) — evidência que nunca chegaria a sair do nó, sem aviso
    nenhum além de uma linha de log. O lock serializa toda chamada à conexão,
    inclusive leitura+escrita de `adiar()`, que precisa ser atômica.
    """

    def __init__(self, caminho: str | Path, tentativas_maximas: int = 12) -> None:
        self.caminho = Path(caminho)
        if str(self.caminho) != ":memory:":
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.tentativas_maximas = tentativas_maximas
        self._lock = threading.RLock()
        self._conexao = sqlite3.connect(self.caminho, check_same_thread=False)
        self._conexao.row_factory = sqlite3.Row
        self._conexao.executescript(ESQUEMA)
        self._conexao.commit()

    def fechar(self) -> None:
        self._conexao.close()

    # -- entrada ---------------------------------------------------------

    def enfileirar(
        self,
        tipo: str,
        prioridade: int,
        caminho: str | Path | None = None,
        corpo: str | None = None,
    ) -> int:
        with self._lock:
            cursor = self._conexao.execute(
                "INSERT INTO envios (tipo, prioridade, caminho, corpo, criado_em, "
                "proxima_tentativa) VALUES (?, ?, ?, ?, ?, 0)",
                (tipo, prioridade, str(caminho) if caminho else None, corpo, time.time()),
            )
            self._conexao.commit()
            return int(cursor.lastrowid)

    def enfileirar_evento(self, caminho: str | Path) -> int:
        return self.enfileirar(TIPO_EVENTO, PRIORIDADE_EVENTO, caminho=caminho)

    def enfileirar_alerta(self, corpo: str) -> int:
        return self.enfileirar(TIPO_ALERTA, PRIORIDADE_ALERTA, corpo=corpo)

    def enfileirar_heartbeat(self, corpo: str) -> int:
        """Heartbeat antigo é descartado: só o mais recente interessa.

        Uma fila com cem heartbeats acumulados de uma noite sem sinal atrasaria
        o que importa e não diria nada além do que o último já diz.
        """
        # Um lock só (RLock reentra em enfileirar()): sem isso, outra thread
        # poderia enfileirar um heartbeat entre o DELETE e o INSERT, e os dois
        # ficariam pendentes ao mesmo tempo — o que a função promete não fazer.
        with self._lock:
            self._conexao.execute(
                "DELETE FROM envios WHERE tipo = ? AND situacao = ?",
                (TIPO_HEARTBEAT, SITUACAO_PENDENTE),
            )
            return self.enfileirar(TIPO_HEARTBEAT, PRIORIDADE_HEARTBEAT, corpo=corpo)

    # -- saída -----------------------------------------------------------

    def proximo(self, agora: float | None = None) -> Item | None:
        agora = time.time() if agora is None else agora
        with self._lock:
            linha = self._conexao.execute(
                "SELECT * FROM envios WHERE situacao = ? AND proxima_tentativa <= ? "
                "ORDER BY prioridade, proxima_tentativa, id LIMIT 1",
                (SITUACAO_PENDENTE, agora),
            ).fetchone()
        if linha is None:
            return None
        return Item(
            id=linha["id"],
            tipo=linha["tipo"],
            prioridade=linha["prioridade"],
            caminho=linha["caminho"],
            corpo=linha["corpo"],
            tentativas=linha["tentativas"],
            ultimo_erro=linha["ultimo_erro"],
        )

    def confirmar(self, item_id: int) -> None:
        with self._lock:
            self._conexao.execute("DELETE FROM envios WHERE id = ?", (item_id,))
            self._conexao.commit()

    def adiar(self, item_id: int, erro: str, agora: float | None = None) -> bool:
        """Registra a falha e agenda nova tentativa. Devolve False se desistiu.

        Espera progressiva: 2 s, 4 s, 8 s… até 10 minutos. Sem teto, uma noite
        sem sinal viraria uma tentativa por hora; sem progressão, o nó martelaria
        o rádio em vão e gastaria bateria.

        Leitura (tentativas atuais) e escrita precisam do mesmo lock: sem isso,
        duas chamadas concorrentes para o mesmo item poderiam ler a mesma
        contagem e a segunda sobrescreveria o incremento da primeira.
        """
        agora = time.time() if agora is None else agora
        with self._lock:
            linha = self._conexao.execute(
                "SELECT tentativas FROM envios WHERE id = ?", (item_id,)
            ).fetchone()
            if linha is None:
                return False

            tentativas = int(linha["tentativas"]) + 1
            if tentativas >= self.tentativas_maximas:
                self._conexao.execute(
                    "UPDATE envios SET situacao = ?, tentativas = ?, ultimo_erro = ? "
                    "WHERE id = ?",
                    (SITUACAO_MORTO, tentativas, erro, item_id),
                )
                self._conexao.commit()
                return False

            espera = min(600.0, 2.0**tentativas)
            self._conexao.execute(
                "UPDATE envios SET tentativas = ?, proxima_tentativa = ?, ultimo_erro = ? "
                "WHERE id = ?",
                (tentativas, agora + espera, erro, item_id),
            )
            self._conexao.commit()
            return True

    def descartar(self, item_id: int, motivo: str) -> None:
        """Recusa definitiva do backend: retentar não resolveria.

        Pacote que o backend considera não íntegro não fica tentando para
        sempre — ele travaria a fila atrás de si. Sai da fila ativa, mas fica
        registrado como morto, e o arquivo continua no disco para inspeção.
        """
        with self._lock:
            self._conexao.execute(
                "UPDATE envios SET situacao = ?, ultimo_erro = ? WHERE id = ?",
                (SITUACAO_MORTO, motivo, item_id),
            )
            self._conexao.commit()

    # -- estado ----------------------------------------------------------

    def pendentes(self) -> int:
        with self._lock:
            return int(
                self._conexao.execute(
                    "SELECT COUNT(*) AS total FROM envios WHERE situacao = ?",
                    (SITUACAO_PENDENTE,),
                ).fetchone()["total"]
            )

    def mortos(self) -> int:
        with self._lock:
            return int(
                self._conexao.execute(
                    "SELECT COUNT(*) AS total FROM envios WHERE situacao = ?",
                    (SITUACAO_MORTO,),
                ).fetchone()["total"]
            )

    def estado(self) -> dict[str, int]:
        with self._lock:
            return {"pendentes": self.pendentes(), "mortos": self.mortos()}
