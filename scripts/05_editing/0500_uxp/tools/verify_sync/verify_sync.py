#!/usr/bin/env python3
"""verify_sync.py — вердикт синхрона В КАДРАХ для кнопки Verify Sync панели.

Тикет TICKET_uxp_audit, задача 7 = TICKET_ch4_sync_truth, 5.3: вердикт сразу
после Build, а не через модель. Гейт: худшая пара камера ↔ петличка ≤ полкадра.

Мерить звук внутри UXP нельзя (нужен ffmpeg), поэтому панель зовёт этот
скрипт через verify_sync.command. Замер НЕ переписан: функции берутся как есть
из арбитра scripts/999_extra/wordsync_multicam/timeline_sync_audit.py
(окно перекрытия переводится в координаты КАЖДОГО исходника через его
source_in, огибающие 200–3800 Гц, шаг 4 мс, корреляция). Здесь только то, что
нужно кнопке: fps секвенции вместо зашитых 25, одна секвенция, классы пар и
JSON-вердикт.

Классы пар:
  cam-lav  — камера/экран ↔ петличка (TXnn). ЭТО гейт.
  lav-lav  — две петлички: контроль прибора. Обязаны дать ≈ 0; нет — сломан
             ЗАМЕР, а не проект, и остальным числам верить нельзя.
  cam-cam  — справочно.
Пары с пиком корреляции < 0.25 не судятся (слабо).

  python3 verify_sync.py --dump dump.json --fps 25 --seq NAME --json-out verdict.json [--run-id ID]
  python3 verify_sync.py --request /tmp/ytai_verify_sync.json      # как зовёт панель

Заказ панели (--request): {run_id, prproj, seq, fps, dump_out, verdict_out}.
Скрипт сам снимает дамп сохранённого .prproj (prproj_dump.py) и ВСЕГДА пишет
verdict_out — даже при ошибке, иначе кнопка ждала бы вечно.
"""
import argparse
import json
import re
import subprocess
import sys
import traceback
from itertools import combinations
from pathlib import Path

ARBITER = Path.home() / "YTAI/scripts/999_extra/wordsync_multicam"
DUMPER = Path.home() / "YTAI/scripts/999_extra/prproj_dump/prproj_dump.py"
PEAK_MIN = 0.25
LAV = re.compile(r"(?:^|_)TX\d+", re.I)


def kind_of(x, y):
    lx, ly = bool(LAV.search(x["name"])), bool(LAV.search(y["name"]))
    if lx and ly:
        return "lav-lav"
    if lx or ly:
        return "cam-lav"
    return "cam-cam"


def measure_sequence(tsa, seq, fps, tol_frames, max_shift, log):
    items = tsa.audio_items(seq)
    tol = tol_frames / fps
    pairs = []
    for x, y in combinations(items, 2):
        if x["track"] == y["track"]:
            continue
        lo, hi = max(x["start_sec"], y["start_sec"]), min(x["end_sec"], y["end_sec"])
        if hi - lo < tsa.MIN_OVERLAP:
            continue
        dur = min(tsa.PROBE, hi - lo)
        mid = (lo + hi) / 2 - dur / 2
        sx = x["source_in_sec"] + (mid - x["start_sec"])
        sy = y["source_in_sec"] + (mid - y["start_sec"])
        log(f"  {x['track']} {x['name'][:34]} ↔ {y['track']} {y['name'][:34]} …")
        ex = tsa.envelope(tsa.pcm_window(x["path"], sx, dur))
        ey = tsa.envelope(tsa.pcm_window(y["path"], sy, dur))
        if ex is None or ey is None:
            continue
        dt, peak = tsa.delta(ex, ey, max_shift_s=max_shift)
        dt, peak = float(dt), float(peak)          # numpy scalars → plain floats for JSON
        judged = bool(peak >= PEAK_MIN)
        pairs.append({
            "a": {"track": x["track"], "name": x["name"]},
            "b": {"track": y["track"], "name": y["name"]},
            "kind": kind_of(x, y),
            "dt_ms": round(dt * 1000, 1),
            "dt_frames": round(dt * fps, 3),
            "peak": round(peak, 3),
            "overlap_sec": round(hi - lo, 1),
            "judged": judged,
            "ok": bool(abs(dt) <= tol) if judged else None,
        })
    judged = [p for p in pairs if p["judged"]]
    cam_lav = [p for p in judged if p["kind"] == "cam-lav"]
    controls = [p for p in judged if p["kind"] == "lav-lav"]
    worst = max(cam_lav, key=lambda p: abs(p["dt_frames"]), default=None)
    bad = [p for p in cam_lav if not p["ok"]]
    controls_ok = all(p["ok"] for p in controls)
    if not controls_ok:
        verdict = "INSTRUMENT"          # контроль не ноль — не верить остальному
    elif not cam_lav:
        verdict = "NO_DATA"
    elif bad:
        verdict = "DESYNC"
    else:
        verdict = "SYNC"
    return {
        "name": seq["name"],
        "pairs": pairs,
        "worst_cam_lav": worst,
        "worst_cam_lav_frames": abs(worst["dt_frames"]) if worst else None,
        "bad_cam_lav": len(bad),
        "controls": len(controls),
        "controls_ok": controls_ok,
        "verdict": verdict,
    }


def summary_line(res, tol_frames):
    s = res["sequences"][0] if res["sequences"] else None
    if not s:
        return "Verify Sync: no sequence in the dump"
    w = s["worst_cam_lav"]
    pair = f"{w['a']['track']}↔{w['b']['track']}" if w else ""
    if s["verdict"] == "SYNC":
        return f"SYNC ✓ worst camera↔lav {s['worst_cam_lav_frames']:.2f} fr {pair} (gate ≤ {tol_frames} fr)"
    if s["verdict"] == "DESYNC":
        return (f"DESYNC ✗ worst camera↔lav {s['worst_cam_lav_frames']:.2f} fr {pair} · "
                f"{s['bad_cam_lav']} pair(s) over {tol_frames} fr")
    if s["verdict"] == "INSTRUMENT":
        return "INSTRUMENT ✗ lav↔lav control is not ≈ 0 — the measurement is broken, do not trust the numbers"
    return "NO DATA — no camera↔lav pair with enough overlap and a clear correlation peak"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", help="заказ панели (JSON): снять дамп и вынести вердикт")
    ap.add_argument("--dump", help="JSON от prproj_dump --json")
    ap.add_argument("--fps", type=float, help="частота кадров секвенции")
    ap.add_argument("--seq", default=None, help="имя секвенции (точное); по умолчанию — все")
    ap.add_argument("--tol-frames", type=float, default=0.5)
    ap.add_argument("--max-shift", type=float, default=6.0)
    ap.add_argument("--json-out")
    ap.add_argument("--run-id", default="")
    a = ap.parse_args()

    if a.request:
        req = json.load(open(a.request))
        Path(a.request).unlink(missing_ok=True)          # one-shot order, like Fine Sync
        a.run_id, a.seq, a.fps = str(req.get("run_id", "")), req.get("seq"), float(req["fps"])
        a.json_out, a.dump = req["verdict_out"], req["dump_out"]
        print(f"Verify Sync · {a.seq} · {a.fps} fps\n  project: {req['prproj']}\n  dump → {a.dump}")
        Path(a.dump).parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([sys.executable, str(DUMPER), "--prproj", req["prproj"], "--seq", a.seq,
                            "--json", a.dump], capture_output=True, text=True)
        if r.returncode != 0 or not Path(a.dump).exists():
            err = {"tool": "verify_sync", "version": 1, "run_id": a.run_id, "verdict": "ERROR",
                   "error": "prproj_dump failed: " + (r.stderr or r.stdout)[-800:],
                   "summary": "Verify Sync failed: could not read the saved project (prproj_dump)",
                   "sequences": []}
            Path(a.json_out).write_text(json.dumps(err, ensure_ascii=False, indent=1))
            print(err["summary"] + "\n" + err["error"])
            return 2
    if not (a.dump and a.fps and a.json_out):
        ap.error("--dump, --fps and --json-out are required without --request")

    out = {"tool": "verify_sync", "version": 1, "run_id": a.run_id, "fps": a.fps,
           "tol_frames": a.tol_frames, "tol_ms": round(a.tol_frames / a.fps * 1000, 1),
           "sequences": [], "verdict": None, "summary": "", "error": None}
    try:
        sys.path.insert(0, str(ARBITER))
        import timeline_sync_audit as tsa  # noqa: E402 — the arbiter, unchanged
        d = json.load(open(a.dump))
        out["prproj"], out["saved_at"] = d.get("prproj"), d.get("saved_at")
        seqs = [s for s in d["sequences"] if a.seq is None or s["name"] == a.seq]
        if not seqs:
            raise RuntimeError(f"sequence {a.seq!r} is not in the dump")
        for seq in seqs:
            print(f"{seq['name']}")
            out["sequences"].append(measure_sequence(tsa, seq, a.fps, a.tol_frames, a.max_shift,
                                                     lambda m: print(m, flush=True)))
        order = ["INSTRUMENT", "DESYNC", "NO_DATA", "SYNC"]
        out["verdict"] = min((s["verdict"] for s in out["sequences"]), key=order.index)
        out["summary"] = summary_line(out, a.tol_frames)
    except Exception as e:                               # the panel must get a verdict file either way
        out["verdict"], out["error"] = "ERROR", f"{type(e).__name__}: {e}"
        out["summary"] = "Verify Sync failed: " + out["error"]
        out["traceback"] = traceback.format_exc()
    # default= keeps the write alive whatever type sneaks in: the panel polls for this file
    Path(a.json_out).write_text(json.dumps(out, ensure_ascii=False, indent=1,
                                           default=lambda o: o.item() if hasattr(o, 'item') else str(o)))
    print("\n" + out["summary"])
    return 0 if out["verdict"] != "ERROR" else 2


if __name__ == "__main__":
    sys.exit(main())
