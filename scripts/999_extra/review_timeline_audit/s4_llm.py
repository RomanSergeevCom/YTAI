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
W6 = Path(__file__).parent
WORDS = '/Volumes/T7-Blue-2-RYA/YTUVI-Projects/YTUVI01_Corundum_Ruby/00_Setup/05_Review/YTUVI01_v1.words.json'
MODEL = 'mlx-community/Qwen3-8B-4bit'
OUT = W6 / 'llm_v6.json'

from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler

ws = []
for seg in json.load(open(WORDS, encoding='utf-8'))['segments']:
    for w in seg.get('words') or []:
        ws.append((w['w'], float(w['s']), float(w['e'])))


def vo(t0, t1, pad=6.0):
    return ' '.join(w for w, s, e in ws if t0 - pad <= s <= t1 + pad)


PROMPT = """/no_think Ты корректор и факт-чекер русскоязычного YouTube-фильма о рубинах.
Экран #{id} (таймкод {tc}). Текст на экране — два независимых распознавания:
OCR: {ocr}
VLM: {vlm}
Что за графика: {desc}
Озвучка в этот момент: {vo}

Правила канала: валюта — знак ПЕРЕД числом и сокращение: «$30,3 МЛН» (НЕ «30 300 000 $»); русский титр главный, английский допустим только вторым/меньше; термины и имена — без опечаток.
Игнорируй артефакты распознавания (обрезанные буквы, путаницу латиницы/кириллицы у OCR), если второе распознавание их не подтверждает.

Ответь СТРОГО одним JSON-объектом:
{{"typos": ["<слово с ошибкой → правильно>", ...],
 "grammar": ["<замечание или пусто>"],
 "currency_numbers": ["<нарушение формата: как на экране → как надо>"],
 "english_only": ["<английский текст/термин без русского перевода>"],
 "facts_to_check": ["<конкретное проверяемое утверждение: число/дата/имя>"],
 "mismatch_with_vo": "<экран противоречит озвучке — или пусто>",
 "severity": "none|low|high"}}"""

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
    v = vlm.get(e['id'], {})
    msg = PROMPT.format(id=e['id'], tc=e['tc'], ocr=' | '.join(e['texts_all'])[:600],
                        vlm=(v.get('vlm_text') or '—')[:600], desc=(v.get('vlm_desc') or '—')[:200],
                        vo=vo(e['t0'], e['t1'])[:900])
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
    rec = {'id': e['id'], 't0': e['t0'], 't1': e['t1'], 'tc': e['tc'], 'chapter': e['chapter'],
           'best_frame': e['best_frame'], 'ocr': e['text_best'][:300],
           'vlm': (v.get('vlm_text') or '')[:300], **parsed}
    res.append(rec)
    if i % 10 == 0:
        print(f'  {i}/{len(jobs)} {e["id"]} @{e["tc"]} sev={parsed.get("severity")}', flush=True)
        json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
print('llm done:', len(res), 'high:', sum(1 for r in res if r.get('severity') == 'high'), flush=True)
