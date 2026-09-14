#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""structure_call.py — обвязка ОДНОГО облачного прохода режима montage_tz (cloud/wf_structure_src.js).

Сам скрипт облако не вызывает: печатает строку Workflow({...}) для основной сессии, готовит вход
(контактный лист мокапов) и вливает выход агентов в план.

  python3 structure_call.py --print-call [--task structure|design_review|both]
      → строка Workflow({scriptPath, args}) с аргументами из карточки (film, rules_text профиля, пути)
  python3 structure_call.py --contact-sheet
      → cloud/in/contact_sheet_NN.jpg (4×4, ≤1568 px) из превью P.MOCK + cloud/in/design_screens.json
  python3 structure_call.py --apply
      → cloud/out/structure.json + segments.json → montage_plan.json (куски, каталог графики, главы);
        ручные note кусков и уже описанные экраны (screens/html) не перезаписываются
  python3 structure_call.py --apply-design
      → cloud/out/design_review.json → замечания в gfx_catalog[*].screens[*].review

Без --print-call/--apply/… (вызов из review.py stage «structure»): если cloud/out/structure.json есть —
--apply, иначе печатает строку вызова и выходит с кодом 0 (стадия SOFT: ждёт облака).
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mt_common import (P, REVIEW_DIR, ROOT, load_words, anchor, tc, plan_path, gfx_catalog_list,  # noqa: E402
                       write_json)

CLOUD = P.CLOUD
IN, OUT = CLOUD / 'in', CLOUD / 'out'
WF = ROOT / 'cloud' / 'wf_structure_src.js'
SEGMENTS = REVIEW_DIR / 'segments.json'
STRUCTURE = OUT / 'structure.json'
DESIGN = OUT / 'design_review.json'
SHEET_W, COLS, ROWS = 1568, 4, 4


def js(v):
    return json.dumps(v, ensure_ascii=False)


# ---------------- print-call ----------------
def call_args(task):
    a = {'task': task, 'film': P.FILM, 'rules': P.profile('rules_text', ''), 'target': P.get('target_runtime', '')}
    if task in ('structure', 'both'):
        if not SEGMENTS.exists():
            print(f'⚠️ нет {SEGMENTS} — сначала segment_local.py', file=sys.stderr)
        a['segments_file'] = str(SEGMENTS)
        pp = plan_path()
        if pp.exists():
            a['plan_file'] = str(pp)
            a['gfx_existing'] = {g['id']: g.get('title', '') for g in gfx_catalog_list(json.loads(pp.read_text(encoding='utf-8')))}
        a['out_file'] = str(STRUCTURE)
    if task in ('design_review', 'both'):
        sheets = sorted(IN.glob('contact_sheet_*.jpg'))
        if not sheets:
            print(f'⚠️ нет контактных листов в {IN} — сначала --contact-sheet', file=sys.stderr)
        a['sheets'] = [str(s) for s in sheets]
        a['screens_file'] = str(IN / 'design_screens.json')
        if task == 'both':
            a['design_out_file'] = str(DESIGN)
        else:
            a['out_file'] = str(DESIGN)
    return a


def print_call(task):
    OUT.mkdir(parents=True, exist_ok=True)
    print(f'Workflow({{scriptPath: {js(str(WF))}, args: {js(call_args(task))}}})')


# ---------------- contact sheet ----------------
def contact_sheet():
    from PIL import Image, ImageDraw, ImageFont
    mock = P.MOCK
    man_path = mock / 'manifest.json'
    if not man_path.exists():
        raise SystemExit(f'нет {man_path} — сначала build_mockups.py')
    man = json.loads(man_path.read_text(encoding='utf-8'))
    IN.mkdir(parents=True, exist_ok=True)
    cw = SHEET_W // COLS
    ch = cw * 9 // 16
    label_h = 26
    try:
        font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 18)
    except Exception:
        font = ImageFont.load_default()
    screens, sheets = [], []
    per = COLS * ROWS
    for si in range(0, len(man), per):
        batch = man[si:si + per]
        rows = (len(batch) + COLS - 1) // COLS
        sheet = Image.new('RGB', (cw * COLS, (ch + label_h) * rows), (24, 24, 28))
        d = ImageDraw.Draw(sheet)
        n = len(sheets) + 1
        for j, m in enumerate(batch):
            src = mock / m['thumb'] if (mock / m['thumb']).exists() else mock / m['png']
            try:
                im = Image.open(src).convert('RGB')
            except Exception:
                continue
            im.thumbnail((cw - 8, ch - 8))
            x, y = (j % COLS) * cw, (j // COLS) * (ch + label_h)
            sheet.paste(im, (x + 4, y + 4))
            key = f"{m['id']}_{m['variant']}"
            d.text((x + 6, y + ch + 3), f"{key} · {m['kind']}{' · α' if m.get('alpha') else ''}", fill=(235, 235, 235), font=font)
            screens.append({'sheet': f'contact_sheet_{n:02d}.jpg', 'cell': j + 1, 'row': j // COLS + 1, 'col': j % COLS + 1,
                            'id': key, 'gid': m['id'], 'variant': m['variant'], 'title': m['title'], 'kind': m['kind'],
                            'alpha': bool(m.get('alpha')), 'qc': m.get('qc')})
        out = IN / f'contact_sheet_{n:02d}.jpg'
        sheet.save(out, quality=88)
        sheets.append(out)
        print(f'{out.name}: {len(batch)} экранов · {sheet.size[0]}×{sheet.size[1]}')
    write_json(IN / 'design_screens.json', screens)
    print(f'листов {len(sheets)} · экранов {len(screens)} → {IN}')


# ---------------- apply structure ----------------
def apply_structure():
    if not STRUCTURE.exists():
        raise SystemExit(f'нет {STRUCTURE} — сначала прогон воркфлоу (--print-call)')
    if not SEGMENTS.exists():
        raise SystemExit(f'нет {SEGMENTS}')
    st = json.loads(STRUCTURE.read_text(encoding='utf-8'))
    if 'structure' in st and isinstance(st['structure'], dict):
        st = st['structure']
    segs = {s['id']: s for s in json.loads(SEGMENTS.read_text(encoding='utf-8'))}
    pp = plan_path()
    plan = json.loads(pp.read_text(encoding='utf-8')) if pp.exists() else {'schema': 'ytai-montage-plan-v1', 'pieces': [], 'gfx_catalog': []}
    old_by_seg = {p.get('seg'): p for p in plan.get('pieces', []) if p.get('seg')}
    old_cat = {g['id']: g for g in gfx_catalog_list(plan)}
    theses = {t['id']: t for t in st.get('theses', [])}
    ws = load_words()

    # графика: якорь на слово внутри тезиса
    gfx_by_seg, unplaced = {}, []
    order = [sid for sid in st.get('order', []) if sid in segs]
    missing = [sid for sid in st.get('order', []) if sid not in segs]
    for g in st.get('graphics', []):
        try:
            hint, word = float(g['on'][0]), str(g['on'][1])
        except Exception:
            unplaced.append((g.get('id'), 'нет on=[сек, слово]'))
            continue
        errs = []
        i = anchor(ws, hint, word, 'in', errs)
        t = ws[i]['s']
        home = next((sid for sid in order if segs[sid]['t_in'] - 0.5 <= t <= segs[sid]['t_out'] + 0.5), None)
        if home is None or errs:
            unplaced.append((g.get('id'), errs[0] if errs else f'слово «{word}» @{tc(t)} вне оставленных тезисов'))
            continue
        gfx_by_seg.setdefault(home, []).append([g['id'], [round(t, 2), ws[i]['w']]])
        cat = old_cat.get(g['id'])
        if cat is None:
            cat = {'id': g['id'], 'kind': g.get('kind', 'new'), 'title': g.get('text', ''), 'place': g.get('place', 'full')}
            old_cat[g['id']] = cat
            plan.setdefault('gfx_catalog', []).append(cat)
        else:
            cat.setdefault('title', g.get('text', ''))
        cat['text'] = g.get('text', cat.get('text', ''))

    pieces = []
    for n, sid in enumerate(order, 1):
        s, t = segs[sid], theses.get(sid, {})
        old = old_by_seg.get(sid, {})
        piece = {'id': f'{n:02d}', 'seg': sid, 'title': t.get('thesis') or s.get('thesis', sid)}
        if s.get('block'):
            piece['block'] = s['block']
        if t.get('act') or old.get('act'):
            piece['act'] = t.get('act') or old.get('act')
        piece['parts'] = [['say', s['in'], s['out']]]
        piece['gfx'] = gfx_by_seg.get(sid, []) + [g for g in old.get('gfx', []) if g[0] not in {x[0] for x in gfx_by_seg.get(sid, [])}]
        if old.get('note'):
            piece['note'] = old['note']              # ручная заметка — не перезаписывается
        for k, v in old.items():
            if k.startswith('manual_'):
                piece[k] = v
        pieces.append(piece)
    plan['pieces'] = pieces
    plan['cuts'] = st.get('cuts', [])
    if st.get('chapters'):
        seg2pid = {p['seg']: p['id'] for p in pieces}
        plan['chapters'] = [[seg2pid[c['id']], c['title']] for c in st['chapters'] if c.get('id') in seg2pid]
    if st.get('notes'):
        plan['structure_notes'] = st['notes']
    if unplaced:
        plan['unplaced_gfx'] = [{'id': gid, 'why': why} for gid, why in unplaced]
    write_json(pp, plan)
    kept = sum(1 for c in st.get('cuts', []) if c.get('keep'))
    print(f'план обновлён: кусков {len(pieces)} · keep {kept}/{len(st.get("cuts", []))} · экранов в каталоге {len(plan["gfx_catalog"])} '
          f'· глав {len(plan.get("chapters", []))} · ручных note сохранено {sum(1 for p in pieces if p.get("note"))} → {pp}')
    if missing:
        print(f'⚠️ в order есть id, которых нет в segments.json: {missing}')
    for gid, why in unplaced:
        print(f'⚠️ экран {gid} не поставлен: {why}')
    print('дальше: build_montage.py → build_mockups.py (экраны: gfx_catalog[*].screens — layout+text или html)')


def apply_design():
    if not DESIGN.exists():
        raise SystemExit(f'нет {DESIGN} — сначала прогон воркфлоу design_review')
    dr = json.loads(DESIGN.read_text(encoding='utf-8'))
    if 'design_review' in dr and isinstance(dr['design_review'], dict):
        dr = dr['design_review']
    items = {i['id']: i for i in dr.get('items', [])}
    n = 0
    for pp in [plan_path()] + [REVIEW_DIR / s['plan'] for s in (json.loads(plan_path().read_text(encoding='utf-8')).get('scenes') or []) if isinstance(s, dict)]:
        if not pp.exists():
            continue
        plan = json.loads(pp.read_text(encoding='utf-8'))
        for g in gfx_catalog_list(plan):
            for sc in g.get('screens') or []:
                key = f"{g['id']}_{sc.get('variant', 'A')}"
                if key in items:
                    it = items[key]
                    sc['review'] = {'ok': bool(it.get('ok')), 'problems': it.get('problems') or [], 'fix': it.get('fix', '')}
                    n += 1
        if dr.get('summary'):
            plan.setdefault('mockups', {})['design_summary'] = dr['summary']
        write_json(pp, plan)
    bad = sum(1 for i in items.values() if not i.get('ok'))
    print(f'замечания дизайна записаны: экранов {n} · с проблемами {bad} · сводка: {(dr.get("summary") or "")[:120]}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--print-call', action='store_true')
    ap.add_argument('--task', default='structure', choices=['structure', 'design_review', 'both'])
    ap.add_argument('--contact-sheet', action='store_true')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--apply-design', action='store_true')
    a = ap.parse_args()
    if a.contact_sheet:
        contact_sheet()
    if a.apply:
        apply_structure()
    if a.apply_design:
        apply_design()
    if a.print_call:
        print_call(a.task)
    if not (a.contact_sheet or a.apply or a.apply_design or a.print_call):
        if STRUCTURE.exists():
            apply_structure()
        else:
            print('облачный проход ещё не делался — запусти в основной сессии:')
            print_call('structure')


if __name__ == '__main__':
    main()
