#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Drive для фабрики прокси: снимок, скачивание, заливка, сверка.

Здесь только Drive. Контракт прокси живёт в `1601_build/contract.py`, логистика
места и разбор отказов — в `1601_build/rebuild.py`; оба переиспользуются
ИМПОРТОМ, своей копии тут нет. Ровно три разошедшиеся копии рецепта стоили
комплекта YTCH (441 прокси 8-битными и без таймкода), и заводить четвёртую,
пусть и «только для Мемекса», нельзя.

Что этот модуль добавляет к rclone:

  · щадящие флаги по умолчанию — Drive отдаёт 403 за темп, а не за объём;
  · ⚠️ операции НАД ОДНИМ ФАЙЛОМ идут БЕЗ фильтров. `copyto` с `--exclude`
    падает насмерть: «CRITICAL: can't limit to single files when using
    filters». Этим же copyto идёт каждая заливка и каждое скачивание — забыть
    здесь значит провалить весь прогон, ничего не собрав;
  · разбор отказа в решение (ждать квоту / повторить / отложить) — таблицей из
    rebuild.py, потому что одну и ту же беду rclone пишет двумя способами;
  · сверка залитого ПО РАЗМЕРУ С DRIVE, а не по своему же отчёту.

Версия 1.0 · 23.09.2026 · этап 16_proxy/1603_farm
"""
import json
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "1601_build"))
import rebuild as R                     # noqa: E402  classify_rclone, gb, nfc, parse_modtime

classify_rclone = R.classify_rclone
gb = R.gb
nfc = R.nfc
parse_modtime = R.parse_modtime

#: Щадящий темп. Замер прошлых прогонов: выше 8 запросов в секунду Drive
#: отвечает 403 «Queries per minute» и rclone уходит в ретраи, раздувая счётчик
#: и роняя часть файлов. Медленно и до конца лучше, чем быстро и до первого 403.
TPSLIMIT = 8
#: Квота Drive 750 ГБ в сутки на аккаунт. Ловится только текстом отказа;
#: лечится ожиданием, а не повтором.
QUOTA_SLEEP = 3600


class DriveError(RuntimeError):
    """Отказ Drive с уже принятым решением, что с ним делать."""

    def __init__(self, kind, action, human, text=""):
        super().__init__(f"{kind}: {human}")
        self.kind = kind          # quota | rate | auth | network | notfound | nospace | other
        self.action = action      # wait-quota | retry | retry-later | give-up
        self.human = human
        self.text = text


class Drive:
    """Один remote и один способ с ним говорить.

    remote — имя из rclone.conf (`gdrive_ytevo`), team_drive — id Shared Drive,
    если remote его сам не несёт. Пути внутри — как их печатает rclone, со
    слэшами и без ведущего.
    """

    def __init__(self, remote, team_drive="", tpslimit=TPSLIMIT, bind_v4=True,
                 log=print, dry_run=False, runner=None):
        self.remote = remote
        self.team_drive = team_drive or ""
        self.tpslimit = int(tpslimit)
        self.bind_v4 = bind_v4
        self.log = log
        self.dry_run = dry_run
        self._run = runner or self._subprocess_run
        self.bytes_down = 0
        self.bytes_up = 0
        self.calls = 0

    # ── адреса и флаги ───────────────────────────────────────────────────────
    def at(self, path=""):
        td = f",team_drive={self.team_drive}" if self.team_drive else ""
        return f"{self.remote}{td}:{path}"

    def flags(self, single_file):
        """⚠️ single_file=True — для copyto/moveto/deletefile/lsjson одного файла.
        Любой фильтр в такой команде это мгновенное CRITICAL, а не предупреждение.
        Фильтры имеют смысл только там, где rclone обходит дерево."""
        f = ["--tpslimit", str(self.tpslimit), "--drive-chunk-size", "128M",
             "--retries", "5", "--low-level-retries", "20",
             "--timeout", "300s", "--contimeout", "60s",
             "--drive-stop-on-upload-limit",
             # ⚠️ ОДИН поток НА ФАЙЛ, всегда. По умолчанию rclone рвёт файл
             # крупнее 250 МБ на 4 параллельных потока, а счётчик Google
             # `downloadQuotaExceeded` считается ПО ФАЙЛУ и общий для всех
             # пользователей: четыре Range-потока это четыре открытия одного
             # файла. Так сгорел кат YTCR04 (403 посреди скачивания, обход
             # копией тоже закрылся) и файл 140 ГБ на YTEVO02. Лимит снимается
             # ТИШИНОЙ, а не настойчивостью, и стоит часов простоя.
             # Скорость берётся иначе — НЕСКОЛЬКИМИ ФАЙЛАМИ сразу (у каждого
             # счётчик свой), этим занимается пул качалок в farm.py.
             "--multi-thread-streams", "0"]
        if not single_file:
            f += ["--exclude", ".DS_Store", "--exclude", "._*"]
        if self.bind_v4:
            # На этом канале IPv6 периодически упирается в DPI и соединение
            # висит молча. Дешевле сразу ходить по v4 (память net-ipv6-dpi).
            f += ["--bind", "0.0.0.0"]
        return f

    # ── запуск ───────────────────────────────────────────────────────────────
    def _subprocess_run(self, cmd, timeout):
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def call(self, args, single_file=False, timeout=7200, tolerate=()):
        """Одна команда rclone. Отказ → DriveError с решением.

        tolerate — виды отказов, которые вернуть молча (например notfound там,
        где отсутствие файла это нормальный ответ, а не беда).
        """
        cmd = ["rclone", *args, *self.flags(single_file)]
        self.calls += 1
        try:
            r = self._run(cmd, timeout)
        except subprocess.TimeoutExpired:
            raise DriveError("network", "retry",
                             f"rclone не ответил за {timeout} с", "timeout")
        if r.returncode == 0:
            return r.stdout
        text = f"{r.stdout}\n{r.stderr}"
        kind, action, human = classify_rclone(r.returncode, text)
        if kind in tolerate:
            return ""
        raise DriveError(kind, action, human, text[-800:])

    # ── чтение ───────────────────────────────────────────────────────────────
    def snapshot(self, path, tries=3):
        """Снимок папки: {относительный путь: запись rclone}. None — снять НЕ
        ВЫШЛО, и это не то же самое, что пустая папка: пустой снимок означал бы
        «на Drive ничего нет» и запустил бы пересборку всего уже лежащего.

        Снимок берётся РАЗ на прогон: обращаться к Drive поклипно — это и время,
        и лишний повод получить rate limit.
        """
        for attempt in range(1, tries + 1):
            try:
                out = self.call(["lsjson", "-R", "--files-only", "--no-mimetype",
                                 self.at(path)], timeout=1800, tolerate=("notfound",))
                if out == "":
                    return {}
                rows = json.loads(out)
                return {nfc(r["Path"]): r for r in rows}
            except DriveError as e:
                if e.action == "give-up" or attempt == tries:
                    self.log(f"  снимок Drive не снялся ({e.human}) — "
                             f"попытка {attempt} из {tries}")
                    return None
                self.log(f"  снимок Drive: {e.human}, повтор через 30 с")
                time.sleep(30)
            except Exception as e:
                if attempt == tries:
                    self.log(f"  снимок Drive не разобрался: {e}")
                    return None
                time.sleep(15)
        return None

    def stat(self, path):
        """Одна запись о файле. None — файла нет. Размер в байтах — это то,
        по чему потом выносится приговор «залито».

        ⚠️ Без фильтров: lsjson по одному файлу — тоже операция над одним файлом.
        """
        try:
            out = self.call(["lsjson", "--files-only", "--no-mimetype", self.at(path)],
                            single_file=True, timeout=300, tolerate=("notfound",))
        except DriveError as e:
            if e.kind == "notfound":
                return None
            raise
        if not out.strip():
            return None
        try:
            rows = json.loads(out)
        except Exception:
            return None
        return rows[0] if rows else None

    # ── перенос ──────────────────────────────────────────────────────────────
    def download(self, remote_path, local_path, timeout=10800):
        """Скачать один файл. Атомарно: во временное имя, потом replace — на
        месте назначения не бывает полуфайла, который кто-то примет за готовый.

        Возобновление не нужно: rclone сам переживает моргнувшую сеть своими
        ретраями, а сорванный целиком файл дешевле скачать заново, чем
        доказывать, что недокачанный хвост цел.
        """
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        tmp = local_path + ".part"
        if self.dry_run:
            self.log(f"  [сухо] скачал бы {remote_path}")
            return 0
        if os.path.exists(tmp):
            os.remove(tmp)
        self.call(["copyto", self.at(remote_path), tmp], single_file=True, timeout=timeout)
        size = os.path.getsize(tmp)
        os.replace(tmp, local_path)
        self.bytes_down += size
        return size

    def upload(self, local_path, remote_path, timeout=10800):
        """Залить один файл НА ТОТ ЖЕ ПУТЬ. copyto по существующему пути
        обновляет тот же файл: id папок живы, ссылки, розданные монтажёру, тоже.
        Возвращает размер, подтверждённый снимком Drive, а не своим отчётом.
        """
        if self.dry_run:
            self.log(f"  [сухо] залил бы {remote_path}")
            return os.path.getsize(local_path)
        local_size = os.path.getsize(local_path)
        self.call(["copyto", local_path, self.at(remote_path)],
                  single_file=True, timeout=timeout)
        self.bytes_up += local_size
        rec = self.stat(remote_path)
        if rec is None:
            raise DriveError("notfound", "retry",
                             "после заливки файла на Drive нет — повторю")
        got = int(rec.get("Size") or 0)
        if got != local_size:
            raise DriveError("other", "retry",
                             f"на Drive {got} Б вместо {local_size} Б — залью заново")
        return got

    def copy_server_side(self, src_path, dst_path, timeout=1800):
        """Копия в пределах одного remote. Трафика не тратит — так делается
        вторая копия клипа-спаннера и так же переименовываются луты."""
        if self.dry_run:
            self.log(f"  [сухо] скопировал бы на Drive {src_path} → {dst_path}")
            return True
        self.call(["copyto", self.at(src_path), self.at(dst_path)],
                  single_file=True, timeout=timeout)
        return True

    def put_text(self, text, remote_path, timeout=600):
        """Положить на Drive небольшой текст (манифест, отчёт). Через временный
        файл: rclone умеет rcat, но он не переживает обрыв так же спокойно."""
        import tempfile
        if self.dry_run:
            self.log(f"  [сухо] записал бы {remote_path} ({len(text)} Б)")
            return True
        fd, tmp = tempfile.mkstemp(prefix=".farm-", suffix=".json")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(text)
            self.call(["copyto", tmp, self.at(remote_path)],
                      single_file=True, timeout=timeout)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return True

    def get_text(self, remote_path, timeout=600):
        """Прочитать небольшой файл с Drive. None — нет файла."""
        try:
            return self.call(["cat", self.at(remote_path)],
                             single_file=True, timeout=timeout, tolerate=())
        except DriveError as e:
            if e.kind == "notfound":
                return None
            raise


def sleep_for_quota(log=print, seconds=QUOTA_SLEEP, sleeper=time.sleep):
    """Квота на сутки не лечится повтором — только ожиданием. Спим и
    продолжаем с ТОГО ЖЕ клипа: ничего не потеряно, просто отложено."""
    log(f"  квота Drive: жду {seconds // 60} мин и продолжаю с того же клипа")
    sleeper(seconds)
