#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Пакеты по АКТАМ v4 для агентов-ревьюеров (Workflow) → packs/actNN.md + packs/index.json.

Главы (chapters_cards.json: tc_sec, name, act, color) группируются в акты по полю act —
агент видит соседние главы целиком (связность), а находки пишет по главам.
Пакет = всё, что известно про акт: полный транскрипт абзацами (спикеры, TC, границы глав),
экраны (OCR), VLM-описания кадров, техконтроль, адреса исходников, изменения v3→v4 и v2→v4,
флаги фонда, директивы ревью v2, пути кадров 1 fps (агент может открыть кадр Read'ом).
Плюс packs/v2_unplaced.md — директивы v2 без места в v4 (вырезано / «выпало из плана»).
"""
import json
import os
import re

WORK = os.path.dirname(os.path.abspath(__file__))
REV = os.path.dirname(WORK)
FRAMES = '/Volumes/T9-Black-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review/v4_review/frames1s'
PACKS = os.path.join(WORK, 'packs')


def J(name, default=None):
    p = os.path.join(WORK, name)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else default


def tc(x):
    x = int(round(float(x)))
    return '%d:%02d' % (x // 60, x % 60)


def frame(sec):
    return f'{FRAMES}/f{int(sec) + 1:04d}.jpg'


def overlap(a0, a1, b0, b1):
    return a0 < b1 and a1 > b0


def parse_v2_tc(s):
    m = re.search(r'v2\s+(\d+):(\d{2})[–-](\d+):(\d{2})', s)
    if not m:
        return None
    a, b, c, d = map(int, m.groups())
    return a * 60 + b, c * 60 + d


def v2_to_v4(t0, t1, map_v2):
    hits = [m for m in map_v2 if overlap(m['b_t0'], m['b_t1'], t0, t1)]
    if not hits:
        return None
    return min(m['v4_t0'] for m in hits), max(m['v4_t1'] for m in hits)


def base_to_v4(bt, fwd):
    prev = [m for m in fwd if m['b_t1'] <= bt + 1]
    return max(prev, key=lambda m: m['b_t1'])['v4_t1'] if prev else 0.0


def main():
    os.makedirs(PACKS, exist_ok=True)
    words = json.load(open(f'{REV}/YTCH12_v4.words.json', encoding='utf-8'))
    spk = J('speakers.json', {})
    chapters = sorted(J('chapters_cards.json'), key=lambda c: c['tc_sec'])
    total = float(words['duration_sec'])
    for i, ch in enumerate(chapters):
        ch['t1'] = chapters[i + 1]['tc_sec'] if i + 1 < len(chapters) else total
        ch['n'] = i + 1
    screens = J('screens.json', [])
    vp = os.path.join(WORK, 'vlm_sweep.jsonl')
    vlm = [json.loads(x) for x in open(vp, encoding='utf-8')] if os.path.exists(vp) else []
    qc = J('qc.json', {})
    msrc, m3, m2 = J('map_src.json', []), J('map_v3.json', []), J('map_v2.json', [])
    d3, d2 = J('diff_v3.json', {}), J('diff_v2.json', {})
    risks = J('risk_hits.json', [])
    v2d = J('v2_directives.json', {'rows': []})
    for r in v2d['rows']:
        iv = parse_v2_tc(r['tc_v2'])
        r['_v4'] = v2_to_v4(iv[0], iv[1], m2) if iv else None
        r['_kind'] = 'v2' if iv else 'plan'

    acts = []
    for ch in chapters:
        if not acts or acts[-1]['act'] != ch['act']:
            acts.append({'act': ch['act'], 'chapters': []})
        acts[-1]['chapters'].append(ch)

    index = []
    for ai, act in enumerate(acts, 1):
        a, b = act['chapters'][0]['tc_sec'], act['chapters'][-1]['t1']
        L = [f'# Акт {ai} · v4 {tc(a)}–{tc(b)} ({(b - a) / 60:.1f} мин)', '', '## Главы акта']
        for ch in act['chapters']:
            L.append(f'- «{ch["name"]}» · {tc(ch["tc_sec"])}–{tc(ch["t1"])}'
                     + (f' — {ch["note"]}' if ch.get('note') else ''))
        L += ['', '## Транскрипт (дословно, абзацы wordrole: [TC] Спикер: текст)']
        chi = 0
        for p in words['paragraphs']:
            ps, pe = float(p['start']), float(p['end'])
            if not (a - 0.01 <= ps < b):
                continue
            while chi < len(act['chapters']) and ps >= act['chapters'][chi]['tc_sec'] - 0.01:
                ch = act['chapters'][chi]
                L.append(f'\n### «{ch["name"]}» ({tc(ch["tc_sec"])})')
                chi += 1
            L.append(f'[{tc(ps)}–{tc(pe)}] {spk.get(p["speaker"], p["speaker"])}: {p["text"]}')
        L.append('')

        L += ['## Экраны с текстом (OCR Apple Vision, события; кадр можно открыть Read)']
        for e in screens:
            if a <= e['t0'] < b:
                L.append(f'[{tc(e["t0"])}–{tc(e["t1"])}] «{e["text"][:160]}» · лиц≈{e.get("faces_avg", 0)}'
                         f' · кадр {FRAMES}/{e["rep"]}')
        L += ['', '## Что в кадре (Qwen2.5-VL, кадр каждые 8 с)']
        for v in vlm:
            if a <= v['sec'] < b:
                L.append(f'[{tc(v["sec"])}] {v["desc"]} · {frame(v["sec"])}')
        L += ['', '## Техконтроль (ffmpeg)']
        cuts = [c for c in qc.get('cuts', []) if a <= c < b]
        L.append(f'склеек: {len(cuts)} ({len(cuts) / max(0.1, (b - a) / 60):.1f}/мин; по фильму '
                 f'{qc.get("summary", {}).get("cuts_per_min", "?")}/мин)')
        for k, lab in (('black', 'чёрное'), ('freeze', 'фриз'), ('silence', 'тишина'),
                       ('long_shots', 'план без склейки')):
            for x in qc.get(k, []):
                if a <= x['t0'] < b:
                    L.append(f'{lab}: {tc(x["t0"])}–{tc(x["t1"])} ({x["dur"]:.1f} с) · кадр {frame(x["t0"])}')
        L += ['', '## Адреса исходников (n-gram: v4 → сцена · файл · src-TC)']
        for m in msrc:
            if a <= m['v4_t0'] < b:
                L.append(f'[{tc(m["v4_t0"])}–{tc(m["v4_t1"])}] {m["scene"]} · {m["src_file"]} · '
                         f'src {tc(m["src_t0"])}–{tc(m["src_t1"])}')
        L.append('')
        for name, fwd, d in (('v3 (монтаж 31.08)', m3, d3), ('v2 («История Светы» 26.08)', m2, d2)):
            if not d:
                continue
            L += [f'## Изменения относительно {name}']
            for x in d.get('new', []):
                if a <= x['t0'] < b:
                    L.append(f'➕ НОВОЕ в v4 {tc(x["t0"])}–{tc(x["t1"])} ({x["sec"]:.0f} с): {x["text"][:700]}')
            for x in d.get('moved', []):
                if a <= x['v4_t0'] < b:
                    L.append(f'⇄ ПЕРЕСТАВЛЕНО на v4 {tc(x["v4_t0"])} (в базе было {tc(x["b_t0"])}): {x["text"][:220]}')
            for x in d.get('removed', []):
                at = base_to_v4(x['t0'], fwd)
                if a <= at < b or (ai == len(acts) and at >= b):
                    L.append(f'✂️ УБРАНО (в базе {tc(x["t0"])}–{tc(x["t1"])}, {x["sec"]:.0f} с; '
                             f'место в v4 ≈{tc(at)}): {x["text"][:700]}')
            L.append('')
        L += ['## Флаги согласования с фондом (реестр рисков; политика 27.08: ⚠️ фонд/блюр, НЕ стоп)']
        for h in risks:
            if a <= h['t0'] < b:
                L.append(f'⚠️ {h["label"]} @{h["tc"]} ({spk.get(h["speaker"], h["speaker"])}): …{h["context"]}…')
        L += ['', '## Директивы ревью v2, чей материал в этом акте (проверить: выполнено?)']
        for r in v2d['rows']:
            if r['_v4'] and a <= r['_v4'][0] < b:
                L.append(f'#{r["n"]} [v2 {r["tc_v2"]} → v4 {tc(r["_v4"][0])}–{tc(r["_v4"][1])}] '
                         f'{r["status"]}: {r["directive"]}')
        L.append('')
        path = os.path.join(PACKS, f'act{ai:02d}.md')
        open(path, 'w', encoding='utf-8').write('\n'.join(L))
        index.append({'act': ai, 't0': a, 't1': b, 'pack': path, 'chars': sum(len(x) for x in L),
                      'chapters': [{'n': c['n'], 'name': c['name'], 't0': c['tc_sec'], 't1': c['t1']}
                                   for c in act['chapters']]})

    G = ['# Директивы ревью v2 без места в v4', '',
         'kind=v2 — материал v2 в v4 не найден (вероятно вырезан = директива «вырезать» выполнена);',
         'kind=plan — «выпало из плана» (опора монтажного листа, которую просили вернуть).', '']
    for r in v2d['rows']:
        if not r['_v4']:
            G.append(f'#{r["n"]} ({r["_kind"]}) [{r["tc_v2"]}] {r["status"]}: {r["directive"]}\n'
                     f'   транскрипт v2: {r["transcript_v2"][:500]}')
    G += ['', '## Техблок ревью v2', v2d.get('tech_block', '')]
    open(os.path.join(PACKS, 'v2_unplaced.md'), 'w', encoding='utf-8').write('\n'.join(G))
    json.dump(index, open(os.path.join(PACKS, 'index.json'), 'w'), ensure_ascii=False, indent=1)
    print('acts:', len(index), '· chapters:', len(chapters), '· max chars', max(x['chars'] for x in index))
    for x in index:
        print(f' act{x["act"]:02d} {tc(x["t0"])}–{tc(x["t1"])} · {len(x["chapters"])} гл · {x["chars"]} ch')


if __name__ == '__main__':
    main()
