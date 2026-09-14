#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""s3b_probe_vlm — локальные зонды Qwen2.5-VL-7B (mlx) по экранам ката: чужие следы, обрезка, зум спорных слов.

Для каждого экрана screens_v6.json — best-кадр и last-кадр (если он другой), два вопроса да/нет:
  1) чужой элемент в кадре: вотермарк, чужой логотип, иероглифы/другой язык, курсор, выжженные субтитры;
  2) текст обрезан краем / спрятан за человеком / полукадр анимации.
Плюс зум-перечитывание спорных слов: токены с `zoom_wanted` из candidates.json (route_candidates.py) —
кроп строки OCR (bbox best-кадра) с полями, ×2 → VLM «перепиши дословно» + bin/vision_ocr_ru по тому же кропу.
Выход: W6/probes.jsonl — строка на экран:
  {screen_id, foreign: bool, foreign_note, cut_off: bool, cut_note,
   zoom: [{line_idx, token, vlm, ocr, vlm_line, ocr_line}], frames: [...], sec}
Возобновляемый: экраны, уже записанные в probes.jsonl, пропускаются; P.pause_gate('probe') между экранами;
прогресс каждые 10 экранов; в конце — замер времени и прогноз на весь кат (для запуска на Memex).

usage (env: ~/YTAI/environment/.venv_vlm/bin/python):
  s3b_probe_vlm.py                              # все экраны
  s3b_probe_vlm.py --ids s001-s012,s031,s058    # подмножество (валидация, замер)
  s3b_probe_vlm.py --first 12                   # первые N экранов
  s3b_probe_vlm.py --words-from <candidates.json>   # спорные слова (по умолчанию W6/candidates.json;
                                                #  без файла — те же токены считаются самим скриптом)
  s3b_probe_vlm.py --max-minutes 25             # остановиться по времени, чекпойнт остаётся
  s3b_probe_vlm.py --redo                       # пересчитать выбранные экраны, даже если уже есть
  s3b_probe_vlm.py --full-res                   # вопросы да/нет по кадру 1920×1080 (по умолчанию ≤1280 px)
  s3b_probe_vlm.py --verbose                    # печатать каждый экран
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault('HF_HOME', str(Path.home() / 'YTAI/models/huggingface'))
from _bootstrap import P, W6  # noqa: E402

MODEL = 'mlx-community/Qwen2.5-VL-7B-Instruct-4bit'
HIRES = W6 / 'hires'
OUT = W6 / 'probes.jsonl'
CROPS = W6 / 'probe_crops'
OCR_BIN = Path.home() / 'YTAI/scripts/999_extra/bin/vision_ocr_ru'
FRAME_MAX_W = 1280        # кадр для вопросов да/нет (память local-first: картинки для Qwen ≤1280 px)
ZOOM_SCALE = 2            # кроп строки ×2
ZOOM_PAD_Y = 0.6          # поля кропа: доля высоты строки
ZOOM_PAD_X = 0.015        # поля кропа: доля ширины кадра
ZOOM_MIN_W = 96           # кроп уже этого (px, до масштаба) расширяем — иначе VLM не читает
MAX_TOK_YESNO = 48
MAX_TOK_ZOOM = 40

Q_FOREIGN = ("This is a frame from a Russian-language YouTube video about gemstones. Does the frame contain any "
             "FOREIGN element that does not belong to the video's own graphics: a watermark or stock-site logo, "
             "a third-party brand or TV channel logo, Chinese/Japanese/Korean or other non-Russian characters, "
             "a mouse cursor, burned-in subtitles or captions from another video, a source credit line? "
             "The channel's own small 'uvi' logo, the presenter and the video's own Russian titles do NOT count. "
             "Answer strictly in the form: YES: <what and where> — or NO.")
Q_CUTOFF = ("Is any text in this frame cut off by the frame edge, partially hidden behind a person or object, "
            "or caught mid-animation (letters half-drawn, a word still typing in, a line missing its end)? "
            "Answer strictly: YES: <which text> — or NO.")
Q_ZOOM = ("This is a zoomed crop of one text line from a video frame. Transcribe the text EXACTLY, letter by letter, "
          "as it is written (Russian Cyrillic or Latin). Keep the letter case. Do NOT correct spelling, do NOT add "
          "or translate words. Output only the text.")


def parse_ids(spec, all_ids):
    out = []
    for part in (spec or '').split(','):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r'(s\d{3})-(s\d{3})', part)
        if m:
            lo, hi = int(m.group(1)[1:]), int(m.group(2)[1:])
            out += [f's{i:03d}' for i in range(lo, hi + 1)]
        else:
            out.append(part)
    return [i for i in out if i in all_ids]


def yes_no(answer):
    a = (answer or '').strip()
    if re.match(r'^\s*yes\b', a, re.I):
        note = re.sub(r'^\s*yes\s*[:,;.—-]*\s*', '', a, flags=re.I).strip()
        return True, note[:200]
    return False, ''


def tokens(text):
    return re.findall(r'[^\W_]+', text or '')


def best_token(reading, token):
    """из строки чтения — слово, ближайшее к спорному токену (или '')"""
    import difflib
    best, br = '', 0.0
    for t in tokens(reading):
        r = difflib.SequenceMatcher(None, t.lower(), token.lower(), autojunk=False).ratio()
        if r > br:
            best, br = t, r
    return best if br >= 0.5 else ''


def local_ocr(path):
    """bin/vision_ocr_ru по одному файлу → текст строк через ' | '"""
    if not OCR_BIN.exists():
        return ''
    try:
        p = subprocess.run([str(OCR_BIN)], input=str(path) + '\n', capture_output=True, text=True, timeout=60)
        d = json.loads(p.stdout.strip().splitlines()[-1])
        return ' | '.join(l['t'] for l in d.get('lines', []) if l.get('t'))
    except Exception as ex:                        # noqa: BLE001
        return f'<ocr error: {ex}>'[:80]


def zoom_words_from_candidates(path):
    """{screen_id: [(line_idx, token), …]} из candidates.json (zoom_wanted и line_idx ≥ 0)"""
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    for c in json.load(open(p, encoding='utf-8')):
        if c.get('zoom_wanted') and c.get('line_idx', -1) >= 0:
            out.setdefault(c['screen_id'], [])
            key = (c['line_idx'], c['on_screen_text'])
            if key not in out[c['screen_id']]:
                out[c['screen_id']].append(key)
    return out


def zoom_words_fallback(screens):
    """без candidates.json: слова ≥4 букв вне словаря (каталог + озвучка, pymorphy при наличии)"""
    try:
        import pymorphy3
        morph = pymorphy3.MorphAnalyzer()
    except Exception:                              # noqa: BLE001
        morph = None
    vocab = set()
    for seg in json.load(open(P.WORDS, encoding='utf-8'))['segments']:
        for w in seg.get('words') or []:
            vocab.add(re.sub(r'[^\w]', '', w['w'].lower()))
    out = {}
    for e in screens:
        for li, l in enumerate(e['lines_best']):
            for t in tokens(l['t']):
                if len(t) < 4 or not re.fullmatch(r'[А-ЯЁа-яё]+', t):
                    continue
                tl = t.lower()
                if tl in vocab or (morph is not None and morph.word_is_known(tl)):
                    continue
                out.setdefault(e['id'], []).append((li, t))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--ids', help='s001-s012,s031,s058')
    ap.add_argument('--first', type=int)
    ap.add_argument('--words-from', default=str(W6 / 'candidates.json'))
    ap.add_argument('--max-minutes', type=float, default=0)
    ap.add_argument('--redo', action='store_true')
    ap.add_argument('--full-res', action='store_true')
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args()

    P.banner('probe')
    screens = json.load(open(W6 / 'screens_v6.json', encoding='utf-8'))
    by_id = {e['id']: e for e in screens}
    ids = [e['id'] for e in screens]
    if a.ids:
        ids = parse_ids(a.ids, set(ids))
    if a.first:
        ids = ids[:a.first]
    done = {}
    if OUT.exists():
        for ln in open(OUT, encoding='utf-8'):
            try:
                r = json.loads(ln)
                done[r['screen_id']] = r
            except Exception:                      # noqa: BLE001
                pass
    if a.redo:
        keep = [r for sid, r in done.items() if sid not in ids]
        with open(OUT, 'w', encoding='utf-8') as fh:
            for r in keep:
                fh.write(json.dumps(r, ensure_ascii=False) + '\n')
        done = {r['screen_id']: r for r in keep}
    todo = [sid for sid in ids if sid not in done]
    zoom_words = zoom_words_from_candidates(a.words_from)
    src = 'candidates.json'
    if not zoom_words:
        zoom_words = zoom_words_fallback(screens)
        src = 'fallback (словарь+озвучка)'
    n_zoom = sum(len(v) for sid, v in zoom_words.items() if sid in todo)
    print(f'probe: экранов {len(ids)}, сделано {len(done)}, в очереди {len(todo)}; зум-слов {n_zoom} ({src}); '
          f'кадр {"1920" if a.full_res else FRAME_MAX_W} px', flush=True)
    if not todo:
        return

    from PIL import Image
    from mlx_vlm import load, generate
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.utils import load_config

    t_load = time.time()
    model, processor = load(MODEL)
    config = load_config(MODEL)
    print(f'  модель загружена за {time.time() - t_load:.0f} с', flush=True)
    CROPS.mkdir(exist_ok=True)

    def ask(img_path, q, max_tokens):
        f = apply_chat_template(processor, config, q, num_images=1)
        r = generate(model, processor, f, [str(img_path)], max_tokens=max_tokens, temperature=0.0, verbose=False)
        return (r.text if hasattr(r, 'text') else str(r)).strip()

    def frame_for_q(frame_name):
        """кадр для вопросов да/нет: ≤FRAME_MAX_W (или как есть при --full-res)"""
        src_p = HIRES / frame_name
        if a.full_res:
            return src_p
        dst = CROPS / f'q_{frame_name}'
        if not dst.exists():
            im = Image.open(src_p)
            if im.width > FRAME_MAX_W:
                im = im.resize((FRAME_MAX_W, round(im.height * FRAME_MAX_W / im.width)), Image.LANCZOS)
            im.save(dst, quality=92)
        return dst

    def crop_line(frame_name, line, tag):
        im = Image.open(HIRES / frame_name)
        W, H = im.size
        x0 = (line['x'] - ZOOM_PAD_X) * W
        x1 = (line['x'] + line['bw'] + ZOOM_PAD_X) * W
        y0 = (line['y'] - ZOOM_PAD_Y * line['bh']) * H
        y1 = (line['y'] + line['bh'] * (1 + ZOOM_PAD_Y)) * H
        if x1 - x0 < ZOOM_MIN_W:
            cx = (x0 + x1) / 2
            x0, x1 = cx - ZOOM_MIN_W / 2, cx + ZOOM_MIN_W / 2
        box = (max(0, int(x0)), max(0, int(y0)), min(W, int(x1)), min(H, int(y1)))
        cr = im.crop(box)
        cr = cr.resize((cr.width * ZOOM_SCALE, cr.height * ZOOM_SCALE), Image.LANCZOS)
        dst = CROPS / f'{tag}.png'
        cr.save(dst)
        return dst

    t_start = time.time()
    n_done = 0
    with open(OUT, 'a', encoding='utf-8') as out:
        for i, sid in enumerate(todo):
            if a.max_minutes and (time.time() - t_start) / 60 > a.max_minutes:
                print(f'  ⏱ лимит {a.max_minutes} мин — стоп после {n_done} экранов (чекпойнт в {OUT.name})', flush=True)
                break
            P.pause_gate('probe')
            e = by_id[sid]
            t0 = time.time()
            frames = [e['best_frame']] + ([e['last_frame']] if e['last_frame'] != e['best_frame'] else [])
            rec = {'screen_id': sid, 'tc': e['tc'], 'foreign': False, 'foreign_note': '', 'cut_off': False, 'cut_note': '',
                   'zoom': [], 'frames': []}
            for fr in frames:
                if not (HIRES / fr).exists():
                    rec['frames'].append({'frame': fr, 'skipped': 'нет кадра'})
                    continue
                q_img = frame_for_q(fr)
                fa = ask(q_img, Q_FOREIGN, MAX_TOK_YESNO)
                ca = ask(q_img, Q_CUTOFF, MAX_TOK_YESNO)
                f_yes, f_note = yes_no(fa)
                c_yes, c_note = yes_no(ca)
                rec['frames'].append({'frame': fr, 'foreign': fa[:160], 'cut_off': ca[:160]})
                if f_yes and not rec['foreign']:
                    rec['foreign'], rec['foreign_note'] = True, f'{fr}: {f_note}'
                if c_yes and not rec['cut_off']:
                    rec['cut_off'], rec['cut_note'] = True, f'{fr}: {c_note}'
            for li, tok in zoom_words.get(sid, []):
                if li < 0 or li >= len(e['lines_best']) or not (HIRES / e['best_frame']).exists():
                    continue
                line = e['lines_best'][li]
                crop = crop_line(e['best_frame'], line, f'{sid}_l{li}')
                vlm_line = ask(crop, Q_ZOOM, MAX_TOK_ZOOM).split('\n')[0]
                ocr_line = local_ocr(crop)
                rec['zoom'].append({'line_idx': li, 'token': tok, 'vlm': best_token(vlm_line, tok),
                                    'ocr': best_token(ocr_line, tok), 'vlm_line': vlm_line[:120], 'ocr_line': ocr_line[:120],
                                    'crop': str(crop.relative_to(W6))})
            rec['sec'] = round(time.time() - t0, 1)
            out.write(json.dumps(rec, ensure_ascii=False) + '\n')
            out.flush()
            n_done += 1
            if a.verbose or i % 10 == 0:
                z = ' · '.join(f'{x["token"]}→vlm:{x["vlm"] or "?"}/ocr:{x["ocr"] or "?"}' for x in rec['zoom'])
                print(f'  {i + 1}/{len(todo)} {sid} @{e["tc"]} {rec["sec"]}s foreign={rec["foreign"]} cut={rec["cut_off"]}'
                      + (f' | {rec["foreign_note"][:70]}' if rec['foreign'] else '') + (f' | zoom: {z}' if z else ''), flush=True)
    total = time.time() - t_start
    if n_done:
        per = total / n_done
        print(f'probe done: {n_done} экранов за {total / 60:.1f} мин · {per:.1f} с/экран · прогноз на {len(screens)} экранов: '
              f'{per * len(screens) / 60:.0f} мин (Memex ≈ ×2.6 → {per * len(screens) / 60 * 2.6:.0f} мин)', flush=True)


if __name__ == '__main__':
    main()
