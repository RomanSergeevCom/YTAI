#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6 S2: Apple Vision OCR по hires-кадрам (1920×1080) → ocr_hires.jsonl,
затем ПЕРЕсборка инвентаря экранов по hires-OCR → screens_v6.json (перезапись).

Причина: OCR по 1280×720 путает Щ/Ш, Й/И, латиницу/кириллицу — на 1080p
дословность заметно выше. Координаты bbox нормализованы (origin левый верх) —
×3840/×2160 дают точку для стрелки-аннотации V5.
"""
import json, re, subprocess, sys
from pathlib import Path

W6 = Path(__file__).parent
sys.path.insert(0, str(W6))
import proj_config as P  # noqa: E402

HIRES = W6 / 'hires'
BIN = Path.home() / 'YTAI/scripts/999_extra/bin/vision_ocr_ru'
OUT = W6 / 'ocr_hires.jsonl'
P.banner('ocr')

files = sorted(HIRES.glob('h*.jpg'))
done = set()
if OUT.exists():
    for ln in open(OUT, encoding='utf-8'):
        try:
            done.add(Path(json.loads(ln)['file']).name)
        except Exception:
            pass
todo = [str(f) for f in files if f.name not in done]
print('hires frames:', len(files), 'todo:', len(todo), flush=True)
with open(OUT, 'a', encoding='utf-8') as out:
    for i in range(0, len(todo), 200):
        P.pause_gate('ocr')          # пауза на границе пачки, не посреди неё
        batch = todo[i:i + 200]
        p = subprocess.run([str(BIN)], input='\n'.join(batch), capture_output=True, text=True, timeout=900)
        out.write(p.stdout)
        out.flush()
        print(f'  ocr {min(i + 200, len(todo))}/{len(todo)}', flush=True)

# ── пересборка инвентаря по hires ──
# Границы глав — из карточки проекта (prep_config.json → "chapters").
# Пока главы нового ката не размечены, там лежит [[0,"01"]]: экраны получат главу «01»,
# а пересобрать инвентарь после разметки стоит секунды — OCR покадрово чекпойнтится
# и заново не гоняется.
CHAPTERS = P.CHAPTERS
chapter = P.chapter


def words(lines):
    s = set()
    for l in lines:
        for w in re.findall(r'[а-яёa-z0-9]+', l['t'].lower()):
            if len(w) >= 3 or w.isdigit():
                s.add(w)
    return s


recs = {}
for ln in open(OUT, encoding='utf-8'):
    try:
        d = json.loads(ln)
    except Exception:
        continue
    m = re.search(r'h(\d+)\.jpg', d['file'])
    if not m:
        continue
    sec = int(m.group(1)) - 1
    lines = [l for l in d.get('lines', []) if l.get('t', '').strip() and l.get('c', 0) >= 0.3]
    recs[sec] = {'sec': sec, 'faces': d.get('faces', 0), 'lines': lines, 'words': words(lines),
                 'frame': f'h{sec + 1:04d}.jpg'}

events, cur = [], None
for sec in sorted(recs):
    r = recs[sec]
    if not r['words']:
        continue
    if cur is not None and sec - cur['t1'] <= 2:
        u = cur['union']
        inter = len(u & r['words'])
        jac = inter / max(1, len(u | r['words']))
        sub = r['words'] <= u or u <= r['words'] or inter >= min(len(u), len(r['words'])) * .6
        if jac >= .3 or sub:
            cur['t1'] = sec
            cur['union'] |= r['words']
            cur['secs'].append(sec)
            continue
    cur = {'t0': sec, 't1': sec, 'union': set(r['words']), 'secs': [sec]}
    events.append(cur)

out = []
for i, e in enumerate(events):
    secs = e['secs']
    best = max(secs, key=lambda s: (sum(len(l['t']) for l in recs[s]['lines']), s))
    texts = []
    for s in secs:
        t = ' | '.join(l['t'] for l in recs[s]['lines'])
        if t and (not texts or texts[-1] != t):
            texts.append(t)
    out.append({
        'id': f's{i + 1:03d}', 't0': e['t0'], 't1': e['t1'], 'dur': e['t1'] - e['t0'] + 1,
        'tc': f'{e["t0"] // 60}:{e["t0"] % 60:02d}', 'chapter': chapter(e['t0']),
        'best_sec': best, 'best_frame': recs[best]['frame'], 'last_frame': recs[secs[-1]]['frame'],
        'text_best': ' | '.join(l['t'] for l in recs[best]['lines']),
        'lines_best': recs[best]['lines'],
        'texts_all': texts,
        'faces_avg': round(sum(recs[s]['faces'] for s in secs) / len(secs), 2),
    })
json.dump(out, open(W6 / 'screens_v6.json', 'w'), ensure_ascii=False, indent=1)
print('events (hires):', len(out), '| секунд с текстом:', sum(len(e['secs']) for e in events))
