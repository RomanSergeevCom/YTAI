#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S5 · карта дублей: какой дубль какой урок снимает.

⚠️ ГЛАВНОЕ ПРО МЕТОД. Эксперт **рассказывает сам, без суфлёра** — опора у него
карточка урока, а не начитка (решение Романа 22.09: «ему нужна не начитка,
а опора, чтобы ничего не забывать»). Значит дословного совпадения ждать
НЕЛЬЗЯ: он пересказывает своими словами, и поиск точных 3-грамм по тексту
суфлёра дал бы почти ноль на верном уроке — а выглядело бы это как «урок не
опознан», то есть как ошибка привязки, а не как ошибка метода.

Поэтому сверяем с тем, что у него ПЕРЕД ГЛАЗАМИ, и по тому, что нельзя
перевести своими словами:

  1. Карточка урока — `say[]`, `steps[].body[]`, `remember[]`, `groups[]`,
     `demo.what`, заголовок. Совпадение считается по РЕДКИМ словам: вес слова
     тем выше, чем в меньшем числе из 63 карточек оно встречается. «Песочница»,
     «конституция», «англицизм» разделяют уроки; «нужно», «сделать», «видео» —
     нет. Порог не зашит: лучший урок обязан оторваться от второго, а не
     набрать заданное число.
  2. `verbatim[]` — то, что переврать нельзя: цифры, лимиты, названия моделей,
     структура документа. Сильнейший сигнал, потому что переживает пересказ.
     Цифры в карточках приводятся к словам (`ru_numwords`), потому что в речи
     они звучат словами: «тысяча двести знаков», а не «1 200».
  3. Словесная хлопушка на TX02 — независима и ЕДИНСТВЕННАЯ даёт номер дубля.
     ⚠️ Номера звучат словами и в схеме эксперта, с цифрой съёмочного дня.
     Храним и услышанное, и канонический id, не подменяя одно другим.

Суфлёрные тексты, где они есть (блоки 1 и 3), берём ДОПОЛНИТЕЛЬНЫМ отпечатком
темы — но не как доказательство начитки. У блока 2 их нет и быть не должно.

  python3 takemap.py

Выход: {project}/00_Setup/01_Ingest/{CODE}_day1_takemap.json
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path.home() / "YTAI/scripts/999_extra/wordsync_multicam"))
sys.path.insert(0, str(Path.home() / "YTAI/scripts/13_preprod/shared"))
from common import die, dirs, load_day, load_json, log, save_json  # noqa: E402
from wordsync import flatten_words, norm_token                     # noqa: E402

try:
    from ru_numwords import ONES, TEENS, replace_numbers
except Exception:                                                  # noqa: BLE001
    ONES, TEENS, replace_numbers = {}, [], (lambda s: s)

# ⚠️ Таблица слов-чисел собрана ИНВЕРСИЕЙ ru_numwords: там она только в сторону
# «цифры → слова». Вторую копию форм не заводим — это тот класс ошибки, который
# уже оплачен разошедшимися копиями рецепта в другом слое.
WORD2NUM = {w: i for g in (ONES or {}).values() for i, w in enumerate(g) if w}
WORD2NUM.update({w: 10 + i for i, w in enumerate(TEENS or [])})
WORD2NUM.setdefault("ноль", 0)
if not WORD2NUM:
    WORD2NUM = {"один": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
                "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
                "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13}

PAIR_TOL = 6.0                 # с: клипы одной пары стартуют вместе
SLATE_BEFORE, SLATE_AFTER = 120.0, 45.0
MIN_TAKE_WORDS = 40            # короче — говорить не о чем, урок не опознаём
# (порог отрыва убран: измерено, что отрыв лучшего от второго держится в
# пределах ×1,02-1,16 — 63 урока одного курса делят словарь. Надёжность даёт
# не порог, а выравнивание последовательности: порядок съёмки = порядок курса.)
SEC_HEAD = re.compile(r"^\[(\d{2}[A-ZА-Я]?)-(\d{2})\s*·\s*([^·\]]+?)\s*(?:·[^\]]*)?\]\s*$")
SLATE_CUE = re.compile(r"(ролик|видео|дубл|снимаем|пишем|поехали|это у нас|готов|стоп)")
STOP = set("""и в во не на что он а то все она так его но да ты к у же вы за бы по
только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если
уже или ни быть был него до вас нибудь опять уж вам сказал ведь там потом себя
ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без
будто человек чего раз тоже себе под жизнь будет ж тогда кто этот говорил того
потому этого какой совсем ним здесь этом один почти мой тем чтобы нее кажется
сейчас были куда зачем сказать всех никогда сегодня можно при наконец два об
другой хоть после над больше тот через эти нас про всего них какая много разве
сказала эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя
такой им более всегда конечно всю между это как мы вы они наш ваш свой очень
просто нужно сделать делать значит вообще именно таки туда сюда"""
           .split())


def bag(text):
    """Мешок нормализованных слов. Цифры приводим к словам: в речи они звучат
    словами, и «1 200 знаков» карточки должно встретиться с «тысяча двести»."""
    try:
        text = replace_numbers(text)
    except Exception:                                              # noqa: BLE001
        pass
    out = []
    for w in re.split(r"\s+", text or ""):
        t = norm_token(w)
        if len(t) >= 4 and t not in STOP and not t.isdigit():
            out.append(t)
    return out


def card_text(c):
    """Всё, что у эксперта было перед глазами, одной простынёй."""
    parts = [c.get("title") or "", (c.get("demo") or {}).get("what") or ""]
    parts += list(c.get("say") or [])
    parts += list(c.get("remember") or [])
    parts += [g.get("t", "") for g in (c.get("groups") or [])]
    for s in (c.get("steps") or []):
        parts.append(s.get("t") or "")
        parts += list(s.get("body") or [])
        parts.append(s.get("what") or "")
    hw = c.get("homework")
    parts += (hw if isinstance(hw, list) else [hw or ""])
    return " ".join(p for p in parts if p)


def build_idf(cards):
    """Вес слова тем выше, чем в меньшем числе карточек оно встречается."""
    df = Counter()
    for c in cards:
        df.update(set(bag(card_text(c))))
    n = max(1, len(cards))
    return {w: math.log(n / (1 + d)) + 1.0 for w, d in df.items()}


def _vec(tokens, idf):
    """tf-idf вектор мешка слов."""
    tf = Counter(tokens)
    if not tf:
        return {}, 0.0
    mx = max(tf.values())
    v = {w: (0.5 + 0.5 * n / mx) * idf.get(w, 1.0) for w, n in tf.items()}
    norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return v, norm


def score_cards(said, cards, idf, card_vecs):
    """Близость дубля к уроку — КОСИНУС между tf-idf векторами.

    ⚠️ Сначала здесь была просто сумма весов общих слов, и она мерила не
    похожесть, а длину карточки: подробные уроки («Темы из споров в Threads»,
    «Модели завода и цены») выигрывали у верного на любом материале, а отрыв
    от второго места держался в пределах ×1,04-1,16 — то есть решения не было
    вовсе. Косинус делит на длину обоих векторов, и сравнение становится
    сравнением, а не подсчётом объёма.
    """
    sv, sn = _vec(said, idf)
    if not sv:
        return []
    out = []
    for c in cards:
        cv, cn = card_vecs[c["id"]]
        if not cv:
            continue
        common = sv.keys() & cv.keys()
        if not common:
            continue
        dot = sum(sv[w] * cv[w] for w in common)
        cos = dot / (sn * cn)
        top = sorted(common, key=lambda w: -(sv[w] * cv[w]))[:12]
        out.append({"id": c["id"], "title": c["title"],
                    "score": round(cos * 1000, 1), "cos": round(cos, 4),
                    "shared": len(common), "markers": top})
    return sorted(out, key=lambda x: -x["score"])


def verbatim_hits(said_seq, c):
    """Сколько «непереводимых» кусков карточки прозвучало.

    Считаем по словам, а не по строке: пересказ меняет порядок и служебные
    слова, но цифры, лимиты и названия остаются. Достаточно, чтобы БОЛЬШИНСТВО
    редких слов куска встретилось в дубле.
    """
    said = set(said_seq)
    hits = []
    for v in (c.get("verbatim") or []):
        toks = [t for t in bag(v)]
        if not toks:
            continue
        got = sum(1 for t in toks if t in said)
        if got >= max(2, int(len(toks) * 0.6)):
            hits.append({"text": v[:120], "matched": got, "of": len(toks)})
    return hits


def align_monotonic(scores, n_takes, n_lessons):
    """Выравнивание последовательности: дубли идут в порядке курса.

    ⚠️ Это главный источник надёжности, и он НЕ статистический, а
    производственный: «порядок съёмки — порядок курса, тема за темой»
    (канон смены, `shoot_plan.py`). Поодиночке дубль опознаётся слабо —
    63 урока одного курса делят словарь, и отрыв лучшего от второго держится
    в пределах ×1,02-1,16. Но как ПОСЛЕДОВАТЕЛЬНОСТЬ дубли опознаются
    уверенно: номер урока может стоять на месте (дубли одного урока подряд)
    или расти, но не убывать.

    Динамика: dp[t][l] = score[t][l] + max(dp[t-1][l'] для l' ≤ l).
    Возвращает список индексов уроков по дублям.
    """
    if not n_takes or not n_lessons:
        return []
    NEG = float("-inf")
    dp = [[NEG] * n_lessons for _ in range(n_takes)]
    bk = [[-1] * n_lessons for _ in range(n_takes)]
    for l in range(n_lessons):
        dp[0][l] = scores[0][l]
    for t in range(1, n_takes):
        best, arg = NEG, -1
        for l in range(n_lessons):
            if dp[t - 1][l] > best:
                best, arg = dp[t - 1][l], l
            dp[t][l] = scores[t][l] + best
            bk[t][l] = arg
    l = max(range(n_lessons), key=lambda i: dp[n_takes - 1][i])
    path = [l]
    for t in range(n_takes - 1, 0, -1):
        l = bk[t][l]
        path.append(l)
    return path[::-1]


def read_prompters(day):
    """Суфлёрные секции — ДОПОЛНИТЕЛЬНЫЙ отпечаток темы, не доказательство."""
    out, files = {}, []
    for d in sorted((day["project"].parent).glob("YTUVIE*/00_Setup/00_Preprod/prompter")):
        for f in sorted(d.glob("*.txt")):
            files.append(f)
            cur, buf = None, []
            for ln in f.read_text(encoding="utf-8").splitlines():
                m = SEC_HEAD.match(ln.strip())
                if m:
                    if cur:
                        out[cur] = buf
                    cur, buf = f"{m.group(1)}-{m.group(2)}", []
                elif cur is not None and ln.strip() and not ln.startswith("["):
                    buf += bag(ln)
            if cur:
                out[cur] = buf
    return out, files


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
    return {"heard": text[-360:],
            "number_runs": nums,
            "section_codes": [f"{a.upper()}-{b}" for a, b in
                              re.findall(r"\b(\d{2}[a-zа-я]?)\s*(\d{2})\b", text)],
            "has_cue": bool(SLATE_CUE.search(text))}


def mic_timeline(D, res, day):
    """Слова на общей шкале — ИЗ ТРАНСКРИПТА, а не из сырых дорожек.

    ⚠️ Первая редакция читала сырую дорожку TX01 и получала НОЛЬ слов на дублях
    1958-1961: у эксперта там стоял рекордер, и его речь пришла через микрофон
    продюсера. Транскрипт это уже разобрал — он приписывает реплику по УРОВНЮ,
    а не по дорожке, и добирает с камеры там, где петлички не было вовсе.
    Читать сырьё после этого значит выбрасывать 25 минут содержания и опознавать
    четыре урока одним лишь порядком, без единого слова в доказательство.

    Запасной путь на сырьё остаётся: транскрипт может быть ещё не собран.
    """
    tr = load_json(day["project"] / "01_Source/Transcription"
                   / f"{day['code']}_day1_transcript.json")
    out = defaultdict(list)
    if tr and tr.get("segments"):
        for sg in tr["segments"]:
            tx = sg.get("speaker_tx") or sg.get("tx") or "TX?"
            w0 = sg["wall0"]
            for w in (sg.get("words") or []):
                t = norm_token(w.get("w", ""))
                if t:
                    out[tx].append((t, w0 + (float(w.get("s", 0)) - (sg.get("words") or [{}])[0].get("s", 0))))
        for v in out.values():
            v.sort(key=lambda x: x[1])
        return out

    chunks = {c["chunk_id"]: c for c in res.get("chunks", [])}
    for p in sorted(D["words"].glob("*.words.json")):
        doc = load_json(p) or {}
        if doc.get("kind") != "mic":
            continue
        stem = p.name[:-len(".words.json")]
        ch = chunks.get(stem) or next((v for k, v in chunks.items() if k.startswith(stem)), None)
        w0 = (ch or {}).get("wall_start")
        if w0 is None:
            continue
        for t, s in flatten_words(doc):
            out[doc.get("tx") or "TX?"].append((t, w0 + s))
    for v in out.values():
        v.sort(key=lambda x: x[1])
    return out


def slice_words(tl, a, b):
    return [(t, s) for t, s in tl if a <= s < b]


def screen_windows(D, out_takes):
    """S5b · уроки из окон записи экрана — собственная нумерация эксперта.

    Эксперт пишет экран САМ, и имя файла («1.3.4») — прямая привязка к уроку,
    сильнее любого сопоставления по словам: `day.json` так её и называет.
    Дубль, у которого умерла петличка, речевого ребра не даёт НИКОГДА — и
    словами его не опознать в принципе. Окно записи экрана опознаёт.

    ⚠️ Но мак эксперта и рекордер живут в РАЗНЫХ часовых поясах: на дне 23.09
    расхождение ровно −60 мин. Пересекать окна со шкалой синхрона напрямую
    нельзя — это была бы та самая вера часам, из-за которой и заведён
    word-sync. Поэтому смещение сперва ЗАМЕРЯЕТСЯ по дублям, доказанным
    дословными совпадениями, и применяется, только если сошлось на ВСЕХ
    якорях. Не сошлось — не применяем вовсе и говорим об этом.

    Ошибки часовых поясов квантованы часом, поэтому и ищем по сетке часов:
    так смещение не подгоняется под шум.

    Доказанное дословно НЕ переписываем — там окно лишь подтверждает или
    спорит, и спор виден в отчёте.
    """
    note = []
    sc = load_json(D["work"] / "screencasts.json")
    items = (sc or {}).get("items") or []
    if not items:
        return ["Окон записи экрана нет (screencasts.json пуст или не собран) — "
                "привязка по нумерации эксперта не делалась"]

    wins, titles = [], {}
    for s in items:
        p = Path(s.get("path") or "")
        if not (s.get("lesson") and s.get("dur") and p.exists()):
            continue
        end = p.stat().st_mtime           # mtime = КОНЕЦ записи экрана
        wins.append((end - s["dur"], end, s["lesson"]))
        titles.setdefault(s["lesson"], s.get("title"))
    if not wins:
        return ["Файлы скринкастов недоступны — окна не построены"]
    wins.sort()

    def hit(t, off):
        """Урок, чьё окно дубль накрывает дольше всего."""
        a, b = t["wall_start"] + off, t["wall_start"] + off + t["duration"]
        best = None
        for wa, wb, lid in wins:
            ov = min(b, wb) - max(a, wa)
            if ov > 0 and (best is None or ov > best[0]):
                best = (ov, lid, wa - (t["wall_start"] + off))
        return best

    anchors = [t for t in out_takes
               if (t.get("lesson") or {}).get("verbatim_hits")
               and any(w[2] == t["lesson"]["id"] for w in wins)]
    if len(anchors) < 2:
        return [f"Якорей с дословными совпадениями {len(anchors)} — меньше двух, "
                f"смещение часов замерить не на чем; окна не применялись"]

    best = None
    for h in range(-6, 7):
        off = h * 3600.0
        ok = sum(1 for t in anchors
                 if (r := hit(t, off)) and r[1] == t["lesson"]["id"])
        if best is None or ok > best[0]:
            best = (ok, off)
    ok, off = best
    if ok < len(anchors):
        return [f"Смещение часов не сошлось: лучшая сетка ставит на место "
                f"{ok} якорей из {len(anchors)}. Окна НЕ применялись — "
                f"раскладывать по неподтверждённым часам нельзя"]

    note.append(f"Часы мака эксперта против шкалы синхрона: {off/3600:+.0f} ч "
                f"(замерено по {len(anchors)} дублям с дословными совпадениями, "
                f"сошлось на всех). Разные часовые пояса, не дрейф.")

    agree = argue = new = 0
    for t in out_takes:
        if t["junk"] or "lesson" not in t["kind"]:
            continue
        r = hit(t, off)
        if not r:
            continue
        _, lid, lead = r
        L = t.get("lesson")
        if L and L.get("verbatim_hits"):
            L["screen_window"] = {"id": lid, "agrees": lid == L["id"],
                                  "lead_sec": round(lead, 1)}
            if lid == L["id"]:
                agree += 1
            else:
                argue += 1
                note.append(f"⚠ дубль {t['take']}: дословно опознан как {L['id']}, "
                            f"а окно записи экрана говорит {lid} — разбирают глазами")
            continue
        was = L["id"] if L else None
        t["lesson"] = {
            "id": lid,
            "title": (L or {}).get("title") if was == lid else titles.get(lid),
            "est_min": (L or {}).get("est_min"), "shoot_min": (L or {}).get("shoot_min"),
            "from": "окно записи экрана (нумерация эксперта) + замеренное смещение часов",
            "score": (L or {}).get("score", 0.0),
            "agrees_with_alone": (t.get("alone") or {}).get("id") == lid,
            "alone_said": (t.get("alone") or {}).get("id"),
            "verbatim_hits": [],
            "screen_window": {"id": lid, "agrees": None, "lead_sec": round(lead, 1)},
            "was_before": was,
        }
        t["status"] = "proven" if t["lesson"]["agrees_with_alone"] else "probable"
        new += 1

    note.append(f"Окна записи экрана: подтвердили {agree} дублей, поспорили с {argue}, "
                f"опознали {new} там, где слов не хватило.")
    return note


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
    by_stem = {Path(c["path"]).stem: c for c in idx["clips"]}
    cards = (load_json(day["preprod"] / "05_Lessons/cards.json") or {}).get("cards", [])
    if not cards:
        die("нет cards.json — сверять дубли не с чем")
    shot_today = [c for c in cards if str(c.get("shoot_date")) == day["day"]]
    idf = build_idf(cards)
    sections, pfiles = read_prompters(day)

    log(f"карточек {len(cards)} (на этот день {len(shot_today)}) · "
        f"словарь редких слов {len(idf)} · суфлёрных секций {len(sections)}", day=day)

    tl = mic_timeline(D, res, day)
    log("петличная шкала: " + (", ".join(f"{k} {len(v)} слов" for k, v in sorted(tl.items()))
                               or "ПУСТО"), day=day)

    placed = sorted([c for c in res.get("clips", []) if c.get("wall_start") is not None],
                    key=lambda c: c["wall_start"])
    takes, cur = [], []
    for c in placed:
        if cur and c["wall_start"] - cur[0]["wall_start"] > PAIR_TOL:
            takes.append(cur)
            cur = []
        cur.append(c)
    if cur:
        takes.append(cur)

    # ── карточки в векторы один раз: 63 × словарь, считать на каждом дубле незачем
    card_vecs = {c["id"]: _vec(bag(card_text(c)), idf) for c in cards}
    # порядок курса = порядок съёмки, поэтому план дня держим отсортированным
    planned = sorted(shot_today, key=lambda c: [int(x) for x in re.findall(r"\d+", c["id"])])

    out_takes, warn = [], []
    rows, row_ix = [], []          # для выравнивания последовательности
    for n, grp in enumerate(takes, 1):
        w0 = min(c["wall_start"] for c in grp)
        dur = max(c.get("duration") or 0 for c in grp)
        w1 = w0 + dur
        junk = all(by_stem.get(c["clip_id"], {}).get("junk") for c in grp)
        kinds = sorted({by_stem.get(c["clip_id"], {}).get("kind") for c in grp} - {None})

        said = [t for t, _ in slice_words(tl.get("TX01", []), w0, w1)]
        said_bag = [t for t in said if len(t) >= 4 and t not in STOP]
        slate = parse_slate(slice_words(tl.get("TX02", []), w0 - SLATE_BEFORE, w0 + SLATE_AFTER))

        ranked = (score_cards(said_bag, cards, idf, card_vecs)
                  if len(said_bag) >= MIN_TAKE_WORDS else [])
        best = ranked[0] if ranked else None
        runner = ranked[1] if len(ranked) > 1 else None
        lead = (best["score"] / runner["score"]) if (best and runner and runner["score"]) else None

        vhits = []
        if best:
            card = next((c for c in cards if c["id"] == best["id"]), None)
            if card:
                vhits = verbatim_hits(said_bag, card)

        # строка для выравнивания: счёт этого дубля против КАЖДОГО урока дня
        if not junk and "lesson" in kinds + ["lesson"] and said_bag and planned:
            by_id = {r["id"]: r["score"] for r in ranked}
            rows.append([by_id.get(c["id"], 0.0) for c in planned])
            row_ix.append(n - 1)

        out_takes.append({
            "take": n,
            "clips": {c["cam"]: c["clip_id"] for c in grp},
            "wall_start": round(w0, 3),
            "wall_start_local": datetime.fromtimestamp(w0).isoformat(timespec="seconds"),
            "duration": round(dur, 1),
            "sync_source": sorted({c.get("source", "?") for c in grp}),
            "kind": kinds, "junk": junk,
            "words": {"TX01": len(said),
                      "TX02": len(slice_words(tl.get("TX02", []), w0, w1))},
            # что говорит ОДИН этот дубль, сам по себе
            "alone": ({"id": best["id"], "title": best["title"],
                       "score": best["score"], "shared_terms": best["shared"],
                       "markers": best["markers"],
                       "lead_over_runner": round(lead, 2) if lead else None,
                       "runner_up": ({"id": runner["id"], "score": runner["score"]}
                                     if runner else None),
                       "verbatim_hits": vhits} if best else None),
            "lesson": None,          # заполняется выравниванием ниже
            "slate": slate,
            "status": "junk" if junk else ("unmapped" if not said_bag else "pending"),
        })

    # ── выравнивание последовательности: главный источник надёжности
    if rows and planned:
        path = align_monotonic(rows, len(rows), len(planned))
        for i, li in enumerate(path):
            t = out_takes[row_ix[i]]
            c = planned[li]
            alone = t.get("alone") or {}
            agree = alone.get("id") == c["id"]
            t["lesson"] = {
                "id": c["id"], "title": c["title"],
                "est_min": c.get("est_min"), "shoot_min": c.get("shoot_min"),
                "from": "выравнивание последовательности по порядку курса",
                "score": rows[i][li],
                "agrees_with_alone": agree,
                "alone_said": alone.get("id"),
                "verbatim_hits": verbatim_hits(
                    [tt for tt, _ in slice_words(tl.get("TX01", []), t["wall_start"],
                                                 t["wall_start"] + t["duration"])], c),
            }
            # «доказано» = два независимых источника сошлись, или подтвердил verbatim
            t["status"] = ("proven" if (agree or t["lesson"]["verbatim_hits"])
                           else "probable")
    elif not planned:
        warn.append("В карточках нет уроков с этой датой съёмки — выравнивание "
                    "последовательности невозможно, остаётся только поодиночный счёт")

    # ── окна записи экрана: последнее слово там, где слов не было
    warn.extend(screen_windows(D, out_takes))

    # ── честные оговорки, а не список «дефектов»
    warn.append("Эксперт рассказывает сам, без суфлёра: совпадение считается по редким "
                "словам карточки и по «непереводимым» кускам verbatim[], а не дословно. "
                "Дословного чтения на этом дне не было ни в одном блоке.")
    if sections:
        warn.append(f"Суфлёрные тексты есть у {len({s.split('-')[0] for s in sections})} блоков "
                    f"и использованы только как дополнительный отпечаток темы.")
    for tx in ("TX01", "TX02"):
        if not tl.get(tx):
            warn.append(f"{tx}: на общей шкале нет ни одного слова — "
                        f"привязка по этой дорожке невозможна")
    nomap = [t["take"] for t in out_takes if t["status"] == "unmapped"]
    if nomap:
        warn.append(f"Не опознаны дубли {nomap} — они едут в 09_Nerazobrannoe и видны глазами")

    doc = {"schema": "ytai-takemap-v2",
           "generated": datetime.now().isoformat(timespec="seconds"),
           "code": day["code"], "day": day["day"],
           "method": "редкие слова карточки + verbatim[] + словесная хлопушка; "
                     "эксперт рассказывает сам, дословного совпадения не ждём",
           "sources": {"wordsync": str(D["work"] / "days/full/Transcription/_wordsync"),
                       "cards": str(day["preprod"] / "05_Lessons/cards.json"),
                       "prompters_secondary": [str(p) for p in pfiles]},
           "takes": out_takes, "warnings": warn}
    out = day["project"] / "00_Setup/01_Ingest" / f"{day['code']}_day1_takemap.json"
    save_json(out, doc)

    st = Counter(t["status"] for t in out_takes)
    print(f"\n  дублей {len(out_takes)} · " + " · ".join(f"{k} {v}" for k, v in sorted(st.items())))
    agree = sum(1 for t in out_takes if (t.get("lesson") or {}).get("agrees_with_alone"))
    mapped = sum(1 for t in out_takes if t.get("lesson"))
    if mapped:
        print(f"  поодиночный счёт согласился с выравниванием: {agree} из {mapped}")
    print(f"\n  {'№':>2} {'время':>8} {'мин':>5} {'слов':>5}  {'урок':<8} {'один':<8} "
          f"{'vb':>3}  маркеры")
    for t in out_takes:
        l, al = t.get("lesson") or {}, t.get("alone") or {}
        mark = "=" if l.get("agrees_with_alone") else ("·" if l else " ")
        print(f"  {t['take']:>2} {t['wall_start_local'][11:19]:>8} {t['duration']/60:5.1f} "
              f"{t['words']['TX01']:>5}  {l.get('id', '—'):<8} {mark}{al.get('id', '—'):<7} "
              f"{len(l.get('verbatim_hits') or []):>3}  "
              f"{', '.join((al.get('markers') or [])[:5])}")
        if t["slate"]["has_cue"]:
            print(f"     хлопушка: …{t['slate']['heard'][-90:]}")
    for w in warn:
        print(f"\n  · {w}")
    print(f"\n  → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
