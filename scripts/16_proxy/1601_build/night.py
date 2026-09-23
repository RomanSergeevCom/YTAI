#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ночной супервизор прокси: собрать → самоаудит → починить → снова самоаудит.

Задача — чтобы машина не простаивала и чтобы к утру был не просто набор файлов,
а **доказанный** комплект. Поэтому супервизор не запускает пересборку и не уходит,
а крутит замкнутый круг:

    1. сборка        rebuild.py --kit K          (резюмируемо, своя защита)
    2. самоаудит     rebuild.py --kit K --verify-only
    3. если что-то не сошлось — круг повторяется: сборка переделает ровно
       непрошедшие клипы, аудит проверит заново
    4. канал принят  → следующий канал из очереди
    5. очередь пуста → сверка по всем дискам (audit.py) и отчёт

Почему круг, а не «запустил и забыл»: у сборки есть свои ретраи, но они про
один клип. Круг ловит другое — случаи, когда прогон закончился, а комплект не
сошёлся: оборвалась сеть на середине, Drive вернул квоту, том отвалился.
Такое лечится повтором, и повтор должен случиться ночью, а не утром.

Правила, которые супервизор не нарушает:

- **исходники не трогаются никогда**; удаляется только собранный прокси из
  стейджинга и только после подтверждённой заливки;
- **круг конечен**: `--max-rounds` на канал. Если и после них не сошлось, канал
  помечается «нужны руки», и супервизор идёт к следующему, а не бьётся в стену;
- **место**: ниже неприкосновенного запаса — не расчищаем, а ждём и сообщаем;
- **STOP** в стейджинге останавливает и сборку, и круг.

  python3 night.py --kits YTCH                     одна ночь, один канал
  python3 night.py --kits YTCH,YTUVI --until 09:00 очередь каналов до утра
  python3 night.py --status                        что происходит прямо сейчас
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import contract as K

LOGDIR = os.path.expanduser("~/Library/Logs/ytai")
STATE = os.path.join(HERE, "state", "night.json")
PIDF = os.path.join(HERE, "state", "night.pid")
DEFAULT_STAGE = os.path.expanduser("~/.cache/ytai/proxy_stage")
TG_ENV = os.path.expanduser("~/.claude/channels/telegram-rya/.env")
TG_CHAT = "155880671"


def now():
    return datetime.now().strftime("%H:%M:%S")


def log(msg):
    print(f"{now()} {msg}", flush=True)


def tg(text):
    try:
        token = ""
        with open(TG_ENV) as fh:
            for line in fh:
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"\'')
                    break
        if not token:
            return
        subprocess.run(["curl", "-sS", "--max-time", "45",
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        "-d", f"chat_id={TG_CHAT}",
                        "-d", "disable_web_page_preview=true",
                        "--data-urlencode", f"text={text}"],
                       capture_output=True, timeout=60)
    except Exception:
        pass            # телеграм не обязан работать, чтобы работала ночь


def load(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def single_instance():
    """Второй супервизор за ночь — это два прогона на один стейджинг."""
    old = load(PIDF.replace(".pid", ".pidjson"), {}).get("pid")
    if old:
        r = subprocess.run(["ps", "-p", str(old), "-o", "command="],
                           capture_output=True, text=True)
        if "night.py" in r.stdout:
            return False, old
    save(PIDF.replace(".pid", ".pidjson"), {"pid": os.getpid()})
    return True, os.getpid()


def stop_requested(stage):
    return os.path.exists(os.path.join(stage, "STOP"))


def run_step(cmd, logfile, label):
    """Один шаг круга. Возвращает (код возврата, хвост лога)."""
    log(f"── {label}")
    log(f"   {' '.join(str(c) for c in cmd)}")
    with open(logfile, "a") as fh:
        fh.write(f"\n===== {label} · {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        fh.flush()
        p = subprocess.Popen([str(c) for c in cmd], stdout=fh,
                             stderr=subprocess.STDOUT)
        rc = p.wait()
    tail = ""
    try:
        with open(logfile) as fh:
            tail = "".join(fh.readlines()[-25:])
    except Exception:
        pass
    log(f"   {label}: код {rc}")
    return rc, tail


def parse_acceptance(tail):
    """Вытащить из хвоста лога, сколько клипов не сошлось."""
    m = re.search(r"не сошлось[^\d]{0,20}(\d+)", tail)
    if m:
        return int(m.group(1))
    if re.search(r"ПРИНЯТ|ACCEPTED|всё сошлось", tail):
        return 0
    return None


def channel_round(kit, a, rnd, logfile):
    """Один круг по каналу: сборка, затем самоаудит."""
    py = sys.executable
    build = [py, "-u", os.path.join(HERE, "rebuild.py"), "--kit", kit,
             "--jobs", str(a.jobs), "--stage", a.stage,
             "--min-free-gb", str(a.min_free_gb)]
    if rnd > 1:
        build.append("--rescan")       # второй круг не верит старому снимку Drive
    rc_build, _ = run_step(build, logfile, f"{kit}: сборка, круг {rnd}")

    audit = [py, "-u", os.path.join(HERE, "rebuild.py"), "--kit", kit,
             "--verify-only", "--stage", a.stage, "--no-telegram"]
    rc_audit, tail = run_step(audit, logfile, f"{kit}: самоаудит, круг {rnd}")
    bad = parse_acceptance(tail)
    return rc_build, rc_audit, bad, tail


def disk_audit(a, logfile):
    py = sys.executable
    out = os.path.join(LOGDIR, f"proxy_audit_{datetime.now():%Y%m%d_%H%M}.json")
    rc, tail = run_step([py, "-u", os.path.join(HERE, "audit.py"),
                         "--sample", "8", "--json", out],
                        logfile, "сверка по всем дискам")
    return rc, tail, out


def main():
    ap = argparse.ArgumentParser(description="ночной супервизор прокси")
    ap.add_argument("--kits", default="YTCH", help="каналы через запятую, по порядку")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--stage", default=DEFAULT_STAGE)
    ap.add_argument("--min-free-gb", type=float, default=10.0)
    ap.add_argument("--max-rounds", type=int, default=3,
                    help="сколько раз повторять круг, пока канал не сойдётся")
    ap.add_argument("--until", default="",
                    help="во сколько заканчивать, ЧЧ:ММ; иначе пока не кончится очередь")
    ap.add_argument("--status", action="store_true", help="что происходит сейчас")
    a = ap.parse_args()

    if a.status:
        st = load(STATE, {})
        print(json.dumps(st, ensure_ascii=False, indent=1))
        return 0

    alone, who = single_instance()
    if not alone:
        print(f"супервизор уже бежит (pid {who}) — выхожу", file=sys.stderr)
        return 5

    os.makedirs(LOGDIR, exist_ok=True)
    os.makedirs(a.stage, exist_ok=True)
    logfile = os.path.join(LOGDIR, f"proxy_night_{datetime.now():%Y%m%d_%H%M}.log")

    deadline = None
    if a.until:
        hh, mm = (int(x) for x in a.until.split(":"))
        deadline = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0)
        if deadline <= datetime.now():
            deadline += timedelta(days=1)

    kits = [k.strip() for k in a.kits.split(",") if k.strip()]
    st = {"started": datetime.now().isoformat(timespec="seconds"),
          "kits": kits, "log": logfile, "channels": {},
          "until": deadline.isoformat(timespec="minutes") if deadline else None}
    save(STATE, st)

    log("")
    log(f"═══ НОЧНОЙ СУПЕРВИЗОР ПРОКСИ · каналы: {', '.join(kits)}")
    log(f"    круг: сборка → самоаудит → при расхождении повтор (до {a.max_rounds})")
    log(f"    стейджинг {a.stage}, запас {a.min_free_gb:g} ГБ, потоков {a.jobs}")
    if deadline:
        log(f"    работать до {deadline:%H:%M}")
    log(f"    лог {logfile}")
    tg(f"🌙 Ночь прокси пошла: {', '.join(kits)}. Круг «сборка → самоаудит → "
       f"починка» до {a.max_rounds} раз на канал. Остановить: "
       f"touch {os.path.join(a.stage, 'STOP')}")

    for kit in kits:
        if stop_requested(a.stage):
            log("STOP в стейджинге — заканчиваю")
            break
        if deadline and datetime.now() >= deadline:
            log("время вышло — заканчиваю")
            break

        ch = {"rounds": [], "verdict": "идёт"}
        st["channels"][kit] = ch
        save(STATE, st)

        for rnd in range(1, a.max_rounds + 1):
            if stop_requested(a.stage) or (deadline and datetime.now() >= deadline):
                ch["verdict"] = "прервано"
                break
            t0 = time.time()
            rc_b, rc_a, bad, tail = channel_round(kit, a, rnd, logfile)
            ch["rounds"].append({"round": rnd, "build_rc": rc_b, "audit_rc": rc_a,
                                 "bad": bad, "minutes": round((time.time()-t0)/60, 1)})
            save(STATE, st)

            if rc_a == 0 and (bad in (0, None)):
                ch["verdict"] = "принят"
                log(f"✅ {kit}: комплект сошёлся с {rnd}-го круга")
                tg(f"✅ Прокси {kit}: комплект собран и самоаудит пройден "
                   f"(круг {rnd}). Контракт сошёлся по всем клипам.")
                break
            log(f"⚠️ {kit}: круг {rnd} не сошёлся"
                + (f" ({bad} клипов)" if bad else "") + " — повторяю")
        else:
            ch["verdict"] = "нужны руки"
            log(f"✗ {kit}: {a.max_rounds} круга не сошлись — оставляю на утро")
            tg(f"⚠️ Прокси {kit}: {a.max_rounds} круга подряд комплект не сошёлся. "
               f"Дальше сам не лечу — нужны руки. Лог: {logfile}")
        save(STATE, st)

    if not stop_requested(a.stage):
        log("── заключительная сверка по всем дискам")
        _rc, tail, js = disk_audit(a, logfile)
        st["disk_audit"] = js
        save(STATE, st)
        head = "\n".join(l for l in tail.splitlines() if "требуют работы" in l)
        tg("🌅 Ночь прокси закончена.\n"
           + "\n".join(f"{k}: {v['verdict']}" for k, v in st["channels"].items())
           + (f"\n{head}" if head else "")
           + f"\nЛог: {logfile}")

    st["finished"] = datetime.now().isoformat(timespec="seconds")
    save(STATE, st)
    log("═══ супервизор закончил")
    return 0


if __name__ == "__main__":
    sys.exit(main())
