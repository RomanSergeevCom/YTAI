#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feedback_model — ОДНА модель документа «Обратная связь по кату vN» (контракт docs/feedback_v1.md, §3–§4, §7).

Зачем: монтажёр сдаёт новый кат, и ему нужен один документ из двух частей — что нового нашли в этом кате
(Часть 1, текущее ТЗ) и что стало с каждым пунктом прошлого ТЗ (Часть 2). Раньше вторая часть собиралась руками,
а кодовая сверка (tz-diff-v1) считала «сделано» по одной случайной цитате и печатала таймкоды прошлого ката.
Здесь всё сводится в work/{cut}/feedback.json; HTML и вкладка дока только читают его и статусы не пересчитывают.

Что делает модуль:
  split_nado / unwrap   — разбирает сплошной текст пункта прошлого ТЗ на блоки по меткам ❌ ✅ 📋 📍 📚 🎬. Текст там
                          жёстко перенесён по ~80 знаков, поэтому сначала склейка переносов; проверка без потерь —
                          join_parts(split_nado(x)) == x после сведения пробелов;
  clean_lines           — видимый текст: без внутреннего жаргона (имена кадров, номера заметок, «Директива v2 #18»…),
                          строка с двумя и более таймкодами режется на пункты «M:SS ▸ …» (цитату и скобку с
                          продолжением фразы не рвём — такая строка остаётся целой; длительности «(2:32)» пишутся
                          словами; адреса исходников «0:53:30 ↔ 57:32» таймкодами ката не считаются);
  fix_tc                — секунды пункта в прошлом кате; битые «2449:40» (секунды:минуты) декодируются;
  Projector             — перенос времени прошлого ката на новый по align.json (линейно внутри спана);
  retime_text           — каждый таймкод видимой строки Части 2 пересчитывается на новый кат («≈» — примерно);
  visible_block / fit   — видимый блок пункта: чистка не может опустошить блок (щадящий режим — убираются только
                          следы конвейера), голый таймкод не печатается, 📍 обязана назвать место в новом кате или
                          «весь фильм», строки ≤240 знаков без незакрытых скобок и кавычек (balance);
  partial_pass          — частично выполненный пункт («главы 13 из 13; подглавы 0 из 17»): первая строка ✅ и первый
                          экран говорят о НЕДОСТАЮЩЕМ; пункт-отсылка («Полный список — ТЗ-01») получает see_n;
  ensure_do             — у каждого пункта, печатаемого полным блоком, есть ✅ (иначе «Исправить: …», do_derived);
  human_summary         — строки вердикта без служебных имён правил канала;
  build                 — обе части, статусы (движок — shared/tz_diff.judge_v2), buckets, блокеры, темы фонда.
                          Ключ карточки feedback_sensitive_extra (env YTAI_FEEDBACK_SENSITIVE_EXTRA=86,97) — номера
                          прошлого ТЗ, чувствительные по сути, но без флага: sensitive=true, sensitive_by='card'.
  rebucket              — пересчёт buckets / блокеров / tally у уже записанной модели (после вердиктов агента).

Модуль импортируется без карточки фильма; карточка (YTAI_CARD) нужна только build().

usage: feedback_model.py [--prev PATH] [--out PATH] [--calibrate GOLD.json]
       feedback_model.py --selftest
env:   YTAI_CARD=<review_card.json>; YTAI_PREV_PRAVKI=<ТЗ прошлой версии> (если ключа prev_pravki нет в карточке)
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import i18n  # noqa: E402  (таблицы строк; карточку не требует)
import tz_diff as TD  # noqa: E402  (движок сопоставления; карточку не требует)

SCHEMA = 'feedback-v1'
KEYS = ('now', 'do', 'list', 'where', 'src', 'tl')
_LBL_KEY = {'now': 'core.lbl_now', 'do': 'core.lbl_do', 'list': 'core.lbl_list', 'where': 'core.lbl_where',
            'src': 'core.lbl_source', 'tl': 'core.lbl_timeline'}
# прошлые круги собраны с прежними метками — их текст разбирается здесь же (core.lbl_do_legacy)
_LBL_KEY_OLD = {'do': 'core.lbl_do_legacy'}
# метка → ключ блока, ru и en; длинные первыми
LABELS = sorted(((i18n.TL(lang, k), key)
                 for d in (_LBL_KEY, _LBL_KEY_OLD) for key, k in d.items() for lang in ('ru', 'en')),
                key=lambda x: -len(x[0]))
LABEL_RU = {key: i18n.TL('ru', k) for key, k in _LBL_KEY.items()}

TC = r'(?<![\d:.,])\d{1,4}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?(?!\d|:\d)'
TC_RE = re.compile(TC)
TC_SPAN_RE = re.compile(rf'[≈~]?\s*({TC})(?:\s*[–—-]\s*({TC}))?')
LINE_TC_START = re.compile(r'^[≈~]?\d{1,4}:\d{2}')
SOFT = '\u2028'                         # мягкий стык склеенного переноса (для squash — обычный пробел)
SRC_BEFORE = re.compile(r'(?:\bsrc|исходник\w*|клип\w*\s+tc)\s*$', re.I)
HMS_RE = re.compile(r'\d{1,2}:\d{2}:\d{2}')
DUR_BEFORE = re.compile(r'(?:всего|итого|длительност\w*|продолжительност\w*|хронометраж\w*|длиной)\s*[—:-]?\s*$', re.I)


def foreign_tc(s: str, m, hms_ok=False) -> bool:
    """таймкод НЕ ката: адрес в исходнике («src 57:32», «0:53:30,60 ↔ 57:32,59»; запись Ч:ММ:СС у фильма короче
    часа — тоже исходник). Такие не пересчитываются на новый кат и строку на пункты не режут. m — совпадение TC_SPAN_RE"""
    before, after = s[:m.start()], s[m.end():]
    return bool(SRC_BEFORE.search(before) or (not hms_ok and HMS_RE.match(m.group(1)))
                or re.search(r'↔\s*$', before) or re.match(r'\s*↔', after))


def cut_spans(s: str) -> list:
    """таймкоды ката в строке (совпадения TC_SPAN_RE без адресов исходников)"""
    return [m for m in TC_SPAN_RE.finditer(s) if not foreign_tc(s, m)]


def dur_words(sec) -> str:
    m, x = divmod(int(round(sec)), 60)
    return ' '.join(p for p in (f'{m} мин' if m else '', f'{x} с' if x or not m else '') if p)

# ── жаргон (JUNK — копия шаблонов stages/s14_polish_local.py; тот модуль при запуске грузит локальную модель) ──
JUNK = [(re.compile(r'\s*\(\s*[hsf]\d{3,4}(?:\s*[–,-]\s*[hsf]?\d{3,4})*\s*\)'), ''),
        (re.compile(r'\s*(?:в\s+)?кадр\w*\s+[hsf]\d{3,4}(?:\s*[–,-]\s*[hsf]?\d{3,4})*'), ''),
        (re.compile(r'\s*\b[hsf]\d{3,4}(?:\s*[–,-]\s*[hsf]?\d{3,4})*\b'), ''),
        (re.compile(r'\s*\(нот[аеы]\s*\d+\)|\s*нот[аеы]\s*\d+'), ''),
        (re.compile(r'\s*\(?коммент\s*\d+\)?'), lambda m: _par_safe(m)),
        (re.compile(r'\s*\(ночн\w+ разбор\)|\s*ночн\w+ разбор'), ''),
        (re.compile(r'\s*\(ревью\s*№?\s*\d\)|\s*ревью\s*№?\s*\d'), ''),
        # сверх s14: следы конвейера и прошлых версий ТЗ
        (re.compile(r'\s*\(\s*v\d\s+[\d:.,]+\s*→[^)]*\)'), ''),                    # «(v2 38:39 → v4 11:37)»
        (re.compile(r'(?:[,;]?\s*\(?\s*см\.)?\s*\(?\b[AX]\d{1,2}-\d{2}\b(?:\s*,\s*[AX]\d{1,2}-\d{2}\b)*\)?'),
         lambda m: _par_safe(m)),                                                  # «(X2-06, X2-09)», «…, см. A2-08)»
        (re.compile(r'\s*\((?=[^()]*\bv\d\s*#\d+)(?:[^()]|\([^()]*\))*\)'), ''),          # «(v2 #54 был ⛔, … — ⚠️)» целиком
        (re.compile(r'\s*\(?\bv\d\s*#\d+\)?|\s*\(#\d+\)'), lambda m: _par_safe(m)),    # «v2 #54», «(#5)»
        (re.compile(r'\s*\(?\bVLM\b:?'), lambda m: ' (' if '(' in m.group(0) else ''),
        (re.compile(r'\s*(?:по\s+)?\bv\d-TC\b'), ''),
        (re.compile(r'\s*[—–-]?\s*\b\d{4}\s*·\s*\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?(?:\s*[–—-]\s*\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?)?'), ''),
        (re.compile(r'\b([Вв]) v\d (на|с)(?=\s+[≈~]?\d{1,3}:\d{2})'),
         lambda m: (m.group(2).capitalize() if m.group(1) == 'В' else m.group(2))),                                # «перестановками по v4-TC»
        (re.compile(r'\b([Пп]о) OCR\b'), r'\1 распознаванию текста'),
        (re.compile(r'(?<=одозрения )OCR\b'), 'распознавания текста'),
        (re.compile(r'\bOCR\b'), 'распознавание текста'),
        (re.compile(r'\bTO-BE(?:\s+v\d+)?', re.I), 'перестановки'),
        (re.compile(r'\s*\bstructure_checks\b:?\s*(?:fail|pass|n/a)?,?'), ''),
        (re.compile(r'\s*\((?=[^()]{0,40}\))[^()]*\b[a-z]{2,}(?:_[a-z0-9]+)+\b[^()]*\)'), lambda m: _snake_par(m)),
        (re.compile(r'\s*\b[a-z]{2,}(?:_[a-z0-9]+)+\b'), ''),
        (re.compile(r'\s*\(правило\)'), ''),                      # fund_entry_min и прочие имена полей
        # номера исходных клипов — адрес для монтажного стола, а не для этой поверхности: «(клип 0869)», «(0850, 0877…)»
        (re.compile(r'\s*\(\s*клип\w*\s+\d{4}\s*\)|\s*\bклип\w*\s+\d{4}\b'), ''),
        (re.compile(r'\s*(?<![\d:.,])\d{4}(?:×\d+)?(?:\s*,\s*\d{4}(?:×\d+)?)+(?![\d:])'),
         lambda m: '' if re.search(r'(?<!\d)0\d{3}', m.group(0)) else m.group(0)),
        (re.compile(r'\s*(?<![\d:.,])\d{2}\s*·\s*0\d{3}(?:\s*[–-]\s*0?\d{3,4})?(?![\d:])'), ''),   # «05 · 0901» — сцена · клип
        (re.compile(r'\s*(?:(?<![А-Яа-яЁё])(?:в|из|от)\s+)?(?<![\d:.,×])0\d{3}(?:×\d+)?(?:\s*[–-]\s*0\d{3})?(?![\d:]|[.,]\d)'), '')]
# щадящая чистка (блок нельзя опустошить): вместо предложения целиком убирается только сам след
SOFT_TOKENS = [(re.compile(r'\s*(?:(?<![А-Яа-яЁё])(?:на|с|со|до|по|в|от|к)\s+)?\bsrc[ _]\s*' + TC + r'(?:\s*[–—-]\s*' + TC + r')?'), ''),
               (re.compile(r'\s*\(?(?:Директива v\d(?:\s*#\d+)?|anchors_v\d|Speaker \d|n/a|v\d_tc|end_tc|anchor|subchapters|'
                           r'youtube_chapters|\bsrc\b|\b[\w-]+\.json\b)\)?', re.I), '')]
# предложение с таким следом выкидывается целиком: без него от фразы остаётся обрывок
DROP_SENT = re.compile(r'\bEDL\b|пословн\w*\s+TC|Директива v\d|anchors_v\d|\bSpeaker \d|\bn/a\b|\bsrc[ _]|\bv\d_tc\b|\bend_tc\b|\banchor\b|'
                       r'subchapters|youtube_chapters|\b\w+\.json\b', re.I)
LEAD_DUP = re.compile(r'^(?:[❌✅▶]\s*)+(?:Сделать:\s*(?:-\s*)?)?', re.I)
BLUR_RE = re.compile(r'блюр|заблюр|кроп|перекадр|кадрирова|обезлич|размы', re.I)
COND_RE = re.compile(r'\bесли\b|при отказе|в случае|откаж|не подтверд|не соглас|после ответа|не нуж|не требу', re.I)
INF_RE = re.compile(r'^[«"(]?[А-ЯЁа-яё-]+(?:ть|ти|чь|ться|тись)\b')
JARGON_RE = re.compile(r'\b(?:align|OCR|VLM|overlap|status_by)\b|\b[hsf]\d{3,4}\b', re.I)


def _snake_par(m) -> str:
    """скобка со служебным именем: «(тексты — в graphics_tz)» без имени — обрубок «(тексты — в)» → снимается целиком;
    «(fund_piece_max_sec ≤ 90 c)» → «(≤ 90 c)» — порог остаётся"""
    t = m.group(0)
    rest = re.sub(r'\s*\b[a-z]{2,}(?:_[a-z0-9]+)+\b', '', t.strip()[1:-1]).strip(' ,;:—–-')
    if not re.search(r'\w', rest) or re.search(r'(?<![А-Яа-яЁё])(?:в|во|на|из|по|от|к|с|см\.?)$', rest):
        return ''
    return f' ({rest})'


def _par_safe(m) -> str:
    """замена для следа со «своей» скобкой: «(X2-06)» → пусто, но «(имя звучит позже, см. A2-08)» → «)» — чужую
    закрывающую скобку след не уносит (и открывающую тоже)"""
    t = m.group(0)
    opened, closed = t.count('('), t.count(')')
    return ' (' if opened > closed else (')' if closed > opened else '')


def squash(s) -> str:
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def tc_str(sec) -> str:
    t = int(round(float(sec)))
    return f'{t // 60}:{t % 60:02d}'


# ═══ 1. разбор текста пункта ═════════════════════════════════════════════════════════════════════════════════
def _label_of(line: str):
    """строка начинается с метки блока (без отступа) → (ключ, остаток без « · »); иначе (None, строка)"""
    for lbl, key in LABELS:
        if line.startswith(lbl):
            return key, re.sub(r'^\s*·\s?', '', line[len(lbl):])
    return None, line


def unwrap(lines) -> list:
    """склейка жёстких переносов. Строка-продолжение клеится к предыдущей, КРОМЕ: начинается с «▸» или «•»;
    начинается с таймкода при отступе ≥ 8 (пункт списка; при отступе 5 строка с таймкода — это перенос посреди
    фразы, таких в ТЗ v4 179); предыдущая кончилась на «.», «:», «;», а новая — с заглавной при отступе ≥ 8.
    Стык — пробельный знак SOFT: для проверки «без потерь» это пробел, а резке по таймкодам он подсказывает, где
    прошлая полировка разорвала перечисление."""
    out = []
    for raw in lines:
        s = str(raw).strip()
        if not s:
            continue
        indent = len(raw) - len(str(raw).lstrip())
        new = (not out or s[0] in '▸•' or (LINE_TC_START.match(s) and indent >= 8)
               or (out[-1][-1:] in '.:;' and s[0].isupper() and indent >= 8))
        if new:
            out.append(s)
        else:
            out[-1] = f'{out[-1]}{SOFT}{s}'
    return out


def split_nado(text) -> dict:
    """текст пункта → {now|do|list|where|src|tl: [[строки одного меченого куска], …]}. Метки повторяются внутри
    пункта (три «❌ СЕЙЧАС» подряд — три пересказа одного места), каждый повтор — свой элемент."""
    parts = {k: [] for k in KEYS}
    cur = None
    for ln in str(text or '').split('\n'):
        key, rest = _label_of(ln)
        if key:
            cur = [rest]
            parts[key].append(cur)
        elif cur is not None:
            cur.append(ln)
        elif ln.strip():                                   # текст до первой метки — это «сейчас»
            cur = [ln]
            parts['now'].append(cur)
    return {k: [unwrap(el) for el in v] for k, v in parts.items()}


def join_parts(parts) -> str:
    """обратная сборка для проверки «без потерь»; сравнивать после squash()"""
    out = []
    for k in KEYS:
        for el in parts.get(k) or []:
            out.append(f'{LABEL_RU[k]} · ' + ' '.join(el))
    return '\n'.join(out)


def lossless(text) -> bool:
    """join(split(x)) == x с точностью до пробельных символов и языка метки"""
    src = squash(text)
    for lbl, key in LABELS:
        src = src.replace(lbl, LABEL_RU[key])
    return squash(join_parts(split_nado(text))) == src


# ═══ 2. чистка видимого текста ═══════════════════════════════════════════════════════════════════════════════
def _sentences(s: str) -> list:
    """предложения; внутри «…» не режем"""
    out = []
    for x in re.split(r'(?<=[.!?»)])\s+(?=[А-ЯЁA-Z«❌✅▶⚠])', s):
        if out and out[-1].count('«') > out[-1].count('»'):
            out[-1] += ' ' + x
        else:
            out.append(x)
    return out


def _durations(s: str) -> str:
    """длительность, записанная как таймкод, → словами: «12:45–15:17 (2:32, а дальше…)» → «(2 мин 32 с, …)»,
    «всего 1:22» → «всего 1 мин 22 с». Иначе она пересчиталась бы на новый кат как место в фильме."""
    def after_range(m):
        a, b, d = (_tc_val(m.group(k))[0] for k in (1, 2, 4))
        return m.group(0) if abs((b - a) - d) > 3 else m.group(0)[:m.start(4) - m.start()] + dur_words(d)
    s = re.sub(rf'({TC})\s*[–—-]\s*({TC})(\s*\(\s*)({TC})', after_range, s)

    def after_word(m):
        return m.group(0) if not DUR_BEFORE.search(s[:m.start()]) else dur_words(_tc_val(m.group(0))[0])
    return TC_RE.sub(after_word, s)


HANG_RE = re.compile(r'[\s,;:—–-]+(?<![А-Яа-яЁё])(?:на|в|во|с|со|и|а|до|от|к|по|из|у|о|за|для|или|но)\s*(?=[.!?)]?$)', re.I)


def _punct(s: str) -> str:
    """пунктуация после вычистки: «(, текст» → «(текст», «текст,)» → «текст)», пустые скобки, пробел перед знаком,
    двойные пробелы и знаки, висящий предлог в конце строки. Мягкие стыки SOFT не трогаем."""
    prev = None
    while s != prev:
        prev = s
        s = re.sub(r'\(\s*[,;:·—–-]+\s*', '(', s)
        s = re.sub(r'\s*[,;:·—–-]+\s*\)', ')', s)
        s = re.sub(r'\s*\(\s*\)', '', s)
        s = re.sub(r'\(\s+', '(', s)
        s = re.sub(r'[ \t]+([,.;:)])', r'\1', s)
        s = re.sub(r'([,;:])(?:\s*[,;:])+', r'\1', s)
        s = re.sub(r',\s*\.', '.', s)
        s = re.sub(r'[ \t]{2,}', ' ', s)
        s = HANG_RE.sub(lambda m: m.group(0) if re.search(r'\d\s*$', s[:m.start()]) else '', s)   # «−7 с» — секунды
    return s


_HEAL_PREP = re.compile(r'(?<![А-Яа-яЁё\d])(?<!\d\s)(?:на|в|во|с|со|до|от|к|по|около|и|а|или|но|что|как|из|у|за|для|под|над|при|без|не|о|об)$', re.I)


def heal(s: str) -> str:
    """стык жёсткого переноса (SOFT) → знак, который съела прошлая разбивка «таймкод с новой строки». В ТЗ v4 перенос
    стоит там, где была запятая или точка: «хлам 0:30⏎балкон 0:43», «…нельзя⏎В v4 на 51:02». Правила: перед скобкой,
    стрелкой, тире, «и/или», после предлога и перед таймкодом после слова — пробел; между двумя таймкодами, перед
    «а/но» и перед строчной — запятая; перед заглавной вне цитаты и скобки — точка."""
    if SOFT not in s:
        return s
    bits = s.split(SOFT)
    out = bits[0]
    for nxt in bits[1:]:
        a, b = out.rstrip(), nxt.lstrip()
        if not a or not b:
            out = a + ' ' + b
            continue
        tc_a = bool(re.search(TC + r'\)?$', a))
        if b[0] in '(→—–-,.;:)»·=+/' or a[-1] in ',.;:—–(«=→·+/' or _HEAL_PREP.search(a) or re.match(r'(?:и|или|либо)\s', b):
            j = ' '
        elif re.match(r'(?:а|но)\s', b):
            j = ', '
        elif re.match(r'[≈~]?\d{1,4}:\d{2}', b):
            j = ', ' if (tc_a or a[-1] == '»') else ' '
        elif b[0].isupper() and not _in_quote(a, len(a)) and a.count('(') <= a.count(')'):
            j = '. '
        elif b[0].isupper():                               # внутри цитаты — новое предложение реплики, в скобке — пробел
            j = '. ' if (_in_quote(a, len(a)) and a[-1].islower()) else ' '
        else:
            j = ', '
        out = a + j + b
    return out


def strip_junk(s: str, drop=True) -> str:
    """без squash: мягкие стыки SOFT доживают до резки по таймкодам. drop=False — щадящий режим для блока, который
    обычная чистка опустошила бы: предложение со следом конвейера остаётся, убирается только сам след."""
    s = LEAD_DUP.sub('', str(s or '').strip())
    if drop:
        s = ' '.join(x for x in _sentences(s) if not DROP_SENT.search(x))
    else:
        for rx, rep in SOFT_TOKENS:
            s = rx.sub(rep, s)
    for rx, rep in JUNK:
        s = rx.sub(rep, s)
    s = re.sub(rf'(?<![А-Яа-яЁё])(?:[СсC]|[Оо]т)\s+({TC})\s+(?:до|по)\s+({TC})', r'\1–\2', s)   # «с 12:45 до 15:17»
    s = _punct(_durations(s))
    s = re.sub(r'(?<=[а-яё0-9»)]{3}\.) ([а-яё])(?=[а-яё]{2})', lambda m: ' ' + m.group(1).upper(), s)   # после выкинутого куска
    return s.strip(' ,;—-·')


def _tidy(rest: str) -> str:
    rest, prev = squash(re.sub(r'\s+([,.;:])', r'\1', re.sub(r'\(\s*\)', '', rest))).replace('( ', '('), None
    while rest != prev:                                    # обрывки связок и знаков по краям куска
        prev = rest
        rest = re.sub(r'^[\s,;:.—→•·)–@-]+|[\s,;:—→•·(–@-]+$', '', rest)
        rest = re.sub(r'\s+(?:на|в|во|с|со|и|а|до|от|к|по)$', '', rest)
        rest = re.sub(r'^(?:и|а)\s+', '', rest)
    if rest.count('(') > rest.count(')'):
        rest += ')'
    if rest.count(')') > rest.count('('):
        rest = rest.replace(')', '', 1)
    return rest if re.search(r'\w', rest) else ''


def _in_quote(s: str, pos: int) -> bool:
    return s[:pos].count('«') > s[:pos].count('»')


CONN_RE = re.compile(r'^[\s,;]*(?:и|а\s+также)\s+(?:(?:на|в|с)\s+)?$')
# «осмысленная фраза» для резки по таймкодам: цитата в «…» либо ≥3 слов и действие (глагол, краткое причастие,
# отглагольное существительное, слово монтажного действия). Эвристика намеренно строгая: не узнали действие —
# строку НЕ режем (две метки времени в цитате прошлого ТЗ терпимы, обрубок «1:25 ▸ собака» — нет).
_NOT_VERB = {'если', 'или', 'либо', 'после', 'возле', 'часть', 'опять', 'пять', 'путь', 'мать', 'дочь', 'ночь', 'почти',
             'очень', 'лет', 'свет', 'цвет', 'ответ', 'совет', 'кредит', 'брат', 'минут', 'формат', 'результат',
             'предмет', 'пакет', 'секрет', 'бюджет', 'портрет', 'сюжет', 'интернет', 'кабинет', 'билет', 'привет',
             'мало', 'дело', 'дела', 'тело', 'село', 'число', 'стекло', 'кресло', 'одеяло', 'тепло', 'начало',
             'экран', 'план', 'сцена', 'сцены', 'смена', 'стена', 'стены', 'цена', 'цены', 'жена', 'жены', 'диван',
             'стакан', 'кран', 'перемена', 'колено', 'институт', 'маршрут', 'салют', 'уют', 'стол', 'пол', 'угол',
             'футбол', 'вокзал', 'канал', 'финал', 'сигнал', 'журнал', 'материал', 'оригинал', 'зал', 'школа', 'школы'}
_VERB_RE = re.compile(r'(?<![а-яё])(?:[а-яё]{2,}(?:ть|ти|чь)(?:ся|сь)?|[а-яё]{3,}(?:л|ла|ло|ли)(?:сь|ся)?|'
                      r'[а-яё]{2,}(?:ет|ёт|ит|ют|ут|ат|ят|ем|им|ешь|ишь)(?:ся)?|[а-яё]{3,}(?:[ая]н|[её]н|[ая]н[аоы]|[её]н[аоы]|'
                      r'ыт|ыт[аоы]|ят[аоы])|[а-яё]{3,}(?:ние|ния|нием|нию|нии|ция|ции|цию|тие|тия))(?![а-яё])', re.I)
_ACT_RE = re.compile(r'(?<![а-яё])(?:нет|есть|нужн\w*|надо|нельзя|можно|должн\w*|вырез\w*|вставк\w*|склейк\w*|перенос\w*|'
                     r'замен\w*|повтор\w*|перебив\w*|наезд\w*|блюр\w*|кроп\w*|стык\w*|пауз\w*|обрыв\w*)(?![а-яё])', re.I)


def _meaningful(rest: str) -> bool:
    """кусок после резки — самостоятельная фраза: целая цитата «…» либо ≥3 слов и действие"""
    rest = str(rest or '')
    if rest.count('«') != rest.count('»') or rest.count('(') != rest.count(')'):
        return False
    if re.search(r'«[^«»]{2,}»', rest):
        return True
    words = re.findall(r'[^\W\d_]+', rest)
    if len(words) < 3:
        return False
    if _ACT_RE.search(rest):
        return True
    for m in _VERB_RE.finditer(rest):
        w = m.group(0)
        if w.lower() in _NOT_VERB or (w[:1].isupper() and not re.search(r'(?:ть|ти|чь)(?:ся|сь)?$', w)):
            continue                                        # «Жимагул», «Иваново», «Панфилов» — не глаголы
        return True
    return False


def _cap(s: str) -> str:
    """первая буква фразы — заглавная («≈1:29 ▸ добавить…» → «≈1:29 ▸ Добавить…»): кусок после резки — отдельная
    строка. Цитата «…» дословна — её регистр не трогаем."""
    return re.sub(r'^((?:[≈~]?' + TC + r'(?:\s*[–—-]\s*' + TC + r')?\s*▸\s*)?)([а-яёa-z])',
                  lambda m: m.group(1) + m.group(2).upper(), s, count=1)


def _split_by_tc(s: str) -> list:
    """предложение с ≥2 таймкодами ката → пункты «M:SS ▸ …». Чей текст: таймкод перед «цитатой» или в начале
    предложения — к словам ПОСЛЕ него; таймкод в скобках или в конце куска (за ним стык, знак или конец) — к словам
    ПЕРЕД ним; иначе — к словам после. Внутри «цитаты» и внутри скобки с продолжением фразы не режем: если чистого
    места для разреза нет, предложение остаётся целым (две метки времени в строке лучше разорванной фразы).
    Перечисление «… 0:31 и 1:18» — второй таймкод получает тот же текст, а не обрывок «и»."""
    spans = cut_spans(s)
    if len(spans) < 2:
        return [s]
    if re.search(rf'(?<![а-яё])между\s+[≈~]?{TC}\s+и\s+[≈~]?{TC}', s, re.I):
        return [s]                                          # «между 9:20 и 9:21» — одно место, названное двумя метками
    ends, back, par = [], [], []
    for m in spans:
        before, after = s[:m.start()], s[m.end():]
        in_par = before.rfind('(') > before.rfind(')')
        end = m.end()
        if in_par and ')' in after and not cut_spans(after[:after.index(')')]):
            end = m.end() + after.index(')') + 1            # скобка закрывается сразу за этим таймкодом
        # «цитата» вплотную за таймкодом (без стыка переноса) — его текст; если цитата вплотную ПЕРЕД ним — наоборот
        fwd = not re.search(r'\w', before) or (re.match(r'[ \t]*«', after) and not re.search(r'»[ \t≈~]*$', s[:m.start(1)]))
        back.append(not fwd and (in_par or not after.strip() or after[:1] == SOFT or bool(re.match(r'\s*[.,;]', after))))
        ends.append(end)
        par.append(before.rfind('(') if in_par else -1)
    cuts = [0]
    for i in range(len(spans) - 1):
        lo, hi = min(ends[i], spans[i + 1].start()), spans[i + 1].start()
        if back[i]:
            first = None if back[i + 1] else re.search(SOFT + r'|\.\s|;', s[lo:hi])
            cuts.append(lo + first.start() if first and not _in_quote(s, lo + first.start()) else lo)
        else:
            seg = s[lo:hi]
            marks = [m.start() for m in re.finditer(r'[,;—→]|\.\s|\s[иа]\s|\s•\s' + ('' if back[i + 1] else '|' + SOFT), seg)]
            marks = [k for k in marks if not _in_quote(s, lo + k)]
            cuts.append(lo + marks[-1] if marks else (hi if not _in_quote(s, hi) else lo))
    cuts.append(len(s))
    for i, c in enumerate(cuts[1:-1]):
        open_par = s[:c].rfind('(') > s[:c].rfind(')')
        if _in_quote(s, c) or (open_par and not (par[i] == par[i + 1] == s[:c].rfind('('))):
            return [s]                                      # разрез попал бы в цитату или в скобку с чужим текстом
    out, last = [], ''
    for i, sp in enumerate(spans):
        piece = s[cuts[i]:cuts[i + 1]]
        k = piece.find(sp.group(0).strip())
        tcs = squash(sp.group(0))
        own = k >= 0 and re.match(r'[\s,:—–-]*\(?\s*«', piece[k + len(sp.group(0).strip()):])
        if i and last and k >= 0 and CONN_RE.match(piece[:k]) and not own:   # «… и 1:18»: то же самое, ещё одно место
            tail = _tidy(piece[k + len(sp.group(0).strip()):])
            q = re.findall(r'«[^«»]+»', last)
            same = q[-1] if q else (last if len(last) <= 90 else '')
            if not _meaningful(same) or (tail and not _meaningful(tail)):
                return [s]                                  # голый таймкод или обрывок хвоста — не режем
            out.append(f'{tcs} ▸ {same}')
            if tail:
                out.append(_cap(tail))
            continue
        rest = _tidy(re.sub(r'(?:(?<![А-Яа-яЁё])(?:на|в|во|с|со|до|от|к|по|около))?\s*' + re.escape(sp.group(0).strip()),
                            ' ', piece, count=1, flags=re.I))
        wrapped = re.fullmatch(r'\(([^()]*)\)([.!?]?)', rest)
        if wrapped:                                         # кусок целиком в скобках — скобки снимаются
            rest = _tidy(wrapped.group(1)) + wrapped.group(2)
        if not _meaningful(rest) or rest[:1] in '(,;':
            return [s]                                      # В СОМНЕНИИ — НЕ РЕЗАТЬ: обрубок хуже двух меток времени
        last = rest
        out.append(_cap(f'{tcs} ▸ {rest}'))
    return out


def _split_safe(sent: str) -> list:
    """цитата прошлого ТЗ с ≥2 таймкодами: режем ТОЛЬКО по «;» вне цитат и скобок, и только если каждый кусок —
    осмысленная фраза. Таймкод из середины фразы не выносится в начало и чужой текст куску не приписывается:
    вынос давал неправду («38:10 ▸ «В275АО 152»» там, где номера как раз НЕ читаются) и обрубки («34:50 ▸ Между
    «…когда он умер.»»). Две метки времени в цитате прошлого ТЗ — допустимое предупреждение."""
    pieces = _clauses(sent)
    if len(pieces) < 2 or not all(_meaningful(x) and x[:1] not in '(,' for x in pieces):
        return [sent]
    out = []
    for x in pieces:
        m = re.match(rf'([≈~]?{TC}(?:\s*[–—-]\s*[≈~]?{TC})?)\s+(?=[«А-ЯЁа-яё])', x)
        if m and len(cut_spans(x)) == 1 and '▸' not in x:
            x = f'{squash(m.group(1))} ▸ {x[m.end():]}'
        out.append(_cap(x))
    return out


def clean_lines(lines, safe=False) -> list:
    """видимые строки: без жаргона; строка с ≥2 таймкодами ката режется на пункты «M:SS ▸ …» (сначала по
    предложениям). Адреса исходников (src, Ч:ММ:СС, «↔») таймкодами ката не считаются. safe=True — цитаты прошлого
    ТЗ: режем только по «;» (см. _split_safe), строки Части 1 режутся полностью (там ≥2 таймкода — ошибка)."""
    out = []
    for ln in lines or []:
        s = strip_junk(heal(str(ln)) if safe else ln)      # знаки на стыках переносов — только цитатам прошлого ТЗ
        if not s:
            continue
        if len(cut_spans(s)) < 2:
            out.append(s)
            continue
        cur, cur_n = '', 0
        for sent in _sentences(s):
            n = len(cut_spans(sent))
            if n >= 2:
                if cur:
                    out.append(cur)
                out += _split_safe(sent) if safe else _split_by_tc(sent)
                cur, cur_n = '', 0
            elif cur and cur_n + n >= 2:
                out.append(cur)
                cur, cur_n = sent, n
            else:
                cur, cur_n = (f'{cur} {sent}' if cur else sent), cur_n + n
        if cur:
            out.append(cur)
    return [x for x in (squash(o) for o in out) if x]


MAX_LINE = 240                          # контракт §5; строки модели уже не длиннее — вид их не режет
BARE_TC_RE = re.compile(rf'^[≈~]?{TC}(?:\s*[–—-]\s*{TC})?\s*▸?\s*$')
WHOLE_FILM_RE = re.compile(r'весь фильм|whole film', re.I)
_ABBR = {'т', 'е', 'г', 'ул', 'см', 'руб', 'мин', 'сек', 'тыс', 'млн', 'стр', 'им', 'др', 'пр', 'гг', 'гл'}
_SENT_END = re.compile(r'[.!?]["»”)]?\s+(?=[A-ZА-ЯЁ«“"\d❌✅▶📍⚠≈])')     # «(» не начало: скобка относится к фразе перед ней
_CLAUSE_END = re.compile(r'(?:;|\s—|\s→|,)\s+')


def _open_at(s: str, a: str, b: str) -> tuple:
    """→ (позиции незакрытых открывающих знаков a, позиции лишних закрывающих b)"""
    stack, extra = [], []
    for i, ch in enumerate(s):
        if ch == a:
            stack.append(i)
        elif ch == b:
            if stack:
                stack.pop()
            else:
                extra.append(i)
    return stack, extra


def _balanced(s: str) -> bool:
    return s.count('«') == s.count('»') and s.count('(') == s.count(')')


def _sent_cuts(s: str) -> list:
    out = []
    for m in _SENT_END.finditer(s):
        w = re.search(r'(\w+)\.$', s[:m.start() + 1])
        if not (w and w.group(1).lower() in _ABBR):
            out.append(m.start() + len(m.group(0).rstrip()))
    return out


def balance(s: str) -> str:
    """строка без незакрытых кавычек и скобок. Исходник прошлого ТЗ местами обрезан на полуслове («Продолжить с «и»):
    незакрытая цитата отбрасывается вместе с начатым предложением; незакрытая скобка в хвосте — отбрасывается,
    в середине — заменяется тире; лишние закрывающие знаки убираются."""
    s = squash(s)
    for _ in range(6):
        if _balanced(s):
            break
        q_open, q_extra = _open_at(s, '«', '»')
        p_open, p_extra = _open_at(s, '(', ')')
        if q_extra or p_extra:
            i = (q_extra or p_extra)[-1]
            s = s[:i] + s[i + 1:]
        elif q_open:
            head = s[:q_open[-1]]
            cut = max((c for c in _sent_cuts(head + ' Я') if c >= 40 and _balanced(head[:c])), default=0)
            cand = head[:cut] if cut else _punct(head.rstrip())
            s = cand if len(cand) >= 20 else s + '»'
        elif p_open:
            i = p_open[-1]
            s = s[:i] if len(s) - i <= 80 else s[:i].rstrip() + ' — ' + s[i + 1:]
        s = squash(_punct(s)).rstrip(' ,;:—–-(«')
    return s


def fit(line: str, limit=MAX_LINE):
    """→ (строки ≤ limit, сколько хвостов отброшено). Режем по границе предложения, где скобки и кавычки закрыты, —
    хвост становится следующей строкой блока; нет такой границы — по границе оборота, хвост отбрасывается (он
    начинался бы с полуслова) и считается в more."""
    line = balance(line)
    if len(line) <= limit:
        return ([line] if line else []), 0
    cut = max((c for c in _sent_cuts(line) if 15 <= c <= limit and _balanced(line[:c])), default=0)   # короткое, но целое
    if cut:
        rest, lost = fit(line[cut:].lstrip(' ,;—'), limit)
        return [line[:cut].rstrip(' ,;—')] + rest, lost
    cut = max((m.start() for m in _CLAUSE_END.finditer(line) if 60 <= m.start() <= limit and _balanced(line[:m.start()])),
              default=0)
    if not cut:
        cut = line.rfind(' ', 0, limit)
        cut = cut if cut > 0 else limit
    return [balance(_punct(line[:cut]).rstrip(' ,;:—–-'))], 1


def _key_of(x: str) -> str:
    return squash(re.sub(r'[^\w]+', ' ', x.lower()))


def _dedupe(lines: list) -> list:
    """прошлое ТЗ местами склеено из двух заметок через « · » и повторяет одну фразу дважды («Сверить со Светой, кто
    на снимке. … · Сверить со Светой, кто на снимке.»): куски « · » — отдельные строки, повтор фразы не печатается"""
    seen, out = set(), []
    for ln in (y for x in lines for y in re.split(r'\s+·\s+(?=⚠|[А-ЯЁ][а-яё])', x)):
        keep = []
        for sent in _sentences(ln):
            k = _key_of(sent)
            if len(k) >= 12 and any(o == k or o.startswith(k + ' ') for o in seen):
                continue                                    # повтор фразы или её начала («⚠️ На подтверждение фонда.»)
            seen.add(k)
            keep.append(sent)
        if keep:
            out.append(' '.join(keep))
    return out


def _unnest(s: str) -> str:
    """📍 «якорь ««…» → «…»»» — внешняя пара кавычек лишняя"""
    if '««' in s and '»»' in s:
        i, j = s.index('««'), s.rindex('»»')
        if i < j:
            s = s[:i] + s[i + 1:j] + s[j + 1:]
    return s


def visible_block(els, key, retime=None):
    """меченые куски одного блока (❌ / ✅ / 📍) → (видимые строки, сколько строк исходника не вошло).
    Берётся первый кусок, от которого после чистки что-то осталось. Чистка не имеет права опустошить блок: если
    обычная чистка съела кусок целиком, берётся его первая строка с удалёнными только следами конвейера.
    Голый таймкод без текста в ❌/✅ не печатается. 📍 обязана назвать место в новом кате (таймкод) либо «весь
    фильм» — иначе это не место, а смета или адрес исходника, и строка не печатается."""
    picked, more = [], 0
    for el in (el for el in (els or []) if el):
        if picked:
            more += len(el)
            continue
        lines = clean_lines(el, safe=retime is not None)      # retime есть только у цитат прошлого ТЗ
        if not lines:
            lines = [x for x in (squash(strip_junk(heal(str(ln)) if retime else ln, drop=False)) for ln in el)
                     if re.search(r'\w', x)][:1]
        if retime:
            lines = [x for x in (retime(ln) for ln in lines) if x]
        if retime and key != 'where':
            lines = _dedupe(lines)
        if key == 'where':
            lines = [_unnest(ln) for ln in lines]
        if key == 'where':                                 # 📍 из одних таймкодов — список мест: по месту на строку
            lines = [y for ln in lines for y in ([squash(m.group(0)) for m in cut_spans(ln)]
                                                 if len(cut_spans(ln)) >= 2 and not re.search(r'[^\W\d_]', ln) else [ln])]
        for ln in lines:
            if (key != 'where' and BARE_TC_RE.match(ln)) or \
                    (key == 'where' and not (cut_spans(ln) or WHOLE_FILM_RE.search(ln))):
                more += 1
                continue
            got, lost = fit(_cap(ln) if ('▸' in ln[:24] or (retime and key != 'where')) else ln)
            picked += [x for x in got if not (key != 'where' and BARE_TC_RE.match(x))]
            more += lost
        if not picked:
            more += 0 if lines else len(el)
    return picked, more


def clean_title(t: str, limit=90, retime=None) -> str:
    """заголовок без жаргона; обрезанный исходником на полуслове — до границы слова. retime — пересчёт таймкодов
    на новый кат (заголовок пункта прошлого ТЗ проходит тот же retime_text, что и строки блоков)"""
    raw = squash(t)
    s = strip_junk(raw)
    if retime:
        s = retime(s)
    if len(raw) >= limit - 2 and not re.search(r'[.!?»)…]$', s):
        s = s.rsplit(' ', 1)[0] if ' ' in s else s
    if len(s) > limit:
        s = s[:limit].rsplit(' ', 1)[0]
    s = s.rstrip(' ,;:—-(«')
    if s.count('«') > s.count('»'):
        s += '»'
    return s


def heal_title(title: str, raw: str, texts, limit=90) -> str:
    """заголовок, обрезанный исходником на ~90 знаках, кончается обрубком: «…Съёмка — июль 2026. Отоп»», «…+ кровный»,
    «…«Говорили, типа у них другая»» (закрывающая кавычка приставлена к недосказанной цитате — это искажение).
    Только если заголовок — начало текста пункта и оборван посреди фразы: недосказанная цитата режется до последней целой
    части (конец предложения или « / » в тексте титра), нет такой — снимается целиком; хвост из ≤3 слов после
    последней границы убирается. Новых слов не добавляется."""
    full = squash(' '.join(str(x) for x in texts or []))
    cut_here = squash(raw).endswith('…')                    # исходник сам пометил обрыв
    for cand in (() if cut_here else (squash(raw), squash(title))):
        core = cand.rstrip('…').rstrip().rstrip('»').rstrip()
        k = full.find(core) if len(core) >= 20 else -1
        if k >= 0:
            after = full[k + len(core):].lstrip('»')
            cut_here = bool(after.strip()) and after[:1] not in '.!?;'
            break
    if not cut_here:
        return title                                        # заголовок досказан (или он не начало текста пункта)
    t = title.rstrip('… ').rstrip()
    i = t.rfind('«')
    if i >= 0 and '»' not in t[i:-1]:                       # последняя цитата: закрыта только приставленной «»»
        inner = t[i + 1:].rstrip('»').rstrip()
        kk = full.find(inner) if len(inner) >= 2 else -1
        nxt = full[kk + len(inner):] if kk >= 0 else ''
        whole = kk >= 0 and nxt[:1] == '»'
        if not whole:
            seg_done = bool(re.match(r'\s*/', nxt)) and ' / ' in inner
            cuts = [m.end() for m in re.finditer(r'[.!?](?=\s)', inner)] + [m.start() for m in re.finditer(r'\s/\s', inner)]
            cuts = [c for c in cuts if c >= 10]
            if seg_done:
                t = t[:i + 1] + inner.rstrip(' /.,—') + '»'
            elif cuts:
                t = t[:i + 1] + inner[:max(cuts)].rstrip(' /,—') + '»'
            else:
                t = t[:i].rstrip()
    t = t.rstrip(' ,;:—–+/-(')
    if not re.search(r'[.!?»)]$', t):
        ends = [m.end() for m in re.finditer(r'[.!?](?=\s+[А-ЯЁ«])', t) if not _in_quote(t, m.start()) and m.end() >= 25]
        if ends:
            t = t[:max(ends)]
        else:
            b = max(t.rfind('»'), t.rfind(';'))
            if b >= 25 and len(re.findall(r'\w+', t[b + 1:])) <= 3:
                t = t[:b + 1] if t[b] == '»' else t[:b]
    t = t.rstrip(' ,;:—–+/-(')
    if t.count('(') > t.count(')'):
        t += ')'
    return t if len(t) >= 12 else title


# ═══ 3. таймкоды прошлого ката ═══════════════════════════════════════════════════════════════════════════════
def _tc_val(tok: str):
    """→ (секунды при чтении M:SS / H:MM:SS, левое число, правое число)"""
    m = re.match(r'(\d{1,4}):(\d{2})(?::(\d{2}))?', tok)
    a, b, c = int(m.group(1)), int(m.group(2)), m.group(3)
    return (a * 3600 + b * 60 + int(c), a, int(c)) if c is not None else (a * 60 + b, a, b)


def decode_tc(tok: str, duration: float):
    """'10:57' → (657.0, False); битое «секунды:минуты» '2449:40' → (2449.0, True); не лезет в кат → (None, True)"""
    sec, left, right = _tc_val(tok)
    if sec <= duration and right < 60:
        return float(sec), False
    if left <= duration:
        return float(left), True
    return None, True


def fix_tc(item: dict, duration: float):
    """→ (секунды пункта в прошлом кате, признак «таймкод был битым»). tc_range первым (в нём таймкоды верные и
    перечислены все места пункта: «40:49–40:51 · 42:20–42:31» → [2449, 2540]); если он пуст — v1_tc, где «2449:40»
    читается как секунды:минуты. Всё, что длиннее ката, отбрасывается."""
    secs, fixed = [], False
    for m in TC_SPAN_RE.finditer(str(item.get('tc_range') or '')):
        v, bad = decode_tc(m.group(1), duration)
        fixed = fixed or bad
        if v is not None and not bad and v not in secs:
            secs.append(v)
    v1 = TC_RE.search(str(item.get('v1_tc') or ''))
    if v1:
        v, bad = decode_tc(v1.group(0), duration)
        fixed = fixed or bad
        if not secs and v is not None:
            secs.append(v)
        elif secs and not bad and v != secs[0] and _tc_val(v1.group(0))[1] == int(secs[0]):
            fixed = True                                   # «7:00» при tc_range «0:07–0:09»: та же поломка, секунд < 60
    return secs, fixed


class Projector:
    """время прошлого ката → время нового по bases[<база>].cut_map (спаны {base_t0, base_t1, cut_t0, cut_t1}).
    Внутри спана — линейно, погрешность = половина расхождения сдвигов на краях спана; между спанами — сдвиг
    ближайшего края (gap); на действительно выпавшем куске — dropped; вне спанов — none."""

    def __init__(self, base: dict):
        self.base = base or {}
        self.spans = sorted(self.base.get('cut_map') or [], key=lambda s: s['base_t0'])
        self.dropped = TD.real_dropped(self.base)
        self.t0 = self.spans[0]['base_t0'] if self.spans else 0.0
        self.t1 = max((s['base_t1'] for s in self.spans), default=0.0)

    def shift(self, sec: float) -> float:
        return TD.shift_near(self.spans, sec)

    def project(self, sec) -> dict:
        if sec is None or not self.spans or sec < self.t0 or sec > self.t1:
            return dict(sec_new=None, err=None, how='none')
        sec = float(sec)
        for u in self.dropped:
            if float(u['t0']) <= sec <= float(u['t1']):
                return dict(sec_new=round(float(u['t0']) + self.shift(float(u['t0'])), 1),
                            err=round(float(u['t1']) - float(u['t0']), 1), how='dropped')
        inside = [s for s in self.spans if s['base_t0'] <= sec <= s['base_t1']]
        if inside:
            s = max(inside, key=lambda x: x.get('words') or 0)
            off0, off1 = s['cut_t0'] - s['base_t0'], s['cut_t1'] - s['base_t1']
            k = (sec - s['base_t0']) / ((s['base_t1'] - s['base_t0']) or 1.0)
            return dict(sec_new=round(sec + off0 + (off1 - off0) * k, 1), err=round(abs(off1 - off0) / 2, 1), how='span')
        prev = max((s for s in self.spans if s['base_t1'] < sec), key=lambda x: x['base_t1'])
        nxt = min((s for s in self.spans if s['base_t0'] > sec), key=lambda x: x['base_t0'])
        o_prev, o_next = prev['cut_t1'] - prev['base_t1'], nxt['cut_t0'] - nxt['base_t0']
        off = o_prev if sec - prev['base_t1'] <= nxt['base_t0'] - sec else o_next
        return dict(sec_new=round(sec + off, 1), err=round(abs(o_next - o_prev) / 2, 1), how='gap')


def retime_text(line: str, projector: Projector, duration: float) -> str:
    """каждый таймкод строки прошлого ТЗ → время нового ката; «≈» — место найдено примерно (погрешность > 2 с,
    стык кусков или край фильма). Таймкод, который не лезет в прошлый кат даже после декода, убирается."""
    old_max = max(projector.t1 + 120, 1.0) if projector.spans else duration

    def one(tok):
        v, _ = decode_tc(tok, old_max)
        if v is None:
            return None, True
        p = projector.project(v)
        if p['sec_new'] is None:                           # вне сверенной речи: сдвиг ближайшего куска, примерно
            sn, rough = v + projector.shift(v), True
        else:
            sn, rough = p['sec_new'], (p['err'] or 0) > 2 or p['how'] != 'span'
        return min(max(sn, 0.0), duration), rough

    def repl(m):
        if foreign_tc(line, m, hms_ok=duration >= 3600):
            return m.group(0)                              # адрес в исходнике, не время ката
        a, ra = one(m.group(1))
        b, rb = one(m.group(2)) if m.group(2) else (None, False)
        if a is None:
            return ''
        lead = ' ' if m.group(0)[:1].isspace() else ''
        s = ('≈' if (ra or rb) else '') + tc_str(a)
        if b is not None and int(round(b)) > int(round(a)):
            s += '–' + tc_str(b)
        return lead + s

    out = TC_SPAN_RE.sub(repl, line)
    return squash(_punct(out)).rstrip(' @')


def visible_tc_too_long(rows, duration) -> list:
    """проверка гейта: таймкоды видимого текста, которые длиннее ката"""
    bad = []
    for r in rows:
        for k, lines in (r.get('parts') or {}).items():
            for ln in lines:
                for m in TC_SPAN_RE.finditer(ln):
                    if foreign_tc(ln, m, hms_ok=duration >= 3600):
                        continue
                    for tok in (m.group(1), m.group(2)):
                        if tok and _tc_val(tok)[0] > duration:
                            bad.append((r['label'], k, tok))
    return bad


# ═══ 4. сборка строк ═════════════════════════════════════════════════════════════════════════════════════════
def _flatten(block) -> list:
    """parts.* современного ТЗ: строки или {h, items} → плоский список строк"""
    out = []
    for d in block or []:
        if isinstance(d, dict):
            if d.get('h'):
                out.append(str(d['h']))
            out += [str(x) for x in (d.get('items') or [])]
        elif str(d).strip():
            out.append(str(d))
    return out


def _first_action(do_lines) -> str:
    """действие для первого экрана: первое предложение ✅, начинающееся с глагола; иначе первое предложение без
    таймкода в начале. Длинное режется по границе части фразы («;», «—», «,»), скобка и кавычка не остаются открытыми."""
    cand = [re.sub(rf'^[≈~]?{TC}(?:\s*[–—-]\s*{TC})?\s*▸\s*', '', x).strip() for x in do_lines or []]
    sents = [re.sub(r'^[\s⚠️✅•·-]+', '', x) for c in cand if c for x in _sentences(c)]
    sents = [x for x in sents if x]
    pick = next((x for x in sents if INF_RE.match(x)), '') or next((x for x in sents if not LINE_TC_START.match(x)), '') \
        or (sents[0] if sents else '')
    # таймкод места на первом экране стоит перед строкой — скобка с ним в тексте действия лишняя
    pick = re.sub(rf'\s*\(\s*[≈~]?{TC}(?:\s*[–—-]\s*[≈~]?{TC})?\s*\)', '', pick)
    if len(pick) > 140:
        head = pick[:140]
        if _in_quote(head, len(head)):                     # обрыв внутри цитаты: недосказанную цитату не закрываем кавычкой,
            head = head[:head.rfind('«')]                  # а снимаем целиком вместе со связкой перед ней
            pick = re.sub(r'[\s,;:—–-]+(?:и|или|а|до|от|по|на)?\s*$', '', head)
        else:
            k = max((i for i in (head.rfind(';'), head.rfind(' — '), head.rfind(',')) if not _in_quote(head, i)), default=-1)
            pick = head[:k] if k >= 60 else head.rsplit(' ', 1)[0]
    if pick.count('(') > pick.count(')'):
        pick = pick[:pick.rfind('(')]
    pick = pick.rstrip(' ,;:—-.')
    if pick.count('«') > pick.count('»'):
        pick += '»'
    return pick


def _is_blur(title, do_elems) -> bool:
    """блюр/кроп/обезличивание — работа монтажёра уже сейчас, если действие не поставлено в зависимость от ответа
    фонда («если фонд откажет — блюр» = ждём фонд)"""
    text = squash(title) + '. ' + ' '.join(' '.join(el) for el in do_elems or [])
    for sent in re.split(r'(?<=[.!?;])\s+|\s·\s', text):
        if BLUR_RE.search(sent) and not COND_RE.search(sent):
            return True
    return False


def load_patterns(P) -> list:
    """темы фонда — sensitivity.patterns профиля канала (+ risk_patterns карточки), по образцу risk_registry"""
    raw = list(P.profile('sensitivity.patterns') or []) + list(P.get('risk_patterns') or [])
    pats = []
    for i, r in enumerate(raw):
        try:
            pats.append(dict(key=r.get('key', f'p{i}'), rx=re.compile(r['rx']), topic=r.get('topic') or r.get('key', '')))
        except (re.error, KeyError, TypeError):
            continue
    return pats


def topic_of(text: str, patterns: list):
    """тема по максимуму попаданий шаблонов в нормализованном тексте → (key, title) или (None, None)"""
    n = re.sub(r'[^a-zа-я0-9]+', ' ', str(text or '').lower().replace('ё', 'е'))
    best, best_n = None, 0
    for p in patterns or []:
        k = len(p['rx'].findall(n))
        if k > best_n:
            best, best_n = p, k
    if not best:
        return None, None
    t = best['topic']
    return best['key'], t[:1].upper() + t[1:]


def _frame(cut, sec, what):
    return dict(file=f'work/{cut}/hires/h{int(sec) + 1:04d}.jpg', sec=int(sec), what=what)


def int_set(v) -> set:
    """ключ карточки feedback_sensitive_extra: список [86, 97], строка «86,97» (так приходит из env) или число"""
    if v is None or v == '':
        return set()
    if isinstance(v, (list, tuple, set)):
        v = ','.join(str(x) for x in v)
    return {int(x) for x in re.findall(r'\d+', str(v))}


NOW_LEAD_RE = re.compile(r'^(?:Сейчас|Пока что|На данный момент)\s', re.I)


def do_without_now(do_lines: list, now_lines: list):
    """✅ — действие, а не пересказ ❌. Предложение ✅, которое начинается с «Сейчас …» либо почти дословно повторяет
    ❌ (и само не начинается с глагола-действия), в видимый текст не идёт — если в блоке остаётся хоть одно другое.
    → (строки, сколько строк ушло целиком)"""
    now_text = ' '.join(now_lines or [])
    sents = [(i, x) for i, ln in enumerate(do_lines or []) for x in _sentences(ln)]

    def echo(x):
        body = re.sub(rf'^[≈~]?{TC}(?:\s*[–—-]\s*[≈~]?{TC})?\s*▸?\s*', '', x)
        if INF_RE.match(body) or body[:1] in '«⚠' or '«' in body or '→' in body:
            return False                                    # цитаты у ❌ и ✅ общие по делу («Стык: «…» → «…»»)
        return bool(NOW_LEAD_RE.match(body)) or (len(TD.sig_words(body)) >= 3 and stem_score(body, now_text) >= 0.7)
    keep = [(i, x) for i, x in sents if not echo(x)]
    if not keep or len(keep) == len(sents):
        return list(do_lines or []), 0
    out = [' '.join(x for j, x in keep if j == i) for i in range(len(do_lines))]
    return [x for x in out if x], sum(1 for x in out if not x)


ID_RE = re.compile(r'\b[AX]\d{1,2}-\d{2}\b')


def id_map(items) -> dict:
    """внутренний номер заметки прошлого ТЗ («A4-12») → n пункта, в чьём поле ids он стоит (первый)"""
    out = {}
    for n, it in enumerate(items or [], 1):
        for i in (it.get('ids') or []) if isinstance(it, dict) else []:
            out.setdefault(str(i), n)
    return out


def map_ids(line: str, idmap: dict, own: int, prev_label='') -> str:
    """«Если по A4-12 выбран вариант А» → «Если по ТЗ-63 · v4 выбран вариант А»: без замены чистка жаргона
    оставляла обрубок «Если по выбран…». Ссылка пункта на самого себя и неизвестный номер остаются чистке."""
    def repl(m):
        k = (idmap or {}).get(m.group(0))
        if not k or k == own:
            return m.group(0)
        lab = i18n.tz_label(k)
        return i18n.T('fb.num_prev', label=lab, prev=prev_label) if prev_label else lab
    line = str(line or '')
    # «(X2-06, X2-09)», «…, см. A2-08)» — справочная отсылка в конце фразы: её, как и раньше, снимает чистка
    keep = [m.span() for m in re.finditer(r'\((?:\s*(?:см\.)?\s*[AX]\d{1,2}-\d{2}\s*,?)+\)|см\.\s*[AX]\d{1,2}-\d{2}(?:\s*,\s*[AX]\d{1,2}-\d{2})*', line)]
    out = ID_RE.sub(lambda m: m.group(0) if any(a <= m.start() < b for a, b in keep) else repl(m), line)
    labs = r'ТЗ-\d+(?: · v\d+)?'
    return re.sub(rf'({labs})(?:(\s*(?:,|и)\s*)\1)+', r'\1', out)      # «A8-02 и A8-04» одного пункта — один номер


def row_part2(n, item, f, proj, duration, old_duration, cut, prev_label, patterns, sensitive_extra=False,
              idmap=None) -> dict:
    parts_raw = split_nado(item.get('nado'))
    if idmap:                                              # только видимый текст; проверка «без потерь» идёт по исходнику
        parts_raw = {k: [[map_ids(ln, idmap, n, prev_label) for ln in el] for el in v] for k, v in parts_raw.items()}
    secs_old, fixed = fix_tc(item, old_duration)
    pr = [proj.project(s) for s in secs_old]
    secs_new = [p['sec_new'] for p in pr if p['sec_new'] is not None]
    main = next((p for p in pr if p['sec_new'] is not None), pr[0] if pr else dict(sec_new=None, err=None, how='none'))
    flagged = bool(item.get('sensitive', {}).get('flag') if isinstance(item.get('sensitive'), dict)
                   else item.get('sensitive'))
    # неявно чувствительное: флага в прошлом ТЗ нет, номер назван в карточке (feedback_sensitive_extra)
    sensitive = flagged or bool(sensitive_extra)
    sensitive_by = 'prev' if flagged else ('card' if sensitive_extra else None)
    v = TD.judge_v2(dict(item, sensitive=sensitive), parts_raw, f, secs_new,
                    project=lambda s: proj.project(s)['sec_new'], prev_label=prev_label, secs_old=secs_old)

    def rt(ln):
        return retime_text(ln, proj, duration)
    vis, more = {}, 0
    for k in ('now', 'do', 'where'):
        vis[k], extra = visible_block(parts_raw.get(k), k, rt)
        more += extra
    more += sum(len(el) for el in parts_raw.get('list') or [])

    vis['do'], cut_do = do_without_now(vis['do'], vis['now'])
    more += cut_do

    sec_new = main['sec_new']
    frame = None
    if v['status'] == 'closed' and (v.get('evidence') or {}).get('kind') == 'screen' and v['evidence'].get('sec') is not None:
        frame = _frame(cut, v['evidence']['sec'] + 1, f'кадр ката {cut}')      # карточка: секунда после появления
    elif sec_new is not None:
        frame = _frame(cut, sec_new, f'кадр ката {cut}')
    title = heal_title(clean_title(item.get('title'), retime=rt), item.get('title') or '',
                       [y for k in ('now', 'do') for el in parts_raw.get(k) or [] for ln in el
                        for y in (squash(heal(ln)), rt(squash(heal(ln))))])
    row = dict(part=2, n=n, label=i18n.tz_label(n), key=str(item.get('key') or ''), title=title,
               category=item.get('category') or '', severity=item.get('severity') or '', sensitive=sensitive,
               blocker=False, sec_old=secs_old[0] if secs_old else None,
               tc_old=tc_str(secs_old[0]) if secs_old else '', sec_new=sec_new,
               tc_new=tc_str(sec_new) if sec_new is not None else '', err=main['err'], how=main['how'],
               tc_fixed=fixed, parts=vis, more=more, status=v['status'], status_by=v['by'], evidence=v['evidence'],
               checks=v['checks'], bucket='', dup_of=None, topic=None, topic_title=None, frame=frame, typo=[],
               agent_note='', sensitive_by=sensitive_by, do_derived=False, see_n=None)
    row['_rule'] = v['rule'] if (f.checks.get(v['rule']) or {}).get('status') == 'fail' else ''
    row['_do_els'] = [[x for x in (rt(ln) for ln in clean_lines(el, safe=True)) if x] for el in (parts_raw.get('do') or []) if el]
    row['_do_raw'] = ' '.join(ln for el in (parts_raw.get('do') or []) for ln in el)
    row['_blur'] = sensitive and _is_blur(item.get('title'), (parts_raw.get('do') or [])[:1])   # судим по видимому ✅
    if sensitive:
        key, ttl = topic_of(' '.join([str(item.get('title') or '')] + [' '.join(el) for k in ('now', 'do')
                                                                        for el in parts_raw.get(k) or []]), patterns)
        row['topic'], row['topic_title'] = key or 'other', ttl or TD._t('fb.topic_other', 'Прочие согласования')
    return row


def row_part1(n, p, checks, cut, review_dir) -> dict:
    text_all = ' '.join(str(p.get(k) or '') for k in ('title', 'est'))     # правило названо в самом требовании
    rule = next((r for r in checks if r in text_all), '') or TD.bound_rule(p.get('title'), checks)[0]
    rule = rule if (checks.get(rule) or {}).get('status') == 'fail' else ''
    parts_src = p.get('parts') or {}
    if not parts_src:
        raw = split_nado(p.get('nado'))
        parts_src = {k: (raw[k][0] if raw[k] else []) for k in ('now', 'do', 'where')}
    vis, lost = {}, 0
    for k in ('now', 'do', 'where'):
        vis[k], extra = visible_block([_flatten(parts_src.get(k))], k)
        lost += extra
    has_tc = p.get('timeline_in_sec') is not None or TC_RE.search(str(p.get('tc_range') or '') + ' ' + str(p.get('v1_tc') or ''))
    sec = float(p['_sec']) if has_tc and p.get('_sec') is not None else None
    frame = None
    if p.get('_frame') and (sec is not None or Path(p['_frame']).parent.name != 'hires'):   # без времени кадр «нулевой секунды» не нужен
        try:
            rel = str(Path(p['_frame']).resolve().relative_to(Path(review_dir).resolve()))
        except ValueError:
            rel = str(p['_frame'])
        frame = dict(file=rel, sec=int(sec) if sec is not None else None, what=f'кадр ката {cut}')
    elif sec is not None:
        frame = _frame(cut, sec, f'кадр ката {cut}')
    ev = None
    if rule:
        c = checks[rule]
        ev = TD._ev('rule', TD.tc_start({'v1_tc': c.get('tc')}), TD.rule_text(rule, c))
    typo = [t for t in (p.get('typo') or []) if isinstance(t, dict) and t.get('was') and t.get('now')]
    title1 = heal_title(clean_title(p.get('_title') or p.get('title')), p.get('_title') or p.get('title') or '',
                        [x for k in ('now', 'do') for x in _flatten(parts_src.get(k))])
    row = dict(part=1, n=n, label=i18n.tz_label(n), key=str(p.get('key') or ''), title=title1,
               category=p.get('category') or '', severity=p.get('severity') or '', sensitive=bool(p.get('_sensitive')),
               blocker=bool(rule) or (p.get('class') in ('fact', 'typo', 'mismatch')),
               sec_old=None, tc_old='', sec_new=sec, tc_new=tc_str(sec) if sec is not None else '', err=0.0,
               how='native' if sec is not None else 'none', tc_fixed=False, parts=vis,
               more=len(_flatten(parts_src.get('list'))) + lost,
               status='new', status_by='rule' if rule else 'code', evidence=ev, checks=[], bucket='new', dup_of=None,
               topic=None, topic_title=None, frame=frame, typo=typo, agent_note='', sensitive_by=None, do_derived=False,
               see_n=None)
    row['_rule'] = rule
    return row


# ── частично выполненные пункты: первый экран и первая строка ✅ говорят о НЕДОСТАЮЩЕМ ──────────────────────
def is_partial(row: dict) -> bool:
    """пункт с проверками по экрану, где часть целей найдена, а часть нет («главы 13 из 13; подглавы 0 из 17»)"""
    ch = row.get('checks') or []
    return (row.get('part') == 2 and row.get('status') == 'open' and (row.get('evidence') or {}).get('kind') == 'screen'
            and any(c.get('found') for c in ch) and any(not c.get('found') for c in ch))


def check_groups(row: dict) -> list:
    """[(имя группы, проверки)] — имена и размеры групп из доказательства («главы — 13 из 13; подглавы — 0 из 17»),
    сами проверки — из checks по порядку. Не сошлось по числу — одна безымянная группа."""
    checks = row.get('checks') or []
    found = re.findall(r'([^;:«»]+?)\s+—\s+(\d+)\s+из\s+(\d+)', (row.get('evidence') or {}).get('text') or '')
    if found and sum(int(n) for _, _, n in found) == len(checks):
        out, i = [], 0
        for name, _, n in found:
            out.append((squash(name).lower(), checks[i:i + int(n)]))
            i += int(n)
        return out
    return [('', checks)]


def missing_line(row: dict, limit=MAX_LINE) -> str:
    """«Добавить недостающее: подглавы — 0 из 17: «…», «…», «…» и ещё 14» — только из checks, без новых фактов;
    ≤3 названий на группу, затем счётчик; строка не длиннее limit"""
    line = ''
    for top in (3, 2, 1, 0):
        segs = []
        for name, part in check_groups(row):
            miss = [squash(c.get('q')).strip('«»') for c in part if not c.get('found')]
            if not miss:
                continue
            head = f'{name} — ' if name else ''
            names = ', '.join(f'«{q}»' for q in miss[:top])
            rest = len(miss) - min(top, len(miss))
            tail = (TD._t('fb.do_more', ' и ещё {n}', n=rest) if names else TD._t('fb.do_more_only', 'нет {n}', n=rest)) if rest else ''
            segs.append(f'{head}{len(part) - len(miss)} из {len(part)}: {names}{tail}')
        line = TD._t('fb.do_missing', 'Добавить недостающее: ') + '; '.join(segs)
        if len(line) <= limit:
            break
    return line


def _stem(name: str) -> str:
    w = re.sub(r'[аеёиоуыэюяйь]+$', '', (squash(name).split() or [''])[0].lower())
    return w if len(w) >= 4 else ''


def _clauses(s: str) -> list:
    """части фразы по «;» вне цитат и скобок"""
    out, cur = [], ''
    for ch in s:
        if ch == ';' and cur.count('«') == cur.count('»') and cur.count('(') == cur.count(')'):
            out.append(cur)
            cur = ''
        else:
            cur += ch
    return [x.strip() for x in out + [cur] if x.strip()]


def clause_done(clause: str, groups: list, f) -> bool:
    """эта часть ✅ уже выполнена в новом кате? Да — если её цитаты стоят на экране (остальные цитаты — реплики-якоря
    из речи), либо цитат нет, а названа только полностью найденная группа («13 карточек глав» при «главы 13 из 13»).
    Часть, где названа недостающая группа или недостающая цитата, выполненной не считается никогда."""
    low = clause.lower()
    full = [_stem(n) for n, part in groups if n and all(c.get('found') for c in part)]
    lack = [_stem(n) for n, part in groups if n and not all(c.get('found') for c in part)]
    if any(st and re.search(rf'(?<![а-яё]){re.escape(st)}', low) for st in lack):
        return False
    missing = [c.get('q') or '' for _, part in groups for c in part if not c.get('found')]
    qs = TD._quotes_in([clause])
    if any(TD.match(q, m)[0] >= TD.SURE or TD.match(m, q)[0] >= TD.SURE for q in qs for m in missing):
        return False
    if qs and f is not None:
        shown = [q for q in qs if any(h['score'] >= TD.SURE for h in f.screen_hits(q))]
        said = [q for q in qs if q not in shown and (f.speech_hit(q) or {}).get('score', 0) >= TD.SURE]
        return bool(shown) and len(shown) + len(said) == len(qs)
    return not qs and any(st and re.search(rf'(?<![а-яё]){re.escape(st)}', low) for st in full)


def _same_stem(w: str, t: str) -> bool:
    """одно слово в разных падежах: «фонда» ~ «фонд», «Панфиловой» ~ «Панфилова»; «Жимагул» и «Жумагул» — разные"""
    if w == t:
        return True
    k = 0
    for a, b in zip(w, t):
        if a != b:
            break
        k += 1
    return min(len(w), len(t)) >= 4 and abs(len(w) - len(t)) <= 3 and k >= max(4, min(len(w), len(t)) - 2)


def stem_score(q: str, text: str) -> float:
    qs = TD.sig_words(q)
    tw = TD.norm2(text).split()
    return (sum(1 for w in qs if any(_same_stem(w, t) for t in tw)) / len(qs)) if qs else 0.0


def alt_spelling(row: dict, f) -> int:
    """цель «не найдена», хотя стоит на экране в другом падеже или с другой пунктуацией («Жимагул Панфилова, куратор
    фонда» при экране «ЖИМАГУЛ ПАНФИЛОВА | куратор по семьям • фонд …»): считаем найденной (check.alt=true), счётчики
    и список «нет: …» в доказательстве пересобираются. Статус пункта от этого не меняется — остальных целей нет."""
    if f is None:
        return 0
    groups = check_groups(row)
    n_alt = 0
    for c in row.get('checks') or []:
        q = c.get('q') or ''
        if c.get('found') or float(c.get('score') or 0) < TD.MAYBE or len(TD.sig_words(q)) < TD.MIN_SIG:
            continue
        for h in f.screen_hits(q):
            e = h['e']
            sc = stem_score(q, f._screen_text(e))
            if sc >= TD.SURE and not f.was_there(q, e):
                c.update(found=True, alt=True, score=round(sc, 2), tc=e.get('tc') or tc_str(e.get('t0') or 0))
                n_alt += 1
                break
    ev = row.get('evidence') or {}
    if n_alt and all(name for name, _ in groups):
        txt = TD._t('fb.ev.on_screen_counts', 'на экране есть: {what}',
                    what='; '.join(f'{name} — {sum(1 for c in part if c.get("found"))} из {len(part)}' for name, part in groups))
        miss = [c.get('q') or '' for _, part in groups for c in part if not c.get('found')]
        if miss:
            txt += TD._t('fb.ev.missing', '; нет: {what}', what=', '.join(f'«{TD._cut(m, 40)}»' for m in miss[:3]))
        ev['text'] = txt
    return n_alt


def partial_now(row: dict) -> str:
    """❌ частично выполненного пункта — по фактам нового ката, а не цитатой прошлого ТЗ («в кате нет ни титула, ни
    одной карточки главы» — уже неправда): «Сделано: главы — 13 из 13. Не хватает: подглавы — 16 из 17.»"""
    done, lack = [], []
    for name, part in check_groups(row):
        k = sum(1 for c in part if c.get('found'))
        head = f'{name} — ' if name else ''
        if k:
            done.append(f'{head}{k} из {len(part)}')
        if k < len(part):
            lack.append(f'{head}{len(part) - k} из {len(part)}')
    out = []
    if done:
        out.append(TD._t('fb.now_done', 'Сделано: {what}.', what='; '.join(done)))
    if lack:
        out.append(TD._t('fb.now_lack', 'Не хватает: {what}.', what='; '.join(lack)))
    return ' '.join(out)


CAPTION_RE = re.compile(r'подпис|титр|плашк', re.I)
NAME_TC_RE = re.compile(r'((?:[А-ЯЁ][а-яё]+\s+){0,2}[А-ЯЁ][а-яё]+)\s*\(\s*[≈~]?(' + TC + r')\s*\)')


def _caption_on_screen(name: str, sec: float, f, win=45.0) -> bool:
    ws = [w for w in TD.norm2(name).split() if len(w) >= 4]
    for e in (getattr(f, 'screens', None) or []):
        if abs(float(e.get('t0') or 0) - sec) <= win:
            tw = TD.norm2(f._screen_text(e)).split()
            if ws and all(any(_same_stem(w, t) for t in tw) for w in ws):
                return True
    return False


def drop_done_captions(clause: str, f) -> str:
    """«добавить подписи Светланы (1:29) и Жимагул Панфиловой (≈11:10), хронологический титр»: подписи с этими
    именами уже стоят на экране рядом с названным временем → остаётся «Добавить хронологический титр». Часть
    перечисления убирается, только если на экране найдены ВСЕ её имена; глагол берётся из начала той же фразы."""
    if f is None or not CAPTION_RE.search(clause) or not NAME_TC_RE.search(clause):
        return clause
    segs = [x.strip() for x in re.split(r',\s+(?![^«]*»)(?![^(]*\))', clause) if x.strip()]
    keep = []
    for seg in segs:
        pairs = list(NAME_TC_RE.finditer(seg))
        if pairs and all(_caption_on_screen(m.group(1), _tc_val(m.group(2))[0], f) for m in pairs):
            continue
        keep.append(seg)
    if len(keep) == len(segs):
        return clause
    if not keep:
        return ''
    verb = INF_RE.match(segs[0])
    if verb and keep[0] is not segs[0] and not _VERB_RE.search(keep[0]):
        keep[0] = f'{verb.group(0)} {keep[0]}'
    return ', '.join(keep)


def _undone(els, groups, f, skip=None) -> list:
    """строки всех кусков ✅ без уже выполненных частей (и без предложений, подходящих под skip)"""
    out = []
    for el in els or []:
        for ln in el:
            sents = []
            for sent in _sentences(ln):
                if skip is not None and skip.search(sent):
                    continue
                keep = [c for c in _clauses(sent) if not clause_done(c, groups, f)]
                keep = [c for c in (drop_done_captions(c, f) for c in keep) if c]
                if keep:
                    sents.append('; '.join(keep))
            ln2 = squash(_punct(' '.join(sents)))
            if ln2 and not BARE_TC_RE.match(ln2):
                out += fit(_cap(ln2))[0]
    return out


def partial_pass(part2: list, f, prev_label='') -> None:
    """А: у частично выполненного пункта первая строка ✅ — недостающее, выполненные строки ✅ уходят в more.
    Пункт, чей ✅ сам отсылает к такому пункту («Полный список — ТЗ-01»), получает see_n: свои невыполненные части
    + короткая строка-отсылка; на первом экране такое требование стоит один раз — у пункта, на который ссылаются."""
    for a in [r for r in part2 if is_partial(r)]:
        alt_spelling(a, f)
        if not is_partial(a):
            continue
        groups = check_groups(a)
        kept = _undone(a.get('_do_els'), groups, f)
        before = len(a['parts'].get('do') or [])
        a['parts']['do'] = [missing_line(a)] + kept
        a['more'] = max(0, int(a.get('more') or 0) + before - len(kept))
        now_line = partial_now(a)
        if now_line:                                       # ❌ — по фактам нового ката; цитата прошлого ТЗ уходит в more
            a['more'] += len(a['parts'].get('now') or [])
            a['parts']['now'] = [now_line]
        found_q = [c.get('q') or '' for c in a.get('checks') or [] if c.get('found')]
        where = a['parts'].get('where') or []
        stay = [ln for ln in where if not any(TD.match(q, fq)[0] >= TD.SURE or TD.match(fq, q)[0] >= TD.SURE
                                              for q in TD._quotes_in([ln]) for fq in found_q)]
        a['more'] += len(where) - len(stay)                # 📍 про уже поставленную карточку — не место недостающего
        a['parts']['where'] = stay
        ref = re.compile(rf'ТЗ-0*{a["n"]}(?!\d)')
        for b in part2:
            if b is a or b.get('see_n') or is_partial(b) or b['status'] == 'closed' or b['sensitive'] \
                    or not ref.search(b.get('_do_raw') or ''):
                continue
            kept_b = _undone(b.get('_do_els'), groups, f, skip=ref)
            before = len(b['parts'].get('do') or [])
            label = i18n.T('fb.num_prev', label=i18n.tz_label(a['n']), prev=prev_label) if prev_label else i18n.tz_label(a['n'])
            b['parts']['do'] = kept_b + [TD._t('fb.do_see', 'Полный список недостающего — {label}', label=label)]
            b['more'] = max(0, int(b.get('more') or 0) + before - len(kept_b))
            b['see_n'] = a['n']
            if now_line:                                   # его ❌ описывал тот же прошлый кат («ни титула, ни карточек»)
                b['more'] += len(b['parts'].get('now') or [])
                b['parts']['now'] = [now_line]


def ensure_do(part2: list) -> None:
    """Г: у каждого пункта, который печатается полным блоком (block / open / blur без dup_of), есть ≥1 строка ✅.
    Если в исходном пункте ✅ не было вовсе — «Исправить: <заголовок>» (без новых фактов), пометка do_derived."""
    for r in part2:
        r.setdefault('do_derived', False)
        if r.get('bucket') in ('block', 'open', 'blur') and r.get('dup_of') is None and not (r['parts'].get('do') or []):
            r['parts']['do'] = fit(TD._t('fb.do_derived', 'Исправить: {what}', what=squash(r.get('title')).rstrip('.')))[0][:1]
            r['do_derived'] = True


def link_and_bucket(part1: list, part2: list):
    """dup_of, blocker, bucket — строго по контракту §4 (вызывается и после вливания вердиктов агента)"""
    for r in part2:
        r['dup_of'] = None
        if r['status'] != 'closed' and not r['sensitive']:
            same_rule = [q for q in part1 if r.get('_rule') and q.get('_rule') == r['_rule']]
            near = [q for q in part1 if q['category'] == r['category'] and q['sec_new'] is not None
                    and r['sec_new'] is not None and abs(q['sec_new'] - r['sec_new']) <= 60]
            if same_rule:
                r['dup_of'] = same_rule[0]['n']
            elif near:
                r['dup_of'] = min(near, key=lambda q: abs(q['sec_new'] - r['sec_new']))['n']
        r['blocker'] = r['status'] != 'closed' and not r['sensitive'] and (
            bool(r.get('_rule')) or (r['severity'] == 'must' and r['dup_of'] is None))
        if r['status'] == 'closed':
            r['bucket'] = 'closed'
        elif r['sensitive']:
            r['bucket'] = 'blur' if r.get('_blur') else 'fund'
            if r['bucket'] == 'blur' and r['status'] == 'fund':
                r['status'] = 'open'                       # блюр фонда не ждёт — это работа монтажёра (status_by=flag)
        elif r['blocker']:
            r['bucket'] = 'block'
        elif r['status'] == 'unknown':
            r['bucket'] = 'appendix'
        else:
            r['bucket'] = 'open'


def _blocker_tc(r: dict):
    """→ (таймкод для первого экрана, секунды для порядка). У пункта без места в новом кате (начало прошлого ката
    вырезано) берётся таймкод из его видимой строки 📍; нет и там — строка идёт без таймкода, это честно."""
    if r.get('tc_new'):
        return r['tc_new'], r.get('sec_new')
    for ln in (r.get('parts') or {}).get('where') or []:
        for m in cut_spans(ln):
            tok = re.sub(r'[.,]\d+$', '', m.group(1))
            rough = '≈' if m.group(0).lstrip()[:1] in '≈~' else ''
            return rough + tok, float(_tc_val(tok)[0])
    return '', None


def _blocker_do(r: dict) -> str:
    do = (r.get('parts') or {}).get('do') or []
    if do and do[0].startswith(TD._t('fb.do_missing', 'Добавить недостающее: ')):
        return do[0]                                       # частично выполненный пункт: недостающее целиком, ≤240
    return _cap(_first_action(do) or r['title'])             # «отодвинуть вход фонда…» → с заглавной, как остальные


def make_blockers(part1, part2, limit=8) -> list:
    """первый экран: «таймкод ▸ действие»; требование, перенесённое в Часть 1, считается один раз; пункт-отсылка
    (see_n) не печатается, пока блокером стоит пункт, на который он ссылается; одинаковая строка — один раз"""
    holds = {r['n'] for r in part2 if r['blocker'] and r['dup_of'] is None}
    rows = [r for r in part1 if r['blocker']] + [r for r in part2 if r['blocker'] and r['dup_of'] is None
                                                 and not (r.get('see_n') in holds and r.get('see_n') != r['n'])]
    # под лимит: сначала провалы правил канала, затем Часть 1, затем доказанное «осталось», непроверенное — последним
    rows.sort(key=lambda r: (0 if r.get('_rule') else 1, r['part'], 1 if r.get('status') == 'unknown' else 0,
                             -1 if r['sec_new'] is None else r['sec_new']))
    seen, uniq = set(), []
    for r in rows:
        k = (_blocker_tc(r)[0], squash(_blocker_do(r)).lower())   # то же действие в том же месте — одно требование
        if k not in seen:
            seen.add(k)
            uniq.append(r)

    def order(r):
        sec = _blocker_tc(r)[1]
        return (-1 if sec is None else sec, r['part'], r['n'])
    rows = sorted(uniq[:limit], key=order)
    return [dict(part=r['part'], n=r['n'], label=r['label'], tc=_blocker_tc(r)[0], do=_blocker_do(r)) for r in rows]


RULE_HUMAN = {'fund_entry_min': ('fb.rule.fund_entry_min', 'фонд входит раньше {thr}-й минуты'),
              'last_sound_rule': ('fb.rule.last_sound_rule', 'фильм кончается призывом о деньгах'),
              'teaser_rule': ('fb.rule.teaser_rule', 'тизер целиком из бед'),
              'fund_piece_max_sec': ('fb.rule.fund_piece_max_sec', 'непрерывный кусок фонда длиннее {thr} с')}
SNAKE_RE = re.compile(r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b')


def human_summary(lines, checks=None) -> list:
    """строки вердикта для читателя: служебные имена правил канала переводятся на человеческий («fund_entry_min» →
    «фонд входит раньше 34-й минуты»); строка, где после перевода остался служебный след, в модель не попадает"""
    def one(m):
        key = RULE_HUMAN.get(m.group(0))
        if not key:
            return m.group(0)
        thr = ((checks or {}).get(m.group(0)) or {}).get('threshold')
        if '{thr}' in key[1] and thr in (None, ''):
            return TD._t(key[0] + '_nothr', {'fund_entry_min': 'фонд входит слишком рано'}.get(m.group(0), m.group(0)))
        return TD._t(key[0], key[1], thr=thr) if '{thr}' in key[1] else TD._t(key[0], key[1])
    out = []
    for ln in lines or []:
        s = SNAKE_RE.sub(one, squash(ln))
        if s and not SNAKE_RE.search(s) and not JARGON_RE.search(s):
            out.append(s)
    return out


def tally_of(part1, part2) -> dict:
    b = [r['bucket'] for r in part2]
    return dict(new=len(part1), prev_total=len(part2), closed=b.count('closed'),
                open=b.count('open') + b.count('block'), blur=b.count('blur'), fund=b.count('fund'),
                unknown=b.count('appendix'))


def fund_topics_of(part2) -> list:
    cnt = {}
    for r in part2:
        if r['bucket'] == 'fund':
            k = r['topic'] or 'other'
            cnt.setdefault(k, dict(key=k, title=r['topic_title'] or '', count=0))['count'] += 1
    return sorted(cnt.values(), key=lambda x: (-x['count'], x['key']))


def rebucket(fb: dict) -> dict:
    """пересчёт buckets, блокеров, tally и тем фонда у УЖЕ записанной модели — после вливания вердиктов агента
    (контракт §6). Служебных признаков в файле нет, они восстанавливаются: блюр — по прежнему bucket (чувствительное
    агенту не уходит, признак не меняется); привязка к правилу канала — по доказательству вида rule, а если агент его
    заменил — по прежней паре blocker + dup_of (блокер с dup_of бывает только у провала правила)."""
    p1, p2 = fb.get('part1') or [], fb.get('part2') or []
    by_n = {r['n']: r for r in p1}

    def rule_id(r):
        ev = r.get('evidence') or {}
        if ev.get('kind') == 'rule':
            return ev.get('text') or 'rule'
        if r['part'] == 2 and r.get('blocker') and r.get('dup_of') in by_n:
            return rule_id(by_n[r['dup_of']]) or 'rule'
        return 'rule' if (r['part'] == 2 and r.get('blocker') and r.get('severity') != 'must') else ''
    for r in p1 + p2:
        r['_rule'] = rule_id(r)
        r['_blur'] = r.get('bucket') == 'blur'
    link_and_bucket(p1, p2)
    ensure_do(p2)
    fb.update(tally=tally_of(p1, p2), blockers=make_blockers(p1, p2), fund_topics=fund_topics_of(p2),
              part1=[_public(r) for r in p1], part2=[_public(r) for r in p2])
    return fb


def _public(r: dict) -> dict:
    return {k: v for k, v in r.items() if not k.startswith('_')}


def _sort_key(r):
    return (-1 if r['sec_new'] is None else r['sec_new'], r['n'])


# ═══ 5. build ════════════════════════════════════════════════════════════════════════════════════════════════
def find_prev(P, prev_path=None, prev_ver=''):
    """файл прошлого ТЗ: аргумент → карточка prev_pravki (env YTAI_PREV_PRAVKI) → архив → {prev}_review/"""
    cands = [prev_path, P.get('prev_pravki')]
    if prev_ver:
        cands += [f'pravki/archive/pravki_{prev_ver}.json', f'{prev_ver}_review/pravki_{prev_ver}.json']
    for c in cands:
        if c and Path(P.resolve(c)).exists():
            return str(c), Path(P.resolve(c))
    return '', None


def build(prev_path=None) -> dict:
    sys.path.insert(0, str(HERE.parent / 'stages'))
    from _bootstrap import P, W6, M, MOCK                  # карточка нужна только здесь
    import pravki_lib

    cut = P.CUT_VERSION
    against = P.get('align_against') or ''
    against = against[0] if isinstance(against, list) and against else against
    against_abs = P.resolve(against) if against else ''
    mv = re.search(r'_v(\d+)\.words', str(against))
    prev_ver = str(P.get('prev_cut_version') or (f'v{mv.group(1)}' if mv else ''))
    prev_scr = next((c for c in (Path(P.REVIEW_DIR) / 'work' / prev_ver / 'screens_v6.json',
                                 Path(P.REVIEW_DIR) / f'{prev_ver}_review' / 'screens.json') if prev_ver and c.exists()), None)
    f = TD.Facts(W6, P.WORDS, against_abs, prev_screens=prev_scr)
    duration = float(P.get('duration_sec') or f.duration or 0)
    old_duration = duration
    try:
        old_duration = float(json.load(open(against_abs, encoding='utf-8')).get('duration_sec') or duration)
    except Exception:                                      # noqa: BLE001  (слов прошлого ката рядом нет)
        pass
    proj = Projector(f.base)

    # Часть 1 — текущее ТЗ через общий загрузчик (сигнатура не меняется). Нет файла правок → часть пустая.
    part1, notes = [], []
    try:
        pravki, _ = pravki_lib.load_pravki(P, W6, M, MOCK)
    except SystemExit as ex:
        pravki, _ = [], None
        notes.append(f'Часть 1 пуста: {squash(ex)[:120]}')
    for i, p in enumerate(pravki, 1):
        if not p.get('_rejected'):
            part1.append(row_part1(i, p, f.checks, cut, P.REVIEW_DIR))

    # Часть 2 — прошлое ТЗ читается напрямую
    prev_file, prev_abs = find_prev(P, prev_path, prev_ver)
    part2, lossless_ok = [], 0
    if prev_abs:
        raw = json.loads(prev_abs.read_text(encoding='utf-8'))
        items = raw.get('all') if isinstance(raw, dict) else raw
        patterns = load_patterns(P)
        idmap = id_map(items)
        extra = int_set(P.get('feedback_sensitive_extra'))  # env YTAI_FEEDBACK_SENSITIVE_EXTRA=86,97
        for n, it in enumerate(items, 1):
            if it.get('status') == 'rejected':             # снятые Романом номера не сдвигают
                continue
            lossless_ok += 1 if lossless(it.get('nado')) else 0
            part2.append(row_part2(n, it, f, proj, duration, old_duration, cut, prev_ver, patterns, n in extra,
                                   idmap=idmap))
        unknown_extra = sorted(extra - {r['n'] for r in part2})
        if unknown_extra:
            notes.append(f'feedback_sensitive_extra: в прошлом ТЗ нет пунктов {unknown_extra}')
    else:
        notes.append('прошлого ТЗ нет (ключ prev_pravki) — Часть 2 пропущена')

    link_and_bucket(part1, part2)
    partial_pass(part2, f, prev_ver)
    ensure_do(part2)
    part1.sort(key=_sort_key)
    part2.sort(key=_sort_key)

    prev_no = 0
    try:
        prev_no = int(json.load(open(W6 / 'feedback.json', encoding='utf-8')).get('build_no') or 0)
    except Exception:                                      # noqa: BLE001
        pass
    summ = pravki_lib.load_summary(W6) or {}
    wanted = sorted({r['frame']['file'] for r in part1 + part2 if r.get('frame')})
    fb = dict(schema=SCHEMA, code=P.CODE, cut_version=cut, prev_cut_version=prev_ver,
              built_at=datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), build_no=prev_no + 1,
              duration_sec=duration, prev_file=prev_file,
              align=dict(base=f.base_tag, moved=f.moved, dropped_sec=f.dropped_sec,
                         coverage_pct=(f.base or {}).get('coverage_pct'), spans=len(proj.spans)),
              thresholds=dict(TD.THRESHOLDS), tally=tally_of(part1, part2),
              summary_lines=human_summary(summ.get('lines') or [], f.checks),
              blockers=make_blockers(part1, part2), fund_topics=fund_topics_of(part2), frames_wanted=wanted,
              part1=[_public(r) for r in part1], part2=[_public(r) for r in part2])
    fb['_stats'] = dict(lossless=f'{lossless_ok}/{len(part2)}', notes=notes)
    return fb


# ═══ 6. калибровка по эталону ════════════════════════════════════════════════════════════════════════════════
def calibrate(fb: dict, gold_path) -> int:
    """таблица ожидание/факт по gold. Критерий — ТОЧНОСТЬ «закрыто» = 100 %: ни одного closed, которого нет в
    эталоне как closed. Полноту добирает облачный сверщик, поэтому недобор здесь не ошибка."""
    gold = json.load(open(gold_path, encoding='utf-8'))
    exp = {int(g['n']): g for g in gold.get('items') or []}
    rows = {r['n']: r for r in fb['part2']}
    print(f'{"пункт":<8}{"ожидание":<16}{"факт":<10}{"кем":<6} итог   заголовок')
    bad = miss = 0
    for n in sorted(exp):
        g, r = exp[n], rows.get(n)
        ok_set = {g['expected_status'], *(g.get('also_ok') or [])}
        got = r['status'] if r else '—'
        verdict = 'ok' if got in ok_set else ('ЛОЖНОЕ' if got == 'closed' else 'недобор')
        bad += verdict == 'ЛОЖНОЕ'
        miss += verdict == 'недобор'
        print(f'{i18n.tz_label(n):<8}{"/".join(sorted(ok_set)):<16}{got:<10}{(r or {}).get("status_by", ""):<6} '
              f'{verdict:<7}{(r or g).get("title", "")[:60]}')
    closed = [r['n'] for r in fb['part2'] if r['status'] == 'closed' and r['status_by'] == 'code']
    stray = [n for n in closed if n not in exp or 'closed' not in {exp[n]['expected_status'], *(exp[n].get('also_ok') or [])}]
    print(f'\nкодовых «закрыто»: {len(closed)} {[i18n.tz_label(n) for n in closed]}')
    print(f'из них не подтверждены эталоном: {len(stray)} {[i18n.tz_label(n) for n in stray]}')
    print(f'точность «закрыто»: {(len(closed) - len(stray)) / len(closed):.0%}' if closed else 'точность «закрыто»: — (закрытых нет)')
    print(f'недобор (добирает сверщик): {miss}')
    tc_bad = 0
    for n, g in sorted(exp.items()):                       # у эталона может быть проверка восстановленного таймкода
        r = rows.get(n)
        if r and g.get('expected_evidence_null') and r.get('evidence') is not None:
            tc_bad += 1
            print(f'ДОКАЗАТЕЛЬСТВО {i18n.tz_label(n)}: ждали пустое, получили {r["evidence"]}')
        if r and 'expected_sec_old' in g and (r['sec_old'] != g['expected_sec_old'] or r['tc_fixed'] != g.get('expected_tc_fixed', r['tc_fixed'])):
            tc_bad += 1
            print(f'ТАЙМКОД {i18n.tz_label(n)}: ждали {g["expected_sec_old"]} с, получили {r["sec_old"]} (tc_fixed={r["tc_fixed"]})')
    return 1 if (bad or stray or tc_bad) else 0


# ═══ 7. самопроверка ═════════════════════════════════════════════════════════════════════════════════════════
def selftest() -> int:
    nado = ('❌ СЕЙЧАС · Фонд входит на 10:57 (21% фильма): Гуля 56 с рассказывает про обращение. Блок стоит между\n'
            '     выпуском (10:30–10:57) и возвратом в детдом\n'
            '     (11:53 «Это Валька»). Директива v2 #18 выполнена наоборот\n'
            '     (v2 38:39\n'
            '     → v4 11:37)\n'
            '❌ СЕЙЧАС · ❌ Гуля в кадре (VLM 11:08–11:40), кадр f0061\n'
            '✅ СДЕЛАТЬ · Вырезать 10:57–11:53 целиком (X1-10).\n'
            '📋 СПИСОК · Главы (карточки)\n'
            '        1:18.4  ▸ ДЕТСТВО СВЕТЫ\n'
            '        4:54.5  ▸ ПОЧЕМУ ИНТЕРНАТ?\n'
            '📍 ГДЕ · 10:57–11:53 · якорь «Света является выпускницей»\n'
            '📚 ИСТОЧНИК · \n'
            '🎬 НА ТАЙМЛАЙНЕ · маркер')
    p = split_nado(nado)
    assert [len(p[k]) for k in KEYS] == [2, 1, 1, 1, 1, 1], p
    assert lossless(nado), 'сплиттер теряет текст'
    assert squash(p['now'][0][0]).endswith('выпуском (10:30–10:57) и возвратом в детдом (11:53 «Это Валька»). Директива v2 #18 '
                                   'выполнена наоборот (v2 38:39 → v4 11:37)'), p['now'][0]
    assert p['list'][0] == ['Главы (карточки)', '1:18.4  ▸ ДЕТСТВО СВЕТЫ', '4:54.5  ▸ ПОЧЕМУ ИНТЕРНАТ?']
    assert lossless('❌ NOW · old\n✅ DO · new'), 'английские метки'
    assert [squash(x) for x in unwrap(['Раз:', '        Два пункта', '     хвост', '     1:05 и дальше', '        2:10  ▸ ГЛАВА'])] == \
        ['Раз:', 'Два пункта хвост 1:05 и дальше', '2:10 ▸ ГЛАВА']

    vis = clean_lines(p['now'][0])
    assert all(len(TC_SPAN_RE.findall(x)) <= 1 for x in vis), vis
    assert not any(re.search(r'Директива|v2|f0061|VLM', x) for x in vis + clean_lines(p['now'][1])), vis
    assert clean_lines(p['now'][1]) == ['Гуля в кадре (11:08–11:40)'], clean_lines(p['now'][1])
    assert clean_lines(p['do'][0]) == ['Вырезать 10:57–11:53 целиком.'], clean_lines(p['do'][0])
    assert clean_lines(['Сейчас на 11:16 подпись «ЖИМАГУЛ», а на 19:33 — «ЖУМАГУЛ».']) == \
        ['11:16 ▸ Сейчас подпись «ЖИМАГУЛ»', '19:33 ▸ «ЖУМАГУЛ».'], clean_lines(['Сейчас на 11:16 подпись «ЖИМАГУЛ», а на 19:33 — «ЖУМАГУЛ».'])
    assert clean_lines(['Правило канала fund_entry_min: не раньше 34-й минуты. structure_checks: fail, первое на 11:16.']) == \
        ['Правило канала: не раньше 34-й минуты. Первое на 11:16.']

    # таймкоды
    assert fix_tc({'v1_tc': '2449:40', 'tc_range': '40:49–40:51 · 42:20–42:31'}, 3045) == ([2449.0, 2540.0], True)
    assert fix_tc({'v1_tc': '668:36', 'tc_range': ''}, 3045) == ([668.0], True)
    assert fix_tc({'v1_tc': '10:57', 'tc_range': '10:57–20:56'}, 3045) == ([657.0], False)
    assert fix_tc({'v1_tc': '', 'tc_range': 'весь фильм'}, 3045) == ([], False)
    assert fix_tc({'v1_tc': '9999:59', 'tc_range': ''}, 3045) == ([], True)

    base = dict(cut_map=[dict(base_t0=100, base_t1=200, cut_t0=110, cut_t1=210, words=50),
                         dict(base_t0=220, base_t1=400, cut_t0=240, cut_t1=440, words=90)],
                unused=[dict(t0=200, t1=206, sec=6, text='думаю в ура они помирились все такая радостная'),
                        dict(t0=210, t1=219, sec=9, text='совсем другой кусок про кредит на лекарства и переезд')],
                new=[dict(t0=211, t1=216, text='Думала, ура, они помирились, я такая радостная')], moved=[])
    pj = Projector(base)
    assert [u['t0'] for u in pj.dropped] == [210], pj.dropped     # первый unused — та же речь, не вырез
    assert pj.project(150) == dict(sec_new=160.0, err=0.0, how='span')
    assert pj.project(310) == dict(sec_new=340.0, err=10.0, how='span')
    assert pj.project(203)['how'] == 'gap' and pj.project(203)['sec_new'] == 213.0
    assert pj.project(215)['how'] == 'dropped'
    assert pj.project(50) == dict(sec_new=None, err=None, how='none') == pj.project(999)
    assert retime_text('Вырезать 2:30–2:40 целиком', pj, 450) == 'Вырезать 2:40–2:50 целиком'
    assert retime_text('смотри 5:10', pj, 450) == 'смотри ≈5:40'
    assert retime_text('битый 150:02 и мусор 9000:10', pj, 450) == 'битый 2:40 и мусор'
    assert retime_text('хвост 7:20', pj, 450) == 'хвост ≈7:30'                # вне спанов → не длиннее ката
    assert retime_text('src 29:37–29:41 исходник', pj, 450) == 'src 29:37–29:41 исходник'

    # движок: синтетический кат
    words = dict(duration_sec=450, segments=[
        dict(start=158, text='Света является выпускницей одного из детских домов',
             words=[dict(w=w, s=158 + i * 0.4) for i, w in enumerate('Света является выпускницей одного из детских домов'.split())]),
        dict(start=300, text='Мы жили очень бедно', words=[dict(w=w, s=300 + i * 0.4) for i, w in enumerate('Мы жили очень бедно'.split())])])
    screens = [dict(id='s001', t0=112, t1=116, tc='1:52', text_best='ОДНА | C | РЕБЁНКОМ | фильм', texts_all=[]),
               dict(id='s002', t0=330, t1=334, tc='5:30', text_best='ЖУМАГУЛ ПАНФИЛОВА | куратор фонда', texts_all=[])]
    checks = dict(checks=[dict(rule='fund_entry_min', status='fail', value=11.3, threshold=34, tc='11:16', detail='…')])
    f = TD.Facts(data=dict(screens=screens, words=words, align=dict(bases={'B_v1': base}), checks=checks))
    assert f.moved == 0 and f.dropped_sec == 9.0 and f.base_tag == 'B_v1'
    assert TD.match('Одна с ребёнком', 'ОДНА | C | РЕБЁНКОМ | фильм') == (1.0, True)
    assert TD.match('совсем другой текст', 'ОДНА С РЕБЁНКОМ')[0] == 0.0

    def jv(item, nado_text, secs):
        return TD.judge_v2(item, split_nado(nado_text), f, secs, project=lambda s: pj.project(s)['sec_new'],
                           prev_label='v1', secs_old=[150])
    g = dict(title='титул: «Одна с ребёнком»', category='graphics', severity='should', sensitive=False)
    v = jv(g, '❌ СЕЙЧАС · титула нет\n✅ СДЕЛАТЬ · Поставить титул «Одна с ребёнком / фильм»\n📍 ГДЕ · 1:40 · якорь «Мы жили очень бедно»', [110])
    assert v['status'] == 'closed' and v['evidence']['tc'] == '1:52' and not TC_RE.search(v['evidence']['text']), v
    v = jv(g, '❌ СЕЙЧАС · нет\n✅ СДЕЛАТЬ · Титул «Одна с ребёнком» и подпись «Жимагул Панфилова, куратор фонда»', [110])
    assert v['status'] != 'closed', v                       # найдена одна цитата из двух → не «закрыто»
    v = jv(dict(g, title='Структура (TO-BE) — решение', category='structure'), '❌ СЕЙЧАС · порядок\n✅ СДЕЛАТЬ · переставить', [])
    assert v['status'] == 'open' and 'v1' in v['evidence']['text'] and not JARGON_RE.search(v['evidence']['text']), v
    v = jv(dict(g, title='Фонд входит слишком рано', category='structure', severity='must'), '❌ СЕЙЧАС · рано\n✅ СДЕЛАТЬ · перенести', [160])
    assert (v['status'], v['by'], v['rule'], v['evidence']['tc']) == ('open', 'rule', 'fund_entry_min', '11:16'), v
    f.prev_screens = [dict(t0=102.0, text='ОДНА С РЕБЁНКОМ фильм')]          # 102 с базы → 112 с ката: стояло и раньше
    v = jv(g, '❌ СЕЙЧАС · титула нет\n✅ СДЕЛАТЬ · Поставить титул «Одна с ребёнком / фильм»', [110])
    assert v['status'] != 'closed', v
    f.prev_screens = []
    v = jv(dict(g, title='плашка (перенос): «Одна с ребёнком»'), '❌ СЕЙЧАС · нет\n✅ СДЕЛАТЬ · перенести «Одна с ребёнком фильм»', [180])
    assert v['status'] != 'closed', v                       # «перенести»: в 68 с от места — не доказательство
    s = dict(title='Реплика про детдом', category='fund', severity='should', sensitive=True)
    v = jv(s, '❌ СЕЙЧАС · «Света является выпускницей одного из детских домов»\n✅ СДЕЛАТЬ · согласовать', [160])
    assert v['status'] == 'fund' and v['by'] == 'flag' and v['evidence'] and v['evidence']['kind'] == 'speech', v
    v = jv(s, '❌ СЕЙЧАС · «Света является выпускницей одного из детских домов»\n✅ СДЕЛАТЬ · согласовать', [400])
    assert v['status'] == 'fund' and v['evidence'] is None, v           # вне окна доказательства нет
    c = dict(title='Вырезать реплику', category='cut', severity='should', sensitive=False)
    v = jv(c, '❌ СЕЙЧАС · звучит «является выпускницей одного из детских домов»\n✅ СДЕЛАТЬ · вырезать', [160])
    assert v['status'] == 'open' and v['evidence']['kind'] == 'speech', v

    # buckets / dup_of / блокеры
    def r2(n, **kw):
        d = dict(part=2, n=n, label=f'ТЗ-{n:02d}', title='t', category='cut', severity='should', sensitive=False,
                 status='open', sec_new=100.0 * n, tc_new=tc_str(100 * n), dup_of=None, parts=dict(do=['Вырезать кусок.']),
                 topic=None, topic_title=None, _rule='', _blur=False)
        d.update(kw)
        return d
    p1 = [dict(part=1, n=4, label='ТЗ-04', title='t', category='structure', sec_new=669.0, tc_new='11:09', blocker=True,
               _rule='fund_entry_min', parts=dict(do=['11:09 ▸ куратор объясняет', 'отодвинуть вход фонда ближе к 34-й минуте'])),
          dict(part=1, n=2, label='ТЗ-02', title='t', category='structure', sec_new=None, tc_new='', blocker=False, _rule='', parts={})]
    p2 = [r2(1, severity='must'), r2(2, status='closed', severity='must'), r2(3, status='unknown'),
          r2(4, sensitive=True, status='fund', _blur=True), r2(5, sensitive=True, status='fund', topic='adoption', topic_title='Тайна'),
          r2(6, severity='must', category='structure', _rule='fund_entry_min'), r2(7, status='unknown', severity='must'),
          r2(8, category='structure', sec_new=700.0)]
    link_and_bucket(p1, p2)
    assert [r['bucket'] for r in p2] == ['block', 'closed', 'appendix', 'blur', 'fund', 'block', 'block', 'open'], [r['bucket'] for r in p2]
    assert p2[5]['dup_of'] == 4 and p2[7]['dup_of'] == 4 and p2[0]['dup_of'] is None
    bl = make_blockers(p1, p2)
    assert [(b['part'], b['n']) for b in bl] == [(2, 1), (1, 4), (2, 7)], bl        # ТЗ-06 ушёл в Часть 1 — один раз
    assert bl[1]['do'] == 'Отодвинуть вход фонда ближе к 34-й минуте', bl[1]
    assert tally_of(p1, p2) == dict(new=2, prev_total=8, closed=1, open=4, blur=1, fund=1, unknown=1)
    assert _is_blur('Фото детей: кроп или блюр', []) and not _is_blur('ФИО', [['Если фонд откажет — блюр.']])
    assert _is_blur('x', [['⚠️ На подтверждение фонда. Госномера заблюрить сразу.']])
    pats = [dict(key='adoption', rx=re.compile(r'усынов\w*'), topic='тайна усыновления')]
    assert topic_of('Антошку усыновили', pats) == ('adoption', 'Тайна усыновления') and topic_of('нет', pats) == (None, None)
    assert clean_title('«Я работаю в магните.» и через полторы минуты: «Я работаю неофициально. Если я сейчас буду').endswith('сейчас»')

    # резка по таймкодам: эталоны с реальных оборотов ТЗ (перенос строки прошлой полировки = SOFT)
    assert clean_lines([f'С 12:45 до{SOFT}15:17{SOFT}(2:32{SOFT}а дальше до 15:36) на экране только говорящая голова.']) == \
        ['12:45–15:17 (2 мин 32 с а дальше до 15:36) на экране только говорящая голова.']   # длительность — не место в фильме
    assert clean_lines(['8 вставок из 7 клипов (всего 1:22) по адресам листа.']) == ['8 вставок из 7 клипов (всего 1 мин 22 с) по адресам листа.']
    assert clean_lines([f'Повторы: «Детство, что я помню» 0:31.82{SOFT}и 1:18.96; «Вообще{SOFT}если самое детство» 0:43.46{SOFT}и 1:24.68.']) == \
        ['0:31.82 ▸ Повторы: «Детство, что я помню»', '1:18.96 ▸ «Детство, что я помню»',
         '0:43.46 ▸ «Вообще если самое детство»', '1:24.68 ▸ «Вообще если самое детство»']
    got = clean_lines([f'Вырезать 4:08–4:14 («Хотя их привезли. Я не знаю{SOFT}почему, их не привезли ко мне.»): развязка остаётся на 7:34–7:40.'])
    assert all(x.count('«') == x.count('»') for x in got) and 'Я не знаю почему, их не привезли' in got[0], got   # цитата цела
    assert clean_lines([f'Тема (3:29 «Русланчик»{SOFT}3:54–3:59 «Его усыновили. И он на СВО»{SOFT}4:30){SOFT}и диагноз 8:30–8:37 «Валера»']) == \
        ['Тема (3:29 «Русланчик» 3:54–3:59 «Его усыновили. И он на СВО» 4:30) и диагноз 8:30–8:37 «Валера»']   # голый «4:30» → не режем
    assert clean_lines([f'перебивки (машины 1:13–1:14{SOFT}подъезд 1:15–1:17{SOFT}собака 1:18){SOFT}и сразу интервью с 1:18,96.']) == \
        ['перебивки (машины 1:13–1:14 подъезд 1:15–1:17 собака 1:18) и сразу интервью с 1:18,96.']     # обрубки «подъезд», «собака»
    src = 'Сдвиг +242 с («две кофты» лист 0:53:30,60 ↔ 57:32,59; «Миша» 0:38:37,74 ↔ 42:39,73).'
    assert clean_lines([src]) == [src] and retime_text(src, pj, 450) == src          # адреса исходников: не режем, не пересчитываем
    assert visible_tc_too_long([dict(label='x', parts=dict(now=[src, 'на 9:10 и дальше']))], 450) == [('x', 'now', '9:10')]
    assert clean_lines(['⚠️ На подтверждение фонда (v2 #54 был ⛔, по политике 27.08 — ⚠️). Жесть не убирать.']) == \
        ['⚠️ На подтверждение фонда. Жесть не убирать.']
    assert clean_lines(['Порядок сохранён. КООРДИНАТЫ: - v4_tc, anchor и end_tc даны в v4. v4_tc — склейка из qc.json. Дальше по листу.']) == \
        ['Порядок сохранён. Дальше по листу.']
    assert fix_tc({'v1_tc': '7:00', 'tc_range': '0:07–0:09 · 0:55–0:57'}, 3045) == ([7.0, 55.0], True)
    assert retime_text('смотри 2:30 и дальше', Projector(dict(cut_map=[dict(base_t0=100, base_t1=200, cut_t0=110, cut_t1=216)])), 450) \
        == 'смотри ≈2:43 и дальше'                                                   # погрешность 3 с → «примерно»

    # первый экран
    assert _first_action(['13:06–15:38 на экране только синхрон у озера. Оставить синхрон на ударных битах, остальное перекрыть.']) == \
        'Оставить синхрон на ударных битах, остальное перекрыть'
    long_do = ('Оставить жёсткий крючок (политика канала), но добавить 4 бита квартиры и обрыв на «могут даже забрать»; вырезать 5 '
               'дословных повторов (≈27 с), которые звучат в первые 5 минут')
    fa = _first_action([long_do])
    assert fa == 'Оставить жёсткий крючок (политика канала), но добавить 4 бита квартиры и обрыв на «могут даже забрать»', fa
    many = [r2(10 + i, severity='must', status='unknown', sec_new=50.0 * i) for i in range(8)] + [r2(30, severity='must', sec_new=3000.0)]
    link_and_bucket([], many)
    assert 30 in [b['n'] for b in make_blockers([], many)], 'доказанное «осталось» вытеснено непроверенным'
    assert len(make_blockers([], many)) == 8
    assert _first_action(['Вырезать «Молодец в том, что признает ошибки, которые совершила» (≈38:24–38:35) и «Ввиду ряда ошибок, '
                          'которые были с Светланой сделаны» (50:00–50:05).']) == \
        'Вырезать «Молодец в том, что признает ошибки, которые совершила» и «Ввиду ряда ошибок, которые были с Светланой сделаны»'
    assert _first_action(['Вырезать «Молодец в том, что признает ошибки, которые совершила после выпуска из детского дома» и «Ввиду ряда '
                          'ошибок, которые были с Светланой сделаны до этого» целиком.']) == \
        'Вырезать «Молодец в том, что признает ошибки, которые совершила после выпуска из детского дома»'   # цитата не обрывается

    # пересчёт записанной модели (после вердиктов агента служебных полей в файле нет)
    fbx = dict(part1=[_public(r) | dict(status='new', evidence=dict(kind='rule', text='фонд рано') if r['n'] == 4 else None,
                                        severity='high', sensitive=False) for r in p1],
               part2=[_public(r) | dict(evidence=dict(kind='rule', text='фонд рано') if r['n'] == 6 else None) for r in p2])
    before = [(r['n'], r['bucket'], r['dup_of'], r['blocker']) for r in fbx['part2']]
    rebucket(fbx)
    assert [(r['n'], r['bucket'], r['dup_of'], r['blocker']) for r in fbx['part2']] == before, 'пересчёт без изменений обязан быть тождественным'
    assert not any(k.startswith('_') for r in fbx['part1'] + fbx['part2'] for k in r)
    next(r for r in fbx['part2'] if r['n'] == 1)['status'] = 'closed'               # агент подтвердил ТЗ-01
    next(r for r in fbx['part2'] if r['n'] == 6).update(evidence=dict(kind='speech', text='реплика на месте'), status_by='agent')
    rebucket(fbx)
    got = {r['n']: (r['bucket'], r['dup_of']) for r in fbx['part2']}
    assert got[1] == ('closed', None) and got[6] == ('block', 4) and got[4] == ('blur', None), got
    assert fbx['tally']['closed'] == 2 and [b['n'] for b in fbx['blockers']] == [4, 7], (fbx['tally'], fbx['blockers'])
    # ── доработка видимого текста (дефекты А–З) ──────────────────────────────────────────────────────────
    def rt(x):
        return retime_text(x, pj, 450)
    # В: пунктуация после вычистки, обрубки резки, голые таймкоды, незакрытые скобки и кавычки
    assert clean_lines(['Два разворота альбома: голый малыш 29 с (f0012, в том числе крупно).']) == \
        ['Два разворота альбома: голый малыш 29 с (в том числе крупно).']
    assert clean_lines(['Держать без имени (имя Кати звучит позже, см. A2-08). Дальше по листу (X2-06, X2-09).']) == \
        ['Держать без имени (имя Кати звучит позже). Дальше по листу.']              # чужую скобку след не уносит
    one = clean_lines([f'Поставить титул на затемнение 1:09,9 (продлить до 4 с); добавить подписи Светланы{SOFT}(1:22) и '
                       f'Жимагул Панфиловой{SOFT}(10:57), хронологический титр.'])
    assert len(one) == 1 and 'Светланы (1:22) и Жимагул Панфиловой (10:57), хронологический титр.' in one[0], one
    assert clean_lines(['Вырезать повтор на 4:10, потом 4:37.']) == ['Вырезать повтор на 4:10, потом 4:37.']   # «4:37» голым не уходит
    assert clean_lines(['Вырезать 2:13–2:15 «Антошка младший брат» и 2:18–2:23 «Мы пятеро от одного отца».']) == \
        ['2:13–2:15 ▸ Вырезать «Антошка младший брат»', '2:18–2:23 ▸ «Мы пятеро от одного отца».']   # у второго места своя цитата
    assert clean_lines(['Сначала вырезать всю паузу на 1:05, затем схлопнуть весь хвост на 1:20.']) == \
        ['1:05 ▸ Сначала вырезать всю паузу', '1:20 ▸ Затем схлопнуть весь хвост.']       # каждый кусок — фраза с действием
    assert clean_lines(['Вставить между 9:20 и 9:21 её реплику: «несколько месяцев продолжалось».']) == \
        ['Вставить между 9:20 и 9:21 её реплику: «несколько месяцев продолжалось».']
    assert clean_lines([f'Блок стоит между выпуском (10:30–10:57) и возвратом в детдом{SOFT}(11:53 «Это Валька»).']) == \
        ['10:30–10:57 ▸ Блок стоит между выпуском и возвратом в детдом', '11:53 ▸ «Это Валька».']   # скобки куска сняты
    assert len(cut_spans('резать не 21:50–22:28: вырезать')) == 1 and not cut_spans('клип 0:53:30,60 ↔ 57:32')
    assert not _meaningful('собака') and not _meaningful('Жимагул Панфиловой, хронологический титр') and _meaningful('«ЖУМАГУЛ».')
    assert visible_block([['4:10']], 'now') == ([], 1) and visible_block([['на 4:10 пауза']], 'now') == (['на 4:10 пауза'], 0)
    assert balance('Вырезать 4:44–5:34, от «Самый интересный момент был» до «…мама впала в кому». Продолжить с «и') == \
        'Вырезать 4:44–5:34, от «Самый интересный момент был» до «…мама впала в кому».'
    assert balance('Держать как есть: это причина интерната — без иллюстраций и без имени (имя звучит позже, на 8:15, см') == \
        'Держать как есть: это причина интерната — без иллюстраций и без имени'
    assert balance('Лишняя) скобка и «цитата» целы') == 'Лишняя скобка и «цитата» целы'
    long_q = 'Вставить реплику. ' + 'Она говорит: «' + 'слово ' * 45 + 'конец». ' + 'Потом идёт вторая фраза без кавычек. ' * 3
    got, lost = fit(long_q)
    assert all(len(x) <= MAX_LINE and _balanced(x) for x in got) and got[0] == 'Вставить реплику.', (got, lost)
    assert _cap('≈1:29 ▸ добавить подписи') == '≈1:29 ▸ Добавить подписи' and _cap('1:05 ▸ «цитата»') == '1:05 ▸ «цитата»'
    # Г: чистка не опустошает блок; пустой ✅ у полного пункта выводится из заголовка
    assert clean_lines(['Вернуть «И он»: вход склейки сдвинуть на src 25:44.9 (клип 0869), чтобы звучало «И он уехал.»']) == []
    assert visible_block([['Вернуть «И он»: вход склейки сдвинуть на src 25:44.9 (клип 0869), чтобы звучало «И он уехал.»']], 'do') == \
        (['Вернуть «И он»: вход склейки сдвинуть, чтобы звучало «И он уехал.»'], 0)
    e = [r2(1, title='Неправильная склейка фразы.', bucket='open', parts=dict(do=[])), r2(2, bucket='open'),
         r2(3, bucket='appendix', parts=dict(do=[])), r2(4, bucket='block', dup_of=4, parts=dict(do=[]))]
    ensure_do(e)
    assert e[0]['parts']['do'] == ['Исправить: Неправильная склейка фразы'] and e[0]['do_derived'] is True
    assert [x['do_derived'] for x in e[1:]] == [False, False, False] and e[2]['parts']['do'] == [] and e[3]['parts']['do'] == []
    # Б: 📍 — место в новом кате или «весь фильм»; смета и номера исходных клипов местом не считаются
    assert visible_block([['Монтажёр — около трёх рабочих дней (22–28 ч): 8 вставок из 7 клипов (0850, 0877, 0894×3)']], 'where') == ([], 1)
    assert visible_block([['весь фильм']], 'where') == (['весь фильм'], 0)
    assert visible_block([['смета на три дня'], ['2:30–2:40 · якорь «Мы жили бедно»']], 'where', rt) == (['2:40–2:50 · якорь «Мы жили бедно»'], 1)
    assert visible_block([['2:30–2:32 2:35 2:40–2:41']], 'where', rt) == (['2:40–2:42', '2:45', '2:50–2:51'], 0)   # список мест
    assert clean_lines(['8 вставок из 7 исходных клипов (0850, 0877, 0885, 0894×3; всего 1:22), скамейка 0890.']) == \
        ['8 вставок из 7 исходных клипов (всего 1 мин 22 с), скамейка.']
    # Д: заголовок пересчитан на новый кат; диапазон с долями секунды — один таймкод без долей
    assert clean_title('Фонд: убрать ранний вход на 2:30 и решить по второму', retime=rt) == 'Фонд: убрать ранний вход на 2:40 и решить по второму'
    assert clean_title('Ошибка распознавания. На 2:30,78–2:31,48', retime=rt) == 'Ошибка распознавания. На 2:40–2:41'
    assert len(TC_SPAN_RE.findall(clean_title('На 2:30,78–2:31,48', retime=rt))) == 1
    # Е: строки вердикта — без служебных имён правил
    assert human_summary(['Кат плотный.', 'правила листа нарушены: fund_entry_min, last_sound_rule, teaser_rule', 'сбой some_new_rule',
                          'align: moved 0'], dict(fund_entry_min=dict(threshold=34))) == \
        ['Кат плотный.', 'правила листа нарушены: фонд входит раньше 34-й минуты, фильм кончается призывом о деньгах, тизер целиком из бед']
    assert human_summary(['нарушено: fund_entry_min'], {}) == ['нарушено: фонд входит слишком рано']
    # Ж: блокер без места в новом кате берёт таймкод из своей видимой 📍
    assert _blocker_tc(dict(tc_new='', sec_new=None, parts=dict(where=['≈1:25–1:40 · карточка «ДЕТСТВО»']))) == ('≈1:25', 85.0)
    assert _blocker_tc(dict(tc_new='', sec_new=None, parts=dict(where=['весь фильм']))) == ('', None)
    assert _blocker_tc(dict(tc_new='5:00', sec_new=300.0, parts=dict(where=['1:25']))) == ('5:00', 300.0)
    # З: неявно чувствительные пункты — номера из карточки (список или строка из env)
    assert int_set('86,97') == {86, 97} == int_set([86, '97']) == int_set('86 97') and int_set(None) == set() == int_set('')
    it = dict(title='Неправильная склейка сцены', category='cut', severity='must', sensitive=False,
              v1_tc='2:30', tc_range='2:30–2:40', nado='❌ СЕЙЧАС · оффтоп\n✅ СДЕЛАТЬ · Вырезать 2:30–2:40 целиком.\n📍 ГДЕ · 2:30–2:40')
    plain = row_part2(86, it, f, pj, 450, 450, 'v2', 'v1', [])
    extra = row_part2(86, it, f, pj, 450, 450, 'v2', 'v1', [], True)
    flagged = row_part2(86, dict(it, sensitive=True), f, pj, 450, 450, 'v2', 'v1', [], True)
    link_and_bucket([], [plain, extra, flagged])
    assert (plain['sensitive'], plain['sensitive_by'], plain['bucket']) == (False, None, 'block'), plain
    assert (extra['sensitive'], extra['sensitive_by'], extra['status'], extra['status_by'], extra['bucket']) == \
        (True, 'card', 'fund', 'flag', 'fund'), extra
    assert flagged['sensitive_by'] == 'prev' and extra['topic'] == 'other'
    assert extra['parts']['do'] == ['Вырезать 2:40–2:50 целиком.'] and extra['title'] == 'Неправильная склейка сцены'
    # А: частично выполненный пункт — первая строка ✅ и первый экран говорят о недостающем
    scr = [dict(id='s001', t0=112, t1=116, tc='1:52', text_best='ОДНА С РЕБЁНКОМ | фильм', texts_all=[]),
           dict(id='s002', t0=160, t1=163, tc='2:40', text_best='ДЕТСТВО СВЕТЫ', texts_all=[]),
           dict(id='s003', t0=340, t1=343, tc='5:40', text_best='ПОЧЕМУ ИНТЕРНАТ', texts_all=[])]
    fa = TD.Facts(data=dict(screens=scr, words=words, align=dict(bases={'B_v1': base}), checks=dict(checks=[])))
    a_nado = ('❌ СЕЙЧАС · В кате нет структуры.\n✅ СДЕЛАТЬ · Титул после тизера: «ОДНА С РЕБЁНКОМ / фильм» на 1:42.\n'
              '✅ СДЕЛАТЬ · Поставить 2 карточки глав в стиле канала.\n✅ СДЕЛАТЬ · Подглавы — маленькие плашки слева.\n'
              '📋 СПИСОК · Главы (карточки)\n        2:30  ▸ ДЕТСТВО СВЕТЫ\n        5:10  ▸ ПОЧЕМУ ИНТЕРНАТ?\n'
              '📋 СПИСОК · Подглавы (плашки)\n        3:00  ▸ Последняя Пасха\n        3:20  ▸ «Всю жизнь работала»\n'
              '        4:00  ▸ Жених с коробочкой\n        4:30  ▸ Новый год у мамы\n        6:00  ▸ Кредит на лекарства\n'
              '📍 ГДЕ · 2:30 · карточка «ДЕТСТВО СВЕТЫ»')
    ra = row_part2(1, dict(title='Структура: титул, главы и подглавы', category='structure', severity='must', tc_range='весь фильм',
                           nado=a_nado), fa, pj, 450, 450, 'v2', 'v1', [])
    rb = row_part2(9, dict(title='Структура: титул, карточки глав, подписи', category='graphics', severity='must', v1_tc='1:42',
                           tc_range='весь фильм', nado='❌ СЕЙЧАС · После тизера затемнение.\n✅ СДЕЛАТЬ · Поставить титул на '
                           'затемнение и 2 карточки глав; добавить подписи героини и куратора. Полный список — ТЗ-01 «Структура»\n'
                           '📍 ГДЕ · 1:42–1:50'), fa, pj, 450, 450, 'v2', 'v1', [])
    assert is_partial(ra) and not is_partial(rb), (ra['status'], ra['evidence'], rb['status'])
    assert ra['parts']['do'] == ['Титул после тизера: «ОДНА С РЕБЁНКОМ / фильм» на 1:52.'], ra['parts']['do']   # до прохода — как в ТЗ
    link_and_bucket([], [ra, rb])
    partial_pass([ra, rb], fa, 'v1')
    assert ra['parts']['do'] == ['Добавить недостающее: подглавы — 0 из 5: «Последняя Пасха», «Всю жизнь работала», «Жених с коробочкой» '
                                 'и ещё 2', 'Подглавы — маленькие плашки слева.'], ra['parts']['do']
    assert len(ra['parts']['do'][0]) <= MAX_LINE and len(missing_line(ra, 90)) <= 90 and 'и ещё' in missing_line(ra, 90)
    assert rb['see_n'] == 1 and rb['parts']['do'] == ['Добавить подписи героини и куратора.', 'Полный список недостающего — ТЗ-01 · v1'], rb['parts']['do']
    bl = make_blockers([], [ra, rb])
    assert [(b['n'], b['tc'], b['do']) for b in bl] == [(1, '', ra['parts']['do'][0])], bl          # требование — один раз
    # ❌ и 📍 частично выполненного пункта — по фактам нового ката: «в кате нет структуры» уже неправда, а 📍 про
    # поставленную карточку «ДЕТСТВО СВЕТЫ» — не место недостающего (строка без таймкода на первом экране — честно)
    assert ra['parts']['now'] == ['Сделано: главы — 2 из 2. Не хватает: подглавы — 5 из 5.'] and ra['parts']['where'] == [], ra['parts']
    assert rb['parts']['now'] == ra['parts']['now']
    assert _blocker_tc(dict(tc_new='', parts=dict(where=['≈2:40,5–2:50 · якорь «…»']))) == ('≈2:40', 160.0)   # Ж: время из 📍
    ra['status'] = 'closed'                                                          # пункт закрыт — отсылка снова держит выпуск
    link_and_bucket([], [ra, rb])
    assert [b['n'] for b in make_blockers([], [ra, rb])] == [9]
    # ── придирчивая проверка: эталоны на найденное глазами ──────────────────────────────────────────────────
    # знаки на стыках переносов прошлого ТЗ (там стояли запятая или точка)
    assert heal(f'перебивки (машины 1:13–1:14{SOFT}подъезд 1:15–1:17{SOFT}собака 1:18){SOFT}и сразу интервью') == \
        'перебивки (машины 1:13–1:14, подъезд 1:15–1:17, собака 1:18) и сразу интервью'
    assert heal(f'С 12:45 до{SOFT}15:17{SOFT}(2:32{SOFT}а дальше до 15:36)') == 'С 12:45 до 15:17 (2:32, а дальше до 15:36)'
    assert heal(f'кадр брать нельзя{SOFT}В v4 на 51:02 Миша машет') == 'кадр брать нельзя. В v4 на 51:02 Миша машет'
    assert heal(f'«Детство, что я помню{SOFT}что по помойкам лазила.»') == '«Детство, что я помню, что по помойкам лазила.»'
    assert heal(f'→ 20 с{SOFT}(оставить «если бы»)') == '→ 20 с (оставить «если бы»)' and heal(f'о квартире впервые{SOFT}≈15:12') == 'о квартире впервые ≈15:12'
    # цитата прошлого ТЗ: таймкод из середины фразы не выносится, чужой текст куску не приписывается
    plates = f'Госномера машин: на 1:13–1:14 читаются «В662ВУ 252» и «В275АО 152»{SOFT}на 38:10{SOFT}и 50:40–50:44 в 720p не читаются'
    assert clean_lines([plates], safe=True) == ['Госномера машин: на 1:13–1:14 читаются «В662ВУ 252» и «В275АО 152», на 38:10 и '
                                                '50:40–50:44 в 720p не читаются']
    assert clean_lines([f'Повтор вырезать.{SOFT}Между 34:09 «…когда он умер.»{SOFT}и 34:10 дать 1–2 с воздуха на перебивке'], safe=True) == \
        ['Повтор вырезать.', 'Между 34:09 «…когда он умер.» и 34:10 дать 1–2 с воздуха на перебивке']
    assert clean_lines([f'Квартира появляется на 24:13 (47% хронометража); что это квартира от государства{SOFT}зритель узнаёт на 30:15'],
                       safe=True) == ['Квартира появляется на 24:13 (47% хронометража)',
                                      'Что это квартира от государства, зритель узнаёт на 30:15']
    assert clean_lines([f'Резать по «мое чудо.» (0:22.18){SOFT}0:22.36–0:23.58 убрать{SOFT}паузу до 0:24.68 схлопнуть.'], safe=True) == \
        ['Резать по «мое чудо.» (0:22.18), 0:22.36–0:23.58 убрать, паузу до 0:24.68 схлопнуть.']
    # «−7 с» — секунды, а не висящий предлог; адрес исходника и «В v4 на» (таймкод уже по новому кату)
    assert strip_junk('— немой пейзаж. −7 с') == '— немой пейзаж. −7 с'.strip(' —') and strip_junk('Вырезать хвост на') == 'Вырезать хвост'
    assert strip_junk('помечена к удалению — 1101 · 0:11:19,54–0:11:28,52; судьбу решает Роман.') == 'помечена к удалению; судьбу решает Роман.'
    assert strip_junk('Брать нельзя. В v4 на 51:02–51:11 Миша машет') == 'Брать нельзя. На 51:02–51:11 Миша машет'
    # внутренние номера заметок → номера пунктов прошлого ТЗ (иначе «Если по выбран вариант А», «отдать под и.»)
    im = id_map([dict(ids=['A1-01']), dict(ids=['A8-02', 'A8-04']), dict(ids=['A4-12'])])
    assert map_ids('Если по A4-12 выбран вариант А; отдать под A8-02 и A8-04 (A1-01, X9-99).', im, 1, 'v4') == \
        'Если по ТЗ-03 · v4 выбран вариант А; отдать под ТЗ-02 · v4 (A1-01, X9-99).'
    assert map_ids('фонду — к сведению (A8-02).', im, 1, 'v4') == 'фонду — к сведению (A8-02).'      # справочную скобку снимет чистка
    assert strip_junk('Титр «X» (тексты — в graphics_tz). Дальше.') == 'Титр «X». Дальше.'
    assert strip_junk('не монолитом (fund_piece_max_sec ≤ 90 c).') == 'не монолитом (≤ 90 c).'
    assert strip_junk('или заменить на 05 · 0901 «рука в руке» либо общий план') == 'или заменить на «рука в руке» либо общий план'
    assert strip_junk('Сдвинуть вход в 0894 на 6 с раньше') == 'Сдвинуть вход на 6 с раньше'
    assert strip_junk('по OCR подписей имён в фильме нет') == 'по распознаванию текста подписей имён в фильме нет'
    # повтор фразы внутри блока, двойные кавычки якоря, заглавная буква строки
    assert _dedupe(['Сверить со Светой, кто на снимке. Если не родители — заменить. · Сверить со Светой, кто на снимке.']) == \
        ['Сверить со Светой, кто на снимке. Если не родители — заменить.']
    assert _unnest('1:16 · якорь ««Судьба.» → затемнение → «Детство.»»') == '1:16 · якорь «Судьба.» → затемнение → «Детство.»'
    assert visible_block([['карточка главы: «Вечер с Мишей»']], 'do', rt)[0] == ['Карточка главы: «Вечер с Мишей»']
    # заголовок, оборванный исходником посреди цитаты
    def ht(raw, txt):
        return heal_title(clean_title(raw), raw, [txt])
    assert ht('хроно-титр: «Малая Пица / Съёмка — июль 2026. Отоп»', 'хроно-титр: «Малая Пица / Съёмка — июль 2026. Отопительный сезон»') == \
        'хроно-титр: «Малая Пица / Съёмка — июль 2026.»'
    assert ht('Диагнозы брата Валеры: «и валера вот он брат инвалид», «Говорили, типа у них другая',
              'Диагнозы брата Валеры: «и валера вот он брат инвалид», «Говорили, типа у них другая инвалидность.»') == \
        'Диагнозы брата Валеры: «и валера вот он брат инвалид»'
    assert ht('Тайна усыновления №2: «А Антошку его усыновили.» + кровный', 'Тайна усыновления №2: «А Антошку его усыновили.» + кровный отец') == \
        'Тайна усыновления №2: «А Антошку его усыновили.»'
    assert ht('Третье лицо «Катя». Названа по имени', 'Третье лицо «Катя». Названа по имени. Дальше') == 'Третье лицо «Катя». Названа по имени'
    assert ht('Фонд: убрать ранний вход и решить по второму', 'совсем другой текст пункта') == 'Фонд: убрать ранний вход и решить по второму'
    # А по существу: цель стоит на экране в другом падеже; подписи, которые уже стоят, заново не требуются
    assert _same_stem('фонда', 'фонд') and _same_stem('панфиловой', 'панфилова') and not _same_stem('жимагул', 'жумагул')
    scr2 = scr + [dict(id='s004', t0=92, t1=96, tc='1:32', text_best='СВЕТЛАНА | выпускница детского дома', texts_all=[]),
                  dict(id='s005', t0=676, t1=681, tc='11:16', text_best='ЖИМАГУЛ ПАНФИЛОВА | куратор по семьям • фонд «Бюро Добрых Дел»', texts_all=[])]
    fb2 = TD.Facts(data=dict(screens=scr2, words=words, align=dict(bases={'B_v1': base}), checks=dict(checks=[])))
    assert drop_done_captions('добавить подписи Светланы (1:29) и Жимагул Панфиловой (≈11:10), хронологический титр', fb2) == \
        'добавить хронологический титр'
    assert drop_done_captions('добавить подписи Светланы (1:29) и Марии Ивановой (≈11:10), хронологический титр', fb2) == \
        'добавить подписи Светланы (1:29) и Марии Ивановой (≈11:10), хронологический титр'
    rowx = dict(part=2, status='open', evidence=dict(kind='screen', text='на экране есть: главы — 1 из 1; подглавы — 0 из 2; нет: «x»'),
                checks=[dict(q='ДЕТСТВО СВЕТЫ', found=True, tc='2:40', score=1.0),
                        dict(q='Жимагул Панфилова, куратор фонда', found=False, tc='11:16', score=0.75),
                        dict(q='Последняя Пасха', found=False, tc='', score=0.0)])
    assert alt_spelling(rowx, fb2) == 1 and rowx['checks'][1]['found'] and rowx['checks'][1]['alt']
    assert rowx['evidence']['text'] == 'на экране есть: главы — 1 из 1; подглавы — 1 из 2; нет: «Последняя Пасха»', rowx['evidence']
    assert missing_line(rowx) == 'Добавить недостающее: подглавы — 1 из 2: «Последняя Пасха»'
    assert partial_now(rowx) == 'Сделано: главы — 1 из 1; подглавы — 1 из 2. Не хватает: подглавы — 1 из 2.'
    # ✅ не пересказывает ❌
    assert do_without_now(['13:06–15:38 на экране только синхрон у озера. Оставить синхрон на ударных битах.'],
                          ['13:06–15:38 (2 мин 32 с) на экране только говорящая голова у озера: синхрон, скамейка.']) == \
        (['Оставить синхрон на ударных битах.'], 0)
    assert do_without_now(['Решение Романа: переносить ли акт.', 'Сейчас обещание оплачивается только на 48% хронометража.'], ['x']) == \
        (['Решение Романа: переносить ли акт.'], 1)
    assert do_without_now(['Сейчас титра нет.'], ['Титра нет.']) == (['Сейчас титра нет.'], 0)       # блок не опустошается
    print('SELFTEST OK')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description='модель «Обратная связь по кату» → work/{cut}/feedback.json')
    ap.add_argument('--prev', default='', help='ТЗ прошлой версии (иначе карточка prev_pravki / env YTAI_PREV_PRAVKI)')
    ap.add_argument('--out', default='')
    ap.add_argument('--calibrate', default='', help='эталон gold.json: печатает таблицу ожидание/факт, файл не пишет')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    fb = build(a.prev or None)
    stats = fb.pop('_stats')
    if a.calibrate:
        return calibrate(fb, a.calibrate)
    sys.path.insert(0, str(HERE.parent / 'stages'))
    from _bootstrap import W6
    out = Path(a.out) if a.out else W6 / 'feedback.json'
    out.write_text(json.dumps(fb, ensure_ascii=False, indent=1), encoding='utf-8')
    t = fb['tally']
    print(f'обратная связь {fb["code"]} {fb["cut_version"]} · сборка {fb["build_no"]} · новых {t["new"]} · прошлых {t["prev_total"]}: '
          f'закрыто {t["closed"]} · осталось {t["open"]} · блюр {t["blur"]} · фонд {t["fund"]} · не проверено {t["unknown"]}')
    print(f'разбор без потерь: {stats["lossless"]} · блокеров на первом экране: {len(fb["blockers"])} · кадров нужно: {len(fb["frames_wanted"])}')
    for n in stats['notes']:
        print('⚠️', n)
    print('→', out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
