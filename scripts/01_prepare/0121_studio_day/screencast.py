#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S7 · скринкасты: что именно показано на экране и к какому уроку это относится.

Экран эксперт пишет сам на своём маке, поэтому это отдельный источник, а не
камера. И у него есть то, чего нет у камерного материала: **имя файла уже
содержит номер урока** — в схеме эксперта, с цифрой съёмочного дня. Это прямая
привязка, сильнее любого сопоставления по словам; переводим её таблицей из
`day.json` и храним ОБА номера, не подменяя одно другим.

Карта экранов строится **локальным Apple Vision OCR**, а не свипом VLM.
Замер (YTAgeFree05, 10.08): OCR прожевал 924 кадра за 51 секунду и дал
дословный текст без галлюцинаций, а агентский свип наврал — назвал плашку
CTA заставкой главы и слепил 42 экрана в 29. VLM остаётся на смысловой слой:
одна подпись на экран, а не на кадр.

  python3 screencast.py --index        # только перепись и привязка к урокам
  python3 screencast.py                # + кадры + OCR + группировка
  python3 screencast.py --vlm          # + смысловая подпись каждому экрану

Выход: {work}/screencasts.json · {work}/sc_frames/ · {work}/sc_ocr.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (die, dirs, duration_of, ffprobe_json, load_day,  # noqa: E402
                    load_json, log, run, save_json)

OCR_BIN = Path.home() / "YTAI/scripts/999_extra/bin/vision_ocr_ru"
VIDEO_EXT = (".mov", ".mp4", ".m4v")
NUM_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?")
# угловой бейдж и хром браузера повторяются на КАЖДОМ кадре и склеивают все
# экраны в один — на группировку они не идут
CHROME = re.compile(r"bokorev|partners|telegram|chatgpt\.com/c/|^https?$|^view$", re.I)
MIN_WORD = 4


def canon(name, nmap):
    """«1.2.3..mov» → (услышанный номер эксперта, канонический id урока)."""
    m = NUM_RE.match(name)
    if not m:
        return None, None, None
    day_n, blk, les = int(m.group(1)), int(m.group(2)), int(m.group(3))
    part = int(m.group(4)) if m.group(4) else None
    heard = f"{day_n}.{blk}.{les}" + (f".{part}" if part else "")
    key = f"{day_n}.{blk}"
    tgt = nmap.get(key)
    if isinstance(tgt, list):
        cid = tgt[les - 1] if 1 <= les <= len(tgt) else None
    elif isinstance(tgt, str):
        cid = f"{tgt}.{les}"
    else:
        cid = None
    return heard, cid, part


def words(text):
    out = []
    for w in re.split(r"[^\w]+", (text or "").lower().replace("ё", "е")):
        if len(w) >= MIN_WORD and not CHROME.match(w):
            out.append(w)
    return out


def group_screens(frames, thresh=0.45):
    """Соседние кадры — один экран, если делят достаточно СОДЕРЖАТЕЛЬНЫХ слов.

    ⚠️ Хром браузера и бейдж агентства стоят на каждом кадре; без их отсева
    любые два кадра «похожи» и весь скринкаст схлопывается в один экран.
    """
    screens = []
    for f in frames:
        w = set(f["words"])
        if screens:
            prev = screens[-1]["_w"]
            inter = len(w & prev)
            union = len(w | prev) or 1
            if union and inter / union >= thresh:
                screens[-1]["t_out"] = f["t"]
                screens[-1]["_w"] = prev | w
                screens[-1]["frames"].append(f["t"])
                if len(f["words"]) > screens[-1]["_best_n"]:
                    screens[-1]["best"] = f["t"]
                    screens[-1]["_best_n"] = len(f["words"])
                    screens[-1]["text"] = f["text"][:600]
                continue
        screens.append({"t_in": f["t"], "t_out": f["t"], "best": f["t"],
                        "frames": [f["t"]], "text": f["text"][:600],
                        "_w": set(w), "_best_n": len(f["words"])})
    for s in screens:
        s["keywords"] = [w for w, _ in Counter(
            [x for x in s["_w"]]).most_common(14)]
        s.pop("_w"), s.pop("_best_n")
        s["sec"] = round(s["t_out"] - s["t_in"] + 1, 1)
    return screens


def main():
    ap = argparse.ArgumentParser(description="скринкасты дня (0121_studio_day)")
    ap.add_argument("--day", default=None)
    ap.add_argument("--index", action="store_true", help="только перепись и привязка")
    ap.add_argument("--vlm", action="store_true", help="смысловая подпись каждому экрану")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    day = load_day(a.day)
    D = dirs(day)
    cfg = day.get("screencasts") or die("в day.json нет раздела screencasts")
    src = day["card"] / cfg["dir"]
    if not src.is_dir():
        die(f"нет папки скринкастов: {src}")
    nmap = {k: v for k, v in (cfg.get("number_map") or {}).items() if not k.startswith("_")}
    cards = {c["id"]: c for c in
             (load_json(day["preprod"] / "05_Lessons/cards.json") or {}).get("cards", [])}

    files = sorted(p for p in src.iterdir()
                   if p.suffix.lower() in VIDEO_EXT and not p.name.startswith("."))
    log(f"скринкастов {len(files)} в {src}", day=day)

    items = []
    for p in files:
        doc = ffprobe_json(p)
        v = next((s for s in doc.get("streams", []) if s["codec_type"] == "video"), {})
        heard, cid, part = canon(p.name, nmap)
        items.append({
            "file": p.name, "path": str(p), "heard": heard, "lesson": cid,
            "part": part, "title": (cards.get(cid) or {}).get("title"),
            "kind_planned": (cards.get(cid) or {}).get("kind"),
            "dur": round(duration_of(doc), 1),
            "w": v.get("width"), "h": v.get("height"),
            "fps_reported": v.get("r_frame_rate"), "vcodec": v.get("codec_name"),
            "size": int(doc.get("format", {}).get("size") or 0),
            "bitrate_mbit": round(int(doc.get("format", {}).get("bit_rate") or 0) / 1e6, 2),
        })

    print(f"\n  {'файл':<30} {'услышан':<9} {'урок':<8} {'мин':>5} {'Мбит/с':>7}  название")
    for it in items:
        print(f"  {it['file'][:29]:<30} {str(it['heard']):<9} {str(it['lesson']):<8} "
              f"{it['dur']/60:5.1f} {it['bitrate_mbit']:>7.1f}  {(it['title'] or '—')[:34]}")
    nomap = [i["file"] for i in items if not i["lesson"]]
    if nomap:
        print(f"\n  ⚠ номер не разобран: {nomap}")
    unknown = [i for i in items if i["lesson"] and not i["title"]]
    if unknown:
        print(f"  ⚠ урока нет в карточках: {[i['lesson'] for i in unknown]}")

    doc = {"schema": "ytai-screencasts-v1", "code": day["code"], "day": day["day"],
           "source": str(src), "items": items}
    if a.index:
        save_json(D["work"] / "screencasts.json", doc)
        print(f"\n  → {D['work'] / 'screencasts.json'}")
        return 0

    # ── кадры
    fdir = D["work"] / "sc_frames"
    fps, sw = cfg["ocr"]["fps"], cfg["ocr"]["scale_w"]
    for it in items:
        out = fdir / Path(it["file"]).stem.replace(" ", "_")
        if out.is_dir() and any(out.iterdir()) and not a.force:
            it["frames_dir"] = str(out)
            continue
        out.mkdir(parents=True, exist_ok=True)
        r = run(["ffmpeg", "-nostdin", "-v", "error", "-i", it["path"],
                 "-vf", f"fps={fps},scale={sw}:-2", "-q:v", "4",
                 str(out / "f_%05d.jpg")], timeout=3600)
        it["frames_dir"] = str(out)
        log(f"  кадры {it['file'][:34]:<36} {len(list(out.glob('*.jpg'))):>5}", day=day)

    # ── OCR
    all_frames = sorted(fdir.rglob("*.jpg"))
    ocr_f = D["work"] / "sc_ocr.jsonl"
    done = set()
    if ocr_f.exists() and not a.force:
        for ln in ocr_f.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(ln)["file"])
            except Exception:                                      # noqa: BLE001
                pass
    todo = [str(p) for p in all_frames if str(p) not in done]
    log(f"OCR: кадров {len(all_frames)}, к распознаванию {len(todo)}", day=day)
    with ocr_f.open("a", encoding="utf-8") as fh:
        for i in range(0, len(todo), 200):
            batch = todo[i:i + 200]
            p = subprocess.run([str(OCR_BIN), "--langs", "ru,en"],
                               input="\n".join(batch), capture_output=True,
                               text=True, timeout=1800)
            fh.write(p.stdout)
            fh.flush()
            log(f"  ocr {min(i+200, len(todo))}/{len(todo)}", day=day)

    # ── группировка в экраны
    by_file = {}
    for ln in ocr_f.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
        except Exception:                                          # noqa: BLE001
            continue
        p = Path(r["file"])
        txt = " ".join(l.get("t", "") for l in r.get("lines", []))
        by_file.setdefault(p.parent.name, []).append(
            {"t": round((int(p.stem.split("_")[-1]) - 1) / fps, 1),
             "text": txt, "words": words(txt), "faces": r.get("faces", 0)})
    for it in items:
        key = Path(it["file"]).stem.replace(" ", "_")
        fr = sorted(by_file.get(key, []), key=lambda x: x["t"])
        it["screens"] = group_screens(fr) if fr else []
        it["n_frames"] = len(fr)

    print(f"\n  {'файл':<30} {'урок':<8} {'кадров':>7} {'экранов':>8}  первые ключевые слова")
    for it in items:
        kw = (it["screens"][0]["keywords"][:6] if it["screens"] else [])
        print(f"  {it['file'][:29]:<30} {str(it['lesson']):<8} {it['n_frames']:>7} "
              f"{len(it['screens']):>8}  {', '.join(kw)}")

    if a.vlm:
        from vlm_caption import caption_screens                    # noqa: E402
        caption_screens(items, fdir, fps, day)

    doc["items"] = items
    save_json(D["work"] / "screencasts.json", doc)
    print(f"\n  → {D['work'] / 'screencasts.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
