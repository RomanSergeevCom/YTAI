#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Локальное сведение вердикта (агенты-синтезаторы не отработали: session limit).
synth_manual.json (вердикт и 15 обязательных правок — мои) + автогруппировка остальных находок
по (глава, категория) → synth в wf_result.json. Заголовки групп — ЛОКАЛЬНАЯ Qwen3-8B (.venv_llm),
при сбое — обрезанный текст находки. Ноль облачных токенов.
Usage: [PY=.venv_llm/bin/python] x_synth_local.py
"""
import json
import os
import re
import sys

WORK = os.path.dirname(os.path.abspath(__file__))
MODEL = 'mlx-community/Qwen3-8B-4bit'


def sec(s):
    m = re.findall(r'\d+', str(s or ''))
    return int(m[0]) * 60 + int(m[1]) if len(m) >= 2 else 0


def titles_local(groups):
    """Короткие заголовки групп локальной моделью; батчами по 10."""
    try:
        from mlx_lm import generate, load
    except Exception as e:                                  # noqa: BLE001
        print('mlx_lm недоступен:', str(e)[:80], '— заголовки из текста находок')
        return {}
    model, tok = load(MODEL)
    out = {}
    keys = list(groups)
    for i in range(0, len(keys), 10):
        chunk = keys[i:i + 10]
        lines = []
        for k, key in enumerate(chunk, 1):
            g = groups[key]
            lines.append(f'{k}| ' + ' || '.join(re.sub(r'\s+', ' ', f['now'])[:150] for f in g[:3]))
        prompt = ('Ты — редактор монтажного ТЗ. Для каждого пункта напиши КОРОТКИЙ заголовок правки '
                  'по-русски: 3–7 слов, без кавычек, без точки, по существу проблемы. '
                  'Ответ строго по строке на пункт в формате N|заголовок.\n' + '\n'.join(lines))
        p = tok.apply_chat_template([{'role': 'user', 'content': prompt}], add_generation_prompt=True,
                                    tokenize=False, enable_thinking=False)
        try:
            r = generate(model, tok, prompt=p, max_tokens=400, verbose=False)
        except Exception as e:                              # noqa: BLE001
            print('  генерация сбойнула:', str(e)[:80])
            continue
        r = re.sub(r'<think>.*?</think>', '', r, flags=re.S)
        for line in r.splitlines():
            m = re.match(r'\s*(\d+)\s*\|\s*(.+)', line)
            if m and 0 < int(m.group(1)) <= len(chunk):
                out[chunk[int(m.group(1)) - 1]] = m.group(2).strip().strip('«».')
        print(f'  заголовки {min(i + 10, len(keys))}/{len(keys)}', flush=True)
    return out


def main():
    wf = json.load(open(os.path.join(WORK, 'wf_result.json'), encoding='utf-8'))
    man = json.load(open(os.path.join(WORK, 'synth_manual.json'), encoding='utf-8'))
    finds = wf['findings']
    used = {i for m in man['must'] for i in m['ids']}
    rest = [f for f in finds if f['id'] not in used and f['severity'] in ('must', 'should')]
    groups = {}
    for f in rest:
        groups.setdefault((f.get('chapter', 0), f['category']), []).append(f)
    for g in groups.values():
        g.sort(key=lambda f: sec(f['tc_start']))
    order = sorted(groups, key=lambda k: min(sec(f['tc_start']) for f in groups[k]))
    names = titles_local(groups) if '--no-llm' not in sys.argv else {}
    should = []
    for n, key in enumerate(order, 1):
        g = groups[key]
        todo = ' · '.join(dict.fromkeys(re.sub(r'\s+', ' ', f['todo']).strip() for f in g))
        should.append({'num': n, 'title': names.get(key) or re.sub(r'\s+', ' ', g[0]['now'])[:70],
                       'tc': f"{g[0]['tc_start']}–{g[-1]['tc_end']}", 'todo': todo[:900],
                       'ids': [f['id'] for f in g]})
    wf['synth'] = {**{k: v for k, v in man.items()}, 'should': should, 'chapter_colors': []}
    json.dump(wf, open(os.path.join(WORK, 'wf_result.json'), 'w'), ensure_ascii=False)
    print(f'synth: must {len(man["must"])} (находок {len(used)}) · should-групп {len(should)} '
          f'(находок {len(rest)}) · вне ТЗ (nice) {sum(1 for f in finds if f["severity"] == "nice")}')


if __name__ == '__main__':
    main()
