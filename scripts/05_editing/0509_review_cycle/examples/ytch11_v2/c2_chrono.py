#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хронология событий: кандидаты из ВСЕХ исходников (Claude4_assembly) + ката v2.

1) Регекс-скан временных маркеров (годы, возраст, месяцы, праздники, "мне было").
2) Qwen3-8B (mlx, локально) по окну ±20с вокруг маркера: событие + когда + уверенность.
Выход: chrono_candidates.json [{scene,src_tc,marker,window,event,when,conf}]
"""
import json, re, os, collections

WORK = os.path.dirname(os.path.abspath(__file__))
P = '/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik'
ASM = P + '/00_Setup/YTCH11_Claude4_assembly.json'
OUT = os.path.join(WORK, 'chrono_candidates.json')
MODEL = 'mlx-community/Qwen3-8B-4bit'

MARKERS = re.compile(
    r'\b(19|20)\d\d\b|мне было|было \d+|в \d+ (год|года|лет)|\b\d+ лет\b|летом|зимой|осенью|весной|'
    r'ноябр|декабр|январ|феврал|марта|апрел|сентябр|октябр|'
    r'рождеств|пасх|новый год|день рождения|месяц назад|год назад|лет назад|'
    r'когда мне|когда я вышла|когда родился|до смерти|после смерти|класса\b|классе\b',
    re.I)

PROMPT = """/no_think Ты помощник документалиста. Герои — Лиза (19, выпускница интерната, мама младенца Миши) и Виталик (её муж, тоже выпускник интерната). Из фрагмента интервью выдели СОБЫТИЕ жизни героев и КОГДА оно случилось (возраст/год/сезон/привязка к другому событию). Если событие не жизненное (общие рассуждения) — верни null.
Фрагмент:
---
{win}
---
Ответь СТРОГО JSON: {{"event": "<короткое событие или null>", "when": "<когда: возраст/год/привязка или null>", "conf": "<high|low>"}}"""


def tosec(x):
    if isinstance(x, (int, float)):
        return float(x)
    p = [float(v) for v in str(x).split(':')]
    return p[0]*3600+p[1]*60+p[2] if len(p) == 3 else p[0]*60+p[1]


def main():
    asm = json.load(open(ASM, encoding='utf-8'))
    # поток слов по (scene, source) для окон
    streams = collections.defaultdict(list)
    for seg in asm['segments']:
        for w in seg.get('words') or []:
            streams[(seg['scene'], seg['source_file'])].append(
                (tosec(w['s']), w['w']))
    for k in streams:
        streams[k].sort()

    # кандидаты: сегменты с маркером (дедуп параллельных дорожек по тексту-нормали)
    seen_txt = set()
    cands = []
    for seg in asm['segments']:
        t = seg.get('text', '')
        if not t or not MARKERS.search(t):
            continue
        key = re.sub(r'[^а-яa-z0-9]', '', t.lower())[:60]
        if key in seen_txt:
            continue
        seen_txt.add(key)
        s0 = tosec(seg['start'])
        st = streams[(seg['scene'], seg['source_file'])]
        win = ' '.join(w for ts, w in st if s0 - 20 <= ts <= s0 + 25)
        cands.append({'scene': seg['scene'], 'src_file': seg['source_file'],
                      'tc': seg['tc_in'], 'marker': MARKERS.search(t).group(0),
                      'window': win[:700]})
    print('candidates:', len(cands), flush=True)

    done = {}
    if os.path.exists(OUT):
        try:
            done = {(r['scene'], r['tc']): r for r in json.load(open(OUT, encoding='utf-8'))}
        except Exception:
            done = {}

    from mlx_lm import load, generate
    from mlx_lm.sample_utils import make_sampler
    model, tok = load(MODEL)
    sampler = make_sampler(temp=0.0)
    res = list(done.values())
    todo = [c for c in cands if (c['scene'], c['tc']) not in done]
    print('todo:', len(todo), flush=True)
    for i, c in enumerate(todo):
        msg = PROMPT.format(win=c['window'])
        prompt = tok.apply_chat_template([{'role': 'user', 'content': msg}],
                                         add_generation_prompt=True)
        r = generate(model, tok, prompt=prompt, max_tokens=150, sampler=sampler)
        m = re.search(r'\{.*\}', r, flags=re.S)
        parsed = {}
        if m:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                parsed = {}
        c2 = dict(c)
        c2['event'] = parsed.get('event')
        c2['when'] = parsed.get('when')
        c2['conf'] = parsed.get('conf')
        res.append(c2)
        if i % 20 == 0:
            print('  %d/%d %s | %s -> %s' % (i, len(todo), c['scene'][:14],
                                             c['marker'], str(parsed.get('event'))[:50]), flush=True)
            json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
    ev = [r for r in res if r.get('event') and r['event'] != 'null']
    print('events extracted: %d of %d' % (len(ev), len(res)), flush=True)


if __name__ == '__main__':
    main()
