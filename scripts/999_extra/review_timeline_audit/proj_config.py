#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проектные константы конвейера ревью — ОДНО место вместо восьми файлов.

Читает `prep_config.json` из папки со скриптами (W6 = рабочая копия инструмента).

Почему падаем, а не подставляем дефолт: до этого путь к транскрипту был зашит
в пяти файлах строкой прошлого проекта. Чужой words.json не роняет скрипты —
он молча сдвигает таймкоды и подсовывает цитаты из другого фильма, а вылезает
это через сутки, в готовом ТЗ. Явное падение с текстом дешевле.

Любой ключ перебивается переменной окружения `YTAI_<KEY>` (YTAI_WORDS, YTAI_SRC…).

Пример prep_config.json:
{
  "project":      "ytuvi02",
  "src":          "/…/cut/YTUVI02_v1.mp4",
  "words":        "/…/00_Setup/05_Review/YTUVI02_v1.words.json",
  "duration_sec": 1283,
  "chapters":     [[0, "01"], [135, "02"]],
  "ocr_anchors":  [],
  "llm_anchors":  {},
  "materials_id": "",
  "doc_id":       "1cJOFviJ…",
  "sheet_url":    ""
}
"""
import json
import os
import subprocess
import time
from pathlib import Path

W6 = Path(__file__).parent
CFG_PATH = W6 / 'prep_config.json'

_HINT = f"""
НЕТ ФАЙЛА {CFG_PATH}

Это карточка проекта: без неё скрипт не знает, какой кат разбирает, и взял бы
константы прошлого видео. Создай её (образец — в докстринге proj_config.py)
или укажи ключи через окружение: YTAI_PROJECT, YTAI_SRC, YTAI_WORDS.
"""

_cfg = {}
if CFG_PATH.exists():
    try:
        _cfg = json.loads(CFG_PATH.read_text(encoding='utf-8'))
    except Exception as ex:
        raise SystemExit(f'{CFG_PATH}: битый JSON — {ex}')


def get(key, default=None, required=False):
    """Значение ключа: окружение YTAI_<KEY> → prep_config.json → default."""
    env = os.environ.get('YTAI_' + key.upper())
    if env not in (None, ''):
        return env
    if key in _cfg:
        return _cfg[key]
    if required:
        raise SystemExit(f'{_HINT}\nНе хватает ключа «{key}».')
    return default


def _need(key):
    return get(key, required=True)


# ── идентификация проекта ──────────────────────────────────────────────────
PROJECT = _need('project')                      # ytuvi02 — им же назван каталог пауз
CODE = str(get('code', PROJECT.upper()))        # YTUVI02 — префикс выходных файлов
SRC = str(get('src', ''))                       # исходный кат (mp4)
WORDS = str(_need('words'))                     # транскрипт с пословными таймкодами

# ── длительность и ожидаемое число кадров (fps=1) ──────────────────────────
_dur = get('duration_sec')


def duration_sec():
    """Длительность ката в секундах. Из конфига, иначе спрашиваем ffprobe у файла."""
    global _dur
    if _dur:
        return float(_dur)
    if SRC and Path(SRC).exists():
        try:
            out = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=nw=1:nk=1', SRC],
                capture_output=True, text=True, timeout=30).stdout.strip()
            _dur = float(out)
            return _dur
        except Exception:
            pass
    raise SystemExit(f'{_HINT}\nНе хватает «duration_sec» (и ffprobe не смог прочитать {SRC}).')


def expect_frames():
    """Сколько кадров даст `ffmpeg fps=1`. Допуск на округление — в вызывающем коде."""
    v = get('expect_frames')
    return int(v) if v else int(duration_sec())


FRAMES_TOLERANCE = int(get('frames_tolerance', 2))

# ── главы: [[секунда, "номер"], …] ─────────────────────────────────────────
CHAPTERS = [(int(t), str(n)) for t, n in get('chapters', [[0, '01']])]


def chapter(sec):
    c = CHAPTERS[0][1] if CHAPTERS else '01'
    for t, n in CHAPTERS:
        if sec >= t:
            c = n
    return c


# ── якоря самопроверки ─────────────────────────────────────────────────────
# Тексты, которые ТОЧНО есть в этом кате (контроль дословности OCR) и известные
# опечатки, которые обязан поймать корректор. Пусто = проверка не применяется.
# На YTUVI01 якоря прошлого ката трижды забраковали технически верный прогон.
OCR_ANCHORS = list(get('ocr_anchors', []))
LLM_ANCHORS = {int(k): v for k, v in dict(get('llm_anchors', {})).items()}

# ── пороги OCR: считаем от длительности, а не числом из прошлого проекта ───
def screens_range():
    """Ожидаемый диапазон числа экранов. YTUVI01: 203 экрана на 40,7 мин = 5,0/мин."""
    v = get('screens_range')
    if v:
        return int(v[0]), int(v[1])
    mins = duration_sec() / 60.0
    return max(10, int(mins * 1.8)), int(mins * 12) + 20


def min_frames_with_text():
    """Минимум кадров с распознанным текстом. YTUVI01: ~500 на 2440 кадров."""
    v = get('min_frames_with_text')
    return int(v) if v else max(40, int(expect_frames() * 0.12))


# ── внешние идентификаторы (нужны стадиям после моделей) ───────────────────
MATERIALS_ID = str(get('materials_id', ''))     # папка Review_materials на Drive
DOC_ID = str(get('doc_id', ''))                 # сценарный Google Doc
SHEET_URL = str(get('sheet_url', ''))           # лист заметок
SHOTS_REMOTE = str(get('shots_remote', ''))
PROJECT_FOLDER_ID = str(get('project_folder_id', ''))
SPRINT_FOLDER_ID = str(get('sprint_folder_id', ''))


def need(key):
    """Идентификатор внешнего ресурса — пустой недопустим.

    Эти стадии ПИШУТ наружу: пересобирают вкладку дока целиком, заливают файлы в
    папку Drive, правят лист. Дефолт прошлого проекта здесь означал бы затёртую
    вкладку с ручными правками Романа и файлы в чужой папке — откат только через
    ревизии Google Docs. Поэтому пусто = отказ, а не фолбэк.
    """
    v = str(get(key, '') or '')
    if not v:
        raise SystemExit(
            f'В {CFG_PATH} пуст ключ «{key}».\n'
            'Эта стадия пишет во внешний ресурс (Drive / документ / лист): с пустым\n'
            'значением она ушла бы в ресурсы прошлого проекта и затёрла их.\n'
            'Заполни ключ и запусти снова.')
    return v


def folder_url(key='materials_id'):
    return f'https://drive.google.com/drive/folders/{need(key)}'


def audit_or_die(path, what='аудит экранов агентами'):
    """Результат аудита экранов. Нет файла = аудит не проходил или упал по лимиту сессии.

    Раньше каждый потребитель подставлял пустышку (`if exists else {'annotations': []}`),
    и получался «готовый» док и лист без единого ТЗ по ошибкам экранов — без строчки в логах.
    Теперь отказ; пропуск — только осознанно, через YTAI_NO_AUDIT=1 (тогда вернётся None).
    """
    path = Path(path)
    if path.exists():
        return json.load(open(path, encoding='utf-8'))
    if os.environ.get('YTAI_NO_AUDIT') == '1':
        print(f'⚠️ {path.name} нет — {what} пропущен по YTAI_NO_AUDIT=1', flush=True)
        return None
    raise SystemExit(
        f'Нет {path} — {what} ещё не проходил (или упал по лимиту сессии).\n'
        'Без него док и лист соберутся без единого ТЗ по экранам. Прогони аудит\n'
        '(s6_pack_chapters → wf_audit_v6.js → s8_apply_audit) или, если так задумано,\n'
        'запусти с YTAI_NO_AUDIT=1.')

# ── управление паузой ──────────────────────────────────────────────────────
# Контрольные файлы — на ВНУТРЕННЕМ диске: пауза снимется, даже если SSD отвалился.
CTL_DIR = Path(os.path.expanduser(str(get('ctl_dir', f'~/.cache/{PROJECT}'))))


def pause_gate(stage=''):
    """Грациозная пауза на границе экрана: пока лежит файл PAUSE — стоим.

    Второй слой паузы (SIGSTOP из ctl_prep.sh) морозит процесс мгновенно, но это
    не чекпойнт. Этот — переживает перезагрузку: флаг на диске, после рестарта
    стадия снова припаркуется, а не начнёт молотить.
    """
    flag = CTL_DIR / 'PAUSE'
    if not flag.exists():
        return False
    print(f'⏸ {stage}: пауза по флагу {flag} — жду снятия', flush=True)
    while flag.exists():
        time.sleep(5)
    print(f'▶️ {stage}: продолжаю', flush=True)
    return True


def write_json_atomic(path, data, indent=1):
    """Запись через временный файл + os.replace.

    Обычный json.dump обнуляет файл в момент открытия, до первого байта: kill в
    это окно стирал всю стадию целиком. os.replace атомарен в пределах ФС.
    """
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=indent)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def banner(stage):
    """Однострочная шапка: что за проект разбираем — видно в логе стадии."""
    print(f'[{stage}] проект {PROJECT} · кадров ожидаем {expect_frames()} · '
          f'транскрипт {Path(WORDS).name}', flush=True)
