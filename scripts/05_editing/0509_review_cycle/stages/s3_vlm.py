#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6 S3: Qwen2.5-VL-7B (mlx) — ДОСЛОВНАЯ транскрипция экранного текста + описание.

Для каждого экрана screens_v6.json — best-кадр (1920×1080). Два вопроса:
  1) перепиши весь текст на экране дословно (регистр, язык, знаки) — построчно;
  2) одной фразой: что за графика (титр/карта/схема/фото/лоуэр) и что изображено.
Чекпойнт: vlm_v6.jsonl (докидывает при повторном запуске).
env: ~/YTAI/environment/.venv_vlm/bin/python
"""
import json, os, sys
from pathlib import Path

os.environ.setdefault('HF_HOME', str(Path.home() / 'YTAI/models/huggingface'))
from _bootstrap import P, W6, M, HERE, ROOT, T  # noqa: E402

HIRES = W6 / 'hires'
OUT = W6 / 'vlm_v6.jsonl'
MODEL = 'mlx-community/Qwen2.5-VL-7B-Instruct-4bit'
P.banner('vlm')

import mlx.core as mx
from PIL import Image
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config

SMALL_PX = 1280                      # сторона кадра для повторной попытки после нехватки памяти GPU

# язык оригинала — по LANG (shared/i18n_strings/a1.py): ru — кириллица/английский, en — английский (AED, $ …)
Q_TEXT = T('a1.vlm_q_text')
Q_DESC = ("In one sentence (English, max 25 words): what kind of on-screen graphic is this "
          "(title card / lower third / map / diagram / chart / photo / video with caption) and what is shown?")

ev = json.load(open(W6 / 'screens_v6.json', encoding='utf-8'))
done = set()
if OUT.exists():
    for ln in open(OUT, encoding='utf-8'):
        try:
            done.add(json.loads(ln)['id'])
        except Exception:
            pass
todo = [e for e in ev if e['id'] not in done]
print(f'vlm: {len(ev)} screens, done {len(done)}, todo {len(todo)}', flush=True)
if not todo:
    sys.exit(0)

model, processor = load(MODEL)
config = load_config(MODEL)


def ask(img, q, max_tokens):
    f = apply_chat_template(processor, config, q, num_images=1)
    r = generate(model, processor, f, [img], max_tokens=max_tokens, temperature=0.0, verbose=False)
    return (r.text if hasattr(r, 'text') else str(r)).strip()


def ask_safe(img_path, q, max_tokens):
    """Memex — 16 ГБ, MLX держит ~10 ГБ wired: кадр 1920×1080 через vision-tower иногда не влезает
    (Metal «Insufficient Memory», а на повреждённом состоянии GPU — ValueError «take from an empty axis»).
    Первая неудача → чистим кэш MLX и повторяем на уменьшенном кадре; вторая → пустой ответ, один экран
    не должен ронять стадию (VLM у нас — признаки, дословный текст читает Apple Vision).
    → (текст, ok)."""
    try:
        return ask(img_path, q, max_tokens), True
    except (RuntimeError, ValueError) as e1:
        mx.clear_cache()
        print(f'  ⚠️ vlm {Path(img_path).name}: {type(e1).__name__} {str(e1)[:80]} — повтор на {SMALL_PX} px', flush=True)
    try:
        im = Image.open(img_path).convert('RGB')
        im.thumbnail((SMALL_PX, SMALL_PX))
        return ask(im, q, max_tokens), True
    except (RuntimeError, ValueError, OSError) as e2:
        mx.clear_cache()
        print(f'  ⚠️ vlm {Path(img_path).name}: {type(e2).__name__} {str(e2)[:80]} — пропуск экрана', flush=True)
        return '', False


with open(OUT, 'a', encoding='utf-8') as out:
    for i, e in enumerate(todo):
        P.pause_gate('vlm')          # граница экрана — единственное безопасное место паузы
        img = str(HIRES / e['best_frame'])
        if not os.path.exists(img):
            # раньше тут был голый continue: экран без кадра навсегда оставался в очереди,
            # и стадия никогда не «заканчивалась» сама. Пишем пропуск явно.
            out.write(json.dumps({'id': e['id'], 't0': e['t0'], 'best_frame': e['best_frame'],
                                  'vlm_text': '', 'vlm_desc': '',
                                  'skipped': 'нет кадра на диске'}, ensure_ascii=False) + '\n')
            out.flush()
            print(f'  ⚠️ {e["id"]}: нет кадра {e["best_frame"]} — записан пропуск', flush=True)
            continue
        txt, ok_txt = ask_safe(img, Q_TEXT, 220)
        desc, ok_desc = ask_safe(img, Q_DESC, 60)
        rec = {'id': e['id'], 't0': e['t0'], 'best_frame': e['best_frame'],
               'vlm_text': txt, 'vlm_desc': desc}
        if not (ok_txt or ok_desc):
            rec['skipped'] = 'vlm не смог (память GPU)'
        out.write(json.dumps(rec, ensure_ascii=False) + '\n')
        out.flush()
        mx.clear_cache()             # кэш буферов MLX между экранами не копим — иначе 16 ГБ уходят в OOM
        if i % 10 == 0:
            print(f'  {i}/{len(todo)} {e["id"]} @{e["tc"]} → {txt[:70]!r}', flush=True)
print('vlm done', flush=True)
