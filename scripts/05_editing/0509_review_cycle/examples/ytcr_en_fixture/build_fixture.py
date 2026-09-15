#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_fixture.py — пересобрать синтетическую EN-фикстуру (канал YTCR, lang en, 29.97 fps, одно исключение).

Входы Memex-стадий без моделей: work/ocr_hires.jsonl (как пишет bin/vision_ocr_ru), vlm_v6.jsonl, llm_v6.json,
probes.jsonl, words.json (wordrole), review_card.json и канон облачного ответа cloud_canned.json. screens_v6.json
выводится настоящим s2_ocr_hires.py из ocr_hires.jsonl во временной папке (кадров нет → OCR не зовётся, только
пересборка инвентаря) и кладётся рядом — run_fixture.py сверяет, что s2 по-прежнему даёт тот же инвентарь.

Гонять руками после правки SCREENS (пишет в эту папку репо); selftest только читает фикстуру: run_fixture.py.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE = HERE.parent.parent

CARD = {
    'schema': 'review-card-v1', 'project': 'ytcrfx', 'code': 'YTCRFX', 'channel': 'YTCR', 'lang': 'en', 'language': 'en',
    'mode': 'cut_review', 'cut_version': 'v1', 'project_name': 'YTCRFX_Fixture',
    'words': 'words.json', 'duration_sec': 600, 'fps': 29.97, 'frames_tolerance': 2,
    'chapters': [[0, '01'], [300, '02']], 'ch_name': {'01': '[1] Hook, Epic', '02': '[2] Setup'},
    'ch_img': {}, 'sub': [], 'prog': {}, 'new_ch': [],
    'film': 'English-language documentary interview on the Core Realty Dubai channel (synthetic fixture): a Sudanese '
            'engineer who became a Dubai real-estate broker',
    'film_subject': 'Dubai real estate broker story', 'sources': [], 'ocr_anchors': [], 'llm_anchors': {},
    'work_dir': 'work/v1', 'pravki_dir': 'pravki', 'mockups_dir': 'mockups',
    'doc_id': 'FIXTURE_DOC', 'tab_title': 'Edit notes · v1', 'nav_tab': 'Cut review v1 · by timecode',
    'notes_sheet_id': 'FIXTURE_SHEET', 'sheet_url': 'https://docs.google.com/spreadsheets/d/FIXTURE_SHEET',
    'materials_id': 'FIXTURE_MATERIALS', 'project_folder_id': 'FIXTURE_PROJECT', 'sprint_folder_id': 'FIXTURE_SPRINT',
    'shots_remote': '', 'frozen_tabs': [],
    'terms_file': 'review_terms.json', 'ctl_dir': '/tmp/ytai_fixture_ctl',
    'exclusions': [{'t0': 500, 't1': 520, 'reason': 'missing footage (fixture: known black gap)'},
                   {'t0': None, 't1': None, 'reason': 'note without timecodes — ignored by the filter'}],
    'notes': ['synthetic EN fixture for review.py selftest — never a real project'],
}

# (t0, t1, OCR lines, VLM text, VLM description, voice-over sentence, llm extras, probe)
SCREENS = [
    (12, 16, ['DUBAI INFRASTURCTURE BOOM'], None, 'A title card over aerial footage of the Dubai skyline.',
     'When I came here everything was being built.', {}, None),
    (30, 34, ['СORE REALTY'], 'CORE REALTY', 'A lower third with the company name.',                  # Cyrillic С
     'I joined Core Realty after the agency.', {}, None),
    (48, 52, ['KHALID ALI', 'Founder · Core Realty'], None, 'A lower third with a name and role over an interview shot.',
     'My name is Khalid Ali.', {}, {'foreign': True, 'foreign_note': 'Core Realty logo in the corner'}),
    (66, 70, ['Welcome to Dubai', 'مرحبا بكم في دبي'], None, 'A title card with a bilingual greeting.',
     'People from everywhere live in this city.', {'foreign_script': ['مرحبا بكم في دبي']}, None),
    (84, 88, ['Palm Jebel Ali · off-plan · sqft'], None, 'A lower third over drone footage of villas.',
     'Off-plan on the Palm was the big thing.', {}, None),
    (102, 106, ['AED 2.5M'], None, 'A title card showing a price.',
     'Prices there start at 2.5 million dirhams, which is fair.', {}, None),
    (120, 124, ['AED 25M'], None, 'A title card showing a price.',
     'The penthouse sold for 2.5 million, a record then.', {'currency_numbers': ['AED 25M']}, None),
    (138, 142, ['Сделка закрыта'], None, 'A title card with white text on black.',
     'And the deal was closed that night.', {'foreign_script': ['Сделка закрыта']}, None),
    (156, 160, ['THE FIRST DEAL'], None, 'A chapter title card.',
     'The first deal changed everything for me.', {}, None),
    (174, 178, ['Brokerage Licnese'], None, 'A lower third over an office interior.',
     'You need a license to be a broker here.', {}, None),
    (192, 196, ['SHWARMA HOUSSE'], None, 'A photo of a street sign on a shop front.',
     'We used to eat on the street.', {}, None),
    (210, 214, ['ETISALAT · 2009'], None, 'A title card with a company name and a year.',
     'I joined Etisalat in 2009 as an engineer.', {}, None),
    (228, 232, ['MOVED TO DUBAI IN 2008'], None, 'A title card over airport footage.',
     'I moved to Dubai in 2009 with nothing.', {}, None),
    (246, 250, ['BUSINESS BAY', 'shutterstock'], None, 'Aerial footage of towers with a faint watermark across the frame.',
     'Business Bay was just sand back then.', {}, {'foreign': True, 'foreign_note': 'a Shutterstock watermark across the shot'}),
    (318, 322, ['CHAPTER 2 · SUDAN'], None, 'A chapter card.', 'I grew up in Khartoum.', {}, None),
    (336, 340, ['KHARTOUM, SUDAN'], None, 'A location caption over old family photos.', 'Khartoum was home.', {}, None),
    (354, 358, ['Integrity is everything'], None, 'A quote card.',
     'For me integrity is everything in this job.', {}, None),
    (372, 376, ['War Test & Fundamentals'], None, 'A chapter title card.',
     'Then the war tested the fundamentals.', {}, None),
    (505, 509, ['UNFINSHED TITEL HERE'], None, 'A title card, unfinished graphic.',              # inside the exclusion
     'We lost the footage here.', {'typos': ['UNFINSHED']}, None),
    (540, 544, ['The Big Check'], None, 'A title card.', 'And then came the big check.', {}, None),
]

# канон облачного ответа судьи J: вердикты по кандидатам cloud (первое совпадение match в тексте кандидата/экрана
# и kind, «*» = любой), новые находки — на экраны без кандидатов cloud; всё прочее — clean_screens
CANNED = {
    'verdicts': [
        {'match': 'AED 25M', 'kind': 'currency', 'verdict': 'confirm', 'fix_text': 'AED 2.5M', 'severity': 'high',
         'reason': 'The voice-over says 2.5 million; the screen shows AED 25M.'},
        {'match': 'shutterstock', 'kind': 'foreign_trace', 'verdict': 'confirm', 'fix_text': '', 'severity': 'high',
         'reason': 'A stock agency watermark is burned into the shot.'},
        {'match': 'MOVED TO DUBAI', 'kind': '*', 'verdict': 'confirm', 'fix_text': 'MOVED TO DUBAI IN 2009',
         'severity': 'high', 'reason': 'Khalid says he moved to Dubai in 2009; the title says 2008.'},
        {'match': 'مرحبا', 'kind': 'language', 'verdict': 'refute', 'fix_text': '', 'severity': 'low',
         'reason': 'An intentional bilingual greeting card of the channel.'},
        {'match': '*', 'kind': '*', 'verdict': 'refute', 'fix_text': '', 'severity': 'low',
         'reason': 'Not an error on this screen.'},
    ],
    'new_findings': [
        {'match': 'MOVED TO DUBAI IN 2008', 'kind': 'mismatch', 'fix_text': 'MOVED TO DUBAI IN 2009', 'severity': 'high',
         'problem': 'The title says 2008; the voice-over says 2009.', 'why': 'Voice-over: “I moved to Dubai in 2009”.'},
        {'match': 'shutterstock', 'kind': 'foreign_trace', 'fix_text': '', 'severity': 'high',
         'problem': 'A Shutterstock watermark is visible across the shot.', 'why': 'Replace the clip with a licensed one.'},
    ],
}


def line(t, i, n):
    return {'t': t, 'c': 1.0, 'x': 0.18, 'y': round(0.62 + 0.09 * i, 3), 'bw': 0.55, 'bh': 0.07}


def build(dst):
    work = dst / 'work'
    work.mkdir(parents=True, exist_ok=True)
    (dst / 'review_card.json').write_text(json.dumps(CARD, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (dst / 'cloud_canned.json').write_text(json.dumps(CANNED, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    with open(work / 'ocr_hires.jsonl', 'w', encoding='utf-8') as fh:
        for t0, t1, lines, *_ in SCREENS:
            for sec in range(t0, t1 + 1):
                fh.write(json.dumps({'file': f'/fixture/hires/h{sec + 1:04d}.jpg', 'faces': 0,
                                     'lines': [line(t, i, len(lines)) for i, t in enumerate(lines)]},
                                    ensure_ascii=False) + '\n')
    with open(work / 'vlm_v6.jsonl', 'w', encoding='utf-8') as fh:
        for k, (t0, t1, lines, vt, vd, *_r) in enumerate(SCREENS, 1):
            fh.write(json.dumps({'id': f's{k:03d}', 't0': t0, 'best_frame': f'h{t0 + 1:04d}.jpg',
                                 'vlm_text': vt if vt is not None else '\n'.join(lines), 'vlm_desc': vd},
                                ensure_ascii=False) + '\n')
    llm = []
    for k, (t0, t1, lines, _vt, _vd, _vo, extra, _pr) in enumerate(SCREENS, 1):
        rec = {'id': f's{k:03d}', 't0': t0, 't1': t1, 'ocr': ' | '.join(lines), 'typos': [], 'grammar': [],
               'currency_numbers': [], 'english_only': [], 'foreign_script': [], 'facts_to_check': [],
               'mismatch_with_vo': '', 'severity': 'low'}
        rec.update(extra)
        llm.append(rec)
    (work / 'llm_v6.json').write_text(json.dumps(llm, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    with open(work / 'probes.jsonl', 'w', encoding='utf-8') as fh:
        for k, (t0, t1, *_r, probe) in enumerate(SCREENS, 1):
            p = probe or {}
            fh.write(json.dumps({'screen_id': f's{k:03d}', 'foreign': bool(p.get('foreign')),
                                 'foreign_note': p.get('foreign_note', ''), 'cut_off': False, 'cut_note': '', 'zoom': [],
                                 'frames': [f'h{t0 + 1:04d}.jpg'], 'sec': 0.1}, ensure_ascii=False) + '\n')
    segs = []
    for k, (t0, *_r) in enumerate(SCREENS):
        text = SCREENS[k][5]
        start = t0 - 1.0
        ws = [{'w': w, 's': round(start + 0.34 * i, 2), 'e': round(start + 0.34 * i + 0.28, 2)} for i, w in enumerate(text.split())]
        segs.append({'id': k, 'start': start, 'end': ws[-1]['e'], 'text': text, 'speaker': 'SPEAKER_00', 'words': ws})
    (dst / 'words.json').write_text(json.dumps({'language': 'en', 'segments': segs}, ensure_ascii=False, indent=1) + '\n',
                                    encoding='utf-8')


def derive_screens(src):
    """настоящий s2_ocr_hires.py во временной копии: ocr_hires.jsonl → screens_v6.json (без кадров OCR не зовётся)"""
    with tempfile.TemporaryDirectory(prefix='ytai_fx_') as tmp:
        rv = Path(tmp) / 'YTCRFX_Fixture' / '00_Setup' / '05_Review'
        (rv / 'work/v1').mkdir(parents=True)
        shutil.copy2(src / 'review_card.json', rv / 'review_card.json')
        shutil.copy2(src / 'words.json', rv / 'words.json')
        shutil.copy2(src / 'work/ocr_hires.jsonl', rv / 'work/v1/ocr_hires.jsonl')
        env = {k: v for k, v in os.environ.items() if not k.startswith('YTAI_')}
        env['YTAI_CARD'] = str(rv / 'review_card.json')
        r = subprocess.run([sys.executable, str(STAGE / 'stages/s2_ocr_hires.py')], cwd=str(rv), env=env,
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise SystemExit(f's2_ocr_hires rc={r.returncode}: {(r.stdout + r.stderr)[-800:]}')
        return (rv / 'work/v1/screens_v6.json').read_text(encoding='utf-8')


if __name__ == '__main__':
    build(HERE)
    txt = derive_screens(HERE)
    (HERE / 'work' / 'screens_v6.json').write_text(txt, encoding='utf-8')
    print(f'fixture: {len(SCREENS)} screens → {HERE} (screens_v6.json: {len(json.loads(txt))} events)')
