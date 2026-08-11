#!/usr/bin/env sh
# Ponto de entrada do contêiner: semeia no primeiro boot, depois sobe o painel.
#
# O seed roda uma vez só: se o banco já existe no volume, ele é preservado —
# reiniciar o contêiner não apaga as decisões do operador nem a trilha de
# auditoria. Para começar do zero, apague o volume (ver deploy/README.md).
set -e

CONFIG="${ECOAR_CONFIG:-config/backend.vps.yaml}"
BANCO="dados/vps/ecoar.db"

if [ ! -f "$BANCO" ]; then
  echo ">> banco ausente: semeando três cidades pela API real..."
  python -m scripts.semear_demo --config "$CONFIG"
else
  echo ">> banco já existe em $BANCO — preservando dados. (apague o volume para recomeçar)"
fi

echo ">> subindo o painel em 0.0.0.0:8000"
exec python -m backend.cli --config "$CONFIG" --host 0.0.0.0 --porta 8000
