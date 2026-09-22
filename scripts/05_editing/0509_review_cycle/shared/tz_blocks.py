#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tz_blocks — блоки ТЗ («❌ СЕЙЧАС · …», «▶ СДЕЛАТЬ · …», «📍 ГДЕ · …») для поверхностей обратной связи.

Зачем: вкладка «Обратная связь» и HTML продюсеру печатают пункты тем же видом, что вкладка «ТЗ монтажёру»:
метка блока, продолжение с отступом 5 пробелов, пункты списка — 8 пробелов, таймкод пункта добит цифровым
пробелом, чтобы «▸» вставал столбцом. Стадию s10 импортировать нельзя (она читает карточку и файлы фильма
при импорте), поэтому логика скопирована сюда.

⚠️ КОПИЯ логики stages/s10_format_tz.py:606-639 (fmt_item, render_block), :90-92 (clean) и шаблонов :42-46
   (TC, TC_RE, ITEM_RE). Держать в синхроне: поменял вид блока там — поменяй здесь, и наоборот; --selftest сам
   сверяет копию с текстом s10 (не импортируя его) и падает, если они разъехались. Отличия копии:
   - нет expand('@renames' / '@reads' / '@prog:…') — списки из каталога здесь не нужны;
   - язык меток передаётся параметром (lang='ru'), а не берётся из карточки фильма;
   - плоская строка считается пунктом списка, только если в ней явно стоит «▸» после таймкода
     («11:16–11:40» — это место, а не пункт; у s10 такой случай не встречается, там пункты лежат в items).

Модуль импортируется без карточки фильма: таблицы строк (shared/i18n_strings) читаются при первом обращении
к меткам, а не при импорте.

    from tz_blocks import render_block, lint_line, LBL, IND, IND2
    render_block('now', ['11:16 ▸ куратор объясняет работу фонда'])
    → ['❌ СЕЙЧАС · 11:16 ▸ куратор объясняет работу фонда']
"""
import re
import sys
from collections.abc import Mapping
from pathlib import Path

HERE = Path(__file__).resolve().parent

ORDER = ['now', 'do', 'list', 'where', 'src', 'tl']
_KEYS = {'now': 'core.lbl_now', 'do': 'core.lbl_do', 'list': 'core.lbl_list', 'where': 'core.lbl_where',
         'src': 'core.lbl_source', 'tl': 'core.lbl_timeline'}
IND = '     '           # продолжение блока (5 пробелов)
IND2 = '        '       # пункт списка под заголовком (8 пробелов)
FIG = '\u2007'          # цифровой пробел: «0:57» выравнивается под «33:42»
# дробные секунды — часть ОДНОГО таймкода: «2:46.0–2:48.6» это один, а не два (s10:42-44)
TC = r'\d{1,2}:\d{2}(?:\.\d+)?(?:\s*[–-]\s*\d{1,2}:\d{2}(?:\.\d+)?)?'
TC_RE = re.compile(rf'(?<![\d:]){TC}(?![\d:])')
# пункт «TC ▸ …» (s10:46): допускаем «@», «~» и дробные секунды
ITEM_RE = re.compile(r'^@?(~?\d{1,2}:\d{2}(?:\.\d+)?(?:\s*[–-]\s*\d{1,2}:\d{2}(?:\.\d+)?)?)(?![\d:])\s*(?:▸|—|·|:|-)?\s*(.+)$')
# плоская строка-пункт: «▸» обязателен
FLAT_ITEM_RE = re.compile(r'^@?(~?\d{1,2}:\d{2}(?:\.\d+)?(?:\s*[–-]\s*\d{1,2}:\d{2}(?:\.\d+)?)?)(?![\d:])\s*▸\s*(.+)$')
MAX_LEN = 220


# ── метки ────────────────────────────────────────────────────────────────────
_LBL_CACHE = {}


def labels(lang='ru'):
    """{'now': '❌ СЕЙЧАС', …} на нужном языке; таблицы i18n грузятся здесь, а не при импорте модуля"""
    lang = 'en' if str(lang or '').strip().lower() == 'en' else 'ru'
    if lang not in _LBL_CACHE:
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        import i18n  # noqa: E402  (лениво: i18n при импорте читает таблицы строк)
        _LBL_CACHE[lang] = {k: i18n.TL(lang, key) for k, key in _KEYS.items()}
    return _LBL_CACHE[lang]


class _Labels(Mapping):
    """LBL['now'] как у s10, но без чтения файлов при импорте: русские метки подгружаются при первом обращении"""

    def __getitem__(self, k):
        return labels('ru')[k]

    def __iter__(self):
        return iter(ORDER)

    def __len__(self):
        return len(ORDER)


LBL = _Labels()


# ── рендер ───────────────────────────────────────────────────────────────────
def clean(t):
    """как s10:90-92: пробелы в один + вырожденный диапазон «2:47–2:47» → «2:47» (после пересчёта на новый кат
    оба конца диапазона нередко попадают в одну секунду)"""
    t = re.sub(r'\s+', ' ', str(t or '').strip())
    return re.sub(r'(?<![\d:])(\d{1,2}:\d{2})\s*[–-]\s*\1(?![\d:.])', r'\1', t)


def _flat_item(t):
    """плоская строка-пункт → готовый пункт, иначе None: «M:SS ▸ текст» (таймкод столбцом) или «▸ текст» / «• текст»"""
    m = FLAT_ITEM_RE.match(t)
    if m:
        return f'{_pad_tc(m.group(1))}  ▸ {m.group(2)}'
    if t.startswith(('▸', '•')):
        return t
    return None


def _pad_tc(tc):
    """«1:16» → « 1:16» цифровым пробелом. ⚠️ \\s в python съедает U+2007, поэтому добивка — строго ПОСЛЕ clean()"""
    tc = re.sub(r'\s*[–-]\s*', '–', tc)
    if re.fullmatch(r'\d{1,2}:\d{2}', tc):                  # только «M:SS» выравниваем под «MM:SS»
        tc = tc.rjust(5, FIG)
    return tc


def fmt_item(x):
    """пункт списка (s10:606-616): «TC  ▸ текст» с выровненным таймкодом, иначе «▸ текст»"""
    s = clean(x)
    m = ITEM_RE.match(s)
    if m:
        return f'{_pad_tc(m.group(1))}  ▸ {m.group(2)}'
    if s.startswith(('▸', '•', 'http')) or re.match(r'^\S{1,3} ▸ ', s):
        return s
    return '▸ ' + s


def render_block(key, lines, lang='ru'):
    """блок ТЗ → строки ячейки.

    lines — плоский список строк (feedback.json parts) и/или словари {'h': заголовок, 'items': [...]} как в s10.
    Первая строка — «<метка> · <строка>», остальные — с отступом IND. Строки вида «M:SS ▸ текст» (и «▸ текст»
    без таймкода) — пункты:
    - единственная строка блока: «<метка> · M:SS ▸ текст» (выравнивать не с чем);
    - блок только из пунктов (≥2): «<метка> ·», ниже пункты с IND, таймкоды столбцом;
    - пункты после обычной строки — список под ней, отступ IND2.
    """
    lab = labels(lang)[key]
    vals = [v for v in (lines or []) if (isinstance(v, dict) or clean(v))]
    flat = [clean(v) for v in vals if not isinstance(v, dict)]
    if len(vals) == 1 and len(flat) == 1:
        m = FLAT_ITEM_RE.match(flat[0])
        if m:
            tc = re.sub(r'\s*[–-]\s*', '–', m.group(1))
            return [f'{lab} · {tc} ▸ {m.group(2)}']
        return [f'{lab} · {flat[0]}']

    out, first, under_text = [], True, False
    for v in vals:
        if isinstance(v, dict):                             # как s10: заголовок + пункты
            h = clean(v.get('h'))
            items = [fmt_item(x) for x in (v.get('items') or []) if clean(x)]
            if h:
                out.append((f'{lab} · ' if first else IND) + h)
                out += [IND2 + x for x in items]
            else:
                if first:
                    out.append(f'{lab} ·')
                out += [IND + x for x in items]
            first, under_text = False, False
            continue
        t = clean(v)
        item = _flat_item(t)
        if item:
            if first:
                out.append(f'{lab} ·')
                first = False
            out.append((IND2 if under_text else IND) + item)
        else:
            out.append((f'{lab} · ' if first else IND) + t)
            first, under_text = False, True
    return out


# ── проверка строки ──────────────────────────────────────────────────────────
def lint_line(s):
    """замечания к одной видимой строке; пустой список = строка годится.

    - два и больше таймкодов в строке (диапазон «a–b» — ОДИН таймкод): монтажёр не поймёт, к какому месту правка;
    - длиннее 220 знаков (без отступа);
    - обрыв на многоточии («…» или «...» в конце).
    """
    out = []
    t = str(s or '').replace(FIG, ' ').strip()
    n = len(TC_RE.findall(t))
    if n >= 2:
        out.append(f'таймкодов в строке: {n} — оставить один')
    if len(t) > MAX_LEN:
        out.append(f'строка длиннее {MAX_LEN} знаков ({len(t)})')
    if re.search(r'(…|\.\.\.)\s*[»")\]]*$', t):
        out.append('строка обрывается на многоточии')
    return out


# ── самопроверка ─────────────────────────────────────────────────────────────
def _sync_with_s10():
    """копия не разъехалась с оригиналом: функции и шаблоны вынимаются из ТЕКСТА s10 (импортировать его нельзя —
    он читает карточку фильма) и на одних входах обязаны дать то же, что эта копия"""
    import ast
    src = (HERE.parent / 'stages' / 's10_format_tz.py').read_text(encoding='utf-8')
    tree = ast.parse(src)
    need_f, need_v = {'clean', 'fmt_item', 'render_block'}, {'IND', 'IND2', 'FIG', 'TC', 'TC_RE', 'ITEM_RE', 'ORDER'}
    ns = {'re': re, 'LBL': dict(labels('ru')), 'expand': lambda items: items or []}
    got = set()
    for node in tree.body:
        name = node.name if isinstance(node, ast.FunctionDef) else (
            node.targets[0].id if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) else None)
        if name in need_f | need_v:
            exec(compile(ast.Module([node], []), 's10_format_tz.py', 'exec'), ns)      # noqa: S102
            got.add(name)
    assert got == need_f | need_v, f's10_format_tz.py перестроен, не нашёл: {sorted((need_f | need_v) - got)} — сверь копию руками'
    for k in ('IND', 'IND2', 'FIG', 'TC', 'ORDER'):
        assert ns[k] == globals()[k], f'{k} разошёлся с s10'
    assert ns['TC_RE'].pattern == TC_RE.pattern and ns['ITEM_RE'].pattern == ITEM_RE.pattern, 'шаблоны разошлись с s10'
    for t in ['  много   пробелов ', '2:47–2:47 дубль', '2:47 - 2:48', FIG + '0:57  ▸ раз', None, '']:
        assert ns['clean'](t) == clean(t), ('clean', t)
    for x in ['1:05 имя', '@~2:47.4 ▸ хвост', '12:30–12:41 — диапазон', 'без времени', '▸ уже пункт', 'http://x', 'A ▸ b',
              '3:07–3:07: дубль']:
        assert ns['fmt_item'](x) == fmt_item(x), ('fmt_item', x)
    cases = [[{'h': 'Карточки', 'items': ['1:05 имя', 'без времени']}, {'items': ['@~2:47.4 ▸ хвост', '33:42 два']}],
             ['первое', 'второе', '', 'третье 2:47–2:47'], [{'h': '', 'items': ['0:57 раз']}, 'текст после'],
             ['одна строка'], [], None]
    for k in ORDER:
        for vals in cases:
            assert ns['render_block'](k, vals) == render_block(k, vals), ('render_block', k, vals)


def selftest():
    import os
    do_ru, labels_en_do = labels('ru')['do'], labels('en')['do']
    assert IND == ' ' * 5 and IND2 == ' ' * 8 and FIG == '\u2007'
    assert LBL['now'] == '❌ СЕЙЧАС' and LBL['where'] == '📍 ГДЕ' and list(LBL) == ORDER
    assert labels('en')['do'] == labels_en_do and LBL['do'] == do_ru   # знак блока «Как надо» берём из таблицы

    # одна строка — всё на строке метки
    assert render_block('now', ['11:16 ▸ куратор объясняет работу фонда']) == \
        ['❌ СЕЙЧАС · 11:16 ▸ куратор объясняет работу фонда']
    assert render_block('where', ['11:16–11:40']) == ['📍 ГДЕ · 11:16–11:40']     # место — не пункт списка
    assert render_block('do', ['  перенести   вход фонда ']) == [do_ru + ' · перенести вход фонда']
    assert render_block('do', []) == [] and render_block('do', None) == [] and render_block('do', ['', ' ']) == []

    # текст + продолжение
    assert render_block('do', ['первое', 'второе']) == [do_ru + ' · первое', IND + 'второе']

    # только пункты: метка отдельной строкой, таймкоды столбцом (цифровой пробел)
    got = render_block('list', ['0:57 ▸ раз', '33:42 ▸ два', '2:46.0–2:48.6 ▸ три'])
    assert got == ['📋 СПИСОК ·', IND + FIG + '0:57  ▸ раз', IND + '33:42  ▸ два', IND + '2:46.0–2:48.6  ▸ три'], got
    assert got[1].index('▸') == got[2].index('▸')

    # пункты под обычной строкой — отступ 8
    got = render_block('do', ['вернуть реплики', '1:05 ▸ первая', '12:30 ▸ вторая', 'и проверить звук'])
    assert got == [do_ru + ' · вернуть реплики', IND2 + FIG + '1:05  ▸ первая', IND2 + '12:30  ▸ вторая',
                   IND + 'и проверить звук'], got

    # повторный прогон по уже выровненной строке ничего не ломает (\s съедает U+2007 — добивка после чистки)
    again = render_block('list', [x.strip() for x in render_block('list', ['0:57 ▸ раз', '33:42 ▸ два'])[1:]])
    assert again == ['📋 СПИСОК ·', IND + FIG + '0:57  ▸ раз', IND + '33:42  ▸ два'], again

    # словари — как в s10
    got = render_block('list', [{'h': 'Карточки', 'items': ['1:05 имя', 'без времени']}, {'items': ['@~2:47.4 ▸ хвост']}])
    assert got == ['📋 СПИСОК · Карточки', IND2 + FIG + '1:05  ▸ имя', IND2 + '▸ без времени',
                   IND + '~2:47.4  ▸ хвост'], got
    assert render_block('now', ['x'], lang='en') == ['❌ NOW · x']

    # вырожденный диапазон после пересчёта на новый кат (s10:92) и пункты без таймкода
    assert render_block('where', ['11:18–11:18']) == ['📍 ГДЕ · 11:18'] and clean('2:47 - 2:47 хвост') == '2:47 хвост'
    assert clean('2:47–2:47.5') == '2:47–2:47.5' and clean('2:47–12:47') == '2:47–12:47'
    got = render_block('do', ['вернуть реплики', '▸ первая', '• вторая', '7:05–7:05 ▸ третья'])
    assert got == [do_ru + ' · вернуть реплики', IND2 + '▸ первая', IND2 + '• вторая', IND2 + FIG + '7:05  ▸ третья'], got
    assert render_block('now', ['1:05 ▸ раз', 'хвост без времени']) == ['❌ СЕЙЧАС ·', IND + FIG + '1:05  ▸ раз',
                                                                        IND + 'хвост без времени']
    try:
        render_block('нет такого блока', ['x'])
        raise AssertionError('неизвестный блок принят')
    except KeyError:
        pass

    _sync_with_s10()

    # lint
    assert lint_line('11:16–11:40 ▸ куратор объясняет') == []
    assert lint_line(IND + FIG + '0:57  ▸ раз') == []
    assert lint_line('2:46.0–2:48.6 один таймкод') == []
    assert len(lint_line('на 1:05 и ещё на 12:30')) == 1
    assert len(lint_line('1:05–1:10 и 12:30')) == 1
    assert lint_line('счёт 3:2 не таймкод') == [] and lint_line('время 10:15:30 не таймкод') == []
    assert len(lint_line('а' * 221)) == 1 and lint_line(IND2 + 'а' * 220) == []
    assert len(lint_line('реплика обрывается…')) == 1 and len(lint_line('«обрыв...»')) == 1
    assert lint_line('слово… и дальше текст') == []
    assert len(lint_line('1:05 и 2:10 ' + 'а' * 230 + '…')) == 3

    # модуль обязан импортироваться без карточки фильма
    import subprocess
    env = {k: v for k, v in os.environ.items() if not k.startswith('YTAI_')}
    r = subprocess.run([sys.executable, '-c',
                        'import sys; sys.path.insert(0, %r); import tz_blocks; '
                        'assert "i18n" not in sys.modules and "proj_config" not in sys.modules; print("ok")' % str(HERE)],
                       capture_output=True, text=True, cwd='/', env=env)
    assert r.returncode == 0 and r.stdout.strip() == 'ok', r.stderr
    print('SELFTEST OK')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        print(__doc__)
