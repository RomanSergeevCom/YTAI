#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S6 · раскладка `01_Source` деревом КУРСА, а не съёмочного дня.

    01_Source/
      01_Ustanovochnaya/                        блок = сцена
        1.1_Karta_tseha/                        тема
          1.1.1_Zachem_nuzhen_kontent_zavod/    урок
            CAM-A_FX3/  RYA-FX3-1262.MP4 + …M01.XML
            CAM-B_ZVE1/ RYA-ZVE1-1945.MP4 + …M01.XML
      09_Nerazobrannoe/{CAM-*}/   дубли без доказанного урока
      99_BTS/CAM-C_Pocket/        BTS + .LRF
      00_Tests_And_Sync/CAM-*/    обрывки

Почему именно так:

⚠️ Цифровой префикс ВЕРХНЕГО уровня обязателен: `color_media.content_scenes()`
   берёт только `^\\d\\d_` и отбрасывает `00_*`. Значит блок = сцена. Без
   префикса витрина находит ноль сцен и выходит с кодом 0 — тихий провал,
   видимый только в Premiere.
⚠️ `09_Nerazobrannoe` и `99_BTS` под правило подходят и в витрину ПОПАДУТ —
   это и нужно: иначе лог-клипы остались бы без проявки и без единого сообщения.
⚠️ Камера опознаётся по префиксу `CAM-` где угодно в пути (правка `cam_of()`
   от 24.09). До неё `parts[1]` вернул бы имя темы, профиль канала завёл бы
   «камеру» `1.1_Karta_tseha`, и раскладка отказала бы на всём дне, не упав.
⚠️ `_edit.wav` в `01_Source` не попадает ВОВСЕ: `kit.copy_scene_audio()` при
   отсутствии `*_timeline.wav` уходит в ветку «всё, что не _orig» и утащил бы
   2,9 ГБ обработанных рекордером дублей монтажёру.
⚠️ Медиа не удаляется никогда. Обрывки и мёртвый огрызок петлички не прячутся,
   а называются в отчёте.

  python3 layout.py            # сухой прогон: что БЫ разложил
  python3 layout.py --apply
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import die, dirs, load_day, load_json, log, save_json  # noqa: E402

TRANS = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def latin(s, limit=44):
    """Имена файлов и папок только латиницей — канон Романа."""
    s = (s or "").lower()
    s = "".join(TRANS.get(c, c) for c in s)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:limit].rstrip("_") or "bez_nazvaniya"


def resolve_src(p: Path, day):
    """Откуда брать файл: с зеркала, если оно уже полное, иначе с карты.

    ⚠️ Полнота проверяется ТОЧНЫМ РАЗМЕРОМ В БАЙТАХ, а не наличием файла.
    Копия дерева карты идёт часами, и на полпути файл уже существует, но
    дописан наполовину. Симлинк на такой файл выглядит рабочим и ломается
    молча — в Premiere это будет обрыв в середине дубля, а не отсутствующий
    клип. Правило то же, что в подготовке карт: имя И точный размер.
    """
    for m in (day.get("mirrors") or []):
        root = Path(m["root"]).expanduser()
        if not root.is_dir():
            continue
        try:
            rel = p.relative_to(Path(m.get("of") or day["card"]))
        except ValueError:
            continue
        cand = root / rel
        try:
            if cand.stat().st_size == p.stat().st_size:
                return cand, m.get("name") or root.name
        except OSError:
            continue
    return p, "карта"


def wait_mirror(day, minutes):
    """Дождаться, пока зеркало догонит карту по имени И точному размеру.

    ⚠️ Раскладываться на полускопированное дерево нельзя: файл уже существует,
    но дописан наполовину, симлинк на него выглядит рабочим и рвётся молча —
    в Premiere это обрыв в середине дубля, а не отсутствующий клип.
    Ждём ограниченно; не дождались — раскладываем с карты и говорим об этом.
    """
    import time
    m = (day.get("mirrors") or [None])[0]
    if not m:
        return
    root, of = Path(m["root"]), Path(m.get("of") or day["card"])
    deadline = time.time() + minutes * 60
    while True:
        miss = part = 0
        for dp, _, fn in os.walk(of):
            for f in fn:
                if f.startswith("."):
                    continue
                src = Path(dp) / f
                dst = root / src.relative_to(of)
                try:
                    if dst.stat().st_size != src.stat().st_size:
                        part += 1
                except OSError:
                    miss += 1
        if miss == 0 and part == 0:
            print(f"  зеркало {m['name']}: полное, раскладываем с него")
            return
        if time.time() > deadline:
            print(f"  ⚠ зеркало {m['name']} не догнало за {minutes} мин "
                  f"(нет {miss}, недописано {part}) — берём что готово, остальное с карты")
            return
        print(f"  жду зеркало {m['name']}: нет {miss}, недописано {part}", flush=True)
        time.sleep(60)


def link(src: Path, dst: Path, apply: bool):
    if not apply:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    os.symlink(src, dst)            # абсолютный: путь идёт через APFS→exFAT


def sidecars(path: Path):
    """Сайдкар неотделим от клипа: без `{stem}M01.XML` Sony теряет гамму
    (`sony_gamma` ищет его РЯДОМ с клипом), и цвет откажет на всём дне.
    У DJI рядом лежит `.LRF` — собственная запись камеры о дубле.
    """
    out = []
    for cand in (path.with_name(path.stem + "M01.XML"),     # Sony
                 path.with_suffix(".LRF"),                   # DJI
                 path.with_suffix(".lrf")):
        if cand.exists() and cand != path:
            out.append(cand)
    return out


SCENES = re.compile(r"^\d\d_")
# ⚠️ `00_LUT` под `^\d\d_` подходит, но раскладке не принадлежит: там ЖИВЫЕ
# кубы и витрина, а не ссылки. Чистилке туда нельзя даже заглядывать.
NOT_SCENES = {"00_LUT"}


def prune(src_root: Path, apply: bool):
    """Снять ПРЕЖНИЕ ссылки раскладки перед новой.

    ⚠️ Раскладка не перекладывает — она добавляет. Стоит дублю сменить урок
    (уточнилась карта), и клип оказывается сразу в ДВУХ уроках: новая ссылка
    появилась, старая осталась. Сцена с двумя одинаковыми именами роняет
    витрину (`color_media.DuplicateClip`), а если бы не роняла — монтажёр
    получил бы один дубль в двух уроках и не заметил.

    Снимаем ТОЛЬКО символические ссылки и ТОЛЬКО внутри сцен, которые кладёт
    сама раскладка. Настоящие файлы (кубы `00_LUT`, `Transcription`, `Audio`)
    не трогаются: `unlink` вызывается лишь там, где `is_symlink()`.
    """
    if not src_root.exists():
        return
    n = 0
    scenes = [s for s in sorted(src_root.iterdir())
              if s.is_dir() and not s.is_symlink()
              and SCENES.match(s.name) and s.name not in NOT_SCENES]
    for scene in scenes:                                  # 1) ссылки
        for p in scene.rglob("*"):
            if p.is_symlink():
                if apply:
                    p.unlink()
                n += 1
    if apply:                                             # 2) опустевшее — снизу вверх
        for scene in scenes:
            for p in sorted(scene.rglob("*"), key=lambda x: len(x.parts), reverse=True):
                if p.is_dir() and not p.is_symlink() and not any(p.iterdir()):
                    p.rmdir()
    log(f"снято прежних ссылок: {n}" + ("" if apply else " (сухой прогон)"))


def main():
    ap = argparse.ArgumentParser(description="раскладка 01_Source деревом курса")
    ap.add_argument("--day", default=None)
    ap.add_argument("--apply", action="store_true", help="сделать (без флага — только рассказать)")
    ap.add_argument("--wait-mirror", type=int, default=0, metavar="МИН",
                    help="ждать, пока копия на зеркале догонит карту (0 — не ждать)")
    a = ap.parse_args()
    day = load_day(a.day)
    D = dirs(day)

    if a.wait_mirror:
        wait_mirror(day, a.wait_mirror)
    prune(day["project"] / "01_Source", a.apply)
    idx = load_json(D["work"] / "index.json") or die("нет index.json")
    tm = load_json(day["project"] / "00_Setup/01_Ingest" / f"{day['code']}_day1_takemap.json")
    if not tm:
        die("нет карты дублей — сначала python3 takemap.py")
    th = load_json(day["preprod"] / "05_Lessons/themes.json") or {}
    blocks = {b["id"]: b for b in th.get("blocks", [])}
    themes = {t["id"]: t for t in th.get("themes", [])}

    src_root = day["project"] / "01_Source"
    by_stem = {Path(c["path"]).stem: c for c in idx["clips"]}
    lesson_of = {}
    for t in tm["takes"]:
        les = t.get("lesson")
        if t["status"] in ("proven", "probable") and les:
            for cam, stem in t["clips"].items():
                lesson_of[stem] = les

    plan, counts, srcs = [], {"урок": 0, "неразобрано": 0, "BTS": 0, "обрывки": 0}, {}
    for c in idx["clips"]:
        if not c.get("ok"):
            continue
        stem, p = Path(c["path"]).stem, Path(c["path"])
        if c.get("junk"):
            rel = Path("00_Tests_And_Sync") / c["cam"] / p.name
            counts["обрывки"] += 1
        elif c.get("kind") == "bts":
            rel = Path("99_BTS") / c["cam"] / p.name
            counts["BTS"] += 1
        elif stem in lesson_of:
            les = lesson_of[stem]
            bid = int(str(les["id"]).split(".")[0])
            tid = ".".join(str(les["id"]).split(".")[:2])
            b = blocks.get(bid, {})
            t = themes.get(tid, {})
            rel = (Path(f"{bid:02d}_{latin(b.get('title'))}")
                   / f"{tid}_{latin(t.get('title') or t.get('part'))}"
                   / f"{les['id']}_{latin(les.get('title'))}"
                   / c["cam"] / p.name)
            counts["урок"] += 1
        else:
            rel = Path("09_Nerazobrannoe") / c["cam"] / p.name
            counts["неразобрано"] += 1
        real, where = resolve_src(p, day)
        srcs[where] = srcs.get(where, 0) + 1
        plan.append((real, src_root / rel))
        for sc_ in sidecars(p):
            plan.append((resolve_src(sc_, day)[0], (src_root / rel).with_name(sc_.name)))

    # ── скринкасты: тот же путь урока, но ВНЕ нумерованных сцен
    #
    # ⚠️ Почему не внутрь урока рядом с камерами. `content_scenes()` берёт всё,
    # что начинается с цифр, а `scene_clips()` рекурсивна — скринкаст попал бы
    # в витрину лутов. Гаммы у записи экрана нет (сайдкара нет, тега DJI нет),
    # `detect_gamma` вернул бы None, `resolve_develop` — отказ, а отказ в
    # `color_apply` ОБЩИЙ НА ПРОЕКТ: план не записался бы вовсе, и цвет встал бы
    # на всём съёмочном дне из-за файлов, которым красить нечего.
    # Префикс `00_` — ровно та служебная полка, которую слой цвета отбрасывает
    # намеренно. Дерево урока внутри сохраняем: монтажёру нужно именно оно.
    sc = load_json(D["work"] / "screencasts.json") or {}
    sc_plan = []
    for it in (sc.get("items") or []):
        les_id = it.get("lesson")
        if not les_id:
            rel = Path("00_Screencasts") / "_nerazobrannoe" / it["file"]
        else:
            bid = int(str(les_id).split(".")[0])
            tid = ".".join(str(les_id).split(".")[:2])
            b, t = blocks.get(bid, {}), themes.get(tid, {})
            rel = (Path("00_Screencasts")
                   / f"{bid:02d}_{latin(b.get('title'))}"
                   / f"{tid}_{latin(t.get('title') or t.get('part'))}"
                   / f"{les_id}_{latin(it.get('title'))}"
                   / it["file"])
        sc_plan.append((resolve_src(Path(it["path"]), day)[0], src_root / rel))

    # ── петлички: РЕАЛЬНЫЕ копии, они дневные и должны пережить извлечение карты
    dji = day["project"] / "99_Pipeline/DJI_Audio"
    mic_plan = [(resolve_src(Path(m["path"]), day)[0], dji / m["file"]) for m in idx["mics"]]
    mic_bytes = sum(Path(m["path"]).stat().st_size for m in idx["mics"])

    print(f"\n  клипы: урок {counts['урок']} · неразобрано {counts['неразобрано']} · "
          f"BTS {counts['BTS']} · обрывки {counts['обрывки']}")
    print("  источник: " + " · ".join(f"{k} {v}" for k, v in sorted(srcs.items())))
    print(f"  скринкасты: {len(sc_plan)} (вне нумерованных сцен — цвету их красить нечем)")
    print(f"  всего ссылок (с сайдкарами): {len(plan) + len(sc_plan)}")
    print(f"  петлички: {len(mic_plan)} файлов, {mic_bytes/1e9:.2f} ГБ реальной копией")
    tree = sorted({str(d.relative_to(src_root).parent) for _, d in plan + sc_plan})
    print(f"\n  дерево ({len(tree)} папок):")
    for t in tree[:40]:
        print(f"    {t}")
    if len(tree) > 40:
        print(f"    … ещё {len(tree)-40}")

    if not a.apply:
        print("\n  (сухой прогон — ничего не создано; повтори с --apply)")
        return 0

    for s, d in plan + sc_plan:
        link(s, d, True)
    dji.mkdir(parents=True, exist_ok=True)
    copied = 0
    for s, d in mic_plan:
        if d.exists() and d.stat().st_size == s.stat().st_size:
            continue
        shutil.copy2(s, d)
        copied += 1
    log(f"разложено: ссылок {len(plan)} · петличек скопировано {copied}", day=day)

    save_json(D["work"] / "layout.json",
              {"schema": "ytai-studio-day-layout-v1", "code": day["code"],
               "counts": {**counts, "скринкасты": len(sc_plan)},
               "links": [[str(s), str(d)] for s, d in plan + sc_plan],
               "mics_copied_to": str(dji)})
    print(f"\n  готово: {src_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
