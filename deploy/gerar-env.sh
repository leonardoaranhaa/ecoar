#!/usr/bin/env sh
# Gera o arquivo .env com tokens fortes para a demo em VPS.
#
# Roda uma vez. Se .env já existe, para — para não trocar os tokens de uma demo
# no ar por engano (trocaria a senha de login no meio da reunião).
set -e

cd "$(dirname "$0")"

if [ -f .env ]; then
  echo ".env já existe. Apague-o à mão se quiser gerar tokens novos."
  exit 1
fi

# 32 hex = 128 bits. openssl é padrão em qualquer VPS; se faltar, o fallback usa
# /dev/urandom.
token() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 16
  else
    head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

cat > .env <<EOF
# Tokens da demo em VPS — gerados por gerar-env.sh. NÃO versionar.
# Para logar no painel, use ECOAR_TOKEN_OPERADOR (operador) ou
# ECOAR_TOKEN_ADMIN (admin, vê Modelo e Auditoria).

ECOAR_TOKEN_NO_01=$(token)
ECOAR_TOKEN_NO_02=$(token)
ECOAR_TOKEN_NO_03=$(token)
ECOAR_TOKEN_NO_04=$(token)
ECOAR_TOKEN_NO_05=$(token)
ECOAR_TOKEN_OPERADOR=$(token)
ECOAR_TOKEN_ADMIN=$(token)
EOF

chmod 600 .env

echo ".env criado. Os tokens de login (guarde para a reunião):"
echo
grep -E "ECOAR_TOKEN_(OPERADOR|ADMIN)=" .env | sed 's/^/    /'
echo
echo "Suba com:  docker compose up -d"
