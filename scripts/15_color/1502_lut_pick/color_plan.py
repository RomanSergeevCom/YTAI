#!/usr/bin/env python3
"""
color_plan.py — арифметика цвета без картинок: экспозиция, ключи клипов,
профиль канала, файл выбора, адреса на диске.

Здесь же живёт ЕДИНСТВЕННОЕ определение дома лутов (lut_home / lut_build_dir /
build_file): модуль на stdlib, и его импортируют и витрина, и раскладка, — значит
путь считается один раз и в одном месте, а не собирается руками в каждом скрипте.

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
EXPOSURE_EXTRA = (1.5, 2.0, 2.5, 3.0, -1.5, -2.0, -2.5, -3.0)  # ТОЛЬКО когда нужно
# ⚠️ Набор симметричен намеренно. Раньше вверх он дотягивался до +3, а вниз
# упирался в −2, и клип с промахом −2,5 (выбитое лицо при тёмной выученной
# цели: stops_to_target(255, 45) = −2,50) получал потолок −2,0 — та самая
# болезнь, которую докстринг ladder_for объявляет вылеченной.
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
    # ⚠️ Тег несёт ДЕСЯТЫЕ, а не сотые: 0,15 и 0,25 округлились бы в один «02»,
    # и два кадра лестницы молча записались бы в один файл. Сейчас через
    # ladder_for такие ступени не рождаются, но тихо схлопывать их нельзя —
    # именно этот класс ошибки («имя обязано нести всё, от чего зависит
    # содержимое») стоил слою трёх багов за одну сессию. Ступень не на сетке
    # 0,1 — это ошибка вызывающего, а не повод потерять кадр.
    if abs(round(st * 10) - st * 10) > 1e-6:
        raise ValueError(
            f"ступень экспозиции {st} не ложится на сетку 0,1 — имя кадра "
            f"не сможет её отличить от соседней; округли или расширь тег")
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


# ─────────────────────────────────────────────────────────────────────────────
# Дом лутов проекта — ОДИН на всё, что касается цвета
# ─────────────────────────────────────────────────────────────────────────────
# Решение Романа: у лутов один адрес, и монтажёр обязан найти его не спрашивая.
# Поэтому рабочая тройка лежит ПЛОСКО на верхнем уровне 00_LUT — открыл папку и
# сразу видишь три файла, которые кладут на таймлайн. Всё, по чему выбирали
# (витрина, кадры, JSON-ы этапа), уезжает на этаж ниже, в `_build/`: это не
# мусор, его нужно уметь перечитать через полгода, но глаза монтажёру оно
# засоряет. Раньше эти файлы жили в 00_Setup/01_Ingest — то есть выбор цвета
# хранился в папке про ингест, и до самого проекта вообще не доезжал.

LUT_HOME_PARTS = ("01_Source", "00_LUT")
LUT_BUILD_DIRNAME = "_build"
#: где эти файлы лежали до переезда — читаем оттуда, пишем туда НИКОГДА
LEGACY_BUILD_PARTS = ("00_Setup", "01_Ingest")


def lut_home(project: Path) -> Path:
    """`{проект}/01_Source/00_LUT` — рабочие кубы, плоско."""
    return Path(project).joinpath(*LUT_HOME_PARTS)


def lut_build_dir(project: Path) -> Path:
    """`{проект}/01_Source/00_LUT/_build` — как выбирали: доска, кадры, JSON-ы."""
    return lut_home(project) / LUT_BUILD_DIRNAME


def legacy_build_dir(project: Path) -> Path:
    """Старый адрес этапа цвета. ⚠️ Здесь же и дальше живёт легаси
    `{CODE}_lut_plan.json`: его читает UXP-панель, и он никуда не переезжает."""
    return Path(project).joinpath(*LEGACY_BUILD_PARTS)


def build_file(project: Path, name: str, log=None) -> Path:
    """Путь к файлу этапа для ЧТЕНИЯ: новый дом, иначе старый.

    Уже собранные проекты не должны сломаться от переезда, поэтому чтение знает
    оба адреса. Найденное в старом месте — не молчаливая подмена, а строка в
    логе: иначе непонятно, почему свежий прогон опирается на данные, которых в
    новом доме нет. Когда файла нет нигде, возвращаем НОВЫЙ путь — сообщение
    «нет такого файла» обязано показывать туда, где его ждут сегодня.
    """
    new = lut_build_dir(project) / name
    if new.exists():
        return new
    old = legacy_build_dir(project) / name
    if old.exists():
        if log:
            log(f"  ⚠️ {name}: в новом доме нет, читаю старый адрес {old.parent}")
        return old
    return new


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


def save_choice(project: Path, code: str, fb: dict, by_cam_gamma: dict,
                known_slugs=None) -> dict:
    """Сохранить выбор Романа: канальное — в профиль, покадровое — в проект.

    Два адреса, потому что у решений разный срок жизни:
      проявка и look — ДНК канала, живут в YTs/{КАНАЛ}/color_profile.json;
      экспозиция — свойство конкретного съёмочного дня, живёт в проекте.
    Профиль пишется по ГАММЕ, а не по камере: завтра в парке появится третья
    тушка на S-Log3, и она должна получить ту же проявку без правок.
    """
    check_feedback(fb, code, known_slugs)

    prof_p = profile_path(project, code)
    prev_prof = load_json_safe(prof_p)
    if prof_p.exists() and prev_prof is None:
        # ⚠️ Файл ЕСТЬ, но не читается. Профиль лежит под git, и маркеры конфликта
        # от merge/rebase/stash pop делают его нечитаемым. Пойти дальше значило бы
        # собрать профиль заново из пустого места и снести проявки, look и
        # выученную цель СРАЗУ ПО ВСЕМ проектам канала — восстановить неоткуда.
        raise ProfileUnreadable(
            f"профиль канала не читается: {prof_p}\n"
            f"  похоже на маркеры конфликта git или обрыв записи.\n"
            f"  почини файл руками — перезаписать его сейчас значит потерять ДНК канала")
    prof = prev_prof or {}
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
    # ⚠️ Копия ДНК канала обязательна: это единственный файл, который общий на все
    # проекты канала, и восстановить его из проекта нельзя.
    backup(prof_p)
    save_json_atomic(prof_p, prof)

    out_p = lut_build_dir(project) / f"{code}_color_choice.json"
    board = lut_build_dir(project) / f"{code}_lut_board.html"
    # ⚠️ Пишем всегда в новый дом, а нумерацию версии продолжаем от того файла,
    # который РЕАЛЬНО есть: на проекте, собранном до переезда, выбор лежит в
    # старом месте, и начать с единицы значило бы соврать про историю правок.
    doc = load_json_safe(build_file(project, f"{code}_color_choice.json", log=print)) or {}
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
    backup(out_p)
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
    """Запись через временный файл и os.replace — читатель видит либо старое, либо новое.

    ⚠️ Имя временного файла ОБЯЗАНО быть уникальным. Общий `.tmp` на всех писателей
    давал гонку: первый успевал сделать replace, второй падал необработанным
    FileNotFoundError на уже переименованном файле. Битого JSON при этом не
    получалось ни разу, но прогон обрывался на полпути — а save_choice пишет два
    файла подряд, и обрыв между ними оставлял половину сохранения.
    """
    import os as _os
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.{_os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        _os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)      # не оставляем мусор рядом с данными
        raise


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
    # ⚠️ Метка с точностью до СЕКУНДЫ затирала предыдущую копию, когда за ту же
    # секунду писали дважды — а это ровно сценарий, ради которого функция заведена
    # (перезапись утверждённого плана). Если имя занято, ищем свободный суффикс:
    # копия, которая молча затёрла другую копию, хуже отсутствия копии.
    base = f"{path.stem}.{time.strftime('%Y%m%d_%H%M%S')}"
    bak = path.with_name(f"{base}.bak.json")
    n = 1
    while bak.exists():
        bak = path.with_name(f"{base}_{n:02d}.bak.json")
        n += 1
    bak.write_bytes(path.read_bytes())
    return bak


# ─────────────────────────────────────── ключи клипов (нового кода) ──

def _count(it):
    d = {}
    for x in it:
        d[x] = d.get(x, 0) + 1
    return d


class ProfileUnreadable(Exception):
    """Профиль канала есть, но не читается. Перезаписывать нельзя."""


class BadFeedback(Exception):
    """Payload не тот, что ждёт витрина. Сохранять нельзя."""


def check_feedback(fb: dict, code: str, known_slugs=None) -> None:
    """Проверить payload ДО записи. Отказ вместо частичного сохранения.

    ⚠️ Раньше `doc.update(...)` клал в документ то, что пришло, не глядя. Payload
    старого формата (`{type: 'lut_feedback', choices, notes}` — ровно так выгружал
    архивный подборщик) не несёт ни develop, ни look, ни exposure, поэтому все эти
    поля становились None, а doc_version при этом рос. День занулялся молча и
    выглядел сохранённым.

    known_slugs — слаги клипов, которые есть в проекте СЕЙЧАС. Экспозиция в
    выборе заменяется целиком, поэтому payload со старой витрины (сцены
    переименованы или клипы переехали) молча откатывал бы день. 25.09.2026 на
    YTEVO03 26 клипов вечера переехали из 08 в 11; витрина осталась от 23.09, и
    сохранение из неё вернуло бы ключи 08_* — а раскладка потом отказала бы этим
    26 клипам «нет экспозиции», на шаг позже и в другом месте. Поэтому: payload
    обязан покрывать ровно текущие клипы, иначе — отказ с перечнем.
    """
    if not isinstance(fb, dict):
        raise BadFeedback("payload не словарь")
    t = fb.get("type")
    if t != "lut_board":
        raise BadFeedback(
            f"чужой payload: type={t!r}, ожидался 'lut_board'. Похоже на выгрузку "
            f"старой витрины — она не несёт ни проявки, ни look, ни экспозиции")
    proj = fb.get("project")
    if proj and str(proj) != str(code):
        raise BadFeedback(
            f"payload от другого проекта: {proj!r}, а сохраняем в {code!r}")
    if not (fb.get("exposure") or fb.get("develop") or fb.get("look")):
        raise BadFeedback("в payload нет ни экспозиции, ни проявки, ни look — "
                          "сохранять нечего")
    if known_slugs is not None and fb.get("exposure"):
        # Отказ — только на клипы, которых в проекте НЕТ: это и есть тихий откат
        # (старые имена). Клип проекта, которого нет в выборе, не опасен молча:
        # снятый в Rec.709 его и не должен иметь, а новый клип раскладка сама
        # отвергнет вслух («в выборе нет экспозиции»).
        stale = sorted(set(fb["exposure"]) - set(known_slugs))
        if stale:
            raise BadFeedback(
                "выбор скопирован со СТАРОЙ витрины — "
                f"{len(stale)} клип(ов) из выбора в проекте нет: "
                + ", ".join(stale[:4]) + (" …" if len(stale) > 4 else "")
                + ". Ничего не сохранено: пересобери витрину (lut_board.py --project …) "
                  "и скопируй выбор заново")


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


# ─────────────────────────────────────────────────────────────────────────────
# ДНК канала: читаем обратно то, что записал save_choice
# ─────────────────────────────────────────────────────────────────────────────

class DevelopUnknown(Exception):
    """Проявку вывести не удалось. Отказ, а не догадка.

    ⚠️ Именно снисходительность «гамма не совпала — ставим флаг mismatch и едем
    дальше» покрасила 61 клип DJI из 163 чужой математикой. Клип без проявки
    обязан остановить прогон и назваться по имени.
    """


def load_profile(project: Path, code: str) -> dict:
    """ДНК канала. Пустой словарь — профиля ещё нет (первый день канала)."""
    return load_json_safe(profile_path(project, code)) or {}


def resolve_develop(profile: dict, gamma, camera_role: str = ""):
    """(id проявки, откуда) по гамме клипа и роли камеры.

    Порядок — от частного к общему:
      1. develop[гамма].by_camera[роль] — когда одна гамма у РАЗНЫХ тушек
         означает разные кубы;
      2. develop[гамма].lut            — обычный случай, гамма и решает;
      3. отказ.

    ⚠️ Шаг 1 не теоретический: taxonomy._body_independent прямо говорит, что у
    Sony гамма от тушки не зависит, а у DJI зависит — «Pocket 4 и Pocket 4P —
    разные кубы под одним именем D-Log». Сегодня не бьёт только потому, что под
    D-Log2 в парке одна тушка.
    """
    if not gamma:
        raise DevelopUnknown("гамма клипа не определена — проявлять нечем")
    dev = (profile or {}).get("develop") or {}
    entry = dev.get(str(gamma))
    if not entry:
        raise DevelopUnknown(
            f"в профиле канала нет проявки для гаммы {gamma}; "
            f"известны: {', '.join(sorted(dev)) or '(пусто)'}")
    by_cam = entry.get("by_camera") or {}
    if camera_role and camera_role in by_cam:
        return by_cam[camera_role], f"профиль: камера {camera_role} + гамма {gamma}"
    lut = entry.get("lut")
    if not lut:
        raise DevelopUnknown(f"в профиле у гаммы {gamma} пустое поле lut")
    return lut, f"профиль: гамма {gamma}"


def resolve_look(profile: dict):
    """Look канала. None — покраски нет, и это законный план."""
    return ((profile or {}).get("look") or {}).get("id")


# ─────────────────────────────────────────────────────────────────────────────
# Кэш гамм: чтобы система пережила размонтированную карту
# ─────────────────────────────────────────────────────────────────────────────

def gamma_cache_path(project: Path, code: str) -> Path:
    """Куда кэш ПИШЕТСЯ. Читать — через build_file: см. load_gamma_cache."""
    return lut_build_dir(project) / f"{code}_gamma_cache.json"


def load_gamma_cache(project: Path, code: str) -> dict:
    # ⚠️ Читаем с оглядкой на старый адрес: кэш заведён ровно затем, чтобы
    # пережить размонтированную карту, и потерять его на переезде — значит
    # отменить его смысл именно в тот день, когда он нужен.
    d = load_json_safe(build_file(project, f"{code}_gamma_cache.json", log=print)) or {}
    return d.get("clips") or {}


def _stat_pair(clip: Path):
    """(размер, mtime) оригинала. ⚠️ На битом симлинке stat() кидает — тогда
    (None, None), и такая запись НИКОГДА не считается устаревшей: иначе кэш
    самоуничтожается ровно в тот момент, ради которого заведён."""
    try:
        st = clip.stat()
        return st.st_size, st.st_mtime
    except OSError:
        return None, None


def gamma_cache_stale(rec: dict, clip: Path) -> bool:
    size, mtime = _stat_pair(clip)
    if size is None or rec.get("size") is None:
        return False
    if size != rec.get("size"):
        return True
    # ⚠️ Защита симметрична размеру: запись без mtime (ручная правка кэша,
    # частичная миграция схемы) раньше сравнивалась с нулём и всегда выходила
    # устаревшей — файл перезамерялся, хотя не менялся.
    if rec.get("mtime") is None:
        return False
    return abs(mtime - rec["mtime"]) > 1.0


def save_gamma_cache(project: Path, code: str, clips: dict, merge: bool = True) -> Path:
    """Записать кэш гамм. По умолчанию СЛИВАЕТ с тем, что уже лежит.

    ⚠️ Раньше словарь клался как есть, и запись целиком заменяла прошлую: стоило
    переименовать сцену — и замер по её клипам пропадал навсегда, потому что копии
    тоже не делалось. Кэш существует ровно затем, чтобы пережить недоступность
    карты; терять из него записи — отменять его смысл.
    Слияние отдаёт приоритет НОВОМУ замеру, старые ключи сохраняются.
    """
    p = gamma_cache_path(project, code)
    if merge:
        prev = load_gamma_cache(project, code)
        if prev:
            backup(p)
            merged = dict(prev)
            merged.update(clips)          # новый замер важнее старой записи
            clips = merged
    save_json_atomic(p, {
        "schema": "gamma-cache-v1",
        "_note": "Замер гаммы по каждому клипу. Пишется, когда оригинал ДОСТУПЕН; "
                 "читается, когда недоступен. ⚠️ Оригиналы в проекте бывают "
                 "симлинками на съёмную карту — без этого файла после "
                 "размонтирования гамму взять неоткуда, и слой встаёт.",
        "project": code,
        "tool": "scripts/15_color/1502_lut_pick/lut_board.py",
        "updated": now_iso(),
        "clips": clips,
    })
    return p


def seed_gamma_cache_from_lut_plan(plan: dict, keys_by_basename: dict) -> dict:
    """Разовый посев кэша из СТАРОГО {CODE}_lut_plan.json.

    Старый план — единственное место, где гаммы этого дня записаны, пока карта
    не примонтирована. Забираем их один раз, сохраняя сырую строку дословно:
    если завтра найдётся баг в нормализации, его переприменят, не поднимая карту.
    """
    out = {}
    # ⚠️ Ключи старого плана переключаются по basename, а basename не уникален
    # сам по себе: счётчик Sony сбрасывается, и одно имя файла может встретиться
    # в двух сценах. Молча отдать гамму чужой сцене = чужая проявка без единого
    # сообщения. Рядом slug_index в такой же ситуации отказывается работать —
    # здесь правило то же.
    dupes = [b for b, n in _count(k.split("/")[-1] for k in keys_by_basename.values()).items() if n > 1]
    if dupes:
        raise SlugCollision(
            "одно имя файла встречается в разных сценах, посев гамм по basename "
            f"отдал бы гамму чужому клипу: {', '.join(sorted(dupes)[:5])}")
    for pk, rec in (plan.get("clips") or {}).items():
        raw = (rec or {}).get("gamma")
        if not raw:
            continue
        canon = keys_by_basename.get(pk.split("/")[-1]) or pk
        out[canon] = {
            "gamma": _N_normalize(raw),
            "gamma_raw": raw,
            "source": "legacy_lut_plan",
            "cam": (rec or {}).get("cam") or "",
            "pix_fmt": (rec or {}).get("pix_fmt") or "",
            "size": None,
            "mtime": None,
            "measured": plan.get("generated") or "",
        }
    return out


def _N_normalize(raw):
    """normalize_gamma живёт в naming.py (канон один на слой). Импорт ленивый,
    чтобы color_plan оставался stdlib-модулем без обязательной библиотеки."""
    import sys as _sys
    lib = Path(__file__).resolve().parent.parent / "1501_lut_library"
    if str(lib) not in _sys.path:
        _sys.path.insert(0, str(lib))
    import naming as _n
    return _n.normalize_gamma(raw)
