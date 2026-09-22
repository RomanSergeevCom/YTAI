#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feedback_call.py — подготовка и приём облачного сверщика «Обратной связи по кату vN» (cloud/wf_feedback_check.js).
Сам код в облако не ходит. Контракт: docs/feedback_v1.md §6.

Зачем: код судит пункты прошлого ТЗ по совпадению слов и на двух третях пунктов честно отвечает «не удалось
проверить», а найденное «закрыто» иногда находит не в том месте фильма. Один текстовый агент читает новый кат
лентой (речь + надписи + описания кадров) и по каждому пункту отвечает «закрыто / осталось / не знаю» с ДОСЛОВНОЙ
цитатой. Цитату проверяет код: выдумал — вердикт выброшен. Вливание пессимистичное: «закрыто» надо доказать,
а сомнения агента в кодовом «закрыто» достаточно, чтобы его снять.

  --print-call [--exclude N,N]
                           лента → cloud/in/feedback_film.txt, пункты → cloud/in/feedback_items.json (+ packet_sha),
                           последней строкой печатает вызов Workflow({scriptPath, args}) — его читает review.py
                           (_cloud_compound → cloud/CALL_feedback.txt) и автономный режим (headless_claude);
  --apply [--from PATH] [--out PATH] [--fb PATH] [--packet PATH]
                           cloud/out/feedback_check.json → work/{cut}/feedback.json: проверка каждого вердикта,
                           status_by=agent у принятых, причина отказа → agent_note, затем feedback_model.rebucket;
                           чужой packet_sha / cut_version → ОТКАЗ всего файла, код возврата 2;
  --status                 что есть на диске;
  --selftest               офлайн, на синтетике, без карточки.

Кому идёт пакет: все «не удалось проверить» + все кодовые «закрыто» + кодовые «осталось» с severity=must.
Чувствительные пункты (sensitive) и кадры в облако НЕ идут никогда — assert в select() и в самотесте. Лента строится
только из транскрипта, экранов и описаний кадров нового ката: тексты пунктов ТЗ в неё не попадают по построению.

API: select(fb) · build_film(words, screens, vlm) · build_items(fb, rows) · make_packet(...) · parse_film(text)
     validate(verdict, film_index, packet) -> (ok, why) · apply_check(fb, check, packet, film_index, applied_at)
Модуль импортируется без карточки фильма; карточка (YTAI_CARD) нужна только командам --print-call / --apply / --status.
env: YTAI_CARD=<review_card.json>
"""
import argparse
import bisect
import datetime
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import feedback_model as FM  # noqa: E402  (rebucket, tc_str; карточку не требует)
import feedback_view as V    # noqa: E402  (лимиты видимых блоков, словарь жаргона; карточку не требует)
import tz_diff as TD         # noqa: E402  (norm2 — одна нормализация с кодовым судьёй)

WF = HERE.parent / 'cloud' / 'wf_feedback_check.js'
ITEMS_SCHEMA, CHECK_SCHEMA = 'feedback-items-v1', 'feedback-check-v1'
FILM_NAME, ITEMS_NAME, OUT_NAME = 'feedback_film.txt', 'feedback_items.json', 'feedback_check.json'

QUOTE_WIN = 20            # цитата обязана найтись в ленте в ±20 с от tc вердикта (контракт §6)
CONF_MIN = 0.8            # «закрыто» — только с такой уверенностью
QUOTE_MAX = 160           # агенту сказано «≤120 знаков»; небольшой перебор не повод выбрасывать дословную цитату
QUOTE_MIN = 6             # короче (после нормализации) — «да», «вот» найдутся где угодно, это не доказательство
CUT_GAP_WORDS = 4         # вырез: между двумя цитатами вокруг стыка — не больше стольких слов (в 12 поместилась бы сама вырезаемая фраза)…
CUT_GAP_SEC = 15          # …и не больше стольких секунд между их строками
PLACE_PAD = 60            # «закрыто» доказывается цитатой из места пункта: окно look или ±столько секунд от таймкода в его тексте
PLACE_PAD_SCREEN = 120    # …для надписей — шире, как и окно look
TOKEN_LIMIT = 150_000     # выше — из пакета убирается хвост (второго агента по плану нет)
CHARS_PER_TOKEN = 2.5     # кириллица: оценка с запасом в большую сторону
STATUSES = ('closed', 'open', 'unknown')
EXTRA_JARGON = re.compile(r'\b(?:лент[а-яё]*|пакет[а-яё]*|confidence|quote|packet|sha|json|speech|screen)\b', re.I)


# ═══ мелочи ══════════════════════════════════════════════════════════════════════════════════════════════════
def one(s) -> str:
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def tc_str(sec) -> str:
    s = int(sec or 0)
    return f'{s // 60}:{s % 60:02d}'


_TC_IN = re.compile(r'(?<![\d:])(?:(\d{1,2}):)?(\d{1,3}):(\d{2})(?![\d:])')


def tc_secs(s) -> list:
    """все таймкоды строки в секундах: «M:SS», «H:MM:SS», «M:SS–M:SS»"""
    return [int(h or 0) * 3600 + int(m) * 60 + int(x) for h, m, x in _TC_IN.findall(str(s or ''))]


_TC_ONE = r'(?:(\d{1,2}):)?(\d{1,3}):(\d{2})'
_TC_FULL = re.compile(r'\s*≈?\s*' + _TC_ONE + r'\s*(?:[–—-]\s*≈?\s*' + _TC_ONE + r'\s*)?')


def tc_strict(x):
    """таймкод ВЕРДИКТА → (секунда | None, ошибка). Пусто → (None, ''). Не строка, минус, «99:99», «11:75», текст вокруг →
    (None, 'непонятный таймкод'): tc_secs выудил бы «11:15» из «-11:15» и «99:99» сошло бы за 100:39 в длинном фильме."""
    if x is None or x == '':
        return None, ''
    m = _TC_FULL.fullmatch(x) if isinstance(x, str) else None
    if not m:
        return None, 'непонятный таймкод'
    h, mm, ss = m.group(1), int(m.group(2)), int(m.group(3))
    if ss >= 60 or (h is not None and mm >= 60):
        return None, 'непонятный таймкод'
    return int(h or 0) * 3600 + mm * 60 + ss, ''


def is_n(n) -> bool:
    """номер пункта — только целое: True == 1 и 13.0 == 13 как ключи словаря совпали бы с чужим пунктом, список уронил бы приём"""
    return isinstance(n, int) and not isinstance(n, bool)


def load_json(p, default=None):
    p = Path(p)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding='utf-8'))


def write_atomic(path, text: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


def canon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def packet_sha(film: str, items: list) -> str:
    return hashlib.sha1((film + canon(items)).encode('utf-8')).hexdigest()[:8]


def est_tokens(chars: int) -> int:
    return int(math.ceil(chars / CHARS_PER_TOKEN))


# ═══ 1. кому ═════════════════════════════════════════════════════════════════════════════════════════════════
def group_of(r: dict) -> str:
    """'' — пункт агенту не нужен"""
    if r.get('sensitive'):
        return ''
    st, by = r.get('status'), r.get('status_by')
    if st == 'unknown':
        return 'unknown'
    if st == 'closed' and by == 'code':
        return 'closed'
    if st == 'open' and r.get('severity') == 'must' and by in ('code', 'rule'):
        return 'must_open'
    return ''


def select(fb: dict):
    """→ (строки Части 2 для агента, счётчики). Чувствительное не выходит отсюда никогда."""
    rows, stats = [], dict(unknown=0, closed=0, must_open=0, sensitive_excluded=0, part2=0)
    for r in fb.get('part2') or []:
        stats['part2'] += 1
        if r.get('sensitive'):
            stats['sensitive_excluded'] += 1
            continue
        g = group_of(r)
        if g:
            stats[g] += 1
            rows.append(r)
    assert not any(r.get('sensitive') for r in rows), 'чувствительный пункт в пакете для облака'
    rows.sort(key=lambda r: (-1 if r.get('sec_new') is None else r['sec_new'], r['n']))
    return rows, stats


# ═══ 2. лента ════════════════════════════════════════════════════════════════════════════════════════════════
def _speaker(name) -> str:
    m = re.fullmatch(r'\s*(?:speaker|спикер)[ _]*(\d+)\s*', str(name or ''), re.I)
    return f'С{m.group(1)}' if m else (one(name) or '?')


def build_film(words: dict, screens: list, vlm: list, fund_speaker: str = '', title: str = '') -> str:
    """хронологическая лента нового ката. Входы — ТОЛЬКО транскрипт, экраны и описания кадров: ни одного текста из ТЗ."""
    ents = []                                              # (секунда, порядок вида, строка)
    for seg in (words or {}).get('segments') or []:
        t = one(seg.get('text'))
        if t:
            ents.append((float(seg.get('start') or 0), 1, f'{tc_str(seg.get("start"))} [{_speaker(seg.get("speaker"))}] {t}'))
    for e in screens or []:
        best = one(str(e.get('text_best') or '').replace('\n', ' | '))
        if not best:
            continue
        seen, var = {TD.norm2(best)}, [best]
        for x in e.get('texts_all') or []:                 # другие прочтения той же надписи — машина читает с огрехами
            x = one(str(x).replace('\n', ' | '))
            if x and TD.norm2(x) not in seen and len(var) < 3:
                seen.add(TD.norm2(x))
                var.append(x)
        t0 = float(e.get('t0') or 0)
        t1 = max(t0, float(e.get('t1') if e.get('t1') is not None else t0))
        txt = ' / '.join(var).replace('«', '"').replace('»', '"')[:300]
        ents.append((t0, 0, f'ЭКРАН {tc_str(t0)}–{tc_str(t1)} «{txt}»'))
    for e in vlm or []:
        desc = one(e.get('vlm_desc'))[:240]
        seen_txt = one(str(e.get('vlm_text') or '').replace('\n', ' | '))[:160]
        if not desc and not seen_txt:
            continue
        line = f'VLM {tc_str(e.get("t0"))} {desc}' + (f' · текст в кадре: {seen_txt}' if seen_txt else '')
        ents.append((float(e.get('t0') or 0), 2, line))
    ents.sort(key=lambda x: (int(x[0]), x[1], x[0]))
    dur = float((words or {}).get('duration_sec') or 0)
    head = [f'# Лента нового ката{" · " + one(title) if title else ""}{" · длительность " + tc_str(dur) if dur else ""}',
            '# «M:SS [С1] текст» — речь · «ЭКРАН M:SS–M:SS «…»» — надпись на экране · «VLM M:SS …» — машинное описание кадра']
    if fund_speaker:
        head.append(f'# {_speaker(fund_speaker)} — представитель фонда')
    return '\n'.join(head + [x[2] for x in ents]) + '\n'


_RX_SPEECH = re.compile(r'^(\d+):(\d{2}) \[[^\]]*\] (.*)$')
_RX_SCREEN = re.compile(r'^ЭКРАН (\d+):(\d{2})–(\d+):(\d{2}) «(.*)»$')
_RX_VLM = re.compile(r'^VLM (\d+):(\d{2}) (.*)$')


def parse_film(text: str, duration: float = 0.0) -> dict:
    """индекс ленты по секундам — строится один раз. Речь — одна пословная лента (цитата может перейти со строки на
    строку), надписи и описания кадров — каждая своей записью с промежутком времени."""
    words, wsec, marks, line_secs = [], [], [], []
    for ln in str(text or '').splitlines():
        m = _RX_SPEECH.match(ln)
        if m:
            sec = int(m.group(1)) * 60 + int(m.group(2))
            line_secs.append(sec)
            for w in TD.norm2(m.group(3)).split():
                words.append(w)
                wsec.append(sec)
            continue
        m = _RX_SCREEN.match(ln)
        if m:
            marks.append(dict(kind='screen', t0=int(m.group(1)) * 60 + int(m.group(2)),
                              t1=int(m.group(3)) * 60 + int(m.group(4)), norm=TD.norm2(m.group(5))))
            continue
        m = _RX_VLM.match(ln)
        if m:
            t = int(m.group(1)) * 60 + int(m.group(2))
            marks.append(dict(kind='vlm', t0=t, t1=t, norm=TD.norm2(m.group(3))))
    starts = sorted(set(line_secs))
    nxt = {s: (starts[i + 1] if i + 1 < len(starts) else s + 30) for i, s in enumerate(starts)}
    wend = [nxt[s] for s in wsec]                          # конец строки речи = начало следующей
    last = max(wsec + [m['t1'] for m in marks] + [0])
    return dict(words=words, wsec=wsec, wend=wend, marks=marks, duration=float(duration or 0) or float(last),
                blob=' ' + ' '.join(words) + ' ')


def find_quote(ix: dict, quote: str, sec, win: float = QUOTE_WIN) -> list:
    """где цитата стоит в ленте рядом с sec → [{'kind': speech|screen|vlm, 'sec', 'w0', 'w1'}]; sec=None — по всей ленте"""
    qn = TD.norm2(quote)
    if not qn:
        return []
    hits, n = [], len(qn.split())
    lo_t, hi_t = (-1e9, 1e9) if sec is None else (sec - win, sec + win)
    ws, we = ix['wsec'], ix['wend']
    lo = next((i for i in range(len(ws)) if we[i] > lo_t), len(ws))
    hi = bisect.bisect_right(ws, hi_t)                     # слова, чья строка началась не позже конца окна
    if lo < hi:
        pad = ' ' + ' '.join(ix['words'][lo:hi]) + ' '
        pos = pad.find(f' {qn} ')
        while pos >= 0:
            w0 = lo + pad[:pos].count(' ')
            hits.append(dict(kind='speech', sec=ws[w0], w0=w0, w1=w0 + n - 1))
            pos = pad.find(f' {qn} ', pos + 1)
    for m in ix['marks']:
        if m['t1'] >= lo_t and m['t0'] <= hi_t and f' {qn} ' in f' {m["norm"]} ':
            hits.append(dict(kind=m['kind'], sec=m['t0'], w0=None, w1=None))
    return hits


# ═══ 3. пункты и пакет ═══════════════════════════════════════════════════════════════════════════════════════
def look_of(r: dict, duration: float, thresholds: dict) -> str:
    sec = r.get('sec_new')
    if sec is None:
        old = r.get('sec_old')
        if old is None:
            return 'время в новом кате неизвестно: у пункта нет таймкода — искать по всей ленте'
        if old <= 120:
            return (f'время в новом кате неизвестно: пункт из начала прошлого ката ({tc_str(old)}), которое в новом кате '
                    f'вырезано или пересобрано — искать по всей ленте')
        return (f'время в новом кате неизвестно: в прошлом кате было на {tc_str(old)}, это место в новый кат '
                f'не перенеслось — искать по всей ленте')
    win = float((thresholds or {}).get('win_screen', 120) if r.get('category') == 'graphics'
                else (thresholds or {}).get('win_speech', 45)) + float(r.get('err') or 0)
    lo, hi = max(0.0, sec - win), (min(duration, sec + win) if duration else sec + win)
    s = f'{tc_str(lo)}–{tc_str(hi)}'
    return s + (' (примерно: место попало на стык склейки)' if r.get('how') == 'gap' else '')


def build_items(fb: dict, rows: list, patterns=None, film_norm: str = '') -> list:
    """patterns — темы фонда (feedback_model.load_patterns). targets берутся из ВСЕХ строк пункта, в том числе из тех, что
    в видимые блоки не вошли; цель из невидимой строки, которая попадает в тему фонда и не является репликой фильма
    (YTCH12: «Усыновление брата, его новое имя» — название строки стоп-листа), в облако не идёт."""
    dur, thr, out = float(fb.get('duration_sec') or 0), fb.get('thresholds') or {}, []
    for r in rows:
        assert not r.get('sensitive'), f'чувствительный пункт {r.get("n")} в пакете для облака'
        sb = V.short_blocks(r, fb)
        ev = r.get('evidence') or {}
        it = dict(n=r['n'], title=one(r.get('title')), category=r.get('category') or '', severity=r.get('severity') or '',
                  now=one((sb['now'] or [''])[0]), do=' ; '.join(one(x) for x in sb['do']),
                  where=one((sb['where'] or [''])[0]), look=look_of(r, dur, thr),
                  code_status=r.get('status'), code_by=r.get('status_by') or 'code',
                  code_evidence=one(ev.get('text')) + (f' · {ev["tc"]}' if ev.get('tc') else ''))
        targets = [one(c.get('q')) for c in (r.get('checks') or []) if one(c.get('q'))][:30]
        if patterns:
            vis = ' ' + TD.norm2(' '.join([it['title'], it['now'], it['do'], it['where']])) + ' '
            held = [t for t in targets if FM.topic_of(t, patterns)[0] and f' {TD.norm2(t)} ' not in vis
                    and f' {TD.norm2(t)} ' not in film_norm]
            if held:
                targets = [t for t in targets if t not in held]
                it['targets_held'] = len(held)             # сколько целей придержано — без их текста
        if targets:
            it['targets'] = targets
        out.append(it)
    return out


def make_packet(fb: dict, film: str, review_dir='', token_limit: int = TOKEN_LIMIT, patterns=None, exclude=()):
    """→ (пакет, счётчики). Не влезает в лимит — убираем хвост: самые поздние по времени «не проверено» с severity=should.
    exclude — номера, которые человек велел не отправлять (пункт по сути чувствительный, а флага в прошлом ТЗ нет)."""
    rows, stats = select(fb)
    excluded = sorted(r['n'] for r in rows if r['n'] in set(exclude))
    for r in rows:
        if r['n'] in set(exclude):
            stats[group_of(r)] -= 1                        # счётчики групп — по тому, что реально уходит
    rows = [r for r in rows if r['n'] not in set(exclude)]
    trimmed = []
    film_norm = (' ' + TD.norm2(film) + ' ') if patterns else ''

    def size(rs):
        return len(film) + len(dump(build_items(fb, rs, patterns, film_norm)))
    while est_tokens(size(rows)) > token_limit:
        cand = [r for r in rows if r.get('status') == 'unknown' and r.get('severity') != 'must']
        if not cand:
            break
        drop = max(cand, key=lambda r: (-1 if r.get('sec_new') is None else r['sec_new'], r['n']))
        rows = [r for r in rows if r is not drop]
        trimmed.append(drop['n'])
    items = build_items(fb, rows, patterns, film_norm)
    rel = 'cloud/in/' if review_dir else ''
    pk = dict(schema=ITEMS_SCHEMA, code=fb.get('code'), cut_version=fb.get('cut_version'),
              prev_cut_version=fb.get('prev_cut_version'), packet_sha=packet_sha(film, items),
              film=rel + FILM_NAME, out=('cloud/out/' if review_dir else '') + OUT_NAME,
              duration_sec=float(fb.get('duration_sec') or 0), n_items=len(items), trimmed=sorted(trimmed),
              excluded=excluded, items=items)
    stats.update(trimmed=len(trimmed), excluded=len(excluded), targets_held=sum(x.get('targets_held', 0) for x in items), sent=len(items), film_chars=len(film), items_chars=len(dump(pk)),
                 est_tokens=est_tokens(len(film) + len(dump(pk))))
    return pk, stats


def leak_report(fb: dict, pk: dict, film: str) -> dict:
    """ни один чувствительный пункт не ушёл: по номеру — assert; по тексту — счётчик совпадений заголовков
    (лента — это транскрипт фильма, реплика оттуда может совпасть с заголовком пункта; это видно в отчёте)"""
    sens = [r for r in fb.get('part2') or [] if r.get('sensitive')]
    sent = {it['n'] for it in pk['items']}
    assert not sent & {r['n'] for r in sens}, 'чувствительный пункт в пакете для облака'
    blob_items, blob_film = ' ' + TD.norm2(canon(pk['items'])) + ' ', ' ' + TD.norm2(film) + ' '
    common = {TD.norm2(r.get('title')) for r in fb.get('part2') or [] if not r.get('sensitive')}
    titles = {r['n']: TD.norm2(r.get('title')) for r in sens}     # типовой заголовок, общий с обычным пунктом, — не утечка
    titles = {n: t for n, t in titles.items() if len(t.split()) >= 3 and t not in common}
    return dict(sensitive=len(sens), in_items=sorted(n for n, t in titles.items() if f' {t} ' in blob_items),
                in_film=sorted(n for n, t in titles.items() if f' {t} ' in blob_film))


def workflow_call(args: dict) -> str:
    """строка вызова — её вынимает shared/headless_claude.extract_workflow_call: от «Workflow(» до последней «)»,
    поэтому она печатается ПОСЛЕДНЕЙ"""
    return 'Workflow({scriptPath: ' + json.dumps(str(WF)) + ', args: ' + json.dumps(args, ensure_ascii=False) + '})'


# ═══ 4. проверка вердикта ════════════════════════════════════════════════════════════════════════════════════
def _check_quote(ix, quote, sec):
    """→ (находки, причина отказа)"""
    if quote is not None and not isinstance(quote, str):
        return [], 'цитата не строка'
    q = one(quote)
    if not q:
        return [], 'нет цитаты'
    if len(q) > QUOTE_MAX:
        return [], 'цитата длиннее допустимого'
    if len(TD.norm2(q)) < QUOTE_MIN:
        return [], 'цитата слишком короткая, чтобы что-то доказать'
    if sec is None:
        return [], 'у цитаты нет таймкода'
    hits = find_quote(ix, q, sec)
    if hits:
        return hits, ''
    return [], ('цитата есть в фильме, но не рядом с указанным временем' if find_quote(ix, q, None)
                else 'такой цитаты в фильме нет')


def places_of(it: dict):
    """где пункт живёт в новом кате → [(с, по)] или None (время неизвестно — годится любое место). Окно look плюс таймкоды из
    текста пункта («перенести на ≈37:10»); у провала правила канала — только окно look."""
    lk = tc_secs(it.get('look'))
    if len(lk) < 2:
        return None
    out = [(lk[0] - QUOTE_WIN, lk[1] + QUOTE_WIN)]
    if it.get('code_by') != 'rule':
        pad = PLACE_PAD_SCREEN if it.get('category') == 'graphics' else PLACE_PAD
        out += [(s - pad, s + pad) for k in ('now', 'do', 'where') for s in tc_secs(it.get(k))]
    return out


def _in_place(hit, places) -> bool:
    return places is None or any(lo <= hit['sec'] <= hi for lo, hi in places)


def _pick(hits, source):
    want = {'speech': ('speech',), 'screen': ('screen', 'vlm'), 'vlm': ('vlm', 'screen')}.get(str(source or ''), ())
    return next((h for h in hits if h['kind'] in want), hits[0])


def assess(v: dict, ix: dict, pk: dict) -> dict:
    """решение по одному вердикту. Зависит ТОЛЬКО от вердикта, ленты и пакета (кодовый статус берётся из пакета, а не
    из текущей строки модели) — поэтому повторное вливание того же файла даёт тот же результат.
    → {'ok', 'why', 'status', 'hit', 'hit2', 'keep'}; keep=True — вердикт годен, но менять в строке нечего."""
    res = dict(ok=False, why='', status=None, hit=None, hit2=None, keep=False)
    if not isinstance(v, dict) or not is_n(v.get('n')):
        return {**res, 'why': 'ответ не по форме: номер пункта не целое число'}
    it = {x['n']: x for x in pk.get('items') or []}.get(v['n'])
    if it is None:
        return {**res, 'why': 'пункта с таким номером в отправленном списке нет'}
    st = v.get('status')
    if not isinstance(st, str) or st not in STATUSES:
        return {**res, 'why': 'непонятный ответ (не закрыто / осталось / не знаю)'}
    (sec, bad), (sec2, bad2) = tc_strict(v.get('tc')), tc_strict(v.get('tc2'))
    dur = float(pk.get('duration_sec') or ix.get('duration') or 0)
    if dur and any(s is not None and s > dur for s in (sec, sec2)):
        return {**res, 'why': 'таймкод за пределами фильма'}
    code, by = it.get('code_status'), it.get('code_by')
    conf = v.get('confidence')                             # строка «0.9», NaN, 1.5, true — не уверенность, а брак ответа
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not math.isfinite(conf) or not 0 <= conf <= 1:
        conf = None
    if st != 'unknown' and (bad or bad2):
        if st == 'open' and code == 'closed':              # сомнение агента остаётся сомнением и с битым таймкодом
            return {**res, 'ok': True, 'status': 'unknown', 'why': bad or bad2}
        return {**res, 'why': bad or bad2}
    if st == 'unknown':
        if code == 'closed':                               # сомнения достаточно, чтобы снять кодовое «закрыто»
            return {**res, 'ok': True, 'status': 'unknown'}
        return {**res, 'ok': True, 'status': code, 'keep': True}
    hits, why = _check_quote(ix, v.get('quote'), sec)
    if st == 'open':
        if hits:
            return {**res, 'ok': True, 'status': 'open', 'hit': _pick(hits, v.get('source'))}
        if code == 'closed':                               # «осталось» без доказательства поверх кодового «закрыто» → «не знаю»
            return {**res, 'ok': True, 'status': 'unknown', 'why': why}
        return {**res, 'why': why}
    # closed — надо доказать
    if conf is None:
        return {**res, 'why': '«закрыто» без уверенности числом от 0 до 1'}
    if conf < CONF_MIN:
        return {**res, 'why': f'«закрыто» с уверенностью ниже {CONF_MIN}'}
    if not hits:
        return {**res, 'why': why}
    if it.get('targets_held'):                             # часть целей придержана и агенту не показана — судить «всё на месте» ему не по чему
        return {**res, 'why': 'часть целей пункта в облако не отправлялась — «закрыто» по неполному списку не принимается'}
    places = places_of(it)
    if by == 'rule' and places is None:
        return {**res, 'why': 'правило канала: «закрыто» без цитаты из места, о котором пункт'}
    hits = [h for h in hits if _in_place(h, places)]       # настоящая цитата из ДРУГОГО места фильма ничего не закрывает
    if not hits:
        return {**res, 'why': ('правило канала: «закрыто» без цитаты из места, о котором пункт' if by == 'rule'
                               else 'цитата не из того места фильма, о котором пункт')}
    hit = _pick(hits, v.get('source'))
    if it.get('category') == 'cut':                        # вырез доказывается отсутствием: две цитаты вокруг стыка
        hits2, why2 = _check_quote(ix, v.get('quote2'), sec2 if sec2 is not None else sec)
        if not hits2:
            return {**res, 'why': 'вырез: нужна вторая цитата после стыка — ' + (why2 or 'её нет')}
        a = [h for h in hits if h['kind'] == 'speech']
        b = [h for h in hits2 if h['kind'] == 'speech']
        pair = next(((x, y) for x in a for y in b if x['w1'] < y['w0'] and y['w0'] - x['w1'] - 1 <= CUT_GAP_WORDS
                     and ix['wsec'][y['w0']] - ix['wsec'][x['w1']] <= CUT_GAP_SEC), None)
        if not pair:
            return {**res, 'why': 'вырез: цитаты не стоят вплотную по разные стороны стыка'}
        return {**res, 'ok': True, 'status': 'closed', 'hit': pair[0], 'hit2': pair[1]}
    return {**res, 'ok': True, 'status': 'closed', 'hit': hit}


def validate(verdict: dict, film_index: dict, packet: dict):
    """контракт §7: (ok, why). ok — вердикт проходит проверку (в том числе со снижением до «не знаю»)."""
    a = assess(verdict, film_index, packet)
    return a['ok'], a['why']


def check_file(check, pk: dict):
    """годится ли файл ответа целиком → (ok, why). Чужой кат или чужой пакет — отказ: это ответ по другой версии."""
    if not isinstance(check, dict) or not isinstance(check.get('verdicts'), list):
        return False, 'в файле ответа нет списка verdicts'
    if check.get('schema') not in (None, '', CHECK_SCHEMA):
        return False, f'схема ответа {check.get("schema")!r}, нужна {CHECK_SCHEMA}'
    if str(check.get('packet_sha') or '') != str(pk.get('packet_sha') or '-'):
        return False, (f'ответ по другому пакету: packet_sha {check.get("packet_sha")!r}, отправлен {pk.get("packet_sha")!r} '
                       f'(устаревший ответ — нужен новый запуск сверщика)')
    if str(check.get('cut_version') or '') != str(pk.get('cut_version') or '-'):
        return False, f'ответ по другому кату: {check.get("cut_version")!r}, отправлен {pk.get("cut_version")!r}'
    return True, ''


# ═══ 5. вливание ═════════════════════════════════════════════════════════════════════════════════════════════
def _bad_text(s: str) -> bool:
    return bool(V._has_tc(s) or EXTRA_JARGON.search(s) or any(rx.search(s) for rx in V.JARGON)
                or re.search(r'[A-Za-z]{4,}', s))


def clean_note(note) -> str:
    """фраза агента для читателя; с таймкодом, жаргоном или английскими словами — не берём (будет шаблон)"""
    s = one(note).rstrip('.;, ')
    s = s[:200].rsplit(' ', 1)[0] if len(s) > 200 else s
    return '' if (not s or _bad_text(s)) else s


def human_text(status, hit, note, quote, quote2='') -> str:
    """evidence.text: человеческая фраза БЕЗ таймкода (он живёт в evidence.tc) и без жаргона + цитата в «…»"""
    kind = hit['kind'] if hit else ''
    note = clean_note(note)
    base = {('closed', 'speech'): 'реплика на месте', ('closed', 'screen'): 'на экране',
            ('closed', 'vlm'): 'по описанию кадра — сделано', ('open', 'speech'): 'в новом кате по-прежнему звучит',
            ('open', 'screen'): 'на экране по-прежнему', ('open', 'vlm'): 'по описанию кадра — не сделано'}.get((status, kind), '')

    def q(s):
        return TD._cut(one(str(s or '').replace('|', ' ')).replace('«', '"').replace('»', '"'), 110)   # «|» — разделитель строк надписи
    if quote2:
        cands = [f'{note or "фразы больше нет"}: после «{q(quote)}» сразу идёт «{q(quote2)}»',
                 f'фразы больше нет: после «{q(quote)}» сразу идёт «{q(quote2)}»', note, 'фразы больше нет, стык чистый']
    elif kind == 'vlm':                                    # описание кадра — машинный английский текст, читателю не цитируем
        cands = [note, base]
    else:
        cands = [f'{note or base}: «{q(quote)}»', f'{base}: «{q(quote)}»', note, base]
    return next((c for c in cands if c and not (V._has_tc(c) or EXTRA_JARGON.search(c) or any(rx.search(c) for rx in V.JARGON))),
                base or 'проверено по тексту фильма')


def apply_check(fb: dict, check: dict, pk: dict, ix: dict, applied_at: str = '') -> dict:
    """вердикты → строки Части 2 (на месте), затем rebucket. → сводка. Файл целиком уже проверен check_file."""
    rows = {r['n']: r for r in fb.get('part2') or []}
    raw = check.get('verdicts') or []
    verdicts = [v for v in raw if isinstance(v, dict) and is_n(v.get('n'))]
    malformed = len(raw) - len(verdicts)                   # не словарь, n строкой / дробью / списком / true
    seen = {}
    for v in verdicts:
        seen[v['n']] = seen.get(v['n'], 0) + 1
    rejected, changed = {}, []
    by_status = dict(closed=0, open=0, unknown=0)
    accepted = unchanged = 0

    def reject(n, why, row=None):
        rejected.setdefault(why, [])
        if n not in rejected[why]:
            rejected[why].append(n)
        if row is not None:
            row['agent_note'] = f'ответ сверщика не принят: {why}'
    if malformed:
        rejected['ответ не по форме: номер пункта не целое число'] = ['?'] * malformed
    items = {x['n']: x for x in pk.get('items') or []}
    for v in verdicts:
        n = v.get('n')
        row, it = rows.get(n), items.get(n)
        if it is None or row is None or row.get('sensitive'):   # чувствительную строку ответ облака не трогает никогда
            reject(n, 'пункта с таким номером в отправленном списке нет')
            continue
        if seen.get(n, 0) > 1:                             # дубликат номера — выброшены оба: какому верить, неизвестно
            reject(n, 'по пункту пришло два ответа', row)
            continue
        a = assess(v, ix, pk)
        if row.get('status_by') != 'agent' and row.get('status') != it.get('code_status'):
            reject(n, 'вывод кода по пункту изменился после отправки', row)
            continue
        if not a['ok']:
            reject(n, a['why'], row)
            continue
        note = clean_note(v.get('note'))
        if a['keep']:                                      # агент не смог проверить — остаётся то, что было
            unchanged += 1
            row['agent_note'] = note or 'по тексту фильма проверить не удалось'
            continue
        accepted += 1
        by_status[a['status']] += 1
        if a['status'] != it.get('code_status'):
            changed.append({'n': n, 'from': it.get('code_status'), 'to': a['status']})
        row['agent_note'] = note
        if a['status'] == 'open' and it.get('code_by') == 'rule':
            continue                                       # правило канала проверено кодом: статус и доказательство правила остаются
        row['status'], row['status_by'] = a['status'], 'agent'
        if a['hit'] is None:                               # «не знаю» поверх кодового «закрыто»: доказательства нет
            row['evidence'] = None
            row['agent_note'] = note or ('кодовое «закрыто» не подтвердилось' + (f': {a["why"]}' if a['why'] else ''))
            continue
        h = a['hit2'] or a['hit']
        row['evidence'] = dict(kind='speech' if h['kind'] == 'speech' else 'screen', tc=tc_str(h['sec']), sec=int(h['sec']),
                               text=human_text(a['status'], a['hit'], v.get('note'), v.get('quote'),
                                               v.get('quote2') if a['hit2'] else ''))
    answered = set(seen)
    no_answer = sorted(x['n'] for x in pk['items'] if x['n'] not in answered)
    FM.rebucket(fb)
    fb['agent'] = dict(applied_at=applied_at, packet_sha=pk.get('packet_sha'), sent=len(pk['items']), accepted=accepted,
                       rejected=sum(len(x) for x in rejected.values()), unchanged=unchanged, no_answer=no_answer,
                       by_status=by_status, changed=sorted(changed, key=lambda c: c['n']),
                       rejected_why={k: sorted(x, key=str) for k, x in sorted(rejected.items())})
    return fb['agent']


def print_summary(ag: dict, tally: dict):
    print(f'сверщик: отправлено {ag["sent"]} · принято {ag["accepted"]} (закрыто {ag["by_status"]["closed"]} · осталось '
          f'{ag["by_status"]["open"]} · не знаю {ag["by_status"]["unknown"]}) · без изменений {ag["unchanged"]} · '
          f'отброшено {ag["rejected"]} · без ответа {len(ag["no_answer"])}')
    for why, ns in ag['rejected_why'].items():
        print(f'  отброшено · {why}: {", ".join(map(str, ns))}')
    for c in ag['changed']:
        print(f'  изменён вывод кода · {c["n"]}: {c["from"]} → {c["to"]}')
    print(f'итог: закрыто {tally["closed"]} · осталось {tally["open"]} · блюр {tally["blur"]} · фонд {tally["fund"]} · '
          f'не проверено {tally["unknown"]} (новых {tally["new"]}, прошлых {tally["prev_total"]})')


# ═══ 6. команды ══════════════════════════════════════════════════════════════════════════════════════════════
def _card():
    sys.path.insert(0, str(HERE.parent / 'stages'))
    from _bootstrap import P, W6, CLOUD                    # карточка нужна только командам
    return P, W6, CLOUD


def _load_vlm(p) -> list:
    p, out = Path(p), []
    if p.exists():
        for ln in p.read_text(encoding='utf-8').splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    return out


def cmd_print_call(a) -> int:
    P, W6, CLOUD = _card()
    fbp = Path(a.fb) if a.fb else W6 / 'feedback.json'
    fb = load_json(fbp)
    if fb is None:
        raise SystemExit(f'нет {fbp} — сначала shared/feedback_model.py (нужен ключ карточки prev_pravki)')
    if not fb.get('part2'):
        print('Часть 2 пуста (нет прошлого ТЗ — ключ prev_pravki): сверять нечего, вызов не печатается')
        return 0
    words = load_json(P.WORDS, {}) or {}
    screens = load_json(W6 / 'screens_v6.json', []) or []
    screens = screens.get('screens', []) if isinstance(screens, dict) else screens
    film = build_film(words, screens, _load_vlm(W6 / 'vlm_v6.jsonl'), fund_speaker=str(P.get('fund_speaker') or ''),
                      title=f'{fb.get("code")} {fb.get("cut_version")}')
    excl = [int(x) for x in re.findall(r'\d+', f'{a.exclude} {os.environ.get("YTAI_FEEDBACK_EXCLUDE", "")}')]
    pk, st = make_packet(fb, film, review_dir=str(P.REVIEW_DIR), patterns=FM.load_patterns(P), exclude=excl)
    leaks = leak_report(fb, pk, film)
    cin, cout = CLOUD / 'in', CLOUD / 'out'
    cout.mkdir(parents=True, exist_ok=True)
    write_atomic(cin / FILM_NAME, film)
    write_atomic(cin / ITEMS_NAME, dump(pk))
    print(f'пакет сверщика {fb.get("code")} {fb.get("cut_version")}: пунктов {st["sent"]} из {st["part2"]} — не проверено {st["unknown"]}'
          f'{(" (убрано по лимиту " + str(st["trimmed"]) + ")") if st["trimmed"] else ""} · кодовое «закрыто» {st["closed"]} · '
          f'обязательное «осталось» {st["must_open"]} · чувствительных исключено {st["sensitive_excluded"]}')
    print(f'лента {st["film_chars"]} знаков · пункты {st["items_chars"]} знаков · оценка {st["est_tokens"]} токенов '
          f'(лимит {TOKEN_LIMIT}) · packet_sha {pk["packet_sha"]}')
    if st['trimmed']:
        print(f'⚠️ пакет не влез в лимит: убрано {st["trimmed"]} самых поздних необязательных пунктов — они остаются '
              f'«не проверено»: {", ".join(map(str, pk["trimmed"]))}')
    if st['excluded']:
        print(f'исключено вручную (--exclude / YTAI_FEEDBACK_EXCLUDE): {", ".join(map(str, pk["excluded"]))} — остаются как были')
    if st['targets_held']:
        print(f'придержано целей из невидимых строк, попавших в темы фонда: {st["targets_held"]}')
    if leaks['in_items']:
        print(f'⚠️ заголовки чувствительных пунктов дословно встречаются в текстах отправляемых: {leaks["in_items"]}')
    if leaks['in_film']:
        print(f'ℹ️ заголовки чувствительных пунктов совпали с репликами фильма (лента — транскрипт, это допустимо): {leaks["in_film"]}')
    print(f'→ {cin / FILM_NAME}\n→ {cin / ITEMS_NAME}')
    if not pk['items']:
        print('отправлять нечего: все пункты решены кодом или чувствительные — вызов не печатается')
        return 0
    args = dict(code=fb.get('code'), cut_version=fb.get('cut_version'), prev_cut_version=fb.get('prev_cut_version'),
                film=P.FILM, film_path=str(cin / FILM_NAME), items_path=str(cin / ITEMS_NAME),
                out_path=str(cout / OUT_NAME), packet_sha=pk['packet_sha'], n_items=len(pk['items']),
                duration_sec=pk['duration_sec'], film_chars=st['film_chars'], est_tokens=st['est_tokens'])
    print(workflow_call(args))                             # последней строкой: после неё не должно быть ни одной «)»
    return 0


def cmd_apply(a) -> int:
    P = W6 = CLOUD = None
    if not (a.fb and a.packet and getattr(a, 'from')):
        P, W6, CLOUD = _card()
    fbp = Path(a.fb) if a.fb else W6 / 'feedback.json'
    pkp = Path(a.packet) if a.packet else CLOUD / 'in' / ITEMS_NAME
    src = Path(getattr(a, 'from')) if getattr(a, 'from') else CLOUD / 'out' / OUT_NAME
    fb, pk = load_json(fbp), load_json(pkp)
    try:
        check = load_json(src)
    except (ValueError, UnicodeDecodeError) as e:           # агент записал не JSON / файл оборван
        print(f'ОТКАЗ: файл ответа не читается как JSON ({str(e)[:80]})\n  файл ответа: {src}\n  модель не тронута', file=sys.stderr)
        return 2
    if fb is None:
        raise SystemExit(f'нет {fbp} — сначала shared/feedback_model.py')
    if pk is None:
        raise SystemExit(f'нет {pkp} — сначала --print-call')
    if check is None:
        raise SystemExit(f'нет {src} — воркфлоу ещё не отработал (или упал по лимиту: cloud/salvage.py --latest)')
    filmp = pkp.with_name(FILM_NAME)
    film = filmp.read_text(encoding='utf-8') if filmp.exists() else ''
    ok, why = check_file(check, pk)
    if ok and packet_sha(film, pk.get('items') or []) != pk.get('packet_sha'):
        ok, why = False, f'лента или пункты в {pkp.parent} изменились после отправки (packet_sha не сходится) — нужен новый --print-call'
    if ok and str(pk.get('cut_version')) != str(fb.get('cut_version')):
        ok, why = False, f'пакет собран по кату {pk.get("cut_version")}, модель — по {fb.get("cut_version")}'
    if not ok:
        print(f'ОТКАЗ: {why}\n  файл ответа: {src}\n  модель не тронута', file=sys.stderr)
        return 2
    at = datetime.datetime.fromtimestamp(src.stat().st_mtime).strftime('%Y-%m-%d %H:%M')   # время ответа, не «сейчас»
    ag = apply_check(fb, check, pk, parse_film(film, pk.get('duration_sec') or fb.get('duration_sec') or 0), at)
    out = Path(a.out) if a.out else fbp
    write_atomic(out, dump(fb))
    print_summary(ag, fb['tally'])
    bad = [x for x in V.lint(json.loads(dump(fb))) if x[0] == 'FAIL' and 'доказательств' in x[2]]   # на копии: lint метит строки
    for lvl, who, what in bad:
        print(f'⚠️ {who}: {what}')
    print(f'сверщик влит: принято {ag["accepted"]} из {ag["sent"]}, отброшено {ag["rejected"]} → {out}')
    return 0


def cmd_status() -> int:
    P, W6, CLOUD = _card()
    for name, p in (('модель', W6 / 'feedback.json'), ('лента', CLOUD / 'in' / FILM_NAME), ('пункты', CLOUD / 'in' / ITEMS_NAME),
                    ('ответ', CLOUD / 'out' / OUT_NAME)):
        print(f'  {"✅" if p.exists() else "—"} {name:8s} {p}')
    fb = load_json(W6 / 'feedback.json')
    if fb:
        _, st = select(fb)
        print(f'  к отправке: не проверено {st["unknown"]} · кодовое «закрыто» {st["closed"]} · обязательное «осталось» '
              f'{st["must_open"]} · чувствительных исключено {st["sensitive_excluded"]}'
              + (f' · влито {fb["agent"]["applied_at"]} ({fb["agent"]["packet_sha"]})' if fb.get('agent') else ''))
    return 0


# ═══ 7. самотест ═════════════════════════════════════════════════════════════════════════════════════════════
def _syn():
    """мини-модель и мини-лента: 9 пунктов прошлого ТЗ, фильм на 5:50"""
    def row(n, cat, status, by='code', sev='should', sens=False, sec=None, ev=None, title=None, checks=None, how='span'):
        return dict(part=2, n=n, label=f'ТЗ-{n:02d}', key=f'k{n}', title=title or f'пункт {n}', category=cat, severity=sev,
                    sensitive=sens, blocker=False, sec_old=sec, tc_old=tc_str(sec) if sec is not None else '',
                    sec_new=sec, tc_new=tc_str(sec) if sec is not None else '', err=0.5 if sec is not None else None,
                    how=how if sec is not None else 'none', tc_fixed=False,
                    parts=dict(now=[f'что не так в пункте {n}'], do=[f'что сделать в пункте {n}'], where=[tc_str(sec or 0)]),
                    more=0, status=status, status_by=by, evidence=ev, checks=checks or [],
                    bucket='appendix' if status == 'unknown' else status, dup_of=None, topic='adoption' if sens else None,
                    topic_title='Тайна усыновления' if sens else None, frame=None, typo=[], agent_note='')
    ev_c = dict(kind='screen', tc='0:10', sec=10, text='на экране: «СВОЙ ДОМ»')
    ev_r = dict(kind='rule', tc='3:00', sec=180, text='фонд впервые звучит на 3-й минуте, правило канала — не раньше 5-й')
    part2 = [
        row(1, 'graphics', 'closed', ev=ev_c, sec=10, title='титул «Свой дом»', checks=[dict(q='СВОЙ ДОМ', found=True, tc='0:10', score=1.0)]),
        row(2, 'cut', 'unknown', sec=60, title='вырезать фразу про кредит'),
        row(3, 'cut', 'unknown', sec=120, title='вырезать повтор про интернат'),
        row(4, 'fund', 'fund', by='flag', sev='must', sens=True, sec=90, title='тайна усыновления секретное слово абракадабра'),
        row(5, 'graphics', 'closed', ev=dict(ev_c, tc='1:40', sec=100, text='на экране: «КУРАТОР ФОНДА»'), sec=100, title='подпись куратора'),
        row(6, 'structure', 'open', by='rule', sev='must', sec=180, ev=ev_r, title='фонд входит слишком рано'),
        row(7, 'insert', 'unknown', sev='must', title='тизер пересобрать'),
        row(8, 'insert', 'open', sec=200, ev=dict(kind='speech', tc='3:20', sec=200, text='реплика на месте'), title='необязательное осталось'),
        row(9, 'color', 'unknown', sec=300, title='выровнять цвет в финале'),
        row(10, 'graphics', 'unknown', sec=330, title='подпись в самом конце'),
    ]
    fb = dict(schema='feedback-v1', code='YTSYN01', cut_version='v2', prev_cut_version='v1', built_at='2026-01-01 10:00',
              build_no=1, duration_sec=350.0, thresholds=dict(win_speech=45, win_screen=120), tally={}, blockers=[],
              fund_topics=[], part1=[], part2=part2)
    FM.rebucket(fb)
    seg = lambda t, sp, txt: dict(start=t, end=t + 4, speaker=sp, text=txt)   # noqa: E731
    words = dict(duration_sec=350.0, segments=[
        seg(8, 'Speaker 1', 'Мама отдала меня в интернат, потому что мы плохо жили.'),
        seg(55, 'Speaker 1', 'Я тогда работала на двух работах без выходных,'),
        seg(59, 'Speaker 1', 'и всё равно мы как-то справились с этим.'),
        seg(118, 'Speaker 1', 'В интернате нас кормили три раза в день.'),
        seg(122, 'Speaker 1', 'В интернате нас кормили три раза в день, я помню.'),
        seg(180, 'Speaker 2', 'Наш фонд помогает выпускникам детских домов.'),
        seg(300, 'Speaker 1', 'Теперь у нас свой дом и всё хорошо.')])
    screens = [dict(t0=10, t1=14, text_best='СВОЙ | ДOM', texts_all=['СВОЙ | ДOM', 'CBOЙ ДОМ фильм']),
               dict(t0=182, t1=186, text_best='ЖИМАГУЛ ПАНФИЛОВА | куратор фонда', texts_all=[])]
    vlm = [dict(id='s001', t0=10, vlm_text='СВОЙ\nДОМ', vlm_desc='This is a title card.')]
    return fb, words, screens, vlm


def selftest() -> int:
    import copy
    import tempfile
    n_ok = [0]

    def ok(cond, what):
        if not cond:
            raise SystemExit(f'SELFTEST FAIL: {what}')
        n_ok[0] += 1
    fb, words, screens, vlm = _syn()
    film = build_film(words, screens, vlm, fund_speaker='Speaker 2', title='YTSYN01 v2')
    pk, st = make_packet(fb, film)
    ns = [it['n'] for it in pk['items']]
    # кому
    ok(4 not in ns and st['sensitive_excluded'] == 1, 'чувствительный пункт не уходит в пакет')
    ok('абракадабра' not in dump(pk) and 'абракадабра' not in film, 'текст чувствительного пункта не попал ни в пункты, ни в ленту')
    ok(8 not in ns and ns == [7, 1, 2, 5, 3, 6, 9, 10], f'состав и порядок по времени: {ns}')
    ok((st['unknown'], st['closed'], st['must_open']) == (5, 2, 1), f'группы: {st}')
    lr = leak_report(fb, pk, film)
    ok(lr == dict(sensitive=1, in_items=[], in_film=[]), f'отчёт об утечках: {lr}')
    bad = copy.deepcopy(fb)
    bad['part2'][1]['sensitive'] = True
    try:
        build_items(bad, [bad['part2'][1]])
        ok(False, 'assert на чувствительном пункте')
    except AssertionError:
        ok(True, '')
    it7, it1 = pk['items'][0], pk['items'][1]
    ok('неизвестно' in it7['look'] and 'по всей ленте' in it7['look'], f'look без времени: {it7["look"]}')
    ok(it1['look'] == '0:00–2:10' and pk['items'][2]['look'] == '0:14–1:45', 'окно: графика ±120 с, речь ±45 с (+ погрешность)')
    ok(it1['code_evidence'] == 'на экране: «СВОЙ ДОМ» · 0:10' and it1['targets'] == ['СВОЙ ДОМ'], 'code_evidence и targets')
    # лента
    ok('0:08 [С1] Мама отдала' in film and 'ЭКРАН 0:10–0:14 «СВОЙ | ДOM / CBOЙ ДОМ фильм»' in film and 'VLM 0:10 This is' in film, 'три вида строк ленты')
    ok(film.index('ЭКРАН 3:02') > film.index('3:00 [С2]'), 'лента хронологическая')
    # устойчивость
    pk2, _ = make_packet(copy.deepcopy(fb), build_film(words, screens, vlm, fund_speaker='Speaker 2', title='YTSYN01 v2'))
    ok(pk2['packet_sha'] == pk['packet_sha'] and len(pk['packet_sha']) == 8, 'packet_sha стабилен')
    fb3 = copy.deepcopy(fb)
    fb3['part2'][1]['title'] += '!'
    ok(make_packet(fb3, film)[0]['packet_sha'] != pk['packet_sha'], 'packet_sha меняется вместе с пунктами')
    # лимит: убирается хвост необязательных «не проверено», обязательные и кодовые остаются
    small, st_s = make_packet(fb, film, token_limit=est_tokens(len(film) + len(dump(pk['items']))) - 40)   # лимит считается по ленте + пунктам
    ok(small['trimmed'] and small['trimmed'][-1] == 10 and 7 in [x['n'] for x in small['items']]
       and 1 in [x['n'] for x in small['items']] and st_s['trimmed'] == len(small['trimmed']), f'урезание хвоста: {small["trimmed"]}')
    # вызов
    import headless_claude as HC                           # без побочных эффектов на импорте
    line = workflow_call(dict(code='YTSYN01', film='фильм (тест)', packet_sha=pk['packet_sha'], n_items=len(ns)))
    got = HC.extract_workflow_call('пакет сверщика (8 пунктов)\n→ путь\n' + line + '\n')
    ok(got == line and json.loads(got[got.index('args: ') + 6:-2])['packet_sha'] == pk['packet_sha'], 'вызов разбирается extract_workflow_call')

    ix = parse_film(film, 350.0)
    V_ = lambda **k: dict(dict(tc='', quote='', source='speech', confidence=0.9, note=''), **k)   # noqa: E731
    # проверка вердиктов по одному
    ok(validate(V_(n=9, status='open', tc='5:00', quote='у нас свой дом и всё хорошо'), ix, pk) == (True, ''), 'дословная цитата принята')
    ok(validate(V_(n=9, status='open', tc='5:00', quote='мы купили большую квартиру в центре'), ix, pk)
       == (False, 'такой цитаты в фильме нет'), 'выдуманная цитата')
    ok(validate(V_(n=9, status='open', tc='0:08', quote='у нас свой дом и всё хорошо'), ix, pk)
       == (False, 'цитата есть в фильме, но не рядом с указанным временем'), 'цитата в 5 минутах от tc')
    ok(validate(V_(n=9, status='open', tc='9:59', quote='у нас свой дом и всё хорошо'), ix, pk)
       == (False, 'таймкод за пределами фильма'), 'tc больше длительности')
    ok(validate(V_(n=77, status='open', tc='5:00', quote='у нас свой дом'), ix, pk)[0] is False, 'n вне пакета')
    ok(validate(V_(n=10, status='closed', tc='5:00', quote='у нас свой дом и всё хорошо', confidence=0.6), ix, pk)
       == (False, '«закрыто» с уверенностью ниже 0.8'), 'closed с confidence 0.6')
    ok(validate(V_(n=9, status='open', tc='5:00', quote='дом'), ix, pk)[0] is False, 'слишком короткая цитата')
    ok(validate(V_(n=2, status='closed', tc='0:55', quote='работала на двух работах без выходных'), ix, pk)[0] is False,
       'вырез с одной цитатой')
    ok(validate(V_(n=2, status='closed', tc='0:55', quote='работала на двух работах без выходных', tc2='0:59',
                   quote2='и всё равно мы как-то справились'), ix, pk) == (True, ''), 'вырез с двумя цитатами вокруг стыка')
    ok(validate(V_(n=2, status='closed', tc='0:59', quote='и всё равно мы как-то справились', tc2='0:55',
                   quote2='работала на двух работах без выходных'), ix, pk)[0] is False, 'вырез: цитаты не по ту сторону стыка')
    ok(validate(V_(n=2, status='closed', tc='0:55', quote='работала на двух работах', tc2='2:02',
                   quote2='В интернате нас кормили'), ix, pk)[0] is False, 'вырез: вторая цитата далеко от первой')
    ok(validate(V_(n=6, status='closed', tc='5:00', quote='у нас свой дом и всё хорошо'), ix, pk)[0] is False,
       'правило канала не снимается цитатой из другого места')
    ok(validate(V_(n=1, status='closed', tc='0:10', quote='СВОЙ ДОМ', source='screen'), ix, pk) == (True, ''),
       'надпись найдена несмотря на латинские двойники букв')
    # подделки ответа: ни одна не даёт «закрыто» и ни одна не роняет приём
    C1 = dict(n=1, status='closed', tc='0:10', quote='СВОЙ ДОМ', source='screen')      # сам по себе — годный «закрыто»
    for what, conf in (('строкой', '0.9'), ('NaN', float('nan')), ('1.5', 1.5), ('true', True), ('бесконечность', float('inf')),
                       ('null', None), ('отрицательная', -1), ('списком', [0.9])):
        ok(validate(V_(**dict(C1, confidence=conf)), ix, pk)[0] is False, f'closed с уверенностью {what}')
    for tc in ('99:99', '-0:10', '0:75', 10, {'a': 1}, 'около 0:10', '1:75:00', None, ''):
        ok(validate(V_(**dict(C1, tc=tc)), ix, pk)[0] is False, f'closed с таймкодом {tc!r}')
    ok(tc_strict('≈0:10') == (10, '') and tc_strict('1:02:03') == (3723, '') and tc_strict('0:10–0:14') == (10, '')
       and tc_strict('') == (None, '') and tc_strict('-0:10')[1] and tc_strict('99:99')[1] and tc_strict(675)[1], 'строгий разбор таймкода')
    for n_bad in ('1', 1.0, True, [1], {'x': 1}, None):
        ok(validate(V_(**dict(C1, n=n_bad)), ix, pk)[0] is False, f'n не целым числом: {n_bad!r}')
    ok(validate(V_(**dict(C1, status='done')), ix, pk)[0] is False and validate(V_(**dict(C1, status=['closed'])), ix, pk)[0] is False
       and validate('closed', ix, pk)[0] is False, 'status «done» / списком / вердикт не словарь')
    ok(validate(V_(**dict(C1, quote=['СВОЙ ДОМ'])), ix, pk)[0] is False and validate(V_(**dict(C1, quote='   ')), ix, pk)[0] is False,
       'цитата списком / из пробелов')
    ok(validate(V_(n=1, status='closed', tc='5:00', quote='у нас свой дом и всё хорошо'), ix, pk)
       == (False, 'цитата не из того места фильма, о котором пункт'), 'настоящая цитата из другого места фильма ничего не закрывает')
    ok(validate(V_(n=7, status='closed', tc='5:00', quote='у нас свой дом и всё хорошо'), ix, pk) == (True, ''),
       'у пункта без времени годится любое место')
    ok(validate(V_(n=2, status='closed', tc='0:55', quote='работала на двух работах без выходных', tc2='0:55',
                   quote2='работала на двух работах без выходных'), ix, pk)[0] is False, 'вырез с двумя одинаковыми цитатами')
    ok(validate(V_(n=2, status='closed', tc='0:55', quote='Я тогда работала на двух', tc2='0:59', quote2='мы как-то справились'),
                ix, pk)[0] is False, 'вырез: между цитатами помещается целая фраза')
    ok(validate(V_(**C1), ix, pk) == (True, ''), 'контроль: тот же вердикт без подделки принят')
    # файл целиком
    good = dict(schema=CHECK_SCHEMA, cut_version='v2', packet_sha=pk['packet_sha'], verdicts=[])
    ok(check_file(good, pk)[0] and not check_file(dict(good, packet_sha='deadbeef'), pk)[0]
       and not check_file(dict(good, cut_version='v1'), pk)[0] and not check_file({'verdicts': 1}, pk)[0], 'чужой packet_sha / кат → отказ файла')
    # вливание
    check = dict(good, verdicts=[
        V_(n=1, status='closed', tc='0:10', quote='СВОЙ ДОМ', source='screen', note='Титул стоит в начале фильма.'),
        V_(n=5, status='open', tc='3:02', quote='ЖИМАГУЛ ПАНФИЛОВА', source='screen', note='подпись стоит на 3:02, а просили на 1:40'),
        V_(n=2, status='closed', tc='0:55', quote='работала на двух работах без выходных', tc2='0:59',
           quote2='и всё равно мы как-то справились', note='фразы про кредит больше нет'),
        V_(n=3, status='open', tc='2:02', quote='В интернате нас кормили три раза в день, я помню', note='повтор про интернат остался'),
        V_(n=6, status='open', tc='3:00', quote='Наш фонд помогает выпускникам', note='фонд по-прежнему входит рано'),
        V_(n=7, status='unknown', note='по тексту не проверить'),
        V_(n=9, status='closed', tc='5:00', quote='мы купили большую квартиру', note='выдумка'),
        V_(n=10, status='open', tc='5:00', quote='у нас свой дом'), V_(n=10, status='unknown'),
        V_(n=77, status='closed', tc='0:10', quote='СВОЙ ДОМ'),
        V_(n=4, status='closed', tc='0:10', quote='СВОЙ ДОМ')])
    fb_a = copy.deepcopy(fb)
    before4 = copy.deepcopy(next(r for r in fb_a['part2'] if r['n'] == 4))
    ag = apply_check(fb_a, check, pk, ix, '2026-01-01 12:00')
    R = {r['n']: r for r in fb_a['part2']}
    ok(R[1]['status'] == 'closed' and R[1]['status_by'] == 'agent' and R[1]['evidence']['kind'] == 'screen'
       and R[1]['evidence']['text'] == 'Титул стоит в начале фильма: «СВОЙ ДОМ»', f'подтверждённое закрыто: {R[1]["evidence"]}')
    ok(R[5]['status'] == 'open' and R[5]['status_by'] == 'agent' and R[5]['bucket'] == 'open'
       and R[5]['evidence'] == dict(kind='screen', tc='3:02', sec=182, text='на экране по-прежнему: «ЖИМАГУЛ ПАНФИЛОВА»'),
       f'open поверх кодового closed; заметка с таймкодом заменена шаблоном: {R[5]["evidence"]}')
    ok(R[2]['status'] == 'closed' and R[2]['bucket'] == 'closed' and 'сразу идёт' in R[2]['evidence']['text'], 'вырез закрыт двумя цитатами')
    ok(R[3]['status'] == 'open' and R[3]['evidence']['tc'] == '2:02', 'open поверх unknown с цитатой')
    ok(R[6]['status_by'] == 'rule' and R[6]['evidence']['kind'] == 'rule' and R[6]['agent_note'] and R[6]['blocker'],
       'подтверждённый провал правила: доказательство правила остаётся')
    ok(R[7]['status'] == 'unknown' and R[7]['status_by'] == 'code' and ag['unchanged'] == 1, 'агент не знает — строка как была')
    ok(R[9]['status'] == 'unknown' and 'не принят' in R[9]['agent_note'], 'выдуманная цитата: статус не меняется, причина в agent_note')
    ok(R[10]['status'] == 'unknown' and R[10]['status_by'] == 'code' and ag['rejected_why']['по пункту пришло два ответа'] == [10],
       'дубликат n — выброшены оба')
    ok(R[4] == before4, 'чувствительную строку ответ облака не трогает')
    ok(ag['accepted'] == 5 and ag['rejected'] == 4 and ag['sent'] == 8 and ag['no_answer'] == []
       and ag['by_status'] == dict(closed=2, open=3, unknown=0), f'сводка: {ag}')
    ok(ag['changed'] == [{'n': 2, 'from': 'unknown', 'to': 'closed'}, {'n': 3, 'from': 'unknown', 'to': 'open'},
                         {'n': 5, 'from': 'closed', 'to': 'open'}], f'что изменилось: {ag["changed"]}')
    ok(fb_a['tally']['closed'] == 2 and fb_a['tally']['unknown'] == 2 and fb_a['tally'] == FM.tally_of(fb_a['part1'], fb_a['part2'])
       and fb_a['tally'] != fb['tally'], f'tally пересчитан: {fb_a["tally"]}')
    ok(fb_a['build_no'] == 1 and fb_a['agent']['applied_at'] == '2026-01-01 12:00', 'build_no не тронут, время — из файла ответа')
    for r in fb_a['part2']:
        t = (r.get('evidence') or {}).get('text') or ''
        ok(not V._has_tc(t) and not EXTRA_JARGON.search(t) and not any(rx.search(t) for rx in V.JARGON), f'evidence.text чистый: {t}')
    fails = [x for x in V.lint(copy.deepcopy(fb_a)) if x[0] == 'FAIL']     # lint помечает строки служебными полями — на копии
    ok(not fails, f'линтер представления: {fails}')
    # мусор в списке вердиктов и лишние поля
    fb_g = copy.deepcopy(fb)
    ag_g = apply_check(fb_g, dict(good, verdicts=['closed', None, 7, V_(**dict(C1, n=[1])), V_(**dict(C1, n=True)), V_(**dict(C1, n='1')),
                                                  V_(**dict(C1, n=5, tc='1:40', evil='x', status_by='code', sensitive=True, bucket='closed'))]),
                       pk, ix, 'x')
    Rg = {r['n']: r for r in fb_g['part2']}
    ok(ag_g['rejected'] == 7 and ag_g['accepted'] == 0 and Rg[1] == {r['n']: r for r in fb['part2']}[1], f'мусорные вердикты отброшены: {ag_g}')
    ok('evil' not in Rg[5] and Rg[5]['sensitive'] is False and Rg[5]['status_by'] == 'code', 'лишние поля вердикта в модель не попадают')
    # вторая защита targets и ручное исключение
    import re as _re
    pats = [dict(key='adoption', rx=_re.compile(r'усынов\w*'), topic='тайна усыновления')]
    fb_t = copy.deepcopy(fb)
    fb_t['part2'][8]['checks'] = [dict(q='Усыновление брата, его новое имя'), dict(q='Теперь у нас свой дом'), dict(q='Новая глава')]
    pk_t, st_t = make_packet(fb_t, film, patterns=pats, exclude=[10])
    it9 = next(x for x in pk_t['items'] if x['n'] == 9)
    ok(it9['targets'] == ['Теперь у нас свой дом', 'Новая глава'] and it9['targets_held'] == 1 and st_t['targets_held'] == 1
       and 'сыновлен' not in dump(pk_t), f'цель из темы фонда придержана: {it9}')
    ok(validate(V_(n=9, status='closed', tc='5:00', quote='у нас свой дом и всё хорошо'), parse_film(film, 350.0), pk_t)[0] is False
       and validate(V_(n=9, status='closed', tc='5:00', quote='у нас свой дом и всё хорошо'), ix, pk)[0] is True,
       '«закрыто» по неполному списку целей не принимается')
    ok(10 not in [x['n'] for x in pk_t['items']] and pk_t['excluded'] == [10] and st_t['excluded'] == 1, 'ручное исключение пункта')
    # скрипт воркфлоу: без случайности и времени, путь результата — из args, цитата — дословная
    if WF.exists():
        js = WF.read_text(encoding='utf-8')
        ok(not _re.search(r'Date\.now|Math\.random|new Date|: string\b|: number\b|\binterface\b', js), 'JS без времени, случайности и TypeScript')
        ok('A.out_path' in js and 'A.items_path' in js and 'A.film_path' in js and 'ДОСЛОВНАЯ' in js and 'ДО возврата' in js
           and "effort: 'high'" in js and js.count('await agent(') == 1, 'JS: один агент, пути из args, файл до возврата')
    # сомнение без цитаты снимает кодовое «закрыто»
    fb_b = copy.deepcopy(fb)
    apply_check(fb_b, dict(good, verdicts=[V_(n=1, status='open', note='титула не видно'), V_(n=5, status='unknown')]), pk, ix, 'x')
    Rb = {r['n']: r for r in fb_b['part2']}
    ok(Rb[1]['status'] == 'unknown' and Rb[1]['evidence'] is None and Rb[1]['bucket'] == 'appendix' and Rb[5]['status'] == 'unknown'
       and Rb[5]['status_by'] == 'agent', 'open без цитаты / unknown поверх кодового closed → unknown')
    # повторное вливание ничего не меняет
    again = copy.deepcopy(fb_a)
    apply_check(again, check, pk, ix, '2026-01-01 12:00')
    ok(dump(again) == dump(fb_a), 'повторный apply идемпотентен')
    # команда целиком: файлы, отказ, --out
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / 'in').mkdir()
        write_atomic(td / 'in' / FILM_NAME, film)
        write_atomic(td / 'in' / ITEMS_NAME, dump(pk))
        write_atomic(td / 'fb.json', dump(fb))
        write_atomic(td / 'check.json', dump(check))
        write_atomic(td / 'stale.json', dump(dict(check, packet_sha='00000000')))
        ns_ = argparse.Namespace(fb=str(td / 'fb.json'), packet=str(td / 'in' / ITEMS_NAME), out=str(td / 'out.json'))
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            setattr(ns_, 'from', str(td / 'stale.json'))
            rc_stale = cmd_apply(ns_)
            stale_wrote = (td / 'out.json').exists()
            setattr(ns_, 'from', str(td / 'check.json'))
            rc1 = cmd_apply(ns_)
            first = (td / 'out.json').read_text(encoding='utf-8')
            ns_.fb = str(td / 'out.json')
            rc2 = cmd_apply(ns_)
        ok(rc_stale == 2 and not stale_wrote, 'чужой packet_sha → код возврата 2, модель не тронута')
        ok(rc1 == 0 and rc2 == 0 and first == (td / 'out.json').read_text(encoding='utf-8'), 'повторный --apply по уже влитой модели — байт-в-байт')
        ok(load_json(td / 'fb.json') == json.loads(dump(fb)), '--out: исходная модель не перезаписана')
        write_atomic(td / 'broken.json', '{"schema": "feedback-check-v1", verdicts: [')
        setattr(ns_, 'from', str(td / 'broken.json'))
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            ok(cmd_apply(ns_) == 2, 'файл ответа не JSON → отказ файла без трейсбека')
        setattr(ns_, 'from', str(td / 'check.json'))
        write_atomic(td / 'in' / FILM_NAME, film + '9:99 [С1] подмена\n')
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            ok(cmd_apply(ns_) == 2, 'лента изменилась после отправки → отказ')
    print(f'SELFTEST OK · {n_ok[0]} проверок')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--print-call', action='store_true')
    g.add_argument('--apply', action='store_true')
    g.add_argument('--status', action='store_true')
    g.add_argument('--selftest', action='store_true')
    ap.add_argument('--from', default='', help='файл ответа агента (иначе cloud/out/feedback_check.json)')
    ap.add_argument('--out', default='', help='--apply: куда записать модель (иначе на место work/{cut}/feedback.json)')
    ap.add_argument('--fb', default='', help='модель (иначе work/{cut}/feedback.json по карточке)')
    ap.add_argument('--exclude', default='', help='--print-call: номера пунктов через запятую, которые не отправлять '
                    '(то же — env YTAI_FEEDBACK_EXCLUDE); пункт остаётся как был')
    ap.add_argument('--packet', default='', help='--apply: пакет пунктов (иначе cloud/in/feedback_items.json); лента — рядом')
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.print_call:
        return cmd_print_call(a)
    if a.apply:
        return cmd_apply(a)
    return cmd_status()


if __name__ == '__main__':
    sys.exit(main())
