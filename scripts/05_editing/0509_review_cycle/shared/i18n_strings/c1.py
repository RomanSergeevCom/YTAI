# -*- coding: utf-8 -*-
"""c1.* — текст ТЗ (pravki): s8_apply_audit (сборка записи из находок) и s10_format_tz (parts → nado).

RU — байт-в-байт литералы из stages/s8_apply_audit.py и stages/s10_format_tz.py (f-строки стали шаблонами
str.format с теми же подстановками). Метки блоков и названия классов — core.* (не дублируем).
Экранный текст в EN цитируется “…” (как core.was_pre/was_mid), в RU — «…», как было.
"""

STRINGS = {
    # ── общие для s8 и s10 ───────────────────────────────────────────────────
    'c1.title': {'ru': '{kind}: «{text}»', 'en': '{kind}: “{text}”'},
    'c1.now_h': {'ru': '«{text}» — {kind}', 'en': '“{text}” — {kind}'},
    'c1.do_replace': {'ru': 'Заменить титр на «{fix}»', 'en': 'Replace the on-screen text with “{fix}”'},
    # Что делать, когда судья дал только описание ошибки. Ключ — класс находки; без ключа
    # блок ✅ остаётся пустым (и verify это ловит: «у каждого ТЗ непустое Как надо»).
    'c1.do_default.language': {
        'ru': 'Дать русский слой: русский текст крупно, английский оставить вторым и мельче — правило канала.',
        'en': 'Add the channel language layer: local text large, the foreign original second and smaller.'},
    'c1.do_default.foreign_trace': {
        'ru': 'Убрать чужой след из кадра: перекрыть, обрезать или заменить материал.',
        'en': 'Remove the foreign mark from the frame: cover, crop or replace the material.'},
    'c1.where_anchor': {'ru': ' · якорь: «{anc}»', 'en': ' · voice anchor: “{anc}”'},
    'c1.tl_arrow': {'ru': 'стрелка «где ошибка» — слой V5 ревью-секвенции',
                    'en': 'arrow “where the error is” — layer V5 of the review sequence'},
    'c1.tl_draft': {'ru': 'драфт исправленного титра — слой V3 (fix_{fn}.png)',
                    'en': 'draft of the corrected on-screen text — layer V3 (fix_{fn}.png)'},

    # ── s8_apply_audit: запись pravki из находок ─────────────────────────────
    'c1.s8.line_head': {'ru': '[{kind}] «{text}»', 'en': '[{kind}] “{text}”'},
    'c1.s8.line_fix': {'ru': ' → «{fix}»', 'en': ' → “{fix}”'},
    'c1.s8.line_src': {'ru': ' Источник: {src}', 'en': ' Source: {src}'},
    'c1.s8.check_source_fix': {'ru': 'проверить исходник титра', 'en': 'check the source of this on-screen text'},
    'c1.s8.est': {'ru': 'На экране @{tc}: «{text}».', 'en': 'On screen @{tc}: “{text}”.'},
    'c1.s8.nado_anchor': {'ru': '\nЯкорь озвучки: «{anc}».', 'en': '\nVoice anchor: “{anc}”.'},
    'c1.s8.nado_draft': {'ru': '\nДрафт исправления — на V3 (fix_{fn}.png), стрелка — на V5.',
                         'en': '\nDraft fix on V3 (fix_{fn}.png), arrow on V5.'},
    'c1.s8.nado_arrow': {'ru': '\nСтрелка «где ошибка» — на V5.', 'en': '\nArrow “where the error is” on V5.'},
    'c1.s8.mat_frame': {'ru': 'Кадр {tc} с отметкой ошибки (стрелка)', 'en': 'Frame {tc} with the error marked (arrow)'},
    'c1.s8.mat_draft': {'ru': 'Драфт исправленного титра ({fix})', 'en': 'Draft of the corrected on-screen text ({fix})'},
    'c1.s8.ann_text': {'ru': '«{was}» → «{now}»', 'en': '“{was}” → “{now}”'},

    # ── s10_format_tz ────────────────────────────────────────────────────────
    'c1.s10.links': {'ru': 'ссылки', 'en': 'links'},
    'c1.s10.typo_h': {'ru': 'Исправить (в доке изменённые знаки выделены красным):',
                      'en': 'Fix (changed characters are highlighted in red in the doc):'},
    # «исправление» начинается с глагола-инструкции → это не титр, «Заменить титр на …» не оборачиваем
    'c1.s10.do_verbs': {'ru': ['заменить', 'убрать', 'сдвинуть', 'перерисовать', 'добавить'],
                        'en': ['replace', 'remove', 'move', 'redraw', 'add', 'delete', 'change', 'fix', 'check',
                               'use', 'keep', 'translate', 'rewrite', 'align', 'swap']},
}
