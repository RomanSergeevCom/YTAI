#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack.py — пакеты для облачного прохода (wf_judge.js), 0 токенов.

usage:
    pack.py                 J-пакеты судей (текст, без картинок), идемпотентно, + V из need_frame-кандидатов роутера;
                            если ВСЕ J done — заодно F/V/S по их ответам (то же, что --facts --crops --skeptic)
    pack.py --facts         F_<sha8>.json: утверждения на веб-проверку (facts_to_check судей + локальные)
    pack.py --crops         V_<sha8>.json + кропы ≤800 px (или контактные листы 4×4) из need_frames судей
    pack.py --skeptic       S_<sha8>.json: подтверждённые вердикты + новые находки (+F/V) без вердикта скептика
    pack.py --pending       напечатать id батчей со статусом pending
    pack.py --print-call    напечатать (ТОЛЬКО в stdout) готовый вызов Workflow({...}) для сессии

Вход (карточка фильма → P.WORK): screens_v6.json, vlm_v6.jsonl, llm_v6.json, probes.jsonl?, candidates.json?
(без него — candidates[] пустые и предупреждение в stderr), транскрипт words.json; pravki → existing_tz.
Выход: P.CLOUD/in/J_<nn>_<sha8>.json (≤50 экранов, ≤60 кандидатов), in/existing_tz.txt, state.json
{run_ids, batches:{id:{status, kind, in, out, …}}}. sha8 = sha1 блока screens (шапка film/rules/existing_tz
в хеш не входит — иначе каждое новое ТЗ переупаковывало бы весь фильм). Экран, уже покрытый done-батчем
с тем же хешем, второй раз не пакуется; done-батчи не трогаются.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

from cloudlib import (P, W6, IN, OUT, CROPS, WF_JUDGE, KINDS, ensure_dirs, warn, load_json, save_json, sha8,  # noqa: E402
                      norm_text, tc, state_load, state_save, batch_kind, pending_ids, done_batches, batch_in_path,
                      batch_out_path, screens_list, screens_map, vlm_map, llm_map, probes_map, vo, candidates_load,
                      existing_tz_lines, film, rules, sources, derive_findings, needs_skeptic, line_bbox, match_line,
                      union_bbox, fid_fact, qid, _clip)

MAX_SCREENS = 50
MAX_CANDS = 60
MAX_KB = 112                 # текст экранов одного пакета (шапка сверху ≈ 6–8 КБ → итог ≤ 120 КБ)
NUM_RE = re.compile(r'\$?\d[\d\s.,]*\d%?|\d%?')
FOREIGN_RE = re.compile(r'shutterstock|getty|alamy|istock|depositphotos|adobe stock|©|\bwww\.|https?://|'
                        r'\.com\b|\bsource:|\bphoto:|\bcredit|watermark|образец|sample', re.I)
LAT = re.compile(r'[A-Za-z]')
CYR = re.compile(r'[А-Яа-яЁё]')


# ── экраны → записи пакета ─────────────────────────────────────────────────
def _nums(s):
    out = []
    for m in NUM_RE.finditer(s or ''):
        t = re.sub(r'\s+', ' ', m.group(0)).strip(' .,')
        if t and t not in out:
            out.append(t)
    return out[:8]


def _short(v, n=120):
    return _clip(v, n)


def _aslist(v):
    """Поля Qwen приходят то списком, то строкой, то null."""
    if isinstance(v, list):
        return [str(x) for x in v if x not in (None, '')]
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    return []


def build_screen_recs(ids=None):
    """Записи экранов для J-пакета (контракт §7). ids — подмножество экранов (для добора покрытия)."""
    ev = screens_list()
    vlm, llm, probes = vlm_map(), llm_map(), probes_map()
    cands = candidates_load(quiet=ids is not None) or []
    by_screen = {}
    for c in cands:
        if c.get('route') == 'cloud':
            by_screen.setdefault(c.get('screen_id'), []).append(c)
    seen_text = {}
    recs = []
    for e in ev:
        sid = e['id']
        text = e.get('text_best') or ''
        key = norm_text(text)
        dup = seen_text.get(key) if key else None
        if key and key not in seen_text:
            seen_text[key] = sid
        if ids is not None and sid not in ids:
            continue
        l = llm.get(sid, {})
        v = vlm.get(sid, {})
        voice = vo(e['t0'], e['t1'])
        lat, cyr = len(LAT.findall(text)), len(CYR.findall(text))
        pf = probes.get(sid, {}).get('foreign')
        if pf is None:
            pf = bool(FOREIGN_RE.search(text))
        flags = {
            'typo_susp': [_short(x) for x in (_aslist(l.get('typos')) + _aslist(l.get('grammar')))[:6]],
            'latin_ratio': round(lat / (lat + cyr), 2) if lat + cyr else 0.0,
            'numbers_screen': _nums(text), 'numbers_vo': _nums(voice),
            'probe_foreign': pf, 'dup_of': dup,
        }
        hint = {}
        if _aslist(l.get('currency_numbers')):
            hint['currency'] = [_short(x) for x in _aslist(l['currency_numbers'])[:4]]
        if _aslist(l.get('english_only')):
            hint['english'] = [_short(x) for x in _aslist(l['english_only'])[:4]]
        if _aslist(l.get('facts_to_check')):
            hint['facts'] = [_short(x) for x in _aslist(l['facts_to_check'])[:4]]
        if _aslist(l.get('mismatch_with_vo')):
            hint['mismatch'] = _short(' '.join(_aslist(l['mismatch_with_vo'])), 220)
        if hint:
            flags['llm'] = hint
        rec = {
            'id': sid, 'tc': e.get('tc'), 't0': e.get('t0'), 't1': e.get('t1'), 'chapter': e.get('chapter'),
            'frame': e.get('best_frame'),
            'ocr_lines': [{'i': i, 't': ln.get('t', '')} for i, ln in enumerate(e.get('lines_best') or [])],
            'vlm_text': v.get('vlm_text'), 'vlm_desc': _short(v.get('vlm_desc'), 300),
            'vo': voice, 'local_flags': flags,
            'candidates': [{'cand_id': c['cand_id'], 'kind': c.get('kind'), 'text': c.get('on_screen_text'),
                            'line_idx': c.get('line_idx'), 'fix_local': c.get('fix_local'),
                            'route_reason': _short(c.get('route_reason'), 200), 'signals': c.get('signals') or []}
                           for c in by_screen.get(sid, [])],
        }
        last = (e.get('texts_all') or [''])[-1]
        if last and norm_text(last) != key:
            rec['ocr_last'] = _short(last, 300)
        recs.append(rec)
    return recs


def rec_hash(rec):
    return sha8(rec)


def chunk(recs, max_screens=MAX_SCREENS, max_cands=MAX_CANDS):
    """Последовательные куски: ≤max_screens экранов и ≤max_cands кандидатов, размер выровнен."""
    if not recs:
        return []
    n_packs = max(1, math.ceil(len(recs) / max_screens))
    target = math.ceil(len(recs) / n_packs)
    chunks, cur, nc = [], [], 0
    for r in recs:
        k = len(r.get('candidates') or [])
        if cur and (len(cur) >= target or nc + k > max_cands):
            chunks.append(cur)
            cur, nc = [], 0
        cur.append(r)
        nc += k
    if cur:
        chunks.append(cur)
    # байтовый потолок: пакет > MAX_KB КБ (текст экранов) делим пополам, пока не влезет
    out = []
    for part in chunks:
        stack = [part]
        while stack:
            p = stack.pop(0)
            if len(p) > 1 and len(json.dumps(p, ensure_ascii=False)) > MAX_KB * 1024:
                h = len(p) // 2
                stack = [p[:h], p[h:]] + stack
            else:
                out.append(p)
    return out


def header(kind):
    cands = candidates_load(quiet=True) or []
    summary = {'auto_confirmed': sum(1 for c in cands if c.get('route') == 'auto_confirm'),
               'dropped': sum(1 for c in cands if c.get('route') == 'drop'),
               'cloud': sum(1 for c in cands if c.get('route') == 'cloud')}
    return {'kind': kind, 'film': film(), 'rules': rules(), 'existing_tz': existing_tz_lines(), 'summary': summary}


def next_nn(st):
    nn = 0
    for bid in st['batches']:
        m = re.match(r'^J_(\d+)b?_', bid)
        if m:
            nn = max(nn, int(m.group(1)))
    return nn + 1


def write_existing_tz():
    ensure_dirs()
    p = IN / 'existing_tz.txt'
    p.write_text('\n'.join(existing_tz_lines()) + '\n', encoding='utf-8')
    return p


def build_j_packs(st, ids=None, tag=None, quiet=False):
    """J-пакеты для экранов, не покрытых done/pending батчами с тем же хешем.

    ids — подмножество экранов (добор покрытия из collect.py), tag — номер исходного пакета ('03' → J_03b_…).
    Полная сборка (ids=None) снимает pending-пакеты, чей экран изменился или исчез; частичная — только
    те, чей экран из подмножества изменился (остальные pending не трогаем: их экранов тут нет).
    """
    ensure_dirs()
    full = ids is None
    recs = build_screen_recs() if full else build_screen_recs(set(ids))
    current = {r['id']: rec_hash(r) for r in recs}
    covered = {}
    stale = []
    for bid, b in list(st['batches'].items()):
        if batch_kind(bid, b) != 'J':
            continue
        scr = b.get('screens') or {}
        if b.get('status') == 'done':
            covered.update(scr)
            continue
        changed = (any(current.get(sid) != h for sid, h in scr.items()) if full
                   else any(sid in current and current[sid] != h for sid, h in scr.items()))
        if changed:
            stale.append(bid)
            del st['batches'][bid]
        else:
            covered.update(scr)
            hdr = header('J')
            pk = load_json(batch_in_path(bid, b), None)
            if isinstance(pk, dict):
                pk.update(hdr)
                save_json(batch_in_path(bid, b), pk)
    todo = [r for r in recs if covered.get(r['id']) != current[r['id']]]
    new_ids = []
    if todo:
        nn = next_nn(st)
        for i, part in enumerate(chunk(todo)):
            sha = sha8(part)
            # добор покрытия: J_03b_…, J_03c_… (tag = номер исходного пакета); иначе — следующие номера
            label = f'{tag}{"bcdefgh"[i]}' if tag else f'{nn + i:02d}'
            bid = f'J_{label}_{sha}'
            pack = {'batch_id': bid, 'sha8': sha, **header('J'),
                    'n_screens': len(part), 'n_candidates': sum(len(r['candidates']) for r in part),
                    'range_tc': f'{part[0]["tc"]}–{part[-1]["tc"]}',
                    'hires_note': 'кадры не приложены намеренно: суди по тексту; сомнение в буквах → need_frames',
                    'screens': part}
            p = IN / f'{bid}.json'
            save_json(p, pack)
            st['batches'][bid] = {'status': 'pending', 'kind': 'J', 'in': str(p), 'out': str(OUT / f'{bid}.json'),
                                  'n': len(part), 'sha8': sha, 'screens': {r['id']: rec_hash(r) for r in part}}
            new_ids.append(bid)
    write_existing_tz()
    if not quiet:
        if stale:
            print(f'устаревшие pending-пакеты сняты: {", ".join(stale)}')
        j_all = [b for b in st['batches'] if batch_kind(b, st['batches'][b]) == 'J']
        sizes = [(b, Path(st['batches'][b]['in']).stat().st_size // 1024) for b in new_ids if Path(st['batches'][b]['in']).exists()]
        print(f'J-пакетов: {len(j_all)} всего, новых {len(new_ids)} (экранов {len(todo)}), '
              f'покрыто раньше {len(recs) - len(todo)}/{len(recs)}'
              + (f' · размеры новых КБ: {", ".join(f"{b.split("_")[1]}={s}" for b, s in sizes)}' if sizes else ''))
    return new_ids


# ── F: факты ───────────────────────────────────────────────────────────────
def _claimlike(s):
    s = str(s or '')
    return bool(re.search(r'\d|\$|€|%|\bкарат|\bct\b', s, re.I)) and len(s) > 8


def build_facts(st, quiet=False):
    cands = {c['cand_id']: c for c in (candidates_load(quiet=True) or [])}
    llm = llm_map()
    max_claims = int(P.profile('fact_check.max_claims', 40) or 40)
    done_keys = set()
    for bid, b in done_batches(st, 'F').items():
        for it in (load_json(batch_in_path(bid, b), {}) or {}).get('items') or []:
            done_keys.add((it.get('screen_id'), norm_text(it.get('claim'))[:80]))
    for bid, b in list(st['batches'].items()):
        if batch_kind(bid, b) == 'F' and b.get('status') != 'done':
            del st['batches'][bid]
    items, keys = [], set()

    def add(sid, cid, claim, text):
        k = (sid, norm_text(claim)[:80])
        if not claim or k in keys or k in done_keys:
            return
        keys.add(k)
        items.append({'screen_id': sid, 'cand_id': cid or '', 'claim': _clip(claim, 300), 'on_screen_text': _clip(text, 200)})

    for bid, b in sorted(done_batches(st, 'J').items()):
        o = load_json(batch_out_path(bid, b), {}) or {}
        for ft in o.get('facts_to_check') or []:
            add(ft.get('screen_id'), ft.get('cand_id'), ft.get('claim'), ft.get('on_screen_text'))
        for v in o.get('verdicts') or []:
            if v.get('verdict') == 'fact_check':
                c = cands.get(v.get('cand_id'), {})
                add(v.get('screen_id') or c.get('screen_id'), v.get('cand_id'),
                    v.get('reason') or c.get('on_screen_text'), v.get('on_screen_text') or c.get('on_screen_text'))
    n_judge = len(items)
    # локальные кандидаты фактов (Qwen facts_to_check шумные): берём только «похожие на утверждение»
    # с числом И только для экранов, где на самом экране есть число — иначе это пересказ озвучки
    for sid, l in llm.items():
        if not re.search(r'\d', str(l.get('ocr') or '')):
            continue
        for s in _aslist(l.get('facts_to_check')):
            if len(items) >= max_claims:
                break
            if _claimlike(s):
                add(sid, '', s, l.get('ocr') or '')
    items = items[:max_claims]
    if not items:
        if not quiet:
            print('F: утверждений на проверку нет')
        return None
    sha = sha8(items)
    bid = f'F_{sha}'
    for i, it in enumerate(items, 1):
        it['fact_id'] = fid_fact(bid, i)
    pack = {'batch_id': bid, 'sha8': sha, 'kind': 'F', 'film': film(), 'rules': rules(), 'sources': sources(),
            'items': items}
    p = IN / f'{bid}.json'
    save_json(p, pack)
    st['batches'][bid] = {'status': 'pending', 'kind': 'F', 'in': str(p), 'out': str(OUT / f'{bid}.json'), 'n': len(items)}
    if not quiet:
        print(f'F: {bid} — {len(items)} утверждений (от судей {n_judge}, локальных {len(items) - n_judge})')
    return bid


# ── V: кропы ───────────────────────────────────────────────────────────────
def _crop(frame, bbox, dst, max_side=800):
    from PIL import Image
    im = Image.open(frame)
    W, H = im.size
    if bbox:
        x0 = bbox['x'] * W
        y0 = bbox['y'] * H
        x1 = (bbox['x'] + bbox['w']) * W
        y1 = (bbox['y'] + bbox['h']) * H
        pad = max(40.0, 0.35 * (y1 - y0))
        box = (max(0, int(x0 - pad)), max(0, int(y0 - pad)), min(W, int(x1 + pad)), min(H, int(y1 + pad)))
        if box[2] - box[0] > 20 and box[3] - box[1] > 10:
            im = im.crop(box)
    w, h = im.size
    if max(w, h) > max_side:
        k = max_side / max(w, h)
        im = im.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
    elif max(w, h) < 400:                     # мелкая строка (147×98) нечитаема глазами агента — увеличиваем до ~600
        k = min(3.0, 600 / max(w, h))
        im = im.resize((int(w * k), int(h * k)), Image.LANCZOS)
    im.convert('RGB').save(dst, 'JPEG', quality=88)
    return im.size


def _sheet(paths, labels, dst, cell=392, cols=4):
    from PIL import Image, ImageDraw, ImageFont
    rows = math.ceil(len(paths) / cols)
    sheet = Image.new('RGB', (cell * cols, cell * rows), (18, 18, 20))
    try:
        font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 22)
    except Exception:
        font = ImageFont.load_default()
    d = ImageDraw.Draw(sheet)
    for i, (p, lab) in enumerate(zip(paths, labels)):
        r, c = divmod(i, cols)
        im = Image.open(p).convert('RGB')
        k = min((cell - 16) / im.width, (cell - 44) / im.height)
        im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
        x, y = c * cell + 8, r * cell + 36
        sheet.paste(im, (x, y))
        d.rectangle((c * cell, r * cell, c * cell + cell - 1, r * cell + 30), fill=(60, 60, 70))
        d.text((c * cell + 8, r * cell + 4), lab, fill=(255, 255, 255), font=font)
    sheet.save(dst, 'JPEG', quality=86)
    return sheet.size


def build_crops(st, quiet=False):
    cands = {c['cand_id']: c for c in (candidates_load(quiet=True) or [])}
    scr = screens_map()
    done_keys = set()
    for bid, b in done_batches(st, 'V').items():
        for it in (load_json(batch_in_path(bid, b), {}) or {}).get('items') or []:
            done_keys.add((it.get('screen_id'), it.get('cand_id') or '', norm_text(it.get('what_to_look_at'))[:60]))
    for bid, b in list(st['batches'].items()):
        if batch_kind(bid, b) == 'V' and b.get('status') != 'done':
            del st['batches'][bid]
    items, keys = [], set()

    def add(sid, cid, what, text):
        k = (sid, cid or '', norm_text(what)[:60])
        if not sid or sid not in scr or k in keys or k in done_keys:
            return
        keys.add(k)
        items.append({'screen_id': sid, 'cand_id': cid or '', 'tc': scr[sid].get('tc'),
                      'what_to_look_at': _clip(what or 'прочитать текст буква в букву', 300),
                      'on_screen_text': _clip(text or (cands.get(cid) or {}).get('on_screen_text') or scr[sid].get('text_best'), 200)})

    for bid, b in sorted(done_batches(st, 'J').items()):
        o = load_json(batch_out_path(bid, b), {}) or {}
        asked = set()
        for nf in o.get('need_frames') or []:
            asked.add(nf.get('cand_id') or '')
            add(nf.get('screen_id'), nf.get('cand_id'), nf.get('what_to_look_at'), nf.get('on_screen_text'))
        for v in o.get('verdicts') or []:
            if v.get('verdict') == 'need_frame' and v.get('cand_id') not in asked:
                c = cands.get(v.get('cand_id'), {})
                add(v.get('screen_id') or c.get('screen_id'), v.get('cand_id'), v.get('reason'), v.get('on_screen_text'))
    # локальный роутер сам просит глаза (need_frame / zoom_wanted у cloud-кандидата) — кроп готов уже к прогону 1
    for c in cands.values():
        if c.get('route') == 'cloud' and (c.get('need_frame') or c.get('zoom_wanted')):
            add(c.get('screen_id'), c['cand_id'],
                (c.get('route_reason') or '') + ' — прочитать буква в букву, видна ли ошибка', c.get('on_screen_text'))
    if not items:
        if not quiet:
            print('V: вопросов к кадрам нет')
        return None
    sha = sha8(items)
    bid = f'V_{sha}'
    d = CROPS / bid
    d.mkdir(parents=True, exist_ok=True)
    paths, labels = [], []
    for i, it in enumerate(items, 1):
        it['q_id'] = qid(bid, i)
        e = scr[it['screen_id']]
        c = cands.get(it['cand_id'], {})
        bb = line_bbox(e, c.get('line_idx')) if c.get('line_idx') is not None else None
        if not bb:
            li = match_line(e, it['on_screen_text'])
            bb = line_bbox(e, li) if li is not None else union_bbox(e)
        frame = W6 / 'hires' / e['best_frame']
        dst = d / f'{it["q_id"]}_{it["screen_id"]}.jpg'
        if frame.exists():
            _crop(str(frame), bb, str(dst))
            paths.append(str(dst))
            labels.append(it['q_id'])
            it['image'] = str(dst)
        else:
            it['image'] = ''
            warn(f'V: нет кадра {frame}')
    images = list(paths)
    if len(paths) > 16:
        images = []
        for k in range(0, len(paths), 16):
            sp = d / f'sheet_{k // 16 + 1:02d}.jpg'
            _sheet(paths[k:k + 16], labels[k:k + 16], str(sp))
            images.append(str(sp))
            for j, it in enumerate([x for x in items if x.get('image')][k:k + 16]):
                r, c = divmod(j, 4)
                it['image'] = str(sp)
                it['cell'] = f'ряд {r + 1}, колонка {c + 1} (подпись {it["q_id"]})'
    pack = {'batch_id': bid, 'sha8': sha, 'kind': 'V', 'film': film(), 'images': images, 'items': items,
            'note': 'открывать Read только перечисленные images; на контактном листе ячейка подписана q_id'}
    p = IN / f'{bid}.json'
    save_json(p, pack)
    st['batches'][bid] = {'status': 'pending', 'kind': 'V', 'in': str(p), 'out': str(OUT / f'{bid}.json'),
                          'n': len(items), 'images': len(images)}
    if not quiet:
        print(f'V: {bid} — {len(items)} вопросов, картинок {len(images)} ({"контактные листы" if len(paths) > 16 else "кропы"})')
    return bid


# ── S: скептик ─────────────────────────────────────────────────────────────
def skeptic_digest(findings):
    out = []
    for f in findings:
        ev = ''
        if f.get('fact'):
            ev = f"факт: {f['fact'].get('status')} · {f['fact'].get('correct_value') or ''} · {f['fact'].get('source_url') or ''}".strip(' ·')
        if f.get('crop'):
            ev = (ev + ' | ' if ev else '') + f"кроп: видно={f['crop'].get('error_visible')} · «{f['crop'].get('text_as_seen')}» · {f['crop'].get('answer')}"
        out.append({'finding_id': f['finding_id'], 'screen_id': f.get('screen_id'), 'tc': f.get('tc'),
                    'kind': f.get('kind'), 'on_screen_text': f.get('on_screen_text'), 'fix_text': f.get('fix_text'),
                    'problem': f.get('problem'), 'why': f.get('why'), 'existing_tz': f.get('existing_tz') or '',
                    'route': f.get('route'), 'evidence': _clip(ev, 400), 'vo': _clip(vo(f.get('t0') or 0, f.get('t1') or 0, 4), 240)})
    return out


def build_skeptic(st, quiet=False):
    for bid, b in list(st['batches'].items()):
        if batch_kind(bid, b) == 'S' and b.get('status') != 'done':
            del st['batches'][bid]
    findings, _x = derive_findings(st)
    todo = [f for f in findings if needs_skeptic(f)]
    if not todo:
        if not quiet:
            print('S: находок без вердикта скептика нет')
        return None
    items = skeptic_digest(todo)
    sha = sha8([it['finding_id'] for it in items])
    bid = f'S_{sha}'
    pack = {'batch_id': bid, 'sha8': sha, 'kind': 'S', 'mode': 'pack', 'film': film(), 'rules': rules(), 'items': items}
    p = IN / f'{bid}.json'
    save_json(p, pack)
    st['batches'][bid] = {'status': 'pending', 'kind': 'S', 'mode': 'pack', 'in': str(p),
                          'out': str(OUT / f'{bid}.json'), 'n': len(items)}
    if not quiet:
        print(f'S: {bid} — {len(items)} находок на скепсис')
    return bid


# ── вызов воркфлоу ─────────────────────────────────────────────────────────
def print_call(st):
    """Печатает ТОЛЬКО вызов (review.py пишет stdout в CALL.txt). Run-S регистрируется, если пакета S нет."""
    pend = {bid: st['batches'][bid] for bid in pending_ids(st)}
    packs = sorted([b for b in pend if batch_kind(b, pend[b]) == 'J'],
                   key=lambda b: (int(re.match(r'^J_(\d+)', b).group(1)), b))
    f_pack = next((b for b in pend if batch_kind(b, pend[b]) == 'F'), None)
    v_pack = next((b for b in pend if batch_kind(b, pend[b]) == 'V'), None)
    s_pack = next((b for b in pend if batch_kind(b, pend[b]) == 'S' and pend[b].get('mode') == 'pack'), None)
    covers = sorted(packs + [x for x in (f_pack, v_pack, s_pack) if x])
    s_run = next((b for b in pend if batch_kind(b, pend[b]) == 'S' and pend[b].get('mode') == 'run'), None)
    if s_pack:
        if s_run:
            del st['batches'][s_run]
        skeptic = {'batch_id': s_pack, 'file': pend[s_pack]['in']}
    else:
        want = f'S_{sha8(covers + ["run"])}'
        if s_run and s_run != want:
            del st['batches'][s_run]
            s_run = None
        if not covers:
            print('# нечего запускать: pending-батчей нет (pack.py → J; после collect → F/V/S)')
            return
        if not s_run:
            st['batches'][want] = {'status': 'pending', 'kind': 'S', 'mode': 'run', 'in': None,
                                   'out': str(OUT / f'{want}.json'), 'covers': covers}
        skeptic = {'batch_id': want, 'file': None}
    state_save(st)
    ensure_dirs()
    call = {'scriptPath': str(WF_JUDGE), 'args': {
        'packs': [{'batch_id': b, 'file': pend[b]['in']} for b in packs],
        'facts_pack': {'batch_id': f_pack, 'file': pend[f_pack]['in']} if f_pack else None,
        'crops_pack': {'batch_id': v_pack, 'file': pend[v_pack]['in']} if v_pack else None,
        'skeptic': skeptic,
        'film': film(), 'rules': rules(), 'sources': sources(),
        'out_dir': str(OUT), 'existing_tz_file': str(write_existing_tz()),
        'project': P.CODE, 'concurrency': 4}}
    print('Workflow(' + json.dumps(call, ensure_ascii=False, indent=1) + ')')


def main():
    global MAX_SCREENS, MAX_CANDS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--facts', action='store_true')
    ap.add_argument('--crops', action='store_true')
    ap.add_argument('--skeptic', action='store_true')
    ap.add_argument('--pending', action='store_true')
    ap.add_argument('--print-call', action='store_true')
    ap.add_argument('--max-screens', type=int, default=MAX_SCREENS)
    ap.add_argument('--max-cands', type=int, default=MAX_CANDS)
    a = ap.parse_args()
    MAX_SCREENS, MAX_CANDS = a.max_screens, a.max_cands
    ensure_dirs()
    st = state_load()
    if a.pending:
        for b in pending_ids(st):
            print(b)
        return 0
    if a.print_call:
        print_call(st)
        return 0
    explicit = a.facts or a.crops or a.skeptic
    if not explicit:
        build_j_packs(st)
        j = {b: v for b, v in st['batches'].items() if batch_kind(b, v) == 'J'}
        if j and all(v.get('status') == 'done' for v in j.values()):
            print('все J done → добираю F/V/S по ответам судей')
            build_facts(st)
            build_crops(st)
            build_skeptic(st)
        else:
            build_crops(st, quiet=True)          # кропы по просьбам роутера (need_frame) — уже к прогону 1
    else:
        if a.facts:
            build_facts(st)
        if a.crops:
            build_crops(st)
        if a.skeptic:
            build_skeptic(st)
    state_save(st)
    pend = pending_ids(st)
    print(f'state: батчей {len(st["batches"])}, pending {len(pend)}' + (': ' + ', '.join(pend) if pend else '')
          + f' · {P.CODE}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
