#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Постраничная приёмка вкладки «ТЗ монтажёру» кодом (0 токенов) — замена 8 агентов по страницам PDF
и 18 агентов доводки (`cloud/_legacy/v7_tools/wf_final_doc_qa_v7.js`, `wf_final_qa_fix_v7.js`).

    doc_pdf_qc.py [--tab TITLE] [--pdf FILE.pdf] [--no-export] [--contact-sheet OUT.jpg] [--out doc_qc.json]

Вкладка (по умолчанию `tab_title` карточки) экспортируется в PDF через Docs export URL (read-only,
токен rscore как в export_tab_pdf.py) → `W6/doc_qc/tab.pdf`; `--pdf` — взять готовый файл; `--no-export`
— взять прошлый экспорт. Дальше только poppler + PIL:

  pdftohtml -xml   — фрагменты текста и картинки с координатами: колонки таблицы, строки-ТЗ, абзацы;
  pdftotext        — контрольный текст страниц;
  pdfimages -list  — число и ширина картинок;
  pdfimages -png   — пиксели картинок (пустые/однотонные/почти чёрные).

Критерии (канон v7, `listify_rules_v2.md`, память «Приёмка v7.1»):
  high — блокируют выдачу монтажёру: сирота-заголовок ТЗ в последних 3 строках страницы; картинка без
         подписи «таймкод · что видно»; ≥2 таймкода в абзаце; перечисления « → », « / », « | », « vs »;
         «▸ ▸»; нет ✅ СДЕЛАТЬ; сплошной абзац >220 знаков; картинок меньше, чем материалов; битая
         (однотонная/чёрная) картинка; число страниц вне ожидаемого; набор/порядок ТЗ не по pravki.
  low  — косметика: «@», двойные пробелы, жаргон hNNNN/sNNN/«нота»/«коммент», обрыв «…», «;» в строке,
         узкие картинки, перенос номера «ТЗ-0 / 1», подпись уехала на следующую страницу.

Выход: `W6/doc_qc.json` {pages, issues:[{page, tz, severity, criterion, what}], counts} + сводка ≤2 КБ.
Код возврата 0 — нет high, 2 — есть. `--contact-sheet OUT.jpg` — миниатюры страниц 4×4 (≤1568 px)
для одного взгляда человека/VLM (несколько листов → OUT.jpg, OUT_2.jpg, …).
Пишет только в W6 (ничего в Google).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from _bootstrap import P, W6, M, HERE, ROOT, T, LANG, tz_label  # noqa: E402

# ── константы приёмки ─────────────────────────────────────────────────────
ORPHAN_LINES = 3            # заголовок ТЗ в последних N строках страницы — сирота
LONG_PARA = 220             # сплошной абзац (как lint s10)
MIN_IMG_W_PX = 640          # картинка в PDF уже — в доке будет мыло (колонка 262pt ≈ 524 px на retina)
IMG_STD_MIN = 6.0           # однотонная картинка
IMG_MEAN_DARK = 25.0        # почти чёрная
PAGES_PER_TZ = (0.4, 1.6)   # ожидаемое число страниц = [a·n+2, b·n+6]
PAGES_ADD = (2, 6)
CAP_GAP = 42                # подпись не дальше N px (в единицах XML, 1.5×pt) под картинкой
LINE_TOL = 4                # фрагменты с |top−top| ≤ N — одна строка (эмодзи выше базовой линии на 2–3)

TC = r'~?\d{1,2}:\d{2}(?:\.\d+)?(?:\s*[–-]\s*\d{1,2}:\d{2}(?:\.\d+)?)?'
TCR = re.compile(rf'(?<![\d:]){TC}(?![\d:])')
CAP_RE = re.compile(r'^\d{1,2}:\d{2}(?:[–-]\d{1,2}:\d{2})?\s·\s\S')
URL_RE = re.compile(r'https?://\S+')
QUOTE_RE = re.compile(T('c2.qc_quote_rx'))                    # «…» (ru); «…» и “…” (en)
LABELS = ('❌', '✅', '📋', '📍', '📚', '🎬', '💬', '❓')
JARGON = [re.compile(r'(?<![\w/.-])[hsf]\d{3,4}(?![\w-])')]
if LANG == 'ru':                                              # русский жаргон ревью — только на русских вкладках
    JARGON += [re.compile(r'\bнот[аы]\s+\d'), re.compile(r'\bкоммент\w*\s+\d'),
               re.compile(r'ночн\w+ разбор'), re.compile(r'\bревью\s*№')]
# что сборщик вкладки пишет (doc_tab_tz_v3): шапка таблицы, префикс номера, «✅ СДЕЛАТЬ ·», «было «…» → стало»
TZ_HDR = T('c2.tz_hdr')                                       # ['№', '⏱ TC', '', 'ТЗ монтажёру', 'Материал / ссылки']
TZ_PREFIX = T('core.tz_prefix')                               # 'ТЗ' / 'FIX'
DO_LABEL = T('core.lbl_do').split(' ', 1)[1] + ' ·'           # 'СДЕЛАТЬ ·' / 'DO ·'
WASNOW_RE = re.compile(re.escape(T('core.was_pre')) + '.*?' + re.escape(T('core.was_mid').rstrip(' «“')))
ENUM_PATTERNS = [(' → ', re.compile(r'\s→\s')), (' / ', re.compile(r'\s/\s')),
                 (' | ', re.compile(r'\s\|\s')), (' vs ', re.compile(r'\svs\s', re.I))]


def clean(t):
    return re.sub(r'\s+', ' ', str(t or '')).strip()


def tc_sec(tc):
    m = re.match(r'(\d+):(\d{2})', str(tc or '').strip().lstrip('@~'))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, check=True, **kw).stdout


# ── экспорт вкладки (read-only) ───────────────────────────────────────────
def export_tab(title, pdf):
    """Docs export URL → PDF. Id вкладки ищем по имени через один GET документа (без записи)."""
    from doctab_lib import access_token, get_doc, iter_tabs  # noqa: E402
    doc_id = P.need('doc_id')
    tab_id = P.get('tab_id')
    if not tab_id:
        doc = get_doc(doc_id)
        tabs = {t['tabProperties'].get('title'): t['tabProperties']['tabId'] for t in iter_tabs(doc)}
        if title not in tabs:
            raise SystemExit(f'вкладка «{title}» не найдена; есть: {list(tabs)}')
        tab_id = tabs[title]
    url = f'https://docs.google.com/document/d/{doc_id}/export?format=pdf&tab={tab_id}'
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {access_token()}'})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = r.read()
    if not data.startswith(b'%PDF'):
        raise SystemExit('экспорт вернул не PDF (нет доступа к документу?)')
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(data)
    return tab_id


# ── разбор XML pdftohtml: фрагменты → колонки → строки → строки-ТЗ ────────
class Frag:
    __slots__ = ('page', 'top', 'left', 'w', 'h', 'text', 'bold')

    def __init__(self, page, el):
        self.page = page
        self.top = int(el.get('top'))
        self.left = int(el.get('left'))
        self.w = int(el.get('width'))
        self.h = int(el.get('height'))
        self.text = ''.join(el.itertext())
        self.bold = el.find('b') is not None

    @property
    def right(self):
        return self.left + self.w


def parse_xml(pdf):
    """→ pages: [{n, w, h, frags:[Frag], imgs:[{top,left,w,h}]}] (pdftohtml масштабирует pt ×1.5)."""
    tmp = Path(tempfile.mkdtemp(prefix='docqc_xml_'))
    try:
        subprocess.run(['pdftohtml', '-xml', '-q', '-nodrm', str(pdf), str(tmp / 't')],
                       capture_output=True, check=True)
        raw = (tmp / 't.xml').read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    raw = re.sub(rb'[\x00-\x08\x0b\x0c\x0e-\x1f]', b'', raw)
    root = ET.fromstring(raw)
    pages = []
    for pg in root.iter('page'):
        n = int(pg.get('number'))
        frags = [Frag(n, el) for el in pg.iter('text')]
        imgs = [{'page': n, 'top': int(el.get('top')), 'left': int(el.get('left')),
                 'w': int(el.get('width')), 'h': int(el.get('height'))} for el in pg.iter('image')]
        frags = [f for f in frags if f.text.strip() or f.text]        # пустые фрагменты-отступы нужны для строк
        pages.append({'n': n, 'w': int(pg.get('width')), 'h': int(pg.get('height')),
                      'frags': sorted(frags, key=lambda f: (f.top, f.left)), 'imgs': imgs})
    return pages


def find_columns(pages):
    """Границы колонок по строке-шапке «№ | ⏱ TC | | ТЗ монтажёру | Материал / ссылки»."""
    for pg in pages:
        for mat in pg['frags']:
            if not clean(mat.text).startswith(TZ_HDR[4].split(' ')[0]):               # 'Материал' / 'Material'
                continue
            same = [f for f in pg['frags'] if abs(f.top - mat.top) <= LINE_TOL]
            tz = next((f for f in same if clean(f.text).startswith(TZ_HDR[3])), None)  # 'ТЗ монтажёру' / 'Edit notes'
            tc = next((f for f in same if clean(f.text) in ('⏱ TC', 'TC', '⏱')), None)
            if tz:
                x_tc = tc.left - 4 if tc else tz.left - 90
                return {'x_tc': x_tc, 'x_tz': tz.left - 6, 'x_mat': mat.left - 6, 'page': pg['n'], 'top': tz.top}
    # запасной вариант — пропорции WIDTHS сборщика [34, 62, 22, 282, 276] от левого края картинок
    lefts = [i['left'] for pg in pages for i in pg['imgs']]
    if not lefts:
        raise SystemExit('не нашёл ни шапки таблицы, ни картинок — это не вкладка ТЗ?')
    x_mat = min(lefts) - 6
    return {'x_tc': x_mat - 6 - (282 + 22 + 62) * 1.5, 'x_tz': x_mat - 6 - 282 * 1.5, 'x_mat': x_mat,
            'page': None, 'top': None}


def col_of(f, cols):
    if f.left >= cols['x_mat']:
        return 'mat'
    if f.left >= cols['x_tz']:
        return 'tz'
    if f.left >= cols['x_tc']:
        return 'tc'
    return 'num'


def group_lines(frags):
    """фрагменты одной колонки → физические строки (по top с допуском), текст слева направо."""
    lines = []
    for f in sorted(frags, key=lambda f: (f.top, f.left)):
        if lines and abs(f.top - lines[-1]['top']) <= LINE_TOL:
            lines[-1]['frags'].append(f)
        else:
            lines.append({'top': f.top, 'frags': [f]})
    out = []
    for ln in lines:
        fs = sorted(ln['frags'], key=lambda f: f.left)
        text, prev = '', None
        for f in fs:
            if prev is not None and f.left - prev.right >= 4 and not text.endswith(' ') and not f.text.startswith(' '):
                text += ' '
            text += f.text
            prev = f
        out.append({'top': ln['top'], 'left': fs[0].left, 'bottom': max(f.top + f.h for f in fs),
                    'text': text.rstrip('\n'), 'bold': any(f.bold for f in fs), 'page': fs[0].page})
    return out


def read_rows(pages, cols):
    """Строки таблицы: ТЗ-NN (номер может быть перенесён «ТЗ-0» + «1») и главы «[N. …]».
    → rows: [{kind, num|label, page, top, lines:{tz:[], mat:[], num:[]}, imgs:[], pages:set}], head_lines"""
    rows, head = [], {'tz': [], 'mat': [], 'imgs': []}
    cur = None
    wrapped = 0
    for pg in pages:
        frags = pg['frags']
        # шапка вкладки: всё до строки-шапки таблицы (включительно) — одной колонкой, без деления по x
        if cols['page'] is not None and pg['n'] <= cols['page']:
            lim = cols['top'] + LINE_TOL if pg['n'] == cols['page'] else 10 ** 9
            head['tz'] += group_lines([f for f in frags if f.top <= lim])
            head['imgs'] += [im for im in pg['imgs'] if im['top'] + im['h'] // 2 <= lim]
            frags = [f for f in frags if f.top > lim]
        bycol = {'num': [], 'tc': [], 'tz': [], 'mat': []}
        for f in frags:
            bycol[col_of(f, cols)].append(f)
        lines = {c: group_lines(v) for c, v in bycol.items()}
        starts = []                                         # (top, kind, value)
        numl = lines['num']
        i = 0
        while i < len(numl):
            t = clean(numl[i]['text'])
            m = re.match(rf'^{re.escape(TZ_PREFIX)}-(\d{{1,2}})$', t)
            if m and len(m.group(1)) == 2:
                starts.append((numl[i]['top'], 'tz', f'{TZ_PREFIX}-{m.group(1)}'))
            elif m and i + 1 < len(numl) and re.match(r'^\d$', clean(numl[i + 1]['text'])) \
                    and numl[i + 1]['top'] - numl[i]['top'] <= 18:
                starts.append((numl[i]['top'], 'tz', f'{TZ_PREFIX}-{m.group(1)}{clean(numl[i + 1]["text"])}'))
                wrapped += 1
                i += 1
            i += 1
        tzl = lines['tz']
        for k, ln in enumerate(tzl):
            # строка главы «[N. ИМЯ · M:SS–M:SS]» — жирность в PDF задана шрифтом, без <b>; длинное имя переносится
            if re.match(r'^\[\d+\.\s', ln['text'].strip()):
                joined = ' '.join(x['text'].strip() for x in tzl[k:k + 3])
                m = re.match(r'^(\[\d+\.\s.*?·\s*\d{1,3}:\d\d\s*[–-]\s*\d{1,3}:\d\d\])', joined)
                if m:
                    starts.append((ln['top'], 'ch', clean(m.group(1))))
        starts.sort()

        def row_for(top):
            r = cur_page_cur
            for s_top, _, _ in starts:
                if top >= s_top - LINE_TOL:
                    r = start_rows[s_top]
            return r

        start_rows = {}
        cur_page_cur = cur
        for s_top, kind, val in starts:
            row = {'kind': kind, 'num': val if kind == 'tz' else None, 'label': val if kind == 'ch' else None,
                   'page': pg['n'], 'top': s_top, 'lines': {'tz': [], 'mat': [], 'num': []}, 'imgs': [],
                   'pages': {pg['n']}, 'first_page_tz_lines': 0}
            rows.append(row)
            start_rows[s_top] = row
        for c in ('tz', 'mat', 'num'):
            for ln in lines[c]:
                r = row_for(ln['top'])
                if r is None:
                    if c in ('tz', 'mat'):
                        head[c].append(ln)
                    continue
                r['lines'][c].append(ln)
                r['pages'].add(pg['n'])
        for im in pg['imgs']:
            if cols['page'] is not None and pg['n'] <= cols['page'] and im['top'] + im['h'] // 2 <= (cols['top'] + LINE_TOL if pg['n'] == cols['page'] else 10 ** 9):
                continue                                    # картинка шапки уже учтена
            r = row_for(im['top'] + im['h'] // 2)           # по центру: карточка главы выше строки-метки главы
            if r is not None:
                r['imgs'].append(im)
                r['pages'].add(pg['n'])
            else:
                head['imgs'].append(im)
        for row in start_rows.values():
            row['first_page_tz_lines'] = sum(1 for ln in row['lines']['tz'] if ln['page'] == row['page'])
        if starts:
            cur = start_rows[starts[-1][0]]
        pg['lines'] = lines
    return rows, head, wrapped


# ── абзацы: физические строки → логические (label/▸/•/таймкод/отступ = новый абзац) ──
def is_para_start(text):
    s = text.lstrip(' \u2007\u00a0')
    if not s:
        return False
    if s[0] in LABELS or s.startswith(('▸', '•', '【', '[', '🔗', '📁', '🚫')):
        return True
    if TCR.match(s.lstrip('@')):
        return True
    return len(text) - len(s) >= 3          # отступ ≥3 пробелов — подпункт/элемент блока


def paragraphs(lines, head=False):
    out = []
    for ln in lines:
        t = ln['text']
        if not t.strip():
            continue
        if out and not is_para_start(t) and not (head and ln['bold']):
            out[-1]['text'] += ' ' + t.strip()
            out[-1]['n'] += 1
        else:
            out.append({'text': t.strip(), 'page': ln['page'], 'top': ln['top'], 'n': 1})
    for p in out:
        p['text'] = re.sub(r'[ \u2007\u00a0]{2,}', ' ', p['text'])
    return out


def strip_quotes(t):
    t = URL_RE.sub(' ', t)
    t = QUOTE_RE.sub('«»', t)
    # незакрытая цитата (перенос через страницу): всё после « — цитата; незакрытая » — всё до неё
    t = re.sub(r'«[^»]*$', '«', t)
    t = re.sub(r'^[^«]*»', '»', t)
    if LANG == 'en':                                          # те же правила для “…”
        t = re.sub(r'“[^”]*$', '“', t)
        t = re.sub(r'^[^“]*”', '”', t)
    return t


# ── проверки ──────────────────────────────────────────────────────────────
class QC:
    def __init__(self):
        self.issues = []

    def add(self, page, tz, sev, crit, what):
        self.issues.append({'page': page, 'tz': tz, 'severity': sev, 'criterion': crit, 'what': clean(what)[:220]})


def check_text(qc, tz, lines_tz, lines_mat, sev_high='high', is_head=False):
    hi = 'low' if is_head else sev_high
    for ln in lines_tz + lines_mat:
        t = ln['text']
        s = t.lstrip(' \u2007\u00a0')
        if is_head and s.startswith(TZ_HDR[0]):                         # \u0441\u0442\u0440\u043e\u043a\u0430-\u0448\u0430\u043f\u043a\u0430 \u0442\u0430\u0431\u043b\u0438\u0446\u044b ('\u2116' / '#')
            continue
        if '▸ ▸' in re.sub(r'[ \u2007\u00a0]+', ' ', s) or '▸▸' in s:
            qc.add(ln['page'], tz, hi, 'garbage', '«▸ ▸»: ' + s)
        body = URL_RE.sub('', s)
        for m in re.finditer(r'\S([ ]{2,})\S', body):
            before = body[:m.start() + 1]
            if re.search(r'\d:\d\d(?:[–-]\d{1,2}:\d\d)?$', before):      # выравнивание таймкода цифровыми пробелами
                continue
            qc.add(ln['page'], tz, 'low', 'double_space', s)
            break
        nq = strip_quotes(body)                                   # «Copy ТЗ @ playhead» — имя кнопки в кавычках
        if re.search(r'(?<![\w.])@(?![\w-]+\.\w)', nq) and not re.search(r'\S+@\S+\.\S+', nq):
            qc.add(ln['page'], tz, 'low', 'garbage', '«@»: ' + s)
        for rx in JARGON:
            if rx.search(body):
                qc.add(ln['page'], tz, 'low', 'jargon', s)
                break
    for pa in paragraphs(lines_tz, head=is_head):
        t = pa['text']
        s = t.lstrip('@')
        if s.startswith(('💬', '❓')) or (is_head and s.startswith(TZ_HDR[0])):
            continue
        n_tc = len(TCR.findall(URL_RE.sub('', s)))
        if n_tc >= 2:
            qc.add(pa['page'], tz, hi, 'multi_tc', f'{n_tc} таймкода в строке: {s}')
        q = strip_quotes(s)
        q = re.sub(r'«»(\s*/\s*«»)+', '«»', q)                    # «строка титра» / «вторая строка» — цитата в две строки
        if not WASNOW_RE.search(s):                                # «было «…» → стало» / “was “…” → now”
            q_out = re.sub(r'\([^()]*\)', '()', q)                  # « / » только внутри скобок — координаты, пояснение → low
            for name, rx in ENUM_PATTERNS:
                n_hit = len(rx.findall(q))
                if not n_hit:
                    continue
                sev = hi
                if name == ' → ' and n_hit < 2:                      # одиночная стрелка-следствие, не цепочка шагов
                    sev = 'low'
                elif name == ' / ' and not rx.search(q_out):
                    sev = 'low'
                if s.startswith(('📚', '🎬')):                        # источники и слои таймлайна — справка, не действие
                    sev = 'low'
                qc.add(pa['page'], tz, sev, 'enumeration', f'«{name.strip()}»: {s}')
                break
        if re.search(r'\S;\s', q):
            qc.add(pa['page'], tz, 'low', 'semicolon', s)
        if s.endswith('…') and not s.endswith('…»') and not s.startswith('【'):
            qc.add(pa['page'], tz, 'low', 'trailing_ellipsis', s)
        if (len(s) > LONG_PARA and not s.startswith(('📚', '🎬', 'http', '▸ http', '【'))
                and not is_head):
            qc.add(pa['page'], tz, hi, 'long_paragraph', f'{len(s)} зн.: {s}')


def check_row(qc, row, pages_by_n, n_pages):
    tz = row['num']
    lt, lm = row['lines']['tz'], row['lines']['mat']
    check_text(qc, tz, lt, lm)
    text_all = '\n'.join(ln['text'] for ln in lt)
    if not ('✅' in text_all or DO_LABEL in text_all):
        qc.add(row['page'], tz, 'high', 'no_do', 'нет блока ✅ СДЕЛАТЬ')
    # сирота: на первой странице строки ≤ ORPHAN_LINES строк текста, а сама строка продолжается дальше
    cont = len(row['pages']) > 1
    if cont and row['first_page_tz_lines'] <= ORPHAN_LINES:
        qc.add(row['page'], tz, 'high', 'orphan_header',
               f'заголовок ТЗ в последних строках стр. {row["page"]} ({row["first_page_tz_lines"]} строк), текст на стр. {row["page"] + 1}')
    # подписи под картинками
    for im in row['imgs']:
        bottom = im['top'] + im['h']
        below = [ln for ln in lm if ln['page'] == im['page'] and ln['top'] >= bottom - LINE_TOL]
        cand = min(below, key=lambda ln: ln['top']) if below else None
        if cand is None or cand['top'] - bottom > CAP_GAP:
            # картинка у нижнего края — подпись могла уехать на следующую страницу
            nxt = [ln for ln in lm if ln['page'] == im['page'] + 1]
            nl = min(nxt, key=lambda ln: ln['top']) if nxt else None
            if nl and CAP_RE.match(nl['text'].strip()) and bottom > pages_by_n[im['page']]['h'] - 120:
                qc.add(im['page'], tz, 'low', 'caption_split_page', f'подпись на следующей странице: {nl["text"]}')
                continue
            qc.add(im['page'], tz, 'high', 'caption_missing', 'под картинкой нет строки-подписи')
            continue
        ct = cand['text'].strip()
        if not CAP_RE.match(ct):
            qc.add(im['page'], tz, 'high', 'caption_missing', f'под картинкой не «таймкод · что видно»: {ct}')
        elif len(ct) > 110:
            qc.add(im['page'], tz, 'low', 'caption_long', ct)


def check_images(qc, pdf, rows, pages, n_expected):
    """pdfimages -list (число/ширина) + pdfimages -png (пустые/чёрные). Сопоставление с ТЗ — по порядку на странице."""
    lst = run(['pdfimages', '-list', str(pdf)]).splitlines()[2:]
    entries = []
    for ln in lst:
        c = ln.split()
        if len(c) < 12:
            continue
        entries.append({'page': int(c[0]), 'num': int(c[1]), 'type': c[2], 'w': int(c[3]), 'h': int(c[4]),
                        'obj': c[10]})
    imgs = [e for e in entries if e['type'] == 'image']
    if len(imgs) < n_expected:
        qc.add(0, '*', 'high', 'images_fewer', f'картинок в PDF {len(imgs)} < ожидаемых {n_expected} (главы + материалы с картинкой)')
    # какому ТЗ принадлежит k-я картинка страницы (порядок в XML = порядок в потоке PDF)
    owner = {}
    for pg in pages:
        k = 0
        for row in rows:
            for im in row['imgs']:
                if im['page'] == pg['n']:
                    owner[(pg['n'], k)] = row['num'] or row['label']
                    k += 1
    per_page = {}
    for e in imgs:
        e['k'] = per_page.get(e['page'], 0)
        per_page[e['page']] = e['k'] + 1
        e['tz'] = owner.get((e['page'], e['k']), '?')
        if e['w'] < MIN_IMG_W_PX:
            qc.add(e['page'], e['tz'], 'low', 'image_small', f'картинка {e["w"]}×{e["h"]} px (< {MIN_IMG_W_PX})')
    # пиксели
    tmp = Path(tempfile.mkdtemp(prefix='docqc_img_'))
    stats = {'checked': 0, 'uniform': 0, 'dark': 0}
    try:
        # -j: JPEG-потоки пишутся как есть (перекодирование 63 картинок в PNG — 55 с, так — 2 с); остальное PNG
        subprocess.run(['pdfimages', '-j', '-png', '-p', str(pdf), str(tmp / 'i')], capture_output=True, check=True)
        from PIL import Image
        import numpy as np

        def path_of(e):
            for ext in ('png', 'jpg', 'ppm', 'pbm'):
                f = tmp / f'i-{e["page"]:03d}-{e["num"]:03d}.{ext}'
                if f.exists():
                    return f
            return None

        by_num = {e['num']: e for e in entries}
        for e in imgs:
            f = path_of(e)
            if f is None:
                continue
            im = Image.open(f).convert('RGB')
            sm = by_num.get(e['num'] + 1)
            if sm and sm['type'] == 'smask' and sm['obj'] == e['obj']:
                fm = path_of(sm)
                if fm is not None:
                    a = Image.open(fm).convert('L').resize(im.size)
                    white = Image.new('RGB', im.size, (255, 255, 255))
                    im = Image.composite(im, white, a)
            im.thumbnail((400, 400))
            arr = np.asarray(im.convert('L'), dtype=np.float32)
            stats['checked'] += 1
            if arr.std() < IMG_STD_MIN:
                stats['uniform'] += 1
                qc.add(e['page'], e['tz'], 'high', 'image_uniform', f'картинка однотонная (std {arr.std():.1f}, mean {arr.mean():.0f})')
            elif arr.mean() < IMG_MEAN_DARK:
                stats['dark'] += 1
                qc.add(e['page'], e['tz'], 'high', 'image_dark', f'картинка почти чёрная (mean {arr.mean():.0f})')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {'n_images': len(imgs), 'n_expected': n_expected, 'min_w': min((e['w'] for e in imgs), default=0), **stats}


def contact_sheet(pdf, out, n_pages):
    from PIL import Image, ImageDraw
    tmp = Path(tempfile.mkdtemp(prefix='docqc_cs_'))
    try:
        subprocess.run(['pdftoppm', '-r', '28', '-png', str(pdf), str(tmp / 'p')], capture_output=True, check=True)
        files = sorted(tmp.glob('p-*.png'))
        outs = []
        for si in range(0, len(files), 16):
            chunk = files[si:si + 16]
            ims = [Image.open(f).convert('RGB') for f in chunk]
            tw = max(i.width for i in ims)
            th = max(i.height for i in ims)
            cols = 4
            rows_n = (len(ims) + cols - 1) // cols
            sheet = Image.new('RGB', (cols * (tw + 8) + 8, rows_n * (th + 8) + 8), (60, 60, 60))
            d = ImageDraw.Draw(sheet)
            for k, im in enumerate(ims):
                x, y = 8 + (k % cols) * (tw + 8), 8 + (k // cols) * (th + 8)
                sheet.paste(im, (x, y))
                d.rectangle((x, y, x + 34, y + 16), fill=(200, 30, 30))
                d.text((x + 4, y + 2), str(si + k + 1), fill='white')
            if sheet.width > 1568:
                sheet = sheet.resize((1568, int(sheet.height * 1568 / sheet.width)))
            p = Path(out) if si == 0 else Path(out).with_name(f'{Path(out).stem}_{si // 16 + 1}{Path(out).suffix}')
            sheet.save(p, quality=80)
            outs.append(str(p))
        return outs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── main ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--tab', help='имя вкладки (по умолчанию tab_title карточки)')
    ap.add_argument('--pdf', help='готовый PDF вместо экспорта')
    ap.add_argument('--no-export', action='store_true', help='взять прошлый экспорт W6/doc_qc/tab.pdf')
    ap.add_argument('--contact-sheet', metavar='OUT.jpg', help='миниатюры страниц 4×4 (≤1568 px)')
    ap.add_argument('--out', help='куда писать отчёт (по умолчанию W6/doc_qc.json)')
    a = ap.parse_args()
    t0 = time.time()
    for tool in ('pdftohtml', 'pdftotext', 'pdfimages', 'pdftoppm'):
        if not shutil.which(tool):
            raise SystemExit(f'нет {tool} — brew install poppler')
    title = a.tab or P.get('tab_title') or str(P.profile('doc.tab_tz_template', T('c2.tz_tab_template'))).format(ver=P.CUT_VERSION)
    qdir = W6 / 'doc_qc'
    qdir.mkdir(parents=True, exist_ok=True)
    if a.pdf:
        pdf = Path(a.pdf)
    else:
        pdf = qdir / 'tab.pdf'
        if not a.no_export:
            export_tab(title, pdf)
            print(f'экспорт «{title}» → {pdf} ({pdf.stat().st_size // 1024} КБ)', flush=True)
    if not pdf.exists():
        raise SystemExit(f'нет {pdf}')

    pr = json.load(open(M / 'pravki_v2.json', encoding='utf-8'))['all']
    act = [(tz_label(i + 1), p) for i, p in enumerate(pr) if p.get('status') != 'rejected']     # как в doc_tab_tz_v3
    shots = json.load(open(M / 'shots_ids.json', encoding='utf-8')) if (M / 'shots_ids.json').exists() else {}
    n_ch = len(P.CHAPTERS)
    n_expected_imgs = sum(1 for _ in (P.get('ch_img') or {})) + sum(
        1 for _, p in act for it in (p.get('material_rich') or []) if (it.get('preview') or it.get('img')) in shots)

    pages = parse_xml(pdf)
    n_pages = len(pages)
    pages_by_n = {pg['n']: pg for pg in pages}
    cols = find_columns(pages)
    rows, head, wrapped = read_rows(pages, cols)
    qc = QC()

    # шапка вкладки — те же проверки текста, но low
    check_text(qc, 'шапка', head['tz'], head['mat'], is_head=True)

    tz_rows = [r for r in rows if r['kind'] == 'tz']
    ch_rows = [r for r in rows if r['kind'] == 'ch']
    for row in tz_rows:
        check_row(qc, row, pages_by_n, n_pages)
    for row in ch_rows:
        # глава последней строкой страницы — «висячая» шапка главы (следующее ТЗ начинается с новой страницы)
        same_page_after = [r for r in rows if r['page'] == row['page'] and r['top'] > row['top']]
        if not same_page_after and row['page'] < n_pages:
            qc.add(row['page'], row['label'][:40], 'low', 'orphan_chapter', 'строка главы последней на странице')
    if wrapped:
        qc.add(tz_rows[0]['page'] if tz_rows else 0, '*', 'low', 'tz_num_wrapped',
               f'номер ТЗ переносится «ТЗ-0 / 1» в {wrapped} строках — колонка № уже текста')

    # набор и порядок ТЗ
    got = [r['num'] for r in tz_rows]
    exp = [n for n, _ in act]
    dup = sorted({n for n in got if got.count(n) > 1})
    miss = sorted(set(exp) - set(got))
    extra = sorted(set(got) - set(exp))
    if dup:
        qc.add(0, '*', 'high', 'tz_set', f'ТЗ повторяются: {dup}')
    if miss:
        qc.add(0, '*', 'high', 'tz_set', f'нет строк ТЗ: {miss}')
    if extra:
        qc.add(0, '*', 'high', 'tz_set', f'лишние строки ТЗ (нет в pravki или rejected): {extra}')
    sec_of = {n: tc_sec(str(p.get('v1_tc', '')).split('–')[0].split('/')[0]) for n, p in act}
    prev = None
    for r in tz_rows:
        s = sec_of.get(r['num'])
        if s is None:
            continue
        if prev is not None and s < prev[1]:
            qc.add(r['page'], r['num'], 'high', 'tz_order', f'{r["num"]} ({s // 60}:{s % 60:02d}) стоит после {prev[0]} ({prev[1] // 60}:{prev[1] % 60:02d})')
        prev = (r['num'], s)
    if len(ch_rows) != n_ch:
        qc.add(0, '*', 'low', 'chapters', f'строк глав {len(ch_rows)}, в карточке {n_ch}')

    # страницы
    n_tz = len(act)
    lo, hi = int(PAGES_PER_TZ[0] * n_tz + PAGES_ADD[0]), int(PAGES_PER_TZ[1] * n_tz + PAGES_ADD[1])
    if not lo <= n_pages <= hi:
        qc.add(0, '*', 'high', 'page_count', f'страниц {n_pages}, ожидали {lo}–{hi} для {n_tz} ТЗ')

    # картинки
    img_stats = check_images(qc, pdf, rows, pages, n_expected_imgs)

    # контрольный текст (pdftotext) — на диск, для глаз
    (qdir / 'tab.txt').write_text(run(['pdftotext', '-layout', str(pdf), '-']), encoding='utf-8')

    sheets = contact_sheet(pdf, a.contact_sheet, n_pages) if a.contact_sheet else []

    # отчёт
    counts = {'high': sum(1 for i in qc.issues if i['severity'] == 'high'),
              'low': sum(1 for i in qc.issues if i['severity'] == 'low'),
              'by_criterion': {}, 'tz_rows': len(tz_rows), 'ch_rows': len(ch_rows), 'n_tz': n_tz, **img_stats}
    for i in qc.issues:
        c = counts['by_criterion'].setdefault(i['criterion'], {'high': 0, 'low': 0})
        c[i['severity']] += 1
    tz_with_issues = sorted({i['tz'] for i in qc.issues if i['tz'].startswith(TZ_PREFIX + '-')})
    counts['tz_with_issues'] = len(tz_with_issues)
    rep = {'schema': 'doc-qc-v1', 'project': P.PROJECT, 'tab': title, 'pdf': str(pdf), 'pages': n_pages,
           'columns': cols, 'issues': sorted(qc.issues, key=lambda i: (i['severity'] != 'high', i['page'], i['tz'])),
           'counts': counts, 'contact_sheets': sheets, 'took_sec': round(time.time() - t0, 1)}
    out = Path(a.out) if a.out else W6 / 'doc_qc.json'
    P.write_json_atomic(out, rep)

    lines = [f'[doc_pdf_qc] {P.CODE} «{title}»: страниц {n_pages} · строк ТЗ {len(tz_rows)}/{n_tz} · глав {len(ch_rows)}/{n_ch} · '
             f'картинок {img_stats["n_images"]} (ожидали ≥{n_expected_imgs}, мин. ширина {img_stats["min_w"]} px)',
             f'замечаний: {len(qc.issues)} (high {counts["high"]}, low {counts["low"]}) · ТЗ с замечаниями: {len(tz_with_issues)}']
    for crit, c in sorted(counts['by_criterion'].items(), key=lambda kv: (-kv[1]['high'], -kv[1]['low'])):
        lines.append(f'  {crit:<20} high {c["high"]:<3} low {c["low"]}')
    ex = [i for i in rep['issues'] if i['severity'] == 'high'][:5] or rep['issues'][:5]
    if ex:
        lines.append('примеры:')
        lines += [f'  стр.{i["page"]} {i["tz"]} [{i["criterion"]}] {i["what"][:110]}' for i in ex]
    lines.append(f'→ {out}' + (f' · листы: {", ".join(sheets)}' if sheets else '') + f' · {rep["took_sec"]} с')
    summary = '\n'.join(lines)
    print(summary[:2000], flush=True)
    sys.exit(0 if counts['high'] == 0 else 2)


if __name__ == '__main__':
    main()
