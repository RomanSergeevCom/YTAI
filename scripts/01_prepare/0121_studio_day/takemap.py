#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S5 · карта дублей: какой дубль какой урок снимает.

Три независимых источника доказательств, и они НЕ смешиваются в одно число.
Каждый отвечает на свой вопрос, и расхождение между ними — находка, а не шум,
который надо усреднить.

  1. Дословный суфлёр — сильнейший. В `00_Preprod/prompter/*.txt` лежит ровно
     то, что эксперт читал, разбитое заголовками секций. Слова петлички TX01
     против 3-грамм секции: настоящее чтение даёт сотни голосов в одном месте,
     чужая секция — единицы. ⚠️ Покрытие неполное: у блока 2 скрипта нет нигде,
     и его уроки доказать дословно НЕЧЕМ (статус не выше `probable`).
  2. Словесная хлопушка на TX02 — независима и ЕДИНСТВЕННАЯ даёт номер дубля.
     Роман проговаривает номера вслух между дублями: «Так, всё, первый ролик
     готов. Так, это у нас один один. Вторая часть. Видео два».
     ⚠️ Номера звучат СЛОВАМИ, и это номера в схеме эксперта — с цифрой
     съёмочного дня. Храним и услышанное, и канонический id, не подменяя одно
     другим.
  3. Карточки урока (`verbatim[]`, `say[]`, `est_min`) — подтверждение.
     Для блока 2 несёт основную нагрузку, и это честно сказано в `warnings`.

  python3 takemap.py

Выход: {project}/00_Setup/01_Ingest/{CODE}_day1_takemap.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path.home() / "YTAI/scripts/999_extra/wordsync_multicam"))
from common import die, dirs, load_day, load_json, log, save_json  # noqa: E402
from wordsync import flatten_words, norm_token                     # noqa: E402

NGRAM = 3
PAIR_TOL = 6.0            # с: дубли одной пары стартуют вместе
SLATE_BEFORE, SLATE_AFTER = 120.0, 45.0
PROVEN_VOTES = 60         # голосов за секцию, ниже — не «доказано»
RUNNER_MAX = 0.25         # доля голосов у второго места, выше — спор

# ⚠️ Таблица собрана ИНВЕРСИЕЙ ru_numwords.ONES/TEENS: там она только в сторону
# «цифры → слова», а хлопушка звучит словами. Держать вторую таблицу форм нельзя —
# это класс ошибки, который уже оплачен разошедшимися копиями рецепта.
sys.path.insert(0, str(Path.home() / "YTAI/scripts/13_preprod/shared"))
try:
    from ru_numwords import ONES, TEENS
    WORD2NUM = {w: i for g in ONES.values() for i, w in enumerate(g) if w}
    WORD2NUM.update({w: 10 + i for i, w in enumerate(TEENS)})
    WORD2NUM["ноль"] = 0
except Exception:                                            # noqa: BLE001
    WORD2NUM = {"один": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
                "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
                "десять": 10, "одиннадцать": 11, "двенадцать": 12,
                "тринадцать": 13, "ноль": 0}

SEC_HEAD = re.compile(r"^\[(\d{2}[A-ZА-Я]?)-(\d{2})\s*·\s*([^·\]]+?)\s*(?:·[^\]]*)?\]\s*$")
SLATE_CUE = re.compile(r"\b(ролик|видео|дубл|снимаем|пишем|поехали|это у нас|готов)")


def read_prompters(day):
    """Секции суфлёра из всех проектов канала: {код секции: [нормализованные слова]}."""
    out, files = {}, []
    projects = sorted((day["project"].parent).glob("YTUVIE*/00_Setup/00_Preprod/prompter"))
    for d in projects:
        for f in sorted(d.glob("*.txt")):
            files.append(f)
            cur, buf = None, []
            for ln in f.read_text(encoding="utf-8").splitlines():
                m = SEC_HEAD.match(ln.strip())
                if m:
                    if cur:
                        out[cur] = buf
                    cur, buf = f"{m.group(1)}-{m.group(2)}", []
                    out.setdefault(cur + "\u0000title", m.group(3))
                elif cur is not None and ln.strip() and not ln.startswith("["):
                    buf += [t for t in (norm_token(w) for w in ln.split()) if t]
            if cur:
                out[cur] = buf
    return out, files


def ngram_index(words):
    idx = defaultdict(list)
    for i in range(len(words) - NGRAM + 1):
        idx[tuple(words[i:i + NGRAM])].append(i)
    return idx


def match_sections(take_words, sections):
    """Голоса за каждую секцию по 3-граммам. Возвращает отсортированный список."""
    toks = [t for t, _ in take_words]
    have = set()
    for i in range(len(toks) - NGRAM + 1):
        have.add(tuple(toks[i:i + NGRAM]))
    if not have:
        return []
    score = []
    for code, words in sections.items():
        if "\u0000title" in code or len(words) < NGRAM:
            continue
        idx = ngram_index(words)
        hit = sum(1 for g in have if g in idx)
        if hit:
            score.append({"section": code, "votes": hit,
                          "coverage": round(hit / max(1, len(idx)), 3),
                          "title": sections.get(code + "\u0000title", "")})
    return sorted(score, key=lambda x: -x["votes"])


def parse_slate(words):
    """Номера из речи продюсера. Отдаём и услышанное, и разобранные числа."""
    toks = [t for t, _ in words]
    text = " ".join(toks)
    nums, run = [], []
    for t in toks:
        if t in WORD2NUM:
            run.append(WORD2NUM[t])
        elif t.isdigit():
            run.append(int(t))
        else:
            if len(run) >= 2:
                nums.append(run[:])
            run = []
    if len(run) >= 2:
        nums.append(run)
    codes = re.findall(r"\b(\d{2}[a-zа-я]?)\s*(\d{2})\b", text)
    return {"heard": " ".join(toks)[:400],
            "number_runs": nums,
            "section_codes": [f"{a.upper()}-{b}" for a, b in codes],
            "has_cue": bool(SLATE_CUE.search(text))}


def mic_timeline(day, D, res):
    """Слова петличек на ОБЩЕЙ шкале: wall куска (решённый) + смещение слова."""
    chunks = {c["chunk_id"]: c for c in res.get("chunks", [])}
    out = defaultdict(list)
    for p in sorted(D["words"].glob("*.words.json")):
        doc = load_json(p) or {}
        if doc.get("kind") != "mic":
            continue
        stem = p.name[:-len(".words.json")]
        ch = chunks.get(stem) or next((v for k, v in chunks.items() if k.startswith(stem)), None)
        w0 = (ch or {}).get("wall_start")
        if w0 is None:
            continue
        tx = doc.get("tx") or "TX?"
        for t, s in flatten_words(doc):
            out[tx].append((t, w0 + s))
    for v in out.values():
        v.sort(key=lambda x: x[1])
    return out


def slice_words(tl, a, b):
    return [(t, s) for t, s in tl if a <= s < b]


def main():
    ap = argparse.ArgumentParser(description="карта дублей (0121_studio_day)")
    ap.add_argument("--day", default=None)
    a = ap.parse_args()
    day = load_day(a.day)
    D = dirs(day)

    res = load_json(D["work"] / "days/full/Transcription/_wordsync/wordsync_result.json")
    if not res:
        die("нет wordsync_result.json — сначала python3 sync.py")
    idx = load_json(D["work"] / "index.json")
    by_file = {Path(c["path"]).stem: c for c in idx["clips"]}
    cards = (load_json(day["preprod"] / "05_Lessons/cards.json") or {}).get("cards", [])
    card_by_sec = defaultdict(list)
    for c in cards:
        for s in (c.get("sections") or []):
            card_by_sec[s].append(c)

    sections, pfiles = read_prompters(day)
    n_sec = len([k for k in sections if "\u0000title" not in k])
    log(f"секций суфлёра {n_sec} из {len(pfiles)} файлов", day=day)

    tl = mic_timeline(day, D, res)
    log(f"петличная шкала: " + ", ".join(f"{k} {len(v)} слов" for k, v in sorted(tl.items())),
        day=day)

    # ── дубли: клипы, стартующие вместе, — один дубль
    placed = [c for c in res.get("clips", []) if c.get("wall_start") is not None]
    placed.sort(key=lambda c: c["wall_start"])
    takes, cur = [], []
    for c in placed:
        if cur and c["wall_start"] - cur[0]["wall_start"] > PAIR_TOL:
            takes.append(cur)
            cur = []
        cur.append(c)
    if cur:
        takes.append(cur)

    out_takes, warn = [], []
    for n, grp in enumerate(takes, 1):
        w0 = min(c["wall_start"] for c in grp)
        dur = max(c.get("duration") or 0 for c in grp)
        w1 = w0 + dur
        kinds = {by_file.get(c["clip_id"], {}).get("kind") for c in grp}
        junk = all(by_file.get(c["clip_id"], {}).get("junk") for c in grp)

        content = slice_words(tl.get("TX01", []), w0, w1)
        sec_scores = match_sections(content, sections) if content else []
        best = sec_scores[0] if sec_scores else None
        runner = sec_scores[1] if len(sec_scores) > 1 else None

        slate = parse_slate(slice_words(tl.get("TX02", []), w0 - SLATE_BEFORE, w0 + SLATE_AFTER))

        lesson = None
        if best:
            for c in card_by_sec.get(best["section"], []):
                lesson = {"id": c["id"], "title": c["title"], "est_min": c.get("est_min"),
                          "shoot_min": c.get("shoot_min"), "from": "cards.sections"}
                break

        status = "unmapped"
        if best and best["votes"] >= PROVEN_VOTES and (
                not runner or runner["votes"] <= best["votes"] * RUNNER_MAX):
            status = "proven"
        elif best or slate["has_cue"]:
            status = "probable"

        out_takes.append({
            "take": n,
            "clips": {c["cam"]: c["clip_id"] for c in grp},
            "wall_start": round(w0, 3),
            "wall_start_local": datetime.fromtimestamp(w0).isoformat(timespec="seconds"),
            "duration": round(dur, 1),
            "sync_source": sorted({c.get("source", "?") for c in grp}),
            "kind": sorted(k for k in kinds if k),
            "junk": junk,
            "words": {"TX01": len(content),
                      "TX02": len(slice_words(tl.get("TX02", []), w0, w1))},
            "section": ({**best, "runner_up": runner} if best else None),
            "slate": slate,
            "lesson": lesson,
            "status": "junk" if junk else status,
        })

    if not sections:
        warn.append("суфлёрных секций не найдено — дословного доказательства нет вовсе")
    have_blocks = {s.split("-")[0] for s in sections if "\u0000title" not in s}
    if not any(b.startswith("02") for b in have_blocks):
        warn.append("блок 02A: скрипта суфлёра нет нигде на диске — уроки 2.1.1–2.1.5 "
                    "дословно не доказываются, их статус не выше «probable»")
    for tx in ("TX01", "TX02"):
        if not tl.get(tx):
            warn.append(f"{tx}: на общей шкале нет ни одного слова — "
                        f"привязка к урокам по этой дорожке невозможна")

    doc = {"schema": "ytai-takemap-v1",
           "generated": datetime.now().isoformat(timespec="seconds"),
           "code": day["code"], "day": day["day"],
           "sources": {"wordsync": str(D["work"] / "days/full/Transcription/_wordsync"),
                       "cards": str(day["preprod"] / "05_Lessons/cards.json"),
                       "prompters": [str(p) for p in pfiles]},
           "takes": out_takes, "warnings": warn}
    out = day["project"] / "00_Setup/01_Ingest" / f"{day['code']}_day1_takemap.json"
    save_json(out, doc)

    # ── сводка
    st = Counter(t["status"] for t in out_takes)
    print(f"\n  дублей {len(out_takes)} · " +
          " · ".join(f"{k} {v}" for k, v in sorted(st.items())))
    print(f"\n  {'№':>2} {'время':>8} {'мин':>5}  {'секция':<10} {'голосов':>7}  "
          f"{'урок':<7} хлопушка")
    for t in out_takes:
        s = t["section"] or {}
        print(f"  {t['take']:>2} {t['wall_start_local'][11:19]:>8} {t['duration']/60:5.1f}  "
              f"{s.get('section', '—'):<10} {s.get('votes', 0):>7}  "
              f"{(t['lesson'] or {}).get('id', '—'):<7} "
              f"{'✓' if t['slate']['has_cue'] else ' '} "
              f"{t['slate']['heard'][:52]}")
    for w in warn:
        print(f"\n  ⚠ {w}")
    print(f"\n  → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
