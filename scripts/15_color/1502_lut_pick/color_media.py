#!/usr/bin/env python3
"""
color_media.py — файлы, клипы, пути и метаданные источников.

Слой без тяжёлых библиотек: только стандартная библиотека. numpy / PIL / Vision
здесь не нужны и не импортируются — модуль обязан отвечать, когда съёмная карта
размонтирована, а venv_vlm не поднят.

Переехало ДОСЛОВНО:
  из lut_pick.py   — FRAME_WIDTH, VIDEO_EXT, run, ffprobe_duration, lut_arg,
                     scene_clips, cam_of, frame_src, sony_gamma, dji_gamma,
                     probe_pixfmt
  из lut_board.py  — normalize_gamma, detect_gamma

⚠️ Грабли, записанные в этом слое (подробности — в докстрингах функций):
  • scene_clips обходит сцену РЕКУРСИВНО. На YTEVO03 между сценой и клипом есть
    уровень камеры; нерекурсивный glob находил 0 клипов, писал пустой план и
    выходил с кодом 0 — тихий провал, видимый только в Premiere.
  • Дубли имён внутри одной сцены — ошибка, а не предупреждение: ключ плана
    «сцена/файл.MP4» стал бы неоднозначным. В подборщике здесь был sys.exit;
    библиотека не имеет права завершать процесс, поэтому бросается
    DuplicateClip с ТЕМ ЖЕ текстом сообщения.
  • Гамма и битность читаются с ОРИГИНАЛА, а не с прокси: перекодировщик стёр
    теги DJI, а pix_fmt в прокси всегда yuv420p10le — 8-битный источник по нему
    не виден.
  • normalize_gamma: порядок ключей в таблице НЕСУЩИЙ — "dlog2" и "dlogm" стоят
    до "dlog", иначе D-Log2 схлопнется в D-Log.
"""

import re
import subprocess
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent.parent / "1501_lut_library"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import naming as _N                      # noqa: E402
normalize_gamma = _N.normalize_gamma     # канон гаммы — один на слой, в naming.py


class DuplicateClip(Exception):
    """Внутри одной сцены два файла с одинаковым именем — ключ плана неоднозначен."""


FRAME_WIDTH = 960

VIDEO_EXT = {".mp4", ".mov"}


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


# ───────────────────────────────────────────────────────── кадры и ffmpeg ──

def lut_arg(lut):
    """Экранирование пути внутри filter-graph: слэш, двоеточие, апостроф.

    Сейчас пути чистые, но 00_LUT живёт на внешнем томе — один пробел или ':'
    в имени, и ffmpeg молча сыплет ошибкой парсинга на каждом кадре.
    Образец: 999_extra/source_light_transcode.py:48-54.
    """
    return str(lut).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


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
        raise DuplicateClip(
            f"Дубли имён файлов внутри сцены {sdir.name} — ключ плана стал бы "
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


# ────────────────────────────────────────────────────────────────── гамма ──

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




def detect_gamma(clip: Path, cam: str, recorded: dict | None = None):
    """Гамма ТОЛЬКО из измеренных метаданных. Никаких догадок по имени камеры:
    ровно эта догадка и покрасила 61 клип DJI чужой математикой.

    Порядок источников по свежести, а не по удобству: живой сайдкар → живой тег
    контейнера → запись прошлого замера. Источник всегда возвращается наружу и
    печатается в витрине, чтобы «откуда мы это знаем» было видно глазом.
    """
    if clip.exists():
        g = sony_gamma(clip)
        if g:
            return normalize_gamma(g), "сайдкар M01.XML"
        g = dji_gamma(clip)
        if g:
            return normalize_gamma(g), "тег com.dji.camera.ColorGammaSxS"
    rec = (recorded or {}).get(clip.name)
    if rec:
        return normalize_gamma(rec[0]), f"замер {rec[1]}, оригинал сейчас недоступен"
    return None, ("оригинал недоступен и в плане записи нет"
                  if not clip.exists() else "не определена")
