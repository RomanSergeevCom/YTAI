#!/usr/bin/env python3
"""
lut_face_score.py — per-CLIP LUT picker by FACE brightness/saturation, fully local.

For every clip in every scene folder {project}/01_Source/{NN_Scene}/ (RECURSIVELY —
clips may sit one level deeper, in per-camera folders):
  1. sample frames (1-3 per clip depending on duration),
  2. render each sample through every .cube LUT in 01_Source/00_LUT/ (ffmpeg lut3d)
     plus the ungraded original,
  3. detect the largest face (Apple Vision, VNDetectFaceRectanglesRequest — offline),
  4. measure the face patch: mean luma, mean saturation, clipped-highlight share,
  5. score = brightness + saturation − clipping penalty; clip verdict = best mean.

Review HTML is interactive PER CLIP: click a frame card / chip to choose that
clip's LUT (favourite pre-selected), per-scene note field, sticky "Скопировать
фидбек" bar → JSON {type: lut_feedback, choices: {scene/clip: lut}, notes} to
paste back into Claude chat — or straight into this script via --feedback.

Outputs (into {project}/00_Setup/01_Ingest/):
  {CODE}_lut_review.html        — interactive review (open via file://)
  {CODE}_lut_review_files/      — jpg frames (relative links)
  {CODE}_lut_plan.json          — {"scene/clip.MP4" → lut} for the UXP
                                  per-range adjustment stage, plus diagnostics

Usage:
  source ~/YTAI/environment/.venv_vlm/bin/activate   # pyobjc Vision + numpy + Pillow

  # score (frames read from the proxy mirror, plan keys stay on the originals)
  python3 lut_face_score.py --project "/Volumes/T9-Black-RYA/YTEVO/YTEVO03_Plechko_day" \
      --frames-from ~/Desktop/YTEVO03_01_Source_Proxy --jobs 4

  # pull the human's choice back in (no ffmpeg, no Vision, fractions of a second)
  pbpaste | python3 lut_face_score.py --project "..." --feedback -

Env: needs ffmpeg/ffprobe in PATH; macOS only (Apple Vision via pyobjc).
"""

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from PIL import Image

try:
    import Vision
    import Quartz
    from Foundation import NSURL
    HAVE_VISION = True
except ImportError:
    HAVE_VISION = False

FRAME_WIDTH = 960
JPEG_Q = "3"
CLIP_THRESHOLD = 250   # 8-bit value counted as clipped
FACE_CORE = 0.70       # central share of the face bbox used for skin metrics
SAT_FLOOR = 16         # ниже этого max(RGB) насыщенность — шум, а не цвет
SAT_MIN_SHARE = 0.10   # освещено меньше 10 % пятна ⇒ насыщенности нет вовсе

# score = luma + saturation bonus − clipping penalty (weights tuned for
# "максимальная яркость лица без пережога": brightness dominates, clip kills)
W_LUMA, W_SAT, W_CLIP = 1.0, 0.55, 900.0

# Ниже этого перевеса счёт не считается решением: см. verdict_of().
TIE_EPS = 4.0
DEFAULT_LUT = "02_normal_scene"

VIDEO_EXT = {".mp4", ".mov"}

# Semantic order for review columns/chips: bright | normal | dark —
# "normal" sits in the CENTER (decision 18.08.2026); alphabetical fallback
# for LUTs outside the trio.
LUT_ORDER = ("bright", "normal", "dark")

# Луты канала собраны в Resolve под S-Log3 / S-Gamut3.Cine. Всё, что снято не в
# этой науке, красится чужой математикой — вердикт скоринга для таких клипов
# условен, и это обязано быть видно на странице, а не всплыть в цветокоре.
CAM_PROFILE = {
    "CAM-A_FX3":    ("S-Log3", "S-Gamut3.Cine", "match"),
    "CAM-B_ZVE1":   ("S-Log3", "S-Gamut3.Cine", "match"),
    "CAM-C_Pocket": ("D-Log2", "DJI",           "mismatch"),
}

MONTHS_RU = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
             "августа", "сентября", "октября", "ноября", "декабря")

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
           "viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%8E%9A"
           "%3C/text%3E%3C/svg%3E")            # 🎚

FLAG_BADGE = {
    "frame_suspect":  ("кадр не снялся", "bad"),
    "luts_identical": ("луты дали одно и то же", "bad"),
    "noface":         ("лица нет — счёт по всему кадру", "warn"),
    "face_partial":   ("лицо не во всех сэмплах", "dim"),
    "tie":            ("ничья — взята середина", "warn"),
    "lut_crushed":    ("один из лутов давит кадр", "dim"),
    "gamma_mismatch": ("D-Log2 ≠ S-Log3", "dim"),
    "eightbit":       ("8 бит", "dim"),
    "overridden":     ("выбор Романа против счёта", "ok"),
}

# технические поломки — только они идут в run-gate. «crushed» (лут задавил кадр)
# поломкой НЕ является: 01_bright_scene по замыслу давит, и на храмовых клипах он
# законно топит кадр в чёрный — это информация о луте, а не о ffmpeg.
FRAME_BROKEN = ("flat", "blank", "missing", "no_base")

FRAME_NOTE = {
    "crushed": ("лут давит кадр", "#F2B02A"),
    "blown":   ("лут пережигает", "#F2B02A"),
    "flat":    ("кадр пустой", "#F2603C"),
    "blank":   ("кадр вне диапазона", "#F2603C"),
    "missing": ("кадр не снялся", "#F2603C"),
    "no_base": ("нет ориг-кадра", "#F2603C"),
}


# ─────────────────────────────────────────────────────────────── процессы ──

def run(cmd, timeout=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def ffprobe_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)], timeout=60)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def clip_sample_points(clip):
    """1-3 (tc) samples inside one clip, by duration.

    ⚠️ Пол в 0.5 с обязан быть прижат к длине клипа. На YTEVO03 есть клип в
    0.469 с (DJI_20260918072725_0008_D): max(0.5, 0.469*0.5) = 0.5 — это ЗА
    концом, ffmpeg не отдаёт ни одного кадра, и клип молча остаётся без
    вердикта, то есть в Premiere без слоя.
    """
    dur = ffprobe_duration(clip)
    if dur <= 0:
        return []
    if dur < 120:
        fracs = (0.5,)
    elif dur < 900:
        fracs = (0.25, 0.75)
    else:
        fracs = (0.15, 0.5, 0.85)
    ceiling = max(0.0, dur - 0.05)
    return [min(max(0.5, dur * f), ceiling) if ceiling > 0 else 0.0 for f in fracs]


# ───────────────────────────────────────────────────────── кадры и ffmpeg ──

def lut_arg(lut):
    """Экранирование пути внутри filter-graph: слэш, двоеточие, апостроф.

    Сейчас пути чистые, но 00_LUT живёт на внешнем томе — один пробел или ':'
    в имени, и ffmpeg молча сыплет ошибкой парсинга на каждом кадре.
    Образец: 999_extra/source_light_transcode.py:48-54.
    """
    return str(lut).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def vf_chain(lut):
    """Одна цепочка на orig и на варианты — иначе они несравнимы по яркости.

    scale ДО lut3d: куб считается на 960 px, а не на 4K — 0.28 с против 0.34 с.
    format=gbrp10le — общий знаменатель: .cube определён в RGB, и orig, и все
    варианты уходят в mjpeg из ОДНОГО формата, поэтому авто-конверсия одинакова
    для всех и не сдвигает шкалу. Именно это делает orig честной базой
    сравнения в frame_verdict().

    Замер 21.09.2026, ffmpeg 8.1.1, RYA-FX3-1229 @1s, 02_normal_scene:
      lut3d,scale (старая цепочка)                YAVG 623.33 / 1023
      scale,yuv422p10le,lut3d:tetra,yuv420p       YAVG 155.36 /  255  (= 621.5)
      scale,gbrp10le,lut3d:tetra                  YAVG 623.32 / 1023
    Цепочки сходятся, interp=tetrahedral — уже дефолт в ffmpeg 8.1.1, чёрного
    кадра нет ни в одной. Это правка-страховка, а не лечение бага.
    """
    base = f"scale={FRAME_WIDTH}:-2:flags=bicubic,format=gbrp10le"
    if not lut:
        return base
    return f"{base},lut3d=file='{lut_arg(lut)}':interp=tetrahedral"


def jpeg_ok(path, min_w=FRAME_WIDTH // 2):
    """Сигнатура + реальные размеры (образец: 0120_day_ingest/s7_frames.py:37-52).

    Оборванный ffmpeg оставляет файл ненулевого размера, но битый — гейт по
    size > 0 его пропустит, а потом Pillow упадёт уже в скоринге.
    """
    try:
        if path.stat().st_size < 4000:
            return False
        with open(path, "rb") as fh:
            if fh.read(2) != b"\xff\xd8":
                return False
        with Image.open(path) as im:
            return im.width >= min_w and im.height > 100
    except Exception:
        return False


def extract_frame(video, tc, out_jpg, lut=None):
    try:
        r = run(["ffmpeg", "-nostdin", "-hide_banner", "-y", "-v", "error",
                 "-ss", f"{tc:.3f}", "-i", str(video),
                 "-vf", vf_chain(lut), "-frames:v", "1", "-q:v", JPEG_Q,
                 str(out_jpg)], timeout=180)
    except subprocess.TimeoutExpired:
        return False
    # не .exists(): битый файл тоже существует
    return r.returncode == 0 and jpeg_ok(out_jpg)


# ───────────────────────────────────────────────── приёмка кадра числами ──

def load_rgb(jpg_path):
    return np.asarray(Image.open(jpg_path).convert("RGB"), dtype=np.float32)


def frame_stats(rgb):
    """YMIN/YMAX/YAVG по готовому JPEG — тот же смысл, что
    `ffprobe -f lavfi -i "movie=<jpg>,signalstats"`, но без 832 лишних процессов
    (массив мы всё равно открываем для face_metrics).

    ⚠️ JPEG всегда 8-битный, поэтому шкала буквально 0..255. На 10-битном ВЫХОДЕ
    ФИЛЬТРА signalstats отдал бы 0..1023 (замер: YMAX 1015) — читать пороги
    тикета по видео нельзя, только по JPEG.
    """
    y = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    return {"ymin": int(y.min()), "ymax": int(y.max()),
            "yavg": round(float(y.mean()), 2)}


def orig_verdict(st):
    """Ориг-кадр — база сравнения. Если мёртв он сам, сэмпл бесполезен целиком."""
    if st["ymin"] == st["ymax"]:
        return "flat"                      # ровная заливка: ffmpeg не доехал до кадра
    if st["ymax"] - st["ymin"] < 6 or st["yavg"] < 2 or st["yavg"] > 253:
        return "blank"
    return "ok"


def frame_verdict(orig_st, st):
    """Отличаем «ffmpeg отдал чёрное» от «сцена честно тёмная».

    ⚠️ Порог тикета YMAX−YMIN ≥ 60 — абсолютный, и он ложно валит храм:
    DJI_20260918083358_0017_D @2s, ориг 31..83 (размах 52), под лутами 18/33/50.
    Кадры верные, ffmpeg отработал. На 61 храмовом клипе такая приёмка
    обесценила бы себя, поэтому критерий ОТНОСИТЕЛЬНЫЙ: вариант сравнивается со
    своим ориг-кадром того же сэмпла, а абсолютный пол оставлен на заливку.
    Буквальные пороги тикета живут в --strict-frames как аудит.
    """
    if st["ymin"] == st["ymax"]:
        return "flat"                      # ровная заливка — единственная поломка
    span, span0 = st["ymax"] - st["ymin"], orig_st["ymax"] - orig_st["ymin"]
    if span < max(6, 0.25 * span0):        # лут съел >75 % размаха оригинала
        return "crushed"
    # ⚠️ Абсолютного пола по яркости у ВАРИАНТА быть не может. Замер 21.09:
    # в храме 01_bright_scene опускает среднюю с 24 до 1, сохраняя размах
    # (блики остаются) — это не сбой ffmpeg, а «лут не для этого кадра».
    # Двенадцать клипов из-за абсолютного порога попали в «кадр не снялся»
    # и подняли ложную тревогу. Меряем ОТНОСИТЕЛЬНО оригинала.
    if st["yavg"] < max(2.0, 0.15 * orig_st["yavg"]):
        return "crushed"
    if st["yavg"] > 253:
        return "blown"
    return "ok"


def strict_ok(st):
    """Буквальный критерий тикета: YMAX−YMIN ≥ 60 и 12 < YAVG < 200."""
    return (st["ymax"] - st["ymin"]) >= 60 and 12 < st["yavg"] < 200


# ─────────────────────────────────────────────────────── обход исходников ──

def scene_clips(sdir):
    """Клипы сцены РЕКУРСИВНО: 01_Source/{scene}/{CAM-*}/файл.MP4.

    ⚠️ До 21.09.2026 здесь был нерекурсивный sdir.glob("*.MP4"). На YTCH13 клипы
    лежали прямо в папке сцены, и это работало; на YTEVO03 между сценой и клипом
    есть уровень камеры — скрипт находил 0 клипов, писал пустой план и выходил с
    кодом 0. Тихий провал, видимый только в Premiere.
    Sound/ и Transcription/ отсеиваются по расширению, .LRF — тоже.
    """
    found = {}
    for p in sdir.rglob("*"):
        if p.name.startswith(".") or p.suffix.lower() not in VIDEO_EXT:
            continue
        found.setdefault(p.name, []).append(p)
    dups = {n: v for n, v in found.items() if len(v) > 1}
    if dups:
        # ключ плана — "сцена/файл.MP4", камеры в нём нет: одинаковые имена
        # внутри одной сцены затёрли бы друг друга молча
        sys.exit(f"Дубли имён файлов внутри сцены {sdir.name} — ключ плана стал бы "
                 "неоднозначным:\n  " +
                 "\n  ".join(str(x) for v in dups.values() for x in sorted(v)))
    return [v[0] for _, v in sorted(found.items())]


def cam_of(clip, source):
    """Имя камеры = промежуточная папка между сценой и файлом ('' если её нет)."""
    parts = clip.relative_to(source).parts       # (scene, CAM-A_FX3, file.MP4)
    return parts[1] if len(parts) >= 3 else ""


def frame_src(clip, source, mirror):
    """Откуда декодировать. План всегда адресует ОРИГИНАЛ — он поедет в Premiere.

    Оригиналы YTEVO03 — 449 симлинков на /Volumes/SD-V90-RYA, карту дёргать
    нельзя (на ней держится весь проект), и кадр с неё идёт 0.72–0.84 с против
    0.28–0.34 с с прокси. Прокси HEVC Main10 3840×2160 ~12 Мбит/с, LUT в него НЕ
    вшит — образ лог-плоский и идентичен оригиналу (замер FX3-1234 @5s: ориг
    YAVG 235/1023, прокси 58.9/255 — та же точка шкалы).
    """
    if not mirror:
        return clip, "orig"
    cand = mirror / clip.relative_to(source)
    if cand.exists():
        return cand, "proxy"
    for ext in (".MP4", ".mp4", ".mov", ".MOV"):   # перекодировщик мог сменить регистр
        alt = cand.with_suffix(ext)
        if alt.exists():
            return alt, "proxy"
    return clip, "fallback"


def sony_gamma(clip):
    """Sony кладёт рядом сайдкар {stem}M01.XML — гамма берётся ОТТУДА, а не
    угадывается по модели камеры (MEDIAPRO.XML, к слову, про камеру врёт).
    Файл ~2 КБ, карту это не нагружает.
    Проверено: RYA-FX3-1229M01.XML → CaptureGammaEquation value="s-log3-cine".
    """
    x = clip.with_name(clip.stem + "M01.XML")
    if not x.exists():
        return None
    m = re.search(r'CaptureGammaEquation"?\s+value="([^"]+)"',
                  x.read_text(encoding="utf-8", errors="ignore"))
    return m.group(1) if m else None


def dji_gamma(clip):
    """DJI — тег контейнера. ⚠️ В прокси его НЕТ: перекодировщик стёр теги, в
    format_tags остались только major_brand/encoder. Значит читаем ОРИГИНАЛ —
    это ffprobe по header'у, не полный проход файла.
    """
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "format_tags=com.dji.camera.ColorGammaSxS",
             "-of", "default=nw=1:nk=1", str(clip)], timeout=60)
    return r.stdout.strip() or None


def probe_pixfmt(clip):
    """pix_fmt + color_range оригинала — единственный способ узнать битность.
    В прокси всё yuv420p10le, по нему 8-битный источник не виден.
    """
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=pix_fmt,color_range", "-of", "csv=p=0", str(clip)], timeout=60)
    parts = [p for p in r.stdout.strip().split(",") if p]
    return (parts[0] if parts else ""), (parts[1] if len(parts) > 1 else "")


# ───────────────────────────────────────────────────── лицо и метрики ──

def detect_face(jpg_path):
    """Largest face bbox as (x, y, w, h) in pixels (top-left origin), or None."""
    if not HAVE_VISION:
        return None
    url = NSURL.fileURLWithPath_(str(jpg_path))
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if src is None:
        return None
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    if img is None:
        return None
    w, h = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
    req = Vision.VNDetectFaceRectanglesRequest.alloc().init()
    ok, _err = handler.performRequests_error_([req], None)
    if not ok or not req.results():
        return None
    best = max(req.results(),
               key=lambda o: o.boundingBox().size.width * o.boundingBox().size.height)
    bb = best.boundingBox()  # normalized, origin bottom-left
    return (int(bb.origin.x * w),
            int((1.0 - bb.origin.y - bb.size.height) * h),
            int(bb.size.width * w),
            int(bb.size.height * h))


def face_metrics(rgb, bbox, core=FACE_CORE):
    """Mean luma / saturation / clip share over the central `core` of bbox.

    core=FACE_CORE (0.70) для лица — края bbox Vision захватывают волосы и фон.
    core=1.0 для фолбэка «весь кадр»: там обрезать нечего, и «весь кадр» должен
    означать буквально весь кадр, а не центральные 49 % его площади.
    """
    x, y, w, h = bbox
    pad_x, pad_y = w * (1 - core) / 2, h * (1 - core) / 2
    x0, x1 = int(max(0, x + pad_x)), int(min(rgb.shape[1], x + w - pad_x))
    y0, y1 = int(max(0, y + pad_y)), int(min(rgb.shape[0], y + h - pad_y))
    if x1 <= x0 or y1 <= y0:
        return None
    patch = rgb[y0:y1, x0:x1]
    r, g, b = patch[..., 0], patch[..., 1], patch[..., 2]
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    mx = patch.max(axis=2)
    mn = patch.min(axis=2)
    sat_px = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)

    # ⚠️ Насыщенность на почти чёрном пикселе — шум, а не цвет: (max−min)/max у
    # RGB (8,3,2) даёт 0.75. Замер 21.09 на 06_Lunch/RYA-ZVE1-1892: под
    # 01_bright_scene лицо уходит в яркость 7.4, а «насыщенность» показывает
    # 52.7 % — формула выдавала ей 73.9 очка бонуса, и ЧЁРНОЕ лицо выигрывало у
    # нормально экспонированного (81.3 против 65.6). Поэтому насыщенность
    # меряется только по освещённым пикселям, а на совсем тёмном пятне
    # обнуляется. На нормально снятом лице (YTCH13) освещены практически все
    # пиксели — прежнее поведение сохраняется.
    lit = mx >= SAT_FLOOR
    lit_share = float(lit.mean())
    sat = float(sat_px[lit].mean()) if lit_share >= SAT_MIN_SHARE else 0.0

    return {
        "luma": float(luma.mean()),
        "sat": sat,
        "lit": round(lit_share, 3),
        "clip": float((mx >= CLIP_THRESHOLD).mean()),
    }


def score_of(m):
    return W_LUMA * m["luma"] + W_SAT * 255.0 * m["sat"] - W_CLIP * m["clip"]


def verdict_of(means):
    """Вердикт только при явном перевесе. Возвращает (lut, margin, flag).

    ⚠️ Старый код: best = -1e9 и `v["score"] > best`. Если все варианты дали
    одинаково (чёрные кадры, лут не применился), тихо побеждал ПЕРВЫЙ по
    порядку — то есть 01_bright_scene на всех клипах подряд. По HTML это не
    видно: карточки выглядят нормально, а план уже испорчен.
    """
    if not means:
        return None, 0.0, "no_score"
    order = sorted(means.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(order) == 1:
        return order[0][0], 0.0, None
    margin = order[0][1] - order[1][1]
    if margin < TIE_EPS:
        # НЕ оставляем None: клип без записи в plan останется в Premiere вообще
        # без слоя. Ставим безопасную середину и помечаем — Роман увидит её в
        # секции «Смотри первым».
        safe = DEFAULT_LUT if DEFAULT_LUT in means else order[0][0]
        return safe, margin, "tie"
    return order[0][0], margin, None


# ──────────────────────────────────────────────────────────── json и версия ──

def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def write_json_atomic(path, data):
    """tmp + os.replace: ночью некому чинить наполовину записанный JSON."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


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


def stamp(plan_path, bump=True):
    """Версия и дата-время — обязательная подпись документа.

    Роман открывает страницу по нескольку раз за сессию, и без номера непонятно,
    свежая это вкладка или вчерашняя — правки уходят вслепую. Обязана быть видна
    в ТРЁХ местах: title, бейдж под h1, подвал.
    Образец: 0120_day_ingest/common_day.py:173-196 — читать, но НЕ импортировать:
    там CODE/DAY/WORK прибиты к одному дню на уровне модуля.
    Счётчик живёт в самом плане (doc_version) — отдельный файл состояния не нужен.
    """
    try:
        n = int(read_json(plan_path).get("doc_version") or 0)
    except Exception:
        n = 0
    n = max(n + (1 if bump else 0), 1)
    t = time.localtime()
    when = (f"обновлено {t.tm_mday} {MONTHS_RU[t.tm_mon - 1]} {t.tm_year}, "
            f"{t.tm_hour:02d}:{t.tm_min:02d}")
    return n, f"v{n}", when


# ───────────────────────────────────────────────────────────── round-trip ──

def load_feedback(spec):
    raw = sys.stdin.read() if spec == "-" else Path(spec).read_text(encoding="utf-8")
    raw = raw.strip()
    if raw.startswith("```"):                 # из чата часто прилетает в заборе
        raw = re.sub(r"^```[a-z]*\n|\n```$", "", raw)
    try:
        fb = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"Не разобрал фидбек как JSON: {e}\nПервые 200 символов:\n{raw[:200]}")
    if fb.get("type") != "lut_feedback":
        sys.exit(f"Это не фидбек панели: type={fb.get('type')!r}")
    return fb


def apply_feedback(plan_path, fb, lut_names):
    """Влить выбор человека в существующий план. Без ffmpeg и Vision."""
    if not Path(plan_path).exists():
        sys.exit(f"Нет плана {plan_path} — сперва прогони скоринг.")
    doc = read_json(plan_path)
    plan, clips = doc.get("plan", {}), doc.get("clips", {})
    if not plan:
        sys.exit(f"{Path(plan_path).name}: plan пустой — вливать некуда.")

    by_base = {}
    for k in plan:
        by_base.setdefault(k.split("/")[-1], []).append(k)

    changed, same, unknown, badlut = [], 0, [], []
    for raw_key, lut in (fb.get("choices") or {}).items():
        if lut not in lut_names:
            badlut.append(f"{raw_key} → {lut}")
            continue
        key = raw_key if raw_key in plan else None
        if key is None:                       # фидбек мог прийти по basename
            cand = by_base.get(raw_key.split("/")[-1], [])
            key = cand[0] if len(cand) == 1 else None
        if key is None:
            unknown.append(raw_key)
            continue
        if lut == plan[key]:
            same += 1
            continue
        changed.append((key, plan[key], lut, (clips.get(key) or {}).get("scores") or {}))

    # частично влитый фидбек хуже невлитого — либо всё, либо ничего
    if badlut:
        sys.exit("Неизвестные LUT в фидбеке:\n  " + "\n  ".join(badlut[:20]) +
                 f"\nЗнаю только: {', '.join(lut_names)}")
    if unknown:
        sys.exit(f"В фидбеке {len(unknown)} клипов, которых нет в плане:\n  " +
                 "\n  ".join(unknown[:20]) +
                 "\nПроект перепутан или план пересобран — вливать опасно.")

    print(f"Фидбек: {len(changed)} изменено, {same} совпало со счётом, "
          f"{len(plan) - len(changed) - same} не тронуто.")
    for key, was, now, sc in sorted(changed):
        if sc:
            d = sc.get(now, 0.0) - sc.get(was, 0.0)
            tail = (f"счёт {sc.get(was, 0):.0f} → {sc.get(now, 0):.0f} ({d:+.0f})" +
                    ("  ← Роман пошёл ПРОТИВ счёта" if d < 0 else ""))
        else:
            tail = "(счётов в плане нет — старый формат)"
        print(f"  {key}\n      {was} → {now}\n      {tail}")
        plan[key] = now
        if key in clips:
            clips[key].setdefault("machine", was)
            flags = clips[key].setdefault("flags", [])
            if "overridden" not in flags:
                flags.append("overridden")

    doc["plan"] = plan
    if clips:
        doc["clips"] = clips
    doc["approved"] = f"user lut_feedback {time.strftime('%Y-%m-%d')}"
    if fb.get("notes"):
        doc.setdefault("notes", {}).update(fb["notes"])
    doc.setdefault("feedback_history", []).append({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "changed": len(changed), "same": same,
        "diff": [{"clip": k, "was": w, "now": n} for k, w, n, _ in changed],
    })
    bak = backup(plan_path)
    write_json_atomic(plan_path, doc)
    print(f"\nPLAN:     {plan_path}")
    print(f"BACKUP:   {bak}")
    print(f"APPROVED: {doc['approved']}")


# ─────────────────────────────────────────────────────────────────── HTML ──

CSS = """
:root { color-scheme: dark; }
body { background:#0A0D16; color:#E8ECF4; font:14px/1.5 -apple-system,'SF Pro Text',
       Helvetica,Arial,sans-serif; margin:0; padding:32px 40px 130px; }
h1 { font-size:22px; font-weight:700; margin:0 0 6px; }
h1 .ver { font-size:12px; font-weight:700; color:#0A0D16; background:#C6FF4F;
          border-radius:9px; padding:2px 9px; vertical-align:middle; margin-left:10px; }
.sub { color:#8A93A6; margin-bottom:22px; max-width:940px; }
.kpis { display:flex; gap:26px; flex-wrap:wrap; margin:0 0 26px; }
.kpi .v { font:700 19px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace; color:#C6FF4F; }
.kpi .l { font-size:11px; color:#8A93A6; }
.banner { border-radius:10px; padding:12px 16px; margin:0 0 26px; max-width:940px;
          font-size:13px; line-height:1.55; }
.banner.warn { background:#2A210E; border:1px solid #6B5320; color:#F2D79A; }
.banner.info { background:#121826; border:1px solid #2A3347; color:#A9B4C8; }
.first { border:1px solid #6B5320; border-radius:12px; padding:18px 20px 6px;
         margin:0 0 42px; background:#15120A; }
.first > h2 { color:#F2B02A; }
.scene { margin-bottom:52px; }
.scene > h2 { font-size:17px; font-weight:700; margin:0 0 4px; border-bottom:1px solid #2A3347;
              padding-bottom:8px; }
.scene .cnt { font-size:12px; font-weight:400; color:#8A93A6; margin-left:10px; }
.camhead { font:600 12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;
           color:#7D8CA0; margin:18px 0 10px; }
.camhead .note { font-family:-apple-system,sans-serif; font-weight:400; color:#F2B02A; }
.clip { margin:0 0 26px 0; }
.cliphead { display:flex; align-items:center; gap:10px; margin-bottom:8px; flex-wrap:wrap; }
.cliphead .fname { font:700 14px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace; }
.badge { display:inline-block; padding:1px 9px; border-radius:10px; font-size:11px;
         font-weight:700; background:#1B2231; color:#8A93A6; }
.badge.warn { background:#3A2D0E; color:#F2B02A; }
.badge.bad  { background:#3A1712; color:#F2603C; }
.badge.ok   { background:#1F2E12; color:#C6FF4F; }
.badge.dim  { background:#1B2231; color:#6B7689; }
.chip { display:inline-block; padding:3px 12px; border-radius:13px; font-size:12px;
        border:1px solid #2A3347; color:#8A93A6; cursor:pointer; margin-right:6px;
        user-select:none; }
.chip.sel { background:#C6FF4F; color:#0A0D16; border-color:#C6FF4F; font-weight:700; }
.sample { display:flex; gap:10px; margin-bottom:10px; overflow-x:auto; }
.var { flex:0 0 auto; width:226px; cursor:pointer; border-radius:8px; padding:4px; }
.var img { width:100%; border-radius:6px; display:block; background:#000; }
.var.winner img { outline:2px dashed #5A6B8C; }
.var.sel { background:#18202F; }
.var.sel img { outline:2px solid #C6FF4F; }
.var.dead img { outline:2px solid #F2603C; }
.cap { font-size:11px; color:#8A93A6; margin:4px 0 0; }
.cap b { color:#E8ECF4; }
.cap .win { color:#C6FF4F; }
.note { color:#5A6B8C; font-size:11px; margin-top:2px; }
.scene-note { width:520px; max-width:90%; background:#121826; border:1px solid #2A3347;
              border-radius:8px; color:#E8ECF4; padding:7px 12px; font-size:13px;
              margin-top:6px; }
.bar { position:fixed; left:0; right:0; bottom:0; background:#0E1320EE;
       border-top:1px solid #2A3347; padding:12px 40px; display:flex; gap:16px;
       align-items:center; backdrop-filter:blur(6px); }
.bar button { background:#C6FF4F; color:#0A0D16; border:0; border-radius:10px;
              padding:9px 22px; font-size:14px; font-weight:700; cursor:pointer; }
.bar .state { color:#8A93A6; font-size:13px; }
#fb-out { position:fixed; left:40px; right:40px; bottom:70px; height:140px;
          background:#121826; color:#C6FF4F; border:1px solid #2A3347;
          border-radius:10px; padding:10px; font:12px/1.4 ui-monospace,Menlo,monospace;
          display:none; }
.foot { margin-top:56px; padding-top:16px; border-top:1px solid #1E2434;
        color:#5A6B8C; font-size:12px; line-height:1.7; }
.foot b { color:#8A93A6; }
"""


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_clip(rec, lut_names, files_dirname):
    """Одна карточка клипа. Используется и в сценах, и в «Смотри первым»,
    поэтому состояние живёт в choices[] по data-id — дубликаты синхронны сами."""
    cid = rec["key"]
    out = []
    chips = "".join(
        f"<span class='chip' data-id='{esc(cid)}' data-lut='{esc(l)}' "
        f"onclick='pick(this)'>{esc(l)}</span>" for l in lut_names)
    badges = [f"<span class='badge'>счёт: {esc(rec['verdict'] or '—')}</span>"]
    if rec.get("cam"):
        badges.append(f"<span class='badge dim'>{esc(rec['cam'])}</span>")
    for fl in rec.get("flags", []):
        text, cls = FLAG_BADGE.get(fl, (fl, "dim"))
        if fl == "tie":
            text = f"ничья {rec.get('margin', 0):.1f} — взята середина"
        badges.append(f"<span class='badge {cls}'>{esc(text)}</span>")
    out.append("<div class='clip'><div class='cliphead'>"
               f"<span class='fname'>{esc(rec['name'])}</span>"
               + "".join(badges) + f"<span>{chips}</span></div>")
    for smp in rec["samples"]:
        out.append("<div class='sample'>")
        for var in smp["variants"]:
            m = var.get("metrics")
            st = var.get("stats")
            if m:
                cap = (f"<b>{esc(var['name'])}</b> · Y {m['luma']:.0f} · "
                       f"S {m['sat'] * 100:.0f}% · пережог {m['clip'] * 100:.1f}%"
                       + (f" · <span class='win'>{var['score']:.0f}</span>"
                          if var["name"] != "orig" else ""))
                if m.get("lit", 1.0) < 0.5:
                    cap += (f"<br><span style='color:#F2B02A'>освещено лишь "
                            f"{m['lit'] * 100:.0f}% пятна</span>")
            else:
                cap = f"<b>{esc(var['name'])}</b> · —"
            if st:
                cap += f"<br><span style='color:#5A6B8C'>Y {st['ymin']}–{st['ymax']}</span>"
            fv = var.get("frame")
            if fv and fv != "ok":
                text, colour = FRAME_NOTE.get(fv, (fv, "#F2603C"))
                cap += f" <span style='color:{colour}'>{esc(text)}</span>"
            cls = " winner" if var["name"] == smp.get("winner") else ""
            if fv in FRAME_BROKEN:
                cls += " dead"
            click = (f" data-id='{esc(cid)}' data-lut='{esc(var['name'])}' onclick='pick(this)'"
                     if var["name"] != "orig" else "")
            img = (f"<img src='{files_dirname}/{esc(var['img'])}' loading='lazy'>"
                   if var.get("img") else "<img>")
            out.append(f"<div class='var{cls}'{click}>{img}<div class='cap'>{cap}</div></div>")
        out.append("</div>")
        tail = f"@ {smp['tc']:.1f}s"
        if smp.get("roi") == "frame":
            tail += " · лицо не найдено — счёт по всему кадру"
        elif smp.get("roi") == "face":
            tail += " · счёт по лицу"
        out.append(f"<div class='note'>{tail}</div>")
    out.append("</div>")
    return "\n".join(out)


def build_html(code, scenes_data, lut_names, out_dir, files_dirname,
               badge, when, stats, tiers, frames_from, lut_dir):
    by_key = {}
    for sd in scenes_data:
        for rec in sd["clips"]:
            by_key[rec["key"]] = rec

    defaults = {k: r["verdict"] for k, r in by_key.items() if r["verdict"]}

    parts = [
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<link rel='icon' href=\"{FAVICON}\">",
        f"<title>{code} · подбор LUT · {badge}</title><style>{CSS}</style></head><body>",
        f"<h1>{code} — какой LUT на какой клип <span class='ver'>{badge}</span></h1>",
        "<div class='sub'>Выбор — <b>по каждому клипу отдельно</b>: клик по карточке кадра "
        "или чипу у клипа. Предвыбран фаворит счёта (пунктир); твой выбор — сплошная "
        "рамка. Счёт по лицу: яркость + насыщенность − пережог (Apple Vision, офлайн). "
        "Внизу — «Скопировать фидбек»: вставь JSON в чат.<br>"
        "<b>Это превью, а не цветокоррекция</b> — кадры нужны только чтобы выбрать.</div>",
    ]

    parts.append("<div class='kpis'>" + "".join(
        f"<div class='kpi'><div class='v'>{v}</div><div class='l'>{l}</div></div>"
        for v, l in (
            (stats["clips"], "клипов"),
            (stats["samples"], "сэмплов"),
            (stats["noface"], "без лица"),
            (stats["tie"], "ничьих"),
            (stats["frame_suspect"], "кадр не снялся"),
            (stats["gamma_mismatch"], "чужая гамма"),
        )) + "</div>")

    # Счёт вырождается, когда противовес не включается: если пережога нет нигде,
    # «яркость + насыщенность − пережог» сводится к «кто светлее», а светлее
    # всегда тот лут, который вытягивает. Молчать об этом нельзя — иначе
    # предвыбор читается как «так лучше», хотя он значит «так светлее».
    verdicts = collections.Counter(r["verdict"] for sd in scenes_data
                                   for r in sd["clips"] if r["verdict"])
    if verdicts:
        top_lut, top_n = verdicts.most_common(1)[0]
        idle = stats.get("clip_idle", 0)
        if top_n / max(1, stats["clips"]) > 0.55 and idle / max(1, stats["clips"]) > 0.55:
            parts.append(
                "<div class='banner info'><b>Как читать предвыбор.</b> Счёт — это "
                "«яркость + насыщенность − пережог». У "
                f"<b>{idle} клипов из {stats['clips']}</b> пережога практически нет, "
                "штраф весит меньше порога ничьей и решить ничего не может — "
                "счёт сводится к <b>«кто светлее»</b>. Светлее всегда тот лут, который "
                f"вытягивает, отсюда <b>{esc(top_lut)} у {top_n} клипов</b>. "
                "Это значит «светлее», а не «лучше»: <code>03_dark_scene</code> платит "
                "за подъём примерно третью насыщенности — сравни столбец <b>S</b> под "
                "кадрами. <b>Предвыбор здесь — отправная точка, а не рекомендация:</b> "
                "глаз решает лучше счёта, для того и кадры рядом.</div>")

    if stats["gamma_mismatch"]:
        parts.append(
            "<div class='banner warn'><b>⚠️ "
            f"{stats['gamma_mismatch']} клипов DJI Pocket сняты в D-Log2</b>, а луты собраны "
            "в Resolve под <b>S-Log3 / S-Gamut3.Cine</b>. Любой выбор здесь — компромисс: "
            "насыщенность под лутом 4–12 % против 16–22 % у FX3. Это <b>чужая цветовая "
            "наука, а не «тусклая сцена»</b> — счёт для них считается, но вердикту доверять "
            "нельзя, нужен отдельный куб D-Log2 → Rec.709.</div>")

    if any(recs for _, recs, _, _ in tiers):
        top = sum(len(r) for _, r, _, c in tiers if not c)
        parts.append(f"<div class='first'><h2>Смотри первым — {top} клипов</h2>"
                     "<div class='sub'>По убыванию ненадёжности вердикта. Эти же карточки "
                     "повторяются ниже в своих сценах — выбор синхронный, править можно "
                     "где угодно.</div>")
        for title, recs, why, collapsed in tiers:
            if not recs:
                continue
            head = (f"<b>{esc(title)} — {len(recs)}</b><br>"
                    f"<span class='note'>{esc(why)}</span>")
            if collapsed:
                parts.append(f"<details><summary style='cursor:pointer;margin:18px 0 10px'>"
                             f"{head}</summary>")
            else:
                parts.append(f"<div style='margin:18px 0 10px'>{head}</div>")
            for rec in recs:
                parts.append(f"<div class='camhead'>{esc(rec['scene'])} · "
                             f"{esc(rec.get('cam') or '—')}</div>")
                parts.append(render_clip(rec, lut_names, files_dirname))
            if collapsed:
                parts.append("</details>")
        parts.append("</div>")

    for sd in scenes_data:
        n = len(sd["clips"])
        parts.append(f"<div class='scene'><h2>{esc(sd['scene'])}"
                     f"<span class='cnt'>клипов {n}</span></h2>")
        cams = {}
        for rec in sd["clips"]:
            cams.setdefault(rec.get("cam") or "—", []).append(rec)
        for cam, recs in sorted(cams.items()):
            note = ""
            if CAM_PROFILE.get(cam, ("", "", ""))[2] == "mismatch":
                gamma = CAM_PROFILE[cam][0]
                note = (f"<span class='note'> — снято в {gamma}, лут не его: "
                        "вердикт условен</span>")
            parts.append(f"<div class='camhead'>{esc(cam)} · {len(recs)}{note}</div>")
            for rec in recs:
                parts.append(render_clip(rec, lut_names, files_dirname))
        parts.append(f"<input class='scene-note' data-scene='{esc(sd['scene'])}' "
                     f"placeholder='заметка по сцене {esc(sd['scene'])} (не обязательно)'>")
        parts.append("</div>")

    parts.append(
        f"<div class='foot'><b>{code} · подбор LUT · версия {badge}</b> · {when}<br>"
        f"кадры сняты из: {esc(frames_from)}<br>"
        f"луты: {esc(lut_dir)} · {esc(' · '.join(lut_names))}<br>"
        f"клипов {stats['clips']} · сэмплов {stats['samples']} · "
        f"кадров {stats['frames']} · счёт по лицу (Apple Vision, офлайн)</div>")

    parts.append(f"""
<textarea id='fb-out' readonly></textarea>
<div class='bar'>
  <button onclick='copyFeedback()'>&#128203; Скопировать фидбек</button>
  <span class='state' id='fb-state'>LUT выбирается по каждому клипу — предвыбраны фавориты счёта</span>
</div>
<script>
var PROJECT = {json.dumps(code)};
var choices = {json.dumps(defaults, ensure_ascii=False)};
function refresh() {{
  document.querySelectorAll('.chip').forEach(function (c) {{
    c.classList.toggle('sel', choices[c.dataset.id] === c.dataset.lut);
  }});
  document.querySelectorAll('.var[data-lut]').forEach(function (v) {{
    v.classList.toggle('sel', choices[v.dataset.id] === v.dataset.lut);
  }});
}}
function pick(el) {{ choices[el.dataset.id] = el.dataset.lut; refresh(); }}
function copyFeedback() {{
  var notes = {{}};
  document.querySelectorAll('.scene-note').forEach(function (n) {{
    if (n.value.trim()) notes[n.dataset.scene] = n.value.trim();
  }});
  var payload = JSON.stringify({{ type: 'lut_feedback', project: PROJECT,
                                  choices: choices, notes: notes }}, null, 2);
  var out = document.getElementById('fb-out');
  out.value = payload; out.style.display = 'block'; out.select();
  var done = false;
  try {{ done = document.execCommand('copy'); }} catch (e) {{}}
  if (!done && navigator.clipboard) {{
    navigator.clipboard.writeText(payload).then(function () {{ mark(true); }},
                                               function () {{ mark(false); }});
  }} else {{ mark(done); }}
}}
function mark(ok) {{
  document.getElementById('fb-state').textContent = ok
    ? 'скопировано — вставь в чат Claude'
    : 'авто-копирование не удалось — текст выделен, нажми Cmd+C';
}}
refresh();
</script></body></html>""")

    html_path = out_dir / f"{code}_lut_review.html"
    html_path.write_text("\n".join(parts), encoding="utf-8")
    return html_path


# ─────────────────────────────────────────────────────────────────── main ──

def main():
    ap = argparse.ArgumentParser(
        description="Подбор LUT по лицу, по каждому клипу. Ревью-HTML + план для UXP.")
    ap.add_argument("--project", required=True)
    ap.add_argument("--frames-from", metavar="DIR", default=None,
                    help="снимать кадры из зеркала исходников (прокси). Раскладка "
                         "обязана 1:1 совпадать с 01_Source. Ключи плана и clips[*].src "
                         "всё равно пишутся ПО ОРИГИНАЛАМ.")
    ap.add_argument("--jobs", type=int, default=4,
                    help="параллельных ffmpeg (default 4; один ffmpeg берёт ~2 ядра)")
    ap.add_argument("--refresh-frames", action="store_true",
                    help="перерисовать кадры, даже если JPEG на месте "
                         "(обязательно после смены vf_chain — иначе останется старый кэш)")
    ap.add_argument("--strict-frames", action="store_true",
                    help="аудит: показать, сколько кадров не проходят буквальные пороги "
                         "тикета (YMAX−YMIN ≥ 60, 12 < YAVG < 200). Прогон не валит.")
    ap.add_argument("--probe-originals", action="store_true",
                    help="читать гамму и битность из ОРИГИНАЛОВ (единственное, что "
                         "трогает карту). Без флага гамма берётся из CAM_PROFILE.")
    ap.add_argument("--feedback", metavar="FILE|-",
                    help="влить {type:lut_feedback,...} из панели в существующий план")
    ap.add_argument("--force", action="store_true",
                    help="пересчитать, даже если план уже утверждён")
    ap.add_argument("--keep-approved", action="store_true",
                    help="с --force: сохранить утверждённый выбор для старых клипов")
    ap.add_argument("--dry-run", action="store_true",
                    help="посчитать и напечатать, но не писать ни план, ни HTML")
    args = ap.parse_args()

    project = Path(args.project)
    if not project.is_dir():
        sys.exit(f"Нет такого проекта: {project}")
    code_m = re.match(r"^(YT[A-Z]{2,4}\d+)_", project.name)
    code = code_m.group(1) if code_m else project.name

    source = project / "01_Source"
    lut_dir = source / "00_LUT"
    if not lut_dir.is_dir():
        lut_dir = source / "LUT"

    def lut_key(p):
        for i, k in enumerate(LUT_ORDER):
            if k in p.stem:
                return (i, p.stem)
        return (len(LUT_ORDER), p.stem)

    luts = sorted(lut_dir.glob("*.cube"), key=lut_key)
    if not luts:
        sys.exit(f"No .cube LUTs in {lut_dir}")
    lut_names = [l.stem for l in luts]

    out_dir = project / "00_Setup" / "01_Ingest"
    plan_path = out_dir / f"{code}_lut_plan.json"

    # ── ветка round-trip: выходим ДО любого сканирования папок ──
    if args.feedback:
        apply_feedback(plan_path, load_feedback(args.feedback), lut_names)
        return

    # ── guard ДО первого ffmpeg: минуту считать и только потом упереться глупо ──
    old = read_json(plan_path)
    if old.get("approved") and not args.force and not args.dry_run:
        sys.exit(
            f"{plan_path.name} уже утверждён: {old['approved']}\n"
            f"({len(old.get('plan', {}))} клипов). Пересчёт затрёт ручные правки.\n"
            f"  влить новый фидбек      → --feedback <файл|->\n"
            f"  пересчитать, сохранив   → --force --keep-approved\n"
            f"  пересчитать с нуля      → --force\n"
            f"  посмотреть без записи   → --dry-run")

    files_dirname = f"{code}_lut_review_files"
    files_dir = out_dir / files_dirname
    if not args.dry_run:
        files_dir.mkdir(parents=True, exist_ok=True)
    elif not files_dir.is_dir():
        files_dir.mkdir(parents=True, exist_ok=True)   # кадры нужны и для dry-run

    if not source.is_dir():
        sys.exit(f"Нет {source} — это точно проект YTAI?")
    scene_dirs = sorted(d for d in source.iterdir()
                        if d.is_dir() and re.match(r"^\d\d_", d.name)
                        and not d.name.startswith("00_"))
    if not HAVE_VISION:
        print("WARN: pyobjc Vision недоступен — метрики по ВСЕМУ кадру у ВСЕХ клипов",
              file=sys.stderr)

    mirror = Path(args.frames_from).expanduser() if args.frames_from else None
    if mirror and not mirror.is_dir():
        sys.exit(f"Нет зеркала {mirror}")

    # ── фаза 0: собрать записи ──
    records = []
    for sdir in scene_dirs:
        for clip in scene_clips(sdir):
            src, kind = frame_src(clip, source, mirror)
            records.append({
                "key": f"{sdir.name}/{clip.name}",
                "scene": sdir.name, "name": clip.name, "cam": cam_of(clip, source),
                "orig": clip, "src": src, "srckind": kind,
                "samples": [], "flags": [], "verdict": None, "margin": 0.0,
            })

    if not records:
        sys.exit(
            f"В {source} не найдено ни одного клипа — план не написан.\n"
            f"Сцены, которые я видел: {', '.join(d.name for d in scene_dirs) or '—'}\n"
            f"Искал рекурсивно {sorted(VIDEO_EXT)} внутри каждой сцены.\n"
            f"Пустой lut_plan.json писать нельзя: UXP-панель молча не поставит ни "
            f"одного слоя, и это будет видно только в Premiere.")

    missed = [r["key"] for r in records if r["srckind"] == "fallback"]
    if mirror and missed:
        print(f"WARN: {len(missed)}/{len(records)} клипов нет в зеркале — читаю "
              f"оригинал с карты. Первые 5: {missed[:5]}", file=sys.stderr)
        if len(missed) > len(records) * 0.10:
            sys.exit(f"В {mirror} нет {len(missed)} из {len(records)} клипов — похоже, "
                     f"это не то зеркало. Проверь --frames-from.")

    print(f"{code}: сцен {len(scene_dirs)}, клипов {len(records)}, "
          f"лутов {len(luts)} ({', '.join(lut_names)})")
    print(f"кадры из: {mirror if mirror else source}")

    # ── фаза 0.5: точки сэмплирования (ffprobe по тому файлу, что декодируем) ──
    print("считаю длительности…", flush=True)
    for rec in records:
        for si, tc in enumerate(clip_sample_points(rec["src"])):
            base = f"{rec['scene']}_{rec['orig'].stem}_s{si}"
            variants = [{"name": "orig", "lut": None,
                         "img": f"{base}_orig.jpg", "path": files_dir / f"{base}_orig.jpg"}]
            for lut in luts:
                variants.append({"name": lut.stem, "lut": lut,
                                 "img": f"{base}_{lut.stem}.jpg",
                                 "path": files_dir / f"{base}_{lut.stem}.jpg"})
            rec["samples"].append({"tc": tc, "variants": variants, "noface": False,
                                   "winner": None})

    all_jobs = [(rec, smp, var) for rec in records for smp in rec["samples"]
                for var in smp["variants"]]
    todo = [j for j in all_jobs
            if args.refresh_frames or not jpeg_ok(j[2]["path"])]
    n_samples = sum(len(r["samples"]) for r in records)
    print(f"кадров: {len(all_jobs)} всего ({n_samples} сэмплов), "
          f"{len(all_jobs) - len(todo)} из кэша, {len(todo)} рисуем "
          f"в {args.jobs} поток(ов)")

    # ── фаза 1: извлечение, параллельно ──
    if todo:
        workers = max(1, min(args.jobs, (os.cpu_count() or 4)))
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(extract_frame, rec["src"], smp["tc"], var["path"],
                              var["lut"]): (rec, smp, var)
                    for rec, smp, var in todo}
            done = 0
            for f in as_completed(futs):
                done += 1
                if not f.result():
                    rec, smp, var = futs[f]
                    var["failed"] = True
                if done % 25 == 0 or done == len(futs):
                    print(f"  {done}/{len(futs)}  ({time.time() - t0:.0f} c)", flush=True)

    # ── фаза 2: скоринг, последовательно в главном потоке ──
    print("скоринг…", flush=True)
    strict_fail = []
    for rec in records:
        totals = {n: [] for n in lut_names}
        for smp in rec["samples"]:
            cache = {}
            for var in smp["variants"]:
                if var.get("failed") or not jpeg_ok(var["path"]):
                    var["stats"], var["metrics"], var["score"] = None, None, -1e9
                    var["frame"] = "missing"
                    var["img"] = None
                    continue
                rgb = load_rgb(var["path"])
                cache[var["name"]] = rgb
                var["stats"] = frame_stats(rgb)

            orig = next((v for v in smp["variants"] if v["name"] == "orig"), None)
            ost = orig["stats"] if orig else None
            if ost is None:
                for var in smp["variants"]:
                    var.setdefault("frame", "no_base")
                rec["flags"].append("frame_suspect")
                continue
            orig["frame"] = orig_verdict(ost)
            for var in smp["variants"]:
                if var["name"] == "orig" or var.get("frame") == "missing":
                    continue
                var["frame"] = frame_verdict(ost, var["stats"])

            # третья сеть: три куба дали пиксель-в-пиксель одно ⇒ lut3d не применился
            sig = {(v["stats"]["ymin"], v["stats"]["ymax"], v["stats"]["yavg"])
                   for v in smp["variants"]
                   if v["name"] != "orig" and v.get("stats")}
            if len(luts) > 1 and len(sig) == 1:
                rec["flags"].append("luts_identical")

            if any(v.get("frame") in FRAME_BROKEN for v in smp["variants"]):
                rec["flags"].append("frame_suspect")
            if any(v.get("frame") in ("crushed", "blown") for v in smp["variants"]):
                rec["flags"].append("lut_crushed")

            if args.strict_frames:
                for v in smp["variants"]:
                    if v.get("stats") and not strict_ok(v["stats"]):
                        strict_fail.append((rec["key"], v["name"], v["stats"]))

            det_name = next((v["name"] for v in smp["variants"] if "normal" in v["name"]
                             and v["name"] in cache), None)
            det_path = None
            for v in smp["variants"]:
                if v["name"] == det_name:
                    det_path = v["path"]
            if det_path is None:
                det_path = next((v["path"] for v in smp["variants"] if v["name"] in cache),
                                None)
            bbox = detect_face(det_path) if det_path else None
            smp["noface"] = bbox is None
            smp["roi"] = "face" if bbox is not None else "frame"
            if bbox is None:
                # Лица нет — меряем ВЕСЬ КАДР, а не фиксированный прямоугольник в
                # центре. На этом дне лица нет у половины клипов (затылок за рулём,
                # интерьер храма, общие планы освящения), и центральный
                # прямоугольник в машине попадает на лобовое стекло, а не на
                # человека — счёт считался бы по небу. Весь кадр — это ровно тот
                # критерий, по которому мерили YTCH10: «самый сочный из тех, что
                # не завалил тени». Проверено: против центра расходится лишь у 14
                # клипов из 90, и на нулевых перевесах.
                # ⚠️ не `cache.get(x) or y`: numpy-массив в bool не приводится
                ref = cache.get(det_name)
                if ref is None and cache:
                    ref = next(iter(cache.values()))
                if ref is None:
                    continue
                h, w = ref.shape[0], ref.shape[1]
                bbox = (0, 0, w, h)

            core = FACE_CORE if smp["roi"] == "face" else 1.0
            best_name, best = None, None
            for var in smp["variants"]:
                rgb = cache.get(var["name"])
                m = face_metrics(rgb, bbox, core) if rgb is not None else None
                var["metrics"] = m
                var["score"] = score_of(m) if m else -1e9
                if var["name"] != "orig" and m:
                    totals[var["name"]].append(var["score"])
                    if best is None or var["score"] > best:
                        best, best_name = var["score"], var["name"]
            smp["winner"] = best_name

        # noface — только когда лица нет НИ В ОДНОМ сэмпле. Раньше флаг вешался
        # посэмплово, и клип с двумя сэмплами попадал в «без лица» из-за одного
        # промаха: 90 «безлицых» против 83 настоящих.
        scored = [s for s in rec["samples"] if s.get("roi")]
        if scored:
            miss = sum(1 for s in scored if s["roi"] == "frame")
            if miss == len(scored):
                rec["flags"].append("noface")
            elif miss:
                rec["flags"].append("face_partial")
            rec["roi"] = "frame" if miss == len(scored) else "face"

        rec["clip_max"] = max(
            [v["metrics"]["clip"] for s in rec["samples"] for v in s["variants"]
             if v.get("metrics") and v["name"] != "orig"] or [0.0])

        means = {k: (sum(v) / len(v)) for k, v in totals.items() if v}
        rec["scores"] = {k: round(v, 2) for k, v in means.items()}
        verdict, margin, flag = verdict_of(means)
        rec["verdict"], rec["margin"] = verdict, round(margin, 2)
        if flag:
            rec["flags"].append(flag)

        # гамма и битность
        cam = rec["cam"]
        gamma, gamut, domain = CAM_PROFILE.get(cam, ("", "", "unknown"))
        if args.probe_originals:
            g = sony_gamma(rec["orig"]) or dji_gamma(rec["orig"])
            if g:
                gamma = g
                domain = "match" if "log3" in g.lower() else "mismatch"
            pix, rng = probe_pixfmt(rec["orig"])
            rec["pix_fmt"], rec["color_range"] = pix, rng
            if pix and "10" not in pix:
                rec["flags"].append("eightbit")
        rec["gamma"], rec["gamut"], rec["lut_domain"] = gamma, gamut, domain
        if domain == "mismatch":
            rec["flags"].append("gamma_mismatch")

        rec["flags"] = sorted(set(rec["flags"]))

    # ── сводка ──
    stats = {
        "clips": len(records),
        "samples": n_samples,
        "frames": len(all_jobs),
        "noface": sum(1 for r in records if "noface" in r["flags"]),
        "face_partial": sum(1 for r in records if "face_partial" in r["flags"]),
        "tie": sum(1 for r in records if "tie" in r["flags"]),
        "frame_suspect": sum(1 for r in records if "frame_suspect" in r["flags"]),
        "lut_crushed": sum(1 for r in records if "lut_crushed" in r["flags"]),
        "luts_identical": sum(1 for r in records if "luts_identical" in r["flags"]),
        "gamma_mismatch": sum(1 for r in records if "gamma_mismatch" in r["flags"]),
        "clip_max_pct": round(100 * max([r.get("clip_max", 0.0) for r in records] or [0.0]), 3),
        # доля клипов, где штраф за пережог меньше порога ничьей, то есть решить
        # ничего не мог и счёт свёлся к «кто светлее»
        "clip_idle": sum(1 for r in records
                         if W_CLIP * r.get("clip_max", 0.0) < TIE_EPS),
        "eightbit": sum(1 for r in records if "eightbit" in r["flags"]),
        "no_verdict": sum(1 for r in records if not r["verdict"]),
    }

    print()
    for sdir in scene_dirs:
        recs = [r for r in records if r["scene"] == sdir.name]
        if not recs:
            continue
        summary = {}
        for r in recs:
            if r["verdict"]:
                summary[r["verdict"]] = summary.get(r["verdict"], 0) + 1
        print(f"— {sdir.name}: {len(recs)} клип(ов) → {summary}")

    total = {}
    for r in records:
        if r["verdict"]:
            total[r["verdict"]] = total.get(r["verdict"], 0) + 1
    print(f"\nвсего: {total}")
    print(f"счёт по лицу {stats['clips'] - stats['noface']} · по всему кадру "
          f"{stats['noface']} (лица нет) · ничьих {stats['tie']} · "
          f"кадр не снялся {stats['frame_suspect']} · лут давит {stats['lut_crushed']} · "
          f"чужая гамма {stats['gamma_mismatch']}"
          + (f" · 8 бит {stats['eightbit']}" if stats["eightbit"] else ""))

    if args.strict_frames:
        print(f"\n--strict-frames (аудит, прогон не валится): "
              f"{len(strict_fail)} кадров из {len(all_jobs)} не проходят буквальный "
              f"порог тикета YMAX−YMIN ≥ 60 и 12 < YAVG < 200.")
        for key, name, st in strict_fail[:15]:
            print(f"  {key} · {name}: Y {st['ymin']}–{st['ymax']} "
                  f"(размах {st['ymax'] - st['ymin']}), YAVG {st['yavg']}")
        if len(strict_fail) > 15:
            print(f"  … ещё {len(strict_fail) - 15}")
        print("  Тёмные сцены (храм) попадают сюда законно — см. frame_verdict().")

    # ── run-gate ──
    if stats["frame_suspect"] > max(3, 0.10 * len(records)):
        sys.exit(
            f"\nПодозрительных клипов {stats['frame_suspect']} из {len(records)} "
            f"({stats['frame_suspect'] / len(records):.0%}) — это не «тёмные сцены», "
            f"а сбой ffmpeg. План НЕ переписан.\nПервые 10:\n  " +
            "\n  ".join(r["key"] for r in records if "frame_suspect" in r["flags"])[:10])

    # ── «Смотри первым»: ярусами по надёжности вердикта ──
    # ⚠️ Плоский список сюда не годится: без лица половина дня (83 клипа) и ничьих
    # ещё четверть — секция «смотри первым» из 120 клипов перестаёт быть коротким
    # списком и её просто пролистывают. Поэтому два верхних яруса раскрыты, два
    # нижних свёрнуты в <details>.
    def has(r, *f):
        return any(x in r["flags"] for x in f)

    broken = [r for r in records if has(r, "frame_suspect", "luts_identical")]
    coin = [r for r in records if has(r, "noface") and has(r, "tie") and r not in broken]
    ties = [r for r in records if has(r, "tie") and r not in broken and r not in coin]
    nofaces = [r for r in records if has(r, "noface") and r not in broken and r not in coin]

    tiers = [
        ("Техника не отработала", broken,
         "кадр не снялся или все луты дали пиксель-в-пиксель одно. "
         "Вердикта здесь по сути нет.", False),
        ("Монетка: лица нет И счёт не решил", coin,
         "метрики считались по всему кадру, и перевес лучшего лута меньше "
         f"{TIE_EPS:g} очков. Поставлена безопасная середина — выбирай глазами.", False),
        ("Счёт не решил, но лицо было", ties,
         f"перевес меньше {TIE_EPS:g} очков, ROI — лицо. Поставлена середина.", True),
        ("Лица нет, но счёт решил уверенно", nofaces,
         "метрики по всему кадру (критерий «самый сочный из тех, что не завалил "
         "тени»), перевес явный.", True),
    ]
    attention = broken + coin

    scenes_data = [{"scene": d.name,
                    "clips": [r for r in records if r["scene"] == d.name]}
                   for d in scene_dirs
                   if any(r["scene"] == d.name for r in records)]

    if args.dry_run:
        print(f"\n--dry-run: ничего не записано. Было бы: {plan_path.name}, "
              f"{code}_lut_review.html, «смотри первым» {len(attention)} клипов "
              f"(+{len(ties)} ничьих и {len(nofaces)} без лица свёрнутыми).")
        return

    # ── план ──
    ver, badge, when = stamp(plan_path, bump=True)
    lut_plan = {r["key"]: r["verdict"] for r in records if r["verdict"]}

    keep_note = ""
    if args.force and args.keep_approved and old.get("plan"):
        kept = 0
        for key, was in old["plan"].items():
            if key in lut_plan and lut_plan[key] != was:
                for rec in records:
                    if rec["key"] == key:
                        rec["machine"] = lut_plan[key]
                        rec["flags"] = sorted(set(rec["flags"] + ["overridden"]))
                lut_plan[key] = was
                kept += 1
            elif key in lut_plan:
                kept += 1
        keep_note = f" · сохранено из утверждённого: {kept}"
        print(f"--keep-approved: {kept} клипов оставили утверждённый выбор")

    doc = {
        "version": 2,
        "project": project.name,
        "luts_dir": str(lut_dir),
        "scoring": "face luma+sat-clip per clip (lut_face_score.py)",
        "plan": lut_plan,

        "doc_version": ver,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "frames_from": str(mirror) if mirror else str(source),
        "clips": {
            r["key"]: {k: v for k, v in {
                "cam": r["cam"],
                "src": str(r["orig"]),
                "gamma": r["gamma"], "gamut": r["gamut"], "lut_domain": r["lut_domain"],
                "pix_fmt": r.get("pix_fmt"), "color_range": r.get("color_range"),
                "roi": r.get("roi"),          # face | frame — по чему считались метрики
                "samples": len(r["samples"]),
                "margin": r["margin"],
                "scores": r.get("scores") or {},
                "machine": r.get("machine"),
                "flags": r["flags"],
            }.items() if v not in (None, "")}
            for r in records
        },
        "attention": [r["key"] for r in attention],
        "groups": {
            "broken": [r["key"] for r in broken],
            "coinflip": [r["key"] for r in coin],
            "tie": [r["key"] for r in ties],
            "noface": [r["key"] for r in nofaces],
            "gamma_mismatch": [r["key"] for r in records if "gamma_mismatch" in r["flags"]],
            "eightbit": [r["key"] for r in records if "eightbit" in r["flags"]],
        },
        "stats": stats,
    }
    if args.force and args.keep_approved and old.get("approved"):
        doc["approved"] = old["approved"]
    for carry in ("notes", "feedback_history"):
        if old.get(carry):
            doc[carry] = old[carry]

    bak = backup(plan_path)
    write_json_atomic(plan_path, doc)

    html_path = build_html(code, scenes_data, lut_names, out_dir, files_dirname,
                           badge, when, stats, tiers,
                           str(mirror) if mirror else str(source), str(lut_dir))

    print(f"\nHTML:   {html_path}")
    print(f"PLAN:   {plan_path}  ({len(lut_plan)} клипов, {badge}{keep_note})")
    if bak:
        print(f"BACKUP: {bak}")
    print(f"\nОткрой HTML, поправь, жми «Скопировать фидбек», потом:\n"
          f"  pbpaste | python3 {Path(__file__).name} --project \"{project}\" --feedback -")


if __name__ == "__main__":
    main()
