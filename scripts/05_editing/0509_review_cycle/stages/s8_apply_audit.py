#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v8 S8: подтверждённые находки аудита → pravki (ТЗ) + audit_v6.json (стрелки V5, исправления V3, LT V4)
+ кадры ошибок для Drive/листа.

Вход (первый найденный, либо --findings PATH):
  1) W6/audit_findings.json    — review-findings-v8 от cloud/collect.py: findings[] + confirmed[finding_id…]
  2) W6/audit_findings_v6.json — легаси wf_audit_v6 {confirmed:[…]} (через P.audit_or_die; без файла — отказ,
                                 осознанный пропуск YTAI_NO_AUDIT=1)
Правила:
  • классовый фильтр профиля канала tz_classes {keep, drop}: drop-классы (вёрстка, вкус, темп…) НОВОЙ ТЗ не
    становятся (лог dropped_by_class); check_source (скептик H → «проверить исходник титра») остаётся всегда;
    новые классы: foreign_trace «ЧУЖОЙ СЛЕД В КАДРЕ», check_source «ПРОВЕРИТЬ ИСХОДНИК»;
  • одна ТЗ на экран (несколько находок экрана сливаются); находка под existing_tz номера не получает,
    но получает стрелку ТЗ-NNb/c…;
  • идемпотентно: ТЗ ключуется по screen_id (новые записи несут screen_id; у старых он берётся из
    material_rich «v6_err_sNNN.jpg» или audit_v6.json). Повтор не перенумеровывает и не дублирует:
    существующая аудит-ТЗ обновляется на месте, только если набор её находок изменился (поле audit_fp),
    ТЗ без audit_fp (легаси) не трогается; ТЗ никогда не удаляется (номер = позиция, s10/tz_sheet);
  • bbox: из находки, иначе line_idx → строка OCR экрана, иначе объединение строк экрана.
usage: s8_apply_audit.py [--findings PATH] [--dry-run]
       --dry-run — печатает, что добавится/обновится/отпадёт, на диск не пишет ничего.
Выход: pravki (новые записи `source: audit_v6`), audit_v6.json {annotations, placements, new_tz_from, new_tz_count},
err_frames/v6_err_<sid>.jpg — форматы прежние (их читают make_infographics/make_review/s10/s12/s9).
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from _bootstrap import P, W6, M, HERE, ROOT, T  # noqa: E402

ERR = W6 / 'err_frames'
WORDS = P.WORDS
# названия классов — core.kind_up.* (язык карточки/профиля; RU = прежние литералы)
KIND_RU = {k: T(f'core.kind_up.{k}') for k in ('typo', 'grammar', 'fact', 'currency', 'language', 'mismatch', 'design',
                                               'foreign_trace', 'check_source', 'other')}
KIND_OTHER = T('core.kind_up.other')
FIXABLE = {'typo', 'grammar', 'currency', 'fact'}        # где рисуем правильную плашку на V3
SEV = {'high': 0, 'medium': 1, 'low': 2}
AUDIT_SOURCES = {'audit_v6', 'audit'}
CHECK_SOURCE_FIX = T('c1.s8.check_source_fix')

ap = argparse.ArgumentParser()
ap.add_argument('--findings', help='audit_findings.json (v8) или audit_findings_v6.json (легаси)')
ap.add_argument('--dry-run', action='store_true')
a = ap.parse_args()
DRY = a.dry_run

ws = []
for seg in json.load(open(WORDS, encoding='utf-8'))['segments']:
    for w in seg.get('words') or []:
        ws.append((w['w'], float(w['s'])))

SCR = {}
if (W6 / 'screens_v6.json').exists():
    SCR = {e['id']: e for e in json.load(open(W6 / 'screens_v6.json', encoding='utf-8'))}


def anchor(t0, t1):
    return ' '.join(w for w, s in ws if t0 - 2 <= s <= t1 + 2)[:160]


def tc(sec):
    return f'{int(sec) // 60}:{int(sec) % 60:02d}'


def norm(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip().lower()


def typo_pair(f, tcs):
    """находка → пара «было → стало» для красной подсветки знаков (или None, если пара бессмысленна).

    Два случая, на которых наивная пара врала:
      • fix_text — не титр, а инструкция («Стиль (низкий приоритет…)») → пары быть не должно;
      • исправлено ОДНО слово («ПРОДАВАТЬ СИНЕТИКУ» → «СИНТЕТИКУ») → подставляем слово в титр,
        иначе монтажёр прочтёт, что половину титра надо убрать.
    """
    was = (f.get('on_screen_text') or '').replace('\n', ' ').strip()
    now = (f.get('fix_text') or '').replace('\n', ' ').strip()
    if not was or not now or len(was) > 90:
        return None
    if ' ' not in now and ' ' in was:                       # правка одного слова → вставляем его в титр
        words = was.split()
        i, best = max(enumerate(words), key=lambda kv: difflib.SequenceMatcher(
            None, kv[1].lower(), now.lower()).ratio())
        if difflib.SequenceMatcher(None, words[i].lower(), now.lower()).ratio() < 0.5:
            return None
        now = ' '.join(words[:i] + [now] + words[i + 1:])
    if difflib.SequenceMatcher(None, was.lower(), now.lower()).ratio() < 0.55:
        return None                                         # «стало» не похоже на титр — это инструкция
    return {'tc': tcs, 'was': was, 'now': now} if was != now else None


# ── bbox по экрану ─────────────────────────────────────────────────────────
def _bb(l):
    return {'x': l.get('x', 0), 'y': l.get('y', 0), 'w': l.get('bw', l.get('w', 0)), 'h': l.get('bh', l.get('h', 0))}


def screen_bbox(sid, line_idx=None, text=None):
    e = SCR.get(sid) or {}
    lines = e.get('lines_best') or []
    if not lines:
        return None
    if isinstance(line_idx, int) and 0 <= line_idx < len(lines):
        return _bb(lines[line_idx])
    t = norm(text)
    if t:
        best, bi = 0.0, None
        for i, l in enumerate(lines):
            lt = norm(l.get('t'))
            r = difflib.SequenceMatcher(None, lt, t).ratio() if lt else 0
            if lt and (lt in t or t in lt):
                r = max(r, 0.75)
            if r > best:
                best, bi = r, i
        if bi is not None and best >= 0.5:
            return _bb(lines[bi])
    x0 = min(l['x'] for l in lines)
    y0 = min(l['y'] for l in lines)
    x1 = max(l['x'] + l.get('bw', 0) for l in lines)
    y1 = max(l['y'] + l.get('bh', 0) for l in lines)
    return {'x': round(x0, 4), 'y': round(y0, 4), 'w': round(x1 - x0, 4), 'h': round(y1 - y0, 4)}


def frame_of(sid, given=''):
    if given and Path(given).exists():
        return given
    e = SCR.get(sid) or {}
    if given:
        p = W6 / 'hires' / Path(given).name
        if p.exists():
            return str(p)
    return str(W6 / 'hires' / e['best_frame']) if e.get('best_frame') else (given or '')


# ── входные находки: v8 или легаси ─────────────────────────────────────────
def norm_v8(f):
    sid = f.get('screen_id')
    e = SCR.get(sid) or {}
    bb = f.get('bbox') if isinstance(f.get('bbox'), dict) else None
    g = {
        'finding_id': f.get('finding_id'), 'screen_id': sid, 'tc': f.get('tc') or e.get('tc') or tc(f.get('t0') or 0),
        't0': int(f.get('t0', e.get('t0', 0)) or 0), 't1': int(f.get('t1', e.get('t1', 0)) or 0),
        'frame': frame_of(sid, f.get('frame') or ''), 'kind': f.get('kind') or 'other',
        'severity': f.get('severity') if f.get('severity') in SEV else 'medium',
        'on_screen_text': f.get('on_screen_text') or '', 'problem': f.get('problem') or '',
        'fix_text': f.get('fix_text') or '',
        'evidence': ' '.join(x for x in (f.get('why'), (f.get('fact') or {}).get('source_url')) if x and x != f.get('problem')),
        'bbox': bb or screen_bbox(sid, f.get('line_idx'), f.get('on_screen_text')),
        'existing_tz': (f.get('existing_tz') or '').strip(), 'route': f.get('route'),
    }
    if 'fix_draw' in f:
        g['fix_draw'] = f['fix_draw']
    if g['kind'] == 'check_source' and not g['fix_text']:
        g['fix_text'] = CHECK_SOURCE_FIX
    return g


def norm_legacy(f):
    sid = f.get('screen_id')
    bb = f.get('bbox_final') or f.get('bbox')
    g = {
        'finding_id': f.get('vid') or f'legacy.{sid}', 'screen_id': sid, 'tc': f.get('tc') or tc(f.get('t0') or 0),
        't0': int(f.get('t0') or 0), 't1': int(f.get('t1') or 0), 'frame': frame_of(sid, f.get('frame') or ''),
        'kind': f.get('kind') or 'other', 'severity': f.get('severity') if f.get('severity') in SEV else 'medium',
        'on_screen_text': f.get('on_screen_text') or '', 'problem': f.get('problem') or '',
        'fix_text': f.get('fix_text_final') or f.get('fix_text') or '', 'evidence': f.get('evidence') or '',
        'bbox': bb if isinstance(bb, dict) else screen_bbox(sid, None, f.get('on_screen_text')),
        'existing_tz': (f.get('existing_tz') or '').strip(), 'route': 'legacy',
    }
    if 'fix_draw' in f:
        g['fix_draw'] = f['fix_draw']
    return g


def load_findings(path):
    if path:
        p = Path(path)
        data = json.load(open(p, encoding='utf-8'))
    else:
        p = W6 / 'audit_findings.json'
        data = json.load(open(p, encoding='utf-8')) if p.exists() else None
        if data is None:
            p = W6 / 'audit_findings_v6.json'
            data = P.audit_or_die(p, 'аудит экранов (cloud: pack → wf_judge → collect; легаси: s6 → wf_audit_v6.js)') \
                or {'confirmed': [], 'packs': None}
    v8 = str(data.get('schema', '')).startswith('review-findings')
    if v8:
        ids = set(data.get('confirmed') or [])
        conf = [norm_v8(f) for f in data.get('findings') or [] if f.get('finding_id') in ids]
        print(f'вход: {p.name} (v8, прогоны {", ".join(data.get("run_ids") or []) or "—"}): '
              f'находок {len(data.get("findings") or [])}, подтверждено {len(conf)}')
    else:
        # Полнота (легаси): каждый пакет s6 обязан вернуться от аудиторов. Воркфлоу, упавший по лимиту сессии,
        # отдаёт часть пакетов — и глава без аудита выглядела бы «чистой», без единой строчки в логе.
        _idx = W6 / 'audit_pack' / 'INDEX.json'
        if _idx.exists() and data.get('packs') is not None:
            sent = {x['pack'] for x in json.load(open(_idx))}
            back = {x['pack'] for x in data['packs']}
            lost = sorted(sent - back)
            if lost and os.environ.get('YTAI_PARTIAL_AUDIT') != '1':
                raise SystemExit(f'аудит неполный: не вернулись пакеты {", ".join(lost)} (из {len(sent)}).\n'
                                 'Догони их (resume воркфлоу) или, если осознанно, запусти с YTAI_PARTIAL_AUDIT=1.')
            if lost:
                print(f'⚠️ аудит неполный по YTAI_PARTIAL_AUDIT=1 — без пакетов {", ".join(lost)}')
            print(f'аудит: пакетов вернулось {len(back & sent)}/{len(sent)}')
        conf = [norm_legacy(f) for f in data.get('confirmed') or [] if f.get('confirmed', True)]
        print(f'вход: {p.name} (легаси): подтверждено {len(conf)}')
    return conf


# ── исключения карточки: известные не-ошибки ката (дыра в футаже, недоделанные экраны) ─
EXCLUDED = []                                               # [(finding, reason)] — в ТЗ не идут


def drop_excluded(conf):
    if not P.EXCLUSIONS:
        return conf
    keep = []
    for f in conf:
        why = P.in_exclusion(f['t0'], f['t1'])
        if why:
            EXCLUDED.append((f, why))
        else:
            keep.append(f)
    return keep


# ── классовый фильтр профиля ───────────────────────────────────────────────
_classes = P.profile('tz_classes') or {}
KEEP = set(_classes.get('keep') or [])
DROP = set(_classes.get('drop') or [])


def kept(kind):
    if kind == 'check_source':
        return True
    if kind in DROP:
        return False
    return (kind in KEEP) if KEEP else True


# ── pravki: существующие ТЗ по экранам ─────────────────────────────────────
PRAVKI = M / 'pravki.json' if (M / 'pravki.json').exists() else M / 'pravki_v2.json'
pr = json.load(open(PRAVKI, encoding='utf-8')) if PRAVKI.exists() else {'all': []}
allp = pr['all']
OLD_ANN = {}
if (W6 / 'audit_v6.json').exists():
    try:
        for an in json.load(open(W6 / 'audit_v6.json', encoding='utf-8')).get('annotations') or []:
            OLD_ANN.setdefault(an['tz'], an)
    except Exception:
        pass


def tz_label(p, i):
    n = p.get('num')
    if isinstance(n, int):
        return f'ТЗ-{n:02d}'
    if isinstance(n, str) and n.startswith('ТЗ'):
        return n
    return f'ТЗ-{i + 1:02d}'


def entry_screen(p, i):
    if p.get('screen_id'):
        return p['screen_id']
    mr = p.get('material_rich') or []
    if isinstance(mr, str):
        try:
            mr = json.loads(mr)
        except Exception:
            mr = []
    for x in mr:
        m = re.search(r'v6_err_(s\d+)\.jpg', str((x or {}).get('img', '')))
        if m:
            return m.group(1)
    an = OLD_ANN.get(tz_label(p, i))
    return an['screen_id'] if an and not an.get('existing') else None


labels = {tz_label(p, i) for i, p in enumerate(allp)}
own_by_screen = {}
for i, p in enumerate(allp):
    if p.get('source') in AUDIT_SOURCES:
        sid = entry_screen(p, i)
        if sid and sid not in own_by_screen:
            own_by_screen[sid] = i


def fingerprint(fs):
    key = sorted((f['kind'], norm(f['on_screen_text']), norm(f['fix_text']), norm(f['problem'])[:120]) for f in fs)
    return hashlib.sha1(json.dumps(key, ensure_ascii=False).encode('utf-8')).hexdigest()[:12]


# ── сборка ─────────────────────────────────────────────────────────────────
conf = drop_excluded(load_findings(a.findings))
by_screen = {}
for f in conf:
    if f['screen_id']:
        by_screen.setdefault(f['screen_id'], []).append(f)

annotations, existing_ann = [], {}
added, updated, untouched, arrows_only, dropped = [], [], [], [], []
new_entries = []


def build_entry(num, sid, fs, main, t0, t1, draws):
    fix_main = main.get('fix_text') or ''
    lines, now, do, srcs = [], [], [], []
    for f in fs:
        fix = f.get('fix_text') or ''
        kr = KIND_RU.get(f['kind'], KIND_OTHER)
        lines.append(T('c1.s8.line_head', kind=kr, text=f['on_screen_text'])
                     + (T('c1.s8.line_fix', fix=fix) if fix else '') + f". {f['problem']}"
                     + (T('c1.s8.line_src', src=f['evidence']) if f.get('evidence') else ''))
        now.append({'h': T('c1.now_h', text=f['on_screen_text'], kind=kr.lower()) if f['on_screen_text'] else kr.lower(),
                    'items': [f['problem']] if f['problem'] else []})
        if fix:
            do.append(fix if f['kind'] == 'check_source' else T('c1.do_replace', fix=fix))
        if f.get('evidence'):
            srcs.append(f['evidence'])
    anc = anchor(t0, t1)
    fn = num.replace('ТЗ-', 'tz')
    kr_main = KIND_RU.get(main['kind'], KIND_OTHER)
    return {
        'notes': ['audit_v6'], 'v1_tc': tc(t0), 'tc_range': f'{tc(t0)}–{tc(t1)}',
        'title': T('c1.title', kind=kr_main, text=main['on_screen_text'][:38]) + ('…' if len(main['on_screen_text']) > 38 else ''),
        'category': 'graphics', 'source': 'audit_v6', 'class': main['kind'], 'screen_id': sid,
        'finding_ids': [f['finding_id'] for f in fs], 'audit_fp': fingerprint(fs),
        'est': T('c1.s8.est', tc=tc(t0), text=main['on_screen_text']),
        'nado': ('\n'.join(lines) + T('c1.s8.nado_anchor', anc=anc)
                 + (T('c1.s8.nado_draft', fn=fn) if draws else T('c1.s8.nado_arrow'))),
        'parts': {'now': now, 'do': do, 'where': [f'{tc(t0)}–{tc(t1)}' + (T('c1.where_anchor', anc=anc) if anc else '')],
                  'src': srcs, 'tl': [T('c1.tl_arrow')]
                  + ([T('c1.tl_draft', fn=fn)] if draws else [])},
        'material_rich': [{'t': T('c1.s8.mat_frame', tc=tc(t0)), 'img': f'v6_err_{sid}.jpg'}]
                         + ([{'t': T('c1.s8.mat_draft', fix=(main.get("fix_draw") or fix_main)[:40]), 'img': f'fix_{fn}.png'}]
                            if draws else []),
        # опечатки/грамматика/валюта → строка «было → стало», в которой doc_tab красит изменённые знаки
        'typo': [pp for pp in (typo_pair(f, tc(t0)) for f in fs if f['kind'] in ('typo', 'grammar', 'currency')) if pp],
        'sheet_answer': '', 'decision': '',
    }


PRESERVE = ('status', 'decision', 'sheet_answer', 'roman_comment', 'replies', 'rejected_by', 'notes', 'sensitive',
            'skeptic', 'material_rich_extra')

for sid, fs in sorted(by_screen.items(), key=lambda kv: min(f['t0'] for f in kv[1])):
    fs.sort(key=lambda f: SEV[f['severity']])
    own_i = own_by_screen.get(sid)
    own_label = tz_label(allp[own_i], own_i) if own_i is not None else None
    fk = [f for f in fs if kept(f['kind'])]
    for f in fs:
        if f not in fk:
            dropped.append(f'{f["kind"]}@{sid}')
    ex = None
    if own_i is None:
        for f in fs:                                        # EN-агент мог назвать ТЗ «FIX-07» — ключ данных всё равно «ТЗ-07»
            if (f['existing_tz'] or '').startswith('FIX-'):
                f['existing_tz'] = 'ТЗ-' + f['existing_tz'][4:]
        ex = next((f['existing_tz'] for f in fs if re.match(r'^ТЗ-\d+', f['existing_tz'] or '')), None)
        if ex and ex not in labels:
            print(f'⚠️ {sid}: existing_tz «{ex}» нет в pravki — считаю новой находкой')
            ex = None
    if not fk and own_i is None and not ex:
        continue                                            # только drop-классы: новой ТЗ нет
    use = fk if fk else fs                                  # у старой ТЗ стрелка остаётся даже для drop-класса
    t0, t1 = use[0]['t0'], max(f['t1'] for f in use)
    # главная находка экрана: сначала та, у которой есть нарисованное исправление, потом по severity
    use.sort(key=lambda f: (0 if f.get('fix_draw') else 1, SEV[f['severity']]))
    main = use[0]
    fix_main = main.get('fix_text') or ''
    draws = bool(main.get('fix_draw')) or ('fix_draw' not in main and main['kind'] in FIXABLE and fix_main and len(fix_main) <= 60)
    if own_i is not None:
        num = own_label
        p = allp[own_i]
        fp = fingerprint(fk) if fk else None
        if not fk:
            untouched.append(f'{num} ({sid}: только drop-классы)')
        elif p.get('audit_fp') is None or p.get('audit_fp') == fp:
            untouched.append(num)
        else:
            new = build_entry(num, sid, fk, main, t0, t1, draws)
            for k in PRESERVE:
                if k in p:
                    new[k] = p[k]
            new['notes'] = sorted(set((p.get('notes') or []) + ['audit_v6']))
            if not DRY:
                allp[own_i] = new
            updated.append(num)
    elif ex:
        k = existing_ann.get(ex, 0)
        existing_ann[ex] = k + 1
        num = f'{ex}{"bcdefgh"[k]}'                        # ТЗ-21b, ТЗ-21c …
        arrows_only.append(num)
    else:
        # номер = позиция (s10/tz_sheet); если записи несут int `num` — продолжаем их ряд, номера не переиспользуем
        nums = [p['num'] for p in allp + new_entries if isinstance(p.get('num'), int)]
        n_new = (max(nums) + 1) if nums else (len(allp) + len(new_entries) + 1)
        num = f'ТЗ-{n_new:02d}'
        ent = build_entry(num, sid, fk, main, t0, t1, draws)
        if nums:
            ent['num'] = n_new
        new_entries.append(ent)
        added.append(f'{num} · {tc(t0)} · {KIND_RU.get(main["kind"], KIND_OTHER)}: «{main["on_screen_text"][:40]}»')
    bb = main.get('bbox') or screen_bbox(sid, None, main['on_screen_text']) or {'x': 0.1, 'y': 0.1, 'w': 0.8, 'h': 0.2}
    annotations.append({
        'tz': num, 'kind': main['kind'], 'screen_id': sid, 't0': t0, 't1': t1, 'frame': main['frame'],
        'bbox': [bb['x'], bb['y'], bb['w'], bb['h']],
        'text': (T('c1.s8.ann_text', was=main['on_screen_text'][:60], now=fix_main[:60]) if fix_main else main['problem'][:120]),
        'fix': ({'text': main['fix_draw']} if main.get('fix_draw') else
                (None if 'fix_draw' in main else
                 ({'text': fix_main} if main['kind'] in FIXABLE and fix_main and len(fix_main) <= 60 else None))),
        'existing': bool(ex),
    })

# старые аудит-ТЗ, у которых в этом наборе находок нет экрана — стрелку переносим из прошлого audit_v6.json
have = {an['tz'] for an in annotations}
carried = []
for sid, i in own_by_screen.items():
    lab = tz_label(allp[i], i)
    if lab not in have and lab in OLD_ANN and allp[i].get('status') != 'rejected':
        annotations.append(OLD_ANN[lab])
        carried.append(lab)
annotations.sort(key=lambda an: (an['t0'], an['tz']))

if not DRY:
    pr['all'] = allp + new_entries
    P.write_json_atomic(PRAVKI, pr)

n_old = len(allp)
print(f'pravki ({PRAVKI.name}): было {n_old} ТЗ, новых {len(new_entries)}'
      + (f' (ТЗ-{n_old + 1:02d}…ТЗ-{n_old + len(new_entries):02d})' if new_entries else '')
      + f', обновлено на месте {len(updated)}, не тронуто {len(untouched)}, стрелок {len(annotations)}'
        f' (к существующим ТЗ: {sum(1 for an in annotations if an["existing"])}, перенесено {len(carried)})'
      + (f', исключено по exclusions карточки {len(EXCLUDED)}' if P.EXCLUSIONS else ''))
if EXCLUDED:
    from collections import Counter as _C
    print('excluded: ' + '; '.join(f'{r} — {n}' for r, n in _C(r for _f, r in EXCLUDED).most_common())
          + f' ({", ".join(sorted({f["kind"] + "@" + str(f["screen_id"]) for f, _r in EXCLUDED})[:8])})')
if added:
    print('добавить:\n  ' + '\n  '.join(added))
if updated:
    print('обновлено (набор находок изменился — перепроверь листификацию): ' + ', '.join(updated))
if dropped:
    from collections import Counter
    cnt = Counter(x.split('@')[0] for x in dropped)
    print(f'dropped_by_class: {len(dropped)} — ' + ', '.join(f'{k} {v}' for k, v in cnt.most_common())
          + f' ({", ".join(dropped[:8])}{"…" if len(dropped) > 8 else ""})')

# размещения на таймлайне: стрелка V5 на t0 экрана (≤4.8 с), исправление V3 — там же
placements = []
for an in annotations:
    # ставим на секунду КАДРА, который смотрел агент (титр уже дописан), а не на старт анимации
    m = re.search(r'h(\d{4})\.jpg$', an['frame'] or '')
    t = float(int(m.group(1)) - 1) if m else float(an['t0'])
    t = max(t, float(an['t0']))
    dur = min(4.8, max(3.0, an['t1'] - t + 1.0))
    fn = an['tz'].replace('ТЗ-', 'tz')
    placements.append({'sid': f'v5_ann_{fn}', 'track': 'V5', 'png': f'ann_{fn}.png', 't': t, 'dur': dur})
    if an['fix']:
        placements.append({'sid': f'v3_fix_{fn}', 'track': 'V3', 'png': f'fix_{fn}.png', 't': t, 'dur': dur})
out = {'annotations': annotations, 'placements': placements, 'new_tz_from': n_old + 1, 'new_tz_count': len(new_entries)}
if DRY:
    print(f'--dry-run: audit_v6.json не записан ({len(placements)} размещений), pravki не изменён')
    sys.exit(0)
P.write_json_atomic(W6 / 'audit_v6.json', out)
print('audit_v6.json →', len(placements), 'размещений')

# кадры ошибок (чистые; композит со стрелкой делает s9 после рендера G)
ERR.mkdir(exist_ok=True)
for an in annotations:
    src = Path(an['frame'] or '')
    dst = ERR / f'v6_err_{an["screen_id"]}.jpg'
    if src.exists() and not dst.exists():
        subprocess.run(['cp', str(src), str(dst)], check=True)
print('кадры →', ERR)
