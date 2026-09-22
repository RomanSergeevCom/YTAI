#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feedback_view — общий слой представления «Обратной связи по кату vN» (контракт docs/feedback_v1.md §4–§5, §7).

Зачем: у документа две поверхности — HTML продюсеру (shared/feedback_page.py) и вкладка дока монтажёру
(stages/doc_tab_feedback_v1.py). Чтобы они не разошлись в порядке секций, лимитах строк, подписях кадров и
формулировках шапки, всё это считается ЗДЕСЬ, один раз. Поверхности только раскладывают готовое по своей разметке.

Слой ничего не решает за модель: статусы, buckets, blockers, dup_of берутся из work/{cut}/feedback.json как есть.
Здесь только порядок, лимиты видимого текста и слова (через shared/i18n_strings/fb.py).

    import feedback_view as V
    fb = V.load()                                  # work/{cut}/feedback.json по карточке; V.load(path) — без карточки
    for kind, text in V.head(fb): ...              # первый экран = ДЕЙСТВИЯ
    for bucket, label, rows in V.sections(fb): ... # new, block, open, blur, closed, fund, appendix; пустые пропущены

sections(fb)      → [(bucket, label, rows)]; строки отсортированы по времени нового ката (без времени — первыми;
                    в blur обязательные — первыми). Заодно помечает строки служебными _cut/_prev (версии для подписей).
head(fb, …)       → [(kind, text)], kind ∈ h1|meta|warn|tally|list_head|list_item|how. Порядок: заголовок → версия →
                    предупреждение о копии Части 1 → итог → «Держит выпуск — монтаж» (≤8 строк «таймкод ▸ действие») →
                    «Держит выпуск — не монтаж» → «Как читать» (первая строка how — заголовок списка).
blocker_items(fb) → [{'text', 'part', 'n'}] — те же ≤8 строк, что list_item в head(), с адресом пункта (для якорей HTML).
short_blocks(row) → {'now', 'do', 'where', 'more_line', 'rest'}: ❌ 1 · ✅ ≤4 · 📍 1; строка > 240 знаков режется по границе
                    предложения, без многоточий; 'rest' — [(ключ блока, строка)] того, что не вошло (HTML прячет в <details>).
list_line(row)    → «таймкод ▸ что · доказательство» — таймкод ОДИН, в начале (списки closed / fund / appendix).
caption(row)      → «M:SS · что видно» строго по CAP_RE (stages/doc_pdf_qc.py:59); '' если у строки нет кадра.
num_label(row)    → «ТЗ-04» (Часть 1) / «ТЗ-40 · v4» (Часть 2).
fund_groups(rows) → [(key, title, rows)] по темам фонда.  dup_line(row) → «11:16 ▸ не закрыто · перенесено в новое ТЗ-04 (Часть 1)».
tc_label(row)     → таймкод пункта с «≈», если место в новом кате найдено примерно (err > 2 с, стык, вырезанное).
clean_summary(fb) → строки вердикта без слов движка (≤5).
typo_pairs(row)   → [(было, стало)] (только Часть 1).  lint(fb) → [(уровень, номер, что не так)] — жаргон и ≥2 таймкода в строке.

Никакого proj_config на уровне модуля: карточка нужна только load() без пути.
"""
import json
import re
import sys
from pathlib import Path

try:
    import i18n  # noqa: E402
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import i18n  # noqa: E402

ORDER = ('new', 'block', 'open', 'blur', 'closed', 'fund', 'appendix')
PART2 = ('block', 'open', 'blur', 'closed', 'fund', 'appendix')     # секции под общим заголовком «ЧАСТЬ 2»
LIMITS = {'now': 1, 'do': 4, 'where': 1}                            # контракт §5 — одни для обеих поверхностей
MAX_LINE = 240
MAX_BLOCKERS = 8
ARROW = ' ▸ '

# таймкод как в stages/doc_pdf_qc.py (TC): диапазон «M:SS–M:SS» — ОДИН таймкод
TC = r'[~≈]?\d{1,2}:\d{2}(?:\.\d+)?(?:\s*[–-]\s*\d{1,2}:\d{2}(?:\.\d+)?)?'
TCR = re.compile(rf'(?<![\d:]){TC}(?![\d:])')
# шаблон подписи канона — копия stages/doc_pdf_qc.py:59 (сам файл не импортируем: он тянет карточку)
CAP_RE = re.compile(r'^(?:\d{1,2}:\d{2}(?:[–-]\d{1,2}:\d{2})?|сводно)\s·\s\S')
# что не должно попасть читателю: слова движка, имена полей модели, имена кадров (h0677, f0061, s031)
JARGON = [re.compile(r'\b(?:align\w*|OCR|VLM|overlap|status_by|bucket|dup_of|score)\b', re.I),
          re.compile(r'(?<![\w/.-])[hsf]\d{3,4}(?![\w-])'),
          re.compile(r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b')]      # имена правил и полей: fund_entry_min, last_sound_rule
# после этих сокращений точка — не конец предложения
ABBR = {'т', 'е', 'г', 'ул', 'см', 'руб', 'мин', 'сек', 'тыс', 'млн', 'стр', 'им', 'др', 'пр', 'гг', 'vs', 'etc'}
_SENT = re.compile(r'[.!?]["»”)]?\s+(?=[A-ZА-ЯЁ«“"(\d❌✅📍⚠])')
_CLAUSE = re.compile(r'(?:;|\s—|,)\s+')


# ── мелочи ───────────────────────────────────────────────────────────────────
def plural(key, n, **kw):
    """строка с формой числа: значение ключа — список форм (ru: 1 / 2–4 / 5+; en: 1 / много) или обычный шаблон."""
    forms = i18n.T(key)
    if isinstance(forms, str):
        return forms.format(n=n, **kw)
    k = abs(int(n))
    if len(forms) == 2:
        f = forms[0] if k == 1 else forms[1]
    elif k % 10 == 1 and k % 100 != 11:
        f = forms[0]
    elif 2 <= k % 10 <= 4 and not 12 <= k % 100 <= 14:
        f = forms[1]
    else:
        f = forms[2]
    return f.format(n=n, **kw)


def _tc(row):
    return str(row.get('tc_new') or '').strip()


def is_rough(row):
    """место пункта Части 2 в новом кате найдено примерно — то же правило, что у «≈» в тексте модели
    (feedback_model.retime_text): погрешность > 2 с либо время попало на стык кусков / в вырезанное."""
    if row.get('part') == 1 or row.get('sec_new') is None:
        return False
    return float(row.get('err') or 0) > 2 or row.get('how') in ('gap', 'dropped')


def tc_label(row):
    """таймкод пункта для шапки карточки и списков: «≈» впереди, если место найдено примерно. Иначе в шапке стояло бы
    «7:13», а строкой ниже, в тексте модели, — «≈7:13». В подпись кадра «≈» не идёт (caption, шаблон канона)."""
    tc = _tc(row)
    return '≈' + tc if tc and tc[0] not in '≈~' and is_rough(row) else tc


def _has_tc(s):
    return bool(TCR.search(s or ''))


def _sort_key(row):
    s = row.get('sec_new')
    return (s is not None, float(s) if s is not None else 0.0, int(row.get('n') or 0))


def _stamp(fb):
    """версии в строки (служебные поля с «_»): num_label / short_blocks / caption получают только row."""
    cut, prev = str(fb.get('cut_version') or ''), str(fb.get('prev_cut_version') or '')
    for r in (fb.get('part1') or []) + (fb.get('part2') or []):
        r['_cut'], r['_prev'] = cut, prev


# ── модель ───────────────────────────────────────────────────────────────────
def load(path=None):
    """feedback.json → dict. Без пути — work/{cut}/feedback.json по карточке фильма (proj_config подключается здесь,
    а не на уровне модуля)."""
    if path is None:
        stage = Path(__file__).resolve().parent.parent
        if str(stage) not in sys.path:
            sys.path.insert(0, str(stage))
        import proj_config as P
        path = P.WORK / 'feedback.json'
    path = Path(path)
    if not path.is_file():
        raise SystemExit(f'нет модели обратной связи: {path} — сначала собери её (shared/feedback_model.py)')
    fb = json.loads(path.read_text(encoding='utf-8'))
    if fb.get('schema') != 'feedback-v1':
        raise SystemExit(f'{path}: schema={fb.get("schema")!r}, ожидается feedback-v1')
    _stamp(fb)
    return fb


def sections(fb):
    """→ [(bucket, label, rows)] в порядке ORDER; пустые секции пропущены. Статусы и buckets — как в модели."""
    _stamp(fb)
    by = {b: [] for b in ORDER}
    for r in (fb.get('part1') or []) + (fb.get('part2') or []):
        b = r.get('bucket')
        if b in by:
            by[b].append(r)
    out = []
    for b in ORDER:
        rows = sorted(by[b], key=_sort_key)
        if b == 'blur':                                       # обязательные первыми, внутри — по времени
            rows.sort(key=lambda r: r.get('severity') != 'must')
        if rows:
            out.append((b, i18n.T(f'fb.sec.{b}', ver=fb.get('cut_version', '')), rows))
    return out


def counts(fb):
    """цифры строки-итога — по тем же секциям, что видит читатель (счётчики секций и итог обязаны сходиться).
    «Осталось» = блокирует + осталось + блюр: всё это работа монтажёра."""
    n = {b: 0 for b in ORDER}
    for b, _, rows in sections(fb):
        n[b] = len(rows)
    return {'total': len(fb.get('part2') or []), 'new': n['new'], 'closed': n['closed'],
            'open': n['block'] + n['open'] + n['blur'], 'fund': n['fund'], 'unknown': n['appendix'], 'by_bucket': n}


def blocker_items(fb):
    """≤8 строк первого экрана «таймкод ▸ действие» + адрес пункта. Состав — fb['blockers'] (его решает модель)."""
    out = []
    titles = {(r.get('part'), r.get('n')): r.get('title') for r in (fb.get('part1') or []) + (fb.get('part2') or [])}
    for b in (fb.get('blockers') or [])[:MAX_BLOCKERS]:
        tc = str(b.get('tc') or '').strip()
        do = str(b.get('do') or '').strip() or str(titles.get((b.get('part'), b.get('n'))) or b.get('label') or '').strip()
        do, _ = cut_line(do)                                  # первый экран — короткие строки
        if _has_tc(do):                                       # таймкод в строке один: свой не ставим, если он уже в тексте
            tc = ''
        out.append({'text': (tc + ARROW if tc else '') + do, 'part': b.get('part'), 'n': b.get('n')})
    return out


def head(fb, surface='doc', tz_tab=None, frames_note=False):
    """первый экран. surface: 'doc' | 'html' (разница — одно слово в предупреждении: «вкладка» / «страница»).
    tz_tab — имя вкладки ТЗ (по умолчанию шаблон c2.tz_tab_template); frames_note — строка «кадры — в HTML-файле»."""
    ver, prev = str(fb.get('cut_version') or ''), str(fb.get('prev_cut_version') or '')
    c = counts(fb)
    tz_tab = tz_tab or i18n.T('c2.tz_tab_template', ver=ver)
    L = [('h1', i18n.T('fb.doc_title', ver=ver, code=fb.get('code', '')))]
    vkey = 'fb.version_line' if prev else 'fb.version_line_noprev'
    L.append(('meta', i18n.T(vkey, ver=ver, prev=prev, dt=_dt(fb.get('built_at')), n=fb.get('build_no', 1))))
    if frames_note:
        L.append(('meta', i18n.T('fb.frames_in_html')))
    if c['new']:
        L.append(('warn', i18n.T('fb.warn_copy_html' if surface == 'html' else 'fb.warn_copy', tz_tab=tz_tab)))
    if c['total']:
        L.append(('tally', i18n.T('fb.tally_line', **{k: c[k] for k in ('total', 'closed', 'open', 'fund', 'unknown', 'new')})))
    else:
        L.append(('tally', i18n.T('fb.tally_new_only', new=c['new'])))
    items = blocker_items(fb)
    L.append(('list_head', i18n.T('fb.hold_edit' if items else 'fb.hold_edit_none')))
    L += [('list_item', it['text']) for it in items]
    if c['fund']:
        L.append(('list_head', plural('fb.hold_other', c['fund'])))
    L.append(('how', i18n.T('fb.how_head')))
    L.append(('how', i18n.T('fb.how_tc', ver=ver)))
    L.append(('how', i18n.T('fb.how_blocks')))
    L.append(('how', i18n.T('fb.how_typo')))
    L.append(('how', i18n.T('fb.how_nums', label_new=i18n.tz_label(4),
                            label_prev=i18n.T('fb.num_prev', label=i18n.tz_label(40), prev=prev or 'v1'))))
    return L


def _dt(built_at):
    """'2026-09-21 22:40' → '21.09.2026 22:40' (как во всех шапках стадии); иное — как есть."""
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2})', str(built_at or ''))
    return f'{m.group(3)}.{m.group(2)}.{m.group(1)} {m.group(4)}' if m else str(built_at or '')


# ── лимиты видимого текста ───────────────────────────────────────────────────
def cut_line(s, limit=MAX_LINE):
    """→ (видимая часть, хвост). Режем по границе предложения; нет её — по границе оборота; нет и её — по слову.
    Многоточий не ставим: читатель видит законченный кусок, остальное — в «ещё N строк»."""
    s = ' '.join(str(s or '').split())
    if len(s) <= limit:
        return s, ''
    cut = 0
    for m in _SENT.finditer(s):
        end = m.start() + len(m.group(0).rstrip())            # точка и закрывающая кавычка остаются в видимой части
        if end > limit:
            break
        word = re.search(r'(\w+)\.$', s[:m.start() + 1])
        if word and word.group(1).lower() in ABBR:
            continue
        cut = end
    if cut < 60:                                              # предложения нет (или обрубок) — граница оборота
        cut = 0
        for m in _CLAUSE.finditer(s):
            if m.start() > limit:
                break
            if m.start() >= 60:
                cut = m.start() + (1 if s[m.start()] in ';,' else 0)
        cut = cut if s[cut - 1:cut] != ',' else cut - 1       # запятую на конце не оставляем
    if cut < 60:                                              # сплошной текст — по слову
        cut = s.rfind(' ', 0, limit)
        cut = cut if cut > 0 else limit
    return s[:cut].rstrip(' ,;—'), s[cut:].lstrip(' ,;—')


def short_blocks(row, fb=None):
    """видимые блоки пункта по лимитам §5 + строка «ещё N строк — вкладка ТЗ v4, ТЗ-40».
    N = строки модели, не вошедшие в parts (row.more) + то, что не вошло здесь (они же лежат в 'rest')."""
    parts = row.get('parts') or {}
    out, rest = {}, []
    for k in ('now', 'do', 'where'):
        lines = [x for x in (parts.get(k) or []) if str(x).strip()]
        shown = []
        for i, line in enumerate(lines):
            if i >= LIMITS[k]:
                rest.append((k, ' '.join(str(line).split())))
                continue
            vis, tail = cut_line(line)
            shown.append(vis)
            if tail:
                rest.append((k, tail))
        out[k] = shown
    n = int(row.get('more') or 0) + len(rest)
    out['rest'] = rest
    out['more_line'] = None
    if n > 0:
        label = i18n.tz_label(row.get('n')) if row.get('n') is not None else str(row.get('label') or '')
        src = fb or {}
        ver = (src.get('cut_version') if fb else row.get('_cut')) if row.get('part') == 1 else \
              (src.get('prev_cut_version') if fb else row.get('_prev'))
        out['more_line'] = (plural('fb.more_line', n, prev=ver, label=label) if ver
                            else plural('fb.more_line_nover', n, label=label))
    return out


# ── строки и подписи ─────────────────────────────────────────────────────────
def num_label(row, fb=None):
    """«ТЗ-04» для Части 1, «ТЗ-40 · v4» для Части 2 (без версии номера двух ТЗ неразличимы)."""
    label = i18n.tz_label(row['n']) if row.get('n') is not None else str(row.get('label') or '')
    if row.get('part') == 1:
        return label
    prev = (fb or {}).get('prev_cut_version') or row.get('_prev')
    return i18n.T('fb.num_prev', label=label, prev=prev) if prev else label


def list_line(row, with_num=False):
    """«таймкод ▸ что · доказательство» для списков closed / fund / appendix. Таймкод ОДИН и в начале:
    добавка с собственным таймкодом не печатается (время доказательства живёт в evidence.tc, не в тексте).
    closed / appendix: добавка = evidence.text; fund: добавка = первая строка ✅ («что согласовать · если откажут — …»)."""
    what = ' '.join(str(row.get('title') or '').split())
    if row.get('bucket') == 'fund':
        extra = next((x for x in ((row.get('parts') or {}).get('do') or []) if str(x).strip()), '')
    else:
        extra = (row.get('evidence') or {}).get('text') or ''
    extra = ' '.join(str(extra).split())
    tc = tc_label(row)
    if _has_tc(what):                                         # заголовок уже со временем — второе не ставим
        tc = ''
    if _has_tc(extra) or extra.lower() == what.lower():
        extra = ''
    lead = tc + ARROW if tc else ''
    what, _ = cut_line(what, MAX_LINE - len(lead))
    room = MAX_LINE - len(lead) - len(what) - 3               # вся строка списка — не длиннее MAX_LINE (§5)
    if extra and len(extra) > room:
        extra = cut_line(extra, room)[0] if room >= 60 else ''
    s = lead + what + (' · ' + extra if extra else '')
    return s + (f' ({num_label(row)})' if with_num and row.get('n') is not None else '')   # как в пунктах: «ТЗ-13 · v4»


def dup_line(row):
    """пункт Части 2, чьё требование переехало в Часть 1: одна строка вместо блока и кадра."""
    tc = tc_label(row)
    return (tc + ARROW if tc else '') + i18n.T('fb.dup_line', label=i18n.tz_label(row.get('dup_of')))


def caption(row):
    """подпись под кадром «M:SS · что видно» (CAP_RE). Время — секунда кадра; «≈» и доли в подпись не идут."""
    fr = row.get('frame') or {}
    if not fr.get('file'):
        return ''
    sec = fr.get('sec') if fr.get('sec') is not None else row.get('sec_new')
    if sec is None:
        return ''
    t = int(float(sec))
    what = ' '.join(str(fr.get('what') or '').split())
    if not what or _has_tc(what):
        ver = row.get('_cut')
        what = i18n.T('fb.cap_default', ver=ver) if ver else i18n.T('fb.cap_default_nover')
    return i18n.T('fb.cap', tc=f'{t // 60}:{t % 60:02d}', what=what)


def fund_groups(rows, fb=None):
    """→ [(key, title, rows)]: темы в порядке fb['fund_topics'] (если дан), затем по первому появлению; без темы — последними."""
    order = [t.get('key') for t in ((fb or {}).get('fund_topics') or [])]
    titles = {t.get('key'): t.get('title') for t in ((fb or {}).get('fund_topics') or [])}
    groups = {}
    for r in rows:
        k = r.get('topic') or ''
        groups.setdefault(k, []).append(r)
        if k and r.get('topic_title'):
            titles.setdefault(k, r['topic_title'])
    keys = [k for k in order if k in groups] + [k for k in groups if k and k not in order] + ([''] if '' in groups else [])
    return [(k, (titles.get(k) or k) if k else i18n.T('fb.topic_other'), groups[k]) for k in keys]


def typo_pairs(row):
    return [(str(t.get('was') or ''), str(t.get('now') or '')) for t in (row.get('typo') or [])
            if t.get('was') or t.get('now')]


def visible_strings(row):
    """всё, что поверхности печатают из строки (для lint): заголовок, блоки, доказательство, подпись."""
    parts = row.get('parts') or {}
    out = [('title', row.get('title') or ''), ('evidence', (row.get('evidence') or {}).get('text') or ''),
           ('caption', caption(row))]
    out += [(k, x) for k in ('now', 'do', 'where') for x in (parts.get(k) or [])]
    return [(k, str(v)) for k, v in out if v]


def lint(fb):
    """→ [(уровень, подпись пункта, что не так)]. Жаргон — всегда FAIL. «≥2 таймкода в строке» — FAIL для Части 1
    и строк, порождённых кодом (доказательство, подпись), WARN для цитат прошлого ТЗ (контракт §5)."""
    _stamp(fb)
    out = []
    for r in (fb.get('part1') or []) + (fb.get('part2') or []):
        who = num_label(r)
        if r.get('bucket') not in ORDER:                      # sections() такую строку не покажет — молча терять нельзя
            out.append(('FAIL', who, f'пункт не попал ни в одну секцию: bucket={r.get("bucket")!r}'))
        elif (r.get('bucket') == 'new') != (r.get('part') == 1):
            out.append(('FAIL', who, f'секция «{r.get("bucket")}» не от той части документа (часть {r.get("part")})'))
        for k, s in visible_strings(r):
            for rx in JARGON:
                m = rx.search(s)
                if m:
                    out.append(('FAIL', who, f'жаргон «{m.group(0)}» в {k}: {s[:70]}'))
            if len(TCR.findall(s)) >= 2:
                lvl = 'FAIL' if r.get('part') == 1 or k in ('evidence', 'caption') else 'WARN'
                out.append((lvl, who, f'≥2 таймкода в строке {k}: {s[:70]}'))
        ev = (r.get('evidence') or {}).get('text') or ''
        if _has_tc(ev):
            out.append(('FAIL', who, f'таймкод внутри текста доказательства: {ev[:70]}'))
    for b in blocker_items(fb):
        if len(TCR.findall(b['text'])) >= 2:
            out.append(('FAIL', f'шапка · {b["n"]}', f'≥2 таймкода в строке шапки: {b["text"][:70]}'))
    extra = [(f'шапка · {b["n"]}', b['text']) for b in blocker_items(fb)]
    extra += [('вердикт', str(x)) for x in (fb.get('summary_lines') or [])]
    extra += [('тема фонда', str(t.get('title') or '')) for t in (fb.get('fund_topics') or [])]
    for who, s in extra:
        for rx in JARGON:
            m = rx.search(s)
            if m:
                out.append(('FAIL', who, f'жаргон «{m.group(0)}»: {s[:70]}'))
    t, c = fb.get('tally') or {}, counts(fb)                  # итог модели и то, что видит читатель, обязаны сходиться
    if t:
        shown = c['closed'] + c['open'] + c['fund'] + c['unknown']
        if t.get('prev_total', c['total']) != c['total'] or shown != c['total'] or t.get('new', c['new']) != c['new']:
            out.append(('WARN', 'итог', f'счётчики модели {t} расходятся с секциями {c["by_bucket"]}'))
    return out


def clean_summary(fb, limit=5):
    """строки вердикта для показа: без строк со словами движка (они остаются в lint), не больше limit."""
    return [' '.join(str(x).split()) for x in (fb.get('summary_lines') or [])
            if str(x).strip() and not any(rx.search(str(x)) for rx in JARGON)][:limit]


# ── самопроверка ─────────────────────────────────────────────────────────────
def _synthetic():
    def row(part, n, bucket, status, sec, **kw):
        tc = f'{int(sec) // 60}:{int(sec) % 60:02d}' if sec is not None else ''
        r = {'part': part, 'n': n, 'label': f'ТЗ-{n:02d}', 'title': f'Пункт {n}', 'category': 'cut', 'severity': 'should',
             'sensitive': False, 'blocker': False, 'sec_new': sec, 'tc_new': tc, 'parts': {'now': [], 'do': [], 'where': []},
             'more': 0, 'status': status, 'bucket': bucket, 'dup_of': None, 'topic': None, 'topic_title': None,
             'evidence': {'kind': 'code', 'tc': tc, 'sec': sec, 'text': 'реплика на месте'},
             'frame': {'file': f'work/v5/hires/h{int(sec) + 1:04d}.jpg', 'sec': int(sec), 'what': ''} if sec is not None else None,
             'typo': []}
        r.update(kw)
        return r
    long_now = ('Фонд входит в рассказ слишком рано, зритель ещё не знает героиню. ' * 6 +
                'Правило канала — не раньше 34-й минуты. Сейчас это звучит как реклама, а не как помощь.')
    assert len(long_now) > 400
    return {
        'schema': 'feedback-v1', 'code': 'YTXX01', 'cut_version': 'v5', 'prev_cut_version': 'v4',
        'built_at': '2026-09-21 22:40', 'build_no': 3, 'duration_sec': 3000.0,
        'blockers': [{'part': 1, 'n': 1, 'label': 'ТЗ-01', 'tc': '0:42', 'do': 'исправить фамилию в титре'},
                     {'part': 2, 'n': 9, 'label': 'ТЗ-09', 'tc': '5:10', 'do': 'убрать повтор 5:10–5:24'}],
        'fund_topics': [{'key': 'b', 'title': 'Тема Б', 'count': 1}, {'key': 'a', 'title': 'Тема А', 'count': 2}],
        'part1': [row(1, 2, 'new', 'new', 300.0),
                  row(1, 1, 'new', 'new', 42.0, blocker=True, typo=[{'was': 'ЖУМАГУЛ', 'now': 'ЖИМАГУЛ'}])],
        'part2': [row(2, 40, 'block', 'open', 676.2, dup_of=2, severity='must', blocker=False),
                  row(2, 9, 'block', 'open', 310.0, severity='must', blocker=True, more=5,
                      parts={'now': [long_now, 'вторая строка «сейчас»'], 'do': ['раз', 'два', 'три', 'четыре', 'пять'],
                             'where': ['5:10–5:24', 'ещё одно место']}),
                  row(2, 12, 'open', 'open', None, frame=None, tc_new=''),
                  row(2, 11, 'open', 'open', 900.0),
                  row(2, 20, 'blur', 'fund', 100.0, sensitive=True), row(2, 21, 'blur', 'fund', 200.0, sensitive=True, severity='must'),
                  row(2, 30, 'closed', 'closed', 500.0), row(2, 31, 'closed', 'closed', 400.0),
                  row(2, 50, 'fund', 'fund', 800.0, topic='a', topic_title='Тема А', parts={'do': ['согласовать фамилию врача']}),
                  row(2, 51, 'fund', 'fund', 700.0, topic='b', topic_title='Тема Б'),
                  row(2, 52, 'fund', 'fund', 750.0, topic='a', topic_title='Тема А', parts={'do': ['если откажут — блюр с 12:30']}),
                  row(2, 60, 'appendix', 'unknown', 1000.0)],
    }


def selftest():
    old = i18n.set_lang('ru')
    try:
        fb = _synthetic()
        secs = sections(fb)
        want = ['new', 'block', 'open', 'blur', 'closed', 'fund', 'appendix']   # порядок контракта §4 — буквально, не из ORDER
        assert [b for b, _, _ in secs] == want, [b for b, _, _ in secs]
        assert LIMITS == {'now': 1, 'do': 4, 'where': 1} and MAX_LINE == 240 and MAX_BLOCKERS == 8   # контракт §5, §3
        by = {b: rows for b, _, rows in secs}
        assert secs[0][1] == 'ЧАСТЬ 1 · НОВОЕ В v5'
        assert [r['n'] for r in by['new']] == [1, 2]                      # по времени
        assert [r['n'] for r in by['open']] == [12, 11]                    # без времени — первым
        assert [r['n'] for r in by['blur']] == [21, 20]                    # must первым
        assert [r['n'] for r in by['closed']] == [31, 30]
        empty = dict(fb, part2=[r for r in fb['part2'] if r['bucket'] != 'fund'])
        assert 'fund' not in [b for b, _, _ in sections(empty)]           # пустая секция пропущена

        h = head(fb)
        kinds = [k for k, _ in h]
        assert kinds[:4] == ['h1', 'meta', 'warn', 'tally'], kinds
        assert set(kinds) <= {'h1', 'meta', 'warn', 'tally', 'list_head', 'list_item', 'how'}
        txt = dict((k, t) for k, t in h if k in ('h1', 'meta', 'tally'))
        assert txt['h1'] == 'Обратная связь по кату v5 · YTXX01'
        assert txt['meta'] == 'кат v5 против v4 · собрано 21.09.2026 22:40 · сборка 3', txt['meta']
        assert txt['tally'] == ('Из 12 пунктов прошлого ТЗ: закрыто 2 · осталось 6 · 3 ждёт ответа фонда · '
                                '1 не проверено. Новых — 2.'), txt['tally']
        items = [t for k, t in h if k == 'list_item']
        assert items == ['0:42 ▸ исправить фамилию в титре', 'убрать повтор 5:10–5:24'], items   # второй: таймкод уже в тексте
        assert 1 <= len(items) <= MAX_BLOCKERS
        heads = [t for k, t in h if k == 'list_head']
        assert heads[0] == 'Держит выпуск — монтаж:' and '3 пункта ждут ответа юриста фонда (Роман)' in heads[1], heads
        assert 'страница' in dict(head(fb, surface='html'))['warn'] and 'ТЗ монтажёру · v5' in dict(h)['warn']
        assert ('meta', 'кадры — в HTML-файле') in head(fb, frames_note=True)
        many = dict(fb, blockers=[{'part': 2, 'n': i, 'tc': '1:00', 'do': 'x'} for i in range(12)])
        assert len(blocker_items(many)) == MAX_BLOCKERS
        assert plural('fb.hold_other', 21).startswith('Держит выпуск — не монтаж: 21 пункт ждёт')
        assert '11 пунктов ждёт' in plural('fb.hold_other', 11) and '5 пунктов ждёт' in plural('fb.hold_other', 5)

        r9 = next(r for r in fb['part2'] if r['n'] == 9)
        sb = short_blocks(r9)
        assert len(sb['now']) == 1 and len(sb['do']) == 4 and len(sb['where']) == 1
        assert len(sb['now'][0]) <= MAX_LINE and sb['now'][0].endswith('.') and '…' not in sb['now'][0] and '...' not in sb['now'][0]
        assert [k for k, _ in sb['rest']] == ['now', 'now', 'do', 'where'], sb['rest']
        assert sb['more_line'] == 'ещё 9 строк — вкладка ТЗ v4, ТЗ-09', sb['more_line']    # 5 из модели + 4 здесь
        full = ' '.join(r9['parts']['now'][0].split())
        assert sb['now'][0] + ' ' + sb['rest'][0][1] == full                                 # резка без потерь
        assert short_blocks(by['new'][0])['more_line'] is None
        assert short_blocks(dict(by['new'][0], more=1))['more_line'] == 'ещё 1 строка — вкладка ТЗ v5, ТЗ-01'
        assert short_blocks({'part': 2, 'n': 7, 'more': 2})['more_line'] == 'ещё 2 строки — ТЗ-07'   # без версии
        v, t = cut_line('Слово, ' * 60)
        assert 60 <= len(v) <= MAX_LINE and not v.endswith(',') and t
        v, t = cut_line('Снято на ул. Ленина в 2019 г. ' + 'Дальше идёт очень длинное описание сцены без точки ' * 6)
        assert len(v) <= MAX_LINE and not v.endswith(('ул.', ' г.'))
        v, t = cut_line('я' * 300)
        assert len(v) == MAX_LINE and t == 'я' * 60

        assert num_label(by['new'][0]) == 'ТЗ-01' and num_label(r9) == 'ТЗ-09 · v4'
        assert num_label({'part': 2, 'n': 40}, fb) == 'ТЗ-40 · v4'
        assert list_line(by['closed'][0]) == '6:40 ▸ Пункт 31 · реплика на месте'
        assert list_line(by['closed'][0], with_num=True).endswith('(ТЗ-31 · v4)')        # номер как в пунктах — с версией
        assert list_line(by['new'][0], with_num=True).endswith('(ТЗ-01)')                # Часть 1 — без версии
        assert list_line(by['open'][0]) == 'Пункт 12 · реплика на месте'                     # без таймкода
        g = fund_groups(by['fund'], fb)
        assert [(k, t, [r['n'] for r in rows]) for k, t, rows in g] == [('b', 'Тема Б', [51]), ('a', 'Тема А', [52, 50])], g
        assert list_line(g[1][2][1]) == '13:20 ▸ Пункт 50 · согласовать фамилию врача'
        assert list_line(g[1][2][0]) == '12:30 ▸ Пункт 52'                                    # добавка со своим таймкодом снята
        for b, _, rows in secs:
            for r in rows:
                assert len(TCR.findall(list_line(r))) <= 1
                c = caption(r)
                assert (c == '' and not r.get('frame')) or CAP_RE.match(c), c
        assert caption(by['new'][0]) == '0:42 · кадр ката v5'
        assert caption(dict(by['new'][0], frame={'file': 'x.jpg', 'sec': 676, 'what': 'куратор в кадре'})) == '11:16 · куратор в кадре'
        assert dup_line(next(r for r in fb['part2'] if r['n'] == 40)) == '11:16 ▸ не закрыто · перенесено в новое ТЗ-02 (Часть 1)'
        assert typo_pairs(by['new'][0]) == [('ЖУМАГУЛ', 'ЖИМАГУЛ')] and typo_pairs(r9) == []

        # «≈»: примерное место — в списках и строке-переносе, но не в подписи кадра
        rough = dict(by['closed'][0], err=4.2)
        assert tc_label(rough) == '≈6:40' and list_line(rough).startswith('≈6:40 ▸ ') and CAP_RE.match(caption(rough))
        assert tc_label(dict(rough, err=0.5, how='gap')) == '≈6:40' and tc_label(dict(rough, err=0.5, how='span')) == '6:40'
        assert tc_label(dict(by['new'][0], err=9)) == '0:42' and tc_label(dict(rough, tc_new='≈6:40')) == '≈6:40'
        assert dup_line(dict(rough, dup_of=2)).startswith('≈6:40 ▸ ')
        # строка списка целиком ≤ 240: длинный заголовок + длинная добавка
        fat = dict(by['closed'][0], title='Очень длинный заголовок пункта прошлого ТЗ. ' * 4,
                   evidence={'text': 'реплика на месте: «' + 'слово ' * 50 + '». Вторая фраза доказательства.'})
        assert len(list_line(fat)) <= MAX_LINE and '…' not in list_line(fat), len(list_line(fat))
        assert list_line(dict(fat, title='Короткий')).startswith('6:40 ▸ Короткий · реплика на месте')
        # шапка: пустое действие → заголовок пункта; длинное действие режется
        e = dict(fb, blockers=[{'part': 2, 'n': 9, 'tc': '5:10', 'do': ''}, {'part': 1, 'n': 1, 'tc': '0:42', 'do': 'Делать так. ' * 40}])
        bi = blocker_items(e)
        assert bi[0]['text'] == '5:10 ▸ Пункт 9' and len(bi[1]['text']) <= MAX_LINE + 8, bi

        assert lint(fb) == [], lint(fb)
        lost = _synthetic()
        lost['part2'][3]['bucket'] = 'opened'                              # опечатка в модели: строка исчезла бы со страницы
        lost['part2'][4]['bucket'] = 'new'
        ll = [c for a, _, c in lint(lost) if a == 'FAIL']
        assert any('ни в одну секцию' in c for c in ll) and any('не от той части' in c for c in ll), ll
        sm = dict(_synthetic(), summary_lines=['Кат стал плотнее.', 'правила листа нарушены: fund_entry_min, last_sound_rule'],
                  tally={'new': 2, 'prev_total': 99})
        assert clean_summary(sm) == ['Кат стал плотнее.']
        lv = lint(sm)
        assert ('FAIL', 'вердикт') in [(a, w) for a, w, _ in lv] and ('WARN', 'итог') in [(a, w) for a, w, _ in lv], lv
        assert not [x for x in lint(dict(_synthetic(), tally={'new': 2, 'prev_total': 12})) if x[1] == 'итог']
        bad = _synthetic()
        bad['part1'][0]['parts']['now'] = ['в кадре h0677 видно (OCR), 1:00 и 2:00']
        lv = [(a, c.split(' ')[0]) for a, _, c in lint(bad)]
        assert lv.count(('FAIL', 'жаргон')) == 2 and ('FAIL', '≥2') in lv, lv

        i18n.set_lang('en')
        assert head(fb)[0][1] == 'Feedback on cut v5 · YTXX01' and num_label(r9) == 'FIX-09 · v4'
        assert short_blocks(r9)['more_line'] == '9 more lines — notes tab v4, FIX-09'
        miss = sorted(k for k, v in i18n.STRINGS.items() if k.startswith('fb.') and ('ru' not in v or 'en' not in v))
        assert not miss, miss
        for k, v in i18n.STRINGS.items():                                 # слова движка не живут и в самих строках
            if k.startswith('fb.'):
                for s in (x for lang in v.values() for x in (lang if isinstance(lang, list) else [lang])):
                    assert not any(rx.search(re.sub(r'\{\w+\}', '', s)) for rx in JARGON), (k, s)   # {подстановки} — не текст
    finally:
        i18n.set_lang(old)
    print('SELFTEST OK')


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='общий слой «Обратной связи»: печать первого экрана и секций, самопроверка')
    ap.add_argument('--fb', help='путь к feedback.json (по умолчанию — work/{cut}/feedback.json по карточке)')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        selftest()
        sys.exit(0)
    FB = load(a.fb)
    for kind, text in head(FB):
        print(f'{kind:10s} {text}')
    for bucket, label, rows in sections(FB):
        print(f'\n[{label} · {len(rows)}]')
    problems = lint(FB)
    for lvl, who, msg in problems:
        print(f'{lvl} {who}: {msg}')
    sys.exit(1 if any(p[0] == 'FAIL' for p in problems) else 0)
