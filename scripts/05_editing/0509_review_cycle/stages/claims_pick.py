#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Крупные фразы фильма → `card.claims` (блок N: плашка-утверждение во весь кадр).

Зачем. Роман 22.09.2026: «сделай дизайн глав и фраз». Заставки глав и плашки подглав берутся
из структуры, а «фраза» — это отдельный приём: одна мысль во весь кадр, две строки, первая
рубином, вторая костью. Рисовать его умеет блок N `make_infographics_v6`, но брать фразы
ему неоткуда — `card.claims` заполняется вручную. Эта стадия предлагает их из самого ката.

Откуда кандидаты:
  • якоря глав — из ТЗ этого круга («Якорь: «…»» в списке глав пункта структуры): реплика,
    ради которой глава существует;
  • тезисы и утверждения актов — `work/{cut}/acts_compact.json` (`theses`, `claims`).

Правила отбора (жёсткие, нарушивший кандидат выбывает без обсуждения):
  1. фраза звучит В КАТЕ ДОСЛОВНО — ищем подряд идущие слова в транскрипте; текст плашки
     собираем ИЗ НАЙДЕННЫХ СЛОВ, а не из кандидата, чтобы на экран не попало сочинённое;
  2. не длиннее max-words слов;
  3. говорит герой, а не представитель фонда (`card.fund_speaker`);
  4. не задевает чувствительные темы канала (`profile.sensitivity.patterns` + `card.risk_patterns`);
  5. не больше одной фразы на главу — иначе приём перестаёт быть событием.

Фраза разбивается на две строки по смысловой границе ближе к середине: первая строка — предмет
(рубином), вторая — само утверждение (костью).

usage: claims_pick.py [--dry-run] [--max-words 12] [--per-chapter 1]
exit: 0 — ок · 1 — нет входов (транскрипт / правки / акты)
"""
import argparse
import datetime
import json
import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

from _bootstrap import P, W6  # noqa: E402

import tz_diff as TD  # noqa: E402
from align import norm as wnorm  # noqa: E402
from chapters_from_plan import load_words, tcf  # noqa: E402

ANCHOR_RX = re.compile(r'Якор[ья]\s*:\s*[«"](.+?)[»"]', re.I)
# переносить строку лучше ПЕРЕД этими словами: с них начинается вторая половина мысли
BREAK_BEFORE = {'и', 'а', 'но', 'что', 'чтобы', 'потому', 'когда', 'если', 'как', 'же', 'то',
                'это', 'меня', 'мне', 'я', 'он', 'она', 'они', 'мы', 'у', 'в', 'на', 'за', 'с'}
TAIL = ' .,;:!?—-…'
# слова-паразиты устной речи: на плашке во весь экран они читаются как небрежность,
# хотя в потоке речи незаметны. Кандидат с ними выбывает
FILLER = ('вроде как', 'то есть', 'как сказать', 'как бы', 'ну вот', 'это самое', 'в общем')


def candidates():
    """→ [(текст, откуда)] в порядке предпочтения: сперва якоря глав, потом тезисы актов"""
    out = []
    pv = P.MONT / 'pravki_v2.json'
    if not pv.exists():
        pv = next(iter(sorted(P.MONT.glob('pravki*.json'))), None)
    if pv and pv.exists():
        for it in (json.loads(pv.read_text(encoding='utf-8')).get('all') or []):
            if str(it.get('key', '')).endswith('structure'):
                for blk in (it.get('parts') or {}).get('list') or []:
                    for s in blk.get('items') or []:
                        m = ANCHOR_RX.search(str(s))
                        if m:
                            out.append((m.group(1).strip(), 'якорь главы'))
    ac = W6 / 'acts_compact.json'
    if ac.exists():
        for a in json.loads(ac.read_text(encoding='utf-8')).get('acts') or []:
            for t in (a.get('theses') or []):
                out.append((str(t).strip(), f'тезис акта {a.get("act")}'))
            for c in (a.get('claims') or []):
                out.append((str(c.get('text', '')).strip(), f'утверждение акта {a.get("act")}'))
    return [(t, src) for t, src in out if t]


def find_seq(cw, phrase, nwords, index, min_run=4):
    """→ (i0, i1) самого длинного куска ката, который звучит в кандидате ДОСЛОВНО; None — не нашлось.

    Точного совпадения целиком требовать нельзя: в ТЗ реплика записана на слух и почти всегда
    чуть отличается от транскрипта («все самое детство, в 4 года я лежала в коме»). Поэтому
    ищем самый длинный ПОДРЯД идущий общий кусок и берём на экран слова КАТА — тогда на плашке
    в любом случае стоит то, что человек действительно сказал."""
    keys = [k for k in (wnorm(w) for w in TD.norm(phrase).split()) if k]
    if len(keys) < min_run:
        return None
    rare = min(keys, key=lambda k: len(index.get(k, ())) or 10 ** 6)
    spots = index.get(rare) or ()
    if not spots or len(spots) > 400:
        return None
    best = None
    for pos in spots:
        lo, hi = max(0, pos - len(keys) - 4), min(len(cw), pos + len(keys) + 4)
        win = [w['n'] for w in cw[lo:hi]]
        for block in SequenceMatcher(None, keys, win, autojunk=False).get_matching_blocks():
            if block.size >= min_run and (best is None or block.size > best[0]):
                best = (block.size, lo + block.b, lo + block.b + block.size - 1)
    if not best or best[0] > nwords:
        return None
    return best[1], best[2]


def starts_thought(cw, i, pause=0.3):
    """фраза во весь экран должна начинаться с начала мысли, а не с середины оборота.

    ⚠️ Паузы в этом транскрипте почти всегда 0.00 — распознавание ставит слова впритык, —
    поэтому главный признак не пауза, а знак препинания у предыдущего слова и прописная буква
    у первого. Пауза остаётся третьим признаком: на стыке планов она настоящая."""
    if i == 0 or cw[i]['s'] - cw[i - 1]['e'] >= pause:
        return True
    return cw[i - 1]['w'].strip()[-1:] in '.,!?…:;' or cw[i]['w'][:1].isupper()


def build_index(cw):
    """нормализованное слово → позиции в кате (чтобы не сканировать 7000 слов на каждого кандидата)"""
    ix = {}
    for i, w in enumerate(cw):
        ix.setdefault(w['n'], []).append(i)
    return ix


def two_lines(words):
    """слова ката → (строка рубином, строка костью).

    Режем один раз, ближе к середине по длине, но с поблажкой месту, где начинается вторая
    половина мысли («…и», «…что», «…потому»): тогда строки читаются как предмет и утверждение,
    а не как обрывок посреди оборота."""
    txt = [w for w in (str(w).strip(TAIL) for w in words) if w]
    if len(txt) < 2:
        return ' '.join(txt), ''
    half = sum(len(w) + 1 for w in txt) / 2
    best, run = None, 0
    for i in range(1, len(txt)):
        run += len(txt[i - 1]) + 1
        pen = abs(run - half) - (6 if txt[i].lower() in BREAK_BEFORE else 0)
        if best is None or pen < best[0]:
            best = (pen, i)
    cut = best[1]
    return ' '.join(txt[:cut]), ' '.join(txt[cut:])


def sensitive_rx():
    """регулярки чувствительных тем: канон канала + проектные имена из карточки"""
    pats = list((P.profile('sensitivity.patterns') or []))
    pats += list(P.get('risk_patterns', []) or [])
    out = []
    for p in pats:
        rx = p.get('rx') if isinstance(p, dict) else p
        if rx:
            try:
                out.append((re.compile(rx), (p.get('topic') if isinstance(p, dict) else '') or 'чувствительная тема'))
            except re.error:
                pass
    return out


def chapter_of(sec, chap, dur):
    for i, (t0, no) in enumerate(chap):
        t1 = chap[i + 1][0] if i + 1 < len(chap) else dur
        if float(t0) <= sec < t1:
            return str(no)
    return str(chap[-1][1]) if chap else ''


def main():
    ap = argparse.ArgumentParser(description='крупные фразы фильма → card.claims')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--max-words', type=int, default=12)
    ap.add_argument('--per-chapter', type=int, default=1)
    a = ap.parse_args()

    cands = candidates()
    if not cands:
        print('!! нет кандидатов: ни якорей глав в правках, ни acts_compact.json')
        return 1
    cw = load_words(P.WORDS)
    if not cw:
        print(f'!! пустой транскрипт {P.WORDS}')
        return 1
    dur = float(P.get('duration_sec', 0)) or cw[-1]['e']
    chap = [(float(s), str(n)) for s, n in (P.get('chapters') or [])]
    fund = str(P.get('fund_speaker', '') or '')
    rxs = sensitive_rx()
    index = build_index(cw)

    picked, by_ch, drops = [], {}, {}
    for text, src in cands:
        seq = find_seq(cw, text, a.max_words, index)
        if not seq:
            drops.setdefault('в кате так не говорят', []).append(text)
            continue
        i0, i1 = seq
        sec, end = cw[i0]['s'], cw[i1]['e']
        if fund and _speaker_at(sec) == fund:
            drops.setdefault('говорит фонд, а не герой', []).append(text)
            continue
        said = ' '.join(w['w'] for w in cw[i0:i1 + 1])
        hit = next((topic for rx, topic in rxs if rx.search(TD.norm(said))), None)
        if hit:
            drops.setdefault(f'чувствительная тема: {hit}', []).append(said)
            continue
        if any(f in TD.norm(said) for f in FILLER):
            drops.setdefault('слова-паразиты в кадре', []).append(said)
            continue
        # якорь главы выбран судьёй как реплика, ради которой глава существует, — ему верим.
        # Тезисы и утверждения актов собраны машинно, поэтому от них требуем целой мысли.
        if src != 'якорь главы' and not starts_thought(cw, i0):
            drops.setdefault('машинный кандидат не с начала мысли', []).append(said)
            continue
        no = chapter_of(sec, chap, dur)
        if len(by_ch.get(no, [])) >= a.per_chapter:
            drops.setdefault('в главе уже есть фраза', []).append(said)
            continue
        big, small = two_lines([w['w'] for w in cw[i0:i1 + 1]])
        rec = {'sec': int(sec), 'end': round(end, 2), 'ch': no, 'src': src,
               'said': said, 'big': big, 'small': small, 'words': i1 - i0 + 1}
        by_ch.setdefault(no, []).append(rec)
        picked.append(rec)

    picked.sort(key=lambda r: r['sec'])
    print(f'кандидатов {len(cands)} · прошли все правила {len(picked)} '
          f'· глав с фразой {len(by_ch)} из {len(chap)}')
    for r in picked:
        print(f'  {tcf(r["sec"]):>9} гл.{r["ch"]}  «{r["big"]} / {r["small"]}»  ({r["src"]}, {r["words"]} сл.)')
    for why, lst in sorted(drops.items(), key=lambda kv: -len(kv[1])):
        print(f'  ✗ {why}: {len(lst)}')

    if not a.dry_run:
        p = Path(os.environ.get('YTAI_CARD') or (Path(P.REVIEW_DIR) / 'review_card.json'))
        card = json.loads(p.read_text(encoding='utf-8'))
        card['claims'] = [[r['sec'], r['big'], r['small']] for r in picked]
        P.write_json_atomic(p, card)
        P.write_json_atomic(W6 / 'claims_pick.json',
                            {'schema': 'claims-pick-v1', 'code': P.CODE, 'cut_version': P.CUT_VERSION,
                             'built': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
                             'picked': picked, 'dropped': {k: len(v) for k, v in drops.items()}})
        print(f'записано в {p.name}: claims {len(picked)} · отчёт claims_pick.json')
    return 0


_SPK = None


def _speaker_at(sec):
    """кто говорит на этой секунде — по сегментам транскрипта (в словах спикер тоже есть, но
    у отдельного слова он иногда пуст, а у сегмента — всегда)"""
    global _SPK
    if _SPK is None:
        d = json.loads(Path(P.WORDS).read_text(encoding='utf-8'))
        _SPK = [(float(s.get('start', 0)), float(s.get('end', 0)), str(s.get('speaker', '')))
                for s in (d.get('segments') or [])]
    return next((sp for t0, t1, sp in _SPK if t0 <= sec <= t1), '')


if __name__ == '__main__':
    sys.exit(main())
