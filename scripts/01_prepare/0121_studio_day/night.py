#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ночной прогон съёмочного дня: от расшифровки до готовой витрины лутов.

Доводит день до той точки, дальше которой нужен ЧЕЛОВЕК. Человек нужен ровно
в одном месте — выбор цвета: проявка, покраска и экспозиция это решение Романа,
и машина за него не решает. Всё, что до, ночь делает сама; витрина к утру
отрисована и ждёт трёх кликов.

Порядок не произвольный:
  • расшифровка → карта дублей → раскладка. Имя папки урока И ЕСТЬ результат
    расшифровки, поэтому раскладывать раньше значит раскладывать дважды.
  • витрина лутов → прокси. `kit.py` копирует `01_Source/00_LUT/*.cube`
    монтажёру; соберём прокси первыми — уедет старая тройка под видом нового
    цвета, молча. Сам `kit.py` ночь НЕ запускает: он идёт после выбора Романа.
  • стадии строго последовательно — все читают одну карту, и жадность здесь
    уже оплачена на YTEVO03.

⚠️ Ночь ничего не удаляет и ничего не публикует. Провалившийся гейт
   останавливает цепочку и попадает в утренний отчёт — молча дальше не едем.

  python3 night.py                 # весь прогон
  python3 night.py --from proxy    # продолжить с шага
  python3 night.py --dry-run       # что БЫ сделал, ничего не запуская
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import dirs, load_day, load_json, save_json, tg  # noqa: E402

HERE = Path(__file__).resolve().parent
VENV_T = Path.home() / "YTAI/environment/.venv_transcribe/bin/python"
VENV_V = Path.home() / "YTAI/environment/.venv_vlm/bin/python3"
PROXY = Path.home() / "YTAI/scripts/16_proxy/1601_build/proxy.py"
BOARD = Path.home() / "YTAI/scripts/15_color/1502_lut_pick/lut_board.py"

STEPS = ("asr_mic", "audio_cam", "asr_cam", "sync", "takemap", "transcript",
         "screencast", "layout", "board", "proxy", "verify", "report")


def sh(cmd, log_path, timeout=None):
    """Стадия в файл-лог. Возвращает (код, хвост лога)."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n===== {datetime.now():%H:%M:%S} · {' '.join(map(str, cmd))}\n")
        fh.flush()
        try:
            p = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT,
                               timeout=timeout, env=dict(os.environ, TZ="Europe/Moscow"))
            rc = p.returncode
        except subprocess.TimeoutExpired:
            fh.write("\n!! стадия превысила отведённое время\n")
            rc = 124
    tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
    return rc, "\n".join(tail)


def wait_for(pattern, note):
    """Дождаться, пока чужой процесс этой же стадии доработает."""
    seen = False
    while subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0:
        if not seen:
            print(f"[{datetime.now():%H:%M:%S}] жду: {note}", flush=True)
            seen = True
        time.sleep(30)
    return seen


def main():
    ap = argparse.ArgumentParser(description="ночной прогон съёмочного дня")
    ap.add_argument("--day", default=None)
    ap.add_argument("--from", dest="start", choices=STEPS, default=STEPS[0])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    day = load_day(a.day)
    D = dirs(day)
    P = day["project"]
    L = D["logs"]
    state_f = D["work"] / "night.json"
    state = load_json(state_f) or {"steps": {}}
    started = datetime.now()

    plan = [
        ("asr_mic",   [str(VENV_T), str(HERE / "asr.py"), "--only", "mic"],   None,
         "расшифровка петличек"),
        ("audio_cam", ["python3", str(HERE / "audio.py"), "--only", "cam"],   None,
         "рабочий звук камер"),
        ("asr_cam",   [str(VENV_T), str(HERE / "asr.py"), "--only", "cam"],   None,
         "расшифровка камер (якоря синхрона)"),
        ("sync",      [str(VENV_T), str(HERE / "sync.py")],                   None,
         "синхрон дня и гейт из семи пунктов"),
        ("takemap",   [str(VENV_T), str(HERE / "takemap.py")],                None,
         "карта дублей: какой дубль какой урок"),
        ("transcript", ["python3", str(HERE / "transcript.py")],              None,
         "читаемый транскрипт: двое людей, проникание отсечено"),
        ("screencast", [str(VENV_V), str(HERE / "screencast.py"), "--vlm"],   7200,
         "скринкасты: OCR по экранам + смысловая подпись"),
        ("layout",    ["python3", str(HERE / "layout.py"), "--apply", "--wait-mirror", "90"], None,
         "раскладка 01_Source деревом курса"),
        ("board",     [str(VENV_V), str(BOARD), "--project", str(P), "--jobs", "6",
                       "--develop-rows", "3", "--samples", "4",
                       "--look-rows", "3", "--looks", "0"],                   3600,
         "витрина лутов — к утру ждёт трёх кликов"),
        ("proxy",     ["python3", str(PROXY), "--src", str(P / "01_Source"),
                       "--dst", str(P / "01_Source_Proxy"), "--bitrate", "auto",
                       "--exclude", "Video,00_Screencasts", "--jobs", "2",
                       "--report", str(P / "00_Setup/logs" / f"{day['code']}_proxy_report.json")],
         None, "прокси по контракту"),
        ("verify",    ["python3", str(PROXY), "--src", str(P / "01_Source"),
                       "--dst", str(P / "01_Source_Proxy"), "--bitrate", "auto",
                       "--exclude", "Video,00_Screencasts", "--verify-only", "--gate-report",
                       "--report", str(P / "00_Setup/logs" / f"{day['code']}_proxy_verify.json")],
         None, "приёмка прокси, восемь пунктов на каждом клипе"),
        ("report",    ["python3", str(HERE / "dayreport.py")],                None,
         "страница дня: что снято, чем доказано, что осталось"),
    ]
    plan = plan[STEPS.index(a.start):]

    if a.dry_run:
        print("ночной прогон сделал бы:")
        for k, cmd, _, note in plan:
            print(f"  {k:<10} {note}\n             {' '.join(map(str, cmd))}")
        return 0

    tg(f"🌙 <b>{day['code']}</b>: ночной разбор съёмочного дня {day['day']}. "
       f"Шагов {len(plan)}, человек нужен только на выборе цвета.")
    print(f"[{started:%H:%M:%S}] ночной прогон {day['code']} · шагов {len(plan)}", flush=True)

    for key, cmd, tmo, note in plan:
        # Чужой процесс той же стадии (запущенный руками) — дожидаемся его.
        # ⚠️ Но «процесс исчез» ≠ «шаг пройден»: он мог упасть. Проверяем по
        # результату на диске, а не по отсутствию процесса.
        if key == "asr_mic" and wait_for("asr.py --only mic", "расшифровку петличек"):
            want = (day.get("expected") or {}).get("mic_chunks_with_speech") or 0
            got = sum(1 for p in D["words"].glob("*.words.json")
                      if (load_json(p) or {}).get("kind") == "mic"
                      and (load_json(p) or {}).get("speech"))
            ok = got >= want
            state["steps"][key] = {"rc": 0 if ok else 1, "note":
                                   f"шёл отдельным процессом: расшифровок с речью {got}, ждали {want}"}
            save_json(state_f, state)
            print(f"[{datetime.now():%H:%M:%S}] {key}: "
                  f"{'готово' if ok else 'НЕ ДОБРАЛ'} — {got} из {want}", flush=True)
            if ok:
                continue
            tg(f"⛔ <b>{day['code']}</b>: расшифровка петличек не добрала "
               f"({got} из {want}) — ночь встала.")
            state["stopped_at"] = key
            save_json(state_f, state)
            break

        t0 = time.time()
        print(f"[{datetime.now():%H:%M:%S}] {key}: {note}", flush=True)
        rc, tail = sh(cmd, L / f"night_{key}.log", tmo)
        el = time.time() - t0
        state["steps"][key] = {"rc": rc, "sec": round(el), "at": datetime.now().isoformat(timespec="seconds")}
        save_json(state_f, state)
        print(f"[{datetime.now():%H:%M:%S}] {key}: rc={rc} за {el/60:.1f} мин", flush=True)

        if rc != 0:
            # ⚠️ Гейт провалился — дальше не едем. Раскладка на непроверенном
            # синхроне разложит дубли по чужим урокам, и заметить это будет
            # нечем: папки выглядят одинаково правильно.
            tg(f"⛔ <b>{day['code']}</b>: ночь встала на шаге <b>{key}</b> (rc={rc}).\n"
               f"<pre>{tail[-700:]}</pre>")
            print(f"\n⛔ остановка на {key}\n{tail}", flush=True)
            state["stopped_at"] = key
            save_json(state_f, state)
            break

    # ── утренний отчёт
    tm = load_json(P / "00_Setup/01_Ingest" / f"{day['code']}_day1_takemap.json") or {}
    gate = load_json(D["work"] / "days/full/Transcription/_wordsync/gate.json") or {}
    rep = load_json(P / "00_Setup/logs" / f"{day['code']}_proxy_verify.json") or {}
    st = {}
    for t in tm.get("takes", []):
        st[t["status"]] = st.get(t["status"], 0) + 1
    board = P / "01_Source/00_LUT/_build" / f"{day['code']}_lut_board.html"

    lines = [f"🌅 <b>{day['code']}</b> · ночь {started:%H:%M}–{datetime.now():%H:%M}"]
    done = [k for k, v in state["steps"].items() if v.get("rc") == 0]
    lines.append(f"шагов пройдено {len(done)} из {len(plan)}")
    if state.get("stopped_at"):
        lines.append(f"⛔ встали на <b>{state['stopped_at']}</b>")
    if st:
        lines.append("дубли: " + " · ".join(f"{k} {v}" for k, v in sorted(st.items())))
    if gate.get("lav_gaps"):
        lines.append(f"⚠️ петлички не покрывают {len(gate['lav_gaps'])} мест")
    if gate.get("failures"):
        lines.append("⛔ гейт синхрона: " + "; ".join(gate["failures"])[:300])
    if rep:
        lines.append(f"прокси: {rep.get('n', '?')} клипов, отказов {rep.get('fails', '?')}")
    if board.exists():
        lines.append(f"🎨 витрина готова, ждёт выбора:\n<code>{board}</code>")
    tg("\n".join(lines))

    summary = {"generated": datetime.now().isoformat(timespec="seconds"),
               "started": started.isoformat(timespec="seconds"),
               "steps": state["steps"], "stopped_at": state.get("stopped_at"),
               "takes": st, "lav_gaps": len(gate.get("lav_gaps") or []),
               "sync_failures": gate.get("failures") or [],
               "proxy": {k: rep.get(k) for k in ("n", "fails", "total_bytes")} if rep else None,
               "board": str(board) if board.exists() else None}
    save_json(D["work"] / "night_report.json", summary)
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=1))
    return 1 if state.get("stopped_at") else 0


if __name__ == "__main__":
    sys.exit(main())
