#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""proj_config — карточка фильма + профиль канала: ОДНО место путей и констант.

Скрипты стадии лежат в репо (`scripts/05_editing/0509_review_cycle/`), а всё
состояние фильма — в `{project}/00_Setup/05_Review/`. Раньше папка кода была и
папкой данных (W6 = Path(__file__).parent) — отсюда три расходящиеся копии
инструмента. Теперь код никогда не ищет данные рядом с собой.

Порядок поиска карточки `review_card.json`:
  1. окружение YTAI_CARD=<путь к review_card.json>
  2. окружение YTAI_PROJECT_DIR=<корень проекта> → 00_Setup/05_Review/review_card.json
  3. поиск review_card.json вверх от текущей папки (cwd внутри проекта / 05_Review)
  4. легаси: prep_config.json там же (читается с предупреждением; конверсия —
     `review.py init --from-prep-config`)

Почему падаем, а не подставляем дефолт: чужой words.json не роняет скрипты —
он молча сдвигает таймкоды и подсовывает цитаты из другого фильма, а вылезает
это через сутки, в готовом ТЗ. Явное падение с текстом дешевле.

Любой ключ перебивается переменной окружения `YTAI_<KEY>` (YTAI_WORDS, YTAI_SRC…).
Схема карточки и профиля — docs/contracts.md.
"""
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent                     # папка стадии (код)
YTAI = ROOT.parent.parent.parent                           # ~/YTAI
CARD_NAME = 'review_card.json'
LEGACY_CARD_NAME = 'prep_config.json'


# ── поиск карточки ─────────────────────────────────────────────────────────
def _find_card():
    env = os.environ.get('YTAI_CARD')
    if env:
        p = Path(env).expanduser()
        if not p.exists():
            raise SystemExit(f'YTAI_CARD={p}: файла нет')
        return p
    pd = os.environ.get('YTAI_PROJECT_DIR')
    if pd:
        base = Path(pd).expanduser() / '00_Setup' / '05_Review'
        for name in (CARD_NAME, LEGACY_CARD_NAME):
            if (base / name).exists():
                return base / name
        raise SystemExit(f'YTAI_PROJECT_DIR={pd}: нет {base / CARD_NAME}')
    cur = Path.cwd().resolve()
    for d in (cur, *cur.parents):
        for name in (CARD_NAME, LEGACY_CARD_NAME):
            if (d / name).exists():
                return d / name
        if (d / '00_Setup' / '05_Review' / CARD_NAME).exists():
            return d / '00_Setup' / '05_Review' / CARD_NAME
    return None


CARD_PATH = _find_card()

_HINT = f"""
НЕТ КАРТОЧКИ ФИЛЬМА ({CARD_NAME})

Без неё скрипт не знает, какой кат разбирает, и взял бы константы прошлого видео.
Укажи её: YTAI_CARD=<путь> или YTAI_PROJECT_DIR=<корень проекта>, либо запусти из
папки проекта. Создать: review.py init --project <path|CODE> --channel <CH> --mode cut_review
(из старой prep_config.json: --from-prep-config). Схема — docs/contracts.md.
"""

_cfg = {}
if CARD_PATH is not None:
    try:
        _cfg = json.loads(CARD_PATH.read_text(encoding='utf-8'))
    except Exception as ex:
        raise SystemExit(f'{CARD_PATH}: битый JSON — {ex}')
    if CARD_PATH.name == LEGACY_CARD_NAME:
        print(f'⚠️ читаю легаси-карточку {CARD_PATH} — конвертируй: review.py init --from-prep-config', flush=True)


def get(key, default=None, required=False):
    """Значение ключа: окружение YTAI_<KEY> → карточка → default."""
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


REVIEW_DIR = (CARD_PATH.parent if CARD_PATH is not None
              else Path(os.environ.get('YTAI_REVIEW_DIR', Path.cwd())).expanduser())


def resolve(p):
    """Путь из карточки: абсолютный как есть, относительный — от папки карточки."""
    if p in (None, ''):
        return ''
    p = Path(str(p)).expanduser()
    return str(p if p.is_absolute() else (REVIEW_DIR / p).resolve())


# ── идентификация проекта ──────────────────────────────────────────────────
PROJECT = str(_need('project'))                 # ytuvi02 — им же назван каталог пауз
CODE = str(get('code', PROJECT.upper()))        # YTUVI02 — префикс выходных файлов
CHANNEL = str(get('channel', '') or '').upper()
MODE = str(get('mode', 'cut_review'))
CUT_VERSION = str(get('cut_version', 'v1'))
PROJECT_DIR = resolve(get('project_dir', REVIEW_DIR.parent.parent if CARD_PATH else ''))
PROJECT_NAME = str(get('project_name', Path(PROJECT_DIR).name if PROJECT_DIR else CODE))
SRC = resolve(get('src', ''))                   # исходный кат (mp4)
RENDER = resolve(get('render', SRC))            # лёгкая копия для UXP (по умолчанию = src)
WORDS = resolve(_need('words'))                 # транскрипт с пословными таймкодами
FILM = str(get('film', ''))
FPS = float(get('fps', 25))
# NTSC-частоты точной дробью: 29.97 в карточке = 30000/1001 (иначе за 30 минут tc уезжает на ~2 кадра)
_NTSC = ((29.97, 30000), (23.976, 24000), (59.94, 60000))
FPS_RATIONAL = next(((num, 1001) for approx, num in _NTSC if abs(FPS - approx) < 0.01),
                    (int(FPS), 1) if FPS == int(FPS) else (FPS, 1))
FPS_EXACT = next((num / 1001 for approx, num in _NTSC if abs(FPS - approx) < 0.01), FPS)

# ── рабочие папки фильма (данные, не код) ──────────────────────────────────
WORK = Path(resolve(get('work_dir', ''))) if get('work_dir') else REVIEW_DIR / 'work' / CUT_VERSION
MONT = Path(resolve(get('pravki_dir', ''))) if get('pravki_dir') else REVIEW_DIR / 'pravki'
CLOUD = REVIEW_DIR / 'cloud'
MOCK = Path(resolve(get('mockups_dir', ''))) if get('mockups_dir') else REVIEW_DIR / 'mockups'
LOGS = REVIEW_DIR / 'logs'
for _d in (WORK, MONT, CLOUD, MOCK, LOGS):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


# ── профиль канала ─────────────────────────────────────────────────────────
def _load_profile():
    if not CHANNEL:
        return {}
    p = YTAI / 'YTs' / CHANNEL / 'review_profile.json'
    if not p.exists():
        raise SystemExit(f'Нет профиля канала {p} — создай из templates/review_profile.template.json')
    return json.loads(p.read_text(encoding='utf-8'))


PROFILE = _load_profile()


def profile(path, default=None):
    """Значение из профиля канала по пути «style.ivory»; карточка перебивает профиль
    тем же ключом с точками, заменёнными на «_» (style_ivory)."""
    override = get(path.replace('.', '_'))
    if override not in (None, ''):
        return override
    cur = PROFILE
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


# ── язык поверхностей (shared/i18n.py берёт его отсюда) ──────────────────────
def _jsonish(v, default):
    """значение из окружения YTAI_<KEY> приходит строкой — списки/словари разбираем как JSON"""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return default
    return default if v is None else v


LANG = 'en' if str(get('lang') or PROFILE.get('lang') or 'ru').strip().lower() == 'en' else 'ru'


# ── исключения: известные не-ошибки ката (дыра в футаже, недоделанные экраны) ─
def _exclusions():
    out = []
    for e in _jsonish(get('exclusions'), []) or []:
        if not isinstance(e, dict) or e.get('t0') is None or e.get('t1') is None:
            continue                                      # без таймкодов — заметка, в фильтр не идёт
        try:
            t0, t1 = float(e['t0']), float(e['t1'])
        except (TypeError, ValueError):
            continue
        out.append({'t0': min(t0, t1), 't1': max(t0, t1), 'reason': str(e.get('reason') or '')})
    return out


EXCLUSIONS = _exclusions()


def in_exclusion(t0, t1=None):
    """→ reason первого исключения, которое пересекается с [t0, t1] (границы включительно), иначе None."""
    if t0 is None:
        return None
    t0 = float(t0)
    t1 = t0 if t1 is None else float(t1)
    a, b = min(t0, t1), max(t0, t1)
    for e in EXCLUSIONS:
        if a <= e['t1'] and b >= e['t0']:
            return e['reason'] or 'exclusion'
    return None


# ── лексикон: слова, которые не опечатка и не «английский без перевода» ──────
def _lexicon():
    words = []
    for src in (PROFILE.get('lexicon'), PROFILE.get('latin_whitelist'), _jsonish(get('canon_words'), [])):
        if isinstance(src, str):
            src = [src]
        words += [str(w) for w in (src or []) if str(w).strip()]
    return {w.strip().lower() for w in words}


LEXICON = _lexicon()


# ── длительность и ожидаемое число кадров (fps=1) ──────────────────────────
_dur = get('duration_sec')


def duration_sec():
    """Длительность ката в секундах. Из карточки, иначе спрашиваем ffprobe у файла."""
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
OCR_ANCHORS = list(get('ocr_anchors', []))
LLM_ANCHORS = {int(k): v for k, v in dict(get('llm_anchors', {})).items()}


def screens_range():
    """Ожидаемый диапазон числа экранов. YTUVI01: 203 экрана на 40,7 мин = 5,0/мин."""
    v = get('screens_range')
    if v:
        return int(v[0]), int(v[1])
    mins = duration_sec() / 60.0
    return max(10, int(mins * 1.8)), int(mins * 12) + 20


def min_frames_with_text():
    v = get('min_frames_with_text')
    return int(v) if v else max(40, int(expect_frames() * 0.12))


# ── внешние идентификаторы (нужны стадиям после моделей) ───────────────────
MATERIALS_ID = str(get('materials_id', '') or '')
DOC_ID = str(get('doc_id', '') or '')
SHEET_URL = str(get('sheet_url', '') or '')
SHOTS_REMOTE = str(get('shots_remote', '') or '')
PROJECT_FOLDER_ID = str(get('project_folder_id', '') or '')
SPRINT_FOLDER_ID = str(get('sprint_folder_id', '') or '')


def need(key):
    """Идентификатор внешнего ресурса — пустой недопустим (стадия пишет наружу)."""
    v = str(get(key, '') or '')
    if not v:
        raise SystemExit(
            f'В {CARD_PATH} пуст ключ «{key}».\n'
            'Эта стадия пишет во внешний ресурс (Drive / документ / лист): с пустым\n'
            'значением она ушла бы в ресурсы прошлого проекта и затёрла их.\n'
            'Заполни ключ и запусти снова.')
    return v


def folder_url(key='materials_id'):
    return f'https://drive.google.com/drive/folders/{need(key)}'


def audit_or_die(path, what='аудит экранов агентами'):
    """Результат аудита экранов. Нет файла = аудит не проходил или упал по лимиту.
    Пропуск — только осознанно, через YTAI_NO_AUDIT=1 (тогда вернётся None)."""
    path = Path(path)
    if path.exists():
        return json.load(open(path, encoding='utf-8'))
    if os.environ.get('YTAI_NO_AUDIT') == '1':
        print(f'⚠️ {path.name} нет — {what} пропущен по YTAI_NO_AUDIT=1', flush=True)
        return None
    raise SystemExit(
        f'Нет {path} — {what} ещё не проходил (или упал по лимиту сессии).\n'
        'Без него док и лист соберутся без единого ТЗ по экранам. Прогони облачный\n'
        'проход (review.py cloud judge → collect → run --from apply) или, если так\n'
        'задумано, запусти с YTAI_NO_AUDIT=1.')


# ── управление паузой ──────────────────────────────────────────────────────
CTL_DIR = Path(os.path.expanduser(str(get('ctl_dir', f'~/.cache/{PROJECT}'))))


def pause_gate(stage=''):
    """Грациозная пауза на границе экрана: пока лежит файл PAUSE — стоим."""
    flag = CTL_DIR / 'PAUSE'
    if not flag.exists():
        return False
    print(f'⏸ {stage}: пауза по флагу {flag} — жду снятия', flush=True)
    while flag.exists():
        time.sleep(5)
    print(f'▶️ {stage}: продолжаю', flush=True)
    return True


def write_json_atomic(path, data, indent=1):
    """Запись через временный файл + os.replace (kill в окно записи не стирает стадию)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=indent)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def banner(stage):
    """Однострочная шапка: что за проект разбираем — видно в логе стадии."""
    print(f'[{stage}] проект {PROJECT} ({CHANNEL or "канал?"}) · кадров ожидаем {expect_frames()} · '
          f'транскрипт {Path(WORDS).name} · work {WORK}', flush=True)
