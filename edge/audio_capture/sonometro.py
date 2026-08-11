"""Camada de adaptação do instrumento de medição (decisão D5).

ESTE É O ÚNICO ARQUIVO DO SISTEMA QUE CONHECE O PROTOCOLO DO INSTRUMENTO.

Trocar de modelo — Classe 2 na validação, Classe 1 na operação, outro
fabricante, outra forma de conexão — significa escrever uma classe aqui e
apontar `sonometro.tipo` na configuração do nó. Nenhum outro módulo muda. Se
algum dia um `import serial` aparecer fora deste arquivo, a decisão foi
quebrada.

Para integrar um instrumento novo:

1. herde de `SonometroReader`;
2. implemente `info()` (o que é o instrumento) e `_ler()` (o valor);
3. registre em `_IMPLEMENTACOES`;
4. rode `python -m edge.audio_capture.read_sonometro --config <arquivo>` e
   confira contra a leitura da própria plataforma do fabricante, em pelo menos
   5 níveis diferentes (checkpoint 3 de docs/hardware/README.md).

Cada fabricante define baud rate, comando e formato de resposta próprios. O
sintoma clássico de baud errado é silêncio, não erro.
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from edge.config import ConfigNo, ConfigSonometro


class InstrumentoIndisponivel(RuntimeError):
    """Não há leitura de instrumento certificado disponível.

    Em `modo=triagem` isso é normal e esperado — não há instrumento instalado.
    Em `modo=autuacao` é falha grave: sem medição legal, não há o que autuar.
    """


@dataclass(frozen=True)
class InfoInstrumento:
    """Identificação do instrumento, gravada em toda evidência."""

    tipo: str
    modelo: str | None = None
    fabricante: str | None = None
    classe: int | None = None  # IEC 61672
    certificado: str | None = None
    validade_calibracao: str | None = None
    valor_legal: bool = False

    def como_dict(self) -> dict[str, object]:
        return {
            "tipo": self.tipo,
            "modelo": self.modelo,
            "fabricante": self.fabricante,
            "classe_iec_61672": self.classe,
            "certificado": self.certificado,
            "validade_calibracao": self.validade_calibracao,
            "valor_legal": self.valor_legal,
        }


@dataclass(frozen=True)
class LeituraSonometro:
    db: float
    timestamp: float
    instrumento: InfoInstrumento
    ponderacao: str = "A"
    resposta: str = "fast"

    @property
    def valor_legal(self) -> bool:
        return self.instrumento.valor_legal

    def como_dict(self) -> dict[str, object]:
        return {
            "db": round(self.db, 2),
            "timestamp": self.timestamp,
            "ponderacao": self.ponderacao,
            "resposta": self.resposta,
            "valor_legal": self.valor_legal,
            "instrumento": self.instrumento.como_dict(),
        }


class SonometroReader(ABC):
    """Interface única de leitura do instrumento de medição."""

    @abstractmethod
    def info(self) -> InfoInstrumento: ...

    @abstractmethod
    def _ler(self) -> float:
        """Nível em dB, cru do instrumento. Levanta InstrumentoIndisponivel se falhar."""

    def abrir(self) -> None:
        return None

    def fechar(self) -> None:
        return None

    def ler_db(self) -> LeituraSonometro:
        return LeituraSonometro(
            db=self._ler(),
            timestamp=time.time(),
            instrumento=self.info(),
        )

    def __enter__(self) -> "SonometroReader":
        self.abrir()
        return self

    def __exit__(self, *_) -> None:
        self.fechar()


class SonometroAusente(SonometroReader):
    """Nenhum instrumento instalado — a configuração padrão em `modo=triagem`.

    Não finge um valor. Toda leitura falha explicitamente, para que o pacote de
    evidência registre a ausência em vez de um número inventado.
    """

    def info(self) -> InfoInstrumento:
        return InfoInstrumento(tipo="ausente", valor_legal=False)

    def _ler(self) -> float:
        raise InstrumentoIndisponivel(
            "nenhum instrumento de medição configurado (sonometro.tipo='ausente'). "
            "Esperado em modo=triagem — a evidência registra a ausência, e o SPL "
            "estimado do array segue marcado como sem valor legal."
        )


class SonometroMock(SonometroReader):
    """Instrumento simulado, para desenvolver sem o equipamento em mãos.

    Devolve uma sequência de valores de teste. Nunca tem valor legal, e a
    configuração recusa usá-lo em `modo=autuacao` — inclusive por acidente.
    """

    def __init__(self, valores: list[float] | None = None, base_db: float = 62.0) -> None:
        self._valores = list(valores) if valores else []
        self._posicao = 0
        self._base = base_db
        self._t0 = time.time()

    def info(self) -> InfoInstrumento:
        return InfoInstrumento(
            tipo="mock",
            modelo="instrumento simulado",
            valor_legal=False,
        )

    def _ler(self) -> float:
        if self._valores:
            valor = self._valores[self._posicao % len(self._valores)]
            self._posicao += 1
            return float(valor)
        # Sem sequência definida: ruído urbano plausível, determinístico no tempo.
        import math

        decorrido = time.time() - self._t0
        return self._base + 6.0 * math.sin(decorrido / 3.0) + 2.0 * math.sin(decorrido * 1.7)


class SonometroSerialGenerico(SonometroReader):
    """Leitura por porta serial — MOLDE, não driver pronto de nenhum modelo.

    Funciona com instrumentos que respondem a um comando em texto com uma linha
    contendo o valor. Antes de usar em campo, confira no manual do modelo: baud
    rate, comando de consulta, terminador de linha e unidade da resposta.

    Se o instrumento entrega os dados por rede (o caso mais comum em estação de
    monitoramento permanente), o certo é escrever uma classe irmã que fala a
    API do fabricante — não forçar serial.
    """

    PADRAO_VALOR = re.compile(r"(-?\d+(?:[.,]\d+)?)")

    def __init__(self, config: ConfigSonometro) -> None:
        self._config = config
        self._porta = None

    def info(self) -> InfoInstrumento:
        return InfoInstrumento(
            tipo="serial",
            modelo=self._config.modelo,
            fabricante=self._config.fabricante,
            classe=self._config.classe,
            certificado=self._config.certificado,
            validade_calibracao=self._config.validade_calibracao,
            valor_legal=self._config.tem_valor_legal,
        )

    def abrir(self) -> None:
        try:
            import serial  # noqa: PLC0415 — driver de hardware, import sob demanda
        except Exception as erro:  # pragma: no cover - depende do nó
            raise InstrumentoIndisponivel(
                "pyserial não está instalado. No nó de campo: "
                "pip install -r requirements-hardware.txt"
            ) from erro

        try:  # pragma: no cover - depende do nó
            self._porta = serial.Serial(
                port=self._config.porta,
                baudrate=self._config.baud,
                timeout=self._config.timeout_s,
            )
        except Exception as erro:  # pragma: no cover - depende do nó
            raise InstrumentoIndisponivel(
                f"não consegui abrir {self._config.porta} a {self._config.baud} baud: {erro}. "
                "Confira `ls /dev/ttyUSB* /dev/ttyACM*` e o baud rate no manual do modelo."
            ) from erro

    def fechar(self) -> None:  # pragma: no cover - depende do nó
        if self._porta is not None:
            self._porta.close()
            self._porta = None

    def _ler(self) -> float:  # pragma: no cover - depende do nó
        if self._porta is None:
            raise InstrumentoIndisponivel("porta serial não foi aberta")
        if self._config.comando:
            self._porta.write(self._config.comando.encode("ascii"))
        linha = self._porta.readline().decode("ascii", errors="ignore").strip()
        if not linha:
            raise InstrumentoIndisponivel(
                "instrumento não respondeu. Causa mais comum: baud rate diferente do "
                "que o manual do modelo especifica."
            )
        achado = self.PADRAO_VALOR.search(linha)
        if not achado:
            raise InstrumentoIndisponivel(f"resposta sem valor numérico reconhecível: {linha!r}")
        return float(achado.group(1).replace(",", "."))


_IMPLEMENTACOES = {
    "ausente": lambda config: SonometroAusente(),
    "mock": lambda config: SonometroMock(),
    "serial": SonometroSerialGenerico,
}


def criar_sonometro(config: ConfigNo) -> SonometroReader:
    """Instancia o leitor declarado na configuração, com a trava do modo.

    A trava é redundante com `edge/config.py` de propósito: a proibição de
    autuar com instrumento simulado precisa valer mesmo que alguém construa a
    configuração na mão, sem passar pelo carregador.
    """
    cfg = config.sonometro
    if config.modo != "triagem" and not cfg.tem_valor_legal:
        raise InstrumentoIndisponivel(
            f"modo={config.modo} exige instrumento com valor legal (Classe 1, certificado "
            f"declarado); configuração atual é tipo={cfg.tipo!r}, classe={cfg.classe!r}. "
            "Ver docs/legal/inmetro.md"
        )
    return _IMPLEMENTACOES[cfg.tipo](cfg)
