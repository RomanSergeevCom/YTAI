#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""acts_compact.py — сжатие транскрипта ката по актам ЛОКАЛЬНОЙ Qwen3-8B (.venv_llm, mlx_lm) + структурные проверки канала.
Наследник p_packs / x_structure_local (YTCH12 v4): облаку уходит не транскрипт, а компактные акты; правила листа
(вход фонда, тизер, последний звук) проверяет код, а не агент.

Акты: карточка `acts` [[sec, "название"], …] (или [{t0, title}]), иначе главы P.CHAPTERS + ch_name (акт = глава).
Каждый акт режется на окна ≤ --max-tokens (по токенизатору модели; абзацы wordrole не рвутся), окно → модель → JSON
{summary, theses[5], claims[{text, numbers}]}; несколько окон одного акта сводятся вторым вызовом.
Выход W6/acts_compact.json:
  {schema, code, cut_version, model, acts: [{act, title, tc_range, t0, t1, summary (≤120 слов), theses[≤5],
   claims[{text, numbers[]}], speakers_share{имя: доля}, windows, llm (true — модель, false — экстракт), hash}]}
Резюмируемо: акт с тем же hash не пересчитывается (--force — пересчитать); файл пишется после каждого акта;
<think> вычищается, enable_thinking=False.

Структурные проверки (без модели) по P.profile('structure_rules') → W6/structure_checks.json:
  fund_entry_min      — первое упоминание fund_rx не раньше N-й минуты;
  teaser_rule         — в первых teaser_sec секундах есть ≥1 n-грамма (≥teaser_min_ngram слов), которая звучит
                        в актах ≥ teaser_from_act (тизер не только из бед: эхо более поздней, «надеждной» части);
  last_sound_rule     — в последних last_sound_sec секундах речи нет money_rx (последний звук ≠ призыв о деньгах);
  fund_piece_max_sec  — самый длинный непрерывный кусок спикера фонда (карточка: ключ из fund_speaker_key), иначе n/a.

usage: ~/YTAI/environment/.venv_llm/bin/python acts_compact.py [--act N] [--force] [--max-tokens 4000] [--no-llm]
          [--checks-only] [--channel YTCH] [--out path] [--checks-out path] [--screens path]
  --act N        только акт N (1-based); --no-llm — экстрактивная сводка без модели (быстрая проверка формы);
  --checks-only  только structure_checks; --channel — взять structure_rules другого канала (тест на чужом кате).

Без модели по профилю: verdict.acts_llm = false (редакторский вердикт, YTCR) → Qwen не грузится, акты экстрактивные
(extractive_acts, обычный python3): summary = начало + конец акта (≤120 слов), theses = 5 предложений «[M:SS] …»,
равномерно по акту, claims = предложения с цифрами / суммами {text, numbers, tc}, screens = тексты экранов акта из
work/{cut}/screens_v6.json [{tc, text}] (≤25), model = 'extractive'. Профиль без ключа (YTCH) — Qwen, как было.
Названия актов по умолчанию и n/a-проверка — через i18n (e.act_default / e.chapter_default / e.no_structure_rules).
env: YTAI_CARD=<review_card.json>; YTAI_WORK_DIR — куда писать (тесты); HF_HOME по умолчанию ~/YTAI/models/huggingface.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

os.environ.setdefault('HF_HOME', str(Path.home() / 'YTAI/models/huggingface'))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'stages'))
from _bootstrap import P, W6, ROOT, T  # noqa: E402

MODEL = 'mlx-community/Qwen3-8B-4bit'
YTAI = ROOT.parent.parent.parent
PROMPT = """Ты — редактор документального фильма (русский язык). Ниже — дословный транскрипт куска фильма
«{film}», акт «{title}», таймкоды {tc0}–{tc1}. Спикеры подписаны.

Верни ТОЛЬКО JSON без пояснений:
{{"summary": "что происходит и что говорят герои — до 120 слов, нейтрально, без оценок",
 "theses": ["5 главных тезисов куска, по одному предложению каждый"],
 "claims": [{{"text": "фактическое утверждение с числом, датой, именем или суммой — дословно по транскрипту", "numbers": ["27 тысяч", "2019"]}}]}}
Правила: ничего не выдумывай; цитаты и числа — только из транскрипта; тезисов ровно 5 (меньше — если кусок короткий);
claims — все утверждения с цифрами/датами/именами (до 12).

ТРАНСКРИПТ:
{text}
JSON:"""
MERGE = """Ты — редактор документального фильма (русский язык). Ниже — сводки нескольких подряд идущих окон ОДНОГО акта
«{title}» ({tc0}–{tc1}) фильма «{film}». Сведи их в одну: верни ТОЛЬКО JSON того же вида:
{{"summary": "до 120 слов", "theses": ["5 тезисов всего акта"], "claims": [{{"text": "…", "numbers": ["…"]}}]}}
Ничего не добавляй от себя; claims — объединить, дубли убрать (до 15).

СВОДКИ ОКОН:
{text}
JSON:"""


def norm(w):
    return re.sub(r'[^а-яa-z0-9]', '', str(w).lower().replace('ё', 'е'))


def tc(s):
    s = int(s)
    return f'{s // 60}:{s % 60:02d}'


def load_words():
    d = json.load(open(P.WORDS, encoding='utf-8'))
    ws = []
    for seg in d.get('segments') or []:
        for w in seg.get('words') or []:
            if norm(w.get('w', '')):
                ws.append({'w': w['w'], 'n': norm(w['w']), 's': float(w['s']), 'e': float(w['e']),
                           'spk': w.get('speaker') or seg.get('speaker') or ''})
    ws.sort(key=lambda x: x['s'])
    paras = [{'s': float(p['start']), 'e': float(p['end']), 'spk': p.get('speaker', ''), 'text': p.get('text', '')}
             for p in (d.get('paragraphs') or [])]
    return ws, paras


def load_acts(ws):
    total = P.duration_sec() if (P.get('duration_sec') or P.SRC) else ws[-1]['e']
    raw = P.get('acts')
    acts = []
    if raw:
        for i, a in enumerate(raw):
            t0, title = (a[0], a[1]) if isinstance(a, (list, tuple)) else (a.get('t0', a.get('sec', 0)), a.get('title', T('e.act_default', n=i + 1)))
            acts.append({'act': i + 1, 't0': float(t0), 'title': str(title)})
    else:
        names = dict(P.get('ch_name') or {})
        for i, (t0, n) in enumerate(P.CHAPTERS):
            acts.append({'act': i + 1, 't0': float(t0), 'title': names.get(n, T('e.chapter_default', n=n))})
    acts.sort(key=lambda a: a['t0'])
    for i, a in enumerate(acts):
        a['t1'] = acts[i + 1]['t0'] if i + 1 < len(acts) else float(total)
        a['tc_range'] = f'{tc(a["t0"])}–{tc(a["t1"])}'
    return acts


def act_paragraphs(ws, paras, a, names):
    """абзацы акта «[M:SS] Спикер: текст» — из paragraphs wordrole, иначе из слов по смене спикера / 30 с"""
    out = []
    if paras:
        for p in paras:
            if a['t0'] - 0.01 <= p['s'] < a['t1']:
                out.append((p['s'], f'[{tc(p["s"])}] {names.get(p["spk"], p["spk"]) or "—"}: {p["text"].strip()}'))
    if not out:
        cur, spk, t0 = [], None, None
        for w in ws:
            if not (a['t0'] - 0.01 <= w['s'] < a['t1']):
                continue
            if cur and (w['spk'] != spk or w['s'] - t0 > 30):
                out.append((t0, f'[{tc(t0)}] {names.get(spk, spk) or "—"}: {" ".join(cur)}'))
                cur = []
            if not cur:
                spk, t0 = w['spk'], w['s']
            cur.append(w['w'])
        if cur:
            out.append((t0, f'[{tc(t0)}] {names.get(spk, spk) or "—"}: {" ".join(cur)}'))
    return [t for _, t in out]


def windows(paras, count, max_tokens):
    """упаковка абзацев в окна ≤ max_tokens; слишком длинный абзац режется по предложениям"""
    out, cur, n = [], [], 0
    for p in paras:
        k = count(p)
        if k > max_tokens:
            parts = re.split(r'(?<=[.!?…])\s+', p)
            for part in parts:
                kk = count(part)
                if n + kk > max_tokens and cur:
                    out.append('\n'.join(cur)); cur, n = [], 0
                cur.append(part); n += kk
            continue
        if n + k > max_tokens and cur:
            out.append('\n'.join(cur)); cur, n = [], 0
        cur.append(p); n += k
    if cur:
        out.append('\n'.join(cur))
    return out


def speakers_share(ws, a, names):
    sec = {}
    for w in ws:
        if a['t0'] - 0.01 <= w['s'] < a['t1']:
            sec[w['spk']] = sec.get(w['spk'], 0.0) + max(0.0, w['e'] - w['s'])
    tot = sum(sec.values()) or 1.0
    return {names.get(k, k) or '—': round(v / tot, 2) for k, v in sorted(sec.items(), key=lambda kv: -kv[1])}


def parse_json(raw):
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.S)
    raw = raw.replace('<think>', '').replace('</think>', '')
    i, j = raw.find('{'), raw.rfind('}')
    if i < 0 or j <= i:
        return None
    s = raw[i:j + 1]
    for cand in (s, re.sub(r',\s*([}\]])', r'\1', s)):
        try:
            d = json.loads(cand)
            if isinstance(d, dict):
                return d
        except Exception:
            continue
    return None


def clean_result(d, text=''):
    """→ {summary, theses, claims} или None, если форма не та. Числа в claims оставляем только те,
    что реально есть в тексте окна (8B-модель любит дописать «2019»); claim без числа и без имени — не claim."""
    if not isinstance(d, dict) or not str(d.get('summary', '')).strip():
        return None
    summ = re.sub(r'\s+', ' ', str(d['summary'])).strip()
    sw = summ.split()
    if len(sw) > 120:
        summ = ' '.join(sw[:120]) + '…'
    theses = [re.sub(r'\s+', ' ', str(t)).strip() for t in (d.get('theses') or []) if str(t).strip()][:5]
    tnorm = norm_text(text)
    claims = []
    for c in (d.get('claims') or [])[:15]:
        ctext = (c.get('text') if isinstance(c, dict) else c) if c else ''
        ctext = re.sub(r'\s+', ' ', str(ctext or '')).strip()
        if not ctext:
            continue
        raw_nums = (c.get('numbers') if isinstance(c, dict) else None) or re.findall(r'\d[\d\s]*(?:тыс\w*|руб\w*|₽|%|лет|года?)?', ctext)
        nums = []
        for x in raw_nums:
            x = str(x).strip()
            digits = re.findall(r'\d+', x)
            if x and (not text or all(re.search(rf'\b{dg}\b', tnorm) for dg in digits)):
                nums.append(x)
        has_name = bool(re.search(r'(?<![.!?]\s)(?<!^)\b[А-ЯЁA-Z][а-яёa-z]{2,}', ctext))
        if nums or has_name or not text:
            claims.append({'text': ctext, 'numbers': nums[:6]})
    return {'summary': summ, 'theses': theses, 'claims': claims}


def norm_text(text):
    return ' '.join(norm(w) for w in re.findall(r'\w+', str(text or '')) if norm(w))


def extractive(text):
    """запасной вариант без модели: первые 120 слов, первые 5 предложений, предложения с цифрами"""
    body = re.sub(r'\[\d+:\d\d\]\s*[^:]{0,40}:\s*', '', text)
    sents = [s.strip() for s in re.split(r'(?<=[.!?…])\s+', body) if s.strip()]
    return {'summary': ' '.join(body.split()[:120]), 'theses': sents[:5],
            'claims': [{'text': s, 'numbers': re.findall(r'\d+', s)[:6]} for s in sents if re.search(r'\d', s)][:12]}


SENT_END = re.compile(r'[.!?…]["»”)]*$')
NUM_RX = re.compile(r'\d[\d,.]*\s*(?:%|k\b|m\b|million|billion|thousand|hundred|aed|dirhams?|usd|\$|€|тыс\w*|млн|руб\w*|₽)?', re.I)
MONEY_WORDS = re.compile(r'\b(?:million|billion|thousand|hundred|dirhams?|aed|dollars?|percent|half)\b', re.I)


def act_sentences(ws, a, gap=1.5, max_words=40):
    """предложения акта по словам: конец — знак препинания, пауза > gap или max_words → [(s, текст)]"""
    out, cur, t0, prev_e = [], [], None, None
    for w in ws:
        if not (a['t0'] - 0.01 <= w['s'] < a['t1']):
            continue
        if cur and (w['s'] - prev_e > gap or len(cur) >= max_words):
            out.append((t0, ' '.join(cur))); cur = []
        if not cur:
            t0 = w['s']
        cur.append(str(w['w']).strip())
        prev_e = w['e']
        if SENT_END.search(cur[-1]):
            out.append((t0, ' '.join(cur))); cur = []
    if cur:
        out.append((t0, ' '.join(cur)))
    return [(s, re.sub(r'\s+', ' ', t).strip()) for s, t in out if t.strip()]


def load_screens(path):
    """screens_v6.json (s1_screens) → [(t0, текст)]; нет файла / битый → []"""
    try:
        d = json.load(open(path, encoding='utf-8'))
    except Exception:
        return []
    rows = d if isinstance(d, list) else (d.get('screens') or [])
    out = []
    for x in rows:
        if not isinstance(x, dict):
            continue
        txt = re.sub(r'\s+', ' ', str(x.get('text_best') or x.get('text') or '')).strip()
        if txt and x.get('t0') is not None:
            out.append((float(x['t0']), txt))
    return sorted(out)


def extractive_acts(ws, a, screens):
    """акт без модели (profile verdict.acts_llm = false): начало+конец, 5 предложений по всему акту, факты с числами, экраны"""
    sents = act_sentences(ws, a)
    words = [w['w'] for w in ws if a['t0'] - 0.01 <= w['s'] < a['t1']]
    if len(words) <= 120:
        summ = ' '.join(words)
    else:
        summ = ' '.join(words[:75]) + ' … ' + ' '.join(words[-40:])
    long = [x for x in sents if len(x[1].split()) >= 6] or sents
    k = min(5, len(long))
    picks = sorted({round(i * (len(long) - 1) / max(1, k - 1)) for i in range(k)}) if k else []
    theses = [f'[{tc(long[i][0])}] {long[i][1]}' for i in picks]
    claims = []
    for s, t in sents:
        nums = [m.group(0).strip() for m in NUM_RX.finditer(t)]
        if nums or MONEY_WORDS.search(t):
            claims.append({'text': t, 'numbers': nums[:6], 'tc': tc(s)})
    scr = [{'tc': tc(t0), 'text': txt[:120]} for t0, txt in screens if a['t0'] - 0.01 <= t0 < a['t1']]
    return {'summary': summ, 'theses': theses, 'claims': claims[:15], 'screens': scr[:25]}


class LLM:
    def __init__(self):
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler
        print(f'загружаю {MODEL}', flush=True)
        self.model, self.tok = load(MODEL)
        self.generate, self.sampler = generate, make_sampler(temp=0.2, top_p=0.9)

    def count(self, text):
        return len(self.tok.encode(text))

    def ask(self, prompt, max_tokens=900, text=''):
        msg = self.tok.apply_chat_template([{'role': 'user', 'content': prompt}], add_generation_prompt=True,
                                           tokenize=False, enable_thinking=False)
        raw = self.generate(self.model, self.tok, prompt=msg, max_tokens=max_tokens, sampler=self.sampler, verbose=False)
        return clean_result(parse_json(raw), text)


# ── структурные проверки ───────────────────────────────────────────────────
def structure_checks(ws, acts, rules, names):
    checks = []
    text = ' '.join(w['n'] for w in ws)
    starts, pos = [], 0
    for w in ws:
        starts.append(pos); pos += len(w['n']) + 1

    def word_at(off):
        import bisect
        return ws[max(0, bisect.bisect_right(starts, off) - 1)]

    def phrase(i, k=6):
        return ' '.join(x['w'] for x in ws[max(0, i - k):i + k + 1])

    if not rules:
        return [{'rule': 'structure_rules', 'status': 'n/a', 'ok': None, 'detail': T('e.no_structure_rules')}]
    # 1. вход фонда
    n_min = rules.get('fund_entry_min')
    if n_min and rules.get('fund_rx'):
        m = re.search(rules['fund_rx'], text)
        if not m:
            checks.append({'rule': 'fund_entry_min', 'status': 'pass', 'ok': True, 'value': None, 'threshold': n_min,
                           'detail': 'фонд/сбор в речи не упоминается'})
        else:
            w = word_at(m.start()); mn = w['s'] / 60
            checks.append({'rule': 'fund_entry_min', 'status': 'pass' if mn >= n_min else 'fail', 'ok': mn >= n_min,
                           'value': round(mn, 1), 'threshold': n_min, 'tc': tc(w['s']), 'speaker': names.get(w['spk'], w['spk']),
                           'detail': f'первое упоминание «{m.group(0)}» на {tc(w["s"])} (минута {mn:.1f}; правило ≥ {n_min})'})
    # 2. тизер — эхо поздних актов
    tsec, ngram, from_act = rules.get('teaser_sec', 60), rules.get('teaser_min_ngram', 6), rules.get('teaser_from_act', 2)
    if rules.get('teaser_rule'):
        if len(acts) < from_act:
            checks.append({'rule': 'teaser_rule', 'status': 'n/a', 'ok': None, 'detail': f'актов меньше {from_act} — эхо не измерить'})
        else:
            t_from = max(acts[from_act - 1]['t0'], float(tsec))   # эхо ищем ПОСЛЕ окна тизера, иначе фраза совпадёт сама с собой
            teaser = [i for i, w in enumerate(ws) if w['s'] < tsec]
            later = {}
            for i in range(len(ws) - ngram + 1):
                if ws[i]['s'] >= t_from:
                    later.setdefault(tuple(x['n'] for x in ws[i:i + ngram]), i)
            hits, seen = [], set()
            for i in teaser:
                key = tuple(x['n'] for x in ws[i:i + ngram])
                if len(key) == ngram and key in later and key not in seen:
                    seen.add(key); j = later[key]
                    hits.append({'teaser_tc': tc(ws[i]['s']), 'later_tc': tc(ws[j]['s']), 'phrase': ' '.join(x['w'] for x in ws[i:i + ngram])})
            checks.append({'rule': 'teaser_rule', 'status': 'pass' if hits else 'fail', 'ok': bool(hits), 'value': len(hits),
                           'threshold': 1, 'hits': hits[:8],
                           'detail': (f'в первых {tsec} с найдено {len(hits)} фраз(ы) ≥{ngram} слов из актов ≥{from_act} '
                                      f'(с {tc(t_from)}) — судить, есть ли среди них надежда, а не только беды' if hits else
                                      f'в первых {tsec} с нет ни одной фразы ≥{ngram} слов из актов ≥{from_act} (с {tc(t_from)}): тизер — только из начала')})
    # 3. последний звук
    lsec = rules.get('last_sound_sec', 20)
    if rules.get('last_sound_rule') and rules.get('money_rx'):
        end = ws[-1]['e']
        tail = [w for w in ws if w['s'] >= end - lsec]
        ttext = ' '.join(w['n'] for w in tail)
        m = re.search(rules['money_rx'], ttext)
        checks.append({'rule': 'last_sound_rule', 'status': 'fail' if m else 'pass', 'ok': not m, 'value': m.group(0) if m else None,
                       'tc': tc(tail[0]['s']) if tail else tc(end), 'speaker': names.get(tail[-1]['spk'], tail[-1]['spk']) if tail else '',
                       'detail': (f'последние {lsec} с ({tc(end - lsec)}–{tc(end)}) содержат призыв о деньгах: «{m.group(0)}» — '
                                  f'последняя реплика: «…{" ".join(w["w"] for w in tail[-12:])}»' if m else
                                  f'последние {lsec} с без призыва о деньгах; последняя реплика: «…{" ".join(w["w"] for w in tail[-12:])}»')})
    # 4. фонд — малыми кусками
    pmax = rules.get('fund_piece_max_sec')
    if pmax:
        fs = P.get(rules.get('fund_speaker_key', 'fund_speaker'))
        ids = {k for k, v in names.items() if v == fs} | ({fs} if fs else set())
        if not fs:
            checks.append({'rule': 'fund_piece_max_sec', 'status': 'n/a', 'ok': None, 'threshold': pmax,
                           'detail': 'в карточке нет fund_speaker (id или имя спикера фонда) — проверка пропущена'})
        else:
            runs, cur = [], None
            for w in ws:
                if w['spk'] in ids:
                    if cur and w['s'] - cur[1] < 2.0:
                        cur[1] = w['e']
                    else:
                        cur = [w['s'], w['e']]; runs.append(cur)
            longest = max(runs, key=lambda r: r[1] - r[0]) if runs else None
            val = round(longest[1] - longest[0], 1) if longest else 0.0
            checks.append({'rule': 'fund_piece_max_sec', 'status': 'pass' if val <= pmax else 'fail', 'ok': val <= pmax,
                           'value': val, 'threshold': pmax, 'tc': tc(longest[0]) if longest else None,
                           'detail': (f'самый длинный кусок «{fs}»: {val:.0f} с на {tc(longest[0])}–{tc(longest[1])} (правило ≤ {pmax} с); '
                                      f'всего кусков {len(runs)}' if longest else f'спикер «{fs}» в кате не звучит')})
    return checks


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--act', type=int)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--max-tokens', type=int, default=4000)
    ap.add_argument('--no-llm', action='store_true')
    ap.add_argument('--checks-only', action='store_true')
    ap.add_argument('--channel')
    ap.add_argument('--out', default=str(W6 / 'acts_compact.json'))
    ap.add_argument('--checks-out', default=str(W6 / 'structure_checks.json'))
    ap.add_argument('--screens', default=str(W6 / 'screens_v6.json'))
    a = ap.parse_args()
    # профиль verdict.acts_llm = false (редакторский вердикт) → без модели; профиль без ключа (YTCH) — как было
    editorial = P.profile('verdict.acts_llm') is False
    no_llm = a.no_llm or editorial

    ws, paras = load_words()
    if not ws:
        raise SystemExit(f'пустой транскрипт {P.WORDS}')
    names = {k: str(v) for k, v in dict(P.get('speakers') or {}).items()}
    acts = load_acts(ws)
    # ── структурные проверки (всегда, дёшево) ──
    if a.channel:
        pp = YTAI / 'YTs' / a.channel.upper() / 'review_profile.json'
        rules = (json.load(open(pp, encoding='utf-8')) or {}).get('structure_rules') or {}
    else:
        rules = P.profile('structure_rules') or {}
    checks = structure_checks(ws, acts, rules, names)
    P.write_json_atomic(a.checks_out, {'schema': 'structure-checks-v1', 'code': P.CODE, 'cut_version': P.CUT_VERSION,
                                       'rules_from': a.channel or P.CHANNEL, 'checks': checks})
    icon = {'pass': '✅', 'fail': '❌', 'n/a': '➖'}
    print(f'[structure] {P.CODE} {P.CUT_VERSION} · правила {a.channel or P.CHANNEL or "—"} → {a.checks_out}')
    for c in checks:
        print(f'  {icon[c["status"]]} {c["rule"]}: {c["detail"][:160]}')
    if a.checks_only:
        return 0

    # ── акты ──
    out_p = Path(a.out)
    old = {}
    if out_p.exists():
        try:
            old = {x['act']: x for x in json.load(open(out_p, encoding='utf-8')).get('acts', [])}
        except Exception:
            old = {}
    todo = [x for x in acts if not a.act or x['act'] == a.act]
    if a.act and not todo:
        raise SystemExit(f'нет акта {a.act} (всего {len(acts)})')
    llm = None
    screens = load_screens(a.screens) if editorial else []
    model = 'extractive' if editorial else MODEL
    count = (lambda t: max(1, len(t) // 3))
    results = dict(old)
    for act in todo:
        ptxt = act_paragraphs(ws, paras, act, names)
        text = '\n'.join(ptxt)
        h = hashlib.sha1(text.encode('utf-8')).hexdigest()[:10]
        if not a.force and act['act'] in old and old[act['act']].get('hash') == h and (old[act['act']].get('llm') or no_llm):
            print(f'  акт {act["act"]} «{act["title"]}» — без изменений, пропуск')
            continue
        t_start = time.time()
        rec = {'act': act['act'], 'title': act['title'], 'tc_range': act['tc_range'], 't0': act['t0'], 't1': act['t1'],
               'speakers_share': speakers_share(ws, act, names), 'hash': h, 'words': len(text.split())}
        if not text.strip():
            rec.update({'summary': '', 'theses': [], 'claims': [], 'windows': 0, 'llm': False})
        elif editorial:
            rec.update(extractive_acts(ws, act, screens), windows=1, llm=False)
        elif a.no_llm:
            rec.update(extractive(text), windows=1, llm=False)
        else:
            if llm is None:
                llm = LLM(); count = llm.count
            wins = windows(ptxt, count, a.max_tokens)
            parts = []
            for k, wtxt in enumerate(wins, 1):
                r = llm.ask(PROMPT.format(film=P.FILM or P.CODE, title=act['title'], tc0=tc(act['t0']), tc1=tc(act['t1']), text=wtxt), text=wtxt)
                if r is None:
                    r = extractive(wtxt); r['_llm'] = False
                parts.append(r)
                print(f'    окно {k}/{len(wins)} ({count(wtxt)} ток.) — {"модель" if r.get("_llm", True) else "экстракт"}', flush=True)
            ok_llm = all(p.get('_llm', True) for p in parts)
            if len(parts) == 1:
                final = parts[0]
            else:
                mtxt = '\n\n'.join(f'ОКНО {k}: {p["summary"]}\nТезисы: ' + ' | '.join(p['theses']) + '\nФакты: ' +
                                   ' | '.join(c['text'] for c in p['claims']) for k, p in enumerate(parts, 1))
                final = llm.ask(MERGE.format(film=P.FILM or P.CODE, title=act['title'], tc0=tc(act['t0']), tc1=tc(act['t1']), text=mtxt), text=text)
                if final is None:
                    seen, cl = set(), []
                    for p in parts:
                        for c in p['claims']:
                            if c['text'] not in seen:
                                seen.add(c['text']); cl.append(c)
                    final = {'summary': ' '.join(' '.join(p['summary'].split()[:40]) for p in parts)[:900],
                             'theses': [t for p in parts for t in p['theses']][:5], 'claims': cl[:15]}
                    ok_llm = False
            rec.update({k: final[k] for k in ('summary', 'theses', 'claims')}, windows=len(wins), llm=ok_llm)
        rec['sec'] = round(time.time() - t_start, 1)
        results[act['act']] = rec
        P.write_json_atomic(out_p, {'schema': 'acts-compact-v1', 'code': P.CODE, 'cut_version': P.CUT_VERSION, 'model': model,
                                    'acts': [results[k] for k in sorted(results)]})
        print(f'  акт {act["act"]} «{act["title"]}» {act["tc_range"]}: слов {rec["words"]} · окон {rec.get("windows", 0)} · '
              f'{"модель" if rec.get("llm") else "экстракт"} · {rec["sec"]} с · тезисов {len(rec.get("theses", []))} · '
              f'фактов {len(rec.get("claims", []))} · доли {rec["speakers_share"]}', flush=True)
    print(f'[acts] {len(results)}/{len(acts)} актов → {out_p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
