#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Регрессия фабрики: чистая логика, без сети и без медиа.

Проверяет то, что нельзя проверить глазами и что дороже всего ломать: протокол
очереди (журнал, лизы, возобновление), арифметику резерва, перевод путей
диск→Drive и флаги rclone. Диск используется только под временную папку.

⚠️ Правка без прошедшего selftest не уезжает ни в коммит, ни в ночь — то же
правило, что у `rebuild.py selftest`.

  python3 selftest.py
  python3 farm.py selftest
"""
import json
import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "1601_build"))
sys.path.insert(0, _HERE)
import contract as K            # noqa: E402
import rebuild as R             # noqa: E402

PASS = []
FAIL = []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name if not extra else f"{name} — {extra}")


def main():
    import store as S
    import drive as D
    import plan as P
    import farm as F

    tmp = tempfile.mkdtemp(prefix="farm-selftest-")
    try:
        # ── очередь: план, выдача, завершение ────────────────────────────────
        clock = {"t": 1000.0}
        st = S.Store(os.path.join(tmp, "q"), lease_sec=100, max_attempts=2,
                     clock=lambda: clock["t"]).open()
        clips = [{"rel": "a.MP4", "size": 10, "src_drive": "S/a", "dst_drive": "D/a"},
                 {"rel": "b.MP4", "size": 20, "src_drive": "S/b", "dst_drive": "D/b"},
                 {"rel": "c.MP4", "size": 30, "src_drive": "S/c", "dst_drive": "D/c"}]
        st.put_plan(clips)
        check("план лёг в очередь", st.counts()["todo"] == 3)
        check("порядок плана сохранён", st.order == ["a.MP4", "b.MP4", "c.MP4"])

        i1 = st.claim("w1")
        check("выдан первый по порядку", i1 and i1["rel"] == "a.MP4")
        i2 = st.claim("w2")
        check("второму воркеру достался другой клип", i2 and i2["rel"] == "b.MP4")
        check("взятое не выдаётся снова", st.counts()["lease"] == 2)

        st.done("a.MP4", action="encode", out_size=1, drive_size=1)
        check("сделанное помечено", st.clips["a.MP4"]["state"] == "done")

        # ── лиза истекает, клип возвращается САМ ─────────────────────────────
        clock["t"] += 101
        check("истёкшая лиза читается как todo", st.counts()["todo"] == 2)
        again = st.claim("w3")
        check("клип с истёкшей лизой выдан заново",
              again and again["rel"] == "b.MP4", str(again and again["rel"]))
        check("попытка посчиталась", st.clips["b.MP4"]["attempts"] == 2)

        # ── попытки кончились → hold, а не вечный круг ───────────────────────
        st.fail("b.MP4", "сеть моргнула")
        check("после исчерпания попыток клип отложен",
              st.clips["b.MP4"]["state"] == "hold", st.clips["b.MP4"]["state"])
        check("отложенное видно списком", [x["rel"] for x in st.held()] == ["b.MP4"])
        st.revive()
        check("revive вернул отложенное в очередь",
              st.clips["b.MP4"]["state"] == "todo" and st.clips["b.MP4"]["attempts"] == 0)

        # ── провал без исчерпания попыток возвращается в очередь ─────────────
        st.claim("w1")
        st.fail("b.MP4", "первый раз")
        check("первый провал не отложил клип", st.clips["b.MP4"]["state"] == "fail")
        nxt = st.claim("w1")
        check("к провалившемуся возвращаемся после непробованных",
              nxt and nxt["rel"] == "c.MP4", str(nxt and nxt["rel"]))

        # ── убитый прогон не оставляет клипы висеть на три часа ─────────────
        st.claim("wX"); st.claim("wY")
        n_lease = st.counts()["lease"]
        freed = st.release_all_leases()
        check("лизы убитого прогона снимаются на старте",
              freed == n_lease and st.counts()["lease"] == 0, f"снято {freed} из {n_lease}")
        check("снятие лиз не тратит попытки",
              all(c["attempts"] <= st.max_attempts for c in st.clips.values()))

        # ── release не тратит попытку ───────────────────────────────────────
        before = st.clips["c.MP4"]["attempts"]
        st.release("c.MP4")
        check("release вернул клип в очередь", st.clips["c.MP4"]["state"] == "todo")
        check("release не съел попытку", st.clips["c.MP4"]["attempts"] == before)

        st.save_index()
        check("индекс записан атомарно и читается",
              json.load(open(st.index_path))["counts"]["done"] == 1)
        check("временных файлов индекса не осталось",
              not [f for f in os.listdir(os.path.dirname(st.index_path))
                   if f.startswith(".index-")])
        st.close()

        # ── возобновление: состояние собирается из журнала ───────────────────
        st2 = S.Store(os.path.join(tmp, "q"), lease_sec=100, max_attempts=2,
                      clock=lambda: clock["t"])
        st2.replay()
        check("сделанное пережило перезапуск", st2.clips["a.MP4"]["state"] == "done")
        check("очередь пережила перезапуск", st2.counts()["done"] == 1)

        # ── битая строка журнала не обнуляет ночь ───────────────────────────
        with open(st2.journal_path, "a") as fh:
            fh.write("{это не json\n")
        st3 = S.Store(os.path.join(tmp, "q"), lease_sec=100, max_attempts=2,
                      clock=lambda: clock["t"])
        _, bad = st3.replay()
        check("битая строка посчитана и пропущена", bad == 1, f"bad={bad}")
        check("остальное проиграно несмотря на битую строку",
              st3.clips["a.MP4"]["state"] == "done")

        # ── повторная запись плана не сбрасывает сделанное ───────────────────
        st3.open()
        st3.put_plan(clips)
        check("повторный план не обнулил готовое",
              st3.clips["a.MP4"]["state"] == "done")
        check("повторный план не наплодил записей", len(st3.order) == 3)
        st3.close()

        # ── осталось байт: считаем по весу, а не по числу клипов ────────────
        check("осталось байт считается по незакрытым",
              st3.pending_bytes() == 50, str(st3.pending_bytes()))

        # ── резерв места ─────────────────────────────────────────────────────
        check("слепая оценка пессимистичнее ×18",
              F.est_blind(180 * 10**6) > 180 * 10**6 / 18)
        check("слепая оценка не ниже пола", F.est_blind(1) == F.EST_FLOOR)

        class Spec:
            duration = 100.0
            audio = [1, 2]
        exact = F.est_exact(Spec(), "12M")
        # 100 с × (12 Мбит + 2×256 кбит) / 8 × 1.15 ≈ 180 МБ
        check("точная оценка считает по заказанному битрейту",
              170 * 10**6 < exact < 195 * 10**6, f"{exact/1e6:.0f} МБ")
        exact8 = F.est_exact(Spec(), "12M") > F.est_exact(Spec(), "8M")
        check("50p дороже 25p в оценке", exact8)
        check("пол точной оценки не перебивает честный расчёт",
              exact < F.EST_FLOOR, f"{exact/1e6:.0f} МБ против пола "
                                   f"{F.EST_FLOOR/1e6:.0f} МБ")
        check("короткий клип всё же получает пол",
              F.est_exact(type("S", (), {"duration": 0.9, "audio": [1]})(), "12M")
              == F.EXACT_FLOOR)

        # ⚠️ Смысл всей арифметики: ×18 занижает вес 50p. Замер YTEVO03 —
        # 479 ГБ исходников, фактический комплект 34.1 ГБ, «×18» обещает 26.6.
        # Тот же клип: исходник 100 Мбит/с даёт по ×18 ≈ 69 МБ, а честный
        # расчёт на 12 Мбит/с — 180 МБ. Занижение втрое, и это тот самый способ
        # переполнить диск к утру.
        blind18 = int(100e6 * Spec.duration / 8) / 18
        check("×18 действительно занижает 50p", exact > blind18,
              f"честно {exact/1e6:.0f} МБ против ×18 {blind18/1e6:.0f} МБ")

        # ── флаги rclone: главный инвариант ──────────────────────────────────
        dv = D.Drive("gdrive_x", "TD123")
        one = dv.flags(single_file=True)
        many = dv.flags(single_file=False)
        check("⚠️ у операции над ОДНИМ файлом нет фильтров",
              "--exclude" not in one, " ".join(one))
        check("при обходе дерева фильтры есть", "--exclude" in many)
        check("темп ограничен всегда", "--tpslimit" in one and "--tpslimit" in many)
        # ⚠️ Главная мина скачивания: счётчик downloadQuotaExceeded у Google
        # считается ПО ФАЙЛУ. rclone по умолчанию рвёт файл крупнее 250 МБ на
        # 4 потока — это четыре открытия одного файла. Так сгорел кат YTCR04.
        i = one.index("--multi-thread-streams")
        check("⚠️ один поток НА ФАЙЛ: multi-thread выключен", one[i + 1] == "0",
              f"дало {one[i+1]}")
        check("multi-thread выключен и при обходе дерева",
              many[many.index("--multi-thread-streams") + 1] == "0")
        check("остановка на лимите заливки включена",
              "--drive-stop-on-upload-limit" in one)
        check("привязка к v4 включена", "--bind" in one)
        check("адрес собирается с team_drive",
              dv.at("A/b.MP4") == "gdrive_x,team_drive=TD123:A/b.MP4", dv.at("A/b.MP4"))
        check("без team_drive адрес чистый",
              D.Drive("g", "").at("x") == "g:x")

        # ── отказы Drive превращаются в решения ─────────────────────────────
        for text, want in (("User rate limit exceeded", "retry-later"),
                           ("rateLimitExceeded", "retry-later"),
                           ("storage quota exceeded", "wait-quota"),
                           ("Error 403: insufficientFilePermissions", "give-up"),
                           ("connection reset by peer", "retry"),
                           ("no space left on device", "give-up")):
            kind, action, _ = D.classify_rclone(1, text)
            check(f"отказ «{text[:28]}» → {want}", action == want, f"дало {action}")

        # ── перевод путей диск → Drive ───────────────────────────────────────
        mirrors = [{"local": "/Volumes/SD-V90-RYA",
                    "drive": "YTEVO S1/P/00_Card"},
                   {"local": "/Volumes/SD-V90-RYA/ZVe1",
                    "drive": "YTEVO S1/P/00_Card/ZVe1"}]
        got = P.map_to_drive("/Volumes/SD-V90-RYA/M4ROOT/CLIP/RYA-FX3-1212.MP4", mirrors)
        check("путь переведён в Drive",
              got == "YTEVO S1/P/00_Card/M4ROOT/CLIP/RYA-FX3-1212.MP4", str(got))
        nested = P.map_to_drive("/Volumes/SD-V90-RYA/ZVe1/M4ROOT/CLIP/x.MP4", mirrors)
        check("вложенное зеркало берётся по самому длинному префиксу",
              nested == "YTEVO S1/P/00_Card/ZVe1/M4ROOT/CLIP/x.MP4", str(nested))
        check("чужой путь не переводится",
              P.map_to_drive("/Volumes/Other/x.MP4", mirrors) is None)
        check("похожее имя тома не считается совпадением",
              P.map_to_drive("/Volumes/SD-V90-RYA-2/x.MP4", mirrors) is None)

        # ── контракт: то, ради чего всё ──────────────────────────────────────
        # ⚠️ Мина переносимости: ffprobe 9.0 печатает число кадров ДВАЖДЫ
        # (stream_groups + streams). Прежний разбор давал -1, и гейт заворачивал
        # каждый клип. Ловится только на второй машине — значит, ловим здесь.
        check("кадры: одно число (ffprobe 8)", K.parse_frame_count("84") == 84)
        check("кадры: ДВА числа через пустую строку (ffprobe 9)",
              K.parse_frame_count("84\n\n84") == 84,
              str(K.parse_frame_count("84\n\n84")))
        check("кадры: с запятой на конце", K.parse_frame_count("804,") == 804)
        check("кадры: пусто → -1, а не ноль", K.parse_frame_count("") == -1)
        check("кадры: мусор → -1", K.parse_frame_count("N/A") == -1)
        check("кадры: перевод строки и пробелы", K.parse_frame_count(" 1800 \n") == 1800)

        check("спаннер опознаётся по имени", K.is_spanner("RYA-FX3-1071__S10.MP4"))
        check("обычный клип не спаннер", not K.is_spanner("RYA-FX3-1212.MP4"))
        check("WAV-срез рекордера не видео-спаннер",
              not K.is_spanner("TX01_MIC007_orig__S02.wav"))
        check("битрейт 50p из таблицы — 12M",
              K.bitrate_for(type("S", (), {"fps_float": 50.0})(), override="auto") == "12M")
        check("битрейт 25p из таблицы — 8M",
              K.bitrate_for(type("S", (), {"fps_float": 25.0})(), override="auto") == "8M")
        check("⚠️ override НЕ auto перебивает таблицу (потому и нужен auto)",
              K.bitrate_for(type("S", (), {"fps_float": 50.0})(), override="8M") == "8M")

        # ── обратное давление: резерв на ДВА файла ──────────────────────────
        stg = R.Staging(10, log=lambda m: None)
        check("резерв в потолок выдаётся", stg.reserve("k1", 6))
        check("второй резерв за потолок не выдаётся",
              not stg.reserve("k2", 6, timeout=0.2))
        stg.release("k1")
        check("после release место снова есть", stg.reserve("k2", 6))
        stg2 = R.Staging(10, log=lambda m: None)
        check("клип больше потолка пускается в одиночку", stg2.reserve("big", 50))
        stg3 = R.Staging(10, log=lambda m: None)
        stg3.hold(True)
        check("пауза сторожа не даёт занять место",
              not stg3.reserve("k", 1, timeout=0.2))
        stg3.hold(False)
        check("после снятия паузы место выдаётся", stg3.reserve("k", 1))
        stg4 = R.Staging(10, log=lambda m: None)
        stg4.abort()
        check("abort будит ждущих и отказывает", not stg4.reserve("k", 1))

        # ── единственный экземпляр ───────────────────────────────────────────
        pid_path = os.path.join(tmp, "farm.pid")
        ok1, _ = F.single_instance(pid_path, marker="нет-такого-процесса")
        check("первый запуск разрешён", ok1)
        open(pid_path, "w").write("999999")
        ok2, _ = F.single_instance(pid_path, marker="нет-такого-процесса")
        check("мёртвый pid не блокирует запуск", ok2)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for f in FAIL:
        print(f"  ✗ {f}")
    total = len(PASS) + len(FAIL)
    if FAIL:
        print(f"selftest: ПРОВАЛ, {len(FAIL)} из {total}")
        return 1
    print(f"selftest: ок, {len(PASS)}/{total} проверок")
    return 0


if __name__ == "__main__":
    sys.exit(main())
