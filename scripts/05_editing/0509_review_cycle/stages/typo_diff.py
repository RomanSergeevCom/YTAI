# -*- coding: utf-8 -*-
"""Диф «было → стало» для опечаток (Роман 10.09: «если ошибка в орфографии — выделяй ещё то, что исправляешь»).

Общий модуль для s10 (текст ТЗ), doc_tab_tz_v3 (красные буквы в доке) и make_infographics_v6 G (драфты fix_*):
- diff_spans(was, now) → (spans_was, spans_now) — списки (start, end) изменённых знаков в символах python;
  числа сравниваются ЦЕЛЫМИ токенами (3450 → 8500 — красное всё число), остальное посимвольно, с регистром
  (AL → Al: красная «l»); вставленный пробел/запятая тоже спан (в доке видны за счёт фона).
- typo_line(was, now) — строка ТЗ «было «…» → стало «…»» (док ищет её целиком, она уникальна в ячейке).
- spans_for_fragment(was, now, frag) — спаны для текста fix-драфта, который может быть частью «стало».
"""
import difflib
import re
import sys
from pathlib import Path

_TOK = re.compile(r'\d+(?:[   .,]\d+)*|.', re.S)
try:
    import i18n  # noqa: E402  (обычно shared/ уже в sys.path через _bootstrap)
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'shared'))
    import i18n  # noqa: E402

# язык — по карточке/профилю (i18n.LANG): ru «было «…» → стало «…»», en «was “…” → now “…”»
PRE = i18n.T('core.was_pre')
MID = i18n.T('core.was_mid')
POST = i18n.T('core.was_post')


def _tokens(s):
    return [(m.start(), m.end(), m.group(0)) for m in _TOK.finditer(s)]


def _merge(spans):
    out = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def diff_spans(was, now):
    a, b = _tokens(was), _tokens(now)
    sm = difflib.SequenceMatcher(None, [t[2] for t in a], [t[2] for t in b], autojunk=False)
    sw, sn = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            continue
        if i2 > i1:
            sw.append((a[i1][0], a[i2 - 1][1]))
        if j2 > j1:
            sn.append((b[j1][0], b[j2 - 1][1]))
    return _merge(sw), _merge(sn)


def typo_line(was, now):
    return f'{PRE}{was}{MID}{now}{POST}'


def typo_offsets(was):
    """→ (смещение was, смещение now) внутри typo_line, в символах python."""
    return len(PRE), len(PRE) + len(was) + len(MID)


def spans_for_fragment(was, now, frag):
    """Изменённые знаки для текста драфта frag: frag ⊂ now → обрезка; now ⊂ frag → сдвиг; иначе диф was→frag."""
    _, sn = diff_spans(was, now)
    if frag in now:
        k = now.index(frag)
        return [(max(s, k) - k, min(e, k + len(frag)) - k) for s, e in sn if e > k and s < k + len(frag)]
    if now in frag:
        k = frag.index(now)
        return [(s + k, e + k) for s, e in sn]
    return diff_spans(was, frag)[1]


if __name__ == '__main__':
    for w, n in (('ЗАЩИШАЕТ ОТ ЗЛА', 'ЗАЩИЩАЕТ ОТ ЗЛА'), ('ВЕС: 3450 КАРАТА', 'ВЕС: ~8500 КАРАТ'),
                 ('AL₂O₃:CR', 'Al₂O₃:Cr'), ('ЛАТ.RUBEUS', 'ЛАТ. RUBEUS'),
                 ('А МОЖЕТ НЕ ТАКОЙ УЖ И ОБЫЧНЫНИ?', 'А МОЖЕТ, НЕ ТАКОЙ УЖ И ОБЫЧНЫЙ?'),
                 ('КРИСТАЛИЧЕСКИЙ', 'КРИСТАЛЛИЧЕСКИЙ'), ('ЭКСТРИМАЛЬНО РЕДКИЕ', 'ЭКСТРЕМАЛЬНО РЕДКИЕ')):
        sw, sn = diff_spans(w, n)
        print(f'{w!r:42} → {n!r:42} было:{[w[s:e] for s, e in sw]} стало:{[n[s:e] for s, e in sn]}')
    print(spans_for_fragment('А МОЖЕТ НЕ ТАКОЙ УЖ И ОБЫЧНЫНИ?', 'А МОЖЕТ, НЕ ТАКОЙ УЖ И ОБЫЧНЫЙ?', 'ОБЫЧНЫЙ?'))
