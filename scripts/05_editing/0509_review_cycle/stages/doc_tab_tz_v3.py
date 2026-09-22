#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка «ТЗ монтажёру · v3» в сценарном доке (запрос Романа 07.09: «где google doc»; формат v7 — 10.09).

ОДНА таблица (канон): главы = зрительские экраны-заставки (строки с заливкой + HEADING_3 + [скобки]),
ТЗ из pravki_v2.json (тот же источник, что лист «ТЗ монтажёру» и маркеры секвенции — номера синхронны).

v7 (Роман 10.09, эталон — карта структуры info_structure_map.png):
- «ТЗ монтажёру» — списками: метки блоков и заголовки списков жирным, таймкоды пунктов моноширинным
  серым (▸ встаёт столбцом); в опечатках «было → стало» изменённые знаки красным (стало — жирным
  на розовом, было — зачёркнуто);
- «Материал» — КРУПНОЕ превью (s12: оверлей на реальном кадре + кроп на то, о чём речь) в СВОЁМ
  абзаце на всю ширину колонки; под ним короткая подпись «таймкод · что видно»; ссылки и источник —
  мелким серым;
- комменты Романа 💬 — фиолетовым, один раз (s10 уже кладёт их в текст ТЗ).
v3-колонки (Роман 16.09.2026: «транскрипт обязателен во вкладке ТЗ — без него не виден контекст»; канон 5.6 — 6 колонок):
№ | ⏱ TC | категория | ТЗ монтажёру | Говорит | Материал / ссылки. «Говорит» — дословно из words.json (shared/said.py):
абзацы по паузам, опорная фраза (секунда правки) жирным; у глав и ТЗ «весь фильм» — пусто.
build_rows() — чистая функция без записи в док (её использует s13_doc_edits.py); пишет только main().
"""
import copy
import json
import os
import re
import sys
import time
from bisect import bisect_right
from pathlib import Path

from _bootstrap import P, W6, M, HERE, ROOT, T, LANG, tz_label  # noqa: E402
from doctab_lib import DOCS, get_doc, iter_tabs  # noqa: E402
from doctab_lib import batch_update as _batch_update  # noqa: E402
from typo_diff import diff_spans, typo_line, typo_offsets  # noqa: E402
from said import said  # noqa: E402


# ⚠️ Было DOCS['01'] — документ ПЕРВОГО видео. Сборщик пересоздаёт вкладку целиком,
# так что запуск с чужим id затирал бы вкладку YTUVI01 вместе с ручными правками
# Романа от 11.09 (v3 помечена FROZEN именно поэтому); откат — только через ревизии.
DOC_ID = P.need('doc_id')
# вкладка задаётся снаружи: TZ_TAB='ТЗ монтажёру · v4'. v3 ЗАМОРОЖЕНА — в ней правки Романа
# (он удалял неактуальное руками 11.09), пересобирать её нельзя, иначе правки затрутся.
# имя вкладки: TZ_TAB > карточка (tab_title) > дефолт. На новом проекте имя своё («ТЗ монтажёру · v1»),
# и брать его из карточки надёжнее, чем помнить про env на каждом запуске.
TAB_TITLE = (os.environ.get('TZ_TAB') or P.get('tab_title')
             or str(P.profile('doc.tab_tz_template', T('c2.tz_tab_template'))).format(ver=P.CUT_VERSION))
# FROZEN — пары (doc_id, вкладка), которые правились руками и пересобирать их нельзя: из карточки
# (frozen_tabs) + профиля канала (doc.frozen_tabs) + постоянный страж вкладки YTUVI01 (правки Романа 11.09).
# На чужом доке совпадение имён не блокирует сборку: сверяем именно пару.
FROZEN = ({tuple(x) for x in P.get('frozen_tabs', [])} | {tuple(x) for x in (P.profile('doc.frozen_tabs', []) or [])}
          | {('1bzFOdAQFU_nqDAG2QCcaKBfrdgKFqPRsYK7ygjNU5Sk', 'ТЗ монтажёру · v3')})
# лист-чеклист — из карточки; пусто = листа у проекта ещё нет, строку про него не пишем
# (ссылка на лист ДРУГОГО фильма в ТЗ — худший вариант: монтажёр уйдёт в чужой чек-лист).
SHEET_URL = P.get('sheet_url') or ''
# v5 (22.09.2026, раскладка Романа): 9 колонок. Прежние 676 pt больше не держим — у Романа
# вкладка pageless, страница не ограничивает ширину; «Материал» ≥ 250 pt под превью (verify).
WIDTHS = [30, 56, 20, 132, 90, 176, 262, 262, 134]        # = 1162 pt
C_SAY, C_OK, C_ERR, C_MAT, C_DO, C_ROMAN = 3, 4, 5, 6, 7, 8
C_TZ = C_ERR                              # прежнее имя: на него завязаны verify и doc_pdf_qc
TECH_FONT = 6.5                           # техблок (conf, pymorphy, stable, ocr=…) — просьба Романа
FONT = 9
IMG_W = 250                               # превью на всю ширину колонки «Материал» (262 − поля)
HDR = list(T('c2.tz_hdr'))                # 9 колонок, см. c2.tz_hdr
# метки блоков s10 («❌ СЕЙЧАС ·» …) — core.lbl_* + « ·»
LABELS = tuple(T(f'core.lbl_{k}') + ' ·' for k in ('now', 'do', 'list', 'where', 'source', 'timeline'))
SPRINT_NAME = P.get('sprint_name') or T('c2.sprint_default', ch=P.CHANNEL)   # было зашито «YTUVI S1»
CH_BG = {'Green': {'red': 0.85, 'green': 0.93, 'blue': 0.85},
         'Yellow': {'red': 0.98, 'green': 0.95, 'blue': 0.78}}
CAT = {'graphics': '🎨', 'structure': '🧭', 'cut': '✂️', 'insert': '➕',
       'color': '🎛', 'check': '🔍'}
CAT_BG = {'cut': {'red': 0.99, 'green': 0.87, 'blue': 0.86},
          'insert': {'red': 0.87, 'green': 0.95, 'blue': 0.87},
          'graphics': {'red': 1.0, 'green': 0.97, 'blue': 0.82},
          'structure': {'red': 1.0, 'green': 0.92, 'blue': 0.82},
          'color': {'red': 0.87, 'green': 0.92, 'blue': 0.98},
          'check': {'red': 0.93, 'green': 0.93, 'blue': 0.93}}
PURPLE = {'red': 0.42, 'green': 0.18, 'blue': 0.70}
RED = {'red': 0.80, 'green': 0.05, 'blue': 0.05}
PINK = {'red': 1.0, 'green': 0.85, 'blue': 0.85}
GREY = {'red': 0.45, 'green': 0.45, 'blue': 0.45}
LINK = {'red': 0.06, 'green': 0.33, 'blue': 0.8}
# пункт «таймкод ▸ …»: s10 добивает «0:57» цифровым пробелом U+2007 до ширины «33:42» — он входит в моно-спан
ITEM_TC = re.compile(r'^( +)( ?~?\d{1,2}:\d{2}(?:\.\d+)?(?:–\d{1,2}:\d{2})?)  ▸ ', re.M)
URL_RE = re.compile(r'https?://[^\s)\]»]+')

# Главы вкладки — из карточки проекта (chapters + ch_name; кадр заставки главы — ch_img, по желанию).
# Здесь были зашиты 9 глав первого фильма с именами их кадров: вкладка нового фильма получила бы
# чужие строки-главы и картинки. Глава без заставки в кате (new_ch) — жёлтая, как «➕» у YTUVI01.
_IMG, _NEW = P.get('ch_img', {}), set(int(x) for x in P.get('new_ch', []))
CHAPTERS = [{'no': int(n), 'sec': int(t),
             'name': ('➕ ' if int(n) in _NEW else '') + P.get('ch_name', {}).get(n, f"{T('core.chapter')} {n}"),
             'img': _IMG.get(n, ''), 'color': 'Yellow' if int(n) in _NEW else 'Green'}
            for t, n in P.CHAPTERS]
MATERIALS_FOLDER = P.folder_url('materials_id')           # дубль 1 из 4 — из карточки
PROJECT_FOLDER = P.folder_url('project_folder_id')
SPRINT_FOLDER = P.folder_url('sprint_folder_id')


def u16(s):
    return len(s.encode('utf-16-le')) // 2


def tmm(sec):
    t = int(round(sec))
    return f'{t // 60}:{t % 60:02d}'


def tc_sec(tc):
    m = re.match(r'(\d+):(\d{2})', str(tc).strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def clean(t):
    return re.sub(r'\s+', ' ', str(t or '').strip())


def opt(name):
    """необязательная обогащалка (ссылки на клипы, id скриншотов): её делает стадия drive.
    Стадия drive мягкая и законно пропускается, когда у фильма нет публичной папки кадров
    (YTCH12: ребёнок в кадре — shots_remote намеренно пуст). Тогда ссылок просто не будет."""
    p = M / name
    return json.load(open(p)) if p.exists() else {}


def load():
    return (json.load(open(M / 'pravki_v2.json'))['all'], opt('shots_ids.json'),
            opt('proj_material_ids.json'), opt('drive_clips.json'))


# ═══════════════════ чистая сборка строк таблицы ═══════════════════
def clip_link_line(text, drive_clips):
    for name in re.findall(r'RYA-[A-Z0-9]+-\d{3,4}', text or ''):
        e = drive_clips.get(name + '.MP4') or drive_clips.get(name + '.MOV')
        if e:
            return f'{T("c2.link_clip")}https://drive.google.com/file/d/{e[0]["id"]}/view'
    return None


def mat_slot(it):
    """в какую колонку идёт материал: наш драфт исправления — в «Как надо», остальное — в «Материал».

    Роман 22.09.2026: «было стало картинки — в 9 Как надо». Признак берём по имени файла
    (`fix_*` ставит s12 для ВСЕХ драфтов, включая `_ATTACH`-варианты `fix_tz21b`), а не по
    подписи: у шести драфтов фильма подпись пришла из auto_cap и слова «было / стало» в ней нет.
    Явный `slot` в записи перебивает эвристику.
    """
    if it.get('slot') in ('do', 'mat'):
        return it['slot']
    return 'do' if str(it.get('img') or '').startswith('fix_') else 'mat'


def mat_cell(p, shots_ids, proj_ids, drive_clips):
    """→ {slot: (текст, [(индекс пустой строки, имя)], подписи, мелкие строки)} по двум колонкам"""
    acc = {'mat': ([], [], [], []), 'do': ([], [], [], [])}
    for it in p.get('material_rich') or []:
        lines, imgs, caps, small = acc[mat_slot(it)]
        disp = it.get('preview') or it.get('img')
        if disp and disp in shots_ids:
            imgs.append((len(lines), disp))
            lines.append('')                                   # свой абзац под картинку
        cap, t = clean(it.get('cap')), clean(it.get('t'))
        if cap:
            lines.append(cap)
            caps.append(cap)
            if t and not it.get('cap_replaces_t') and t not in cap:
                lines.append('• ' + t)
        elif t:
            lines.append('• ' + t)
        for s in ([clip_link_line(it.get('t'), drive_clips)] +
                  [f'{T("c2.link_file")}https://drive.google.com/file/d/{fid}/view'
                   for fid in [(proj_ids.get(it['img']) or shots_ids.get(it['img'])) if it.get('img') else None] if fid] +
                  ([T('c2.src_prefix') + clean(it['src'])] if it.get('src') else [])):
            if s:
                lines.append(s)
                small.append(s)
    return {k: ('\n'.join(v[0]), v[1], v[2], v[3]) for k, v in acc.items()}


def typo_words(p):
    """фрагменты для подсветки в «Говорит»: текст ошибки, если он ЗВУЧИТ, а не только на экране.
    Чаще не звучит — тогда подсветку даёт опорная фраза по времени (say_bold)."""
    return [t.get('was') for t in (p.get('typo') or []) if t.get('was')]


def tz_row(p, shots_ids, proj_ids, drive_clips):
    """Строка ТЗ по девяти колонкам (раскладка Романа 22.09.2026).

    «Описание ошибки» = 【заголовок】 + ❌ СЕЙЧАС, техблок (📚/🎬) — в её конце мелким серым.
    «Как надо» = ✅ СДЕЛАТЬ и 📋 СПИСОК, там же пары «было → стало» красным.
    «Комментарии Романа» = его 💬 и ❓ РЕШЕНИЕ РОМАНА; раньше и то и другое жило в общей ячейке.
    📍 ГДЕ не печатается вовсе: контекст даёт «Говорит», где слова ошибки подсвечены.
    """
    title = clean(p['title'])
    err = f"【{title}】\n{p.get('nado_err') or p['nado']}"
    tech = clean(p.get('nado_tech'))
    if tech:
        err += '\n' + tech
    do = p.get('nado_do') or ''
    # склейка «текст ✅ + материалы» идёт через \n, значит строка материала i лежит на len(do_lines) + i
    _do_off = len(do.split('\n')) if do else 0
    dec = T('c2.decision_prefix')                          # '❓ РЕШЕНИЕ РОМАНА: '
    roman, purple = [], []
    if p.get('decision'):
        roman.append(dec + p['decision'])
    for c in p.get('roman_comment') or []:
        line = '💬 ' + c
        roman.append(line)
        purple.append(line)
    roman = '\n'.join(roman)
    bold = ([f'【{title}】'] + [l for l in LABELS if l in err or l in do]
            + ([dec.rstrip()] if p.get('decision') else []))
    cells_mat = mat_cell(p, shots_ids, proj_ids, drive_clips)
    mat, imgs, caps, small = cells_mat['mat']
    do_txt, do_imgs, do_caps, do_small = cells_mat['do']
    if do_txt:
        do = (do + '\n' + do_txt) if do else do_txt
    imgs = [(C_MAT, li, n) for li, n in imgs] + [(C_DO, li + _do_off, n) for li, n in do_imgs]
    caps += do_caps
    small += do_small
    tech_lines = [l for l in tech.split('\n') if l.strip()]  # техблок — 6,5 pt серым в конце «Описания ошибки»
    hl = typo_words(p)
    say = (said(p.get('tc_range', ''), p['v1_tc'], hl=hl) if p.get('_sec') is not None
           else {'text': '', 'bold': [], 'hl': []})
    return {'kind': 'tz', 'num': p['num'], 'cat': p['category'],
            'cells': [p['num'], f"⏱ {p.get('tc_range', p['v1_tc'])}", CAT.get(p['category'], '·'),
                      say['text'], f"{T('c2.ok_keep')}\n{T('c2.ok_drop')}", err, mat, do, roman],
            'bold': bold, 'purple': purple, 'imgs': imgs, 'caps': caps, 'small': small,
            'tech': tech_lines, 'typo': p.get('typo') or [], 'say_bold': say['bold'],
            'say_hl': say.get('hl') or [], 'checkbox': True}


def clean_title(t):
    """заголовок для шапки: без переносов и OCR-скобок «ПУТАЛ[И]» → «ПУТАЛИ»"""
    return clean(re.sub(r'\[([^\]]*)\]', r'\1', str(t or '')).replace('\n', ' / '))


def build_head(act, rejected):
    """шапка вкладки — СПИСКАМИ (финальный QA 10.09: сплошные абзацы в шапке тоже не читаются)"""
    decisions = [p for p in act if p.get('decision')]
    li = lambda t: (0, '▸ ' + t, {})                                            # noqa: E731
    head = [
        (1, T('c2.tz_head_title', code=P.CODE, tab=TAB_TITLE), {}),
        (0, T('c2.how_to_read'), {'bold': True}),
        li(T('c2.tz_head_read1')),
        li(T('c2.tz_head_read2')),
        li(T('c2.tz_head_read3')),
        li(T('c2.tz_head_read4')),
        (0, T('c2.tz_head_seq', code=P.CODE), {'bold': True}),
        li(T('c2.tz_head_v1')),
        li(T('c2.tz_head_v2')),
        li(T('c2.tz_head_v3')),
        li(T('c2.tz_head_v4')),
        li(T('c2.tz_head_v5')),
        li(T('c2.tz_head_v6', chs="/".join(sorted(P.get("prog", {}))))),
        li(T('c2.tz_head_markers', n=len(CHAPTERS))),
        (0, T('c2.tz_head_links'), {'bold': True}),
        *([li(T('c2.tz_head_sheet', url=SHEET_URL, sheet_tab=T('c2.sheet_tab')))] if SHEET_URL else []),
        li(T('c2.tz_head_nav', nav=P.get("nav_tab", T('c2.tz_head_nav_default').replace('{ver}', P.CUT_VERSION)))),
        li(T('c2.tz_head_materials', url=MATERIALS_FOLDER)),
        li(T('c2.tz_head_project', url=PROJECT_FOLDER)),
        li(T('c2.tz_head_sprint', sprint=SPRINT_NAME, url=SPRINT_FOLDER)),
        (2, T('c2.tz_head_decisions', n=len(decisions)), {}),
    ]
    for p in decisions:
        head.append((0, f"• {p['num']} · {p['v1_tc']} · {clean_title(p['title'])} — {p['decision']}", {}))
    if rejected:
        head.append((0, T('c2.tz_head_rejected'), {'bold': True}))
        for p in rejected:
            head.append(li(f"{p['num']} · {clean_title(p['title'])}"))
    return head


def build_rows(pravki_all, shots_ids, proj_ids, drive_clips):
    """ЧИСТО: → (rows, head). rows[i] = dict(kind, cells[6], bold, purple, imgs, caps, small, typo, say_bold, …)"""
    pr = copy.deepcopy(pravki_all)
    for i, p in enumerate(pr):
        p['num'] = tz_label(i + 1)                             # 'ТЗ-07' (ru) / 'FIX-07' (en) — то, что видит монтажёр
        p['_sec'] = tc_sec(p['v1_tc'].split('–')[0].split('/')[0])
    rejected = [p for p in pr if p.get('status') == 'rejected']      # Роман снял — номера сохранены, строк нет
    act = [p for p in pr if p.get('status') != 'rejected']
    ch_starts = [c['sec'] for c in CHAPTERS]
    by_ch = {i: [] for i in range(len(CHAPTERS))}
    for p in act:
        if p['_sec'] is not None:
            by_ch[max(0, bisect_right(ch_starts, p['_sec'] + 0.01) - 1)].append(p)
    for lst in by_ch.values():                                 # QA 10.09: внутри главы — по времени, не по номеру ТЗ
        lst.sort(key=lambda p: p['_sec'])
    rows = []
    for p in act:
        if p['_sec'] is None:                                  # ТЗ-30 «весь фильм» — первой строкой
            r = tz_row(p, shots_ids, proj_ids, drive_clips)
            r['cells'][1] = T('c2.whole_film')
            rows.append(r)
    for ci, ch in enumerate(CHAPTERS):
        ch_end = CHAPTERS[ci + 1]['sec'] if ci + 1 < len(CHAPTERS) else int(P.duration_sec()) + 1
        label = f"[{ch.get('no', ci + 1)}. {ch['name']} · {tmm(ch['sec'])}–{tmm(ch_end)}]"
        ch_cells = [''] * len(HDR)
        ch_cells[C_ERR] = label            # метка главы живёт в той же колонке, что и текст ТЗ
        rows.append({'kind': 'ch', 'label': label, 'color': ch['color'], 'cat': None,
                     'cells': ch_cells, 'bold': [], 'purple': [], 'caps': [], 'small': [],
                     'typo': [], 'say_bold': [], 'imgs': [(C_MAT, -1, ch['img'])] if ch.get('img') else []})
        for p in by_ch.get(ci) or []:
            rows.append(tz_row(p, shots_ids, proj_ids, drive_clips))
    return rows, build_head(act, rejected)


# ═══════════════════ запись во вкладку ═══════════════════
def batch_update(doc_id, reqs, tries=5):
    """backoff на 429/5xx и сетевые сбои (doctab_lib не ретраит)"""
    for k in range(tries):
        try:
            return _batch_update(doc_id, reqs)
        except RuntimeError as e:
            m = re.search(r'Docs API (\d+)', str(e))
            if m and m.group(1) in ('429', '500', '502', '503', '504') and k < tries - 1:
                time.sleep(6 * 2 ** k)
                continue
            raise
        except OSError:
            if k < tries - 1:
                time.sleep(6 * 2 ** k)
                continue
            raise


def cell_text(cell):
    return ''.join(e['textRun'].get('content', '') for c in cell.get('content', [])
                   for e in c.get('paragraph', {}).get('elements', []) if 'textRun' in e)


def index_of(cell, pos):
    """смещение в тексте ячейки (только textRun, картинки не считаются) → индекс документа"""
    last = None
    for c in cell.get('content', []):
        for e in c.get('paragraph', {}).get('elements', []):
            tr = e.get('textRun')
            if not tr:
                continue
            t = tr.get('content', '')
            if pos < len(t):
                return e['startIndex'] + u16(t[:pos])
            pos -= len(t)
            last = e['endIndex']
    return last if pos == 0 else None


def main(force=False):
    if (DOC_ID, TAB_TITLE) in FROZEN and not force:
        raise SystemExit(f'«{TAB_TITLE}» в этом доке заморожена: там правки Романа. '
                         f'Запускай с TZ_TAB=«ТЗ монтажёру · v4» или поправь tab_title в карточке.')
    import socket
    socket.setdefaulttimeout(300)                              # зависшее соединение не должно висеть вечно
    pravki, shots_ids, proj_ids, drive_clips = load()
    rows, headp = build_rows(pravki, shots_ids, proj_ids, drive_clips)
    n_imgs = sum(len(r['imgs']) for r in rows)
    print(f"строк: {len(rows)} (глав {sum(r['kind'] == 'ch' for r in rows)}, ТЗ {sum(r['kind'] == 'tz' for r in rows)}), "
          f'картинок {n_imgs}', flush=True)

    doc = get_doc(DOC_ID)
    tab_id = next((t['tabProperties']['tabId'] for t in iter_tabs(doc)
                   if t['tabProperties'].get('title') == TAB_TITLE), None)
    if tab_id is None:
        resp = batch_update(DOC_ID, [{'addDocumentTab': {'tabProperties': {'title': TAB_TITLE}}}])
        tab_id = resp['replies'][0]['addDocumentTab']['tabProperties']['tabId']
        print('создана вкладка', tab_id)
    else:
        print('вкладка найдена', tab_id)

    def tab_body():
        """весь док (~30 с: get_doc тянет все вкладки) → тело нашей вкладки; с повтором на сетевые сбои"""
        for k in range(4):
            try:
                d = get_doc(DOC_ID)
                break
            except Exception as e:                               # noqa: BLE001
                if k == 3:
                    raise
                print('  get_doc повтор:', str(e)[:100], flush=True)
                time.sleep(10 * (k + 1))
        for t in iter_tabs(d):
            if t['tabProperties']['tabId'] == tab_id:
                return t['documentTab']['body']['content']
        raise SystemExit('tab lost')

    body = tab_body()
    first = next(c for c in body if 'paragraph' in c)
    start, end = first['startIndex'], body[-1]['endIndex'] - 1
    if end > start:
        batch_update(DOC_ID, [{'deleteContentRange': {
            'range': {'tabId': tab_id, 'startIndex': start, 'endIndex': end}}}])
    print('вкладка очищена', flush=True)

    # ── шапка — ОДНОЙ пачкой: индексы считаем сами (раньше get_doc на каждый абзац = ~30 с × 13) ──
    HEAD = {1: 'HEADING_1', 2: 'HEADING_2'}
    cur = tab_body()[-1]['endIndex'] - 1
    reqs = []
    for h, text, opts in headp:
        tnl = text + '\n'
        n = u16(tnl)
        reqs += [{'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': tnl}},
                 {'updateParagraphStyle': {
                     'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + n},
                     'paragraphStyle': {'namedStyleType': HEAD.get(h, 'NORMAL_TEXT')},
                     'fields': 'namedStyleType'}}]
        if opts.get('bold'):
            reqs.append({'updateTextStyle': {
                'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + n - 1},
                'textStyle': {'bold': True}, 'fields': 'bold'}})
        cur += n
    batch_update(DOC_ID, reqs)
    print(f'шапка: {len(headp)} абзацев', flush=True)

    # ── таблица + текст (с конца, чтобы индексы не ехали) ──
    cur = tab_body()[-1]['endIndex'] - 1
    batch_update(DOC_ID, [{'insertTable': {'location': {'tabId': tab_id, 'index': cur},
                                           'rows': len(rows) + 1, 'columns': len(HDR)}}])
    tbl = [el for el in tab_body() if 'table' in el][-1]
    cells = [row['tableCells'] for row in tbl['table']['tableRows']]
    # Роман просил номер у каждого столбика — печатаем «N ИМЯ» в шапке (у пустой колонки категории
    # остаётся только номер). Verify сверяет шапку по тем же правилам, см. HDR_NUM в нём.
    hdr_cells = [f'{cj + 1} {h}'.strip() for cj, h in enumerate(HDR)]
    all_cells = [hdr_cells] + [r['cells'] for r in rows]
    reqs = []
    for ri in range(len(all_cells) - 1, -1, -1):
        for cj in range(len(HDR) - 1, -1, -1):
            txt = str(all_cells[ri][cj])
            if txt:
                reqs.append({'insertText': {'location': {'tabId': tab_id, 'index': cells[ri][cj]['content'][0]['startIndex']},
                                            'text': txt}})
    for i in range(0, len(reqs), 400):
        batch_update(DOC_ID, reqs[i:i + 400])
        print(f'text batch {i // 400 + 1}', flush=True)

    # ── чекбоксы приёмки: живые, кликаемые (Роман ставит галочку прямо в доке) ──
    trows = [el for el in tab_body() if 'table' in el][-1]['table']['tableRows']
    cb = []
    for ri, r in enumerate(rows, start=1):
        if not r.get('checkbox'):
            continue
        cell = trows[ri]['tableCells'][C_OK]
        a = cell['content'][0]['startIndex']
        b = cell['content'][-1]['endIndex'] - 1
        # ДВЕ строки-галочки: «оставить» и «убрать». Состояние галочки Docs API не отдаёт,
        # поэтому решающее действие Романа — удалить лишнюю строку; её и читает s13.
        cb.append({'createParagraphBullets': {
            'range': {'tabId': tab_id, 'startIndex': a, 'endIndex': max(a, b)},
            'bulletPreset': 'BULLET_CHECKBOX'}})
    for i in range(0, len(cb), 400):
        batch_update(DOC_ID, cb[i:i + 400])
    print(f'приёмка: {len(cb)} строк по две галочки', flush=True)

    # ── картинки: превью в своём пустом абзаце (материал), у глав — в конец ячейки ──
    trows = [el for el in tab_body() if 'table' in el][-1]['table']['tableRows']
    img_reqs = []
    for ri in range(len(all_cells) - 1, 0, -1):
        r = rows[ri - 1]
        if not r['imgs']:
            continue
        # картинки теперь в ДВУХ колонках: превью ошибки в «Материале», драфт «было / стало» — в «Как надо»
        for cj, li, name in sorted(r['imgs'], key=lambda x: (-x[0], -x[1])):
            cell = trows[ri]['tableCells'][cj]
            base = cell['content'][0]['startIndex']
            lines = str(r['cells'][cj]).split('\n')
            did = shots_ids.get(name)
            if not did:
                continue
            idx = cell['endIndex'] - 1 if li < 0 else base + (u16('\n'.join(lines[:li]) + '\n') if li else 0)
            img_reqs.append({'insertInlineImage': {
                'location': {'tabId': tab_id, 'index': idx},
                'uri': f'https://drive.google.com/uc?export=view&id={did}',
                'objectSize': {'width': {'magnitude': IMG_W, 'unit': 'PT'}}}})
    img_reqs.sort(key=lambda q: -q['insertInlineImage']['location']['index'])
    ok, fails = 0, []
    for i in range(0, len(img_reqs), 20):
        chunk = img_reqs[i:i + 20]
        try:
            batch_update(DOC_ID, chunk)
            ok += len(chunk)
        except Exception as e:                                   # по одной — битая картинка не валит пачку
            print('  img batch err → по одной:', str(e)[:120], flush=True)
            for q in chunk:
                try:
                    batch_update(DOC_ID, [q])
                    ok += 1
                except Exception as e2:
                    fails.append(q['insertInlineImage']['uri'])
                    print('  img err:', str(e2)[:120])
        print(f'  картинки {ok}/{len(img_reqs)}', flush=True)
    print(f'картинок: {ok}, сбоев: {len(fails)}', flush=True)

    # ── стили ──
    tbl = [el for el in tab_body() if 'table' in el][-1]
    tstart = tbl['startIndex']
    trows = tbl['table']['tableRows']
    sreqs = []

    def style(cell, s, e, text_style, fields):
        a, b = index_of(cell, s), index_of(cell, e)
        if a is not None and b is not None and b > a:
            sreqs.append({'updateTextStyle': {'range': {'tabId': tab_id, 'startIndex': a, 'endIndex': b},
                                              'textStyle': text_style, 'fields': fields}})
            return True
        return False

    for row in trows:
        for c in row['tableCells']:
            t = cell_text(c)
            if t.strip():
                style(c, 0, len(t.rstrip('\n')), {'fontSize': {'magnitude': FONT, 'unit': 'PT'}}, 'fontSize')
    for c in trows[0]['tableCells']:
        t = cell_text(c)
        if t.strip():
            style(c, 0, len(t.rstrip('\n')), {'bold': True}, 'bold')

    stat = {'bold': 0, 'head': 0, 'mono': 0, 'typo': 0, 'purple': 0, 'caps': 0}
    for ri, r in enumerate(rows, start=1):
        tc = trows[ri]['tableCells']
        c3, c4, csay = tc[C_ERR], tc[C_MAT], tc[C_SAY]
        cdo, croman = tc[C_DO], tc[C_ROMAN]
        t3, t4 = cell_text(c3), cell_text(c4)
        tdo, troman = cell_text(cdo), cell_text(croman)

        def any_cell(span, kind='bold', st=None, fields='bold'):
            """спан ищем во всех трёх текстовых колонках: заголовок и метки блоков теперь
            разнесены по «Описанию ошибки», «Как надо» и «Комментариям Романа»"""
            for cc, tt in ((c3, t3), (cdo, tdo), (croman, troman)):
                pp = tt.find(span)
                if pp >= 0:
                    return style(cc, pp, pp + len(span), st or {'bold': True}, fields)
            return False
        if r['kind'] == 'ch':
            p = t3.find(r['label'])
            if p >= 0:
                style(c3, p, p + len(r['label']), {'bold': True, 'fontSize': {'magnitude': 10, 'unit': 'PT'}}, 'bold,fontSize')
                a, b = index_of(c3, p), index_of(c3, p + len(r['label']))
                sreqs.append({'updateParagraphStyle': {
                    'range': {'tabId': tab_id, 'startIndex': a, 'endIndex': b + 1},
                    'paragraphStyle': {'namedStyleType': 'HEADING_3'}, 'fields': 'namedStyleType'}})
            sreqs.append({'updateTableCellStyle': {
                'tableRange': {'tableCellLocation': {'tableStartLocation': {'tabId': tab_id, 'index': tstart},
                                                     'rowIndex': ri, 'columnIndex': 0},
                               'rowSpan': 1, 'columnSpan': len(HDR)},
                'tableCellStyle': {'backgroundColor': {'color': {'rgbColor': CH_BG.get(r['color'], CH_BG['Green'])}}},
                'fields': 'backgroundColor'}})
            continue
        for cj in (0, 1):                                      # № + TC жирным целиком
            t = cell_text(tc[cj]).rstrip('\n')
            if t:
                style(tc[cj], 0, len(t), {'bold': True}, 'bold')
        for span in r['bold']:
            if any_cell(span):
                stat['bold'] += 1
        # заголовки списков: строка, за которой идут пункты с отступом 8 пробелов
        for cc, tt in ((c3, t3), (cdo, tdo)):
            lines = tt.split('\n')
            off = 0
            for i, ln in enumerate(lines):
                if ln.strip() and not ln.startswith(' ' * 8) and i + 1 < len(lines) and lines[i + 1].startswith(' ' * 8):
                    s = off + len(ln) - len(ln.lstrip())
                    if style(cc, s, off + len(ln), {'bold': True}, 'bold'):
                        stat['head'] += 1
                off += len(ln) + 1
            for m in ITEM_TC.finditer(tt):                     # таймкоды пунктов — моноширинные серые
                if style(cc, m.start(2), m.end(2), {'weightedFontFamily': {'fontFamily': 'Roboto Mono'},
                                                    'foregroundColor': {'color': {'rgbColor': GREY}}},
                         'weightedFontFamily,foregroundColor'):
                    stat['mono'] += 1
        pos = 0
        for tl in r.get('tech') or []:                         # техблок 📚/🎬 — 6,5 pt серым
            p = t3.find(tl, pos)
            if p >= 0:
                style(c3, p, p + len(tl), {'fontSize': {'magnitude': TECH_FONT, 'unit': 'PT'},
                                           'foregroundColor': {'color': {'rgbColor': GREY}}},
                      'fontSize,foregroundColor')
                pos = p + len(tl)
        for ty in r['typo']:                                   # опечатки: изменённые знаки — красным
            line = typo_line(ty['was'], ty['now'])
            p = tdo.find(line)                                 # пары «было → стало» живут в «Как надо»
            if p < 0:
                print('  !! typo-строка не найдена:', r['num'], line)
                continue
            wo, no = typo_offsets(ty['was'])
            sw, sn = diff_spans(ty['was'], ty['now'])
            for s, e in sn:
                stat['typo'] += style(cdo, p + no + s, p + no + e,
                                      {'bold': True, 'foregroundColor': {'color': {'rgbColor': RED}},
                                       'backgroundColor': {'color': {'rgbColor': PINK}}},
                                      'bold,foregroundColor,backgroundColor')
            for s, e in sw:
                stat['typo'] += style(cdo, p + wo + s, p + wo + e,
                                      {'strikethrough': True, 'foregroundColor': {'color': {'rgbColor': RED}},
                                       'backgroundColor': {'color': {'rgbColor': PINK}}},
                                      'strikethrough,foregroundColor,backgroundColor')
        for s_, e_ in r.get('say_bold') or []:                  # «Говорит»: слова в момент ошибки —
            style(csay, s_, e_, {'bold': True, 'foregroundColor': {'color': {'rgbColor': RED}}},
                  'bold,foregroundColor')                       # жирным рубиновым, вместо блока 📍 ГДЕ
        for s_, e_ in r.get('say_hl') or []:                    # и сам текст ошибки, если он звучит
            style(csay, s_, e_, {'bold': True, 'foregroundColor': {'color': {'rgbColor': RED}}},
                  'bold,foregroundColor')
        for span in r['purple']:                               # 💬 комменты Романа — фиолетовым, жирным
            p = troman.find(span)
            if p >= 0 and style(croman, p, p + len(span),
                                {'bold': True, 'foregroundColor': {'color': {'rgbColor': PURPLE}}},
                                'bold,foregroundColor'):
                stat['purple'] += 1
        for cap in r['caps']:                                  # подпись под превью — жирным
            p = t4.find(cap)
            if p >= 0 and style(c4, p, p + len(cap), {'bold': True}, 'bold'):
                stat['caps'] += 1
        pos = 0
        for sm in r['small']:                                  # ссылки и источник — мелким серым
            p = t4.find(sm, pos)
            if p >= 0:
                style(c4, p, p + len(sm), {'fontSize': {'magnitude': 8, 'unit': 'PT'},
                                           'foregroundColor': {'color': {'rgbColor': GREY}}}, 'fontSize,foregroundColor')
                pos = p + len(sm)
        if r['cat'] in CAT_BG:
            sreqs.append({'updateTableCellStyle': {
                'tableRange': {'tableCellLocation': {'tableStartLocation': {'tabId': tab_id, 'index': tstart},
                                                     'rowIndex': ri, 'columnIndex': 2},
                               'rowSpan': 1, 'columnSpan': 1},
                'tableCellStyle': {'backgroundColor': {'color': {'rgbColor': CAT_BG[r['cat']]}}},
                'fields': 'backgroundColor'}})
    for cj, w in enumerate(WIDTHS):
        sreqs.append({'updateTableColumnProperties': {
            'tableStartLocation': {'tabId': tab_id, 'index': tstart},
            'columnIndices': [cj],
            'tableColumnProperties': {'widthType': 'FIXED_WIDTH', 'width': {'magnitude': w, 'unit': 'PT'}},
            'fields': 'widthType,width'}})
    for i in range(0, len(sreqs), 400):
        batch_update(DOC_ID, sreqs[i:i + 400])
        print(f'style batch {i // 400 + 1}/{(len(sreqs) + 399) // 400}', flush=True)
    print('стили:', stat, flush=True)

    # ── АКТИВНЫЕ ссылки (Роман 07.09): все URL во вкладке → textStyle.link ──
    runs = []

    def walk_runs(content):
        for c in content:
            for e in c.get('paragraph', {}).get('elements', []):
                tr = e.get('textRun')
                if tr and 'http' in tr.get('content', ''):
                    runs.append((e['startIndex'], tr['content']))
            for row in c.get('table', {}).get('tableRows', []):
                for cell in row.get('tableCells', []):
                    walk_runs(cell.get('content', []))
    walk_runs(tab_body())
    lreqs = []
    for start, txt in runs:
        for m in URL_RE.finditer(txt):
            s = start + u16(txt[:m.start()])
            lreqs.append({'updateTextStyle': {
                'range': {'tabId': tab_id, 'startIndex': s, 'endIndex': s + u16(m.group(0))},
                'textStyle': {'link': {'url': m.group(0)}, 'foregroundColor': {'color': {'rgbColor': LINK}},
                              'underline': True},
                'fields': 'link,foregroundColor,underline'}})
    for i in range(0, len(lreqs), 400):
        batch_update(DOC_ID, lreqs[i:i + 400])
    print('активных ссылок:', len(lreqs))
    if fails:
        print('⚠️ не вставились картинки:', fails)
    print(f'https://docs.google.com/document/d/{DOC_ID}/edit?tab={tab_id}')


def dump_main(path):
    """--dump-requests FILE: тот же main() на офлайн-двойнике Docs (shared/fake_docs.py) — все batchUpdate
    ложатся в FILE, Google API не вызывается (golden-регрессия, review.py selftest)."""
    sys.path.insert(0, str(ROOT / 'shared'))
    from fake_docs import FakeDocs  # noqa: E402
    fd = FakeDocs()
    g = globals()
    g['get_doc'], g['_batch_update'] = fd.get_doc, fd.batch_update
    main()
    fd.dump(path, {'tab_title': TAB_TITLE})


def cli():
    if '--dump-requests' in sys.argv:
        dump_main(sys.argv[sys.argv.index('--dump-requests') + 1])
    else:
        main()


if __name__ == '__main__':
    cli()
