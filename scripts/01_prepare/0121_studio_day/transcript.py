#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S8 · читаемый транскрипт дня: двое людей на одной шкале.

Говорящих ровно двое, и кто где — известно ЖЕЛЕЗОМ: TX01 на эксперте, TX02 на
продюсере. Поэтому ни pyannote, ни реестра голосов здесь не нужно. Нужна одна
вещь, которой железо не решает: **проникание**. Микрофон эксперта слышит
продюсера и наоборот, whisper честно расшифровывает обе дорожки целиком, и без
отсечки каждая реплика попала бы в транскрипт дважды — от обоих.

Отсекаем ЗАМЕРОМ, а не моделью: у своего говорящего его собственный микрофон
громче. Сравниваем энергию двух дорожек на одном и том же отрезке настенного
времени и оставляем реплику той, где громче.

⚠️ Сравнивать по рабочим копиям НАПРЯМУЮ нельзя. Они нормированы к −20 дБ
РАЗНЫМ усилением: TX01 получил +12…+20 дБ, TX02 +29…+34 (он тише на 15-20 дБ,
говорит редко, микрофон слышит зал). После нормировки обе дорожки одинаково
громкие, и сравнение показало бы чушь. Поэтому усиление вычитается обратно —
сравнение идёт в исходном масштабе.

Почему не «собрать одно аудио таймлайна и расшифровать целиком», как канон
велит для ката: там источников много и они разнородны, здесь их ровно два и у
каждого известен человек. Склейка ничего не добавила бы, а право на реплику
всё равно решается сравнением энергии.

  python3 transcript.py

Выход: {project}/01_Source/Transcription/
         {CODE}_day1_transcript.txt    ЧЧ:ММ:СС  Имя: текст
         {CODE}_day1_transcript.json   пословно, с дорожкой и уровнями
       + {CODE}_{урок}.txt по урокам, когда карта дублей готова
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import wave
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import die, dirs, load_day, load_json, log, save_json  # noqa: E402

BLEED_DB = 4.0        # порог: своя дорожка должна быть громче на столько
HOP = 0.25            # шаг огибающей, с


def envelope(wav_path, gain_db):
    """Огибающая в ИСХОДНОМ масштабе: применённое усиление вычитается обратно."""
    with wave.open(str(wav_path), "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    import array
    a = array.array("h")
    a.frombytes(raw)
    step = max(1, int(sr * HOP))
    out = []
    for i in range(0, len(a) - step, step):
        s = 0
        chunk = a[i:i + step]
        for v in chunk:
            s += v * v
        rms = math.sqrt(s / len(chunk)) / 32768.0
        db = 20 * math.log10(rms + 1e-9) - (gain_db or 0.0)
        out.append(db)
    return out, HOP


def level_at(env, hop, t0, t1):
    """Средний уровень дорожки на отрезке её ЛОКАЛЬНОГО времени."""
    i0, i1 = int(t0 / hop), max(int(t0 / hop) + 1, int(t1 / hop))
    part = env[max(0, i0):min(len(env), i1)]
    return (sum(part) / len(part)) if part else -120.0


def own_threshold(levels):
    """Граница «хозяин дорожки / чужой через зал» — ИЗ САМИХ ДАННЫХ, двумя средними.

    ⚠️ Распределение уровней на дорожке двугорбое, и это не теория: замер 24.09
    дал у продюсера 362 сегмента около −57 дБ (эксперт через зал) и ~120 около
    −40 дБ (он сам), у эксперта — 607 около −33 дБ (свой голос) и хвост вниз.
    Разница между «своим» и «чужим» — двадцать децибел, её видно невооружённо.

    Порог нельзя зашивать константой: он зависит от того, как сидели и насколько
    подняли усиление. Поэтому ищем его одномерными двумя средними и берём
    середину между кластерами.
    """
    v = sorted(levels)
    if len(v) < 20:
        return None
    lo, hi = v[len(v) // 10], v[-len(v) // 10]
    for _ in range(40):
        a = [x for x in v if abs(x - lo) <= abs(x - hi)]
        b = [x for x in v if abs(x - lo) > abs(x - hi)]
        if not a or not b:
            return None
        lo2, hi2 = sum(a) / len(a), sum(b) / len(b)
        if abs(lo2 - lo) < 0.01 and abs(hi2 - hi) < 0.01:
            break
        lo, hi = lo2, hi2
    return None if hi - lo < 6.0 else (lo + hi) / 2


def hhmmss(sec):
    s = int(sec)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def main():
    ap = argparse.ArgumentParser(description="читаемый транскрипт дня")
    ap.add_argument("--day", default=None)
    a = ap.parse_args()
    day = load_day(a.day)
    D = dirs(day)

    res = load_json(D["work"] / "days/full/Transcription/_wordsync/wordsync_result.json")
    if not res:
        die("нет wordsync_result.json — сначала sync.py")
    au = {r["akey"]: r for r in (load_json(D["work"] / "audio.json") or {}).get("items", [])}
    chunks = {c["chunk_id"]: c for c in res.get("chunks", [])}
    people = day["people"]

    # ── огибающие обеих дорожек, в исходном масштабе
    env = {}
    for akey, rec in au.items():
        if rec.get("kind") != "mic" or not rec.get("wav"):
            continue
        ch = chunks.get(akey) or next((v for k, v in chunks.items() if k.startswith(akey)), None)
        if not ch or ch.get("wall_start") is None:
            continue
        e, hop = envelope(Path(rec["wav"]), rec.get("gain_db"))
        env[akey] = {"env": e, "hop": hop, "w0": ch["wall_start"],
                     "tx": rec.get("tx"), "gain": rec.get("gain_db")}
    if not env:
        die("ни одна петличка не легла на шкалу — транскрипт собирать не из чего")
    log(f"огибающих: {len(env)} " +
        ", ".join(f"{k[:22]} усиление {v['gain']:+.0f}" for k, v in list(env.items())[:3]),
        day=day)

    # ── сегменты обеих дорожек на общей шкале
    segs = []
    for p in sorted(D["words"].glob("*.words.json")):
        doc = load_json(p) or {}
        if doc.get("kind") != "mic" or not doc.get("speech"):
            continue
        akey = p.name[:-len(".words.json")]
        meta = env.get(akey)
        if not meta:
            continue
        for s in doc.get("segments", []):
            segs.append({"akey": akey, "tx": doc.get("tx"),
                         "t0": s["s"], "t1": s["e"],
                         "wall0": meta["w0"] + s["s"], "wall1": meta["w0"] + s["e"],
                         "text": s.get("text", "").strip(),
                         "words": s.get("words", [])})
    segs.sort(key=lambda s: s["wall0"])
    log(f"сегментов обеих дорожек: {len(segs)}", day=day)

    # ── ДОБОР С КАМЕРЫ там, где петлички не было вовсе
    #
    # ⚠️ Без этого транскрипт молча теряет куски дня. Замер 24.09: у эксперта
    # рекордер стоял 51 минуту (дубли 1958 и 1959 целиком, часть 1957) — это
    # 31 минута материала. Петличек там нет, но звук есть на камерах, и он
    # расшифрован: камерная дорожка и так гонится ради якорей синхрона.
    # Качество хуже (зал, не петличка), поэтому источник у каждой реплики
    # проставлен явно — в тексте это видно, а не скрыто.
    cam_w = {c["clip_id"]: c for c in res.get("clips", [])
             if c.get("wall_start") is not None}
    covered = []
    for akey, m in env.items():
        covered.append((m["w0"], m["w0"] + len(m["env"]) * m["hop"]))
    def has_lav(a, b):
        return any(min(b, y) - max(a, x) > (b - a) * 0.5 for x, y in covered)

    cam_pref = {"CAM-A_FX3": 0, "CAM-B_ZVE1": 1, "CAM-C_Pocket": 9}
    added, holes = 0, []
    seen_span = []
    for p2 in sorted(D["words"].glob("*.words.json")):
        doc = load_json(p2) or {}
        if doc.get("kind") != "cam" or not doc.get("speech"):
            continue
        cid = p2.name[:-len(".words.json")]
        c = cam_w.get(cid)
        if not c:
            continue
        w0c = c["wall_start"]
        if has_lav(w0c, w0c + (c.get("duration") or 0)):
            continue                      # петличка есть — камеру не берём
        key = round(w0c, 1)
        if any(abs(key - k) < 2.0 and pr <= cam_pref.get(c["cam"], 5)
               for k, pr in seen_span):
            continue                      # вторая камера того же дубля
        seen_span.append((key, cam_pref.get(c["cam"], 5)))
        holes.append((cid, c["cam"], round((c.get("duration") or 0) / 60, 1)))
        for sg in doc.get("segments", []):
            segs.append({"akey": cid, "tx": None, "cam": c["cam"],
                         "t0": sg["s"], "t1": sg["e"],
                         "wall0": w0c + sg["s"], "wall1": w0c + sg["e"],
                         "text": sg.get("text", "").strip(),
                         "words": sg.get("words", []), "from_cam": True})
            added += 1
    segs.sort(key=lambda s: s["wall0"])
    if holes:
        log(f"добор с камеры: {len(holes)} дублей без петлички, "
            f"{sum(h[2] for h in holes):.1f} мин, сегментов {added}", day=day)
        for cid, cam, mn in holes:
            log(f"    {cid:<22} {cam:<14} {mn:>5.1f} мин", day=day)

    # ── пороги «свой / чужой» по каждой дорожке, до отсечки
    lv = {}
    for sg in segs:
        if sg.get("from_cam"):
            continue
        mine = env[sg["akey"]]
        sg["db_own"] = round(level_at(mine["env"], mine["hop"], sg["t0"], sg["t1"]), 1)
        lv.setdefault(sg["tx"], []).append(sg["db_own"])
    thr = {tx: own_threshold(v) for tx, v in lv.items()}
    other_tx = {t: next((x for x in lv if x != t), None) for t in lv}
    for tx, t in thr.items():
        log(f"порог «свой/чужой» {tx}: "
            + (f"{t:.1f} дБ" if t is not None else "не разделилось, уровнем не судим"),
            day=day)

    # ── отсечка проникания: реплика остаётся той дорожке, где она громче
    kept, dropped, moved = [], 0, 0
    for s in segs:
        if s.get("from_cam"):
            s["db_own"] = s["db_other"] = None
            s["bleed"] = False
            kept.append(s)
            continue
        mine = env[s["akey"]]
        own = level_at(mine["env"], mine["hop"], s["t0"], s["t1"])
        other = None
        for akey, m in env.items():
            if m["tx"] == s["tx"]:
                continue
            lo, hi = s["wall0"] - m["w0"], s["wall1"] - m["w0"]
            if hi < 0 or lo > len(m["env"]) * m["hop"]:
                continue
            v = level_at(m["env"], m["hop"], max(0, lo), hi)
            other = v if other is None else max(other, v)
        s["db_own"], s["db_other"] = round(own, 1), (round(other, 1) if other is not None else None)
        if other is not None:
            # обе дорожки живы — сравнение сильнее любого порога
            if other > own + BLEED_DB:
                dropped += 1
                s["bleed"] = True
                continue
        else:
            # ⚠️ Жива ОДНА дорожка. Сравнивать не с чем, а приписать реплику
            # хозяину дорожки нельзя: у эксперта рекордер стоял 51 минуту, и
            # все 25 минут его речи пришли бы продюсеру, потому что слышал их
            # ЕГО микрофон. Людей двое, поэтому тихая реплика на единственной
            # живой дорожке — это ДРУГОЙ человек, и говорим об этом явно.
            t = thr.get(s["tx"])
            if t is not None and own < t:
                s["speaker_tx"] = other_tx.get(s["tx"])
                s["by_level"] = True
                moved += 1
        s["bleed"] = False
        kept.append(s)
    log(f"проникание отсечено: {dropped} сегментов из {len(segs)} "
        f"(порог {BLEED_DB:.0f} дБ) · переприписано по уровню: {moved}", day=day)

    # ── читаемый текст
    t0 = min(s["wall0"] for s in kept)
    lines, cur = [], None
    for s in kept:
        tx_eff = s.get("speaker_tx") or s["tx"]
        who = (people.get(tx_eff, {}).get("name", tx_eff or "?")
               if not s.get("from_cam")
               else f"с камеры {s.get('cam', '')}".strip())
        rel = s["wall0"] - t0
        if cur and cur["who"] == who and rel - cur["end"] < 12:
            cur["text"] += " " + s["text"]
            cur["end"] = s["wall1"] - t0
        else:
            if cur:
                lines.append(cur)
            cur = {"who": who, "t": rel, "end": s["wall1"] - t0, "text": s["text"]}
    if cur:
        lines.append(cur)

    outdir = day["project"] / "01_Source/Transcription"
    outdir.mkdir(parents=True, exist_ok=True)
    head = (f"{day['code']} · съёмочный день {day['day']}\n"
            f"Говорящих двое, дорожка = человек: "
            + " · ".join(f"{k} — {v['name']}" for k, v in people.items()) + "\n"
            f"Отсчёт от первой реплики ({datetime.fromtimestamp(t0):%H:%M:%S} по стене). "
            f"Проникание отсечено сравнением энергии дорожек.\n"
            + "─" * 78 + "\n\n")
    txt = head + "\n".join(f"{hhmmss(l['t'])}  {l['who']}: {l['text']}" for l in lines)
    ftxt = outdir / f"{day['code']}_day1_transcript.txt"
    ftxt.write_text(txt, encoding="utf-8")

    doc = {"schema": "ytai-day-transcript-v2", "code": day["code"], "day": day["day"],
           "people": people, "t0_wall": t0,
           "bleed_threshold_db": BLEED_DB, "segments_dropped_as_bleed": dropped,
           # ⚠️ Основания решений хранятся ВМЕСТЕ с результатом: порог, найденный
           # в данных, и число реплик, переписанных с хозяина дорожки на другого
           # человека. Без этого транскрипт нечем проверить — он выглядит просто
           # как чей-то уверенный список реплик.
           "own_threshold_db": thr, "reattributed_by_level": moved,
           "from_camera_takes": holes,
           "n_segments": len(kept), "n_words": sum(len(s["words"]) for s in kept),
           "segments": [{**{k: s.get(k) for k in
                            ("tx", "wall0", "wall1", "text", "db_own", "db_other", "words")},
                         "speaker_tx": s.get("speaker_tx") or s.get("tx"),
                         "by_level": bool(s.get("by_level")),
                         "source": ("камера " + s["cam"]) if s.get("from_cam") else "петличка"}
                        for s in kept]}
    fjson = save_json(outdir / f"{day['code']}_day1_transcript.json", doc)

    # ── по урокам, если карта дублей уже есть
    tm = load_json(day["project"] / "00_Setup/01_Ingest" / f"{day['code']}_day1_takemap.json")
    made = 0
    for t in (tm or {}).get("takes", []):
        les = (t.get("lesson") or {}).get("id")
        if not les:
            continue
        a0, a1 = t["wall_start"], t["wall_start"] + t["duration"]
        part = [l for l in lines if a0 - t0 <= l["t"] < a1 - t0]
        if not part:
            continue
        f = outdir / f"{day['code']}_{les}_dubl{t['take']}.txt"
        f.write_text(f"{les} · {(t.get('lesson') or {}).get('title', '')} · дубль {t['take']}\n"
                     f"{datetime.fromtimestamp(a0):%H:%M:%S}, {t['duration']/60:.1f} мин\n"
                     + "─" * 78 + "\n\n"
                     + "\n".join(f"{hhmmss(l['t'] - (a0 - t0))}  {l['who']}: {l['text']}"
                                 for l in part), encoding="utf-8")
        made += 1

    print(f"\n  реплик {len(lines)} · слов {doc['n_words']} · "
          f"проникание отсечено {dropped}")
    by = {}
    for l in lines:
        by[l["who"]] = by.get(l["who"], 0) + len(l["text"].split())
    for who, n in sorted(by.items(), key=lambda x: -x[1]):
        print(f"    {who:<22} {n:>6} слов")
    print(f"\n  → {ftxt}")
    print(f"  → {fjson}")
    if made:
        print(f"  → по урокам: {made} файлов рядом")
    return 0


if __name__ == "__main__":
    sys.exit(main())
