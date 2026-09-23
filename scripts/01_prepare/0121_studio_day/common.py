#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Фундамент этапа 0121_studio_day — пути, состояние, журнал, запуск процессов.

Чем этот этап отличается от 0120_day_ingest: там съёмочный день описан
КОНСТАНТАМИ в common_day.py (CODE, DAY, CARD, PROJECT, список сцен, пороги
гейтов — всё величины YTEVO03), и перенести его на другой канал нельзя, не
переписав модуль. Здесь день описан файлом `day.json`, а код не знает ни одной
даты и ни одного имени папки.

⚠️ КРАСНАЯ ЛИНИЯ: карта открывается ТОЛЬКО на чтение. Ни одна функция здесь не
умеет писать на `card`, и стадии обязаны выводить всё в `work` или `project`.

⚠️ Функции нормировки звука и чистки расшифровки СКОПИРОВАНЫ из
`0120_day_ingest/{s2_audio,s3_transcribe}.py`, а не импортированы. Импорт
потянул бы `common_day`, который считает WORK и PROJECT на самом импорте и
молча увёл бы запись в чужой проект YTEVO03. Источник указан на месте.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


# ───────────────────────────────────────────────────────────── день ──

def load_day(path=None):
    """Прочитать описание дня. Все пути разворачиваются в абсолютные сразу."""
    p = Path(path).expanduser() if path else HERE / "day.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    for k in ("card", "work", "project", "preprod"):
        d[k] = Path(d[k]).expanduser()
    d["_file"] = p
    return d


def dirs(day):
    """Рабочие каталоги дня. Создаются здесь, чтобы стадии не спорили о раскладке."""
    w = day["work"]
    out = {"work": w, "wav16": w / "wav16", "words": w / "words",
           "logs": w / "logs", "state": w / "_state.json"}
    for k, v in out.items():
        if k != "state":
            v.mkdir(parents=True, exist_ok=True)
    return out


# ──────────────────────────────────────────────────────────── журнал ──

def log(msg, *, day=None):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if day is not None:
        try:
            f = dirs(day)["logs"] / f"{day['code']}_{time.strftime('%Y%m%d')}.log"
            with f.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def die(msg, code=2):
    print(f"\n⛔ {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


# ─────────────────────────────────────────────────────── запись json ──

def save_json(path: Path, obj):
    """Атомарно. Ночью некому чинить наполовину записанный JSON.

    ⚠️ Имя временного файла уникально на процесс: общий `.tmp` даёт гонку между
    двумя писателями — та же грабля, что уже оплачена в слое цвета.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


# ────────────────────────────────────────────────────────── процессы ──

def run(cmd, timeout=1800):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def ffprobe_json(path, extra=None):
    """ffprobe в JSON. Пустой словарь вместо исключения на битом файле.

    ⚠️ У битого огрызка петлички (32 776 Б, один заголовок) в `format` НЕТ ключа
    `duration` вовсе — не ноль, не пусто, а отсутствует. Любой разбор обязан это
    пережить значением по умолчанию, иначе индекс падает на одном мёртвом файле
    и день не разбирается.
    """
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json"]
    cmd += list(extra or [])
    cmd += [str(path)]
    r = run(cmd, timeout=300)
    if r.returncode != 0:
        return {}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}


def duration_of(doc, default=0.0):
    """Длительность из ffprobe-документа. См. предупреждение в ffprobe_json."""
    try:
        return float(doc.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────── звук: уровень ──
# Скопировано из 0120_day_ingest/s2_audio.py (gain_for/measure) — см. шапку модуля.

def measure_rms_db(path, seconds=None):
    """Средний и пиковый уровень, dBFS. Меряем RMS, НЕ пик.

    ⚠️ Петличка DJI пишет 32 бита float, и пики законно уходят ВЫШЕ 0 dBFS
    (замер 23.09 на TX01: +4,1 и +9,2 дБ). Нормировка по пику срезала бы файл
    целиком: на YTEVO03 так похоронили тридцатиминутный дубль — речь уехала на
    -54 dBFS, pyannote вернул ноль реплик, whisper — 186 слов вместо тысяч.
    Решает один порыв ветра в капсюль.
    """
    cmd = ["ffmpeg", "-nostdin", "-hide_banner"]
    if seconds:
        cmd += ["-t", str(seconds)]
    cmd += ["-i", str(path), "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"]
    r = run(cmd, timeout=900)
    import re
    mean = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
    peak = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr)
    return (float(mean.group(1)) if mean else None,
            float(peak.group(1)) if peak else None)


def gain_for(rms_db, day):
    """Усиление до целевого RMS, зажатое коридором из day.json."""
    a = day["asr"]
    if rms_db is None:
        return 0.0
    return round(max(a["gain_lo_db"], min(a["gain_hi_db"], a["target_rms_db"] - rms_db)), 2)


def afilter(gain_db):
    """Фильтр извлечения рабочей копии.

    ⚠️ `level=disabled` обязателен: по умолчанию alimiter сам подтягивает выход
    к потолку и уничтожает тот самый запас, ради которого его ставят.
    """
    return (f"volume={gain_db}dB,"
            f"alimiter=limit=0.85:level=disabled:attack=1:release=50")


def env_for_mlx():
    """Окружение для mlx-whisper: свой кэш моделей и прибитая зона времени.

    ⚠️ TZ прибивается не из аккуратности. `wordsync.parse_ct()` переводит
    UTC-метку контейнера в ЛОКАЛЬНОЕ машинное время, и если стадия уедет в
    launchd с другой зоной, весь день сместится на часы, а ниже по течению
    этого никто не заметит.
    """
    e = dict(os.environ)
    e.setdefault("HF_HOME", os.path.expanduser("~/YTAI/models/huggingface"))
    e["TZ"] = "Europe/Moscow"
    return e
