#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v7 S10: ТЗ «как карта структуры» (Роман 10.09; эталон — info_structure_map.png):
крупный заголовок, под ним ВЕРТИКАЛЬНЫЙ СПИСОК — таймкод слева, пункт справа, одна строка = одна мысль;
ничего не перечисляется в строку через «·», «,», «→». «Сплошной текст очень сложно человеку считывать».

  【ЗАГОЛОВОК】
  ❌ СЕЙЧАС · что на экране — в чём проблема (строка на находку; «почему» — отдельной короткой строкой)
  ✅ СДЕЛАТЬ · действие; опечатки — «tc ▸ было «…» → стало «…»» (изменённые буквы док красит красным)
  📋 СПИСОК · полные списки (подглавы / термины / локации) — «tc ▸ пункт» по строке
  📍 ГДЕ · таймкоды — по строке на точку
  📚 ИСТОЧНИК · 🎬 НА ТАЙМЛАЙНЕ · 💬 РОМА (фиолетовым)

Элемент блока p['parts'][k]: строка ИЛИ {"h": "заголовок", "items": ["33:42 ▸ пункт", …] | "@prog:08"}.
Пункт «TC ▸ …»: таймкод дополняется цифровым пробелом до ширины «33:42» (док делает его моноширинным —
«▸» встаёт столбцом, как в эталоне). Списки ТЗ-30/74/75/76 генерятся из данных (SUB/CH_NAME/CH_BOUNDS,
terms_v6.json + terms_catalog) — один источник с картинками. p['typo'] = [{tc, was, now}] → первый блок
✅ СДЕЛАТЬ. Источник истины — p['parts'] + tz_overrides.json поверх; p['nado'] пересобирается каждый раз.
Lint → lint_v7.json: строк с ≥2 таймкодами быть не должно (диапазон «a–b» = один; 💬/❓ не проверяем).
"""
import json
import re
import sys
from pathlib import Path

W6 = Path(__file__).parent
M = W6.parent / 'montage'
sys.path.insert(0, str(W6))
from make_infographics_v6_data import (SUB, CH_NAME, CH_BOUNDS, NEW_CH, PROG, PROG_T,  # noqa: E402
                                       PROG_FINAL, PROG_NOTE)
from terms_catalog import TERMS, LOCS  # noqa: E402
from typo_diff import typo_line  # noqa: E402

PRAVKI = M / 'pravki_v2.json'
WORDS = '/Volumes/T7-Blue-2-RYA/YTUVI-Projects/YTUVI01_Corundum_Ruby/00_Setup/05_Review/YTUVI01_v1.words.json'
LBL = {'now': '❌ СЕЙЧАС', 'do': '✅ СДЕЛАТЬ', 'list': '📋 СПИСОК', 'where': '📍 ГДЕ',
       'src': '📚 ИСТОЧНИК', 'tl': '🎬 НА ТАЙМЛАЙНЕ'}
ORDER = ['now', 'do', 'list', 'where', 'src', 'tl']
IND = '     '           # продолжение блока
IND2 = '        '       # пункт списка под заголовком
FIG = ' '          # цифровой пробел: «0:57» выравнивается под «33:42»
TC = r'\d{1,2}:\d{2}(?:\s*[–-]\s*\d{1,2}:\d{2})?'
TC_RE = re.compile(rf'(?<![\d:]){TC}(?![\d:])')
# пункт «TC ▸ …»: допускаем «@», «~» и дробные секунды (~2:47.4), чтобы хвост «.4» не уехал в текст
ITEM_RE = re.compile(r'^@?(~?\d{1,2}:\d{2}(?:\.\d+)?(?:\s*[–-]\s*\d{1,2}:\d{2}(?:\.\d+)?)?)(?![\d:])\s*(?:▸|—|·|:|-)?\s*(.+)$')
URL_RE = re.compile(r'https?://[^\s;,)»]+')
KIND_RU = {'typo': 'опечатка', 'grammar': 'грамматика', 'fact': 'факт-ошибка',
           'currency': 'формат валюты/числа', 'language': 'английский без перевода',
           'mismatch': 'экран ≠ озвучка', 'design': 'вёрстка', 'other': 'правка'}

pr = json.load(open(PRAVKI))
allp = pr['all']
for i, p in enumerate(allp):
    p['num'] = f'ТЗ-{i + 1:02d}'

audit = json.load(open(W6 / 'audit_v6.json')) if (W6 / 'audit_v6.json').exists() else {'annotations': []}
finds = json.load(open(W6 / 'audit_findings_v6.json'))['confirmed'] if (W6 / 'audit_findings_v6.json').exists() else []
by_screen = {}
for f in finds:
    if f.get('confirmed', True):
        by_screen.setdefault(f['screen_id'], []).append(f)
tz2screen = {a['tz']: a['screen_id'] for a in audit['annotations'] if not a.get('existing')}
tz_has_fix = {a['tz'] for a in audit['annotations'] if a.get('fix')}
TJ = json.load(open(W6 / 'terms_v6.json'))

_ws = []
if Path(WORDS).exists():
    for seg in json.load(open(WORDS, encoding='utf-8'))['segments']:
        for w in seg.get('words') or []:
            _ws.append((w['w'], float(w['s'])))


def clean(t):
    t = re.sub(r'\s+', ' ', str(t or '').strip())
    return re.sub(r'(?<![\d:])(\d{1,2}:\d{2})\s*[–-]\s*\1(?![\d:.])', r'\1', t)    # «2:47–2:47» → «2:47»


def tcs(sec):
    sec = int(sec)
    return f'{sec // 60}:{sec % 60:02d}'


def anchor_words(t0, t1):
    """якорь озвучки как в s8: слова в окне находки ±2 с"""
    return clean(' '.join(w for w, s in _ws if t0 - 2 <= s <= t1 + 2))[:160]


def short_why(t, lim=160):
    t = clean(t)
    m = re.match(r'(.+?[.!?])(\s|$)', t)
    s = m.group(1) if m and len(m.group(1)) >= 25 else t
    return s if len(s) <= lim else s[:lim - 1].rsplit(' ', 1)[0] + '…'


def money(s):
    """«$34,8 МЛН» → «$34,8 МЛН (= $34 800 000)» — Роман: «сумму цифрами, чтобы размер числа понять»"""
    def rep(m):
        v = int(m.group(1)) * 1_000_000 + int(m.group(2)) * 100_000
        return f"{m.group(0)} (= ${format(v, ',').replace(',', ' ')})"
    return re.sub(r'\$(\d+),(\d)\s*МЛН(?!\s*\(=)', rep, s)


def split_src(ev):
    """evidence → (текст без URL, [ссылки])"""
    ev = clean(ev)
    urls = URL_RE.findall(ev)
    txt = URL_RE.sub('', ev)
    txt = re.sub(r'\s*[;·,]\s*(?=[;·,]|$)', '', txt).strip(' ;·,—-')
    return txt, urls


# ── генераторы списков из данных ──
def gen_prog(ch):
    title, labels, _ = PROG[ch]
    n = len(labels)
    out = []
    for i, (t, lab) in enumerate(zip(PROG_T[ch], labels), 1):
        note = PROG_NOTE.get((ch, i))
        out.append(f'{tcs(t)} ▸ {i} из {n} · {lab}' + (f' ({note})' if note else ''))
    if ch in PROG_FINAL:
        t, txt = PROG_FINAL[ch]
        out.append(f'{tcs(t)} ▸ {txt}')
    return out


def gen_structure(style):
    out = []
    for a, b, n in CH_BOUNDS:
        items = [(s, l) for s, ch, l in SUB if a <= s < b]
        name = CH_NAME[n - 1]
        if style == 'map':
            h = f'ГЛАВА {n:02d} · {name} · {tcs(a)}–{tcs(b)}' + (' · ➕ заставки в кате нет — создать' if n in NEW_CH else '')
        else:
            h = f'ГЛ.{n:02d} · {name} ({len(items)})'
        its = [f'{tcs(s)} ▸ {money(l)}' for s, l in items] or ['подтем в кате нет — предложить 2–3 титульных экрана']
        out.append({'h': h, 'items': its})
    return out


def _grouped(entries):
    by = {}
    for e in entries:
        by.setdefault(e['key'], []).append(e)
    return sorted(by.items(), key=lambda kv: (-len(kv[1]), min(e['t'] for e in kv[1])))


def gen_terms():
    meta = {t[0]: (t[2], t[3]) for t in TERMS}
    out = []
    for k, es in _grouped(TJ['terms']):
        title, sub = meta.get(k, (k.upper(), ''))
        out.append({'h': f'{title} ({sub}) — {len(es)}×' if sub else f'{title} — {len(es)}×',
                    'items': [f"{e['tc']} ▸ «…{clean(e['hit'])}…»" for e in sorted(es, key=lambda e: e['t'])]})
    return out


def gen_locs():
    meta = {l[0]: l[4] for l in LOCS}
    return [{'h': f'{meta.get(k, k.upper())} — {len(es)}×',
             'items': [f"{e['tc']} ▸ «…{clean(e['hit'])}…»" for e in sorted(es, key=lambda e: e['t'])]}
            for k, es in _grouped(TJ['locs'])]


GEN_LIST = {'ТЗ-30': lambda: gen_structure('map'), 'ТЗ-74': lambda: gen_structure('sub'),
            'ТЗ-75': gen_terms, 'ТЗ-76': gen_locs}


# ── сборка parts ──
def anchor_of(p):
    m = re.search(r'якорь(?: озвучки)?:\s*«(.+?)»', p.get('nado', ''), re.S | re.I)
    return clean(m.group(1)) if m else ''


def parts_from_audit(p):
    sid = tz2screen.get(p['num'])
    fs = by_screen.get(sid) or []
    if not fs:
        return None
    fs = sorted(fs, key=lambda f: {'high': 0, 'medium': 1, 'low': 2}[f['severity']])
    now, do, srcs = [], [], []
    for f in fs:
        txt = clean(f['on_screen_text'])
        kind = KIND_RU.get(f['kind'], 'правка')
        now.append({'h': f'«{txt}» — {kind}' if txt else kind, 'items': [short_why(f['problem'])]})
        fix = clean(f.get('fix_text_final') or f.get('fix_text'))
        if fix:
            do.append(f'Заменить титр на «{fix}»' if len(fix) <= 70 and not fix[:1].islower()
                      and not fix.lower().startswith(('заменить', 'убрать', 'сдвинуть', 'перерисовать', 'добавить'))
                      else fix)
        t, u = split_src(f.get('evidence'))
        if u:
            srcs.append({'h': t or 'ссылки', 'items': u})
        elif t:
            srcs.append(t)
    t0 = min(int(float(f['t0'])) for f in fs)
    t1 = max(int(float(f['t1'])) for f in fs)
    a = anchor_words(t0, t1) or anchor_of(p)
    where = [p['tc_range'] + (f' · якорь: «{a}»' if a else '')]
    tl = ['стрелка «где ошибка» — слой V5 ревью-секвенции']
    if p['num'] in tz_has_fix:
        tl.append(f"драфт исправленного титра — слой V3 (fix_{p['num'].replace('ТЗ-', 'tz')}.png)")
    return {'now': now, 'do': do, 'where': where, 'src': srcs, 'tl': tl}


def parts_from_legacy(p):
    """Разовый разбор старого nado (если parts ещё нет)."""
    body = p.get('nado', '')
    anchor = anchor_of(p)
    body = re.sub(r'\n?Якорь(?: озвучки)?:.*?(?=\n|$)', '', body, flags=re.S | re.I)
    src = []
    m = re.search(r'Источник:\s*(.+?)(?=\n|$)', body, re.S)
    if m:
        t, u = split_src(m.group(1))
        src.append({'h': t, 'items': u} if u else t)
        body = body.replace(m.group(0), '')
    do = [clean(x) for x in body.split('\n') if clean(x)]
    now = [clean(p.get('est'))] if clean(p.get('est')) else []
    where = [(p.get('tc_range') or p.get('v1_tc', '')) + (f' · якорь: «{anchor}»' if anchor else '')]
    return {'now': now, 'do': do, 'where': where, 'src': src, 'tl': []}


FIX_LINE = re.compile(r'^(?:Заменить титр на|Исправить на|Перерисовать титул:?)\s*«(.+?)»')


def apply_typo(p):
    """p['typo'] → первый блок ✅ СДЕЛАТЬ «tc ▸ было «…» → стало «…»»; дубли «Заменить титр на «…»» убрать."""
    ty = p.get('typo') or []
    do = [v for v in (p['parts'].get('do') or []) if not (isinstance(v, dict) and v.get('_typo'))]
    if not ty:
        p['parts']['do'] = do
        return
    nows = [t['now'] for t in ty]

    def dup(v):
        if not isinstance(v, str):
            return False
        m = FIX_LINE.match(clean(v))
        return bool(m) and any(m.group(1) in n or n in m.group(1) for n in nows)
    do = [v for v in do if not dup(v)]
    items = [f"{t['tc']} ▸ {typo_line(t['was'], t['now'])}" for t in ty]
    do.insert(0, {'h': p.get('typo_h') or 'Исправить (изменённые знаки — красным):', 'items': items, '_typo': True})
    p['parts']['do'] = do


# ── рендер ──
def expand(items):
    if isinstance(items, str):
        return gen_prog(items.split(':', 1)[1]) if items.startswith('@prog:') else [items]
    return items or []


def fmt_item(x):
    s = clean(x)
    m = ITEM_RE.match(s)
    if m:
        tc = re.sub(r'\s*[–-]\s*', '–', m.group(1))
        if re.fullmatch(r'\d{1,2}:\d{2}', tc):              # только «M:SS» выравниваем под «MM:SS»
            tc = tc.rjust(5, FIG)
        return f'{tc}  ▸ {m.group(2)}'
    if s.startswith(('▸', '•', 'http')) or re.match(r'^\S{1,3} ▸ ', s):
        return s
    return '▸ ' + s


def render_block(k, vals):
    out, first = [], True
    lab = LBL[k]
    for v in vals or []:
        if isinstance(v, dict):
            h = clean(v.get('h'))
            items = [fmt_item(x) for x in expand(v.get('items')) if clean(x)]
            if h:
                out.append((f'{lab} · ' if first else IND) + h)
                out += [IND2 + x for x in items]
            else:
                if first:
                    out.append(f'{lab} ·')
                out += [IND + x for x in items]
            first = False
        else:
            t = clean(v)
            if t:
                out.append((f'{lab} · ' if first else IND) + t)
                first = False
    return out


def render(p):
    out = []
    for k in ORDER:
        out += render_block(k, (p.get('parts') or {}).get(k))
    for c in p.get('roman_comment') or []:
        out.append('💬 ' + c)
    return '\n'.join(out)


def lint(p):
    multi, long_ = [], []
    for ln in p['nado'].split('\n'):
        s = ln.strip()
        if not s or s.startswith(('💬', '❓')):
            continue
        if len(TC_RE.findall(s)) >= 2:
            multi.append(s)
        elif len(s) > 220 and not s.startswith(('📚', 'http', '▸ http')):
            long_.append(s)
    return multi, long_


# ── 1. базовые parts ──
n_a = n_l = 0
for p in allp:
    pt = parts_from_audit(p) if p.get('source') == 'audit_v6' else None
    if pt:
        n_a += 1
    else:
        pt = p.get('parts') or parts_from_legacy(p)
        n_l += 1
    p['parts'] = pt

# ── 2. ручные тексты (Роман 09–10.09 + v7) ──
OVERRIDES = json.load(open(W6 / 'tz_overrides.json')) if (W6 / 'tz_overrides.json').exists() else {}
for num, ov in OVERRIDES.items():
    if num.startswith('_'):
        continue
    idx = int(num[3:]) - 1
    if not (0 <= idx < len(allp)):
        print('!! нет', num)
        continue
    p = allp[idx]
    for k, v in ov.items():
        if k in ('title', 'category', 'v1_tc', 'tc_range', 'est', 'status', 'decision', 'roman_comment', 'typo', 'typo_h'):
            p[k] = v
        elif k == 'material_rich':
            p['material_rich'] = v
        elif k == 'parts':
            p['parts'].update(v)
        elif k == 'parts_replace':
            p['parts'] = json.loads(json.dumps(v))
    if 'roman_1009' not in (p.get('notes') or []):
        p.setdefault('notes', []).append('roman_1009')

# ── 3. списки из данных + опечатки + рендер + lint ──
LINT = {}
for p in allp:
    if p['num'] in GEN_LIST:
        p['parts']['list'] = GEN_LIST[p['num']]()
    apply_typo(p)
    p['nado'] = render(p)
    if p.get('status') != 'rejected':
        multi, long_ = lint(p)
        if multi or long_:
            LINT[p['num']] = {'multi': multi, 'long': long_}

for p in allp:
    p.pop('num', None)
json.dump(pr, open(PRAVKI, 'w'), ensure_ascii=False, indent=1)
json.dump(LINT, open(W6 / 'lint_v7.json', 'w'), ensure_ascii=False, indent=1)
n_multi = sum(len(v['multi']) for v in LINT.values())
n_long = sum(len(v['long']) for v in LINT.values())
print(f'переформатировано: audit {n_a} · legacy {n_l} · overrides {len([k for k in OVERRIDES if not k.startswith("_")])}')
print(f'LINT: строк с ≥2 таймкодами {n_multi} (ТЗ: {sorted(k for k, v in LINT.items() if v["multi"])}) · '
      f'длинных >220: {n_long} (ТЗ: {len([k for k, v in LINT.items() if v["long"]])}) → lint_v7.json')
