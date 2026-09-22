#!/usr/bin/env python3
"""write_angles.py — записать синхрон ракурса B сцены в 05_Review/angles.json.

Синхрон считается по ЗВУКУ, не по часам камер: звук ракурса B (Blackmagic) ищется на мастер-дорожке
ракурса A (Sony, клипы встык) нормированной кросс-корреляцией — сначала огибающая, потом сырой сигнал
(scratch: xcorr_sync.py / scan_offsets.py). Где у A дыра записи, смещение B скачет — поэтому карта
кусочная: у каждого непрерывного участка A своё смещение.

  master_t = offset + clip_b_t * rate      (внутри участка master_from … master_to)

  python3 write_angles.py --scene scene1 --file A004_11201111_C010.mov --duration 1515.88 \
      --tc 11:11:46:02 --size "140,1 ГБ" --seg "0:1047.36:6.07:1.0" --seg "1047.36:1e9:2.92:1.0" \
      --points 23 --note-file note.html
"""
import argparse
import json
from pathlib import Path

BASE = Path("/Volumes/T9-Black-RYA/YTEVO/YTEVO02_evolution_manifesto/00_Setup")
OUT = BASE / "05_Review" / "angles.json"


def mmss(t):
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m):02d}:{s:05.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True, choices=["scene1", "scene2"])
    ap.add_argument("--file", required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--tc", default="")
    ap.add_argument("--size", default="")
    ap.add_argument("--folder", default="")
    ap.add_argument("--seg", action="append", required=True, help="master_from:master_to:offset:rate")
    ap.add_argument("--points", type=int, default=0, help="сколько независимых окон подтвердили карту")
    ap.add_argument("--max-resid-ms", type=float, default=None)
    ap.add_argument("--note-file", default=None)
    a = ap.parse_args()

    segs = []
    for s in a.seg:
        f, t, o, r = s.split(":")
        segs.append({"master_from": float(f), "master_to": float(t), "offset": float(o), "rate": float(r)})
    gaps = [{"at": round(p["master_to"], 3), "a_missing_s": round(p["offset"] - n["offset"], 3)}
            for p, n in zip(segs, segs[1:])]
    map_text = " · ".join(
        (f"с {mmss(sg['master_from'])} " if sg["master_from"] > 0 else "") + f"сдвиг {sg['offset']:+.3f} с"
        for sg in segs)
    d = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"schema": "ytevo02-angles-v1"}
    d[a.scene] = {"angles": {"B": {
        "file": a.file, "folder": a.folder, "duration": a.duration, "tc": a.tc, "size": a.size,
        "on_ssd": (BASE.parent / a.folder / a.file).exists(),
        "drive_path": f"gdrive_ytevo:YTEVO S1/{BASE.parent.name}/{a.folder}/{a.file}",
        "offset": segs[0]["offset"], "rate": segs[0]["rate"], "segments": segs, "a_gaps": gaps,
        "map_text": map_text, "method": "xcorr по звуку (огибающая → сырой сигнал), 16 кГц моно",
        "points": a.points, "max_resid_ms": a.max_resid_ms,
        "note_html": Path(a.note_file).read_text(encoding="utf-8") if a.note_file else ""}}}
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{a.scene}: {a.file} · {map_text} · дыр A: {len(gaps)} → {OUT}")


if __name__ == "__main__":
    main()
