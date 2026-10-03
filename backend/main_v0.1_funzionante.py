from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import subprocess
import os
import json


app = FastAPI(title="PhotoCleaner")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif",
    ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".dng", ".raw", ".cr2", ".cr3", ".nef",
    ".arw", ".orf", ".rw2"
}


VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv",
    ".mts", ".m2ts", ".3gp", ".webm"
}


def normalize_name(name):
    return os.path.normcase(name).strip()


def json_candidates(json_filename):

    suffixes = [
        ".supplemental-metadata.json",
        ".supplemental-metadata(1).json",
        ".supplemental-metadata(2).json",
        ".supplemental-metadata(3).json",
        ".json"
    ]

    for suffix in suffixes:

        if json_filename.endswith(suffix):

            return [
                json_filename[:-len(suffix)]
            ]

    return []


@app.get("/")
def home():
    return {
        "app": "PhotoCleaner",
        "status": "online"
    }


@app.get("/api/status")
def status():

    return {
        "status": "online",
        "app": "PhotoCleaner",
        "version": "0.1.0"
    }


@app.get("/api/select-folder")
def select_folder():

    result = subprocess.run(
        [
            "zenity",
            "--file-selection",
            "--directory",
            "--title=Seleziona la cartella da analizzare"
        ],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:

        return {
            "selected": False,
            "path": None
        }


    return {
        "selected": True,
        "path": result.stdout.strip()
    }



def analyze_library(path):

    media_files = {}
    json_files = []

    photo_count = 0
    video_count = 0


    for root, dirs, files in os.walk(path):

        for filename in files:

            full_path = os.path.join(root, filename)

            ext = os.path.splitext(filename)[1].lower()


            if ext in IMAGE_EXTENSIONS:

                photo_count += 1

                media_files[normalize_name(filename)] = {
                    "path": full_path,
                    "filename": filename,
                    "type": "photo"
                }


            elif ext in VIDEO_EXTENSIONS:

                video_count += 1

                media_files[normalize_name(filename)] = {
                    "path": full_path,
                    "filename": filename,
                    "type": "video"
                }


            elif ext == ".json":

                json_files.append(full_path)



    matched_media = set()
    matched_json = set()

    orphan_json = []


    for json_path in json_files:

        filename = os.path.basename(json_path)


        try:

            with open(
                json_path,
                "r",
                encoding="utf-8"
            ) as f:

                metadata = json.load(f)


        except:

            continue



        candidates = []


        title = metadata.get("title")

        if isinstance(title, str) and title.strip():

            candidates.append(title.strip())


        candidates.extend(
            json_candidates(filename)
        )


        found = False


        for candidate in candidates:

            key = normalize_name(
                os.path.basename(candidate)
            )


            if key in media_files:

                matched_media.add(
                    media_files[key]["path"]
                )

                matched_json.add(
                    json_path
                )

                found = True
                break



        if not found:

            orphan_json.append({

                "json": filename,

                "title": metadata.get("title"),

                "photoTakenTime":
                    metadata.get(
                        "photoTakenTime",
                        {}
                    ).get("formatted"),

                "creationTime":
                    metadata.get(
                        "creationTime",
                        {}
                    ).get("formatted"),

                "url":
                    metadata.get("url")

            })



    media_without_json = []


    for media in media_files.values():

        if media["path"] not in matched_media:

            media_without_json.append({

                "file": media["filename"],

                "type": media["type"],

                "path": media["path"]

            })


    return {

        "photos": photo_count,

        "videos": video_count,

        "json": len(json_files),

        "total_files":
            photo_count +
            video_count +
            len(json_files),

        "matched_media":
            len(matched_media),

        "matched_json":
            len(matched_json),

        "orphan_json":
            len(orphan_json),

        "media_without_json":
            len(media_without_json),

        "orphan_json_examples":
            orphan_json[:20],

        "media_without_json_examples":
            media_without_json[:20]

    }



@app.get("/api/scan")
def scan(path: str = Query(...)):

    result = analyze_library(path)

    result["path"] = path

    return result



@app.get("/api/scan-details")
def scan_details(path: str = Query(...)):

    result = analyze_library(path)

    return {

        "orphan_json_count":
            result["orphan_json"],

        "media_without_json_count":
            result["media_without_json"],

        "orphan_json_examples":
            result["orphan_json_examples"],

        "media_without_json_examples":
            result["media_without_json_examples"]

    }
