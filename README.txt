PhotoCleaner – confronto visivo (v0.2.0)
==========================================

Questa cartella contiene tre file da copiare nel progetto esistente:
- backend/main.py
- frontend/src/App.jsx
- frontend/src/App.css

Prima di sostituire i file, chiudi i server e crea una copia di sicurezza dei tre file attuali.

Pillow è facoltativo ma consigliato per leggere dimensioni e EXIF:
  cd ~/Documenti/PhotoCleaner/backend
  source venv/bin/activate
  pip install Pillow

Poi avvia il backend come fai normalmente. Riavvia anche il frontend se necessario.

La schermata è volutamente in sola lettura: i pulsanti “DA TENERE” e “RICONTROLLARE”
sono marcature temporanee in memoria del browser. Non cancellano, spostano o modificano file.

Nota: i gruppi sono suggerimenti basati sui nomi. Non dimostrano che le foto siano duplicati.
Alcuni formati (per esempio HEIC) potrebbero non avere anteprima se il browser/Pillow non li supporta.
