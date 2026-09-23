#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ночная пересборка прокси-комплекта канала с потоковой заливкой на Drive.

Зачем отдельный драйвер, когда рядом лежит proxy.py. proxy.py собирает комплект
ОДНОГО проекта и кладёт его на диск. Здесь задача другая и упирается она не в
кодек, а в арифметику места:

    оригиналов        ~1424 ГБ на пяти проектах, ~430 клипов
    комплекта выйдет  ~81 ГБ
    свободно          38 ГБ на внутреннем, 7.8 / 17 / 32 на внешних

Комплект целиком не помещается никуда. Значит собирать и хранить нельзя —
можно только собирать и сразу увозить: клип закодирован → прошёл гейт →
уехал на Drive → удалён локально. Локально в любой момент живёт лишь хвост
очереди, и этот хвост обязан быть ограничен.

⚠️ Главный замер, из которого растёт вся конструкция. Кодировщик выдаёт
~2.7–4 МБ/с прокси, заливка на длинном прогоне держит ~1.5–2 МБ/с. Кодировщик
быстрее заливки примерно вдвое. Без потолка очередь к пятому часу распухнет до
~45 ГБ при 38 ГБ свободных и уронит прогон — не «замедлит», а именно уронит,
посреди ночи, когда поправить некому. Поэтому потолок стейджинга (класс Staging)
не настройка, а несущая стена: кодировщики большую часть ночи СТОЯТ
заблокированными на reserve(), и это правильная форма прогона, а не зависание.
Сторож это знает и по стоящим кодировщикам тревогу не поднимает — он смотрит,
движутся ли байты хоть где-нибудь, включая заливку.

Что делает с каждым клипом, по-прежнему решает contract.py, и гейт из восьми
пунктов тоже его. Здесь только логистика: очередь, место, сеть, отказы, отчёт.

Порядок работы:
    1. луты        — server-side переименование на Drive к канону (трафика нет)
    2. по проектам — снимок Drive, план, кодирование с обратным давлением,
                     заливка одним потоком, удаление подтверждённого
    3. спаннеры    — вторая копия клипа делается на Drive server-side
    4. приёмка     — proxy_report.json + acceptance.md со сверкой с Drive

Запуск:
    python3 rebuild.py selftest                       чистая логика, без сети
    python3 rebuild.py --kit YTCH --dry-run           план и сколько это займёт
    caffeinate -ims python3 rebuild.py --kit YTCH     боевой прогон

⚠️ Исходное медиа не удаляется НИКОГДА. Удаляется только собранная прокси из
стейджинга и только после подтверждённой заливки. Если места не хватило —
прогон встаёт и пишет в Telegram, а не расчищает диск сам.

См. KB 3.4 /kb/proxy/, contract.py (контракт), proxy.py (сборка проекта),
kit.py (доукомплектование). Версия 1.0, 22.09.2026.
"""
import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contract as K          # noqa: E402
import kit                    # noqa: E402
import proxy                  # noqa: E402

VERSION = "1.0"

# ── конфигурация каналов ─────────────────────────────────────────────────────
#: Один словарь на все каналы. Всё, что относится к КОНКРЕТНОМУ прогону
#: (сколько потоков, какой потолок, какие проекты), живёт в CLI, а не здесь.
#: Здесь — только то, что про канал правда всегда: где лежат оригиналы,
#: куда на Drive уезжает комплект и в каком порядке Роман хочет их видеть.
KITS = {
    "YTCH": {
        "title": "YTCH — спринт 3",
        "local_root": "/Volumes/T7-Beige-RYA/YTCH",
        "remote": "gdrive",
        "team_drive": "0AL5m1S49VznzUk9PVA",
        "drive_root": "YTCH S3",
        # Порядок — приоритет Романа. Всё одним прогоном, но если ночь
        # оборвётся, готовым окажется то, что нужнее.
        "projects": [
            "YTCH12_Sveta",
            "YTCH11_Liza_Vitalik",
            "YTCH10_Anya_Yulia",
            "YTCH14_Katya",
            "YTCH13_Kirill_2",
        ],
        # Съёмочные дни, не привязанные к проекту. У них своя раскладка:
        # ЛОКАЛЬНО материал разложен по сценам, а НА DRIVE у монтажёра лежит
        # плоско в _Proxy/. Плоско и остаётся — ломать то, что у него уже
        # открыто и разослано, ради красоты дерева мы не будем.
        "extras": [
            {"name": "Masha", "local": "Masha",
             "drive": "_unassigned_footage/Masha_20260721/_Proxy"},
            {"name": "Gulya", "local": "Gulya",
             "drive": "_unassigned_footage/Gulya_20260726/_Proxy"},
        ],
    },

    # ── заготовки ────────────────────────────────────────────────────────────
    # ⚠️ Не заполнены намеренно. Объём оригиналов и место под стейджинг у этих
    # каналов НЕ считались: у YTUVI архивы на T7-Blue-2 (17 ГБ свободно), у
    # YTEVO материал съёмочных дней ещё едет. Прежде чем вписывать проекты —
    # посчитать вес комплекта (--dry-run по одному проекту) и убедиться, что
    # потолок стейджинга помещается на том, где он будет жить.
    "YTUVI": {
        "title": "YTUVI — драгоценные камни (заготовка, объём не считан)",
        "local_root": "/Volumes/T7-Blue-2-RYA/YTUVI",
        "remote": "gdrive", "team_drive": "", "drive_root": "YTUVI",
        "projects": [], "extras": [],
    },
    "YTEVO": {
        "title": "YTEVO — Эволюция (заготовка, объём не считан)",
        "local_root": "/Volumes/T9-Black-RYA/YTEVO",
        "remote": "gdrive", "team_drive": "", "drive_root": "YTEVO",
        "projects": [], "extras": [],
    },
}

#: Куда пишем всё, что должно пережить отключение SSD: лог, состояние, отчёты.
#: ⚠️ Не на внешний диск: launchd не открывает лог на /Volumes, а состояние на
#: том же томе, что и медиа, теряется ровно тогда, когда оно нужнее всего.
RUN_DIR = os.path.expanduser("~/Library/Logs/ytai/proxy_rebuild")

#: Стейджинг — рабочая площадка под собираемые прокси. Только медиа и два
#: файла-выключателя (STOP, PAUSE_UPLOAD). Всё остальное в RUN_DIR.
DEFAULT_STAGE = os.path.expanduser("~/.cache/ytai/proxy_stage")

TG_CHAT = "155880671"
TG_ENV = os.path.expanduser("~/.claude/channels/telegram-rya/.env")

#: Спаннер — продолжение длинного клипа, положенное во вторую сцену.
#: Имя ему даёт 0113_frame_align: RYA-FX3-1071__S10.MP4 — это кусок
#: RYA-FX3-1071.MP4. Кодировать его второй раз незачем: на Drive донор
#: копируется server-side, без единого байта трафика.
SPANNER_RE = re.compile(r"^(.+)__S\d+\.(MP4|MOV|mp4|mov)$")

#: Оценка веса прокси до кодирования. Замер: 1.41 ГБ → 76.9 МБ, это ×18.3.
#: Берём ×18 (чуть пессимистичнее замера) и пол в 400 МБ — короткий клип
#: весит непропорционально много из-за заголовков и первого ключевого кадра.
EST_RATIO = 18
EST_FLOOR = 400 * 1024 * 1024

STALL_MIN = 40            # столько минут БЕЗ движения байт где-либо → вмешиваемся
UPLOAD_STALL_MIN = 10     # столько минут молчит лог живого rclone → рвём соединение
PROGRESS_EVERY = 900      # строка прогресса в Telegram раз в 15 минут
SSD_GRACE_MIN = 30        # столько ждём вернувшийся SSD, дальше — стоп
QUOTA_SLEEP = 3600        # квота Drive 750 ГБ/сутки: ждать час и повторять


# ── мелочи ───────────────────────────────────────────────────────────────────
def hms(sec):
    sec = int(max(sec, 0))
    if sec >= 3600:
        return f"{sec // 3600}ч {sec % 3600 // 60:02d}м"
    return f"{sec // 60}м {sec % 60:02d}с"


def gb(n):
    return f"{n / 1e9:.1f} ГБ"


def nfc(s):
    """Drive хранит имена в NFC, macOS отдаёт в NFD. Без нормализации
    кириллические имена сцен ложно расходятся при сверке со снимком."""
    return unicodedata.normalize("NFC", s)


def parse_modtime(s):
    """ISO из rclone ('2026-09-22T18:55:36.859Z') → epoch. Нечитаемое → 0,
    то есть «старое»: так мы скорее пересоберём лишнее, чем зачтём чужое.

    ⚠️ Смещение отрезаем ПЕРВЫМ, до долей секунды. Иначе цифры смещения
    «+04:00» утекают в дробную часть ('.859' + '04' + '00' → '.859040'), время
    уезжает вперёд на величину смещения, и файл ПРОШЛОГО комплекта может
    оказаться «моложе метки старта» — то есть зачтён как собранный этой ночью.
    Ошибаться здесь можно только в сторону «старое», никогда в сторону «своё».
    """
    if not s:
        return 0.0
    t = s.strip()
    if t.endswith(("Z", "z")):
        t, off = t[:-1], "+00:00"
    else:
        # ищем смещение только в части ПОСЛЕ времени: '-' есть и в дате
        head = t[11:] if len(t) > 11 else ""
        pos = max(head.rfind("+"), head.rfind("-"))
        if pos >= 0:
            t, off = t[:11 + pos], head[pos:]
        else:
            off = "+00:00"
    if "." in t:                       # доли секунды бывают любой длины
        whole, frac = t.split(".", 1)
        frac = "".join(c for c in frac if c.isdigit())[:6]
        t = f"{whole}.{frac or '0'}"
    try:
        return datetime.fromisoformat(t + off).timestamp()
    except ValueError:
        return 0.0


def estimate_out(size, action):
    """Сколько места занять под ещё не собранный клип.

    Для copy это весь размер: байт-в-байт копия не худеет. Для encode —
    по замеренному коэффициенту, но не меньше пола."""
    if action == "copy":
        return size
    return max(size // EST_RATIO, EST_FLOOR)


# ── потолок стейджинга ───────────────────────────────────────────────────────
class Staging:
    """Обратное давление: кодировщику не дают начать, пока некуда класть.

    Инвариант: в момент ВЫДАЧИ резерва сумма выданных резервов не превышает
    потолок. Это единственная форма, в которой инвариант вообще достижим:
    файл, который уже лежит на диске, обратно не «разкодируешь», поэтому
    уточнение резерва вверх (revise) может на короткое время вывести сумму за
    потолок. На практике уточнение почти всегда идёт ВНИЗ — оценка ×18
    пессимистичнее замеренных ×18.3, а пол в 400 МБ завышает короткие клипы.
    Перебор вверх просто заставит следующий reserve подождать дольше.

    Отдельный случай — клип, который один больше всего потолка. Отказать ему
    нельзя (прогон встанет навсегда), пустить вместе с другими тоже нельзя.
    Пускаем его в одиночку: ждём, пока стейджинг опустеет, и отдаём всё.
    """

    def __init__(self, cap, log=print, floor_bytes=0, ceiling=0, stage_dir=None):
        self.cap = int(cap)
        self.log = log
        self.floor = int(floor_bytes)   # столько на томе обязано остаться свободным
        self.ceiling = int(ceiling)     # 0 = верхней границы нет
        self.stage_dir = stage_dir
        self.held = {}                 # ключ → выданные байты
        self.cv = threading.Condition()
        self.aborted = False
        self.holding = False           # пауза от сторожа свободного места
        self.waits = 0                 # сколько раз кодировщик ждал — для отчёта
        self.wait_sec = 0.0
        self.retunes = 0

    def retune(self, free_bytes=None):
        """Подогнать потолок под то, сколько места на томе НА САМОМ ДЕЛЕ.

        Фиксированный потолок плох с обеих сторон. Если места много, кодировщики
        стоят зря — а зря стоять нечему. Если диск кто-то забил, фиксированный
        потолок врёт, и прогон упрётся в «нет места» вместо того, чтобы притормозить.

        Поэтому потолок = «свободно сейчас + то, что мы уже заняли − неприкосновенный
        запас». Пол держим всегда: диск обязан остаться рабочим. Всё, что выше пола,
        отдаём под работу.
        """
        if free_bytes is None:
            if not self.stage_dir:
                return self.cap
            free_bytes = int(K.free_gb(self.stage_dir) * 1e9)
        with self.cv:
            want = free_bytes + sum(self.held.values()) - self.floor
            if self.ceiling:
                want = min(want, self.ceiling)
            want = max(want, 4 * 1024 ** 3)    # ниже 4 ГБ смысла нет: это один клип
            if abs(want - self.cap) >= 1024 ** 3:      # шевелимся от гигабайта
                old, self.cap = self.cap, int(want)
                self.retunes += 1
                self.cv.notify_all()
                self.log(f"  стейджинг: потолок {gb(old)} → {gb(self.cap)} "
                         f"(на томе свободно {gb(free_bytes)}, "
                         f"неприкосновенный запас {gb(self.floor)})")
            return self.cap

    @property
    def used(self):
        # ⚠️ Под замком. Сумму читают сторож и строка прогресса из своих
        # потоков, а кодировщики в это время правят словарь: голый
        # sum(dict.values()) однажды выпадет RuntimeError «dictionary changed
        # size during iteration» — и убьёт как раз сторожа, единственного, кто
        # следит за местом, SSD и файлом STOP. Condition держит RLock, так что
        # вызов изнутри reserve() безопасен.
        with self.cv:
            return sum(self.held.values())

    def reserve(self, key, nbytes, timeout=None):
        """Занять место. Блокируется, пока не влезет. False — прогон встаёт."""
        nbytes = int(nbytes)
        t0 = time.time()
        waited = False
        with self.cv:
            while True:
                if self.aborted:
                    return False
                fits = (self.used + nbytes) <= self.cap
                alone = (not self.held) and nbytes > self.cap
                if (fits or alone) and not self.holding:
                    if alone:
                        self.log(f"  стейджинг: {key} один больше потолка "
                                 f"({gb(nbytes)} > {gb(self.cap)}) — пускаю в одиночку")
                    self.held[key] = nbytes
                    if waited:
                        self.waits += 1
                        self.wait_sec += time.time() - t0
                    return True
                waited = True
                if not self.cv.wait(timeout=timeout if timeout else 60):
                    if timeout:
                        return False

    def revise(self, key, nbytes):
        """Оценка → реальный размер. Обычно вниз, и тогда кого-то будит."""
        with self.cv:
            if key in self.held:
                self.held[key] = int(nbytes)
                self.cv.notify_all()

    def release(self, key):
        with self.cv:
            self.held.pop(key, None)
            self.cv.notify_all()

    def hold(self, flag):
        """Пауза выдачи: сторож свободного места сливает очередь."""
        with self.cv:
            self.holding = bool(flag)
            self.cv.notify_all()

    def abort(self):
        """Разбудить всех, кто ждёт: прогон останавливается."""
        with self.cv:
            self.aborted = True
            self.cv.notify_all()


# ── отказы rclone ────────────────────────────────────────────────────────────
#: Таблица отказов. Порядок значим — первое совпадение.
#: Действия: 'wait-quota' — спать час и повторить ту же запись;
#: 'retry' — повторить сразу; 'retry-later' — подождать и повторить;
#: 'give-up' — этот клип не уедет, прогон продолжается.
# ⚠️ Пробелы в шаблонах обязательно «мягкие» (\s*). Одну и ту же беду rclone
# пишет двумя способами: машинной причиной без пробелов («rateLimitExceeded»)
# и человеческим текстом с пробелами («User rate limit exceeded»). Шаблон,
# знающий только одну форму, молча проваливается в 'other' и лечит квоту
# повтором вместо ожидания — ровно то, чего делать нельзя.
RCLONE_FAILS = (
    (r"upload\s*limit|storage\s*quota\s*exceeded"
     r"|team\s*drive\s*file\s*limit\s*exceeded|quota.*exceeded",
     "quota", "wait-quota",
     "квота Drive 750 ГБ/сутки — жду час и продолжаю с того же клипа"),
    (r"rate\s*limit\s*exceeded|too many requests|\b429\b",
     "rate", "retry-later", "Drive просит сбавить темп"),
    (r"insufficientfilepermissions|\b403\b|unauthorized|invalid_grant"
     r"|token expired|could not refresh token", "auth", "give-up",
     "прав или токена нет — сам не починю, нужен Winston"),
    (r"no such host|network is unreachable|connection reset|i/o timeout"
     r"|couldn't connect|tls handshake|eof\b|broken pipe", "network", "retry",
     "сеть моргнула"),
    (r"directory not found|object not found|\b404\b", "notfound", "retry",
     "путь не нашёлся — повторю, папка могла ещё не появиться"),
    (r"no space left|disk full", "nospace", "give-up",
     "на диске кончилось место"),
)


def classify_rclone(rc, text):
    """Почему не уехало и что с этим делать → (вид, действие, по-человечески).

    Судим по ТЕКСТУ лога, а не по коду возврата: rclone отдаёт один и тот же
    rc=1 и на квоту, и на оборванный wifi, а лечатся они по-разному."""
    low = (text or "").lower()
    for pattern, kind, action, human in RCLONE_FAILS:
        if re.search(pattern, low):
            return kind, action, human
    if rc == 0:
        return "ok", "ok", ""
    return "other", "retry", f"rclone rc={rc}, причина в логе не опознана"


# ── спаннеры ─────────────────────────────────────────────────────────────────
def spanner_plan(rels):
    """Кто из этих файлов — продолжение другого. → [(спаннер, донор)].

    Донора ищем по ИМЕНИ по всему набору, а не в той же папке: замеренный
    случай как раз межпапочный — 07_Knitting/RYA-FX3-1071__S10.MP4 сделан из
    06_Photo_Archive_Family/RYA-FX3-1071.MP4. Пути не хардкодим никогда:
    после любой перекладки сцен хардкод молча соврёт."""
    by_name = {}
    for rel in rels:
        by_name.setdefault(os.path.basename(nfc(rel)), nfc(rel))
    plan = []
    for rel in rels:
        rel = nfc(rel)
        m = SPANNER_RE.match(os.path.basename(rel))
        if not m:
            continue
        donor_name = f"{m.group(1)}.{m.group(2)}"
        donor = by_name.get(donor_name)
        if donor and donor != rel:
            plan.append((rel, donor))
    return sorted(plan)


# ── «этот файл уже сделан» ───────────────────────────────────────────────────
def already_done(rec, drive, src_size, run_started, rescan=False,
                 ratio_window=K.RATIO_WINDOW):
    """Три яруса резюма, от дешёвого к дорогому.

    (а) своё состояние — бесплатно: сами записали, что залили;
    (б) снимок Drive — подтверждает размером, что записанное правда лежит;
    (в) состояние потеряно целиком — судим по одному снимку: файл сделан ЭТИМ
        прогоном, если он моложе метки старта И отношение размеров в коридоре
        сжатия (или он байт-в-байт равен источнику — это законная copy).

    ⚠️ Старый комплект от 17.08 под ярус (в) не подходит: он старше метки.
    Так и задумано — он и должен пересобраться, ради этого всё затевалось.
    """
    rec = rec or {}
    if not rescan and rec.get("uploaded"):
        if drive is None:
            return False, "в состоянии залито, но на Drive нет"
        if rec.get("size") and int(drive.get("Size", 0)) != int(rec["size"]):
            return False, "размер на Drive разошёлся с записанным"
        return True, "залито этим прогоном (состояние + снимок)"

    if drive is None:
        return False, "на Drive нет"
    dsize = int(drive.get("Size", 0) or 0)
    if dsize <= 0:
        return False, "на Drive пусто"
    if parse_modtime(drive.get("ModTime")) < run_started:
        return False, "старее метки старта — это прошлый комплект"
    if src_size and dsize == src_size:
        return True, "байт-в-байт копия источника"
    ratio = (src_size / dsize) if dsize else 0
    lo, hi = ratio_window
    if lo <= ratio <= hi:
        return True, f"свежий и сжат в коридоре (×{ratio:.1f})"
    return False, f"сжатие ×{ratio:.1f} вне коридора {lo:g}–{hi:g}"


# ── состояние, лог, Telegram ─────────────────────────────────────────────────
class Ctx:
    """Общий контекст прогона: лог, состояние, счётчики, выключатели."""

    def __init__(self, a):
        self.a = a
        self.run_dir = RUN_DIR
        os.makedirs(self.run_dir, exist_ok=True)
        os.makedirs(a.stage, exist_ok=True)
        self.state_path = os.path.join(self.run_dir, f"state_{a.kit}.json")
        self.seed_path = os.path.join(self.run_dir, f"run_started_{a.kit}.json")
        self.jsonl_path = os.path.join(self.run_dir, f"clips_{a.kit}.jsonl")
        self.log_path = a.log or os.path.join(self.run_dir, f"rebuild_{a.kit}.log")
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.stop_reason = ""
        self._tg_seen = set()
        self._log_fh = open(self.log_path, "a", buffering=1)

        # Метка старта живёт ОТДЕЛЬНЫМ файлом, а не полем в state.json:
        # ярус (в) резюма нужен ровно тогда, когда state.json испорчен, и
        # метка обязана пережить эту порчу.
        self.run_started = self._seed()

        self.rows = []                 # строки приёмки (K.report_row)
        self.hb = {"done": 0, "total": 0, "src": 0, "dst": 0, "up": 0,
                   "t0": time.time(), "unit": "старт", "enc_sec": 0.0,
                   "up_sec": 0.0, "uploaded": 0, "failed": 0, "skipped": 0}

    # ── лог ──
    def log(self, msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        try:
            self._log_fh.write(line + "\n")
        except Exception:
            pass

    # ── Telegram ──
    def tg(self, msg, once_key=None):
        """once_key — чтобы одна и та же беда не писала в чат сто раз за ночь."""
        if self.a.no_telegram:
            return
        if once_key:
            with self.lock:
                if once_key in self._tg_seen:
                    return
                self._tg_seen.add(once_key)
        try:
            tok = ""
            for line in open(TG_ENV):
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    tok = line.split("=", 1)[1].strip()
                    break
            if not tok:
                return
            subprocess.run(["curl", "-s", "-X", "POST",
                            f"https://api.telegram.org/bot{tok}/sendMessage",
                            "-d", f"chat_id={TG_CHAT}", "-d", f"text={msg}"],
                           capture_output=True, timeout=30)
        except Exception as e:
            self.log(f"telegram не ушёл: {e}")

    # ── состояние ──
    def _seed(self):
        if os.path.exists(self.seed_path):
            try:
                return float(json.load(open(self.seed_path))["started"])
            except Exception:
                pass
        # Метку ставим на минуту раньше «сейчас»: часы Drive и Mac расходятся
        # на секунды, и файл, залитый в первую минуту, не должен оказаться
        # «старее старта» из-за этого расхождения.
        t = time.time() - 60
        if self.a.dry_run or self.a.verify_only:
            # Сухой прогон метку НЕ ставит: иначе прикидка, сделанная за день
            # до дела, задним числом решала бы, что считать «своим» файлом.
            return t
        try:
            json.dump({"started": t,
                       "at": datetime.fromtimestamp(t).isoformat(timespec="seconds"),
                       "kit": self.a.kit, "version": VERSION},
                      open(self.seed_path, "w"), ensure_ascii=False)
        except Exception:
            pass
        return t

    def state_load(self):
        if os.path.exists(self.state_path):
            try:
                return json.load(open(self.state_path))
            except Exception:
                # Испорченное состояние не чиним и не удаляем: ярус (в) резюма
                # переживёт его по снимку Drive, а файл пригодится на разборе.
                self.log("состояние не читается — резюм пойдёт по снимку Drive")
        return {}

    def state_set(self, key, val):
        """Атомарно: пишем во временный и переставляем. Падение посреди
        записи не оставит обрубок, который потом не прочитается."""
        with self.lock:
            st = self.state_load()
            st[key] = val
            tmp = self.state_path + ".tmp"
            try:
                json.dump(st, open(tmp, "w"), ensure_ascii=False, indent=0)
                os.replace(tmp, self.state_path)
            except Exception as e:
                self.log(f"состояние не записалось: {e}")

    def jsonl(self, rec):
        try:
            with self.lock:
                with open(self.jsonl_path, "a") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def halt(self, reason):
        """Остановить прогон. Всего три причины имеют на это право —
        см. requirement в шапке: нет места, пропал SSD, STOP."""
        if self.stop.is_set():
            return
        self.stop_reason = reason
        self.stop.set()
        self.log(f"!! ОСТАНОВКА: {reason}")
        self.tg(f"⛔ Прокси {self.a.kit}: прогон остановлен — {reason}")


# ── единственный экземпляр ───────────────────────────────────────────────────
def single_instance(path):
    """pid-файл плюс сверка имени процесса: номер могли переиспользовать,
    и тогда мы бы отказались стартовать из-за чужого Chrome."""
    old = None
    try:
        old = int(open(path).read().strip())
    except Exception:
        pass
    if old:
        try:
            out = subprocess.run(["ps", "-p", str(old), "-o", "command="],
                                 capture_output=True, text=True, timeout=20).stdout
            if "rebuild.py" in out:
                return False, old
        except Exception:
            pass
    open(path, "w").write(str(os.getpid()))
    return True, os.getpid()


# ── единица работы ───────────────────────────────────────────────────────────
class Unit:
    """Проект или съёмочный день: откуда брать, куда класть, как раскладывать."""

    def __init__(self, name, src_root, drive_path, stage_dir, layout="scenes"):
        self.name = name
        self.src_root = src_root
        self.drive_path = drive_path
        self.stage_dir = stage_dir
        self.layout = layout

    def rel_drive(self, rel):
        """Путь внутри комплекта на Drive. У проектов — 1:1 со сценой,
        у съёмочных дней плоско: так уже лежит у монтажёра."""
        rel = nfc(rel)
        return os.path.basename(rel) if self.layout == "flat" else rel


def build_units(a, cfg):
    stage = a.stage
    units = []
    want = [p.strip() for p in a.projects.split(",") if p.strip()] if a.projects else None
    for name in cfg["projects"]:
        if want and name not in want:
            continue
        src = os.path.join(cfg["local_root"], name, "01_Source")
        units.append(Unit(name, src,
                          f"{cfg['drive_root']}/{name}/01_Source_Proxy",
                          os.path.join(stage, name)))
    for ex in cfg.get("extras", []):
        if want and ex["name"] not in want:
            continue
        units.append(Unit(ex["name"], os.path.join(cfg["local_root"], ex["local"]),
                          f"{cfg['drive_root']}/{ex['drive']}",
                          os.path.join(stage, ex["name"]),
                          layout=a.extras_layout))
    return units


# ── Drive ────────────────────────────────────────────────────────────────────
def remote_of(cfg, path=""):
    td = f",team_drive={cfg['team_drive']}" if cfg.get("team_drive") else ""
    return f"{cfg['remote']}{td}:{path}"


def rclone_base(a, single_file=False):
    """Общие флаги. --bind auto = привязка к v4-джокеру: на этом канале
    IPv6 периодически упирается в DPI и соединение висит молча (см. память
    net-ipv6-dpi). Дешевле сразу ходить по v4.

    ⚠️ `single_file=True` для операций НАД ОДНИМ ФАЙЛОМ (`copyto`, `moveto`,
    `deletefile`). Такая команда с любым фильтром падает насмерть:

        CRITICAL: can't limit to single files when using filters

    Поймано вживую 22.09.2026 на переименовании лутов, и это же убило бы
    КАЖДУЮ заливку клипа за ночь — путь заливки идёт тем же `copyto`.
    Фильтры `--exclude` нужны только там, где rclone обходит дерево
    (`copy`, `check`, `lsjson`); при одном файле исключать нечего.
    """
    flags = ["--tpslimit", str(a.tpslimit), "--drive-chunk-size", "128M",
             "--retries", "5", "--low-level-retries", "20",
             "--timeout", "300s", "--contimeout", "60s",
             "--drive-stop-on-upload-limit"]
    if not single_file:
        flags += ["--exclude", ".DS_Store", "--exclude", "._*"]
    if a.bind == "auto":
        flags += ["--bind", "0.0.0.0"]
    elif a.bind != "off":
        flags += ["--bind", a.bind]
    return flags


def drive_snapshot(cfg, a, path, ctx, tries=3):
    """Один снимок папки комплекта: {относительный путь: запись rclone}.
    None — снимок СНЯТЬ НЕ ВЫШЛО (это не то же самое, что пустая папка).

    ⚠️ Снимок берётся РАЗ на проект. Замер: самый большой проект (904 файла)
    отдаётся за 5 секунд, весь канал — секунд за 25. А вот поклипные обращения
    к Drive по 430 клипов — это и время, и лишний повод словить rate limit.

    ⚠️ Повторяем: снимок стоит 5 секунд, а его провал стоит проекта. Моргнувший
    на этих пяти секундах wifi не должен оборачиваться пересборкой 497 ГБ уже
    лежащего на Drive материала (см. как это читает already_done: «на Drive
    нет» для пустого снимка неотличимо от «снимка нет»).
    """
    cmd = (["rclone", "lsjson", "-R", "--fast-list", "--files-only"]
           + rclone_base(a) + [remote_of(cfg, path)])
    why = ""
    for attempt in range(1, max(1, tries) + 1):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            why = "не успел за 15 минут"
            r = None
        if r is not None:
            if r.returncode == 0:
                try:
                    data = json.loads(r.stdout or "[]")
                    return {nfc(f["Path"]): f for f in data}
                except json.JSONDecodeError:
                    why = "ответ не разобрался"
            else:
                kind, _act, human = classify_rclone(r.returncode, r.stderr)
                # Пустой папки на Drive ещё нет — это законный «снимок пуст»,
                # а не сбой: первый прогон по новому проекту начинается так.
                if kind == "notfound":
                    return {}
                why = f"{kind}: {human}"
        ctx.log(f"  снимок Drive не снялся ({why}), попытка {attempt} из {tries}: {path}")
        if attempt < tries:
            time.sleep(30)
    return None


# ── заливка ──────────────────────────────────────────────────────────────────
class Uploader(threading.Thread):
    """Один поток заливки. Не два и не четыре.

    Аплинк узкий: насыщенная отдача душит всё остальное, включая собственные
    API-вызовы rclone (см. память uplink-starves-dl). Параллельные заливки
    суммарной скорости не прибавят, а очередь запутают."""

    def __init__(self, ctx, cfg, staging):
        super().__init__(daemon=True)
        self.ctx, self.cfg, self.staging = ctx, cfg, staging
        self.q = queue.Queue()
        self.bytes_up = 0
        self.last_move = time.time()
        self.paused_since = None
        #: собрано, но уехать не смогло. Место под ним НЕ освобождается —
        #: файл реально лежит на диске, и врать потолку нельзя (см. _one).
        self.stuck = {}

    # ── одна попытка ──
    def _copy_once(self, local, remote_path, logf):
        """rclone copyto по СУЩЕСТВУЮЩЕМУ пути обновляет тот же файл: ID папки
        и файла живы, а значит живы и ссылки, розданные монтажёру. Поэтому
        copyto по полному пути, а не copy в папку."""
        a = self.ctx.a
        cmd = (["rclone", "copyto", local, remote_of(self.cfg, remote_path)]
               + rclone_base(a, single_file=True)
               + ["--stats", "60s", "--stats-one-line", "-v", "--log-file", logf])
        try:
            open(logf, "w").close()
        except Exception:
            pass
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                             text=True)
        # Сторож залипшего rclone. Боевой случай 07.08: процесс жив, соединение
        # молча умерло, ни одного байта за 80 минут. Ждать бесполезно — рвём.
        stalled = {"yes": False}

        def watch():
            prev, still = -1, 0
            while p.poll() is None:
                time.sleep(30)
                try:
                    cur = os.path.getsize(logf)
                except OSError:
                    cur = prev
                if cur != prev:
                    prev, still = cur, 0
                    self.last_move = time.time()
                else:
                    still += 1
                    if still >= UPLOAD_STALL_MIN * 2:      # тики по 30 с
                        stalled["yes"] = True
                        self.ctx.log(f"  ⚠️ заливка залипла: лог не растёт "
                                     f"{UPLOAD_STALL_MIN} мин — рву соединение")
                        try:
                            p.kill()
                        except Exception:
                            pass
                        return

        w = threading.Thread(target=watch, daemon=True)
        w.start()
        try:
            _out, err = p.communicate(timeout=7200)
        except subprocess.TimeoutExpired:
            p.kill()
            _out, err = "", "заливка не уложилась в два часа"
        tail = ""
        try:
            tail = open(logf).read()[-4000:]
        except Exception:
            pass
        if stalled["yes"]:
            return 1, "stalled", "retry", "соединение залипло и было разорвано"
        kind, action, human = classify_rclone(p.returncode, (err or "") + tail)
        return p.returncode, kind, action, human

    def _verify(self, remote_path, size):
        """Убедиться, что файл лежит ТАМ и ТАКОГО размера.

        Нулевой rc у rclone почти всегда правда, но «почти» тут дорогое:
        заливка не туда с rc=0 означала бы, что монтажёр открывает старую
        прокси и ничего об этом не знает. Один --stat на клип это переживёт."""
        try:
            r = subprocess.run(["rclone", "lsjson", "--stat"] + rclone_base(self.ctx.a)
                               + [remote_of(self.cfg, remote_path)],
                               capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                return False, "проверки не вышло: " + (r.stderr or "")[:160]
            obj = json.loads(r.stdout or "{}") or {}
            got = int(obj.get("Size", -1))
            if got != int(size):
                return False, f"на Drive {got} Б вместо {size} Б"
            return True, ""
        except Exception as e:
            return False, f"проверка упала: {e}"

    # ── цикл ──
    def run(self):
        """⚠️ Этот поток не имеет права умереть. Его смерть — не «одна потерянная
        заливка», а тихий повал всего прогона: run_unit ждёт на q.join(), ждать
        будет вечно, а сторож такого не ловит — он снимает зависший ffmpeg, а не
        воскрешает заливщика. Поэтому ловим ВСЁ, включая сбой самого разбора
        ошибки, и продолжаем цикл."""
        ctx = self.ctx
        while True:
            item = self.q.get()
            if item is None:
                self.q.task_done()
                return
            try:
                self._one(item)
            except Exception as e:
                # ⚠️ Упавшую заливку ОБЯЗАТЕЛЬНО записываем в застрявшее.
                # Резерв под этот клип снять нельзя (файл лежит на диске), а
                # молча забыть про него — значит выдать потолку дыру, которую
                # никто не считает: сторож смотрит именно на stuck. Пять таких
                # исключений подряд — и потолок съеден фантомами, кодировщики
                # навсегда стоят в reserve, а тревоги нет, потому что stuck
                # пуст. Ночь проходит впустую и никто об этом не узнаёт.
                try:
                    key = (item or {}).get("key", "?")
                    ctx.log(f"  ✗ заливка упала на {key}: {e}")
                    ctx.tg(f"Прокси {ctx.a.kit}: заливка споткнулась "
                           f"({type(e).__name__}) на {key}.",
                           once_key=f"upexc:{type(e).__name__}")
                    self._mark_stuck(item or {}, f"{type(e).__name__}: {e}")
                except Exception:
                    pass
            finally:
                self.q.task_done()

    def stuck_total(self):
        """Сколько байт собрано и не уехало. Считаем под замком: словарь
        правится из этого же потока, а читают его сторож и приёмка."""
        with self.ctx.lock:
            return sum(self.stuck.values()), len(self.stuck)

    def _mark_stuck(self, item, why):
        """Клип собран, но не уехал. Место под ним остаётся занятым — оно и
        правда занято, — а сам клип попадает в счёт застрявшего, по которому
        сторож понимает, что очередь перестала сливаться."""
        ctx = self.ctx
        key, size = item.get("key", "?"), int(item.get("size") or 0)
        rec = (ctx.state_load().get(key) or {})
        rec.update({"uploaded": False, "upload_failed": True, "err": why[:300]})
        ctx.state_set(key, rec)
        with ctx.lock:
            ctx.hb["failed"] += 1
            self.stuck[key] = size
        total, _n = self.stuck_total()
        ctx.log(f"  ⚠️ {key} собран, но не уехал — остаётся в стейджинге "
                f"({gb(total)} застряло)")

    def _one(self, item):
        ctx = self.ctx
        key, local, remote_path = item["key"], item["local"], item["remote"]
        size = item["size"]
        logf = os.path.join(ctx.run_dir, "rclone_current.log")

        for attempt in range(1, 6):
            # Выключатель для Романа: не убивая прогон, придержать отдачу
            # (например, когда нужен канал под что-то ещё).
            while os.path.exists(os.path.join(ctx.a.stage, "PAUSE_UPLOAD")):
                if self.paused_since is None:
                    self.paused_since = time.time()
                    ctx.log("  заливка на паузе: в стейджинге лежит PAUSE_UPLOAD")
                self.last_move = time.time()       # пауза это не залипание
                time.sleep(30)
                if ctx.stop.is_set():
                    return
            if self.paused_since:
                ctx.log(f"  заливка снята с паузы ({hms(time.time() - self.paused_since)})")
                self.paused_since = None
            if ctx.stop.is_set():
                return

            t0 = time.time()
            rc, kind, action, human = self._copy_once(local, remote_path, logf)
            took = time.time() - t0

            if rc == 0:
                ok, why = self._verify(remote_path, size)
                if ok:
                    self.bytes_up += size
                    self.last_move = time.time()
                    with ctx.lock:
                        ctx.hb["uploaded"] += 1
                        ctx.hb["up"] += size
                        ctx.hb["up_sec"] += took
                    rec = (ctx.state_load().get(key) or {})
                    rec.update({"uploaded": True, "size": size,
                                "at": datetime.now().isoformat(timespec="seconds")})
                    ctx.state_set(key, rec)
                    ctx.log(f"  ↑ {key} — {gb(size)} за {hms(took)}")
                    # Удаляем ТОЛЬКО собранную прокси и ТОЛЬКО сейчас, когда
                    # она подтверждена на Drive. Исходное медиа не трогаем.
                    try:
                        os.remove(local)
                    except OSError:
                        pass
                    self.staging.release(key)
                    return
                ctx.log(f"  ✗ {key}: залилось, но не подтвердилось — {why}")
                kind, action, human = "mismatch", "retry", why

            ctx.log(f"  ✗ {key}: попытка {attempt} не удалась ({kind}) — {human}")
            ctx.jsonl({"key": key, "stage": "upload", "ok": False, "kind": kind,
                       "attempt": attempt, "err": human,
                       "at": time.strftime("%H:%M:%S")})
            if action == "give-up":
                ctx.tg(f"Прокси {ctx.a.kit}: {key} не уехал — {human}. "
                       f"Остальное идёт дальше.", once_key=f"giveup:{kind}")
                break
            if action == "wait-quota":
                ctx.tg(f"Прокси {ctx.a.kit}: {human} Заливка продолжится сама "
                       f"через час.", once_key="quota")
                self.last_move = time.time()
                for _ in range(QUOTA_SLEEP // 30):
                    if ctx.stop.is_set():
                        return
                    time.sleep(30)
                    self.last_move = time.time()
                continue
            if action == "retry-later":
                ctx.tg(f"Прокси {ctx.a.kit}: {human}, сбавляю темп.",
                       once_key="rate")
                time.sleep(300)
                continue
            time.sleep(min(60 * attempt, 300))

        # Все попытки кончились. Файл остаётся в стейджинге, и резерв под него
        # НЕ снимается: он занимает диск на самом деле, а потолок обязан знать
        # правду. Удалять собранную работу из-за того, что моргнула сеть, мы не
        # станем — следующей ночью резюм увидит её в состоянии и просто дольёт.
        # ⚠️ Но если такое копится, кодировщики однажды упрутся в потолок,
        # заваленный тем, что не уезжает, и встанут молча. Поэтому считаем
        # застрявшее и, когда оно съедает половину потолка, останавливаемся
        # вслух: это и есть «очередь не сливается».
        self._mark_stuck(item, human or f"{kind}: попытки кончились")


# ── сторож ───────────────────────────────────────────────────────────────────
def drain_uploads(up, ctx, why=""):
    """Дождаться, пока очередь заливки опустеет.

    ⚠️ Не q.join(). У него нет срока, и если поток заливки всё-таки умер, ждать
    придётся до утра: счётчик незавершённых задач уже не обнулится никогда,
    прогон замрёт на этой строке, и ни одно из сообщений так и не придёт.
    Смотрим не только на очередь, но и на то, жив ли тот, кто её разбирает.
    """
    while up.q.unfinished_tasks:
        if not up.is_alive():
            ctx.log(f"!! поток заливки мёртв, а в очереди осталось "
                    f"{up.q.unfinished_tasks} — дальше не жду{(' (' + why + ')') if why else ''}")
            ctx.tg(f"Прокси {ctx.a.kit}: поток заливки погиб, в очереди осталось "
                   f"{up.q.unfinished_tasks} клипов. Собранное лежит в стейджинге "
                   f"и дольётся следующим прогоном.", once_key="upderad")
            return False
        time.sleep(2)
    return True


def moving_bytes(stage):
    """Сумма недописанных .part.mp4 — видно, что кодировщик реально пишет."""
    total = 0
    for dp, _dn, fn in os.walk(stage):
        for f in fn:
            if f.endswith(K.TMP_SUFFIX) or f.endswith(".part"):
                try:
                    total += os.path.getsize(os.path.join(dp, f))
                except OSError:
                    pass
    return total


def progress_line(ctx, up):
    hb = ctx.hb
    el = time.time() - hb["t0"]
    d, t = hb["done"], max(hb["total"], 1)
    # Честный ETA считаем по ЗАЛИВКЕ, а не по кодированию: узкое место она.
    rate = (hb["up"] / hb["up_sec"]) if hb["up_sec"] > 0 else 0
    left_bytes = max(0, int((hb["dst"] / max(d, 1)) * (t - d))) if d else 0
    eta = (left_bytes / rate) if rate > 0 else 0
    ratio = (hb["src"] / hb["dst"]) if hb["dst"] else 0
    return (f"{d}/{t} клипов ({100 * d / t:.0f}%), прошло {hms(el)}"
            + (f", осталось ~{hms(eta)}" if eta else "")
            + f"; залито {hb['uploaded']}, очередь {up.q.qsize()}, "
              f"собрано {gb(hb['dst'])} (×{ratio:.1f}), "
              f"стейджинг {gb(up.staging.used)}/{gb(up.staging.cap)}, "
              f"свободно {K.free_gb(ctx.a.stage):.0f} ГБ, {hb['unit']}")


def watchdog(ctx, up, staging):
    """Сторож. Три вещи: движутся ли байты, есть ли место, не пропал ли SSD.

    ⚠️ Молчание САМО ПО СЕБЕ не признак зависания — наивный сторож по тишине
    уже убивал живой рендер (21.08, см. proxy_night.py). Здесь тем более:
    при работающем потолке кодировщики большую часть ночи СТОЯТ заблокированными,
    и на диске ничего не шевелится, пока уходит очередной файл. Поэтому
    «живо» = сдвинулся хоть один счётчик: недописанные файлы, залитые байты,
    готовые клипы.

    ⚠️ Сон машины. monotonic на macOS во сне стоит, а wall-clock идёт. Если
    между тиками wall-clock ушёл заметно дальше monotonic — машина спала, и
    это НЕ повод считать прогон залипшим: сбрасываем отсчёт и идём дальше.

    ⚠️ Сторож не имеет права умереть молча. Он единственный, кто видит место,
    SSD и файл STOP; если его поток свалится на случайной OSError (том отвалился
    ровно во время os.walk по стейджингу), прогон останется без присмотра до
    утра и никто об этом не узнает. Поэтому виток обёрнут целиком, а не по месту.
    """
    while not ctx.stop.is_set():
        try:
            _watch_loop(ctx, up, staging)
            return                     # вышел сам: либо halt, либо конец прогона
        except Exception as e:
            # Поднимаемся с чистыми счётчиками — это безопасная сторона:
            # свежий отсчёт тишины не снимет живой ffmpeg сгоряча.
            ctx.log(f"!! сторож упал ({type(e).__name__}: {e}) — поднимаю заново")
            ctx.tg(f"Прокси {ctx.a.kit}: сторож споткнулся ({type(e).__name__}), "
                   f"поднял его заново.", once_key=f"wdexc:{type(e).__name__}")
            time.sleep(30)


def _watch_loop(ctx, up, staging):
    last_report = time.time()
    prev_mark = (moving_bytes(ctx.a.stage), up.bytes_up, ctx.hb["done"])
    quiet_since = time.time()
    ssd_gone_since = None
    prev_wall, prev_mono = time.time(), time.monotonic()

    while not ctx.stop.is_set():
        time.sleep(60)
        wall, mono = time.time(), time.monotonic()
        slept = (wall - prev_wall) - (mono - prev_mono)
        prev_wall, prev_mono = wall, mono
        if slept > 120:
            ctx.log(f"  часы прыгнули на {hms(slept)} — машина спала, "
                    f"отсчёт тишины сбрасываю")
            quiet_since = time.time()

        mark = (moving_bytes(ctx.a.stage), up.bytes_up, ctx.hb["done"])
        if mark != prev_mark or (time.time() - up.last_move) < 120:
            prev_mark = mark
            quiet_since = time.time()

        # ── пропал SSD ──
        # Проверяем КОРЕНЬ канала, а не папки проектов: отсутствующая папка
        # проекта это опечатка в KITS, а отсутствующий корень — отвалившийся
        # диск. Лечатся они по-разному, и останавливать прогон стоит только
        # второе.
        if not os.path.isdir(ctx.kit_root):
            if ssd_gone_since is None:
                ssd_gone_since = time.time()
                ctx.log("  ⚠️ источник не виден — жду возвращения SSD")
                ctx.tg(f"Прокси {ctx.a.kit}: пропал SSD с оригиналами. Жду "
                       f"{SSD_GRACE_MIN} минут, потом встану.", once_key="ssd")
            elif time.time() - ssd_gone_since > SSD_GRACE_MIN * 60:
                staging.abort()
                ctx.halt(f"SSD с оригиналами не вернулся за {SSD_GRACE_MIN} минут")
                return
        elif ssd_gone_since is not None:
            ctx.log("  SSD вернулся, продолжаю")
            ssd_gone_since = None

        # ── место ──
        # Сначала подгоняем потолок под реальную обстановку: кто-то мог освободить
        # диск (тогда грех стоять) или, наоборот, забить его (тогда тормозим сами,
        # не дожидаясь аварии). Пол при этом неприкосновенен.
        free = K.free_gb(ctx.a.stage)
        staging.retune(int(free * 1e9))
        if free < ctx.a.min_free_gb:
            ctx.log(f"  ⚠️ свободно {free:.1f} ГБ — придерживаю кодировщиков "
                    f"и сливаю очередь")
            staging.hold(True)
            deadline = time.time() + 3600
            # ⚠️ STOP проверяем и здесь: иначе выключатель Романа не сработает
            # целый час — ровно тогда, когда он им скорее всего и воспользуется.
            while (up.q.unfinished_tasks and time.time() < deadline
                   and not ctx.stop.is_set()
                   and not os.path.exists(os.path.join(ctx.a.stage, "STOP"))):
                time.sleep(30)
            if os.path.exists(os.path.join(ctx.a.stage, "STOP")):
                staging.abort()
                ctx.halt("в стейджинге появился файл STOP")
                return
            free = K.free_gb(ctx.a.stage)
            if free < ctx.a.min_free_gb:
                staging.abort()
                ctx.halt(f"после слива очереди свободно всего {free:.1f} ГБ "
                         f"(нужно {ctx.a.min_free_gb}). Место сам не расчищаю.")
                return
            staging.hold(False)
            ctx.log(f"  место вернулось ({free:.0f} ГБ), кодировщики пущены")

        # ── застрявшее не даёт очереди сливаться ──
        stuck, n_stuck = up.stuck_total()
        if stuck >= staging.cap // 2:
            staging.abort()
            ctx.halt(f"{n_stuck} клипов собрано, но не уезжает "
                     f"({gb(stuck)} — половина потолка). Очередь не сливается, "
                     f"дальше кодировать некуда. Собранное лежит в стейджинге "
                     f"и дольётся следующим прогоном.")
            return

        # ── STOP ──
        if os.path.exists(os.path.join(ctx.a.stage, "STOP")):
            staging.abort()
            ctx.halt("в стейджинге появился файл STOP")
            return

        # ── настоящее залипание ──
        if time.time() - quiet_since > STALL_MIN * 60:
            ctx.log(f"!! ничего не движется {STALL_MIN} мин — снимаю ffmpeg, "
                    f"кодировщики пересоберут клип")
            ctx.tg(f"Прокси {ctx.a.kit}: конвейер молчит {STALL_MIN} мин — снял "
                   f"зависший ffmpeg, работа продолжается. {progress_line(ctx, up)}",
                   once_key=None)
            subprocess.run(["pkill", "-f", f"ffmpeg.*{ctx.a.stage}"],
                           capture_output=True)
            quiet_since = time.time()

        if time.time() - last_report > PROGRESS_EVERY:
            last_report = time.time()
            line = progress_line(ctx, up)
            ctx.log("-- " + line)
            ctx.tg(f"Прокси {ctx.a.kit}: {line}")


# ── луты ─────────────────────────────────────────────────────────────────────
def luts_step(cfg, a, ctx, units):
    """Канонические имена лутов — первым делом, до всякого кодирования.

    Переименование идёт server-side (rclone moveto в пределах одного remote):
    трафика ноль, ID файла сохраняется. Ни один .prproj не ссылается на .cube
    по пути, так что Premiere это не заметит.

    Идемпотентно: канон уже на месте и старых имён нет — «уже сделано».

    ⚠️ `--verify-only` обязан быть таким же немым, как `--dry-run`. Он заявлен
    как «ничего не делать, только сверить», и Роман зовёт его утром, чтобы
    посмотреть на итог ночи. Переименовывать и удалять при этом файлы в живом
    комплекте, уже открытом у монтажёра, — не то, на что он соглашался, нажимая
    «только сверить».
    """
    done, notes = 0, []
    quiet = a.dry_run or a.verify_only
    for u in units:
        if u.layout == "flat":
            continue            # у съёмочных дней своего 00_LUT нет
        project = u.drive_path.rsplit("/", 1)[0]     # .../{проект}
        for sub in ("01_Source/00_LUT", "01_Source_Proxy/00_LUT"):
            path = f"{project}/{sub}"
            snap = drive_snapshot(cfg, a, path, ctx)
            if snap is None:
                notes.append(f"{u.name}/{sub}: папку не прочитал")
                continue
            have = {os.path.basename(p): f for p, f in snap.items()}
            if not have:
                continue
            for old, new in kit.LUT_CANON.items():
                if old not in have:
                    continue
                src, dst = f"{path}/{old}", f"{path}/{new}"
                if new in have:
                    # Обе тройки рядом (случай YTCH13). Равные размеры —
                    # это дубль, старое имя убираем. Разные — не трогаем
                    # и говорим вслух: тут думать человеку.
                    if int(have[new]["Size"]) == int(have[old]["Size"]):
                        if quiet:
                            notes.append(f"{u.name}/{sub}: дубль {old} убрать")
                        else:
                            r = subprocess.run(["rclone", "deletefile"] + rclone_base(a, single_file=True)
                                               + [remote_of(cfg, src)],
                                               capture_output=True, text=True, timeout=300)
                            ok = r.returncode == 0
                            notes.append(f"{u.name}/{sub}: дубль {old} "
                                         + ("убран" if ok else "убрать не вышло"))
                            done += int(ok)
                    else:
                        notes.append(f"⚠️ {u.name}/{sub}: {old} и {new} РАЗНЫХ "
                                     f"размеров — не трогаю, смотреть руками")
                    continue
                if quiet:
                    notes.append(f"{u.name}/{sub}: {old} → {new}")
                    continue
                r = subprocess.run(["rclone", "moveto"] + rclone_base(a, single_file=True)
                                   + [remote_of(cfg, src), remote_of(cfg, dst)],
                                   capture_output=True, text=True, timeout=600)
                ok = r.returncode == 0
                notes.append(f"{u.name}/{sub}: {old} → {new} "
                             + ("" if ok else f"НЕ ВЫШЛО: {(r.stderr or '')[:120]}"))
                done += int(ok)
        # Локальное зеркало — тем же каноном, руками ничего не переименовываем.
        local_lut = os.path.join(u.src_root, kit.LUT_DIR)
        if os.path.isdir(local_lut):
            kit.canon_luts(local_lut, apply=not quiet, log=ctx.log)

    for n in notes:
        ctx.log(f"  лут {n}")
    if not notes:
        ctx.log("  луты: канон уже на месте — уже сделано")
    return done, notes


# ── один клип ────────────────────────────────────────────────────────────────
def one_clip(unit, src, rel, a, ctx, staging, up):
    """Снять → решить → занять место → собрать → гейт → доказательство → в очередь.

    ⚠️ Доказательство контракта пишется В МОМЕНТ ГЕЙТА, до удаления локального
    файла. Перевывести его потом с Drive нельзя: это 81 ГБ скачивания ради
    таблички. Один раз посмотрели — один раз записали."""
    key = f"{unit.name}/{unit.rel_drive(rel)}"
    if ctx.stop.is_set():
        return None
    try:
        size = os.path.getsize(src)
        spec = K.probe(src)
    except Exception as e:
        ctx.log(f"  ✗ {key}: не прочитался — {e}")
        return {"rel": rel, "status": "FAIL", "err": f"{type(e).__name__}: {e}",
                "src": src, "dst": "", "size": 0, "size_src": 0, "action": "?",
                "reason": "", "frames_src": 0, "frames_dst": 0, "dur_src": 0,
                "dur_dst": 0, "ratio": 0, "contract": {}, "attempts": 0,
                "encode_sec": 0, "speed_x": 0, "at": ""}

    dec = K.decide(spec, bitrate=K.bitrate_for(spec, override=a.bitrate), chroma="420")
    if dec.action == "skip-symlink":
        ctx.log(f"  — {key}: {dec.reason}")
        with ctx.lock:
            ctx.hb["skipped"] += 1
        return K.skipped_row(spec, dec, unit.rel_drive(rel))

    dst = os.path.join(unit.stage_dir, unit.rel_drive(rel))

    # Клип, собранный прошлой ночью и не уехавший (сеть моргнула, квота),
    # лежит тут же и уже прошёл гейт — доказательство записано в состоянии.
    # Пересобирать его значит выкинуть час работы ради того же файла.
    prev = ctx.state_load().get(key) or {}
    if (prev.get("proxy") and not prev.get("uploaded") and os.path.exists(dst)
            and prev.get("size") and os.path.getsize(dst) == int(prev["size"])):
        real = os.path.getsize(dst)
        if staging.reserve(key, real):
            ctx.log(f"  ⇧ {key}: собран прошлым прогоном и проверен — сразу в заливку")
            up.q.put({"key": key, "local": dst, "size": real,
                      "remote": f"{unit.drive_path}/{unit.rel_drive(rel)}"})
        return None

    est = estimate_out(size, dec.action)
    if not staging.reserve(key, est):
        return None                      # прогон останавливается, это не отказ клипа

    ok, err, took = False, "", 0.0
    dstspec, g, attempts = None, None, 0
    try:
        for attempt in range(1, a.retries + 2):
            attempts = attempt
            if ctx.stop.is_set():
                staging.release(key)
                return None
            if dec.action == "copy":
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                try:
                    shutil.copy2(src, dst + ".part")
                    os.replace(dst + ".part", dst)
                    ok, err, took = True, "", 0.0
                except Exception as e:
                    ok, err = False, f"копия не удалась: {e}"
            else:
                ok, err, took = proxy.do_encode(spec, dst, dec)
            if not ok:
                ctx.log(f"  ! {key}: попытка {attempt} — не собралось: {err[:160]}")
                continue
            dstspec = K.probe(dst)
            g = K.gate(spec, dstspec, unit.rel_drive(rel), unit.rel_drive(rel), dec)
            if g.ok:
                break
            ctx.log(f"  ! {key}: попытка {attempt} — {g.summary()}")
            ok = False
            if attempt <= a.retries and os.path.exists(dst):
                os.remove(dst)

        if not ok or g is None or not g.ok:
            # Не сошлось — в комплект не идёт, но и старое на Drive не портим.
            if os.path.exists(dst):
                os.remove(dst)
            row = (K.report_row(spec, dstspec, dec, g, unit.rel_drive(rel), attempts,
                                took, datetime.now().isoformat(timespec="seconds"))
                   if dstspec and g else
                   K.skipped_row(spec, dec, unit.rel_drive(rel), note="не собрался"))
            row["status"] = "FAIL"
            row["err"] = err or (g.summary() if g else "не собрался")
            row["dst"] = ""
            ctx.state_set(key, {"proxy": False, "failed": True, "err": row["err"][:300]})
            ctx.jsonl({"key": key, "stage": "encode", "ok": False,
                       "err": row["err"][:300], "at": time.strftime("%H:%M:%S")})
            ctx.tg(f"Прокси {ctx.a.kit}: клип {key} не собрался после "
                   f"{attempts} попыток. Остальные идут дальше.",
                   once_key=f"encfail:{unit.name}")
            with ctx.lock:
                ctx.hb["failed"] += 1
            staging.release(key)
            return row

        real = os.path.getsize(dst)
        row = K.report_row(spec, dstspec, dec, g, unit.rel_drive(rel), attempts, took,
                           datetime.now().isoformat(timespec="seconds"))
        # ── доказательство, пока файл ещё под рукой ──
        ctx.state_set(key, {"proxy": True, "uploaded": False, "size": real,
                            "action": dec.action, "ratio": row["ratio"],
                            "contract": {k: v["ok"] for k, v in row["contract"].items()},
                            "at": row["at"]})
        ctx.jsonl(row)

        with ctx.lock:
            ctx.hb["done"] += 1
            ctx.hb["src"] += size
            ctx.hb["dst"] += real
            ctx.hb["enc_sec"] += took
        ctx.log(f"  ✓ {key} — {dec.action}, {gb(size)}→{gb(real)} "
                f"(×{size / max(real, 1):.1f}), {hms(took)}")

        staging.revise(key, real)         # оценка → правда, обычно вниз
        up.q.put({"key": key, "local": dst, "size": real,
                  "remote": f"{unit.drive_path}/{unit.rel_drive(rel)}"})
        return row
    except Exception:
        staging.release(key)
        raise


# ── спаннеры на Drive ────────────────────────────────────────────────────────
def spanners_step(unit, cfg, a, ctx, rels):
    """Вторая копия клипа-спаннера делается НА DRIVE, server-side.

    Кодировать его повторно незачем: это тот же материал. Оба конца — один
    remote, значит копия идёт внутри Drive и трафика не стоит.

    ⚠️ Спаннера НЕТ в оригиналах. Проверено 22.09 по всем пяти проектам:
    под `01_Source` ни одного `*__S\\d+.MP4/MOV` — все `__S` там это WAV
    рекордера. Единственный видео-спаннер живёт ТОЛЬКО на Drive
    (YTCH12/07_Knitting/RYA-FX3-1071__S10.MP4). Значит искать его в списке
    локальных работ бессмысленно: план всегда выйдет пустым, шаг молча
    ничего не сделает, донор пересоберётся, а спаннер останется куском
    комплекта от 17.08 — рядом с новым донором и без единого слова об этом.
    Ищем по СНИМКУ DRIVE, донора берём оттуда же.

    Идемпотентность без книгоучёта: копируем, только если спаннера нет или
    его размер разошёлся с донором. После копии размеры равны, и следующий
    прогон по этому же признаку ничего не трогает.
    """
    # Снимок свежий: прошлый брался ДО заливки, а нам нужны новые размеры.
    snap = drive_snapshot(cfg, a, unit.drive_path, ctx)
    if snap is None:
        ctx.log("  спаннеры: снимок Drive не снялся — пропускаю шаг")
        return []
    names = list(dict.fromkeys(
        [nfc(r) for r in rels]
        + [p for p in snap if p.lower().endswith(K.VIDEO_EXT)]))
    plan = spanner_plan(names)
    if not plan:
        return []
    out = []
    for spanner, donor in plan:
        d_rec, s_rec = snap.get(donor), snap.get(spanner)
        if d_rec is None:
            ctx.log(f"  спаннер {spanner}: донора {donor} на Drive нет — пропускаю")
            out.append((spanner, donor, False))
            continue
        d_size = int(d_rec.get("Size") or 0)
        if s_rec is not None and int(s_rec.get("Size") or 0) == d_size and d_size > 0:
            ctx.log(f"  спаннер {spanner}: уже совпадает с донором — не трогаю")
            out.append((spanner, donor, True))
            continue
        src = f"{unit.drive_path}/{donor}"
        dst = f"{unit.drive_path}/{spanner}"
        if a.dry_run:
            ctx.log(f"  спаннер: {spanner} ← {donor} (server-side)")
            out.append((spanner, donor, True))
            continue
        r = subprocess.run(["rclone", "copyto"] + rclone_base(a, single_file=True)
                           + [remote_of(cfg, src), remote_of(cfg, dst)],
                           capture_output=True, text=True, timeout=1800)
        ok = r.returncode == 0
        ctx.log(f"  спаннер {spanner} ← {donor}: "
                + ("готов (server-side)" if ok else
                   f"НЕ ВЫШЛО: {(r.stderr or '')[:160]}"))
        if ok:
            ctx.state_set(f"{unit.name}/{spanner}",
                          {"proxy": True, "uploaded": True, "spanner_of": donor,
                           "size": d_size,
                           "at": datetime.now().isoformat(timespec="seconds")})
        out.append((spanner, donor, ok))
    return out


# ── проект целиком ───────────────────────────────────────────────────────────
def run_unit(unit, cfg, a, ctx, staging, up):
    ctx.hb["unit"] = unit.name
    if not os.path.isdir(unit.src_root):
        ctx.log(f"=== {unit.name}: источника нет ({unit.src_root}) — пропускаю")
        return {"unit": unit.name, "skipped": "источника нет"}

    jobs = proxy.collect(unit.src_root, unit.stage_dir)
    if not jobs:
        ctx.log(f"=== {unit.name}: клипов не найдено")
        return {"unit": unit.name, "skipped": "клипов нет"}

    # Плоская раскладка схлопывает сцены в одну папку: одинаковые имена
    # затрут друг друга молча. Лучше сказать сейчас, чем недосчитаться утром.
    seen = {}
    for _src, _dst, rel in jobs:
        n = unit.rel_drive(rel)
        if n in seen and seen[n] != rel:
            ctx.log(f"  ⚠️ {unit.name}: имя {n} встречается дважды "
                    f"({seen[n]} и {rel}) — при плоской раскладке они затрут друг друга")
        seen[n] = rel

    # ⚠️ Снимок Drive — единственный источник правды о том, что уже сделано.
    # Не снялся — НЕ делаем вид, что папка пуста: пустой снимок означает «нет
    # ничего», и проект целиком уехал бы на пересборку (для YTCH10 это 497 ГБ
    # чтения, ~28 ГБ лишней заливки и половина ночи). Раз Drive не отвечает,
    # заливать всё равно некуда — честнее пропустить проект и сказать вслух.
    snap = drive_snapshot(cfg, a, unit.drive_path, ctx)
    if snap is None:
        ctx.log(f"=== {unit.name}: снимок Drive не снялся — пропускаю проект "
                f"целиком, чтобы не пересобирать уже готовое вслепую")
        ctx.tg(f"Прокси {a.kit}: {unit.name} пропущен — Drive не отдал список "
               f"файлов, а без него не видно, что уже готово. Остальное идёт дальше.",
               once_key=f"nosnap:{unit.name}")
        return {"unit": unit.name, "skipped": "снимок Drive не снялся",
                "clips": len(jobs), "done": 0, "todo": 0, "snapshot": 0}

    state = ctx.state_load()
    todo, done_already, seen_key = [], 0, {}
    for src, _dst, rel in jobs:
        rel_d = unit.rel_drive(rel)
        key = f"{unit.name}/{rel_d}"
        # Плоская раскладка уже схлопнула два имени в одно (предупредили выше).
        # Пустить оба в работу нельзя: у них один ключ резерва, один временный
        # файл и одна запись состояния — два ffmpeg писали бы один и тот же
        # .part.mp4, а release одного освободил бы место под оба и вывел
        # стейджинг за потолок. Второй не собираем и говорим об этом в приёмке.
        if key in seen_key:
            ctx.log(f"  ✗ {key}: то же имя уже идёт из {seen_key[key]} — "
                    f"не собираю, иначе затрут друг друга")
            continue
        seen_key[key] = rel
        try:
            size = os.path.getsize(src)
        except OSError:
            size = 0
        ok, why = already_done(state.get(key), snap.get(nfc(rel_d)), size,
                               ctx.run_started, rescan=a.rescan)
        if ok:
            done_already += 1
            continue
        todo.append((src, rel, why))

    ctx.log(f"=== {unit.name}: клипов {len(jobs)}, уже готово {done_already}, "
            f"к сборке {len(todo)} · {unit.drive_path}")
    with ctx.lock:
        ctx.hb["total"] += len(todo)

    if a.verify_only or a.dry_run:
        for _src, rel, why in todo[:8]:
            ctx.log(f"   · {unit.rel_drive(rel)} — {why}")
        if len(todo) > 8:
            ctx.log(f"   … и ещё {len(todo) - 8}")
        return {"unit": unit.name, "clips": len(jobs), "done": done_already,
                "todo": len(todo), "snapshot": len(snap)}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        futs = [ex.submit(one_clip, unit, src, rel, a, ctx, staging, up)
                for src, rel, _why in todo]
        for f in futs:
            try:
                row = f.result()
            except Exception as e:
                ctx.log(f"  ✗ клип упал: {type(e).__name__}: {e}")
                row = None
            if row:
                with ctx.lock:
                    ctx.rows.append(row)

    # Ждём, пока всё собранное этим проектом уедет: только после этого можно
    # трогать спаннеров (их донор должен уже лежать на Drive) и считать итог.
    drained = drain_uploads(up, ctx, why=unit.name)
    # Прогон встал или заливщик погиб — значит донор мог не уехать. Копировать
    # поверх спаннера старого донора хуже, чем не трогать его вовсе: получится
    # пара, о которой никто не знает, что она разъехалась.
    if drained and not ctx.stop.is_set():
        spanners_step(unit, cfg, a, ctx, [unit.rel_drive(r) for _s, _d, r in jobs])

    took = time.time() - t0
    msg = (f"Прокси {a.kit}: {unit.name} готов — собрано {len(todo)}, "
           f"было готово {done_already}, за {hms(took)}. {progress_line(ctx, up)}")
    ctx.log(f"=== {unit.name}: закончен за {hms(took)}")
    ctx.tg(msg)
    return {"unit": unit.name, "clips": len(jobs), "done": done_already,
            "todo": len(todo), "sec": round(took, 1)}


# ── приёмка ──────────────────────────────────────────────────────────────────
def acceptance(cfg, a, ctx, units, unit_stats, luts, started):
    """Отчёт приёмки: машинный proxy_report.json и читаемый acceptance.md.

    Сверка «ожидали / лежит на Drive» делается по свежему снимку — по одному
    на проект. Лишнее на Drive только ПЕРЕЧИСЛЯЕМ: удалять чужое из комплекта,
    который уже открыт монтажёром, мы не станем ни при каких обстоятельствах."""
    state = ctx.state_load()
    per_unit = []
    for u in units:
        if not os.path.isdir(u.src_root):
            continue
        snap = drive_snapshot(cfg, a, u.drive_path, ctx)
        if snap is None:
            # ⚠️ Не подменяем несостоявшийся снимок пустым. Иначе приёмка
            # объявит «не долетело 151», Роман получит в Telegram ложную
            # тревогу и пойдёт ночью спасать комплект, с которым всё в порядке.
            ctx.log(f"  сверка {u.name}: Drive не отдал список — не сверено")
            per_unit.append({"unit": u.name, "drive": u.drive_path,
                             "expect": 0, "on_drive": 0, "bytes_on_drive": 0,
                             "missing": [], "mismatch": [], "extra": [],
                             "unverified": "Drive не отдал список файлов"})
            continue
        jobs = proxy.collect(u.src_root, u.stage_dir)
        expect, known, missing, mismatch = {}, set(), [], []
        # ⚠️ Спаннера нет в оригиналах — он рождается server-side на самом
        # Drive. В локальных работах его не найти, а в «лишнее» он попасть не
        # должен: это законный файл комплекта. Берём его из состояния.
        for skey, srec in state.items():
            if srec.get("spanner_of") and skey.startswith(f"{u.name}/"):
                known.add(nfc(skey[len(u.name) + 1:]))
        for src, _dst, rel in jobs:
            rel_d = nfc(u.rel_drive(rel))
            key = f"{u.name}/{rel_d}"
            rec = state.get(key) or {}
            known.add(rel_d)
            if rec.get("action") == "skip-symlink" or rec.get("spanner_of"):
                continue
            expect[rel_d] = rec
            d = snap.get(rel_d)
            if d is None:
                missing.append(rel_d)
            elif rec.get("size") and int(d["Size"]) != int(rec["size"]):
                mismatch.append((rel_d, rec.get("size"), int(d["Size"])))
        extra = [p for p in snap
                 if p not in known and p.lower().endswith(K.VIDEO_EXT)]
        per_unit.append({"unit": u.name, "drive": u.drive_path,
                         "expect": len(expect), "on_drive": len(snap),
                         "bytes_on_drive": sum(int(f["Size"]) for f in snap.values()),
                         "missing": missing, "mismatch": mismatch, "extra": extra})

    meta = {"version": VERSION, "kit": a.kit,
            "started": datetime.fromtimestamp(started).isoformat(timespec="seconds"),
            "finished": datetime.now().isoformat(timespec="seconds"),
            "hours": round((time.time() - started) / 3600, 2),
            "bitrate": a.bitrate, "jobs": a.jobs,
            "stage_cap": a.stage_cap, "extras_layout": a.extras_layout,
            "stopped": ctx.stop_reason, "units": unit_stats,
            "drive_check": per_unit}
    report = K.summarize(ctx.rows, meta)
    rpath = os.path.join(ctx.run_dir, f"proxy_report_{a.kit}.json")
    with open(rpath, "w") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    # ── читаемая версия ──
    L = []
    L.append(f"# Приёмка прокси-комплекта {a.kit}")
    L.append("")
    L.append(f"rebuild.py v{VERSION} · собрано "
             f"{datetime.now().strftime('%d.%m.%Y %H:%M')} · "
             f"прогон {meta['hours']} ч")
    if ctx.stop_reason:
        L.append("")
        L.append(f"**Прогон остановлен:** {ctx.stop_reason}")
    L.append("")
    L.append("## Коротко")
    L.append("")
    L.append(f"- клипов в отчёте: {report['n']}")
    L.append(f"- не прошли контракт: {report['fails']}")
    L.append(f"- совпало по кадрам: {report['frames_ok']}")
    L.append(f"- вес собранного: {gb(report['total_bytes'])}")
    if report["counts"]:
        L.append("- по действиям: " + ", ".join(f"{k} — {v}"
                                                for k, v in sorted(report["counts"].items())))
    if luts:
        L.append(f"- лутов приведено к канону: {luts}")
    L.append("")

    L.append("## По клипам")
    L.append("")
    L.append("| клип | действие | сжатие | контракт | вес прокси |")
    L.append("|---|---|---|---|---|")
    for r in sorted(ctx.rows, key=lambda x: x.get("rel", "")):
        c = r.get("contract") or {}
        bad = [proxy.RU.get(k, k) for k, v in c.items() if not v.get("ok")]
        mark = "сошёлся" if (c and not bad) else ("—" if not c else "✗ " + ", ".join(bad))
        L.append(f"| `{r.get('rel', '')}` | {r.get('action', '')} | "
                 f"×{r.get('ratio', 0)} | {mark} | {gb(r.get('size', 0))} |")
    L.append("")

    L.append("## Сверка с Drive")
    L.append("")
    L.append("| проект | ожидали | лежит на Drive | вес | нет на Drive | не сошлось | лишнее |")
    L.append("|---|---|---|---|---|---|---|")
    for p in per_unit:
        if p.get("unverified"):
            L.append(f"| {p['unit']} | — | — | — | — | — | "
                     f"НЕ СВЕРЕНО: {p['unverified']} |")
            continue
        L.append(f"| {p['unit']} | {p['expect']} | {p['on_drive']} | "
                 f"{gb(p['bytes_on_drive'])} | {len(p['missing'])} | "
                 f"{len(p['mismatch'])} | {len(p['extra'])} |")
    L.append("")

    for title, field, fmt in (
            ("Не сошлось по размеру", "mismatch",
             lambda x: f"`{x[0]}` — ожидали {x[1]} Б, лежит {x[2]} Б"),
            ("Нет на Drive", "missing", lambda x: f"`{x}`"),
            ("Лишнее на Drive (только перечисляю, не удаляю)", "extra",
             lambda x: f"`{x}`")):
        items = [(p["unit"], v) for p in per_unit for v in p[field]]
        if not items:
            continue
        L.append(f"### {title}")
        L.append("")
        for unit_name, v in items[:200]:
            L.append(f"- {unit_name}: {fmt(v)}")
        if len(items) > 200:
            L.append(f"- … и ещё {len(items) - 200}")
        L.append("")

    L.append("## Файлы")
    L.append("")
    L.append("```")
    L.append(rpath)
    L.append(ctx.jsonl_path)
    L.append(ctx.state_path)
    L.append(ctx.log_path)
    L.append("```")
    apath = os.path.join(ctx.run_dir, f"acceptance_{a.kit}.md")
    with open(apath, "w") as fh:
        fh.write("\n".join(L) + "\n")
    return report, rpath, apath, per_unit


# ── selftest ─────────────────────────────────────────────────────────────────
def selftest():
    """Чистая логика за секунду и без сети. Ни одной правки без прошедшего.

    Проверяем ровно то, что нельзя проверить ночью: потолок, разбор размеров,
    предикат «уже сделано», классификацию отказов и поиск спаннеров."""
    ok, fail = 0, []

    def check(name, cond):
        nonlocal ok
        if cond:
            ok += 1
        else:
            fail.append(name)

    # ── 1. потолок стейджинга ──
    s = Staging(1000, log=lambda m: None)
    check("резерв выдаётся, пока влезает", s.reserve("a", 600) and s.used == 600)
    check("второй резерв влезает впритык", s.reserve("b", 400) and s.used == 1000)

    got = {"v": None}

    def third():
        got["v"] = s.reserve("c", 300)

    t = threading.Thread(target=third, daemon=True)
    t.start()
    t.join(0.4)
    check("третий заблокирован — потолок держит", got["v"] is None and t.is_alive())
    s.release("a")                       # освободили 600 — третий должен пройти
    t.join(2.0)
    check("после release заблокированный проходит", got["v"] is True)
    check("инвариант: сумма не выше потолка", s.used <= s.cap)

    s.revise("c", 100)
    check("уточнение резерва вниз уменьшает занятое", s.used == 500)
    s.release("b")
    s.release("c")
    check("после всех release стейджинг пуст", s.used == 0)

    # клип больше потолка пускается в одиночку, иначе прогон встал бы навсегда
    s2 = Staging(100, log=lambda m: None)
    check("одиночный переросток пускается", s2.reserve("big", 500) and s2.used == 500)
    got2 = {"v": None}
    t2 = threading.Thread(target=lambda: got2.update(v=s2.reserve("x", 10)), daemon=True)
    t2.start()
    t2.join(0.3)
    check("при занятом переростке остальные ждут", got2["v"] is None)
    s2.abort()
    t2.join(2.0)
    check("abort будит заблокированных", got2["v"] is False)

    # ── 2. разбор размеров ──
    check("20G", K.parse_size("20G") == 20 * 1024 ** 3)
    check("512M", K.parse_size("512M") == 512 * 1024 ** 2)
    check("голые байты", K.parse_size("1500000000") == 1_500_000_000)
    check("оценка encode по коэффициенту",
          estimate_out(20 * 1024 ** 3, "encode") == 20 * 1024 ** 3 // EST_RATIO)
    check("оценка encode не ниже пола",
          estimate_out(100 * 1024 ** 2, "encode") == EST_FLOOR)
    check("оценка copy равна размеру",
          estimate_out(12345, "copy") == 12345)

    # ── 3. «уже сделано» ──
    t_run = 1_700_000_000.0
    newer = datetime.fromtimestamp(t_run + 3600, timezone.utc).isoformat().replace("+00:00", "Z")
    older = datetime.fromtimestamp(t_run - 86400, timezone.utc).isoformat().replace("+00:00", "Z")
    check("состояние говорит «залито», размер сошёлся",
          already_done({"uploaded": True, "size": 100},
                       {"Size": 100, "ModTime": newer}, 1800, t_run)[0] is True)
    check("состояние говорит «залито», но на Drive нет",
          already_done({"uploaded": True, "size": 100}, None, 1800, t_run)[0] is False)
    check("состояние говорит «залито», размер разошёлся",
          already_done({"uploaded": True, "size": 100},
                       {"Size": 99, "ModTime": newer}, 1800, t_run)[0] is False)
    check("без состояния: свежий и в коридоре — зачтён",
          already_done({}, {"Size": 100, "ModTime": newer}, 1800, t_run)[0] is True)
    check("без состояния: старый комплект не зачтён",
          already_done({}, {"Size": 100, "ModTime": older}, 1800, t_run)[0] is False)
    check("без состояния: сжатие вне коридора не зачтено",
          already_done({}, {"Size": 100, "ModTime": newer}, 100000, t_run)[0] is False)
    check("без состояния: байт-в-байт копия зачтена",
          already_done({}, {"Size": 1800, "ModTime": newer}, 1800, t_run)[0] is True)
    check("--rescan игнорирует состояние и судит по снимку",
          already_done({"uploaded": True, "size": 100},
                       {"Size": 100, "ModTime": older}, 1800, t_run,
                       rescan=True)[0] is False)
    check("дробные доли секунды в ModTime разбираются",
          parse_modtime("2026-09-22T18:55:36.859Z") > 0)
    check("нечитаемый ModTime считается старым", parse_modtime("мусор") == 0.0)
    # ⚠️ Смещение обязано УЧИТЫВАТЬСЯ, а не утекать в доли секунды: иначе
    # время уезжает вперёд на величину смещения, и файл прошлого комплекта
    # может оказаться «моложе метки старта», то есть зачтён как свой.
    check("смещение +04:00 сдвигает время назад, а не съедается",
          parse_modtime("2026-09-22T18:55:36.859+04:00")
          == parse_modtime("2026-09-22T14:55:36.859Z"))
    check("смещение без долей секунды тоже учитывается",
          parse_modtime("2026-09-22T18:55:36+04:00")
          == parse_modtime("2026-09-22T14:55:36Z"))
    check("отрицательное смещение сдвигает вперёд",
          parse_modtime("2026-09-22T18:55:36-05:00")
          == parse_modtime("2026-09-22T23:55:36Z"))

    # ── 4. классификация отказов rclone ──
    cases = [
        # обе формы одной беды: человеческий текст и машинная причина
        ("Failed to copy: googleapi: Error 403: User rate limit exceeded", "rate"),
        ("googleapi: Error 403: rateLimitExceeded", "rate"),
        ("error 403: The user has exceeded their Drive storage quota upload limit", "quota"),
        ("googleapi: Error 403: storageQuotaExceeded", "quota"),
        ("teamDriveFileLimitExceeded", "quota"),
        ("dial tcp: lookup www.googleapis.com: no such host", "network"),
        ("Failed to copy: directory not found", "notfound"),
        ("googleapi: Error 403: Insufficient file permissions", "auth"),
        ("write /Volumes/x: no space left on device", "nospace"),
        ("что-то совсем новое", "other"),
    ]
    for text, want in cases:
        kind, _a, _h = classify_rclone(1, text)
        check(f"отказ «{want}» опознан", kind == want)
    check("rc=0 — это не отказ", classify_rclone(0, "")[0] == "ok")
    check("квота ждёт, а не сдаётся",
          classify_rclone(1, "upload limit")[1] == "wait-quota")
    check("прав нет — сдаёмся по этому клипу",
          classify_rclone(1, "invalid_grant")[1] == "give-up")

    # ── 5. спаннеры ──
    rels = ["06_Photo/RYA-FX3-1071.MP4", "07_Knitting/RYA-FX3-1071__S10.MP4",
            "07_Knitting/RYA-FX3-1072.MP4", "08_X/RYA-ZVE1-0003__S02.MOV",
            "08_X/RYA-ZVE1-0003.MOV", "09_Y/RYA-FX3-9999__S01.MP4"]
    plan = dict((s, d) for s, d in spanner_plan(rels))
    check("спаннер находит донора в ДРУГОЙ папке",
          plan.get("07_Knitting/RYA-FX3-1071__S10.MP4") == "06_Photo/RYA-FX3-1071.MP4")
    check("спаннер .MOV тоже находится",
          plan.get("08_X/RYA-ZVE1-0003__S02.MOV") == "08_X/RYA-ZVE1-0003.MOV")
    check("спаннер без донора не попадает в план",
          "09_Y/RYA-FX3-9999__S01.MP4" not in plan)
    check("обычный клип спаннером не считается",
          "07_Knitting/RYA-FX3-1072.MP4" not in plan)
    check("спаннеров ровно два", len(plan) == 2)
    # ⚠️ Боевой случай: спаннера НЕТ в оригиналах (проверено по всем пяти
    # проектам — под 01_Source ни одного видео-__S), он живёт только на Drive.
    # План обязан собираться из объединения «локальные работы + снимок Drive»,
    # иначе шаг всегда пуст, донор пересобирается, а спаннер остаётся от
    # старого комплекта и молча разъезжается с донором.
    local_only = ["06_Photo/RYA-FX3-1071.MP4"]
    drive_only = ["06_Photo/RYA-FX3-1071.MP4", "07_Knitting/RYA-FX3-1071__S10.MP4"]
    check("по одним локальным работам спаннер не находится",
          spanner_plan(local_only) == [])
    union = list(dict.fromkeys(local_only + drive_only))
    check("объединение с Drive находит спаннер и его донора",
          spanner_plan(union) == [("07_Knitting/RYA-FX3-1071__S10.MP4",
                                   "06_Photo/RYA-FX3-1071.MP4")])

    # ── 6. раскладка съёмочного дня ──
    u_flat = Unit("Masha", "/x", "d", "/s", layout="flat")
    u_sc = Unit("YTCH12", "/x", "d", "/s", layout="scenes")
    check("плоская раскладка срезает сцену",
          u_flat.rel_drive("01_Scene/RYA-FX3-1032.MP4") == "RYA-FX3-1032.MP4")
    check("посценная раскладка сохраняет путь",
          u_sc.rel_drive("01_Scene/RYA-FX3-1032.MP4") == "01_Scene/RYA-FX3-1032.MP4")
    check("имена нормализуются в NFC",
          nfc(unicodedata.normalize("NFD", "Лиза")) == "Лиза")

    # ── 7. упавшая заливка обязана попасть в застрявшее ──
    # ⚠️ Самый тихий способ потерять ночь: заливщик ловит исключение, клип
    # исчезает из очереди, а резерв под него остаётся висеть. Потолок съеден
    # фантомами, кодировщики навсегда стоят в reserve, сторож молчит — он
    # смотрит на stuck, а stuck пуст. Проверяем, что не пуст.
    class _StubCtx:
        def __init__(self):
            self.a = type("A", (), {"kit": "TEST", "no_telegram": True,
                                    "stage": "/tmp"})()
            self.lock = threading.Lock()
            self.stop = threading.Event()
            self.run_dir = "/tmp"
            self.hb = {"failed": 0}
            self.lines = []

        def log(self, m):
            self.lines.append(m)

        def tg(self, m, once_key=None):
            pass

        def state_load(self):
            return {}

        def state_set(self, k, v):
            pass

    stub = _StubCtx()
    up_t = Uploader(stub, {"remote": "x", "team_drive": ""}, Staging(1000, log=lambda m: None))
    up_t._one = lambda item: (_ for _ in ()).throw(OSError("Too many open files"))
    up_t.q.put({"key": "U/a.MP4", "local": "/tmp/a", "size": 777, "remote": "r"})
    up_t.q.put(None)
    up_t.run()
    check("исключение в заливке попадает в застрявшее", up_t.stuck == {"U/a.MP4": 777})
    check("исключение в заливке считается провалом", stub.hb["failed"] == 1)
    check("после исключения очередь дочищена", up_t.q.unfinished_tasks == 0)

    # ⚠️ Если заливщик всё же погиб, ждать его на q.join() нельзя: счётчик
    # незавершённых задач уже не обнулится, и прогон замрёт до утра молча.
    dead = Uploader(stub, {"remote": "x", "team_drive": ""},
                    Staging(1000, log=lambda m: None))
    dead.q.put({"key": "U/b.MP4", "local": "/tmp/b", "size": 1, "remote": "r"})
    t_drain = time.time()
    check("мёртвый заливщик не держит прогон вечно",
          drain_uploads(dead, stub, why="тест") is False
          and time.time() - t_drain < 5)
    empty = Uploader(stub, {"remote": "x", "team_drive": ""},
                     Staging(1000, log=lambda m: None))
    check("пустая очередь считается слитой",
          drain_uploads(empty, stub) is True)

    total = ok + len(fail)
    if fail:
        print(f"selftest: ПРОВАЛ {len(fail)} из {total}")
        for f in fail:
            print(f"   ✗ {f}")
        return 1
    print(f"selftest: ок, {ok}/{total} проверок")
    return 0


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        return selftest()

    ap = argparse.ArgumentParser(
        description="ночная пересборка прокси-комплекта канала с потоковой заливкой")
    ap.add_argument("--kit", default="YTCH", choices=sorted(KITS),
                    help="канал из KITS")
    ap.add_argument("--projects", default="",
                    help="только эти проекты/дни через запятую (по умолчанию все)")
    ap.add_argument("--jobs", type=int, default=2,
                    help="сколько клипов кодировать разом")
    ap.add_argument("--stage", default=DEFAULT_STAGE,
                    help="рабочая площадка под собираемые прокси")
    ap.add_argument("--stage-cap", default="auto",
                    help="жёсткий потолок очереди; auto (по умолчанию) — потолок "
                         "живёт по свободному месту, держа --min-free-gb неприкосновенным: "
                         "диск остаётся рабочим, а кодировщики не стоят зря")
    ap.add_argument("--min-free-gb", type=float, default=10.0,
                    help="неприкосновенный запас на томе стейджинга: ниже него не опускаемся, "
                         "а если всё-таки опустились — сливаем очередь и встаём")
    ap.add_argument("--bitrate", default=K.DEFAULT_BITRATE,
                    help="8M по умолчанию; auto — по частоте кадров")
    ap.add_argument("--bind", default="auto",
                    help="auto (v4-джокер), off или конкретный IP")
    ap.add_argument("--tpslimit", type=int, default=8)
    ap.add_argument("--luts", choices=("rename", "skip", "only"), default="rename",
                    help="привести имена лутов к канону на Drive и локально")
    ap.add_argument("--extras-layout", choices=("flat", "scenes"), default="flat",
                    help="как класть съёмочные дни: плоско (как у монтажёра) или по сценам")
    ap.add_argument("--retries", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true",
                    help="план и арифметика, ничего не собирается и не льётся")
    ap.add_argument("--verify-only", action="store_true",
                    help="ничего не делать, только сверить с Drive и выписать приёмку")
    ap.add_argument("--rescan", action="store_true",
                    help="не верить своему состоянию, судить по снимку Drive")
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--log", default=None)
    a = ap.parse_args()

    cfg = KITS[a.kit]
    if not cfg["projects"] and not cfg.get("extras"):
        print(f"{a.kit}: в KITS нет ни одного проекта — это заготовка. "
              f"Посчитать объём и место прежде, чем заполнять.", file=sys.stderr)
        return 2

    ctx = Ctx(a)
    a.stage_cap_fixed = (a.stage_cap or "auto").lower() != "auto"
    # при auto стартуем от свободного минус запас; дальше сторож подгоняет каждую минуту
    ctx.a.stage_cap_bytes = (K.parse_size(a.stage_cap) if a.stage_cap_fixed
                             else max(int((K.free_gb(a.stage) - a.min_free_gb) * 1e9),
                                      4 * 1024 ** 3))
    ctx.kit_root = cfg["local_root"]
    units = build_units(a, cfg)
    started = time.time()

    # Второй экземпляр посреди ночи — это две очереди на один потолок и два
    # rclone на один аплинк. Пускаем ровно один.
    pidf = os.path.join(ctx.run_dir, f"rebuild_{a.kit}.pid")
    if not (a.dry_run or a.verify_only):
        alone, who = single_instance(pidf)
        if not alone:
            print(f"уже бежит (pid {who}) — выхожу", file=sys.stderr)
            return 5

    for f in ("STOP",):
        p = os.path.join(a.stage, f)
        if os.path.exists(p):
            print(f"в стейджинге лежит {f} — уберите его, прежде чем запускать: {p}",
                  file=sys.stderr)
            return 3

    ctx.log("")
    ctx.log(f"═══ ПЕРЕСБОРКА ПРОКСИ {a.kit} · rebuild.py v{VERSION}"
            + (" · СУХОЙ ПРОГОН" if a.dry_run else "")
            + (" · ТОЛЬКО СВЕРКА" if a.verify_only else ""))
    ctx.log(f"    проектов {len(units)}, потоков {a.jobs}, потолок очереди "
            f"{'жёсткий ' + a.stage_cap if a.stage_cap_fixed else 'по свободному месту'} "
            f"({gb(ctx.a.stage_cap_bytes)}, запас {a.min_free_gb:.0f} ГБ), "
            f"свободно {K.free_gb(a.stage):.0f} ГБ")
    ctx.log(f"    стейджинг {a.stage}")
    ctx.log(f"    метка старта {datetime.fromtimestamp(ctx.run_started).strftime('%d.%m %H:%M')}")

    # ── луты первым делом ──
    lut_done = 0
    if a.luts in ("rename", "only"):
        ctx.log("── луты: канонические имена на Drive (server-side) и локально")
        lut_done, _notes = luts_step(cfg, a, ctx, units)
    if a.luts == "only":
        ctx.log(f"готово: лутов приведено {lut_done}")
        return 0

    # Потолок очереди — не константа: он живёт по реальному свободному месту,
    # держа неприкосновенный запас `--min-free-gb`. Так диск всегда остаётся
    # рабочим, а кодировщики не стоят, когда места на самом деле много.
    staging = Staging(ctx.a.stage_cap_bytes, log=ctx.log,
                      floor_bytes=int(a.min_free_gb * 1e9),
                      ceiling=ctx.a.stage_cap_bytes if a.stage_cap_fixed else 0,
                      stage_dir=a.stage)
    staging.retune()
    up = Uploader(ctx, cfg, staging)

    if not (a.dry_run or a.verify_only):
        ctx.tg(f"🌙 Прокси {a.kit}: пересборка пошла. Проектов {len(units)}, "
               f"кодирование и заливка внахлёст, потолок очереди "
               f"{gb(ctx.a.stage_cap_bytes)}. Отчёт каждые 15 минут.")
        up.start()
        threading.Thread(target=watchdog, args=(ctx, up, staging), daemon=True).start()

    # ── проекты по очереди, в порядке приоритета ──
    stats = []
    calibrated = False
    for u in units:
        if ctx.stop.is_set():
            ctx.log(f"пропускаю {u.name}: {ctx.stop_reason}")
            continue
        stats.append(run_unit(u, cfg, a, ctx, staging, up))
        if not calibrated and ctx.hb["uploaded"] and not (a.dry_run or a.verify_only):
            calibrated = True
            enc = (ctx.hb["dst"] / ctx.hb["enc_sec"] / 1e6) if ctx.hb["enc_sec"] else 0
            upl = (ctx.hb["up"] / ctx.hb["up_sec"] / 1e6) if ctx.hb["up_sec"] else 0
            ctx.tg(f"Прокси {a.kit}: калибровка по первым клипам — кодирование "
                   f"{enc:.1f} МБ/с, заливка {upl:.1f} МБ/с. "
                   f"{progress_line(ctx, up)}")

    if not (a.dry_run or a.verify_only):
        drain_uploads(up, ctx, why="конец прогона")
        up.q.put(None)

    # ── приёмка ──
    if a.dry_run:
        need = sum(s.get("todo", 0) for s in stats)
        ctx.log("")
        ctx.log(f"СУХОЙ ПРОГОН: к сборке {need} клипов, "
                f"свободно на стейджинге {K.free_gb(a.stage):.0f} ГБ, "
                f"потолок {gb(ctx.a.stage_cap_bytes)}")
        for s in stats:
            ctx.log(f"   {s.get('unit'):<22} "
                    + (s["skipped"] if "skipped" in s else
                       f"клипов {s['clips']:>4}, готово {s['done']:>4}, "
                       f"к сборке {s['todo']:>4}, на Drive {s['snapshot']:>4} файлов"))
        return 0

    report, rpath, apath, per = acceptance(cfg, a, ctx, units, stats, lut_done, started)
    miss = sum(len(p["missing"]) for p in per)
    mism = sum(len(p["mismatch"]) for p in per)
    extra = sum(len(p["extra"]) for p in per)
    unver = [p["unit"] for p in per if p.get("unverified")]
    # Проект, который Drive отказался показать, и проект, где всё сошлось, —
    # разные вещи. Молчать про первое нельзя: «не долетело 0» читается как
    # «всё в порядке», а на деле мы просто не смотрели.
    skipped_units = [s["unit"] for s in stats if s.get("skipped")]
    if a.verify_only:
        tail = (f"Сверка {a.kit} с Drive: ожидали {sum(p['expect'] for p in per)}, "
                f"не долетело {miss}, размер разошёлся {mism}, лишнего {extra}. "
                f"Отчёт: {apath}")
    else:
        tail = (f"✅ Прокси {a.kit}: пересборка закончена за "
                f"{(time.time() - started) / 3600:.1f} ч. Собрано {report['n']} клипов, "
                f"{gb(report['total_bytes'])}, не прошли контракт {report['fails']}. "
                f"На Drive не долетело {miss}, размер разошёлся {mism}, "
                f"лишнего {extra}. Отчёт: {apath}")
    if skipped_units:
        tail += f" ⚠️ Пропущено без сборки: {', '.join(skipped_units)}."
    if unver:
        tail += f" ⚠️ Не сверено с Drive: {', '.join(unver)}."
    if ctx.stop_reason:
        tail = f"⛔ Прокси {a.kit}: прогон встал — {ctx.stop_reason}. " + tail
    ctx.log("")
    ctx.log(tail)
    if not a.verify_only:            # ручная сверка телефон не будит
        ctx.tg(tail)
    ctx.log(f"    {rpath}")
    ctx.log(f"    {apath}")
    return 1 if (report["fails"] or miss or mism or unver or skipped_units
                 or ctx.stop_reason) else 0


if __name__ == "__main__":
    sys.exit(main())
