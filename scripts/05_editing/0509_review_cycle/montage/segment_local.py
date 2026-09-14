#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""segment_local.py — смысловая нарезка исходника ЛОКАЛЬНОЙ моделью (Qwen3-8B, mlx) → segments.json.

Транскрипт (words.json карточки) режется на окна по 3–4 минуты; на каждое окно модель возвращает
тезисы с якорями «секунда + слово» (тот же формат, что в montage_plan.json: in/out = [hint_sec, word]).
Код проверяет каждый якорь по words.json: слово должно быть в ±3 с от подсказки (иначе — попытка
подтянуть подсказку к ближайшему вхождению слова в ±10 с, флаг snapped; не нашлось — тезис
отбрасывается с предупреждением). Спикер считается по большинству слов в диапазоне, не со слов модели.

Возобновляемо: окно = единица работы, состояние в work/{cut}/segment_state.json, результат
дописывается атомарно после каждого окна; пауза — флаг PAUSE (P.pause_gate('segment')).
Ноль облачных токенов: следующий шаг — ОДИН облачный агент структуры (structure_call.py).

  env: ~/YTAI/environment/.venv_llm/bin/python (mlx_lm + Qwen3-8B-4bit в HF-кэше)
  python3 segment_local.py                    # все окна
  python3 segment_local.py --limit 2          # первые два окна (проба, тайминг на окно)
  python3 segment_local.py --window 240 --force   # окно 4 мин, пересчитать сделанные
  python3 segment_local.py --dry-run          # только нарезка окон и промпт первого, без модели

Выход REVIEW_DIR/segments.json: [{id, win, thesis, in:[sec, word], out:[sec, word], t_in, t_out, dur,
speaker, quality, text, snapped?, block?}] — читают structure_call.py и облачный агент структуры.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

os.environ.setdefault('HF_HOME', str(Path.home() / 'YTAI/models/huggingface'))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mt_common import P, REVIEW_DIR, load_words, load_words_doc, norm, tc, speakers_map, speaker_parts  # noqa: E402

MODEL = 'mlx-community/Qwen3-8B-4bit'
OUT = REVIEW_DIR / 'segments.json'
STATE = P.WORK / 'segment_state.json'
STRICT_WIN, SNAP_WIN = 3.0, 10.0

PROMPT = """/no_think Ты редактор монтажа документального видео. Фильм: {film}.
Ниже пронумерованные строки дословной транскрибации исходника ({t0}–{t1}), формат «N | Говорящий | текст».
Сгруппируй строки в смысловые куски-тезисы для монтажа: один кусок — одна законченная мысль,
ОБЫЧНО 3–8 СТРОК ПОДРЯД (10–60 секунд). Не дроби на отдельные строки. Куски идут подряд, без пропусков
и без перекрытий, покрывая все строки. Служебные реплики (команды на площадке, «ещё раз», «давай сначала»,
проверка звука) помечай quality "service"; сбитые дубли, оговорки, повторы — "retake"; чистую речь — "clean".

Верни СТРОГО JSON-массив (без пояснений, без markdown), не больше {max_items} объектов вида:
{{"thesis": "суть куска одной фразой, до 12 слов", "first": [N, "слово"], "last": [M, "слово"],
  "quality": "clean", "block": "тема куска, 2–3 слова"}}
first — номер строки, где кусок начинается, и ПЕРВОЕ слово куска (дословно, как в строке);
last  — номер строки, где кусок заканчивается, и ПОСЛЕДНЕЕ слово куска (дословно, как в строке).

СТРОКИ:
{lines}
"""


# ---------------- окна ----------------
def build_windows(doc, window):
    """Окна по сегментам транскрипта: закрываем на первой границе сегмента после t0+window."""
    segs = [s for s in doc['segments'] if s.get('words')]
    wins, cur, t0 = [], [], None
    for s in segs:
        if t0 is None:
            t0 = float(s['start'])
        cur.append(s)
        if float(s['end']) - t0 >= window:
            wins.append(cur)
            cur, t0 = [], None
    if cur:
        if wins and float(cur[-1]['end']) - float(cur[0]['start']) < window * 0.35:
            wins[-1].extend(cur)          # короткий хвост — к предыдущему окну
        else:
            wins.append(cur)
    return [{'i': i, 't0': float(w[0]['start']), 't1': float(w[-1]['end']), 'segs': w} for i, w in enumerate(wins)]


def window_lines(win, names):
    out = []
    for k, s in enumerate(win['segs'], 1):
        who = names.get(s.get('speaker'), s.get('speaker') or '?')
        out.append(f"{k} | {who} | {str(s['text']).strip()}")
    return '\n'.join(out)


def max_items_for(win):
    return max(5, min(18, -(-len(win['segs']) // 3)))


# ---------------- проверка якорей ----------------
def _ok(n):
    return lambda w: w['n'] == n or w['n'].startswith(n) or (n.startswith(w['n']) and len(w['n']) >= 4)


def find_word(ws, hint, word, edge):
    """(индекс, snapped) — слово в ±3 с от подсказки; иначе ближайшее в ±10 с (snapped=True); иначе None."""
    key = 's' if edge == 'in' else 'e'
    n = norm(word)
    if not n:
        return None, False
    ok = _ok(n)
    cand = [i for i, w in enumerate(ws) if abs(w[key] - hint) <= STRICT_WIN and ok(w)]
    if cand:
        return min(cand, key=lambda i: abs(ws[i][key] - hint)), False
    cand = [i for i, w in enumerate(ws) if abs(w[key] - hint) <= SNAP_WIN and ok(w)]
    if cand:
        return min(cand, key=lambda i: abs(ws[i][key] - hint)), True
    return None, False


def find_in_line(ws, line, word, edge):
    """Слово внутри строки транскрипта (первое вхождение для in, последнее для out) → индекс или None."""
    n = norm(word)
    if not n:
        return None
    ok = _ok(n)
    a, b = float(line['start']) - 0.3, float(line['end']) + 0.3
    cand = [i for i, w in enumerate(ws) if a <= w['s'] <= b and ok(w)]
    if not cand:
        return None
    return cand[0] if edge == 'in' else cand[-1]


def resolve_anchor(ws, win, ref, edge):
    """[номер строки, слово] → (индекс слова, snapped) — по строке, затем ±3 с, затем ±10 с от края строки."""
    try:
        ln, word = int(ref[0]), str(ref[1])
    except Exception:
        return None, False, 'нет [строка, слово]'
    if not 1 <= ln <= len(win['segs']):
        return None, False, f'строки {ln} нет в окне'
    line = win['segs'][ln - 1]
    i = find_in_line(ws, line, word, edge)
    if i is not None:
        return i, False, ''
    hint = float(line['start']) if edge == 'in' else float(line['end'])
    i, sn = find_word(ws, hint, word, edge)
    if i is None:
        return None, False, f'{edge} «{word}» нет в строке {ln} ({tc(hint)}) и рядом'
    return i, True, ''


def validate(items, ws, win, names_rev):
    good, dropped = [], []
    for it in items:
        if not isinstance(it, dict):
            dropped.append(({'thesis': str(it)[:40]}, 'не объект'))
            continue
        a_ref, b_ref = it.get('first') or it.get('in'), it.get('last') or it.get('out')
        i0, sn0, why0 = resolve_anchor(ws, win, a_ref or [], 'in')
        i1, sn1, why1 = resolve_anchor(ws, win, b_ref or [], 'out')
        if i0 is None or i1 is None:
            dropped.append((it, f'якорь не найден: {why0} {why1}'.strip()))
            continue
        if i1 < i0:
            dropped.append((it, 'конец раньше начала'))
            continue
        seg = ws[i0:i1 + 1]
        sp = {}
        for w in seg:
            sp[w['sp']] = sp.get(w['sp'], 0) + 1
        major = max(sp, key=sp.get)
        rec = {'win': win['i'], 'thesis': str(it.get('thesis', '')).strip(),
               'in': [round(ws[i0]['s'], 2), ws[i0]['w']], 'out': [round(ws[i1]['e'], 2), ws[i1]['w']],
               't_in': round(ws[i0]['s'], 3), 't_out': round(ws[i1]['e'], 3), 'dur': round(ws[i1]['e'] - ws[i0]['s'], 2),
               'speaker': major, 'quality': str(it.get('quality', 'clean')),
               'text': ' '.join(w['w'] for w in seg)}
        if it.get('block'):
            rec['block'] = str(it['block']).strip()
        if sn0 or sn1:
            rec['snapped'] = True
        good.append(rec)
    return good, dropped


def parse_json_array(raw):
    """JSON-массив из ответа; обрезанный по лимиту токенов ответ спасается пообъектно."""
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.S)
    raw = re.sub(r'^```(?:json)?|```$', '', raw.strip(), flags=re.M)
    m = re.search(r'\[.*\]', raw, flags=re.S)
    if m:
        s = m.group(0)
        for attempt in (s, re.sub(r',\s*([\]}])', r'\1', s)):
            try:
                v = json.loads(attempt)
                if isinstance(v, list):
                    return v, False
            except Exception:
                continue
    # спасение: все законченные объекты верхнего уровня
    items, depth, start = [], 0, None
    for i, ch in enumerate(raw):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    items.append(json.loads(raw[start:i + 1]))
                except Exception:
                    pass
                start = None
    return (items, True) if items else (None, False)


# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--window', type=float, default=210.0, help='длина окна, с (3–4 мин)')
    ap.add_argument('--limit', type=int, default=0, help='только первые N окон')
    ap.add_argument('--force', action='store_true', help='пересчитать уже сделанные окна')
    ap.add_argument('--dry-run', action='store_true', help='показать окна и промпт первого, модель не грузить')
    ap.add_argument('--max-tokens', type=int, default=2000, help='потолок ответа; реальный лимит = 95×max_items+250')
    a = ap.parse_args()

    doc = load_words_doc()
    ws = load_words()
    cam = speakers_map()
    names = {k: (speaker_parts(v)[1] or k) for k, v in cam.items()}
    wins = build_windows(doc, a.window)
    film = P.FILM or P.get('film_subject', '') or 'документальное видео'
    print(f'[segment] {Path(P.WORDS).name}: слов {len(ws)} · окон {len(wins)} по ~{a.window:.0f} с → {OUT}', flush=True)

    state = {'windows': {}}
    if STATE.exists() and not a.force:
        try:
            state = json.loads(STATE.read_text(encoding='utf-8'))
        except Exception:
            state = {'windows': {}}
    results = []
    if OUT.exists() and not a.force:
        try:
            results = json.loads(OUT.read_text(encoding='utf-8'))
        except Exception:
            results = []
    done = {int(k) for k, v in state['windows'].items() if v.get('status') == 'done'}

    todo = [w for w in wins if w['i'] not in done]
    if a.limit:
        todo = todo[:a.limit]
    if a.dry_run:
        for w in wins:
            print(f"  окно {w['i']:>2} {tc(w['t0'])}–{tc(w['t1'])} · строк {len(w['segs'])} · {'done' if w['i'] in done else 'todo'}")
        if todo:
            print(PROMPT.format(film=film, t0=tc(todo[0]['t0']), t1=tc(todo[0]['t1']), lines=window_lines(todo[0], names),
                                max_items=max_items_for(todo[0]))[:1500])
        return
    if not todo:
        print('все окна сделаны — --force, чтобы пересчитать')
        return

    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler
    t_load = time.time()
    model, tok = load(MODEL)
    sampler = make_sampler(temp=0.0)
    print(f'модель {MODEL} загружена за {time.time() - t_load:.1f} с', flush=True)

    for w in todo:
        P.pause_gate('segment')
        t0 = time.time()
        max_items = max_items_for(w)
        msg = PROMPT.format(film=film, t0=tc(w['t0']), t1=tc(w['t1']), lines=window_lines(w, names), max_items=max_items)
        try:
            prompt = tok.apply_chat_template([{'role': 'user', 'content': msg}], add_generation_prompt=True,
                                             tokenize=False, enable_thinking=False)
        except TypeError:
            prompt = tok.apply_chat_template([{'role': 'user', 'content': msg}], add_generation_prompt=True, tokenize=False)
        max_tokens = min(a.max_tokens, 95 * max_items + 250)
        raw = generate(model, tok, prompt=prompt, max_tokens=max_tokens, sampler=sampler, verbose=False)
        items, salvaged = parse_json_array(raw)
        secs = time.time() - t0
        if salvaged:
            print(f"  окно {w['i']:>2}: ответ обрезан по лимиту {max_tokens} токенов — спасено объектов {len(items)}", flush=True)
        if items is None:
            state['windows'][str(w['i'])] = {'t0': w['t0'], 't1': w['t1'], 'status': 'failed', 'secs': round(secs, 1),
                                             'raw': raw[:300]}
            P.write_json_atomic(STATE, state)
            print(f"  окно {w['i']:>2} {tc(w['t0'])}–{tc(w['t1'])} ⚠️ модель не вернула JSON ({secs:.0f} с) — окно повторится при следующем запуске", flush=True)
            continue
        good, dropped = validate(items, ws, w, names)
        results = [r for r in results if r.get('win') != w['i']] + good
        results.sort(key=lambda r: r['t_in'])
        for i, r in enumerate(results, 1):
            r['id'] = f's{i:03d}'
        state['windows'][str(w['i'])] = {'t0': w['t0'], 't1': w['t1'], 'status': 'done', 'secs': round(secs, 1),
                                         'n_lines': len(w['segs']), 'n_model': len(items), 'n_ok': len(good),
                                         'n_dropped': len(dropped), 'n_snapped': sum(1 for g in good if g.get('snapped'))}
        P.write_json_atomic(OUT, results)
        P.write_json_atomic(STATE, state)
        print(f"  окно {w['i']:>2} {tc(w['t0'])}–{tc(w['t1'])} · {secs:5.1f} с · тезисов {len(good)}/{len(items)}"
              f" · подтянуто {state['windows'][str(w['i'])]['n_snapped']} · отброшено {len(dropped)}", flush=True)
        for it, why in dropped:
            print(f"     ⚠️ отброшен «{str(it.get('thesis', ''))[:50]}»: {why}", flush=True)
        for g in good[:3]:
            print(f"     {tc(g['t_in'])}–{tc(g['t_out'])} [{g['quality']}] {g['thesis'][:70]}", flush=True)

    n_done = sum(1 for v in state['windows'].values() if v.get('status') == 'done')
    print(f'segments.json: {len(results)} тезисов · окон {n_done}/{len(wins)} → {OUT}', flush=True)


if __name__ == '__main__':
    main()
