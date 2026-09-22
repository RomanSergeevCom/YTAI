#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify вкладки «ТЗ монтажёру · v3» (формат v7, 10.09): структура и номера, превью у каждого ТЗ
(ширина, свой абзац), списки без строк с ≥2 таймкодами, красные буквы в опечатках, суммы цифрами,
ссылки, решения, без дублей 💬."""
import json
import os
import re
import sys
from pathlib import Path

from _bootstrap import P, W6, M, HERE, ROOT, T, LANG, tz_label  # noqa: E402
from doctab_lib import DOCS, get_doc, iter_tabs  # noqa: E402
from typo_diff import diff_spans, typo_line, typo_offsets  # noqa: E402
from said import stream as said_stream  # noqa: E402


DOC_ID = P.need('doc_id')                  # было DOCS['01'] — проверяли бы вкладку первого видео
TAB_TITLE = os.environ.get('TZ_TAB') or P.need('tab_title')
N_CH = int(P.get('n_chapters', len(P.CHAPTERS)))   # YTUVI01: 9 (глава «Техпаспорт» снята 09.09)
MIN_IMG_W = 250
TC_RE = re.compile(r'(?<![\d:])~?\d{1,2}:\d{2}(?:\.\d+)?(?:\s*[–-]\s*\d{1,2}:\d{2}(?:\.\d+)?)?(?![\d:])')  # доли секунды: «2:46.0–2:48.6» — один таймкод

def _opt(p):
    """необязательные обогащалки от мягкой стадии drive: без публичной папки кадров их нет"""
    return json.load(open(p)) if p.exists() else {}


pravki = json.load(open(M / 'pravki_v2.json'))['all']
shots = _opt(M / 'shots_ids.json')
proj = _opt(M / 'proj_material_ids.json')
drive_clips = _opt(M / 'drive_clips.json')
act = [(tz_label(i + 1), p) for i, p in enumerate(pravki) if p.get('status') != 'rejected']   # ТЗ-07 / FIX-07
NUM_RE = re.compile(rf'^{re.escape(T("core.tz_prefix"))}-\d{{2,3}}$')     # ТЗ-07 … ТЗ-100 (YTUVI02 v3: 100 ТЗ)
DEC = T('c2.decision_prefix').rstrip()                                                         # '❓ РЕШЕНИЕ РОМАНА:'

doc = get_doc(DOC_ID)
tab = next((t for t in iter_tabs(doc) if t['tabProperties'].get('title') == TAB_TITLE), None)
assert tab, 'вкладка не найдена'
body = tab['documentTab']['body']['content']
inl = tab['documentTab'].get('inlineObjects', {})
tables = [el for el in body if 'table' in el]


def runs(cell):
    return [e for c in cell.get('content', []) for e in c.get('paragraph', {}).get('elements', []) if 'textRun' in e]


def cell_text(cell):
    return ''.join(e['textRun'].get('content', '') for e in runs(cell))


checks = []


def ck(name, ok, detail=''):
    checks.append((name, ok, detail))
    print(('✅' if ok else '❌'), name, detail)


ck('одна таблица', len(tables) == 1, f'найдено {len(tables)}')
rows = tables[0]['table']['tableRows']
# v5 22.09.2026 (раскладка Романа): № | TC | кат. | Говорит | Комментарии Романа | ✅ | Описание ошибки | Материал | Как надо
C_SAY, C_ROMAN, C_OK, C_ERR, C_MAT, C_DO = 3, 4, 5, 6, 7, 8
C_TZ = C_ERR
HDR = [h.strip() for h in T('c2.tz_hdr')]
# в шапке у каждой колонки свой номер («7 Описание ошибки») — просьба Романа
HDR_NUM = [f'{i + 1} {h}'.strip() for i, h in enumerate(HDR)]
got_hdr = [cell_text(c).strip() for c in rows[0]['tableCells']]
ck(f'шапка: {len(HDR)} колонок с номерами «{" | ".join(HDR_NUM)}»', got_hdr == HDR_NUM,
   f'={got_hdr}' if got_hdr != HDR_NUM else '')
n_tz = len(act)
ck(f'строк {n_tz + N_CH + 1} (шапка + {n_tz} ТЗ + {N_CH} глав)', len(rows) == n_tz + N_CH + 1, f'={len(rows)}')
col0 = [cell_text(r['tableCells'][0]).strip() for r in rows]
row_of = {c: r for c, r in zip(col0, rows) if NUM_RE.match(c)}
exp_nums = {n for n, _ in act}
ck(f'все {n_tz} номеров ТЗ', set(row_of) == exp_nums,
   f'нет: {sorted(exp_nums - set(row_of))} лишние: {sorted(set(row_of) - exp_nums)}' if set(row_of) != exp_nums else '')
# речь ката («Говорит») в счёт ссылок/решений не идёт — это слова ведущей, не текст ТЗ;
# чекбокс приёмки — тоже не текст
full = '\n'.join(cell_text(c) for r in rows for j, c in enumerate(r['tableCells']) if j not in (C_SAY, C_OK))
# «текст ТЗ» для проверок по содержанию — обе половины: описание ошибки и как надо
t3 = {n: cell_text(r['tableCells'][C_ERR]) + '\n' + cell_text(r['tableCells'][C_DO]) for n, r in row_of.items()}
# Проверки «по содержанию конкретного ТЗ» — из карточки (verify_tz: {«ТЗ-12»: [«23.976», «Interpret»]}).
# Были зашиты номера и тексты первого фильма (ТЗ-30 первой строкой, fps в ТЗ-12, дубль @25:48 в ТЗ-17,
# суммы в ТЗ-21): на другом кате они гарантированно падали и топили реальные замечания.
for _num, _needles in (P.get('verify_tz') or {}).items():
    _txt = t3.get(_num, '')
    _miss = [x for x in _needles if x not in _txt]
    ck(f'{_num}: содержит {", ".join(_needles)}', not _miss, f'нет: {_miss}' if _miss else '')
if P.get('verify_first_tz'):
    ck(f'{P.get("verify_first_tz")} первой строкой', col0[1] == P.get('verify_first_tz'), f'={col0[1]!r}')
ch_labels = [t for t in (cell_text(r['tableCells'][C_TZ]).strip() for r in rows) if t.startswith('[') and '·' in t]
ck(f'{N_CH} глав-строк со [скобками]', len(ch_labels) == N_CH, f'={len(ch_labels)}')

# ── колонки v5 (раскладка Романа 22.09.2026) ──
no_do = [n for n, r in row_of.items() if not cell_text(r['tableCells'][C_DO]).strip()]
ck('у каждого ТЗ непустое «Как надо»', not no_do, f'пусто: {sorted(no_do)}' if no_do else '')
no_err = [n for n, r in row_of.items() if not cell_text(r['tableCells'][C_ERR]).strip()]
ck('у каждого ТЗ непустое «Описание ошибки»', not no_err, f'пусто: {sorted(no_err)}' if no_err else '')
# ❓ РЕШЕНИЕ РОМАНА и 💬 живут только в его колонке — иначе он их не найдёт там, где ищет
dec_pref = T('c2.decision_prefix').strip()
stray = [n for n, r in row_of.items()
         if any(x in cell_text(r['tableCells'][j]) for j in (C_ERR, C_DO, C_MAT) for x in (dec_pref, '💬'))]
ck('❓ решения и 💬 — только в колонке Романа', not stray, f'утекли: {sorted(stray)}' if stray else '')
# чекбокс приёмки: ровно один список-галочка на строку ТЗ
def _has_cb(c):
    return sum(1 for el in c['content'] if 'paragraph' in el and el['paragraph'].get('bullet'))
bad_cb = [n for n, r in row_of.items() if _has_cb(r['tableCells'][C_OK]) != 1]
ck('чекбокс приёмки в каждой строке ТЗ', not bad_cb, f'нет/лишние: {sorted(bad_cb)}' if bad_cb else '')

# ── картинки ──
def imgs_in(cell):
    out = []
    for c in cell.get('content', []):
        els = c.get('paragraph', {}).get('elements', [])
        objs = [e for e in els if 'inlineObjectElement' in e]
        if objs:
            other = ''.join(e.get('textRun', {}).get('content', '') for e in els if 'textRun' in e)
            for o in objs:
                out.append((o['inlineObjectElement']['inlineObjectId'], other.strip() == ''))
    return out


all_imgs = [x for r in rows for c in r['tableCells'] for x in imgs_in(c)]
exp_imgs = N_CH + sum(1 for _, p in act for it in (p.get('material_rich') or [])
                      if (it.get('preview') or it.get('img')) in shots)
# Картинки во вкладку вставляются ТОЛЬКО из публичной папки кадров (shots_remote). У фильма
# её может не быть намеренно (YTCH12: в кадре ребёнок) — тогда картинок нет ни при каком
# раскладе, и требовать их значит проваливать вкладку за решение о приватности.
if str(P.get('shots_remote', '') or ''):
    ck(f'картинок ≥ {exp_imgs} (главы + превью/материал)', len(all_imgs) >= exp_imgs, f'={len(all_imgs)}')
    no_img = [n for n, r in row_of.items() if not imgs_in(r['tableCells'][C_MAT])]
    ck('у каждого ТЗ есть картинка справа', not no_img, f'без картинки: {sorted(no_img)}' if no_img else '')
else:
    print('—  картинки: shots_remote пуст (публичной папки кадров у фильма нет) — проверки пропущены')


def width(oid):
    try:
        return inl[oid]['inlineObjectProperties']['embeddedObject']['size']['width']['magnitude']
    except KeyError:
        return 0


narrow = [round(width(o), 2) for o, _ in all_imgs if width(o) < MIN_IMG_W - 0.01]   # Docs отдаёт 249.99999999999997 за 250
ck(f'все картинки ≥ {MIN_IMG_W}pt по ширине', not narrow, f'узких: {len(narrow)} {narrow[:8]}' if narrow else '')
shared = sum(1 for _, alone in all_imgs if not alone)
ck('каждая картинка — в своём абзаце', shared == 0, f'в абзаце с текстом: {shared}' if shared else '')

# ── формат: одна строка — один таймкод ──
multi = []
for n, t in t3.items():
    for ln in t.split('\n'):
        s = ln.strip()
        if s and not s.startswith(('💬', '❓')) and len(TC_RE.findall(s)) >= 2:
            multi.append(f'{n}: {s[:90]}')
ck('в «ТЗ монтажёру» нет строк с ≥2 таймкодами', not multi, f'{len(multi)}: {multi[:5]}' if multi else '')

# ── опечатки: изменённые знаки красным ──
def red_mask(cell):
    txt, mask = '', []
    for e in runs(cell):
        c = e['textRun'].get('content', '')
        st = e['textRun'].get('textStyle', {})
        rgb = st.get('foregroundColor', {}).get('color', {}).get('rgbColor', {})
        red = rgb.get('red', 0) > 0.7 and rgb.get('green', 0) < 0.2 and rgb.get('blue', 0) < 0.2
        txt += c
        mask += [(red, bool(st.get('bold')), bool(st.get('strikethrough')))] * len(c)
    return txt, mask


bad_typo, n_typo = [], 0
for n, p in act:
    for ty in p.get('typo') or []:
        n_typo += 1
        txt, mask = red_mask(row_of[n]['tableCells'][C_DO])   # пары «было → стало» — в «Как надо»
        pos = txt.find(typo_line(ty['was'], ty['now']))
        if pos < 0:
            bad_typo.append(f'{n}: строки «было → стало» нет')
            continue
        wo, no = typo_offsets(ty['was'])
        sw, sn = diff_spans(ty['was'], ty['now'])
        okn = all(mask[pos + no + k][0] and mask[pos + no + k][1] for s, e in sn for k in range(s, e))
        okw = all(mask[pos + wo + k][0] and mask[pos + wo + k][2] for s, e in sw for k in range(s, e))
        red_total = sum(1 for k in range(pos, pos + len(typo_line(ty['was'], ty['now']))) if mask[k][0])
        exp_total = sum(e - s for s, e in sn) + sum(e - s for s, e in sw)
        if not (okn and okw and red_total == exp_total):
            bad_typo.append(f'{n}: красных {red_total} из {exp_total}')
# Опечаток в ТЗ может не быть вовсе (v5: экранная графика чистая) — красить тогда нечего,
# и «0 правок» это не провал проверки, а её отсутствие предмета.
if n_typo:
    ck(f'опечатки: изменённые знаки красным ({n_typo} правок)', not bad_typo, '; '.join(bad_typo))
else:
    print('—  опечатки: в ТЗ нет ни одной правки типа typo — проверка пропущена')

# ── v8 (Роман 11.09): карточка на каждый термин/место + канон названий ──
N75, N76 = tz_label(75), tz_label(76)      # номера карт названий YTUVI01; проверки ниже — только когда их термины есть
for num in (N75, N76):
    if num not in row_of:
        continue
    p_ = dict(act)[num]
    exp = len(p_.get('material_rich') or [])
    got = len(imgs_in(row_of[num]['tableCells'][C_MAT]))
    ck(f'{num}: карточка на каждый пункт ({exp})', got == exp, f'в доке {got}')
if 'МЬЯНМА' in t3.get(N76, ''):
    bad_canon = [ln for ln in t3.get(N76, '').split('\n')
                 if re.match(r'^\s*МЬЯНМА\s·', ln) and 'БИРМА' not in ln]
    ck(f'{N76}: страна везде «МЬЯНМА (БИРМА)»', not bad_canon, f'{bad_canon[:2]}' if bad_canon else '')
if 'в кадре по-английски' in t3.get(N75, '') + t3.get(N76, ''):
    no_orig = [ln for ln in (t3.get(N75, '') + t3.get(N76, '')).split('\n')
               if re.search(r'\d{1,2}:\d{2}.*в кадре по-английски', ln) and '«' not in ln]
    ck('строки «в кадре по-английски» показывают оригинал', not no_orig, f'{no_orig[:2]}' if no_orig else '')

# Роман 11.09: «не вижу просто объяснение» — у каждого переименования должно быть, что это такое
# «было «X» — стало «Y» · …» из core-ключей (ru: было « » — стало «; en: was “ ” — now “)
_NOW = T('core.was_mid').split('→', 1)[1].strip()                                  # 'стало «' / 'now “'
RENAME_RE = re.compile(re.escape(T('core.was_pre')) + '.+' + re.escape(T('core.was_post')) + ' — ' + re.escape(_NOW))
_NOW_WORD = _NOW.rstrip(' «“"')                                                    # 'стало' / 'now'
if N75 in t3:
    no_why = [ln for ln in t3[N75].split('\n')
              if RENAME_RE.search(ln) and ' · ' not in ln.split(_NOW_WORD)[1]]
    ck(f'{N75}: у каждого переименования есть объяснение', not no_why, f'{no_why[:2]}' if no_why else '')

# ── «Говорит» (Роман 16.09.2026): у каждой ТЗ с таймкодом — дословная речь ката с жирной опорой ──
_stream = said_stream()
_whole = T('c2.whole_film')
say_empty, say_not_verbatim, say_no_bold = [], [], []
for n, r in row_of.items():
    if _whole in cell_text(r['tableCells'][1]):
        continue
    c = r['tableCells'][C_SAY]
    txt = cell_text(c).strip()
    if not txt:
        say_empty.append(n)
        continue
    if any(par.strip() and par.strip() not in _stream for par in txt.split('\n')):
        say_not_verbatim.append(n)
    if not any((e['textRun'].get('textStyle') or {}).get('bold') and e['textRun'].get('content', '').strip() for e in runs(c)):
        say_no_bold.append(n)
ck('«Говорит»: у каждой ТЗ с таймкодом есть речь', not say_empty, f'{say_empty[:8]}' if say_empty else '')
ck('«Говорит»: каждый абзац дословно из words.json', not say_not_verbatim, f'{say_not_verbatim[:8]}' if say_not_verbatim else '')
ck('«Говорит»: опорная фраза жирным', not say_no_bold, f'{say_no_bold[:8]}' if say_no_bold else '')

dups = [n for n, p in act if p.get('roman_comment') and t3[n].count('💬') != len(p['roman_comment'])]
ck('💬 комменты Романа без дублей', not dups, f'{dups}' if dups else '')

# ── ссылки: клипы пула + «🔗 файл:» на каждый материал с img + источники + ссылки внутри ТЗ ──
exp_links = 0
for _, p in act:
    for it in p.get('material_rich') or []:
        names = re.findall(r'RYA-[A-Z0-9]+-\d{3,4}', it.get('t') or '')
        if any((nm + '.MP4') in drive_clips or (nm + '.MOV') in drive_clips for nm in names):
            exp_links += 1
        if it.get('img') and (it['img'] in proj or it['img'] in shots):
            exp_links += 1
        exp_links += str(it.get('src') or '').count('drive.google.com')
    exp_links += str(p.get('nado') or '').count('drive.google.com')
n_links = full.count('drive.google.com')
ck(f'ссылок в таблице = {exp_links}', n_links == exp_links, f'={n_links}')

exp_dec = sum(1 for _, p in act if p.get('decision'))
ck(f'{exp_dec} решений в строках', full.count(DEC) == exp_dec, f"={full.count(DEC)}")

bad = [n for n, ok, _ in checks if not ok]
print('\nALL PASS' if not bad else f'\nFAIL: {bad}')
sys.exit(0 if not bad else 1)
