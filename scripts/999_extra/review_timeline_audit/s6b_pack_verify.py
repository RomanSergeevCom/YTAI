#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6 S6b: пакеты для ДОГОНЯЮЩЕЙ проверки находок (после падения verify-фазы по лимиту сессии).

Зачем: wf_audit_v6.js проверяет находки тремя линзами сразу после аудита. Если линзы упали
(лимит сессии, сеть), находка остаётся без голосов — `status: unverified`. Этот скрипт собирает
такие находки в пакеты «одна находка = один файл» (агент читает только свой файл, не весь JSON)
и готовит материал для пропущенного критика полноты.

Вход:  audit_findings_v6.json (поле findings со status), screens_v6.json, vlm_v6.jsonl, llm_v6.json, words.json
Выход: verify_pack/v###.json      — находка + контекст экрана (кадры, OCR с bbox, VLM, флаги, озвучка)
       verify_pack/INDEX.json     — [{id, file, screen_id, tc, kind, severity, frame}] для args воркфлоу
       verify_pack/INVENTORY.json — все экраны компактно (id, tc, chapter, frame, ocr) для критика
       verify_pack/STATE.json     — {flagged, clean, confirmed_brief} — что аудиторы уже отметили

usage: python3 s6b_pack_verify.py [--findings audit_findings_v6.json] [--all]
       --all — переупаковать ВСЕ находки, а не только unverified (например, для повторного прогона)
"""
import argparse
import json
import sys
from pathlib import Path

W6 = Path(__file__).parent
sys.path.insert(0, str(W6))
import proj_config as P  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--findings', default=str(W6 / 'audit_findings_v6.json'))
ap.add_argument('--all', action='store_true')
a = ap.parse_args()

PACK = W6 / 'verify_pack'
PACK.mkdir(exist_ok=True)

data = P.audit_or_die(Path(a.findings), 'аудит экранов агентами (s6 → wf_audit_v6.js)')
findings = data['findings']
todo = findings if a.all else [f for f in findings if f.get('status') == 'unverified' or not f.get('votes')]
if not todo:
    raise SystemExit('нечего догонять: у всех находок есть голоса')

# ── контекст: экраны, VLM, LLM, озвучка ───────────────────────────────────
ev = {e['id']: e for e in json.load(open(W6 / 'screens_v6.json', encoding='utf-8'))}
vlm = {}
if (W6 / 'vlm_v6.jsonl').exists():
    for ln in open(W6 / 'vlm_v6.jsonl', encoding='utf-8'):
        try:
            r = json.loads(ln)
            vlm[r['id']] = r
        except Exception:
            pass
llm = {}
if (W6 / 'llm_v6.json').exists():
    for r in json.load(open(W6 / 'llm_v6.json', encoding='utf-8')):
        llm[r['id']] = {k: r.get(k) for k in ('typos', 'grammar', 'currency_numbers', 'english_only',
                                              'facts_to_check', 'mismatch_with_vo', 'severity')}
ws = []
for seg in json.load(open(P.WORDS, encoding='utf-8'))['segments']:
    for w in seg.get('words') or []:
        ws.append((w['w'], float(w['s'])))


def vo(t0, t1, pad=8.0):
    return ' '.join(w for w, s in ws if t0 - pad <= s <= t1 + pad)


index = []
# vid — адрес пакета ТЕКУЩЕГО прогона. Старые штампы снимаем: иначе вторая упаковка (после частичного
# падения) выдаст v001 новой находке, а merge вернёт её голоса на чужую находку с тем же старым v001.
for f in findings:
    f.pop('vid', None)
# порядок детерминированный (сортировка стабильная) → id пакета не «переедет» при повторной упаковке,
# и тот же id штампуется в саму находку (поле vid) — по нему merge_verify_v6.py вернёт голоса на место.
for i, f in enumerate(sorted(todo, key=lambda x: (x.get('t0', 0), x.get('screen_id', ''))), 1):
    fid = f'v{i:03d}'
    f['vid'] = fid
    e = ev.get(f['screen_id'], {})
    t0, t1 = f.get('t0', e.get('t0', 0)), f.get('t1', e.get('t1', 0))
    rec = {
        'id': fid,
        'finding': {k: f.get(k) for k in ('screen_id', 'tc', 't0', 't1', 'frame', 'kind', 'severity',
                                          'on_screen_text', 'problem', 'fix_text', 'evidence', 'bbox',
                                          'existing_tz', 'confidence')},
        'screen': {
            'tc': e.get('tc'), 'chapter': e.get('chapter'), 'dur': e.get('dur'),
            'frame_best': str(W6 / 'hires' / e['best_frame']) if e.get('best_frame') else f.get('frame'),
            'frame_last': str(W6 / 'hires' / e['last_frame']) if e.get('last_frame') else None,
            'frames_all': [str(W6 / 'hires' / f'h{s + 1:04d}.jpg') for s in range(t0, t1 + 1)],
            'ocr_best': e.get('text_best'), 'ocr_all_frames': e.get('texts_all'),
            'ocr_lines_best_bbox': [{'t': l['t'], 'x': l['x'], 'y': l['y'], 'w': l['bw'], 'h': l['bh']}
                                    for l in e.get('lines_best', [])],
            'vlm_text': vlm.get(f['screen_id'], {}).get('vlm_text'),
            'vlm_desc': vlm.get(f['screen_id'], {}).get('vlm_desc'),
            'llm_flags': llm.get(f['screen_id']),
            'voiceover_around': vo(t0, t1),
        },
        'hires_dir': str(W6 / 'hires'),
        'frame_naming': 'h{sec+1:04d}.jpg = секунда sec (кадр = сек+1)',
    }
    json.dump(rec, open(PACK / f'{fid}.json', 'w'), ensure_ascii=False, indent=1)
    index.append({'id': fid, 'file': str(PACK / f'{fid}.json'), 'screen_id': f['screen_id'], 'tc': f.get('tc'),
                  'kind': f.get('kind'), 'severity': f.get('severity'), 'frame': f.get('frame')})
json.dump(index, open(PACK / 'INDEX.json', 'w'), ensure_ascii=False, indent=1)

# ── инвентарь всех экранов + состояние аудита (для критика полноты) ────────
inventory = [{'id': e['id'], 'tc': e['tc'], 'chapter': e['chapter'],
              'frame': str(W6 / 'hires' / e['best_frame']), 'ocr': e['text_best']}
             for e in sorted(ev.values(), key=lambda x: x['t0'])]
json.dump(inventory, open(PACK / 'INVENTORY.json', 'w'), ensure_ascii=False, indent=1)

clean = sorted({sid for p in data.get('packs', []) for sid in (p.get('clean_screens') or [])})
state = {
    'flagged': sorted({f['screen_id'] for f in findings}),
    'clean': clean,
    'confirmed_brief': [f'{f["screen_id"]} {f["tc"]} [{f["kind"]}] «{f["on_screen_text"]}» → '
                        f'«{f.get("fix_text_final") or f.get("fix_text")}»'
                        for f in findings if f.get('confirmed')],
    'unverified_brief': [f'{f["screen_id"]} {f["tc"]} [{f["kind"]}] «{f["on_screen_text"]}»' for f in todo],
}
json.dump(state, open(PACK / 'STATE.json', 'w'), ensure_ascii=False, indent=1)

data['findings'] = findings                      # с проштампованными vid
json.dump(data, open(a.findings, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

print(f'пакетов на проверку: {len(index)} (из {len(findings)} находок)')
print(f'инвентарь экранов: {len(inventory)} · отмечено аудиторами: {len(state["flagged"])} · чистых: {len(clean)}')
print(f'→ {PACK}/INDEX.json · INVENTORY.json · STATE.json')
