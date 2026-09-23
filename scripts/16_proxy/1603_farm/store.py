#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Долговечная очередь фабрики прокси: журнал-истина, производный индекс, лизы.

Зачем отдельный модуль, а не словарь в памяти. Фабрика живёт на машине в другой
стране, работает ночами по нескольку часов и обязана переживать всё: обрыв ssh,
перезагрузку, kill -9, порчу файла состояния, две попытки запуска сразу. Значит
очередь — не структура данных, а протокол на диске. Три правила, из которых
растёт весь модуль:

  1. ИСТИНА — ЖУРНАЛ, и он только дописывается. `journal.jsonl`, одна запись в
     строку, fsync после каждой. Никакая беда не может стереть то, что уже
     записано, потому что записанное никогда не перезаписывается.

  2. ИНДЕКС — ПРОИЗВОДНОЕ. `index.json` это кэш, чтобы не перечитывать журнал
     на каждый чих. Потерялся, испортился, отстал — не беда: восстанавливается
     проигрыванием журнала. Поэтому пишется атомарно (временный файл + replace)
     и никогда не считается источником правды.

  3. КЛИП НЕ ТЕРЯЕТСЯ И НЕ ДЕЛАЕТСЯ ДВАЖДЫ. Взятый в работу клип получает лизу
     со сроком. Воркер упал, машина перезагрузилась, процесс убит — лиза
     истекает, и клип возвращается в очередь сам. Никакой ручной расчистки
     «подвисших» записей: их нет как класса.

⚠️ Писатель у журнала ОДИН — этот класс, под замком. Два писателя одного JSON
уже стоили молча потерянных данных (память no-parallel-writers), и повторять
это здесь нельзя тем более: журнал — единственное, что остаётся после падения.

⚠️ Окончательная истина о сделанной работе живёт НЕ ЗДЕСЬ, а на Drive: клип
сделан, если прокси лежит на месте и проходит контракт. Этот модуль лишь делает
возобновление дешёвым. Полная потеря его файлов не теряет ни одного клипа —
только заставляет заново снять снимок Drive. Так и задумано.

Версия 1.0 · 23.09.2026 · этап 16_proxy/1603_farm
"""
import json
import os
import tempfile
import threading
import time

#: Сколько живёт лиза на клип. Дольше самого долгого мыслимого клипа: замер
#: 52 ГБ FX3 — 21 минута кодирования плюс скачивание с Drive на 20–40 МБ/с,
#: то есть под час. Берём с запасом втрое: лишний час ожидания дешевле, чем
#: два воркера, одновременно делающие один клип.
LEASE_SEC = 3 * 3600

#: Сколько раз пробуем один клип, прежде чем отложить его совсем. Провал не
#: обязательно вечен: сеть, квота и перегрев проходят сами.
MAX_ATTEMPTS = 3


def _utc():
    """Время строкой. Отдельной функцией, чтобы selftest мог подменить."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


class Store:
    """Очередь работ на диске. Потокобезопасен, писатель один.

    Состояния клипа: `todo` → `lease` → `done` | `fail` | `hold`.
      todo   в плане, никто не взял
      lease  взят воркером, срок идёт
      done   собран, залит и подтверждён на Drive — больше не трогаем
      fail   попытка не удалась, вернётся в очередь (пока попытки не вышли)
      hold   попытки вышли либо причина неустранима сама — ждёт человека
    """

    def __init__(self, run_dir, lease_sec=LEASE_SEC, max_attempts=MAX_ATTEMPTS,
                 now=_utc, clock=time.time):
        self.run_dir = run_dir
        self.lease_sec = lease_sec
        self.max_attempts = max_attempts
        self.now = now
        self.clock = clock
        os.makedirs(run_dir, exist_ok=True)
        self.journal_path = os.path.join(run_dir, "journal.jsonl")
        self.index_path = os.path.join(run_dir, "index.json")
        self._lock = threading.RLock()
        self._fh = None
        self.clips = {}          # rel → запись
        self.order = []          # порядок из плана: приоритет Романа
        self.replayed = 0

    # ── журнал ───────────────────────────────────────────────────────────────
    def open(self):
        """Открыть журнал на дозапись. Строчная буферизация плюс fsync: падение
        между строками не должно оставить полстроки."""
        with self._lock:
            if self._fh is None:
                self._fh = open(self.journal_path, "a", buffering=1)
        return self

    def close(self):
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.flush()
                    os.fsync(self._fh.fileno())
                finally:
                    self._fh.close()
                    self._fh = None

    def _append(self, event):
        """Одна запись в журнал. Под замком, с fsync. Двести клипов за ночь —
        цена fsync здесь неизмеримо мала, а польза абсолютна."""
        event.setdefault("at", self.now())
        line = json.dumps(event, ensure_ascii=False)
        with self._lock:
            if self._fh is None:
                self.open()
            self._fh.write(line + "\n")
            self._fh.flush()
            try:
                os.fsync(self._fh.fileno())
            except OSError:
                pass       # сетевой том или закрытый дескриптор — строка уже записана

    # ── проигрывание ─────────────────────────────────────────────────────────
    def replay(self):
        """Собрать состояние из журнала. Битые строки пропускаются поимённо:
        одна порченая строка не имеет права обнулить всю ночь работы."""
        with self._lock:
            self.clips, self.order, self.replayed = {}, [], 0
            bad = 0
            if not os.path.exists(self.journal_path):
                return self, bad
            for raw in open(self.journal_path, errors="replace"):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    e = json.loads(raw)
                except Exception:
                    bad += 1
                    continue
                self._apply(e)
                self.replayed += 1
            return self, bad

    def _apply(self, e):
        kind, rel = e.get("kind"), e.get("rel")
        if kind == "plan":
            for item in e.get("clips", []):
                r = item["rel"]
                if r not in self.clips:
                    self.clips[r] = {**item, "state": "todo", "attempts": 0,
                                     "lease_until": 0, "err": "", "worker": ""}
                    self.order.append(r)
                else:
                    # План пересняли: обновляем сведения об источнике, но НЕ
                    # трогаем состояние — сделанное остаётся сделанным.
                    keep = {k: self.clips[r][k] for k in
                            ("state", "attempts", "lease_until", "err", "worker")}
                    self.clips[r].update(item)
                    self.clips[r].update(keep)
            return
        if not rel or rel not in self.clips:
            return
        c = self.clips[rel]
        if kind == "claim":
            c["state"] = "lease"
            c["lease_until"] = e.get("until", 0)
            c["worker"] = e.get("worker", "")
            c["attempts"] = e.get("attempt", c["attempts"])
        elif kind == "done":
            c["state"] = "done"
            c["lease_until"] = 0
            c["err"] = ""
            for k in ("action", "reason", "out_size", "ratio", "took", "drive_size"):
                if k in e:
                    c[k] = e[k]
        elif kind == "fail":
            c["attempts"] = e.get("attempt", c["attempts"] + 1)
            c["err"] = e.get("err", "")
            c["lease_until"] = 0
            c["state"] = "hold" if (e.get("hold")
                                    or c["attempts"] >= self.max_attempts) else "fail"
        elif kind == "release":
            if c["state"] == "lease":
                c["state"] = "todo"
                c["lease_until"] = 0
        elif kind == "hold":
            c["state"] = "hold"
            c["err"] = e.get("err", c.get("err", ""))
            c["lease_until"] = 0
        elif kind == "revive":
            if c["state"] in ("hold", "fail"):
                c["state"] = "todo"
                c["attempts"] = 0
                c["err"] = ""

    # ── план ─────────────────────────────────────────────────────────────────
    def put_plan(self, clips, meta=None):
        """Записать план работ. Идемпотентно: повторная запись того же плана не
        сбрасывает сделанное (см. _apply/'plan')."""
        self._append({"kind": "plan", "clips": list(clips), "meta": meta or {}})
        with self._lock:
            self._apply({"kind": "plan", "clips": list(clips)})
        return len(clips)

    # ── выдача работы ────────────────────────────────────────────────────────
    def claim(self, worker):
        """Взять следующий клип. None — работы нет.

        Порядок: сперва ни разу не пробованные (по порядку плана), потом
        провалившиеся (у них попытки ещё есть). Истёкшие лизы подбираются как
        обычный `todo` — отдельной расчистки не нужно.
        """
        with self._lock:
            nowt = self.clock()
            for pool in ("todo", "fail"):
                for rel in self.order:
                    c = self.clips.get(rel)
                    if not c:
                        continue
                    st = c["state"]
                    if st == "lease" and c["lease_until"] and c["lease_until"] < nowt:
                        st = "todo"          # лиза истекла — клип снова свободен
                        c["state"] = "todo"
                    if st != pool:
                        continue
                    if c["attempts"] >= self.max_attempts:
                        c["state"] = "hold"
                        continue
                    attempt = c["attempts"] + 1
                    until = nowt + self.lease_sec
                    c.update(state="lease", lease_until=until,
                             worker=worker, attempts=attempt)
                    self._append({"kind": "claim", "rel": rel, "worker": worker,
                                  "attempt": attempt, "until": until})
                    return dict(c, rel=rel)
            return None

    def done(self, rel, **fields):
        with self._lock:
            self._append({"kind": "done", "rel": rel, **fields})
            self._apply({"kind": "done", "rel": rel, **fields})

    def fail(self, rel, err, hold=False):
        with self._lock:
            c = self.clips.get(rel) or {}
            attempt = c.get("attempts", 0)
            self._append({"kind": "fail", "rel": rel, "err": str(err)[:400],
                          "attempt": attempt, "hold": bool(hold)})
            self._apply({"kind": "fail", "rel": rel, "err": str(err)[:400],
                         "attempt": attempt, "hold": bool(hold)})

    def release(self, rel):
        """Вернуть клип в очередь, не считая попытку израсходованной. Нужно при
        остановке прогона: человек нажал стоп — клип не виноват."""
        with self._lock:
            self._append({"kind": "release", "rel": rel})
            self._apply({"kind": "release", "rel": rel})

    def revive(self, rels=None):
        """Вернуть отложенные клипы в очередь. Причина провала могла пройти
        сама: сеть, квота, перегрев. Без этого отложенное ждало бы человека."""
        with self._lock:
            targets = rels if rels is not None else [
                r for r, c in self.clips.items() if c["state"] in ("hold", "fail")]
            for r in targets:
                self._append({"kind": "revive", "rel": r})
                self._apply({"kind": "revive", "rel": r})
            return len(targets)

    def mark_done_from_drive(self, rel, drive_size, reason):
        """Клип уже лежит на Drive и признан годным снимком. Записываем как
        сделанный, не тратя ни байта трафика."""
        self.done(rel, action="skip", reason=reason, drive_size=drive_size)

    # ── сводка ───────────────────────────────────────────────────────────────
    def counts(self):
        with self._lock:
            nowt = self.clock()
            out = {"todo": 0, "lease": 0, "done": 0, "fail": 0, "hold": 0}
            for c in self.clips.values():
                st = c["state"]
                if st == "lease" and c["lease_until"] and c["lease_until"] < nowt:
                    st = "todo"
                out[st] = out.get(st, 0) + 1
            return out

    def pending_bytes(self):
        """Сколько исходных байт осталось. Для честного ETA, а не «по клипам»:
        клипы у нас от 2 МБ до 52 ГБ, средний по ним смысла не имеет."""
        with self._lock:
            nowt = self.clock()
            tot = 0
            for c in self.clips.values():
                st = c["state"]
                if st == "lease" and c["lease_until"] and c["lease_until"] < nowt:
                    st = "todo"
                if st in ("todo", "fail", "lease"):
                    tot += int(c.get("size") or 0)
            return tot

    def held(self):
        with self._lock:
            return [dict(c, rel=r) for r, c in self.clips.items()
                    if c["state"] == "hold"]

    def save_index(self):
        """Производный кэш. Атомарно: временный файл рядом + replace. Оборвись
        запись на середине — на месте останется прошлая целая версия."""
        with self._lock:
            payload = {"at": self.now(), "counts": self.counts(),
                       "clips": self.clips, "order": self.order}
        d = os.path.dirname(self.index_path) or "."
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".index-", suffix=".json")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(payload, fh, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.index_path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        return self.index_path
