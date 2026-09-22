#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сверка ТЗ прошлой версии ката против фактов новой: «что монтажёр закрыл с прошлого раза».

Вопрос возникает на каждом повторном кате и раньше решался руками. Конвейер отвечает на другой
вопрос — «что не так в новой версии», — поэтому закрытые пункты в его ТЗ не попадают вовсе.

Что считается кодом, а что честно помечается «нужен глаз»:
  graphics  — закавыченный текст пункта ищется среди экранов нового ката (OCR);
  fund/sensitive — закавыченные реплики ищутся в транскрипте нового ката;
  cut       — по align: если перестановок 0 и из базы не выпало ничего рядом с таймкодом пункта,
              вырез не сделан; длительность выпавшего берётся из align;
  structure — по structure_checks.json (правила канала) и по наличию карточек глав на экране;
  insert / check / color — визуальные и постановочные, автоматически не судятся.

Каждая строка несёт ДОКАЗАТЕЛЬСТВО: текст с экрана с таймкодом, реплику из транскрипта или
число из align. Без доказательства статус не ставится — вместо него «нужен глаз».

Два поколения в одном файле:
  tz-diff-v1   — judge() и CLI ниже: ими пользуется вкладка «Сверка» (stages/doc_tab_diff_v1.py читает tz_diff.json);
  feedback-v1  — match(), quotes_by_role(), judge_v2(): движок для shared/feedback_model.py (контракт
                 docs/feedback_v1.md). Отличия: цитаты берутся по роли блока (что должно появиться — из ✅,
                 что должно исчезнуть — из ❌; из 📍/📚/🎬 никогда), ищутся в окне вокруг проекции таймкода на
                 новый кат, «закрыто» ставится только когда найдены ВСЕ целевые цитаты пункта.

Модуль импортируется без карточки фильма: карточка нужна только CLI (main).

usage: tz_diff.py --old <pravki прошлой версии.json> [--out diff.json]
       tz_diff.py --selftest
"""
import argparse
import bisect
import json
import re
import sys
from pathlib import Path

QUOTE_RE = re.compile(r'[«"]([^»"]{4,120})[»"]')
AUTO_CATS = {'graphics', 'fund', 'cut', 'structure'}


# OCR путает латинские и кириллические двойники (титул «ОДНА С РЕБЁНКОМ» читается с латинской C).
# Буквальное сравнение на этом ломается, поэтому обе азбуки складываем в одну.
HOMOGLYPH = str.maketrans('acekmoptxy', 'асекмортху')   # складываем после lower(), в обе стороны одинаково
# feedback-v1: ещё и двойники заглавных (B→В, H→Н) и латинская ë из «MOË» — tz-diff-v1 не трогаем, его числа сверены
HOMOGLYPH2 = str.maketrans('acekmoptxybhë', 'асекмортхувне')
STOP = {'и', 'в', 'на', 'с', 'по', 'не', 'что', 'для', 'из', 'от', 'за', 'к', 'у', 'о', 'а', 'же', 'то'}


def norm(t: str) -> str:
    t = (t or '').lower().replace('ё', 'е').translate(HOMOGLYPH)
    return re.sub(r'[^a-zа-я0-9]+', ' ', t).strip()


def norm2(t: str) -> str:
    t = (t or '').lower().replace('ё', 'е').translate(HOMOGLYPH2)
    return re.sub(r'[^a-zа-я0-9]+', ' ', t).strip()


def words_of(t: str) -> set:
    return {w for w in norm(t).split() if len(w) > 2 and w not in STOP}


def overlap(quote: str, blob_words: set) -> float:
    """доля значащих слов цитаты, встретившихся в тексте — устойчива к перефразировке и к OCR-шуму"""
    qw = words_of(quote)
    return len(qw & blob_words) / len(qw) if qw else 0.0


def tc(sec) -> str:
    s = int(float(sec))
    return f'{s // 60}:{s % 60:02d}'


def quotes(item: dict) -> list:
    """закавыченные куски пункта — это ровно то, что можно искать в фактах нового ката"""
    blob = ' '.join(str(item.get(k) or '') for k in ('title', 'nado', 'est', 'decision'))
    out, seen = [], set()
    for q in QUOTE_RE.findall(blob):
        n = norm(q)
        if len(n) >= 8 and n not in seen:
            seen.add(n)
            out.append(q.strip())
    return out[:6]


def tc_start(item: dict):
    """первый таймкод пункта в секундах (v1_tc или начало tc_range)"""
    raw = str(item.get('v1_tc') or item.get('tc_range') or '')
    m = re.search(r'(\d+):(\d{2})', raw)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def pick_base(al: dict, against=''):
    """база сверки в align.json → (тег, словарь базы). Та же логика, что chapters_from_plan.pick_base
    (тот модуль тянет карточку при импорте, поэтому здесь повтор); базы нет → ('', {})"""
    bases = (al or {}).get('bases') or {}
    if against:
        ap = Path(against).resolve()
        for tag, b in bases.items():
            if b.get('file') and Path(b['file']).resolve() == ap:
                return tag, b
        stem = Path(against).stem.replace('.words', '')
        if stem in bases:
            return stem, bases[stem]
        for tag, b in bases.items():                       # align считан на другой машине: сверяем по имени файла
            if Path(str(b.get('file') or '')).name == Path(against).name:
                return tag, b
    if len(bases) == 1:
        return next(iter(bases.items()))
    return '', {}


def shift_near(cut_map: list, t: float) -> float:
    """сдвиг «новый кат − база» у ближайшего к t края спана"""
    best, off = None, 0.0
    for sp in cut_map or []:
        for bt, ct in ((sp['base_t0'], sp['cut_t0']), (sp['base_t1'], sp['cut_t1'])):
            d = abs(t - bt)
            if best is None or d < best:
                best, off = d, ct - bt
    return off


def real_dropped(base: dict, near=30.0, same=0.5) -> list:
    """куски базы, которых в новом кате действительно нет. align кладёт в unused и ту же речь, расшифрованную
    иначе («думаю в ура они помирились» ↔ «Думала, ура, они помирились»): если рядом с проекцией куска в новом
    кате стоит new с долей общих слов ≥ same — это не вырез."""
    out = []
    for u in (base or {}).get('unused') or []:
        at = float(u.get('t0') or 0) + shift_near(base.get('cut_map'), float(u.get('t0') or 0))
        uw = words_of(u.get('text'))
        twin = False
        for nw in base.get('new') or []:
            if float(nw.get('t1') or 0) < at - near or float(nw.get('t0') or 0) > at + near:
                continue
            nwords = words_of(nw.get('text'))
            if max(overlap(u.get('text'), nwords), overlap(nw.get('text'), uw)) >= same:
                twin = True
                break
        if not twin:
            out.append(u)
    return out


class Facts:
    """факты нового ката: экраны, речь, align (база сверки), структурные проверки"""

    def __init__(self, work=None, words_path=None, against='', data=None, prev_screens=None):
        d = data or {}
        # экраны ПРОШЛОГО ката (если есть): текст, который стоял там же и раньше, не доказывает, что правку сделали
        ps = d.get('prev_screens') if data else (self._load(prev_screens, []) if prev_screens else [])
        ps = ps.get('screens', []) if isinstance(ps, dict) else (ps or [])
        self.prev_screens = [dict(t0=float(e.get('t0') or 0), text=self._screen_text(e) + ' ' + str(e.get('text') or ''))
                             for e in ps]
        self.screens = d.get('screens') if data else self._load(Path(work) / 'screens_v6.json', [])
        if isinstance(self.screens, dict):
            self.screens = self.screens.get('screens', [])
        self.screens = self.screens or []
        self.screen_blob = norm(' '.join(self._screen_text(e) for e in self.screens))
        words = d.get('words') if data else self._load(words_path, {})
        self.segs = (words or {}).get('segments') or []
        self.duration = float((words or {}).get('duration_sec') or 0)
        self.align = d.get('align') if data else self._load(Path(work) / 'align.json', {})
        self.base_tag, self.base = pick_base(self.align or {}, against)
        checks = d.get('checks') if data else self._load(Path(work) / 'structure_checks.json', {})
        self.checks = {c['rule']: c for c in (checks or {}).get('checks', [])}
        self.dropped = real_dropped(self.base)
        # пословная лента речи: (нормализованное слово, слово как есть, секунда начала)
        self.wseq = []
        for seg in self.segs:
            ws = seg.get('words') or [{'w': w, 's': seg.get('start', 0)} for w in str(seg.get('text') or '').split()]
            for w in ws:
                for k, n in enumerate(norm2(w.get('w')).split()):   # «из-за» → два слова, исходник — у первого
                    self.wseq.append((n, str(w.get('w')) if k == 0 else '', float(w.get('s') or 0)))
        self.wseq.sort(key=lambda x: x[2])
        self._wt = [x[2] for x in self.wseq]

    @staticmethod
    def _load(p, default):
        try:
            return json.load(open(p, encoding='utf-8'))
        except Exception:                                  # noqa: BLE001
            return default

    @staticmethod
    def _screen_text(e) -> str:
        return (e.get('text_best') or '') + ' ' + ' '.join(e.get('texts_all') or [])

    def on_screen(self, q: str):
        """лучший экран по доле совпавших слов; (tc, текст, доля)"""
        best = (None, None, 0.0)
        for e in self.screens:
            w = words_of(self._screen_text(e))
            s = overlap(q, w)
            if s > best[2]:
                best = (e.get('tc'), (e.get('text_best') or '').replace('\n', ' | '), s)
        return best

    def in_speech(self, q: str):
        best = (None, None, 0.0)
        for seg in self.segs:
            s = overlap(q, words_of(seg.get('text')))
            if s > best[2]:
                best = (tc(seg.get('start', 0)), (seg.get('text') or '').strip(), s)
        return best

    @property
    def moved(self) -> int:
        """сколько кусков базы переставлено (align.bases[база].moved)"""
        return len((self.base or {}).get('moved') or [])

    @property
    def dropped_sec(self) -> float:
        """секунд речи базы, которых в новом кате действительно нет (см. real_dropped)"""
        return round(float(sum(float(u.get('sec') or 0) for u in self.dropped)), 1)

    # ── feedback-v1: поиск в окне ────────────────────────────────────────────
    def was_there(self, q: str, e: dict, tol=15.0) -> bool:
        """тот же текст стоял на том же месте уже в прошлом кате (место прошлого ката переносится сдвигом спана)"""
        t_new = float(e.get('t0') or 0)
        for pe in self.prev_screens:
            if abs(pe['t0'] + shift_near((self.base or {}).get('cut_map'), pe['t0']) - t_new) <= tol \
                    and match(q, pe['text'])[0] >= SURE:
                return True
        return False

    def screen_hits(self, q: str, sec=None, win=None) -> list:
        """экраны, где найдена цитата: [{score, exact, dist, e}], лучший первым; dist — секунд от окна до экрана
        (0 — внутри окна; None — у пункта нет времени)"""
        out = []
        for e in self.screens:
            sc, ex = match(q, self._screen_text(e))
            if sc < MAYBE:
                continue
            dist = None
            if sec is not None:
                t0, t1 = float(e.get('t0') or 0), float(e.get('t1') or e.get('t0') or 0)
                dist = 0.0 if t0 - win <= sec <= t1 + win else min(abs(sec - t0), abs(sec - t1)) - win
            out.append(dict(score=sc, exact=ex, dist=dist, e=e))
        out.sort(key=lambda h: (-(h['score'] + (0.001 if h['exact'] else 0)), h['dist'] or 0))
        return out

    def speech_hit(self, q: str, sec=None, win=None):
        """лучшее место цитаты в речи: скользящее окно по словам (в окне ±win с вокруг sec либо по всему фильму).
        → {score, exact, sec, text} или None"""
        qn = norm2(q).split()
        if not qn or not self.wseq:
            return None
        i0, i1 = 0, len(self.wseq)
        if sec is not None:
            i0 = bisect.bisect_left(self._wt, sec - win)
            i1 = bisect.bisect_right(self._wt, sec + win)
        span = max(6, len(qn) + len(qn) // 2)
        seq = self.wseq[i0:i1]
        if not seq:
            return None
        # точная подстрока — по границам слов, с адресом первого слова
        names = [c[0] for c in seq]
        for i in range(len(names) - len(qn) + 1) if len(qn) >= 2 else ():
            if names[i] == qn[0] and names[i:i + len(qn)] == qn:
                chunk = seq[i:i + len(qn)]                  # дословное попадание: в доказательство идёт сама реплика
                return dict(score=1.0, exact=True, sec=chunk[0][2], text=' '.join(c[1] for c in chunk if c[1]))
        best = None
        for i in range(0, max(1, len(seq) - span + 1), max(1, span // 3)):
            chunk = seq[i:i + span]
            sc, _ = match(q, ' '.join(c[0] for c in chunk))
            if best is None or sc > best['score']:
                best = dict(score=sc, exact=False, sec=chunk[0][2], text=' '.join(c[1] for c in chunk if c[1]))
        return best


SURE_V1, MAYBE_V1 = 0.70, 0.30          # tz-diff-v1: доля совпавших слов — уверенно / спорно


def best_of(qs, finder):
    """лучшее попадание по всем цитатам пункта"""
    best = (None, None, 0.0)
    for q in qs:
        hit = finder(q)
        if hit[2] > best[2]:
            best = hit
    return best


def judge(item: dict, f: Facts) -> dict:
    """статус пункта + доказательство; при частичном совпадении честно «нужен глаз»"""
    cat = item.get('category') or ''
    qs = quotes(item)
    if not qs:
        return dict(status='нужен глаз', why='в пункте нет закавыченного текста — судить по таймлайну')

    if item.get('sensitive'):
        tcv, txt, s = best_of(qs, f.in_speech)
        if s >= SURE_V1:
            return dict(status='ждёт фонд', why=f'на месте в {tcv}: «{txt[:90]}»')
        if s >= MAYBE_V1:
            return dict(status='нужен глаз', why=f'похоже, на месте в {tcv} (совпало {s:.0%}): «{txt[:70]}»')
        return dict(status='нужен глаз', why='реплика не опознана по транскрипту — проверить кадром')

    if cat == 'graphics':
        tcv, txt, s = best_of(qs, f.on_screen)
        if s >= SURE_V1:
            return dict(status='сделано', why=f'на экране {tcv}: «{txt[:90]}»')
        if s >= MAYBE_V1:
            return dict(status='нужен глаз',
                        why=f'на экране {tcv} похожее (совпало {s:.0%}): «{txt[:70]}» — сверить формулировку')
        return dict(status='не сделано', why=f'на экранах нового ката нет: «{qs[0][:70]}»')

    if cat == 'cut':
        tcv, txt, s = best_of(qs, f.in_speech)
        if s >= SURE_V1:
            return dict(status='не сделано', why=f'реплика на месте в {tcv}: «{txt[:90]}»')
        if f.moved == 0 and f.dropped_sec < 20:
            return dict(status='не сделано',
                        why=f'align: перестановок {f.moved}, из базы выпало {f.dropped_sec:.0f} с на весь фильм')
        return dict(status='нужен глаз', why='align не даёт однозначного ответа по этому куску')

    if cat == 'structure':
        for rule, human in (('fund_entry_min', 'вход фонда'),
                            ('last_sound_rule', 'последний звук'),
                            ('teaser_rule', 'тизер')):
            c = f.checks.get(rule) or {}
            t = norm(str(item.get('title')))
            if human.split()[0] in t or (human == 'вход фонда' and 'фонд' in t):
                st = 'не сделано' if c.get('status') == 'fail' else 'нужен глаз'
                return dict(status=st, why=f'{rule}: {c.get("status")} — {str(c.get("detail"))[:110]}')
        if 'структур' in norm(str(item.get('title'))):
            n = sum(1 for e in f.screens if len(norm(e.get('text_best') or '')) > 3
                    and (e.get('dur') or 0) >= 3)
            return dict(status='сделано' if n >= 10 else 'нужен глаз',
                        why=f'полноэкранных карточек на экране: {n}')
        return dict(status='нужен глаз', why='структурный пункт — судить по таймлайну')

    return dict(status='нужен глаз', why=f'категория «{cat}» автоматически не судится')


# ═══ feedback-v1: новый судья ════════════════════════════════════════════════════════════════════════════════
MIN_SIG = 3                             # меньше значащих слов в цитате — судить нечем (экран: 2 при точной подстроке)
SURE, MAYBE = 0.80, 0.50                # доля совпавших значащих слов: уверенно / похоже
WIN_SPEECH, WIN_SCREEN = 45, 120        # окно вокруг проекции таймкода, с (карточка главы стоит ДО главы — экрану шире)
THRESHOLDS = dict(min_sig=MIN_SIG, sure=SURE, maybe=MAYBE, win_speech=WIN_SPEECH, win_screen=WIN_SCREEN)
STOP2 = STOP | {'это', 'как', 'так', 'его', 'она', 'они', 'мне', 'меня', 'был', 'была', 'были', 'или', 'при', 'уже',
                'еще', 'там', 'тут', 'вот', 'что', 'чтобы', 'когда', 'если', 'тоже', 'очень', 'себя', 'свой'}
TC_ANY = re.compile(r'(?<![\d:.,])(\d{1,4}):(\d{2})(?::(\d{2}))?(?:[.,]\d{1,3})?(?![\d:])')
# привязка пункта к правилу канала (structure_checks.json) — по заголовку
RULE_BIND = (('fund_entry_min', re.compile(r'фонд\w*.{0,40}(вход|входит|рано|раньше)|(вход|входит|рано)\w*.{0,40}фонд', re.I)),
             ('last_sound_rule', re.compile(r'последн\w+ (звук|слов)|деньги не последн|призыв\w*.{0,40}(конц|финал)|'
                                            r'(конц|финал)\w*.{0,40}призыв', re.I)),
             ('teaser_rule', re.compile(r'тизер', re.I)))
CUT_RE = re.compile(r'вырез|убрать|удалить', re.I)
MOVE_RE = re.compile(r'перенос|перенести|продублир|сдвинуть|передвинуть', re.I)
REORDER_RE = re.compile(r'TO-BE|перестанов|переставить|порядок сцен|хронологи\w+ сцен', re.I)


def _t(key: str, default: str, **kw) -> str:
    """человеческая строка: shared/i18n_strings (если ключ там заведён) → русский текст по умолчанию"""
    try:
        import i18n
        v = i18n.T(key)
        v = v if isinstance(v, str) else default
    except Exception:                                      # noqa: BLE001  (ключа нет / i18n недоступен)
        v = default
    return v.format(**kw) if kw else v


def sig_words(t: str) -> list:
    """значащие слова цитаты: длиннее 3 букв, без служебных; числа считаются"""
    out = []
    for w in norm2(t).split():
        if (len(w) > 3 or w.isdigit()) and w not in STOP2 and w not in out:
            out.append(w)
    return out


def match(q: str, text: str):
    """→ (score, exact). Точная нормализованная подстрока по границам слов — (1.0, True);
    иначе доля значащих слов цитаты, встретившихся в тексте — (доля, False)."""
    qn, tn = norm2(q), norm2(text)
    if not qn or not tn:
        return 0.0, False
    if f' {qn} ' in f' {tn} ':
        return 1.0, True
    qs = sig_words(q)
    if not qs:
        return 0.0, False
    tw = set(tn.split())
    return len([w for w in qs if w in tw]) / len(qs), False


def _quotes_in(lines) -> list:
    out, seen = [], set()
    for q in QUOTE_RE.findall(' '.join(lines)):
        q = re.sub(r'\s*[/|]\s*', ' ', q).replace('...', '…').strip(' .…,')
        n = norm2(q)
        if len(n) >= 4 and n not in seen and '…' not in q:    # многоточие внутри — пересказ, а не цитата
            seen.add(n)
            out.append(q)
    # «Одна с ребёнком» и «ОДНА С РЕБЁНКОМ фильм» — одно требование: оставляем более длинную (строгую) запись
    keep = [q for q in out if not any(q is not o and f' {norm2(q)} ' in f' {norm2(o)} ' for o in out)]
    return keep[:8]


def quotes_by_role(parts: dict, category: str, title: str = '') -> list:
    """целевые цитаты пункта по роли блока. parts — результат feedback_model.split_nado().
    graphics — то, что должно ПОЯВИТЬСЯ на экране: из ✅ (пусто → из заголовка после «:»);
    cut      — то, что должно ИСЧЕЗНУТЬ из речи: из ❌;
    остальное (в т.ч. чувствительные) — реплика, о которой пункт: из ❌.
    Из 📍/📚/🎬 цитаты не берутся никогда: там якоря и исходники, то есть ровно то, что в кате останется."""
    def flat(key):
        return [ln for el in (parts.get(key) or []) for ln in el]
    if category == 'graphics':
        qs = _quotes_in(flat('do'))
        if not qs and ':' in (title or ''):
            qs = _quotes_in([title.split(':', 1)[1]])
        return qs
    return _quotes_in(flat('now'))


def bound_rule(title: str, checks: dict):
    """правило канала, к которому относится пункт: (имя, запись проверки) или ('', {})"""
    for rule, rx in RULE_BIND:
        if rule in (checks or {}) and rx.search(title or ''):
            return rule, checks[rule]
    return '', {}


def rule_text(rule: str, c: dict) -> str:
    """доказательство по правилу канала — фраза без таймкода (он живёт в evidence.tc)"""
    if rule == 'fund_entry_min':
        return _t('fb.ev.fund_entry', 'фонд впервые звучит на {m}-й минуте, правило канала — не раньше {thr}-й',
                  m=int(float(c.get('value') or 0)) + 1, thr=c.get('threshold') or 34)
    if rule == 'last_sound_rule':
        return _t('fb.ev.last_sound', 'фильм заканчивается призывом о деньгах, правило канала — '
                                      'последним звучит герой')
    return _t('fb.ev.rule_fail', 'правило канала нарушено')


def _cut(s: str, n: int = 110) -> str:
    """фраза целиком или по границе слова, без многоточия"""
    s = re.sub(r'\s+', ' ', str(s or '')).strip()
    return s if len(s) <= n else s[:n].rsplit(' ', 1)[0].rstrip(' ,;:—-')


def _ev(kind, sec, text, score=None):
    return dict(kind=kind, tc=tc(sec) if sec is not None else '', sec=int(sec) if sec is not None else None,
                text=text, **({'score': round(score, 2)} if score is not None else {}))


def _screen_check(q, f: Facts, secs, win=None):
    """одна цитата против экранов: → (found, check, hit). found=True только при SURE в окне; вне окна — лишь
    точная подстрока из ≥ MIN_SIG значащих слов, стоящая ровно на одном экране."""
    nsig = len(sig_words(q))
    best, where = None, ''
    for sec in (secs or [None]):
        for h in f.screen_hits(q, sec, win or WIN_SCREEN):
            if best is None or (h['score'], h['exact']) > (best['score'], best['exact']) or \
                    ((h['score'], h['exact']) == (best['score'], best['exact']) and (h['dist'] or 0) < (best['dist'] or 0)):
                best = h
    found = False
    if best:
        qn = norm2(q)
        enough = nsig >= MIN_SIG or (best['exact'] and (nsig >= 2 or (len(qn.split()) >= 2 and len(qn) >= 8)))
        inside = best['dist'] == 0.0
        if f.was_there(q, best['e']):
            where = 'before'                               # стояло и в прошлом кате — не доказательство
        elif best['score'] >= SURE and enough and inside:
            found, where = True, 'window'
        elif best['exact'] and nsig >= MIN_SIG and win is None and \
                sum(1 for h in f.screen_hits(q) if h['exact']) == 1:
            found, where = True, 'elsewhere'
    chk = dict(q=q, found=found, tc=(best['e'].get('tc') or tc(best['e'].get('t0') or 0)) if best else '',
               score=round(best['score'], 2) if best else 0.0)
    return found, chk, (best if best else None), where


def judge_v2(item: dict, parts: dict, f: Facts, secs_new=None, project=None, prev_label='', secs_old=None) -> dict:
    """пересуд одного пункта прошлого ТЗ по фактам нового ката.
    item — {title, category, severity, sensitive}; parts — split_nado(); secs_new — секунды пункта в НОВОМ кате
    (пусто — времени нет, окна снимаются, но и «закрыто» тогда ставится только по правилу «ровно один экран»);
    project — sec_old → sec_new|None для таймкодов внутри 📋 СПИСОК; secs_old — секунды пункта в прошлом кате
    (нужны только вырезам: лежит ли пункт на действительно выпавшем куске базы).
    → {status: closed|open|fund|unknown, by: code|flag|rule, evidence: {...}|None, checks: [...], rule: str}"""
    cat = item.get('category') or ''
    title = str(item.get('title') or '')
    secs = [s for s in (secs_new or []) if s is not None]
    out = dict(status='unknown', by='code', evidence=None, checks=[], rule='')

    # 1. чувствительное: статус по флагу; доказательство — только уверенная реплика внутри окна
    if item.get('sensitive'):
        out.update(status='fund', by='flag')
        for q in quotes_by_role(parts, cat, title):
            if len(sig_words(q)) < MIN_SIG:
                continue
            for sec in secs:
                h = f.speech_hit(q, sec, WIN_SPEECH)
                if h and h['score'] >= SURE:
                    out['evidence'] = _ev('speech', h['sec'], _t('fb.ev.line_stays', 'реплика на месте: «{q}»',
                                                                 q=_cut(h['text'])), h['score'])
                    return out
        return out

    # 2. правило канала
    rule, c = bound_rule(title, f.checks)
    if rule:
        out['rule'] = rule
        if c.get('status') == 'fail':
            sec = tc_start({'v1_tc': c.get('tc')})
            out.update(status='open', by='rule', evidence=_ev('rule', sec, rule_text(rule, c)))
            return out

    # 3. 📋 СПИСОК: каждая строка списка — отдельная проверка по экранам (в checks[] идёт всегда)
    lists = [el for el in (parts.get('list') or []) if el and not re.search(r'youtube|описани', el[0], re.I)]
    per, missing, last_hit, stale = [], [], None, 0
    if lists:
        for el in lists:
            k = n = 0
            for ln in el[1:]:
                m = TC_ANY.search(ln)
                q = ln.split('▸', 1)[1] if '▸' in ln else (ln[m.end():] if m else ln)
                head, _, tail = q.partition(' — ')
                q = head if len(tail.split()) > 4 else q    # «НАЗВАНИЕ — пояснение на строку»: ищем название
                q = re.sub(r'\(гл\.?\s*\d+\)', '', q).strip(' «»"')
                if len(norm2(q)) < 4:
                    continue
                so = (int(m.group(1)) * 60 + int(m.group(2))) if m else None
                sn = project(so) if (project and so is not None) else None
                found, chk, hit, where = _screen_check(q, f, [sn] if sn is not None else [])
                out['checks'].append(chk)
                n += 1
                k += 1 if (found or where == 'before') else 0
                if found:
                    last_hit = hit
                elif where == 'before':
                    stale += 1                              # на экране есть, но стояло и в прошлом кате: не «нет» и не «сделано»
                else:
                    missing.append(q)
            if n:
                per.append((re.sub(r'\s*\(.*?\)\s*', '', el[0]).strip().lower() or 'список', k, n))
    # 4. перестановки / TO-BE — по числу переставленных кусков базы
    if REORDER_RE.search(title) and f.base:
        if f.moved == 0:
            txt = _t('fb.ev.same_order', 'порядок сцен тот же, что в {prev}: ни одна сцена не переставлена',
                     prev=prev_label or 'прошлом кате')
            out.update(status='open', by='code', evidence=_ev('align', None, txt))
        return out

    if cat in ('structure', 'graphics') and per:
        txt = _t('fb.ev.on_screen_counts', 'на экране есть: {what}',
                 what='; '.join(f'{h} — {k} из {n}' for h, k, n in per))
        if missing:
            txt += _t('fb.ev.missing', '; нет: {what}', what=', '.join(f'«{_cut(m, 40)}»' for m in missing[:3]))
            out.update(status='open', evidence=_ev('screen', secs[0] if secs else None, txt))
            return out
        # список на экране целиком; «закрыто» — только если и цитаты из ✅ все на экране
        rest = [q for q in _quotes_in([ln for el in (parts.get('do') or []) for ln in el]) if len(sig_words(q)) >= 2]
        if not stale and last_hit and all(_screen_check(q, f, secs)[0] for q in rest):
            out.update(status='closed', evidence=_ev('screen', float(last_hit['e'].get('t0') or 0), txt))
        return out

    qs = quotes_by_role(parts, cat, title)

    # 5. графика: все цитаты из ✅ должны стоять на экране
    if cat == 'graphics':
        targets, anchors = [], 0
        for q in qs:
            if len(norm2(q).split()) < 2 or len(norm2(q)) < 8:
                continue
            said = f.speech_hit(q) if len(sig_words(q)) >= MIN_SIG else None
            if said and said['score'] >= SURE and not f.screen_hits(q):
                anchors += 1                               # реплика-якорь («после слов …»), а не текст титра:
                continue                                   # «осталось» при таких цитатах код не ставит
            targets.append(q)
        if not targets:
            return out
        found_hits, missing, maybe = [], [], False
        do0 = ' '.join((parts.get('do') or [[]])[0])
        tight = 15 if (MOVE_RE.search(title) or MOVE_RE.search(do0)) else None   # «перенести»: текст нужен именно здесь
        for q in targets:
            found, chk, hit, where = _screen_check(q, f, secs, tight)
            out['checks'].append(chk)
            if found:
                found_hits.append((q, hit, where))
            else:
                missing.append(q)
                maybe = maybe or bool(hit)                 # похожее на экранах есть — судить не кодом
        if not missing:
            q, hit, where = found_hits[0]
            seen = _cut((hit['e'].get('text_best') or '').replace('\n', ' ').replace(' | ', ' '), 90)
            key, dflt = (('fb.ev.on_screen', 'на экране: «{q}»') if where == 'window' else
                         ('fb.ev.on_screen_else', 'на экране, но в другом месте фильма: «{q}»'))
            out.update(status='closed', evidence=_ev('screen', float(hit['e'].get('t0') or 0), _t(key, dflt, q=seen),
                                                     hit['score']))
        elif maybe or anchors:
            return out                                     # похожее на экранах есть либо в ✅ цитируется речь → не кодом
        else:
            if found_hits:
                txt = _t('fb.ev.k_of_n', 'на экране есть {k} из {n}; нет: {what}', k=len(found_hits), n=len(targets),
                         what=', '.join(f'«{_cut(m, 50)}»' for m in missing[:3]))
            else:
                txt = _t('fb.ev.not_on_screen', 'на экранах нового ката такого текста нет: {what}',
                         what=', '.join(f'«{_cut(m, 50)}»' for m in missing[:2]))
            out.update(status='open', evidence=_ev('screen', secs[0] if secs else None, txt))
        return out

    # 6. вырез: реплика из ❌ на месте → осталось; «закрыто» — только когда кусок базы действительно выпал
    if cat == 'cut' or (cat == 'structure' and CUT_RE.search(title)):
        qs = qs or quotes_by_role(parts, 'cut', title)
        targets = [q for q in qs if len(sig_words(q)) >= MIN_SIG]
        if not targets or not secs:
            return out
        stays, gone = None, 0
        for q in targets:
            hs = [h for h in (f.speech_hit(q, s, WIN_SPEECH) for s in secs) if h]
            h = max(hs, key=lambda x: x['score']) if hs else None
            out['checks'].append(dict(q=q, found=bool(h and h['score'] >= SURE), tc=tc(h['sec']) if h else '',
                                      score=round(h['score'], 2) if h else 0.0))
            if h and h['score'] >= SURE:
                stays = stays or h
            elif not h or h['score'] < 0.3:
                whole = f.speech_hit(q)
                gone += 1 if (not whole or whole['score'] < MAYBE) else 0
        if stays:
            out.update(status='open', evidence=_ev('speech', stays['sec'], _t('fb.ev.line_stays',
                       'реплика на месте: «{q}»', q=_cut(stays['text'])), stays['score']))
        elif gone == len(targets) and any(float(u.get('t0') or 0) - 5 <= so <= float(u.get('t1') or 0) + 5
                                          for u in f.dropped for so in (secs_old or [])):
            out.update(status='closed', evidence=_ev('align', secs[0], _t('fb.ev.line_gone',
                       'реплики больше нет в кате: «{q}»', q=_cut(targets[0]))))
        return out

    return out                                             # insert / check / color / прочее — кодом не судится

def selftest() -> int:
    """офлайн, на синтетике: починенный Facts, старый судья tz-diff-v1 и новый движок"""
    base = dict(file='/nowhere/F_v1.words.json',
                cut_map=[dict(base_t0=0, base_t1=100, cut_t0=10, cut_t1=110, words=40),
                         dict(base_t0=120, base_t1=300, cut_t0=140, cut_t1=320, words=90)],
                unused=[dict(t0=100, t1=106, sec=6.0, text='думаю в ура они помирились все такая радостная'),
                        dict(t0=108, t1=118, sec=10.0, text='совсем другой кусок про кредит на лекарства и переезд')],
                new=[dict(t0=111, t1=116, text='Думала, ура, они помирились, я такая радостная')], moved=[], reused=[])
    seg = 'Света является выпускницей одного из детских домов'
    words = dict(duration_sec=330, segments=[dict(start=50, text=seg, words=[dict(w=w, s=50 + i * 0.4)
                                                                             for i, w in enumerate(seg.split())])])
    screens = [dict(id='s1', t0=12, t1=16, tc='0:12', dur=5, text_best='ОДНА | C | РЕБЁНКОМ | фильм', texts_all=[]),
               dict(id='s2', t0=200, t1=205, tc='3:20', dur=6, text_best='МИША | MOË | ЧУДО', texts_all=[])]
    f = Facts(data=dict(screens=screens, words=words, align=dict(bases={'F_v1': base}),
                        checks=dict(checks=[dict(rule='last_sound_rule', status='fail', tc='5:20', detail='…')])))
    # Facts читает bases[...]: перестановок 0, «выпал» только второй кусок (первый — та же речь, расшифрованная иначе)
    assert (f.base_tag, f.moved, f.dropped_sec) == ('F_v1', 0, 10.0), (f.base_tag, f.moved, f.dropped_sec)
    assert pick_base(dict(bases={'a': {}, 'F_v1': base}), '/other/machine/F_v1.words.json')[0] == 'F_v1'
    assert pick_base({}, '') == ('', {})
    # tz-diff-v1 жив
    old = judge(dict(title='титул: «Одна с ребёнком»', category='graphics', nado='✅ СДЕЛАТЬ · «Одна с ребёнком»'), f)
    assert old['status'] == 'сделано', old
    old = judge(dict(title='Вырезать', category='cut', nado='❌ СЕЙЧАС · «совершенно другая реплика которой нет»'), f)
    assert old['status'] == 'не сделано' and 'выпало 10' in old['why'], old
    # новый движок
    assert match('Миша — моё чудо', 'МИША | MOË | ЧУДО') == (1.0, True)
    assert match('Квартира от государства', 'КВАРТИРА | OT | ГОСУДАРСТВА') == (1.0, True)
    sc, ex = match('выпускницей одного из детских домов страны', seg)
    assert not ex and sc == 0.8, (sc, ex)                   # 4 значащих слова из 5
    parts = dict(now=[['звучит «является выпускницей одного из детских домов»']], do=[['Титр «Одна с ребёнком»']],
                 where=[['0:40 · якорь «реплика из якоря не считается»']], src=[['«и из источника тоже»']])
    assert quotes_by_role(parts, 'graphics') == ['Одна с ребёнком']
    assert quotes_by_role(parts, 'cut') == ['является выпускницей одного из детских домов']
    assert quotes_by_role(dict(do=[['без кавычек']]), 'graphics', 'подпись: «Светлана / выпускница»') == ['Светлана выпускница']
    h = f.speech_hit('является выпускницей одного из детских домов', 52, WIN_SPEECH)
    assert h['exact'] and abs(h['sec'] - 50.4) < 0.01, h
    assert f.speech_hit('является выпускницей одного из детских домов', 200, WIN_SPEECH) is None
    v = judge_v2(dict(title='карточка: «Миша — моё чудо»', category='graphics'), dict(do=[['карточка «Миша — моё чудо»']]), f, [260])
    assert v['status'] == 'closed' and v['evidence']['tc'] == '3:20', v
    v = judge_v2(dict(title='карточка: «Миша — моё чудо»', category='graphics'), dict(do=[['карточка «Миша — моё чудо»']]), f, [20])
    assert v['status'] == 'unknown', v                      # вне окна ±120 с и цитата короче трёх значащих слов
    v = judge_v2(dict(title='Финал: деньги не последний звук', category='structure'), {}, f, [300])
    assert (v['status'], v['by'], v['evidence']['tc']) == ('open', 'rule', '5:20'), v
    v = judge_v2(dict(title='Цвет', category='color'), dict(now=[['«что-то»']]), f, [50])
    assert v['status'] == 'unknown' and v['evidence'] is None, v
    assert h['text'] == 'является выпускницей одного из детских домов', h   # дословное попадание — без хвоста соседних слов
    assert isinstance(f.dropped_sec, float)
    # 📋 список: всё на экране → закрыто; чего-то нет → осталось и названо; стояло и в прошлом кате → кодом не судим
    st = dict(title='Структура: карточки глав', category='structure')
    lst = dict(do=[['поставить карточки глав']], list=[['Главы (карточки)', '0:02 ▸ ОДНА С РЕБЁНКОМ', '3:00 ▸ МИША — МОЁ ЧУДО']])
    v = judge_v2(st, lst, f, [], project=lambda s: s + 15)
    assert v['status'] == 'closed' and v['evidence']['kind'] == 'screen' and [c['found'] for c in v['checks']] == [True, True], v
    bad = dict(lst, list=[lst['list'][0] + ['4:00 ▸ КАРТОЧКА КОТОРОЙ НЕТ НА ЭКРАНЕ']])
    v = judge_v2(st, bad, f, [], project=lambda s: s + 15)
    assert v['status'] == 'open' and 'нет: «КАРТОЧКА КОТОРОЙ' in v['evidence']['text'] and '2 из 3' in v['evidence']['text'], v
    f.prev_screens = [dict(t0=180.0, text='МИША МОЁ ЧУДО')]                  # 180 с базы → 200 с ката: карточка не новая
    v = judge_v2(st, lst, f, [], project=lambda s: s + 15)
    assert v['status'] == 'unknown' and v['evidence'] is None, v
    f.prev_screens = []
    # вырез: «закрыто» только на действительно выпавшем куске базы (108–118 с), а не по одному отсутствию реплики
    cut = dict(title='Вырезать про кредит', category='cut')
    gone = dict(now=[['звучит «совсем другой кусок про кредит на лекарства и переезд»']], do=[['вырезать']])
    v = judge_v2(cut, gone, f, [125], secs_old=[110])
    assert v['status'] == 'closed' and not re.search(r'\d:\d\d|align', v['evidence']['text']), v
    v = judge_v2(cut, gone, f, [60], secs_old=[50])
    assert v['status'] == 'unknown', v
    print('SELFTEST OK')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--old', default='', help='pravki прошлой версии (json со списком в ключе all)')
    ap.add_argument('--out', default='')
    ap.add_argument('--selftest', action='store_true', help='офлайн-проверка на синтетике, без карточки фильма')
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.old:
        ap.error('нужен --old <pravki прошлой версии.json>')
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'stages'))
    from _bootstrap import P, W6                           # карточка нужна только здесь

    old = json.load(open(a.old, encoding='utf-8'))
    items = old.get('all') if isinstance(old, dict) else old
    against = P.get('align_against') or ''
    against = against[0] if isinstance(against, list) and against else against
    f = Facts(W6, P.WORDS, P.resolve(against) if against else '')

    rows, tally = [], {}
    for i, it in enumerate(items, 1):
        v = judge(it, f)
        tally[v['status']] = tally.get(v['status'], 0) + 1
        rows.append(dict(n=i, tc=str(it.get('v1_tc') or it.get('tc_range') or ''),
                         category=it.get('category') or '', severity=it.get('severity') or '',
                         title=str(it.get('title') or ''), sensitive=bool(it.get('sensitive')),
                         status=v['status'], why=v['why'], sec=tc_start(it)))

    out = Path(a.out) if a.out else (W6 / "tz_diff.json")
    payload = dict(schema='tz-diff-v1', code=P.CODE, cut_version=P.CUT_VERSION, old_file=str(a.old),
                   total=len(rows), tally=tally, rows=rows,
                   align=dict(moved=f.moved, dropped_sec=f.dropped_sec))
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'сверка: {len(rows)} пунктов · ' + ' · '.join(f'{k} {v}' for k, v in sorted(tally.items())))
    print('→', out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
