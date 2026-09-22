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
            out = probe_dir / (re.sub(r"[^A-Za-z0-9]+", "_", f"{scene}_{clip.stem}") + ".jpg")
            tasks.append((video, tc, out, (lead,) if lead else (), clip.name))
    with ThreadPoolExecutor(max_workers=jobs_n) as ex:
        list(ex.map(lambda t: extract(t[0], t[1], t[2], t[3], PROBE_W), tasks))
    out = {}
    for _, _, jpg, _, name in tasks:
        if not frame_ok(jpg, PROBE_W // 2):
            continue
        a = np.asarray(Image.open(jpg).convert("RGB"), dtype=np.float64)
        bbox = P.detect_face(jpg)
        # Яркость по лицу — та же величина, что решает на ступени 3, только
        # посчитанная для ВСЕХ клипов дня, а не для двенадцати в витрине.
        fm = P.face_metrics(a, bbox, core=P.FACE_CORE) if bbox else None
        out[name] = {"luma": float((a * (0.2126, 0.7152, 0.0722)).sum(-1).mean()),
                     "face": bbox is not None,
                     "face_luma": float(fm["luma"]) if fm else None,
                     "clip": float(fm["clip"]) if fm else None}
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


def look_candidates(luts, limit=MAX_LOOKS):
    """Look'и: сперва те, что не ломают нейтраль слишком сильно, затем яркие.
    Порядок в витрине — от спокойного к характерному, чтобы глаз шёл по шкале."""
    pool = [l for l in luts if l["stage"] == "look"]
    pool.sort(key=lambda l: l["metrics"].get("neutral_drift255", 0.0))
    if len(pool) <= limit:
        return pool
    idx = np.linspace(0, len(pool) - 1, limit).round().astype(int)
    return [pool[i] for i in sorted(set(idx))]


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
            ranked = sorted(items, key=lambda it: luma.get(it[1].name, 999.0))
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
.built{background:#1b2030;border:1px solid var(--acc);border-radius:10px;
       padding:10px 14px;margin:0 0 20px;font-size:13.5px}
.sec{background:var(--card);border:1px solid var(--line);border-radius:14px;
     padding:18px 18px 8px;margin:0 0 18px}
.sec h2{font:700 18px/1.3 'Space Grotesk','Inter',sans-serif;margin:0 0 4px}
.sec h2 .ic{margin-right:8px}
.sec .why{color:var(--dim);font-size:13.5px;margin:0 0 14px;max-width:1100px}
.camttl{font:700 14px ui-monospace,monospace;color:var(--acc);margin:16px 0 4px}
.gam{color:var(--dim);font:500 12.5px ui-monospace,monospace;margin:0 0 10px}
.row{display:flex;gap:10px;overflow-x:auto;padding-bottom:8px}
.cell{flex:0 0 232px}
.cell img{display:block;width:232px;height:130px;object-fit:cover;border-radius:8px;
          border:2px solid transparent;background:#000}
.cell.base img{border-color:var(--line)}
.cell.sel img{border-color:var(--acc)}
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
    h.append("<p class=sub>Слева направо в каждой строке: исходник в логе → та же "
             "картинка после <b>проявки</b> → и после <b>проявки с покраской</b>. "
             "Проявку выбирает камера, а не вкус — но у кандидатов разная цена "
             "по теням, и цену видно числами под кадром. Покраска — ДНК канала, "
             "одна на весь канал.</p>")

    k = ctx["kpi"]
    h.append("<div class=kpi>" + "".join(
        f"<b>{esc(a)} <i>{esc(b)}</i></b>" for a, b in k) + "</div>")

    h.append("<div class=built>Кадры собраны так: <b>цепочкой из двух lut3d</b>, "
             "а не через склеенный куб — в превью ошибки склейки нет вообще. "
             "Склейка в один куб точна не для всякого look'а (замер 22.09: Baza "
             "0,98/255, GOLD 54/255), и вопрос о ней решается после пробы Input LUT "
             "в Premiere.</div>")

    # ── ступень 2: проявка
    h.append('<div class=sec><h2><span class=ic>🎞</span>Ступень 2 · Проявка — '
             'решает камера, не вкус</h2>')
    h.append('<p class=why>Проявка переводит лог в Rec.709 и выбирается '
             'детерминированно по камере и гамме клипа. Кандидаты ниже — из '
             'библиотеки, отобраны под гамму этой камеры и отсортированы по '
             'цене в тенях. <b>Красное число = куб съедает картинку:</b> '
             'чёрное выше 1 % значит зажатые тени, пережог выше 2 % — выбитые света. '
             'Исходники дня проверены: в них 0,00 % чистого чёрного, поэтому всё '
             'зажатое создаёт именно лут.</p>')
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
                h.append(cell_html(d["rel"], d["name"], d["m"], s["orig_m"],
                                   "pick", d["id"], d.get("cam", "")))
            h.append("</div>")
    h.append("</div>")

    # ── ступень 3: экспозиция
    h.append('<div class=sec><h2><span class=ic>🔆</span>Ступень 3 · Экспозиция — '
             'по лицу, правится потом</h2>')
    h.append(f'<p class=why>Экспозиция — <b>не лут</b>, а число: слайдер Exposure '
             f'в Basic Correction. Порядок обработки внутри Lumetri вытащен из '
             f'твоего же шаблона проекта и выглядит так: '
             f'<code>LUT (проявка) → BasicCorrection3 (Exposure) → LUT (покраска)</code>. '
             f'То есть экспозиция живёт ровно между ступенями, и превью ниже '
             f'повторяет этот порядок.<br>'
             f'Замер идёт <b>по лицу</b> и только на проявленном кадре — на логе '
             f'пороги бессмысленны. Цель <b>{ctx["target"]:.0f}</b> '
             f'({esc(ctx["target_src"])}). Пунктиром обведено предложение машины; '
             f'твой выбор её переучивает. Монтажёр потом двигает тот же слайдер '
             f'и видит, что там стоит — в отличие от куба, который непрозрачен.</p>')
    for row in ctx["expo_rows"]:
        lock = row.get("locked")
        note = (' · <span style="color:var(--warn)">лица нет — экспозиция не '
                'предлагается</span>' if lock else
                (f' · промах {row["miss_stops"]:+.2f} стопа'
                 + (' · <span style="color:var(--warn)">лестницы не хватает — '
                    'снято сильно мимо либо тёмный по замыслу</span>'
                    if row.get("out_of_range") else '')))
        h.append(f'<div class=lbl>{esc(row["label"])} · {esc(row["develop"])}{note}</div>')
        h.append('<div class=row>')
        for st in row["steps"]:
            m = st["m"]
            nm = ("0 (как снято)" if abs(st["stop"]) < 1e-6
                  else f'{st["stop"]:+.1f} стопа')
            mm = (f'лицо {m["luma"]:.0f} · переж {m["clip"]*100:.1f}%'
                  if m.get("roi") == "face"
                  else f'кадр {m["luma"]:.0f} · переж {m["clip"]*100:.1f}%')
            sel = ' style="outline:2px dashed var(--acc);outline-offset:3px"' \
                if (not lock and abs(st["stop"] - row["machine"]) < 1e-6) else ''
            cls = "cell base" if lock else "cell pick"
            attr = "" if lock else (f' data-expo="{st["stop"]}" '
                                    f'data-clip="{esc(row["clip_key"])}"')
            h.append(f'<div class="{cls}"{attr}{sel}>'
                     f'<img loading="lazy" decoding="async" width="232" height="130" '
                     f'src="{esc(st["rel"])}" alt="{esc(nm)}">'
                     f'<div class="nm">{esc(nm)}</div><div class="m">{mm}</div></div>')
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

    # ── ступень 4: покраска
    h.append('<div class=sec><h2><span class=ic>🎨</span>Ступень 4 · Покраска — '
             'ДНК канала</h2>')
    h.append(f'<p class=why>Один look на весь канал. Слева закреплён кадр '
             f'<b>без покраски</b> — это база сравнения. Все варианты положены '
             f'поверх одной и той же проявки '
             f'(<code>{esc(ctx["look_base_name"])}</code>), поэтому разница между '
             f'колонками — это ровно покраска и ничего больше.</p>')
    for s in ctx["look_rows"]:
        h.append(f'<div class=lbl>{esc(s["label"])}</div><div class=row>')
        h.append(cell_html(s["base_rel"], "только проявка", s["base_m"], None, "base"))
        h.append('<div class=arrow>→</div>')
        for lk in s["looks"]:
            h.append(cell_html(lk["rel"], lk["name"], lk["m"], s["base_m"],
                               "pick", lk["id"]))
        h.append("</div>")
    h.append("</div>")

    h.append('<div class=foot>')
    h.append(f'<b>Версия v{v} · собрано {esc(ctx["when"])}</b><br>')
    h.append(f'кадры: <code>{esc(ctx["files_dir"])}</code> · '
             f'библиотека: <code>{esc(str(STORE))}</code><br>')
    h.append('Страница статическая, открывается с <code>file://</code>, сервер не нужен.')
    h.append('</div>')

    h.append('<div class=bar><button onclick="copyFeedback()">Скопировать выбор</button>'
             '<span class=st id=st>ничего не выбрано</span></div>')

    # таблица «клип → стоп → яркость лица»: по ней страница считает медиану
    # того, что Роман выбрал, и это и есть выученная цель.
    expo_luma = json.dumps(
        {r["clip_key"]: {str(st["stop"]): round(st["m"]["luma"], 1) for st in r["steps"]}
         for r in ctx["expo_rows"]}, ensure_ascii=False)
    h.append(f"""<script>
var CH = {{develop:{{}}, look:null, expo:{{}}}};
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
  document.getElementById('st').textContent =
    'проявка: ' + d + ' камер · look: ' + (CH.look || 'нет') +
    ' · экспозиция: ' + e + ' клипов · твоя цель по лицу ≈ ' + med;
}}
document.addEventListener('click', function(e){{
  var c = e.target.closest('.cell.pick'); if(!c) return;
  if(c.dataset.expo !== undefined){{ CH.expo[c.dataset.clip]=parseFloat(c.dataset.expo); refresh(); return; }}
  var id=c.dataset.lut, cam=c.dataset.cam;
  if(cam) CH.develop[cam]=id; else CH.look=id;
  refresh();
}});
function copyFeedback(){{
  var lm=[];
  for(var k in CH.expo){{ var v=EXPO_LUMA[k]; if(v&&v[CH.expo[k]]!==undefined) lm.push(v[CH.expo[k]]); }}
  lm.sort(function(a,b){{return a-b;}});
  var payload = {{type:'lut_board', project:{json.dumps(ctx['code'])},
                  doc_version:{v}, develop:CH.develop, look:CH.look,
                  exposure:CH.expo,
                  target_face_luma: lm.length ? +lm[Math.floor(lm.length/2)].toFixed(1) : null}};
  var t=JSON.stringify(payload,null,1);
  var ta=document.createElement('textarea'); ta.value=t; document.body.appendChild(ta);
  ta.select(); try{{document.execCommand('copy');}}catch(e){{}}
  document.body.removeChild(ta);
  document.getElementById('st').textContent='скопировано — вставь в чат';
}}
refresh();
</script>""")
    h.append("</div></body></html>")
    return "\n".join(h)


# ───────────────────────────────────────────────────────── main ──

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Поступенчатая витрина выбора лутов: исходник → проявка → +look.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--project", required=True, help="путь к папке проекта YTAI")
    ap.add_argument("--frames-from", help="зеркало прокси, откуда снимать кадры")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--samples", type=int, default=SAMPLES_PER_CAM,
                    help=f"клипов на камеру (по умолчанию {SAMPLES_PER_CAM})")
    ap.add_argument("--develops", type=int, default=MAX_DEVELOP)
    ap.add_argument("--looks", type=int, default=MAX_LOOKS)
    ap.add_argument("--look-rows", type=int, default=4, help="клипов на лук-борде")
    ap.add_argument("--refresh", action="store_true", help="перерисовать кадры из кэша")
    ap.add_argument("--target", type=float,
                    help="цель яркости лица; по умолчанию — выученная из профиля канала")
    args = ap.parse_args(argv)

    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        die(f"проекта нет: {project}")
    m = re.match(r"^(YT[A-Z]{2,4}\d+)_", project.name)
    code = m.group(1) if m else project.name
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
    samples = pick_samples(by_cam, args.samples,
                           {k: v["luma"] for k, v in probe.items()})
    face_samples = pick_face_samples(by_cam, args.samples, probe)
    print(f"  ступень 2 (проявка): {sum(len(v) for v in samples.values())} клипов, "
          f"самые тёмные · ступень 3 (экспозиция): "
          f"{sum(len(v) for v in face_samples.values())} клипов с лицом")

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
    if lead_dev:
        rows = lead_cam["samples"][:args.look_rows]
        for s in rows:
            stem = Path(s["orig_path"]).stem.replace("_orig", "")
            base = files_dir / f"{stem}__base.jpg"
            jobs.append((None, None, base, None, 0.0))       # заполнится ниже
            rec = {"label": s["label"], "base_path": base,
                   "base_rel": f"{files_dirname}/{base.name}", "looks": []}
            for lk in looks:
                p = files_dir / f"{stem}__{lk['id']}.jpg"
                rec["looks"].append({"id": lk["id"], "path": p,
                                     "rel": f"{files_dirname}/{p.name}",
                                     "name": lk["id"].replace("look__", "")})
            look_rows.append(rec)

    # достроить задания лук-борда (нужен video/tc того же клипа)
    jobs = [j for j in jobs if j[0] is not None]
    if lead_dev:
        for s, rec in zip(lead_cam["samples"][:args.look_rows], look_rows):
            src_job = next(j for j in jobs if j[2] == s["orig_path"])
            video, tc = src_job[0], src_job[1]
            jobs.append((video, tc, Path(rec["base_path"]),
                         (STORE / lead_dev["file"],), 0.0))
            for lk, meta in zip(rec["looks"], looks):
                jobs.append((video, tc, Path(lk["path"]),
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
    target = args.target or profile_target(project, code) or TARGET_FACE_LUMA_DEFAULT
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

    vpath = out_dir / f"{code}_lut_board_version.json"
    ver = int((json.loads(vpath.read_text()) if vpath.exists() else {}).get("v", 0)) + 1
    vpath.write_text(json.dumps({"v": ver, "at": time.strftime("%Y-%m-%d %H:%M:%S")}),
                     encoding="utf-8")

    unknown = [c["cam"] for c in cams if not c["gamma"]]
    nolut = [c["cam"] for c in cams if not c["develops"]]
    ctx = {
        "code": code, "version": ver, "when": when_ru(),
        "cams": cams, "look_rows": look_rows, "expo_rows": expo_rows,
        "coverage": coverage,
        "target": target, "target_src": target_src, "faces": faces,
        "look_base_name": lead_dev["id"] if lead_dev else "—",
        "files_dir": str(files_dir), "lut_cam": lut_cam,
        "kpi": [("камер", len(cams)),
                ("клипов в выборке", sum(len(c["samples"]) for c in cams)),
                ("кадров", len(jobs)),
                ("кандидатов проявки", sum(len(c["develops"]) for c in cams)),
                ("look'ов", len(looks)),
                ("лиц найдено", f"{faces} из {len(expo_rows)}"),
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
