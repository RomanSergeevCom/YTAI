#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v7 S14: доводка оставшихся строк ТЗ ЛОКАЛЬНОЙ моделью (Qwen3-8B, mlx) — когда облачные агенты недоступны.

Задача модели маленькая и проверяемая: разбить ОДНУ слитую строку на пункты формата «M:SS ▸ …»
(таймкод в начале, одна мысль в строке, без «→ / ; vs»-перечислений и без внутреннего жаргона hNNNN/sNNN).
Всё, что модель вернула, проверяет код: таймкоды не потеряны и не выдуманы, слова сохранены, в строке ≤1 таймкода.
Не прошло — берётся детерминированное разбиение. Вход: local_todo.json (нарушения) + r3_data.json (оригиналы).
Выход: r3/local_fixes.json {ТЗ-NN: parts_replace} → сливать merge_r3.py (guard_v7b).
env: ~/YTAI/environment/.venv_llm/bin/python
"""
import copy
import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault('HF_HOME', str(Path.home() / 'YTAI/models/huggingface'))
from _bootstrap import P, W6, M, HERE, ROOT  # noqa: E402
SP = W6 / 'polish'  # рабочие файлы полировки ТЗ
MODEL = 'mlx-community/Qwen3-8B-4bit'
TC = re.compile(r'(?<![\d:])~?\d{1,2}:\d{2}(?:\.\d+)?(?:\s*[–-]\s*\d{1,2}:\d{2}(?:\.\d+)?)?(?![\d:])')
# внутренний жаргон: имена кадров, ноты, комменты — вычищаем и после модели
JUNK = [(re.compile(r'\s*\(\s*[hsf]\d{3,4}(?:\s*[–,-]\s*[hsf]?\d{3,4})*\s*\)'), ''),
        (re.compile(r'\s*(?:в\s+)?кадр\w*\s+[hsf]\d{3,4}(?:\s*[–,-]\s*[hsf]?\d{3,4})*'), ''),
        (re.compile(r'\s*[hsf]\d{3,4}(?:\s*[–,-]\s*[hsf]?\d{3,4})*'), ''),
        (re.compile(r'\s*\(нот[аеы]\s*\d+\)|\s*нот[аеы]\s*\d+'), ''),
        (re.compile(r'\s*\(?коммент\s*\d+\)?'), ''),
        (re.compile(r'\s*\(ночн\w+ разбор\)|\s*ночн\w+ разбор'), ''),
        (re.compile(r'\s*\(ревью\s*№?\s*\d\)|\s*ревью\s*№?\s*\d'), '')]
PROMPT = """/no_think Ты редактор технического задания монтажёру (русский язык). Разбей ОДНУ строку на список коротких строк.

ПРАВИЛА:
1. Одна строка — одна мысль. Если в строке есть таймкод (формат M:SS или M:SS–M:SS), он ДОЛЖЕН стоять в начале своей строки: «9:32–9:50 ▸ что делать».
2. Перечисления через «→», «/», «;», «vs» разбей на отдельные строки; порядок шагов сохрани.
3. Убери внутренний жаргон: имена кадров вида h0555, s078, f0061, «нота 049», «коммент 050», «ночной разбор», «ревью №1».
4. НИЧЕГО не выдумывай и не теряй: все факты, числа, названия, цитаты в «…» и таймкоды сохрани дословно.
5. Не добавляй пояснений от себя.

ОТВЕТ: только JSON-массив строк, без пояснений. Пример: ["9:32–9:50 ▸ схема огранённого камня в разрезе", "площадка", "корона"]

СТРОКА: {line}
JSON:"""


def clean(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def strip_junk(s):
    for rx, rep in JUNK:
        s = rx.sub(rep, s)
    return clean(re.sub(r'\s+([,.;:])', r'\1', s)).strip(' ,;:—-')


def words(s):
    return {w for w in re.findall(r'\w+', s.lower()) if len(w) >= 4 and not re.fullmatch(r'[hsf]\d{3,4}', w)}


def det_split(s):
    """детерминированный запасной разбор: таймкод в начало, перечисления по разделителям"""
    s = strip_junk(s)
    m = TC.search(s)
    head = s
    if m and m.start() > 0:
        rest = clean(s[:m.start()] + ' ' + s[m.end():]).strip(' ,;:—-')
        rest = re.sub(r'\s*\bна\s*$', '', rest).strip(' ,;:—-')
        head = f'{m.group(0)} ▸ {rest}'
    parts = [clean(x) for x in re.split(r'\s*(?:→|;|(?<!\w)/(?!\w)|\svs\s)\s*', head) if clean(x)]
    return parts if len(parts) > 1 else [head]


def ok(orig, out):
    """проверка ответа модели: таймкоды, слова, ≤1 таймкода в строке"""
    if not out or not all(isinstance(x, str) and x.strip() for x in out):
        return False, 'пусто/не строки'
    joined = '\n'.join(out)
    to, tp = set(TC.findall(orig)), set(TC.findall(joined))
    if to - tp:
        return False, f'потеряны таймкоды {to - tp}'
    if tp - to:
        return False, f'новые таймкоды {tp - to}'
    wo, wp = words(strip_junk(orig)), words(joined)
    kept = len(wo & wp) / max(1, len(wo))
    if kept < 0.92:
        return False, f'слов {kept:.0%}'
    if len(wp - wo) > max(4, 0.25 * len(wp)):
        return False, 'много новых слов'
    for x in out:
        if len(TC.findall(x)) >= 2:
            return False, '≥2 таймкода в строке'
    return True, f'слов {kept:.0%}'


def main():
    todo = json.load(open(SP / 'local_todo.json'))
    data = json.load(open(SP / 'r3_data.json'))
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler
    print('загружаю', MODEL, flush=True)
    model, tok = load(MODEL)
    sampler = make_sampler(temp=0.2, top_p=0.9)
    out_parts, log = {}, []
    for num, viol in todo.items():
        parts = copy.deepcopy(data[num]['parts'])
        for v in viol:
            src = v['text']
            msg = tok.apply_chat_template([{'role': 'user', 'content': PROMPT.format(line=src)}],
                                          add_generation_prompt=True, tokenize=False)
            raw = generate(model, tok, prompt=msg, max_tokens=700, sampler=sampler, verbose=False)
            raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.S).strip()
            m = re.search(r'\[.*\]', raw, re.S)
            res, why = None, 'нет JSON'
            if m:
                try:
                    cand = [strip_junk(x) for x in json.loads(m.group(0))]
                    cand = [x for x in cand if x]
                    good, why = ok(src, cand)
                    res = cand if good else None
                except Exception as e:                              # noqa: BLE001
                    why = f'JSON: {e}'
            if res is None:
                res = det_split(src)
                why = f'локальная модель не прошла ({why}) → детерминированно'
            log.append({'tz': num, 'block': v['block'], 'src': src, 'out': res, 'why': why})
            print(f"{num} [{v['block']}] {why}: {' | '.join(x[:60] for x in res)}", flush=True)
            # вставляем результат на место исходной строки
            blk = parts.get(v['block']) or []
            for i, el in enumerate(blk):
                if isinstance(el, str) and el == src:
                    blk[i] = res[0] if len(res) == 1 else {'h': res[0], 'items': res[1:]}
                    break
                if isinstance(el, dict):
                    if v['kind'] == 'h' and el.get('h') == src:
                        el['h'] = res[0]
                        el['items'] = res[1:] + [x for x in (el.get('items') or []) if isinstance(x, str)]
                        break
                    if v['kind'] == 'i' and isinstance(el.get('items'), list) and src in el['items']:
                        j = el['items'].index(src)
                        el['items'][j:j + 1] = res
                        break
        out_parts[num] = parts
    (SP / 'r3').mkdir(exist_ok=True)
    json.dump(out_parts, open(SP / 'r3' / 'local_fixes.json', 'w'), ensure_ascii=False, indent=1)
    json.dump(log, open(SP / 'local_fixes_log.json', 'w'), ensure_ascii=False, indent=1)
    print(f'\nготово: ТЗ {len(out_parts)} · строк {len(log)} · '
          f'локальной моделью {sum(1 for x in log if "детерминированно" not in x["why"])}')


if __name__ == '__main__':
    main()
