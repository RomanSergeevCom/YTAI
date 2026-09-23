#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Манифест работ фабрики: что собирать, откуда брать, куда класть.

Зачем отдельный шаг, а не «просто обойти папку на месте». Фабрика живёт на
Мемексе, а дерево сцен читается только здесь, на маке: у проектов вроде YTEVO03
`01_Source` это не файлы, а 449 симлинков на SD-карту, и восстановить по ним
раскладку на другой машине нечем. Поэтому соответствие «сцена → файл на Drive»
считается ОДИН РАЗ там, где оно видно, проверяется по точному размеру и уезжает
на Drive отдельным файлом. Дальше Мемекс не знает ни про карту, ни про симлинки,
ни про то, какой том был смонтирован: он читает манифест и работает.

Отсюда же берётся ответ на вопрос «можно ли чистить карту». Манифест, у которого
все источники подтверждены на Drive по имени и точному размеру, — это расписка,
что карта больше не нужна для сборки прокси. Пока такой расписки нет, чистка
карты отнимает у фабрики исходники.

⚠️ Непроверенный манифест не публикуется. Если хоть один источник на Drive не
нашёлся или разошёлся в байтах, план остаётся черновиком и печатает, чего не
хватает. Молча собрать 171 клип из 172 и отдать монтажёру — худший исход, чем
не собрать ничего: недостача обнаружится на финальной сборке.

  python3 plan.py --unit YTEVO03                     построить и проверить
  python3 plan.py --unit YTEVO03 --publish           выгрузить манифест на Drive
  python3 plan.py --unit YTEVO03 --show 20           показать первые записи

Версия 1.0 · 23.09.2026 · этап 16_proxy/1603_farm
"""
import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "1601_build"))
sys.path.insert(0, _HERE)
import contract as K                    # noqa: E402
import rebuild as R                     # noqa: E402
from drive import Drive                 # noqa: E402

UNITS_PATH = os.path.join(_HERE, "units.json")
#: Имя манифеста. Лежит РЯДОМ с комплектом на Drive, а не в служебной папке:
#: кто нашёл комплект, нашёл и расписку, из чего он собран.
PLAN_NAME = "_farm_plan.json"
#: Папки, которые в комплект не едут видео-дорожкой: луты и транскрипты
#: доукомплектовываются отдельно (kit.py), звук — сведёнными WAV.
SKIP_DIRS = {"00_LUT", "Transcription", "_XML", "_Proxy", "Sound"}


def load_units(path=UNITS_PATH):
    with open(path) as fh:
        return json.load(fh)


def unit_by_name(cfg, name):
    for u in cfg["units"]:
        if u["name"] == name:
            return u
    raise SystemExit(f"единицы работы «{name}» нет в {UNITS_PATH}; "
                     f"есть: {', '.join(u['name'] for u in cfg['units'])}")


def real_path(p):
    """Куда на самом деле ведёт файл. Симлинк может вести через симлинк."""
    return os.path.realpath(p)


def collect_clips(src_root):
    """Видео проекта: относительный путь (он же путь в комплекте) → что это
    на диске. Обходим рекурсивно: медиа лежит и прямо в сцене, и в подпапках
    камер {сцена}/CAM-A_FX3/."""
    out = {}
    for cur, dirs, files in os.walk(src_root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
        for f in sorted(files):
            if f.startswith("._") or not f.lower().endswith(K.VIDEO_EXT):
                continue
            fp = os.path.join(cur, f)
            out[R.nfc(os.path.relpath(fp, src_root))] = fp
    return out


def map_to_drive(target, mirrors):
    """Абсолютный путь на диске → путь на Drive по таблице зеркал.
    None — этот файл ни в одном зеркале не живёт, и фабрика его не достанет."""
    t = R.nfc(os.path.abspath(target))
    best = None
    for m in mirrors:
        pre = R.nfc(os.path.abspath(m["local"])).rstrip("/") + "/"
        if t.startswith(pre):
            # Самый длинный совпавший префикс: зеркала могут вкладываться.
            if best is None or len(pre) > len(best[0]):
                best = (pre, m["drive"].rstrip("/") + "/" + t[len(pre):])
    return best[1] if best else None


def build(unit, drive, log=print, verify=True):
    """Собрать манифест и проверить каждый источник на Drive по точному размеру."""
    src_root = unit["src_root"]
    if not os.path.isdir(src_root):
        raise SystemExit(f"нет дерева сцен: {src_root}\n"
                         f"  манифест строится там, где оно смонтировано")
    found = collect_clips(src_root)
    log(f"клипов в {os.path.basename(src_root)}: {len(found)}")

    mirrors = unit.get("source_mirrors", [])
    snaps = {}
    if verify:
        for m in mirrors:
            pre = m["drive"].rstrip("/")
            log(f"снимок зеркала на Drive: {pre}")
            s = drive.snapshot(pre)
            if s is None:
                raise SystemExit(f"снимок зеркала {pre} снять не вышло — "
                                 f"без него манифест не проверить, повтори позже")
            snaps[pre] = s
            log(f"  файлов в зеркале: {len(s)}")

    clips, problems = [], []
    for rel in sorted(found):
        local = found[rel]
        tgt = real_path(local)
        try:
            size = os.path.getsize(tgt)
        except OSError as e:
            problems.append((rel, f"источник не читается: {e}"))
            continue
        dpath = map_to_drive(tgt, mirrors)
        if not dpath:
            problems.append((rel, f"нет зеркала на Drive для {tgt}"))
            continue
        if verify:
            pre = next(p for p in snaps if dpath.startswith(p + "/"))
            inner = dpath[len(pre) + 1:]
            rec = snaps[pre].get(R.nfc(inner))
            if rec is None:
                problems.append((rel, f"на Drive нет: {dpath}"))
                continue
            dsize = int(rec.get("Size") or 0)
            if dsize != size:
                problems.append((rel, f"размер разошёлся: диск {size} Б, "
                                      f"Drive {dsize} Б ({dpath})"))
                continue
        clips.append({
            "rel": rel,
            "src_drive": dpath,
            "dst_drive": unit["drive_kit"].rstrip("/") + "/" + rel,
            "size": size,
            "src_local": tgt,          # подсказка: если том смонтирован, берём с него
        })

    # Спаннеры — по ИМЕНИ, а не по признаку симлинка. Признак симлинка здесь
    # бессмыслен: в YTEVO03 симлинками являются ВСЕ источники, и по этому
    # признаку фабрика пропустила бы весь проект, ничего не собрав.
    spanners = dict(R.spanner_plan([c["rel"] for c in clips]))
    for c in clips:
        if c["rel"] in spanners:
            c["spanner_of"] = spanners[c["rel"]]

    meta = {
        "unit": unit["name"],
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "built_on": os.uname().nodename,
        "src_root": src_root,
        "drive_kit": unit["drive_kit"],
        "remote": unit["remote"],
        "team_drive": unit.get("team_drive", ""),
        "clips": len(clips),
        "bytes": sum(c["size"] for c in clips),
        "spanners": len(spanners),
        "verified": bool(verify),
        "problems": [f"{r}: {w}" for r, w in problems],
    }
    return {"meta": meta, "clips": clips}, problems


def main():
    ap = argparse.ArgumentParser(description="манифест работ фабрики прокси")
    ap.add_argument("--unit", required=True, help="имя из units.json")
    ap.add_argument("--units", default=UNITS_PATH)
    ap.add_argument("--publish", action="store_true",
                    help="выгрузить манифест на Drive рядом с комплектом")
    ap.add_argument("--out", default="", help="куда положить локальную копию")
    ap.add_argument("--no-verify", action="store_true",
                    help="не сверять источники с Drive (черновик, не публикуется)")
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--tpslimit", type=int, default=8)
    a = ap.parse_args()

    cfg = load_units(a.units)
    unit = unit_by_name(cfg, a.unit)
    drive = Drive(unit["remote"], unit.get("team_drive", ""), tpslimit=a.tpslimit)

    plan, problems = build(unit, drive, verify=not a.no_verify)
    m = plan["meta"]
    print()
    print(f"манифест {m['unit']}: клипов {m['clips']}, "
          f"{m['bytes']/1e9:.1f} ГБ исходников, спаннеров {m['spanners']}")
    print(f"комплект уедет в: {m['drive_kit']}")
    if a.show:
        for c in plan["clips"][:a.show]:
            print(f"  {c['rel']}  {c['size']/1e9:.2f} ГБ")
            print(f"      ← {c['src_drive']}")

    out = a.out or os.path.join(_HERE, "state", f"plan_{m['unit']}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=1)
    print(f"локальная копия: {out}")

    if problems:
        print(f"\n⛔ манифест НЕ ПОЛНЫЙ: {len(problems)} записей без подтверждённого "
              f"источника на Drive")
        for rel, why in problems[:30]:
            print(f"   · {rel} — {why}")
        if len(problems) > 30:
            print(f"   … ещё {len(problems)-30}")
        print("\nпубликация отменена: фабрика не должна собирать комплект с дырой.")
        print("Пока это не закрыто — карту НЕ чистить: источники ещё нужны.")
        return 1

    if a.no_verify:
        print("\nчерновик (--no-verify): не публикую, источники не сверены с Drive")
        return 0

    print(f"\n✅ все {m['clips']} источников подтверждены на Drive "
          f"по имени и точному размеру")
    if a.publish:
        dst = unit["drive_kit"].rstrip("/") + "/" + PLAN_NAME
        drive.put_text(json.dumps(plan, ensure_ascii=False, indent=1), dst)
        print(f"манифест на Drive: {dst}")
        print("с этого момента фабрике карта не нужна — она работает от Drive")
    else:
        print("для выгрузки на Drive: добавь --publish")
    return 0


if __name__ == "__main__":
    sys.exit(main())
