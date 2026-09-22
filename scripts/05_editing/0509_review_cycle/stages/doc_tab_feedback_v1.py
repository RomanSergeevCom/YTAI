#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка Google Doc «Обратная связь · vN» — поверхность монтажёра (контракт docs/feedback_v1.md v2, §8–9; канон 5.6).

Зачем: прошлая вкладка «Сверка v4 → v5» вышла отчётом машины — 170 одинаковых строк без блоков, кадров и порядка
важности. Эта вкладка — документ для человека, шесть колонок по решению Романа 22.09.2026:
№ · ⏱ TC · Говорит (дословная речь ката вокруг таймкода) · Вердикт и почему (первая строка — вердикт цветом) ·
Экран с ошибкой (кадр нового ката со стрелкой) · Как надо (действие, место, картинка-рекомендация и её источник).

Вкладка ничего не решает сама: статусы, секции, лимиты строк и слова берутся из модели work/{cut}/feedback.json
через общий слой shared/feedback_view.py — тот же, что у HTML продюсера; картинки колонок 5–6 — из индекса слоя
визуалов work/{cut}/feedback_visuals/index.json (shared/feedback_visuals.py, §9); речь — shared/said.py.
Запись в док — shared/doc_table.py (ОДНА таблица, стили явными спанами, картинки в двух колонках), заливка
кадров — shared/doc_images.py (временный доступ к файлу с гарантированным отзывом).

    build_rows(fb, lang='ru', have_frames=None, tz_tab=None, visuals=None, say=None) -> (rows, head)
        ЧИСТАЯ: без карточки, сети и файлов.
        visuals     — rows индекса визуалов: {'{part}:{n}': {'err': {...}, 'fix': {...}}} (§9) или None;
        have_frames — множество '{part}:{n}/{err|fix}' визуалов, чей файл реально есть (проверка диска —
                      снаружи, frames_on_disk); пусто → картинок нет, в шапке строка «кадры — в HTML-файле»;
        say         — {'{part}:{n}': {'text', 'bold'}} от said.said() (считается в main(), где есть карточка).

CLI: [--fb PATH] [--images none|temp] [--dump-requests FILE] [--force] [--frames-dir DIR] | --selftest
  --images temp      кадры в док под временным доступом. Сработает только если в карточке images_mode=temp_grant,
                     запуск с Мака и не автономный; иначе картинок нет (при любом сомнении — без картинок).
  --dump-requests    всё на офлайн-двойнике Docs (shared/fake_docs.py): ни Docs, ни Drive не вызываются; с
                     --images temp картинки встают поддельными адресами fake://<имя>. Дамп детерминирован.
                     Карточка в этом режиме не обязательна, если дан --fb (кадры ищутся от --frames-dir,
                     по умолчанию — от папки модели; индекс визуалов — рядом с моделью).
  Индекса визуалов нет → вкладка собирается без картинок, с предупреждением (проверка тогда даёт FAIL «нет визуала»
  у полных строк — так и задумано: картинка «как надо» обязательна у каждого полного пункта).

Вкладка НОВАЯ и находится ПО ИМЕНИ (карточка feedback_tab, иначе «Обратная связь · {ver}»). «Сверка v4 → v5»
и замороженные вкладки не трогаются. Карточка фильма читается только внутри main(): модуль импортируется откуда
угодно без YTAI_CARD.
"""
import argparse
import hashlib
import json
import os
import re
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SHARED = ROOT / 'shared'
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

import i18n  # noqa: E402
import feedback_view as V  # noqa: E402
import tz_blocks as TB  # noqa: E402
import doc_table as DT  # noqa: E402

WIDTHS = [40, 44, 104, 168, 160, 160]             # № | ⏱ TC | Говорит | Вердикт и почему | Экран с ошибкой | Как надо = 676 pt
C_NUM, C_TC, C_SAID, C_VERDICT, C_ERR, C_FIX = range(6)
HDR_KEYS = ('fb.col.num', 'fb.col.tc', 'fb.col.said', 'fb.col.verdict', 'fb.col.err', 'fb.col.fix')
FONT = 9
IMG_W = 150                                       # картинка на ширину колонки 160 pt минус поля (§8)
MIN_IMG_W = 140                                   # минимум ЭТОЙ вкладки (канон 5.6 просит 250 — при шести колонках невыполнимо)
FULL = ('new', 'block', 'open', 'blur', 'closed')  # секции с полными строками; fund и appendix — строка-список
KINDS = ('err', 'fix')                            # визуалы колонок 5 и 6
VIS_DIR = 'feedback_visuals'                      # work/{cut}/feedback_visuals/index.json (§9)
# вердикт первой строкой колонки 4: ключ строки и ключ цвета doc_table (was = красный, now = зелёный, warn = оранжевый)
VERDICT = {'new': ('fb.verdict.wrong', 'was'), 'block': ('fb.verdict.wrong', 'was'), 'open': ('fb.verdict.wrong', 'was'),
           'blur': ('fb.verdict.blur', 'warn'), 'closed': ('fb.verdict.right', 'now'),
           'fund': ('fb.verdict.fund', 'warn'), 'appendix': ('fb.verdict.unchecked', 'muted')}
DUMP_DOC = 'doc-dump'                             # id дока в офлайн-дампе (настоящий id в дамп не попадает)
# запись оборвалась: вкладка пересобирается с нуля, но уже не пуста — без --force следующий прогон откажет
HALF = ('⚠️ запись вкладки «{title}» оборвалась — она могла остаться недописанной. Когда причина устранена, '
        'запусти ещё раз с --force: вкладка пересоберётся с нуля.')
NO_VISUALS = ('⚠️ индекса визуалов нет: {path} — вкладка соберётся без картинок (собери слой визуалов: '
              'python3 shared/feedback_visuals.py)')
# значок категории во второй строке ячейки № — как на вкладке «ТЗ монтажёру» (у «разобрано» лупа, а не галочка:
# галочка рядом с незакрытым пунктом читалась бы как «сделано»)
CAT = {'graphics': '🎨', 'structure': '🧭', 'cut': '✂️', 'insert': '➕', 'color': '🎛', 'check': '🔍', 'fund': '⚠️'}
FILL = {'part2': (0.85, 0.85, 0.85), 'new': (0.85, 0.91, 0.98), 'block': (0.99, 0.85, 0.84),
        'open': (1.0, 0.92, 0.82), 'blur': (0.98, 0.95, 0.78), 'closed': (0.85, 0.93, 0.85),
        'fund': (0.98, 0.95, 0.78), 'appendix': (0.93, 0.93, 0.93)}
_URL_RE = re.compile(r'^https?://\S+$')


# ═══════════════════ строки таблицы (чистая часть) ═══════════════════
def _safe(s):
    """знаки, которые Docs выбросит при вставке (управляющие, частная область), убираем заранее: иначе doc_table
    откажется писать всю вкладку из-за одного мусорного знака в тексте прошлого ТЗ. Длина строки не меняется —
    смещения жирного в речи (said.bold) остаются верными."""
    return DT.BAD_CHARS.sub(' ', str(s or ''))


def _one(s):
    return ' '.join(_safe(s).split())


class _Cell(DT.CellText):
    """ячейка со спанами; каждая добавка чистится от знаков, ломающих индексы"""

    def add(self, s, key=None, url=None):
        return super().add(_safe(s), key, url)

    def line(self, s, key=None, url=None):
        if self.text:
            self.nl()
        return self.add(s, key, url)


def hdr(lang='ru'):
    return [i18n.TL(lang, k) for k in HDR_KEYS]


def row_key(row):
    return f'{row.get("part")}:{row.get("n")}'


def vis_key(row, kind):
    """ключ have_frames: '{part}:{n}/{err|fix}'"""
    return f'{row_key(row)}/{kind}'


def visual_name(row, kind):
    """имя файла картинки в доке (обе картинки строки — разные файлы)"""
    return f'fb_p{int(row["part"])}_{int(row["n"]):03d}_{kind}.jpg'


def sec_text(label, n):
    """квадратные скобки обязательны: так секции видны в панели «Структура» дока"""
    return f'[{_one(label)} · {n}]'


def _visual(visuals, row, kind):
    """запись индекса визуалов для строки и вида, если у неё есть файл; иначе None"""
    v = ((visuals or {}).get(row_key(row)) or {}).get(kind)
    return v if isinstance(v, dict) and v.get('file') else None


def _tc_of(row):
    sec = row.get('sec_new')
    if sec is None:
        return ''
    t = int(float(sec))
    return f'{t // 60}:{t % 60:02d}'


def _caption(vis, row, lang):
    """подпись под картинкой по шаблону канона «M:SS · что видно» (V.CAP_RE); подпись индекса без времени
    впереди получает время пункта, без времени вовсе — «сводно»"""
    cap = _one((vis or {}).get('caption'))
    if cap and V.CAP_RE.match(cap):
        return cap
    what = cap or (V.caption(row).split(' · ', 1)[1] if V.caption(row) else '') or i18n.TL(lang, 'fb.cap_default_nover')
    tc = _tc_of(row)
    return i18n.TL(lang, 'fb.cap', tc=tc or 'сводно', what=what)


def _source(vis):
    """→ (текст, адрес|None) строки «Источник: …»; адрес без схемы получает https://"""
    src = (vis or {}).get('source') or {}
    if isinstance(src, str):
        src = {'text': src}
    text = _one(src.get('text'))
    url = ' '.join(str(src.get('url') or '').split())
    if url and not _URL_RE.match(url):
        url = 'https://' + url if re.match(r'^[\w.-]+\.[a-z]{2,}(/|$)', url, re.I) else ''
    return text or (url.split('://', 1)[-1] if url else '—'), (url or None)


def _num_cell(row, fb):
    c = _Cell()
    c.add(V.num_label(row, fb), 'label')
    if row.get('blocker'):
        c.add(' 🔴')
    icon = CAT.get(row.get('category') or '')
    if icon:
        c.line(icon)
    return c


def _said_cell(row, say):
    """колонка «Говорит»: дословная речь, опорная фраза жирным (спан title = bold)"""
    c = _Cell()
    s = (say or {}).get(row_key(row)) or {}
    raw = _safe(s.get('text'))
    lead = len(raw) - len(raw.lstrip('\n'))                 # срезанные переводы строки впереди сдвигают смещения жирного
    text = raw.strip('\n')
    if not text:
        return c
    c.add(text)
    for pair in s.get('bold') or []:
        try:
            a, b = int(pair[0]) - lead, int(pair[1]) - lead
        except (TypeError, ValueError, IndexError):
            continue
        a, b = max(0, a), min(len(text), b)
        if a < b and text[a:b].strip():
            c.spans.append((a, b, 'title'))
    c.spans.sort()
    return c


def _blocks(cell, keys, sb, lang):
    lab = TB.labels(lang)
    for key in keys:
        head = lab[key] + ' ·'
        for ln in TB.render_block(key, sb[key], lang):
            if ln.startswith(head):
                cell.line(head, 'label').add(ln[len(head):])
            else:
                cell.line(ln)


def _verdict_cell(row, fb, lang, bucket):
    """колонка 4: вердикт цветом → 【заголовок】 → «Почему:» доказательство → ❌ СЕЙЧАС → опечатки → «ещё N строк»"""
    vkey, color = VERDICT[bucket]
    c = _Cell()
    c.add(i18n.TL(lang, vkey), color)
    c.line('【' + _one(row.get('title')) + '】', 'title')
    sb = V.short_blocks(row, fb)
    ev = _one((row.get('evidence') or {}).get('text'))
    now_first = sb['now'][0] if sb['now'] else ''
    why = ev or _one(now_first) or _one(row.get('title'))
    c.line(i18n.TL(lang, 'fb.why'), 'label').add(' ' + why)
    if ev and sb['now']:                                    # доказательство есть — строка ❌ СЕЙЧАС отдельно, как в ТЗ
        _blocks(c, ('now',), sb, lang)
    pre, mid, post = (i18n.TL(lang, k) for k in ('core.was_pre', 'core.was_mid', 'core.was_post'))
    for was, now in V.typo_pairs(row):                      # только Часть 1
        c.line(pre).add(_one(was), 'was').add(mid).add(_one(now), 'now').add(post)
    if sb['more_line']:
        c.line(sb['more_line'], 'muted')
    return c


def _item_row(row, fb, lang, have, visuals, say, bucket):
    num = _num_cell(row, fb)
    said_c = _said_cell(row, say)
    verdict = _verdict_cell(row, fb, lang, bucket)
    sb = V.short_blocks(row, fb)
    imgs = []

    err = _Cell()                                           # колонка 5: пустой абзац-якорь + подпись
    ve = _visual(visuals, row, 'err')
    if ve and vis_key(row, 'err') in have:
        err.nl().add(_caption(ve, row, lang), 'cap')
        imgs.append((C_ERR, 0, visual_name(row, 'err')))

    fix = _Cell()                                           # колонка 6: ✅ и 📍, затем якорь + подпись + источник
    _blocks(fix, ('do', 'where'), sb, lang)
    vf = _visual(visuals, row, 'fix')
    if vf and vis_key(row, 'fix') in have:
        if fix.text:
            fix.nl()
        li = fix.line_idx()
        fix.nl().add(_caption(vf, row, lang), 'cap')
        text, url = _source(vf)
        fix.nl().add(i18n.TL(lang, 'fb.source') + ' ', 'muted')
        if url:
            fix.add(text, 'link', url)
        else:
            fix.add(text, 'muted')
        imgs.append((C_FIX, li, visual_name(row, 'fix')))

    cells = [num.text, _safe(V.tc_label(row)), said_c.text, verdict.text, err.text, fix.text]
    spans = {C_NUM: num.spans, C_VERDICT: verdict.spans, C_FIX: fix.spans}
    if said_c.spans:
        spans[C_SAID] = said_c.spans
    if err.spans:
        spans[C_ERR] = err.spans
    return {'kind': 'item', 'cells': cells, 'spans': spans, 'fill': None, 'imgs': imgs,
            'meta': {'role': 'item', 'bucket': bucket, 'part': row.get('part'), 'n': row.get('n')}}


def _dup_row(row, fb):
    """требование переехало в Часть 1: одна строка вместо блоков и картинок (+ заголовок серым, чтобы было ясно, о чём)"""
    body = _Cell()
    body.add(V.dup_line(row))
    if _one(row.get('title')):
        body.line(_one(row.get('title')), 'muted')
    num = _num_cell(row, fb)
    return {'kind': 'item', 'cells': [num.text, _safe(V.tc_label(row)), '', body.text, '', ''],
            'spans': {C_NUM: num.spans, C_VERDICT: body.spans}, 'fill': None, 'imgs': [],
            'meta': {'role': 'dup', 'bucket': row.get('bucket'), 'part': row.get('part'), 'n': row.get('n')}}


def _list_row(bucket, rows, fb, lang):
    """fund / appendix: вердикт первой строкой, затем по пункту на строку (темы фонда жирным)"""
    vkey, color = VERDICT[bucket]
    body = _Cell()
    body.add(i18n.TL(lang, vkey), color)
    if bucket == 'fund':
        for _key, title, group in V.fund_groups(rows, fb):
            body.line(_one(title), 'title')
            for r in group:
                body.line(TB.IND2 + V.list_line(r, with_num=True))
    else:
        for r in rows:
            body.line(V.list_line(r, with_num=True))
    return {'kind': 'list', 'cells': ['', '', '', body.text, '', ''], 'spans': {C_VERDICT: body.spans}, 'fill': None,
            'imgs': [], 'meta': {'role': 'list', 'bucket': bucket, 'ns': [r.get('n') for r in rows]}}


def _sec_row(text, fill, meta, sub=None):
    cells = ['', '', '', text + ('\n' + sub if sub else ''), '', '']
    spans = {C_VERDICT: [(0, len(text), 'sec'), (len(text) + 1, len(text) + 1 + len(sub), 'muted')]} if sub else {}
    return {'kind': 'sec', 'cells': cells, 'head_col': C_VERDICT, 'spans': spans, 'fill': fill, 'imgs': [], 'meta': meta}


def build_rows(fb, lang='ru', have_frames=None, tz_tab=None, visuals=None, say=None):
    """модель → (rows, head) для doc_table.write_tab. Чистая функция: ни карточки, ни сети, ни файлов.

    rows — одна таблица: строка-секция «[НАЗВАНИЕ · n]» → полные строки (new/block/open/blur/closed) либо ОДНА
    строка-список (fund/appendix). У каждой строки служебное 'meta' (роль, секция, номер) — для проверки;
    doc_table его не читает. head — первый экран из feedback_view.head() + две строки «как читать» про колонки."""
    have = set(have_frames or ())
    old = i18n.set_lang(lang)
    try:
        rows = []
        prev = str(fb.get('prev_cut_version') or '')
        part2_done = False
        for bucket, label, items in V.sections(fb):
            if bucket in V.PART2 and not part2_done:        # общий заголовок Части 2 — одна строка перед её секциями
                part2_done = True
                n2 = len(fb.get('part2') or [])
                rows.append(_sec_row(sec_text(i18n.T('fb.part2', prev=prev).strip(), n2), FILL['part2'],
                                     {'role': 'part2', 'n': n2}, sub=i18n.T('fb.part2_sub')))
            rows.append(_sec_row(sec_text(label, len(items)), FILL.get(bucket),
                                 {'role': 'sec', 'bucket': bucket, 'n': len(items)}))
            if bucket in FULL:
                for r in items:
                    rows.append(_dup_row(r, fb) if r.get('dup_of') else _item_row(r, fb, lang, have, visuals, say, bucket))
            else:
                rows.append(_list_row(bucket, items, fb, lang))
        n_img = sum(len(r['imgs']) for r in rows)
        head = [(k, _one(t)) for k, t in V.head(fb, surface='doc', tz_tab=tz_tab, frames_note=not n_img)]
        head += [('how', _one(i18n.T('fb.how_verdict'))), ('how', _one(i18n.T('fb.how_screens')))]
        return rows, head
    finally:
        i18n.set_lang(old)


# ═══════════════════ диск, индекс визуалов, речь ═══════════════════
def index_path(fb_path=None, w6=None):
    """где лежит индекс визуалов: рядом с моделью (work/{cut}/feedback_visuals/index.json)"""
    base = Path(fb_path).resolve().parent if fb_path else Path(w6)
    return base / VIS_DIR / 'index.json'


def load_visuals(path, log=print):
    """→ rows индекса (§9) или None, если индекса нет / он битый (с предупреждением, без падения)"""
    path = Path(path)
    if not path.is_file():
        log(NO_VISUALS.format(path=path))
        return None
    try:
        idx = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as e:
        log(f'⚠️ индекс визуалов не читается ({path}: {e}) — вкладка соберётся без картинок')
        return None
    if idx.get('schema') != 'feedback-visuals-v1' or not isinstance(idx.get('rows'), dict):
        log(f'⚠️ индекс визуалов {path}: schema={idx.get("schema")!r} — ожидается feedback-visuals-v1; без картинок')
        return None
    return idx['rows']


def _full_rows(fb):
    return [r for r in (fb.get('part1') or []) + (fb.get('part2') or []) if r.get('bucket') in FULL and not r.get('dup_of')]


def frames_on_disk(fb, base_dir, visuals):
    """→ {'{part}:{n}/{kind}'} визуалов полных строк, чей файл лежит на диске (картинки строятся частями на Мак и Memex —
    части может не быть). Без индекса — пусто."""
    base, out = Path(base_dir), set()
    if not visuals:
        return out
    for r in _full_rows(fb):
        for kind in KINDS:
            v = _visual(visuals, r, kind)
            if not v:
                continue
            p = Path(v['file']) if Path(v['file']).is_absolute() else base / v['file']
            if p.is_file():
                out.add(vis_key(r, kind))
    return out


def prepare_visuals(fb, visuals, out_dir, base_dir, width=1000, quality=80, log=print):
    """картинки индекса → JPEG ≤ width в out_dir под именами дока (fb_p2_040_err.jpg / _fix.jpg).
    → [{name, path, row_key, kind}] для doc_images.upload_all / insert_with_temp_grant (они работают по имени).
    doc_images.prepare() даёт одно имя на строку, а здесь картинок две — поэтому подготовка своя, заливка и вставка — его."""
    import io
    from PIL import Image
    out_dir, base = Path(out_dir), Path(base_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    done, skipped = [], []
    for r in _full_rows(fb):
        for kind in KINDS:
            v = _visual(visuals, r, kind)
            if not v:
                continue
            src = Path(v['file']) if Path(v['file']).is_absolute() else base / v['file']
            if not src.is_file():
                skipped.append(f'{vis_key(r, kind)}: нет файла {v["file"]}')
                continue
            try:
                im = Image.open(src).convert('RGB')
                if im.width > width:
                    im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, 'JPEG', quality=quality, optimize=True, progressive=True)
                data = buf.getvalue()
            except Exception as e:                          # noqa: BLE001
                skipped.append(f'{vis_key(r, kind)}: картинка не читается ({type(e).__name__})')
                continue
            name = visual_name(r, kind)
            dst = out_dir / name
            if not (dst.exists() and dst.read_bytes() == data):   # те же байты → тот же md5 → повторной заливки не будет
                dst.write_bytes(data)
            done.append({'name': name, 'path': str(dst), 'row_key': row_key(r), 'kind': kind})
    if skipped:
        log(f'  визуалы пропущены: {len(skipped)} (первый: {skipped[0]})')
    return done


def compute_say(fb, said_fn=None):
    """колонка «Говорит»: {'{part}:{n}': {'text', 'bold'}} для полных строк с временем. said.py читает транскрипт
    по карточке, поэтому зовётся только из main() (или получает said_fn для проверок)."""
    if said_fn is None:
        import said                                         # noqa: E402  (лениво: модуль читает карточку при импорте)
        said_fn = said.said
    out = {}
    for r in _full_rows(fb):
        tc = str(r.get('tc_new') or '').strip()
        if not tc:
            continue
        where = next((x for x in ((r.get('parts') or {}).get('where') or []) if V.TCR.search(str(x))), '') or tc
        try:
            s = said_fn(where, tc) or {}
        except Exception as e:                              # noqa: BLE001  — речь необязательна, вкладка важнее
            print(f'  речь для {row_key(r)} не получена: {type(e).__name__}: {str(e)[:80]}', flush=True)
            continue
        text = str(s.get('text') or '')
        if text.strip():
            out[row_key(r)] = {'text': text, 'bold': [[int(a), int(b)] for a, b in (s.get('bold') or [])]}
    return out


def fb_sha(fb):
    """отпечаток модели без служебных полей «_…» — проверка сверяет, что дамп собран из той же модели"""
    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if not str(k).startswith('_')}
        return [strip(v) for v in x] if isinstance(x, list) else x
    return hashlib.sha256(json.dumps(strip(fb), ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:16]


def detect_host(review_dir=None, env=None, hostname=None):
    """'mac' | 'memex' | 'unknown'. review.py хост дочерним стадиям не передаёт, поэтому признаки свои:
    YTAI_HOST (если волна 3 начнёт его выставлять), имя машины, данные фильма под ~/YTAI_work (так они лежат
    только на Memex и в golden-прогонах). Любое сомнение — не 'mac', а значит без картинок."""
    env = os.environ if env is None else env
    declared = str(env.get('YTAI_HOST') or '').strip().lower()
    if declared and declared != 'mac':
        return 'memex' if declared == 'memex' else 'unknown'
    try:
        name = (hostname if hostname is not None else socket.gethostname()).lower()
    except Exception:                                       # noqa: BLE001
        return 'unknown'
    if 'memex' in name:
        return 'memex'
    if review_dir is not None:
        try:
            if Path(review_dir).resolve().is_relative_to((Path.home() / 'YTAI_work').resolve()):
                return 'memex'
        except Exception:                                   # noqa: BLE001
            return 'unknown'
    return 'mac' if sys.platform == 'darwin' else 'unknown'


def detect_autonomous(ctl_dir=None, env=None):
    """автономный прогон: флаг-файл AUTONOMOUS в ~/.cache/<project>/ (его ставит review.py run --autonomous и
    держит сторож Memex) либо YTAI_AUTONOMOUS=1. Не смогли проверить — считаем автономным."""
    env = os.environ if env is None else env
    if str(env.get('YTAI_AUTONOMOUS') or '').strip().lower() in ('1', 'true', 'yes'):
        return True
    if ctl_dir is None:
        return False
    try:
        return (Path(ctl_dir) / 'AUTONOMOUS').exists()
    except Exception:                                       # noqa: BLE001
        return True


def pick_mode(card_mode, shots_remote, cli_images, host, autonomous, log=print):
    """режим картинок ЭТОЙ вкладки: 'none' | 'temp_grant'. Постоянно открытую папку (public_folder) здесь не
    используем: в кадрах ребёнок — такая строка в карточке для этой вкладки означает «без картинок»."""
    import doc_images as DI
    mode = DI.resolve_mode(card_mode, shots_remote, cli_images, host, autonomous)
    if mode == 'public_folder':
        log('⚠️ images_mode=public_folder: для вкладки «Обратная связь» открытая папка кадров не используется — '
            'вкладка соберётся без картинок (кадры — в HTML-файле)')
        return 'none'
    if cli_images == 'temp' and mode != 'temp_grant':
        log(f'⚠️ --images temp не сработал: в карточке images_mode={card_mode or "—"}, машина: {host}, '
            f'автономный прогон: {"да" if autonomous else "нет"} — вкладка соберётся без картинок')
    return mode if mode == 'temp_grant' else 'none'


def guard_test_pair(env=None):
    """тестовый прогон подменяет док И папку кадров разом. Подменён только один — кадры ушли бы не в ту пару
    (тестовый док + рабочая папка или наоборот)."""
    env = os.environ if env is None else env
    doc, folder = bool(env.get('YTAI_DOC_ID')), bool(env.get('YTAI_PRIVATE_FRAMES_FOLDER_ID'))
    if doc != folder:
        have, miss = (('YTAI_DOC_ID', 'YTAI_PRIVATE_FRAMES_FOLDER_ID') if doc else
                      ('YTAI_PRIVATE_FRAMES_FOLDER_ID', 'YTAI_DOC_ID'))
        raise SystemExit(f'задан {have}, но не задан {miss}: для прогона с кадрами док и закрытая папка кадров '
                         f'подменяются только ВМЕСТЕ — иначе кадры уйдут не в ту пару док/папка. Задай оба или ни одного.')


def _card_raw(P, key):
    """значение ключа ТОЛЬКО из карточки, в обход окружения YTAI_<KEY> (контракт §1: images_mode)"""
    fn = getattr(P, 'card_only', None)
    if callable(fn):
        return fn(key)
    try:
        return json.loads(Path(P.CARD_PATH).read_text(encoding='utf-8')).get(key)
    except Exception:                                       # noqa: BLE001
        return None


def _pairs(v):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            v = []
    return {tuple(x) for x in (v or []) if isinstance(x, (list, tuple)) and len(x) == 2}


# ═══════════════════ запись ═══════════════════
# страница ЭТОЙ вкладки — альбомная Letter с полями 36 pt: полезно 720 pt ≥ 676 pt таблицы. На портретной странице
# (468 pt полезных) шесть колонок с двумя картинками не помещаются: в браузере Docs таблица вылезает за поля,
# а PDF-экспорт и печать режут шестую колонку (проверено 22.09.2026 на тестовом доке). Формат задаётся только
# своей вкладке (tabId) — остальные вкладки дока не трогаются.
PAGE = {'pageSize': {'width': {'magnitude': 792, 'unit': 'PT'}, 'height': {'magnitude': 612, 'unit': 'PT'}},
        'marginLeft': {'magnitude': 36, 'unit': 'PT'}, 'marginRight': {'magnitude': 36, 'unit': 'PT'},
        'marginTop': {'magnitude': 36, 'unit': 'PT'}, 'marginBottom': {'magnitude': 36, 'unit': 'PT'}}


def page_request(tab_id):
    return {'updateDocumentStyle': {'tabId': tab_id, 'documentStyle': PAGE,
                                    'fields': 'pageSize,marginLeft,marginRight,marginTop,marginBottom'}}


def write(doc_id, title, rows, head, lang='ru', *, frozen=(), force=False, insert_images=None,
          get_doc=None, batch=None, log=print):
    tab_id = DT.write_tab(doc_id, title, head, hdr(lang), rows, WIDTHS, col_img=C_ERR, img_w={C_ERR: IMG_W, C_FIX: IMG_W},
                          font=FONT, frozen=frozen, force=force, insert_images=insert_images,
                          get_doc=get_doc, batch=batch, log=log, after=[page_request])
    return tab_id


def _img_request(tab_id, q, uri=None):
    ins = {'location': {'tabId': tab_id, 'index': q['index']},
           'objectSize': {'width': {'magnitude': q['width_pt'], 'unit': 'PT'}}}
    if uri:
        ins['uri'] = uri
    return {'name': q['name'], 'insertInlineImage': ins}


def dump(fb, path, *, title=None, lang='ru', have_frames=None, tz_tab=None, visuals=None, say=None, frozen=(),
         force=False, log=print):
    """вкладка на офлайн-двойнике Docs → файл дампа. Ни Docs, ни Drive не вызываются; картинки — fake://<имя>.
    В дампе: пачки запросов, итоговый текст, итоговый документ (final_doc), индекс визуалов и речь (по ним
    проверка пересобирает строки) и отпечаток модели — без дат и путей."""
    from fake_docs import FakeDocs
    title = title or i18n.TL(lang, 'fb.tab_template', ver=fb.get('cut_version', ''))
    rows, head = build_rows(fb, lang, have_frames, tz_tab, visuals, say)
    fd = FakeDocs()

    def put(tab_id, img_reqs):
        reqs = [_img_request(tab_id, q, 'fake://' + q['name']) for q in img_reqs]
        fd.batch_update(DUMP_DOC, [{'insertInlineImage': r['insertInlineImage']} for r in reqs])
        return {'inserted': len(reqs), 'failed': [], 'revoke_failed': []}

    write(DUMP_DOC, title, rows, head, lang, frozen=frozen, force=force, insert_images=put,
          get_doc=fd.get_doc, batch=fd.batch_update, log=log)
    n_img = sum(len(r['imgs']) for r in rows)
    fd.dump(path, {'surface': 'doc_tab_feedback_v1', 'tab_title': title, 'lang': lang, 'widths': WIDTHS,
                   'images': 'fake' if n_img else 'none', 'frames': sorted(have_frames or ()), 'tz_tab': tz_tab,
                   'visuals': {k: visuals[k] for k in sorted(visuals)} if visuals else None,
                   'say': {k: say[k] for k in sorted(say)} if say else None,
                   'fb_sha': fb_sha(fb), 'fb': {k: fb.get(k) for k in ('code', 'cut_version', 'built_at', 'build_no')},
                   'final_doc': fd.get_doc(DUMP_DOC)})
    return rows, head


def _load_card(optional):
    """карточка фильма — только здесь, не на уровне модуля. optional: офлайн-дамп с явным --fb обходится без неё."""
    try:
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        import _bootstrap as B  # noqa: E402
        return B
    except SystemExit:
        if optional:
            return None
        raise


def stats(rows):
    out = {}
    for r in rows:
        k = r['meta']['role']
        out[k] = out.get(k, 0) + 1
    out['картинок'] = sum(len(r['imgs']) for r in rows)
    out['ошибка'] = sum(1 for r in rows for cj, _, _ in r['imgs'] if cj == C_ERR)
    out['как надо'] = sum(1 for r in rows for cj, _, _ in r['imgs'] if cj == C_FIX)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='вкладка Google Doc «Обратная связь · vN» из work/{cut}/feedback.json')
    ap.add_argument('--fb', help='путь к feedback.json (по умолчанию — work/{cut}/feedback.json по карточке)')
    ap.add_argument('--images', choices=['none', 'temp'], help='temp — кадры под временным доступом (только с Мака, вручную)')
    ap.add_argument('--dump-requests', metavar='FILE', help='офлайн: все запросы и итоговый документ → FILE, сеть не трогается')
    ap.add_argument('--frames-dir', metavar='DIR', help='от какой папки считать пути картинок (по умолчанию — 05_Review)')
    ap.add_argument('--force', action='store_true', help='перезаписать НЕпустую вкладку (замороженную не трогает никогда)')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.images == 'temp':
        guard_test_pair()

    B = _load_card(optional=bool(a.dump_requests and a.fb))
    P = B.P if B else None
    fb = V.load(a.fb) if a.fb else V.load(B.W6 / 'feedback.json')
    lang = P.LANG if P else 'ru'
    if P and str(fb.get('cut_version') or '') != str(P.CUT_VERSION):
        raise SystemExit(f'модель собрана для ката {fb.get("cut_version")}, а карточка — про {P.CUT_VERSION}: '
                         f'пересобери модель (shared/feedback_model.py)')
    title = str((P.get('feedback_tab') if P else '') or i18n.TL(lang, 'fb.tab_template', ver=fb.get('cut_version', '')))
    tz_tab = None
    if P:
        tz_tab = (os.environ.get('TZ_TAB') or P.get('tab_title')
                  or str(P.profile('doc.tab_tz_template', i18n.TL(lang, 'c2.tz_tab_template'))).format(ver=P.CUT_VERSION))
    frozen = (_pairs(P.get('frozen_tabs', [])) | _pairs(P.profile('doc.frozen_tabs', []))) if P else set()
    base = Path(a.frames_dir) if a.frames_dir else (Path(P.REVIEW_DIR) if P else Path(a.fb).resolve().parent)
    visuals = load_visuals(index_path(a.fb, B.W6 if B else None))
    say = compute_say(fb) if P else {}                      # речь читается по карточке; без неё колонка пустая

    # ── офлайн-дамп ──
    if a.dump_requests:
        real_doc = str(P.get('doc_id', '') or '') if P else ''
        if (real_doc, title) in frozen:
            raise SystemExit(f'вкладка «{title}» в этом доке заморожена: в ней ручные правки. force заморозку не снимает.')
        have = frames_on_disk(fb, base, visuals) if a.images == 'temp' else None
        rows, _head = dump(fb, a.dump_requests, title=title, lang=lang, have_frames=have, tz_tab=tz_tab, visuals=visuals,
                           say=say, frozen={(DUMP_DOC, t) for d, t in frozen if d == real_doc}, force=a.force)
        print(f'вкладка «{title}»: {stats(rows)}', flush=True)
        return 0

    # ── настоящий док ──
    import doc_images as DI
    doc_id = P.need('doc_id')
    # заморозка — раньше всего остального: иначе кадры уехали бы на Drive ради вкладки, которую писать нельзя
    # (write_tab проверит её ещё раз — по текущему имени найденной вкладки)
    if (doc_id, title) in frozen:
        raise SystemExit(f'вкладка «{title}» в этом доке заморожена: в ней ручные правки. force заморозку не снимает.')
    mode = pick_mode(_card_raw(P, 'images_mode'), P.SHOTS_REMOTE, a.images,
                     detect_host(P.REVIEW_DIR), detect_autonomous(P.CTL_DIR))
    rc = 0
    ledger = B.W6 / 'feedback_grants.json'
    with DT.lock(P.REVIEW_DIR, what='doc_feedback'):
        if mode != 'temp_grant':
            # прошлый прогон с кадрами могли убить: его открытые доступы закрываем и в прогоне без картинок,
            # молча пройти мимо непустого журнала нельзя
            try:
                pending = DI.ledger_pending(ledger)
            except ValueError as e:
                pending = [str(e)]
            if pending:
                _closed, stuck = DI.revoke_from_ledger(ledger)
                if stuck:
                    print(f'⚠️ в журнале временных доступов остались незакрытые записи ({len(stuck)}) — кадры прошлого '
                          f'прогона могут быть открыты: python3 shared/doc_images.py --revoke-ledger {ledger}', flush=True)
                    rc = 1
                else:
                    print(f'журнал временных доступов: закрыто записей прошлого прогона — {len(_closed)}', flush=True)
            rows, head = build_rows(fb, lang, None, tz_tab, visuals, say)
            try:
                tab_id = write(doc_id, title, rows, head, lang, frozen=frozen, force=a.force)
            except Exception:                                # noqa: BLE001
                print(HALF.format(title=title), flush=True)
                raise
        else:
            folder = str(P.get('private_frames_folder_id', '') or '')
            _closed, stuck = DI.revoke_from_ledger(ledger)   # страховка после убитого прошлого прогона
            if stuck:
                raise SystemExit(f'в журнале временных доступов остались незакрытые записи ({len(stuck)}): '
                                 f'python3 shared/doc_images.py --revoke-ledger {ledger}')
            try:
                DI.preflight(folder)
            except DI.Refused as e:
                raise SystemExit(f'кадры в док не вставляю: {e}')
            try:
                files = prepare_visuals(fb, visuals, B.W6 / 'feedback_doc_frames', base_dir=base)
                ids = DI.upload_all(folder, files, B.M / 'feedback_frames_ids.json') if files else {}
                have = {f['row_key'] + '/' + f['kind'] for f in files if f['name'] in ids}
                rows, head = build_rows(fb, lang, have, tz_tab, visuals, say)

                def put(tab_id, img_reqs):
                    return DI.insert_with_temp_grant(doc_id, [_img_request(tab_id, q) for q in img_reqs], ids, ledger)

                tab_id = write(doc_id, title, rows, head, lang, frozen=frozen, force=a.force, insert_images=put)
                res = DT.LAST.get('images') or {}
                print(f'картинки: вставлено {res.get("inserted", 0)}, не вставлено {len(res.get("failed") or [])}, '
                      f'самое длинное окно доступа {res.get("max_window_sec", 0)} с', flush=True)
                for f in (res.get('failed') or [])[:20]:
                    print(f'  ! {f.get("name")}: {f.get("why")}', flush=True)
                if res.get('failed') or res.get('revoke_failed'):
                    rc = 1
            except DI.Refused as e:                          # отказ по приватности посреди работы (журнал, папка)
                raise SystemExit(f'кадры в док не вставляю: {e}')
            except Exception:                                # noqa: BLE001
                print(HALF.format(title=title), flush=True)
                raise
            finally:                                         # ревизор — при любом исходе: открытых кадров остаться не должно
                problems = DI.audit(folder, ledger)
                for p in problems[:30]:
                    print(f'  ! {p}', flush=True)
                if problems:
                    print(f'РЕВИЗОР ДОСТУПОВ: проблем {len(problems)} — кадры могут быть открыты, разберись до любых '
                          f'следующих шагов', flush=True)
                    rc = 1
    print(f'вкладка «{title}»: {stats(rows)}', flush=True)
    print(f'https://docs.google.com/document/d/{doc_id}/edit?tab={tab_id}', flush=True)
    return rc


# ═══════════════════ самопроверка (офлайн) ═══════════════════
def synthetic():
    """модель на все секции и краевые случаи: блокер с опечаткой, эмодзи вне BMP, ❌ длиннее 500 знаков, пункт без
    времени и кадра, примерное место («≈»), дубль в Часть 1, блюр must/should, темы фонда и пункт без темы,
    строка прошлого ТЗ с двумя таймкодами (WARN), мусорный управляющий знак в тексте."""
    def row(part, n, bucket, status, sec, **kw):
        tc = f'{int(sec) // 60}:{int(sec) % 60:02d}' if sec is not None else ''
        r = {'part': part, 'n': n, 'label': f'ТЗ-{n:02d}', 'key': f'k:{part}:{n}', 'title': f'Пункт {n}', 'category': 'cut',
             'severity': 'should' if part == 2 else 'medium', 'sensitive': False, 'blocker': False,
             'sec_old': None, 'tc_old': '', 'sec_new': sec, 'tc_new': tc, 'err': 0.4, 'how': 'native' if part == 1 else 'span',
             'tc_fixed': False, 'parts': {'now': [f'{tc} ▸ сейчас так' if tc else 'сейчас так'], 'do': ['сделать иначе'],
                                          'where': [tc] if tc else []},
             'more': 0, 'status': status, 'status_by': 'code', 'checks': [], 'bucket': bucket, 'dup_of': None,
             'topic': None, 'topic_title': None, 'typo': [], 'agent_note': '',
             'evidence': {'kind': 'code', 'tc': tc, 'sec': sec, 'text': 'реплика на месте'} if part == 2 else None,
             'frame': {'file': f'frames/h{int(sec) + 1:04d}.jpg', 'sec': int(sec), 'what': 'кадр ката v5'} if sec is not None else None}
        r.update(kw)
        return r
    long_now = ('5:10 ▸ ' + 'Фонд входит в рассказ слишком рано, зритель ещё не знает героиню. ' * 7 +
                'Правило канала — не раньше 34-й минуты.')
    assert len(long_now) > 500
    p1 = [row(1, 1, 'new', 'new', 42, category='graphics', severity='high', blocker=True,
              title='Опечатка в титре с именем героини', typo=[{'was': 'ЖУМАГУЛ', 'now': 'ЖИМАГУЛ'}],
              parts={'now': ['0:42 ▸ в титре фамилия написана с ошибкой'],
                     'do': ['исправить фамилию в титре', 'проверить тот же титр в финале'], 'where': ['0:42–0:47']}),
          row(1, 2, 'new', 'new', 676, category='structure', blocker=True, title='Фонд входит слишком рано 👁', more=1,
              parts={'now': ['11:16 ▸ куратор объясняет работу фонда'], 'do': ['перенести вход фонда за 34-ю минуту'],
                     'where': ['11:16–11:40']}),
          row(1, 3, 'new', 'new', None, category='color', title='Громкость музыки по всему фильму')]
    p2 = [row(2, 40, 'block', 'open', 676.2, dup_of=2, severity='must', category='structure', title='Вход фонда'),
          row(2, 9, 'block', 'open', 310.0, severity='must', blocker=True, more=5, err=4.2, category='insert',
              title='Вернуть вырезанные реплики \x07героини',
              parts={'now': [long_now, 'вторая строка «сейчас»'],
                     'do': ['вернуть реплики', '5:12 ▸ первая', '5:20 ▸ вторая', 'проверить звук', 'пятая строка'],
                     'where': ['5:10–5:24', 'ещё одно место']}),
          row(2, 11, 'open', 'open', 900.0, category='graphics',
              parts={'now': ['15:00 ▸ плашка держится до 15:04 вместо положенных секунд'], 'do': ['укоротить плашку'],
                     'where': ['15:00']}),
          row(2, 12, 'open', 'open', None, category='check', title='Общее правило титров'),
          row(2, 13, 'open', 'open', 1200.0, title='Кадр не приехал с Memex'),
          row(2, 20, 'blur', 'fund', 100.0, sensitive=True, category='fund', title='Размыть лицо соседки'),
          row(2, 21, 'blur', 'fund', 200.0, sensitive=True, severity='must', category='fund', title='Обезличить документ'),
          row(2, 30, 'closed', 'closed', 500.0), row(2, 31, 'closed', 'closed', 400.0, err=6.0),
          row(2, 50, 'fund', 'fund', 800.0, sensitive=True, topic='a', topic_title='Тема А',
              parts={'now': [], 'do': ['согласовать фамилию врача'], 'where': []}),
          row(2, 51, 'fund', 'fund', 700.0, sensitive=True, topic='b', topic_title='Тема Б 📍'),
          row(2, 52, 'fund', 'fund', 750.0, sensitive=True),
          row(2, 60, 'appendix', 'unknown', 1000.0, evidence=None), row(2, 61, 'appendix', 'unknown', None, evidence=None)]
    return {'schema': 'feedback-v1', 'code': 'YTXX01', 'cut_version': 'v5', 'prev_cut_version': 'v4',
            'built_at': '2026-09-21 22:40', 'build_no': 3, 'duration_sec': 3094.08, 'prev_file': 'v4_review/pravki_v4.json',
            'tally': {'new': 3, 'prev_total': len(p2)}, 'summary_lines': ['Кат стал плотнее.'],
            'blockers': [{'part': 1, 'n': 1, 'label': 'ТЗ-01', 'tc': '0:42', 'do': 'исправить фамилию в титре'},
                         {'part': 1, 'n': 2, 'label': 'ТЗ-02', 'tc': '11:16', 'do': 'перенести вход фонда за 34-ю минуту'},
                         {'part': 2, 'n': 9, 'label': 'ТЗ-09', 'tc': '≈5:10', 'do': 'вернуть реплики'}],
            'fund_topics': [{'key': 'b', 'title': 'Тема Б 📍', 'count': 1}, {'key': 'a', 'title': 'Тема А', 'count': 1}],
            'frames_wanted': [], 'part1': p1, 'part2': p2}


def synthetic_visuals(fb, rel_dir='work/v5/' + VIS_DIR):
    """индекс визуалов (§9) на синтетическую модель: err у строк с временем, fix у КАЖДОЙ полной строки;
    у ТЗ-02 источник с адресом (ссылка), у ТЗ-11 подпись без времени впереди (сборщик добивает по канону),
    у ТЗ-31 адрес без схемы; файлы — synthetic_visual_files()"""
    rows = {}
    for r in _full_rows(fb):
        key, tc = row_key(r), str(r.get('tc_new') or '')
        stem = f'p{r["part"]}_{r["n"]:03d}'
        d = {}
        if tc:
            d['err'] = {'file': f'{rel_dir}/{stem}_err.jpg', 'caption': f'{tc} · {r["title"]} 👁'.replace(' \x07', ' '),
                        'kind': 'arrow', 'source': {'text': f'кадр ката v5, {tc}', 'url': None}}
        fix = {'file': f'{rel_dir}/{stem}_fix.jpg', 'caption': f'{tc or "сводно"} · как надо: {r["parts"]["do"][0]}',
               'kind': 'draft', 'source': {'text': f'наш драфт по кадру v5 {tc}'.strip(), 'url': None}}
        if key == '1:2':
            fix['source'] = {'text': 'референс: burodd.ru/team', 'url': 'https://burodd.ru/team'}
        if key == '2:11':
            fix['caption'] = 'подпись без времени впереди'
        if key == '2:31':
            fix['source'] = {'text': 'мокап стадии', 'url': 'burodd.ru/team'}
        d['fix'] = fix
        rows[key] = d
    return {'schema': 'feedback-visuals-v1', 'built_at': '2026-09-22 00:00', 'rows': rows}


def synthetic_visual_files(index_rows, base_dir, skip=('2:13/err',)):
    """крошечные JPEG по индексу (в офлайн-дампе картинки не читаются — важно только, что файл есть);
    skip — визуалы, которых «нет на диске» (кадр не приехал с Memex)"""
    from PIL import Image
    im = Image.new('RGB', (16, 9), (120, 120, 120))
    for key, kinds in index_rows.items():
        for kind, v in kinds.items():
            if f'{key}/{kind}' in skip or not v.get('file'):
                continue
            p = Path(base_dir) / v['file']
            p.parent.mkdir(parents=True, exist_ok=True)
            im.save(p, 'JPEG', quality=50)


def make_visuals(fb, base_dir, rel_dir='work/v5/' + VIS_DIR, skip=('2:13/err',)):
    """индекс + файлы под base_dir; индекс кладётся в base_dir/rel_dir/index.json. → rows индекса"""
    idx = synthetic_visuals(fb, rel_dir)
    p = Path(base_dir) / rel_dir / 'index.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding='utf-8')
    synthetic_visual_files(idx['rows'], base_dir, skip)
    return idx['rows']


def synthetic_say(fb):
    """речь колонки «Говорит» без транскрипта: у полных строк с временем, опорная фраза жирным; у ТЗ-13 речи нет"""
    out = {}
    for r in _full_rows(fb):
        tc = str(r.get('tc_new') or '')
        if not tc or row_key(r) == '2:13':
            continue
        text = f'Она узнала о фонде и обратилась за помощью 📍 на {tc}.\nПозвонила, сказала, что переехала.'
        out[row_key(r)] = {'text': text, 'bold': [[11, 18]]}
    return out


# имитация живой ветки main() для самопроверки: сеть закрыта наглухо, шаги Drive подменены протоколом вызовов;
# detect_host / detect_autonomous / pick_mode / revoke_from_ledger / замок / compute_say — НАСТОЯЩИЕ
_LIVE_SIM = r"""
import json, os, sys
from pathlib import Path
sys.path.insert(0, %(here)r)
import doc_tab_feedback_v1 as B
import doc_table as DT
import doc_images as DI
from fake_docs import FakeDocs
FAIL = os.environ.get('SIM_FAIL', '')
fd, calls = FakeDocs(), []
def net(*a, **k):
    raise AssertionError('сеть')
DI._api = DI._anon = DI._token = DT._token = DT._http = net
# самопроверка идёт и на Memex, и на Linux: машина считается Маком, пока сценарий сам не объявит другую
B.detect_host = (lambda real: lambda *a, **k: real(*a, **k) if os.environ.get('YTAI_HOST') else 'mac')(B.detect_host)
orig = DT.write_tab
def write_tab(*a, **k):
    lockf = Path(os.environ['YTAI_CARD']).parent / 'logs' / 'doc_write.lock'
    calls.append('write_tab' if lockf.exists() else 'write_tab БЕЗ ЗАМКА')
    if FAIL == 'write':
        raise RuntimeError('обрыв посреди записи')
    k['get_doc'], k['batch'], k['log'] = fd.get_doc, fd.batch_update, (lambda *x: None)
    return orig(*a, **k)
DT.write_tab = write_tab
real_revoke = DI.revoke_from_ledger
DI.revoke_from_ledger = lambda p: (calls.append('revoke_from_ledger') or real_revoke(p))
DI.revoke = lambda fid, perm: (calls.append('revoke:' + str(fid)) or FAIL != 'stuck')
DI.preflight = lambda f: calls.append('preflight:' + str(f))
real_prepare = B.prepare_visuals
B.prepare_visuals = lambda *a, **k: (calls.append('prepare') or real_prepare(*a, **k))
DI.upload_all = lambda folder, files, ids: (calls.append('upload_all') or {f['name']: 'id_' + f['name'] for f in files})
def ins(doc_id, reqs, ids, ledger):
    calls.append('insert')
    assert all(set(q) == {'name', 'insertInlineImage'} and 'uri' not in q['insertInlineImage'] for q in reqs)
    assert all(q['insertInlineImage']['objectSize']['width']['magnitude'] == B.IMG_W for q in reqs)
    idx = [q['insertInlineImage']['location']['index'] for q in reqs]
    assert idx == sorted(idx, reverse=True), 'картинки обязаны идти по убыванию индекса'
    done = reqs[:2] if FAIL == 'insert' else reqs
    fd.batch_update(doc_id, [{'insertInlineImage': dict(q['insertInlineImage'], uri='fake://' + q['name'])} for q in done])
    if FAIL == 'insert':
        raise RuntimeError('обрыв после двух картинок')
    return {'inserted': len(reqs), 'failed': [], 'revoke_failed': [], 'max_window_sec': 1.0}
DI.insert_with_temp_grant = ins
DI.audit = lambda folder, ledger: (calls.append('audit') or (['у файла остался доступ по ссылке'] if FAIL == 'dirty' else []))
rc, err = None, ''
try:
    rc = B.main(sys.argv[1:])
except SystemExit as e:
    err = 'SystemExit: ' + str(e)
except Exception as e:
    err = type(e).__name__ + ': ' + str(e)
txt = fd.tab_text() if fd.tabs else ''
print('SIM ' + json.dumps({'rc': rc, 'err': err, 'calls': calls, 'tabs': [t['title'] for t in fd.tabs],
                           'img': txt.count('[IMG]'), 'said': 'о фонде и' in txt, 'batches': len(fd.batches)}, ensure_ascii=False))
"""


def _selftest_live(tmp, env):
    """живая ветка main() на подменённой сети: временный доступ сам не включается, отзыв — до записи, ревизор — после
    любого исхода, заморозка — раньше заливки кадров, замок взят, непустой журнал не проходит молча, речь из words"""
    import subprocess
    rd = tmp / 'film' / '00_Setup' / '05_Review'
    fb = synthetic()
    (rd / 'work' / 'v5').mkdir(parents=True)
    (rd / 'work' / 'v5' / 'feedback.json').write_text(json.dumps(fb, ensure_ascii=False), encoding='utf-8')
    # транскрипт для said.py: одно предложение вокруг 11:16 (ТЗ-02) — колонка «Говорит» заполняется по-настоящему
    words = [{'w': w, 's': 674.0 + i * 0.4, 'e': 674.3 + i * 0.4} for i, w in
             enumerate('Она узнала о фонде и обратилась за помощью.'.split())]
    (rd / 'words.json').write_text(json.dumps({'segments': [{'speaker': 'A', 'words': words}]}, ensure_ascii=False), encoding='utf-8')
    visuals = make_visuals(fb, rd)
    n_frames = len(frames_on_disk(fb, rd, visuals))
    assert n_frames == sum(len(v) for v in visuals.values()) - 1
    ledger = rd / 'work' / 'v5' / 'feedback_grants.json'
    tab = 'Обратная связь · v5'

    def card(**kw):
        c = {'project': 'ytxx01_selftest', 'code': 'YTXX01', 'cut_version': 'v5', 'words': 'words.json', 'doc_id': 'DOC-TEST',
             'duration_sec': 3094, 'private_frames_folder_id': 'FOLDER-TEST', 'images_mode': 'temp_grant',
             'ctl_dir': str(tmp / 'ctl'), 'frozen_tabs': [['DOC-TEST', 'Сверка v4 → v5']]}
        c.update(kw)
        (rd / 'review_card.json').write_text(json.dumps({k: v for k, v in c.items() if v is not None}, ensure_ascii=False),
                                             encoding='utf-8')

    def run(*args, **extra):
        e = dict(env, YTAI_CARD=str(rd / 'review_card.json'), **extra)
        r = subprocess.run([sys.executable, '-c', _LIVE_SIM % {'here': str(HERE)}, *args], capture_output=True, text=True,
                           cwd='/tmp', env=e)
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith('SIM ')), None)
        assert line, r.stdout[-800:] + r.stderr[-800:]
        return json.loads(line[4:]), r.stdout

    temp_chain = ['revoke_from_ledger', 'preflight:FOLDER-TEST', 'prepare', 'upload_all', 'write_tab', 'insert', 'audit']
    card()
    o, _ = run()                                            # в карточке temp_grant, но флага нет
    assert o['calls'] == ['write_tab'] and o['img'] == 0 and o['rc'] == 0 and o['said'], o
    o, _ = run('--images', 'temp')
    assert o['calls'] == temp_chain and o['img'] == n_frames and o['rc'] == 0 and o['tabs'] == [tab], o
    assert (rd / 'work' / 'v5' / 'feedback_doc_frames' / 'fb_p1_002_fix.jpg').is_file()
    for extra in ({'YTAI_HOST': 'memex'}, {'YTAI_AUTONOMOUS': '1'}):
        o, out = run('--images', 'temp', **extra)
        assert o['calls'] == ['write_tab'] and o['img'] == 0 and '--images temp не сработал' in out, (extra, o)
    (tmp / 'ctl').mkdir(exist_ok=True)
    (tmp / 'ctl' / 'AUTONOMOUS').write_text('x')
    o, _ = run('--images', 'temp')                          # флаг-файл автономного прогона
    assert o['calls'] == ['write_tab'] and o['img'] == 0, o
    (tmp / 'ctl' / 'AUTONOMOUS').unlink()
    card(images_mode=None)                                  # режим подсунут окружением, в карточке его нет
    o, _ = run('--images', 'temp', YTAI_IMAGES_MODE='temp_grant')
    assert o['calls'] == ['write_tab'] and o['img'] == 0, o
    card()
    for one in ({'YTAI_DOC_ID': 'X'}, {'YTAI_PRIVATE_FRAMES_FOLDER_ID': 'X'}):
        o, _ = run('--images', 'temp', **one)
        assert 'ВМЕСТЕ' in o['err'] and o['calls'] == [] and o['batches'] == 0, o
    o, _ = run('--images', 'temp', YTAI_DOC_ID='X', YTAI_PRIVATE_FRAMES_FOLDER_ID='Y')
    assert o['calls'] == ['revoke_from_ledger', 'preflight:Y'] + temp_chain[2:], o
    # сбой посреди картинок и до них: ревизор обязан отработать, подсказка про --force — напечатана
    for how, n_img in (('insert', 2), ('write', 0)):
        o, out = run('--images', 'temp', SIM_FAIL=how)
        assert o['calls'][-1] == 'audit' and o['err'].startswith('RuntimeError') and o['img'] == n_img and '--force' in out, o
    o, out = run('--images', 'temp', SIM_FAIL='dirty')      # ревизор нашёл открытый файл → код возврата ≠ 0
    assert o['rc'] == 1 and 'РЕВИЗОР ДОСТУПОВ' in out, o
    # заморозка: отказ ДО любой заливки кадров и любой записи, force не помогает
    card(frozen_tabs=[['DOC-TEST', tab]])
    o, _ = run('--images', 'temp', '--force')
    assert 'заморожена' in o['err'] and o['calls'] == [] and o['batches'] == 0, o
    card(frozen_tabs=None, feedback_tab='Своя вкладка')      # имя вкладки — из карточки
    o, _ = run()
    assert o['tabs'] == ['Своя вкладка'], o
    # индекса визуалов нет: вкладка пишется без картинок, с предупреждением, без падения
    idx = rd / 'work' / 'v5' / VIS_DIR / 'index.json'
    idx.rename(idx.with_suffix('.bak'))
    card()
    o, out = run('--images', 'temp')
    assert o['rc'] == 0 and o['img'] == 0 and 'индекса визуалов нет' in out and o['calls'] == temp_chain[:3] + ['write_tab', 'audit'], o   # без файлов заливки нет
    idx.with_suffix('.bak').rename(idx)
    # непустой журнал в прогоне БЕЗ картинок: доступы закрываются; не закрылись — код возврата ≠ 0
    entry = {'schema': 'feedback-grants-v1', 'open': [{'fid': 'FID1', 'perm_id': 'p', 'name': 'fb_p1_001_err.jpg'}], 'batches': []}
    ledger.write_text(json.dumps(entry), encoding='utf-8')
    o, _ = run(SIM_FAIL='stuck')
    assert o['calls'] == ['revoke_from_ledger', 'revoke:FID1', 'write_tab'] and o['rc'] == 1, o
    assert json.loads(ledger.read_text(encoding='utf-8'))['open'], 'незакрытая запись пропала из журнала'
    o, _ = run('--images', 'temp', SIM_FAIL='stuck')        # с кадрами при незакрытом журнале — отказ до всего
    assert 'незакрытые записи' in o['err'] and o['calls'] == ['revoke_from_ledger', 'revoke:FID1'] and o['batches'] == 0, o
    o, _ = run('--force')
    assert o['calls'] == ['revoke_from_ledger', 'revoke:FID1', 'write_tab'] and o['rc'] == 0, o
    assert not json.loads(ledger.read_text(encoding='utf-8'))['open']
    # замок: пока в док пишет живой процесс — отказ до любых вызовов
    lockf = rd / 'logs' / 'doc_write.lock'
    lockf.write_text(json.dumps({'pid': os.getpid(), 'host': socket.gethostname(), 'what': 'чужой', 'started': 'x'}), encoding='utf-8')
    o, _ = run('--force')
    assert 'пишет другой процесс' in o['err'] and o['calls'] == [], o
    lockf.unlink()


def selftest():
    import subprocess
    import tempfile
    quiet = lambda *a, **k: None                            # noqa: E731
    fb = synthetic()
    assert V.lint(fb) == [] or all(lv == 'WARN' for lv, _, _ in V.lint(fb)), V.lint(fb)
    tmp = Path(tempfile.mkdtemp(prefix='doc_tab_feedback_selftest_'))
    visuals = make_visuals(fb, tmp, rel_dir=VIS_DIR)      # индекс рядом с моделью: tmp/feedback_visuals/index.json
    say = synthetic_say(fb)

    # ── строки: чистая функция, одна таблица, секции в порядке общего слоя ──
    rows, head = build_rows(fb)
    assert sum(WIDTHS) == DT.TOTAL_W == 676 and len(hdr('ru')) == len(WIDTHS) == 6 and WIDTHS == [40, 44, 104, 168, 160, 160]
    assert hdr('ru') == ['№', '⏱ TC', 'Говорит', 'Вердикт и почему', 'Экран с ошибкой', 'Как надо'] and hdr('en')[2] == 'Says'
    secs = [r for r in rows if r['meta']['role'] == 'sec']
    assert [s['meta']['bucket'] for s in secs] == [b for b, _, _ in V.sections(fb)] == list(V.ORDER)
    assert secs[0]['cells'][C_VERDICT] == '[ЧАСТЬ 1 · НОВОЕ В v5 · 3]' and secs[1]['cells'][C_VERDICT] == '[🔴 БЛОКИРУЕТ ВЫПУСК · 2]'
    p2 = [r for r in rows if r['meta']['role'] == 'part2']
    assert len(p2) == 1 and rows.index(p2[0]) == rows.index(secs[1]) - 1
    assert p2[0]['cells'][C_VERDICT].split('\n')[0] == '[ЧАСТЬ 2 · ПРОВЕРКА ТЗ v4 · 14]'
    assert all(r['cells'][C_VERDICT].startswith('[') and r['head_col'] == C_VERDICT for r in rows if r['kind'] == 'sec')
    assert ('meta', 'кадры — в HTML-файле') in head and not any(r['imgs'] for r in rows)     # без картинок — строка в шапке
    assert stats(rows) == {'sec': 7, 'part2': 1, 'item': 11, 'dup': 1, 'list': 2, 'картинок': 0, 'ошибка': 0, 'как надо': 0}, stats(rows)
    assert head[-2][0] == 'how' and 'Вердикт и почему' in head[-2][1] and 'Как надо' in head[-1][1]
    assert all(len(r['cells']) == 6 for r in rows)

    have = frames_on_disk(fb, tmp, visuals)
    n_full = len(_full_rows(fb))
    assert n_full == 11 and len(have) == n_full + 8 and '2:13/err' not in have and '2:13/fix' in have and '1:3/err' not in have, have
    rows, head = build_rows(fb, have_frames=have, visuals=visuals, say=say)
    assert ('meta', 'кадры — в HTML-файле') not in head
    by = {(r['meta'].get('part'), r['meta'].get('n')): r for r in rows if r['meta']['role'] in ('item', 'dup')}
    r1 = by[(1, 1)]
    assert r1['cells'][C_NUM] == 'ТЗ-01 🔴\n🎨' and r1['cells'][C_TC] == '0:42'
    t = r1['cells'][C_VERDICT].split('\n')
    assert t[:4] == ['❌ НЕПРАВИЛЬНО', '【Опечатка в титре с именем героини】', 'Почему: 0:42 ▸ в титре фамилия написана с ошибкой',
                     'было «ЖУМАГУЛ» → стало «ЖИМАГУЛ»'], t
    assert '❌ СЕЙЧАС' not in r1['cells'][C_VERDICT], 'без доказательства строка ❌ уже в «Почему:» — второй раз не печатается'
    got = {(r1['cells'][C_VERDICT][sp[0]:sp[1]], sp[2]) for sp in r1['spans'][C_VERDICT]}
    assert {('❌ НЕПРАВИЛЬНО', 'was'), ('ЖУМАГУЛ', 'was'), ('ЖИМАГУЛ', 'now'), ('Почему:', 'label'),
            ('【Опечатка в титре с именем героини】', 'title')} <= got, got
    assert r1['spans'][C_VERDICT][0] == (0, len('❌ НЕПРАВИЛЬНО'), 'was'), 'вердикт — первый спан, первая строка'
    f = r1['cells'][C_FIX].split('\n')
    assert f[:3] == ['✅ СДЕЛАТЬ · исправить фамилию в титре', '     проверить тот же титр в финале', '📍 ГДЕ · 0:42–0:47'], f
    assert f[3] == '' and f[4] == '0:42 · как надо: исправить фамилию в титре' and f[5] == 'Источник: наш драфт по кадру v5 0:42', f
    assert r1['imgs'] == [(C_ERR, 0, 'fb_p1_001_err.jpg'), (C_FIX, 3, 'fb_p1_001_fix.jpg')], r1['imgs']
    assert r1['cells'][C_ERR] == '\n0:42 · Опечатка в титре с именем героини 👁' and r1['spans'][C_ERR] == [(1, len(r1['cells'][C_ERR]), 'cap')]
    assert V.CAP_RE.match(f[4]) and V.CAP_RE.match(r1['cells'][C_ERR].split('\n')[1])
    assert r1['cells'][C_SAID].startswith('Она узнала о фонде и') and '\n' in r1['cells'][C_SAID]
    assert r1['spans'][C_SAID] == [(11, 18, 'title')] and r1['cells'][C_SAID][11:18] == 'о фонде'
    led = _said_cell({'part': 1, 'n': 1}, {'1:1': {'text': '\n\nОна узнала о фонде', 'bold': [[13, 20]]}})   # переводы строки впереди
    assert led.text == 'Она узнала о фонде' and led.spans == [(11, 18, 'title')] and led.text[11:18] == 'о фонде', led.spans
    r2 = by[(1, 2)]
    src = [sp for sp in r2['spans'][C_FIX] if sp[2] == 'link']
    assert src == [(r2['cells'][C_FIX].rfind('референс'), len(r2['cells'][C_FIX]), 'link', 'https://burodd.ru/team')], src
    assert r2['cells'][C_FIX].endswith('Источник: референс: burodd.ru/team')
    r3 = by[(1, 3)]                                          # без времени: нет речи, нет кадра ошибки, но «как надо» есть
    assert r3['cells'][C_TC] == '' and r3['cells'][C_SAID] == '' and r3['cells'][C_ERR] == '' and not any(cj == C_ERR for cj, _, _ in r3['imgs'])
    assert [cj for cj, _, _ in r3['imgs']] == [C_FIX] and 'сводно · как надо: сделать иначе' in r3['cells'][C_FIX]
    r13 = by[(2, 13)]                                        # кадр ошибки не приехал — колонка 5 пустая, «как надо» на месте
    assert r13['cells'][C_ERR] == '' and [cj for cj, _, _ in r13['imgs']] == [C_FIX] and r13['cells'][C_SAID] == ''
    r9 = by[(2, 9)]
    assert r9['cells'][C_NUM].startswith('ТЗ-09 · v4 🔴') and r9['cells'][C_TC] == '≈5:10'   # «≈» — только через общий слой
    v9 = r9['cells'][C_VERDICT].split('\n')
    assert '\x07' not in r9['cells'][C_VERDICT] and v9[0] == '❌ НЕПРАВИЛЬНО' and v9[2] == 'Почему: реплика на месте'
    assert v9[3].startswith('❌ СЕЙЧАС · 5:10 ▸ Фонд входит') and v9[-1] == 'ещё 9 строк — вкладка ТЗ v4, ТЗ-09', v9
    assert r9['cells'][C_FIX].count('✅ СДЕЛАТЬ ·') == 1 and '        ' + TB.FIG + '5:12  ▸ первая' in r9['cells'][C_FIX]
    r11 = by[(2, 11)]
    assert '\n15:00 · подпись без времени впереди\n' in r11['cells'][C_FIX], r11['cells'][C_FIX]   # подпись индекса добита по канону
    r31 = by[(2, 31)]
    assert r31['cells'][C_VERDICT].split('\n')[0] == '✅ ПРАВИЛЬНО' and r31['spans'][C_VERDICT][0][2] == 'now'
    assert [sp for sp in r31['spans'][C_FIX] if sp[2] == 'link'][0][3] == 'https://burodd.ru/team'   # адрес без схемы
    r20 = by[(2, 20)]
    assert r20['cells'][C_VERDICT].split('\n')[0] == '⚠️ БЛЮР — делает монтажёр' and r20['spans'][C_VERDICT][0][2] == 'warn'
    d = by[(2, 40)]
    assert d['meta']['role'] == 'dup' and d['cells'][C_VERDICT].split('\n')[0] == '11:16 ▸ не закрыто · перенесено в новое ТЗ-02 (Часть 1)'
    assert '✅' not in d['cells'][C_VERDICT] and d['cells'][C_ERR] == d['cells'][C_FIX] == d['cells'][C_SAID] == '' and not d['imgs']
    lists = {r['meta']['bucket']: r for r in rows if r['kind'] == 'list'}
    assert set(lists) == {'fund', 'appendix'}
    fl = lists['fund']['cells'][C_VERDICT].split('\n')
    assert fl[0] == '⚠️ ЖДЁТ ФОНДА' and fl[1] == 'Тема Б 📍' and fl[2].startswith(TB.IND2 + '11:40 ▸ ') and fl[-2] == 'Прочие согласования', fl
    assert lists['fund']['spans'][C_VERDICT][0] == (0, len(fl[0]), 'warn')
    assert [fl[1], fl[3], fl[5]] == [lists['fund']['cells'][C_VERDICT][s:e] for s, e, k in lists['fund']['spans'][C_VERDICT] if k == 'title']
    al = lists['appendix']['cells'][C_VERDICT].split('\n')
    assert al[0] == '👁 НЕ ПРОВЕРЕНО' and len(al) == 3 and lists['appendix']['spans'][C_VERDICT][0][2] == 'muted'
    assert all(not r['imgs'] and r['cells'][C_ERR] == '' and r['cells'][C_FIX] == '' for r in rows if r['kind'] != 'item')
    for r in rows:                                          # спаны не выходят за текст своей ячейки
        for cj, sp in r['spans'].items():
            assert all(0 <= s[0] < s[1] <= len(r['cells'][cj]) for s in sp), (r['meta'], cj)
    full = [r for r in rows if r['meta']['role'] == 'item']
    assert len(full) == n_full and all(any(cj == C_FIX for cj, _, _ in r['imgs']) for r in full), 'картинка «как надо» у каждой полной строки'
    assert all(r['cells'][C_VERDICT].split('\n')[0] in ('❌ НЕПРАВИЛЬНО', '✅ ПРАВИЛЬНО', '⚠️ БЛЮР — делает монтажёр') for r in full)
    assert stats(rows) == {'sec': 7, 'part2': 1, 'item': 11, 'dup': 1, 'list': 2, 'картинок': 19, 'ошибка': 8, 'как надо': 11}, stats(rows)
    assert build_rows(fb, have_frames=have, visuals=visuals, say=say) == (rows, head), 'build_rows обязана быть детерминированной'
    en_rows, en_head = build_rows(fb, 'en', have, visuals=visuals)
    assert en_head[0][1].startswith('Feedback on cut v5') and '✅ DO ·' in en_rows[2]['cells'][C_FIX]
    assert en_rows[2]['cells'][C_VERDICT].startswith('❌ WRONG\n') and 'Source: ' in en_rows[2]['cells'][C_FIX]
    assert i18n.LANG in ('ru', 'en') and build_rows(fb, have_frames=have, visuals=visuals, say=say)[1] == head   # язык возвращён
    assert _source({'source': {'text': '', 'url': 'x y'}}) == ('—', None) and _source({'source': 'кадр'}) == ('кадр', None)
    assert _source({'source': {'text': '', 'url': 'https://a.b/c'}}) == ('a.b/c', 'https://a.b/c')
    assert load_visuals(tmp / 'нет' / 'index.json', log=quiet) is None
    (tmp / 'bad.json').write_text('{"schema": "x"}', encoding='utf-8')
    assert load_visuals(tmp / 'bad.json', log=quiet) is None and load_visuals(index_path(tmp / 'feedback.json'), log=quiet) == visuals

    # compute_say: окно = 📍 ГДЕ, якорь = таймкод пункта; без речи — ключа нет; сбой said — не валит вкладку
    seen = []
    say2 = compute_say(fb, said_fn=lambda rng, tc: (seen.append((rng, tc)) or {'text': f'речь {tc}', 'bold': [(0, 4)]}))
    assert ('0:42–0:47', '0:42') in seen and ('5:10–5:24', '5:10') in seen and ('8:20', '8:20') in seen and len(say2) == 9, seen
    assert say2['1:1'] == {'text': 'речь 0:42', 'bold': [[0, 4]]} and '1:3' not in say2 and '2:40' not in say2
    assert compute_say(fb, said_fn=lambda *a: 1 / 0) == {}
    assert compute_say(fb, said_fn=lambda *a: {'text': '  ', 'bold': []}) == {}

    # ── дамп: детерминирован, без сети; картинки — поддельными адресами ──
    a, b = tmp / 'a.json', tmp / 'b.json'
    dump(synthetic(), a, have_frames=have, visuals=visuals, say=say, log=quiet)
    dump(synthetic(), b, have_frames=frames_on_disk(synthetic(), tmp, visuals), visuals=json.loads(json.dumps(visuals)),
         say=synthetic_say(synthetic()), log=quiet)
    assert a.read_bytes() == b.read_bytes(), 'дамп не детерминирован'
    dj = json.loads(a.read_text(encoding='utf-8'))
    ims = [q['insertInlineImage'] for bt in dj['batches'] for q in bt if 'insertInlineImage' in q]
    assert len(ims) == len(have) == 19 and all(i['uri'].startswith('fake://fb_p') for i in ims), len(ims)
    assert all(i['objectSize']['width']['magnitude'] == IMG_W for i in ims)
    assert sorted(i['uri'] for i in ims)[:2] == ['fake://fb_p1_001_err.jpg', 'fake://fb_p1_001_fix.jpg']
    assert dj['tab_title'] == 'Обратная связь · v5' and dj['fb_sha'] == fb_sha(synthetic()) and dj['images'] == 'fake'
    assert dj['visuals'] == visuals and dj['say'] == say and dj['widths'] == WIDTHS
    assert 'http' not in json.dumps(dj['batches']) or all('burodd.ru' in ln for ln in re.findall(r'"https?://[^"]*"', json.dumps(dj['batches']))), \
        'в офлайн-дампе не должно быть сетевых адресов, кроме ссылок-источников'
    tabs = dj['final_doc']['tabs']
    assert len(tabs) == 1 and sum('table' in c for c in tabs[0]['documentTab']['body']['content']) == 1
    dump(synthetic(), b, log=quiet)                         # без картинок
    assert json.loads(b.read_text(encoding='utf-8'))['images'] == 'none' and 'кадры — в HTML-файле' in b.read_text(encoding='utf-8')

    # ── CLI: офлайн-дамп из файла модели без карточки фильма (индекс рядом с моделью); verify на нём = ALL PASS ──
    mf = tmp / 'feedback.json'
    mf.write_text(json.dumps(synthetic(), ensure_ascii=False), encoding='utf-8')
    env = {k: v for k, v in os.environ.items() if not k.startswith('YTAI_') and k != 'TZ_TAB'}
    r = subprocess.run([sys.executable, __file__, '--fb', str(mf), '--images', 'temp', '--dump-requests', str(tmp / 'c.json')],
                       capture_output=True, text=True, cwd=str(tmp), env=env)
    assert r.returncode == 0 and "'картинок': 19" in r.stdout, r.stdout + r.stderr
    cj = json.loads((tmp / 'c.json').read_text(encoding='utf-8'))
    assert cj['say'] is None and cj['visuals'] == visuals and cj['frames'] == sorted(have), 'CLI без карточки: речи нет, индекс есть'
    for f_ in (tmp / 'c.json', a):
        r = subprocess.run([sys.executable, str(HERE / 'doc_tab_feedback_v1_verify.py'), '--fb', str(mf), '--from-dump', str(f_)],
                           capture_output=True, text=True, cwd=str(tmp), env=env)
        assert r.returncode == 0 and r.stdout.strip().endswith('ALL PASS'), r.stdout[-1500:] + r.stderr[-500:]
    r = subprocess.run([sys.executable, __file__, '--fb', str(tmp / 'nowhere' / 'feedback.json'), '--dump-requests', str(tmp / 'd.json')],
                       capture_output=True, text=True, cwd=str(tmp), env=env)
    assert r.returncode != 0 and 'нет модели' in r.stderr

    # ── замороженная вкладка — отказ при любом force; непустая — только с force ──
    from fake_docs import FakeDocs
    fd = FakeDocs()
    try:
        write(DUMP_DOC, 'Обратная связь · v5', rows, head, frozen={(DUMP_DOC, 'Обратная связь · v5')}, force=True,
              get_doc=fd.get_doc, batch=fd.batch_update, log=quiet)
        raise AssertionError('замороженная вкладка перезаписана')
    except SystemExit as e:
        assert 'заморожена' in str(e)
    assert not fd.batches, 'до отказа в док не должно уйти ни одного запроса'
    write(DUMP_DOC, 'Обратная связь · v5', rows, head, frozen={('чужой-док', 'Обратная связь · v5')},
          get_doc=fd.get_doc, batch=fd.batch_update, log=quiet)
    try:
        write(DUMP_DOC, 'Обратная связь · v5', rows, head, get_doc=fd.get_doc, batch=fd.batch_update, log=quiet)
        raise AssertionError('непустая вкладка перезаписана без force')
    except SystemExit as e:
        assert 'не пустая' in str(e)
    assert [t['title'] for t in fd.tabs] == ['Обратная связь · v5']
    assert _pairs('[["d", "t"]]') == {('d', 't')} and _pairs(None) == set() and _pairs([['d', 't'], 'мусор']) == {('d', 't')}

    # ── режим картинок: временный доступ сам собой не включается ──
    assert pick_mode('temp_grant', '', None, 'mac', False, log=quiet) == 'none'               # нет --images temp
    assert pick_mode('temp_grant', 'remote:x', 'temp', 'mac', False, log=quiet) == 'temp_grant'
    assert pick_mode('temp_grant', '', 'temp', 'memex', False, log=quiet) == 'none'
    assert pick_mode('temp_grant', '', 'temp', 'unknown', False, log=quiet) == 'none'
    assert pick_mode('temp_grant', '', 'temp', 'mac', True, log=quiet) == 'none'
    assert pick_mode('', 'remote:x', 'temp', 'mac', False, log=quiet) == 'none'               # в карточке режима нет
    assert pick_mode('public_folder', 'remote:x', None, 'mac', False, log=quiet) == 'none'    # открытая папка — не для этой вкладки
    assert pick_mode('temp_grant', '', 'none', 'mac', False, log=quiet) == 'none'
    assert detect_host(env={'YTAI_HOST': 'memex'}) == 'memex' and detect_host(env={}, hostname='Memex-M4.local') == 'memex'
    assert detect_host(Path.home() / 'YTAI_work' / 'YTXX01' / '00_Setup' / '05_Review', env={}, hostname='macbook') == 'memex'
    assert detect_host(env={'YTAI_HOST': 'сервер'}) == 'unknown'
    assert detect_host(tmp, env={}, hostname='macbook') == ('mac' if sys.platform == 'darwin' else 'unknown')
    (tmp / 'AUTONOMOUS').write_text('x')
    assert detect_autonomous(tmp, env={}) and detect_autonomous(None, env={'YTAI_AUTONOMOUS': '1'})
    assert not detect_autonomous(tmp / 'нет', env={}) and not detect_autonomous(None, env={})
    for bad in ({'YTAI_DOC_ID': 'd'}, {'YTAI_PRIVATE_FRAMES_FOLDER_ID': 'f'}):
        try:
            guard_test_pair(bad)
            raise AssertionError('подмена одного из пары док/папка пропущена')
        except SystemExit as e:
            assert 'ВМЕСТЕ' in str(e)
    guard_test_pair({}), guard_test_pair({'YTAI_DOC_ID': 'd', 'YTAI_PRIVATE_FRAMES_FOLDER_ID': 'f'})
    r = subprocess.run([sys.executable, __file__, '--fb', str(mf), '--images', 'temp', '--dump-requests', str(tmp / 'd.json')],
                       capture_output=True, text=True, cwd=str(tmp), env=dict(env, YTAI_DOC_ID='тестовый-док'))
    assert r.returncode != 0 and 'ВМЕСТЕ' in r.stderr and not (tmp / 'd.json').exists(), r.stderr

    # ── подготовка картинок дока: два файла на строку, ширина ≤ 1000, повторный прогон те же байты ──
    files = prepare_visuals(fb, visuals, tmp / 'doc_frames', tmp, log=quiet)
    assert len(files) == 19 and {f['kind'] for f in files} == {'err', 'fix'} and files[0]['name'] == 'fb_p1_001_err.jpg', files[:2]
    assert all(Path(f['path']).is_file() and Path(f['path']).stat().st_size > 0 for f in files)
    m1 = {f['name']: Path(f['path']).stat().st_mtime_ns for f in files}
    prepare_visuals(fb, visuals, tmp / 'doc_frames', tmp, log=quiet)
    assert m1 == {f['name']: Path(f['path']).stat().st_mtime_ns for f in files}, 'те же байты — файл не перезаписывается'
    assert prepare_visuals(fb, None, tmp / 'doc_frames2', tmp, log=quiet) == []

    # ── модуль импортируется откуда угодно без карточки фильма ──
    r = subprocess.run([sys.executable, '-c',
                        'import sys; sys.path.insert(0, %r); import doc_tab_feedback_v1 as m; '
                        'assert "proj_config" not in sys.modules and "_bootstrap" not in sys.modules; '
                        'assert "doc_images" not in sys.modules and "said" not in sys.modules; print("ok")' % str(HERE)],
                       capture_output=True, text=True, cwd='/tmp', env=env)
    assert r.returncode == 0 and r.stdout.strip() == 'ok', r.stderr

    _selftest_live(tmp, env)
    print('SELFTEST OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
