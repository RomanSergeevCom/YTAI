#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка прокси-комплекта проекта по контракту (KB 3.4 /kb/proxy/).

Повторяет дерево сцен `01_Source` в `01_Source_Proxy`: имена файлов и
относительные пути 1:1, отличается только имя корневой папки. Тогда подмена в
Premiere — это смена одного корня, и таймлайн не двигается ни на кадр.

Что делает с каждым клипом, решает contract.py:
  encode        тяжёлый материал с камеры → HEVC, битность и таймкод с источника
  copy          уже лёгкое (айфон) или есть недекодируемая дорожка → байт-в-байт
  skip-symlink  клип-спаннер, вторая копия делается на Drive server-side

Каждый готовый файл проходит гейт из восьми пунктов. Не сошлось → один ретрай;
не сошлось снова → клип НЕ уезжает в комплект и попадает в отчёт.

  python3 proxy.py --src <01_Source> --dst <01_Source_Proxy> [--jobs 2]
  python3 proxy.py --src ... --dst ... --dry-run          что и почему будет сделано
  python3 proxy.py --src ... --dst ... --verify-only      прогнать гейт по готовому
  python3 proxy.py --src ... --dst ... --only "RYA-FX3-1107.MP4" --gate-report
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from fnmatch import fnmatch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contract as K

SKIP_DIRS = {"00_LUT", "Transcription", "_XML", "_Proxy"}


def now():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def hhmm(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def gb(n):
    return f"{n / 1e9:.2f} ГБ"


# ── сбор списка работ ────────────────────────────────────────────────────────
def collect(src_root, dst_root, only=None, exclude=()):
    """Медиа может лежать и прямо в сцене, и в подпапках камер {сцена}/CAM1-FX3/.
    Относительный путь сохраняется 1:1 — обходим рекурсивно."""
    jobs = []
    for root, dirs, files in os.walk(src_root):
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and d not in SKIP_DIRS and d not in exclude]
        for f in sorted(files):
            if f.startswith("._") or not f.lower().endswith(K.VIDEO_EXT):
                continue
            if only and not (fnmatch(f, only) or fnmatch(os.path.join(root, f), only)):
                continue
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, src_root)
            jobs.append((fp, os.path.join(dst_root, rel), rel))
    return sorted(jobs, key=lambda j: j[2])


# ── один клип ────────────────────────────────────────────────────────────────
def do_encode(spec, dst, dec, force_bt709=False, timeout=None):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + K.TMP_SUFFIX
    cmd = K.build_cmd(spec, dst, dec, force_bt709=force_bt709)
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout or max(900, spec.duration * 3))
    except subprocess.TimeoutExpired:
        if os.path.exists(tmp):
            os.remove(tmp)
        return False, "кодирование не уложилось в отведённое время", time.time() - t0
    if r.returncode != 0 or not os.path.exists(tmp):
        if os.path.exists(tmp):
            os.remove(tmp)
        return False, (r.stderr or "").strip()[-400:], time.time() - t0
    os.replace(tmp, dst)
    return True, "", time.time() - t0


def do_copy(spec, dst):
    """Копия обязана быть побайтово равной — copy2 несёт и время."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".part"
    t0 = time.time()
    shutil.copy2(spec.path, tmp)
    os.replace(tmp, dst)
    return True, "", time.time() - t0


def process(src, dst, rel, a, log):
    """Полный цикл по одному клипу: снять → решить → сделать → проверить."""
    spec = K.probe(src)
    dec = K.decide(spec, bitrate=K.bitrate_for(spec, override=a.bitrate),
                   chroma=a.chroma, force=a.force)

    if dec.action == "skip-symlink":
        log(f"  {rel}: пропуск — {dec.reason}")
        return K.skipped_row(spec, dec, rel)

    # уже готовое и проходящее гейт не переделываем
    if os.path.exists(dst):
        try:
            g = K.gate(spec, K.probe(dst), rel, rel, dec)
            if g.ok:
                row = K.report_row(spec, K.probe(dst), dec, g, rel, attempts=0, at=now())
                row["status"] = "skip"
                log(f"  {rel}: уже собран и проходит контракт")
                return row
        except Exception:
            pass
        if a.verify_only:
            dstspec = K.probe(dst)
            g = K.gate(spec, dstspec, rel, rel, dec)
            return K.report_row(spec, dstspec, dec, g, rel, attempts=0, at=now())
        os.remove(dst)

    if a.verify_only:
        row = K.skipped_row(spec, dec, rel, note="прокси нет")
        row["status"] = "FAIL"
        row["err"] = "прокси нет на диске"
        return row

    attempts, err, took = 0, "", 0.0
    for attempt in range(1, a.retries + 2):
        attempts = attempt
        if dec.action == "copy":
            ok, err, took = do_copy(spec, dst)
        else:
            ok, err, took = do_encode(spec, dst, dec, force_bt709=a.force_bt709)
        if not ok:
            log(f"  {rel}: попытка {attempt} — не собралось: {err[:160]}")
            continue
        dstspec = K.probe(dst)
        g = K.gate(spec, dstspec, rel, rel, dec)
        if g.ok:
            log(f"  {rel}: {dec.action}, {hhmm(took)}, ×{spec.size / max(dstspec.size,1):.1f}")
            return K.report_row(spec, dstspec, dec, g, rel, attempts, took, now())
        log(f"  {rel}: попытка {attempt} — {g.summary()}")
        if attempt <= a.retries:
            os.remove(dst)
    # не сошлось — клип в комплект НЕ идёт
    dstspec = K.probe(dst) if os.path.exists(dst) else None
    g = (K.gate(spec, dstspec, rel, rel, dec) if dstspec
         else K.GateResult(False, {}, ("не собрался",)))
    row = K.report_row(spec, dstspec, dec, g, rel, attempts, took, now())
    row["status"] = "FAIL"
    row["err"] = err or g.summary()
    if dstspec and os.path.exists(dst):
        os.remove(dst)
        row["dst"] = ""
    return row


# ── печать таблицы контракта ─────────────────────────────────────────────────
RU = {"resolution": "разрешение", "fps": "частота", "frames": "кадры",
      "bit_depth": "битность", "path": "имя и путь", "audio": "звук",
      "timecode": "таймкод", "color": "теги цвета", "size_ratio": "сжатие"}


def print_gate(row):
    print(f"\n── {row['rel']}   [{row['action']}] {row['reason']}")
    for key, v in (row.get("contract") or {}).items():
        mark = "✓" if v["ok"] else "✗"
        print(f"   {mark} {RU.get(key, key):<12} {str(v['src'])[:46]:<46} → {str(v['dst'])[:46]}")
        if not v["ok"] and v.get("note"):
            print(f"       {v['note']}")


def main():
    ap = argparse.ArgumentParser(description="прокси по контракту (KB 3.4)")
    ap.add_argument("--src", required=True, help="корень оригиналов (01_Source)")
    ap.add_argument("--dst", required=True, help="корень прокси (01_Source_Proxy)")
    ap.add_argument("--jobs", type=int, default=2,
                    help="сколько клипов кодировать разом (пик места = jobs × самый большой)")
    ap.add_argument("--bitrate", default=K.DEFAULT_BITRATE,
                    help="8M по умолчанию; auto — по частоте кадров")
    ap.add_argument("--chroma", choices=("420", "422"), default="420",
                    help="422 замерян и выгоды не даёт — см. шапку contract.py")
    ap.add_argument("--only", default=None, help="маска одного клипа — для проверки")
    ap.add_argument("--exclude", default="", help="папки сцен через запятую")
    ap.add_argument("--force", choices=("encode", "copy"), default=None)
    ap.add_argument("--force-bt709", action="store_true",
                    help="подставить bt709, если источник без тегов вовсе; на логе это враньё")
    ap.add_argument("--retries", type=int, default=1)
    ap.add_argument("--report", default=None, help="куда положить proxy_report.json")
    ap.add_argument("--gate-report", action="store_true", help="напечатать восемь пунктов по каждому")
    ap.add_argument("--verify-only", action="store_true", help="ничего не делать, только проверить")
    ap.add_argument("--dry-run", action="store_true", help="показать план и выйти")
    a = ap.parse_args()

    exclude = {x.strip() for x in a.exclude.split(",") if x.strip()}
    jobs = collect(a.src, a.dst, only=a.only, exclude=exclude)
    if not jobs:
        print("клипов не найдено", file=sys.stderr)
        return 1

    if a.dry_run:
        plan, need = {}, 0
        for src, dst, rel in jobs:
            spec = K.probe_fast(src)
            dec = K.decide(spec, bitrate=K.bitrate_for(spec, override=a.bitrate),
                           chroma=a.chroma, force=a.force)
            plan.setdefault(dec.action, []).append((rel, dec.reason, spec.size))
            if dec.action == "encode":
                need += spec.size // 18
            elif dec.action == "copy":
                need += spec.size
        print(f"клипов: {len(jobs)}")
        for action, items in plan.items():
            src_bytes = sum(i[2] for i in items)
            print(f"\n{action}: {len(items)} шт, исходников {gb(src_bytes)}")
            print(f"   причина: {items[0][1]}")
            for rel, _r, _s in items[:5]:
                print(f"   · {rel}")
            if len(items) > 5:
                print(f"   … и ещё {len(items) - 5}")
        print(f"\nожидаемый вес комплекта: ~{gb(need)}")
        print(f"свободно на целевом томе: {K.free_gb(a.dst):.1f} ГБ")
        return 0

    print(f"клипов: {len(jobs)} · jobs={a.jobs} · битрейт {a.bitrate} · chroma {a.chroma}"
          + (" · ТОЛЬКО ПРОВЕРКА" if a.verify_only else ""), flush=True)
    lock = threading.Lock()
    done = {"n": 0}
    t_start = time.time()

    def log(msg):
        print(msg, flush=True)

    def work(job):
        src, dst, rel = job
        try:
            row = process(src, dst, rel, a, log)
        except Exception as exc:                      # клип не должен ронять прогон
            row = {"src": src, "dst": "", "rel": rel, "status": "FAIL",
                   "action": "?", "reason": "", "err": f"{type(exc).__name__}: {exc}",
                   "frames_src": 0, "frames_dst": 0, "dur_src": 0, "dur_dst": 0,
                   "size": 0, "size_src": 0, "ratio": 0, "contract": {},
                   "attempts": 0, "encode_sec": 0, "speed_x": 0, "at": now()}
            log(f"  {rel}: СБОЙ — {row['err']}")
        with lock:
            done["n"] += 1
            n = done["n"]
        print(f"[{n}/{len(jobs)}] {row['status']:8} {rel}", flush=True)
        return row

    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        rows = list(ex.map(work, jobs))

    meta = {"started": datetime.fromtimestamp(t_start).strftime("%Y-%m-%dT%H:%M:%S"),
            "finished": now(), "bitrate": a.bitrate, "jobs": a.jobs, "chroma": a.chroma,
            "src_root": os.path.abspath(a.src), "dst_root": os.path.abspath(a.dst),
            "verify_only": a.verify_only}
    summary = K.summarize(rows, meta)

    if a.gate_report:
        for row in rows:
            if row.get("contract"):
                print_gate(row)

    fails = [r for r in rows if r["status"] == "FAIL"]
    print(f"\nГОТОВО за {hhmm(time.time() - t_start)} · {summary['n']} клипов · "
          f"{gb(summary['total_bytes'])} · " +
          " · ".join(f"{k}: {v}" for k, v in sorted(summary["counts"].items())))
    if fails:
        print(f"\nВ КОМПЛЕКТ НЕ ВОШЛИ ({len(fails)}):")
        for r in fails:
            print(f"   ✗ {r['rel']} — {r['err'][:180]}")

    if a.report:
        os.makedirs(os.path.dirname(os.path.abspath(a.report)), exist_ok=True)
        with open(a.report, "w") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=1)
        print(f"\nотчёт: {a.report}")

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
