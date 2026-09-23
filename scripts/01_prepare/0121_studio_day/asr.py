#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S3 · расшифровка: петлички — результат, камеры — якоря синхрона.

Две модели по НАЗНАЧЕНИЮ, а не по вкусу: петличку слушает человек и по ней
собирается монтажный текст, поэтому large-v3; камерный звук нужен только как
n-граммы для графа часов, поэтому turbo.

  python3 asr.py                 # всё, чего ещё нет
  python3 asr.py --only mic
  python3 asr.py --force

Выход: {work}/words/{akey}.words.json — формат ровно тот, что ест wordsync:
`segments[].words[] = {w, s, e}`. Не `{word, start, end}`: `flatten_words()`
читает именно `w`/`s`, и на чужой схеме падает с KeyError.

⚠️ Правила отбраковки СКОПИРОВАНЫ из 0120_day_ingest/s3_transcribe.py (JUNK,
drop_repeats, пороги no_speech/logprob/compression, коридор темпа). Импорт
потянул бы common_day, который считает пути чужого проекта на самом импорте.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (die, dirs, env_for_mlx, load_day, load_json, log,  # noqa: E402
                    save_json)

JUNK = [
    "субтитры сделал", "субтитры делал", "dimatorzok", "субтитры и перевод",
    "продолжение следует", "спасибо за просмотр", "подписывайтесь",
    "редактор субтитров", "корректор", "добро пожаловать на наш канал",
    "thanks for watching", "subscribe", "субтитры создавал",
]
WPM_LO, WPM_HI = 20, 250


def is_junk(text):
    t = (text or "").lower()
    return any(j in t for j in JUNK)


def drop_repeats(segs, limit=5):
    """Одна и та же фраза подряд ≥limit раз — заклинивший декодер, не речь.

    ⚠️ Замер 23.09 на этой карте: у TX02 хвост «проведу проведу проведу…» ×20.
    Отличать от настоящего дубля: эксперт повторяет фразу с суфлёра почти
    дословно, но с ДРУГИМИ таймкодами и с паузой между — сюда это не попадает,
    потому что считаются только идущие ПОДРЯД одинаковые сегменты.
    """
    out, run, prev = [], 0, None
    for s in segs:
        key = re.sub(r"\W+", " ", (s.get("text") or "").lower()).strip()
        if key and key == prev:
            run += 1
            if run >= limit:
                continue
        else:
            run, prev = 0, key
        out.append(s)
    return out


def clean(res, dur):
    """Whisper → наш формат + отбраковка. Возвращает (obj, проблемы)."""
    segs_in = [s for s in (res.get("segments") or []) if not is_junk(s.get("text"))]
    segs_in = drop_repeats(segs_in)

    segments, nwords = [], 0
    for s in segs_in:
        if s.get("no_speech_prob", 0) > 0.6 and s.get("avg_logprob", 0) < -1.0:
            continue
        if s.get("compression_ratio", 0) > 2.4:
            continue
        words = []
        for w in (s.get("words") or []):
            txt = (w.get("word") or w.get("text") or "").strip()
            if txt:
                words.append({"w": txt,
                              "s": round(float(w.get("start", 0)), 3),
                              "e": round(float(w.get("end", 0)), 3)})
        if not words:
            continue
        nwords += len(words)
        segments.append({"s": round(float(s.get("start", 0)), 3),
                         "e": round(float(s.get("end", 0)), 3),
                         "text": (s.get("text") or "").strip(),
                         "words": words})

    issues = []
    if nwords and dur > 30:
        wpm = nwords / (dur / 60.0)
        if wpm < WPM_LO or wpm > WPM_HI:
            issues.append(f"темп {wpm:.0f} слов/мин вне {WPM_LO}–{WPM_HI}")
    return {"speech": bool(segments), "n_words": nwords,
            "duration": round(dur, 3), "segments": segments}, issues


def transcribe(wav, model, lang):
    import mlx_whisper
    return mlx_whisper.transcribe(
        str(wav), path_or_hf_repo=model, language=lang,
        word_timestamps=True,
        # ⚠️ Обязательно False: на начитке с суфлёра дубли почти дословно
        # повторяют друг друга, и с включённым conditioning whisper зацикливается
        # между ними, вместо того чтобы расшифровать каждый.
        condition_on_previous_text=False,
        no_speech_threshold=0.5, verbose=None)


def main():
    ap = argparse.ArgumentParser(description="расшифровка дня (0121_studio_day)")
    ap.add_argument("--day", default=None)
    ap.add_argument("--only", choices=("mic", "cam"), default=None)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    import os
    os.environ.update(env_for_mlx())

    day = load_day(a.day)
    D = dirs(day)
    au = load_json(D["work"] / "audio.json")
    if not au:
        die("нет audio.json — сначала python3 audio.py")

    items = [r for r in au["items"] if r.get("wav")]
    if a.only:
        items = [r for r in items if r["kind"] == a.only]
    # петлички первыми: это результат, камеры — только якоря
    items.sort(key=lambda r: (r["kind"] != "mic", r["akey"]))

    todo = [r for r in items
            if a.force or not (D["words"] / f"{r['akey']}.words.json").exists()]
    log(f"расшифровка: {len(todo)} из {len(items)} "
        f"(готово {len(items) - len(todo)})", day=day)

    mic_m, cam_m = day["asr"]["model_mic"], day["asr"]["model_cam"]
    lang = day["asr"]["lang"]
    done, problems = [], []
    for i, r in enumerate(todo, 1):
        model = mic_m if r["kind"] == "mic" else cam_m
        t0 = time.time()
        try:
            res = transcribe(Path(r["wav"]), model, lang)
        except Exception as e:                                # noqa: BLE001
            problems.append(f"{r['akey']}: {type(e).__name__}: {e}")
            log(f"  [{i}/{len(todo)}] {r['akey']:<32} ⚠ {type(e).__name__}", day=day)
            continue
        import wave
        with wave.open(r["wav"], "rb") as wf:
            dur = wf.getnframes() / float(wf.getframerate())
        obj, issues = clean(res, dur)
        obj.update({"schema": "ytai-words-v1", "akey": r["akey"], "kind": r["kind"],
                    "tx": r.get("tx"), "cam": r.get("cam"), "model": model,
                    "language": lang, "src": r.get("src"), "wav": r["wav"],
                    "issues": issues})
        save_json(D["words"] / f"{r['akey']}.words.json", obj)
        done.append(obj)
        if issues:
            problems += [f"{r['akey']}: {x}" for x in issues]
        el = time.time() - t0
        log(f"  [{i}/{len(todo)}] {r['akey']:<32} {obj['n_words']:>6} слов · "
            f"{el:5.0f} с · ×{dur/max(el, .01):.1f} реалтайма"
            f"{'  ⚠ ' + '; '.join(issues) if issues else ''}", day=day)

    # ── сводка
    allw = [load_json(p) for p in sorted(D["words"].glob("*.words.json"))]
    allw = [w for w in allw if w]
    mics = [w for w in allw if w.get("kind") == "mic"]
    cams = [w for w in allw if w.get("kind") == "cam"]
    print()
    print(f"  петличек   {len(mics):>3}   {sum(w['n_words'] for w in mics):>7} слов")
    print(f"  камерных   {len(cams):>3}   {sum(w['n_words'] for w in cams):>7} слов")
    silent = [w["akey"] for w in allw if not w.get("speech")]
    if silent:
        print(f"  без речи   {len(silent)}: {', '.join(silent[:6])}")
    for p in problems:
        print(f"  ⚠ {p}")
    exp = (day.get("expected") or {}).get("mic_chunks_with_speech")
    if exp is not None and a.only != "cam":
        got = sum(1 for w in mics if w.get("speech"))
        if got != exp:
            print(f"  ⚠ петличек с речью {got}, ждали {exp}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
