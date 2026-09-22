#!/usr/bin/env python3
"""
lut_select.py — отбор кубов из библиотеки: кто годится в проявку, кто в покраску.

Чистая логика выбора над manifest.json, без ffmpeg, без рендера, без numpy.
Переехало ДОСЛОВНО из 15_color/1502_lut_pick/lut_board.py:
    STORE, MANIFEST, MAX_DEVELOP, load_library,
    develop_candidates, look_candidates, recommend_develop, recommend_look,
    short_name.
Новое здесь: store_path() и verify_cube() — путь к кубу на диске и проверка,
что файл на месте и не подменён (sha256 из манифеста).

⚠️ Грабли, записанные в этих функциях:
  • Неизвестная гамма → ПУСТОЙ список, а не «подберём что-нибудь похожее».
    Ровно та снисходительность покрасила 61 клип DJI чужой математикой.
  • Порог «проявка не красит» берётся из taxonomy (neutral_drift255_develop_max),
    он калиброван на 166 кубах. Хардкодить его нельзя.
  • look_candidates по умолчанию отдаёт ВСЕ покрасочные. Первая версия резала
    до восьми, и человек выбрал look, не увидев девятнадцати остальных.
  • STORE/MANIFEST выведены от ЭТОЙ папки (модуль лежит внутри 1501_lut_library),
    а не от папки подборщика, как было в lut_board.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import naming as _N           # noqa: E402
N_TAX = _N.taxonomy()
normalize_gamma = _N.normalize_gamma   # канон гаммы — один на слой, в naming.py

STORE = HERE / "store"
MANIFEST = HERE / "manifest.json"

MAX_DEVELOP = 6    # candidates per camera on stage 2


def load_library() -> list[dict]:
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return man["luts"]


def develop_candidates(luts, gamma, limit=MAX_DEVELOP):
    """Кандидаты проявки под гамму клипа.

    Порядок — по цене в тенях: меньше зажатого чёрного, лучше. Это не вкус,
    а измеримый ущерб. «Родную» семью neutral держим в списке всегда, даже если
    она платит тенями: автор коллекции рекомендует именно её, и Роман должен
    видеть, чего эта рекомендация стоит на его материале.
    """
    g = normalize_gamma(gamma)
    if not g:
        # Неизвестная гамма НЕ ДОЛЖНА молча подбирать кубы с такой же неизвестной.
        # Ровно эта снисходительность и покрасила 61 клип DJI чужой математикой:
        # старый код ставил флаг «mismatch» и ехал дальше.
        return []
    pool = [l for l in luts
            if l["stage"] == "develop"
            and normalize_gamma((l.get("input") or {}).get("gamma")) == g]
    if not pool:
        return []
    # ⚠️ Проявка не имеет права тонировать серое. Её работа тональная — разжать
    # логарифм; цвет начинается на следующей ступени. Кубы, которые красят
    # (Tungsten 6.4, Eastman 7.4, Vision 9.5, Utopia 11.2, IceBlue 19.8 по
    # neutral_drift255) — это проявка с покраской внутри, то есть ровно то, что
    # мы разделяем. Предлагать их как «проявку» значит протащить вкус обратно
    # в технический шаг. В библиотеке они остаются и годятся как look.
    drift_max = N_TAX["stage_detect"]["neutral_drift255_develop_max"]
    flavoured = [l for l in pool
                 if l["metrics"].get("neutral_drift255", 0.0) > drift_max]
    pool = [l for l in pool
            if l["metrics"].get("neutral_drift255", 0.0) <= drift_max]
    if not pool:
        return []
    pool.sort(key=lambda l: (l["metrics"].get("black_share", 0.0), l["id"]))
    picked = pool[:limit]
    return picked


def look_candidates(luts, limit=0):
    """Все покрасочные, от спокойных к характерным.

    ⚠️ По умолчанию показываются ВСЕ. Первая версия резала до восьми «репрезентативных»,
    и Роман выбрал look, не увидев девятнадцати остальных. Покраска — единственное
    по-настоящему вкусовое решение в системе; урезать выбор за человека тут нельзя.
    Покрасочные не привязаны к камере: они ложатся на уже нормальный Rec.709,
    поэтому все до одного годятся для любой из трёх камер.
    """
    pool = [l for l in luts if l["stage"] == "look"]
    pool.sort(key=lambda l: l["metrics"].get("neutral_drift255", 0.0))
    if not limit or len(pool) <= limit:
        return pool
    # Прореживание через np.linspace убрано вместе с зависимостью от numpy.
    # При limit=0 (значение по умолчанию) отдаются ВСЕ покрасочные — так и
    # задумано: раньше резали до восьми, и человек не увидел девятнадцати.
    return pool[:limit]


def recommend_develop(devs):
    """Моя рекомендация по проявке: меньше всего зажатых теней.

    Это не вкус, а измеримый ущерб — зажатую тень не вернуть ничем, а лишний
    пережог светов у log→709 кубов идёт по ролловфу и стоит дешевле.
    Замер 22.09: на S-Log3 neutral топит 14.9 % тёмного кадра, neutral legacy —
    0.01 %; на D-Log2 plus топит 55.7 %, minus — 0.11 %.
    """
    if not devs:
        return None
    return min(devs, key=lambda d: (d["metrics"].get("black_share", 0.0), d["id"]))


def recommend_look(looks, look_metrics):
    """Моя рекомендация по look: максимум характера при нуле повреждений.

    Сначала отбрасываем всё, что режет картинку (пережог > 2 % или зажатое
    чёрное > 1 %), потом из выживших берём самый насыщенный — насыщенность и
    есть тот характер, ради которого look ставят. Единственное решение во всей
    системе, которое действительно вкусовое; числа тут только отсекают вред.
    """
    ok = [l for l in looks
          if look_metrics.get(l["id"], {}).get("clip", 99) <= 2.0
          and look_metrics.get(l["id"], {}).get("black", 99) <= 1.0]
    pool = ok or looks
    if not pool:
        return None
    return max(pool, key=lambda l: look_metrics.get(l["id"], {}).get("sat", 0.0))


# ──────────────────────────────────────────────────── подписи ──

def short_name(lut_id: str) -> str:
    """Читаемая подпись под кадром. Полный id — для манифеста, не для глаза:
    «sony__slog3_sgamut3cine__rec709__neutral__legacy» ни о чём не говорит,
    а «neutral legacy» говорит всё."""
    if lut_id.startswith("look__"):
        return lut_id[6:].replace("_", " ")
    parts = [b for b in lut_id.split("__") if b not in ("rec709",)]
    return " ".join(parts[2:]).replace("_", " ") or " ".join(parts).replace("_", " ")


# ─────────────────────────────────────────────── файл куба на диске ──

def store_path(entry: dict) -> Path:
    """Абсолютный путь куба по записи манифеста. Поле "file" в манифесте
    относительное — от корня store/, а не от текущей папки."""
    return STORE / entry["file"]


def verify_cube(entry: dict) -> tuple[bool, str]:
    """Файл на месте и это тот самый файл? Сверяем sha256 с манифестом.

    Возвращает (True, "") или (False, причина по-русски). Причина для человека:
    её показывают в отчёте, а не парсят.
    """
    path = store_path(entry)
    if not path.exists():
        return False, f"файла нет на диске: {path}"
    want = entry.get("sha256")
    if not want:
        return False, "в манифесте нет sha256 — сверить не с чем"
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    got = h.hexdigest()
    if got != want:
        return False, (f"файл подменён или побит: sha256 {got[:12]}… "
                       f"вместо {want[:12]}…")
    return True, ""
