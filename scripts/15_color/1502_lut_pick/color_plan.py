#!/usr/bin/env python3
"""
color_plan.py — арифметика цвета без картинок: экспозиция, ключи клипов,
профиль канала, файл выбора.

Только стандартная библиотека. Ни ffmpeg, ни Vision, ни numpy/PIL: модуль обязан
считать при размонтированной карте и на машине без медиатеки — иначе «посчитать
промах по стопам» упирается в наличие кадров, которых в этот момент нет.

Переехало ДОСЛОВНО:
  из lut_board.py — EXPOSURE_STOPS, EXPOSURE_EXTRA, EXPOSURE_MAX,
      TARGET_FACE_LUMA_DEFAULT, _TARGET_NOTE, MONTHS_RU, when_ru, stop_tag,
      ladder_for, stops_to_target, profile_path, profile_target, save_choice,
      load_json_safe, save_json_atomic, now_iso;
  из lut_pick.py — backup.

⚠️ stops_to_target переписана с numpy на math. Зажим тот же (±EXPOSURE_MAX),
   результат до знака тот же, но target <= 0 теперь ValueError: у numpy там
   получался -inf, который молча уезжал в зажим -3.0, то есть битая цель
   выглядела как честное «притушить на три стопа».
⚠️ clip_key и clip_slug — не удобство, а формат. Ключ читает панель UXP,
   слаг вшит в ~1100 имён файлов кадров витрины. Правило менять нельзя.
⚠️ Стопы витрины ≠ стопы Lumetri: превью считает экспозицию поверх
   гамма-кодированного Rec.709, Lumetri — после линеаризации. Множитель 2.4,
   см. to_lumetri_stops.
"""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

EXPOSURE_STOPS = (-1.0, -0.5, 0.0, 0.5, 1.0)
EXPOSURE_EXTRA = (1.5, 2.0, 2.5, 3.0, -1.5, -2.0)   # добираются ТОЛЬКО когда нужно
EXPOSURE_MAX = 3.0                                   # предел фильтра exposure в ffmpeg
TARGET_FACE_LUMA_DEFAULT = 150.0
_TARGET_NOTE = ("стартовая догадка; уточняется по ТВОЕМУ выбору — "
                "медиана яркости лиц на кадрах, которые ты отметил")

MONTHS_RU = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
             "августа", "сентября", "октября", "ноября", "декабря")


def when_ru():
    t = time.localtime()
    return (f"{t.tm_mday} {MONTHS_RU[t.tm_mon - 1]} {t.tm_year}, "
            f"{t.tm_hour:02d}:{t.tm_min:02d}")


def stop_tag(st: float) -> str:
    """Имя файла для ступени экспозиции: expm10 / expm05 / exp00 / expp05 / expp10."""
    sign = "m" if st < -1e-6 else ("p" if st > 1e-6 else "")
    return f"exp{sign}{abs(st)*10:02.0f}"


def ladder_for(miss):
    """Ступени для клипа. Базовые ±1 всем, а если промах больше — лестница
    достраивается до него.

    Раньше клип с промахом +3.00 получал те же пять ступеней и подпись
    «лестницы не хватает»: машина знала, что нужно больше, и всё равно
    предлагала потолок. Теперь нужные ступени просто есть.
    """
    steps = set(EXPOSURE_STOPS)
    if miss is None:
        return sorted(steps)
    need = max(-EXPOSURE_MAX, min(EXPOSURE_MAX, miss))
    for st in EXPOSURE_EXTRA:
        if (need > 1.0 and 1.0 < st <= need + 0.5) or \
           (need < -1.0 and need - 0.5 <= st < -1.0):
            steps.add(st)
    return sorted(steps)


def stops_to_target(luma: float, target: float) -> float:
    """На сколько стопов промах. Стоп — это удвоение света, поэтому log2."""
    if luma <= 1.0:
        return 3.0
    # ⚠️ Проверка цели стоит ПОСЛЕ ветки «кадр почти чёрный», чтобы та вела себя
    # ровно как в lut_board.py. Дальше цель обязана быть положительной: log2 от
    # нуля или минуса — это -inf/ошибка, а у numpy -inf молча уезжал в зажим
    # -3.0 и битая цель выглядела как честный замер.
    if target <= 0:
        raise ValueError(f"цель по лицу должна быть больше нуля, получено {target!r}")
    return max(-EXPOSURE_MAX, min(EXPOSURE_MAX, math.log2(target / luma)))


def profile_path(project: Path, code: str) -> Path:
    ch = re.match(r"^(YT[A-Z]{2,4})", code)
    return (Path.home() / "YTAI" / "YTs" / (ch.group(1) if ch else code)
            / "color_profile.json")


def profile_target(project: Path, code: str):
    """Цель по лицу, выученная из прошлых выборов Романа. None — ещё не учились."""
    try:
        d = json.loads(profile_path(project, code).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return (d.get("exposure") or {}).get("target_face_luma")


def save_choice(project: Path, code: str, fb: dict, by_cam_gamma: dict) -> dict:
    """Сохранить выбор Романа: канальное — в профиль, покадровое — в проект.

    Два адреса, потому что у решений разный срок жизни:
      проявка и look — ДНК канала, живут в YTs/{КАНАЛ}/color_profile.json;
      экспозиция — свойство конкретного съёмочного дня, живёт в проекте.
    Профиль пишется по ГАММЕ, а не по камере: завтра в парке появится третья
    тушка на S-Log3, и она должна получить ту же проявку без правок.
    """
    prof_p = profile_path(project, code)
    prof = load_json_safe(prof_p) or {}
    ch = re.match(r"^(YT[A-Z]{2,4})", code)
    prof.setdefault("schema", "color-profile-v1")
    prof["channel"] = ch.group(1) if ch else code
    prof.setdefault("_note", "Цветовая ДНК канала. Проявка выбирается "
                    "ДЕТЕРМИНИРОВАННО по камере+гамме — это технический шаг, не "
                    "вкус. Look — решение Романа, ОДИН на канал.")
    dev = prof.setdefault("develop", {})
    for cam, lut_id in (fb.get("develop") or {}).items():
        gamma = by_cam_gamma.get(cam)
        if not gamma:
            continue
        key = str(gamma)
        entry = dev.setdefault(key, {})
        entry["lut"] = lut_id
        entry.setdefault("cameras", [])
        if cam not in entry["cameras"]:
            entry["cameras"].append(cam)
        entry["decided_by"] = "roman"
        entry["decided_at"] = time.strftime("%Y-%m-%d")
    if fb.get("look"):
        prof["look"] = {"id": fb["look"], "decided_by": "roman",
                        "decided_at": time.strftime("%Y-%m-%d"),
                        "_why": "ДНК канала, выбрана в витрине на реальных кадрах"}
    if fb.get("target_face_luma"):
        prof["exposure"] = {
            "target_face_luma": fb["target_face_luma"],
            "_why": ("выучено по выбору Романа — медиана яркости лиц на кадрах, "
                     "которые он отметил; машина целится сюда, человек правит"),
            "learned_at": time.strftime("%Y-%m-%d"),
            "learned_from": code,
        }
    prof["updated"] = time.strftime("%Y-%m-%d")
    save_json_atomic(prof_p, prof)

    out_p = (project / "00_Setup" / "01_Ingest" / f"{code}_color_choice.json")
    board = project / "00_Setup" / "01_Ingest" / f"{code}_lut_board.html"
    doc = load_json_safe(out_p) or {}
    # Файл описывает САМ СЕБЯ: что за этап, чем закрыт, где артефакты и что
    # дальше. Иначе через месяц по одному словарю экспозиций не восстановить,
    # откуда он взялся и можно ли на него опираться.
    doc.update({
        "schema": "color-choice-v1",
        "stage": {
            "layer": "15_color",
            "name": "Выбор цвета: проявка, покраска, экспозиция",
            "done": True,
            "decided_by": "roman",
            "model": "три ступени: pre → проявка (по камере) → покраска (ДНК канала); "
                     "экспозиция — число между проявкой и покраской, не лут",
            "artifacts": {
                "board": str(board),
                "frames": str(board.parent / f"{code}_lut_board_files"),
                "channel_profile": str(profile_path(project, code)),
            },
            "tool": "scripts/15_color/1502_lut_pick/lut_board.py",
            "next": "проба Input LUT / Exposure в Premiere, затем раскладка "
                    "по клипам и донор канала",
        },
        "project": code,
        "_note": "Покадровый выбор Романа по этому съёмочному дню. Проявка и look "
                 "живут в профиле канала, здесь — только то, что свойство ДНЯ.",
        "develop": fb.get("develop"),
        "look": fb.get("look"),
        "target_face_luma": fb.get("target_face_luma"),
        "exposure": fb.get("exposure"),
        "machine": (fb.get("mine") or {}).get("expo"),
        "corrected": fb.get("corrected"),
        "saved": now_iso(),
        "doc_version": int(doc.get("doc_version") or 0) + 1,
    })
    save_json_atomic(out_p, doc)
    return {"profile": prof_p, "choice": out_p,
            "corrected": len(fb.get("corrected") or {}),
            "clips": len(fb.get("exposure") or {})}


def load_json_safe(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_json_atomic(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    import os as _os
    _os.replace(tmp, path)


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def backup(path):
    """Перед ЛЮБОЙ перезаписью — копия рядом.

    Утверждённый Романом план стоит дороже любого прогона: до 21.09 здесь был
    безусловный plan_path.write_text(), затиравший approved вместе с ручными
    правками.
    """
    path = Path(path)
    if not path.exists():
        return None
    bak = path.with_name(f"{path.stem}.{time.strftime('%Y%m%d_%H%M%S')}.bak.json")
    bak.write_bytes(path.read_bytes())
    return bak


# ─────────────────────────────────────── ключи клипов (нового кода) ──

class SlugCollision(Exception):
    """Два разных клипа дали один слаг.

    Молча взять первый нельзя: кадры второго клипа лягут поверх кадров первого,
    и витрина покажет Роману чужую картинку под правильной подписью.
    """


def clip_key(scene: str, clip_name: str) -> str:
    """Канонический ключ клипа: "01_Morning_Run/RYA-FX3-1212.MP4".

    Сцена и ПОЛНОЕ имя файла с расширением, через прямой слэш.

    ⚠️ Это тот же формат, что читает панель UXP (index.js пере-ключует по
    basename). Менять его нельзя — иначе панель не найдёт ни одного клипа.
    """
    return f"{scene}/{clip_name}"


def clip_slug(scene: str, clip_stem: str) -> str:
    """Слаг для имени файла кадра: "01_Morning_Run_RYA_FX3_1212".

    Сцена и имя клипа БЕЗ расширения, всё не-латинское и не-цифровое схлопнуто
    в подчёркивание.

    ⚠️ Слаг ЛОССОВЫЙ (точка, дефис и слэш становятся одним и тем же "_") и вшит
    в ~1100 имён кадров витрины. Правило менять нельзя: переименование сломает
    все готовые кадры разом. Обратный путь слаг → ключ — только через
    slug_index().
    """
    return re.sub(r"[^A-Za-z0-9]+", "_", f"{scene}_{clip_stem}")


def slug_index(keys) -> dict:
    """Обратная карта: слаг → канонический ключ.

    На вход — канонические ключи вида "сцена/имя.MP4" (см. clip_key).
    Бросает SlugCollision, если два разных ключа дают один слаг: слаг лоссовый,
    и «RYA-FX3-1212.MP4» с «RYA.FX3.1212.MP4» в одной сцене неразличимы.
    """
    out: dict[str, str] = {}
    for key in keys:
        key = str(key)
        scene, _, name = key.rpartition("/")
        slug = clip_slug(scene, Path(name).stem)
        prev = out.get(slug)
        if prev is not None and prev != key:
            raise SlugCollision(
                f"слаг «{slug}» дают два разных клипа: «{prev}» и «{key}» — "
                "кадры одного перезапишут кадры другого; переименуй файл")
        out[slug] = key
    return out



# ────────────────────────────── стопы витрины → стопы Lumetri (ново) ──

LUMETRI_GAMMA = 2.4          # Linearize Gamma 2.4 to Linear — ступень перед экспозицией
LUMETRI_EXPOSURE_LIMIT = 7.0  # предел ползунка Exposure в Basic Correction


def to_lumetri_stops(preview_stops: float) -> float:
    """Стопы витрины → стопы, которые надо вбить в Lumetri.

    ⚠️ Главное знание этого модуля. Превью и Premiere считают экспозицию в
    РАЗНЫХ пространствах, и число из витрины в Lumetri вставлять НЕЛЬЗЯ.

    Превью: ffmpeg вешает фильтр exposure поверх уже проявленного,
    ГАММА-кодированного Rec.709 — то есть просто умножает код на 2^X.
    Lumetri: сначала линеаризует, и только потом двигает экспозицию —
        LUT (проявка) → Linearize Gamma 2.4 to Linear → BasicCorrection3.

    Связь выходит точная: стопы Lumetri = 2.4 × стопы витрины
    (проверено на 30 комбинациях, расхождений нет).

    Округление до 6 знаков — не косметика: 1.5 × 2.4 в double даёт
    3.5999999999999996, и это число уезжает в подпись и в JSON как есть.
    """
    return round(preview_stops * LUMETRI_GAMMA, 6)


def check_lumetri_stops(preview_stops: float) -> tuple[bool, str]:
    """Влезает ли пересчитанная экспозиция в ползунок Lumetri (±7)?

    Зажимать молча нельзя: зажатая экспозиция — это картинка, которая не
    совпадёт с витриной, а человек об этом не узнает. Возвращаем (False,
    причина), чтобы вызывающий показал причину и переснял решение на проявке.
    """
    st = to_lumetri_stops(preview_stops)
    if abs(st) <= LUMETRI_EXPOSURE_LIMIT:
        return True, (f"{preview_stops:+.2f} витрины = {st:+.2f} в Lumetri, "
                      f"предел ±{LUMETRI_EXPOSURE_LIMIT:.0f} выдержан")
    return False, (f"{preview_stops:+.2f} витрины = {st:+.2f} в Lumetri, "
                   f"а ползунок Exposure кончается на "
                   f"±{LUMETRI_EXPOSURE_LIMIT:.0f}: столько одной экспозицией "
                   "не вытянуть, нужна другая проявка")
