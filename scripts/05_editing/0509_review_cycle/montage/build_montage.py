#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_montage.py — монтажный лист из исходников по ПОСЛОВНЫМ таймкодам (режим montage_tz).

Целевой порядок сборки (montage_plan.json, docs/contracts.md §8) превращается в список склеек:
  tc_in  = начало первого слова куска
  tc_out = конец последнего слова + min(зазор до следующего слова, 0,3 с)
Для каждой склейки считается файл-источник и смещение внутри него, кто в кадре (по большинству
слов — карта `speakers` карточки: {"Speaker 1": "A · Дарья"}), паузы ≥0,7 с внутри куска,
пересечение стыка клипов. Экраны графики получают таймкод в ЧИСТОВИКЕ.

Границы задаются якорями (подсказка_сек, "слово"): берётся ближайшее к подсказке вхождение
слова — правка на полсекунды не ломает склейку. Логика якорей — как в первом проекте (YTEVO02).

Пути — из карточки фильма (YTAI_CARD / YTAI_PROJECT_DIR): `words`, `clips`, `speakers`, `plan_file`.
План сцены может перебивать words/clips/speakers своими ключами (вторая камера).

  python3 build_montage.py                         # план карточки (+ все сцены из plan.scenes) → montage.json
  python3 build_montage.py --plan montage_plan_cam2.json --out montage_cam2.json
  python3 build_montage.py --plan-from-legacy examples/ytevo02/build_montage.py \\
        [--legacy-mockups …/build_mockups.py] [--legacy-html …/build_structure_html.py] [--scene cam2]
      → одноразовый конвертер: PIECES/CLIPS/CAM/GFX легаси-скрипта → montage_plan.json,
        карточка получает clips/speakers/plan_file; экраны мокапов и тексты страницы — в план.

Выход montage.json: schema "ytai-montage-v1", ключи как в эталоне examples/ytevo02/montage.golden.json.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mt_common import (P, REVIEW_DIR, GAP_MIN, GAP_KEEP, PAD, anchor, tc, load_words,  # noqa: E402
                       plan_clips, plan_words, clip_at, clips_total, speakers_map,
                       gfx_catalog_dict, load_plan, plan_path, scene_plans, write_json)

SCHEMA = 'ytai-montage-v1'
PLAN_SCHEMA = 'ytai-montage-plan-v1'


# ---------------- сборка ----------------
def build(plan, ws, clips, cam):
    """План → данные montage.json. Возвращает (data, errors)."""
    errors = []
    gfx_cat = gfx_catalog_dict(plan)
    cursor = 0.0            # позиция в чистовике
    trimmed_cursor = 0.0    # то же после подрезки пауз
    pieces_out = []
    for p in plan['pieces']:
        parts_out, piece_start, piece_start_tr = [], cursor, trimmed_cursor
        spoken_ranges = []
        for part in p['parts']:
            if part[0] in ('gfx', 'hold'):
                dur = float(part[2])
                parts_out.append({'kind': part[0], 'ref': part[1], 'dur': dur,
                                  'dst_in': cursor, 'dst_out': cursor + dur})
                cursor += dur
                trimmed_cursor += dur
                continue
            i0 = anchor(ws, float(part[1][0]), part[1][1], 'in', errors)
            i1 = anchor(ws, float(part[2][0]), part[2][1], 'out', errors)
            if i1 < i0:
                raise SystemExit(f"{p['id']}: конец раньше начала")
            s_in = ws[i0]['s']
            gap_next = ws[i1 + 1]['s'] - ws[i1]['e'] if i1 + 1 < len(ws) else PAD
            s_out = ws[i1]['e'] + max(0.0, min(gap_next, PAD))
            seg = ws[i0:i1 + 1]
            sp = {}
            for w in seg:
                sp[w['sp']] = sp.get(w['sp'], 0) + 1
            major = max(sp, key=sp.get)
            gaps = []
            for a, b in zip(seg, seg[1:]):
                g = b['s'] - a['e']
                if g >= GAP_MIN:
                    gaps.append({'at': a['e'], 'dur': round(g, 2), 'after': a['w']})
            trim = sum(g['dur'] - GAP_KEEP for g in gaps)
            f_in, o_in = clip_at(clips, s_in)
            f_out, o_out = clip_at(clips, s_out)
            crosses = [c[1] for c in clips[1:] if s_in < c[1] < s_out]
            dur = s_out - s_in
            parts_out.append({
                'kind': 'say', 'src_in': round(s_in, 3), 'src_out': round(s_out, 3),
                'dur': round(dur, 3), 'dst_in': round(cursor, 3), 'dst_out': round(cursor + dur, 3),
                'file_in': f_in, 'off_in': round(o_in, 3), 'file_out': f_out, 'off_out': round(o_out, 3),
                'crosses_clip': [round(c, 2) for c in crosses],
                'camera': cam.get(major, major), 'speaker': major,
                'words': len(seg), 'first': ' '.join(w['w'] for w in seg[:6]),
                'last': ' '.join(w['w'] for w in seg[-5:]),
                'text': ' '.join(w['w'] for w in seg),
                'gaps': gaps, 'trim_est': round(trim, 2)})
            spoken_ranges.append((s_in, s_out, cursor))
            cursor += dur
            trimmed_cursor += dur - trim
        gfx_out = []
        for gid, (hint, word) in p.get('gfx', []):
            i = anchor(ws, float(hint), word, 'in', errors)
            t_src = ws[i]['s']
            dst = None
            for a, b, c0 in spoken_ranges:
                if a - 0.01 <= t_src <= b + 0.01:
                    dst = c0 + (t_src - a)
                    break
            kind, title, place = gfx_cat[gid]
            gfx_out.append({'id': gid, 'src': round(t_src, 3), 'dst': round(dst, 3) if dst is not None else None,
                            'on_word': ws[i]['w'], 'kind': kind, 'title': title, 'place': place})
        for part in parts_out:
            if part['kind'] == 'gfx':
                kind, title, place = gfx_cat[part['ref']]
                gfx_out.append({'id': part['ref'], 'src': None, 'dst': round(part['dst_in'], 3),
                                'on_word': None, 'kind': kind, 'title': title, 'place': place,
                                'insert': part['dur']})
        gfx_out.sort(key=lambda g: g['dst'] if g['dst'] is not None else 1e9)
        pieces_out.append({**{k: v for k, v in p.items() if k not in ('parts', 'gfx')},
                           'dst_in': round(piece_start, 3), 'dst_out': round(cursor, 3),
                           'dur': round(cursor - piece_start, 3),
                           'dur_trimmed': round(trimmed_cursor - piece_start_tr, 3),
                           'parts': parts_out, 'gfx': gfx_out})
    total, total_tr = cursor, trimmed_cursor
    n_cuts = sum(1 for p in pieces_out for x in p['parts'] if x['kind'] == 'say')
    n_gaps = sum(len(x.get('gaps', [])) for p in pieces_out for x in p['parts'])
    gfx_ids = sorted({g['id'] for p in pieces_out for g in p['gfx']})
    data = {'schema': SCHEMA}
    if plan.get('scene'):
        data['scene'] = plan['scene']
    data.update({'total': round(total, 2), 'total_trimmed': round(total_tr, 2),
                 'source_total': clips_total(clips), 'pieces': pieces_out, 'gfx_catalog': gfx_cat,
                 'gfx_used': gfx_ids, 'n_say_parts': n_cuts, 'n_gaps': n_gaps})
    return data, errors


def print_table(data, out_path):
    for p in data['pieces']:
        print(f"{p['id']} {tc(p['dst_in'], False)}–{tc(p['dst_out'], False)} "
              f"{p['dur']:5.1f}s → {p['dur_trimmed']:5.1f}s  [{p.get('act', '')}] {p['title']}")
        for x in p['parts']:
            if x['kind'] == 'say':
                flag = f"  ⚠ стык {x['crosses_clip']}" if x['crosses_clip'] else ''
                print(f"     {tc(x['src_in'])}–{tc(x['src_out'])} {x['camera']:<14} "
                      f"{x['file_in']}+{tc(x['off_in'])}  пауз {len(x['gaps'])}{flag}")
                print(f"        «{x['first']} … {x['last']}»")
            else:
                print(f"     [{x['kind']}] {x['ref']} {x['dur']} с")
        for g in p['gfx']:
            print(f"     ▣ {g['id']} @ {tc(g['dst'], False) if g['dst'] is not None else '—'} "
                  f"на «{g['on_word'] or 'вставка'}» — {g['title']}")
    print(f"\nИТОГО: {tc(data['total'], False)} до подрезки пауз · ~{tc(data['total_trimmed'], False)} после "
          f"· склеек речи {data['n_say_parts']} · пауз ≥{GAP_MIN} с: {data['n_gaps']} · экранов {len(data['gfx_used'])}")
    print(f'→ {out_path}')


def build_plan_file(plan_file, out_name=None, quiet=False):
    plan = load_plan(plan_file)
    words_path = plan_words(plan)
    if not words_path.exists():
        raise SystemExit(f'нет транскрипта {words_path} (ключ words карточки/плана)')
    ws = load_words(words_path)
    clips = plan_clips(plan)
    cam = speakers_map(plan)
    data, errors = build(plan, ws, clips, cam)
    if errors:
        print('\n'.join(errors))
        raise SystemExit(f'{len(errors)} якорей не найдено — поправить план {plan_file}')
    out = REVIEW_DIR / (out_name or plan.get('out') or 'montage.json')
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    if not quiet:
        print_table(data, out)
    else:
        print(f"{out.name}: {tc(data['total'], False)} · кусков {len(data['pieces'])} · склеек {data['n_say_parts']} → {out}")
    return data


# ---------------- конвертер из легаси-скрипта ----------------
def exec_legacy(path):
    """Выполнить модуль легаси с подменённым BASE: константы получаем, ничего не запускается."""
    src = Path(path).read_text(encoding='utf-8')
    src = re.sub(r'^BASE\s*=\s*Path\([^\n]*\)', 'BASE = Path("/nonexistent_legacy_base")', src, flags=re.M)
    src = re.sub(r'^(SRC|SETUP)\s*=\s*Path\("/Volumes[^\n]*\)', r'\1 = Path("/nonexistent_legacy_base")', src, flags=re.M)
    ns = {'__name__': '__legacy__', '__file__': str(path)}
    sys.path.insert(0, str(Path.home() / 'YTAI/scripts/999_extra/infographic'))
    exec(compile(src, str(path), 'exec'), ns)
    return ns, src


def _jsonable(v):
    if isinstance(v, tuple):
        return [_jsonable(x) for x in v]
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, Path):
        return v.name
    return v


def pieces_from_legacy(PIECES):
    out = []
    for p in PIECES:
        q = {k: _jsonable(v) for k, v in p.items()}
        out.append(q)
    return out


def catalog_from_legacy(GFX):
    return [{'id': gid, 'kind': v[0], 'title': v[1], 'place': v[2]} for gid, v in GFX.items()]


def clips_from_legacy(CLIPS):
    return [{'file': n, 'dur': round(float(b) - float(a), 3)} for n, a, b in CLIPS]


def screens_from_legacy_mockups(path, catalogs, add_missing=False):
    """SCREENS/CLIENT_MAP/BG_* легаси build_mockups.py → экраны в каталоги планов (html-тело + тема).
    Плашки, собранные типовыми хелперами (lower_third/council_title), распознаются и хранятся как
    layout+text — если раскладка mockup_layouts воспроизводит тот же HTML побайтно.
    Экран, чьего id нет ни в одном каталоге: add_missing=False — пропустить (он из другой сцены),
    True — завести запись в последнем (сценарном) каталоге."""
    ns, src = exec_legacy(path)
    try:
        from mockup_layouts import recognize  # noqa: WPS433
    except Exception:
        recognize = None
    by_id = {}
    for cat in catalogs:
        for g in cat:
            by_id.setdefault(g['id'], g)      # общий экран — у первого (главного) каталога
    n_attached, missing, skipped = 0, [], []
    for gid, var, title, fn in ns.get('SCREENS', []):
        body, cls = fn()
        entry = {'variant': var, 'title': title, 'theme': cls}
        rec = recognize(body) if recognize else None
        if rec:
            entry.update(rec)
        else:
            entry['html'] = body
        g = by_id.get(gid)
        if g is None:
            if not add_missing:
                skipped.append(gid)           # экран другой сцены — прикрепится при конверсии её плана
                continue
            g = {'id': gid, 'kind': 'new', 'title': title, 'place': 'overlay' if cls == 'alpha' else 'full'}
            catalogs[-1].append(g)
            by_id[gid] = g
            missing.append(gid)
        scr = [s for s in g.get('screens') or [] if s.get('variant') != var]   # тот же вариант — заменить
        scr.append(entry)
        g['screens'] = scr
        n_attached += 1
    if skipped:
        print(f'экраны не из этого каталога (пропущены, ждут план своей сцены): {sorted(set(skipped))}')
    for gid, (fname, title) in (ns.get('CLIENT_MAP') or {}).items():
        g = by_id.get(gid)
        if g is None:
            if not add_missing:
                continue
            g = {'id': gid, 'kind': 'client', 'title': title, 'place': 'full'}
            catalogs[-1].append(g)
            by_id[gid] = g
        g['kind'] = 'client'
        g['file'] = fname
    mock = {}
    if ns.get('BG_FRAME') is not None:
        mock['bg_frame'] = Path(ns['BG_FRAME']).name
    if ns.get('BG_OVERRIDE'):
        mock['bg_override'] = {k: Path(v).name for k, v in ns['BG_OVERRIDE'].items()}
    if ns.get('PUNY_URL'):
        mock['qr_url'] = ns['PUNY_URL']
    m = re.search(r'<div class="draft">(.*?)</div>', ns.get('DRAFT', ''))
    if m:
        mock['draft_badge'] = m.group(1)
    if ns.get('COUNCILS'):
        mock['lists'] = {'councils': _jsonable(ns['COUNCILS'])}
    return mock, n_attached, missing


def _between(src, a, b):
    i = src.find(a)
    if i < 0:
        return None
    j = src.find(b, i + len(a))
    if j < 0:
        return None
    return src[i + len(a):j].replace('{{', '{').replace('}}', '}').strip()


def page_from_legacy_html(path):
    """Константы и тексты легаси build_structure_html.py → блок page плана (без кода)."""
    ns, src = exec_legacy(path)
    page = {}
    if ns.get('SPEAKERS'):
        page['speakers'] = {k: {'name': v[0], 'note': v[2]} for k, v in ns['SPEAKERS'].items()}
    meta = {}
    for key in ('CLIPS', 'CLIPS2'):
        for row in ns.get(key) or []:
            if len(row) >= 6:
                meta[row[0]] = {'rec_utc': row[4], 'size': row[5]}
    if meta:
        page['clips_meta'] = meta
    for key, name in (('DEVIATIONS', 'deviations'), ('RECOMMEND', 'recommend'), ('FINDING_TAGS', 'finding_tags'),
                      ('FINDING_SKIP', 'finding_skip'), ('STORY_REC', 'story_variant'), ('LINKS_BLOCK', 'links_html'),
                      ('SEAM_NOTE', 'seam_note'), ('SCENE2_NOTE', 'scene2_note')):
        if ns.get(key) is not None:
            page[name] = _jsonable(ns[key])
    chapters = _jsonable(ns.get('CHAPTERS') or [])
    chapters2 = _jsonable(ns.get('CHAPTERS2') or [])
    # тексты, зашитые в f-строку main(): вынимаем между маркерами
    grabs = {
        'h1': ('<h1>', '</h1>'),
        'hero_tags': ('<div class="tags">', '</div>'),
        'montage_note': ('<div class="sec" id="montage">Структура чистовика — монтажный лист</div>\n  ', '\n  {build_montage(mont)}'),
        'voices_note': ('<div class="sp-grid">{spk_rows}{spk2}</div>\n  ', '\n\n  <div class="sec" id="blocks">'),
        'blocks_note': ('<div class="sec" id="blocks">Блоки исходника — диагноз</div>\n  ', '\n  {build_blocks(canon, viz_by_n)}'),
        'style_html': ('<div class="sec" id="style">Визуальный язык клиента</div>\n  ', '\n\n  {build_issues('),
        'transcript_note': ('<div class="sec" id="transcript">Полная транскрибация по ролям</div>\n  ', '\n  <div class="tr-wrap">'),
        'clips_note2': ('<div class="note n-info" style="margin-top:12px"><b>Вторая сцена', '</div>'),
        'foot': ('<div class="foot">', '</div>'),
        'gallery_note': ('<div class="sec" id="screens">Экраны графики — {screens} шт.</div>\n  ', '\n  {build_gallery('),
    }
    for k, (a, b) in grabs.items():
        v = _between(src, a, b)
        if v:
            page[k] = v
    if 'clips_note2' in page:
        page['clips_note2'] = '<b>Вторая сцена' + page['clips_note2']
    if 'hero_tags' in page:
        page['hero_tags'] = [re.sub(r'<[^>]+>', '', x).strip() for x in re.findall(r'<span>(.*?)</span>', page['hero_tags'])]
        page['hero_tags'] = [t for t in page['hero_tags'] if '{' not in t]
    if 'gallery_note' in page:
        page['gallery_note'] = re.sub(r'\{[^}]*\}', '', page['gallery_note'])
    # правило варианта «в куске NN показывать B» — было в коде pick_variant(): want = "B" if (gid == "G08" and pid == "16")
    for gid, pid in re.findall(r'"(\w+)" and pid == "(\w+)"', src):
        page.setdefault('story_variant', {})[f'{gid}@{pid}'] = 'B'
    m = re.search(r'srcd = \("(.*?)" if main\["kind"\] == "client"\s*else "(.*?)"\)', src, re.S)
    if m:
        page['client_source_label'], page['draft_label'] = m.group(1), m.group(2)
    return page, chapters, chapters2


def convert_legacy(a):
    ns, src = exec_legacy(a.plan_from_legacy)
    for k in ('PIECES', 'CLIPS', 'CAM', 'GFX'):
        if k not in ns:
            raise SystemExit(f'{a.plan_from_legacy}: нет константы {k}')
    plan = {'schema': PLAN_SCHEMA}
    m = re.search(r'"scene":\s*"([^"]+)"', src)
    if m:
        plan['scene'] = m.group(1)
    out_name = Path(ns['OUT']).name if ns.get('OUT') is not None else ('montage.json' if not a.scene else f'montage_{a.scene}.json')
    card_path = Path(P.CARD_PATH)
    card = json.loads(card_path.read_text(encoding='utf-8'))
    clips = clips_from_legacy(ns['CLIPS'])
    if a.scene:
        # сцена со своим транскриптом/клипами/спикерами — всё в её плане, карточка не трогается
        words_name = Path(ns['WORDS']).name if ns.get('WORDS') is not None else None
        if words_name:
            wp = Path(P.WORDS).parent / words_name
            plan['words'] = str(Path(wp).resolve().relative_to(REVIEW_DIR.resolve())) if str(wp).startswith(str(REVIEW_DIR)) \
                else str(Path(__import__('os').path.relpath(wp, REVIEW_DIR)))
        plan['clips'] = clips
        plan['speakers'] = dict(ns['CAM'])
        plan['out'] = out_name
        plan_name = a.plan_out or f'montage_plan_{a.scene}.json'
    else:
        plan_name = a.plan_out or P.get('plan_file', 'montage_plan.json')
        card['clips'] = clips
        card['speakers'] = dict(ns['CAM'])
        card['plan_file'] = plan_name
        card_path.write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'карточка обновлена: clips {len(clips)} · speakers {len(card["speakers"])} · plan_file {plan_name}')
    plan['pieces'] = pieces_from_legacy(ns['PIECES'])
    plan['gfx_catalog'] = catalog_from_legacy(ns['GFX'])
    if a.legacy_mockups:
        catalogs = [plan['gfx_catalog']]
        main_plan = None
        if a.scene:
            mp = plan_path()
            if mp.exists():
                main_plan = json.loads(mp.read_text(encoding='utf-8'))
                catalogs.insert(0, main_plan['gfx_catalog'])   # общие экраны уже у главного плана
        mock, n_att, missing = screens_from_legacy_mockups(a.legacy_mockups, catalogs, add_missing=bool(a.scene))
        target = main_plan if main_plan is not None else plan
        target.setdefault('mockups', {}).update(mock)
        if main_plan is not None:
            write_json(plan_path(), main_plan)
        print(f'экраны мокапов прикреплены: {n_att} · заведены в каталоге сцены: {missing or "—"}')
    if a.legacy_html:
        page, chapters, chapters2 = page_from_legacy_html(a.legacy_html)
        if a.scene:
            mp = plan_path()
            main_plan = json.loads(mp.read_text(encoding='utf-8')) if mp.exists() else None
            plan['chapters'] = chapters2
            if main_plan is not None:
                sc = {'plan': plan_name, 'out': out_name, 'title': plan.get('scene', a.scene),
                      'note': page.get('scene2_note', ''), 'clips_note': page.get('clips_note2', ''),
                      'frames_sub': f'story_frames_{a.scene}'}
                main_plan['scenes'] = [s for s in main_plan.get('scenes', []) if s.get('plan') != plan_name] + [sc]
                write_json(mp, main_plan)
        else:
            plan['chapters'] = chapters
            page.pop('scene2_note', None)
            page.pop('clips_note2', None)
            plan['page'] = page
    out = REVIEW_DIR / plan_name
    write_json(out, plan)
    print(f'план записан: {out} · кусков {len(plan["pieces"])} · экранов в каталоге {len(plan["gfx_catalog"])}')
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plan', default=None, help='план (относительно папки карточки); по умолчанию plan_file карточки')
    ap.add_argument('--out', default=None, help='имя выходного montage.json (по умолчанию из плана / montage.json)')
    ap.add_argument('--no-scenes', action='store_true', help='не собирать дополнительные сцены из plan.scenes')
    ap.add_argument('--quiet', action='store_true', help='без таблицы, одна строка итога')
    ap.add_argument('--plan-from-legacy', default=None, metavar='BUILD_MONTAGE_PY',
                    help='конвертер: PIECES/CLIPS/CAM/GFX легаси-скрипта → план + карточка')
    ap.add_argument('--legacy-mockups', default=None, metavar='BUILD_MOCKUPS_PY', help='+ экраны легаси build_mockups.py → каталог')
    ap.add_argument('--legacy-html', default=None, metavar='BUILD_STRUCTURE_HTML_PY', help='+ тексты легаси страницы → plan.page')
    ap.add_argument('--scene', default=None, help='конвертер: это дополнительная сцена (напр. cam2) — свой план и montage_<scene>.json')
    ap.add_argument('--plan-out', default=None, help='конвертер: имя файла плана')
    a = ap.parse_args()

    if a.plan_from_legacy:
        convert_legacy(a)
        return
    if a.plan:
        build_plan_file(a.plan, a.out, a.quiet)
        return
    data = build_plan_file(P.get('plan_file', 'montage_plan.json'), a.out, a.quiet)
    if not a.no_scenes:
        plan = load_plan()
        for path, sc in scene_plans(plan):
            if path.exists():
                print(f'\n— сцена {sc.get("title") or path.name} —')
                build_plan_file(path, sc.get('out'), quiet=True)
            else:
                print(f'⚠️ сцена {path.name}: плана нет — пропуск')


if __name__ == '__main__':
    main()
