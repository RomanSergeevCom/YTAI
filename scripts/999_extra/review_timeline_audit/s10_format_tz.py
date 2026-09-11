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
from terms_catalog import TERMS, LOCS, PLACE, TERM_EXTRA, place_family  # noqa: E402
from typo_diff import typo_line  # noqa: E402

PRAVKI = M / 'pravki_v2.json'
WORDS = '/Volumes/T7-Blue-2-RYA/YTUVI-Projects/YTUVI01_Corundum_Ruby/00_Setup/05_Review/YTUVI01_v1.words.json'
LBL = {'now': '❌ СЕЙЧАС', 'do': '✅ СДЕЛАТЬ', 'list': '📋 СПИСОК', 'where': '📍 ГДЕ',
       'src': '📚 ИСТОЧНИК', 'tl': '🎬 НА ТАЙМЛАЙНЕ'}
ORDER = ['now', 'do', 'list', 'where', 'src', 'tl']
IND = '     '           # продолжение блока
IND2 = '        '       # пункт списка под заголовком
FIG = ' '          # цифровой пробел: «0:57» выравнивается под «33:42»
# дробные секунды — часть ОДНОГО таймкода: «2:46.0–2:48.6» это один, а не два (как в verify дока)
TC = r'\d{1,2}:\d{2}(?:\.\d+)?(?:\s*[–-]\s*\d{1,2}:\d{2}(?:\.\d+)?)?'
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


ABBR = re.compile(r'(?:\b(?:англ|лат|ср|напр|см|рис|стр|г|гг|в|вв|др|пр|ок|т\.\s?е|т\.\s?ч|т\.\s?к|№)\.)$', re.I)


def short_why(t, lim=220):
    """«почему» одной строкой: целиком, если короткое; иначе первая фраза (не рвём на «англ.», «т. ч.»)"""
    t = clean(t)
    if len(t) <= lim:
        return t
    for m in re.finditer(r'[.!?](?=\s|$)', t):
        head = t[:m.end()]
        if len(head) >= 40 and not ABBR.search(head):
            if len(head) <= lim:
                return head
            break
    return t[:lim - 1].rsplit(' ', 1)[0] + '…'


KIND_UP = {'typo': 'ОПЕЧАТКА', 'grammar': 'ГРАММАТИКА', 'fact': 'ФАКТ-ОШИБКА', 'currency': 'ФОРМАТ ВАЛЮТЫ/ЧИСЛА',
           'language': 'АНГЛИЙСКИЙ БЕЗ ПЕРЕВОДА', 'mismatch': 'ЭКРАН ≠ ОЗВУЧКА', 'design': 'ВЁРСТКА', 'other': 'ПРАВКА'}


def audit_title(f):
    """заголовок аудит-ТЗ без обрыва посреди слова (было: первые 40 знаков + «»…»)"""
    raw = re.sub(r'\s*\n\s*', ' / ', str(f.get('on_screen_text') or ''))
    raw = clean(re.sub(r'\[([^\]]*)\]', r'\1', raw))
    if len(raw) > 64:
        raw = raw[:62].rsplit(' ', 1)[0].rstrip(' ,;:/·—') + '…'
    return f"{KIND_UP.get(f.get('kind'), 'ПРАВКА')}: «{raw}»"


def money(s):
    """«$34,8 МЛН» → «$34,8 МЛН (= $34 800 000)» — Роман: «сумму цифрами, чтобы размер числа понять»"""
    def rep(m):
        v = int(m.group(1)) * 1_000_000 + int(m.group(2)) * 100_000
        return f"{m.group(0)} (= ${format(v, ',').replace(',', ' ')})"
    return re.sub(r'\$(\d+),(\d)\s*МЛН(?!\s*\(=)', rep, s)


def split_src(ev):
    """evidence → (текст без URL, [ссылки]); без мусора «—;», «: ;» и точки на конце ссылки"""
    ev = clean(ev)
    urls = [u.rstrip('.') for u in URL_RE.findall(ev)]
    txt = URL_RE.sub('', ev)
    txt = re.sub(r'\s*—\s*;', ';', txt)
    txt = re.sub(r':\s*;', ':', txt)
    txt = re.sub(r'\s*[;·,]\s*(?=[;·,]|$)', '', txt).strip(' ;·,—-:')
    return txt, urls


def src_el(t, urls):
    """источник: по мысли на строку — «;» делит мысли, ссылки отдельными пунктами"""
    chunks = [c.strip(' ;·') for c in re.split(r';\s+', t) if c.strip(' ;·')] if t else []
    if not chunks and not urls:
        return None
    if len(chunks) <= 1 and not urls:
        return chunks[0]
    return {'h': chunks[0] if chunks else 'ссылки', 'items': chunks[1:] + urls}


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


def hit_txt(e, lim=110):
    """фраза упоминания: озвучка — «…фраза…»; экранный титр (OCR) — помечен и обрезан по границе слова"""
    h = clean(e['hit']).replace(' | ', ' / ').strip(' |/')
    if len(h) > lim:
        h = h[:lim].rsplit(' ', 1)[0] + '…'
    return f'титр на экране: «{h}»' if e.get('src') != 'vo' else f'«…{h}…»'


def _forms(m):
    """английские формы — в том написании, как они стоят в кадре («Burma», «Mogok Valley», «17 jewels»)"""
    txt = m.get('screen_text') or m.get('text') or ''
    out = []
    for f in (m.get('en_forms') or m.get('forms') or [])[:2]:
        hit = re.search(re.escape(f).replace(r'\ ', r'[\s-]+'), txt, re.I)
        out.append(hit.group(0).replace('\n', ' ') if hit else f)
    return ' и '.join(f'«{x}»' for x in out)


def _said(e, win=10.0, lim=95):
    """что звучит в этот момент — чтобы монтажёр сопоставил надпись в кадре со словами"""
    t = float(e['t'])
    said = clean(' '.join(w for w, s in _ws if t - 1.5 <= s <= t + win))
    if len(said) > lim:
        said = said[:lim].rsplit(' ', 1)[0]
    return said.strip(' .,…')


def _tc_line(m, what):
    return f"{m['tc']} ▸ {what}"


def _head_lines(key, meta_extra, title, sub, lead_en):
    """шапка карточки: что писать на экране, как читается, как объясняем, зачем"""
    x = meta_extra or {}
    out = []
    if x.get('screen_note'):
        out.append('на экране: ' + x['screen_note'])
    elif lead_en:
        out.append(f'на экране: первой строкой «{(x.get("en") or [""])[0].upper()}» — как в кадре, под ней крупно «{title}»')
    else:
        out.append(f'на экране: крупно «{title}», под ней мелко «{sub}»' if sub else f'на экране: крупно «{title}»')
    if x.get('read'):
        out.append(f'читается «{x["read"]}»')
    return out


def gen_terms():
    """ТЗ-75: по строке на каждый таймкод — что звучит, что видно в кадре, что пишем.
    Роман 11.09: «мы показываем на часах 17 JEWELS, надо использовать это вместе с переводом»."""
    meta = {t[0]: (t[2], t[3], t[4]) for t in TERMS}
    by = {}
    for e in TJ['terms']:
        by.setdefault(e['key'], []).append(e)
    extra_scr = {}
    for e in TJ.get('en_screens', []):
        if e['kind'] == 'terms':
            extra_scr.setdefault(e['key'], []).append(e)
    out = []
    for k, es in sorted(by.items(), key=lambda kv: min(e['t'] for e in kv[1])):
        title, sub, definition = meta.get(k, (k.upper(), '', ''))
        x = TERM_EXTRA.get(k) or {}
        lead_en = x.get('lead') == 'en'
        en_here = [e for e in es if e.get('en_on_screen')] + extra_scr.get(k, [])
        head = f'{title} ({sub})' if sub else title
        head += f' — {_plural(len(es), "плашка", "плашки", "плашек")}'
        if en_here:
            head += ' · оригинал виден в кадре'
        items = _head_lines(k, x, title, sub, lead_en)
        items.append(f'объясняем так: {definition}')
        if x.get('why'):
            items.append(f'зачем: {x["why"]}')
        if lead_en:
            items.append('ведём оригиналом: надпись на предмете, её не перерисовать')
        rows = []
        for e in sorted(es, key=lambda e: e['t']):
            if e.get('en_on_screen'):
                rows.append((e['t'], _tc_line(e, f'в кадре по-английски {_forms(e)} — плашка повторяет надпись и переводит её')))
                said = _said(e)                      # что она говорит в этот момент — ради сопоставления
                if said:
                    rows.append((e['t'] + 0.01, _tc_line(e, f'в озвучке: «…{said}…»')))
            else:
                rows.append((e['t'], _tc_line(e, hit_txt(e))))
        for e in extra_scr.get(k, []):
            rows.append((e['t'], _tc_line(e, f'в кадре по-английски {_forms(e)} — дать перевод на экране')))
        items += [t for _, t in sorted(rows)]
        out.append({'h': head, 'items': items})
    return out


def gen_renames():
    """Блок ТЗ-75 «что переписать»: переименование + КОРОТКОЕ объяснение, что это такое.
    Роман 11.09: «не вижу просто объяснение… здесь не перевод нужен, а коротко объяснить, что это»."""
    meta = {t[0]: (t[2], t[3], t[4]) for t in TERMS}
    order = {k: i for i, (k, *_) in enumerate(TERMS)}
    out = []
    for k, x in sorted(TERM_EXTRA.items(), key=lambda kv: order.get(kv[0], 99)):
        if not x.get('was'):
            continue
        title, _sub, definition = meta.get(k, (k.upper(), '', ''))
        why = clean(definition).rstrip('.')
        why = why[0].lower() + why[1:] if why else ''
        was = x['was'] if x['was'].startswith('«') else f'«{x["was"]}»'
        now = title if title.startswith('«') else f'«{title}»'
        out.append(f'было {was} — стало {now} · {why}')
    return out


def gen_reads():
    """трудные слова — как читаются вслух"""
    meta = {t[0]: t[2] for t in TERMS}
    order = {k: i for i, (k, *_) in enumerate(TERMS)}
    out = []
    for k, x in sorted(TERM_EXTRA.items(), key=lambda kv: order.get(kv[0], 99)):
        if x.get('read') and x.get('read_of'):
            out.append(f'{x["read_of"]} — читается «{x["read"]}», на экране «{meta.get(k, k.upper())}»')
    return out


def _plural(n, one, few, many):
    n10, n100 = n % 10, n % 100
    return f'{n} ' + (one if n10 == 1 and n100 != 11 else
                      few if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else many)


def _loc_head(k, n):
    """Заголовок места: город подписан своей страной ПОЛНЫМ каноном «МЬЯНМА (БИРМА) · долина МОГОК»."""
    p = PLACE[k]
    cnt = _plural(n, 'мини-карта', 'мини-карты', 'мини-карт')
    if p.get('parent'):
        return f"{PLACE[p['parent']]['label']} · {p['role']} {p['ru']} — {cnt}"
    kind = p.get('kind_label') or {'country': 'страна', 'region': 'горный район, не страна'}.get(p['kind'], '')
    return f'{p["label"]} · {kind} — {cnt}' if kind else f'{p["label"]} — {cnt}'


def gen_locs():
    """ТЗ-76: места — города сразу за своей страной, по строке на каждый таймкод."""
    by = {}
    for e in TJ['locs']:
        by.setdefault(e['key'], []).append(e)
    extra_scr = {}
    for e in TJ.get('en_screens', []):
        if e['kind'] == 'locs':
            extra_scr.setdefault(e['key'], []).append(e)
    fam = {}
    for k in by:
        fam.setdefault(place_family(k), []).append(k)
    out, belt = [], []
    order = sorted(fam.items(), key=lambda kv: min(e['t'] for k in kv[1] for e in by[k]))
    for _f, keys in order:
        keys.sort(key=lambda k: (bool(PLACE[k].get('parent')), min(e['t'] for e in by[k])))
        for k in keys:
            own = [e for e in by[k] if not e.get('cover')]
            belt += [(e['t'], e['tc'], PLACE[k]['ru']) for e in by[k] if e.get('cover')]
            if not own:
                continue
            p = PLACE[k]
            en_here = [e for e in own if e.get('en_on_screen')] + extra_scr.get(k, [])
            head = _loc_head(k, len(own))
            if en_here:
                head += ' · имя видно в кадре по-английски'
            items = [x for x in (p.get('screen_note'), p.get('read_note')) if x]
            if p.get('note'):
                items.append('сноску про переименование даём один раз, на первом упоминании')
            if p.get('parent'):
                items.append(f'зачем: {p["ru"]} — это {p["role"]} ВНУТРИ страны {PLACE[p["parent"]]["ru"]}, а не отдельная страна')
            rows = []
            for e in sorted(own, key=lambda e: e['t']):
                if e.get('en_on_screen'):
                    rows.append((e['t'], _tc_line(e, f'в кадре по-английски {_forms(e)} — ставим подпись по-русски')))
                    said = _said(e)
                    if said:
                        rows.append((e['t'] + 0.01, _tc_line(e, f'в озвучке: «…{said}…»')))
                else:
                    line = hit_txt(e)
                    if e.get('note'):
                        line += ' — здесь ставим сноску про переименование'
                    rows.append((e['t'], _tc_line(e, line)))
            for e in extra_scr.get(k, []):
                what = f'в кадре по-английски {_forms(e)}'
                if len(e.get('forms') or []) > 1 and k == 'burma':
                    what = 'в кадре рядом стоят «Burma» и «Myanmar» — подписать «МЬЯНМА (БИРМА), это одна страна»'
                else:
                    what += ' — дать подпись по-русски'
                rows.append((e['t'], _tc_line(e, what)))
            items += [t for _, t in sorted(rows)]
            out.append({'h': head, 'items': items})
    if belt:
        out.append({'h': 'ПЕРЕЧИСЛЕНИЕ «РУБИНОВОГО ПОЯСА» · мини-карты не ставим, всё на большой карте',
                    'items': [f'{tc} ▸ {ru}' for _t, tc, ru in sorted(belt)]})
    return out


GEN_LIST = {'ТЗ-30': lambda: gen_structure('sub'), 'ТЗ-75': gen_terms, 'ТЗ-76': gen_locs}


def _card(img, t, title, n, what):
    return {'t': f'{what} «{title}» — {_plural(n, "показ", "показа", "показов")}', 'img': img, '_t': t}


def gen_term_cards():
    """правый столбец ТЗ-75: карточка на каждый термин, по порядку появления в фильме"""
    meta = {t[0]: t[2] for t in TERMS}
    by = {}
    for e in TJ['terms']:
        by.setdefault(e['key'], []).append(e)
    cards = [_card(f'term_{k}.png', min(e['t'] for e in es), meta.get(k, k.upper()), len(es), 'Плашка')
             for k, es in by.items()]
    cards.sort(key=lambda c: c.pop('_t'))
    grp = 'termgrp_marble_iron_fluor.png'
    cards.append({'t': 'Так выглядит общая плашка, когда 2–3 термина звучат подряд', 'img': grp})
    # сводная шпаргалка: что звучит → как подписываем (Роман 11.09 — «иначе легко путаться»)
    cards.append({'t': 'КАРТА НАЗВАНИЙ: термины по порядку появления, часть 1', 'img': 'info_namemap_terms.png'})
    cards.append({'t': 'КАРТА НАЗВАНИЙ: термины по порядку появления, часть 2', 'img': 'info_namemap_terms_2.png'})
    return cards


def gen_loc_cards():
    """правый столбец ТЗ-76: мини-карта каждого места + большие карты"""
    by = {}
    for e in TJ['locs']:
        by.setdefault(e['key'], []).append(e)
    cards = []
    for k, es in by.items():
        own = [e for e in es if not e.get('cover')]
        if not own:
            continue
        img = f'map_{k}_note.png' if any(e.get('note') for e in own) else f'map_{k}.png'
        cards.append(_card(img, min(e['t'] for e in own), PLACE[k]['label'], len(own), 'Мини-карта'))
    cards.sort(key=lambda c: c.pop('_t'))
    return cards + [
        {'t': 'Большая карта: одна страна — два разных месторождения', 'img': 'mapfull_burma.png'},
        {'t': '«Рубиновый пояс», шаг 1 из 3', 'img': 'mapfull_belt.png'},
        {'t': '«Рубиновый пояс», шаг 2 из 3', 'img': 'mapfull_belt_2.png'},
        {'t': '«Рубиновый пояс», шаг 3 из 3', 'img': 'mapfull_belt_3.png'},
        {'t': 'КАРТА НАЗВАНИЙ: все 13 мест одним кадром — что звучит и что ставим на экран',
         'img': 'info_namemap_places.png'},
    ]


GEN_MAT = {'ТЗ-75': gen_term_cards, 'ТЗ-76': gen_loc_cards}


# ── карточка-пример в каждом ТЗ (Роман 11.09: «проверь, чтобы все карточки были во всех местах») ──
# слева — ТЗ, справа — наш рендер: либо свежий fix-драфт «как должно быть», либо уже готовая плашка
ADD_MAT = {
    'ТЗ-02': [('map_mogok.png', 'Драфт: мини-карта «МОГОК» — русская подпись поверх английской карты')],
    'ТЗ-11': [('term_silk.png', 'Драфт: плашка «ШЁЛК» — что это простыми словами')],
    'ТЗ-13': [('info_structure_map.png', 'Карта структуры: все главы и подглавы одним кадром')],
    'ТЗ-14': [('term_pigeon.png', 'Драфт: «ГОЛУБИНАЯ КРОВЬ» крупно, «pigeon blood» мелко')],
    'ТЗ-18': [('info_videomap_ch06.png', 'Карта выпуска: где стоит глава «Происхождение рубина»')],
    'ТЗ-20': [('term_sothebys.png', 'Драфт: плашка «СОТБИС» — что это за дом')],
    'ТЗ-24': [('term_jewels17.png', 'Драфт: «17 JEWELS» как на часах и перевод «17 КАМНЕЙ»')],
    'ТЗ-25': [('term_highjew.png', 'Драфт: «ВЫСОКОЕ ЮВЕЛИРНОЕ ИСКУССТВО» — что это значит'),
              ('term_cartier.png', 'Драфт: плашка «КАРТЬЕ»'),
              ('term_winston.png', 'Драфт: плашка «ГАРРИ УИНСТОН»')],
    'ТЗ-36': [('fix_tz36.png', 'Драфт: титр «ТЫСЯЧИ ЛЕТ» — вариант А')],
    'ТЗ-54': [('fix_tz54.png', 'Драфт: русский перевод схемы')],
    'ТЗ-56': [('fix_tz56.png', 'Драфт: исправленная строка сертификата')],
    'ТЗ-57': [('fix_tz57.png', 'Драфт: русский титр вместо английского пресс-релиза')],
    'ТЗ-65': [('fix_tz65.png', 'Драфт: титр «Затравки»')],
    'ТЗ-66': [('fix_tz66.png', 'Драфт: русская подпись к фото Меймана')],
    'ТЗ-68': [('fix_tz68.png', 'Драфт: исправленный заголовок таблицы')],
}


def add_cards(p):
    """дописать карточку-рендер, если её ещё нет (оверрайды и GEN_MAT не трогаем)"""
    have = {m.get('img') for m in (p.get('material_rich') or [])}
    for img, cap in ADD_MAT.get(p['num'], []):
        if img not in have:
            p.setdefault('material_rich', []).append({'t': cap, 'img': img})


def title_terms():
    st = TJ['stats']['terms']
    en = TJ['stats'].get('en', {}).get('on_screen_terms', 0)
    return (f'ТЕРМИНЫ: перевод и объяснение при каждом упоминании '
            f'({len(st["by_key"])} терминов / {st["plates"]} показов; у {en} оригинал виден в кадре)')


def title_locs():
    st = TJ['stats']['locs']
    en = TJ['stats'].get('en', {}).get('on_screen_locs', 0)
    mini = st['plates'] - st.get('covered', 0)
    return (f'ЛОКАЦИИ НА КАРТЕ: канон названий мест ({len(st["by_key"])} мест / {st["plates"]} упоминаний) — '
            f'{mini} мини-карт и 4 большие карты; у {en} имя видно в кадре по-английски')


GEN_TITLE = {'ТЗ-75': title_terms, 'ТЗ-76': title_locs}


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
        el = src_el(*split_src(f.get('evidence')))
        if el:
            srcs.append(el)
    p['title'] = audit_title(fs[0])
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
    do.insert(0, {'h': p.get('typo_h') or 'Исправить (в доке изменённые знаки выделены красным):', 'items': items,
                  '_typo': True})
    p['parts']['do'] = do


# ── рендер ──
AT = {'@renames': lambda: gen_renames(), '@reads': lambda: gen_reads()}


def expand(items):
    """строка-плейсхолдер вместо списка: '@prog:08' · '@renames' · '@reads' — списки из каталога"""
    if isinstance(items, str):
        if items.startswith('@prog:'):
            return gen_prog(items.split(':', 1)[1])
        return AT[items]() if items in AT else [items]
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
    if p['num'] in GEN_TITLE:
        p['title'] = GEN_TITLE[p['num']]()
    if p['num'] in GEN_MAT:                       # правый столбец: карточка на каждый термин/место
        p['material_rich'] = GEN_MAT[p['num']]()
    add_cards(p)
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
