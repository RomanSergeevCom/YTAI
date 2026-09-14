#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Строки вкладки «Ревью по видео · v4» (навигатор: канон YTCH11 Review_v2_video + KB review-timeline).
Один источник с вкладкой «ТЗ монтажёру · v4»: ГЛАВЫ = предложенные зрительские карточки
(chapters_cards.json, собран из structure_v4.json), ТЗ-номера = pravki_v4.json (синхронны с листом и маркерами).

ОДНА таблица по таймлайну v4; главы = merged-строки [🟩/🟨 NN. КАРТОЧКА · TC] + ⚠️ правки главы;
куски = абзацы wordrole внутри главы (≤80 с, разрез на смене спикера) — каждое слово ровно в одной строке.
Колонки: № | Таймкод (v4 + v2) | Статус | Транскрибация (полная, абзацы, спикеры, bold) |
         Экран (кадр 150pt + подпись по-русски) | ТЗ (номера и блоки из pravki_v4).
Выход: doc_content_review_v4.json, review_rows_v4.json, frames_wanted_nav.json.
"""
import json
import os
import re

WORK = os.path.dirname(os.path.abspath(__file__))
REV = os.path.dirname(WORK)
FOLDER = '1NQTnpDbPMhBxc8-872xWMULS5d9AC8IY'
SEV = {'must': '🔴', 'should': '🟠', 'nice': '⚪'}
SHADE = {'Green': 'green', 'Yellow': 'yellow', 'Red': 'red'}
ICON = {'Green': '🟩', 'Yellow': '🟨', 'Red': '🟥'}


def J(name, default=None):
    p = os.path.join(WORK, name)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else default


def tc(x):
    x = int(float(x))
    return '%d:%02d' % (x // 60, x % 60)


def sec(s):
    m = re.findall(r'\d+(?:\.\d+)?', str(s or ''))
    p = [float(x) for x in m[:3]]
    if not p:
        return None
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else (p[0] * 60 + p[1] if len(p) == 2 else p[0])


def toks(t):
    return re.findall(r'[а-яёa-z0-9]+', t.lower().replace('ё', 'е'))


def bold_exact(cell, phrase):
    tk = re.findall(r'\w+', phrase)
    if len(tk) < 3:
        return None
    m = re.search(r'\W*'.join(map(re.escape, tk)), cell, re.I)
    return m.group(0) if m and '\n' not in m.group(0) else None


def main():
    words = json.load(open(f'{REV}/YTCH12_v4.words.json', encoding='utf-8'))
    spk = J('speakers.json', {})
    chapters = sorted(J('chapters_cards.json'), key=lambda c: c['tc_sec'])
    total = float(words['duration_sec'])
    wf = J('wf_result.json', {}) or {}
    phrases = [p for c in (wf.get('chapters') or []) for p in (c.get('bold_phrases') or [])]
    m2 = J('map_v2.json', [])
    new_v2 = (J('diff_v2.json', {}) or {}).get('new', [])
    vlm_ru = J('vlm_ru.json', {})
    vsecs = sorted(int(k) for k in vlm_ru)
    pr = (J('pravki_v4.json', {}) or {}).get('all', [])
    for i, p in enumerate(pr):
        p['num'] = f'ТЗ-{i + 1:02d}'
        p['_sec'] = sec(str(p.get('v1_tc') or '').split('–')[0]) if p.get('v1_tc') else None
    act = [p for p in pr if p.get('status') != 'rejected' and p['_sec'] is not None]

    for i, ch in enumerate(chapters):
        ch['t1'] = chapters[i + 1]['tc_sec'] if i + 1 < len(chapters) else total + 1
        ch['n'] = i + 1
    paras = words['paragraphs']
    seg_words = [w['w'] for s in words['segments'] for w in s['words']]
    assert toks(' '.join(seg_words)) == toks(' '.join(w['w'] for p in paras for w in p['words'])), 'абзацы ≠ сегменты'

    rows, flat, wanted, used = [], [], [], set()
    n_piece = 0
    for ch in chapters:
        mine = [p for p in act if ch['tc_sec'] - 0.5 <= p['_sec'] < ch['t1'] - 0.5]
        col = 'Yellow' if any(p.get('severity') in ('must', 'should') for p in mine) else 'Green'
        warn = [f'{p["num"]} {p["title"]}' for p in mine if p.get('severity') == 'must'][:4]
        head = f'[{ICON[col]} {ch["n"]:02d}. {ch["name"].split(" ", 1)[1]} · {tc(ch["tc_sec"])}–{tc(min(ch["t1"], total))}]'
        rows.append({'kind': 'chapter', 'text': head + (('\n⚠️ ' + ' · '.join(warn)) if warn else ''), 'shade': SHADE[col]})
        ps = [p for p in paras if ch['tc_sec'] - 0.05 <= float(p['start']) < ch['t1'] - 0.05]
        pieces, cur = [], []
        for p in ps:
            if cur:
                d_all = float(p['end']) - float(cur[0]['start'])
                d_cur = float(cur[-1]['end']) - float(cur[0]['start'])
                if d_all > 80 or (p['speaker'] != cur[-1]['speaker'] and d_cur >= 15):
                    pieces.append(cur)
                    cur = []
            cur.append(p)
        if cur:
            pieces.append(cur)
        for pc in pieces:
            n_piece += 1
            a, b = float(pc[0]['start']), float(pc[-1]['end'])
            parts, last = [], None
            for p in pc:
                txt = ' '.join(w['w'] for w in p['words']).strip()
                name = spk.get(p['speaker'], p['speaker'])
                parts.append(f'{name}: {txt}' if name != last else txt)
                last = name
                flat += [w['w'] for w in p['words']]
            cell_tr = '\n\n'.join(parts)
            ov = [(min(b, m['v4_t1']) - max(a, m['v4_t0']), m) for m in m2]
            ov = [x for x in ov if x[0] > 0]
            if ov:
                o, m = max(ov, key=lambda x: x[0])
                v2t = m['b_t0'] + (max(a, m['v4_t0']) - m['v4_t0'])
                offs = [mm['b_t0'] - mm['v4_t0'] for oo, mm in ov if oo > 5]
                v2tc = f'v2 {tc(v2t)}' + (' (сборный)' if len(offs) > 1 and max(offs) - min(offs) > 30 else '')
            else:
                v2tc = 'v2 —'
            pf = [p for p in act if a - 0.5 <= p['_sec'] < b + 0.5 and p['num'] not in used]
            used.update(p['num'] for p in pf)
            st = []
            if ch['n'] == 1 and a < 80:
                st.append('тизер')
            if any(p['speaker'] == 'Speaker 2' for p in pc):
                st.append('фонд (Гуля)')
            if any(x['t0'] < b and x['t1'] > a for x in new_v2):
                st.append('➕ нов. vs v2')
            if any(p.get('severity') == 'must' and p['category'] != 'fund' for p in pf):
                st.append('⚠️ правка')
            if any(p['category'] == 'fund' for p in pf):
                st.append('⚠️ фонд')
            tz = '\n\n'.join(f'{p["num"]} {SEV.get(p.get("severity"), "")} · ⏱ {p.get("tc_range")}\n【{p["title"]}】\n{p["nado"]}'
                             for p in pf)
            fsec = int(pf[0]['_sec']) if pf else int((a + b) / 2)
            fsec = max(0, min(fsec, int(total) - 1))
            img = f'f{fsec + 1:04d}.jpg'
            wanted.append(img)
            near = min(vsecs, key=lambda s: abs(s - fsec)) if vsecs else None
            cap = vlm_ru.get(str(near), '') if near is not None else ''
            bold = []
            for ph in phrases:
                ex = bold_exact(cell_tr, ph)
                if ex and ex not in bold:
                    bold.append(ex)
            rows.append({'kind': 'row', 'cells': [str(n_piece), f'v4 {tc(a)}–{tc(b)}\n{v2tc}', ' · '.join(st) or 'в кате',
                                                  cell_tr, f'{tc(fsec)} · {cap}'.strip(' ·'), tz],
                         'img': img, 'img_w': 150, 'shade': 'yellow' if pf else '', 'bold': bold,
                         't0': a, 't1': b, 'chapter': ch['n'], 'tz': [p['num'] for p in pf]})
    assert toks(' '.join(flat)) == toks(' '.join(seg_words)), 'ПАРТИЦИЯ нарушена'
    # ТЗ, не попавшие в кусок (пауза/музыка) → в ближайший кусок
    for p in act:
        if p['num'] in used:
            continue
        rr = min((r for r in rows if r['kind'] == 'row'), key=lambda r: abs(r['t0'] - p['_sec']))
        rr['cells'][5] = (rr['cells'][5] + '\n\n' if rr['cells'][5] else '') + \
            f'{p["num"]} {SEV.get(p.get("severity"), "")} · ⏱ {p.get("tc_range")}\n【{p["title"]}】\n{p["nado"]}'
        rr['tz'].append(p['num'])
        rr['shade'] = 'yellow'
        used.add(p['num'])
    json.dump(rows, open(os.path.join(WORK, 'review_rows_v4.json'), 'w'), ensure_ascii=False, indent=1)
    json.dump(sorted(set(wanted)), open(os.path.join(WORK, 'frames_wanted_nav.json'), 'w'))
    n_rows = sum(r['kind'] == 'row' for r in rows)
    print(f'глав {len(chapters)} · кусков {n_rows} · слов {len(flat)} (партиция OK) · ТЗ в навигаторе {len(used)} · '
          f'bold {sum(len(r.get("bold") or []) for r in rows)} · кадров {len(set(wanted))}')

    s = wf.get('synth') or {}
    must = [p for p in pr if p.get('severity') == 'must' and p.get('status') != 'rejected']
    content = {
        'doc_title': 'YTCH12_Review_v4', 'folder_id': FOLDER,
        'paras': [[1, 'YTCH12 · Ревью по видео v4 — полная транскрибация по таймлайну (montage_1, 50:45)'],
                  [0, f'Вердикт: {s.get("verdict_short", "—").upper()} — {s.get("headline", "")}'],
                  [0, 'ОДНА таблица по таймлайну v4 (+ v2-TC для сверки со старым доком). Главы = предлагаемые зрительские '
                      'карточки (те же, что во вкладке «ТЗ монтажёру · v4»). Каждое слово ролика — ровно в одной строке; '
                      'жирное — опорные фразы; реплики подписаны: Света, Гуля (Жимагул Панфилова, куратор фонда). '
                      'ТЗ-NN — те же номера, что во вкладке ТЗ, в листе и на таймлайне.']],
        'pre_table': {'headers': ['ТЗ', 'TC', 'Обязательная правка', 'Что сделать'], 'widths': [40, 70, 190, 420],
                      'rows': [[p['num'], p.get('tc_range') or 'весь фильм', p['title'],
                                next((ln.split('·', 1)[1].strip() for ln in p['nado'].split('\n') if ln.startswith('✅ СДЕЛАТЬ')), '')]
                               for p in must]} if must else None,
        'paras2': [[2, 'Ревью по видео — одна таблица по таймлайну v4']],
        'table': {'headers': ['№', 'Таймкод', 'Статус', 'Транскрибация (полная)', 'Экран (кадр)', 'ТЗ'],
                  'widths': [24, 62, 66, 230, 168, 170], 'rows': rows},
        'post': [[2, 'Файлы'],
                 [0, 'Мастер: T9-Black · YTCH12_Sveta/03_Exports/YTCH12_Sveta_montage_1.mp4 (24,2 ГБ, 1080p25) · лайт 4K '
                     'кадр-в-кадр: 03_Exports/YTCH12_v4_light_4K.mp4 (3,2 ГБ) · транскрипт: 00_Setup/05_Review/'
                     'YTCH12_v4.review.html · таймлайн: 00_Setup/05_Review/YTCH12_review_v4_full.json · тулинг: '
                     '00_Setup/05_Review/v4_review/.']],
    }
    json.dump(content, open(os.path.join(WORK, 'doc_content_review_v4.json'), 'w'), ensure_ascii=False, indent=1)
    print('→ doc_content_review_v4.json')


if __name__ == '__main__':
    main()
