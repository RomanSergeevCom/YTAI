#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6 S7: контрольные композиты — каждый стилл-сегмент V3/V4/V5/V6 из YTUVI01_review_v6.json,
наложенный на кадр рендера в момент timeline_in (кадр hires 1920) → previews_v6/<sid>.jpg (960px)
+ previews_v6/index.html (галерея по дорожкам). Для самопроверки глазами/агентами: прозрачность,
попадание стрелки, читаемость, наезды на титры ката.
"""
import json, sys
from pathlib import Path
from PIL import Image

W6 = Path(__file__).parent
OUT = W6 / 'previews_v6'
OUT.mkdir(exist_ok=True)
J = Path('/Volumes/T7-Blue-2-RYA/YTUVI-Projects/YTUVI01_Corundum_Ruby/00_Setup/05_Review/YTUVI01_review_v6.json')
doc = json.load(open(J))
segs = [s for s in doc['segments'] if s['kind'] == 'graphic' and s['track'] in ('V3', 'V4', 'V5', 'V6')]
only = sys.argv[1] if len(sys.argv) > 1 else None
rows = []
for s in segs:
    if only and s['track'] != only:
        continue
    sec = int(s['timeline_in_sec'] + 0.5)
    if sec >= 2440:
        continue
    fr = W6 / 'hires' / f'h{sec + 1:04d}.jpg'
    dst = OUT / f'{s["segment_id"]}.jpg'
    if not dst.exists():
        bg = Image.open(fr).convert('RGBA')
        ov = Image.open(s['source_path']).convert('RGBA').resize(bg.size, Image.LANCZOS)
        Image.alpha_composite(bg, ov).convert('RGB').resize((960, 540), Image.LANCZOS).save(dst, quality=85)
    mm, ss = divmod(sec, 60)
    rows.append((s['track'], f'{mm}:{ss:02d}', s['segment_id'], dst.name, Path(s['source_path']).name))
html = ['<meta charset="utf-8"><style>body{font-family:Helvetica;background:#111;color:#ddd}h2{margin:30px 0 8px}'
        '.g{display:flex;flex-wrap:wrap;gap:10px}.c{width:480px}.c img{width:480px;display:block}.c div{font-size:12px;padding:4px 0}</style>']
for tr in ('V3', 'V4', 'V5', 'V6'):
    rs = [r for r in rows if r[0] == tr]
    html.append(f'<h2>{tr} — {len(rs)}</h2><div class="g">')
    for r in rs:
        html.append(f'<div class="c"><img src="{r[3]}"><div>{r[1]} · {r[2]} · {r[4]}</div></div>')
    html.append('</div>')
(OUT / 'index.html').write_text('\n'.join(html))
print(len(rows), 'композитов →', OUT / 'index.html')
