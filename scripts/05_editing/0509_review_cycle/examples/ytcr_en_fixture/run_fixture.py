#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_fixture.py — EN-цепочка ревью на синтетической фикстуре YTCR (lang en, 29.97 fps, исключение) во ВРЕМЕННОЙ копии.

0 токенов, без моделей, без Google: s2 (пересборка инвентаря из ocr_hires.jsonl) → route_candidates → pack →
канон облачного ответа (cloud_canned.json → out/J_*, out/V_*) → collect → s8_apply_audit → terms_index →
s10_format_tz → make_infographics_v6 (HTML без chrome) → make_review_v6 → mockbuild_v6.js → дампы вкладки ТЗ,
навигатора и листа (офлайн-двойники) → проверка «нет кириллицы в поверхностях монтажёра вне текста на экране».
Репо не пишется никогда: всё во tempfile, папка удаляется (кроме --keep).

    python3 run_fixture.py            # таблица проверок, exit 0 = всё сошлось
    python3 run_fixture.py --json     # + последняя строка «ROWS [[name, ok, msg], …]» (review.py selftest)
    python3 run_fixture.py --keep     # оставить временную папку (путь в выводе)
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
STAGE = HERE.parent.parent
YTAI = STAGE.parent.parent.parent
PY = sys.executable or 'python3'
PY_LLM = YTAI / 'environment/.venv_llm/bin/python'
PY_ROUTE = str(PY_LLM) if PY_LLM.exists() else PY          # EN-словарь pyspellchecker стоит в .venv_llm
NODE = '/opt/homebrew/bin/node' if Path('/opt/homebrew/bin/node').exists() else 'node'
FPS = 30000 / 1001
CYR = re.compile(r'[А-Яа-яЁё]')
ARAB = re.compile(r'[؀-ۿ]')
QUOTED = re.compile(r'“[^”]*”|«[^»]*»|"[^"]*"')

ROWS = []


def row(name, cond, msg=''):
    ROWS.append([name, bool(cond), '' if cond else str(msg)[:220]])
    return bool(cond)


def jload(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except Exception:
        return default


def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)


class Chain:
    def __init__(self, keep=False):
        self.keep = keep
        self.tmp = Path(tempfile.mkdtemp(prefix='ytai_en_fixture_'))
        self.rv = self.tmp / 'YTCRFX_Fixture' / '00_Setup' / '05_Review'
        self.w = self.rv / 'work' / 'v1'
        self.w.mkdir(parents=True)
        (self.rv / 'pravki').mkdir()
        for side in ('drive_clips.json', 'shots_ids.json'):      # клипов пула и id кадров на Drive у фикстуры нет
            (self.rv / 'pravki' / side).write_text('{}', encoding='utf-8')
        (self.rv / 'mockups').mkdir()
        shutil.copy2(HERE / 'review_card.json', self.rv / 'review_card.json')
        shutil.copy2(HERE / 'words.json', self.rv / 'words.json')
        for f in ('ocr_hires.jsonl', 'vlm_v6.jsonl', 'llm_v6.json', 'probes.jsonl'):
            shutil.copy2(HERE / 'work' / f, self.w / f)
        self.card = jload(self.rv / 'review_card.json', {})
        env = {k: v for k, v in os.environ.items() if not k.startswith('YTAI_') and k != 'TZ_TAB'}
        env.update({'YTAI_CARD': str(self.rv / 'review_card.json'), 'YTAI_CTL_DIR': str(self.tmp / 'ctl'),
                    'PYTHONHASHSEED': '0', 'PYTHONUNBUFFERED': '1', 'TZ_TAB': str(self.card.get('tab_title') or ''),
                    'PATH': '/opt/homebrew/bin:/usr/local/bin:' + env.get('PATH', '')})
        self.env = env
        self.log = []

    def run(self, name, argv, extra=None, timeout=300):
        env = dict(self.env, **(extra or {}))
        r = subprocess.run([str(a) for a in argv], cwd=str(self.rv), env=env, capture_output=True, text=True, timeout=timeout)
        out = r.stdout + r.stderr
        self.log.append((name, r.returncode, out[-1500:]))
        return r.returncode, out

    def close(self):
        if self.keep:
            print(f'kept: {self.tmp}')
        else:
            shutil.rmtree(self.tmp, ignore_errors=True)


def canned_cloud(c: Chain):
    """pending J/V → out/<batch>.json по cloud_canned.json (как если бы агенты записали ответ сами)"""
    canned = jload(HERE / 'cloud_canned.json', {})
    st = jload(c.rv / 'cloud' / 'state.json', {}) or {}
    wrote = 0
    for bid, b in (st.get('batches') or {}).items():
        if b.get('status') == 'done':
            continue
        pk = jload(b['in'], {}) or {} if b.get('in') else {}
        kind = b.get('kind') or bid[:1]
        if kind == 'S':                                            # скептик: все подтверждённые находки реальны
            af = jload(c.w / 'audit_findings.json')
            if af is None and not pk:
                continue                                           # run-режим: судить нечего, пока collect не собрал J/V
            ids = [it.get('finding_id') for it in pk.get('items') or []] or \
                  [f['finding_id'] for f in (af or {}).get('findings') or [] if f.get('confirmed') and not f.get('skeptic')]
            out = {'batch_id': bid, 'sha8': pk.get('sha8') or bid.split('_', 1)[-1], 'verdicts': [
                {'finding_id': fid, 'real': True, 'code': '', 'reason': 'fixture: a real error', 'corrected_fix_text': ''}
                for fid in ids if fid]}
        elif not pk:
            continue
        elif kind == 'J':
            out = {'batch_id': bid, 'sha8': pk.get('sha8'), 'verdicts': [], 'new_findings': [], 'need_frames': [],
                   'facts_to_check': [], 'clean_screens': [], 'notes': 'fixture: canned answer'}
            for s in pk.get('screens') or []:
                text = ' | '.join(l.get('t', '') for l in s.get('ocr_lines') or []) or s.get('vlm_text') or ''
                cands = s.get('candidates') or []
                for cd in cands:
                    hay = f"{cd.get('text') or ''} {text}"
                    rule = next(x for x in canned['verdicts']
                                if (x['match'] == '*' or x['match'] in hay) and x['kind'] in ('*', cd.get('kind')))
                    out['verdicts'].append({'cand_id': cd['cand_id'], 'screen_id': s['id'], 'kind': cd.get('kind'),
                                            'verdict': rule['verdict'], 'reason': rule['reason'],
                                            'on_screen_text': cd.get('text') or text, 'fix_text': rule['fix_text'],
                                            'existing_tz': '', 'severity': rule['severity'], 'confidence': 0.9})
                nf = next((x for x in canned['new_findings'] if x['match'] in text), None) if not cands else None
                if nf:
                    out['new_findings'].append({'screen_id': s['id'], 'kind': nf['kind'], 'on_screen_text': text,
                                                'line_idx': -1, 'problem': nf['problem'], 'fix_text': nf['fix_text'],
                                                'why': nf['why'], 'severity': nf['severity'], 'existing_tz': ''})
                elif not cands:
                    out['clean_screens'].append(s['id'])
        elif kind == 'V':
            out = {'batch_id': bid, 'sha8': pk.get('sha8'), 'results': [
                {'q_id': it.get('q_id'), 'screen_id': it.get('screen_id'), 'cand_id': it.get('cand_id'),
                 'on_screen_text': it.get('on_screen_text'), 'text_as_seen': it.get('on_screen_text'),
                 'error_visible': False, 'answer': 'fixture: nothing visible', 'confidence': 0.5}
                for it in pk.get('items') or []]}
        else:
            continue
        p = Path(b.get('out') or c.rv / 'cloud' / 'out' / f'{bid}.json')
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
        wrote += 1
    return wrote


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--keep', action='store_true')
    a = ap.parse_args()
    c = Chain(keep=a.keep)
    try:
        chain(c)
    except Exception as e:                                          # цепочка упала — строка FAIL, а не трейсбек в selftest
        import traceback
        row('EN fixture: цепочка без исключений', False, f'{type(e).__name__}: {e} · {traceback.format_exc()[-300:]}')
    finally:
        if not all(r[1] for r in ROWS):
            for name, rc, out in c.log:
                if rc:
                    print(f'--- {name} rc={rc}\n{out[-800:]}')
        c.close()
    for name, good, msg in ROWS:
        print(f'{"✅" if good else "✗ "} {name}' + (f'  — {msg}' if msg else ''))
    bad = [r for r in ROWS if not r[1]]
    print('ИТОГ EN fixture:', 'OK' if not bad else f'FAIL {len(bad)}')
    if a.json:
        print('ROWS ' + json.dumps(ROWS, ensure_ascii=False))
    return 0 if not bad else 1


def chain(c: Chain):
    S = STAGE / 'stages'
    # ── s2: инвентарь экранов из ocr_hires.jsonl (кадров нет → OCR не зовётся) ──
    rc, out = c.run('s2', [PY, S / 's2_ocr_hires.py'])
    scr = jload(c.w / 'screens_v6.json', [])
    row('EN s2: инвентарь из ocr_hires.jsonl = фикстура (главы по карточке)',
        rc == 0 and scr == jload(HERE / 'work' / 'screens_v6.json'), f'rc={rc} {out[-200:]}')
    by_t0 = {e['t0']: e for e in scr}
    ex = [e for e in scr if 500 <= e['t0'] <= 520]
    ex_ids = {e['id'] for e in ex}
    onscreen = sorted({l['t'] for e in scr for l in e.get('lines_best') or []}, key=len, reverse=True)

    # ── route ──
    rc, out = c.run('route', [PY_ROUTE, S / 'route_candidates.py'])
    cands = jload(c.w / 'candidates.json', []) or []
    row('EN route: rc 0, candidates.json', rc == 0 and cands, f'rc={rc} {out[-200:]}')

    def of(e):
        return [x for x in cands if e and e['id'] in (x.get('screens') or [x.get('screen_id')])]

    lat_auto = [x for x in cands if x.get('kind') == 'language' and x.get('route') == 'auto_confirm'
                and not CYR.search(x.get('on_screen_text') or '') and not ARAB.search(x.get('on_screen_text') or '')]
    row('EN route: language auto_confirm 0 на английских титрах', not lat_auto,
        [(x['screen_id'], x['on_screen_text']) for x in lat_auto][:4])
    ty = [x for x in of(by_t0.get(12)) if x.get('kind') == 'typo' and x.get('route') != 'drop']
    row('EN route: typo INFRASTURCTURE → fix INFRASTRUCTURE', any(x.get('fix_local') == 'INFRASTRUCTURE' for x in ty),
        [(x['route'], x.get('fix_local')) for x in of(by_t0.get(12))])
    homo = [x for x in of(by_t0.get(30)) if x.get('kind') == 'language']
    row('EN route: токен с кириллической С («СORE») → language-кандидат (OCR-двойник: drop ocr_homoglyph)',
        homo and all(x.get('route') == 'drop' and x.get('drop_class') == 'ocr_homoglyph' for x in homo),
        [(x.get('kind'), x.get('route'), x.get('drop_class')) for x in of(by_t0.get(30))])
    cyr = [x for x in of(by_t0.get(138)) if x.get('kind') == 'language']
    row('EN route: кириллический титр («Сделка закрыта», VLM согласна) → language auto_confirm',
        any(x.get('route') == 'auto_confirm' for x in cyr), [(x.get('route'), x.get('route_reason')) for x in of(by_t0.get(138))])
    exc = [x for e in ex for x in of(e)]
    row('EN route: экран в исключении карточки → только drop known_exclusion',
        ex and exc and all(x.get('route') == 'drop' and str(x.get('route_reason', '')).startswith('known_exclusion') for x in exc),
        [(x.get('route'), x.get('route_reason', '')[:40]) for x in exc])
    ru_reason = [x for x in cands if x.get('route') != 'drop' and CYR.search(QUOTED.sub('', x.get('route_reason') or ''))]
    row('EN route: причины маршрута (не drop) без кириллицы', not ru_reason, [x.get('route_reason') for x in ru_reason][:2])

    # ── облако: pack → канон ответа → collect ──
    rc, out = c.run('pack', [PY, STAGE / 'cloud/pack.py'])
    packs = sorted((c.rv / 'cloud' / 'in').glob('J_*.json'))
    packed = {s['id'] for p in packs for s in (jload(p, {}) or {}).get('screens') or []}
    row('EN pack: J-пакеты собраны, экран исключения не пакуется', rc == 0 and packs and not (packed & ex_ids),
        f'rc={rc} packs={len(packs)} excluded_packed={sorted(packed & ex_ids)} {out[-160:]}')
    rc, call = c.run('print_call', [PY, STAGE / 'cloud/pack.py', '--print-call'])
    try:
        args = json.loads(call[len('Workflow('):call.rindex(')')])['args']
    except Exception:
        args = {}
    row('EN pack --print-call: args.lang = en, args.exclusions с таймкодами',
        args.get('lang') == 'en' and [(x['t0'], x['t1']) for x in args.get('exclusions') or []] == [(500.0, 520.0)],
        f'{str(args.get("lang"))} {args.get("exclusions")}')
    for _ in range(4):                                             # J (+V по need_frame) → collect → S (run) → collect
        wrote = canned_cloud(c)
        rc, out = c.run('collect', [PY, STAGE / 'cloud/collect.py'])
        if rc == 0 or not wrote:
            break
    rc, out = c.run('collect_legacy', [PY, STAGE / 'cloud/collect.py', '--emit-legacy'])
    af = jload(c.w / 'audit_findings.json', {}) or {}
    conf = [f for f in af.get('findings') or [] if f.get('confirmed')]
    row('EN collect: канон J/V собран, все батчи done, находки подтверждены',
        rc == 0 and len(conf) >= 4 and (c.w / 'audit_findings_v6.json').exists(),
        f'rc={rc} confirmed={len(conf)} {out[-200:]}')

    # ── apply → terms → format_tz ──
    rc, out = c.run('apply', [PY, S / 's8_apply_audit.py'])
    pr = (jload(c.rv / 'pravki' / 'pravki_v2.json', {}) or {}).get('all') or []
    ex_tz = [p for p in pr if p.get('screen_id') in ex_ids or any(500 <= float(p.get(k) or -1) <= 520
                                                                 for k in ('timeline_in_sec',))]
    row('EN apply: ТЗ созданы, на экране исключения ТЗ нет', rc == 0 and len(pr) >= 4 and not ex_tz,
        f'rc={rc} tz={len(pr)} excluded={[p.get("title") for p in ex_tz]} {out[-200:]}')
    rc, out = c.run('terms', [PY, S / 'terms_index.py'])
    row('EN terms_index: rc 0', rc == 0, out[-200:])
    rc, out = c.run('format_tz', [PY, S / 's10_format_tz.py'])
    pr = (jload(c.rv / 'pravki' / 'pravki_v2.json', {}) or {}).get('all') or []
    row('EN format_tz: rc 0, блоки ❌ NOW / ✅ DO', rc == 0 and pr and all('❌ NOW' in (p.get('nado') or '') for p in pr),
        f'rc={rc} {out[-200:]}')
    # стадия sources (review.py st_sources) идёт после format_tz у всех каналов: авто-источники картинок → 📚 SOURCE
    rc, out = c.run('sources', [PY, S / 's11_apply_sources.py'])
    pr = (jload(c.rv / 'pravki' / 'pravki_v2.json', {}) or {}).get('all') or []
    srcs = [mr.get('src') for p in pr for mr in p.get('material_rich') or [] if mr.get('src')]
    ru_src = [s for s in srcs if CYR.search(s)]
    row('EN sources: rc 0, источники проставлены, без кириллицы', rc == 0 and srcs and not ru_src,
        f'rc={rc} src={len(srcs)} ru={ru_src[:2]} {out[-200:]}')

    # ── графика (HTML) → таймлайн → мок-сборка ──
    rc, out = c.run('infographics', [PY, S / 'make_infographics_v6.py', 'all'], {'YTAI_RENDER_HTML_ONLY': '1'})
    html = sorted((c.rv / 'mockups' / 'src').glob('*.html'))
    row('EN infographics (HTML без chrome): rc 0', rc == 0 and html, f'rc={rc} pages={len(html)} {out[-200:]}')
    for p in html:
        (c.rv / 'mockups' / f'{p.stem}.png').write_bytes(b'')        # раскладка проверяет только наличие PNG
    rc, out = c.run('review_json', [PY, S / 'make_review_v6.py'])
    doc = jload(c.rv / 'YTCRFX_review_v6.json', {}) or {}
    part, segs = doc.get('part') or {}, doc.get('segments') or []

    def on_grid(t):
        return abs(t * FPS - round(t * FPS)) <= 0.02

    off = [(s['segment_id'], s[k]) for s in segs for k in ('timeline_in_sec', 'timeline_out_sec') if not on_grid(s[k])]
    off += [(m.get('name'), m.get('tc_sec')) for m in part.get('chapter_markers') or [] if not on_grid(m.get('tc_sec', 0))]
    row('EN review_json: part.fps = 30000/1001, все tc на сетке 29.97', rc == 0 and segs and abs(float(part.get('fps', 0)) - FPS) < 1e-9
        and not off, f'rc={rc} fps={part.get("fps")} off={off[:4]} {out[-160:]}')
    r = subprocess.run([NODE, str(S / 'mockbuild_v6.js')], cwd=str(c.rv), env=c.env, capture_output=True, text=True, timeout=120)
    row('EN mockbuild: error 0', r.returncode == 0 and re.search(r'error 0\b', r.stdout), (r.stdout + r.stderr)[-200:])

    # ── офлайн-дампы вкладок и листа ──
    dumps = {}
    for name, script, flag in (('tz_dump', 'doc_tab_tz_v4.py', '--dump-requests'), ('nav_dump', 'doc_tab_review_v1.py', '--dump-requests'),
                               ('sheet_dump', 'tz_sheet.py', '--dump-rows')):
        dst = c.tmp / f'{name}.json'
        rc, out = c.run(name, [PY, S / script, flag, dst])
        dumps[name] = jload(dst)
        row(f'EN {name}: rc 0', rc == 0 and dumps[name] is not None, f'rc={rc} {out[-200:]}')

    # ── язык поверхностей монтажёра: кириллица только внутри текста на экране ──
    word = re.compile(r'[А-Яа-яЁё]+')
    screen_words = {w for t in onscreen for w in word.findall(t)}      # слова с экрана (в т.ч. в сигналах «ocr:…») — не утечка

    def leaks(obj):
        bad = set()
        for s in strings(obj):
            for t in onscreen:
                s = s.replace(t, '')
            bad.update(w for w in word.findall(QUOTED.sub('', s)) if w not in screen_words)
        return sorted(bad)

    editor = {'pravki': [{k: p.get(k) for k in ('title', 'est', 'nado', 'parts', 'material_rich', 'typo', 'decision')} for p in pr],
              'review_json': {'note': part.get('note'), 'markers': part.get('chapter_markers'), 'tracks': doc.get('tracks'),
                              'items': [s.get('item_marker') for s in segs], 'dropped': doc.get('dropped')},
              'summary_md': (c.rv / 'YTCRFX_review_v6_summary.md').read_text(encoding='utf-8')
              if (c.rv / 'YTCRFX_review_v6_summary.md').exists() else '',
              'mockups_html': [p.read_text(encoding='utf-8') for p in html], 'dumps': dumps}
    for k, v in editor.items():
        bad = leaks(v)
        row(f'EN язык: {k} без кириллицы вне текста на экране', not bad, bad[:8])

    # ── главы поменялись → chapter экранов/находок перепомечается без OCR (review.py rebuild_screen_chapters) ──
    spec = importlib.util.spec_from_file_location('ytai_review_cli', STAGE / 'review.py')
    rv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rv)
    n = rv.rebuild_screen_chapters(SimpleNamespace(card={'chapters': [[0, '01'], [150.4, '02'], [300, '03']]}, work=c.w))
    scr2 = {e['id']: e['chapter'] for e in jload(c.w / 'screens_v6.json', [])}
    af2 = jload(c.w / 'audit_findings.json', {}) or {}
    want = {e['id']: ('01' if e['t0'] < 150 else '02' if e['t0'] < 300 else '03') for e in scr}
    row('review.py rebuild_screen_chapters: screens_v6 + audit_findings перепомечены по новым главам',
        n > 0 and scr2 == want and all(f.get('chapter') == want.get(f.get('screen_id'), f.get('chapter'))
                                        for f in af2.get('findings') or []), f'n={n}')


if __name__ == '__main__':
    sys.exit(main())
