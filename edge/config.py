"""Configuração do nó de campo.

Fail-closed por desenho: configuração inválida aborta a inicialização em vez de
assumir um padrão conveniente. E `modo=autuacao` só carrega com declaração
completa de base normativa e instrumento certificado — ver docs/legal/inmetro.md.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

MODO_TRIAGEM = "triagem"
MODO_AUTUACAO = "autuacao"
MODOS = (MODO_TRIAGEM, MODO_AUTUACAO)

PONDERACOES = ("A", "Z")

_ENV = re.compile(r"^\$\{([A-Z0-9_]+)(?::-(.*))?\}$")


class ConfiguracaoInvalida(RuntimeError):
    """Configuração recusada. O nó não sobe."""


@dataclass(frozen=True)
class Geolocalizacao:
    latitude: float
    longitude: float

    def como_dict(self) -> dict[str, float]:
        return {"latitude": self.latitude, "longitude": self.longitude}


@dataclass(frozen=True)
class ConfigArray:
    """Geometria física do array, medida na montagem — não é constante de código.

    O raio precisa bater com a régua. Erro aqui vira erro sistemático de ângulo
    em todos os eventos do nó, e é a causa mais comum de "o ângulo está sempre
    errado mesmo com áudio limpo".
    """

    geometria: str = "circular"
    raio_m: float = 0.045
    n_microfones: int = 4
    azimute_offset_graus: float = 0.0
    velocidade_som_ms: float = 343.0

    def validar(self) -> None:
        if self.geometria != "circular":
            raise ConfiguracaoInvalida(
                f"array.geometria: só 'circular' é suportada hoje, recebi {self.geometria!r}"
            )
        if self.raio_m <= 0:
            raise ConfiguracaoInvalida("array.raio_m precisa ser maior que zero")
        if self.n_microfones < 3:
            raise ConfiguracaoInvalida(
                "array.n_microfones: são necessários pelo menos 3 microfones para "
                "estimar azimute sem ambiguidade"
            )
        if self.velocidade_som_ms <= 0:
            raise ConfiguracaoInvalida("array.velocidade_som_ms precisa ser maior que zero")


@dataclass(frozen=True)
class ConfigCalibracao:
    """Converte dBFS do array em dB SPL estimado.

    Isto NÃO é calibração metrológica. É o ajuste de uma campanha de referência,
    e o valor resultante carrega `valor_legal: false` em todo lugar por onde
    passa (decisão D3).
    """

    offset_db: float = 94.0
    ponderacao: str = "A"
    referencia: str = "sem campanha de calibração registrada"
    medido_em: str | None = None

    def validar(self) -> None:
        if self.ponderacao not in PONDERACOES:
            raise ConfiguracaoInvalida(
                f"audio.calibracao.ponderacao: use 'A' ou 'Z', recebi {self.ponderacao!r}"
            )


@dataclass(frozen=True)
class ConfigFonte:
    tipo: str = "sintetica"
    dispositivo: str | int | None = None
    caminho: str | None = None
    laco: bool = False
    tempo_real: bool = True
    perfil: str = "ambiente"
    azimute_graus: float = 45.0

    def validar(self) -> None:
        tipos = ("i2s", "wav", "sintetica")
        if self.tipo not in tipos:
            raise ConfiguracaoInvalida(
                f"audio.fonte.tipo: use um de {tipos}, recebi {self.tipo!r}"
            )
        if self.tipo == "wav" and not self.caminho:
            raise ConfiguracaoInvalida("audio.fonte.caminho é obrigatório quando tipo='wav'")


@dataclass(frozen=True)
class ConfigAudio:
    taxa_amostragem: int = 48000
    canais: int = 4
    buffer_segundos: float = 30.0
    bloco_amostras: int = 4096
    fonte: ConfigFonte = field(default_factory=ConfigFonte)
    calibracao: ConfigCalibracao = field(default_factory=ConfigCalibracao)

    def validar(self) -> None:
        if self.taxa_amostragem <= 0:
            raise ConfiguracaoInvalida("audio.taxa_amostragem precisa ser maior que zero")
        if self.canais < 1:
            raise ConfiguracaoInvalida("audio.canais precisa ser pelo menos 1")
        if self.buffer_segundos < 1:
            raise ConfiguracaoInvalida(
                "audio.buffer_segundos: o buffer precisa cobrir a janela de evento "
                "inteira (10 s antes + 10 s depois do pico), com folga"
            )
        if self.bloco_amostras <= 0:
            raise ConfiguracaoInvalida("audio.bloco_amostras precisa ser maior que zero")
        self.fonte.validar()
        self.calibracao.validar()


@dataclass(frozen=True)
class ConfigSonometro:
    """Instrumento de medição — camada de adaptação, decisão D5.

    `tipo` escolhe a implementação de `SonometroReader`. Trocar de modelo de
    instrumento mexe aqui e em uma classe de `sonometro.py`. Em nenhum outro
    lugar.
    """

    tipo: str = "ausente"
    porta: str | None = None
    baud: int = 9600
    timeout_s: float = 2.0
    comando: str | None = None
    modelo: str | None = None
    fabricante: str | None = None
    classe: int | None = None
    certificado: str | None = None
    validade_calibracao: str | None = None

    def validar(self) -> None:
        tipos = ("ausente", "mock", "serial")
        if self.tipo not in tipos:
            raise ConfiguracaoInvalida(
                f"sonometro.tipo: use um de {tipos}, recebi {self.tipo!r}"
            )
        if self.tipo == "serial" and not self.porta:
            raise ConfiguracaoInvalida("sonometro.porta é obrigatória quando tipo='serial'")
        if self.classe is not None and self.classe not in (1, 2):
            raise ConfiguracaoInvalida("sonometro.classe: use 1 ou 2 (IEC 61672)")

    @property
    def tem_valor_legal(self) -> bool:
        """Só um instrumento real, Classe 1 e com certificado declarado."""
        return self.tipo == "serial" and self.classe == 1 and bool(self.certificado)


@dataclass(frozen=True)
class ConfigAutuacao:
    """Declaração exigida para habilitar `modo=autuacao`.

    Existe para que ligar a autuação seja um ato registrado, com nome de quem
    autorizou e norma que sustenta — não uma linha trocada num arquivo.
    """

    habilitada_por: str
    base_normativa: str
    instrumento_modelo: str
    instrumento_classe: int
    instrumento_certificado: str
    validade_calibracao: str


@dataclass(frozen=True)
class ConfigNo:
    id: str
    descricao: str = ""
    geolocalizacao: Geolocalizacao = field(
        default_factory=lambda: Geolocalizacao(0.0, 0.0)
    )
    modo: str = MODO_TRIAGEM
    audio: ConfigAudio = field(default_factory=ConfigAudio)
    array: ConfigArray = field(default_factory=ConfigArray)
    sonometro: ConfigSonometro = field(default_factory=ConfigSonometro)
    autuacao: ConfigAutuacao | None = None

    def validar(self) -> None:
        if not self.id or not self.id.strip():
            raise ConfiguracaoInvalida("no.id é obrigatório — é o que identifica o nó na evidência")
        if self.modo not in MODOS:
            raise ConfiguracaoInvalida(f"modo: use um de {MODOS}, recebi {self.modo!r}")

        self.audio.validar()
        self.array.validar()
        self.sonometro.validar()

        if self.audio.canais != self.array.n_microfones:
            raise ConfiguracaoInvalida(
                f"audio.canais ({self.audio.canais}) difere de array.n_microfones "
                f"({self.array.n_microfones}) — a localização direcional produziria "
                "ângulo errado sem avisar"
            )

        if self.modo == MODO_AUTUACAO:
            self._validar_autuacao()

    def _validar_autuacao(self) -> None:
        if self.autuacao is None:
            raise ConfiguracaoInvalida(
                "modo=autuacao exige o bloco 'autuacao' completo (quem habilitou, base "
                "normativa e instrumento certificado). Ver docs/legal/inmetro.md"
            )
        if self.autuacao.instrumento_classe != 1:
            raise ConfiguracaoInvalida(
                "modo=autuacao exige instrumento Classe 1 (IEC 61672); "
                f"foi declarada Classe {self.autuacao.instrumento_classe}"
            )
        if not self.sonometro.tem_valor_legal:
            raise ConfiguracaoInvalida(
                "modo=autuacao exige um SonometroReader real, Classe 1 e com certificado "
                f"declarado — a configuração atual é sonometro.tipo={self.sonometro.tipo!r}, "
                f"classe={self.sonometro.classe!r}. O array MEMS não substitui medição "
                "legal (docs/legal/inmetro.md)"
            )

    @property
    def em_triagem(self) -> bool:
        return self.modo == MODO_TRIAGEM

    def resumo(self) -> dict[str, Any]:
        """Resumo estável para gravar em evidência e em log de inicialização."""
        return {
            "no_id": self.id,
            "modo": self.modo,
            "geolocalizacao": self.geolocalizacao.como_dict(),
            "taxa_amostragem": self.audio.taxa_amostragem,
            "canais": self.audio.canais,
            "array": {
                "geometria": self.array.geometria,
                "raio_m": self.array.raio_m,
                "n_microfones": self.array.n_microfones,
                "azimute_offset_graus": self.array.azimute_offset_graus,
            },
            "calibracao": {
                "offset_db": self.audio.calibracao.offset_db,
                "ponderacao": self.audio.calibracao.ponderacao,
                "referencia": self.audio.calibracao.referencia,
                "medido_em": self.audio.calibracao.medido_em,
            },
            "sonometro": {
                "tipo": self.sonometro.tipo,
                "modelo": self.sonometro.modelo,
                "classe": self.sonometro.classe,
                "valor_legal": self.sonometro.tem_valor_legal,
            },
        }


def _resolver_env(valor: Any) -> Any:
    """Expande `${VAR}` e `${VAR:-padrao}` — segredo não mora no arquivo."""
    if not isinstance(valor, str):
        return valor
    achado = _ENV.match(valor.strip())
    if not achado:
        return valor
    nome, padrao = achado.group(1), achado.group(2)
    obtido = os.environ.get(nome)
    if obtido is not None:
        return obtido
    if padrao is not None:
        return padrao
    raise ConfiguracaoInvalida(
        f"variável de ambiente {nome} não definida e sem valor padrão na configuração"
    )


def _percorrer(dados: Any) -> Any:
    if isinstance(dados, dict):
        return {k: _percorrer(v) for k, v in dados.items()}
    if isinstance(dados, list):
        return [_percorrer(v) for v in dados]
    return _resolver_env(dados)


def _apenas_campos(cls: type, dados: dict[str, Any], onde: str) -> dict[str, Any]:
    """Recusa chave desconhecida em vez de ignorar em silêncio.

    Um typo em `bufer_segundos` que passa despercebido vira um nó rodando com
    buffer padrão e ninguém sabendo por quê.
    """
    validos = {f.name for f in cls.__dataclass_fields__.values()}
    desconhecidos = set(dados) - validos
    if desconhecidos:
        raise ConfiguracaoInvalida(
            f"{onde}: chave(s) desconhecida(s) {sorted(desconhecidos)}; "
            f"esperava {sorted(validos)}"
        )
    return dados


def de_dict(dados: dict[str, Any]) -> ConfigNo:
    dados = _percorrer(dados or {})

    # `no:` sem aspas vira a chave booleana False no YAML 1.1 (a mesma regra que
    # transforma `yes`/`on` em booleano). O bloco se chama "no" porque é o nome
    # do domínio; aceitar as duas formas evita um erro confuso de "no.id é
    # obrigatório" num arquivo que claramente tem o id.
    bloco_no = dados.get("no") or dados.get(False) or {}
    if not isinstance(bloco_no, dict):
        raise ConfiguracaoInvalida("bloco 'no' precisa ser um mapa")

    geo = bloco_no.get("geolocalizacao") or {}
    geolocalizacao = Geolocalizacao(
        latitude=float(geo.get("latitude", 0.0)),
        longitude=float(geo.get("longitude", 0.0)),
    )

    bloco_audio = dict(dados.get("audio") or {})
    fonte = ConfigFonte(**_apenas_campos(ConfigFonte, dict(bloco_audio.pop("fonte", {}) or {}), "audio.fonte"))
    calibracao = ConfigCalibracao(
        **_apenas_campos(
            ConfigCalibracao, dict(bloco_audio.pop("calibracao", {}) or {}), "audio.calibracao"
        )
    )
    audio = ConfigAudio(
        fonte=fonte,
        calibracao=calibracao,
        **_apenas_campos(ConfigAudio, bloco_audio, "audio"),
    )

    array = ConfigArray(**_apenas_campos(ConfigArray, dict(dados.get("array") or {}), "array"))
    sonometro = ConfigSonometro(
        **_apenas_campos(ConfigSonometro, dict(dados.get("sonometro") or {}), "sonometro")
    )

    autuacao = None
    bloco_autuacao = dados.get("autuacao")
    if bloco_autuacao:
        instrumento = bloco_autuacao.get("instrumento_certificado") or {}
        faltando = [
            campo
            for campo in ("habilitada_por", "base_normativa")
            if not bloco_autuacao.get(campo)
        ]
        faltando += [
            f"instrumento_certificado.{campo}"
            for campo in ("modelo", "classe", "certificado", "validade_calibracao")
            if not instrumento.get(campo)
        ]
        if faltando:
            raise ConfiguracaoInvalida(
                f"bloco 'autuacao' incompleto, faltando: {faltando}. Ver docs/legal/inmetro.md"
            )
        autuacao = ConfigAutuacao(
            habilitada_por=str(bloco_autuacao["habilitada_por"]),
            base_normativa=str(bloco_autuacao["base_normativa"]),
            instrumento_modelo=str(instrumento["modelo"]),
            instrumento_classe=int(instrumento["classe"]),
            instrumento_certificado=str(instrumento["certificado"]),
            validade_calibracao=str(instrumento["validade_calibracao"]),
        )

    config = ConfigNo(
        id=str(bloco_no.get("id", "")),
        descricao=str(bloco_no.get("descricao", "")),
        geolocalizacao=geolocalizacao,
        modo=str(dados.get("modo", MODO_TRIAGEM)),
        audio=audio,
        array=array,
        sonometro=sonometro,
        autuacao=autuacao,
    )
    config.validar()
    return config


def carregar(caminho: str | Path) -> ConfigNo:
    caminho = Path(caminho)
    if not caminho.exists():
        raise ConfiguracaoInvalida(f"configuração não encontrada: {caminho}")
    with caminho.open(encoding="utf-8") as arquivo:
        dados = yaml.safe_load(arquivo)
    if not isinstance(dados, dict):
        raise ConfiguracaoInvalida(f"{caminho}: esperava um mapa YAML no topo do arquivo")
    return de_dict(dados)
