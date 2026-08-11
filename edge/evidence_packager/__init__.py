"""Pacote de evidência: montagem, leitura e verificação."""

from edge.evidence_packager.pacote import (
    CAMPO_HASH,
    EXTENSAO,
    NOME_MANIFESTO,
    VERSAO_MANIFESTO,
    PacoteInvalido,
    RelatorioVerificacao,
    calcular_hash_manifesto,
    canonico,
    ler_manifesto,
    montar_pacote,
    sha256_arquivo,
    sha256_bytes,
    verificar_pacote,
)

__all__ = [
    "CAMPO_HASH",
    "EXTENSAO",
    "NOME_MANIFESTO",
    "PacoteInvalido",
    "RelatorioVerificacao",
    "VERSAO_MANIFESTO",
    "calcular_hash_manifesto",
    "canonico",
    "ler_manifesto",
    "montar_pacote",
    "sha256_arquivo",
    "sha256_bytes",
    "verificar_pacote",
]
