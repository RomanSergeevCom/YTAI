#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""risk_registry.py — чек-лист согласования с фондом по транскрипту ката (наследник b_risk_v4 / b_risk_v2, YTCH).

Паттерны живут НЕ в коде, а в профиле канала YTs/{CH}/review_profile.json → sensitivity.patterns:
  [{key, rx, topic, note, kind?: fund|blur, hard?: bool}]
  rx — regex (re.search) по НОРМАЛИЗОВАННОМУ транскрипту: нижний регистр, ё→е, только буквы/цифры,
  слова через один пробел (\\b — граница слова; фразы из нескольких слов — тоже через пробел).
Проектные имена (Руслан, Дядяков, Люба…) — в карточке фильма, ключ `risk_patterns` той же схемы.

Сканирует P.WORDS (words.json: segments[].words[{w,s,e,speaker}]) → W6/risk.json:
  [{tc, sec, t0, t1, speaker, hit, phrase (±6 слов), topic, key, note, action, hard}]
  action: «⚠️ на подтверждение фонда» (kind fund) · «блюр» (kind blur) · «⛔ прямой запрет» — ТОЛЬКО hard: true
  (письменный запрет юриста фонда). Политика 27.08 (feedback_ytch_sensitive_fund_approved): реестр — чек-лист,
  не нож; ⛔ по паттерну без hard не выдаётся никогда.

usage: risk_registry.py [--apply] [--channel YTCH] [--patterns file.json] [--words path] [--out path]
                        [--pravki path] [--dedup-sec 20] [--pad 3] [--quiet]
  --apply     проставить sensitive:{flag:true, reason} в ТЗ M/pravki_v2.json, чей таймкод (timeline_in/out_sec,
              иначе tc_range / v1_tc) пересекается с находкой ±pad с; без --apply — сухой прогон (что бы пометил);
  --channel   паттерны из профиля другого канала (проверка чужого транскрипта на ложные срабатывания);
  --patterns  файл с паттернами вместо профиля (список или {"patterns": [...]}).
env: YTAI_CARD=<review_card.json>; YTAI_WORK_DIR / YTAI_PRAVKI_DIR — куда писать (тесты).
Сводка в консоль ≤2 КБ.
"""
import argparse
import bisect
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'stages'))
from _bootstrap import P, W6, M, ROOT  # noqa: E402

ACTION = {'fund': '⚠️ на подтверждение фонда', 'blur': 'блюр'}
HARD = '⛔ прямой запрет'
YTAI = ROOT.parent.parent.parent


def pravki_file():
    """файл правок по канону pravki_lib (карточка pravki_file → pravki.json → pravki_v2.json)"""
    try:
        from pravki_lib import pravki_path
        return str(pravki_path(M, P))
    except (ImportError, SystemExit):
        return str(M / 'pravki_v2.json')


def norm(w):
    return re.sub(r'[^а-яa-z0-9]', '', str(w).lower().replace('ё', 'е'))


def tc(s):
    s = int(s)
    return f'{s // 60}:{s % 60:02d}'


def load_words(path):
    d = json.load(open(path, encoding='utf-8'))
    out = []
    for seg in d.get('segments') or []:
        for w in seg.get('words') or []:
            n = norm(w.get('w', ''))
            if n:
                out.append({'n': n, 'w': w['w'], 's': float(w['s']), 'e': float(w['e']),
                            'spk': w.get('speaker') or seg.get('speaker') or ''})
    out.sort(key=lambda x: x['s'])
    return out


def load_patterns(a):
    """профиль канала (или --channel / --patterns) + risk_patterns карточки → [{key, rx(compiled), …}]"""
    if a.patterns:
        raw = json.load(open(a.patterns, encoding='utf-8'))
        raw = raw.get('patterns', raw) if isinstance(raw, dict) else raw
        src = a.patterns
    elif a.channel:
        pp = YTAI / 'YTs' / a.channel.upper() / 'review_profile.json'
        if not pp.exists():
            raise SystemExit(f'нет профиля {pp}')
        raw = (json.load(open(pp, encoding='utf-8')).get('sensitivity') or {}).get('patterns') or []
        src = f'профиль {a.channel.upper()}'
    else:
        raw = P.profile('sensitivity.patterns') or []
        src = f'профиль {P.CHANNEL or "?"}'
    extra = P.get('risk_patterns') or []
    pats = []
    for i, r in enumerate(list(raw) + list(extra)):
        try:
            rx = re.compile(r['rx'])
        except (re.error, KeyError) as ex:
            raise SystemExit(f'паттерн #{i} {r.get("key", "?")}: плохой rx — {ex}')
        pats.append({'key': r.get('key', f'p{i}'), 'rx': rx, 'topic': r.get('topic', r.get('key', '')),
                     'note': r.get('note', ''), 'kind': r.get('kind', 'fund'), 'hard': bool(r.get('hard'))})
    return pats, src, len(extra)


def scan(words, pats, dedup_sec=20.0):
    text = ' '.join(w['n'] for w in words)
    starts, pos = [], 0
    for w in words:
        starts.append(pos)
        pos += len(w['n']) + 1
    hits = []
    for p in pats:
        for m in p['rx'].finditer(text):
            i = bisect.bisect_right(starts, m.start()) - 1
            j = bisect.bisect_right(starts, max(m.start(), m.end() - 1)) - 1
            w0, w1 = words[i], words[j]
            hits.append({'tc': tc(w0['s']), 'sec': round(w0['s'], 2), 't0': round(w0['s'], 2), 't1': round(w1['e'], 2),
                         'speaker': w0['spk'], 'hit': m.group(0),
                         'phrase': ' '.join(x['w'] for x in words[max(0, i - 6):j + 7]),
                         'topic': p['topic'], 'key': p['key'], 'note': p['note'],
                         'action': HARD if p['hard'] else ACTION.get(p['kind'], ACTION['fund']), 'hard': p['hard']})
    hits.sort(key=lambda h: (h['t0'], h['key']))
    ded, last = [], {}
    for h in hits:                                   # один ключ не чаще раза в dedup_sec
        if h['key'] in last and h['t0'] - last[h['key']] < dedup_sec:
            continue
        last[h['key']] = h['t0']
        ded.append(h)
    return ded


def tz_window(p):
    """(t0, t1) ТЗ: timeline_in/out_sec → tc_range «a–b» → v1_tc; None, если таймкода нет («весь фильм»)."""
    if p.get('timeline_in_sec') is not None:
        t0 = float(p['timeline_in_sec'])
        return t0, float(p.get('timeline_out_sec') or t0)
    rx = re.compile(r'(\d{1,2}):(\d{2})(?:[.,](\d+))?')
    ms = rx.findall(str(p.get('tc_range') or '')) or rx.findall(str(p.get('v1_tc') or ''))
    if not ms:
        return None
    secs = [int(a) * 60 + int(b) + (float('0.' + c) if c else 0) for a, b, c in ms]
    return min(secs), max(secs)


def label(p, i):
    n = p.get('num')
    return n if isinstance(n, str) else (f'ТЗ-{int(n):02d}' if n is not None else f'ТЗ-{i + 1:02d}')


def apply_to_pravki(hits, path, pad, do_write):
    if not Path(path).exists():
        print(f'нет {path} — помечать нечего')
        return 0
    pr = json.load(open(path, encoding='utf-8'))
    n_flag = 0
    for i, p in enumerate(pr.get('all') or []):
        win = tz_window(p)
        if win is None:
            continue
        found = [h for h in hits if h['t0'] - pad <= win[1] and h['t1'] + pad >= win[0]]
        if not found:
            continue
        reasons = [f'{h["action"]} · {h["topic"]} @{h["tc"]} «{h["hit"]}»' for h in found]
        old = p.get('sensitive') if isinstance(p.get('sensitive'), dict) else {}
        merged = list(dict.fromkeys((old.get('reason', '').split(' ; ') if old.get('reason') else []) + reasons))
        p['sensitive'] = {'flag': True, 'reason': ' ; '.join(merged)}
        n_flag += 1
        print(f'  {"помечено" if do_write else "пометил бы"} {label(p, i)} ({p.get("tc_range") or p.get("v1_tc")}): {reasons[0][:90]}'
              + (f' (+{len(reasons) - 1})' if len(reasons) > 1 else ''))
    if do_write and n_flag:
        P.write_json_atomic(path, pr)
    return n_flag


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--channel')
    ap.add_argument('--patterns')
    ap.add_argument('--words', default=P.WORDS)
    ap.add_argument('--out', default=str(W6 / 'risk.json'))
    ap.add_argument('--pravki', default=None, help='файл правок (по умолчанию — канон pravki_lib: pravki.json / pravki_v2.json)')
    ap.add_argument('--dedup-sec', type=float, default=20.0)
    ap.add_argument('--pad', type=float, default=3.0)
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()

    pats, src, n_extra = load_patterns(a)
    if not pats:
        print(f'в {src} нет sensitivity.patterns — риск-реестр пуст (канал без политики фонда?)')
        P.write_json_atomic(a.out, [])
        return 0
    words = load_words(a.words)
    hits = scan(words, pats, a.dedup_sec)
    P.write_json_atomic(a.out, hits)

    by_action = {}
    for h in hits:
        by_action[h['action']] = by_action.get(h['action'], 0) + 1
    lines = [f'[risk] {P.CODE} {P.CUT_VERSION} · слов {len(words)} · паттернов {len(pats)} ({src}'
             + (f' + {n_extra} из карточки' if n_extra else '') + f') · находок {len(hits)}: '
             + ' · '.join(f'{k} {v}' for k, v in by_action.items()) + f' → {a.out}']
    if not a.quiet:
        for h in hits:
            lines.append(f'{h["tc"]:>6} {h["action"][:2]} {h["topic"][:34]:34s} «…{h["phrase"][:70]}…»')
    text = '\n'.join(lines)
    if len(text) > 2000:
        cut = text[:1900]
        text = cut[:cut.rfind('\n')] + f'\n… ещё {len(hits) - cut.count(chr(10))} строк — см. {a.out}'
    print(text, flush=True)
    if hits:
        n = apply_to_pravki(hits, a.pravki or pravki_file(), a.pad, a.apply)
        print(f'ТЗ с пересечением: {n}' + ('' if a.apply else ' (сухой прогон, --apply запишет)'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
