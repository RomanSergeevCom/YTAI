#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Колонка «Говорит» вкладки ТЗ (Роман 16.09.2026: «транскрипт обязателен — без него не виден контекст»).

Дословные слова ката из words.json в окне ТЗ, без модели и без пересказа (KB 5.8: транскрипт руками не перебивать):
  окно    = tc_range ±3 с, расширенное до границ предложений; диапазон длиннее 40 с (ТЗ на главу) — якорь ±10 с;
  предел  = 70 слов вокруг якоря;
  абзацы  = пауза ≥ 1,2 с или смена спикера;
  жирным  = опорная фраза: слова в [якорь − 0,3 с, якорь + 1,5 с] (якорь = v1_tc — секунда, где делать правку;
            у вставок kb_visuals это первое слово предмета).
said(tc_range, v1_tc) → {'text': str, 'bold': [(start, end)]} — смещения в text; нет слов/якоря — пустой text.
stream() — все слова ката одной строкой через пробел: каждый абзац text — её подстрока (проверка verify).
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'stages'))
from _bootstrap import P  # noqa: E402

# Окно шире прежнего (3.0 / 70 / 12): вкладка ТЗ больше не печатает 📍 ГДЕ с якорем, и весь
# контекст теперь несёт эта колонка — Роман просил «чуть больше контекста» (22.09.2026).
PAD, LONG, NEAR, MAX_WORDS, PAUSE, BOLD_BEFORE, BOLD_AFTER = 4.5, 40.0, 12.0, 90, 1.2, 0.3, 1.5
EXT_WORDS = 18                         # насколько далеко тянуть окно до границы предложения
END_RE = re.compile(r'[.?!…]["»)]?$')
TC_RE = re.compile(r'~?(\d{1,2}):(\d{2})(?:\.(\d+))?')

_W = None


def words():
    """[(слово, начало, конец, спикер)] по порядку"""
    global _W
    if _W is None:
        try:
            segs = json.load(open(P.WORDS, encoding='utf-8'))['segments']
        except Exception:                                      # noqa: BLE001 — нет транскрипта: колонка пустая
            segs = []
        _W = [(w['w'], float(w['s']), float(w['e']), w.get('speaker') or sg.get('speaker') or '')
              for sg in segs for w in sg.get('words') or []]
    return _W


def stream():
    return ' '.join(w[0] for w in words())


def secs(tc):
    """все таймкоды строки → секунды ('4:49–5:21' → [289, 321])"""
    return [int(m.group(1)) * 60 + int(m.group(2)) + (float('0.' + m.group(3)) if m.group(3) else 0)
            for m in TC_RE.finditer(str(tc or ''))]


def _hl_spans(text, frags):
    """спаны фрагментов ошибки в тексте речи, без учёта регистра и кавычек.

    Вкладка ТЗ больше не печатает блок 📍 ГДЕ — он слово в слово повторял эту же колонку
    (решение Романа 22.09.2026). Вместо него слова, где ошибка, подсвечиваются прямо в речи.
    Ищем по нормализованным буквам, чтобы «кристале» нашлось и в «кристале,».
    """
    out = []
    low = text.lower().replace('ё', 'е')
    for f in frags or []:
        f = re.sub(r'[«»„“”"\']', '', str(f or '')).strip().lower().replace('ё', 'е')
        if len(f) < 4:
            continue
        i = low.find(f)
        while i >= 0:
            out.append((i, i + len(f)))
            i = low.find(f, i + len(f))
    return sorted(set(out))


def said(tc_range, v1_tc, hl=None):
    ws = words()
    anc = (secs(v1_tc) or secs(tc_range) or [None])[0]
    if not ws or anc is None:
        return {'text': '', 'bold': [], 'hl': []}
    rng = secs(tc_range) or [anc]
    r0, r1 = min(rng), max(rng)
    if r1 - r0 > LONG:
        r0, r1 = anc - NEAR, anc + NEAR
    w0, w1 = min(r0, anc) - PAD, max(r1, anc) + PAD
    idx = [i for i, w in enumerate(ws) if w[2] >= w0 and w[1] <= w1]
    if not idx:
        return {'text': '', 'bold': [], 'hl': []}
    i0, i1 = idx[0], idx[-1]
    k = 0
    while i0 > 0 and not END_RE.search(ws[i0 - 1][0]) and k < EXT_WORDS:       # влево — до конца прошлого предложения
        i0, k = i0 - 1, k + 1
    k = 0
    while i1 < len(ws) - 1 and not END_RE.search(ws[i1][0]) and k < EXT_WORDS:  # вправо — до точки
        i1, k = i1 + 1, k + 1
    if i1 - i0 + 1 > MAX_WORDS:                                                  # длинно — вокруг якоря
        ai = min(range(i0, i1 + 1), key=lambda i: abs(ws[i][1] - anc))
        i0 = max(i0, ai - MAX_WORDS // 3)
        i1 = min(i1, i0 + MAX_WORDS - 1)
    bold_i = {i for i in range(i0, i1 + 1) if anc - BOLD_BEFORE <= ws[i][1] <= anc + BOLD_AFTER}
    if not bold_i:
        bold_i = {min(range(i0, i1 + 1), key=lambda i: abs(ws[i][1] - anc))}
    text, bold, run = '', [], None
    for i in range(i0, i1 + 1):
        w, s, e, spk = ws[i]
        if i > i0:
            new_par = s - ws[i - 1][2] >= PAUSE or spk != ws[i - 1][3]
            if run is not None and (i not in bold_i or new_par):
                bold.append((run, len(text)))
                run = None
            text += '\n' if new_par else ' '
        if i in bold_i and run is None:
            run = len(text)
        text += w
    if run is not None:
        bold.append((run, len(text)))
    return {'text': text, 'bold': bold, 'hl': _hl_spans(text, hl)}


if __name__ == '__main__':
    r = said(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else '')
    t = r['text']
    for s, e in reversed(r['bold']):
        t = t[:s] + '**' + t[s:e] + '**' + t[e:]
    print(t)
