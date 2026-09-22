# -*- coding: utf-8 -*-
"""c2.* — вкладка «ТЗ монтажёру» (doc_tab_tz_v3/v4 + verify), навигатор (doc_tab_review_v1), лист (tz_sheet),
комменты Drive (s9_materials_drive), превью дока (s12_doc_previews, preview_qc_local), приёмка PDF (doc_pdf_qc).

RU — байт-в-байт прежние литералы этих файлов (f-строки → шаблоны str.format с теми же именами полей).
Значения могут быть списками (шапки таблиц) и регулярными выражениями (…_rx: берутся T() без kw — без format).
Общие метки блоков, классы находок, «было → стало», глава, префикс ТЗ — в core.py (здесь не дублируются).
"""

STRINGS = {
    # ── общие для дока и листа ───────────────────────────────────────────────
    'c2.qo': {'ru': '«', 'en': '“'},
    'c2.qc': {'ru': '»', 'en': '”'},
    'c2.link_clip': {'ru': '🔗 клип: ', 'en': '🔗 clip: '},
    'c2.link_file': {'ru': '🔗 файл: ', 'en': '🔗 file: '},
    'c2.src_prefix': {'ru': '📚 источник: ', 'en': '📚 source: '},
    'c2.how_to_read': {'ru': 'Как читать:', 'en': 'How to read:'},
    'c2.sprint_default': {'ru': '{ch} S1', 'en': '{ch}'},

    # ── doc_tab_tz_v3: вкладка ТЗ ────────────────────────────────────────────
    'c2.tz_tab_template': {'ru': 'ТЗ монтажёру · {ver}', 'en': 'Edit notes · {ver}'},
    # 9 колонок — раскладка Романа от 22.09.2026: ошибка и лечение разнесены («Описание ошибки»
    # и «Как надо»), у него своя колонка для комментариев и чекбокс приёмки рядом с ней.
    # Номер колонки печатается мелким серым префиксом — просьба Романа «каждый столбик с номером».
    'c2.tz_hdr': {'ru': ['№', '⏱ TC', '', 'Говорит', '✅',
                         'Описание ошибки', 'Материал / ссылки', 'Как надо', 'Комментарии Романа'],
                  'en': ['#', '⏱ TC', '', 'Said', '✅',
                         'What is wrong', 'Material / links', 'How it should be', "Roman's comments"]},
    # Приёмка: состояние чекбокса Docs API НЕ отдаёт — ни в JSON, ни в экспорте. Поэтому решающее
    # действие Романа — удалить лишнюю строку, а галочка рядом только для глаза (22.09.2026).
    'c2.ok_keep': {'ru': 'оставить', 'en': 'keep'},
    'c2.ok_drop': {'ru': 'убрать', 'en': 'drop'},
    'c2.decision_prefix': {'ru': '❓ РЕШЕНИЕ РОМАНА: ', 'en': '❓ DECISION (ROMAN): '},
    'c2.whole_film': {'ru': '⏱ весь фильм', 'en': '⏱ whole film'},
    'c2.tz_head_title': {'ru': '{code} · {tab} — по секвенции Review_v6_tz (формат 11.09)',
                         'en': '{code} · {tab} — for the Review_v6_tz sequence'},
    'c2.tz_head_read1': {'ru': 'каждый таймкод — отдельной строкой: «таймкод ▸ что там», как в карте структуры',
                         'en': 'one timecode per line: “timecode ▸ what is there”, as in the structure map'},
    'c2.tz_head_read2': {'ru': 'справа — крупное превью: наш драфт или стрелка на реальном кадре, кроп на то, о чём речь; '
                               'под ним «таймкод · что видно»',
                         'en': 'right column — a large preview: our draft or an arrow on the real frame, cropped to the '
                               'spot in question; below it “timecode · what you see”'},
    'c2.tz_head_read3': {'ru': 'опечатки — строкой «было → стало»: изменённые знаки выделены в доке красным',
                         'en': 'typos — one line “was → now”: the changed characters are highlighted in red'},
    'c2.tz_head_read4': {'ru': 'суммы — цифрами', 'en': 'amounts — in digits'},
    'c2.tz_head_seq': {'ru': 'Рабочая секвенция: {code}_5_Review_v6_tz_v1 (или последняя _vN) — панель UXP → Review → '
                             'Review_v6. Слои:',
                       'en': 'Working sequence: {code}_5_Review_v6_tz_v1 (or the latest _vN) — UXP panel → Review → '
                             'Review_v6. Tracks:'},
    'c2.tz_head_v1': {'ru': 'V1 — оригинал монтажёра (не тронут)', 'en': 'V1 — your original cut (untouched)'},
    'c2.tz_head_v2': {'ru': 'V2 — футажи: видео и фото', 'en': 'V2 — footage: video and photos'},
    'c2.tz_head_v3': {'ru': 'V3 — инфографика, плашки терминов, мини-карты локаций, нарисованные исправления',
                      'en': 'V3 — infographics, term cards, location mini-maps, drawn fixes'},
    'c2.tz_head_v4': {'ru': 'V4 — плашки ТЗ: полный текст и ссылки (маркер клипа / кнопка панели «Copy ТЗ @ playhead»)',
                      'en': 'V4 — fix cards: full text and links (clip marker, or the panel button “Copy ТЗ @ playhead”)'},
    'c2.tz_head_v5': {'ru': 'V5 — стрелки правок на кадре', 'en': 'V5 — arrows marking the fixes on the frame'},
    'c2.tz_head_v6': {'ru': 'V6 — главы, подглавы, прогресс перечислений гл.{chs}',
                      'en': 'V6 — chapters, sub-chapters, list progress in ch. {chs}'},
    'c2.tz_head_markers': {'ru': 'маркеры секвенции — только {n} разноцветных глав; CTA сразу после рендера',
                           'en': 'sequence markers — only the {n} colour-coded chapters; CTA right after the render'},
    'c2.tz_head_links': {'ru': 'Ссылки:', 'en': 'Links:'},
    'c2.tz_head_sheet': {'ru': 'живой чек-лист со статусами — лист «ТЗ монтажёру»: {url}',
                         'en': 'live checklist with statuses — sheet “{sheet_tab}”: {url}'},
    'c2.tz_head_nav': {'ru': 'полный разбор с транскрибацией — вкладка «{nav}»',
                       'en': 'full breakdown with the transcript — tab “{nav}”'},
    'c2.tz_head_nav_default': {'ru': 'Ревью v2 · правки', 'en': 'Cut review {ver} · by timecode'},
    'c2.tz_head_materials': {'ru': '📁 все материалы (на каждом файле — коммент с ТЗ, таймкодом и источником): {url}',
                             'en': '📁 all materials (each file carries a comment with the fix, timecode and source): {url}'},
    'c2.tz_head_project': {'ru': '📁 папка проекта: {url}', 'en': '📁 project folder: {url}'},
    'c2.tz_head_sprint': {'ru': '📁 спринт {sprint}: {url}', 'en': '📁 sprint {sprint}: {url}'},
    'c2.tz_head_decisions': {'ru': '❓ Решения Романа ({n})', 'en': "❓ Roman's decisions ({n})"},
    'c2.tz_head_rejected': {'ru': '🚫 Снято Романом (09–10.09) — не менять, номера сохранены:',
                            'en': '🚫 Dropped by Roman — do not change; numbering is kept:'},

    # ── doc_tab_review_v1: навигатор ─────────────────────────────────────────
    'c2.nav_tab_default': {'ru': 'Ревью v1 по видео', 'en': 'Cut review {ver} · by timecode'},
    'c2.nav_hdr': {'ru': ['№', '⏱ TC', 'Статус', 'Транскрибация', 'Экран (кадры из ката)', 'Находки / что показать'],
                   'en': ['#', '⏱ TC', 'Status', 'Transcript', 'Screen (frames from the cut)', 'Findings / what to show']},
    'c2.nav_kind.typo': {'ru': 'опечатка', 'en': 'typo'},
    'c2.nav_kind.grammar': {'ru': 'грамматика', 'en': 'grammar'},
    'c2.nav_kind.fact': {'ru': 'факт', 'en': 'fact'},
    'c2.nav_kind.currency': {'ru': 'валюта/число', 'en': 'currency/number'},
    'c2.nav_kind.language': {'ru': 'англ. без перевода', 'en': 'language'},
    'c2.nav_kind.mismatch': {'ru': 'экран ≠ озвучка', 'en': 'screen ≠ voice'},
    'c2.nav_kind.design': {'ru': 'вёрстка', 'en': 'layout'},
    'c2.nav_kind.other': {'ru': 'правка', 'en': 'edit'},
    'c2.nav_ch_findings': {'ru': '{n} находок в главе', 'en': '{n} findings in the chapter'},
    'c2.nav_no_voice': {'ru': '(без озвучки)', 'en': '(no voice-over)'},
    'c2.nav_no_text': {'ru': ' (без текста)', 'en': ' (no text)'},
    'c2.nav_pending': {'ru': '\n(ждёт проверки линзами)', 'en': '\n(awaiting lens check)'},
    # поле {name}, не {key}: «key» — первый аргумент T(key, **kw)
    'c2.nav_term': {'ru': '💡 термин {name}: плашка на {tc}', 'en': '💡 term {name}: card at {tc}'},
    'c2.nav_loc': {'ru': '🗺 локация {name}: мини-карта на {tc}', 'en': '🗺 location {name}: mini-map at {tc}'},
    'c2.nav_head_title': {'ru': '{code} · {tab} — кат v1 целиком, {dur}', 'en': '{code} · {tab} — the whole cut {ver}, {dur}'},
    'c2.nav_head_1': {'ru': '▸ кат в его хронологии: главы — строки с заливкой, подглавы и пункты перечислений — строками ▸',
                      'en': '▸ the cut in its own order: chapters — shaded rows, sub-chapters and list items — rows with ▸'},
    'c2.nav_head_2': {'ru': '▸ «Транскрибация» — полная расшифровка озвучки без пропусков; «Экран» — что в этот момент на экране',
                      'en': '▸ “Transcript” — the full voice-over text with no gaps; “Screen” — what is on screen at that moment'},
    'c2.nav_head_3': {'ru': '▸ «Находки»: ❌ подтверждённая ошибка и ✅ как должно быть; 💡 термин и 🗺 локация — где нужна плашка или карта',
                      'en': '▸ “Findings”: ❌ confirmed error and ✅ how it should be; 💡 term and 🗺 location — where a card or map is needed'},
    'c2.nav_head_4': {'ru': '▸ «Статус» — твоя колонка: ✅ согласен / ⚠️ поправить / ❌ убрать. По ней собираем следующую версию ТЗ',
                      'en': '▸ “Status” — your column: ✅ agree / ⚠️ adjust / ❌ drop. The next version of the notes is built from it'},
    'c2.nav_head_tz': {'ru': 'Короткое ТЗ монтажёру (только правки) — вкладка «{tab}».',
                       'en': 'Short edit notes (fixes only) — tab “{tab}”.'},
    'c2.nav_head_tz_default': {'ru': 'ТЗ монтажёру', 'en': 'Edit notes'},

    # ── tz_sheet: лист ───────────────────────────────────────────────────────
    'c2.sheet_tab': {'ru': 'ТЗ монтажёру', 'en': 'Edit notes'},
    'c2.sheet_hdr': {'ru': ['ТЗ', 'v1 TC', 'Тип', 'Название', 'Что сделать', 'Материал / ссылки',
                            'Кадр 1', 'Кадр 2', 'Кадр 3', '⏳ Решение Романа', 'Статус'],
                     'en': ['#', 'TC', 'Type', 'Title', 'What to do', 'Material / links',
                            'Frame 1', 'Frame 2', 'Frame 3', 'Decision (Roman)', 'Status']},
    'c2.sheet_cat.cut': {'ru': '✂️ резать', 'en': '✂️ cut'},
    'c2.sheet_cat.insert': {'ru': '➕ вставить', 'en': '➕ insert'},
    'c2.sheet_cat.graphics': {'ru': '🎨 графика', 'en': '🎨 graphics'},
    'c2.sheet_cat.structure': {'ru': '🃏 структура', 'en': '🃏 structure'},
    'c2.sheet_cat.color': {'ru': '🔧 обработка', 'en': '🔧 grading'},
    'c2.sheet_cat.check': {'ru': '✅ разобрано', 'en': '✅ reviewed'},
    'c2.sheet_status_decide': {'ru': 'решить', 'en': 'decide'},
    'c2.sheet_legend': {
        'ru': ('Секвенция: {code}_5_Review_v6_tz_v{{N}} (панель UXP → Review → Review_v6). '
               'Слои: V1 = ОРИГИНАЛ (не тронут) · V2 = футажи видео+фото · V3 = инфографика + плашки терминов при каждом упоминании + мини-карты локаций + нарисованные исправления · '
               'V4 = плашки ТЗ (полный текст + ссылки: маркер клипа / кнопка панели «Copy ТЗ @ playhead») '
               '· V5 = стрелки правок на кадре · V6 = прозрачные главы + подглавы + прогресс перечислений. '
               'Маркеры секвенции = только разноцветные главы; '
               'CTA сразу после конца рендера.\n'
               '📁 Все материалы (на каждом файле — коммент с ТЗ и таймкодом): {materials} · '
               '📁 Папка проекта: {project} · 📁 Спринт {sprint_name} (исходники): {sprint}\n'
               'PDF-источники: страницы указаны в материалах. Подробный разбор — вкладка дока '
               '«Ревью v2 · правки»; компакт-ТЗ — вкладка «ТЗ монтажёру · v4».'),
        'en': ('Sequence: {code}_5_Review_v6_tz_v{{N}} (UXP panel → Review → Review_v6). '
               'Tracks: V1 = ORIGINAL (untouched) · V2 = footage video+photo · V3 = infographics + term cards at every mention + location mini-maps + drawn fixes · '
               'V4 = fix cards (full text + links: clip marker / panel button “Copy ТЗ @ playhead”) '
               '· V5 = arrows marking fixes on the frame · V6 = transparent chapters + sub-chapters + list progress. '
               'Sequence markers = colour-coded chapters only; '
               'CTA right after the end of the render.\n'
               '📁 All materials (each file carries a comment with the fix and timecode): {materials} · '
               '📁 Project folder: {project} · 📁 Sprint {sprint_name} (sources): {sprint}\n'
               'Full breakdown — doc tab “{nav_tab}”; compact notes — doc tab “{tz_tab}”.')},

    # ── s9_materials_drive: комменты на файлах Drive ─────────────────────────
    'c2.drv_err': {'ru': '{num} · {tc} · {kind}: {text} — кадр рендера v1 с отметкой места ошибки (стрелка = слой V5 секвенции Review_v6).',
                   'en': '{num} · {tc} · {kind}: {text} — frame of the {ver} render with the error spot marked (arrow = track V5 of the Review_v6 sequence).'},
    'c2.drv_fix': {'ru': '{num} · {tc} · драфт ИСПРАВЛЕННОГО титра (слой V3): {fix}. Перерисовать в стиле канала.',
                   'en': '{num} · {tc} · draft of the CORRECTED title (track V3): {fix}. Redraw in channel style.'},
    'c2.drv_variant': {'ru': '{num} · {tc} · драфт ИСПРАВЛЕНИЯ (слой V3), вариант {v} — сумма цифрами. Роман выбирает А или Б; перерисовать в стиле канала.',
                       'en': '{num} · {tc} · draft FIX (track V3), option {v} — amount in digits. Roman picks A or B; redraw in channel style.'},
    'c2.drv_term': {'ru': 'V3 · термин «{title}» ({sub}) — плашка-определение при каждом упоминании: {tcs}. Прозрачный PNG 4K, драфт — перерисовать в стиле канала.',
                    'en': 'V3 · term “{title}” ({sub}) — definition card at every mention: {tcs}. Transparent 4K PNG, draft — redraw in channel style.'},
    'c2.drv_termgrp': {'ru': 'V3 · группа терминов {keys} @ {tc} — одна плашка на 2–3 определения, прозрачный PNG 4K.',
                       'en': 'V3 · term group {keys} @ {tc} — one card for 2–3 definitions, transparent 4K PNG.'},
    'c2.drv_map': {'ru': 'V3 · мини-карта «{label}» — при каждом упоминании локации: {tcs}. География Natural Earth 50m (public domain), координаты месторождений сверены (GIA/Lotus). Прозрачный PNG 4K.',
                   'en': 'V3 · mini-map “{label}” — at every mention of the location: {tcs}. Geography: Natural Earth 50m (public domain). Transparent 4K PNG.'},
    'c2.drv_map_note': {'ru': 'V3 · мини-карта со сноской про переименование — только на первом упоминании @{tc}. Прозрачный PNG 4K.',
                        'en': 'V3 · mini-map with a renaming footnote — first mention only @{tc}. Transparent 4K PNG.'},
    'c2.drv_fx.mapfull_burma': {'ru': 'V3 · Мьянма (Бирма): Могок и Монг Су на реальной карте @17:27 (замена рисованной схемы 052).',
                                'en': 'V3 · Myanmar (Burma): Mogok and Mong Hsu on a real map @17:27 (replaces hand-drawn scheme 052).'},
    'c2.drv_fx.mapfull_belt': {'ru': 'V3 · «Рубиновый пояс», шаг 1 из 3 @19:30 — Мьянма, Мозамбик, Таиланд и Камбоджа (замена английского титра).',
                               'en': 'V3 · “Ruby belt”, step 1 of 3 @19:30 — Myanmar, Mozambique, Thailand and Cambodia (replaces the English title).'},
    'c2.drv_fx.mapfull_belt_2': {'ru': 'V3 · «Рубиновый пояс», шаг 2 из 3 @19:33 — Вьетнам, Таджикистан, Афганистан, Пакистан, Шри-Ланка.',
                                 'en': 'V3 · “Ruby belt”, step 2 of 3 @19:33 — Vietnam, Tajikistan, Afghanistan, Pakistan, Sri Lanka.'},
    'c2.drv_fx.mapfull_belt_3': {'ru': 'V3 · «Рубиновый пояс», шаг 3 из 3 @19:37 — Танзания, Мадагаскар, Кения, Малави.',
                                 'en': 'V3 · “Ruby belt”, step 3 of 3 @19:37 — Tanzania, Madagascar, Kenya, Malawi.'},
    'c2.drv_fx.info_mohs_what_t': {'ru': 'V3 · «Что такое шкала Мооса» — прозрачная панель по центру (видео видно) @13:56.',
                                   'en': 'V3 · “What is the Mohs scale” — transparent centre panel (video stays visible) @13:56.'},
    'c2.drv_fx.info_synthesis_list_t': {'ru': 'V3 · «3 способа вырастить рубин» — прозрачная панель @30:04.',
                                        'en': 'V3 · “3 ways to grow a ruby” — transparent panel @30:04.'},
    'c2.drv_fx.info_treatments_scheme_t': {'ru': 'V3 · «Обработка рубинов: 6 способов» — прозрачная панель @33:45 и @38:20.',
                                           'en': 'V3 · “Ruby treatments: 6 methods” — transparent panel @33:45 and @38:20.'},
    'c2.drv_fx.info_namemap_places': {'ru': 'Справочник монтажёру · КАРТА НАЗВАНИЙ: места — что звучит в озвучке и что ставим на экран (ТЗ-76).',
                                      'en': 'Editor reference · NAME MAP: places — what is said in the voice-over and what goes on screen (FIX-76).'},
    'c2.drv_fx.info_namemap_terms': {'ru': 'Справочник монтажёру · КАРТА НАЗВАНИЙ: термины, часть 1 (ТЗ-75).',
                                     'en': 'Editor reference · NAME MAP: terms, part 1 (FIX-75).'},
    'c2.drv_fx.info_namemap_terms_2': {'ru': 'Справочник монтажёру · КАРТА НАЗВАНИЙ: термины, часть 2 (ТЗ-75).',
                                       'en': 'Editor reference · NAME MAP: terms, part 2 (FIX-75).'},
    'c2.drv_sub': {'ru': 'V6 · подглава «{label}» (глава {ch:02d}) @{tc} — прозрачная плашка, левый борт.',
                   'en': 'V6 · sub-chapter “{label}” (chapter {ch:02d}) @{tc} — transparent card, left edge.'},
    'c2.drv_prog': {'ru': 'V6 · прогресс перечисления гл.{ch} «{title}»: шаг {k} из {n} — {item}.',
                    'en': 'V6 · list progress ch.{ch} “{title}”: step {k} of {n} — {item}.'},
    'c2.drv_lt': {'ru': '{num} · {tc} · плашка ТЗ (слой V4): {title}.', 'en': '{num} · {tc} · fix card (track V4): {title}.'},

    # ── s12_doc_previews: превью и подписи ───────────────────────────────────
    'c2.pv_att.fix_tz21b': {'ru': 'Драфт: цена Sunrise Ruby — два варианта оформления', 'en': 'Draft: Sunrise Ruby price — two layout options'},
    'c2.pv_att.fix_tz21c': {'ru': 'Драфт: вес Колокола Свободы — 8500 карат', 'en': 'Draft: Liberty Bell Ruby weight — 8,500 carats'},
    'c2.pv_att.fix_tz21d': {'ru': 'Драфт: цена Estrela de Fura — два варианта оформления', 'en': 'Draft: Estrela de Fura price — two layout options'},
    'c2.pv_att.fix_tz31b': {'ru': 'Драфт исправленного титула', 'en': 'Draft of the corrected title'},
    'c2.pv_att.fix_tz32b': {'ru': 'Драфт исправленной плашки', 'en': 'Draft of the corrected card'},
    'c2.pv_att.fix_tz10b': {'ru': 'Драфт: «ШКАЛА МООСА» по-русски', 'en': 'Draft: “MOHS SCALE” in Russian'},
    'c2.pv_src_fix': {'ru': 'наш драфт исправления поверх кадра v1 (слой V3) — перерисовать в стиле канала',
                      'en': 'our draft fix over the cut frame (track V3) — redraw in channel style'},
    'c2.pv_tag_was': {'ru': 'БЫЛО', 'en': 'WAS'},
    'c2.pv_tag_now': {'ru': 'СТАЛО', 'en': 'NOW'},
    'c2.pv_tag_opt_a': {'ru': 'ВАРИАНТ А', 'en': 'OPTION A'},
    'c2.pv_tag_opt_b': {'ru': 'ВАРИАНТ Б', 'en': 'OPTION B'},
    'c2.pv_cap_wasnow': {'ru': 'было / стало', 'en': 'was / now'},
    'c2.pv_cap_wasvar': {'ru': 'было / варианты А и Б', 'en': 'was / options A and B'},
    'c2.pv_cap_err': {'ru': 'где ошибка (стрелка на кадре)', 'en': 'error spot (arrow on the frame)'},
    'c2.pv_short_rx': {'ru': r'^(Драфт(?:-мокап)?|Мокап|Кадр|Пример кадра)\s*[:—-]?\s*',
                       'en': r'^(Draft(?: mockup)?|Mockup|Frame|Example frame|Драфт(?:-мокап)?|Мокап|Кадр|Пример кадра)\s*[:—-]?\s*'},
    'c2.pv_auto_rx': {'ru': r'^\s*[•·—:-]*\s*(Драфт(?:-мокап)?|Мокап|Кадр(?: ката)?|Пример кадра|Реф)\b\s*[:—-]?\s*',
                      'en': r'^\s*[•·—:-]*\s*(Draft(?: mockup)?|Mockup|Frame(?: of the cut)?|Cut frame|Example frame|Ref|'
                            r'Драфт(?:-мокап)?|Мокап|Кадр(?: ката)?|Пример кадра|Реф)\b\s*[:—-]?\s*'},

    # ── preview_qc_local: подписи «таймкод · что видно» ──────────────────────
    'c2.pq_title_rx': {'ru': r'^[А-ЯЁ /-]+:\s*', 'en': r'^[А-ЯЁA-Z][А-ЯЁA-Z ≠/-]*:\s*'},
    'c2.pq_quoted_rx': {'ru': r'«([^»]{2,})»', 'en': r'[«“]([^»”]{2,})[»”]'},
    'c2.pq_term': {'ru': 'плашка термина {q}', 'en': 'term card {q}'},
    'c2.pq_term0': {'ru': 'плашка термина', 'en': 'term card'},
    'c2.pq_termgrp': {'ru': 'плашка терминов: {qs}', 'en': 'term cards: {qs}'},
    'c2.pq_termgrp0': {'ru': 'плашка терминов', 'en': 'term cards'},
    'c2.pq_map': {'ru': 'карта {q}', 'en': 'map {q}'},
    'c2.pq_map0': {'ru': 'мини-карта', 'en': 'mini-map'},
    'c2.pq_mapfull': {'ru': 'карта региона', 'en': 'regional map'},
    'c2.pq_sub': {'ru': 'подглава {q}', 'en': 'sub-chapter {q}'},
    'c2.pq_sub0': {'ru': 'плашка подглавы', 'en': 'sub-chapter card'},
    'c2.pq_prog': {'ru': 'прогресс {q} · {k} из {n} · {it}', 'en': 'progress {q} · {k} of {n} · {it}'},
    'c2.pq_prog_short': {'ru': 'прогресс · {k} из {n}', 'en': 'progress · {k} of {n}'},
    'c2.pq_prog0': {'ru': 'плашка прогресса', 'en': 'progress card'},
    'c2.pq_chmap': {'ru': 'карта главы {n} {q}', 'en': 'chapter {n} map {q}'},
    'c2.pq_chmap0': {'ru': 'карта главы', 'en': 'chapter map'},
    'c2.pq_structmap': {'ru': 'карта структуры фильма', 'en': 'film structure map'},
    'c2.pq_fix_wasnow': {'ru': 'было {qw} → стало {qn}', 'en': 'was {qw} → now {qn}'},
    'c2.pq_fix_now': {'ru': 'было → стало {qn}', 'en': 'was → now {qn}'},
    'c2.pq_fix_text': {'ru': 'было / стало: {q}', 'en': 'was / now: {q}'},
    'c2.pq_err_q': {'ru': 'где ошибка: {q}', 'en': 'error spot: {q}'},
    'c2.pq_lt': {'ru': 'плашка {num} на кадре', 'en': '{num} card on the frame'},
    'c2.pq_ch': {'ru': 'глава {n} {q}', 'en': 'chapter {n} {q}'},
    'c2.pq_ch0': {'ru': 'карточка главы', 'en': 'chapter card'},
    'c2.pq_frame_x': {'ru': 'кадр: {x}', 'en': 'frame: {x}'},
    'c2.pq_frame_tz': {'ru': 'кадр ТЗ', 'en': 'fix frame'},
    'c2.pq_frame': {'ru': 'кадр', 'en': 'frame'},

    # ── doc_pdf_qc: разбор PDF вкладки ───────────────────────────────────────
    'c2.qc_quote_rx': {'ru': r'«[^«»]*»', 'en': r'«[^«»]*»|“[^“”]*”'},
}
