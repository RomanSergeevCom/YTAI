#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S1 · перепись съёмочного дня: что вообще лежит на карте.

Один проход ffprobe по каждому файлу + чтение сайдкаров Sony и тегов DJI.
Дальше ВСЕ стадии дня читают `index.json` и карту больше не сканируют:
перепись должна быть одна, иначе числа стадий расходятся, и поймать это
можно только глазами в Premiere.

  python3 index.py                      # перепись, печатает сводку
  python3 index.py --day other.json     # другой съёмочный день

Выход: {work}/index.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (die, dirs, duration_of, ffprobe_json, load_day, log,  # noqa: E402
                    measure_rms_db, save_json)

# TX01_MIC003_20260923_161629_orig.wav → (TX01, 2026-09-23 16:16:29)
MIC_RE = re.compile(r"^(TX\d+)_MIC\d+_(\d{8})_(\d{6})_")
VIDEO_EXT = (".mp4", ".mov", ".mxf", ".mts", ".m4v")


def sony_gamma(clip: Path, suffix: str):
    """Гамма из сайдкара Sony, а не из догадки по модели камеры.

    ⚠️ MEDIAPRO.XML про камеру врёт; `CaptureGammaEquation` в {stem}{suffix}
    — измеренная величина. Проверено на этой карте: s-log3-cine у обеих тушек.
    """
    x = clip.with_name(clip.stem + suffix)
    if not x.exists():
        return None, None
    d = x.read_text(encoding="utf-8", errors="replace")
    g = re.search(r'CaptureGammaEquation"?\s+value="([^"]+)"', d)
    c = re.search(r'CaptureColorPrimaries"?\s+value="([^"]+)"', d)
    return (g.group(1) if g else None), (c.group(1) if c else None)


def creation_local(doc):
    """creation_time контейнера → локальное время без зоны.

    ⚠️ Sony пишет метку в UTC (`…Z`), сайдкар — в +03:00. После astimezone()
    обе дают одно и то же настенное время, поэтому сайдкар для синхрона не нужен.
    Но зона процесса обязана быть верной — см. common.env_for_mlx.
    """
    t = (doc.get("format", {}).get("tags") or {}).get("creation_time")
    if not t:
        return None
    try:
        return (dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
                .astimezone().replace(tzinfo=None).isoformat(timespec="seconds"))
    except ValueError:
        return None


def timecode_of(doc):
    """ТС ищем на дорожках data/video ПЕРЕД контейнером.

    ⚠️ Sony держит таймкод на data-дорожке `rtmd`, и `format_tags=timecode` у
    неё пуст. Ровно эта проверка «только в контейнере» потеряла таймкод во всех
    441 прокси комплекта YTCH, и нашли это через месяц.
    """
    for s in doc.get("streams", []):
        if s.get("codec_type") in ("data", "video"):
            tc = (s.get("tags") or {}).get("timecode")
            if tc:
                return tc, s.get("codec_tag_string") or s.get("codec_type")
    tc = (doc.get("format", {}).get("tags") or {}).get("timecode")
    return (tc, "format") if tc else (None, None)


def probe_clip(path: Path, cam: dict):
    doc = ffprobe_json(path)
    if not doc:
        return {"file": path.name, "path": str(path), "ok": False,
                "why": "ffprobe не прочитал файл"}
    vs = next((s for s in doc.get("streams", []) if s.get("codec_type") == "video"), {})
    aud = [s for s in doc.get("streams", []) if s.get("codec_type") == "audio"]
    tc, tc_src = timecode_of(doc)
    fmt_tags = doc.get("format", {}).get("tags") or {}
    gamma = gamut = None
    gsrc = None
    if cam.get("sidecar"):
        gamma, gamut = sony_gamma(path, cam["sidecar"])
        gsrc = f"сайдкар {cam['sidecar']}" if gamma else None
    if not gamma and fmt_tags.get("com.dji.camera.ColorGammaSxS"):
        gamma = fmt_tags["com.dji.camera.ColorGammaSxS"]
        gsrc = "тег com.dji.camera.ColorGammaSxS"
    return {
        "file": path.name, "path": str(path), "ok": True,
        "cam": cam["role"], "kind": cam["kind"],
        "size": int(doc.get("format", {}).get("size") or 0),
        "dur": round(duration_of(doc), 3),
        "w": vs.get("width"), "h": vs.get("height"),
        "fps": vs.get("r_frame_rate"), "vcodec": vs.get("codec_name"),
        "profile": vs.get("profile"), "pix_fmt": vs.get("pix_fmt"),
        "color": [vs.get("color_space") or "", vs.get("color_primaries") or "",
                  vs.get("color_transfer") or ""],
        "audio": [{"codec": a.get("codec_name"), "ch": a.get("channels")} for a in aud],
        "timecode": tc, "timecode_src": tc_src,
        "created": creation_local(doc),
        "gamma": gamma, "gamut": gamut, "gamma_src": gsrc,
        "encoder": fmt_tags.get("encoder"),
        "model": fmt_tags.get("com.dji.camera.CameraModel"),
    }


def probe_mic(path: Path, day, dead: set):
    doc = ffprobe_json(path)
    m = MIC_RE.match(path.name)
    wall = None
    if m:
        try:
            wall = dt.datetime.strptime(m.group(2) + m.group(3),
                                        "%Y%m%d%H%M%S").isoformat(timespec="seconds")
        except ValueError:
            wall = None
    dur = duration_of(doc)                      # 0.0, если ключа нет вовсе
    rel = str(path.relative_to(day["card"]))
    rec = {"file": path.name, "path": str(path), "rel": rel,
           "tx": m.group(1) if m else None,
           "wall_name": wall, "dur": round(dur, 3),
           "size": path.stat().st_size,
           "dead": rel in dead or dur <= 0.0}
    if not rec["dead"]:
        mean, peak = measure_rms_db(path)
        rec["rms_db"], rec["peak_db"] = mean, peak
    return rec


def main():
    ap = argparse.ArgumentParser(description="перепись съёмочного дня (0121_studio_day)")
    ap.add_argument("--day", default=None, help="описание дня (по умолчанию day.json рядом)")
    a = ap.parse_args()

    day = load_day(a.day)
    D = dirs(day)
    card = day["card"]
    if not card.is_dir():
        die(f"карта не примонтирована: {card}")

    dead = set(day.get("known_dead") or [])
    junk = {Path(j).name for j in (day.get("junk_clips") or [])}

    log(f"перепись {day['code']} · {day['day']} · карта {card}", day=day)

    clips = []
    for cam in day["cameras"]:
        d = card / cam["dir"]
        if not d.is_dir():
            die(f"нет папки камеры {cam['role']}: {d}")
        got = sorted(p for p in d.iterdir()
                     if p.suffix.lower() in VIDEO_EXT and not p.name.startswith("."))
        for p in got:
            rec = probe_clip(p, cam)
            rec["junk"] = p.name in junk
            clips.append(rec)
        log(f"  {cam['role']:<14} {len(got):>3} клипов", day=day)

    mics = []
    for d in sorted(card.glob(day["mic_glob"])):
        for p in sorted(d.glob("*" + day["mic_keep"])):
            mics.append(probe_mic(p, day, dead))
    log(f"  петлички       {len(mics):>3} кусков "
        f"({sum(1 for m in mics if m['dead'])} мёртвых)", day=day)

    doc = {"schema": "ytai-studio-day-index-v1",
           "code": day["code"], "day": day["day"], "card": str(card),
           "clips": clips, "mics": mics}
    out = save_json(D["work"] / "index.json", doc)

    # ── сводка и гейт: расхождение с замером = карта прочитана не полностью
    lesson = [c for c in clips if c.get("kind") == "lesson" and not c.get("junk")]
    bts = [c for c in clips if c.get("kind") == "bts"]
    jn = [c for c in clips if c.get("junk")]
    alive = [m for m in mics if not m["dead"]]
    exp = day.get("expected") or {}
    print()
    print(f"  урочных клипов   {len(lesson):>3}   {sum(c['dur'] for c in lesson)/60:6.1f} мин")
    print(f"  BTS              {len(bts):>3}   {sum(c['dur'] for c in bts)/60:6.1f} мин")
    print(f"  обрывков         {len(jn):>3}")
    print(f"  петличек живых   {len(alive):>3}   {sum(m['dur'] for m in alive)/3600:6.2f} ч")
    print(f"\n  → {out}")

    bad = []
    for key, got in (("lesson_clips", len(lesson)), ("bts_clips", len(bts)),
                     ("junk_clips", len(jn)), ("mic_chunks_total", len(mics)),
                     ("mic_chunks_with_speech", len(alive))):
        if key in exp and exp[key] != got:
            bad.append(f"{key}: ждали {exp[key]}, нашли {got}")
    nogamma = [c["file"] for c in clips if c["ok"] and not c.get("gamma")]
    if nogamma:
        bad.append(f"без гаммы {len(nogamma)}: {', '.join(nogamma[:5])}")
    broken = [c["file"] for c in clips if not c["ok"]]
    if broken:
        bad.append(f"не прочитались: {', '.join(broken)}")
    if bad:
        print()
        for b in bad:
            print(f"  ⚠ {b}")
        die("перепись не сошлась с замером дня — разобрать до следующих стадий", 3)
    print("\n  гейт пройден: перепись сошлась с замером дня")
    return 0


if __name__ == "__main__":
    sys.exit(main())
