# -*- coding: utf-8 -*-
"""i18n — язык поверхностей ревью (редакторских и продюсерских) по карточке фильма и профилю канала.

    from _bootstrap import T, LANG, tz_label          # в stages/
    import i18n; i18n.T('core.lbl_now')              # в shared/ или cloud/ (STAGE/shared в sys.path)

LANG = карточка 'lang' → профиль канала 'lang' → 'ru' (окружение YTAI_LANG перебивает карточку, как любой ключ
proj_config). Любое значение, кроме 'en', = 'ru': русские каналы (YTUVI/YTCH/YTEVO) не меняются ни на байт.

T(key, **kw)   строка на LANG; с kw — str.format(**kw). Неизвестный ключ → KeyError. LANG='en' и у ключа нет
               'en' → KeyError (никакой тихой подстановки русского в английский ТЗ).
TL(lang, key, **kw)  то же для явного языка (страницы, где нужны оба).
tz_label(num)  'ТЗ-07' (ru) / 'FIX-07' (en); принимает 7, '07', 'ТЗ-07', 'ТЗ-21b'. Ключи данных «ТЗ-NN» во всех
               JSON остаются как есть — меняется только то, что видит человек.
set_lang(lang) переключить язык процесса (тесты); возвращает прежний.

Таблицы — shared/i18n_strings/<owner>.py (STRINGS = {'<owner>.key': {'ru', 'en'}}), грузятся все модули папки;
ключ обязан начинаться с «<owner>.» (owner = имя файла до первого «_»: d.py и d_nav.py — оба «d»),
дубль ключа между файлами → ImportError.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE = HERE.parent
YTAI = STAGE.parent.parent.parent
TABLES = HERE / 'i18n_strings'
SUPPORTED = ('ru', 'en')


# ── таблицы ──────────────────────────────────────────────────────────────────
def _load_tables():
    strings, owner_of = {}, {}
    for f in sorted(TABLES.glob('*.py')):
        if f.name.startswith('_'):
            continue
        owner = f.stem.split('_')[0]                        # d.py и d_nav.py — оба владельца «d»
        spec = importlib.util.spec_from_file_location(f'ytai_i18n_strings.{f.stem}', f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        table = getattr(mod, 'STRINGS', None)
        if not isinstance(table, dict):
            raise ImportError(f'i18n: {f.name} без словаря STRINGS')
        for k, v in table.items():
            if not str(k).startswith(owner + '.'):
                raise ImportError(f'i18n: ключ «{k}» в {f.name} — ключи этого файла начинаются с «{owner}.»')
            if not isinstance(v, dict) or not (set(v) & set(SUPPORTED)) or set(v) - set(SUPPORTED):
                raise ImportError(f'i18n: {f.name} «{k}» — ожидается {{"ru": …, "en": …}}, а не {v!r:.80}')
            if k in strings:
                raise ImportError(f'i18n: дубль ключа «{k}»: {owner_of[k]} и {f.name}')
            strings[k] = v
            owner_of[k] = f.name
    return strings, owner_of


STRINGS, OWNER = _load_tables()


# ── язык ─────────────────────────────────────────────────────────────────────
def norm_lang(v):
    return 'en' if str(v or '').strip().lower() == 'en' else 'ru'


def _card_light():
    """карточка без proj_config (он падает без карточки): тот же порядок поиска, но без SystemExit"""
    env = os.environ.get('YTAI_CARD')
    cands = []
    if env:
        cands.append(Path(env).expanduser())
    elif os.environ.get('YTAI_PROJECT_DIR'):
        cands.append(Path(os.environ['YTAI_PROJECT_DIR']).expanduser() / '00_Setup' / '05_Review' / 'review_card.json')
    else:
        cur = Path.cwd().resolve()
        for d in (cur, *cur.parents):
            cands += [d / 'review_card.json', d / '00_Setup' / '05_Review' / 'review_card.json']
    for c in cands:
        try:
            if c.is_file():
                return json.loads(c.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def detect_lang():
    pc = sys.modules.get('proj_config')
    if pc is not None and hasattr(pc, 'LANG'):
        return norm_lang(pc.LANG)
    if os.environ.get('YTAI_LANG'):
        return norm_lang(os.environ['YTAI_LANG'])
    card = _card_light()
    if card.get('lang'):
        return norm_lang(card['lang'])
    ch = str(card.get('channel') or '').upper()
    if ch:
        try:
            prof = json.loads((YTAI / 'YTs' / ch / 'review_profile.json').read_text(encoding='utf-8'))
            return norm_lang(prof.get('lang'))
        except Exception:
            pass
    return 'ru'


LANG = detect_lang()


def set_lang(lang):
    global LANG
    old, LANG = LANG, norm_lang(lang)
    return old


# ── API ──────────────────────────────────────────────────────────────────────
def TL(lang, key, **kw):
    entry = STRINGS.get(key)
    if entry is None:
        raise KeyError(f'i18n: нет ключа «{key}»')
    lang = norm_lang(lang)
    if lang not in entry:
        raise KeyError(f'i18n: у «{key}» нет перевода «{lang}» ({OWNER.get(key)})')
    s = entry[lang]
    return s.format(**kw) if kw and isinstance(s, str) else s


def T(key, **kw):
    return TL(LANG, key, **kw)


def has(key, lang=None):
    e = STRINGS.get(key)
    return bool(e) and norm_lang(lang or LANG) in e


def tz_label(num, lang=None):
    """7 / '07' / 'ТЗ-07' / 'ТЗ-21b' → 'ТЗ-07' (ru) или 'FIX-07' (en)."""
    prefix = TL(lang or LANG, 'core.tz_prefix')
    if isinstance(num, int):
        return f'{prefix}-{num:02d}'
    s = str(num).strip()
    for p in ('ТЗ-', 'FIX-'):
        if s.startswith(p):
            s = s[len(p):]
            break
    if s.isdigit():
        return f'{prefix}-{int(s):02d}'
    return f'{prefix}-{s}'


__all__ = ['T', 'TL', 'LANG', 'tz_label', 'set_lang', 'has', 'STRINGS', 'norm_lang', 'detect_lang']
