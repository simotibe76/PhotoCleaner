# 📸 PhotoCleaner

**Fai ordine nel tuo Google Takeout: trova doppioni, screenshot e "buongiornissimo" di WhatsApp: tutto in locale, senza cloud, senza cancellare nulla di nascosto.**

PhotoCleaner è un'app web locale (backend Python + frontend React) pensata per chi ha scaricato la propria libreria di **Google Foto con Google Takeout** e si ritrova con migliaia di file, copie ripetute e immagini che non vale la pena tenere. Analizza una cartella del tuo computer, ti mostra cosa sembra da rivedere e ti lascia decidere, foto per foto.

<!-- Aggiungi qui uno screenshot (senza foto private!):
![PhotoCleaner](docs/screenshot.png)
-->

## ✨ Cosa fa

| Funzione | Descrizione |
|---|---|
| 🔎 **Scansione con avanzamento** | Legge foto, video e JSON del Takeout mostrando fase, percentuale e tempo stimato. |
| 🧩 **Confronto visivo** | Raggruppa i file con nomi simili (`IMG_1234`, `IMG_1234-modificata`, `IMG_1234(1)`…) e li affianca con risoluzione, peso, data EXIF e GPS. |
| 🚩 **Sospetti** | Segnala i file probabilmente da rivedere: provenienti da **WhatsApp**, **screenshot**, immagini piccole e senza EXIF. Ogni segnalazione mostra il motivo. |
| 👯 **Doppioni esatti** | Trova le copie identiche byte per byte (SHA-256, solo tra file della stessa dimensione) e calcola quanto spazio puoi recuperare. |
| 🗃️ **Quarantena reversibile** | Niente cancellazioni: i file scelti vengono **spostati** in `data/quarantena/` insieme al loro JSON, e puoi ripristinarli con un clic. |
| 🔍 **Zoom al passaggio del mouse** | Ingrandisci qualsiasi miniatura senza aprirla. |
| ✅ **Segni "da tenere"** | Proteggi le foto importanti: non vengono mai spostate. |

## 🔒 Sicurezza e privacy

- **Tutto gira sul tuo computer.** Nessun account Google, nessun upload, nessuna telemetria.
- **Nessuna cancellazione definitiva.** L'app sposta i file in quarantena; per eliminarli davvero cancelli tu la cartella `data/quarantena/`.
- **Le modifiche riguardano solo la copia locale.** Foto e video su Google Foto e sui telefoni non vengono toccati.
- Nei gruppi di doppioni l'app **non ti lascia spostare tutte le copie**: ne resta sempre almeno una.
- Il backend ascolta solo su `127.0.0.1` e non ha autenticazione: **non esporlo in rete**.

> ⚠️ Fai sempre un backup prima di lavorare sulle tue foto. I suggerimenti (nomi simili, "sospetti") sono indizi, non prove: guarda sempre le immagini prima di spostarle.

## 🧰 Requisiti

- **Linux** (testato con GNOME). Il selettore di cartelle usa [`zenity`](https://help.gnome.org/users/zenity/stable/) e lo script di avvio usa `gnome-terminal`.
- **Python 3.9+**
- **Node.js 20.19+** (consigliata la 22, ad esempio con [nvm](https://github.com/nvm-sh/nvm))
- Una cartella con il tuo Google Takeout già estratto

## 🚀 Installazione

```bash
git clone https://github.com/<tuo-utente>/PhotoCleaner.git
cd PhotoCleaner

# Backend
python3 -m venv backend/venv
source backend/venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend
npm install
cd ..
```

## ▶️ Avvio

**Con lo script** (apre due terminali):

```bash
chmod +x avvia_photocleaner.sh
./avvia_photocleaner.sh
```

**A mano**, in due terminali separati:

```bash
# Terminale 1: backend (dalla cartella principale del progetto)
source backend/venv/bin/activate
uvicorn backend.main:app --reload

# Terminale 2: frontend
cd frontend
npm run dev
```

Poi apri **http://localhost:5173**. In alto, accanto alla scritta ONLINE, compare la versione del backend.

Se la tua libreria sta su un disco o una condivisione che va montata prima, puoi far controllare allo script che sia pronta:

```bash
PHOTOCLEANER_MOUNT="$HOME/MiaCartellaMontata" ./avvia_photocleaner.sh
```

## 🧭 Come si usa

1. **Scarica il Takeout** da [takeout.google.com](https://takeout.google.com) (solo *Google Foto*) ed estrai gli archivi in un'unica cartella.
2. Clicca **Seleziona cartella** e scegli la cartella del Takeout.
3. Clicca **Avvia scansione** e segui la barra di avanzamento.
4. Esplora le schede:
   - **Confronto visivo**: gruppi di foto con nomi simili;
   - **Sospetti**: WhatsApp, screenshot, piccole senza EXIF;
   - **Doppioni**: copie identiche (richiede un secondo passaggio, con la sua barra);
   - **Quarantena**: tutto ciò che hai spostato, con il pulsante *Ripristina*.
5. Seleziona i file da togliere e premi **Sposta in quarantena**. Quando sei sicuro, svuota a mano `data/quarantena/`.

## 🧱 Com'è fatto

```
PhotoCleaner/
├── backend/            # API FastAPI (scansione, sospetti, doppioni, quarantena)
│   └── main.py
├── frontend/           # Interfaccia React + Vite
│   └── src/App.jsx
├── data/               # Creata all'uso: quarantena e registro (non versionata)
├── requirements.txt
└── avvia_photocleaner.sh
```

Le operazioni lunghe (scansione, ricerca doppioni) girano in un thread in background; il frontend ne legge lo stato con una richiesta ogni mezzo secondo.

<details>
<summary><strong>API principali</strong></summary>

| Metodo | Percorso | Cosa fa |
|---|---|---|
| `GET` | `/api/status` | Versione e stato del backend |
| `GET` | `/api/select-folder` | Apre il selettore di cartelle (zenity) |
| `POST` | `/api/jobs/scan?path=…` | Avvia la scansione |
| `POST` | `/api/jobs/duplicates?path=…` | Avvia la ricerca dei doppioni |
| `GET` | `/api/jobs/{id}` | Avanzamento di un'operazione |
| `GET` | `/api/suspects?path=…&category=…` | File sospetti (paginati) |
| `GET` | `/api/duplicates?path=…` | Gruppi di doppioni (paginati) |
| `GET` | `/api/preview?path=…&root=…` | Anteprima di un'immagine |
| `POST` | `/api/quarantine` | Sposta file in quarantena |
| `GET` | `/api/quarantine` | Elenco della quarantena |
| `POST` | `/api/quarantine/restore` | Ripristina file |

</details>

## ⚠️ Limiti noti

- I doppioni sono solo **copie esatte**: una foto ridimensionata o ricompressa (tipico di WhatsApp) non risulta uguale.
- I gruppi per nome sono **suggerimenti**: non dimostrano che le foto siano la stessa.
- I formati come HEIC possono non avere anteprima, a seconda del browser e di Pillow.
- I video non vengono analizzati nel dettaglio (niente metadati).
- Pensato e provato su Linux; su altri sistemi servono modifiche (selettore cartelle, script di avvio).

## 🗺️ Idee per il futuro

- Hash percettivo per trovare foto simili ma non identiche
- Esportazione dell'elenco dei file messi in quarantena (nome e data di scatto)
- Selettore di cartelle indipendente da zenity
- Supporto a macOS e Windows

I contributi sono benvenuti: apri una *issue* o una *pull request*.

## 📄 Licenza

Rilasciato sotto licenza [MIT](LICENSE).

---

*PhotoCleaner non è affiliato né approvato da Google. "Google Foto" e "Google Takeout" sono marchi di Google LLC.*
