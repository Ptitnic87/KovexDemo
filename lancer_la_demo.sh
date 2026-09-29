#!/usr/bin/env bash
# ===========================================================================
# Kovex - Plateforme de démonstration (serveur Linux)
#
# Remet les espaces de démonstration dans leur état figé, datés du jour, puis
# lance l'API et l'interface du Kovex du sous-module kovex/. La clé du
# modèle, posée une fois sur ce serveur, reste.
#
# Les arguments sont passés à restaurer.py (ex. : --actif Alvea_ATELIER).
# Adresses et ports : KOVEX_API_HOST, KOVEX_API_PORT, KOVEX_FRONTEND_HOST,
# KOVEX_FRONTEND_PORT, KOVEX_API_URL.
# ===========================================================================
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
PORT_API="${KOVEX_API_PORT:-8000}"

if [ ! -f kovex/run_api.py ]; then
    echo "Kovex est absent de kovex/ : git submodule update --init, ou utilisez l'archive d'empaqueter.py." >&2
    exit 1
fi

"$PYTHON" restaurer.py --api "http://127.0.0.1:${PORT_API}" "$@"

cd kovex
"$PYTHON" run_api.py &
API=$!
"$PYTHON" serve_frontend.py &
INTERFACE=$!
trap 'kill "$API" "$INTERFACE" 2>/dev/null || true' INT TERM EXIT
wait -n "$API" "$INTERFACE"
