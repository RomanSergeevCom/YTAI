#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6 S5: САМОПРОВЕРКА подготовки (Роман: «если долго — чтобы шла самопроверка, что всё хорошо»).

Проверяет каждый артефакт локального конвейера и пишет prep_check.json + человекочитаемый
вердикт в stdout. Код выхода 1 = что-то не так (run_prep.sh ретраит стадию).
usage: s5_selfcheck.py [frames|ocr|vlm|llm|all]
"""
import json, re, sys
from pathlib import Path

from _bootstrap import P, W6, M, HERE, ROOT  # noqa: E402

# Раньше тут стояло 2440 — число кадров ПЕРВОГО ката. На кате другой длины условие
# не выполнялось никогда: стадия стирала кадры и перегоняла 4K заново три раза подряд,
# после чего прогон объявлялся провальным при технически верных данных.
EXPECT_FRAMES = P.expect_frames()
TOL = P.FRAMES_TOLERANCE
stage = sys.argv[1] if len(sys.argv) > 1 else 'all'
rep, bad = {}, []


def check_frames():
    n = len(list((W6 / 'hires').glob('h*.jpg')))
    small = [p.name for p in (W6 / 'hires').glob('h*.jpg') if p.stat().st_size < 20_000]
    rep['frames'] = {'count': n, 'expected': EXPECT_FRAMES, 'tolerance': TOL,
                     'suspicious_small': small[:10]}
    if n < EXPECT_FRAMES - TOL:
        bad.append(f'frames: {n} < {EXPECT_FRAMES}')
    if len(small) > 5:
        bad.append(f'frames: {len(small)} подозрительно маленьких (<20 КБ) — битые кадры?')


def check_ocr():
    p = W6 / 'ocr_hires.jsonl'
    if not p.exists():
        bad.append('ocr: нет ocr_hires.jsonl'); return
    n, txt, broken = 0, 0, 0
    for ln in open(p, encoding='utf-8'):
        try:
            d = json.loads(ln); n += 1
            if d.get('lines'):
                txt += 1
        except Exception:
            broken += 1
    ev = json.load(open(W6 / 'screens_v6.json')) if (W6 / 'screens_v6.json').exists() else []
    lo, hi = P.screens_range()
    min_txt = P.min_frames_with_text()
    rep['ocr'] = {'frames': n, 'with_text': txt, 'broken_lines': broken, 'screens': len(ev),
                  'expect_screens': [lo, hi], 'min_with_text': min_txt}
    if n < EXPECT_FRAMES - TOL:
        bad.append(f'ocr: {n} кадров < {EXPECT_FRAMES}')
    if broken:
        bad.append(f'ocr: {broken} битых JSON-строк')
    if txt < min_txt:
        bad.append(f'ocr: с текстом всего {txt} (ожидали ≥{min_txt}) — OCR отработал?')
    if not (lo <= len(ev) <= hi):
        bad.append(f'ocr: событий экранов {len(ev)} — вне ожидаемого {lo}..{hi}')
    # Якоря дословности — тексты, которые ТОЧНО есть в ЭТОМ кате (prep_config.json → ocr_anchors).
    # Пустой список = проверка не применяется. Раньше тут были зашиты якоря первого фильма,
    # и на любом другом кате селфчек браковал корректный прогон.
    # Й/И и Ё/Е OCR путает на титрах — якоря сравниваем в нормализованном виде.
    if P.OCR_ANCHORS:
        allt = ' '.join(' '.join(e['texts_all']) for e in ev).upper().replace('Й', 'И').replace('Ё', 'Е')
        for anchor in P.OCR_ANCHORS:
            if anchor.upper().replace('Й', 'И').replace('Ё', 'Е') not in allt:
                bad.append(f'ocr: якорь «{anchor}» не найден в текстах экранов')
        rep['ocr']['anchors_ok'] = [a for a in P.OCR_ANCHORS
                                    if a.upper().replace('Й', 'И').replace('Ё', 'Е') in allt]
    else:
        rep['ocr']['anchors_ok'] = 'якоря не заданы — проверка пропущена'


def check_vlm():
    p = W6 / 'vlm_v6.jsonl'
    ev = json.load(open(W6 / 'screens_v6.json'))
    if not p.exists():
        bad.append('vlm: нет vlm_v6.jsonl'); return
    recs = {}
    for ln in open(p, encoding='utf-8'):
        try:
            r = json.loads(ln); recs[r['id']] = r
        except Exception:
            pass
    empty = [i for i, r in recs.items() if len(r.get('vlm_text', '')) < 2]
    notext = [i for i, r in recs.items() if 'NO TEXT' in r.get('vlm_text', '').upper()]
    rep['vlm'] = {'done': len(recs), 'screens': len(ev), 'empty': len(empty), 'no_text': len(notext)}
    if len(recs) < len(ev):
        bad.append(f'vlm: {len(recs)}/{len(ev)} экранов')
    if len(notext) > len(ev) * .35:
        bad.append(f'vlm: NO TEXT у {len(notext)} экранов — модель не читает кадры?')
    # кириллица должна присутствовать в большинстве транскрипций
    cyr = sum(1 for r in recs.values() if re.search(r'[А-Яа-я]', r.get('vlm_text', '')))
    rep['vlm']['cyrillic'] = cyr
    if recs and cyr < len(recs) * .4:
        bad.append(f'vlm: кириллица только в {cyr}/{len(recs)} — транскрибирует не то')


def check_llm():
    p = W6 / 'llm_v6.json'
    if not p.exists():
        bad.append('llm: нет llm_v6.json'); return
    res = json.load(open(p, encoding='utf-8'))
    ev = json.load(open(W6 / 'screens_v6.json'))
    jobs = [e for e in ev if len(re.sub(r'\W', '', e['text_best'])) >= 3]
    raw = [r['id'] for r in res if 'raw' in r]
    sev = {}
    for r in res:
        sev[r.get('severity')] = sev.get(r.get('severity'), 0) + 1
    rep['llm'] = {'done': len(res), 'jobs': len(jobs), 'unparsed': len(raw), 'severity': sev}
    if len(res) < len(jobs):
        bad.append(f'llm: {len(res)}/{len(jobs)}')
    if len(raw) > len(jobs) * .1:
        bad.append(f'llm: {len(raw)} ответов не распарсились как JSON')
    # Известные опечатки ЭТОГО ката: {секунда: 'слово'} из prep_config.json → llm_anchors.
    # Пусто = проверка пропущена. Флаг мягкий: стадию не валит.
    for t0, word in P.LLM_ANCHORS.items():
        hit = [r for r in res if abs(r['t0'] - t0) <= 4 and any(word.lower() in str(x).lower() for x in (r.get('typos') or []))]
        rep['llm'][f'anchor_{word}'] = bool(hit)
        if not hit:
            bad.append(f'llm: известная опечатка «{word}» @{t0}s не поймана корректором (мягкий флаг)')


def check_transcript():
    """Контракт words.json: segments[].words[].{w, s, e}, где s/e — ЧИСЛА-секунды (формат wordrole).

    Чужой формат (строки «M:SS.sss», как в Claude4_assembly) роняет float() в трёх скриптах.
    Хуже, если ключа words нет вовсе: `seg.get('words') or []` ничего не роняет, но молча
    обнуляет озвучку в пакетах аудита, якоря ТЗ и каталог терминов.
    """
    p = Path(P.WORDS)
    if not p.exists():
        bad.append(f'transcript: нет {p}')
        return
    d = json.load(open(p, encoding='utf-8'))
    segs = d.get('segments') or []
    words = [w for s in segs for w in (s.get('words') or [])]
    num = lambda v: isinstance(v, (int, float))                            # noqa: E731
    nonnum = [w for w in words if not (num(w.get('s')) and num(w.get('e')))]
    no_words = sum(1 for s in segs if not s.get('words'))
    last = max((w['e'] for w in words if num(w.get('e'))), default=0)
    rep['transcript'] = {'segments': len(segs), 'words': len(words), 'segments_without_words': no_words,
                         'non_numeric_times': len(nonnum), 'last_word_sec': round(last, 1),
                         'language': d.get('language'), 'diarization': d.get('diarization')}
    if not words:
        bad.append('transcript: ни одного слова в segments[].words — озвучка в аудите будет пустой')
    if nonnum:
        bad.append(f'transcript: {len(nonnum)} слов с нечисловыми s/e (не формат wordrole) — float() упадёт')
    if segs and no_words > len(segs) * .1:
        bad.append(f'transcript: {no_words}/{len(segs)} сегментов без words[]')
    dur = P.duration_sec()
    if words and not (dur * .6 <= last <= dur + 5):
        bad.append(f'transcript: последнее слово на {last:.0f} с, а кат {dur:.0f} с — транскрипт от другого файла?')


funcs = {'frames': check_frames, 'ocr': check_ocr, 'transcript': check_transcript,
         'vlm': check_vlm, 'llm': check_llm}
for k in (funcs if stage == 'all' else [stage]):
    try:
        funcs[k]()
    except Exception as ex:
        bad.append(f'{k}: исключение {ex}')
rep['bad'] = bad
json.dump(rep, open(W6 / f'prep_check_{stage}.json', 'w'), ensure_ascii=False, indent=1)
print(json.dumps(rep, ensure_ascii=False, indent=1))
hard = [b for b in bad if 'мягкий' not in b]
print('SELFCHECK', stage, 'OK' if not hard else f'FAIL ({len(hard)})')
sys.exit(1 if hard else 0)
