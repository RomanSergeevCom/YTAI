#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка вкладки «Обратная связь · vN» (stages/doc_tab_feedback_v1.py, 6 колонок по §8) — офлайн по дампу или по живому доку.

Зачем: вкладку читает монтажёр, и ошибка в ней стоит дороже ошибки в коде — вердикт не той краской, пропавшее
«▶ СДЕЛАТЬ», секция с неверным счётчиком, картинка без подписи или без источника, стиль, съехавший на соседние
буквы из-за эмодзи. Проверка не доверяет сборщику на слово: она заново строит ожидаемые строки из модели
(build_rows) и сверяет с тем, что реально лежит в документе, а диапазоны и цвета стилей берёт из отправленных запросов.

    doc_tab_feedback_v1_verify.py [--fb PATH] --from-dump FILE     офлайн: дамп от --dump-requests (индекс визуалов и
                                                                   речь — из дампа)
    doc_tab_feedback_v1_verify.py [--fb PATH]                      живой док по карточке (читает вкладку по имени; индекс
                                                                   визуалов — work/{cut}/feedback_visuals/index.json, речь —
                                                                   said.py; если во вкладке есть кадры — ещё и ревизор доступов)
    doc_tab_feedback_v1_verify.py --selftest

Печатает по строке на проверку (PASS / WARN / FAIL), в конце — «ALL PASS» либо «FAIL: …»; код возврата ≠ 0 при FAIL.
У каждого FAIL пометка, чья это ошибка: [вкладка] — сборщика или записи, [модель] — дефект текста в feedback.json
(его чинит модель, а не вкладка: две и больше меток времени в строке, слова движка, время длиннее ката),
[визуалы] — слой визуалов не дал картинку «как надо» полной строке.

Что проверяется: одна таблица · ширины [40, 44, 104, 168, 160, 160] = 676 pt · секции и их счётчики против общего
слоя · у каждой полной строки: вердикт первой строкой из разрешённого набора и тем цветом (по запросам дампа),
【заголовок】, «Почему:» с текстом, «▶ СДЕЛАТЬ ·» в колонке «Как надо», № и таймкод, речь в «Говорит» (когда она есть)
· картинки: только в колонках 5–6, в своём абзаце, ≥140 pt (минимум ЭТОЙ вкладки, не канона), подпись по шаблону
канона, под картинкой «как надо» — «Источник:», картинка «как надо» у каждой полной строки · правило «один таймкод
в строке» (FAIL для Части 1 и строк, порождённых кодом; WARN со счётчиком для цитат прошлого ТЗ; речь не считается)
· посимвольная сверка каждой ячейки и шапки · границы стилей не режут суррогатную пару и не выходят за ячейку ·
в шапке версия ката и дата-время сборки · нет таймкодов длиннее ката · нет слов движка.
Карточка фильма читается только внутри main().
"""
import argparse
import copy
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SHARED = ROOT / 'shared'
for _p in (SHARED, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import i18n  # noqa: E402
import feedback_view as V  # noqa: E402
import tz_blocks as TB  # noqa: E402
import doc_table as DT  # noqa: E402
import doc_tab_feedback_v1 as B  # noqa: E402

# шаблон подписи под кадром — КОПИЯ stages/doc_pdf_qc.py:59 (сам модуль не импортируем: он при импорте читает
# карточку фильма и тянет doc_tab_tz_v3). Держать в синхроне; --selftest сверяет копию с текстом оригинала.
CAP_RE = re.compile(r'^(?:\d{1,2}:\d{2}(?:[–-]\d{1,2}:\d{2})?|сводно)\s·\s\S')
SEC_RE = re.compile(r'^\[(.+) · (\d+)\]$')
MIN_IMG_W = B.MIN_IMG_W                             # 140: минимум этой вкладки (канон 5.6 просит 250 — шесть колонок не дают)
SHOW = 12                                           # сколько строк одной проверки печатать
IMG_COLS = (B.C_ERR, B.C_FIX)
_PATH_RE = re.compile(r'\S*/\S+|\S+\.(?:png|jpe?g|webp)\b')   # путь к файлу в строке «Источник:» (§9)
# поля модели, которые читателю не печатаются (для разбора «чья ошибка»)
SERVICE_KEYS = frozenset(('schema', 'key', 'prev_file', 'status', 'status_by', 'how', 'bucket', 'category', 'severity',
                          'align', 'thresholds', 'frames_wanted', 'file', 'kind', 'checks', 'agent_note', 'topic'))


# ═══════════════════ документ → удобный вид ═══════════════════
def find_tab(doc, title):
    tabs = [t for t in DT.iter_tabs(doc) if t['tabProperties'].get('title') == title]
    if len(tabs) != 1:
        raise SystemExit(f'вкладок с именем «{title}» в документе: {len(tabs)} (нужна ровно одна)')
    return tabs[0]


def doc_view(tab):
    """вкладка из get_doc → {'head': [абзацы до таблицы], 'tables': n, 'grid': [[ячейка]], 'edges', 'inside'}.
    Ячейка: text (без хвостового перевода строки), paras [{text, imgs, n_el}], a/b — границы содержимого.
    Индексы приведены к состоянию ДО вставки картинок (каждая картинка сдвигает всё после себя на 1): диапазоны
    стилей в запросах считались именно тогда. edges — допустимые границы диапазона, inside — середины суррогатных пар."""
    view = {'head': [], 'tables': 0, 'grid': [], 'edges': set(), 'inside': set(), 'imgs': 0, 'img_ids': []}
    shift = [0]

    def paragraph(c):
        text, imgs, n_el = '', [], 0
        for e in c['paragraph'].get('elements', []):
            n_el += 1
            if 'textRun' in e:
                i = e['startIndex'] - shift[0]
                for ch in e['textRun'].get('content', ''):
                    w = 2 if ord(ch) > 0xFFFF else 1
                    view['edges'].update((i, i + w))
                    if w == 2:
                        view['inside'].add(i + 1)
                    i += w
                text += e['textRun'].get('content', '')
            elif 'inlineObjectElement' in e:
                imgs.append(e['inlineObjectElement'].get('inlineObjectId'))
                view['img_ids'].append(imgs[-1])
                shift[0] += 1
        return {'text': text, 'imgs': imgs, 'n_el': n_el}

    for c in tab['documentTab']['body']['content']:
        if 'paragraph' in c:
            p = paragraph(c)
            if not view['tables']:
                view['head'].append(p['text'].rstrip('\n'))
        elif 'table' in c:
            view['tables'] += 1
            if view['tables'] > 1:
                continue
            view['table_style'] = c['table'].get('tableStyle') or {}
            for row in c['table'].get('tableRows', []):
                cells = []
                for cell in row.get('tableCells', []):
                    content = [x for x in cell.get('content', []) if 'paragraph' in x]
                    a = (content[0]['startIndex'] - shift[0]) if content else None
                    paras = [paragraph(x) for x in content]
                    text = ''.join(p['text'] for p in paras)
                    cells.append({'text': text[:-1] if text.endswith('\n') else text, 'paras': paras,
                                  'a': a, 'b': cell.get('endIndex', 0) - shift[0]})
                view['grid'].append(cells)
    while view['head'] and view['head'][-1] == '':          # пустой абзац перед таблицей — служебный
        view['head'].pop()
    view['imgs'] = len(view['img_ids'])
    return view


# ═══════════════════ проверки ═══════════════════
class Report:
    def __init__(self):
        self.lines, self.fails, self.warns = [], [], 0

    def ok(self, what):
        self.lines.append(f'PASS  {what}')

    def warn(self, what, items):
        self.warns += len(items)
        self.lines.append(f'WARN  {what}: {len(items)}')
        self.lines += [f'        {x}' for x in items[:SHOW]] + ([f'        … и ещё {len(items) - SHOW}'] if len(items) > SHOW else [])

    def check(self, what, problems):
        """problems — [(чья ошибка: 'вкладка'|'модель'|'визуалы', текст)]"""
        if not problems:
            return self.ok(what)
        self.fails += [(o, what, m) for o, m in problems]
        self.lines.append(f'FAIL  {what}: {len(problems)}')
        self.lines += [f'        [{o}] {m}' for o, m in problems[:SHOW]]
        if len(problems) > SHOW:
            self.lines.append(f'        … и ещё {len(problems) - SHOW}')

    def verdict(self):
        if not self.fails:
            return 'ALL PASS'
        tab = sum(1 for o, _, _ in self.fails if o == 'вкладка')
        vis = sum(1 for o, _, _ in self.fails if o == 'визуалы')
        s = f'FAIL: {len(self.fails)} (вкладка {tab} · модель {len(self.fails) - tab - vis}'
        return s + (f' · визуалы {vis})' if vis else ')')


def _norm(s):
    return ' '.join(str(s or '').replace(TB.FIG, ' ').split())


def _n_tc(s):
    return sum(1 for m in TB.lint_line(s) if m.startswith('таймкодов'))


class Origin:
    """чья ошибка: если дефектная строка целиком пришла из модели (заголовок, блок, действие блокера) — 'модель'"""

    def __init__(self, fb):
        # только ЗНАЧЕНИЯ-строки и только из полей, которые поверхности печатают: имена ключей модели («align»,
        # «status_by», «checks») и служебные значения (key, how, file) — сами слова движка, и по json.dumps всей
        # модели любое такое слово, напечатанное сборщиком, списывалось бы на модель
        vals = []

        def walk(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if k not in SERVICE_KEYS:
                        walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
            elif isinstance(x, str):
                vals.append(x)
        walk(fb)
        self.text = '\n'.join(vals)
        self.two_tc = set()
        strings = []
        for r in (fb.get('part1') or []) + (fb.get('part2') or []):
            strings += [r.get('title'), (r.get('evidence') or {}).get('text')]
            strings += [x for k in ('now', 'do', 'where') for x in ((r.get('parts') or {}).get(k) or [])]
        strings += [b.get('do') for b in (fb.get('blockers') or [])] + [t.get('title') for t in (fb.get('fund_topics') or [])]
        for s in strings:
            if s and len(TB.TC_RE.findall(_norm(s))) >= 2:
                self.two_tc.add(_norm(s)[:40])

    def of_two_tc(self, line):
        n = _norm(line)
        return 'модель' if any(p and p in n for p in self.two_tc) else 'вкладка'

    def of_word(self, word):
        return 'модель' if word and word in self.text else 'вкладка'


def _where(meta, ri):
    if not meta:
        return f'строка {ri}'
    if meta.get('role') in ('item', 'dup'):
        return i18n.tz_label(meta['n']) + ('' if meta.get('part') == 1 else ' · прошлое ТЗ')
    return {'sec': 'секция', 'part2': 'заголовок Части 2', 'list': 'список'}.get(meta.get('role'), '?') + \
        (f' «{meta.get("bucket")}»' if meta.get('bucket') else '')


def _rgb_of(ts):
    return ((ts or {}).get('foregroundColor') or {}).get('color', {}).get('rgbColor')


def verify(fb, tab, *, lang='ru', have=None, tz_tab=None, visuals=None, say=None, batches=None, widths=None,
           img_widths=None, pre=()):
    """→ Report. fb — модель; tab — вкладка из get_doc (или final_doc дампа); visuals / say — индекс визуалов и речь,
    по которым собиралась вкладка; batches — пачки запросов дампа (для живого дока None: диапазоны и цвета стилей тогда
    не проверяются); widths — ширины колонок; img_widths — ширины картинок."""
    rep = Report()
    for o, m in pre:
        rep.check('дамп и модель', [(o, m)])
    exp_rows, exp_head = B.build_rows(fb, lang, have, tz_tab, visuals, say)
    hdr = B.hdr(lang)
    view = doc_view(tab)
    origin = Origin(fb)
    grid = view['grid']
    body = grid[1:]                                         # без строки заголовков колонок
    metas = [r['meta'] for r in exp_rows] if len(body) == len(exp_rows) else [None] * len(body)
    model = {(r.get('part'), r.get('n')): r for r in (fb.get('part1') or []) + (fb.get('part2') or [])}
    old = i18n.set_lang(lang)
    try:
        verdicts = {b: i18n.T(k) for b, (k, _c) in B.VERDICT.items()}
        colors = {'was': DT.RED, 'now': DT.GREEN, 'warn': DT.ORANGE, 'muted': DT.GREY}
        why_label, src_label, do_label = i18n.T('fb.why'), i18n.T('fb.source'), TB.labels(lang)['do'] + ' ·'
        # 1. одна таблица
        rep.check('одна таблица', [] if view['tables'] == 1 else [('вкладка', f'таблиц во вкладке: {view["tables"]}')])

        # 2. ширины
        bad = []
        if widths is None:
            bad.append(('вкладка', 'ширины колонок не найдены'))
        elif sum(widths) != DT.TOTAL_W or list(widths) != B.WIDTHS:
            bad.append(('вкладка', f'ширины {list(widths)} = {sum(widths)} pt, должно быть {B.WIDTHS} = {DT.TOTAL_W}'))
        if len(grid) and len(grid[0]) != len(B.WIDTHS):
            bad.append(('вкладка', f'колонок в таблице {len(grid[0])}, должно быть {len(B.WIDTHS)}'))
        rep.check(f'6 колонок, ширины {B.WIDTHS} = {DT.TOTAL_W} pt', bad)

        # 3. секции: на месте, в порядке общего слоя, n в скобках = числу пунктов модели
        want = []
        for bucket, label, items in V.sections(fb):
            if bucket in V.PART2 and not any(w[0] == 'part2' for w in want):
                want.append(('part2', _norm(i18n.T('fb.part2', prev=fb.get('prev_cut_version') or '')), len(fb.get('part2') or [])))
            want.append((bucket, _norm(label), len(items)))
        got = []
        for ri, row in enumerate(body, start=1):
            first = row[B.C_VERDICT]['text'].split('\n')[0] if len(row) > B.C_VERDICT else ''
            m = SEC_RE.match(first)
            if m and not any(row[c]['text'] for c in (B.C_NUM, B.C_TC, B.C_SAID) if c < len(row)):
                got.append((_norm(m.group(1)), int(m.group(2))))
        bad = []
        if [g[0] for g in got] != [w[1] for w in want]:
            bad.append(('вкладка', f'секции не те или не в том порядке: во вкладке {[g[0] for g in got]}, в модели {[w[1] for w in want]}'))
        else:
            bad += [('вкладка', f'секция «{w[1]}»: в скобках {g[1]}, в модели {w[2]}') for g, w in zip(got, want) if g[1] != w[2]]
        rep.check(f'секции на месте и счётчики совпадают с моделью ({len(want)})', bad)

        # 4. полные строки: вердикт первой строкой (тот и тем цветом), 【заголовок】, «Почему:», ✅ в «Как надо», №, таймкод, речь
        sent = {}
        if batches is not None:
            for q in (q for bt in batches for q in bt):
                if 'updateTextStyle' in q and q['updateTextStyle'].get('range'):
                    r_ = q['updateTextStyle']['range']
                    sent.setdefault((r_['startIndex'], r_['endIndex']), []).append(q['updateTextStyle'].get('textStyle') or {})
        bad, n_items, no_speech = [], 0, []
        if len(body) != len(exp_rows):
            bad.append(('вкладка', f'строк в таблице {len(body)}, по модели должно быть {len(exp_rows)} — пункты не сопоставить'))
        for ri, (row, meta) in enumerate(zip(body, metas), start=1):
            if not meta or meta.get('role') not in ('item', 'list'):
                continue
            who = _where(meta, ri)
            vcell = row[B.C_VERDICT]
            lines = vcell['text'].split('\n')
            want_v = verdicts.get(meta.get('bucket'))
            if lines[0] not in verdicts.values():
                bad.append(('вкладка', f'{who}: первая строка колонки «{hdr[B.C_VERDICT]}» — не вердикт: {lines[0][:50]!r}'))
            elif lines[0] != want_v:
                bad.append(('вкладка', f'{who}: вердикт «{lines[0]}», по секции должен быть «{want_v}»'))
            elif batches is not None and vcell['a'] is not None:
                rng = (vcell['a'], vcell['a'] + DT.u16(lines[0]))
                want_c = colors[B.VERDICT[meta['bucket']][1]]
                # в Docs побеждает ПОСЛЕДНИЙ стиль на диапазон: верный цвет, отправленный раньше чужого, не спасает
                got_c = [_rgb_of(ts) for ts in sent.get(rng, []) if _rgb_of(ts)]
                if not got_c or got_c[-1] != want_c:
                    bad.append(('вкладка', f'{who}: вердикт «{lines[0]}» не тем цветом (отправлено {got_c or "ничего"})'))
            if meta.get('role') != 'item':
                continue
            n_items += 1
            src = model.get((meta.get('part'), meta.get('n'))) or {}
            if len(lines) < 2 or not (lines[1].startswith('【') and lines[1].endswith('】') and len(lines[1]) > 2):
                bad.append(('вкладка', f'{who}: второй строкой нет 【заголовка】'))
            why = next((ln for ln in lines if ln.startswith(why_label)), None)
            if why is None or not why[len(why_label):].strip():
                bad.append(('вкладка', f'{who}: нет строки «{why_label}» с текстом'))
            if do_label not in row[B.C_FIX]['text']:
                no_do = not V.short_blocks(src, fb)['do']
                bad.append(('модель' if no_do else 'вкладка',
                            f'{who}: в колонке «{hdr[B.C_FIX]}» нет блока «{do_label}»' +
                            (' — в модели у пункта нет ни одной строки действия' if no_do else '')))
            if not row[B.C_NUM]['text'].strip():
                bad.append(('вкладка', f'{who}: пустая ячейка №'))
            if not row[B.C_TC]['text'].strip() and V.tc_label(src):
                bad.append(('вкладка', f'{who}: пустой таймкод, а у пункта он есть ({V.tc_label(src)})'))
            speech = ((say or {}).get(f'{meta.get("part")}:{meta.get("n")}') or {}).get('text') or ''
            if speech.strip() and not row[B.C_SAID]['text'].strip():
                bad.append(('вкладка', f'{who}: речь есть, а колонка «{hdr[B.C_SAID]}» пустая'))
            if V.tc_label(src) and not row[B.C_SAID]['text'].strip():
                no_speech.append(who)
        rep.check(f'у полных строк: вердикт первой строкой и тем цветом, 【заголовок】, «{why_label}», «{do_label}» в '
                  f'«{hdr[B.C_FIX]}», №, таймкод, речь ({n_items})', bad)
        if no_speech:
            rep.warn(f'у пункта есть время, а речи в «{hdr[B.C_SAID]}» нет (нет транскрипта или слов в окне)', no_speech)

        # 5. картинки: колонки 5–6, свой абзац, подпись по шаблону, «Источник:» под «как надо», ширина, число, «как надо» у всех
        bad, n_img, fix_rows = [], 0, set()
        for ri, row in enumerate(grid):
            meta = metas[ri - 1] if ri and ri - 1 < len(metas) else None
            for cj, cell in enumerate(row):
                for pi, p in enumerate(cell['paras']):
                    if not p['imgs']:
                        continue
                    n_img += len(p['imgs'])
                    who = _where(meta, ri)
                    if cj not in IMG_COLS:
                        bad.append(('вкладка', f'{who}: картинка в колонке {cj} — можно только в «{hdr[B.C_ERR]}» и «{hdr[B.C_FIX]}»'))
                    if len(p['imgs']) != 1 or p['text'] != '\n' or p['n_el'] != 2:
                        bad.append(('вкладка', f'{who}: картинка не в своём абзаце (рядом текст или вторая картинка)'))
                    cap = cell['paras'][pi + 1]['text'].rstrip('\n') if pi + 1 < len(cell['paras']) else ''
                    if not CAP_RE.match(cap):
                        bad.append(('вкладка', f'{who}: под картинкой нет подписи «таймкод · что видно» (стоит: {cap!r})'))
                    if cj == B.C_FIX:
                        fix_rows.add(ri)
                        src_ln = cell['paras'][pi + 2]['text'].rstrip('\n') if pi + 2 < len(cell['paras']) else ''
                        if not src_ln.startswith(src_label) or not src_ln[len(src_label):].strip():
                            bad.append(('вкладка', f'{who}: под картинкой «{hdr[B.C_FIX]}» нет строки «{src_label} …» (стоит: {src_ln!r})'))
        for ri, meta in enumerate(metas, start=1):
            if meta and meta.get('role') == 'item' and ri not in fix_rows:
                bad.append(('визуалы', f'{_where(meta, ri)}: нет визуала «{hdr[B.C_FIX]}» — картинка-рекомендация обязательна '
                                       f'у каждой полной строки (§8–9)'))
        want_img = sum(len(r['imgs']) for r in exp_rows)
        if n_img != want_img:
            bad.append(('вкладка', f'картинок во вкладке {n_img}, по модели и индексу визуалов должно быть {want_img}'))
        if n_img:
            if img_widths is None or len(img_widths) != n_img:
                bad.append(('вкладка', f'ширины картинок известны для {len(img_widths or [])} из {n_img}'))
            bad += [('вкладка', f'картинка шириной {w} pt — уже {MIN_IMG_W} pt') for w in (img_widths or []) if w < MIN_IMG_W]
        rep.check(f'картинки: колонки 5–6, свой абзац, ≥{MIN_IMG_W} pt, подпись по канону, «{src_label}» под «как надо», '
                  f'«как надо» у каждой полной строки ({n_img})', bad)

        # 6. один таймкод в строке (речь — дословная, не считается)
        bad, soft = [], []
        for ln in view['head']:
            if _n_tc(ln):
                bad.append((origin.of_two_tc(ln), f'шапка: {_norm(ln)[:110]}'))
        for ri, (row, meta) in enumerate(zip(body, metas), start=1):
            quote = bool(meta) and meta.get('role') in ('item', 'dup') and meta.get('part') == 2
            for cj, cell in enumerate(row):
                if cj == B.C_SAID:
                    continue
                for li, ln in enumerate(cell['text'].split('\n')):
                    if not _n_tc(ln):
                        continue
                    msg = f'{_where(meta, ri)}: {_norm(ln)[:110]}'
                    # цитаты прошлого ТЗ: текст пункта Части 2 (у строки-переноса — всё, кроме первой, порождённой кодом)
                    if quote and cj in (B.C_VERDICT, B.C_FIX) and not (meta.get('role') == 'dup' and li == 0):
                        soft.append(msg)
                    else:
                        bad.append((origin.of_two_tc(ln), msg))
        rep.check('один таймкод в строке — Часть 1 и строки, порождённые кодом', bad)
        if soft:
            rep.warn('два и больше таймкодов в строке — цитаты прошлого ТЗ (Часть 2)', soft)

        # 7. посимвольная сверка
        bad = []
        want_cells = [hdr] + [r['cells'] for r in exp_rows]
        for ri, row in enumerate(grid):
            if ri >= len(want_cells):
                break
            for cj, cell in enumerate(row):
                w = want_cells[ri][cj] if cj < len(want_cells[ri]) else ''
                if cell['text'] != w:
                    k = next((i for i, (x, y) in enumerate(zip(cell['text'], w)) if x != y), min(len(cell['text']), len(w)))
                    bad.append(('вкладка', f'{_where(metas[ri - 1] if ri and ri - 1 < len(metas) else None, ri)}, колонка '
                                           f'{cj}: расхождение с {k}-го знака — во вкладке {cell["text"][k:k + 40]!r}, '
                                           f'по модели {w[k:k + 40]!r}'))
        if len(grid) != len(want_cells):
            bad.append(('вкладка', f'строк в таблице {len(grid)}, по модели {len(want_cells)}'))
        want_head = [t for _, t in exp_head]
        if view['head'] != want_head:
            k = next((i for i, (x, y) in enumerate(zip(view['head'], want_head)) if x != y), min(len(view['head']), len(want_head)))
            bad.append(('вкладка', f'шапка расходится с {k + 1}-го абзаца: во вкладке '
                                   f'{(view["head"][k] if k < len(view["head"]) else "—")[:60]!r}, по модели '
                                   f'{(want_head[k] if k < len(want_head) else "—")[:60]!r}'))
        rep.check(f'текст каждой ячейки и шапки совпадает с моделью посимвольно ({sum(len(r) for r in grid)} ячеек)', bad)

        # 8. диапазоны стилей (только дамп)
        if batches is not None:
            bad, n_rng = [], 0
            cells = [c for row in grid for c in row if c['a'] is not None]
            t_a = cells[0]['a'] if cells else 0
            t_b = cells[-1]['b'] if cells else 0
            for q in (q for bt in batches for q in bt):
                (op, val), = q.items()
                rng = val.get('range') if isinstance(val, dict) else None
                if op not in ('updateTextStyle', 'updateParagraphStyle') or not rng:
                    continue
                n_rng += 1
                a, b = rng['startIndex'], rng['endIndex']
                if a in view['inside'] or b in view['inside']:
                    bad.append(('вкладка', f'диапазон стиля ({a}, {b}) режет суррогатную пару (эмодзи)'))
                    continue
                if not a < b or a not in view['edges'] or b not in view['edges']:
                    bad.append(('вкладка', f'диапазон стиля ({a}, {b}) пуст или попал мимо текста'))
                    continue
                if b <= t_a or (a, b) == (t_a, t_b):        # шапка над таблицей · общий сброс оформления таблицы
                    continue
                if not any(c['a'] <= a and b <= c['b'] for c in cells):
                    bad.append(('вкладка', f'диапазон стиля ({a}, {b}) выходит за ячейку'))
            for ri, r in enumerate(exp_rows, start=1):      # каждый спан сборщика дошёл до дока своим диапазоном
                if ri >= len(grid):
                    break
                for cj, spans in r['spans'].items():
                    text, a0 = r['cells'][cj], grid[ri][cj]['a']
                    for sp in spans:
                        s, e, key, url = DT._span4(sp)
                        rng = (a0 + DT.u16(text[:s]), a0 + DT.u16(text[:e]))
                        if DT.span_style(key, B.FONT, url)[0] not in sent.get(rng, []):
                            bad.append(('вкладка', f'{_where(r["meta"], ri)}: стиль «{key}» на «{text[s:e][:30]}» не отправлен '
                                                   f'своим диапазоном {rng}'))
            rep.check(f'границы стилей не режут эмодзи и не выходят за ячейку ({n_rng} диапазонов)', bad)

        # 9. шапка: версия ката и дата-время сборки
        bad = []
        joined = '\n'.join(view['head'])
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2})', str(fb.get('built_at') or ''))
        stamp = f'{m.group(3)}.{m.group(2)}.{m.group(1)} {m.group(4)}' if m else ''
        if not fb.get('cut_version') or str(fb['cut_version']) not in joined:
            bad.append(('вкладка', f'в шапке нет версии ката ({fb.get("cut_version")})'))
        if not stamp:
            bad.append(('модель', f'в модели нет даты сборки built_at ({fb.get("built_at")!r})'))
        elif stamp not in joined:
            bad.append(('вкладка', f'в шапке нет даты и времени сборки ({stamp})'))
        rep.check('в шапке версия ката и дата-время сборки', bad)

        # 10–11. таймкоды не длиннее ката · слов движка нет (речь: только жаргон — время в ней дословное)
        dur = float(fb.get('duration_sec') or 0)
        too_long, jargon = [], []
        lines = [('шапка', ln, False) for ln in view['head']]
        for ri, (row, meta) in enumerate(zip(body, metas), start=1):
            lines += [(_where(meta, ri), ln, cj == B.C_SAID) for cj, cell in enumerate(row) for ln in cell['text'].split('\n')]
        for who, ln, speech in lines:
            # время сборки «собрано 22.09.2026 23:47» — не таймкод: на кате короче 23:47 оно давало ложный FAIL
            scan = ln.replace(stamp, ' ') if stamp else ln
            for mm, ss in ([] if speech else re.findall(r'(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])', scan.replace(TB.FIG, ' '))):
                if dur and int(mm) * 60 + int(ss) > dur + 1:
                    too_long.append(('модель' if origin.of_word(f'{int(mm)}:{ss}') == 'модель' else 'вкладка',
                                     f'{who}: {mm}:{ss} — за концом ката ({int(dur) // 60}:{int(dur) % 60:02d}): {_norm(ln)[:80]}'))
            # строка «Источник: мокап стадии: mockups/tz/tz_03.png» — путь к файлу разрешён контрактом (§9), это не слово
            # движка; сам путь из проверки жаргона вырезаем, остальной текст строки проверяется как обычно
            scan_j = _PATH_RE.sub(' ', ln) if ln.startswith(src_label) else ln
            for rx in V.JARGON:
                j = rx.search(scan_j)
                if j:
                    jargon.append((origin.of_word(j.group(0)), f'{who}: «{j.group(0)}» — {_norm(ln)[:90]}'))
        if not dur:
            too_long.append(('модель', 'в модели нет длительности ката (duration_sec)'))
        rep.check('ни одного таймкода длиннее ката', too_long)
        rep.check('слов движка в видимом тексте нет', jargon)
    finally:
        i18n.set_lang(old)
    return rep


# ═══════════════════ источники ═══════════════════
def from_dump(fb, dump):
    pre = []
    if dump.get('surface') != 'doc_tab_feedback_v1' or 'final_doc' not in dump:
        raise SystemExit('это не дамп вкладки «Обратная связь» (нет final_doc): собери его через '
                         'doc_tab_feedback_v1.py --dump-requests FILE')
    if dump.get('fb_sha') != B.fb_sha(fb):
        pre.append(('вкладка', f'дамп собран из другой модели (отпечаток {dump.get("fb_sha")}, у модели {B.fb_sha(fb)}) — '
                               f'пересобери дамп'))
    batches = dump.get('batches') or []
    flat = [q for bt in batches for q in bt]
    widths = [q['updateTableColumnProperties']['tableColumnProperties']['width']['magnitude']
              for q in flat if 'updateTableColumnProperties' in q]
    img_w = [((q['insertInlineImage'].get('objectSize') or {}).get('width') or {}).get('magnitude', 0)
             for q in flat if 'insertInlineImage' in q]
    tab = find_tab(dump['final_doc'], dump.get('tab_title'))
    have = set(dump.get('frames') or []) if dump.get('images') != 'none' else None
    return verify(fb, tab, lang=dump.get('lang') or 'ru', have=have, tz_tab=dump.get('tz_tab'), visuals=dump.get('visuals'),
                  say=dump.get('say'), batches=batches, widths=widths or None, img_widths=img_w, pre=pre)


def have_from_doc(view, fb, lang='ru', tz_tab=None, visuals=None, say=None):
    """→ {'{part}:{n}/{kind}'} визуалов, которые во вкладке реально стоят: «ошибка» — занята ячейка колонки 5 (картинкой
    или подписью), «как надо» — в колонке 6 есть картинка либо строка «Источник:». Строки вкладки и модели
    сопоставляются по месту; число строк не сошлось → пусто (это отдельно поймает сверка текста)."""
    rows, _head = B.build_rows(fb, lang, None, tz_tab, visuals, say)
    body = view['grid'][1:]
    if len(body) != len(rows):
        return set()
    src_label = i18n.TL(lang, 'fb.source')
    out = set()
    for cells, r in zip(body, rows):
        if r['meta']['role'] != 'item' or len(cells) <= B.C_FIX:
            continue
        key = f'{r["meta"]["part"]}:{r["meta"]["n"]}'
        e, f = cells[B.C_ERR], cells[B.C_FIX]
        if e['text'].strip() or any(p['imgs'] for p in e['paras']):
            out.add(key + '/err')
        if any(p['imgs'] for p in f['paras']) or any(ln.startswith(src_label) for ln in f['text'].split('\n')):
            out.add(key + '/fix')
    return out


def from_live(fb, frames_dir=None):
    """живой док: вкладка по имени из карточки. Только чтение; при кадрах во вкладке — ещё и ревизор доступов."""
    import os
    Bt = B._load_card(optional=False)
    P = Bt.P
    lang = P.LANG
    title = str(P.get('feedback_tab') or i18n.TL(lang, 'fb.tab_template', ver=fb.get('cut_version', '')))
    tz_tab = (os.environ.get('TZ_TAB') or P.get('tab_title')
              or str(P.profile('doc.tab_tz_template', i18n.TL(lang, 'c2.tz_tab_template'))).format(ver=P.CUT_VERSION))
    from doctab_lib import get_doc  # noqa: E402  (путь к нему добавил _bootstrap)
    tab = find_tab(DT.get_doc_retry(P.need('doc_id'), call=get_doc), title)
    view = doc_view(tab)
    ts = (view.get('table_style') or {}).get('tableColumnProperties') or []
    widths = [int(round((c.get('width') or {}).get('magnitude', 0))) for c in ts] or None
    objs = tab['documentTab'].get('inlineObjects') or {}
    img_w = []
    for oid in view['img_ids']:
        size = (((objs.get(oid) or {}).get('inlineObjectProperties') or {}).get('embeddedObject') or {}).get('size') or {}
        img_w.append(round((size.get('width') or {}).get('magnitude', 0)))
    base = Path(frames_dir) if frames_dir else Path(P.REVIEW_DIR)
    visuals = B.load_visuals(B.index_path(None, Bt.W6))
    say = B.compute_say(fb)
    # у каких пунктов картинки — читаем из САМОЙ вкладки, а не с диска: проверять могут на машине без картинок (или
    # картинка приехала уже после сборки), и сверка текста упала бы на всех подписях разом. Подпись без картинки при
    # этом не спрячется: проверка картинок сверяет их число с числом подписей.
    have = have_from_doc(view, fb, lang, tz_tab, visuals, say)
    rep = verify(fb, tab, lang=lang, have=have or None, tz_tab=tz_tab, visuals=visuals, say=say, batches=None,
                 widths=widths, img_widths=img_w)
    late = sorted(B.frames_on_disk(fb, base, visuals) - have) if view['imgs'] else []   # вкладка без картинок — так и задумано
    if late:
        rep.warn('визуал на диске есть, а во вкладке у пункта его нет (пересобери вкладку с картинками)', late)
    import doc_images as DI
    ledger = Bt.W6 / 'feedback_grants.json'
    try:
        pending = bool(DI.ledger_pending(ledger))           # локальный файл, сети не трогает
    except ValueError:
        pending = True                                      # журнал не читается — считаем, что доступы открыты
    # ревизор — не только когда во вкладке есть кадры: прогон с кадрами могли убить ДО первой картинки, а открытые
    # доступы тогда числятся только в журнале
    if view['imgs'] or pending:
        folder = str(P.get('private_frames_folder_id', '') or '')
        problems = DI.audit(folder, ledger) if folder else ['в карточке нет private_frames_folder_id — права кадров '
                                                            'проверить негде']
        rep.check('ревизор доступов к кадрам: открытых файлов нет', [('вкладка', p) for p in problems])
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description='проверка вкладки «Обратная связь · vN»: офлайн по дампу или по живому доку')
    ap.add_argument('--fb', help='путь к feedback.json (по умолчанию — work/{cut}/feedback.json по карточке)')
    ap.add_argument('--from-dump', metavar='FILE', help='дамп от doc_tab_feedback_v1.py --dump-requests')
    ap.add_argument('--frames-dir', metavar='DIR', help='живой док: от какой папки считать пути картинок')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    fb = V.load(a.fb)
    if a.from_dump:
        rep = from_dump(fb, json.loads(Path(a.from_dump).read_text(encoding='utf-8')))
    else:
        rep = from_live(fb, a.frames_dir)
    for ln in rep.lines:
        print(ln)
    if rep.warns:
        print(f'предупреждений: {rep.warns}')
    print(rep.verdict(), flush=True)
    return 1 if rep.fails else 0


# ═══════════════════ самопроверка (офлайн) ═══════════════════
def _table(dump):
    tab = dump['final_doc']['tabs'][0]
    return next(c for c in tab['documentTab']['body']['content'] if 'table' in c)['table']['tableRows']


def _cells_text(row):
    return [''.join(e.get('textRun', {}).get('content', '') for p in c['content'] for e in p['paragraph']['elements'])
            for c in row['tableCells']]


def _find_row(dump, pred):
    for row in _table(dump):
        if pred(_cells_text(row)):
            return row
    raise AssertionError('строка для порчи не найдена')


def _replace(row, cj, old, new):
    for p in row['tableCells'][cj]['content']:
        for e in p['paragraph']['elements']:
            tr = e.get('textRun')
            if tr and old in tr['content']:
                tr['content'] = tr['content'].replace(old, new, 1)
                return
    raise AssertionError(f'в ячейке нет {old!r}')


def selftest():
    import os
    import subprocess
    import tempfile
    quiet = lambda *a, **k: None                            # noqa: E731

    # копия шаблона подписи не разъехалась с оригиналом (и с общим слоем)
    src = (HERE / 'doc_pdf_qc.py').read_text(encoding='utf-8')
    assert f"CAP_RE = re.compile(r'{CAP_RE.pattern}')" in src, 'CAP_RE в doc_pdf_qc.py изменился — обнови копию'
    assert CAP_RE.pattern == V.CAP_RE.pattern and MIN_IMG_W == 140

    tmp = Path(tempfile.mkdtemp(prefix='doc_tab_feedback_verify_'))
    fb = B.synthetic()
    visuals = B.make_visuals(fb, tmp, rel_dir=B.VIS_DIR)
    say = B.synthetic_say(fb)
    have = B.frames_on_disk(fb, tmp, visuals)
    path = tmp / 'dump.json'
    B.dump(B.synthetic(), path, have_frames=have, visuals=visuals, say=say, log=quiet)
    good = json.loads(path.read_text(encoding='utf-8'))

    rep = from_dump(B.synthetic(), good)
    assert not rep.fails and rep.verdict() == 'ALL PASS', rep.lines
    assert any(ln.startswith('WARN') and 'цитаты прошлого ТЗ' in ln for ln in rep.lines), rep.lines
    assert any(ln.startswith('WARN') and 'речи в' in ln and ': 1' in ln for ln in rep.lines), rep.lines   # ТЗ-13: время есть, речи нет
    assert sum(ln.startswith('PASS') for ln in rep.lines) == 11, rep.lines
    view = doc_view(good['final_doc']['tabs'][0])
    assert view['tables'] == 1 and view['imgs'] == len(have) == 19 and view['inside'], 'в синтетике обязаны быть эмодзи вне BMP'
    assert len(view['grid'][0]) == 6
    assert have_from_doc(view, B.synthetic(), visuals=visuals, say=say) == have   # живой режим: набор визуалов — из самой вкладки

    # без картинок — тоже чисто в остальном, но у полных строк FAIL «нет визуала» (так и задумано), и строка про кадры в шапке
    B.dump(B.synthetic(), tmp / 'noimg.json', say=say, log=quiet)
    noimg = json.loads((tmp / 'noimg.json').read_text(encoding='utf-8'))
    rep0 = from_dump(B.synthetic(), noimg)
    assert rep0.fails and all(o == 'визуалы' for o, _, _ in rep0.fails) and len(rep0.fails) == 11, rep0.lines
    assert rep0.verdict() == 'FAIL: 11 (вкладка 0 · модель 0 · визуалы 11)', rep0.verdict()
    assert have_from_doc(doc_view(noimg['final_doc']['tabs'][0]), B.synthetic(), say=say) == set()
    # индекс есть, а у одной строки нет «как надо» → ровно один FAIL [визуалы]
    v1 = json.loads(json.dumps(visuals))
    del v1['2:11']['fix']
    B.dump(B.synthetic(), tmp / 'onefix.json', have_frames=B.frames_on_disk(fb, tmp, v1), visuals=v1, say=say, log=quiet)
    r1 = from_dump(B.synthetic(), json.loads((tmp / 'onefix.json').read_text(encoding='utf-8')))
    assert [(o, m[:31]) for o, _, m in r1.fails] == [('визуалы', 'ТЗ-11 · прошлое ТЗ: нет визуала')], r1.fails

    def broken(mutate, fb_=None):
        d = copy.deepcopy(good)
        mutate(d)
        r = from_dump(fb_ or B.synthetic(), d)
        assert r.fails and r.verdict().startswith('FAIL: '), 'порча не замечена'
        return '\n'.join(r.lines)

    # 1) убрана подпись под картинкой «ошибка» · подпись без «·»
    def no_caption(d):
        cell = _find_row(d, lambda c: c[0].startswith('ТЗ-01'))['tableCells'][B.C_ERR]
        assert len(cell['content']) == 2
        del cell['content'][1]
    out = broken(no_caption)
    assert 'ТЗ-01: под картинкой нет подписи' in out, out
    out = broken(lambda d: _replace(_find_row(d, lambda c: c[0].startswith('ТЗ-01')), B.C_ERR, '0:42 · ', '0:42 - '))
    assert 'ТЗ-01: под картинкой нет подписи' in out and 'расхождение с' in out, out

    # 2) секция с неверным счётчиком
    out = broken(lambda d: _replace(_find_row(d, lambda c: c[B.C_VERDICT].startswith('[❌ ОСТАЛОСЬ')), B.C_VERDICT, '· 3]', '· 5]'))
    assert 'секция «❌ ОСТАЛОСЬ»: в скобках 5, в модели 3' in out, out

    # 3) у незакрытого пункта вырезан блок «Как надо» (метка core.lbl_do, с 22.09.2026 «▶ СДЕЛАТЬ»)
    _do = i18n.TL('ru', 'core.lbl_do')
    out = broken(lambda d: _replace(_find_row(d, lambda c: c[0].startswith('ТЗ-11 · v4')), B.C_FIX,
                                    f'{_do} · укоротить плашку\n', ''))
    assert f'ТЗ-11 · прошлое ТЗ: в колонке «Как надо» нет блока «{_do} ·»' in out and 'расхождение с' in out, out

    # 4) вердикт не первой строкой · не тем цветом · нет «Почему:» · нет источника под «как надо»
    def verdict_second(d):                                  # абзацы вердикта и заголовка меняются местами
        paras = _find_row(d, lambda c: c[0].startswith('ТЗ-11 · v4'))['tableCells'][B.C_VERDICT]['content']
        a, b = paras[0]['paragraph']['elements'][0]['textRun'], paras[1]['paragraph']['elements'][0]['textRun']
        assert a['content'] == '❌ НЕПРАВИЛЬНО\n' and b['content'] == '【Пункт 11】\n'
        a['content'], b['content'] = b['content'], a['content']
    out = broken(verdict_second)
    assert 'ТЗ-11 · прошлое ТЗ: первая строка колонки «Вердикт и почему» — не вердикт' in out, out

    def verdict_wrong(d):
        _replace(_find_row(d, lambda c: c[0].startswith('ТЗ-11 · v4')), B.C_VERDICT, '❌ НЕПРАВИЛЬНО', '✅ ПРАВИЛЬНО')
    out = broken(verdict_wrong)
    assert 'вердикт «✅ ПРАВИЛЬНО», по секции должен быть «❌ НЕПРАВИЛЬНО»' in out, out

    def verdict_color(d):
        v = doc_view(d['final_doc']['tabs'][0])
        a = next(c for c in v['grid'][2] if c['text'].startswith('❌ НЕПРАВИЛЬНО'))['a']
        q = next(q for bt in d['batches'] for q in bt if 'updateTextStyle' in q
                 and q['updateTextStyle']['range']['startIndex'] == a and _rgb_of(q['updateTextStyle']['textStyle']) == DT.RED)
        q['updateTextStyle']['textStyle']['foregroundColor']['color']['rgbColor'] = DT.GREEN
    out = broken(verdict_color)
    assert 'ТЗ-03: вердикт «❌ НЕПРАВИЛЬНО» не тем цветом' in out and 'стиль «was» на «❌ НЕПРАВИЛЬНО» не отправлен' in out, out

    def verdict_color_after(d):                             # верный красный отправлен, а ПОСЛЕ него тем же диапазоном — зелёный
        v = doc_view(d['final_doc']['tabs'][0])
        a = next(c for c in v['grid'][2] if c['text'].startswith('❌ НЕПРАВИЛЬНО'))['a']
        q = next(q for bt in d['batches'] for q in bt if 'updateTextStyle' in q
                 and q['updateTextStyle']['range']['startIndex'] == a and _rgb_of(q['updateTextStyle']['textStyle']) == DT.RED)
        q2 = copy.deepcopy(q)
        q2['updateTextStyle']['textStyle']['foregroundColor']['color']['rgbColor'] = DT.GREEN
        d['batches'][-1].append(q2)
    out = broken(verdict_color_after)
    assert 'ТЗ-03: вердикт «❌ НЕПРАВИЛЬНО» не тем цветом' in out, out   # в Docs побеждает последний стиль

    out = broken(lambda d: _replace(_find_row(d, lambda c: c[0].startswith('ТЗ-11 · v4')), B.C_VERDICT, 'Почему:', 'Потому:'))
    assert 'ТЗ-11 · прошлое ТЗ: нет строки «Почему:» с текстом' in out, out

    def no_source(d):
        cell = _find_row(d, lambda c: c[0].startswith('ТЗ-11 · v4'))['tableCells'][B.C_FIX]
        assert cell['content'][-1]['paragraph']['elements'][0]['textRun']['content'].startswith('Источник:')
        del cell['content'][-1]
        cell['content'][-1]['paragraph']['elements'][-1]['textRun']['content'] = cell['content'][-1]['paragraph']['elements'][-1]['textRun']['content'].rstrip('\n') + '\n'
    out = broken(no_source)
    assert 'ТЗ-11 · прошлое ТЗ: под картинкой «Как надо» нет строки «Источник: …»' in out, out

    # 5) граница стиля внутри эмодзи; диапазон через две ячейки
    def cut_emoji(d):
        inside = min(doc_view(d['final_doc']['tabs'][0])['inside'])
        q = next(q for bt in d['batches'] for q in bt if 'updateTextStyle' in q
                 and q['updateTextStyle']['range']['startIndex'] < inside < q['updateTextStyle']['range']['endIndex'])
        q['updateTextStyle']['range']['endIndex'] = inside
    assert 'режет суррогатную пару' in broken(cut_emoji)

    def cross_cells(d):
        v = doc_view(d['final_doc']['tabs'][0])
        a, b = v['grid'][2][B.C_NUM], v['grid'][2][B.C_VERDICT]
        d['batches'][-2].append({'updateTextStyle': {'range': {'tabId': 't', 'startIndex': a['a'], 'endIndex': b['a'] + 1},
                                                     'textStyle': {'bold': True}, 'fields': 'bold'}})
    assert 'выходит за ячейку' in broken(cross_cells)

    # 6) картинка 120 pt · ширины не 676 · вторая таблица · чужая модель · время за концом ката · слово движка · два таймкода в Части 1
    def narrow(d):
        next(q for bt in d['batches'] for q in bt if 'insertInlineImage' in q)['insertInlineImage']['objectSize']['width']['magnitude'] = 120
    assert 'картинка шириной 120 pt — уже 140 pt' in broken(narrow)

    def widths_off(d):
        q = next(q for bt in d['batches'] for q in bt if 'updateTableColumnProperties' in q)
        q['updateTableColumnProperties']['tableColumnProperties']['width']['magnitude'] = 60
    out = broken(widths_off)
    assert 'ширины [60, 44, 104, 168, 160, 160] = 696 pt, должно быть [40, 44, 104, 168, 160, 160] = 676' in out, out
    assert 'таблиц во вкладке: 2' in broken(lambda d: d['final_doc']['tabs'][0]['documentTab']['body']['content'].append(
        copy.deepcopy(next(c for c in d['final_doc']['tabs'][0]['documentTab']['body']['content'] if 'table' in c))))
    short = B.synthetic()
    short['duration_sec'] = 600.0
    out = broken(lambda d: None, short)
    assert 'дамп собран из другой модели' in out and 'за концом ката (10:00)' in out and '[модель]' in out, out

    def model_defects(f):
        f['part1'][1]['parts']['do'] = ['сдвинуть с 11:16 на 34:00, проверить OCR']
        f['part2'][7]['title'] = 'Повтор на 8:20 и на 8:31'       # пункт 30 — полная строка «закрыто»: заголовок и «Почему:» — цитата
        f['part2'][7]['evidence']['text'] = 'смотри align'          # доказательство с жаргоном — тоже модель
        return f
    bad_fb = model_defects(B.synthetic())
    B.dump(model_defects(B.synthetic()), tmp / 'bad.json', have_frames=have, visuals=visuals, say=say, log=quiet)
    r = from_dump(bad_fb, json.loads((tmp / 'bad.json').read_text(encoding='utf-8')))
    txt = '\n'.join(r.lines)
    assert r.fails and all(o == 'модель' for o, _, _ in r.fails), txt      # вкладка собрана верно — виновата модель
    assert '[модель] ТЗ-02: ' in txt and '[модель] ТЗ-30 · прошлое ТЗ' in txt and '«OCR»' in txt and '«align»' in txt, txt
    assert r.verdict() == f'FAIL: {len(r.fails)} (вкладка 0 · модель {len(r.fails)})'
    # таймкод в речи — дословный, не ошибка; жаргон в речи — ошибка вкладки (речь не из модели)
    say_tc = json.loads(json.dumps(say))
    say_tc['1:1']['text'] = 'на 1:05 и на 12:30 она сказала про 99:00 ещё'
    B.dump(B.synthetic(), tmp / 'saytc.json', have_frames=have, visuals=visuals, say=say_tc, log=quiet)
    r = from_dump(B.synthetic(), json.loads((tmp / 'saytc.json').read_text(encoding='utf-8')))
    assert not r.fails, r.lines

    # 5б) путь к мокапу в «Источник:» — не жаргон (§9); слово движка в источнике вне пути — жаргон [вкладка]
    v2 = json.loads(json.dumps(visuals))
    v2['2:11']['fix']['source'] = {'text': 'мокап стадии: mockups/tz/tz_11.png', 'url': None}
    v2['2:30']['fix']['source'] = {'text': 'кадр h0501 по OCR', 'url': None}
    B.dump(B.synthetic(), tmp / 'src.json', have_frames=have, visuals=v2, say=say, log=quiet)
    r = from_dump(B.synthetic(), json.loads((tmp / 'src.json').read_text(encoding='utf-8')))
    assert sorted(m[:60] for o, _, m in r.fails) == ['ТЗ-30 · прошлое ТЗ: «OCR» — Источник: кадр h0501 по OCR',
                                                       'ТЗ-30 · прошлое ТЗ: «h0501» — Источник: кадр h0501 по OCR'], r.fails

    # 6а) поломки записи, а не модели: стиль съехал на один знак · секции перепутаны · в текст вкладки попали
    #     время за концом ката и слово движка · речь пропала — всё это ошибки [вкладка], модель тут чиста
    def shift_label(d):
        v = doc_view(d['final_doc']['tabs'][0])
        q = next(q for bt in d['batches'] for q in bt if 'updateTextStyle' in q and q['updateTextStyle'].get('fields') == 'bold'
                 and q['updateTextStyle']['range']['startIndex'] > v['grid'][2][B.C_VERDICT]['a'])
        q['updateTextStyle']['range']['startIndex'] += 1
        q['updateTextStyle']['range']['endIndex'] += 1
    out = broken(shift_label)
    assert 'не отправлен своим диапазоном' in out, out

    def swap_sections(d):
        a = _find_row(d, lambda c: c[B.C_VERDICT].startswith('[✅'))['tableCells'][B.C_VERDICT]['content'][0]['paragraph']['elements'][0]['textRun']
        b = _find_row(d, lambda c: c[B.C_VERDICT].startswith('[❌'))['tableCells'][B.C_VERDICT]['content'][0]['paragraph']['elements'][0]['textRun']
        a['content'], b['content'] = b['content'], a['content']
    assert 'секции не те или не в том порядке' in broken(swap_sections)

    def leak(d):
        _replace(_find_row(d, lambda c: c[0].startswith('ТЗ-11 · v4')), B.C_FIX, 'укоротить плашку', 'укоротить плашку до 95:42, см. OCR и align')
    out = broken(leak)
    assert '[вкладка] ТЗ-11 · прошлое ТЗ: 95:42 — за концом ката' in out, out
    assert '[вкладка] ТЗ-11 · прошлое ТЗ: «OCR»' in out and '[модель]' not in out, out   # ключ модели «align» — не оправдание

    def lost_speech(d):
        row = _find_row(d, lambda c: c[0].startswith('ТЗ-01'))
        for p in row['tableCells'][B.C_SAID]['content']:
            for e in p['paragraph']['elements']:
                e['textRun']['content'] = '\n' if e['textRun']['content'].endswith('\n') else ''
        row['tableCells'][B.C_SAID]['content'] = row['tableCells'][B.C_SAID]['content'][-1:]
    out = broken(lost_speech)
    assert '[вкладка] ТЗ-01: речь есть, а колонка «Говорит» пустая' in out, out

    # 7) CLI: код возврата и последняя строка
    mf = tmp / 'feedback.json'
    mf.write_text(json.dumps(B.synthetic(), ensure_ascii=False), encoding='utf-8')
    env = {k: v for k, v in os.environ.items() if not k.startswith('YTAI_') and k != 'TZ_TAB'}
    r = subprocess.run([sys.executable, __file__, '--fb', str(mf), '--from-dump', str(path)], capture_output=True, text=True,
                       cwd=str(tmp), env=env)
    assert r.returncode == 0 and r.stdout.strip().splitlines()[-1] == 'ALL PASS', r.stdout + r.stderr
    d = copy.deepcopy(good)
    no_caption(d)
    (tmp / 'broken.json').write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8')
    r = subprocess.run([sys.executable, __file__, '--fb', str(mf), '--from-dump', str(tmp / 'broken.json')],
                       capture_output=True, text=True, cwd=str(tmp), env=env)
    assert r.returncode == 1 and r.stdout.strip().splitlines()[-1].startswith('FAIL: '), r.stdout + r.stderr

    # 8) модуль импортируется откуда угодно без карточки фильма
    r = subprocess.run([sys.executable, '-c',
                        'import sys; sys.path.insert(0, %r); import doc_tab_feedback_v1_verify as m; '
                        'assert "proj_config" not in sys.modules and "doc_pdf_qc" not in sys.modules and "said" not in sys.modules; '
                        'print("ok")' % str(HERE)],
                       capture_output=True, text=True, cwd='/tmp', env=env)
    assert r.returncode == 0 and r.stdout.strip() == 'ok', r.stderr
    print('SELFTEST OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
