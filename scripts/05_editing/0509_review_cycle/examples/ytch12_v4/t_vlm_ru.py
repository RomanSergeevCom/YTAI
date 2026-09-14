#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Подписи кадров по-русски: vlm_sweep.jsonl (Qwen2.5-VL, EN) → vlm_ru.json {sec: "перевод"}.
Локальная Qwen3-8B-4bit (venv .venv_llm, mlx_lm), батчи по 15, <think> вычищается.
Резюмируемо: уже переведённые секунды пропускаются. Запускать ПОСЛЕ VLM (один mlx за раз).
"""
import json
import os
import re

WORK = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(WORK, 'vlm_sweep.jsonl')
OUT = os.path.join(WORK, 'vlm_ru.json')
MODEL = 'mlx-community/Qwen3-8B-4bit'
BATCH = 15

from mlx_lm import generate, load  # noqa: E402

HEAD = ('Переведи на русский описания кадров документального фильма. Каждое — коротко, до 12 слов, '
        'естественным языком, без выдумок и без оценок. Женщина — просто «женщина», ребёнок — «ребёнок». '
        'Ответ строго по строке на пункт в формате N|перевод, ничего больше.\n')


def main():
    src = [json.loads(x) for x in open(SRC, encoding='utf-8')]
    done = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    todo = [r for r in src if str(r['sec']) not in done]
    print(f'captions: {len(src)} · done {len(done)} · todo {len(todo)}', flush=True)
    if not todo:
        return
    model, tok = load(MODEL)
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        prompt = HEAD + '\n'.join(f'{k + 1}|{r["desc"]}' for k, r in enumerate(batch))
        p = tok.apply_chat_template([{'role': 'user', 'content': prompt}], add_generation_prompt=True,
                                    tokenize=False, enable_thinking=False)
        out = generate(model, tok, prompt=p, max_tokens=900, verbose=False)
        out = re.sub(r'<think>.*?</think>', '', out, flags=re.S).strip()
        for line in out.splitlines():
            m = re.match(r'\s*(\d+)\s*\|\s*(.+)', line)
            if m and 0 < int(m.group(1)) <= len(batch):
                done[str(batch[int(m.group(1)) - 1]['sec'])] = m.group(2).strip().rstrip('.')
        json.dump(done, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
        print(f'  {min(i + BATCH, len(todo))}/{len(todo)} · {out.splitlines()[0][:70] if out else ""}', flush=True)
    print('vlm_ru:', len(done), flush=True)


if __name__ == '__main__':
    main()
