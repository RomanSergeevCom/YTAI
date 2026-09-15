# -*- coding: utf-8 -*-
"""core.* — общие строки поверхностей: метки блоков ТЗ, названия классов находок, диф опечаток, глава, бейдж драфта.

RU — байт-в-байт литералы из stages/s10_format_tz.py (LBL, KIND_UP, KIND_RU), s8_apply_audit.py (KIND_RU),
typo_diff.py (PRE/MID и закрывающая «»»), make_infographics_v6.py (DRAFT). Пакеты переводят свои файлы на эти
ключи сами; варианты формулировок, которых здесь нет (короткие «факт», «ПЕРЕВЕСТИ» и т.п.), — в своих таблицах.
"""

STRINGS = {
    # ── метки блоков ТЗ (s10 LBL / doc_tab_tz_v3 LABELS без « ·») ─────────────
    'core.lbl_now': {'ru': '❌ СЕЙЧАС', 'en': '❌ NOW'},
    'core.lbl_do': {'ru': '✅ СДЕЛАТЬ', 'en': '✅ DO'},
    'core.lbl_list': {'ru': '📋 СПИСОК', 'en': '📋 LIST'},
    'core.lbl_where': {'ru': '📍 ГДЕ', 'en': '📍 WHERE'},
    'core.lbl_source': {'ru': '📚 ИСТОЧНИК', 'en': '📚 SOURCE'},
    'core.lbl_timeline': {'ru': '🎬 НА ТАЙМЛАЙНЕ', 'en': '🎬 TIMELINE'},
    'core.lbl_comment': {'ru': '💬 РОМА', 'en': '💬 COMMENTS'},

    # ── классы находок, ВЕРХНИЙ регистр (s8 KIND_RU ⊇ s10 KIND_UP) ────────────
    'core.kind_up.typo': {'ru': 'ОПЕЧАТКА', 'en': 'TYPO'},
    'core.kind_up.grammar': {'ru': 'ГРАММАТИКА', 'en': 'GRAMMAR'},
    'core.kind_up.fact': {'ru': 'ФАКТ-ОШИБКА', 'en': 'FACT'},
    'core.kind_up.currency': {'ru': 'ФОРМАТ ВАЛЮТЫ/ЧИСЛА', 'en': 'CURRENCY'},
    'core.kind_up.language': {'ru': 'АНГЛИЙСКИЙ БЕЗ ПЕРЕВОДА', 'en': 'LANGUAGE'},
    'core.kind_up.mismatch': {'ru': 'ЭКРАН ≠ ОЗВУЧКА', 'en': 'SCREEN ≠ VOICE'},
    'core.kind_up.foreign_trace': {'ru': 'ЧУЖОЙ СЛЕД В КАДРЕ', 'en': 'FOREIGN TRACE'},
    'core.kind_up.structure': {'ru': 'СТРУКТУРА', 'en': 'STRUCTURE'},
    'core.kind_up.check_source': {'ru': 'ПРОВЕРИТЬ ИСХОДНИК', 'en': 'CHECK SOURCE'},
    'core.kind_up.design': {'ru': 'ВЁРСТКА', 'en': 'LAYOUT'},
    'core.kind_up.other': {'ru': 'ПРАВКА', 'en': 'EDIT'},

    # ── классы находок, нижний регистр (s10 KIND_RU) ─────────────────────────
    'core.kind_low.typo': {'ru': 'опечатка', 'en': 'typo'},
    'core.kind_low.grammar': {'ru': 'грамматика', 'en': 'grammar'},
    'core.kind_low.fact': {'ru': 'факт-ошибка', 'en': 'fact'},
    'core.kind_low.currency': {'ru': 'формат валюты/числа', 'en': 'currency'},
    'core.kind_low.language': {'ru': 'английский без перевода', 'en': 'language'},
    'core.kind_low.mismatch': {'ru': 'экран ≠ озвучка', 'en': 'screen ≠ voice'},
    'core.kind_low.foreign_trace': {'ru': 'чужой след в кадре', 'en': 'foreign trace'},
    'core.kind_low.structure': {'ru': 'структура', 'en': 'structure'},
    'core.kind_low.check_source': {'ru': 'проверить исходник', 'en': 'check source'},
    'core.kind_low.design': {'ru': 'вёрстка', 'en': 'layout'},
    'core.kind_low.other': {'ru': 'правка', 'en': 'edit'},

    # ── опечатка «было → стало» (typo_diff.PRE / MID / закрывающая кавычка typo_line) ──
    'core.was_pre': {'ru': 'было «', 'en': 'was “'},
    'core.was_mid': {'ru': '» → стало «', 'en': '” → now “'},
    'core.was_post': {'ru': '»', 'en': '”'},

    # ── прочее ───────────────────────────────────────────────────────────────
    'core.chapter': {'ru': 'ГЛАВА', 'en': 'CHAPTER'},
    'core.draft_badge': {'ru': 'DRAFT · ПЕРЕРИСОВАТЬ В СТИЛЕ КАНАЛА', 'en': 'DRAFT · redraw in channel style'},
    'core.tz_prefix': {'ru': 'ТЗ', 'en': 'FIX'},
}
