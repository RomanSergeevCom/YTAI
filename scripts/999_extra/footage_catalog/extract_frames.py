#!/usr/bin/env python3
"""Extract one mid-clip frame per video from local YTFP footage folders."""
import json, os, subprocess, sys

ROOT = "/Volumes/T7-Beige-RYA/YTFP"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thumbs")
os.makedirs(OUT, exist_ok=True)

FOLDERS = [
    "00_Lyudmila_Chibireva_Home_Archive",
    "02_Lyudmila_Chibireva_Cochlear_Implant",
    "04_Center_BTS",
    "05_Yulia_Reznik_Interview",
    "06_Yulia_Reznik_Kids_Session",
    "07_Tatyana_Nesterenko_Neuroplasticity",
    "08_Tatyana_Nesterenko_Center_Tour",
    "09_Maria_Gaidarova_Kids_Session",
    "11_Tatyana_Kislyakova_Director_Vision",
    "13_Olga_Gritsay_Legal_Rights",
]

meta = {}
for folder in FOLDERS:
    fpath = os.path.join(ROOT, folder)
    vids = []
    for dirpath, dirnames, filenames in os.walk(fpath):
        dirnames[:] = [d for d in dirnames if d not in ("Audio", "Transcripts")]
        for fn in sorted(filenames):
            if fn.lower().endswith((".mp4", ".mov", ".mts")) and not fn.startswith("._"):
                vids.append(os.path.join(dirpath, fn))
    vids.sort()
    meta[folder] = []
    for v in vids:
        rel = os.path.relpath(v, fpath)
        size = os.path.getsize(v)
        try:
            dur = float(subprocess.check_output(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", v], text=True).strip())
        except Exception:
            dur = 0.0
        thumb = f"{folder[:2]}_{rel.replace('/', '__').rsplit('.',1)[0]}.jpg"
        tpath = os.path.join(OUT, thumb)
        if not os.path.exists(tpath):
            ss = max(dur * 0.4, 1.0)
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(ss),
                 "-i", v, "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "6",
                 "-y", tpath], capture_output=True)
            if r.returncode != 0 or not os.path.exists(tpath):
                # retry near start
                subprocess.run(
                    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "1",
                     "-i", v, "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "6",
                     "-y", tpath], capture_output=True)
        meta[folder].append({
            "rel": rel, "size": size, "dur": dur,
            "thumb": thumb if os.path.exists(tpath) else None,
        })
        print(f"{folder}/{rel}  {dur:.0f}s", flush=True)

with open(os.path.join(os.path.dirname(OUT), "local_meta.json"), "w") as f:
    json.dump(meta, f, ensure_ascii=False, indent=1)
print("DONE")
