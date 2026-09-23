#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Фабрика прокси: автономная очередь, работающая от Drive.

Чем отличается от соседей по этапу. `proxy.py` собирает комплект ОДНОГО проекта
из локальной папки и кладёт рядом. `rebuild.py` пересобирает канал с локального
SSD и льёт на Drive внахлёст. Здесь третья задача: собирать прокси НЕЗАВИСИМО ОТ
ТОГО, ГДЕ ЛЕЖАТ ДИСКИ И ГДЕ НАХОДИТСЯ РОМАН. Исходники берутся с Drive, готовые
прокси уезжают на Drive, локально в любой момент живёт только хвост очереди.

Из этого следуют два ответа, которых нельзя было получить иначе:

  · карту можно чистить. Фабрике она не нужна: манифест (plan.py) один раз
    доказал, что каждый исходник лежит на Drive по имени и точному размеру;
  · симлинки перестают быть препятствием. `decide()` в контракте отдаёт на
    симлинке `skip-symlink` («спаннер»), и в YTEVO03, где симлинками являются
    ВСЕ 172 источника, штатный прогон собрал бы ноль клипов. Фабрика кодирует
    настоящий файл, скачанный с Drive, и правило про спаннеры снова работает
    по назначению — по имени `__S##`, а не по признаку симлинка.

Контракт из восьми пунктов — по-прежнему `1601_build/contract.py`, логистика
места и разбор отказов Drive — `1601_build/rebuild.py`. Оба переиспользуются
импортом. Своей копии рецепта здесь НЕТ и быть не может: три разошедшиеся копии
уже стоили комплекта YTCH.

Что делает фабрику устойчивой (а не просто работающей):

  1. Истина о сделанном — НА DRIVE. Клип сделан, если прокси лежит на месте и
     проходит контракт. Очередь на диске — кэш для дешёвого возобновления;
     потеряется целиком — прогон восстановится по одному снимку Drive.
  2. Очередь — журнал, который только дописывается (store.py). Лизы: упавший
     воркер, убитый процесс, перезагрузка — клип возвращается сам.
  3. Место — обратное давление. Кодировщик не начинает, пока некуда класть,
     и резерв считается на ОБА файла: скачанный оригинал (до 52 ГБ) и прокси.
  4. Приговор выносит гейт, а не наш отчёт. И залитое подтверждается размером
     с Drive, а не тем, что rclone не ругнулся.
  5. Исходники не удаляются никогда. Удаляется только то, что фабрика сама
     скачала в стейджинг, и только после подтверждённой заливки.
  6. Выключатели файлами: STOP и PAUSE_UPLOAD в стейджинге. Человек может
     остановить прогон, не убивая процесс и не теряя очередь.

  python3 farm.py selftest                          чистая логика, без сети
  python3 farm.py plan   --unit YTEVO03 --publish   манифест (там, где диски)
  python3 farm.py run    --unit YTEVO03 --dry-run   что и почему будет сделано
  python3 farm.py run    --unit YTEVO03             боевой прогон
  python3 farm.py status --unit YTEVO03             где стоим
  python3 farm.py revive --unit YTEVO03             вернуть отложенное в очередь

Версия 1.0 · 23.09.2026 · этап 16_proxy/1603_farm · KB 3.4 /kb/proxy/
"""
import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "1601_build"))
sys.path.insert(0, _HERE)
import contract as K                                 # noqa: E402
import rebuild as R                                  # noqa: E402
import plan as PLAN                                  # noqa: E402
from drive import Drive, DriveError, sleep_for_quota  # noqa: E402
from store import Store                              # noqa: E402

#: Всё, что должно пережить отключение дисков: журнал очереди, лог, отчёты.
#: ⚠️ Не на /Volumes: launchd не открывает лог на внешнем томе, а состояние на
#: том же томе, что медиа, теряется ровно тогда, когда нужнее всего.
RUN_DIR = os.path.expanduser("~/Library/Logs/ytai/proxy_farm")
#: Стейджинг — рабочая площадка. Только медиа и два файла-выключателя.
DEFAULT_STAGE = os.path.expanduser("~/.cache/ytai/proxy_farm")

TG_CHAT = "155880671"
TG_ENV = os.path.expanduser("~/.claude/channels/telegram-rya/.env")

#: Неприкосновенный запас на томе стейджинга. Ниже него фабрика не опускается
#: никогда: диск обязан остаться рабочим, даже если прогон встанет.
MIN_FREE_GB = 25.0
#: Оценка веса прокси. ⚠️ Отношение ×18 годится только для 25p на 8 Мбит/с.
#: Для 50p заказывается 12 Мбит/с, и та же ×18 занижает вес на четверть: на
#: YTEVO03 (109 клипов из 172 идут 50p) «×18» обещает 26.6 ГБ против фактических
#: 34.1 ГБ. Занижение резерва — это и есть способ забить диск в четыре утра,
#: поэтому до probe резервируем ПЕССИМИСТИЧНО, а после — считаем честно по
#: длительности и заказанному битрейту.
EST_RATIO_BLIND = 10          # до probe: заведомо с запасом
#: Пол СЛЕПОЙ оценки — 400 МБ, как в rebuild.py: пока известен только вес
#: исходника, короткий клип легко недооценить в разы.
EST_FLOOR = R.EST_FLOOR
#: Пол ТОЧНОЙ оценки другой и много меньше. Тот же 400-мегабайтный пол здесь
#: перебивал честный расчёт: клип 100 с на 12 Мбит/с весит 180 МБ, а пол требовал
#: резервировать 419 — вдвое больше нужного. Резерв с запасом не опасен, но он
#: держит кодировщик в очереди зря, а весь смысл точной оценки был в том, чтобы
#: перестать врать. После probe длительность известна, и пола хватает такого,
#: который покрывает контейнер и первый ключевой кадр.
EXACT_FLOOR = 32 * 1024 ** 2


def est_blind(src_size):
    """Резерв до probe: про клип известен только вес исходника."""
    return max(int((src_size or 0) / EST_RATIO_BLIND), EST_FLOOR)


def est_exact(spec, bitrate):
    """Резерв после probe: длительность × заказанный битрейт плюс звук и запас.
    Считает то, что мы у кодера ЗАКАЗАЛИ, а не то, во что верим про сжатие."""
    bps = K._bitrate_bps(bitrate)
    audio_bps = 256_000 * max(1, len(getattr(spec, "audio", []) or [1]))
    body = (bps + audio_bps) * max(spec.duration, 0.5) / 8.0
    return max(int(body * 1.15), EXACT_FLOOR)
#: Столько минут байты не двигаются НИГДЕ → вмешиваемся.
STALL_MIN = 45
#: Строка прогресса в Telegram.
PROGRESS_EVERY = 1800


def hms(s):
    return R.hms(s)


def gb(n):
    return R.gb(n)


# ── единственный экземпляр ───────────────────────────────────────────────────
def single_instance(path, marker="farm.py"):
    """pid-файл плюс сверка имени процесса: номер могли переиспользовать, и
    тогда фабрика отказалась бы стартовать из-за чужого процесса."""
    old = None
    try:
        old = int(open(path).read().strip())
    except Exception:
        pass
    if old and old != os.getpid():
        try:
            out = subprocess.run(["ps", "-p", str(old), "-o", "command="],
                                 capture_output=True, text=True, timeout=20).stdout
            if marker in out:
                return False, old
        except Exception:
            pass
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    open(path, "w").write(str(os.getpid()))
    return True, os.getpid()


# ── контекст прогона ─────────────────────────────────────────────────────────
class Ctx:
    """Лог, Telegram, выключатели, счётчики. Один на прогон."""

    def __init__(self, unit_name, stage, log_path=None, no_telegram=False):
        self.unit = unit_name
        self.stage = stage
        os.makedirs(RUN_DIR, exist_ok=True)
        os.makedirs(stage, exist_ok=True)
        self.log_path = log_path or os.path.join(RUN_DIR, f"farm_{unit_name}.log")
        self._fh = open(self.log_path, "a", buffering=1)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        #: Качалки закончили: кодировщику больше ждать нечего, можно выходить,
        #: как только разберёт очередь готового.
        self.fetch_done = threading.Event()
        self.stop_reason = ""
        self.no_telegram = no_telegram
        self._tg_seen = set()
        self.started = time.time()
        self.hb = {"encoded": 0, "copied": 0, "skipped": 0, "failed": 0,
                   "spanners": 0, "bytes_in": 0, "bytes_out": 0}
        self.moved_at = time.time()      # когда байты двигались последний раз

    def log(self, msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        with self.lock:
            print(line, flush=True)
            self._fh.write(line + "\n")

    def tg(self, msg, once_key=None):
        if self.no_telegram:
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

    def moved(self, nbytes=0):
        """Отметить движение байт. Сторож смотрит именно на это, а не на то,
        жив ли процесс: живой процесс, который ничего не делает, — худший случай."""
        with self.lock:
            self.moved_at = time.time()

    def bump(self, key, n=1):
        with self.lock:
            self.hb[key] = self.hb.get(key, 0) + n

    def halt(self, reason):
        self.stop_reason = reason
        self.stop.set()
        self.log(f"⛔ прогон останавливается: {reason}")
        self.tg(f"⛔ Фабрика прокси {self.unit}: {reason}", once_key=f"halt:{reason}")

    # ── выключатели файлами ──
    def stop_file(self):
        return os.path.join(self.stage, "STOP")

    def pause_file(self):
        return os.path.join(self.stage, "PAUSE_UPLOAD")


# ── флаг нагрузки для сторожа температуры ────────────────────────────────────
def load_flag(on, unit, stage_minutes=240, log=print):
    """Сказать сторожу Мемекса, что нагрев — это работа, а не беда.

    Конвенция уже есть: `~/bin/ytai_load start "job" <мин>` пишет
    `~/.cache/ytai/LOAD.json`, и тогда тревога «горячо» понижается до заметки с
    подписью. Без флага сторож поднимет ложную тревогу на каждом ночном прогоне,
    и Роман перестанет читать его сообщения — это хуже, чем отсутствие сторожа.
    Подпись держим короткой (≤28 знаков), как того требует сторож.
    """
    tool = os.path.expanduser("~/bin/ytai_load")
    if not os.path.exists(tool):
        return False
    try:
        args = ([tool, "start", f"proxy {unit}"[:28], str(int(stage_minutes))]
                if on else [tool, "stop"])
        subprocess.run(args, capture_output=True, timeout=30)
        return True
    except Exception as e:
        log(f"флаг нагрузки не выставился: {e}")
        return False


# ── манифест ─────────────────────────────────────────────────────────────────
def load_plan(unit, drive, ctx, local_first=True):
    """Взять манифест: сперва локальную копию, потом с Drive. На Мемексе
    локальной копии нет — и это нормально, манифест живёт на Drive рядом с
    комплектом именно для того, чтобы фабрика не зависела от машины."""
    local = os.path.join(_HERE, "state", f"plan_{unit['name']}.json")
    if local_first and os.path.exists(local):
        try:
            with open(local) as fh:
                p = json.load(fh)
            ctx.log(f"манифест: локальная копия {local}")
            return p
        except Exception as e:
            ctx.log(f"локальная копия манифеста не прочиталась ({e}) — беру с Drive")
    dst = unit["drive_kit"].rstrip("/") + "/" + PLAN.PLAN_NAME
    text = drive.get_text(dst)
    if not text:
        raise SystemExit(
            f"манифеста нет ни локально, ни на Drive ({dst}).\n"
            f"  Построй его там, где смонтированы диски:\n"
            f"    python3 {os.path.join(_HERE, 'plan.py')} --unit {unit['name']} --publish")
    ctx.log(f"манифест: с Drive {dst}")
    p = json.loads(text)
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "w") as fh:
        json.dump(p, fh, ensure_ascii=False, indent=1)
    return p


# ── этап 1: достать исходник ─────────────────────────────────────────────────
def fetch_one(item, ctx, drive, staging, store, a):
    """Взять клип с Drive и положить в стейджинг. Держит лизу и резерв места.

    Возвращает:
      ("ready", (local_src, downloaded))  можно кодировать
      ("done",  payload)                  делать нечего (спаннер, сухой прогон)
      ("fail"|"hold"|"requeue", почему)   вернуть в очередь или отложить
    """
    rel = item["rel"]
    src_size = int(item.get("size") or 0)

    # Спаннер: второй экземпляр клипа, живущего в двух сценах. Кодировать его
    # второй раз незачем — на Drive копия делается server-side, без трафика.
    if item.get("spanner_of"):
        donor = item["spanner_of"]
        drec = store.clips.get(donor) or {}
        if drec.get("state") != "done":
            return "requeue", f"жду донора {donor}"
        donor_dst = (drec.get("dst_drive")
                     or os.path.dirname(item["dst_drive"]) + "/" + os.path.basename(donor))
        drive.copy_server_side(donor_dst, item["dst_drive"])
        ctx.bump("spanners")
        ctx.moved()
        return "done", {"action": "spanner", "reason": f"копия донора {donor} на Drive",
                        "out_size": 0, "ratio": 0, "took": 0}

    # Том с оригиналами смонтирован? Тогда качать незачем — и это тот же код,
    # что работает на маке с картой в ридере.
    hint = item.get("src_local") or ""
    local_ready = False
    if hint and os.path.isfile(hint):
        try:
            local_ready = os.path.getsize(hint) == src_size
        except OSError:
            local_ready = False

    if a.dry_run:
        # Сухой прогон ничего не качает, значит и probe делать не на чем.
        # Соврать в сухом прогоне хуже, чем промолчать.
        ctx.log(f"  {rel}: [сухо] {'взял бы с диска' if local_ready else 'скачал бы'} "
                f"{gb(src_size)}, собрал бы ≈{gb(est_blind(src_size))} "
                f"→ {item['dst_drive']}")
        return "done", {"action": "dry", "reason": "сухой прогон", "out_size": 0,
                        "ratio": 0, "took": 0}

    # ⚠️ Резерв СРАЗУ на оба файла — скачанный оригинал и будущую прокси.
    # Если резервировать их порознь, качалки заполнят потолок оригиналами,
    # кодировщику не хватит места под прокси, и прогон встанет намертво:
    # освободить место может только он, а начать он не может.
    need = est_blind(src_size) + (0 if local_ready else src_size)
    if not staging.reserve(rel, need, timeout=None):
        return "requeue", "стейджинг остановлен"

    if local_ready:
        return "ready", (hint, False)

    work_dir = os.path.join(ctx.stage, ctx.unit, os.path.dirname(rel))
    os.makedirs(work_dir, exist_ok=True)
    local_src = os.path.join(work_dir, ".src-" + os.path.basename(rel))
    try:
        ctx.log(f"  {rel}: качаю {gb(src_size)} с Drive")
        t0 = time.time()
        got = drive.download(item["src_drive"], local_src)
        ctx.bump("bytes_in", got)
        ctx.moved(got)
        dt = max(time.time() - t0, 0.001)
        ctx.log(f"  {rel}: скачан за {hms(dt)} ({got/dt/1e6:.1f} МБ/с)")
        if src_size and got != src_size:
            raise RuntimeError(f"скачалось {got} Б вместо {src_size} Б — "
                               f"манифест или Drive разошлись")
        return "ready", (local_src, True)
    except DriveError as e:
        _rm(local_src)
        staging.release(rel)
        if e.action == "wait-quota":
            sleep_for_quota(ctx.log)
            return "requeue", "квота Drive — подождал, вернул в очередь"
        if e.action == "give-up":
            return "hold", f"{e.kind}: {e.human}"
        return "fail", f"{e.kind}: {e.human}"
    except Exception as e:
        _rm(local_src)
        staging.release(rel)
        return "fail", f"{type(e).__name__}: {str(e)[:300]}"


def _rm(*paths):
    for p in paths:
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


# ── этап 2: собрать, проверить гейтом, залить ────────────────────────────────
def build_one(item, local_src, downloaded, ctx, drive, staging, store, a):
    """Снять параметры → решить → собрать → ГЕЙТ → залить → подтвердить.
    Резерв места уже держится с этапа 1 и снимается здесь."""
    rel = item["rel"]
    dst_drive = item["dst_drive"]
    work_dir = os.path.join(ctx.stage, ctx.unit, os.path.dirname(rel))
    os.makedirs(work_dir, exist_ok=True)
    local_dst = os.path.join(work_dir, os.path.basename(rel))
    t0 = time.time()
    try:
        spec = K.probe(local_src)
        # ⚠️ bitrate=auto обязателен. У proxy.py дефолт --bitrate это «8M», а
        # bitrate_for() отдаёт override как есть — таблица FPS_BITRATE тогда не
        # работает вовсе, и 109 клипов 50p уехали бы на 8 Мбит/с вместо 12,
        # а гейт бы промолчал: его коридор 0.35–2.5× это пропускает.
        bitrate = K.bitrate_for(spec, override=a.bitrate)
        dec = K.decide(spec, bitrate=bitrate, chroma=a.chroma)
        if dec.action == "skip-symlink":
            return "hold", ("клип опознан спаннером уже после скачивания — "
                            "манифест и контракт разошлись")
        # Оценка уточняется по длительности и ЗАКАЗАННОМУ битрейту; обычно вниз.
        staging.revise(rel, (0 if not downloaded else spec.size) + est_exact(spec, bitrate))

        _rm(local_dst)
        if dec.action == "copy":
            shutil.copy2(local_src, local_dst + ".part")
            os.replace(local_dst + ".part", local_dst)
        else:
            cmd = K.build_cmd(spec, local_dst, dec)
            tmp = local_dst + K.TMP_SUFFIX
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=max(1800, spec.duration * 4))
            if r.returncode != 0 or not os.path.exists(tmp):
                _rm(tmp)
                return "fail", "ffmpeg: " + (r.stderr or "").strip()[-300:]
            os.replace(tmp, local_dst)
        took = time.time() - t0
        ctx.moved()

        # ── гейт: приговор выносит он, а не мы ──
        dstspec = K.probe(local_dst)
        g = K.gate(spec, dstspec, rel, rel, dec)
        if not g.ok:
            _rm(local_dst)
            return "fail", g.summary()

        # ── залить и подтвердить размером С DRIVE ──
        while os.path.exists(ctx.pause_file()) and not ctx.stop.is_set():
            ctx.log("  заливка на паузе (файл PAUSE_UPLOAD)")
            time.sleep(60)
        confirmed = drive.upload(local_dst, dst_drive)
        ctx.bump("bytes_out", confirmed)
        ctx.moved(confirmed)
        ctx.bump("encoded" if dec.action == "encode" else "copied")
        ratio = spec.size / max(dstspec.size, 1)
        ctx.log(f"  ✓ {rel}: {dec.action} {bitrate}, {gb(spec.size)}→{gb(dstspec.size)} "
                f"(×{ratio:.1f}), {hms(took)}")
        return "done", {"action": dec.action, "reason": dec.reason,
                        "out_size": dstspec.size, "drive_size": confirmed,
                        "ratio": round(ratio, 2), "took": round(took, 1),
                        "dst_drive": dst_drive}

    except DriveError as e:
        if e.action == "wait-quota":
            sleep_for_quota(ctx.log)
            return "requeue", "квота Drive — подождал, вернул в очередь"
        if e.action == "give-up":
            return "hold", f"{e.kind}: {e.human}"
        return "fail", f"{e.kind}: {e.human}"
    except subprocess.TimeoutExpired:
        return "fail", "кодирование не уложилось в отведённое время"
    except Exception as e:
        return "fail", f"{type(e).__name__}: {str(e)[:300]}"
    finally:
        # ⚠️ Удаляем ТОЛЬКО то, что скачали сами. Локальный исходник — чужой
        # файл, и трогать его нельзя ни при каком исходе (медиа не удаляем).
        # Скачанный с Drive — можно и НУЖНО: на Drive он остаётся нетронутым,
        # а иначе диск кончится на пятнадцатом проценте.
        if downloaded:
            _rm(local_src)
        _rm(local_dst, local_dst + ".part", local_dst + K.TMP_SUFFIX)
        staging.release(rel)


# ── пул качалок: работает на несколько клипов вперёд ─────────────────────────
def fetcher(name, ctx, drive, staging, store, ready_q, a):
    """Качает НЕСКОЛЬКО РАЗНЫХ файлов сразу — так берётся скорость.

    ⚠️ Именно разных. Рвать один файл на потоки нельзя: счётчик
    `downloadQuotaExceeded` у Google считается по файлу (см. флаги в drive.py).
    Замер 23.09.2026: один файл в один поток — 14 МБ/с, восемь РАЗНЫХ файлов —
    42 МБ/с. Узкое место конвейера здесь, а не в кодировщике: скачать 479 ГБ
    дольше, чем их закодировать.
    """
    idle = 0
    while not ctx.stop.is_set():
        item = store.claim(name)
        if item is None:
            idle += 1
            if idle > 3:
                return
            time.sleep(5)
            continue
        idle = 0
        verdict, payload = fetch_one(item, ctx, drive, staging, store, a)
        rel = item["rel"]
        if verdict == "ready":
            local_src, downloaded = payload
            # Очередь ограничена: качалки не должны убежать вперёд дальше,
            # чем кодировщик успевает разбирать, иначе диск кончится.
            while not ctx.stop.is_set():
                try:
                    ready_q.put((item, local_src, downloaded), timeout=30)
                    break
                except queue.Full:
                    continue
            if ctx.stop.is_set():
                if downloaded:
                    _rm(local_src)
                staging.release(rel)
                store.release(rel)
            continue
        if verdict == "done":
            store.done(rel, **(payload if isinstance(payload, dict) else {}))
        elif verdict == "requeue":
            ctx.log(f"  {rel}: возвращаю в очередь — {payload}")
            store.release(rel)
            time.sleep(5)
        elif verdict == "hold":
            ctx.log(f"  {rel}: отложен — {payload}")
            store.fail(rel, payload, hold=True)
            ctx.bump("failed")
        else:
            ctx.log(f"  {rel}: не скачался — {payload}")
            store.fail(rel, payload)
            ctx.bump("failed")


# ── пул кодировщиков ─────────────────────────────────────────────────────────
def encoder(name, ctx, drive, staging, store, ready_q, a):
    """Разбирает скачанное. Кодировщиков мало — hevc_videotoolbox это один
    аппаратный блок, и второй поток покупает ~8 %, а стоит вдвое больше
    площадки под оригинал и прокси."""
    while True:
        try:
            job = ready_q.get(timeout=10)
        except queue.Empty:
            if ctx.stop.is_set() or ctx.fetch_done.is_set():
                return
            continue
        if job is None:
            return
        item, local_src, downloaded = job
        rel = item["rel"]
        try:
            if ctx.stop.is_set():
                if downloaded:
                    _rm(local_src)
                staging.release(rel)
                store.release(rel)
                continue
            verdict, payload = build_one(item, local_src, downloaded,
                                         ctx, drive, staging, store, a)
            if verdict == "done":
                store.done(rel, **(payload if isinstance(payload, dict) else {}))
            elif verdict == "requeue":
                ctx.log(f"  {rel}: возвращаю в очередь — {payload}")
                store.release(rel)
            elif verdict == "hold":
                ctx.log(f"  {rel}: отложен — {payload}")
                store.fail(rel, payload, hold=True)
                ctx.bump("failed")
            else:
                ctx.log(f"  ✗ {rel}: не собралось — {payload}")
                store.fail(rel, payload)
                ctx.bump("failed")
        finally:
            ready_q.task_done()


# ── сторож ───────────────────────────────────────────────────────────────────
def watchdog(ctx, staging, store, a):
    """Смотрит на три вещи: двигаются ли байты, есть ли место, не нажал ли
    человек STOP. Сознательно НЕ смотрит, «работают ли кодировщики»: стоящий на
    reserve() кодировщик — правильная форма прогона, а не зависание."""
    last_progress = time.time()
    while not ctx.stop.is_set():
        time.sleep(30)
        if os.path.exists(ctx.stop_file()):
            ctx.halt("файл STOP в стейджинге")
            staging.abort()
            return
        # место: подгоняем потолок под то, сколько свободно на самом деле
        try:
            staging.retune()
        except Exception as e:
            ctx.log(f"сторож: потолок не пересчитался: {e}")
        free = K.free_gb(ctx.stage)
        if free < a.min_free_gb * 0.6:
            ctx.log(f"сторож: свободно {free:.1f} ГБ — придерживаю выдачу места")
            staging.hold(True)
            ctx.tg(f"⚠️ Фабрика {ctx.unit}: на диске {free:.1f} ГБ, придержал очередь",
                   once_key="lowspace")
        else:
            staging.hold(False)
        # движение байт
        quiet = (time.time() - ctx.moved_at) / 60
        if quiet > STALL_MIN:
            ctx.halt(f"байты не двигались {quiet:.0f} мин")
            staging.abort()
            return
        if time.time() - last_progress > PROGRESS_EVERY:
            last_progress = time.time()
            c = store.counts()
            left = store.pending_bytes()
            ctx.log(f"-- {c['done']} готово, {c['todo']+c['fail']} в очереди, "
                    f"{c['lease']} в работе, отложено {c['hold']}; "
                    f"осталось {gb(left)} исходников, "
                    f"прошло {hms(time.time()-ctx.started)}")
            store.save_index()


# ── прогон ───────────────────────────────────────────────────────────────────
def run(a):
    cfg = PLAN.load_units(a.units)
    unit = PLAN.unit_by_name(cfg, a.unit)
    stage = a.stage
    ok, pid = single_instance(os.path.join(RUN_DIR, f"farm_{a.unit}.pid"))
    if not ok:
        print(f"фабрика {a.unit} уже идёт (pid {pid}) — второй экземпляр не нужен")
        return 3

    ctx = Ctx(a.unit, stage, no_telegram=a.no_telegram)
    ctx.log("=" * 74)
    ctx.log(f"фабрика прокси {unit['name']} · {unit.get('title','')}")
    ctx.log(f"машина {os.uname().nodename} · стейджинг {stage} · "
            f"свободно {K.free_gb(stage):.1f} ГБ")
    drive = Drive(unit["remote"], unit.get("team_drive", ""),
                  tpslimit=a.tpslimit, log=ctx.log, dry_run=a.dry_run)

    plan_doc = load_plan(unit, drive, ctx)
    clips = plan_doc["clips"]
    meta = plan_doc.get("meta", {})
    if meta.get("problems"):
        ctx.log(f"⛔ манифест помечен неполным ({len(meta['problems'])} записей) — "
                f"прогон отменён")
        return 2
    ctx.log(f"манифест: {len(clips)} клипов, {gb(meta.get('bytes',0))} исходников, "
            f"построен {meta.get('built_at','?')} на {meta.get('built_on','?')}")

    # ⚠️ У сухого прогона СВОЙ журнал. Общий он бы отравил: сухой прогон
    # помечает клипы сделанными, ничего не собрав, а журнал — это кэш
    # возобновления. Боевой прогон после сухого решил бы, что всё готово,
    # и не собрал бы ни одного клипа, отчитавшись зелёным.
    store = Store(os.path.join(RUN_DIR, a.unit + ("-dry" if a.dry_run else ""))).open()
    _, bad = store.replay()
    if bad:
        ctx.log(f"журнал: {bad} битых строк пропущено, остальное проиграно "
                f"({store.replayed} записей)")
    store.put_plan(clips, meta)
    stuck = store.release_all_leases()
    if stuck:
        ctx.log(f"снял лизы прошлого прогона: {stuck} (он был убит, а не завершён — "
                f"иначе эти клипы три часа висели бы «в работе» ни у кого)")

    # Что уже лежит на Drive — одним снимком. Поклипные обращения это и время,
    # и лишний повод получить rate limit.
    snap = drive.snapshot(unit["drive_kit"])
    if snap is None:
        ctx.log("снимок комплекта на Drive не снялся — прогон отменён: "
                "без него мы не знаем, что уже сделано, и пересобрали бы всё")
        return 2
    ready = 0
    for c in clips:
        inner = c["dst_drive"][len(unit["drive_kit"].rstrip("/")) + 1:]
        rec = snap.get(R.nfc(inner))
        if store.clips.get(c["rel"], {}).get("state") == "done":
            continue
        if rec is None:
            continue
        # На Drive что-то лежит. Годно ли оно — решает контракт, а не наличие.
        # Скачать и проверить дешевле, чем пересобрать, ТОЛЬКО если файл похож
        # на прокси по весу; иначе это старый комплект и он пересобирается.
        dsize = int(rec.get("Size") or 0)
        ratio = (c["size"] / dsize) if dsize else 0
        if a.trust_drive and dsize and K.RATIO_WINDOW[0] <= ratio <= K.RATIO_WINDOW[1]:
            store.mark_done_from_drive(c["rel"], dsize,
                                       f"на Drive уже лежит, сжатие ×{ratio:.1f}")
            ready += 1
    if ready:
        ctx.log(f"уже на Drive и принято без пересборки: {ready} "
                f"(флаг --trust-drive; без него пересобирается всё)")

    c0 = store.counts()
    ctx.log(f"очередь: {c0['todo']} к сборке, {c0['done']} готово, "
            f"{c0['hold']} отложено, {c0['fail']} с провалом")
    if a.revive_on_start and (c0["hold"] or c0["fail"]):
        n = store.revive()
        ctx.log(f"вернул в очередь отложенное: {n} (причина провала могла пройти сама)")

    if not (store.counts()["todo"] or store.counts()["fail"]):
        ctx.log("делать нечего: всё собрано")
        store.save_index()
        return 0

    # Потолок стейджинга: свободно − неприкосновенный запас. Один клип FX3
    # бывает 52 ГБ, и вместе с прокси это 55 ГБ на один слот, поэтому потолок
    # и число воркеров связаны: два воркера требуют вдвое больше площадки.
    floor = int(a.min_free_gb * 1e9)
    cap = max(int(K.free_gb(stage) * 1e9) - floor, 8 * 1024 ** 3)
    staging = R.Staging(cap, log=ctx.log, floor_bytes=floor, stage_dir=stage)
    ctx.log(f"стейджинг: потолок {gb(cap)}, неприкосновенный запас {gb(floor)}; "
            f"качалок {a.fetchers}, кодировщиков {a.jobs}, "
            f"упреждение {a.prefetch} клипов")

    load_flag(True, unit["name"], log=ctx.log)
    ctx.tg(f"🪶 Фабрика прокси {unit['name']}: старт, "
           f"{store.counts()['todo']} клипов, {gb(store.pending_bytes())} исходников")

    # ⚠️ Маркер «идёт пересборка» в комплекте. Заливка идёт НА ТЕ ЖЕ ПУТИ —
    # так живы id папок и ссылки, розданные монтажёру, и не трогаются 277
    # транскриптов, которые лежат в комплекте и других копий вне _work не имеют.
    # Плата за это одна: пока прогон идёт, комплект наполовину старый. Значит об
    # этом надо сказать вслух прямо в папке, а не надеяться, что никто не зайдёт.
    marker = unit["drive_kit"].rstrip("/") + "/_farm_ПЕРЕСБОРКА_ИДЁТ.md"
    if not a.dry_run:
        try:
            drive.put_text(
                f"# Комплект пересобирается\n\n"
                f"Начато {time.strftime('%d.%m.%Y %H:%M')} на {os.uname().nodename}.\n"
                f"Клипов к сборке: {store.counts()['todo']}.\n\n"
                f"Пока этот файл здесь, часть прокси — старые, часть — новые.\n"
                f"**Монтажёру комплект не отдавать.** Файл исчезнет сам, когда\n"
                f"приёмка станет зелёной; если он остался — смотреть\n"
                f"`_farm_acceptance.md` рядом.\n", marker)
        except Exception as e:
            ctx.log(f"маркер пересборки не лёг на Drive: {e}")

    wd = threading.Thread(target=watchdog, args=(ctx, staging, store, a), daemon=True)
    wd.start()

    # Два пула внахлёст. Узкое место — СКАЧИВАНИЕ, а не кодировщик: замер
    # 23.09.2026 даёт 14 МБ/с в один поток против 42 МБ/с восемью разными
    # файлами, а кодировщик переваривает ~70 МБ/с по входу. Поэтому качалок
    # много, кодировщиков мало, и очередь готового ограничена, чтобы качалки
    # не убежали вперёд дальше, чем есть место на диске.
    ready_q = queue.Queue(maxsize=max(1, a.prefetch))
    fetchers = [threading.Thread(target=fetcher, args=(f"f{i+1}", ctx, drive, staging,
                                                       store, ready_q, a), daemon=True)
                for i in range(a.fetchers)]
    encoders = [threading.Thread(target=encoder, args=(f"e{i+1}", ctx, drive, staging,
                                                       store, ready_q, a), daemon=True)
                for i in range(a.jobs)]
    for t in fetchers + encoders:
        t.start()
    try:
        for t in fetchers:
            while t.is_alive():
                t.join(timeout=5)
        ctx.fetch_done.set()          # качать больше нечего
        for t in encoders:
            while t.is_alive():
                t.join(timeout=5)
    except KeyboardInterrupt:
        ctx.halt("прервано с клавиатуры")
        staging.abort()
    finally:
        ctx.stop.set()
        load_flag(False, unit["name"], log=ctx.log)
        # Лизы отпускаем: клип не виноват, что прогон закончился.
        for rel, c in list(store.clips.items()):
            if c["state"] == "lease":
                store.release(rel)
        store.save_index()
        store.close()

    return report(ctx, store, drive, unit, a)


def report(ctx, store, drive, unit, a):
    c = store.counts()
    took = time.time() - ctx.started
    h = ctx.hb
    lines = [
        f"# Приёмка фабрики прокси — {unit['name']}",
        "",
        f"- прогон: {hms(took)} на {os.uname().nodename}",
        f"- собрано: {h['encoded']} кодированием, {h['copied']} копией, "
        f"{h['spanners']} спаннеров server-side",
        f"- принято без пересборки: {h['skipped']}",
        f"- скачано с Drive: {gb(h['bytes_in'])} · залито: {gb(h['bytes_out'])}",
        f"- очередь на выходе: готово {c['done']}, осталось {c['todo']+c['fail']}, "
        f"отложено {c['hold']}",
        f"- провалов за прогон: {h['failed']}",
        "",
    ]
    held = store.held()
    if held:
        lines.append("## Отложено — ждёт человека")
        lines.append("")
        for x in held:
            lines.append(f"- `{x['rel']}` — {x.get('err','')}")
        lines.append("")
    green = not (c["todo"] + c["fail"] + c["hold"])
    verdict = ("✅ комплект собран полностью" if green
               else "⚠️ комплект НЕ полон — отдавать монтажёру нельзя")
    lines.append(verdict)
    text = "\n".join(lines)
    path = os.path.join(RUN_DIR, f"acceptance_{unit['name']}.md")
    open(path, "w").write(text)
    ctx.log("")
    ctx.log(text)
    ctx.log(f"приёмка: {path}")
    if not a.dry_run:
        try:
            drive.put_text(text, unit["drive_kit"].rstrip("/") + "/_farm_acceptance.md")
        except Exception as e:
            ctx.log(f"приёмку на Drive не положил: {e}")
        # Маркер снимается ТОЛЬКО по зелёной приёмке. Не сошлось — пусть висит:
        # комплект в этом состоянии отдавать нельзя, и молчать об этом нельзя.
        if green:
            try:
                drive.call(["deletefile", drive.at(
                    unit["drive_kit"].rstrip("/") + "/_farm_ПЕРЕСБОРКА_ИДЁТ.md")],
                    single_file=True, timeout=300, tolerate=("notfound",))
                ctx.log("маркер пересборки снят: комплект полон")
            except Exception as e:
                ctx.log(f"маркер пересборки не снялся: {e}")
    ctx.tg(f"{'✅' if not (c['todo']+c['fail']+c['hold']) else '⚠️'} "
           f"Фабрика {unit['name']}: готово {c['done']}, "
           f"осталось {c['todo']+c['fail']}, отложено {c['hold']}, "
           f"за {hms(took)}")
    return 0 if not (c["todo"] + c["fail"] + c["hold"]) else 1


def status(a):
    store = Store(os.path.join(RUN_DIR, a.unit))
    _, bad = store.replay()
    c = store.counts()
    print(f"фабрика {a.unit}: " + ", ".join(f"{k} {v}" for k, v in c.items()))
    print(f"осталось исходников: {gb(store.pending_bytes())}"
          + (f" · битых строк журнала: {bad}" if bad else ""))
    held = store.held()
    if held:
        print(f"\nотложено ({len(held)}) — ждёт человека:")
        for x in held[:30]:
            print(f"  · {x['rel']} — {x.get('err','')}")
    return 0


def revive(a):
    store = Store(os.path.join(RUN_DIR, a.unit)).open()
    store.replay()
    n = store.revive()
    store.save_index()
    store.close()
    print(f"вернул в очередь: {n}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="фабрика прокси, работающая от Drive")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--unit", required=True)
        p.add_argument("--units", default=PLAN.UNITS_PATH)

    pr = sub.add_parser("run", help="боевой прогон")
    common(pr)
    pr.add_argument("--jobs", type=int, default=1,
                    help="воркеров; hevc_videotoolbox — один аппаратный блок, "
                         "два потока покупают ~8%% и стоят вдвое больше площадки")
    pr.add_argument("--fetchers", type=int, default=4,
                    help="сколько РАЗНЫХ файлов качать одновременно; узкое место "
                         "конвейера здесь (14 МБ/с в один поток против 42 в восемь). "
                         "Рвать ОДИН файл на потоки нельзя — счётчик квоты по файлу")
    pr.add_argument("--prefetch", type=int, default=4,
                    help="на сколько клипов качалки могут убежать вперёд")
    pr.add_argument("--stage", default=DEFAULT_STAGE)
    pr.add_argument("--min-free-gb", type=float, default=MIN_FREE_GB)
    pr.add_argument("--bitrate", default="auto",
                    help="auto = по частоте кадров из контракта (25p 8M, 50p 12M)")
    pr.add_argument("--chroma", default="420", choices=("420", "422"))
    pr.add_argument("--tpslimit", type=int, default=8)
    pr.add_argument("--dry-run", action="store_true")
    pr.add_argument("--no-telegram", action="store_true")
    pr.add_argument("--trust-drive", action="store_true",
                    help="принять уже лежащее на Drive, если сжатие в коридоре; "
                         "БЕЗ этого флага пересобирается всё — так и надо, когда "
                         "старый комплект собран не по контракту")
    pr.add_argument("--revive-on-start", action="store_true", default=True)

    ps = sub.add_parser("status", help="где стоим")
    common(ps)
    pv = sub.add_parser("revive", help="вернуть отложенное в очередь")
    common(pv)
    sub.add_parser("selftest", help="чистая логика, без диска и сети")
    pp = sub.add_parser("plan", help="построить манифест (там, где диски)")
    common(pp)
    pp.add_argument("--publish", action="store_true")

    a = ap.parse_args()
    if a.cmd == "selftest":
        import selftest
        return selftest.main()
    if a.cmd == "plan":
        argv = ["--unit", a.unit, "--units", a.units] + (["--publish"] if a.publish else [])
        sys.argv = [PLAN.__file__] + argv
        return PLAN.main()
    if a.cmd == "status":
        return status(a)
    if a.cmd == "revive":
        return revive(a)
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
