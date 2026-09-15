#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6 S4: Qwen3-8B (mlx-lm) — корректор каждого экрана.

Вход: screens_v6.json (OCR hires) + vlm_v6.jsonl (дословная VLM-транскрипция) +
озвучка ±6 с из words.json. Проверяет: опечатки/грамматика RU, формат валюты/чисел
(канон: знак ПЕРЕД числом, «$30,3 МЛН»), английский текст без перевода, спорные факты.
Выход: llm_v6.json. Чистим <think>…</think>.
env: ~/YTAI/environment/.venv_llm/bin/python
"""
import json, os, re, sys
from pathlib import Path

os.environ.setdefault('HF_HOME', str(Path.home() / 'YTAI/models/huggingface'))
from _bootstrap import P, W6, M, HERE, ROOT, T, LANG  # noqa: E402

WORDS = P.WORDS
MODEL = 'mlx-community/Qwen3-8B-4bit'
OUT = W6 / 'llm_v6.json'
SUBJECT = P.get('film_subject', T('a1.llm_subject_default'))     # чем фильм — идёт в промпт корректора
RULES = ''
if LANG == 'en':
    # «documentary{subject}»: пустая тема не оставляет висячий пробел; правила — из профиля канала
    SUBJECT = f' {str(SUBJECT).strip()}' if str(SUBJECT or '').strip() else ''
    RULES = str(P.profile('rules_text') or '').strip() or T('a1.llm_rules_default')
P.banner('llm')

from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler

ws = []
for seg in json.load(open(WORDS, encoding='utf-8'))['segments']:
    for w in seg.get('words') or []:
        ws.append((w['w'], float(w['s']), float(w['e'])))


def vo(t0, t1, pad=6.0):
    return ' '.join(w for w, s, e in ws if t0 - pad <= s <= t1 + pad)


# ru — канон YTUVI (правила зашиты в промпт); en — английский фильм: правила из профиля (rules_text),
# english_only всегда пуст, вместо него foreign_script — чужой алфавит в графике канала (не в реальном b-roll)
PROMPT = T('a1.llm_prompt')

ev = json.load(open(W6 / 'screens_v6.json', encoding='utf-8'))
vlm = {}
if (W6 / 'vlm_v6.jsonl').exists():
    for ln in open(W6 / 'vlm_v6.jsonl', encoding='utf-8'):
        try:
            r = json.loads(ln)
            vlm[r['id']] = r
        except Exception:
            pass
done = {}
if OUT.exists():
    try:
        done = {r['id']: r for r in json.load(open(OUT, encoding='utf-8'))}
    except Exception:
        done = {}

jobs = [e for e in ev if len(re.sub(r'\W', '', e['text_best'])) >= 3]
print(f'llm: {len(jobs)} screens (of {len(ev)}), done {len(done)}', flush=True)
model, tok = load(MODEL)
sampler = make_sampler(temp=0.0)
res = list(done.values())
for i, e in enumerate(jobs):
    if e['id'] in done:
        continue
    P.pause_gate('llm')              # граница экрана; дамп на диске уже согласован
    v = vlm.get(e['id'], {})
    msg = PROMPT.format(subject=SUBJECT, id=e['id'], tc=e['tc'], ocr=' | '.join(e['texts_all'])[:600],
                        vlm=(v.get('vlm_text') or '—')[:600], desc=(v.get('vlm_desc') or '—')[:200],
                        vo=vo(e['t0'], e['t1'])[:900], rules=RULES)
    prompt = tok.apply_chat_template([{'role': 'user', 'content': msg}], add_generation_prompt=True)
    r = generate(model, tok, prompt=prompt, max_tokens=400, sampler=sampler)
    r = re.sub(r'<think>.*?</think>', '', r, flags=re.S)
    m = re.search(r'\{.*\}', r, flags=re.S)
    parsed = {}
    if m:
        try:
            parsed = json.loads(m.group(0))
        except Exception:
            parsed = {'raw': r[:300]}
    if LANG == 'en' and isinstance(parsed, dict) and 'raw' not in parsed:
        # английский канал: «английский без перевода» не бывает ошибкой — даже если модель что-то туда положила
        parsed['english_only'] = []
        if not isinstance(parsed.get('foreign_script'), list):
            parsed['foreign_script'] = [parsed['foreign_script']] if parsed.get('foreign_script') else []
    rec ={'id': e['id'], 't0': e['t0'], 't1': e['t1'], 'tc': e['tc'], 'chapter': e['chapter'],
           'best_frame': e['best_frame'], 'ocr': e['text_best'][:300],
           'vlm': (v.get('vlm_text') or '')[:300], **parsed}
    res.append(rec)
    # дамп через временный файл + os.replace: обычный json.dump обнулял llm_v6.json
    # в момент открытия, и kill в это окно стирал стадию целиком. Раз в 5 экранов —
    # окно потери вдвое короче прежнего, цена записи копеечная (файл ~200 КБ).
    if i % 5 == 0:
        print(f'  {i}/{len(jobs)} {e["id"]} @{e["tc"]} sev={parsed.get("severity")}', flush=True)
        P.write_json_atomic(OUT, res)
P.write_json_atomic(OUT, res)
print('llm done:', len(res), 'high:', sum(1 for r in res if r.get('severity') == 'high'), flush=True)
