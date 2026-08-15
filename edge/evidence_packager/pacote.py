"""Montagem e verificação do pacote de evidência.

Um arquivo `.ecoar` por evento: um zip com `evento.json` e a mídia. Autocontido
e verificável **sem o nosso sistema** — quem recebe confere sozinho, o que é o
ponto inteiro de uma cadeia de custódia.

Como a integridade funciona, em uma frase: cada arquivo de mídia entra no
manifesto com seu próprio SHA-256, e o manifesto inteiro recebe um hash
calculado sobre a sua forma canônica. Alterar um byte de áudio muda o hash do
áudio, que está dentro do manifesto, que muda o hash do manifesto. Um número no
fim da cadeia protege tudo.

Canônico significa: chaves ordenadas, sem espaço supérfluo, UTF-8. Sem isso,
reserializar o mesmo conteúdo produziria bytes diferentes e a verificação
falharia por um motivo que não é adulteração — e um verificador que dá alarme
falso deixa de ser usado.
"""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from edge.audio_capture.captura import JanelaEvento
from edge.audio_capture.fontes import escrever_wav
from edge.camera_trigger.acionador import ResultadoAcionamento
from edge.classifier.base import Predicao
from edge.config import ConfigNo
from edge.localization.doa import EstimativaDOA

VERSAO_MANIFESTO = "evidencia/1.0"

NOME_MANIFESTO = "evento.json"
PASTA_MIDIA = "midia"
EXTENSAO = ".ecoar"

CAMPO_HASH = "hash_manifesto"


class PacoteInvalido(RuntimeError):
    """O pacote não passou na verificação de integridade."""


def sha256_bytes(dados: bytes) -> str:
    return "sha256:" + hashlib.sha256(dados).hexdigest()


def sha256_arquivo(caminho: Path) -> str:
    digest = hashlib.sha256()
    with Path(caminho).open("rb") as arquivo:
        for pedaco in iter(lambda: arquivo.read(1 << 20), b""):
            digest.update(pedaco)
    return "sha256:" + digest.hexdigest()


def _converter(valor):
    """Rede de segurança contra tipo numpy vazando para o manifesto.

    `np.float64` e `np.bool_` atravessam o código sem chamar atenção e só
    aparecem aqui, na serialização, como erro. Converter na saída garante que um
    esquecimento em qualquer módulo não impeça o pacote de ser gerado — e o
    número gravado é o mesmo.
    """
    if isinstance(valor, np.generic):
        return valor.item()
    if isinstance(valor, np.ndarray):
        return valor.tolist()
    if isinstance(valor, Path):
        return str(valor)
    raise TypeError(f"tipo não serializável no manifesto: {type(valor).__name__}")


def canonico(manifesto: dict) -> bytes:
    """Serialização estável: mesma informação, sempre os mesmos bytes."""
    return json.dumps(
        manifesto,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_converter,
    ).encode("utf-8")


def calcular_hash_manifesto(manifesto: dict) -> str:
    """Hash do manifesto sem o próprio campo de hash — senão seria circular."""
    sem_hash = {chave: valor for chave, valor in manifesto.items() if chave != CAMPO_HASH}
    return sha256_bytes(canonico(sem_hash))


@dataclass(frozen=True)
class RelatorioVerificacao:
    valido: bool
    problemas: tuple[str, ...] = ()
    manifesto: dict = field(default_factory=dict)

    def __str__(self) -> str:
        if self.valido:
            return "íntegro"
        return "ADULTERADO OU CORROMPIDO: " + "; ".join(self.problemas)


def montar_pacote(
    config: ConfigNo,
    evento_id: str,
    evento: JanelaEvento,
    doa: EstimativaDOA | None,
    predicao: Predicao | None,
    acionamento: ResultadoAcionamento,
    destino: Path | str,
) -> Path:
    """Monta o `.ecoar` do evento e devolve o caminho."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    caminho_audio = destino.parent / f"{evento_id}-audio.wav"
    escrever_wav(caminho_audio, np.asarray(evento.amostras), evento.taxa_amostragem)

    # Grava num arquivo temporário e só move para `destino` no fim, com sucesso.
    # Sem isso, uma falha no meio da escrita do zip (mídia sumiu do disco entre
    # o acionamento e a montagem, por exemplo) deixaria um `.ecoar` parcial no
    # caminho final — e cadeia de custódia (D8) não convive com "pacote que
    # existe mas está incompleto": ou o evento tem evidência completa, ou não
    # tem nenhuma.
    temporario = destino.with_name(destino.name + ".tmp")
    try:
        arquivos: list[tuple[str, Path]] = [(f"{PASTA_MIDIA}/audio.wav", caminho_audio)]
        for captura in acionamento.capturas:
            arquivos.append((f"{PASTA_MIDIA}/{captura.caminho.name}", captura.caminho))

        manifesto = _montar_manifesto(
            config=config,
            evento_id=evento_id,
            evento=evento,
            doa=doa,
            predicao=predicao,
            acionamento=acionamento,
            arquivos=arquivos,
        )
        manifesto[CAMPO_HASH] = calcular_hash_manifesto(manifesto)

        with zipfile.ZipFile(temporario, "w", zipfile.ZIP_DEFLATED) as pacote:
            pacote.writestr(NOME_MANIFESTO, canonico(manifesto))
            for nome, caminho in arquivos:
                pacote.write(caminho, nome)
        os.replace(temporario, destino)
    finally:
        caminho_audio.unlink(missing_ok=True)
        temporario.unlink(missing_ok=True)

    return destino


def _montar_manifesto(
    config: ConfigNo,
    evento_id: str,
    evento: JanelaEvento,
    doa: EstimativaDOA | None,
    predicao: Predicao | None,
    acionamento: ResultadoAcionamento,
    arquivos: list[tuple[str, Path]],
) -> dict:
    hashes = {nome: sha256_arquivo(caminho) for nome, caminho in arquivos}

    imagens = []
    for captura in acionamento.capturas:
        nome = f"{PASTA_MIDIA}/{captura.caminho.name}"
        imagens.append({**captura.como_dict(), "arquivo": nome, "sha256": hashes[nome]})

    return {
        "versao_manifesto": VERSAO_MANIFESTO,
        "evento_id": evento_id,
        "modo": config.modo,
        "no": config.resumo(),
        "capturado_em": datetime.fromtimestamp(
            evento.instante_pico, tz=timezone.utc
        ).isoformat(),
        "instante_pico_epoch": evento.instante_pico,
        "audio": {
            "arquivo": f"{PASTA_MIDIA}/audio.wav",
            "sha256": hashes[f"{PASTA_MIDIA}/audio.wav"],
            "taxa_amostragem": evento.taxa_amostragem,
            "canais": int(np.asarray(evento.amostras).shape[1]),
            "inicio_epoch": evento.janela.inicio,
            "fim_epoch": evento.janela.fim,
            "duracao_s": round(evento.janela.duracao_s, 3),
            "pre_registro_s": {
                "pedido": round(evento.antes_pedido_s, 2),
                "obtido": round(evento.antes_obtido_s, 2),
                "truncado": evento.truncado,
            },
        },
        "spl_estimado": evento.spl.como_dict(),
        "medicao_instrumento": (
            evento.sonometro.como_dict() if evento.sonometro else None
        ),
        "motivo_sem_instrumento": evento.motivo_sem_sonometro,
        "localizacao": doa.como_dict() if doa else None,
        "classificacao": predicao.como_dict() if predicao else None,
        "decisao": acionamento.decisao.como_dict(),
        "imagens": imagens,
        "falha_de_captura": acionamento.falha_de_captura,
        # Explícito porque a ausência é uma decisão de arquitetura, não um
        # esquecimento: o nó não lê placa (D10, docs/legal/lgpd.md).
        "leitura_de_placa": {
            "realizada": False,
            "motivo": "o nó de borda não executa OCR; em modo=triagem a placa não é lida",
        },
        "retencao": config.retencao.como_dict(),
        "aviso_legal": (
            "SPL do array MEMS é estimativa sem valor legal. Medição com validade "
            "legal exige instrumento IEC 61672 Classe 1 (ver medicao_instrumento). "
            "Este pacote registra ocorrência para triagem; não constitui auto de "
            "infração."
        ),
    }


def ler_manifesto(caminho: Path | str) -> dict:
    with zipfile.ZipFile(caminho) as pacote:
        return json.loads(pacote.read(NOME_MANIFESTO).decode("utf-8"))


def verificar_pacote(caminho: Path | str) -> RelatorioVerificacao:
    """Confere o pacote inteiro. Não depende de banco nem de rede."""
    caminho = Path(caminho)
    if not caminho.exists():
        return RelatorioVerificacao(False, (f"arquivo não encontrado: {caminho}",))

    problemas: list[str] = []
    try:
        with zipfile.ZipFile(caminho) as pacote:
            nomes = set(pacote.namelist())
            if NOME_MANIFESTO not in nomes:
                return RelatorioVerificacao(False, ("pacote sem manifesto evento.json",))

            manifesto = json.loads(pacote.read(NOME_MANIFESTO).decode("utf-8"))

            declarado = manifesto.get(CAMPO_HASH)
            recalculado = calcular_hash_manifesto(manifesto)
            if declarado != recalculado:
                problemas.append(
                    "hash do manifesto não confere: algum campo foi alterado depois "
                    f"da geração (declarado {declarado}, recalculado {recalculado})"
                )

            for referencia in _referencias_de_midia(manifesto):
                nome = referencia["arquivo"]
                if nome not in nomes:
                    problemas.append(f"mídia ausente no pacote: {nome}")
                    continue
                obtido = sha256_bytes(pacote.read(nome))
                if obtido != referencia["sha256"]:
                    problemas.append(f"conteúdo de {nome} não confere com o hash declarado")

            extras = nomes - {NOME_MANIFESTO} - {
                ref["arquivo"] for ref in _referencias_de_midia(manifesto)
            }
            for extra in sorted(extras):
                problemas.append(f"arquivo não declarado no manifesto: {extra}")

    except zipfile.BadZipFile:
        return RelatorioVerificacao(False, ("arquivo não é um pacote .ecoar válido",))
    except json.JSONDecodeError as erro:
        return RelatorioVerificacao(False, (f"manifesto ilegível: {erro}",))

    return RelatorioVerificacao(not problemas, tuple(problemas), manifesto)


def _referencias_de_midia(manifesto: dict) -> list[dict]:
    referencias = []
    audio = manifesto.get("audio")
    if isinstance(audio, dict) and audio.get("arquivo"):
        referencias.append({"arquivo": audio["arquivo"], "sha256": audio.get("sha256")})
    for imagem in manifesto.get("imagens") or []:
        if imagem.get("arquivo"):
            referencias.append(
                {"arquivo": imagem["arquivo"], "sha256": imagem.get("sha256")}
            )
    return referencias
