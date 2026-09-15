# -*- coding: utf-8 -*-
"""e.* — вердикт и акты: shared/verdict_call.py (записи ТЗ «structure», сводка продюсера, правила для агента),
shared/acts_compact.py (названия актов по умолчанию, n/a-проверка структуры).

RU — байт-в-байт литералы из verdict_call.py (make_entries, rules_text, cmd_apply) и acts_compact.py (load_acts,
structure_checks). Промпты агента вердикта — в cloud/wf_verdict_doc.js (таблицы RU/EN там же, язык — args.lang).
"""

STRINGS = {
    # ── verdict_call.make_entries: ТЗ «Структура» (только если вердикт предложил главы) ─────────────
    'e.structure_title': {'ru': 'Структура: предложенные главы', 'en': 'Structure: proposed chapters'},
    'e.whole_film': {'ru': 'весь фильм', 'en': 'whole film'},
    'e.structure_do': {'ru': 'Поставить карточки глав по списку ниже (порядок ката не меняется, если не сказано иное).',
                       'en': 'Place the chapter cards from the list below (the cut order stays as is unless stated otherwise).'},
    'e.structure_list_h': {'ru': 'Главы (карточки)', 'en': 'Chapters (cards)'},
    # ── verdict_call.make_entries: ТЗ «Открытые вопросы» ─────────────────────────────────────────────
    'e.questions_title': {'ru': 'Открытые вопросы — решения Романа', 'en': 'Open questions — Roman decides'},
    'e.questions_est': {'ru': 'Вердикт оставил вопросы, без ответов правки ниже не закрыть.',
                        'en': 'The verdict left open questions; the fixes below cannot be closed without the answers.'},
    # ── verdict_call.rules_text: блоки правил для агента ─────────────────────────────────────────────
    'e.rules_structure': {'ru': 'ПРАВИЛА СТРУКТУРЫ: ', 'en': 'STRUCTURE RULES: '},
    'e.rules_sensitive': {'ru': 'ЧУВСТВИТЕЛЬНОЕ: политика {policy} — находка = {mark} «на подтверждение фонда / блюр», '
                                'НЕ ⛔; ⛔ только дубли, техбрак и письменные запреты фонда.',
                          'en': 'SENSITIVE: policy {policy} — a hit = {mark} “to be confirmed / blur”, NOT a cut; '
                                'cuts only for duplicates, technical defects and written bans.'},
    'e.rules_notes': {'ru': 'ГРАБЛИ ПРОЕКТА: ', 'en': 'PROJECT NOTES: '},
    # ── verdict_call.cmd_apply: строки producer_summary.lines ────────────────────────────────────────
    'e.summary_counts': {'ru': 'обязательных правок {edits} · глав предложено {chapters} · '
                               'вопросов Роману {questions} · ⚠️ фонд/блюр {sensitive}',
                         'en': 'mandatory fixes {edits} · chapters proposed {chapters} · questions for Roman {questions}'},
    'e.rules_failed': {'ru': 'правила листа нарушены: ', 'en': 'structure rules failed: '},
    # ── acts_compact ─────────────────────────────────────────────────────────────────────────────────
    'e.act_default': {'ru': 'Акт {n}', 'en': 'Act {n}'},
    'e.chapter_default': {'ru': 'Глава {n}', 'en': 'Chapter {n}'},
    'e.no_structure_rules': {'ru': 'в профиле канала нет structure_rules', 'en': 'the channel profile has no structure_rules'},
}
