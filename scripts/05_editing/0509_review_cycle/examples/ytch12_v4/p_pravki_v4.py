#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pravki_v4.json — ЕДИНЫЙ источник правок YTCH12 v4 (метод KB review-timeline, схема YTUVI01 pravki_v2):
из него строятся вкладка дока «ТЗ монтажёру · v4», лист «ТЗ монтажёру» и маркеры секвенции.

Порядок: ТЗ-01 = вся структура (главы + подглавы + титул + YouTube-главы; канон «первое ТЗ дока =
структура + пример кадра»), затем по таймлайну: обязательные (must) и желательные (should) правки
из вердикта — находки разных агентов на одно место СЛИВАЮТСЯ в одно ТЗ (📍 ГДЕ по строке на точку),
затем прочие проверенные находки, затем графика (graphics_tz), не покрытая находками.
Текст ТЗ (nado) — блоками формата v7: одна строка = одна мысль / один таймкод:
  ❌ СЕЙЧАС · …  ✅ СДЕЛАТЬ · …  📋 СПИСОК · (заголовок + пункты «tc ▸ …»)  📍 ГДЕ · tc · якорь «…»
  📚 ИСТОЧНИК · …  🎬 НА ТАЙМЛАЙНЕ · …
Вход: wf_result.json (ревью), structure_v4.json (структура), mockups_index.json. Номера ТЗ стабильны:
если pravki_v4.json уже есть, существующие ТЗ (по ключу key) сохраняют номер и status/roman_comment.
"""
import json
import os
import re

WORK = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(WORK, 'pravki_v4.json')
SEQ = 'YTCH12_5_Review_v4_full'
FIG = ' '  # цифровой пробел — выравнивание таймкодов под «33:42»
IND2 = ' ' * 8
CAT = {'structure': 'structure', 'ending': 'structure', 'pacing': 'cut', 'duplicate': 'cut',
       'broken_phrase': 'cut', 'missing_plan_anchor': 'insert', 'picture': 'insert',
       'graphics': 'graphics', 'missing_context': 'graphics', 'tech': 'color',
       'sensitive_fund': 'fund', 'fact': 'check', 'other': 'check'}


def J(name, default=None):
    p = os.path.join(WORK, name)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else default


def sec(s):
    m = re.findall(r'\d+(?:\.\d+)?', str(s or ''))
    p = [float(x) for x in m[:3]]
    if not p:
        return None
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else (p[0] * 60 + p[1] if len(p) == 2 else p[0])


def tc(s):
    s = int(s)
    return f'{s // 60}:{s % 60:02d}'


def pad(t):
    return t.rjust(5, FIG) if re.match(r'^\d{1,2}:\d{2}$', t) else t


def rng(f):
    a, b = f.get('tc_start', ''), f.get('tc_end', '')
    return a if not b or b == a else f'{a}–{b}'


def one(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


TCRE = re.compile(r'(?<![\d:])\d{1,2}:\d{2}(?:[.,]\d+)?(?:\s*[–-]\s*\d{1,2}:\d{2}(?:[.,]\d+)?)?(?![\d:])')
IND = ' ' * 5


def split_tc(line):
    """Канон v7: одна строка — один таймкод. Режем повторно, пока в куске не останется один."""
    out, queue = [], [line]
    while queue:
        cur = queue.pop(0)
        parts = _split_once(cur)
        if len(parts) == 1:
            p = parts[0]
            ms = list(TCRE.finditer(p))
            if len(ms) >= 2:                       # разделителя нет — жёсткий разрез перед вторым
                b = ms[1].start()
                queue = [p[:b].strip(' ,;·—.'), p[b:].strip(' ,;·—.')] + queue
                continue
            if p:
                out.append(p)
        else:
            queue = parts + queue
    return out


def _split_once(line):
    ms = list(TCRE.finditer(line))
    if len(ms) < 2:
        return [line]
    out, start = [], 0
    for m in ms[1:]:
        b = max(line.rfind(', ', start, m.start()), line.rfind('; ', start, m.start()),
                line.rfind(' · ', start, m.start()), line.rfind(' — ', start, m.start()),
                line.rfind('. ', start, m.start()), line.rfind(' и ', start, m.start()),
                line.rfind(' → ', start, m.start()), line.rfind(' / ', start, m.start()),
                line.rfind('• ', start, m.start()), line.rfind('(', start, m.start()))
        if b <= start:
            b = m.start()
        out.append(line[start:b].strip(' ,;·—.'))
        start = b
    out.append(line[start:].strip(' ,;·—.'))
    return [x for x in out if x]


def nado(blocks):
    """blocks: [(label, [строки] | {'h':…, 'items':[…]})] → текст формата v7."""
    out = []
    for lab, val in blocks:
        if isinstance(val, dict):
            out.append(f'{lab} · {val["h"]}')
            for it in val['items']:
                for part in split_tc(one(it)):
                    m = re.match(r'^(\d{1,2}:\d{2}(?:[.,]\d+)?(?:\s*[–-]\s*\d{1,2}:\d{2}(?:[.,]\d+)?)?)'
                                 r'\s*▸?\s*(.+)$', part)
                    out.append(f'{IND2}{pad(m.group(1))}  ▸ {m.group(2)}' if m else f'{IND2}{IND}{part}')
        else:
            for ln in val:
                if not one(ln):
                    continue
                for k, part in enumerate(split_tc(one(ln))):
                    out.append(f'{lab} · {part}' if k == 0 else f'{IND}{part}')
    return '\n'.join(out)


def frame_img(s):
    return f'f{int(max(0, s)) + 1:04d}.jpg' if s is not None else None


def main():
    wf = J('wf_result.json', {})
    st = (J('structure_v4.json', {}) or {}).get('final') or {}
    ver = (J('structure_v4.json', {}) or {}).get('ver') or {}
    mk = J('mockups_index.json', {})
    synth = wf.get('synth') or {}
    finds = {f['id']: f for f in (wf.get('findings') or []) + ((wf.get('gapfill') or {}).get('findings') or [])}
    items = []

    # ── ТЗ-01: структура ──
    chs = (st.get('asis') or {}).get('chapters') or []
    fix = {(c['part'], c['n']): c for c in (ver.get('checks') or []) if not c.get('ok')}
    for c in chs:                                   # исправления проверяющего якорей
        f = fix.get(('asis', c['n']))
        if f and f.get('v4_tc'):
            c['v4_tc'], c['anchor'] = f['v4_tc'], f.get('anchor') or c['anchor']
    if chs:
        lst = [f'{c["v4_tc"]} ▸ {c["title"].upper()}' + (f' · {c["subtitle"]}' if c.get('subtitle') else '')
               for c in chs]
        subs = [f'{s["tc"]} ▸ {s["title"]} (гл.{i})' for i, c in enumerate(chs, 1) for s in (c.get('subchapters') or [])]
        yt = [f'{y["time"]} ▸ {y["title"]}' for y in (st.get('asis') or {}).get('youtube_chapters') or []]
        where = [f'{c["v4_tc"]} · карточка «{c["title"].upper()}» перед «{one(c["anchor"])}»' for c in chs]
        blocks = [('❌ СЕЙЧАС', ['В кате нет структуры: ни титула, ни одной карточки главы, ни подглав — '
                                 '50 минут одним потоком, зритель не понимает, где он в жизни героини.']),
                  ('✅ СДЕЛАТЬ', [f'Титул после тизера: «{st.get("film_title", "").upper()} / фильм» '
                                 f'на {st.get("title_card_tc", "")} (перед «{one(st.get("title_card_anchor", ""))}»).',
                                 f'Поставить {len(chs)} карточек глав в стиле YTCH11 (чёрный кадр, белый узкий капс '
                                 'столбиком, 2–3 с) — порядок ката не меняется, карточки встают на склейки.',
                                 'Подглавы — маленькие плашки слева-посередине (не полноэкранные).',
                                 'Главы — в описание YouTube (таймкоды ниже).']),
                  ('📋 СПИСОК', {'h': 'Главы (карточки)', 'items': lst})]
        if subs:
            blocks.append(('📋 СПИСОК', {'h': 'Подглавы (плашки)', 'items': subs}))
        if yt:
            blocks.append(('📋 СПИСОК', {'h': 'YouTube-главы для описания', 'items': yt}))
        blocks += [('📍 ГДЕ', where),
                   ('🎬 НА ТАЙМЛАЙНЕ', [f'{SEQ} · маркеры секвенции = эти главы (разноцветные)'])]
        mat = [{'img': os.path.basename(mk['structure_map']), 'cap': 'карта структуры · главы и подглавы на шкале 0–50:45',
                't': 'Мокап карты структуры (DRAFT)'}] if mk.get('structure_map') else []
        if mk.get('title'):
            mat.append({'img': os.path.basename(mk['title']), 'cap': f'{st.get("title_card_tc", "")} · титул (мокап в стиле YTCH11)',
                        't': 'Мокап титула (DRAFT)'})
        items.append({'key': 'structure', 'title': 'Структура: титул, главы и подглавы', 'category': 'structure',
                      'severity': 'must', 'v1_tc': '', 'tc_range': 'весь фильм', 'nado': nado(blocks),
                      'material_rich': mat, 'decision': (st.get('recommendation') or '') and
                      f'Структура v5 (перестановки) — см. ТЗ «Структура v5 (TO-BE)»: {one(st.get("recommendation"))}',
                      'ids': [], 'sensitive': False})
        tobe = st.get('tobe') or {}
        if tobe.get('moves'):
            tb = [('❌ СЕЙЧАС', ['Порядок v4 расходится с монтажным листом (квартира на 24:48, фонд с 10:57, финал — призыв).']),
                  ('✅ СДЕЛАТЬ', [one(tobe.get('notes')) or 'Пересобрать порядок по списку ниже.']),
                  ('📋 СПИСОК', {'h': 'Главы v5', 'items': [f'{c["v4_tc"]} ▸ {c["title"].upper()} — {one(c["purpose"])}'
                                                          for c in tobe.get('chapters') or []]}),
                  ('📋 СПИСОК', {'h': 'Перестановки и вставки', 'items': [f'{m["from_tc"]} ▸ {one(m["what"])} → {one(m["to"])} ({one(m["why"])})'
                                                                       for m in tobe['moves']]}),
                  ('📍 ГДЕ', [one(tobe.get('time_math'))])]
            items.append({'key': 'structure_tobe', 'title': 'Структура v5 (TO-BE) — решение Романа', 'category': 'structure',
                          'severity': 'should', 'v1_tc': '', 'tc_range': 'весь фильм', 'nado': nado(tb),
                          'material_rich': [], 'decision': 'Делать ли перестановки v5 или только карточки в v4?',
                          'ids': [], 'sensitive': False})

    # ── правки вердикта: must/should — слияние находок ──
    used = set()
    for sev in ('must', 'should'):
        for m in synth.get(sev) or []:
            src = [finds[i] for i in (m.get('ids') or []) if i in finds]
            used.update(f['id'] for f in src)
            t0 = min([sec(f.get('tc_start')) for f in src if sec(f.get('tc_start')) is not None] or [sec(m.get('tc'))] or [0])
            cats = [CAT.get(f.get('category'), 'check') for f in src]
            cat = max(set(cats), key=cats.count) if cats else 'check'
            now = list(dict.fromkeys(one(f.get('now')) for f in src if one(f.get('now'))))[:4]
            where = [f'{rng(f)} · якорь «{one(f.get("anchor"))}»' for f in src if f.get('anchor')]
            mats = list(dict.fromkeys(one(f.get('material')) for f in src if one(f.get('material'))))
            blocks = [('❌ СЕЙЧАС', now or [one(m.get('title'))]),
                      ('✅ СДЕЛАТЬ', [one(m.get('todo'))]),
                      ('📍 ГДЕ', where or [one(m.get('tc'))]),
                      ('📚 ИСТОЧНИК', mats),
                      ('🎬 НА ТАЙМЛАЙНЕ', [f'{SEQ} · V1 @ {tc(t0)}' if t0 is not None else ''])]
            # превью — только у обязательных (иначе сотни картинок и часовая сборка дока)
            items.append({'key': f'{sev}:{one(m.get("title"))[:60]}', 'title': one(m.get('title')), 'category': cat,
                          'severity': sev, 'v1_tc': tc(t0) if t0 is not None else '', 'tc_range': one(m.get('tc')),
                          'nado': nado(blocks),
                          'material_rich': [{'img': frame_img(t0), 'cap': f'{tc(t0)} · кадр в таймкод ТЗ', 't': ''}]
                          if t0 is not None and sev == 'must' else [],
                          'ids': [f['id'] for f in src], 'sensitive': any(f.get('sensitive') for f in src)})

    # ── прочие проверенные находки: только ОБЯЗАТЕЛЬНЫЕ (остальные покрыты группами should) ──
    for f in sorted(finds.values(), key=lambda x: sec(x.get('tc_start')) or 0):
        if f['id'] in used or f.get('severity') != 'must':
            continue
        t0 = sec(f.get('tc_start'))
        blocks = [('❌ СЕЙЧАС', [f.get('now')]), ('✅ СДЕЛАТЬ', [f.get('todo')]),
                  ('📍 ГДЕ', [f'{rng(f)} · якорь «{one(f.get("anchor"))}»']),
                  ('📚 ИСТОЧНИК', [f.get('material')]),
                  ('🎬 НА ТАЙМЛАЙНЕ', [f'{SEQ} · V1 @ {tc(t0)}' if t0 is not None else ''])]
        items.append({'key': f'find:{f["id"]}', 'title': one(f.get('now'))[:90], 'category': CAT.get(f.get('category'), 'check'),
                      'severity': f.get('severity', 'nice'), 'v1_tc': tc(t0) if t0 is not None else '',
                      'tc_range': rng(f), 'nado': nado(blocks),
                      'material_rich': [{'img': frame_img(t0), 'cap': f'{tc(t0)} · кадр в таймкод ТЗ', 't': ''}]
                      if t0 is not None else [],
                      'ids': [f['id']], 'sensitive': bool(f.get('sensitive'))})

    # ── чек-лист фонда → ТЗ ⚠️ (дедуп: пропускаем точки, уже покрытые правкой в ±5 с) ──
    taken = [sec(x['v1_tc']) for x in items if x['v1_tc']]
    for c in (wf.get('tables') or {}).get('fund_checklist') or []:
        t0 = sec(c.get('tc'))
        if t0 is not None and any(abs(t0 - t) < 5 for t in taken if t is not None):
            continue
        blocks = [('❌ СЕЙЧАС', [c.get('what')]), ('✅ СДЕЛАТЬ', [c.get('action')]),
                  ('📍 ГДЕ', [one(c.get('tc'))]), ('📚 ИСТОЧНИК', [f'риск: {one(c.get("risk"))}'])]
        items.append({'key': f'fund:{one(c.get("tc"))}:{one(c.get("what"))[:40]}', 'title': one(c.get('what'))[:90],
                      'category': 'fund', 'severity': 'must' if c.get('priority') == 'high' else 'should',
                      'v1_tc': tc(t0) if t0 is not None else '', 'tc_range': one(c.get('tc')), 'nado': nado(blocks),
                      'material_rich': [{'img': frame_img(t0), 'cap': f'{tc(t0)} · кадр в таймкод ТЗ', 't': ''}]
                      if t0 is not None else [], 'ids': [], 'sensitive': True})
        if t0 is not None:
            taken.append(t0)

    # ── графика из аудита (подписи, хроно-титры, плашки), если не покрыта ──
    for g in (wf.get('tables') or {}).get('graphics_tz') or []:
        key = f'gfx:{one(g.get("type"))}:{one(g.get("tc"))}'
        t0 = sec(g.get('tc'))
        is_gulya = 'гул' in (g.get('text', '') + g.get('note', '')).lower() or 'панфилов' in g.get('text', '').lower()
        mat = [{'img': os.path.basename(mk['lt_gulya']), 'cap': f'{one(g.get("tc"))} · подпись (мокап, прозрачный PNG)',
                't': 'Жимагул Панфилова — куратор по семьям в Нижегородской области (burodd.ru/team/zhimagul-panfilova)',
                'src': 'https://burodd.ru/team/zhimagul-panfilova'}] if is_gulya and mk.get('lt_gulya') else \
            ([{'img': frame_img(t0), 'cap': f'{tc(t0)} · кадр в таймкод ТЗ', 't': ''}] if t0 is not None else [])
        blocks = [('❌ СЕЙЧАС', ['Графики нет.']), ('✅ СДЕЛАТЬ', [f'{one(g.get("type"))}: «{one(g.get("text"))}»']),
                  ('📍 ГДЕ', [one(g.get('tc'))]), ('📚 ИСТОЧНИК', [one(g.get('note'))])]
        items.append({'key': key, 'title': f'{one(g.get("type"))}: «{one(g.get("text"))[:60]}»', 'category': 'graphics',
                      'severity': 'should', 'v1_tc': tc(t0) if t0 is not None else '', 'tc_range': one(g.get('tc')),
                      'nado': nado(blocks), 'material_rich': mat, 'ids': [], 'sensitive': False})

    # ── стабильные номера: структура первой, остальное по таймлайну; старые ключи сохраняют номер/статус ──
    head = [x for x in items if x['key'].startswith('structure')]
    rest = sorted([x for x in items if not x['key'].startswith('structure')], key=lambda x: sec(x['v1_tc']) or 0)
    old = {p['key']: p for p in (J('pravki_v4.json', {}) or {}).get('all', [])}
    allp = head + rest
    for p in allp:
        o = old.get(p['key'])
        p['status'] = (o or {}).get('status', 'draft')
        p['roman_comment'] = (o or {}).get('roman_comment', [])
    for p in allp:                                   # канон v7 действует и на строку заголовка 【…】
        ms = list(TCRE.finditer(p['title']))
        if len(ms) >= 2:
            p['title'] = p['title'][:ms[1].start()].strip(' ,;·—.«(и') + '…'
    json.dump({'all': allp}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    cats = {}
    for p in allp:
        cats[p['category']] = cats.get(p['category'], 0) + 1
    print(f'pravki_v4: {len(allp)} ТЗ · {cats} · must {sum(p["severity"] == "must" for p in allp)}')


if __name__ == '__main__':
    main()
