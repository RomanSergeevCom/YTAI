#!/usr/bin/env python3
"""
lut_board.py — поступенчатая витрина выбора: исходник → проявка → проявка+look.

Зачем отдельный инструмент, а не режим подборщика. Роман выбирает ДВА решения
на канал, и оба — глазами, по реальным кадрам:
  ступень 2 — какая проявка на какую камеру (технический шаг, но у кандидатов
              разная цена по теням и светам, и цену надо видеть);
  ступень 3 — какой look, это ДНК канала.
Пока эти два не выбраны, подбирать экспозицию по клипам не на чем. Витрина
закрывает именно выбор; пер-клиповый подбор живёт в lut_pick.py и включается
после.

Кадры рендерятся ЦЕПОЧКОЙ из двух lut3d, а не через склеенный куб. Так в превью
нет ошибки композиции вообще: замер 22.09 показал, что склейка проявки с
покраской точна только для гладких look'ов (Baza — 0.98/255), а на
стилизованных разъезжается (GOLD — 54/255) и уплотнение сетки не лечит.

Usage:
  source ~/YTAI/environment/.venv_vlm/bin/activate
  python3 lut_board.py --project "/Volumes/T9-Black-RYA/YTEVO/YTEVO03_Plechko_day" \
      --frames-from ~/Desktop/YTEVO03_01_Source_Proxy --jobs 4

Читает библиотеку из 15_color/1501_lut_library/manifest.json. Ничего в проекте
не меняет, кроме своей папки кадров и своей страницы.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
LIB = HERE.parent / "1501_lut_library"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(LIB))

import lut_pick as P          # noqa: E402  — reuse the proven frame/gamma plumbing
import naming as _N           # noqa: E402
N_TAX = _N.taxonomy()

STORE = LIB / "store"
MANIFEST = LIB / "manifest.json"

BLACK = 6          # 8-bit max(RGB) at or below this is crushed to black
WHITE = 250        # at or above this is blown
MAX_DEVELOP = 6    # candidates per camera on stage 2
MAX_LOOKS = 8      # candidates on stage 3
SAMPLES_PER_CAM = 4

EXPOSURE_STOPS = (-1.0, -0.5, 0.0, 0.5, 1.0)
EXPOSURE_EXTRA = (1.5, 2.0, 2.5, 3.0, -1.5, -2.0)   # добираются ТОЛЬКО когда нужно
EXPOSURE_MAX = 3.0                                   # предел фильтра exposure в ffmpeg
TARGET_FACE_LUMA_DEFAULT = 150.0
_TARGET_NOTE = ("стартовая догадка; уточняется по ТВОЕМУ выбору — "
                "медиана яркости лиц на кадрах, которые ты отметил")

MONTHS_RU = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
             "августа", "сентября", "октября", "ноября", "декабря")


def die(msg, code=2):
    print(f"\n✗ {msg}\n", file=sys.stderr)
    sys.exit(code)


def when_ru():
    t = time.localtime()
    return (f"{t.tm_mday} {MONTHS_RU[t.tm_mon - 1]} {t.tm_year}, "
            f"{t.tm_hour:02d}:{t.tm_min:02d}")


def normalize_gamma(g: str | None) -> str | None:
    """Камеры и библиотека называют одну гамму по-разному: сайдкар Sony отдаёт
    's-log3-cine', манифест хранит 'S-Log3'. Сводим к одному ключу."""
    if not g:
        return None
    s = re.sub(r"[^a-z0-9]", "", g.lower())
    for key, norm in (("slog3", "S-Log3"), ("slog2", "S-Log2"),
                      ("dlog2", "D-Log2"), ("dlogm", "D-Log M"), ("dlog", "D-Log"),
                      ("vlog", "V-Log"), ("clog3", "C-Log3"), ("clog2", "C-Log2"),
                      ("applelog", "Apple Log"), ("flog2", "F-Log2"),
                      ("ilog", "I-Log"), ("rec709", "Rec.709")):
        if s.startswith(key) or key in s:
            return norm
    return g


def vf_chain_multi(luts, width=None, stops=0.0) -> str:
    """scale ДО lut3d, общий gbrp10le, дальше ступени подряд.

    Одна и та же цепочка на исходник и на варианты — иначе они несравнимы по
    яркости (обоснование и замеры: lut_pick.vf_chain).

    ⚠️ Экспозиция вставляется ПОСЛЕ ПЕРВОГО лута и ДО остальных. Это не
    произвол: порядок обработки внутри Lumetri вытащен из шаблона проекта и
    выглядит так —
        Basic Correction: LUT (проявка) → BasicCorrection3 (здесь Exposure)
        Creative:         LUT (покраска)
    то есть экспозиция живёт ровно между проявкой и покраской. Превью обязано
    повторять этот порядок, иначе оно врёт про результат в Premiere.
    """
    base = f"scale={width or P.FRAME_WIDTH}:-2:flags=bicubic,format=gbrp10le"
    for i, lut in enumerate(luts):
        if lut:
            base += f",lut3d=file='{P.lut_arg(lut)}':interp=tetrahedral"
        if i == 0 and abs(stops) > 1e-6:
            base += f",exposure=exposure={stops:.3f}"
    return base


def frame_ok(path: Path, min_w: int = 100) -> bool:
    """Кадр цел? Сигнатура + размеры + ПОЛНОЕ декодирование.

    ⚠️ Не по весу файла. Порог lut_pick.jpeg_ok в 4 КБ откалиброван под кадры
    960 px, а на пробных 320 px нормальный кадр весит 1.2-1.5 КБ: вес JPEG
    зависит от ДЕТАЛЬНОСТИ, а не от целости. Замер: тёмный интерьер храма —
    1234 байта при luma 17, ровная светлая стена — 1504 байта при luma 161.
    Оба кадра идеальны, а порог по весу забраковал шесть таких из 163.
    im.load() поднимает исключение на оборванном файле независимо от размера —
    это и есть настоящая проверка.
    """
    try:
        if path.stat().st_size < 300:
            return False
        with open(path, "rb") as fh:
            if fh.read(2) != b"\xff\xd8":
                return False
        with Image.open(path) as im:
            if im.width < min_w or im.height < 40:
                return False
            im.load()
        return True
    except Exception:
        return False


def extract(video, tc, out_jpg, luts=(), width=None, stops=0.0):
    if frame_ok(out_jpg, (width or P.FRAME_WIDTH) // 2):
        return True
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    P.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error",
           "-ss", f"{tc:.3f}", "-i", str(video), "-an",
           "-vf", vf_chain_multi(luts, width, stops), "-frames:v", "1", "-q:v", "3",
           str(out_jpg)], timeout=180)
    return frame_ok(out_jpg, (width or P.FRAME_WIDTH) // 2)


PROBE_W = 320
PERCLIP_W = 640      # ширина кадра в сетке «по каждому клипу»
READABLE_LUMA = 30   # ниже этого в логе кадр нечитаем — решения по нему не принять


def probe_developed(by_cam, cam_info, source, mirror, probe_dir, jobs_n):
    """Проход 1: крошечный кадр с КАЖДОГО клипа, снятый ЧЕРЕЗ ведущую проявку.

    Отдаёт сразу две вещи, и обе нужны разным ступеням:
      luma — чтобы ступень 2 (проявка) смотрела на ТЁМНЫЕ сцены, где кубы и
             расходятся: на светлом кадре любой выглядит прилично;
      face — чтобы ступень 3 (экспозиция) смотрела на кадры С ЛИЦОМ, потому что
             меряем мы по лицу.

    ⚠️ Проход идёт через проявку, а не по логу, и это принципиально. На плоском
    логарифмическом кадре Vision лицо почти не находит, а пороги яркости не
    значат ничего. Замер: на проявленных кадрах дня лицо находится, на тех же
    тёмных сценах без проявки — нет.

    320 px и q=3 — около 10 КБ на кадр, секунды на весь съёмочный день.
    """
    probe_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for cam, items in by_cam.items():
        devs = (cam_info.get(cam) or {}).get("develops") or []
        lead = STORE / devs[0]["file"] if devs else None
        for scene, clip in items:
            video, _ = P.frame_src(clip, source, mirror)
            dur = P.ffprobe_duration(video) or 4.0
            tc = max(0.0, min(dur * 0.5, dur - 0.05))
            # ⚠️ Имя несёт ПРОЯВКУ. Без неё проб-кадры переживают смену
            # рекомендации и остаются от прошлого прогона — а в самом первом
            # прогоне гамма ещё не определялась и лут не применялся вовсе.
            # Тогда и поиск лиц, и вся экспозиция по 163 клипам считались бы по
            # ЛОГАРИФМИЧЕСКИМ кадрам, где эти метрики ничего не значат.
            devtag = devs[0]["id"] if devs else "nodev"
            out = probe_dir / (re.sub(r"[^A-Za-z0-9]+", "_", f"{scene}_{clip.stem}")
                               + f"__{devtag}.jpg")
            tasks.append((video, tc, out, (lead,) if lead else (), clip.name))
    with ThreadPoolExecutor(max_workers=jobs_n) as ex:
        list(ex.map(lambda t: extract(t[0], t[1], t[2], t[3], PROBE_W), tasks))
    want = {t[2].name for t in tasks}
    for q in probe_dir.glob("*.jpg"):
        if q.name not in want:
            q.unlink()
    out = {}
    for _, _, jpg, _, name in tasks:
        if not frame_ok(jpg, PROBE_W // 2):
            continue
        a = np.asarray(Image.open(jpg).convert("RGB"), dtype=np.float64)
        bbox = P.detect_face(jpg)
        # Яркость по лицу — та же величина, что решает на ступени 3, только
        # посчитанная для ВСЕХ клипов дня, а не для двенадцати в витрине.
        fm = P.face_metrics(a, bbox, core=P.FACE_CORE) if bbox else None
        mx = a.max(-1)
        out[name] = {"luma": float((a * (0.2126, 0.7152, 0.0722)).sum(-1).mean()),
                     "face": bbox is not None,
                     "face_luma": float(fm["luma"]) if fm else None,
                     "clip": float(fm["clip"]) if fm else None,
                     # метрики ВСЕГО кадра: эталон для покраски обязан быть цел
                     # не только по лицу — выбитое небо за спиной убивает
                     # карточку так же, как чёрный кадр
                     "frame_clip": float((mx >= WHITE).mean()),
                     "frame_black": float((mx <= BLACK).mean())}
    return out


def pick_face_samples(by_cam, per_cam, probe):
    """Выборка для ступени 3: только клипы, где лицо НАЙДЕНО, размазанные по яркости.

    Ступени 2 и 3 не могут жить на одной выборке. Проявку решают тёмные кадры,
    экспозицию — кадры с лицом, а это почти непересекающиеся множества: на
    YTEVO03 самые тёмные клипы (luma 17-39) лиц не содержат вовсе.
    """
    out = {}
    for cam, items in by_cam.items():
        withface = [it for it in items if (probe.get(it[1].name) or {}).get("face")]
        if not withface:
            continue
        withface.sort(key=lambda it: probe[it[1].name]["luma"])
        k = min(per_cam, len(withface))
        idx = np.linspace(0, len(withface) - 1, k)
        out[cam] = [withface[int(round(i))] for i in idx]
    return out


def metrics(jpg: Path) -> dict:
    """Числа, по которым видно цену кандидата. Те же, что доказали себя на
    замере 22.09: зажатые тени отличают проявки друг от друга сильнее всего."""
    a = np.asarray(Image.open(jpg).convert("RGB"), dtype=np.float64)
    mx, mn = a.max(-1), a.min(-1)
    lit = mx >= 16                      # ниже насыщенность — шум, не цвет
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    return {
        "luma": float((a * (0.2126, 0.7152, 0.0722)).sum(-1).mean()),
        "sat": float(sat[lit].mean() * 100) if lit.any() else 0.0,
        "black": float((mx <= BLACK).mean() * 100),
        "clip": float((mx >= WHITE).mean() * 100),
    }


def stop_tag(st: float) -> str:
    """Имя файла для ступени экспозиции: expm10 / expm05 / exp00 / expp05 / expp10."""
    sign = "m" if st < -1e-6 else ("p" if st > 1e-6 else "")
    return f"exp{sign}{abs(st)*10:02.0f}"


def face_measure(jpg: Path, bbox=None) -> dict:
    """Яркость по ЛИЦУ на ПРОЯВЛЕННОМ кадре — иначе пороги бессмысленны.

    На логарифмическом кадре «кожа на ключе ≈ 150» не значит ничего: лог кодирует
    18 % серого около 0.41. Мерить экспозицию можно только после проявки, когда
    картинка уже в Rec.709.

    bbox передаётся снаружи, чтобы все ступени лестницы мерились по ОДНОМУ И ТОМУ
    ЖЕ прямоугольнику: Vision на пере- и недодержанном кадре находит лицо чуть
    иначе, и тогда «разница в стопах» смешивается с разницей в рамке.
    """
    rgb = np.asarray(Image.open(jpg).convert("RGB"), dtype=np.float64)
    if bbox is None:
        bbox = P.detect_face(jpg)
    roi = "face" if bbox else "frame"
    if bbox is None:
        bbox = (0, 0, rgb.shape[1], rgb.shape[0])
    m = P.face_metrics(rgb, bbox, core=P.FACE_CORE if roi == "face" else 1.0)
    if m is None:
        m = {"luma": 0.0, "sat": 0.0, "lit": 0.0, "clip": 0.0}
    m["roi"] = roi
    return m


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
    return float(np.clip(np.log2(target / luma), -3.0, 3.0))


# ───────────────────────────────────────────────── выбор кандидатов ──

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
    idx = np.linspace(0, len(pool) - 1, limit).round().astype(int)
    return [pool[i] for i in sorted(set(idx))]


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


# ───────────────────────────────────────────────────────── сбор ──

def all_clips_by_cam(source: Path) -> dict:
    by_cam: dict[str, list] = {}
    scenes = sorted(d for d in source.iterdir()
                    if d.is_dir() and re.match(r"^\d\d_", d.name)
                    and not d.name.startswith("00_"))
    for sdir in scenes:
        for clip in P.scene_clips(sdir):
            by_cam.setdefault(P.cam_of(clip, source), []).append((sdir.name, clip))
    return by_cam


def pick_samples(by_cam: dict, per_cam: int, luma: dict | None = None):
    """По несколько клипов на камеру — СМЕЩЁННЫЕ В ТЁМНОЕ, а не размазанные ровно.

    ⚠️ Это не придирка. Первый прогон витрины брал клипы равномерно по дню и
    показал у всех проявок Sony ровно 0,00 % зажатого чёрного — то есть разницы
    как будто нет. На полной выборке из 132 кадров та же `Neutral` зажимала тени
    на 32 кадрах. Равномерная выборка просто не попала в тёмные сцены, а проявки
    различаются именно там: в светлом кадре любая из них выглядит прилично.

    Поэтому: две самых тёмных сцены, медиана и одна светлая. Светлая нужна, чтобы
    было видно и обратную цену — пережог.
    """
    out = {}
    for cam, items in by_cam.items():
        if not items:
            continue
        k = min(per_cam, len(items))
        if luma:
            # ⚠️ Тёмные — да, чёрные — нет. Первый заход брал абсолютно самые
            # тёмные клипы, и кадры DJI выходили с luma 9-10: на таком кадре
            # решения не принять, видно только чёрный прямоугольник. Поэтому
            # сначала отсекаем нечитаемое, и уже среди оставшегося берём тёмное.
            readable = [it for it in items
                        if luma.get(it[1].name, 0.0) >= READABLE_LUMA]
            ranked = sorted(readable or items,
                            key=lambda it: luma.get(it[1].name, 999.0))
            picked, seen = [], set()
            order = ([0, 1] +                                   # самые тёмные
                     [len(ranked) // 2] +                       # медиана
                     [len(ranked) - 1] +                        # самая светлая
                     list(range(2, len(ranked))))               # добор по темноте
            for i in order:
                if len(picked) >= k:
                    break
                if 0 <= i < len(ranked) and i not in seen:
                    seen.add(i)
                    picked.append(ranked[i])
            out[cam] = picked
        else:
            idx = np.linspace(0, len(items) - 1, k)
            out[cam] = [items[int(round(i))] for i in idx]
    return out


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


def load_recorded_gammas(project: Path, code: str) -> dict:
    """Гаммы, записанные прошлым прогоном подборщика, — `clips[*].gamma` в плане.

    ⚠️ Нужно потому, что оригиналы в проекте могут быть симлинками на съёмную
    карту: на YTEVO03 все 163 клипа И все 108 сайдкаров M01.XML ведут на
    /Volumes/SD-V90-RYA, и пока карта не примонтирована, измерить гамму нечем.
    Запись в плане — тот же самый замер с карты, просто сделанный раньше
    (21.09.2026), а не догадка по имени камеры.
    """
    plan = project / "00_Setup" / "01_Ingest" / f"{code}_lut_plan.json"
    try:
        doc = json.loads(plan.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    out = {}
    for key, rec in (doc.get("clips") or {}).items():
        if rec.get("gamma"):
            out[key.split("/")[-1]] = (rec["gamma"], doc.get("generated", "")[:10])
    return out


def detect_gamma(clip: Path, cam: str, recorded: dict | None = None):
    """Гамма ТОЛЬКО из измеренных метаданных. Никаких догадок по имени камеры:
    ровно эта догадка и покрасила 61 клип DJI чужой математикой.

    Порядок источников по свежести, а не по удобству: живой сайдкар → живой тег
    контейнера → запись прошлого замера. Источник всегда возвращается наружу и
    печатается в витрине, чтобы «откуда мы это знаем» было видно глазом.
    """
    if clip.exists():
        g = P.sony_gamma(clip)
        if g:
            return normalize_gamma(g), "сайдкар M01.XML"
        g = P.dji_gamma(clip)
        if g:
            return normalize_gamma(g), "тег com.dji.camera.ColorGammaSxS"
    rec = (recorded or {}).get(clip.name)
    if rec:
        return normalize_gamma(rec[0]), f"замер {rec[1]}, оригинал сейчас недоступен"
    return None, ("оригинал недоступен и в плане записи нет"
                  if not clip.exists() else "не определена")


# ───────────────────────────────────────────────────────── витрина ──

FAVICON = ("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20"
           "viewBox='0%200%20100%20100'%3E%3Ctext%20y='.9em'%20font-size='88'%3E"
           "%F0%9F%AA%9C%3C/text%3E%3C/svg%3E")

CSS = """
:root{--bg:#0d0f14;--card:#151922;--line:#232938;--tx:#e8ecf4;--dim:#8b94a8;
      --acc:#c8f04a;--warn:#ffb454;--bad:#ff6b6b;--ok:#5ad19a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
     font:15px/1.5 -apple-system,'Inter',system-ui,sans-serif}
.wrap{max-width:1680px;margin:0 auto;padding:22px 20px 80px}
h1{font:800 26px/1.2 'Space Grotesk','Inter',sans-serif;margin:0 0 6px}
.ver{display:inline-block;margin-left:10px;padding:3px 9px;border-radius:6px;
     background:var(--acc);color:#0d0f14;font:700 12px ui-monospace,monospace;vertical-align:middle}
.sub{color:var(--dim);margin:0 0 14px;max-width:1100px}
.kpi{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px}
.kpi b{background:var(--card);border:1px solid var(--line);border-radius:8px;
       padding:6px 11px;font:600 12.5px ui-monospace,monospace;color:var(--dim)}
.kpi b i{font-style:normal;color:var(--tx)}
.built{background:#141821;border:1px solid var(--line);border-left:3px solid var(--acc);
       border-radius:10px;padding:11px 15px;margin:0 0 14px;font-size:13.5px;color:var(--dim)}
.built b{color:var(--tx)}
/* Сводка решения по камере — карточка, а не тревожная рамка. */
.sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px;
     margin:0 0 20px}
.sumc{background:#141821;border:1px solid var(--line);border-radius:12px;padding:13px 15px}
.sumc .cam{font:700 14px 'Inter',sans-serif;color:var(--tx)}
.sumc .gam{font:500 11.5px ui-monospace,monospace;color:var(--dim);margin-left:8px}
.sumc .opt{display:flex;align-items:center;gap:9px;margin-top:9px;
           font:500 12px ui-monospace,monospace;color:var(--dim)}
.sumc .opt .nm{flex:1;color:var(--dim)}
.sumc .opt.on .nm{color:var(--acc);font-weight:700}
/* Полоску убрал: при двух кандидатах она ничего не добавляет к числу, а на
   тёмном фоне теряется. Цену показывает само число — зелёным когда даром,
   красным когда куб платит тенями. */
.sumc .cost{flex:0 0 132px;white-space:nowrap;text-align:right;color:var(--ok);font-weight:600}
.sumc .cost.bad{color:var(--bad)}
.sumc .hdr{display:flex;gap:9px;margin-top:11px;padding-bottom:5px;
           border-bottom:1px solid var(--line);
           font:600 10.5px ui-monospace,monospace;color:#6b7488;
           text-transform:uppercase;letter-spacing:.04em}
.sumc .hdr .a{flex:1}
.sumc .hdr .b{flex:0 0 132px;text-align:right}
.sumc .tail{margin-top:9px;font:500 11.5px/1.5 ui-monospace,monospace;color:var(--dim)}
.sumc .opt.on .nm:after{content:' — выбран';color:var(--acc);font-weight:700}
.sumc .val{flex:0 0 60px;text-align:right}
.sumc .tick{flex:0 0 14px;color:var(--acc)}
/* Плашка «что выбрано сейчас» — одно место, где видно всё решение целиком. */
.now{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:10px;
     background:#141821;border:1px solid var(--line);border-radius:12px;
     padding:14px 16px;margin:0 0 16px}
.now .t{font:600 11px ui-monospace,monospace;color:var(--dim);text-transform:uppercase;
        letter-spacing:.05em}
.now .v{font:700 14px 'Inter',sans-serif;color:var(--acc);margin-top:4px;word-break:break-word}
.now .s{font:500 11.5px ui-monospace,monospace;color:var(--dim);margin-top:2px}
.sec{background:var(--card);border:1px solid var(--line);border-radius:14px;
     padding:18px 18px 8px;margin:0 0 18px}
.sec h2{font:700 18px/1.3 'Space Grotesk','Inter',sans-serif;margin:0 0 4px}
.sec h2 .ic{margin-right:8px}
.sec .why{color:var(--dim);font-size:13.5px;margin:0 0 14px;max-width:1100px}
.camttl{font:700 14px ui-monospace,monospace;color:var(--acc);margin:16px 0 4px}
.gam{color:var(--dim);font:500 12.5px ui-monospace,monospace;margin:0 0 10px}
.row{display:flex;gap:10px;overflow-x:auto;padding-bottom:8px;
     /* 1110 картинок на одной file:// странице: без этого браузер считает
        раскладку для всех сразу и прокрутка дёргается. */
     content-visibility:auto;contain-intrinsic-size:170px 1400px}
.cell{flex:0 0 300px}
.cell img{display:block;width:300px;height:169px;object-fit:cover;border-radius:8px;
          border:3px solid transparent;background:#000}
.cell.base img{border-color:var(--line)}
.cell.sel img{border-color:var(--acc);box-shadow:0 0 0 3px rgba(200,240,74,.25)}
.cell.sel .nm:after{content:' ✓ выбран';color:var(--acc);font-weight:700}
.nav{position:sticky;top:0;z-index:8;background:rgba(13,15,20,.94);
     backdrop-filter:blur(8px);display:flex;gap:8px;padding:10px 0 12px;margin:0 0 14px;
     border-bottom:1px solid var(--line)}
.nav a{flex:1;text-align:center;padding:12px 10px;border-radius:10px;
       background:var(--card);border:1px solid var(--line);color:var(--tx);
       text-decoration:none;font:700 14px 'Inter',sans-serif}
.nav a:hover{border-color:var(--acc)}
.nav a b{display:block;font:600 11.5px ui-monospace,monospace;color:var(--dim);
         margin-top:3px}
details.more{margin:0 0 14px}
details.more summary{cursor:pointer;color:var(--dim);font-size:13px;
                     padding:6px 0;list-style:none}
details.more summary::-webkit-details-marker{display:none}
details.more summary:before{content:'▸ ';color:var(--acc)}
details.more[open] summary:before{content:'▾ '}
details.more .why{margin-top:8px}
.lookgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.lookgrid .cell{flex:none}
.lookgrid .cell img{width:100%;height:auto;aspect-ratio:16/9}
.cell .nm{font:600 11.5px ui-monospace,monospace;margin:5px 0 2px;
          white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cell .m{font:500 10.5px ui-monospace,monospace;color:var(--dim);line-height:1.45}
.cell .m .bad{color:var(--bad)}
.cell .m .ok{color:var(--ok)}
.cell.pick{cursor:pointer}
.cell.pick:hover img{border-color:var(--dim)}
.lbl{font:600 11px ui-monospace,monospace;color:var(--dim);margin:0 0 4px}
.arrow{flex:0 0 18px;align-self:center;color:var(--dim);font-size:18px}
.bar{position:fixed;left:0;right:0;bottom:0;background:#11141c;
     border-top:1px solid var(--line);padding:11px 20px;display:flex;
     gap:14px;align-items:center;z-index:9}
.bar button{background:var(--acc);color:#0d0f14;border:0;border-radius:8px;
            padding:9px 16px;font:700 13px 'Inter',sans-serif;cursor:pointer}
.bar .st{color:var(--dim);font:600 12.5px ui-monospace,monospace}
.foot{color:var(--dim);font-size:12.5px;margin-top:22px;line-height:1.7}
pre.p{background:#11141c;border:1px solid var(--line);border-radius:8px;
      padding:10px 12px;overflow-x:auto;font:500 11.5px ui-monospace,monospace;color:var(--dim)}
@media(max-width:760px){.wrap{padding:16px}.cell,.cell img{flex-basis:200px;width:200px}}
"""


def short_name(lut_id: str) -> str:
    """Читаемая подпись под кадром. Полный id — для манифеста, не для глаза:
    «sony__slog3_sgamut3cine__rec709__neutral__legacy» ни о чём не говорит,
    а «neutral legacy» говорит всё."""
    if lut_id.startswith("look__"):
        return lut_id[6:].replace("_", " ")
    parts = [b for b in lut_id.split("__") if b not in ("rec709",)]
    return " ".join(parts[2:]).replace("_", " ") or " ".join(parts).replace("_", " ")


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def cell_html(rel, name, m, base_m, kind, lut_id="", cam=""):
    """Одна ячейка витрины. Числа всегда под кадром — решение принимается по ним
    вместе с картинкой, а не вместо неё."""
    def col(v, warn, good_low=True):
        bad = (v > warn) if good_low else (v < warn)
        return f'<span class="{"bad" if bad else "ok"}">{v:.1f}</span>'
    if base_m is None:
        mm = (f'luma {m["luma"]:.0f} · нас {m["sat"]:.0f}% · '
              f'чёрн {m["black"]:.1f}% · переж {m["clip"]:.1f}%')
    else:
        mm = (f'luma {m["luma"]:.0f} · нас {m["sat"]:.0f}%<br>'
              f'чёрн {col(m["black"], 1.0)}% · переж {col(m["clip"], 2.0)}%')
    cls = "cell " + ("base" if kind == "base" else "pick")
    attr = f' data-lut="{esc(lut_id)}"' if lut_id else ""
    if cam:
        # Камера едет в самой ячейке: одна и та же проявка предлагается обеим
        # камерам Sony (у них общая гамма), и выбор должен относиться к той
        # строке, по которой кликнули, а не к последней в общей карте.
        attr += f' data-cam="{esc(cam)}"'
    return (f'<div class="{cls}"{attr}>'
            f'<img loading="lazy" decoding="async" width="232" height="130" '
            f'src="{esc(rel)}" alt="{esc(name)}">'
            f'<div class="nm" title="{esc(name)}">{esc(name)}</div>'
            f'<div class="m">{mm}</div></div>')


def build_html(ctx) -> str:
    v = ctx["version"]
    title = f"{ctx['code']} · луты по ступеням · v{v}"
    h = [f"<!DOCTYPE html><html lang=ru><head><meta charset=utf-8>",
         f"<meta name=viewport content='width=device-width,initial-scale=1'>",
         f"<link rel=icon href=\"{FAVICON}\">",
         f"<title>{esc(title)}</title><style>{CSS}</style></head><body><div class=wrap>"]

    h.append(f"<h1>{esc(ctx['code'])} — луты по ступеням<span class=ver>v{v}</span></h1>")
    h.append("<p class=sub>Три решения. Первые два — один раз на канал, третье — "
             "по каждому клипу. " + (
                 "Проставлен <b>твой сохранённый выбор</b> — правь, он "
                 "подхватится автоматически." if ctx.get("from_saved") else
                 "Мой выбор уже проставлен, правь что не нравится.") +
             " Выбор сохраняется в браузере сам, вкладку можно закрыть.</p>")

    k = ctx["kpi"]
    h.append("<div class=kpi>" + "".join(
        f"<b>{esc(a)} <i>{esc(bb)}</i></b>" for a, bb in k) + "</div>")

    nowc = []
    for camx in ctx["cams"]:
        if not camx["develops"]:
            continue
        cur = ctx.get("rec_dev", {}).get(camx["cam"])
        best = next((d for d in camx["develops"] if d["id"] == cur), camx["develops"][0])
        nowc.append((camx["cam"], short_name(best["id"]),
                     f'{camx["gamma"]} · съедает '
                     f'{best["metrics"].get("black_share", 0)*100:.1f} % теней'))
    nowc.append(("покраска канала", short_name(ctx["rec_look"] or "—"),
                 f'{len(ctx["look_rows"] and ctx["look_rows"][0]["looks"] or [])} кандидатов показано'))
    nowc.append(("цель по лицу", f'{ctx["target"]:.0f}', esc(ctx["target_src"])))
    h.append('<div class=now>' + "".join(
        f'<div><div class=t>{esc(a)}</div><div class=v>{esc(b)}</div>'
        f'<div class=s>{esc(c)}</div></div>' for a, b, c in nowc) + '</div>')

    h.append('<div class=nav>'
             '<a href="#s1">1 · Проявка<b>один выбор на камеру</b></a>'
             '<a href="#s2">2 · Покраска<b>один выбор на канал</b></a>'
             f'<a href="#s3">3 · Экспозиция<b>{len(ctx["per_clip"])} клипов</b></a>'
             '</div>')

    h.append('<details class=more><summary>Как это устроено и почему так</summary>'
             '<p class=why>Внутри Lumetri картинка идёт '
             '<b>проявка → экспозиция → покраска</b> — это порядок обработки, '
             'вытащенный из твоего же шаблона проекта. Решения принимаются в '
             'другом порядке: сначала две настройки на весь канал, и только '
             'потом экспозиция по каждому клипу под ними. Выбирать экспозицию, '
             'не зная look, бессмысленно — он сдвигает яркость.<br><br>'
             'Кадры собраны <b>цепочкой из двух lut3d</b>, а не через склеенный '
             'куб: в превью ошибки склейки нет вообще. Склейка в один куб точна '
             'не для всякого look (замер 22.09: Baza 0,98/255, GOLD 54/255), и '
             'вопрос о ней решается после пробы Input LUT в Premiere.</p></details>')

    # ── ступень 2: проявка
    h.append('<div class=sec id=s1><h2><span class=ic>🎞</span>Решение 1 · '
             'Проявка — один выбор на камеру</h2>')
    h.append('<p class=why>Возвращает лог в нормальную картинку. Определяется '
             '<b>камерой</b>, а не вкусом: выбрал один раз — живёт в профиле '
             'канала. <b>Здесь нечего править по клипам.</b> Победитель по '
             'числам отмечен ✓, клик по любому кадру меняет выбор для всей '
             'камеры.</p>')
    h.append('<details class=more><summary>Почему кадры такие тёмные</summary>'
             '<p class=why>Специально: проявки различаются именно на тёмных '
             'сценах, на светлом кадре любая выглядит прилично. Число '
             '<b>чёрн</b> — сколько процентов кадра куб утопил в чистый чёрный. '
             'Эту деталь не вернуть ничем. Исходники дня проверены: в них '
             '0,00 % чистого чёрного, значит всё зажатое создал именно лут.</p>'
             '</details>')
    h.append('<div class=sum>')
    for camx in ctx["cams"]:
        if not camx["develops"]:
            continue
        cur = ctx.get("rec_dev", {}).get(camx["cam"])
        best_bs = min((d["metrics"].get("black_share", 0) for d in camx["develops"]),
                      default=0.0)
        h.append(f'<div class=sumc><span class=cam>{esc(camx["cam"])}</span>'
                 f'<span class=gam>{esc(camx["gamma"] or "?")}</span>'
                 f'<div class=hdr><span class=a>кандидат проявки</span>'
                 f'<span class=b>съедает теней</span></div>')
        for d in camx["develops"]:
            bs = d["metrics"].get("black_share", 0.0)
            on = (d["id"] == cur)
            # полоска — доля зажатых теней относительно худшего кандидата,
            # чтобы цена выбора читалась без чтения цифр
            # Красным — то, что ХУЖЕ лучшего доступного, а не то, что просто
            # не ноль. У DJI даже лучший куб зажимает 6.2 %, и красить его
            # тревожным значило бы ругать выбор, которому нет альтернативы.
            costly = bs > best_bs + 0.01
            h.append(f'<div class="opt{" on" if on else ""}">'
                     f'<span class=tick>{"✓" if on else ""}</span>'
                     f'<span class=nm>{esc(short_name(d["id"]))}</span>'
                     f'<span class="cost{" bad" if costly else ""}">'
                     f'{bs*100:.1f} % в чёрное</span></div>')
        fams = {(d.get("family") or "") for d in camx["develops"]}
        has_legacy = any("legacy" in (d.get("variant") or "") for d in camx["develops"])
        tail = ("Это один и тот же лут в двух вариантах автора: "
                "<b>legacy</b> — более контрастный." if has_legacy and len(fams) == 1
                else "<b>plus</b> и <b>minus</b> — два варианта автора под эту камеру.")
        h.append(f'<div class=tail>{tail} Число — сколько кадра лут утапливает в '
                 f'чистый чёрный: эту деталь не вернуть ничем.</div>')
        h.append('</div>')
    h.append('</div>')
    for cam in ctx["cams"]:
        h.append(f'<div class=camttl>{esc(cam["cam"] or "без камеры")}</div>')
        h.append(f'<div class=gam>гамма {esc(cam["gamma"] or "НЕ ОПРЕДЕЛЕНА")} '
                 f'· источник: {esc(cam["gamma_src"])} · кандидатов '
                 f'{len(cam["develops"])}</div>')
        if not cam["develops"]:
            h.append('<p class=why style="color:var(--bad)">В библиотеке нет проявки '
                     'под эту гамму. Прогон по такому клипу должен падать, а не '
                     'красить чужой математикой.</p>')
        for s in cam["samples"]:
            h.append(f'<div class=lbl>{esc(s["label"])}</div><div class=row>')
            h.append(cell_html(s["orig_rel"], "исходник (лог)", s["orig_m"], None, "base"))
            h.append('<div class=arrow>→</div>')
            for d in s["dev"]:
                h.append(cell_html(d["rel"], short_name(d["id"]), d["m"],
                                   s["orig_m"], "pick", d["id"], d.get("cam", "")))
            h.append("</div>")
    h.append("</div>")

    # ── решение 2: покраска, крупными карточками
    h.append('<div class=sec id=s2><h2><span class=ic>🎨</span>Решение 2 · '
             'Покраска — один выбор на канал</h2>')
    h.append(f'<div class=built>Сейчас выбрано: '
             f'<b>{esc(short_name(ctx["rec_look"] or "—"))}</b>. '
             f'Поверх проявки <b>{esc(short_name(ctx["look_base_name"]))}</b>. '
             f'Кандидатов в коллекции — <b>{len(ctx["look_rows"][0]["looks"]) if ctx["look_rows"] else 0}</b>, '
             f'показаны все.</div>')
    h.append(f'<p class=why>Характер канала. Кладётся поверх проявки '
             f'(<code>{esc(short_name(ctx["look_base_name"]))}</code>), поэтому '
             f'разница между карточками — это ровно покраска. '
             f'<b>Кликни по той, что нравится.</b> Кадры взяты нормально снятые, '
             f'не тёмные — покраску на чёрном кадре не выбрать.<br>'
             f'Первая карточка — <b>без покраски</b>, база сравнения. '
             f'Перечёркнутые числа значат, что look режет картинку.</p>')
    for s_row in ctx["look_rows"]:
        h.append(f'<div class=lbl>{esc(s_row["label"])}</div><div class=lookgrid>')
        bm = s_row["base_m"]
        h.append(f'<div class="cell base"><img loading="lazy" decoding="async" '
                 f'src="{esc(s_row["base_rel"])}" alt="без покраски">'
                 f'<div class="nm">без покраски</div>'
                 f'<div class="m">нас {bm["sat"]:.0f}% · пережог {bm["clip"]:.1f}%</div>'
                 f'</div>')
        for lk in s_row["looks"]:
            m = lk["m"]
            harm = m["clip"] > 2.0 or m["black"] > 1.0
            warn = (f'<span class="bad">режет: пережог {m["clip"]:.1f}% · '
                    f'чёрное {m["black"]:.1f}%</span>' if harm else
                    f'нас {m["sat"]:.0f}% · чисто')
            h.append(f'<div class="cell pick" data-lut="{esc(lk["id"])}">'
                     f'<img loading="lazy" decoding="async" '
                     f'src="{esc(lk["rel"])}" alt="{esc(lk["name"])}">'
                     f'<div class="nm">{esc(short_name(lk["id"]))}</div>'
                     f'<div class="m">{warn}</div></div>')
        h.append('</div>')
    h.append('</div>')

    # ── покрытие: все клипы дня
    cov = ctx["coverage"]
    from collections import Counter
    by_state = Counter(c["state"] for c in cov)
    by_stop = Counter(f'{c["stop"]:+.1f}' for c in cov if c.get("stop") is not None)
    h.append('<div class=sec><h2><span class=ic>📋</span>Покрытие — все '
             f'{len(cov)} клипов дня</h2>')
    h.append('<p class=why>Витрина выше учит цель на двенадцати клипах: '
             'прокликать весь день, чтобы выразить вкус, невозможно. '
             'Применяется цель ко <b>всем</b> — вот что машина предложит каждому '
             'клипу при нынешней цели. Кадры для этого уже сняты проб-проходом, '
             'считать заново нечего.</p>')
    h.append('<div class=kpi>' + "".join(
        f'<b>{esc(k)} <i>{v}</i></b>' for k, v in by_state.most_common()) + '</div>')
    h.append('<div class=kpi>' + "".join(
        f'<b>ступень {esc(k)} <i>{v} клипов</i></b>'
        for k, v in sorted(by_stop.items())) + '</div>')
    moved = [c for c in cov if c.get("stop") not in (None, 0.0)]
    if moved:
        h.append('<p class=why>Клипы, которым машина двигает экспозицию '
                 f'({len(moved)} из {len(cov)}):</p><pre class=p>')
        for c in sorted(moved, key=lambda c: -abs(c.get("miss") or 0))[:40]:
            h.append(f'{c["stop"]:+.1f}  лицо {c.get("luma", 0):5.0f}  '
                     f'промах {c.get("miss", 0):+5.2f}  {esc(c["scene"])}/{esc(c["clip"])}')
        if len(moved) > 40:
            h.append(f'… и ещё {len(moved)-40}')
        h.append('</pre>')

    # ── сетка по каждому клипу
    _dev_line = " · ".join(f'{esc(c)} → {esc(short_name(d))}'
                           for c, d in (ctx.get("rec_dev") or {}).items() if d)
    h.append('<div class=sec id=s3><h2><span class=ic>🎬</span>Решение 3 · Экспозиция — '
             f'по каждому из {len(ctx["per_clip"])} клипов, мой выбор отмечен</h2>')
    h.append(f'<p class=why>Здесь <b>весь день</b>, а не выборка, и в каждой строке '
             f'уже стоит моё предложение — правь только то, с чем не согласен. '
             f'Кадры показывают <b>итог</b>: проявка + экспозиция + look '
             f'(<code>{esc(ctx["rec_look"] or "без look")}</code>), то есть ровно то, '
             f'что ляжет на таймлайн.<br>'
             f'Экспозицию предлагаю только там, где найдено лицо: без лица мерить '
             f'нечего, и трогать её — значит гадать. Такие клипы стоят на нуле '
             f'и помечены.</p>')
    h.append(f'<div class=built>Кадры ниже собраны под: {_dev_line} · look '
             f'<b>{esc(short_name(ctx["rec_look"] or "—"))}</b> · цель по лицу '
             f'<b>{ctx["target"]:.0f}</b>. Поменяешь проявку или look — '
             f'страницу надо пересобрать, кадры обновятся.</div>')
    for row in ctx["per_clip"]:
        tag = ''
        if not row["face"]:
            tag = ' · <span style="color:var(--dim)">лица нет, экспозиция не трогается</span>'
        elif row.get("over"):
            tag = (f' · промах {row["miss"]:+.2f} — <span style="color:var(--warn)">'
                   f'лестницы не хватает</span>')
        elif row.get("miss") is not None:
            tag = f' · промах {row["miss"]:+.2f} стопа'
        h.append(f'<div class=lbl>{esc(row["key"])} · {esc(row["cam"])}{tag}</div>')
        h.append('<div class=row>')
        h.append(f'<div class="cell base"><img loading="lazy" decoding="async" '
                 f'width="232" height="130" src="{esc(row["orig_rel"])}" alt="лог">'
                 f'<div class="nm">исходник (лог)</div>'
                 f'<div class="m">до проявки</div></div>')
        h.append('<div class=arrow>→</div>')
        for st in row["steps"]:
            nm = ("0 (как снято)" if abs(st["stop"]) < 1e-6
                  else f'{st["stop"]:+.1f} стопа')
            mine = abs(st["stop"] - row["mine"]) < 1e-6
            h.append(f'<div class="cell pick" data-expo="{st["stop"]}" '
                     f'data-clip="{esc(row["clip_key"])}">'
                     f'<img loading="lazy" decoding="async" width="232" height="130" '
                     f'src="{esc(st["rel"])}" alt="{esc(nm)}">'
                     f'<div class="nm">{esc(nm)}</div>'
                     f'<div class="m">{("твой выбор" if row.get("from_saved") else "мой выбор") if mine else "&nbsp;"}</div></div>')
        h.append('</div>')
    h.append('</div>')

    h.append('<div class=foot>')
    h.append(f'<b>Версия v{v} · собрано {esc(ctx["when"])}</b><br>')
    h.append(f'кадры: <code>{esc(ctx["files_dir"])}</code> · '
             f'библиотека: <code>{esc(str(STORE))}</code><br>')
    h.append('Страница статическая, открывается с <code>file://</code>, сервер не нужен.')
    h.append('</div>')

    h.append('<div class=bar><button onclick="copyFeedback()">Скопировать выбор</button>'
             '<span class=st id=st>ничего не выбрано</span><span class=st id=restored style="color:var(--ok)"></span><button onclick="localStorage.removeItem(LSKEY);location.reload()" style="background:var(--card);color:var(--dim);border:1px solid var(--line)">сбросить к моему выбору</button></div>')

    # таблица «клип → стоп → яркость лица»: по ней страница считает медиану
    # того, что Роман выбрал, и это и есть выученная цель.
    code_json = json.dumps(ctx["code"])
    from_saved = "true" if ctx.get("from_saved") else "false"
    mine_json = json.dumps({
        "develop": {c: d for c, d in (ctx.get("rec_dev") or {}).items() if d},
        "look": ctx.get("rec_look"),
        "expo": {r["clip_key"]: r["mine"] for r in ctx["per_clip"]},
    }, ensure_ascii=False)
    expo_luma = json.dumps(
        {r["clip_key"]: {str(st["stop"]): round(st["m"]["luma"], 1) for st in r["steps"]}
         for r in ctx["expo_rows"]}, ensure_ascii=False)
    h.append(f"""<script>
// Моё предложение проставлено СРАЗУ, по всем ступеням и по каждому клипу.
// MINE — копия, по ней страница показывает, что именно правил Роман.
var MINE = {mine_json};
var CH = {{develop: Object.assign({{}}, MINE.develop),
           look: MINE.look,
           expo: Object.assign({{}}, MINE.expo)}};
var EXPO_LUMA = {expo_luma};

function refresh(){{
  document.querySelectorAll('.cell.pick').forEach(function(c){{
    if(c.dataset.expo !== undefined){{
      c.classList.toggle('sel', CH.expo[c.dataset.clip]===parseFloat(c.dataset.expo));
      return;
    }}
    var id=c.dataset.lut, cam=c.dataset.cam;
    var on = cam ? (CH.develop[cam]===id) : (CH.look===id);
    c.classList.toggle('sel', !!on);
  }});
  var d=Object.keys(CH.develop).length, e=Object.keys(CH.expo).length;
  var lm=[];
  for(var k in CH.expo){{ var v=EXPO_LUMA[k]; if(v&&v[CH.expo[k]]!==undefined) lm.push(v[CH.expo[k]]); }}
  lm.sort(function(a,b){{return a-b;}});
  var med = lm.length ? lm[Math.floor(lm.length/2)].toFixed(0) : '—';
  var ch=0;
  for(var k in CH.expo){{ if(MINE.expo[k]!==CH.expo[k]) ch++; }}
  for(var c in CH.develop){{ if(MINE.develop[c]!==CH.develop[c]) ch++; }}
  if(MINE.look!==CH.look) ch++;
  document.getElementById('st').textContent =
    ({from_saved} ? 'твой сохранённый выбор · изменено сейчас: '
                  : 'мой выбор проставлен · ты поправил: ') + ch +
    ' · цель по лицу ≈ ' + med + ' · look: ' + (CH.look || 'нет');
}}
document.addEventListener('click', function(e){{
  var c = e.target.closest('.cell.pick'); if(!c) return;
  if(c.dataset.expo !== undefined){{ CH.expo[c.dataset.clip]=parseFloat(c.dataset.expo); refresh(); return; }}
  var id=c.dataset.lut, cam=c.dataset.cam;
  if(cam) CH.develop[cam]=id; else CH.look=id;
  refresh(); persist();
}});
function copyFeedback(){{
  var lm=[];
  for(var k in CH.expo){{ var v=EXPO_LUMA[k]; if(v&&v[CH.expo[k]]!==undefined) lm.push(v[CH.expo[k]]); }}
  lm.sort(function(a,b){{return a-b;}});
  var payload = {{type:'lut_board', project:{json.dumps(ctx['code'])},
                  doc_version:{v}, develop:CH.develop, look:CH.look,
                  exposure:CH.expo, mine:MINE,
                  corrected: (function(){{var o={{}};
                    for(var k in CH.expo){{ if(MINE.expo[k]!==CH.expo[k]) o[k]=[MINE.expo[k],CH.expo[k]]; }}
                    return o;}})(),
                  target_face_luma: lm.length ? +lm[Math.floor(lm.length/2)].toFixed(1) : null}};
  var t=JSON.stringify(payload,null,1);
  var ta=document.createElement('textarea'); ta.value=t; document.body.appendChild(ta);
  ta.select(); try{{document.execCommand('copy');}}catch(e){{}}
  document.body.removeChild(ta);
  document.getElementById('st').textContent='скопировано — вставь в чат';
}}
// Промежуточное сохранение: выбор живёт в браузере и переживает закрытие
// вкладки. Прокликать 163 клипа и потерять всё на случайном Cmd+W — недопустимо.
var LSKEY = 'lutboard_' + {code_json};
function persist(){{
  try{{ localStorage.setItem(LSKEY, JSON.stringify(
    {{at:new Date().toISOString(), doc:{v}, CH:CH}})); }}catch(e){{}}
}}
(function restore(){{
  try{{
    var raw = localStorage.getItem(LSKEY); if(!raw) return;
    var got = JSON.parse(raw); if(!got || !got.CH) return;
    CH.develop = Object.assign({{}}, MINE.develop, got.CH.develop||{{}});
    CH.look = got.CH.look || MINE.look;
    CH.expo = Object.assign({{}}, MINE.expo, got.CH.expo||{{}});
    var el=document.getElementById('restored');
    if(el) el.textContent = 'восстановлен выбор от ' + String(got.at).slice(0,16).replace('T',' ');
  }}catch(e){{}}
}})();
refresh();
</script>""")
    h.append("</div></body></html>")
    return "\n".join(h)


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


# ───────────────────────────────────────────────────────── main ──

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Поступенчатая витрина выбора лутов: исходник → проявка → +look.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--project", required=True, help="путь к папке проекта YTAI")
    ap.add_argument("--frames-from", help="зеркало прокси, откуда снимать кадры")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--samples", type=int, default=SAMPLES_PER_CAM,
                    help=f"клипов на камеру для ступени 3 (по умолчанию {SAMPLES_PER_CAM})")
    ap.add_argument("--develop-rows", type=int, default=2,
                    help="клипов на камеру на ступени 2; это ОДИН выбор, "
                         "строки нужны только чтобы увидеть разницу")
    ap.add_argument("--develops", type=int, default=MAX_DEVELOP)
    ap.add_argument("--looks", type=int, default=0,
                    help="сколько покрасочных показать; 0 = все")
    ap.add_argument("--look-rows", type=int, default=4, help="клипов на лук-борде")
    ap.add_argument("--refresh", action="store_true", help="перерисовать кадры из кэша")
    ap.add_argument("--feedback", help="файл с выбором из витрины (или - для stdin); "
                                       "сохраняет и выходит, ничего не рендерит")
    ap.add_argument("--target", type=float,
                    help="цель яркости лица; по умолчанию — выученная из профиля канала")
    args = ap.parse_args(argv)

    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        die(f"проекта нет: {project}")
    m = re.match(r"^(YT[A-Z]{2,4}\d+)_", project.name)
    code = m.group(1) if m else project.name

    if args.feedback:
        raw = sys.stdin.read() if args.feedback == "-" else \
            Path(args.feedback).expanduser().read_text(encoding="utf-8")
        try:
            fb = json.loads(raw)
        except json.JSONDecodeError as e:
            die(f"выбор не разобрался как JSON: {e}")
        src = project / "01_Source"
        rec = load_recorded_gammas(project, code)
        cam_gamma = {}
        for cam, items in all_clips_by_cam(src).items():
            g = [normalize_gamma((rec.get(c.name) or (None,))[0])
                 for _, c in items if rec.get(c.name)]
            g = [x for x in g if x]
            if g:
                cam_gamma[cam] = max(set(g), key=g.count)
        res = save_choice(project, code, fb, cam_gamma)
        print(f"\nВЫБОР СОХРАНЁН")
        print(f"  профиль канала: {res['profile']}")
        print(f"  выбор по дню:   {res['choice']}")
        print(f"  клипов: {res['clips']} · поправлено против машины: {res['corrected']}")
        return 0
    source = project / "01_Source"
    if not source.is_dir():
        die(f"нет {source}")
    mirror = Path(args.frames_from).expanduser().resolve() if args.frames_from else None
    if not MANIFEST.exists():
        die("библиотека пуста — сначала `lut_lib.py --import --apply`")

    out_dir = project / "00_Setup" / "01_Ingest"
    files_dirname = f"{code}_lut_board_files"
    files_dir = out_dir / files_dirname
    if args.refresh and files_dir.exists():
        for p in files_dir.glob("*.jpg"):
            p.unlink()
    files_dir.mkdir(parents=True, exist_ok=True)

    luts = load_library()
    by_cam = all_clips_by_cam(source)
    if not by_cam:
        die("в проекте не нашлось клипов по сценам 01_Source/NN_*")
    recorded = load_recorded_gammas(project, code)

    print(f"\nВИТРИНА {code}")
    if recorded:
        print(f"  записанных гамм в плане: {len(recorded)} "
              f"(запасной источник, если оригинал недоступен)")

    # ── 1. Гамма и ведущая проявка — ДО любых кадров. Гамма это свойство клипа,
    # а не камеры: на YTEVO03 один клип ZV-E1 снят в rec709, остальные в S-Log3.
    cam_info = {}
    for cam, items in sorted(by_cam.items()):
        per_clip = [detect_gamma(c, cam, recorded) for _, c in items]
        seen = [g for g, _ in per_clip if g]
        gamma = max(set(seen), key=seen.count) if seen else None
        gsrc = next((s for g, s in per_clip if g == gamma), "не определена")
        mixed = sorted({g for g in seen if g != gamma})
        devs = develop_candidates(luts, gamma, args.develops)
        cam_info[cam] = {"gamma": gamma, "gamma_src": gsrc, "mixed": mixed,
                         "develops": devs}
        print(f"  {cam or '—':<16} гамма {str(gamma):<12} ({gsrc}) → "
              f"кандидатов {len(devs)}"
              + (f"  ⚠ в выборке ещё: {', '.join(mixed)}" if mixed else ""))

    # ── 2. Проб-проход через проявку: яркость (для ступени 2) и лицо (для ступени 3)
    t_probe = time.time()
    probe = probe_developed(by_cam, cam_info, source, mirror,
                            files_dir / "_probe", args.jobs)
    nface = sum(1 for v in probe.values() if v["face"])
    print(f"  проход 1: {len(probe)} клипов за {time.time()-t_probe:.0f} с · "
          f"лицо найдено у {nface}")

    # ── 3. Две выборки, потому что ступени спрашивают разное
    samples = pick_samples(by_cam, args.develop_rows,
                           {k: v["luma"] for k, v in probe.items()})
    face_samples = pick_face_samples(by_cam, args.samples, probe)
    print(f"  ступень 2 (проявка): {sum(len(v) for v in samples.values())} клипов, "
          f"самые тёмные · ступень 3 (экспозиция): "
          f"{sum(len(v) for v in face_samples.values())} клипов с лицом")

    _target = args.target or profile_target(project, code) or TARGET_FACE_LUMA_DEFAULT
    target = _target
    jobs = []          # (video, tc, out_path, luts, stops)
    cams = []
    lut_cam = {}       # id лута -> камера (look'и не попадают, у них камеры нет)

    for cam, items in sorted(samples.items()):
        info = cam_info[cam]
        gamma, gsrc, mixed, devs = (info["gamma"], info["gamma_src"],
                                    info["mixed"], info["develops"])
        for d in devs:
            lut_cam[d["id"]] = cam
        entry = {"cam": cam, "gamma": gamma, "gamma_src": gsrc, "mixed": mixed,
                 "develops": devs, "samples": []}

        for scene, clip in items:
            video, kind = P.frame_src(clip, source, mirror)
            dur = P.ffprobe_duration(video) or 4.0
            # Середина клипа, прижатая к его концу. ⚠️ Никакого нижнего порога в
            # полсекунды: на YTEVO03 два клипа короче (0.400 и 0.469 с), и порог
            # уводил таймкод ЗА конец — ffmpeg тогда не отдаёт кадр вовсе, а ругань
            # мjpeg про «Non full-range YUV» это лишь следствие, и она уводит в сторону.
            tc = max(0.0, min(dur * 0.5, dur - 0.05))
            stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{scene}_{clip.stem}")
            orig = files_dir / f"{stem}_orig.jpg"
            jobs.append((video, tc, orig, (), 0.0))
            srec = {"label": f"{scene} / {clip.name}", "orig_path": orig,
                    "orig_rel": f"{files_dirname}/{orig.name}", "dev": []}
            for d in devs:
                # ⚠️ id НЕ обрезать: общий префикс проявок Sony —
                # sony_a7s3__slog3_sgamut3cine__rec709__ — это 38 символов, и любая
                # обрезка до ~40 схлопывает eastman с eastmanrm, vision с visionteal.
                # Кадр тогда молча показывает не тот куб, что подписан.
                p = files_dir / f"{stem}__{d['id']}.jpg"
                jobs.append((video, tc, p, (STORE / d["file"],), 0.0))
                srec["dev"].append({"id": d["id"], "cam": cam, "path": p,
                                    "rel": f"{files_dirname}/{p.name}",
                                    "name": d["id"]})
            entry["samples"].append(srec)
        cams.append(entry)

    # ── Ступень 3: лестница экспозиции по ведущей проявке камеры.
    # Кадр на 0 стопов уже снят как вариант проявки — переиспользуем, не дублируем.
    expo_rows = []
    for cam, items in sorted(face_samples.items()):
        devs = cam_info[cam]["develops"]
        if not devs:
            continue
        lead = devs[0]
        for scene, clip in items:
            video, _ = P.frame_src(clip, source, mirror)
            dur = P.ffprobe_duration(video) or 4.0
            tc = max(0.0, min(dur * 0.5, dur - 0.05))
            stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{scene}_{clip.stem}")
            row = {"label": f"{scene} / {clip.name}", "cam": cam,
                   "develop": lead["id"], "clip_key": stem, "steps": []}
            for st in EXPOSURE_STOPS:
                pth = files_dir / f"{stem}__{lead['id']}__{stop_tag(st)}.jpg"
                jobs.append((video, tc, pth, (STORE / lead["file"],), st))
                row["steps"].append({"stop": st, "path": pth,
                                     "rel": f"{files_dirname}/{pth.name}"})
            expo_rows.append(row)

    # Лук-борд: одна проявка на всех, иначе разница между колонками — не только look.
    lead_cam = max(cams, key=lambda c: len(c["samples"]))
    lead_dev = lead_cam["develops"][0] if lead_cam["develops"] else None
    looks = look_candidates(luts, args.looks)
    look_rows = []
    # ⚠️ Look смотрят на НОРМАЛЬНО снятом кадре с лицом, а не на самом тёмном.
    # Выборка ступени «проявка» смещена в тёмное намеренно — там кубы и
    # расходятся, — но на чёрном кадре покраску не выбрать: не видно ничего.
    # Эталон — кадр, экспонированный ПРАВИЛЬНО, то есть с лицом ближе всего к
    # цели. Не самый тёмный (там ничего не видно) и не самый светлый: первый
    # заход брал самые светлые, и эталон вышел с 37 % пережога ещё ДО покраски —
    # на выбитом кадре характер look'а так же неразличим, как на чёрном.
    look_ref = []
    ref_pool = []
    for cam, items in face_samples.items():
        for scene, c in items:
            pr = probe.get(c.name) or {}
            fl = pr.get("face_luma")
            if not fl:
                continue
            if pr.get("frame_clip", 1) > 0.05 or pr.get("frame_black", 1) > 0.02:
                continue          # выбитый или утопленный кадр эталоном не годится
            ref_pool.append((abs(fl - target), scene, c))
    ref_pool.sort(key=lambda t: t[0])
    for _, scene, clip in ref_pool[:args.look_rows]:
        video, _ = P.frame_src(clip, source, mirror)
        dur = P.ffprobe_duration(video) or 4.0
        tc = max(0.0, min(dur * 0.5, dur - 0.05))
        look_ref.append((f"{scene} / {clip.name}",
                         re.sub(r"[^A-Za-z0-9]+", "_", f"{scene}_{clip.stem}"),
                         video, tc))
    if lead_dev:
        for label, stem0, vid0, tc0 in look_ref:
            stem = f"lookref_{stem0}"
            base = files_dir / f"{stem}__base.jpg"
            jobs.append((vid0, tc0, base, (STORE / lead_dev["file"],), 0.0))
            rec = {"label": label, "base_path": base,
                   "base_rel": f"{files_dirname}/{base.name}", "looks": []}
            for lk in looks:
                p = files_dir / f"{stem}__{lk['id']}.jpg"
                rec["looks"].append({"id": lk["id"], "path": p,
                                     "rel": f"{files_dirname}/{p.name}",
                                     "name": lk["id"].replace("look__", "")})
            look_rows.append(rec)

    if lead_dev:
        for (label, stem0, vid0, tc0), rec in zip(look_ref, look_rows):
            for lk, meta in zip(rec["looks"], looks):
                jobs.append((vid0, tc0, Path(lk["path"]),
                             (STORE / lead_dev["file"], STORE / meta["file"]), 0.0))

    print(f"  кадров к рендеру: {len(jobs)}")
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        for ok in ex.map(lambda j: extract(j[0], j[1], j[2], j[3], None, j[4]), jobs):
            done += 1 if ok else 0
    print(f"  снято {done}/{len(jobs)} за {time.time()-t0:.0f} с")
    if done < len(jobs):
        missing = [j[2].name for j in jobs if not frame_ok(j[2])]
        print(f"  ⚠ не снялось {len(missing)} кадров — в витрине будут дыры:")
        for nm in missing[:6]:
            print(f"        {nm}")

    # Убрать кадры, которых в ЭТОМ прогоне нет. Иначе страница смешивает результаты
    # разных прогонов, и выбор делается по кадрам от другого набора кубов.
    wanted = {j[2].name for j in jobs}
    stale = [p for p in files_dir.glob("*.jpg") if p.name not in wanted]   # _probe/ не трогаем
    for p in stale:
        p.unlink()
    if stale:
        print(f"  убрано кадров от прошлых прогонов: {len(stale)}")

    for cam in cams:
        for s in cam["samples"]:
            s["orig_m"] = metrics(s["orig_path"]) if frame_ok(s["orig_path"]) else \
                {"luma": 0, "sat": 0, "black": 0, "clip": 0}
            for d in s["dev"]:
                d["m"] = metrics(d["path"]) if frame_ok(d["path"]) else \
                    {"luma": 0, "sat": 0, "black": 0, "clip": 0}
    # ── Ступень 3: замер по ЛИЦУ. Рамка ищется один раз, на кадре 0 стопов, и
    # переиспользуется на всей лестнице: Vision на пере- и недодержанном кадре
    # находит лицо чуть иначе, и тогда разница в стопах смешалась бы с разницей
    # в рамке, а мы меряем именно экспозицию.
    target = _target
    target_src = ("задан флагом" if args.target else
                  ("выучен по твоему выбору" if profile_target(project, code)
                   else _TARGET_NOTE))
    faces = 0
    for row in expo_rows:
        zero = next(st for st in row["steps"] if abs(st["stop"]) < 1e-6)
        bbox = P.detect_face(zero["path"]) if frame_ok(zero["path"]) else None
        row["roi"] = "face" if bbox else "frame"
        faces += 1 if bbox else 0
        for st in row["steps"]:
            st["m"] = face_measure(st["path"], bbox) if frame_ok(st["path"]) else \
                {"luma": 0.0, "sat": 0.0, "lit": 0.0, "clip": 0.0, "roi": row["roi"]}
        z = next(st for st in row["steps"] if abs(st["stop"]) < 1e-6)
        row["miss_stops"] = stops_to_target(z["m"]["luma"], target)
        # Машина предлагает ближайшую доступную ступень, но ТОЛЬКО если лицо
        # найдено. Без лица предлагать экспозицию не по чему — счёт пошёл бы
        # по небу за лобовым стеклом, а это ровно та ошибка, что была раньше.
        if row["roi"] == "face":
            row["machine"] = min((st["stop"] for st in row["steps"]),
                                 key=lambda v: abs(v - row["miss_stops"]))
            # Лестница конечна. Если промах больше её потолка, машина упирается
            # и об этом надо сказать, а не молча предложить крайнюю ступень:
            # такой кадр либо снят сильно не так, либо тёмный по замыслу.
            row["out_of_range"] = abs(row["miss_stops"]) > max(EXPOSURE_STOPS) + 1e-6
        else:
            row["machine"] = 0.0
            row["locked"] = True

    # ── Покрытие: та же арифметика, но по ВСЕМ клипам дня. Витрина учит цели
    # на двенадцати клипах — прокликать 163, чтобы выразить вкус, невозможно, —
    # а применяется цель ко всему дню. Кадры для этого уже сняты проб-проходом.
    coverage = []
    for cam, items in sorted(by_cam.items()):
        devs = cam_info[cam]["develops"]
        for scene, clip in items:
            pr = probe.get(clip.name)
            if not pr:
                coverage.append({"cam": cam, "clip": clip.name, "scene": scene,
                                 "state": "кадр не снялся", "stop": None})
                continue
            if not devs:
                coverage.append({"cam": cam, "clip": clip.name, "scene": scene,
                                 "state": "нет проявки под гамму", "stop": None})
                continue
            if not pr["face"]:
                coverage.append({"cam": cam, "clip": clip.name, "scene": scene,
                                 "state": "лица нет — экспозиция не трогается",
                                 "stop": 0.0, "luma": pr["luma"]})
                continue
            miss = stops_to_target(pr["face_luma"], target)
            st = min(EXPOSURE_STOPS, key=lambda v: abs(v - miss))
            over = abs(miss) > max(EXPOSURE_STOPS) + 1e-6
            coverage.append({"cam": cam, "clip": clip.name, "scene": scene,
                             "state": "лестницы не хватает" if over else "по лицу",
                             "stop": st, "miss": miss, "luma": pr["face_luma"]})

    for rec in look_rows:
        rec["base_m"] = metrics(rec["base_path"]) if frame_ok(rec["base_path"]) else \
            {"luma": 0, "sat": 0, "black": 0, "clip": 0}
        for lk in rec["looks"]:
            lk["m"] = metrics(lk["path"]) if frame_ok(lk["path"]) else \
                {"luma": 0, "sat": 0, "black": 0, "clip": 0}

    # ── ВОЛНА 2: сетка по КАЖДОМУ клипу дня, под моей рекомендацией.
    # Роман: «выбор по каждому видео, а не по группе» и «ты делаешь выбор,
    # я корректирую». Поэтому здесь не выборка, а весь день, и в каждой строке
    # моё предложение уже отмечено — он правит только то, с чем не согласен.
    # ⚠️ Среднее по ВСЕМ строкам лук-борда, а не последняя строка. Словарь-
    # компрехеншн по {id: m} оставлял метрики последнего клипа и выбирал look
    # по одному кадру: так malibu обошёл porsche_xblue_contrast, который в
    # среднем насыщеннее при том же нуле повреждений.
    _acc = {}
    for rec in look_rows:
        for lk in rec["looks"]:
            _acc.setdefault(lk["id"], []).append(lk["m"])
    look_metrics = {k: {mk: sum(m[mk] for m in v) / len(v) for mk in v[0]}
                    for k, v in _acc.items()}
    rec_look = recommend_look(looks, look_metrics) if look_rows else None
    rec_dev = {cam: recommend_develop(info["develops"]) for cam, info in cam_info.items()}

    # ⚠️ Если Роман уже выбирал по этому дню — предлагается ЕГО выбор, а не мой.
    # Иначе каждая пересборка витрины откатывала бы его работу к рекомендации.
    saved = load_json_safe(out_dir / f"{code}_color_choice.json") or {}
    by_id = {l["id"]: l for l in luts}
    if saved.get("look") and saved["look"] in by_id:
        rec_look = by_id[saved["look"]]
    for cam, lut_id in (saved.get("develop") or {}).items():
        if lut_id in by_id and cam in rec_dev:
            rec_dev[cam] = by_id[lut_id]
    saved_expo = saved.get("exposure") or {}
    if saved:
        print(f"  найден твой сохранённый выбор от {saved.get('saved', '?')[:16]} — "
              f"витрина предлагает его, не мой")

    per_clip = []
    skipped_nonlog = []
    jobs2 = []
    for cam, items in sorted(by_cam.items()):
        dev = rec_dev.get(cam)
        if not dev:
            continue
        chain = [STORE / dev["file"]] + ([STORE / rec_look["file"]] if rec_look else [])
        for scene, clip in items:
            # ⚠️ Снятое НЕ в логе сюда не попадает: проявка ему не нужна, а
            # применить её — значит проявить уже проявленное и убить кадр.
            # На YTEVO03 это один клип ZV-E1, снятый в rec709.
            grec = (recorded.get(clip.name) or (None,))[0]
            if grec and normalize_gamma(grec) == "Rec.709":
                skipped_nonlog.append(f"{scene}/{clip.name}")
                continue
            pr = probe.get(clip.name)
            video, _ = P.frame_src(clip, source, mirror)
            dur = P.ffprobe_duration(video) or 4.0
            tc = max(0.0, min(dur * 0.5, dur - 0.05))
            stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{scene}_{clip.stem}")
            row = {"key": f"{scene}/{clip.name}", "clip_key": stem, "cam": cam,
                   "scene": scene, "clip": clip.name, "develop": dev["id"],
                   "look": rec_look["id"] if rec_look else None,
                   "face": bool(pr and pr["face"]), "steps": []}
            o = files_dir / "_perclip" / f"{stem}_orig.jpg"
            jobs2.append((video, tc, o, (), 0.0))
            row["orig_rel"] = f"{files_dirname}/_perclip/{o.name}"
            if pr and pr["face"] and pr.get("face_luma"):
                miss = stops_to_target(pr["face_luma"], target)
                row["miss"] = miss
                lad = ladder_for(miss)
                row["mine"] = min(lad, key=lambda v: abs(v - miss))
                row["over"] = abs(miss) > EXPOSURE_MAX + 1e-6
            else:
                row["mine"] = 0.0          # без лица экспозицию не двигаем
                row["miss"] = None
            if stem in saved_expo:         # сохранённый выбор человека сильнее
                row["mine"] = float(saved_expo[stem])
                row["from_saved"] = True
            # ⚠️ Имя кадра несёт ПРОЯВКУ и LOOK. Без них смена рекомендации не
            # инвалидирует кэш: кадры остаются от прошлого look, а подпись на
            # странице уже новая — и выбор делается по картинке от другого куба.
            # Поймано живьём: кадры под malibu подписались porsche_xblue_contrast.
            tagbase = f"{stem}__{dev['id']}__{rec_look['id'] if rec_look else 'nolook'}"
            for st in ladder_for(row.get("miss")):
                f = files_dir / "_perclip" / f"{tagbase}__{stop_tag(st)}.jpg"
                jobs2.append((video, tc, f, tuple(chain), st))
                row["steps"].append({"stop": st, "path": f,
                                     "rel": f"{files_dirname}/_perclip/{f.name}"})
            per_clip.append(row)

    print(f"  волна 2: {len(per_clip)} клипов × {len(EXPOSURE_STOPS)+1} кадров "
          f"= {len(jobs2)} — под {rec_dev and 'моей проявкой'} и look "
          f"{rec_look['id'] if rec_look else '—'}")
    t2 = time.time()
    done2 = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        for ok in ex.map(lambda j: extract(j[0], j[1], j[2], j[3], PERCLIP_W, j[4]), jobs2):
            done2 += 1 if ok else 0
    print(f"  снято {done2}/{len(jobs2)} за {time.time()-t2:.0f} с")
    want2 = {j[2].name for j in jobs2}
    pc = files_dir / "_perclip"
    stale2 = [q for q in pc.glob("*.jpg") if q.name not in want2] if pc.exists() else []
    for q in stale2:
        q.unlink()
    if stale2:
        print(f"  убрано кадров от прошлой рекомендации: {len(stale2)}")

    vpath = out_dir / f"{code}_lut_board_version.json"
    ver = int((json.loads(vpath.read_text()) if vpath.exists() else {}).get("v", 0)) + 1
    vpath.write_text(json.dumps({"v": ver, "at": time.strftime("%Y-%m-%d %H:%M:%S")}),
                     encoding="utf-8")

    unknown = [c["cam"] for c in cams if not c["gamma"]]
    nolut = [c["cam"] for c in cams if not c["develops"]]
    ctx = {
        "code": code, "version": ver, "when": when_ru(),
        "cams": cams, "look_rows": look_rows, "expo_rows": expo_rows,
        "coverage": coverage, "per_clip": per_clip,
        "skipped_nonlog": skipped_nonlog, "from_saved": bool(saved),
        "rec_look": rec_look["id"] if rec_look else None,
        "rec_dev": {c: (d["id"] if d else None) for c, d in rec_dev.items()},
        "target": target, "target_src": target_src, "faces": faces,
        "look_base_name": lead_dev["id"] if lead_dev else "—",
        "files_dir": str(files_dir), "lut_cam": lut_cam,
        "kpi": [("камер", len(cams)),
                ("клипов в выборке", sum(len(c["samples"]) for c in cams)),
                ("кадров", len(jobs)),
                ("кандидатов проявки", sum(len(c["develops"]) for c in cams)),
                ("look'ов", len(looks)),
                ("лиц найдено", f"{faces} из {len(expo_rows)}"),
                ("снято не в логе", len(skipped_nonlog)),
                ("цель по лицу", f"{target:.0f}"),
                ("гамма не определена", len(unknown)),
                ("нет проявки под гамму", len(nolut))],
    }
    html = out_dir / f"{code}_lut_board.html"
    html.write_text(build_html(ctx), encoding="utf-8")

    size_mb = sum(p.stat().st_size for p in files_dir.glob("*.jpg")) / 1024 / 1024
    print(f"\n  → {html}")
    print(f"     кадров {len(list(files_dir.glob('*.jpg')))} · {size_mb:.0f} МБ · v{ver}")
    if unknown:
        print(f"  ⚠ гамма не определена: {', '.join(unknown)}")
    if nolut:
        print(f"  ⚠ в библиотеке нет проявки под гамму: {', '.join(nolut)}")
    print(f"\n  open \"{html}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
