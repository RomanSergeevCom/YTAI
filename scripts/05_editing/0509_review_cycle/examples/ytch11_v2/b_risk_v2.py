#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Риск-свип ката YTCH12 по стоп-реестру ТЗ (юр/этические стопы).

Ищет паттерны в пословном транскрипте КАТА, выдаёт окна контекста ±12с.
Выход: risk_hits.json [{label,hard,tc,t0,t1,hit,context}]
"""
import json, re, os

WORK = os.path.dirname(os.path.abspath(__file__))
CUT_WORDS = '/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review/YTCH12_v1.words.json'

PATTERNS = [
    ('Тайна усыновления (Руслан/Денис)', True,  r'усынов|руслан|денис'),
    ('СВО (брат/дядя)',                  True,  r'\bсво\b|спецоперац'),
    ('Суицидальные высказывания',        True,  r'умереть|сбей|сбила|аборт|на живот|выкидыш'),
    ('Работодатель (сеть, карта на чужое имя)', True, r'магнит\w*|банкрот|арест|на другое имя|на чужое'),
    ('Домогательства мастера',           True,  r'домогат|занизил|пристава\w*'),
    ('Алкоголь (стоп, если Света о себе)', True, r'алкогол|выпив|напива|пью|пила|бухал|не пью'),
    ('Неофициальная работа',             True,  r'неофициальн'),
    ('Братья: инвалидность/психиатрия (Валера)', False, r'инвалид|коррекционн|с головой|валер'),
    ('«Рукожопа» (ломает рамку)',        False, r'рукожоп'),
    ('Возраст «мне 37» (только от фонда)', False, r'\b37\b|тридцать семь'),
    ('«Квартиру могут забрать» (юр. формулировка)', False, r'забер|забрать|не одобр|отобра'),
    ('Третьи лица (муж Сергей, слухи, Катя, прокуратура)', False, r'слухи|сергей|кат[еюя]\b|прокуратур'),
    ('ВИЧ/диагнозы',                     True,  r'вич|спид|диагноз'),
]


def main():
    cut = json.load(open(CUT_WORDS, encoding='utf-8'))
    words = []
    for seg in cut['segments']:
        for w in seg.get('words') or []:
            words.append((w['w'], float(w['s']), float(w['e']),
                          w.get('speaker') or seg.get('speaker') or ''))
    hits = []
    for i, (w, s, e, spk) in enumerate(words):
        wl = w.lower().replace('ё', 'е')
        wn = re.sub(r'[^а-яa-z0-9 ]', '', wl)
        for label, hard, pat in PATTERNS:
            if re.search(pat, wn):
                ctx = ' '.join(x[0] for x in words[max(0, i-25):i+25])
                hits.append({'label': label, 'hard': hard,
                             'tc': '%d:%02d' % (int(s)//60, int(s) % 60),
                             't0': s, 't1': e, 'speaker': spk,
                             'hit': w, 'context': ctx})
    # дедуп: один label не чаще раза в 20 секунд
    ded, last = [], {}
    for h in hits:
        k = h['label']
        if k in last and h['t0'] - last[k] < 20:
            continue
        last[k] = h['t0']
        ded.append(h)
    json.dump(ded, open(os.path.join(WORK, 'risk_hits.json'), 'w'),
              ensure_ascii=False, indent=1)
    print('risk hits:', len(ded))
    for h in ded:
        print(' [%s]%s %s @%s: …%s…' % ('HARD' if h['hard'] else 'soft',
              '', h['label'], h['tc'], h['context'][:80]))


if __name__ == '__main__':
    main()
