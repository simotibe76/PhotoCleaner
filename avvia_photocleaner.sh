#!/bin/bash

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================"
echo "       PHOTOCLEANER - AVVIO"
echo "========================================"
echo

# 1. Controllo (opzionale) di una cartella montata
# Esempio: PHOTOCLEANER_MOUNT="$HOME/GoogleFoto" ./avvia_photocleaner.sh
echo "[1/3] Controllo cartella montata..."

if [ -n "$PHOTOCLEANER_MOUNT" ]; then
    if mountpoint -q "$PHOTOCLEANER_MOUNT"; then
        echo "      $PHOTOCLEANER_MOUNT montato correttamente."
    else
        echo "      ERRORE: $PHOTOCLEANER_MOUNT non è montato."
        exit 1
    fi
else
    echo "      Nessun controllo richiesto (PHOTOCLEANER_MOUNT non impostata)."
fi

# 2. Backend Python
echo "[2/3] Avvio backend..."

gnome-terminal -- bash -c "
    cd '$PROJECT'
    source '$PROJECT/backend/venv/bin/activate'
    echo '=== PHOTOCLEANER BACKEND ==='
    uvicorn backend.main:app --reload
    exec bash
"

# 3. Frontend React
echo "[3/3] Avvio frontend..."

gnome-terminal -- bash -c "
    export NVM_DIR=\"\$HOME/.nvm\"
    source \"\$NVM_DIR/nvm.sh\"
    nvm use 22
    cd '$PROJECT/frontend'
    echo '=== PHOTOCLEANER FRONTEND ==='
    npm run dev
    exec bash
"

echo
echo "========================================"
echo "       PHOTOCLEANER AVVIATO"
echo "========================================"
echo
echo "Frontend: http://localhost:5173/"
echo "Backend:  http://127.0.0.1:8000/"
echo
