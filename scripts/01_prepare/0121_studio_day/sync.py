#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S4 · синхрон дня: дерево под wordsync, прогон, гейт из семи пунктов.

Зачем ранбук вообще нужен, если пара камер уже сошлась по часам. Сошлась —
и это ПРОВЕРКА, а не решение: `creation_time` FX3 опережает ZV-E1 ровно на
4:47 на каждом из 21 дубля, и корреляция огибающих речи это подтверждает.
Но к петличкам это не относится никак: их часы врут независимо, и по
огибающей они НЕ привязываются — замер 23.09 дал разброс 764 и 804 секунды
по четырём окнам при отрыве пика от фона всего ×1,4-1,9. Речь самоподобна
на получасовом монологе. Разделительная способность есть только у пословных
n-грамм, ради них ранбук и существует.

  python3 sync.py --stage        # только разложить дерево
  python3 sync.py                # дерево + wordsync + гейт

Выход: {work}/days/full/ (симлинки) и {work}/days/full/Transcription/_wordsync/
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import die, dirs, env_for_mlx, load_day, load_json, log  # noqa: E402

WS = Path.home() / "YTAI/scripts/999_extra/wordsync_multicam/wordsync.py"


def link(src: Path, dst: Path):
    """Абсолютный симлинк. Относительный вёл бы через границу APFS→exFAT."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    os.symlink(src, dst)


def stage(day, D):
    """Дерево ровно в той раскладке, которую ждёт wordsync:
    {day}/CAM*/**/*.MP4 · {day}/Sound/*.wav · {day}/Transcription/{stem}.words.json
    """
    root = D["work"] / "days" / "full"
    idx = load_json(D["work"] / "index.json")
    if not idx:
        die("нет index.json — сначала python3 index.py")

    n_cam = n_snd = n_wrd = 0
    for c in idx["clips"]:
        if not c.get("ok"):
            continue
        link(Path(c["path"]), root / c["cam"] / c["file"])
        n_cam += 1
    for m in idx["mics"]:
        if m["dead"]:
            continue                       # мёртвый огрызок в синхрон не идёт
        link(Path(m["path"]), root / "Sound" / m["file"])
        n_snd += 1
    for w in sorted(D["words"].glob("*.words.json")):
        link(w, root / "Transcription" / w.name)
        n_wrd += 1

    # ⚠️ wordsync.discover() глобит Sound ПЛОСКО, а find_words() падает на
    # неоднозначном стволе. Наши стволы сегодня уникальны, но папки рекордера
    # 182243 и 182252 созданы с разницей в девять секунд — одна перезагрузка
    # рекордера, и они столкнутся. Проверяем каждый раз.
    stems = [p.name.rsplit(".words.json")[0]
             for p in (root / "Transcription").glob("*.words.json")]
    dup = sorted({s for s in stems if stems.count(s) > 1})
    if dup:
        die(f"одинаковые стволы расшифровок — wordsync откажется: {dup}")

    log(f"дерево: камер {n_cam} · петличек {n_snd} · расшифровок {n_wrd} → {root}", day=day)
    return root


def gate(day, res, D):
    """Семь пунктов приёмки. Каждый — из оплаченной ошибки, а не из осторожности."""
    bad, note = [], []
    idx = load_json(D["work"] / "index.json")
    by_file = {c["file"]: c for c in idx["clips"]}
    junk = {Path(j).name for j in (day.get("junk_clips") or [])}

    # 2. независимая проверка: разность Δ камер обязана дать замеренный сдвиг
    deltas = {k: v for k, v in (res.get("cam_delta") or res.get("deltas") or {}).items()}
    want = day.get("cam_pair_offset_sec")
    if want is not None and {"CAM-A_FX3", "CAM-B_ZVE1"} <= set(deltas):
        got = deltas["CAM-A_FX3"] - deltas["CAM-B_ZVE1"]
        note.append(f"Δ(FX3) − Δ(ZV-E1) = {got:+.2f} с, замерено {want:+.1f} с")
        if abs(got - want) > 1.0:
            bad.append(f"разность Δ камер {got:+.2f} с против замеренных {want:+.1f} с "
                       f"— решение не воспроизводит то, что видно в сайдкарах")
    else:
        note.append("⚠ разность Δ камер не проверена: в результате нет обеих камер")

    # 3. стыки автосплита воспроизводят дельту по имени
    T = res.get("chunk_T") or res.get("T") or {}
    for a, b in day.get("split_joins") or []:
        ka = next((k for k in T if k.startswith(a)), None)
        kb = next((k for k in T if k.startswith(b)), None)
        if not (ka and kb):
            bad.append(f"стык {a} → {b}: куска нет в решении")
            continue
        d = T[kb] - T[ka]
        if abs(d - 1800.2) > 0.6:
            bad.append(f"стык {a} → {b}: {d:.1f} с вместо 1800,2 "
                       f"({'синхрон развалился' if abs(d-1800.2) > 10 else 'вне допуска ±0,6 с'}")

    # 5-6. каждый урочный клип поставлен ПО РЕЧИ
    placed = res.get("clips") or {}
    byclock = [k for k, v in placed.items()
               if v.get("source") != "speech"
               and Path(k).name not in junk
               and by_file.get(Path(k).name, {}).get("kind") == "lesson"]
    if byclock:
        bad.append(f"по часам, а не по речи ({len(byclock)}): {byclock[:6]} — "
                   f"на студийном дне с двумя петличками это значит, что "
                   f"транскрипт пуст или не совпал")

    return bad, note


def coverage(day, res, D):
    """7. Покрытие петличками по каждому дублю — из решённых T_k, НЕ из имён файлов.

    ⚠️ Весь смысл в том, что имена могут врать: по ним TX01 не покрывает первые
    45 минут съёмки, но часы рекордера уже уличены в расхождении с камерой.
    Дыру объявляет только решение.
    """
    idx = load_json(D["work"] / "index.json")
    T = res.get("chunk_T") or res.get("T") or {}
    durs = {m["file"]: m["dur"] for m in idx["mics"]}
    iv = []
    for k, t0 in T.items():
        f = next((n for n in durs if n.startswith(Path(k).stem) or Path(k).name == n), None)
        if f:
            iv.append((t0, t0 + durs[f], Path(f).name[:4]))
    out = []
    for c in idx["clips"]:
        if c.get("kind") != "lesson" or c.get("junk"):
            continue
        p = (res.get("clips") or {}).get(c["file"]) or {}
        w0 = p.get("wall_start")
        if w0 is None:
            continue
        w1 = w0 + (c["dur"] or 0)
        for tx in ("TX01", "TX02"):
            got = sum(max(0.0, min(w1, b) - max(w0, a)) for a, b, t in iv if t == tx)
            if got < (w1 - w0) - 1.0:
                out.append({"clip": c["file"], "tx": tx,
                            "missing_sec": round((w1 - w0) - got, 1)})
    return out


def main():
    ap = argparse.ArgumentParser(description="синхрон съёмочного дня (0121_studio_day)")
    ap.add_argument("--day", default=None)
    ap.add_argument("--stage", action="store_true", help="только разложить дерево")
    a = ap.parse_args()

    day = load_day(a.day)
    D = dirs(day)
    root = stage(day, D)
    if a.stage:
        return 0

    out = root / "Transcription" / "_wordsync"
    log("wordsync --selftest", day=day)
    r = subprocess.run([sys.executable, str(WS), "--selftest"],
                       capture_output=True, text=True, env=env_for_mlx())
    if "SELFTEST PASS" not in (r.stdout + r.stderr):
        die("selftest wordsync не прошёл:\n" + (r.stdout + r.stderr)[-1500:])
    print((r.stdout or "").strip()[-400:])

    log(f"wordsync --day {root}", day=day)
    r = subprocess.run([sys.executable, str(WS), "--day", str(root), "--out", str(out)],
                       text=True, env=env_for_mlx())
    res = load_json(out / "wordsync_result.json")
    if not res:
        die("wordsync не оставил результата")

    bad, note = gate(day, res, D)
    gaps = coverage(day, res, D)

    print("\n──────── гейт синхрона")
    for n in note:
        print(f"  {n}")
    if gaps:
        print(f"\n  ⚠⚠ ПОКРЫТИЕ ПЕТЛИЧКАМИ НЕПОЛНОЕ — {len(gaps)} случаев:")
        for g in gaps[:20]:
            print(f"     {g['clip']:<24} {g['tx']}  не покрыто {g['missing_sec']:.0f} с")
    else:
        print("  покрытие петличками: все дубли закрыты обеими дорожками")
    for b in bad:
        print(f"  ⛔ {b}")
    (out / "gate.json").write_text(json.dumps(
        {"generated": datetime.now().isoformat(timespec="seconds"),
         "notes": note, "failures": bad, "lav_gaps": gaps},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
