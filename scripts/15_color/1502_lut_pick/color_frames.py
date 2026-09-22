#!/usr/bin/env python3
"""
color_frames.py — кадры: извлечение через ffmpeg, метрики по числам, лица.

Переехало дословно, без правок тела:
  из 1502_lut_pick/lut_pick.py  — блок импорта Vision (HAVE_VISION),
      CLIP_THRESHOLD, FACE_CORE, SAT_FLOOR, SAT_MIN_SHARE,
      load_rgb(), detect_face(), face_metrics();
  из 1502_lut_pick/lut_board.py — BLACK, WHITE, PROBE_W, PERCLIP_W,
      READABLE_LUMA, vf_chain_multi(), frame_ok(), extract(),
      metrics(), face_measure().

Единственное, что изменено при переезде, — по чьему имени зовутся соседи:
бывшие P.run / P.lut_arg / P.FRAME_WIDTH теперь M.run / M.lut_arg /
M.FRAME_WIDTH (модуль color_media), а P.detect_face / P.face_metrics /
P.FACE_CORE зовутся напрямую — они живут здесь же. Тела, докстринги и
комментарии посимвольно как в источниках.

⚠️ Грабли, записанные в комментариях ниже, — оплаченные замерами. Коротко:
  • frame_ok НЕ смотрит на вес файла: порог lut_pick.jpeg_ok в 4 КБ
    откалиброван под 960 px и бракует нормальные кадры 320 px;
  • vf_chain_multi вставляет exposure ПОСЛЕ первого лута и ДО остальных —
    это порядок обработки внутри Lumetri, а не произвол;
  • насыщенность меряется только по освещённым пикселям (SAT_FLOOR /
    SAT_MIN_SHARE), иначе чёрное лицо выигрывает у нормально снятого;
  • Vision — опционально: без pyobjc HAVE_VISION = False, detect_face
    возвращает None, а face_measure честно уходит в roi="frame".

Это библиотека: ни argparse, ни main(), ни print.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

import color_media as M      # noqa: E402 — папки этапов начинаются с цифры

try:
    import Vision
    import Quartz
    from Foundation import NSURL
    HAVE_VISION = True
except ImportError:
    HAVE_VISION = False

CLIP_THRESHOLD = 250   # 8-bit value counted as clipped
FACE_CORE = 0.70       # central share of the face bbox used for skin metrics
SAT_FLOOR = 16         # ниже этого max(RGB) насыщенность — шум, а не цвет
SAT_MIN_SHARE = 0.10   # освещено меньше 10 % пятна ⇒ насыщенности нет вовсе

BLACK = 6          # 8-bit max(RGB) at or below this is crushed to black
WHITE = 250        # at or above this is blown
PROBE_W = 320
PERCLIP_W = 640      # ширина кадра в сетке «по каждому клипу»
READABLE_LUMA = 30   # ниже этого в логе кадр нечитаем — решения по нему не принять


# ───────────────────────────────────────────────── приёмка кадра числами ──

def load_rgb(jpg_path):
    return np.asarray(Image.open(jpg_path).convert("RGB"), dtype=np.float32)



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



# ──────────────────────────────────────────── цепочка ffmpeg и извлечение ──

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
    base = f"scale={width or M.FRAME_WIDTH}:-2:flags=bicubic,format=gbrp10le"
    for i, lut in enumerate(luts):
        if lut:
            base += f",lut3d=file='{M.lut_arg(lut)}':interp=tetrahedral"
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
    if frame_ok(out_jpg, (width or M.FRAME_WIDTH) // 2):
        return True
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    M.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error",
           "-ss", f"{tc:.3f}", "-i", str(video), "-an",
           "-vf", vf_chain_multi(luts, width, stops), "-frames:v", "1", "-q:v", "3",
           str(out_jpg)], timeout=180)
    return frame_ok(out_jpg, (width or M.FRAME_WIDTH) // 2)


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
        bbox = detect_face(jpg)
    roi = "face" if bbox else "frame"
    if bbox is None:
        bbox = (0, 0, rgb.shape[1], rgb.shape[0])
    m = face_metrics(rgb, bbox, core=FACE_CORE if roi == "face" else 1.0)
    if m is None:
        m = {"luma": 0.0, "sat": 0.0, "lit": 0.0, "clip": 0.0}
    m["roi"] = roi
    return m
