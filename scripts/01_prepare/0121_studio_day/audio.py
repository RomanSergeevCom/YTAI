#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S2 · рабочий звук 16 кГц моно из ОРИГИНАЛОВ + замер громкости.

Рабочая копия под whisper — не замена дорожки: исходный звук остаётся в
исходнике и нигде не подменяется. Каждая запись помнит, из чего получена.

Почему из оригиналов, а не из прокси или `.LRF`: `-vn` демуксит только
аудиопакеты, поэтому размер файла почти ничего не решает, а дорожка LRF у DJI
короче оригинала на десятки миллисекунд. На пословных таймкодах это риск
на ровном месте.

  python3 audio.py                  # всё, чего ещё нет
  python3 audio.py --only mic       # только петлички
  python3 audio.py --force          # переснять уже готовое

Выход: {work}/wav16/*.wav + {work}/audio.json
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (afilter, die, dirs, gain_for, load_day, load_json, log,  # noqa: E402
                    measure_rms_db, run, save_json)

DEAD_DB = -80.0          # цифровая тишина (замерено: ровно -240 dBFS)
JOBS = 4


def akey(rec):
    """Ключ рабочей копии — имя без расширения. Имена на карте уникальны глобально."""
    return Path(rec["file"]).stem


def live_channels(path, nch):
    """Какие каналы вообще несут сигнал.

    ⚠️ Замер 23.09 на ZV-E1: на дублях 1958-1960 ЛЕВЫЙ канал — цифровая тишина
    (-240 дБ), живёт только правый. Сведение `-ac 1` дало бы -6 дБ ни за что,
    а на трёх дублях подряд это уже заметная потеря якорей синхрона.
    """
    live = []
    for c in range(nch):
        r = run(["ffmpeg", "-nostdin", "-hide_banner", "-t", "60",
                 "-i", str(path), "-map", "0:a:0", "-af",
                 f"pan=mono|c0=c{c},volumedetect", "-f", "null", "-"], timeout=600)
        import re
        m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
        db = float(m.group(1)) if m else None
        if db is not None and db > DEAD_DB:
            live.append(c)
    return live


def extract(src, dst, pan, gain):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part.wav")
    r = run(["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(src),
             "-map", "0:a:0", "-af", f"{pan},{afilter(gain)}",
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
             "-f", "wav", str(tmp)], timeout=3600)
    if r.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return None, (r.stderr or "").strip()[:200]
    tmp.replace(dst)
    return dst, None


def do_mic(rec, day, D, force, prev=None):
    dst = D["wav16"] / (akey(rec) + ".wav")
    if dst.exists() and not force:
        # ⚠️ Пропуск обязан вернуть ПОЛНУЮ запись, а не заглушку: усиление и
        # дорожка нужны транскрипту, чтобы вычесть нормировку и сравнить
        # уровни. Заглушка-«skipped» молча лишала его этих полей.
        if prev:
            return {**prev, "skipped": True}
        return {"akey": akey(rec), "kind": "mic", "tx": rec.get("tx"),
                "src": rec["path"], "src_rms_db": rec.get("rms_db"),
                "gain_db": gain_for(rec.get("rms_db"), day),
                "wav": str(dst), "skipped": True}
    gain = gain_for(rec.get("rms_db"), day)
    wav, err = extract(Path(rec["path"]), dst, "pan=mono|c0=c0", gain)
    out = {"akey": akey(rec), "kind": "mic", "tx": rec.get("tx"),
           "src": rec["path"], "src_rms_db": rec.get("rms_db"),
           "src_peak_db": rec.get("peak_db"), "gain_db": gain,
           "wav": str(wav) if wav else None, "err": err}
    if wav:
        out["rms_db"], out["peak_db"] = measure_rms_db(wav)
    return out


def do_cam(rec, day, D, force, prev=None):
    dst = D["wav16"] / (akey(rec) + ".wav")
    if dst.exists() and not force:
        if prev:
            return {**prev, "skipped": True}
        return {"akey": akey(rec), "kind": "cam", "cam": rec.get("cam"),
                "src": rec["path"], "wav": str(dst), "skipped": True}
    src = Path(rec["path"])
    nch = (rec.get("audio") or [{}])[0].get("ch") or 1
    live = live_channels(src, nch) if nch > 1 else [0]
    if not live:
        return {"akey": akey(rec), "kind": "cam", "cam": rec.get("cam"),
                "src": rec["path"], "wav": None, "speech": False,
                "why": "все каналы — цифровая тишина"}
    pan = ("pan=mono|c0=c0" if len(live) == 1 and live[0] == 0 else
           f"pan=mono|c0=c{live[0]}" if len(live) == 1 else
           "pan=mono|c0=" + "+".join(f"{1/len(live):.4f}*c{c}" for c in live))
    mean, _ = measure_rms_db(src)
    gain = gain_for(mean, day)
    wav, err = extract(src, dst, pan, gain)
    out = {"akey": akey(rec), "kind": "cam", "cam": rec.get("cam"),
           "src": rec["path"], "live_channels": live, "pan": pan,
           "src_rms_db": mean, "gain_db": gain,
           "wav": str(wav) if wav else None, "err": err}
    if wav:
        out["rms_db"], out["peak_db"] = measure_rms_db(wav)
    return out


def main():
    ap = argparse.ArgumentParser(description="рабочий звук 16 кГц (0121_studio_day)")
    ap.add_argument("--day", default=None)
    ap.add_argument("--only", choices=("mic", "cam"), default=None)
    ap.add_argument("--force", action="store_true", help="переснять уже готовое")
    a = ap.parse_args()

    day = load_day(a.day)
    D = dirs(day)
    idx = load_json(D["work"] / "index.json")
    if not idx:
        die("нет index.json — сначала python3 index.py")

    jobs = []
    if a.only != "cam":
        jobs += [("mic", m) for m in idx["mics"] if not m["dead"]]
    if a.only != "mic":
        jobs += [("cam", c) for c in idx["clips"] if c.get("ok")]
    log(f"рабочий звук: {len(jobs)} файлов, потоков {JOBS}", day=day)

    # ⚠️ СЛИЯНИЕ, а не перезапись. `--only cam` писал файл целиком и затирал
    # записи петличек: транскрипт потом не находил ни одной дорожки и честно
    # отказывался работать. Два писателя одного JSON — уже оплаченная ошибка.
    было = {r["akey"]: r for r in
            (load_json(D["work"] / "audio.json") or {}).get("items", [])}
    res = []
    with ThreadPoolExecutor(max_workers=JOBS) as ex:
        futs = [ex.submit(do_mic if k == "mic" else do_cam, r, day, D, a.force,
                          было.get(akey(r)))
                for k, r in jobs]
        for i, f in enumerate(futs, 1):
            r = f.result()
            res.append(r)
            if not r.get("skipped"):
                log(f"  [{i}/{len(futs)}] {r['akey']:<32} "
                    f"{'' if r.get('wav') else '⚠ '}{r.get('err') or r.get('why') or ''}"
                    f"{('gain %+.1f дБ → %.1f' % (r.get('gain_db') or 0, r.get('rms_db') or 0)) if r.get('wav') else ''}",
                    day=day)

    было.update({r["akey"]: r for r in res})
    save_json(D["work"] / "audio.json", {"schema": "ytai-studio-day-audio-v1",
                                         "code": day["code"],
                                         "items": sorted(было.values(),
                                                         key=lambda r: (r["kind"], r["akey"]))})

    # ── гейты, оба дешёвые и оба ловили настоящие потери
    mics = [r for r in res if r["kind"] == "mic" and r.get("wav")]
    bad = []
    clipped = [r for r in mics if (r.get("peak_db") or -99) > -0.1]
    if clipped:
        bad.append(f"клиппинг в рабочей копии петлички: {', '.join(r['akey'] for r in clipped)}")
    quiet = [r for r in mics
             if r.get("src_rms_db") is not None and r.get("rms_db") is not None
             and r["src_rms_db"] > -40 and r["rms_db"] < r["src_rms_db"] - 6]
    if quiet:
        bad.append(f"копия ТИШЕ источника: {', '.join(r['akey'] for r in quiet)}")
    nowav = [r for r in res if not r.get("wav") and not r.get("skipped")]

    print()
    print(f"  петличек   {len(mics):>3}")
    print(f"  камерных   {len([r for r in res if r['kind'] == 'cam' and r.get('wav')]):>3}")
    if nowav:
        print(f"  ⚠ без звука {len(nowav)}: {', '.join(r['akey'] for r in nowav)}")
    if mics:
        lo = min(r.get("rms_db") or 0 for r in mics)
        hi = max(r.get("rms_db") or 0 for r in mics)
        print(f"  уровень петличек после нормировки: {lo:.1f} … {hi:.1f} дБ "
              f"(цель {day['asr']['target_rms_db']:.0f})")
    for b in bad:
        print(f"  ⚠ {b}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
