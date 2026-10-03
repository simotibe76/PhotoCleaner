from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import List, Optional
from uuid import uuid4
import shutil
import threading
import time
import hashlib
import subprocess
import os
import json
import re

try:
    from PIL import Image, ExifTags
    PIL_AVAILABLE = True
except ImportError:
    Image = None
    ExifTags = None
    PIL_AVAILABLE = False


app = FastAPI(title="PhotoCleaner")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif",
    ".bmp", ".tif", ".tiff", ".dng", ".raw", ".cr2", ".cr3",
    ".nef", ".arw", ".orf", ".rw2"
}
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".mts", ".m2ts", ".3gp", ".webm"
}
VERSION_SUFFIXES = (
    "-modificata", "_modificata", "-modified", "_modified",
    "-effects", "_effects", "-mix", "_mix", "-edited", "_edited",
    "-enhanced", "_enhanced"
)

# --- Rilevamento "sospetti" (v0.3.0) ---
WHATSAPP_NAME_RE = re.compile(
    r"^(?:(?:img|vid|ptt|aud)-\d{8}-wa\d+|whatsapp (?:image|video|immagine))",
    re.IGNORECASE,
)
SCREENSHOT_RE = re.compile(r"^screenshot", re.IGNORECASE)
SMALL_BYTES = 200 * 1024   # sotto questa dimensione una foto è "piccola"
SMALL_SIDE = 1600          # lato massimo in pixel per essere "piccola"
MAX_GROUPS = 2000          # tetto ai gruppi restituiti dalla scansione
_CACHE = {}                # risultati dell'ultima scansione per cartella
INTERNAL_KEYS = ("suspects", "media_index", "duplicates")

# --- Quarantena (v0.4.0): i file vengono SPOSTATI, mai cancellati ---
QUARANTINE_DIR = Path(__file__).resolve().parent.parent / "data" / "quarantena"
QUARANTINE_LOG = QUARANTINE_DIR / "log.json"
SIDECAR_SUFFIXES = (".supplemental-metadata.json", ".json")


def normalize_name(name):
    return os.path.normcase(name).strip()


def json_candidates(json_filename):
    suffixes = [
        ".supplemental-metadata(3).json",
        ".supplemental-metadata(2).json",
        ".supplemental-metadata(1).json",
        ".supplemental-metadata.json",
        ".json",
    ]
    for suffix in suffixes:
        if json_filename.lower().endswith(suffix):
            return [json_filename[:-len(suffix)]]
    return []


def safe_metadata(path):
    """Read basic file details; unavailable metadata stays null."""
    item = {
        "size_bytes": None,
        "width": None,
        "height": None,
        "gps": None,
        "taken_at": None,
        "metadata_note": None,
    }
    try:
        item["size_bytes"] = os.path.getsize(path)
    except OSError:
        pass

    if not PIL_AVAILABLE:
        item["metadata_note"] = "Pillow non installato: dettagli immagine non disponibili"
        return item

    try:
        with Image.open(path) as image:
            item["width"], item["height"] = image.size
            exif = image.getexif()
            if exif:
                names = {ExifTags.TAGS.get(k, str(k)): v for k, v in exif.items()}
                item["taken_at"] = (
                    names.get("DateTimeOriginal")
                    or names.get("DateTimeDigitized")
                    or names.get("DateTime")
                )
                gps_ifd = None
                try:
                    gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
                except Exception:
                    gps_ifd = None
                if gps_ifd:
                    gps_names = {ExifTags.GPSTAGS.get(k, str(k)): v for k, v in gps_ifd.items()}
                    lat = gps_names.get("GPSLatitude")
                    lon = gps_names.get("GPSLongitude")
                    lat_ref = gps_names.get("GPSLatitudeRef")
                    lon_ref = gps_names.get("GPSLongitudeRef")

                    def decimal(coords):
                        if not coords or len(coords) < 3:
                            return None
                        vals = []
                        for part in coords[:3]:
                            try:
                                vals.append(float(part[0]) / float(part[1]))
                            except Exception:
                                try:
                                    vals.append(float(part))
                                except Exception:
                                    return None
                        return vals[0] + vals[1] / 60 + vals[2] / 3600

                    lat_value = decimal(lat)
                    lon_value = decimal(lon)
                    if lat_value is not None and lon_value is not None:
                        if str(lat_ref).upper() == "S":
                            lat_value = -lat_value
                        if str(lon_ref).upper() == "W":
                            lon_value = -lon_value
                        item["gps"] = {"latitude": round(lat_value, 6), "longitude": round(lon_value, 6)}
    except Exception as exc:
        item["metadata_note"] = "Anteprima o EXIF non leggibili con Pillow"
    return item


def extract_origin(metadata):
    """Legge dal JSON del Takeout la cartella/app di origine sul telefono, se presenti."""
    folder = package = None
    if isinstance(metadata, dict):
        origin = metadata.get("googlePhotosOrigin")
        upload = origin.get("mobileUpload") if isinstance(origin, dict) else None
        device_folder = upload.get("deviceFolder") if isinstance(upload, dict) else None
        if isinstance(device_folder, dict):
            value = device_folder.get("localFolderName")
            folder = value if isinstance(value, str) else None
        app_source = metadata.get("appSource")
        if isinstance(app_source, dict):
            value = app_source.get("androidPackageName")
            package = value if isinstance(value, str) else None
    return {"folder": folder, "package": package}


def classify_suspect(item):
    """Restituisce (categoria, motivi) se il file sembra da rivedere, altrimenti (None, [])."""
    name = item["filename"]
    folder = item.get("origin_folder") or ""
    package = item.get("origin_package") or ""

    reasons = []
    if "whatsapp" in folder.lower():
        reasons.append(f"cartella sul telefono: {folder}")
    if package.lower().startswith("com.whatsapp"):
        reasons.append("app di origine: WhatsApp")
    if WHATSAPP_NAME_RE.match(name):
        reasons.append("nome file tipo WhatsApp")
    if reasons:
        return "whatsapp", reasons

    if SCREENSHOT_RE.match(name) or "screenshot" in folder.lower():
        return "screenshot", ["nome o cartella da screenshot"]

    if item["type"] == "photo" and item.get("width") and item.get("height"):
        small = (item.get("size_bytes") or 0) < SMALL_BYTES
        low_res = max(item["width"], item["height"]) <= SMALL_SIDE
        if small and low_res and not item.get("taken_at"):
            return "piccola_senza_exif", [
                f"{item['width']}×{item['height']} px, sotto {SMALL_BYTES // 1024} KB, nessuna data EXIF"
            ]
    return None, []


def candidate_key(filename):
    """Create a broad review key, not a claim that files are duplicates."""
    stem = Path(filename).stem.lower().strip()
    # Remove common Google Photos edit/version suffixes, repeatedly.
    changed = True
    while changed:
        changed = False
        for suffix in VERSION_SUFFIXES:
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)].rstrip(" _-.")
                changed = True
                break
        new_stem = re.sub(r"(?:[\s_-]*\(\d+\)|(?<!\d)[\s_-]+\d+)$", "", stem)
        if new_stem != stem and new_stem:
            stem = new_stem.rstrip(" _-.")
            changed = True
    return stem


def analyze_library(path, progress=None):
    def report(phase, done=0, total=0, message=""):
        if progress:
            progress(phase, done, total, message)

    base = Path(path).expanduser().resolve()
    if not base.exists() or not base.is_dir():
        raise HTTPException(status_code=400, detail="La cartella selezionata non esiste o non è una cartella.")

    media = []
    json_files = []
    photos = videos = 0

    report("conteggio", 0, 0, "Conteggio dei file...")
    file_list = []
    for root, dirs, files in os.walk(base):
        dirs.sort()
        files.sort()
        for filename in files:
            file_list.append((root, filename))
        report("conteggio", len(file_list), 0, f"Conteggio dei file: {len(file_list)} trovati...")

    total_found = len(file_list)
    for index, (root, filename) in enumerate(file_list):
        if index % 25 == 0:
            report("lettura", index, total_found, f"Lettura di foto e video: {index} / {total_found}")
        full_path = Path(root) / filename
        ext = full_path.suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            photos += 1
            kind = "photo"
        elif ext in VIDEO_EXTENSIONS:
            videos += 1
            kind = "video"
        elif ext == ".json":
            json_files.append(full_path)
            continue
        else:
            continue

        details = safe_metadata(str(full_path)) if kind == "photo" else {
            "size_bytes": full_path.stat().st_size if full_path.exists() else None,
            "width": None, "height": None, "gps": None, "taken_at": None,
            "metadata_note": "Metadati video non analizzati in questa versione"
        }
        media.append({
            "path": str(full_path.resolve()),
            "filename": filename,
            "relative_path": str(full_path.resolve().relative_to(base)),
            "type": kind,
            **details,
        })

    # Match JSON against the full relative path when possible, then filename.
    # Keep all media with the same filename as candidates rather than overwriting collisions.
    by_name = defaultdict(list)
    for item in media:
        by_name[normalize_name(item["filename"])].append(item)

    matched_media_paths = set()
    matched_json_paths = set()
    orphan_json = []
    for json_index, json_path in enumerate(json_files):
        if json_index % 100 == 0:
            report("json", json_index, len(json_files), f"Abbinamento dei file JSON: {json_index} / {len(json_files)}")
        filename = json_path.name
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            orphan_json.append({
                "json": filename, "title": None, "photoTakenTime": None,
                "creationTime": None, "url": None, "reason": "JSON non leggibile"
            })
            continue

        origin = extract_origin(metadata)
        candidates = []
        title = metadata.get("title") if isinstance(metadata, dict) else None
        if isinstance(title, str) and title.strip():
            candidates.append(Path(title.strip()).name)
        candidates.extend(json_candidates(filename))

        found = False
        for candidate in candidates:
            matches = by_name.get(normalize_name(Path(candidate).name), [])
            if matches:
                # If a same-named file exists in the same directory, prefer it.
                same_dir = [m for m in matches if Path(m["path"]).parent == json_path.parent]
                chosen = same_dir if same_dir else matches
                for match in chosen:
                    matched_media_paths.add(match["path"])
                    match["origin_folder"] = origin["folder"]
                    match["origin_package"] = origin["package"]
                matched_json_paths.add(str(json_path))
                found = True
                break

        if not found:
            taken = metadata.get("photoTakenTime", {}) if isinstance(metadata, dict) else {}
            created = metadata.get("creationTime", {}) if isinstance(metadata, dict) else {}
            orphan_json.append({
                "json": filename,
                "title": title,
                "photoTakenTime": taken.get("formatted") if isinstance(taken, dict) else None,
                "creationTime": created.get("formatted") if isinstance(created, dict) else None,
                "url": metadata.get("url") if isinstance(metadata, dict) else None,
                "reason": "Nessun file multimediale corrispondente trovato"
            })

    media_without_json = [
        {"file": item["filename"], "type": item["type"], "path": item["path"]}
        for item in media if item["path"] not in matched_media_paths
    ]

    report("gruppi", 0, 0, "Creazione di gruppi e sospetti...")
    grouped = defaultdict(list)
    for item in media:
        # Do not create groups from empty keys or singletons.
        key = candidate_key(item["filename"])
        if key:
            grouped[key].append(item)

    review_groups = []
    for key, items in grouped.items():
        if len(items) < 2:
            continue
        # A group is just a review suggestion. Keep all variants visible.
        items.sort(key=lambda x: (x["filename"].lower(), x["relative_path"].lower()))
        labels = []
        for item in items:
            lower = item["filename"].lower()
            if any(s in lower for s in ("modificata", "modified", "edited", "effects", "mix", "enhanced")):
                labels.append("possibile versione modificata")
            elif re.search(r"(?:[_ -]\d+|\(\d+\))(?=\.[^.]+$)", lower):
                labels.append("suffisso numerico")
            else:
                labels.append("nome base")
        for item, label in zip(items, labels):
            item["hint"] = label
        review_groups.append({
            "id": key,
            "label": items[0]["filename"] if len(items) == 1 else key,
            "count": len(items),
            "files": items,
            "note": "Gruppo suggerito dal nome: verifica visivamente, non implica duplicati."
        })

    review_groups.sort(key=lambda g: (-g["count"], g["label"].lower()))

    suspects = []
    suspects_summary = {}
    for item in media:
        category, reasons = classify_suspect(item)
        if not category:
            continue
        suspects.append({
            "path": item["path"],
            "filename": item["filename"],
            "relative_path": item["relative_path"],
            "type": item["type"],
            "size_bytes": item["size_bytes"],
            "width": item["width"],
            "height": item["height"],
            "taken_at": item["taken_at"],
            "category": category,
            "reasons": reasons,
        })
        entry = suspects_summary.setdefault(category, {"count": 0, "size_bytes": 0})
        entry["count"] += 1
        entry["size_bytes"] += item["size_bytes"] or 0
    suspects.sort(key=lambda x: (x["category"], x["relative_path"].lower()))

    return {
        "path": str(base),
        "photos": photos,
        "videos": videos,
        "json": len(json_files),
        "total_files": photos + videos + len(json_files),
        "matched_media": len(matched_media_paths),
        "matched_json": len(matched_json_paths),
        "orphan_json": len(orphan_json),
        "media_without_json": len(media_without_json),
        "orphan_json_examples": orphan_json[:100],
        "media_without_json_examples": media_without_json[:100],
        "groups_count": len(review_groups),
        "groups": review_groups[:MAX_GROUPS],
        "suspects_summary": suspects_summary,
        "suspects": suspects,
        "media_index": media,
        "pillow_available": PIL_AVAILABLE,
    }


def get_analysis(path, refresh=False):
    """Scansione con cache: evita di rifare tutto a ogni richiesta."""
    key = str(Path(path).expanduser().resolve())
    if refresh or key not in _CACHE:
        _CACHE[key] = analyze_library(path)
    return _CACHE[key]


@app.get("/")
def home():
    return {"app": "PhotoCleaner", "status": "online"}


@app.get("/api/status")
def status():
    return {"status": "online", "app": "PhotoCleaner", "version": "0.5.0"}


@app.get("/api/select-folder")
def select_folder():
    try:
        result = subprocess.run(
            ["zenity", "--file-selection", "--directory", "--title=Seleziona la cartella da analizzare"],
            capture_output=True, text=True, timeout=300
        )
    except (OSError, subprocess.TimeoutExpired):
        raise HTTPException(status_code=500, detail="Impossibile avviare il selettore cartelle (zenity).")

    if result.returncode != 0:
        return {"selected": False, "path": None}
    return {"selected": True, "path": result.stdout.strip()}


@app.get("/api/scan")
def scan(path: str = Query(...)):
    # "Avvia scansione" rifà sempre la scansione completa e aggiorna la cache.
    result = get_analysis(path, refresh=True)
    # La lista completa dei sospetti si legge da /api/suspects; qui solo il riepilogo.
    return {k: v for k, v in result.items() if k not in INTERNAL_KEYS}


@app.get("/api/scan-details")
def scan_details(path: str = Query(...)):
    result = get_analysis(path)
    return {
        "orphan_json_count": result["orphan_json"],
        "media_without_json_count": result["media_without_json"],
        "orphan_json_examples": result["orphan_json_examples"],
        "media_without_json_examples": result["media_without_json_examples"],
        "groups_count": result["groups_count"],
        "groups": result["groups"],
    }


# --- Operazioni lunghe in background con avanzamento (v0.5.0) ---
JOBS = {}
JOBS_LOCK = threading.Lock()


def start_job(kind, key, work):
    """Avvia work(progress) in un thread. Se c'è già un job uguale in corso, restituisce quello."""
    with JOBS_LOCK:
        for existing in JOBS.values():
            if existing["status"] == "running" and existing["kind"] == kind and existing["key"] == key:
                return existing
        for old_id in [i for i, j in JOBS.items() if j["kind"] == kind and j["status"] != "running"]:
            del JOBS[old_id]
        now = time.time()
        job = {
            "id": uuid4().hex, "kind": kind, "key": key, "status": "running",
            "phase": "avvio", "message": "Avvio...", "done": 0, "total": 0,
            "elapsed": 0, "phase_started": now, "result": None, "error": None,
        }
        JOBS[job["id"]] = job

    def progress(phase, done=0, total=0, message=""):
        now = time.time()
        if phase != job["phase"]:
            job["phase_started"] = now
        job.update(phase=phase, done=done, total=total, message=message,
                   elapsed=round(now - job["phase_started"], 1))

    def runner():
        try:
            job["result"] = work(progress)
            job["status"] = "done"
        except HTTPException as exc:
            job["error"] = str(exc.detail)
            job["status"] = "error"
        except Exception as exc:  # noqa: BLE001 - l'errore viene mostrato all'utente
            job["error"] = f"{type(exc).__name__}: {exc}"
            job["status"] = "error"

    threading.Thread(target=runner, daemon=True).start()
    return job


def public_job(job):
    return {k: v for k, v in job.items() if k not in ("key", "phase_started")}


def resolved_key(path):
    return str(Path(path).expanduser().resolve())


def duplicate_summary(groups):
    return {
        "groups": len(groups),
        "files": sum(g["count"] for g in groups),
        "wasted_bytes": sum(g["wasted_bytes"] for g in groups),
    }


def find_duplicates(key, progress):
    """Doppioni esatti: stesso contenuto (SHA-256), controllato solo tra file della stessa dimensione."""
    cached = _CACHE.get(key)
    if not cached:
        raise HTTPException(status_code=400, detail="Esegui prima la scansione della cartella.")

    by_size = defaultdict(list)
    for item in cached["media_index"]:
        if item["size_bytes"]:
            by_size[item["size_bytes"]].append(item)
    candidates = [group for group in by_size.values() if len(group) > 1]
    total_files = sum(len(group) for group in candidates)
    total_bytes = sum(item["size_bytes"] for group in candidates for item in group)

    done_bytes = 0
    done_files = 0
    by_hash = defaultdict(list)
    progress("confronto", 0, total_bytes, f"Confronto del contenuto: 0 / {total_files} file")
    for group in candidates:
        for item in group:
            try:
                digest = hashlib.sha256()
                with open(item["path"], "rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        digest.update(chunk)
                        done_bytes += len(chunk)
                        progress("confronto", done_bytes, total_bytes,
                                 f"Confronto del contenuto: {done_files} / {total_files} file")
                by_hash[(item["size_bytes"], digest.hexdigest())].append(item)
            except OSError:
                done_bytes += item["size_bytes"]
            done_files += 1

    groups = []
    for (size, digest), items in by_hash.items():
        if len(items) < 2:
            continue
        items = sorted(items, key=lambda x: (len(x["filename"]), x["relative_path"].lower()))
        groups.append({
            "id": digest[:12],
            "count": len(items),
            "size_bytes": size,
            "wasted_bytes": size * (len(items) - 1),
            "files": [
                {k: item.get(k) for k in (
                    "path", "filename", "relative_path", "type",
                    "size_bytes", "width", "height", "taken_at")}
                for item in items
            ],
        })
    groups.sort(key=lambda g: (-g["wasted_bytes"], g["id"]))
    cached["duplicates"] = groups
    return {"summary": duplicate_summary(groups)}


@app.post("/api/jobs/scan")
def job_scan(path: str = Query(...)):
    base = Path(path).expanduser().resolve()
    if not base.is_dir():
        raise HTTPException(status_code=400, detail="La cartella selezionata non esiste o non è una cartella.")

    def work(progress):
        result = analyze_library(str(base), progress)
        _CACHE[str(base)] = result
        return {k: v for k, v in result.items() if k not in INTERNAL_KEYS}

    return public_job(start_job("scan", str(base), work))


@app.post("/api/jobs/duplicates")
def job_duplicates(path: str = Query(...)):
    key = resolved_key(path)
    if key not in _CACHE:
        raise HTTPException(status_code=400, detail="Esegui prima la scansione della cartella.")
    return public_job(start_job("duplicates", key, lambda progress: find_duplicates(key, progress)))


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Operazione non trovata.")
    return public_job(job)


@app.get("/api/duplicates")
def duplicates(path: str = Query(...), offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=200)):
    cached = _CACHE.get(resolved_key(path))
    if not cached or cached.get("duplicates") is None:
        return {"summary": None, "total": 0, "offset": 0, "groups": []}
    groups = cached["duplicates"]
    return {
        "summary": duplicate_summary(groups),
        "total": len(groups),
        "offset": offset,
        "groups": groups[offset:offset + limit],
    }


@app.get("/api/suspects")
def suspects(
    path: str = Query(...),
    category: Optional[str] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
):
    """File da rivedere (WhatsApp, screenshot, piccole senza EXIF). Sola lettura."""
    result = get_analysis(path)
    items = result["suspects"]
    if category:
        items = [i for i in items if i["category"] == category]
    return {
        "summary": result["suspects_summary"],
        "total": len(items),
        "offset": offset,
        "items": items[offset:offset + limit],
    }


class QuarantineRequest(BaseModel):
    root: str
    paths: List[str]


class RestoreRequest(BaseModel):
    ids: List[str] = []
    all: bool = False


def read_quarantine_log():
    try:
        with open(QUARANTINE_LOG, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def write_quarantine_log(entries):
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = QUARANTINE_LOG.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)
    os.replace(tmp, QUARANTINE_LOG)


def drop_from_cache(paths):
    """Toglie i file spostati dai sospetti in cache, senza rifare la scansione."""
    gone = set(paths)
    for cached in _CACHE.values():
        cached["media_index"] = [m for m in cached["media_index"] if m["path"] not in gone]
        if cached.get("duplicates") is not None:
            remaining = []
            for group in cached["duplicates"]:
                files = [f for f in group["files"] if f["path"] not in gone]
                if len(files) > 1:
                    remaining.append({
                        **group, "count": len(files), "files": files,
                        "wasted_bytes": group["size_bytes"] * (len(files) - 1),
                    })
            cached["duplicates"] = remaining
        cached["suspects"] = [s for s in cached["suspects"] if s["path"] not in gone]
        summary = {}
        for item in cached["suspects"]:
            entry = summary.setdefault(item["category"], {"count": 0, "size_bytes": 0})
            entry["count"] += 1
            entry["size_bytes"] += item["size_bytes"] or 0
        cached["suspects_summary"] = summary


@app.post("/api/quarantine")
def quarantine_files(req: QuarantineRequest):
    """Sposta i file scelti (e i loro JSON) in data/quarantena. Reversibile."""
    base = Path(req.root).expanduser().resolve()
    if not base.is_dir():
        raise HTTPException(status_code=400, detail="Cartella di partenza non valida.")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    entries = read_quarantine_log()
    moved, failed = [], []
    try:
        for raw in req.paths:
            target = Path(raw).expanduser().resolve()
            try:
                relative = target.relative_to(base)
            except ValueError:
                failed.append({"path": raw, "reason": "fuori dalla cartella analizzata"})
                continue
            if target.suffix.lower() not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS or not target.is_file():
                failed.append({"path": raw, "reason": "non è una foto o un video esistente"})
                continue

            destination = QUARANTINE_DIR / stamp / relative
            try:
                size = target.stat().st_size
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(destination))
            except OSError as exc:
                failed.append({"path": raw, "reason": f"errore: {exc.strerror or exc}"})
                continue

            sidecars = []
            for suffix in SIDECAR_SUFFIXES:
                side = target.with_name(target.name + suffix)
                if side.is_file():
                    side_destination = destination.with_name(destination.name + suffix)
                    try:
                        shutil.move(str(side), str(side_destination))
                        sidecars.append({"original_path": str(side), "quarantine_path": str(side_destination)})
                    except OSError:
                        pass

            entries.append({
                "id": uuid4().hex,
                "root": str(base),
                "relative_path": str(relative),
                "filename": target.name,
                "original_path": str(target),
                "quarantine_path": str(destination),
                "size_bytes": size,
                "moved_at": datetime.now().isoformat(timespec="seconds"),
                "sidecars": sidecars,
            })
            moved.append(str(target))
    finally:
        write_quarantine_log(entries)
        drop_from_cache(moved)
    return {"moved": len(moved), "failed": failed}


@app.get("/api/quarantine")
def quarantine_list(limit: int = Query(500, ge=1, le=5000)):
    entries = read_quarantine_log()
    recent = list(reversed(entries))[:limit]
    return {
        "count": len(entries),
        "size_bytes": sum(e.get("size_bytes") or 0 for e in entries),
        "items": [
            {k: e.get(k) for k in ("id", "relative_path", "filename", "size_bytes", "moved_at")}
            for e in recent
        ],
    }


@app.post("/api/quarantine/restore")
def quarantine_restore(req: RestoreRequest):
    """Rimette i file nella posizione originale (se libera)."""
    entries = read_quarantine_log()
    wanted = set(req.ids)
    remaining, restored, failed = [], 0, []
    try:
        for entry in entries:
            if not req.all and entry.get("id") not in wanted:
                remaining.append(entry)
                continue
            source = Path(entry["quarantine_path"])
            destination = Path(entry["original_path"])
            if not source.is_file():
                failed.append({"file": entry["filename"], "reason": "non più presente in quarantena"})
                remaining.append(entry)
                continue
            if destination.exists():
                failed.append({"file": entry["filename"], "reason": "esiste già un file nella posizione originale"})
                remaining.append(entry)
                continue
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(destination))
                for side in entry.get("sidecars", []):
                    side_source = Path(side["quarantine_path"])
                    side_destination = Path(side["original_path"])
                    if side_source.is_file() and not side_destination.exists():
                        shutil.move(str(side_source), str(side_destination))
                restored += 1
            except OSError as exc:
                failed.append({"file": entry["filename"], "reason": f"errore: {exc.strerror or exc}"})
                remaining.append(entry)
    finally:
        write_quarantine_log(remaining)
    return {"restored": restored, "failed": failed}


@app.get("/api/preview")
def preview(path: str = Query(...), root: str = Query(...)):
    base = Path(root).expanduser().resolve()
    target = Path(path).expanduser().resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=403, detail="Percorso fuori dalla cartella analizzata.")
    if not target.is_file() or target.suffix.lower() not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=404, detail="Immagine non trovata o formato non supportato.")
    return FileResponse(target)
