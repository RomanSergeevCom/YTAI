#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""route_candidates — маршрутизация кандидатов-находок по экранам ката: auto_confirm | cloud | drop (0 токенов).

Детерминированные правила поверх локального разбора: что можно подтвердить кодом (опечатка с исправлением из
озвучки/каталога, формат валюты, символ элемента, контрольная цифра, канон канала) — подтверждаем сами; что
требует взгляда/рассуждения — в облако одним проходом (§7 contracts.md); вёрстка/вкус — никогда не кандидат.

Вход (всё через _bootstrap/P, без зашитых путей):
  W6/screens_v6.json   инвентарь экранов: lines_best (OCR hires, bbox 0..1), texts_all (OCR по секундам)
  W6/vlm_v6.jsonl      дословная VLM-транскрипция + описание графики
  W6/llm_v6.json       флаги Qwen3 — только как сигнал в signals[], маршрут по ним не решается
  W6/probes.jsonl      (если есть) зонды s3b_probe_vlm: чужие следы, обрезка, зум-перечитывание спорных слов
  P.WORDS              транскрипт озвучки с пословными таймкодами
  terms_catalog        TERMS / PLACES / CONFUSABLES / CANON_WORDS (профиль канала + фильм)
  профиль канала       latin_whitelist, rules_text
  P.MONT/pravki_v2.json      existing_tz (tc ±5 с + пересечение слов ≥0.5)
  P.MONT/channel_rules.json  (если есть) отклонённое Романом → drop
Выход: W6/candidates.json (список по contracts.md §6) + W6/candidates_summary.json; сводка ≤2 КБ в stdout.

usage:
  ~/YTAI/environment/.venv_llm/bin/python stages/route_candidates.py                 # прогон
  … route_candidates.py --eval <audit_findings_v6.json>                              # сверка со старым облачным аудитом
  … route_candidates.py --explain s031                                                # сигналы одного экрана
Без pymorphy3 (`.venv_llm/bin/pip install pymorphy3 pymorphy3-dicts-ru`) работает в урезанном режиме:
словарь = каталог + карточка + озвучка (предупреждение в stdout).

Язык (LANG = карточка lang → профиль lang → ru): ru — правила ниже без изменений; en — rule_typo_en (латиница,
pyspellchecker==0.9.0, фолбэк /usr/share/dict/web2), rule_language_en (кириллица/арабское письмо),
rule_currency_en (AED/Dh/dirham/$ ↔ озвучка), rule_fact/rule_mismatch/rule_foreign — общие; русские
rule_typo/rule_grammar/rule_language/rule_currency для en не запускаются. Экран в P.EXCLUSIONS → любой
кандидат drop «known_exclusion: <reason>» (оба языка).
"""
import argparse
import difflib
import json
import math
import os
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path

from _bootstrap import P, W6, M, T, LANG  # noqa: E402
import terms_catalog as TC  # noqa: E402

# ── пороги (все константы здесь) ───────────────────────────────────────────
TYPO_MIN_LEN = 4          # кириллический токен короче — не кандидат в опечатки
CORR_RATIO = 0.85         # SequenceMatcher.ratio() токен ↔ исправление
CORR_LEN_DIFF = 2         # |len(токен) − len(исправление)| ≤
AUTO_SAME_LEN = True      # auto_confirm опечатки — только при равной длине (замена/перестановка букв).
#   OCR путает НАЧЕРТАНИЯ (Й/И, Ч/Т, Ь/Ы, М/И) — длина при этом не меняется: «ИСТОРИТЕСКОЙ» → «ИСТОРИЧЕСКОЙ».
#   Вставка или удаление буквы значит, что словарь подобрал ДРУГОЕ слово, и на именах это стабильно врёт:
#   YTUVI01 v2 (21.09.2026) — «Пьин»→«Пьи», «Чаук»→«Чак», «Яунг»→«Янг» (топонимы карты Могока), «Моосу»→«Мосу»
#   (шкала Мооса), «РОБЕРТС»→«РОБЕРТАС», «БЕЗЕЛЬ»→«БЕНЗЕЛЬ», «КУЛЕТА»→«КУПЛЕТА» (огранка). Такие — в облако.
VO_PAD_TYPO = 90.0        # окно озвучки для поиска исправления, с
VO_PAD_MISMATCH = 8.0     # окно озвучки для чисел, с
VO_PAD_FACT = 8.0         # окно озвучки для символа элемента, с
LATIN_SHARE = 0.6         # доля латинских слов → «английский без перевода»
LATIN_MIN_DUR = 3         # … только если экран держится ≥ с
LATIN_BIGGER = 1.1        # латинская строка выше русской парной во столько раз → иерархия нарушена
WHITELIST_RATIO = 0.75    # нечёткое попадание в latin_whitelist (OCR-артефакты логотипа)
DUP_DIST = 0.1            # экраны с сигнатурой OCR ближе этого — одна группа
TZ_TC_PAD = 5             # existing_tz: таймкод ТЗ в [t0−5, t1+5]
TZ_WORD_OVERLAP = 0.5     # … и пересечение слов заголовка ≥
FEEDBACK_SIM = 0.8        # похожесть на отклонённое Романом → drop
MONEY_MLN = 1_000_000     # суммы от миллиона — только сокращением «МЛН»
CORNER = 0.12             # «угол» кадра для чужих следов (доля ширины/высоты)
TINY_H = 0.035            # мелкая строка в углу (доля высоты кадра) — чужой след
TINY_LINE_H = 0.02        # строка ниже ~22 px: OCR без второго чтения не верим (мелкий текст документов)
OCR_CONF_TRUST = 0.5      # строке OCR с меньшей уверенностью без второго чтения не верим
MAX_NUMBERS_TITLE = 4     # больше чисел на экране — это документ, а не титр (mismatch не считаем)
GEM_SG = 4.0              # плотность корунда для проверки «вес ↔ размеры»
GEM_SHAPE_K = 0.0020      # коэффициент формы (овал/подушка) для ct ≈ L·W·H·SG·K
WEIGHT_TOL = 2.0          # расхождение веса и оценки по размерам во столько раз → факт в облако
MATCH_SIM_KIND = 0.35     # --eval: похожесть текстов при совпавшем классе
MATCH_SIM_ANY = 0.6       # --eval: похожесть текстов при любом классе
# EN-ветка (LANG == 'en')
CAPS_ACRONYM_MAX = 5      # ALL-CAPS токен не длиннее — аббревиатура (RERA, DAMAC), не опечатка
SPELL_MAX_ED = 2          # исправление словарём — ближайший уровень правок, не дальше двух
VLM_READ_RATIO = 0.75     # VLM-токен считается чтением того же слова от такой похожести
MONEY_TOL = 0.02          # сумма экрана ≈ сумма озвучки (доля)
MONEY_MIX_WIN = 90.0      # одна сумма в разных валютах на экранах ближе стольких секунд — смешение валют

OUT = W6 / 'candidates.json'
OUT_SUMMARY = W6 / 'candidates_summary.json'

# ── словарь ────────────────────────────────────────────────────────────────
MORPH = None
if LANG != 'en':                                    # EN: русская морфология не нужна (словарь — pyspellchecker)
    try:
        import pymorphy3
        MORPH = pymorphy3.MorphAnalyzer()
    except Exception:                               # noqa: BLE001
        MORPH = None
        print('⚠️ pymorphy3 не установлен — словарь = каталог + карточка + озвучка '
              '(.venv_llm/bin/pip install pymorphy3 pymorphy3-dicts-ru)', flush=True)

CYR = 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'
_HOMO = {'a': 'а', 'c': 'с', 'e': 'е', 'o': 'о', 'p': 'р', 'x': 'х', 'y': 'у', 'k': 'к', 'm': 'м', 't': 'т',
         'h': 'н', 'b': 'в', 'i': 'и', 'ı': 'и', 'і': 'и', 'ï': 'и', 'j': 'й'}     # только настоящие двойники
_CONF = {'й': 'и', 'ё': 'е', 'щ': 'ш', 'ъ': 'ь'}
RX_TOKEN = re.compile(r'[^\W_]+', re.U)
RX_CYR_WORD = re.compile(r'[А-ЯЁа-яё]+')
RX_LAT_WORD = re.compile(r'[A-Za-zÀ-ÖØ-öø-ÿ]+')
RX_MIXED = re.compile(r'(?=[^\W\d_]*[А-ЯЁа-яё])(?=[^\W\d_]*[A-Za-z])[^\W\d_]+', re.U)


def is_cyr(s):
    return bool(RX_CYR_WORD.fullmatch(s))


def is_lat(s):
    return bool(RX_LAT_WORD.fullmatch(s))


def homo_to_cyr(s):
    """латинские двойники → кириллица (для слов, где есть хоть одна кириллическая буква)"""
    return ''.join(_HOMO.get(ch, ch) for ch in s.lower())


_HOMO_BACK = {v: k for k, v in _HOMO.items() if k in 'aceopxykmthbi'}


def sig(s):
    """сигнатура для сравнений: регистр, Й/И, Ё/Е, Щ/Ш, двойники (в сторону преобладающего алфавита),
    без пробелов/пунктуации"""
    s = s.lower()
    n_cyr = len(RX_CYR_WORD.findall(s) and ''.join(RX_CYR_WORD.findall(s)))
    n_lat = len(''.join(RX_LAT_WORD.findall(s)))
    if n_cyr >= n_lat and n_cyr:
        s = homo_to_cyr(s)
    elif n_lat:
        s = ''.join(_HOMO_BACK.get(ch, ch) for ch in s)
    s = ''.join(_CONF.get(ch, ch) for ch in s)
    return re.sub(r'[\W_]+', '', s)


def ratio(a, b):
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def tokens(text):
    return RX_TOKEN.findall(text or '')


def words_set(text, min_len=3):
    return {sig(t) for t in tokens(text) if len(t) >= min_len}


def case_like(fix, sample):
    if sample.isupper():
        return fix.upper()
    if sample[:1].isupper():
        return fix[:1].upper() + fix[1:]
    return fix


def tc(sec):
    return f'{int(sec) // 60}:{int(sec) % 60:02d}'


# ── данные фильма ──────────────────────────────────────────────────────────
def load_jsonl(path):
    out = {}
    if not Path(path).exists():
        return out
    for ln in open(path, encoding='utf-8'):
        try:
            r = json.loads(ln)
            out[r.get('id') or r.get('screen_id')] = r
        except Exception:                           # noqa: BLE001
            pass
    return out


SCREENS = json.load(open(W6 / 'screens_v6.json', encoding='utf-8'))
BY_ID = {e['id']: e for e in SCREENS}
VLM = load_jsonl(W6 / 'vlm_v6.jsonl')
PROBES = load_jsonl(W6 / 'probes.jsonl')
LLM = {}
if (W6 / 'llm_v6.json').exists():
    try:
        LLM = {r['id']: r for r in json.load(open(W6 / 'llm_v6.json', encoding='utf-8'))}
    except Exception:                               # noqa: BLE001
        LLM = {}

WORDS = []                                          # (слово, начало, конец, чистое-нижнее)
for _seg in json.load(open(P.WORDS, encoding='utf-8'))['segments']:
    for _w in _seg.get('words') or []:
        WORDS.append((_w['w'], float(_w['s']), float(_w['e']), re.sub(r'[^\w]', '', _w['w'].lower())))
VO_VOCAB = {w[3] for w in WORDS if w[3]}


def vo_words(t0, t1, pad):
    return [w for w in WORDS if t0 - pad <= w[1] <= t1 + pad]


def vo_text(t0, t1, pad):
    return ' '.join(w[0] for w in vo_words(t0, t1, pad))


# ── лексикон: каталог + карточка + белый список ────────────────────────────
def _catalog_words():
    out = set()
    for _k, _rx, title, sub, _d in TC.TERMS:
        out |= {t.lower() for t in tokens(title + ' ' + sub) if len(t) >= 3}
    for v in TC.TERM_EXTRA.values():
        for s in (v or {}).values():
            if isinstance(s, str):
                out |= {t.lower() for t in tokens(s) if len(t) >= 3}
    for p in TC.PLACES:
        for s in (p.get('ru'), p.get('old'), p.get('label'), p.get('sub')):
            if s:
                out |= {t.lower() for t in tokens(s) if len(t) >= 3}
    for s in TC.CANON_WORDS + list(P.get('canon_words', []) or []):
        out |= {t.lower() for t in tokens(s)}
    for k in ('ch_name', 'prog'):
        v = P.get(k, {}) or {}
        for x in v.values():
            s = json.dumps(x, ensure_ascii=False)
            out |= {t.lower() for t in tokens(s) if len(t) >= 3}
    for s in (P.get('sub', []) or []):
        out |= {t.lower() for t in tokens(json.dumps(s, ensure_ascii=False)) if len(t) >= 3}
    return out


CATALOG_WORDS = _catalog_words()
# стемы — только для слов каталога, которых нет в словаре (геммолог → геммологический); словарные слова
# стемить нельзя: «высок» из «ВЫСОКОЕ ЮВЕЛИРНОЕ» делал «ВЫСОКВАЯ» известным словом
CATALOG_STEMS = {w[:max(6, len(w) - 2)] for w in CATALOG_WORDS
                 if len(w) >= 7 and is_cyr(w) and (MORPH is None or not MORPH.word_is_known(w))}
LATIN_WHITELIST = [str(x) for x in (P.profile('latin_whitelist', []) or [])] + list(TC.CANON_WORDS)
_own_logo = P.profile('probe.own_logo', []) or []                              # профиль: probe.own_logo (строка или список)
OWN_LOGOS = LATIN_WHITELIST + [str(x) for x in ([_own_logo] if isinstance(_own_logo, str) else _own_logo)]
_EN_FORMS = set()
for _p in TC.PLACES:
    _EN_FORMS |= {t.lower() for e in (_p.get('en') or []) for t in tokens(e)}
for _v in TC.TERM_EXTRA.values():
    if isinstance(_v, dict) and isinstance(_v.get('en'), str):
        _EN_FORMS |= {t.lower() for t in tokens(_v['en'])}
CHEM_SYMBOLS = set()
for _k, _rx, _title, _sub, _d in TC.TERMS:
    CHEM_SYMBOLS |= set(re.findall(r'\(([A-Z][a-z]?)\)', _title + ' ' + _sub))
    for f in re.findall(r'\b(?:[A-Z][a-z]?[₀-₉\d]*){2,}\b', _sub):          # Al₂O₃ · MgAl₂O₄ · TiO₂
        CHEM_SYMBOLS |= set(re.findall(r'[A-Z][a-z]?', f))
    CHEM_SYMBOLS |= set(re.findall(r'\b([A-Z][a-z]?)\s*[·-]', _sub))          # «Fe · iron-rich»
CHEM_SYMBOLS -= {'I', 'A', 'O', 'V'} & {s for s in CHEM_SYMBOLS if len(s) == 1}   # однобуквенные легко спутать со словами
CHEM_ELEMENT_RX = {}                                                            # символ → rx русского имени из каталога
for _k, _rx, _title, _sub, _d in TC.TERMS:
    m = re.search(r'\(([A-Z][a-z]?)\)', _title)
    if m:
        CHEM_ELEMENT_RX[m.group(1)] = re.compile(_rx, re.I)


def whitelisted(tok):
    t = tok.lower()
    if t in _EN_FORMS:
        return True
    for w in LATIN_WHITELIST:
        wl = w.lower()
        if t == wl or (len(t) >= 3 and ratio(re.sub(r'[^a-z]', '', t), re.sub(r'[^a-z]', '', wl)) >= WHITELIST_RATIO):
            return True
    return False


def known(tok):
    """слово известно: pymorphy | каталог/карточка | озвучка (точная форма)"""
    t = tok.lower()
    if t in CATALOG_WORDS or t in VO_VOCAB:
        return True
    if any(t.startswith(st) for st in CATALOG_STEMS):
        return True
    if MORPH is not None and MORPH.word_is_known(t):
        return True
    return False


# ── EN: словарь, письменность, известность слова ───────────────────────────
RX_ARABIC = re.compile(r'[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]')
_CYR2LAT = {'А': 'A', 'В': 'B', 'Е': 'E', 'К': 'K', 'М': 'M', 'Н': 'H', 'О': 'O', 'Р': 'P', 'С': 'C', 'Т': 'T',
            'Х': 'X', 'У': 'Y', 'а': 'a', 'е': 'e', 'о': 'o', 'р': 'p', 'с': 'c', 'х': 'x', 'у': 'y', 'к': 'k',
            'і': 'i', 'ј': 'j', 'ѕ': 's'}                       # кириллица, неотличимая от латиницы
_CYR_HOMO = set(_CYR2LAT)
EN_UNIT_WORDS = {'sqft', 'sqm', 'bhk', 'psf', 'aed', 'dhs', 'usd', 'eur', 'gbp', 'kwh', 'roi', 'etc'}
# вывеска/улица/фото в описании VLM — текст реального мира, не титр; но «title/caption/overlay…» = графика монтажёра
RX_REAL_WORLD = re.compile(r'\b(photo|photograph|street|road|signs?|signage|signboard|storefront|shop\s?front|billboard|'
                           r'licen[cs]e plate|number plate|facade|real[- ]world)\b', re.I)
RX_EDITOR_GFX = re.compile(r'\b(title|titles|lower[- ]third|caption|captions|subtitles?|overlay|graphics?|infographic|'
                           r'chart|diagram|map|animated|animation|headline|text box|kinetic)\b', re.I)


def cyr_to_lat(s):
    return ''.join(_CYR2LAT.get(ch, ch) for ch in s)


def damerau(a, b):
    """расстояние правки с перестановкой соседних букв (OSA)"""
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


class EnDict:
    """EN-словарь: pyspellchecker==0.9.0 (импорт только в EN-ветке) → /usr/share/dict/web2 с предупреждением."""
    WEB2 = Path('/usr/share/dict/web2')
    _SUFFIXES = (("'s", ''), ('ies', 'y'), ('es', ''), ('s', ''), ('ed', ''), ('ed', 'e'), ('ing', ''), ('ing', 'e'),
                 ('ly', ''), ('er', ''), ('ers', ''))

    def __init__(self):
        self._near = {}
        self.sp, self.words = None, set()
        try:
            from spellchecker import SpellChecker
            self.sp = SpellChecker(language='en', distance=SPELL_MAX_ED)
            self.name = 'pyspellchecker'
        except Exception:                           # noqa: BLE001
            self.name = 'web2'
            if self.WEB2.exists():
                self.words = {w.strip().lower() for w in self.WEB2.read_text(encoding='utf-8', errors='ignore').splitlines()
                              if w.strip()}
            print('⚠️ pyspellchecker не установлен — EN-словарь = /usr/share/dict/web2 '
                  '(.venv_llm/bin/python -m pip install pyspellchecker==0.9.0)', flush=True)

    def known(self, w):
        w = w.lower()
        if self.sp is not None:
            return w in self.sp
        if w in self.words:
            return True
        return any(w.endswith(suf) and len(w) - len(suf) >= 3 and (w[:-len(suf)] + rep) in self.words
                   for suf, rep in self._SUFFIXES)

    @staticmethod
    def _edits1(w):
        letters = 'abcdefghijklmnopqrstuvwxyz'
        splits = [(w[:i], w[i:]) for i in range(len(w) + 1)]
        return ({a + b[1:] for a, b in splits if b} | {a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1}
                | {a + c + b[1:] for a, b in splits if b for c in letters} | {a + c + b for a, b in splits for c in letters})

    def nearest(self, w):
        """известные слова на ближайшем уровне правок (1, иначе 2), без самого слова; кэш по слову"""
        w = w.lower()
        if w not in self._near:
            if self.sp is not None:
                res = set(self.sp.candidates(w) or ())
            else:
                e1 = self._edits1(w)
                res = {x for x in e1 if x in self.words}
                if not res and len(w) <= 12:
                    res = {y for x in e1 for y in self._edits1(x) if y in self.words}
            self._near[w] = {x for x in res if x != w}
        return self._near[w]

    def correction(self, w):
        near = self.nearest(w)
        if not near:
            return None
        if self.sp is not None:
            return max(sorted(near), key=self.sp.word_usage_frequency)
        return min(near)


_EN_DICT = None


def en_dict():
    global _EN_DICT
    if _EN_DICT is None:
        _EN_DICT = EnDict()
    return _EN_DICT


EN_KNOWN_EXTRA = set()                              # EN: лексикон канала + карточка (фильм/гость) + озвучка + единицы
if LANG == 'en':
    for _s in list(P.LEXICON) + [str(P.get('film', '') or ''), str(P.get('film_subject', '') or ''), P.PROJECT_NAME]:
        EN_KNOWN_EXTRA |= {t.lower() for t in tokens(_s)}
    EN_KNOWN_EXTRA |= {t.lower() for _w in WORDS for t in tokens(_w[0])}
    EN_KNOWN_EXTRA |= EN_UNIT_WORDS


def known_en(tok):
    """EN: словарь EN | лексикон/латинский белый список профиля | карточка | каталог | озвучка (токены)"""
    t = tok.lower()
    return t in CATALOG_WORDS or t in EN_KNOWN_EXTRA or en_dict().known(t)


def real_world(sc):
    """описание VLM — фото/улица/вывеска и ни слова о графике монтажёра → текст реального мира"""
    d = sc.vlm_desc or ''
    return bool(RX_REAL_WORLD.search(d)) and not RX_EDITOR_GFX.search(d)


# ── исправления ────────────────────────────────────────────────────────────
def edit1_known(t):
    """словарные слова на расстоянии одной правки (удаление/вставка/замена/перестановка)"""
    if MORPH is None:
        return set()
    out = set()
    L = len(t)
    for i in range(L):                                        # удаление
        out.add(t[:i] + t[i + 1:])
    for i in range(L - 1):                                    # перестановка
        out.add(t[:i] + t[i + 1] + t[i] + t[i + 2:])
    for i in range(L + 1):                                    # вставка
        for ch in CYR:
            out.add(t[:i] + ch + t[i:])
    for i in range(L):                                        # замена
        for ch in CYR:
            if ch != t[i]:
                out.add(t[:i] + ch + t[i + 1:])
    return {w for w in out if len(w) >= 3 and MORPH.word_is_known(w)}


def find_correction(tok, t0, t1):
    """→ (исправление, источник, ratio, где) или None. Порядок предпочтения: озвучка → каталог → словарь."""
    t = tok.lower()
    best = None
    pools = [('vo', {w[3]: w[1] for w in vo_words(t0, t1, VO_PAD_TYPO) if len(w[3]) >= 3}),
             ('catalog', {w: None for w in CATALOG_WORDS if is_cyr(w)}),
             ('dict', {w: None for w in edit1_known(t)})]
    bonus = {'vo': 0.08, 'catalog': 0.04, 'dict': 0.0}       # озвучка — контекст фильма, словарь — последний
    for src, pool in pools:
        for w, where in pool.items():
            if w == t or abs(len(w) - len(t)) > CORR_LEN_DIFF:
                continue
            r = ratio(t, w)
            if r < CORR_RATIO:
                continue
            key = round(r + bonus[src], 3)
            if best is None or key > best[0]:
                best = (key, w, src, r, where)
    if best is None:
        return None
    _, w, src, r, where = best
    return (w, src, r, (f'{w} @{tc(where)}' if where is not None else w))


def glued(tok, t0, t1):
    """токен = склейка 2–3 подряд идущих слов озвучки → «слово слово»"""
    t = tok.lower()
    ws = [w[3] for w in vo_words(t0, t1, VO_PAD_TYPO) if w[3]]
    for i in range(len(ws) - 1):
        if ws[i] + ws[i + 1] == t:
            return ws[i] + ' ' + ws[i + 1]
        if i + 2 < len(ws) and ws[i] + ws[i + 1] + ws[i + 2] == t:
            return ' '.join(ws[i:i + 3])
    return None


# ── числа: экран и озвучка ─────────────────────────────────────────────────
_NUM_WORDS = {'ноль': 0, 'один': 1, 'одна': 1, 'одно': 1, 'одного': 1, 'одной': 1, 'два': 2, 'две': 2, 'двух': 2,
              'три': 3, 'трёх': 3, 'трех': 3, 'четыре': 4, 'четырёх': 4, 'четырех': 4, 'пять': 5, 'пяти': 5,
              'шесть': 6, 'шести': 6, 'семь': 7, 'семи': 7, 'восемь': 8, 'восьми': 8, 'девять': 9, 'девяти': 9,
              'десять': 10, 'десяти': 10, 'одиннадцать': 11, 'двенадцать': 12, 'тринадцать': 13, 'четырнадцать': 14,
              'пятнадцать': 15, 'шестнадцать': 16, 'семнадцать': 17, 'восемнадцать': 18, 'девятнадцать': 19,
              'двадцать': 20, 'двадцати': 20, 'тридцать': 30, 'тридцати': 30, 'сорок': 40, 'сорока': 40,
              'пятьдесят': 50, 'пятидесяти': 50, 'шестьдесят': 60, 'семьдесят': 70, 'восемьдесят': 80,
              'девяносто': 90, 'сто': 100, 'ста': 100, 'двести': 200, 'двухсот': 200, 'триста': 300, 'трёхсот': 300,
              'четыреста': 400, 'пятьсот': 500, 'пятисот': 500, 'шестьсот': 600, 'семьсот': 700, 'восемьсот': 800,
              'девятьсот': 900}
_MULT = {'тысяч': 1e3, 'миллион': 1e6, 'миллиард': 1e9}
_MAGN = {'десятк': (10, 99), 'сотн': (100, 999), 'сотен': (100, 999), 'тысяч': (1000, 9999), 'миллион': (1e6, 9.99e6)}


def _num_tok(w):
    """слово озвучки → ('n', v) число | ('m', mult) множитель | ('r', (lo,hi)) порядок | None"""
    raw = w[0]
    if re.fullmatch(r'[.,]\d+[.,]?', raw.strip()):           # ASR: «0» «,2» → дробная часть (до срезания пунктуации)
        return ('frac', float('0' + raw.strip().rstrip('.,').replace(',', '.')))
    s = raw.lower().strip('.,;:!?()«»"–—-')
    if re.fullmatch(r'\d+(?:[.,]\d+)?', s):
        return ('n', float(s.replace(',', '.')))
    if s in _NUM_WORDS:
        return ('n', float(_NUM_WORDS[s]))
    for k, v in _MULT.items():
        if s.startswith(k):
            return ('m', v)
    for k, v in _MAGN.items():
        if s.startswith(k):
            return ('r', v)
    return None


def vo_numbers(t0, t1, pad=VO_PAD_MISMATCH):
    """→ (значения, порядки [(lo,hi)], множители «в N раз» [(lo,hi)]) из окна озвучки"""
    ws = vo_words(t0, t1, pad)
    toks = [(_num_tok(w), w[3]) for w in ws]
    vals, ranges, factors = set(), [], []
    runs, cur = [], []
    for i, (nt, low) in enumerate(toks):
        if nt is None:
            if cur:
                runs.append(cur)
            cur = []
            continue
        cur.append((i, nt))
    if cur:
        runs.append(cur)
    for run in runs:
        items = [nt for _i, nt in run]
        # склейка «0» «,2» → 0.2
        merged = []
        for nt in items:
            if nt[0] == 'frac' and merged and merged[-1][0] == 'n':
                merged[-1] = ('n', merged[-1][1] + nt[1])
            elif nt[0] != 'frac':
                merged.append(nt)
        for a in range(len(merged)):
            for b in range(a, len(merged)):
                sub = merged[a:b + 1]
                if sub[0][0] == 'm':
                    continue
                if all(x[0] == 'r' for x in sub) and len(sub) == 1:
                    continue
                acc, part, ok = 0.0, 0.0, True
                for kind, v in sub:
                    if kind == 'n':
                        part += v
                    elif kind == 'm':
                        acc += (part or 1.0) * v
                        part = 0.0
                    else:
                        ok = False
                if ok:
                    vals.add(acc + part)
        i0 = run[0][0]
        for j, (kind, v) in enumerate(items):
            if kind == 'r':
                prev_n = j > 0 and items[j - 1][0] == 'n'
                nxt = toks[i0 + j + 1][1] if i0 + j + 1 < len(toks) else ''
                prev = toks[i0 + j - 1][1] if i0 + j - 1 >= 0 else ''
                if nxt.startswith('раз'):
                    factors.append(v)
                elif not prev_n:
                    ranges.append(v)
                    if prev == 'несколько':
                        ranges[-1] = (v[0] * 2, v[1])
    # «в 10 раз» / «в тысячу раз» с числом
    for i, (nt, low) in enumerate(toks):
        if nt and nt[0] == 'n' and i + 1 < len(toks) and toks[i + 1][1].startswith('раз'):
            factors.append((nt[1], nt[1]))
    return vals, ranges, factors


RX_SCREEN_NUM = re.compile(r'(?<![\w.,])[$€]?\s?\d{1,3}(?:[\s  ]\d{3})+(?![\d])|(?<![\w.,/-])\d+(?:[.,]\d+)?(?![\d/])')


def screen_numbers(text):
    """числа на экране: (значение, как написано); одиночные цифры без знака валюты/единицы не считаем (шаги, шкалы)"""
    out = []
    for m in RX_SCREEN_NUM.finditer(text):
        raw = m.group(0)
        s = re.sub(r'[\s  $€]', '', raw)
        try:
            v = float(s.replace(',', '.'))
        except ValueError:
            continue
        after = text[m.end():m.end() + 6].lower()
        has_unit = bool(re.match(r'\s?(ct|cts|кар|г\b|мм|mm|нм|%|°|k\b|к\b)', after)) or '$' in raw or '€' in raw
        if v < 10 and float(v).is_integer() and not has_unit:
            continue
        if re.fullmatch(r'0\d', s):                             # «01», «06» — номер шага
            continue
        out.append((v, raw.strip()))
    return out


# ── экран: разбор ──────────────────────────────────────────────────────────
class Screen:
    def __init__(self, idx):
        e = SCREENS[idx]
        self.idx, self.e = idx, e
        self.id, self.t0, self.t1, self.dur = e['id'], e['t0'], e['t1'], e['dur']
        self.lines = e['lines_best']
        self.ocr_text = e['text_best']
        v = VLM.get(self.id, {})
        self.vlm_text = (v.get('vlm_text') or '').strip()
        self.vlm_desc = (v.get('vlm_desc') or '').strip()
        self.vlm_notext = self.vlm_text.upper().startswith('NO TEXT') or not self.vlm_text
        self.vlm_tokens = tokens(self.vlm_text)
        self.probe = PROBES.get(self.id) or {}
        self.llm = LLM.get(self.id) or {}
        self.all_tokens = {t for txt in [self.ocr_text] + e['texts_all'] for t in tokens(txt)}
        self.all_tokens |= set(self.vlm_tokens)
        # соседние экраны (допечатка титра часто режется s2 на два события)
        self.neigh_tokens = set()
        for j in (idx - 1, idx + 1):
            if 0 <= j < len(SCREENS) and min(abs(SCREENS[j]['t0'] - self.t1), abs(self.t0 - SCREENS[j]['t1'])) <= 3:
                n = SCREENS[j]
                self.neigh_tokens |= {t for txt in [n['text_best']] + n['texts_all'] for t in tokens(txt)}
                self.neigh_tokens |= set(tokens((VLM.get(n['id']) or {}).get('vlm_text') or ''))
        self.sec_count = len(e['texts_all'])
        self.typing_of = None                     # id соседа, для которого этот экран — недопечатанный титр
        self.is_typing_prefix()

    def vlm_split_of(self, work):
        """OCR склеил два соседних слова VLM-транскрипции → «слово слово» (иначе None)"""
        vt = [t.lower() for t in self.vlm_tokens]
        w = work.lower()
        for i in range(len(vt) - 1):
            if vt[i] + vt[i + 1] == w:
                return vt[i] + ' ' + vt[i + 1]
        return None

    def vlm_longer_known(self, work):
        """VLM читает длинное словарное слово с тем же началом (≥5 букв) → OCR обрезал (голова/анимация)"""
        w = work.lower()
        for v in self.vlm_tokens:
            vl = v.lower()
            if len(vl) > len(w) and len(w) >= 5 and vl.startswith(w[:5]) and known(vl):
                common = 0
                for a, b in zip(vl, w):
                    if a != b:
                        break
                    common += 1
                if common >= max(5, len(w) - 2):
                    return v
        return None

    def stable(self, tok):
        """в скольких секундах экрана OCR видел токен"""
        return sum(1 for txt in self.e['texts_all'] if tok in tokens(txt))

    def is_typing_prefix(self):
        """весь экран — недопечатанный титр: короткий, и его текст/слова — СТРОГИЕ префиксы соседа
        (равные слова не в счёт: тот же титр секундой раньше — не анимация, его кандидаты сольёт дедуп)"""
        if self.typing_of:
            return True
        if self.dur > 2:
            return False
        own = [t for t in tokens(self.ocr_text) if len(t) >= 3]
        if not own:
            return False
        s_own = sig(self.ocr_text)
        for j in (self.idx - 1, self.idx + 1):
            if not (0 <= j < len(SCREENS)) or min(abs(SCREENS[j]['t0'] - self.t1), abs(self.t0 - SCREENS[j]['t1'])) > 3:
                continue
            n = SCREENS[j]
            neigh_texts = [n['text_best']] + n['texts_all'] + [(VLM.get(n['id']) or {}).get('vlm_text') or '']
            if len(s_own) >= 5 and any(sig(t).startswith(s_own) and len(sig(t)) > len(s_own) for t in neigh_texts):
                self.typing_of = n['id']
                return True
            nb = {t.lower() for txt in neigh_texts for t in tokens(txt)}
            strict = sum(1 for t in own if any(w.startswith(t.lower()) and len(w) > len(t) for w in nb))
            if strict >= 1 and strict >= max(1, int(len(own) * 0.6 + 0.5)):
                self.typing_of = n['id']
                return True
        return False

    def vlm_match(self, tok):
        best, br = None, 0.0
        for v in self.vlm_tokens:
            r = ratio(tok.lower(), v.lower())
            if r > br:
                best, br = v, r
        return best, br

    def zoom(self, line_idx, tok):
        for z in self.probe.get('zoom') or []:
            if z.get('line_idx') == line_idx and (z.get('token') or '').lower() == tok.lower():
                return z
        return None


# ── кандидаты ──────────────────────────────────────────────────────────────
def cand(sc, kind, text, line_idx, fix, signals, route, reason, need_frame=False, **extra):
    """scope: 'token' (слово/строка с line_idx) | 'screen' (решение про экран целиком — язык, документ, озвучка)"""
    d = OrderedDict(cand_id='', screen_id=sc.id, tc=sc.e['tc'], t0=sc.t0, t1=sc.t1, kind=kind,
                    on_screen_text=text, line_idx=line_idx, fix_local=fix, signals=list(signals),
                    route=route, route_reason=reason, need_frame=bool(need_frame), existing_tz=None,
                    scope='screen' if line_idx == -1 else 'token')
    d.update(extra)
    return d


def rule_typo(sc):
    out = []
    if sc.vlm_notext and all(l['c'] < OCR_CONF_TRUST for l in sc.lines):
        out.append(cand(sc, 'typo', sc.ocr_text[:60], -1, '', ['vlm:NO TEXT', 'ocr_conf<0.5'], 'drop',
                        'OCR-шум на кадре без текста (VLM: NO TEXT)', drop_class='ocr_noise'))
        return out
    if sc.is_typing_prefix():
        out.append(cand(sc, 'typo', sc.ocr_text[:60], -1, '', ['typing_prefix', f'same_title_as:{sc.typing_of}'], 'drop',
                        f'недопечатанный титр: текст — префикс экрана {sc.typing_of} (его кандидаты покрывают этот экран)',
                        drop_class='typing_anim'))
        return out
    seen = set()
    for li, line in enumerate(sc.lines):
        text = line['t']
        for tok in tokens(text):
            if len(tok) < TYPO_MIN_LEN or tok.lower() in seen or re.search(r'\d', tok):
                continue
            mixed = bool(RX_MIXED.fullmatch(tok))
            if not (is_cyr(tok) or mixed):
                continue
            seen.add(tok.lower())
            sigs = [f'conf:{line["c"]}']
            work = tok
            if mixed:
                work = homo_to_cyr(tok)
                if not is_cyr(work):
                    continue
                sigs.append('homoglyph_mix')
                if known(work):
                    vt, vr = sc.vlm_match(work)
                    if vt and sig(vt) == sig(work):
                        out.append(cand(sc, 'typo', tok, li, case_like(work, tok), sigs + ['vlm=cyr'], 'drop',
                                        'латиница внутри слова — артефакт OCR, VLM читает кириллицу',
                                        drop_class='ocr_artifact', zoom_wanted=line['c'] >= OCR_CONF_TRUST))
                    else:
                        out.append(cand(sc, 'typo', tok, li, case_like(work, tok), sigs + ['vlm≠'], 'cloud',
                                        'смешанный алфавит внутри слова, VLM не подтверждает кириллицу',
                                        need_frame=True, zoom_wanted=True))
                    continue
            # канон канала (confusables) — раньше словаря: «дуплет» словарное слово, но у камней — «дублет»
            conf_hit = next(((w, r) for w, r in TC.CONFUSABLES if work.lower().startswith(w)), None)
            if conf_hit:
                wrong, right = conf_hit
                fx = case_like(right + work.lower()[len(wrong):], tok)
                vt, vr = sc.vlm_match(work)
                sigs += [f'confusable:{wrong}→{right}', 'ocr=vlm' if vt and vt.lower() == work.lower() else f'vlm:{vt}']
                out.append(cand(sc, 'typo', tok, li, fx, sigs, 'auto_confirm',
                                f'канон канала: «{wrong}» → «{right}»', zoom_wanted=False))
                continue
            if known(work):
                continue
            # префикс известного слова, полное слово есть в другой секунде/соседнем экране → допечатка
            pool = {t.lower() for t in sc.all_tokens | sc.neigh_tokens}
            full = [w for w in pool if w.startswith(work.lower()) and len(w) > len(work) and known(w)]
            if full:
                out.append(cand(sc, 'typo', tok, li, '', sigs + [f'prefix_of:{full[0]}'], 'drop',
                                'анимация допечатки: префикс слова, полное слово есть рядом', drop_class='typing_anim'))
                continue
            sigs.append('unknown:' + ('pymorphy' if MORPH else 'lexicon'))
            st = sc.stable(tok)
            sigs.append(f'stable:{st}/{sc.sec_count}s')
            # чтения: OCR ↔ VLM ↔ зум
            vt, vr = sc.vlm_match(work)
            corr = find_correction(work, sc.t0, sc.t1)
            gl = glued(work, sc.t0, sc.t1)
            fix = case_like(corr[0], tok) if corr else ''
            if corr:
                sigs.append(f'{corr[1]}_match:{corr[2]:.2f} ({corr[3]})')
            z = sc.zoom(li, tok)
            readings = {'ocr': work.lower(), 'vlm': (vt or '').lower() if vr >= 0.75 else ''}
            if z:
                readings['zoom_vlm'] = (z.get('vlm') or '').lower()
                readings['zoom_ocr'] = (z.get('ocr') or '').lower()
            agree = [k for k, v in readings.items() if v and v == work.lower()]           # точное совпадение чтений
            confirm_fix = [k for k, v in readings.items() if v and corr and v == corr[0]]
            other = [k for k, v in readings.items() if v and k not in agree and k not in confirm_fix]
            sigs.append('=' .join(agree) if len(agree) > 1 else 'ocr_only')
            if confirm_fix:
                sigs.append('reads_fix:' + ','.join(confirm_fix))
            if other:
                sigs.append('reads_other:' + ','.join(f'{k}={readings[k]}' for k in other))
            zoom_wanted = z is None
            # ── маршрут ──
            split = sc.vlm_split_of(work)
            if split and not gl:
                out.append(cand(sc, 'typo', tok, li, case_like(split, tok), sigs + ['vlm_split'], 'drop',
                                'OCR склеил два слова, VLM читает их раздельно — артефакт', drop_class='ocr_artifact',
                                zoom_wanted=True))
                continue
            longer = sc.vlm_longer_known(work)
            if longer and not corr and not gl:
                out.append(cand(sc, 'typo', tok, li, case_like(longer, tok), sigs + [f'ocr_truncated:{longer}'], 'drop',
                                'OCR оборвал слово (голова ведущей/анимация), VLM читает целиком', drop_class='ocr_truncated',
                                zoom_wanted=True))
                continue
            if gl:
                # VLM читает те же слова раздельно → OCR склеил их сам (широкий трекинг) — артефакт
                split_rx = r'\b' + re.escape(gl.split()[0]) + r'\s+' + re.escape(gl.split()[-1]) + r'\b'
                if re.search(split_rx, sc.vlm_text, flags=re.I):
                    out.append(cand(sc, 'typo', tok, li, case_like(gl, tok), sigs + ['glued_vo', 'vlm_split'], 'drop',
                                    'OCR склеил слова, VLM читает их раздельно — артефакт', drop_class='ocr_artifact',
                                    zoom_wanted=True))
                else:
                    out.append(cand(sc, 'typo', tok, li, case_like(gl, tok), sigs + ['glued_vo'], 'cloud',
                                    'слово = склейка слов озвучки — проверить пробел/наезд титров',
                                    need_frame=True, zoom_wanted=zoom_wanted))
                continue
            if True:                                      # ветка «чтения разошлись / согласны»
                if len(agree) == 1 and readings.get('vlm') and readings['vlm'] != work.lower():
                    # VLM прочёл иначе
                    if sig(readings['vlm']) == sig(work) and known(readings['vlm']):
                        # отличие только Й/И, Ё/Е, Щ/Ш, двойники — классическая путаница OCR; решает зум
                        zo = readings.get('zoom_ocr', '')
                        if z and zo == work.lower():
                            out.append(cand(sc, 'typo', tok, li, case_like(readings['vlm'], tok), sigs + ['confusable_vs_vlm', 'zoom=ocr'],
                                            'cloud', 'зум подтверждает чтение OCR, VLM читает словарную форму (Й/И, Ё/Е, Щ/Ш) — нужен кадр',
                                            need_frame=True, zoom_wanted=False))
                        else:
                            out.append(cand(sc, 'typo', tok, li, case_like(readings['vlm'], tok), sigs + ['confusable_vs_vlm'], 'drop',
                                            'OCR путает Й/И, Ё/Е, Щ/Ш, двойники; VLM читает словарное слово' + (' (зум согласен с VLM)' if z else ''),
                                            drop_class='ocr_confusable', zoom_wanted=z is None))
                        continue
                    if corr and readings['vlm'] == corr[0]:
                        if z and sig(readings.get('zoom_ocr', '')) == sig(work) and sig(readings.get('zoom_vlm', '')) == sig(work):
                            out.append(cand(sc, 'typo', tok, li, fix, sigs + ['vlm_autocorrect', 'zoom=ocr'], 'auto_confirm',
                                            'зум подтвердил чтение OCR, VLM в полном кадре «починил» слово; исправление из '
                                            + corr[1], zoom_wanted=False))
                        elif z and (sig(readings.get('zoom_ocr', '')) == sig(corr[0]) or
                                    (sig(readings.get('zoom_vlm', '')) == sig(corr[0]) and sig(readings.get('zoom_ocr', '')) != sig(work))):
                            # зум читает словарную форму (или OCR в зуме дал третий вариант) — OCR тут не источник
                            out.append(cand(sc, 'typo', tok, li, fix, sigs + ['vlm_autocorrect', 'zoom=vlm'], 'drop',
                                            'зум читает правильную форму, чтения OCR расходятся между собой — артефакт OCR',
                                            drop_class='ocr_artifact', zoom_wanted=False))
                        else:
                            out.append(cand(sc, 'typo', tok, li, fix, sigs + ['vlm_autocorrect'], 'cloud',
                                            'OCR и VLM разошлись на одну правку (VLM мог «починить» слово) — нужен кадр',
                                            need_frame=True, zoom_wanted=zoom_wanted))
                    elif known(readings['vlm']) and ratio(readings['vlm'], work.lower()) >= 0.75:
                        if z and sig(readings.get('zoom_ocr', '')) == sig(work):
                            out.append(cand(sc, 'typo', tok, li, fix or case_like(readings['vlm'], tok), sigs + ['zoom=ocr'],
                                            'cloud', 'зум подтверждает OCR, VLM читает словарное слово — нужен кадр',
                                            need_frame=True, zoom_wanted=False))
                        elif line['c'] < OCR_CONF_TRUST or sig(readings['vlm']) == sig(work):
                            out.append(cand(sc, 'typo', tok, li, case_like(readings['vlm'], tok), sigs + ['vlm_known'], 'drop',
                                            'артефакт OCR: VLM читает словарное слово' + (' (Й/И, Ё/Е, Щ/Ш)' if sig(readings['vlm']) == sig(work) else ''),
                                            drop_class='ocr_artifact', zoom_wanted=zoom_wanted))
                        else:
                            out.append(cand(sc, 'typo', tok, li, case_like(readings['vlm'], tok), sigs + ['vlm_known'], 'cloud',
                                            'OCR (уверенно) и VLM читают по-разному — нужен кадр', need_frame=True,
                                            zoom_wanted=zoom_wanted))
                    else:
                        out.append(cand(sc, 'typo', tok, li, fix, sigs + ['both_unknown'], 'cloud',
                                        'OCR и VLM читают по-разному, оба варианта вне словаря — нужен кадр',
                                        need_frame=True, zoom_wanted=zoom_wanted))
                    continue
                if not readings.get('vlm') and not z:
                    if line['c'] < OCR_CONF_TRUST or line['bh'] < TINY_LINE_H:
                        out.append(cand(sc, 'typo', tok, li, fix, sigs + ['vlm_missing', f'line_h:{line["bh"]:.3f}'], 'drop',
                                        'VLM не видит строки, OCR неуверен или строка мелкая — решает зум',
                                        drop_class='ocr_artifact', zoom_wanted=True))
                    else:
                        out.append(cand(sc, 'typo', tok, li, fix, sigs + ['vlm_missing'], 'cloud',
                                        'VLM не видит строки — единственное чтение OCR' + (', исправление найдено' if corr else ''),
                                        need_frame=True, zoom_wanted=True))
                    continue
                # зум есть, но ни одно его чтение не совпало с OCR → OCR полного кадра тут не источник
                if z and 'zoom_vlm' not in agree and 'zoom_ocr' not in agree:
                    zv = readings.get('zoom_vlm', '')
                    if zv and known(zv):
                        out.append(cand(sc, 'typo', tok, li, case_like(zv, tok), sigs + ['zoom_contradicts_ocr'], 'drop',
                                        'зум читает словарное слово, OCR полного кадра не подтверждён', drop_class='ocr_artifact',
                                        zoom_wanted=False))
                    else:
                        out.append(cand(sc, 'typo', tok, li, fix, sigs + ['zoom_contradicts_ocr'], 'cloud',
                                        'три чтения разошлись, ни одно не словарное — решить по кадру', need_frame=True,
                                        zoom_wanted=False))
                    continue
                # чтения согласны (OCR=VLM или зум подтвердил)
                if corr and sig(corr[0]) == sig(work) and corr[0] != work.lower():
                    out.append(cand(sc, 'typo', tok, li, fix, sigs + ['diff_confusable_only'], 'cloud',
                                    'отличие от исправления только в Й/И, Ё/Е, Щ/Ш или двойниках — OCR тут ненадёжен',
                                    need_frame=True, zoom_wanted=zoom_wanted))
                elif corr and len(agree) >= 2:
                    src = 'озвучки' if corr[1] == 'vo' else corr[1]
                    if AUTO_SAME_LEN and len(corr[0]) != len(work):
                        out.append(cand(sc, 'typo', tok, li, fix, sigs + [f'len_diff:{len(work)}→{len(corr[0])}'], 'cloud',
                                        f'чтения совпали, но исправление из {src} другой длины — словарь мог подобрать '
                                        f'другое слово (имена, топонимы, термины огранки); решить по кадру',
                                        need_frame=True, zoom_wanted=zoom_wanted))
                    else:
                        out.append(cand(sc, 'typo', tok, li, fix, sigs, 'auto_confirm',
                                        f'чтения совпали ({"=".join(agree)}), исправление из {src}',
                                        zoom_wanted=False))
                elif corr:
                    out.append(cand(sc, 'typo', tok, li, fix, sigs, 'cloud',
                                    'исправление найдено, но второго чтения нет', need_frame=True, zoom_wanted=zoom_wanted))
                else:
                    out.append(cand(sc, 'typo', tok, li, '', sigs + ['no_correction'], 'cloud',
                                    'слово вне словаря без исправления — решить по кадру', need_frame=True,
                                    zoom_wanted=zoom_wanted))
    # единицы/регистр в капс-титрах — не опечатка
    for li, line in enumerate(sc.lines):
        if line['t'].upper() == line['t'] and re.search(r'\d\s?(НМ|ММ|СМ|КГ|МГ|МЛ|КМ|CT|MM|CM|KG)\b', line['t']):
            out.append(cand(sc, 'typo', line['t'], li, '', ['units_caps'], 'drop',
                            'единица измерения в капс-титре — регистр не ошибка', drop_class='units_caps'))
    return out


def rule_grammar(sc):
    out = []
    srcs = [(li, l['t']) for li, l in enumerate(sc.lines)] + [(-1, ln) for ln in sc.vlm_text.split('\n')]
    seen = set()
    for li, text in srcs:
        if not text.strip():
            continue
        # тире внутри слова
        for m in re.finditer(r'([А-Яа-яё]+)\s?[–—]\s?([а-яё]+)', text):
            if m.group(2) in ('то', 'нибудь', 'либо', 'ка', 'таки') or (len(m.group(1)) <= 4 and len(m.group(2)) <= 4):
                key = ('dash', sig(m.group(0)))
                if key in seen:
                    continue
                seen.add(key)
                out.append(cand(sc, 'grammar', m.group(0), li, f'{m.group(1)}-{m.group(2)}', ['en_dash_in_word'],
                                'auto_confirm', 'тире внутри слова вместо дефиса'))
        # аббревиатура + слово без дефиса: «УФ свете» → «УФ-свете»
        for m in re.finditer(r'(?<![\w-])(УФ|ИК|СВЧ|ВЧ|УЗ|ЖК|LED|3D)\s+(свет\w*|луч\w*|излучен\w*|лампа\w*|лампе\w*|фонар\w*|спектр\w*|фильтр\w*|област\w*|диапазон\w*|подсветк\w*|детектор\w*)',
                             text, flags=re.I):
            key = ('abbr', sig(m.group(0)))
            if key in seen:
                continue
            seen.add(key)
            fix = f'{m.group(1).upper()}-{m.group(2)}'
            out.append(cand(sc, 'grammar', m.group(0), li, fix, ['abbr_no_hyphen'], 'auto_confirm',
                            'аббревиатура + слово пишутся через дефис'))
        # -то/-нибудь/-либо без дефиса; «из за», «все таки»
        for m in re.finditer(r'\b(как|что|кто|где|когда|какой|какие|какая|какое|куда|откуда|почему|чей|сколько|кого|чего)\s+(то|нибудь|либо)\b',
                             text, flags=re.I):
            key = ('hyph', sig(m.group(0)))
            if key in seen:
                continue
            seen.add(key)
            out.append(cand(sc, 'grammar', m.group(0), li, f'{m.group(1)}-{m.group(2)}', ['missing_hyphen'],
                            'auto_confirm', 'частица -то/-нибудь/-либо пишется через дефис'))
        for m in re.finditer(r'\b(из)\s+(за)\b|\b(вс[её])\s+(таки)\b', text, flags=re.I):
            key = ('hyph2', sig(m.group(0)))
            if key in seen:
                continue
            seen.add(key)
            parts = [g for g in m.groups() if g]
            out.append(cand(sc, 'grammar', m.group(0), li, '-'.join(parts), ['missing_hyphen'], 'auto_confirm',
                            'пишется через дефис'))
        # слитно/раздельно — спорные пары → облако с локальным исправлением
        for m in re.finditer(r'\b(на)\s+(сколько)\b(?=\s+(?:он|она|оно|они|это|важно|сильно|хорошо|плохо|дорого|дёшево|дешево)\b)',
                             text, flags=re.I):
            key = ('naskolko', sig(m.group(0)))
            if key in seen:
                continue
            seen.add(key)
            out.append(cand(sc, 'grammar', text, li, text.replace(m.group(0), m.group(1) + m.group(2)), ['split_adverb'],
                            'cloud', 'наречие меры «насколько» пишется слитно (раздельно — только «на сколько дней»)'))
    # форма глагола расходится с озвучкой: инфинитив в титре, императив в речи (пункты списка)
    if MORPH is not None:
        vo = vo_words(sc.t0, sc.t1, VO_PAD_MISMATCH)
        vo_lemmas = {}
        for w in vo:
            if len(w[3]) < 4:
                continue
            p = MORPH.parse(w[3])[0]
            if p.tag.POS == 'VERB' and 'impr' in p.tag:
                vo_lemmas.setdefault(p.normal_form, w[3])
        for li, l in enumerate(sc.lines):
            first = tokens(l['t'])
            if not first or not is_cyr(first[0]) or len(first[0]) < 4:
                continue
            p = MORPH.parse(first[0].lower())[0]
            if p.tag.POS == 'INFN' and p.normal_form in vo_lemmas:
                imp = vo_lemmas[p.normal_form]
                out.append(cand(sc, 'grammar', l['t'], li, l['t'].replace(first[0], case_like(imp, first[0]), 1),
                                [f'verb_form_vs_vo:{first[0]}↔{imp}'], 'cloud',
                                'титр в инфинитиве, озвучка — в повелительном наклонении (единообразие пунктов)'))
    return out


RX_MONEY = re.compile(r'[$€₽]|\bUSD\b|\bРУБ\b', re.I)


def rule_currency(all_screens):
    """одна находка на весь фильм: список всех денежных экранов + нарушения канона"""
    money, viol = [], []
    for sc in all_screens:
        for li, l in enumerate(sc.lines):
            t = l['t']
            if not RX_MONEY.search(t) and not re.search(r'\d{1,3}(?:[\s  ]\d{3}){2,}', t):
                continue
            if re.search(r'\+\d[\d\s-]{8,}\d', t) and not RX_MONEY.search(t):     # телефон, не сумма
                continue
            money.append(f'{sc.id} {sc.e["tc"]} «{t[:60]}»')
            m1 = re.search(r'[$€]\s+\d', t)
            m2 = re.search(r'\d\s*[$€]', t)
            big = [m for m in re.finditer(r'(?<!\d)(\d{1,3}(?:[\s  ]\d{3}){2,})(?!\d)', t)]
            vo = vo_text(sc.t0, sc.t1, VO_PAD_MISMATCH).lower()
            for m in big:
                v = int(re.sub(r'\D', '', m.group(1)))
                if v >= MONEY_MLN and not re.search(r'МЛН|МЛРД|ТЫС', t, re.I):
                    if RX_MONEY.search(t) or re.search(r'доллар|рубл|евро', vo):
                        mln = v / MONEY_MLN
                        num = (f'{mln:.1f}'.replace('.', ',')).replace(',0', '')
                        sign = '$' if '$' in t or 'доллар' in vo else ('€' if '€' in t or 'евро' in vo else '')
                        viol.append((sc, li, t, f'{sign}{num} МЛН', 'sum_ge_1M_no_MLN'))
                        continue
                    if re.search(r'доллар|рубл|евро|тысяч|миллион', vo) is None:
                        continue
            if m1:
                fix = re.sub(r'([$€])\s+', r'\1', t)
                v = re.sub(r'\D', '', fix)
                if v and int(v) >= MONEY_MLN and not re.search(r'МЛН|МЛРД|ТЫС', t, re.I):
                    mln = int(v) / MONEY_MLN
                    fix = f'{fix[0]}{(f"{mln:.1f}".replace(".", ",")).replace(",0", "")} МЛН'
                if not any(x[0] is sc and x[1] == li for x in viol):
                    viol.append((sc, li, t, fix, 'space_after_sign'))
                else:
                    viol[-1] = (sc, li, t, fix, viol[-1][4] + '+space_after_sign')
            elif m2:
                fix = re.sub(r'(\d)\s*([$€])', r'\2\1', t)
                viol.append((sc, li, t, fix, 'sign_after_number'))
    out = []
    if not viol:
        # только маленькие суммы — фиксируем drop для трассируемости
        for sc in all_screens:
            for li, l in enumerate(sc.lines):
                if re.search(r'[$€]\s?\d', l['t']):
                    out.append(cand(sc, 'currency', l['t'], li, '', ['sum_lt_1M'], 'drop',
                                    'сумма меньше миллиона цифрами — по канону допустимо', drop_class='sum_lt_1M'))
        return out
    first = viol[0][0]
    screens = []
    for sc, li, t, fix, why in viol:
        if sc.id not in screens:
            screens.append(sc.id)
    canon = (P.profile('rules_text') or '')
    m = re.search(r'«\$[^»]*МЛН»', canon)
    out.append(cand(first, 'currency', ' · '.join(f'{v[0].e["tc"]} «{v[2]}»' for v in viol), viol[0][1],
                    ' · '.join(f'{v[0].e["tc"]} «{v[3]}»' for v in viol),
                    [f'violations:{",".join(v[4] for v in viol)}', 'money_screens: ' + ' | '.join(money)],
                    'auto_confirm', 'формат валюты по канону канала ' + (m.group(0) if m else '«$30,3 МЛН»') +
                    ' — знак вплотную перед числом, от миллиона — сокращение; единый формат по фильму',
                    screens=screens))
    for sc in all_screens:
        for li, l in enumerate(sc.lines):
            if re.search(r'[$€]\s?\d', l['t']) and not any(v[0] is sc and v[1] == li for v in viol):
                v = re.sub(r'\D', '', l['t'])
                if v and int(v) < MONEY_MLN:
                    out.append(cand(sc, 'currency', l['t'], li, '', ['sum_lt_1M'], 'drop',
                                    'сумма меньше миллиона цифрами — по канону допустимо', drop_class='sum_lt_1M'))
    return out


LAT_UNITS = r'(ct|cts|mm|cm|g|kg|oz|in|USD)'
CYR_UNITS = r'(г|кг|мм|см|м|км|кар|мг|мл|л)'
RX_LAT_UNIT = re.compile(r'\d\s*' + LAT_UNITS + r'(?![A-Za-z])', re.I)
RX_CYR_UNIT = re.compile(r'\d\s*' + CYR_UNITS + r'(?![А-Яа-яё])', re.I)


def rule_language(sc):
    out = []
    if sc.vlm_notext:
        return out
    lat = [t for t in tokens(sc.ocr_text) if is_lat(t) and len(t) >= 2]
    cyr = [t for t in tokens(sc.ocr_text) if is_cyr(t) and len(t) >= 2]
    if lat:
        share = len(lat) / max(1, len(lat) + len(cyr))
        wl = [t for t in lat if whitelisted(t)]
        if share >= LATIN_SHARE and sc.dur >= LATIN_MIN_DUR:
            sigs = [f'latin_share:{share:.2f}', f'dur:{sc.dur}s', f'whitelisted:{len(wl)}/{len(lat)}']
            if len(wl) == len(lat) and len(lat) + len(cyr) <= 2:
                out.append(cand(sc, 'language', sc.ocr_text[:120], -1, '', sigs + ['whitelist_logo'], 'drop',
                                'логотип/бейдж из белого списка канала', drop_class='whitelist_logo'))
            elif len(wl) == len(lat):
                out.append(cand(sc, 'language', sc.ocr_text[:120], -1, '', sigs + ['all_whitelisted'], 'cloud',
                                'латиница целиком из белого списка канала — проверить, нужен ли русский слой',
                                priority='low'))
            else:
                out.append(cand(sc, 'language', sc.ocr_text[:120], -1, '', sigs, 'auto_confirm',
                                f'английский текст без русского слоя ≥{int(LATIN_SHARE*100)}% экрана, держится {sc.dur} с — '
                                'правило канала: русский титр главный'))
        elif share >= LATIN_SHARE:
            out.append(cand(sc, 'language', sc.ocr_text[:120], -1, '', [f'latin_share:{share:.2f}', f'dur:{sc.dur}s'], 'drop',
                            f'латиница, но экран короче {LATIN_MIN_DUR} с', drop_class='latin_short'))
    # латинская строка крупнее русской парной (иерархия перевёрнута)
    pairs = []
    for i, L in enumerate(sc.lines):
        if not is_lat(L['t'].replace(' ', '')) or len(L['t']) < 3 or whitelisted(L['t']):
            continue
        for j, C in enumerate(sc.lines):
            if i == j or not RX_CYR_WORD.search(C['t']):
                continue
            if abs(C['x'] - L['x']) <= 0.03 and 0 < C['y'] - L['y'] <= 3 * L['bh'] and L['bh'] > C['bh'] * LATIN_BIGGER:
                pairs.append((L['t'], C['t'], round(L['bh'] / C['bh'], 2)))
    if len(pairs) >= 2:
        out.append(cand(sc, 'language', ' · '.join(f'{a} / {b}' for a, b, _ in pairs[:6]), -1, '',
                        [f'latin_bigger:{p[2]}' for p in pairs[:6]], 'cloud',
                        'английское название стоит первым и крупнее русского — правило канала: русский главный',
                        need_frame=True))
    # смешение алфавитов внутри группы через «/» и в формуле с единицами
    for li, l in enumerate(sc.lines):
        t = l['t']
        if re.search(r'[А-ЯЁа-яё]{2,}/[A-Za-z]{2,}|[A-Za-z]{2,}/[А-ЯЁа-яё]{2,}', t):
            out.append(cand(sc, 'language', t, li, '', ['mixed_alphabet_group'], 'cloud',
                            'кириллица и латиница внутри одной скобки/группы через «/»', need_frame=False))
    vl = sc.vlm_text.replace('\n', ' | ')
    for t in (sc.ocr_text, vl):
        if '=' in t and (RX_LAT_UNIT.search(t) or RX_LAT_UNIT.search(vl)) and (RX_CYR_UNIT.search(t) or RX_CYR_UNIT.search(vl)):
            out.append(cand(sc, 'language', vl[:80] if sc.vlm_text else sc.ocr_text[:80], -1, '', ['mixed_units_formula'], 'cloud',
                            'в одной формуле латинская и русская единицы (CT ↔ Г) — привести к одной системе'))
            break
    return out


def ean_check(digits):
    """контрольная цифра EAN-13/EAN-8/UPC-A → (ок?, правильная цифра)"""
    d = [int(c) for c in digits]
    body, chk = d[:-1], d[-1]
    if len(d) == 13:
        s = sum(v * (1 if i % 2 == 0 else 3) for i, v in enumerate(body))
    elif len(d) in (12, 8):
        s = sum(v * (3 if i % 2 == 0 else 1) for i, v in enumerate(body))
    else:
        return None
    c = (10 - s % 10) % 10
    return (c == chk, c)


def rule_fact(sc):
    out = []
    text = sc.ocr_text
    vlm = sc.vlm_text.replace('\n', ' | ')
    vo = vo_text(sc.t0, sc.t1, VO_PAD_FACT).lower()
    # 1) символ химического элемента (регистр) — по каталогу, при упоминании элемента в озвучке
    for li, l in enumerate(sc.lines):
        for tok in tokens(l['t']):
            if len(tok) > 2 or not is_lat(tok):
                continue
            for symb in CHEM_SYMBOLS:
                if tok.lower() == symb.lower() and tok != symb and len(symb) == 2:
                    rx = CHEM_ELEMENT_RX.get(symb)
                    said = bool(rx and rx.search(vo))
                    if said:
                        out.append(cand(sc, 'fact', l['t'], li, l['t'].replace(tok, symb), [f'chem_symbol:{tok}→{symb}', 'vo_names_element'],
                                        'auto_confirm', T('a2.fact_chem_said', symb=symb)))
                    else:
                        out.append(cand(sc, 'fact', l['t'], li, l['t'].replace(tok, symb), [f'chem_symbol:{tok}→{symb}'],
                                        'cloud', T('a2.fact_chem_case', symb=symb)))
    # VLM мог прочитать символ кириллицей («СР»): сверяем с OCR через сигнатуру
    # 2) места: канон написания и порядка «СОВРЕМЕННОЕ (СТАРОЕ)»
    for p in TC.PLACES:
        rx = re.compile(p['rx'], re.I)
        canon_words = [w for w in tokens(p.get('ru', '')) if len(w) >= 4]
        old = (p.get('old') or '').strip()
        for li, l in enumerate(sc.lines):
            for tok in tokens(l['t']):
                if len(tok) < 4 or not is_cyr(tok) or not rx.search(tok.lower()):
                    continue
                for cw in canon_words:
                    cwl = cw.lower()
                    if sig(tok).startswith(sig(cwl)) and not tok.lower().startswith(cwl) \
                            and sig(tok)[:len(sig(cwl))] == sig(cwl):
                        fix = case_like(cwl + tok.lower()[len(cwl):], tok)
                        vt, vr = sc.vlm_match(tok)
                        agree = bool(vt) and vt.lower() == tok.lower()
                        out.append(cand(sc, 'typo', tok, li, fix, [f'places_canon:{cw}', 'diff_confusable_only',
                                                                  'ocr=vlm' if agree else f'vlm:{vt}'],
                                        'cloud', T('a2.fact_place_confusable', cw=cw),
                                        need_frame=True, zoom_wanted=True))
                if old and tok.lower().startswith(old.lower()[:5]) and not any(
                        sig(cw).lower() in sig(text) for cw in canon_words):
                    out.append(cand(sc, 'fact', l['t'], li, p.get('label', ''), [f'places_old_name:{old}'], 'auto_confirm',
                                    T('a2.fact_place_old', label=p.get('label'))))
            if old and re.search(re.escape(old) + r'\s*\(\s*' + re.escape(p['ru']), l['t'], re.I):
                out.append(cand(sc, 'fact', l['t'], li, p.get('label', ''), ['places_order'], 'auto_confirm',
                                T('a2.fact_place_order', label=p.get('label'))))
    # 3) контрольные цифры штрихкодов: только EAN-13 / UPC-A; суммы «30 300 000» (группы по 3, знак валюты) — не код
    for li, l in enumerate(sc.lines):
        for m in re.finditer(r'(?<![\d$€])(\d[\d ]{10,16}\d)(?!\d)', l['t']):
            digits = re.sub(r'\D', '', m.group(1))
            if re.fullmatch(r'\d{1,3}(?: \d{3})+', m.group(1).strip()) or (RX_MONEY_EN if LANG == 'en' else RX_MONEY).search(l['t']):
                continue
            if len(digits) in (12, 13):
                r = ean_check(digits)
                if r and not r[0]:
                    fixed = digits[:-1] + str(r[1])
                    out.append(cand(sc, 'fact', m.group(1), li, m.group(1)[:-1] + str(r[1]),
                                    [f'ean{len(digits)}_check:{digits[-1]}→{r[1]}'], 'auto_confirm',
                                    T('a2.fact_ean', n=len(digits), d=r[1], fixed=fixed)))
    # 4) вес ↔ размеры камня
    ct = re.search(r'(\d+[.,]\d+)\s*(ct|кар)\b', text + ' ' + vlm, re.I)
    dims = re.search(r'(\d+[.,]\d+)\s*[x×х]\s*(\d+[.,]\d+)\s*[x×х]\s*(\d+[.,]\d+)', text + ' ' + vlm, re.I)
    if ct and dims:
        w = float(ct.group(1).replace(',', '.'))
        L, Wd, H = (float(dims.group(i).replace(',', '.')) for i in (1, 2, 3))
        est = L * Wd * H * GEM_SG * GEM_SHAPE_K
        if w > 0 and est > 0 and (w / est > WEIGHT_TOL or est / w > WEIGHT_TOL):
            out.append(cand(sc, 'fact', f'{ct.group(0)} · {dims.group(0)}', -1, '',
                            [f'weight_vs_dims: est≈{est:.2f} ct vs {w} ct'], 'cloud',
                            T('a2.fact_weight', L=L, Wd=Wd, H=H, est=est, sg=GEM_SG, w=w)))
    # 5) всё остальное с числами/именами/датами — в облако (документ/карта — с кадром)
    nums = screen_numbers_en(text, with_money=True) if LANG == 'en' else screen_numbers(text)
    is_map = bool(re.search(r'\bmap\b', sc.vlm_desc, re.I))
    is_doc = bool(re.search(r'certificate|document|report|scan|photo|table|tag|label', sc.vlm_desc, re.I))
    date = re.search(r'\b\d{1,2}\s+[A-Za-zА-Яа-я]{3,}\s+\d{4}\b|\b(19|20)\d{2}\b', text)
    phone = re.search(r'\+\d[\d\s-]{8,}\d', text)
    legal = re.search(r'\bЗАКОН(?!Н)\w{0,3}\b|\bФЗ\b|\bКОДЕКС\w*|\bГОСТ\b|\bУКАЗ\w{0,2}\b|\bСТАТЬ[ЯИ]\b|№\s*\d', text)
    if LANG == 'en':                                  # EN: площадь (sqft / sq ft / m²) — тоже единица
        unit_nums = re.findall(r'\d+(?:[.,]\d+)?\s*(?:sq\.?\s?ft|sqft|ft²|sq\.?\s?m\b|sqm|m²|ct|mm|km|°|k\b)', text, re.I)
    else:
        unit_nums = re.findall(r'\d+(?:[.,]\d+)?\s*(?:ct|кар|мм|mm|г\b|кг|нм|°|проб|k\b)', text, re.I)
    trigger = []
    if date:
        trigger.append(f'date:{date.group(0)}')
    if phone:
        trigger.append(f'phone:{phone.group(0)}')
    if legal:
        trigger.append(f'legal:{legal.group(0)}')
    if len(nums) >= 3:
        trigger.append(f'numbers:{len(nums)}')
    if unit_nums:
        trigger.append('units:' + ','.join(unit_nums[:4]))
    if is_map:
        trigger.append('map')
    if trigger and not (len(trigger) == 1 and trigger[0].startswith('units') and len(nums) <= 2 and not is_doc):
        lines_n = [l['t'] for l in sc.lines if re.search(r'\d', l['t']) or (legal and legal.group(0) in l['t'])]
        if is_map:
            lines_n = [l['t'] for l in sc.lines]
        shown = ' · '.join(lines_n)[:200] or text[:120]
        out.append(cand(sc, 'fact', shown, -1, '', trigger + ([f'llm:{sc.llm.get("severity")}'] if sc.llm.get('severity') else []),
                        'cloud', (T('a2.fact_map') if is_map else
                                  T('a2.fact_numbers') + (T('a2.fact_doc_suffix') if is_doc else '')),
                        need_frame=is_map or is_doc))
    return out


def rule_mismatch(sc):
    out = []
    en = LANG == 'en'                                 # EN: 1,850 = 1850, «2.5 million», суммы — в rule_currency_en
    nums = screen_numbers_en(sc.ocr_text) if en else screen_numbers(sc.ocr_text)
    if not nums or len(nums) > MAX_NUMBERS_TITLE:
        return out
    vals, ranges, factors = vo_numbers_en(sc.t0, sc.t1) if en else vo_numbers(sc.t0, sc.t1)
    if not vals and not ranges and not factors:
        return out
    unmatched, competing = [], []
    for v, raw in nums:
        eq = any(abs(v - x) <= 0.02 * max(v, x, 1) for x in vals)
        inr = any(lo <= v <= hi for lo, hi in ranges)
        if eq or inr:
            continue
        comp = any(x > 0 and 0.1 <= v / x <= 10 for x in vals) or any(hi >= v / 10 and lo <= v * 10 for lo, hi in ranges)
        unmatched.append(raw)
        if comp:
            competing.append(raw)
    sigs = [f'screen:{",".join(r for _v, r in nums)}',
            'vo:' + ','.join(f'{x:g}' for x in sorted(vals)) + (' ranges:' + ','.join(f'{lo:g}–{hi:g}' for lo, hi in ranges) if ranges else '')
            + (' factors:' + ','.join(f'×{lo:g}–{hi:g}' for lo, hi in factors) if factors else '')]
    fired = False
    if competing:
        fired = True
        sigs.append('unmatched:' + ','.join(competing))
    if factors and len(nums) >= 2:
        vs = sorted(v for v, _r in nums if v > 0)
        if vs[0] > 0:
            r = vs[-1] / vs[0]
            if not any(lo / 2 <= r <= hi * 2 for lo, hi in factors):
                fired = True
                sigs.append(f'factor_screen:×{r:g}')
    if fired:
        out.append(cand(sc, 'mismatch', sc.ocr_text[:100], -1, '', sigs, 'cloud',
                        T('a2.mismatch_vo'), need_frame=False))
    return out


def rule_foreign(sc):
    out = []
    if sc.probe.get('foreign'):
        note = (sc.probe.get('foreign_note') or '')[:160]
        own = [w for w in OWN_LOGOS if len(w) >= 3 and re.search(r'(?<![a-z])' + re.escape(w.lower()) + r'(?![a-z])', note.lower())]
        if own:
            out.append(cand(sc, 'foreign_trace', note[:120], -1, '', ['probe:foreign', f'own_logo:{own[0]}'], 'drop',
                            T('a2.foreign_own_logo'), drop_class='own_logo'))
        else:
            out.append(cand(sc, 'foreign_trace', note[:120], -1, '', ['probe:foreign'],
                            'cloud', T('a2.foreign_probe'),
                            need_frame=True))
    for li, l in enumerate(sc.lines):
        tiny = l['bh'] <= TINY_H and l['bw'] <= 0.12
        corner = (l['x'] <= CORNER or l['x'] + l['bw'] >= 1 - CORNER) and (l['y'] <= CORNER or l['y'] + l['bh'] >= 1 - CORNER)
        if tiny and corner and l['c'] >= OCR_CONF_TRUST and not whitelisted(l['t']):
            out.append(cand(sc, 'foreign_trace', l['t'], li, '', ['tiny_corner_text'], 'cloud',
                            T('a2.foreign_tiny_corner'), need_frame=True))
    # cut_off зонда — не самостоятельная находка («титр за головой ведущей — приём», вёрстка = не класс ТЗ);
    # он лишь подкрепляет drop OCR-обрезков: сигнал вешается на typo-кандидаты экрана в build()
    return out


# ══ EN-правила (LANG == 'en') ═══════════════════════════════════════════════
def find_correction_en(tok, t0, t1):
    """→ (слово озвучки, ratio, начало) или None: похожее слово озвучки в окне VO_PAD_TYPO, ≤2 правок"""
    t = tok.lower()
    best = None
    for w in vo_words(t0, t1, VO_PAD_TYPO):
        for v in tokens(w[0]):
            v = v.lower()
            if len(v) < 3 or v == t or not is_lat(v) or abs(len(v) - len(t)) > CORR_LEN_DIFF:
                continue
            r = ratio(t, v)
            if r >= CORR_RATIO and damerau(t, v) <= SPELL_MAX_ED and (best is None or r > best[1]):
                best = (v, r, w[1])
    return best


def vlm_longer_known_en(sc, work):
    """VLM читает длинное известное слово с тем же началом (≥5 букв) → OCR обрезал"""
    w = work.lower()
    for v in sc.vlm_tokens:
        vl = v.lower()
        if len(vl) > len(w) and len(w) >= 5 and vl.startswith(w[:5]) and is_lat(vl) and known_en(vl):
            if len(os.path.commonprefix([vl, w])) >= max(5, len(w) - 2):
                return v
    return None


def rule_typo_en(sc):
    """латинские токены ≥4 букв без цифр (ALL-CAPS ≤5 — аббревиатура). Известно: словарь EN, озвучка, лексикон
    профиля, карточка, каталог. auto_confirm — только если OCR и VLM читают токен одинаково И исправление ровно одно
    (ближайший уровень правок ≤2, вместе с исправлением из озвучки); иначе cloud. Текст реального мира → drop."""
    out = []
    if sc.vlm_notext and all(l['c'] < OCR_CONF_TRUST for l in sc.lines):
        out.append(cand(sc, 'typo', sc.ocr_text[:60], -1, '', ['vlm:NO TEXT', 'ocr_conf<0.5'], 'drop',
                        T('a2.typo_ocr_noise'), drop_class='ocr_noise'))
        return out
    if sc.is_typing_prefix():
        out.append(cand(sc, 'typo', sc.ocr_text[:60], -1, '', ['typing_prefix', f'same_title_as:{sc.typing_of}'], 'drop',
                        T('a2.typo_typing_prefix', sid=sc.typing_of), drop_class='typing_anim'))
        return out
    real = real_world(sc)
    ed = en_dict()
    seen = set()
    for li, line in enumerate(sc.lines):
        for tok in tokens(line['t']):
            if len(tok) < TYPO_MIN_LEN or re.search(r'\d', tok):
                continue
            sigs = [f'conf:{line["c"]}']
            work = tok
            if RX_MIXED.fullmatch(tok):                       # кириллические двойники в латинском слове — артефакт OCR
                work = cyr_to_lat(tok)
                sigs.append('homoglyph_mix')
            if not is_lat(work) or work.lower() in seen:
                continue
            wl = work.lower()
            seen.add(wl)
            if work.isupper() and len(work) <= CAPS_ACRONYM_MAX:
                continue
            vt, vr = sc.vlm_match(work)
            conf_hit = next(((w, r) for w, r in TC.CONFUSABLES if is_lat(str(w)) and wl.startswith(str(w).lower())), None)
            if conf_hit:
                wrong, right = conf_hit
                fx = case_like(str(right).lower() + wl[len(wrong):], tok)
                same = bool(vt) and vt.lower() == wl
                sigs += [f'confusable:{wrong}→{right}', 'ocr=vlm' if same else f'vlm:{vt}']
                if same:
                    out.append(cand(sc, 'typo', tok, li, fx, sigs, 'auto_confirm',
                                    T('a2.typo_confusable_auto', wrong=wrong, right=right), zoom_wanted=False))
                else:
                    out.append(cand(sc, 'typo', tok, li, fx, sigs, 'cloud', T('a2.typo_confusable_cloud', wrong=wrong, right=right),
                                    need_frame=True, zoom_wanted=True))
                continue
            if known_en(work):
                continue
            if real:
                out.append(cand(sc, 'typo', tok, li, '', sigs + ['vlm_desc:real_world'], 'drop', T('a2.typo_real_world'),
                                drop_class='real_world_text'))
                continue
            pool = {t.lower() for t in sc.all_tokens | sc.neigh_tokens}
            full = [w for w in pool if w.startswith(wl) and len(w) > len(wl) and is_lat(w) and known_en(w)]
            if full:
                out.append(cand(sc, 'typo', tok, li, '', sigs + [f'prefix_of:{sorted(full)[0]}'], 'drop',
                                T('a2.typo_prefix_anim'), drop_class='typing_anim'))
                continue
            sigs.append('unknown:' + ed.name)
            sigs.append(f'stable:{sc.stable(tok)}/{sc.sec_count}s')
            vo_fix = find_correction_en(work, sc.t0, sc.t1)
            near = ed.nearest(wl)
            fixes = set(near) | ({vo_fix[0]} if vo_fix else set())
            fix_word = vo_fix[0] if vo_fix else ed.correction(wl)
            fix = case_like(fix_word, tok) if fix_word else ''
            if vo_fix:
                sigs.append(f'vo_match:{vo_fix[1]:.2f} ({vo_fix[0]} @{tc(vo_fix[2])})')
            if near:
                sigs.append(f'{ed.name}:' + ','.join(sorted(near)[:4]))
            sigs.append(f'fixes:{len(fixes)}')
            gl = glued(work, sc.t0, sc.t1)
            z = sc.zoom(li, tok)
            readings = {'ocr': wl, 'vlm': (vt or '').lower() if vr >= VLM_READ_RATIO else ''}
            if z:
                readings['zoom_vlm'] = (z.get('vlm') or '').lower()
                readings['zoom_ocr'] = (z.get('ocr') or '').lower()
            agree = [k for k, v in readings.items() if v and v == wl]
            sigs.append('='.join(agree) if len(agree) > 1 else 'ocr_only')
            zoom_wanted = z is None
            split = sc.vlm_split_of(work)
            if split and not gl:
                out.append(cand(sc, 'typo', tok, li, case_like(split, tok), sigs + ['vlm_split'], 'drop',
                                T('a2.typo_vlm_split'), drop_class='ocr_artifact', zoom_wanted=True))
                continue
            longer = vlm_longer_known_en(sc, work)
            if longer and not vo_fix and not gl:
                out.append(cand(sc, 'typo', tok, li, case_like(longer, tok), sigs + [f'ocr_truncated:{longer}'], 'drop',
                                T('a2.typo_ocr_truncated'), drop_class='ocr_truncated', zoom_wanted=True))
                continue
            if gl:
                split_rx = r'\b' + re.escape(gl.split()[0]) + r'\s+' + re.escape(gl.split()[-1]) + r'\b'
                if re.search(split_rx, sc.vlm_text, flags=re.I):
                    out.append(cand(sc, 'typo', tok, li, case_like(gl, tok), sigs + ['glued_vo', 'vlm_split'], 'drop',
                                    T('a2.typo_vlm_split'), drop_class='ocr_artifact', zoom_wanted=True))
                else:
                    out.append(cand(sc, 'typo', tok, li, case_like(gl, tok), sigs + ['glued_vo'], 'cloud',
                                    T('a2.typo_glued_vo'), need_frame=True, zoom_wanted=zoom_wanted))
                continue
            vlm = readings['vlm']
            vlm_agrees = 'vlm' in agree or 'zoom_vlm' in agree
            zv = readings.get('zoom_vlm', '')
            zoom_against = bool(z) and bool(zv) and zv != wl and readings.get('zoom_ocr', '') != wl
            if not vlm_agrees:
                if vlm and is_lat(vlm) and known_en(vlm) and line['c'] < OCR_CONF_TRUST:
                    out.append(cand(sc, 'typo', tok, li, case_like(vlm, tok), sigs + ['vlm_known'], 'drop',
                                    T('a2.typo_vlm_known_low_conf'), drop_class='ocr_artifact', zoom_wanted=zoom_wanted))
                elif zoom_against and is_lat(zv) and known_en(zv):
                    out.append(cand(sc, 'typo', tok, li, case_like(zv, tok), sigs + ['zoom_contradicts_ocr'], 'drop',
                                    T('a2.typo_zoom_known'), drop_class='ocr_artifact', zoom_wanted=False))
                elif not vlm and not z and (line['c'] < OCR_CONF_TRUST or line['bh'] < TINY_LINE_H):
                    out.append(cand(sc, 'typo', tok, li, fix, sigs + ['vlm_missing', f'line_h:{line["bh"]:.3f}'], 'drop',
                                    T('a2.typo_vlm_missing_weak'), drop_class='ocr_artifact', zoom_wanted=True))
                elif not vlm and not z:
                    out.append(cand(sc, 'typo', tok, li, fix, sigs + ['vlm_missing'], 'cloud', T('a2.typo_vlm_missing'),
                                    need_frame=True, zoom_wanted=True))
                else:
                    alt = case_like(vlm, tok) if vlm and is_lat(vlm) and known_en(vlm) else ''
                    out.append(cand(sc, 'typo', tok, li, fix or alt, sigs + [f'reads_other:vlm={vlm}'], 'cloud',
                                    T('a2.typo_readings_differ'), need_frame=True, zoom_wanted=zoom_wanted))
                continue
            if zoom_against:
                out.append(cand(sc, 'typo', tok, li, fix, sigs + ['zoom_contradicts_ocr'], 'cloud', T('a2.typo_zoom_differs'),
                                need_frame=True, zoom_wanted=False))
            elif fix and len(fixes) == 1:
                out.append(cand(sc, 'typo', tok, li, fix, sigs, 'auto_confirm',
                                T('a2.typo_auto', tok=tok, fix=fix, src=T('a2.src_vo') if vo_fix else T('a2.src_dict')),
                                zoom_wanted=False))
            elif fix:
                out.append(cand(sc, 'typo', tok, li, fix, sigs, 'cloud', T('a2.typo_many_fixes', n=len(fixes)),
                                need_frame=True, zoom_wanted=zoom_wanted))
            else:
                out.append(cand(sc, 'typo', tok, li, '', sigs + ['no_correction'], 'cloud', T('a2.typo_no_fix'),
                                need_frame=True, zoom_wanted=zoom_wanted))
    return out


def rule_language_en(sc):
    """кириллица в титре/графике → auto_confirm (если второе чтение VLM тоже видит кириллицу, иначе cloud);
    арабское письмо → cloud; латинское слово с кириллическими двойниками — артефакт OCR → drop; текст реального
    мира → drop. Русское «английский без перевода» для en не существует."""
    out = []
    if sc.vlm_notext and all(l['c'] < OCR_CONF_TRUST for l in sc.lines):
        return out
    homo, cyr_lines, arab_lines = [], [], []
    for li, l in enumerate(sc.lines):
        real_cyr = []
        for tok in tokens(l['t']):
            if RX_MIXED.fullmatch(tok) or (is_cyr(tok) and all(ch in _CYR_HOMO for ch in tok)):
                homo.append(tok)
            elif is_cyr(tok) and len(tok) >= 2:
                real_cyr.append(tok)
        if real_cyr:
            cyr_lines.append((li, l['t'], real_cyr))
        if RX_ARABIC.search(l['t']):
            arab_lines.append((li, l['t']))
    vlm_cyr = [t for t in tokens(sc.vlm_text) if is_cyr(t) and len(t) >= 2 and not all(ch in _CYR_HOMO for ch in t)]
    vlm_arab = bool(RX_ARABIC.search(sc.vlm_text))
    fs = sc.llm.get('foreign_script')
    llm_sig = ['llm:foreign_script'] if (fs if not isinstance(fs, str) else fs.strip()) else []
    real = real_world(sc)
    if homo:
        uniq = list(dict.fromkeys(homo))
        out.append(cand(sc, 'language', ' '.join(uniq)[:120], -1, ' '.join(cyr_to_lat(t) for t in uniq)[:120],
                        ['homoglyph_mix:' + ','.join(uniq[:6])], 'drop', T('a2.lang_homoglyph'), drop_class='ocr_homoglyph'))
    if cyr_lines or vlm_cyr:
        text = ' · '.join(t for _li, t, _r in cyr_lines) or ' '.join(vlm_cyr)
        sigs = ['script:cyrillic', 'ocr:' + ','.join(t for _li, _t, r in cyr_lines for t in r)[:80],
                'vlm=cyr' if vlm_cyr else 'vlm≠cyr'] + llm_sig
        if real:
            out.append(cand(sc, 'language', text[:120], -1, '', sigs + ['vlm_desc:real_world'], 'drop',
                            T('a2.lang_real_world'), drop_class='real_world_text'))
        elif cyr_lines and vlm_cyr:
            out.append(cand(sc, 'language', text[:120], -1, '', sigs, 'auto_confirm', T('a2.lang_cyr_auto')))
        else:
            out.append(cand(sc, 'language', text[:120], -1, '', sigs, 'cloud', T('a2.lang_cyr_cloud'), need_frame=True))
    if arab_lines or vlm_arab:
        text = ' · '.join(t for _li, t in arab_lines) or sc.vlm_text.replace('\n', ' | ')[:120]
        sigs = ['script:arabic', 'ocr' if arab_lines else 'vlm_only'] + llm_sig
        if real:
            out.append(cand(sc, 'language', text[:120], -1, '', sigs + ['vlm_desc:real_world'], 'drop',
                            T('a2.lang_real_world'), drop_class='real_world_text'))
        else:
            out.append(cand(sc, 'language', text[:120], -1, '', sigs, 'cloud', T('a2.lang_arabic'), need_frame=True))
    return out


# ── EN: суммы и числа ──────────────────────────────────────────────────────
EN_CUR = r'AED|DHS|Dhs|dhs|DH|Dh|[Dd]irhams?|DIRHAMS?|USD|US\$|\$|EUR|€|GBP|£'
EN_SCALE = r'(?:\s?(?:K|k|MN|Mn|mn|M|m|BN|Bn|bn|B|b)(?![A-Za-z²³])|\s(?:thousand|million|billion)\b)?'
_EN_SCALE_V = {'k': 1e3, 'thousand': 1e3, 'm': 1e6, 'mn': 1e6, 'million': 1e6, 'b': 1e9, 'bn': 1e9, 'billion': 1e9}
_EN_UNITS = {'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
             'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15, 'sixteen': 16,
             'seventeen': 17, 'eighteen': 18, 'nineteen': 19}
_EN_TENS = {'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90}
_EN_BIG = {'thousand': 1e3, 'million': 1e6, 'billion': 1e9}
_EN_PLURAL = {'dozens': (24, 99), 'hundreds': (200, 999), 'thousands': (2000, 9999), 'millions': (2e6, 9.99e6),
              'billions': (2e9, 9.99e9)}
RX_VO_NUM = re.compile(r'^(?P<cur>[$€£])?(?P<n>\d[\d,]*(?:\.\d+)?)(?P<suf>k|mn|m|bn|b)?$', re.I)
RX_MONEY_EN = re.compile(r'[$€£]|\b(?:USD|AED|EUR|GBP|Dhs?|DH)\b', re.I)
_EN_RX = {}


def _en_num_pat():
    dec = str(P.profile('currency.decimal', '.') or '.')
    grp = str(P.profile('currency.group', ',') or ',')
    return rf'\d{{1,3}}(?:{re.escape(grp)}\d{{3}})+(?:{re.escape(dec)}\d+)?|\d+(?:{re.escape(dec)}\d+)?', dec, grp


def en_rx():
    if not _EN_RX:
        num, dec, grp = _en_num_pat()
        _EN_RX.update(num=num, dec=dec, grp=grp,
                      money=re.compile(rf'(?<![A-Za-z])(?P<pre>{EN_CUR})\s?(?P<n1>{num})(?P<s1>{EN_SCALE})'
                                       rf'|(?<![\w.,])(?P<n2>{num})(?P<s2>{EN_SCALE})\s?(?P<post>{EN_CUR})(?![A-Za-z])'),
                      number=re.compile(rf'(?<![\w.,])({num})(?![\d])'),
                      num_scale=re.compile(rf'({num})({EN_SCALE})'))
    return _EN_RX


def _en_float(s):
    rx = en_rx()
    return float(s.replace(rx['grp'], '').replace(rx['dec'], '.'))


def cur_code(s):
    s = (s or '').strip().lower().strip('.,;:!?()')
    if s in ('aed', 'dh', 'dhs') or s.startswith('dirham'):
        return 'AED'
    if s in ('$', 'usd', 'us$', 'bucks') or s.startswith('dollar'):
        return 'USD'
    if s in ('€', 'eur') or s.startswith('euro'):
        return 'EUR'
    if s in ('£', 'gbp', 'quid') or s.startswith('pound'):
        return 'GBP'
    return None


def screen_money_en(text):
    """суммы на экране → [(значение, валюта, как написано, (start, end))]; формат не проверяется"""
    out = []
    for m in en_rx()['money'].finditer(text or ''):
        n, s, c = (m.group('n1'), m.group('s1'), m.group('pre')) if m.group('pre') else (m.group('n2'), m.group('s2'), m.group('post'))
        try:
            v = _en_float(n) * _EN_SCALE_V.get((s or '').strip().lower(), 1.0)
        except ValueError:
            continue
        out.append((v, cur_code(c), m.group(0).strip(), m.span()))
    return out


def _vo_toks_en(t0, t1, pad):
    out = []
    for w in vo_words(t0, t1, pad):
        s = w[0].strip().lower().strip('.,;:!?()"“”‘’\'–—')
        parts = s.split('-') if re.fullmatch(r'[a-z]+(?:-[a-z]+)+', s) else [s]      # twenty-five
        out += [(p, w[1]) for p in parts if p]
    return out


def vo_amounts_en(t0, t1, pad=VO_PAD_MISMATCH):
    """числа озвучки → [{'v', 'cur', 'money', 'parts', 'text', 't'}]: «2.5 million dirhams», «$2.5M», «two and a half million»"""
    toks = _vo_toks_en(t0, t1, pad)
    out, i, n = [], 0, len(toks)
    while i < n:
        s = toks[i][0]
        nxt0 = toks[i + 1][0] if i + 1 < n else ''
        if not (RX_VO_NUM.match(s) or s in _EN_UNITS or s in _EN_TENS
                or (s in ('a', 'half') and (nxt0 in _EN_BIG or nxt0 in ('hundred', 'half')))):
            i += 1
            continue
        j, total, cur, parts, scaled, code, point, frac, raw = i, 0.0, 0.0, [], False, None, False, 1.0, []
        while j < n:
            s = toks[j][0]
            m = RX_VO_NUM.match(s)
            if m:
                digits = m.group('n').replace(',', '')
                if point:
                    cur += float('0.' + digits.replace('.', ''))
                    point = False
                elif cur and not raw[-1:] == ['and']:
                    break                                          # «2015 2016» — два разных числа
                else:
                    cur += float(digits)
                parts.append(float(digits))
                code = code or cur_code(m.group('cur') or '')
                if m.group('suf'):
                    total += (cur or 1.0) * _EN_SCALE_V[m.group('suf').lower()]
                    cur, scaled = 0.0, True
            elif s in _EN_UNITS or s in _EN_TENS:
                v = _EN_UNITS.get(s, _EN_TENS.get(s))
                if point:
                    frac *= 10
                    cur += v / frac
                else:
                    cur += v
                parts.append(float(v))
            elif s == 'point' and (cur or total):
                point, frac = True, 1.0
            elif s == 'hundred':
                cur = (cur or 1.0) * 100
            elif s in _EN_BIG:
                total += (cur or 1.0) * _EN_BIG[s]
                cur, scaled = 0.0, True
            elif s == 'half':
                if cur == 0 and total:
                    total *= 1.5
                else:
                    cur += 0.5
            elif s in ('a', 'and'):
                pass
            else:
                break
            raw.append(s)
            j += 1
        while raw and raw[-1] in ('a', 'and'):
            raw.pop()
        value = total + cur
        nxt = toks[j][0] if j < n else ''
        prev = toks[i - 1][0] if i > 0 else ''
        code = code or cur_code(nxt) or cur_code(prev)
        if value > 0:
            text = ' '.join(raw) + (f' {nxt}' if cur_code(nxt) else '')
            out.append({'v': value, 'cur': code, 'money': bool(code) or scaled, 'parts': parts, 'text': text,
                        't': toks[i][1]})
        i = max(j, i + 1)
    return out


def vo_numbers_en(t0, t1, pad=VO_PAD_MISMATCH):
    """как vo_numbers, но для английской озвучки: (значения, порядки, множители «N times»)"""
    vals, ranges, factors = set(), [], []
    for a in vo_amounts_en(t0, t1, pad):
        vals.add(a['v'])
        vals.update(a['parts'])
    toks = _vo_toks_en(t0, t1, pad)
    for k, (s, _t) in enumerate(toks):
        prev = toks[k - 1][0] if k else ''
        prev_num = bool(RX_VO_NUM.match(prev)) or prev in _EN_UNITS or prev in _EN_TENS
        if s in _EN_PLURAL and not prev_num:
            ranges.append(_EN_PLURAL[s])
        elif s in ('twice', 'double', 'doubled'):
            factors.append((2, 2))
        elif s in ('triple', 'tripled'):
            factors.append((3, 3))
        elif s == 'times' and prev:
            m = RX_VO_NUM.match(prev)
            v = float(m.group('n').replace(',', '')) if m else _EN_UNITS.get(prev, _EN_TENS.get(prev))
            if v:
                factors.append((v, v))
    return vals, ranges, factors


def screen_numbers_en(text, with_money=False):
    """числа экрана (EN: 1,850 = 1850); денежные суммы сверяет rule_currency_en — без with_money их тут нет"""
    money = screen_money_en(text)
    out = [(v, raw) for v, _c, raw, _sp in money] if with_money else []
    spans = [sp for _v, _c, _r, sp in money]
    for m in en_rx()['number'].finditer(text or ''):
        if any(a <= m.start() < b for a, b in spans):
            continue
        raw = m.group(1)
        try:
            v = _en_float(raw)
        except ValueError:
            continue
        after = text[m.end():m.end() + 8]
        has_unit = bool(re.match(r'\s?(sq\.?\s?ft|sqft|ft²|sq\.?\s?m\b|sqm|m²|m2\b|%|°|k\b|m\b|b\b|bn\b|mn\b|km\b|x\b|×)',
                                 after, re.I))
        if v < 10 and float(v).is_integer() and not has_unit:
            continue
        if re.fullmatch(r'0\d', raw):
            continue
        out.append((v, raw.strip()))
    return out


def _money_close(a, b):
    return abs(a - b) <= MONEY_TOL * max(abs(a), abs(b), 1)


def _money_competing(v, x):
    """та же величина с ошибкой: в пределах ×10 или сдвиг разряда (25M ↔ 2.5M, 250K ↔ 2.5M)"""
    if v <= 0 or x <= 0:
        return False
    r = v / x
    return 0.1 <= r <= 10 or any(abs(r - 10 ** k) <= MONEY_TOL * 10 ** k for k in (-3, -2, 2, 3))


def _fmt_money_like(raw, value):
    """та же запись, что на экране, с другим числом: «AED 25M» + 2.5e6 → «AED 2.5M»"""
    rx = en_rx()
    m = rx['num_scale'].search(raw)
    if not m:
        return raw
    scale = _EN_SCALE_V.get((m.group(2) or '').strip().lower(), 1.0)
    if scale > 1:
        num = f'{value / scale:.2f}'.rstrip('0').rstrip('.')
    else:
        num = f'{value:,.2f}'.rstrip('0').rstrip('.')
    num = num.replace(',', '\x00').replace('.', rx['dec']).replace('\x00', rx['grp'])
    return raw[:m.start(1)] + num + raw[m.end(1):]


def rule_currency_en(all_screens):
    """суммы AED/Dh/dirham/$/€/£ на экране. Кандидат (cloud) — только если число или валюта расходятся с озвучкой
    ±8 с, либо одна сумма показана в разных валютах; формат (профиль currency.canon) — информационно, не проверяем."""
    out, shown = [], []
    for sc in all_screens:
        for li, l in enumerate(sc.lines):
            for v, code, raw, _sp in screen_money_en(l['t']):
                shown.append((sc, li, v, code, raw, l['t']))
    for sc, li, v, code, raw, line in shown:
        money_vo = [a for a in vo_amounts_en(sc.t0, sc.t1) if a['money'] and a['v'] > 0]
        if not money_vo:
            continue
        vo_sig = 'vo:' + ','.join(f"{a['cur'] or ''}{a['v']:g}" for a in money_vo)[:120]
        base = [f'screen:{code or ""}{v:g}', vo_sig]
        same = [a for a in money_vo if _money_close(a['v'], v)]
        if same:
            codes = sorted({a['cur'] for a in same if a['cur']})
            if code and codes and code not in codes:
                vo_txt = next(a['text'] for a in same if a['cur'])
                out.append(cand(sc, 'currency', line, li, '', base + ['currency_vs_vo'], 'cloud',
                                T('a2.cur_code_vs_vo', screen=raw, vo=vo_txt)))
            continue
        comp = [a for a in money_vo if (not a['cur'] or not code or a['cur'] == code) and _money_competing(v, a['v'])]
        if comp:
            best = min(comp, key=lambda a: abs(math.log10(v / a['v'])))
            out.append(cand(sc, 'currency', line, li, line.replace(raw, _fmt_money_like(raw, best['v'])),
                            base + ['figure_vs_vo'], 'cloud', T('a2.cur_figure_vs_vo', screen=raw, vo=best['text'])))
    used = set()
    for i, (sc, li, v, code, raw, line) in enumerate(shown):
        if not code or i in used:
            continue
        others = [k for k in range(i + 1, len(shown)) if k not in used and shown[k][3] and shown[k][3] != code
                  and _money_close(shown[k][2], v) and abs(shown[k][0].t0 - sc.t0) <= MONEY_MIX_WIN]
        if others:
            used.update(others)
            items = ' · '.join(f'{x[0].e["tc"]} «{x[4]}»' for x in [shown[i]] + [shown[k] for k in others])
            screens = list(dict.fromkeys([sc.id] + [shown[k][0].id for k in others]))
            out.append(cand(sc, 'currency', items, li, '', ['mixed_currency:' + ','.join(sorted({code} | {shown[k][3] for k in others}))],
                            'cloud', T('a2.cur_mixed', items=items), screens=screens))
    return out


# ── дедуп, existing_tz, обратная связь ─────────────────────────────────────
def screen_sig(sc):
    return re.sub(r'\d+', '#', sig(sc.ocr_text))


def dedup(cands):
    groups = []                                              # группы экранов по сигнатуре OCR
    by_sc = {}
    for sc in ALL:
        s = screen_sig(sc)
        for g in groups:
            if ratio(s, g['sig']) >= 1 - DUP_DIST:
                g['ids'].append(sc.id)
                by_sc[sc.id] = g
                break
        else:
            g = {'sig': s, 'ids': [sc.id]}
            groups.append(g)
            by_sc[sc.id] = g
    kept = []
    for c in cands:
        key_group = tuple(by_sc[c['screen_id']]['ids'])
        merged = False
        for k in kept:
            if k['kind'] != c['kind'] or k['route'] != c['route'] or k.get('drop_class') != c.get('drop_class'):
                continue
            same_group = tuple(by_sc[k['screen_id']]['ids']) == key_group
            same_text = sig(k['on_screen_text']) == sig(c['on_screen_text']) and sig(k['fix_local']) == sig(c['fix_local'])
            if c['scope'] == 'screen':
                ok = same_group and c['screen_id'] != k['screen_id']          # тот же экран-дубль: одно решение
            else:
                ok = same_text and (same_group or c['kind'] in ('typo', 'grammar'))   # то же слово в другом месте фильма
            if ok:
                k.setdefault('screens', [k['screen_id']])
                if c['screen_id'] not in k['screens']:
                    k['screens'].append(c['screen_id'])
                k['signals'].append(f'dup:{c["screen_id"]}')
                merged = True
                break
        if not merged:
            kept.append(c)
    return kept


def parse_tc(s):
    m = re.match(r'(\d+):(\d{2})', str(s or ''))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def load_pravki():
    p = M / 'pravki_v2.json'
    if not p.exists():
        p = M / 'pravki.json'
    if not p.exists():
        return []
    try:
        d = json.load(open(p, encoding='utf-8'))
    except Exception:                                   # noqa: BLE001
        return []
    out = []
    for t in d.get('all', []):
        secs = []
        for k in ('timeline_in_sec', 'timeline_out_sec'):
            if t.get(k) is not None:
                secs.append(float(t[k]))
        v = parse_tc(t.get('v1_tc'))
        if v is not None:
            secs.append(v)
        for x in re.findall(r'\d+:\d{2}', str(t.get('tc_range') or '')):
            secs.append(parse_tc(x))
        if not secs:
            continue
        label = f'ТЗ-{t["num"]}' if t.get('num') is not None else (t.get('title') or '')[:40]
        out.append({'lo': min(secs), 'hi': max(secs), 'words': words_set(t.get('title') or ''), 'label': label,
                    'status': t.get('status')})
    return out


def attach_existing_tz(cands, pravki):
    for c in cands:
        cw = words_set(c['on_screen_text'])
        if not cw:
            continue
        for t in pravki:
            if t['lo'] - TZ_TC_PAD <= c['t1'] and c['t0'] - TZ_TC_PAD <= t['hi'] + 0:
                ov = len(cw & t['words']) / len(cw)
                if ov >= TZ_WORD_OVERLAP:
                    c['existing_tz'] = t['label']
                    c['signals'].append(f'existing_tz:{ov:.2f}')
                    break


def apply_feedback(cands):
    p = M / 'channel_rules.json'
    if not p.exists():
        return 0
    try:
        d = json.load(open(p, encoding='utf-8'))
    except Exception:                                   # noqa: BLE001
        return 0
    rej = d.get('rejected') or d.get('rejects') or []
    n = 0
    for c in cands:
        if c['route'] == 'drop':
            continue
        for r in rej:
            if (r.get('class') or r.get('kind')) != c['kind']:
                continue
            if ratio(sig(r.get('text') or r.get('on_screen_text') or ''), sig(c['on_screen_text'])) >= FEEDBACK_SIM:
                c['route'], c['route_reason'], c['drop_class'] = 'drop', T('a2.feedback_rejected') + (r.get('reason') or '')[:80], 'feedback'
                c['signals'].append('feedback_rejected')
                n += 1
                break
    return n


ALL = [Screen(i) for i in range(len(SCREENS))]


RULES_EN = (rule_typo_en, rule_language_en, rule_fact, rule_mismatch, rule_foreign)   # RU-only: grammar/language/typo


def build():
    cands = []
    if LANG == 'en':
        for sc in ALL:
            for rule in RULES_EN:
                cands += rule(sc)
        cands += rule_currency_en(ALL)
    else:
        for sc in ALL:
            for rule in (rule_typo, rule_grammar, rule_language, rule_fact, rule_mismatch, rule_foreign):
                cands += rule(sc)
        cands += rule_currency(ALL)
    if P.EXCLUSIONS:                                  # известные не-ошибки ката (дыра в футаже, недоделанные экраны)
        for c in cands:
            why = P.in_exclusion(c['t0'], c['t1'])
            if why:
                c['route'], c['route_reason'], c['drop_class'] = 'drop', T('a2.known_exclusion', reason=why), 'known_exclusion'
                c['signals'].append('known_exclusion')
    for c in cands:                                   # обрезка по зонду — сигнал к словам этого экрана
        pr = PROBES.get(c['screen_id']) or {}
        if pr.get('cut_off') and c['kind'] == 'typo':
            c['signals'].append('probe:cut_off')
    cands.sort(key=lambda c: (c['t0'], c['kind'], c['line_idx']))
    cands = dedup(cands)
    # недопечатанный титр: тот же титр секундой раньше — кандидаты полного экрана покрывают и его
    covers = {}
    for sc in ALL:
        if sc.typing_of:
            covers.setdefault(sc.typing_of, []).append(sc.id)
    for c in cands:
        if c['route'] == 'drop':
            continue
        for sid in list(c.get('screens', [c['screen_id']])):
            for pre in covers.get(sid, []):
                c.setdefault('screens', [c['screen_id']])
                if pre not in c['screens']:
                    c['screens'].append(pre)
                    c['signals'].append(f'covers:{pre}')
                    c['t0'] = min(c['t0'], BY_ID[pre]['t0'])
    attach_existing_tz(cands, load_pravki())
    n_fb = apply_feedback(cands)
    for i, c in enumerate(cands, 1):
        c['cand_id'] = f'c{i:04d}'
    return cands, n_fb


def summary(cands, n_fb):
    routes = Counter(c['route'] for c in cands)
    kinds = Counter((c['kind'], c['route']) for c in cands)
    drops = Counter(c.get('drop_class', '?') for c in cands if c['route'] == 'drop')
    cloud_screens = sorted({s for c in cands if c['route'] == 'cloud' for s in c.get('screens', [c['screen_id']])})
    auto = [c for c in cands if c['route'] == 'auto_confirm']
    kk = ['typo', 'grammar', 'currency', 'language', 'fact', 'mismatch', 'foreign_trace']
    lines = [f'route_candidates: экранов {len(ALL)} · кандидатов {len(cands)} · auto {routes["auto_confirm"]} · '
             f'cloud {routes["cloud"]} ({len(cloud_screens)} экр.) · drop {routes["drop"]} · probes {len(PROBES)} · '
             f'pymorphy {"да" if MORPH else "НЕТ"}',
             '  ' + ' | '.join(f'{k} a{kinds[(k, "auto_confirm")]}/c{kinds[(k, "cloud")]}/d{kinds[(k, "drop")]}' for k in kk),
             '  dropped_by_class: ' + ', '.join(f'{k} {v}' for k, v in drops.most_common()) + ' · design/taste: не кандидат'
             + (f' · feedback {n_fb}' if n_fb else ''),
             '  auto_confirm: ' + ' | '.join(f'{c["screen_id"]} {c["kind"]} «{c["on_screen_text"][:22]}»→«{c["fix_local"][:22]}»'
                                          for c in auto)[:900],
             '  cloud: ' + ' '.join(cloud_screens)[:400]]
    return '\n'.join(lines)[:2000]


# ── --eval ─────────────────────────────────────────────────────────────────
KIND_COMPAT = {frozenset(['typo', 'grammar']), frozenset(['typo', 'fact']), frozenset(['fact', 'mismatch']),
               frozenset(['grammar', 'fact']), frozenset(['language', 'other']), frozenset(['typo', 'other']),
               frozenset(['grammar', 'other']), frozenset(['fact', 'other']), frozenset(['mismatch', 'other'])}


def text_sim(a, b):
    sa, sb = sig(a), sig(b)
    if not sa or not sb:
        return 0.0
    if (len(sa) >= 6 and sa in sb) or (len(sb) >= 6 and sb in sa):
        return 1.0
    wa, wb = words_set(a, 2), words_set(b, 2)
    jac = len(wa & wb) / max(1, len(wa | wb)) if wa and wb else 0.0
    return max(ratio(sa, sb), jac)


ROUTE_RANK = {'auto_confirm': 2, 'cloud': 1, 'drop': 0}


def match_finding(f, cands):
    """старая находка ↔ кандидат: тот же экран (или группа экранов) + класс/похожесть текста.
    Экранный кандидат (scope=screen) того же класса считается парой без сравнения текста:
    «экран целиком на английском» и есть решение про этот экран. При равной похожести
    предпочитаем словесный кандидат и более сильный маршрут."""
    best, bs = None, None
    for c in cands:
        if f['screen_id'] not in c.get('screens', [c['screen_id']]):
            continue
        s = text_sim(f.get('on_screen_text') or '', c['on_screen_text'])
        same = f['kind'] == c['kind']
        compat = same or frozenset([f['kind'], c['kind']]) in KIND_COMPAT
        ok = (compat and s >= MATCH_SIM_KIND) or s >= MATCH_SIM_ANY or (same and c['scope'] == 'screen')
        if not ok:
            continue
        key = (round(s, 2) + (0.2 if same else 0), 1 if c['scope'] == 'token' else 0, ROUTE_RANK[c['route']])
        if bs is None or key > bs:
            best, bs = c, key
    return best


def do_eval(path, cands):
    d = json.load(open(path, encoding='utf-8'))
    fs = d['findings']
    drop_classes = set(P.profile('tz_classes.drop', ['design', 'taste', 'pacing', 'layout']) or [])
    mapped, rows, miss_conf, false_auto, conf_hit = 0, [], [], [], Counter()
    conf_nd = [f for f in fs if f.get('confirmed') and f['kind'] not in drop_classes]
    for i, f in enumerate(fs):
        if f['kind'] in drop_classes:
            mapped += 1
            rows.append((i, f, None, 'class_drop'))
            continue
        c = match_finding(f, cands)
        if c is not None:
            mapped += 1
            rows.append((i, f, c, c['route']))
            if f.get('confirmed'):
                conf_hit[c['route']] += 1
                if c['route'] == 'drop':
                    miss_conf.append((i, f, c))
            elif c['route'] == 'auto_confirm':
                false_auto.append((i, f, c))
        else:
            rows.append((i, f, None, 'unmapped'))
            if f.get('confirmed'):
                miss_conf.append((i, f, None))
    routes = Counter(c['route'] for c in cands)
    cloud_screens = sorted({s for c in cands if c['route'] == 'cloud' for s in c.get('screens', [c['screen_id']])})
    rec = conf_hit['auto_confirm'] + conf_hit['cloud']
    print(f'--eval {Path(path).name}: находок {len(fs)} · подтверждённых не-design {len(conf_nd)}')
    print(f'  1) сопоставлено с локальным решением: {mapped}/{len(fs)} (цель ≥45) — '
          f'design→class_drop {sum(1 for r in rows if r[3] == "class_drop")}, '
          f'auto {sum(1 for r in rows if r[3] == "auto_confirm")}, cloud {sum(1 for r in rows if r[3] == "cloud")}, '
          f'drop {sum(1 for r in rows if r[3] == "drop")}, без пары {sum(1 for r in rows if r[3] == "unmapped")}')
    print(f'  2) recall по {len(conf_nd)} подтверждённым: {rec}/{len(conf_nd)} = {100 * rec / max(1, len(conf_nd)):.0f}% '
          f'(auto {conf_hit["auto_confirm"]}, cloud {conf_hit["cloud"]}; цель ≥90%)')
    print(f'  3) облачный список: {routes["cloud"]} кандидатов на {len(cloud_screens)} экранах (цель ≤45)')
    print(f'  4) auto_confirm, опровергнутых старым аудитом: {len(false_auto)} (цель 0)')
    for i, f, c in false_auto:
        print(f'     ✗ #{i} {f["screen_id"]} {f["kind"]} «{f["on_screen_text"][:50]}» ↔ {c["cand_id"]} {c["kind"]} '
              f'«{c["on_screen_text"][:40]}»→«{c["fix_local"][:30]}» [{", ".join(c["signals"][:3])}]')
    print(f'  пропущенные подтверждённые ({len(miss_conf)}):')
    for i, f, c in miss_conf:
        why = f'drop:{c.get("drop_class")} {c["cand_id"]}' if c else 'нет кандидата'
        print(f'     – #{i} {f["screen_id"]} {f["tc"]} {f["kind"]:<9} «{f["on_screen_text"][:48]}» → {why}')
    print('  сопоставление не-design (номер · экран · класс · подтв · локальное решение):')
    for i, f, c, r in rows:
        if r == 'class_drop':
            continue
        cid = f'{c["cand_id"]} {c["kind"]}' if c else '—'
        print(f'     #{i:2d} {f["screen_id"]} {f["kind"]:<9} {"✓" if f.get("confirmed") else "✗"} → {r:<12} {cid}')


# ── --explain ──────────────────────────────────────────────────────────────
def explain(sid, cands):
    sc = next((s for s in ALL if s.id == sid), None)
    if sc is None:
        raise SystemExit(f'нет экрана {sid}')
    print(f'{sc.id} {sc.e["tc"]} t={sc.t0}–{sc.t1} dur={sc.dur} ch{sc.e["chapter"]} faces={sc.e["faces_avg"]} '
          f'best={sc.e["best_frame"]} last={sc.e["last_frame"]} typing_prefix={sc.is_typing_prefix()}')
    for li, l in enumerate(sc.lines):
        print(f'  OCR[{li}] c={l["c"]} x={l["x"]:.3f} y={l["y"]:.3f} w={l["bw"]:.3f} h={l["bh"]:.3f} «{l["t"]}»')
    print('  texts_all:', ' || '.join(sc.e['texts_all'])[:300])
    print('  VLM:', sc.vlm_text.replace('\n', ' / ')[:300])
    print('  VLM desc:', sc.vlm_desc[:160])
    print('  VO ±8:', vo_text(sc.t0, sc.t1, 8)[:300])
    if LANG == 'en':
        vals, ranges, factors = vo_numbers_en(sc.t0, sc.t1)
        print('  числа экрана:', screen_numbers_en(sc.ocr_text), '| суммы:', [(v, c, r) for v, c, r, _s in screen_money_en(sc.ocr_text)],
              '| озвучка:', sorted(vals), ranges, factors, '| суммы озвучки:',
              [(a['v'], a['cur'], a['text']) for a in vo_amounts_en(sc.t0, sc.t1)])
        print(f'  токены ≥4 (EN, словарь {en_dict().name}):')
        for tok in sorted({t for t in tokens(sc.ocr_text) if len(t) >= TYPO_MIN_LEN and (is_lat(t) or RX_MIXED.fullmatch(t))}):
            w = cyr_to_lat(tok)
            k = known_en(w)
            vt, vr = sc.vlm_match(w)
            print(f'    {tok:<20} known={k} vlm={vt}({vr:.2f}) stable={sc.stable(tok)}/{sc.sec_count} '
                  f'near={sorted(en_dict().nearest(w))[:5] if not k else []} vo={None if k else find_correction_en(w, sc.t0, sc.t1)}')
    else:
        vals, ranges, factors = vo_numbers(sc.t0, sc.t1)
        print('  числа экрана:', screen_numbers(sc.ocr_text), '| озвучка:', sorted(vals), ranges, factors)
        print('  токены ≥4:')
        for tok in sorted({t for t in tokens(sc.ocr_text) if len(t) >= TYPO_MIN_LEN and (is_cyr(t) or RX_MIXED.fullmatch(t))}):
            w = homo_to_cyr(tok) if RX_MIXED.fullmatch(tok) else tok
            k = known(w)
            corr = None if k else find_correction(w, sc.t0, sc.t1)
            vt, vr = sc.vlm_match(w)
            print(f'    {tok:<20} known={k} vlm={vt}({vr:.2f}) stable={sc.stable(tok)}/{sc.sec_count} corr={corr}')
    if sc.probe:
        print('  probe:', json.dumps(sc.probe, ensure_ascii=False)[:400])
    if sc.llm:
        llm_keys = ('typos', 'currency_numbers', 'foreign_script', 'severity') if LANG == 'en' else \
            ('typos', 'currency_numbers', 'english_only', 'severity')
        print('  llm:', json.dumps({k: sc.llm.get(k) for k in llm_keys}, ensure_ascii=False)[:300])
    mine = [c for c in cands if sid in c.get('screens', [c['screen_id']])]
    print(f'  кандидаты ({len(mine)}):')
    for c in mine:
        print(f'    {c["cand_id"]} {c["kind"]:<12} {c["route"]:<12} «{c["on_screen_text"][:40]}» → «{c["fix_local"][:40]}» '
              f'[{", ".join(c["signals"])}] — {c["route_reason"]}' + (f' · {c["existing_tz"]}' if c.get('existing_tz') else ''))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--eval', metavar='AUDIT_JSON', help='сверка со старым облачным аудитом')
    ap.add_argument('--explain', metavar='SCREEN_ID', help='сигналы одного экрана')
    ap.add_argument('--out', default=str(OUT), help='куда писать candidates.json')
    a = ap.parse_args()
    cands, n_fb = build()
    if a.explain:
        explain(a.explain, cands)
        return
    if a.eval:
        do_eval(a.eval, cands)
        return
    P.write_json_atomic(Path(a.out), cands)
    routes = Counter(c['route'] for c in cands)
    P.write_json_atomic(OUT_SUMMARY, {
        'screens': len(ALL), 'candidates': len(cands), 'auto_confirmed': routes['auto_confirm'],
        'cloud': routes['cloud'], 'dropped': routes['drop'],
        'dropped_by_class': dict(Counter(c.get('drop_class', '?') for c in cands if c['route'] == 'drop')),
        'cloud_screens': sorted({s for c in cands if c['route'] == 'cloud' for s in c.get('screens', [c['screen_id']])}),
        'zoom_wanted': sum(1 for c in cands if c.get('zoom_wanted')), 'probes': len(PROBES), 'pymorphy': MORPH is not None})
    print(summary(cands, n_fb), flush=True)
    print(f'  → {a.out}', flush=True)


if __name__ == '__main__':
    main()
