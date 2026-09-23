#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка прокси по всем дискам: где они есть, где их нет и где они негодные.

Обходит смонтированные тома, находит проекты по канону имени
(`YT{XX}{NN}_{описание}`), и по каждому отвечает на три вопроса:

  1. сколько исходного видео в `01_Source`;
  2. есть ли комплект `01_Source_Proxy` и полон ли он;
  3. проходят ли имеющиеся прокси контракт — и какой именно пункт не проходят.

Ничего не пишет и не трогает: только читает файлы и зовёт ffprobe.
Результат — таблица в консоль и JSON для ночного прогона.

  python3 audit.py                       все тома, быстрая проверка
  python3 audit.py --full                считать кадры (долго, но честно)
  python3 audit.py --json out.json       машиночитаемо
  python3 audit.py --channel YTCG        только один канал
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contract as K

PROJECT_RE = re.compile(r"^(YT[A-Z]{2,4}\d+)_")
SOURCE_DIR = "01_Source"
PROXY_DIR = "01_Source_Proxy"
SKIP_DIRS = {"00_LUT", "Transcription", "_XML", "_Proxy", "_dupes", "_archive"}
#: тома, куда лезть без толку
SKIP_VOL = {"Macintosh HD", "com.apple.TimeMachine.localsnapshots"}


def volumes():
    out = []
    for name in sorted(os.listdir("/Volumes")):
        p = os.path.join("/Volumes", name)
        if name in SKIP_VOL or not os.path.isdir(p):
            continue
        try:
            if os.path.islink(p):
                continue
            out.append(p)
        except OSError:
            continue
    return out


def find_projects(root, depth=3):
    """Проекты по канону имени. Ищем неглубоко: проект — это папка верхнего
    или второго уровня, а не что-то зарытое в сценах."""
    found = []
    root = os.path.abspath(root)
    base_depth = root.rstrip("/").count("/")
    for cur, dirs, _files in os.walk(root):
        if cur.rstrip("/").count("/") - base_depth >= depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for d in list(dirs):
            m = PROJECT_RE.match(d)
            if not m:
                continue
            p = os.path.join(cur, d)
            if os.path.isdir(os.path.join(p, SOURCE_DIR)):
                found.append((m.group(1), p))
                dirs.remove(d)          # внутрь проекта не спускаемся
    return found


def media_of(root):
    """Видео проекта: относительный путь → абсолютный."""
    out = {}
    if not os.path.isdir(root):
        return out
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
        for f in files:
            if f.startswith("._") or not f.lower().endswith(K.VIDEO_EXT):
                continue
            fp = os.path.join(cur, f)
            if os.path.islink(fp):
                continue
            out[os.path.relpath(fp, root)] = fp
    return out


def check_pair(src_path, dst_path, full):
    """Один клип: проходит ли контракт. Возвращает (статус, что не сошлось)."""
    try:
        spec = K.probe(src_path, count_frames=full)
    except Exception as exc:
        return "источник не читается", [str(exc)[:80]]
    dec = K.decide(spec, bitrate=K.bitrate_for(spec))
    if dec.action == "skip-symlink":
        return "спаннер", []
    if not dst_path or not os.path.exists(dst_path):
        return "прокси нет", []
    try:
        dstspec = K.probe(dst_path, count_frames=full)
    except Exception as exc:
        return "прокси не читается", [str(exc)[:80]]
    rel = os.path.basename(src_path)
    g = K.gate(spec, dstspec, rel, os.path.basename(dst_path), dec)
    bad = [k for k in g.failed if not (k == "frames" and not full)]
    return ("годен" if not bad else "НЕ ПО КОНТРАКТУ"), bad


def audit_project(code, path, full, sample, log):
    src_root = os.path.join(path, SOURCE_DIR)
    dst_root = os.path.join(path, PROXY_DIR)
    src = media_of(src_root)
    dst = media_of(dst_root)
    res = {"code": code, "path": path, "clips": len(src),
           "proxies": len(dst), "has_kit": os.path.isdir(dst_root),
           "src_bytes": 0, "dst_bytes": 0,
           "verdict": {}, "bad_points": {}, "checked": 0}
    if not src:
        res["verdict"]["нет исходников"] = 0
        return res

    rels = sorted(src)
    res["src_bytes"] = sum(os.path.getsize(src[r]) for r in rels)
    res["dst_bytes"] = sum(os.path.getsize(p) for p in dst.values())
    take = rels if (sample <= 0 or sample >= len(rels)) else \
        [rels[i] for i in range(0, len(rels), max(1, len(rels) // sample))][:sample]

    def one(rel):
        return check_pair(src[rel], dst.get(rel), full)

    with ThreadPoolExecutor(max_workers=4) as ex:
        for status, bad in ex.map(one, take):
            res["verdict"][status] = res["verdict"].get(status, 0) + 1
            for b in bad:
                res["bad_points"][b] = res["bad_points"].get(b, 0) + 1
    res["checked"] = len(take)
    return res


def main():
    ap = argparse.ArgumentParser(description="проверка прокси по всем дискам")
    ap.add_argument("--volumes", default="", help="тома через запятую; иначе все")
    ap.add_argument("--channel", default="", help="только этот канал, например YTCG")
    ap.add_argument("--full", action="store_true",
                    help="считать кадры (точно, но каждый 4K-клип это секунды)")
    ap.add_argument("--sample", type=int, default=6,
                    help="сколько клипов проверять на проект; 0 — все")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    vols = [v.strip() for v in a.volumes.split(",") if v.strip()] or volumes()
    print(f"тома: {', '.join(os.path.basename(v) for v in vols)}", flush=True)

    projects = []
    for v in vols:
        for code, p in find_projects(v):
            if a.channel and not code.startswith(a.channel):
                continue
            projects.append((code, p))
    projects.sort()
    print(f"проектов по канону имени: {len(projects)}"
          + (f" (выборка {a.sample} клипов на проект)" if a.sample else " (все клипы)"),
          flush=True)
    print()

    t0 = time.time()
    rows = []
    hdr = f"{'проект':<34} {'клипов':>7} {'прокси':>7} {'исходники':>11} {'комплект':>10}  вердикт"
    print(hdr)
    print("─" * len(hdr))
    for code, p in projects:
        r = audit_project(code, p, a.full, a.sample, print)
        rows.append(r)
        v = r["verdict"]
        worst = ("НЕ ПО КОНТРАКТУ" if v.get("НЕ ПО КОНТРАКТУ") else
                 "прокси нет" if v.get("прокси нет") else
                 "годен" if v.get("годен") else
                 next(iter(v), "—"))
        pts = ", ".join(f"{k}×{n}" for k, n in sorted(r["bad_points"].items(),
                                                      key=lambda x: -x[1])[:3])
        name = os.path.basename(p)[:33]
        print(f"{name:<34} {r['clips']:>7} {r['proxies']:>7} "
              f"{r['src_bytes']/1e9:>9.0f} ГБ {r['dst_bytes']/1e9:>8.1f} ГБ  "
              f"{worst}" + (f" — {pts}" if pts else ""), flush=True)

    need = [r for r in rows if r["verdict"].get("НЕ ПО КОНТРАКТУ")
            or r["verdict"].get("прокси нет")]
    src_need = sum(r["src_bytes"] for r in need)
    print()
    print(f"проверено за {time.time()-t0:.0f} с · требуют работы: {len(need)} проектов, "
          f"{src_need/1e9:.0f} ГБ исходников → ~{src_need/1e9/18.9:.0f} ГБ прокси")
    for r in need:
        print(f"   · {os.path.basename(r['path']):<32} "
              + ", ".join(f"{k}: {n}" for k, n in sorted(r['verdict'].items())))

    if a.json:
        with open(a.json, "w") as fh:
            json.dump({"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "full": a.full, "sample": a.sample, "projects": rows},
                      fh, ensure_ascii=False, indent=1)
        print(f"\nJSON: {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
