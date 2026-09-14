#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Чек-лист согласования с фондом по монтажу v4 (YTCH12).

Политика 27.08 (feedback_ytch_sensitive_fund_approved): чувствительное — НЕ стоп,
а ⚠️ «на подтверждение фонда / блюр». Реестр рисков ТЗ = чек-лист, не нож.
Паттерны: реестр ТЗ + всё, что ревью v1/v2 отмечали стопами.

Выход: risk_hits.json [{label,kind,tc,t0,t1,speaker,hit,context}]
  kind: 'fund' — согласовать с фондом / блюр; 'soft' — формулировка/рамка.
"""
import json
import os
import re

WORK = os.path.dirname(os.path.abspath(__file__))
REV = '/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review'
WORDS = (REV + '/YTCH12_v4.words.json') if os.path.exists(REV + '/YTCH12_v4.words.json') \
    else REV + '/_wordrole_work/YTCH12_v4_words.json'

PATTERNS = [
    ('Тайна усыновления (Руслан → Денис)',        'fund', r'усынов|руслан|денис'),
    ('СВО (брат / дядя Женя)',                    'fund', r'^сво$|спецоперац|одной ногой'),
    # паттерны — по ОДНОМУ нормализованному слову; «сбила» (авария отца) и «повесила» (колготки) — ложные
    ('Суицидальные высказывания',                 'fund', r'^умереть$|^сбей$|покончи|повеситьс|повешус|самоубий|суицид'),
    ('Аборт / беременность',                      'fund', r'аборт|выкидыш'),
    ('Работодатель (сеть) / карта на чужое имя',  'fund', r'магнит|пятерочк|банкрот|арест|чужое|другое имя'),
    ('Домогательства',                            'fund', r'домогат|приставал|пристава'),
    ('Алкоголь (Света о себе)',                   'fund', r'алкогол|выпив|напива|пиво|^пью$|бухал'),
    ('Неофициальная работа',                      'fund', r'неофициальн|вчерную'),
    ('Насилие в семье (нож / била)',              'fund', r'ножом|^нож$|избива|^била$|^бил$'),
    ('Опека / лишение прав',                      'fund', r'опек|лишени|лишить|родительских'),
    ('Фото детей без одежды («голенькие»)',        'fund', r'голеньк|голые|голый'),
    ('ФИО ребёнка / фамилии',                     'fund', r'дядяков|фамили|отчеств'),
    ('ВИЧ / диагнозы',                            'fund', r'^вич$|^спид$|диагноз|психиатр'),
    ('Братья: инвалидность',                      'soft', r'инвалид|коррекционн'),
    ('«Рукожоп» (самоуничижение, ломает рамку)',  'soft', r'рукожоп'),
    ('Возраст «37» (цифра только от фонда)',       'soft', r'^37$|тридцатисем'),
    # «забер-» без якоря ловит «забеременела» — только формы глагола «забрать»
    ('«Квартиру заберут» (юр. формулировка)',     'soft', r'^забер(у|ут|ет|ете)$|^забрать$|^одобрят$|отобра'),
    ('Третьи лица (муж Сергей, слухи, прокуратура)', 'soft', r'слухи|сергей|прокуратур'),
]


def main():
    d = json.load(open(WORDS, encoding='utf-8'))
    words = []
    for seg in d['segments']:
        for w in seg.get('words') or []:
            words.append((w['w'], float(w['s']), float(w['e']),
                          w.get('speaker') or seg.get('speaker') or ''))
    hits = []
    for i, (w, s, e, spk) in enumerate(words):
        wn = re.sub(r'[^а-яa-z0-9]', '', w.lower().replace('ё', 'е'))
        if not wn:
            continue
        for label, kind, pat in PATTERNS:
            if re.search(pat, wn):
                hits.append({'label': label, 'kind': kind,
                             'tc': '%d:%02d' % (int(s) // 60, int(s) % 60),
                             't0': round(s, 2), 't1': round(e, 2), 'speaker': spk, 'hit': w,
                             'context': ' '.join(x[0] for x in words[max(0, i - 25):i + 25])})
    ded, last = [], {}
    for h in sorted(hits, key=lambda x: x['t0']):
        if h['label'] in last and h['t0'] - last[h['label']] < 20:
            continue
        last[h['label']] = h['t0']
        ded.append(h)
    json.dump(ded, open(os.path.join(WORK, 'risk_hits.json'), 'w'), ensure_ascii=False, indent=1)
    print('risk hits:', len(ded), '(fund %d / soft %d)' % (
        sum(h['kind'] == 'fund' for h in ded), sum(h['kind'] == 'soft' for h in ded)))
    for h in ded:
        print(' [%s] %s @%s (%s): …%s…' % (h['kind'], h['label'], h['tc'], h['speaker'],
                                           h['context'][60:170]))


if __name__ == '__main__':
    main()
