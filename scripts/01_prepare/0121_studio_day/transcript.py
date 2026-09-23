#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S8 · читаемый транскрипт дня: двое людей на одной шкале.

Говорящих ровно двое, и кто где — известно ЖЕЛЕЗОМ: TX01 на эксперте, TX02 на
продюсере. Поэтому ни pyannote, ни реестра голосов здесь не нужно. Нужна одна
вещь, которой железо не решает: **проникание**. Микрофон эксперта слышит
продюсера и наоборот, whisper честно расшифровывает обе дорожки целиком, и без
отсечки каждая реплика попала бы в транскрипт дважды — от обоих.

Отсекаем ЗАМЕРОМ, а не моделью: у своего говорящего его собственный микрофон
громче. Сравниваем энергию двух дорожек на одном и том же отрезке настенного
времени и оставляем реплику той, где громче.

⚠️ Сравнивать по рабочим копиям НАПРЯМУЮ нельзя. Они нормированы к −20 дБ
РАЗНЫМ усилением: TX01 получил +12…+20 дБ, TX02 +29…+34 (он тише на 15-20 дБ,
говорит редко, микрофон слышит зал). После нормировки обе дорожки одинаково
громкие, и сравнение показало бы чушь. Поэтому усиление вычитается обратно —
сравнение идёт в исходном масштабе.

Почему не «собрать одно аудио таймлайна и расшифровать целиком», как канон
велит для ката: там источников много и они разнородны, здесь их ровно два и у
каждого известен человек. Склейка ничего не добавила бы, а право на реплику
всё равно решается сравнением энергии.

  python3 transcript.py

Выход: {project}/01_Source/Transcription/
         {CODE}_day1_transcript.txt    ЧЧ:ММ:СС  Имя: текст
         {CODE}_day1_transcript.json   пословно, с дорожкой и уровнями
       + {CODE}_{урок}.txt по урокам, когда карта дублей готова
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import wave
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import die, dirs, load_day, load_json, log, save_json  # noqa: E402

BLEED_DB = 4.0        # порог: своя дорожка должна быть громче на столько
HOP = 0.25            # шаг огибающей, с


def envelope(wav_path, gain_db):
    """Огибающая в ИСХОДНОМ масштабе: применённое усиление вычитается обратно."""
    with wave.open(str(wav_path), "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    import array
    a = array.array("h")
    a.frombytes(raw)
    step = max(1, int(sr * HOP))
    out = []
    for i in range(0, len(a) - step, step):
        s = 0
        chunk = a[i:i + step]
        for v in chunk:
            s += v * v
        rms = math.sqrt(s / len(chunk)) / 32768.0
        db = 20 * math.log10(rms + 1e-9) - (gain_db or 0.0)
        out.append(db)
    return out, HOP


def level_at(env, hop, t0, t1):
    """Средний уровень дорожки на отрезке её ЛОКАЛЬНОГО времени."""
    i0, i1 = int(t0 / hop), max(int(t0 / hop) + 1, int(t1 / hop))
    part = env[max(0, i0):min(len(env), i1)]
    return (sum(part) / len(part)) if part else -120.0


def hhmmss(sec):
    s = int(sec)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def main():
    ap = argparse.ArgumentParser(description="читаемый транскрипт дня")
    ap.add_argument("--day", default=None)
    a = ap.parse_args()
    day = load_day(a.day)
    D = dirs(day)

    res = load_json(D["work"] / "days/full/Transcription/_wordsync/wordsync_result.json")
    if not res:
        die("нет wordsync_result.json — сначала sync.py")
    au = {r["akey"]: r for r in (load_json(D["work"] / "audio.json") or {}).get("items", [])}
    chunks = {c["chunk_id"]: c for c in res.get("chunks", [])}
    people = day["people"]

    # ── огибающие обеих дорожек, в исходном масштабе
    env = {}
    for akey, rec in au.items():
        if rec.get("kind") != "mic" or not rec.get("wav"):
            continue
        ch = chunks.get(akey) or next((v for k, v in chunks.items() if k.startswith(akey)), None)
        if not ch or ch.get("wall_start") is None:
            continue
        e, hop = envelope(Path(rec["wav"]), rec.get("gain_db"))
        env[akey] = {"env": e, "hop": hop, "w0": ch["wall_start"],
                     "tx": rec.get("tx"), "gain": rec.get("gain_db")}
    if not env:
        die("ни одна петличка не легла на шкалу — транскрипт собирать не из чего")
    log(f"огибающих: {len(env)} " +
        ", ".join(f"{k[:22]} усиление {v['gain']:+.0f}" for k, v in list(env.items())[:3]),
        day=day)

    # ── сегменты обеих дорожек на общей шкале
    segs = []
    for p in sorted(D["words"].glob("*.words.json")):
        doc = load_json(p) or {}
        if doc.get("kind") != "mic" or not doc.get("speech"):
            continue
        akey = p.name[:-len(".words.json")]
        meta = env.get(akey)
        if not meta:
            continue
        for s in doc.get("segments", []):
            segs.append({"akey": akey, "tx": doc.get("tx"),
                         "t0": s["s"], "t1": s["e"],
                         "wall0": meta["w0"] + s["s"], "wall1": meta["w0"] + s["e"],
                         "text": s.get("text", "").strip(),
                         "words": s.get("words", [])})
    segs.sort(key=lambda s: s["wall0"])
    log(f"сегментов обеих дорожек: {len(segs)}", day=day)

    # ── отсечка проникания: реплика остаётся той дорожке, где она громче
    kept, dropped = [], 0
    for s in segs:
        mine = env[s["akey"]]
        own = level_at(mine["env"], mine["hop"], s["t0"], s["t1"])
        other = None
        for akey, m in env.items():
            if m["tx"] == s["tx"]:
                continue
            lo, hi = s["wall0"] - m["w0"], s["wall1"] - m["w0"]
            if hi < 0 or lo > len(m["env"]) * m["hop"]:
                continue
            v = level_at(m["env"], m["hop"], max(0, lo), hi)
            other = v if other is None else max(other, v)
        s["db_own"], s["db_other"] = round(own, 1), (round(other, 1) if other is not None else None)
        if other is not None and other > own + BLEED_DB:
            dropped += 1
            s["bleed"] = True
            continue
        s["bleed"] = False
        kept.append(s)
    log(f"проникание отсечено: {dropped} сегментов из {len(segs)} "
        f"(порог {BLEED_DB:.0f} дБ)", day=day)

    # ── читаемый текст
    t0 = min(s["wall0"] for s in kept)
    lines, cur = [], None
    for s in kept:
        who = people.get(s["tx"], {}).get("name", s["tx"] or "?")
        rel = s["wall0"] - t0
        if cur and cur["who"] == who and rel - cur["end"] < 12:
            cur["text"] += " " + s["text"]
            cur["end"] = s["wall1"] - t0
        else:
            if cur:
                lines.append(cur)
            cur = {"who": who, "t": rel, "end": s["wall1"] - t0, "text": s["text"]}
    if cur:
        lines.append(cur)

    outdir = day["project"] / "01_Source/Transcription"
    outdir.mkdir(parents=True, exist_ok=True)
    head = (f"{day['code']} · съёмочный день {day['day']}\n"
            f"Говорящих двое, дорожка = человек: "
            + " · ".join(f"{k} — {v['name']}" for k, v in people.items()) + "\n"
            f"Отсчёт от первой реплики ({datetime.fromtimestamp(t0):%H:%M:%S} по стене). "
            f"Проникание отсечено сравнением энергии дорожек.\n"
            + "─" * 78 + "\n\n")
    txt = head + "\n".join(f"{hhmmss(l['t'])}  {l['who']}: {l['text']}" for l in lines)
    ftxt = outdir / f"{day['code']}_day1_transcript.txt"
    ftxt.write_text(txt, encoding="utf-8")

    doc = {"schema": "ytai-day-transcript-v1", "code": day["code"], "day": day["day"],
           "people": people, "t0_wall": t0,
           "bleed_threshold_db": BLEED_DB, "segments_dropped_as_bleed": dropped,
           "n_segments": len(kept), "n_words": sum(len(s["words"]) for s in kept),
           "segments": [{k: s[k] for k in
                         ("tx", "wall0", "wall1", "text", "db_own", "db_other", "words")}
                        for s in kept]}
    fjson = save_json(outdir / f"{day['code']}_day1_transcript.json", doc)

    # ── по урокам, если карта дублей уже есть
    tm = load_json(day["project"] / "00_Setup/01_Ingest" / f"{day['code']}_day1_takemap.json")
    made = 0
    for t in (tm or {}).get("takes", []):
        les = (t.get("lesson") or {}).get("id")
        if not les:
            continue
        a0, a1 = t["wall_start"], t["wall_start"] + t["duration"]
        part = [l for l in lines if a0 - t0 <= l["t"] < a1 - t0]
        if not part:
            continue
        f = outdir / f"{day['code']}_{les}_dubl{t['take']}.txt"
        f.write_text(f"{les} · {(t.get('lesson') or {}).get('title', '')} · дубль {t['take']}\n"
                     f"{datetime.fromtimestamp(a0):%H:%M:%S}, {t['duration']/60:.1f} мин\n"
                     + "─" * 78 + "\n\n"
                     + "\n".join(f"{hhmmss(l['t'] - (a0 - t0))}  {l['who']}: {l['text']}"
                                 for l in part), encoding="utf-8")
        made += 1

    print(f"\n  реплик {len(lines)} · слов {doc['n_words']} · "
          f"проникание отсечено {dropped}")
    by = {}
    for l in lines:
        by[l["who"]] = by.get(l["who"], 0) + len(l["text"].split())
    for who, n in sorted(by.items(), key=lambda x: -x[1]):
        print(f"    {who:<22} {n:>6} слов")
    print(f"\n  → {ftxt}")
    print(f"  → {fjson}")
    if made:
        print(f"  → по урокам: {made} файлов рядом")
    return 0


if __name__ == "__main__":
    sys.exit(main())
