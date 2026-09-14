#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verdict_call.py — подготовка и приём облачного вердикта (cloud/wf_verdict_doc.js). Сам код в облако не ходит.
Наследник p_pravki_v4 / x_synth_local (YTCH12 v4): вердикт + обязательные правки → ТЗ в едином JSON правок.

  --print-call [--want-tobe]   собрать args воркфлоу (пути к acts_compact / structure_checks, top-20 risk.json,
                               ПУТЬ к транскрипту — текст в промпт не кладём, правила канала, существующие ТЗ) →
                               cloud/in/verdict_args.json и напечатать вызов Workflow({scriptPath, args});
  --apply [--verdict path]     cloud/out/verdict.json → ТЗ в M/pravki_v2.json: class «structure», source «verdict»,
                               номера ПОСЛЕ последнего ТЗ (повторный --apply заменяет прежние verdict-ТЗ, их номера
                               сохраняются по ключу) + W6/producer_summary.json для продюсерской страницы;
  --status                     что есть на диске.
Схема ответа агента (пишет сам Write'ом до возврата): {verdict, headline?, mandatory_edits: [{tc, what, why}],
structure_proposal: [{title, tc_range, note}], open_questions: [str], sensitive_notes: [str], strengths?: [str], time_math?}.
env: YTAI_CARD=<review_card.json>; YTAI_WORK_DIR / YTAI_PRAVKI_DIR — куда писать (тесты).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'stages'))
from _bootstrap import P, W6, M, CLOUD, REVIEW_DIR, ROOT  # noqa: E402

WF = ROOT / 'cloud' / 'wf_verdict_doc.js'


def pravki_file():
    """файл правок по канону pravki_lib (карточка pravki_file → pravki.json → pravki_v2.json); нет ни одного → pravki_v2.json"""
    try:
        from pravki_lib import pravki_path
        return Path(pravki_path(M, P))
    except (ImportError, SystemExit):
        return M / 'pravki_v2.json'
TCRE = re.compile(r'(\d{1,2}):(\d{2})(?:[.,](\d+))?')
CAT_RX = [('cut', r'вырез|убрать|резать|сократ|сжать|удалить|дорезать|обрыв'),
          ('insert', r'вставить|вернуть|добавить|врезк|перебивк|подложить'),
          ('graphics', r'титул|карточк|подпис|плашк|график|титр|лоуэр|lower'),
          ('structure', r'.')]


def tc(s):
    s = int(s)
    return f'{s // 60}:{s % 60:02d}'


def secs(s):
    ms = TCRE.findall(str(s or ''))
    return [int(a) * 60 + int(b) + (float('0.' + c) if c else 0) for a, b, c in ms]


def one(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def num_int(p):
    """номер ТЗ записи как int: «ТЗ-07» (канон s10 / pravki_lib) или 7 (contracts §5); нет → None"""
    n = p.get('num')
    if isinstance(n, int):
        return n
    m = re.search(r'(\d+)', str(n or ''))
    return int(m.group(1)) if m else None


def num_label(n):
    return f'ТЗ-{int(n):02d}'


def load(p, default=None):
    p = Path(p)
    return json.load(open(p, encoding='utf-8')) if p.exists() else default


def rules_text():
    sr = P.profile('structure_rules') or {}
    sens = P.profile('sensitivity') or {}
    parts = [P.profile('rules_text') or '']
    if sr:
        parts.append('ПРАВИЛА СТРУКТУРЫ: ' + ' · '.join(f'{k}: {v}' for k, v in sr.items() if not k.startswith('_') and not k.endswith('_rx')))
    if sens:
        parts.append(f'ЧУВСТВИТЕЛЬНОЕ: политика {sens.get("policy", "")} — находка = {sens.get("mark", "⚠️")} «на подтверждение фонда / блюр», '
                     'НЕ ⛔; ⛔ только дубли, техбрак и письменные запреты фонда.')
    notes = P.get('notes') or []
    if notes:
        parts.append('ГРАБЛИ ПРОЕКТА: ' + ' · '.join(map(str, notes)))
    return '\n'.join(x for x in parts if x)


def existing_tz():
    pr = load(pravki_file(), {'all': []})
    out = []
    for i, p in enumerate(pr.get('all') or []):
        if p.get('status') == 'rejected':
            continue
        n = p.get('num')
        lab = n if isinstance(n, str) else (f'ТЗ-{int(n):02d}' if n is not None else f'ТЗ-{i + 1:02d}')
        out.append(f'{lab} · {p.get("tc_range") or p.get("v1_tc") or "—"} · {one(p.get("title"))[:80]}')
    return out


def cmd_print_call(a):
    acts, checks, risk = W6 / 'acts_compact.json', W6 / 'structure_checks.json', W6 / 'risk.json'
    missing = [str(p) for p in (acts, checks) if not p.exists()]
    if missing:
        raise SystemExit('нет входов: ' + ', '.join(missing) + '\nсначала: acts_compact.py (акты + structure_checks) и risk_registry.py')
    risk_rows = load(risk, [])
    top = [{k: r.get(k) for k in ('tc', 'topic', 'phrase', 'action', 'speaker')} for r in risk_rows[:20]]
    (CLOUD / 'in').mkdir(parents=True, exist_ok=True)
    (CLOUD / 'out').mkdir(parents=True, exist_ok=True)
    args = {'card': str(P.CARD_PATH), 'code': P.CODE, 'cut_version': P.CUT_VERSION, 'channel': P.CHANNEL,
            'film': P.FILM, 'duration_sec': P.duration_sec() if (P.get('duration_sec') or P.SRC) else None,
            'acts_compact': str(acts), 'structure_checks': str(checks), 'risk_top': top, 'risk_total': len(risk_rows),
            'transcript_path': str(P.WORDS), 'rules': rules_text(), 'existing_tz': existing_tz()[:80],
            'chapters': [f'{n} · {tc(t)} · {dict(P.get("ch_name") or {}).get(n, "")}' for t, n in P.CHAPTERS],
            'out_path': str(CLOUD / 'out' / 'verdict.json'), 'want_tobe': bool(a.want_tobe),
            'tobe_out_path': str(CLOUD / 'out' / 'tobe.json')}
    P.write_json_atomic(CLOUD / 'in' / 'verdict_args.json', args)
    print(f'args → {CLOUD / "in" / "verdict_args.json"} (risk top {len(top)}/{len(risk_rows)}, существующих ТЗ {len(args["existing_tz"])})')
    print('Workflow({scriptPath: ' + json.dumps(str(WF)) + ', args: ' + json.dumps(args, ensure_ascii=False) + '})')
    return 0


def make_entries(v, start_num):
    """вердикт → записи ТЗ (contracts.md §5): структура, обязательные правки по таймлайну, открытые вопросы"""
    items = []
    props = v.get('structure_proposal') or []
    if props:
        lst = [f'{one(p.get("tc_range"))} ▸ {one(p.get("title")).upper()}' + (f' — {one(p.get("note"))}' if p.get('note') else '') for p in props]
        items.append({'key': 'verdict:structure', 'title': 'Структура: предложенные главы',
                      'category': 'structure', 'v1_tc': '', 'tc_range': 'весь фильм',
                      'est': one(v.get('headline') or v.get('verdict'))[:300],
                      'parts': {'now': [one(v.get('headline') or v.get('verdict'))[:300]],
                                'do': ['Поставить карточки глав по списку ниже (порядок ката не меняется, если не сказано иное).'],
                                'list': [{'h': 'Главы (карточки)', 'items': lst}]},
                      'decision': ' ; '.join(one(q) for q in (v.get('open_questions') or [])[:3])})
    for e in sorted(v.get('mandatory_edits') or [], key=lambda e: (secs(e.get('tc')) or [10 ** 6])[0]):
        ss = secs(e.get('tc'))
        what, why = one(e.get('what')), one(e.get('why'))
        cat = next(c for c, rx in CAT_RX if re.search(rx, what.lower()))
        it = {'key': f'verdict:{one(e.get("tc"))}:{what[:40]}', 'title': what[:90], 'category': cat,
              'v1_tc': tc(ss[0]) if ss else '', 'tc_range': one(e.get('tc')), 'est': why,
              'parts': {'now': [why], 'do': [what], 'where': [one(e.get('tc'))]}}
        if ss:
            it['timeline_in_sec'], it['timeline_out_sec'] = min(ss), max(ss)
        items.append(it)
    qs = [one(q) for q in (v.get('open_questions') or []) if one(q)]
    if qs:
        items.append({'key': 'verdict:questions', 'title': 'Открытые вопросы — решения Романа', 'category': 'structure',
                      'v1_tc': '', 'tc_range': 'весь фильм', 'est': 'Вердикт оставил вопросы, без ответов правки ниже не закрыть.',
                      'parts': {'now': ['Вердикт оставил вопросы, без ответов правки ниже не закрыть.'], 'do': qs},
                      'decision': ' ; '.join(qs)})
    for i, it in enumerate(items):
        it.update({'num': start_num + i, 'class': 'structure', 'source': 'verdict', 'notes': ['verdict'],
                   'severity': 'medium' if it['key'] == 'verdict:questions' else 'high',   # pravki_lib: high → _must
                   'material_rich': [], 'typo': [], 'sheet_answer': '', 'nado': render(it['parts'])})
        it.setdefault('decision', '')
    return items


LBL = {'now': '❌ СЕЙЧАС', 'do': '✅ СДЕЛАТЬ', 'list': '📋 СПИСОК', 'where': '📍 ГДЕ', 'src': '📚 ИСТОЧНИК', 'tl': '🎬 НА ТАЙМЛАЙНЕ'}


def render(parts):
    out = []
    for k in ('now', 'do', 'list', 'where', 'src', 'tl'):
        for el in parts.get(k) or []:
            if isinstance(el, dict):
                out.append(f'{LBL[k]} · {el.get("h", "")}')
                out += [f'        {x}' for x in el.get('items') or []]
            elif one(el):
                out.append(f'{LBL[k]} · {one(el)}')
    return '\n'.join(out)


def cmd_apply(a):
    vp = Path(a.verdict or CLOUD / 'out' / 'verdict.json')
    v = load(vp)
    if v is None:
        raise SystemExit(f'нет {vp} — воркфлоу ещё не отработал (или упал по лимиту: cloud/salvage.py --latest)')
    pp = pravki_file()
    pr = load(pp, {'all': []})
    allp = pr.get('all') or []
    keep = [p for p in allp if p.get('source') != 'verdict']
    old = {p.get('key'): p for p in allp if p.get('source') == 'verdict'}
    nums = [num_int(p) for p in keep if num_int(p) is not None]
    start = max(nums + [len(keep)]) + 1
    new = make_entries(v, start)
    used = {num_int(p) for p in old.values() if num_int(p) is not None}
    nxt = max([start - 1] + list(used)) + 1
    for it in new:                                       # стабильные номера по ключу; новые — после всех
        o = old.get(it['key'])
        if o and num_int(o) is not None:
            it['num'] = num_int(o)
            for k in ('status', 'roman_comment', 'replies', 'sheet_answer', 'rejected_by', 'sensitive'):
                if k in o:
                    it[k] = o[k]
        else:
            it['num'] = nxt; nxt += 1
    new.sort(key=lambda p: p['num'])
    for it in new:                                       # на диск — «ТЗ-NN», как кладут s10_format_tz и читает pravki_lib
        it['num'] = num_label(it['num'])
    if pp.exists():
        bak = pp.with_suffix('.json.bak-verdict')
        bak.write_text(pp.read_text(encoding='utf-8'), encoding='utf-8')
    P.write_json_atomic(pp, {**pr, 'all': keep + new})
    acts = load(W6 / 'acts_compact.json', {}) or {}
    vtext = one(v.get('verdict'))
    short = re.split(r'\s+[—–-]\s+|[.:;]\s', vtext, maxsplit=1)[0][:80] if vtext else ''
    checks = (load(W6 / 'structure_checks.json', {}) or {}).get('checks', [])
    edits = v.get('mandatory_edits') or []
    tz_by_key = {p['key']: p for p in new}
    must = []
    for e in edits:
        p = tz_by_key.get(f'verdict:{one(e.get("tc"))}:{one(e.get("what"))[:40]}')
        must.append({'num': p['num'] if p else '', 'tc': one(e.get('tc')), 'title': one(e.get('what'))[:90],
                     'todo': one(e.get('what')) + (f' — {one(e.get("why"))}' if e.get('why') else '')})
    fails = [c['rule'] for c in checks if c.get('status') == 'fail']
    lines = [x for x in (short, one(v.get('headline')),
                         f'обязательных правок {len(edits)} · глав предложено {len(v.get("structure_proposal") or [])} · '
                         f'вопросов Роману {len(v.get("open_questions") or [])} · ⚠️ фонд/блюр {len(v.get("sensitive_notes") or [])}',
                         ('правила листа нарушены: ' + ', '.join(fails)) if fails else '',
                         one(v.get('time_math'))) if x][:5]
    # ключи verdict_short / lines / must / decisions читает pravki_lib.load_summary (producer_page, phone_brief)
    summ = {'schema': 'producer-summary-v1', 'code': P.CODE, 'cut_version': P.CUT_VERSION, 'film': P.FILM,
            'verdict_short': short, 'lines': lines, 'must': must, 'decisions': [one(q) for q in (v.get('open_questions') or [])],
            'verdict': v.get('verdict'), 'headline': v.get('headline', ''), 'strengths': v.get('strengths') or [],
            'time_math': v.get('time_math', ''), 'mandatory_edits': edits,
            'structure_proposal': v.get('structure_proposal') or [], 'open_questions': v.get('open_questions') or [],
            'sensitive_notes': v.get('sensitive_notes') or [],
            'structure_checks': checks,
            'risk_top': (load(W6 / 'risk.json', []) or [])[:20],
            'acts': [{k: x.get(k) for k in ('act', 'title', 'tc_range', 'summary', 'theses')} for x in acts.get('acts', [])],
            'tz_added': [p['num'] for p in new], 'verdict_file': str(vp)}
    P.write_json_atomic(W6 / 'producer_summary.json', summ)
    print(f'[verdict] «{one(v.get("verdict"))[:80]}» · обязательных правок {len(v.get("mandatory_edits") or [])} · '
          f'глав {len(v.get("structure_proposal") or [])} · вопросов {len(v.get("open_questions") or [])} · '
          f'чувствительных заметок {len(v.get("sensitive_notes") or [])}')
    labels = ', '.join(p['num'] for p in new)
    print(f'  ТЗ: было {len(keep)} (+{len(old)} прежних verdict) → добавлено {len(new)}: {labels} → {pp}')
    print(f'  producer_summary → {W6 / "producer_summary.json"}')
    return 0


def cmd_status():
    for name, p in (('acts_compact', W6 / 'acts_compact.json'), ('structure_checks', W6 / 'structure_checks.json'),
                    ('risk', W6 / 'risk.json'), ('args', CLOUD / 'in' / 'verdict_args.json'),
                    ('verdict', CLOUD / 'out' / 'verdict.json'), ('tobe', CLOUD / 'out' / 'tobe.json'),
                    ('producer_summary', W6 / 'producer_summary.json')):
        print(f'  {"✅" if p.exists() else "—"} {name:18s} {p}')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--print-call', action='store_true')
    g.add_argument('--apply', action='store_true')
    g.add_argument('--status', action='store_true')
    ap.add_argument('--want-tobe', action='store_true')
    ap.add_argument('--verdict')
    a = ap.parse_args()
    if a.print_call:
        return cmd_print_call(a)
    if a.apply:
        return cmd_apply(a)
    return cmd_status()


if __name__ == '__main__':
    sys.exit(main())
