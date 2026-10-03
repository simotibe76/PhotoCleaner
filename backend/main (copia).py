from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path
from collections import defaultdict
from datetime import datetime
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


def analyze_library(path):
    base = Path(path).expanduser().resolve()
    if not base.exists() or not base.is_dir():
        raise HTTPException(status_code=400, detail="La cartella selezionata non esiste o non è una cartella.")

    media = []
    json_files = []
    photos = videos = 0

    for root, dirs, files in os.walk(base):
        dirs.sort()
        files.sort()
        for filename in files:
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
    for json_path in json_files:
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
        "groups": review_groups[:300],
        "pillow_available": PIL_AVAILABLE,
    }


@app.get("/")
def home():
    return {"app": "PhotoCleaner", "status": "online"}


@app.get("/api/status")
def status():
    return {"status": "online", "app": "PhotoCleaner", "version": "0.2.0"}


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
    result = analyze_library(path)
    # Frontend uses these totals and candidate groups; nothing is modified.
    return result


@app.get("/api/scan-details")
def scan_details(path: str = Query(...)):
    result = analyze_library(path)
    return {
        "orphan_json_count": result["orphan_json"],
        "media_without_json_count": result["media_without_json"],
        "orphan_json_examples": result["orphan_json_examples"],
        "media_without_json_examples": result["media_without_json_examples"],
        "groups_count": result["groups_count"],
        "groups": result["groups"],
    }


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
