"""Cliente HTTP do nó e o remetente que esvazia a fila."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from edge.config import ConfigUplink
from edge.uplink.fila import TIPO_ALERTA, TIPO_EVENTO, TIPO_HEARTBEAT, FilaEnvio, Item

log = logging.getLogger("ecoar.uplink")


class EnvioRecusado(RuntimeError):
    """O backend recusou de forma definitiva. Retentar não resolveria."""


class EnvioFalhou(RuntimeError):
    """Falha temporária: rede, servidor fora do ar, tempo esgotado."""


@dataclass(frozen=True)
class Resposta:
    situacao: str
    corpo: dict


class ClienteBackend:
    def __init__(self, config: ConfigUplink, cliente_http: httpx.Client | None = None) -> None:
        if not config.token:
            raise EnvioRecusado(
                "uplink.token vazio: defina a variável de ambiente do token do nó. "
                "Sem token, todo envio voltaria 401 e a evidência ficaria parada na "
                "fila local até estourar o limite de tentativas."
            )
        self.config = config
        self._http = cliente_http or httpx.Client(
            base_url=config.url.rstrip("/"),
            timeout=config.timeout_s,
            headers={"Authorization": f"Bearer {config.token}"},
        )

    def fechar(self) -> None:
        self._http.close()

    def enviar_evento(self, caminho: str | Path) -> Resposta:
        caminho = Path(caminho)
        if not caminho.exists():
            raise EnvioRecusado(f"pacote sumiu do disco: {caminho}")
        with caminho.open("rb") as arquivo:
            return self._executar(
                "POST", "/v1/eventos", files={"pacote": (caminho.name, arquivo)}
            )

    def enviar_alerta(self, corpo: str) -> Resposta:
        return self._executar("POST", "/v1/alertas", json=json.loads(corpo))

    def enviar_heartbeat(self, corpo: str) -> Resposta:
        return self._executar("POST", "/v1/heartbeat", json=json.loads(corpo))

    def _executar(self, metodo: str, caminho: str, **argumentos) -> Resposta:
        try:
            resposta = self._http.request(metodo, caminho, **argumentos)
        except httpx.HTTPError as erro:
            raise EnvioFalhou(f"falha de rede: {erro}") from erro

        if resposta.is_success:
            try:
                return Resposta(situacao="ok", corpo=resposta.json())
            except ValueError:
                return Resposta(situacao="ok", corpo={})

        # 4xx é decisão do backend sobre o conteúdo: reenviar o mesmo bytes daria
        # o mesmo resultado. 5xx e rede são transitórios e merecem retentativa.
        # 429 é a exceção entre os 4xx: significa "depois", não "nunca".
        if 400 <= resposta.status_code < 500 and resposta.status_code != 429:
            raise EnvioRecusado(f"HTTP {resposta.status_code}: {resposta.text[:300]}")
        raise EnvioFalhou(f"HTTP {resposta.status_code}: {resposta.text[:200]}")


class Remetente:
    """Esvazia a fila em segundo plano, respeitando prioridade e espera."""

    def __init__(
        self,
        fila: FilaEnvio,
        cliente: ClienteBackend,
        intervalo_s: float = 2.0,
        apagar_apos_envio: bool = True,
    ) -> None:
        self.fila = fila
        self.cliente = cliente
        self.intervalo_s = intervalo_s
        self.apagar_apos_envio = apagar_apos_envio
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self.enviados = 0
        self.recusados = 0

    def iniciar(self) -> None:
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name="ecoar-uplink", daemon=True)
        self._thread.start()

    def parar(self, timeout: float = 5.0) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _laco(self) -> None:
        while not self._parar.is_set():
            if not self.despachar_um():
                self._parar.wait(self.intervalo_s)

    def despachar_um(self) -> bool:
        """Envia o próximo item elegível. Devolve False se não havia nada."""
        item = self.fila.proximo()
        if item is None:
            return False

        try:
            resposta = self._enviar(item)
        except EnvioRecusado as erro:
            self.recusados += 1
            log.error("envio %s recusado em definitivo: %s", item.tipo, erro)
            self.fila.descartar(item.id, str(erro))
            return True
        except EnvioFalhou as erro:
            ainda_tenta = self.fila.adiar(item.id, str(erro))
            nivel = log.warning if ainda_tenta else log.error
            nivel("envio %s adiado (tentativa %d): %s", item.tipo, item.tentativas + 1, erro)
            return True

        # Só aqui o item sai da fila: o backend confirmou e validou o hash.
        self.fila.confirmar(item.id)
        self.enviados += 1
        log.info(
            "envio %s confirmado (%s)", item.tipo, resposta.corpo.get("status", "ok")
        )

        if item.tipo == TIPO_EVENTO and item.caminho and self.apagar_apos_envio:
            Path(item.caminho).unlink(missing_ok=True)
        return True

    def despachar_tudo(self, limite: int = 1000) -> int:
        enviados = 0
        while enviados < limite and self.despachar_um():
            enviados += 1
        return enviados

    def _enviar(self, item: Item) -> Resposta:
        if item.tipo == TIPO_EVENTO:
            return self.cliente.enviar_evento(item.caminho)
        if item.tipo == TIPO_ALERTA:
            return self.cliente.enviar_alerta(item.corpo or "{}")
        if item.tipo == TIPO_HEARTBEAT:
            return self.cliente.enviar_heartbeat(item.corpo or "{}")
        raise EnvioRecusado(f"tipo de envio desconhecido: {item.tipo}")


class Heartbeat:
    """Sinal de vida periódico. A ausência dele é que vira alerta no painel."""

    def __init__(self, fila: FilaEnvio, intervalo_s: float, estado) -> None:
        self.fila = fila
        self.intervalo_s = intervalo_s
        self._estado = estado
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None

    def iniciar(self) -> None:
        self._parar.clear()
        self._thread = threading.Thread(
            target=self._laco, name="ecoar-heartbeat", daemon=True
        )
        self._thread.start()

    def parar(self, timeout: float = 5.0) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def pulsar(self) -> None:
        detalhe = self._estado() or {}
        self.fila.enfileirar_heartbeat(
            json.dumps(
                {"bateria_pct": detalhe.pop("bateria_pct", None), "detalhe": detalhe},
                ensure_ascii=False,
                default=str,
            )
        )

    def _laco(self) -> None:
        while not self._parar.is_set():
            try:
                self.pulsar()
            except Exception:  # noqa: BLE001 — heartbeat nunca derruba o nó
                log.exception("falha ao montar heartbeat")
            self._parar.wait(self.intervalo_s)


def agora() -> float:
    return time.time()
