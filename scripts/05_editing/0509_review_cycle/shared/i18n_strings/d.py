# -*- coding: utf-8 -*-
"""d.* — ревью-таймлайн (make_review_v6.py) и графика ревью (make_infographics_v6.py).

RU — байт-в-байт литералы этих двух файлов (golden review_json / infographics_html). Номер ТЗ на поверхностях —
i18n.tz_label(); метки классов — core.kind_up.*, кроме двух вариантов плашки-стрелки (currency/language), которые
на графике исторически звучат иначе, чем в ТЗ.
"""

STRINGS = {
    # ══ make_review_v6.py — маркеры V4, drop-лог, шапка части, summary.md ══
    'd.rv.decision': {'ru': '\n\n⏳ РЕШЕНИЕ РОМАНА: {text}', 'en': "\n\n⏳ ROMAN'S DECISION: {text}"},
    'd.rv.drop_superseded': {'ru': 'V5: {sid} (ручная стрелка v5) заменена стрелкой аудита',
                             'en': 'V5: {sid} (manual v5 arrow) replaced by the audit arrow'},
    'd.rv.drop_clash': {'ru': '{track}: {sid} выпал (наезд на {other}, нет окна ±{fwd}/{back} с)',
                        'en': '{track}: {sid} dropped (overlaps {other}, no free slot ±{fwd}/{back} s)'},
    'd.rv.note': {'ru': '6 слоёв (канон 07.09) + тикет v6: V1 оригинал не тронут · V2 футажи · V3 инфографика '
                        '(прозрачные панели, термины при каждом упоминании, мини-карты локаций, нарисованные '
                        'исправления) · V4 плашки ТЗ (полный текст+ссылки в маркере мастер-клипа; кнопка панели '
                        '«Copy Brief @ playhead») · V5 стрелки «где ошибка» (аудит всех экранов) · V6 главы + подглавы + '
                        'прогресс перечислений. Маркеры секвенции = ТОЛЬКО {n} глав.',
                  'en': '6 layers + review ticket v6: V1 original untouched · V2 footage · V3 graphics '
                        '(transparent panels, term cards at every mention, location mini-maps, drawn fixes) · '
                        'V4 FIX plates (full text + links in the master-clip marker; panel button '
                        '“Copy @ playhead”) · V5 arrows “where the error is” (audit of all screens) · '
                        'V6 chapters + sub-chapters + list progress. Sequence markers = ONLY {n} chapters.'},
    'd.rv.note_materials': {'ru': ' Материалы с комментами: {url}', 'en': ' Review materials with comments: {url}'},
    'd.rv.tracks': {'ru': 'V1 = оригинал · V2 = футажи · V3 = инфографика+термины+карты+исправления · V4 = ТЗ · '
                          'V5 = стрелки ошибок · V6 = главы/подглавы/прогресс',
                    'en': 'V1 = original · V2 = footage · V3 = graphics+terms+maps+fixes · V4 = FIX notes · '
                          'V5 = error arrows · V6 = chapters/sub-chapters/progress'},
    'd.rv.audio_policy': {'ru': 'A1 (голос) не трогается; звук футажа и CTA → A2; стилы без звука',
                          'en': 'A1 (voice) untouched; footage and CTA audio → A2; stills are silent'},
    'd.rv.md_title': {'ru': '# Review_v6 — 6 слоёв + аудит экранов, термины, карты, подглавы',
                      'en': '# Review_v6 — 6 layers + screen audit, terms, maps, sub-chapters'},
    'd.rv.md_created': {'ru': 'Создан: {created}. Секвенция: `{code}_5_Review_v6_tz_v{{N}}`.',
                        'en': 'Created: {created}. Sequence: `{code}_5_Review_v6_tz_v{{N}}`.'},
    'd.rv.md_counts': {'ru': '- V2 футажи: {v2} · V3 инфографика/термины/карты/исправления: {v3} · V4 ТЗ: {v4} · '
                             'V5 стрелки: {v5} · V6 структура: {v6}.',
                       'en': '- V2 footage: {v2} · V3 graphics/terms/maps/fixes: {v3} · V4 FIX notes: {v4} · '
                             'V5 arrows: {v5} · V6 structure: {v6}.'},
    'd.rv.md_dropped': {'ru': '- Выпало по арбитражу наездов: {n} (см. `dropped` в JSON).',
                        'en': '- Dropped by overlap arbitration: {n} (see `dropped` in the JSON).'},
    'd.rv.md_builder': {'ru': '- Требует partsBuilder ≥1.11.0; текст ТЗ — маркер клипа или кнопка «Copy Brief @ playhead» (панель v2.17.0).',
                        'en': '- Requires partsBuilder ≥1.11.0; FIX text is in the clip marker or the “Copy @ playhead” panel button (panel v2.17.0).'},

    # ══ make_infographics_v6.py ══
    # A. термины
    'd.ig.term_lbl': {'ru': 'ТЕРМИН', 'en': 'TERM'},
    'd.ig.term_lbl_onscreen': {'ru': 'ТЕРМИН · ЧТО НАПИСАНО В КАДРЕ', 'en': 'TERM · AS WRITTEN ON SCREEN'},
    'd.ig.terms_lbl': {'ru': 'ТЕРМИНЫ', 'en': 'TERMS'},
    # B. мини-карты
    'd.ig.where_lbl': {'ru': 'ГДЕ ЭТО', 'en': 'WHERE IS IT'},
    # D. прогресс перечислений
    'd.ig.prog_k_of_n': {'ru': '{k} из {n}', 'en': '{k} of {n}'},
    'd.ig.prog_next': {'ru': 'ЧТО ДАЛЬШЕ', 'en': 'COMING UP'},
    # K. карточка «было → надо» (ТЗ с несколькими заменами в одном кадре)
    'd.ig.wasnow_a': {'ru': 'БЫЛО НА ЭКРАНЕ', 'en': 'ON SCREEN NOW'},
    'd.ig.wasnow_b': {'ru': 'НАДО', 'en': 'SHOULD BE'},
    # G. стрелки / исправления / LT-плашки ТЗ
    'd.ig.kind_currency': {'ru': 'ФОРМАТ ЧИСЛА/ВАЛЮТЫ', 'en': 'CURRENCY'},
    'd.ig.kind_language': {'ru': 'ПЕРЕВЕСТИ', 'en': 'LANGUAGE'},
    'd.ig.fix_badge': {'ru': '✔ ИСПРАВЛЕНО · {num}{extra} · драфт', 'en': '✔ FIXED · {num}{extra} · draft'},
    'd.ig.fix_underlined': {'ru': ' · подчёркнуто — исправлено', 'en': ' · underlined = corrected'},
    'd.ig.fix_var_a': {'ru': ' · вариант А: все цифры', 'en': ' · option A: all digits'},
    'd.ig.fix_var_b': {'ru': ' · вариант Б: «МЛН» + цифрами', 'en': ' · option B: “M” + digits'},
    'd.ig.lt_ico.cut': {'ru': '✂️ РЕЗАТЬ', 'en': '✂️ CUT'},
    'd.ig.lt_ico.insert': {'ru': '➕ ВСТАВИТЬ', 'en': '➕ INSERT'},
    'd.ig.lt_ico.graphics': {'ru': '🎨 ГРАФИКА', 'en': '🎨 GRAPHICS'},
    'd.ig.lt_ico.structure': {'ru': '🧭 СТРУКТУРА', 'en': '🧭 STRUCTURE'},
    'd.ig.lt_ico.color': {'ru': '🎛 ОБРАБОТКА', 'en': '🎛 GRADING'},
    'd.ig.lt_ico.check': {'ru': '🔍 РАЗОБРАНО', 'en': '🔍 REVIEWED'},
    # H. карта структуры + «карта выпуска»
    'd.ig.sm_none': {'ru': '▸ подтем в кате нет — добавить', 'en': '▸ no sub-topics in the cut — add'},
    'd.ig.sm_plus': {'ru': '➕ СОЗДАТЬ', 'en': '➕ CREATE'},
    'd.ig.here': {'ru': 'ВЫ ЗДЕСЬ', 'en': 'YOU ARE HERE'},
    'd.ig.sm_legend_map': {'ru': '«Карта выпуска» — 2–3 сек на каждой смене главы',
                           'en': '“Episode map” — 2–3 s at every chapter change'},
    'd.ig.sm_legend_sub': {'ru': 'плашка подглавы «ГЛАВА NN ▸ подтема» на каждом титульном экране ({n})',
                           'en': 'sub-chapter plate “CHAPTER NN ▸ sub-topic” on every title screen ({n})'},
    'd.ig.sm_legend_prog': {'ru': 'прогресс перечисления гл.{k}: {title} — обзор ДО и подсветка следующего пункта ({n} шт)',
                            'en': 'list progress ch.{k}: {title} — overview BEFORE, then the next item highlighted ({n} items)'},
    'd.ig.sm_legend_new': {'ru': 'гл.{n:02d} — заставки нет в кате, создать',
                           'en': 'ch.{n:02d} — no title card in the cut, create one'},
    # хук и финал главами не нумеруются (решение Романа 22.09.2026) — у них вместо номера эта метка
    'd.ig.sm_no_no': {'ru': 'БЕЗ НОМЕРА', 'en': 'NO NUMBER'},
    'd.ig.sm_h1': {'ru': 'СТРУКТУРА ВЫПУСКА: <span class="r">{nch} ГЛАВ · {nsub} ПОДГЛАВ</span>',
                   'en': 'EPISODE STRUCTURE: <span class="r">{nch} CHAPTERS · {nsub} SUB-CHAPTERS</span>'},
    'd.ig.sm_sub': {'ru': 'кат {tc} · главы = заставки · подглавы = титульные экраны подтем',
                    'en': 'cut {tc} · chapters = title cards · sub-chapters = sub-topic title screens'},
    'd.ig.sm_legend_h': {'ru': 'ЧТО ДОБАВЛЯЕМ ПО СТРУКТУРЕ', 'en': 'WHAT WE ADD TO THE STRUCTURE'},
    'd.ig.sm_foot_plus': {'ru': '➕ = заставки нет в кате, создать', 'en': '➕ = no title card in the cut, create one'},
    'd.ig.vm_h1': {'ru': 'КАРТА <span class="r">ВЫПУСКА</span>', 'en': 'EPISODE <span class="r">MAP</span>'},
    'd.ig.vm_sub': {'ru': '2–3 сек на каждой смене главы', 'en': '2–3 s at every chapter change'},
    'd.ig.vm_foot': {'ru': 'ТЗ-30 · пример «вы здесь» на главе {n:02d}',
                     'en': 'example “you are here” on chapter {n:02d}'},
    # I. карта названий
    'd.ig.nm_head_said': {'ru': 'ЧТО ЗВУЧИТ В ОЗВУЧКЕ', 'en': 'WHAT THE VOICE-OVER SAYS'},
    'd.ig.nm_head_screen': {'ru': 'ЧТО СТАВИМ НА ЭКРАН', 'en': 'WHAT GOES ON SCREEN'},
    'd.ig.nm_h1': {'ru': 'КАРТА <span class="r">НАЗВАНИЙ</span>', 'en': 'NAME <span class="r">MAP</span>'},
    'd.ig.nm_rule': {'ru': 'ПРАВИЛО', 'en': 'RULE'},
    'd.ig.nm_since': {'ru': 'с {tc} · {n} раз', 'en': 'from {tc} · {n}×'},
    'd.ig.nm_since_few': {'ru': 'с {tc} · {n} раза', 'en': 'from {tc} · {n}×'},
    'd.ig.nm_on_screen': {'ru': ' · в кадре: ', 'en': ' · on screen: '},
    'd.ig.nm_read': {'ru': ' · читается «{r}»', 'en': ' · pronounced “{r}”'},
    'd.ig.nm_places_title': {'ru': 'МЕСТА · {n} названий — страна, город, месторождение',
                             'en': 'PLACES · {n} names — country, city, site'},
    'd.ig.nm_places_note': {'ru': 'Современное имя первым, старое в скобках. Город и месторождение всегда подписаны своей страной. '
                                  'Пояснение про переименование — один раз, на первом упоминании.',
                            'en': 'Current name first, old name in brackets. A city or site is always labelled with its country. '
                                  'The renaming note appears once, at the first mention.'},
    'd.ig.nm_places_foot': {'ru': 'ТЗ-76 · канон названий мест', 'en': 'place-name canon'},
    'd.ig.nm_terms_title': {'ru': 'ТЕРМИНЫ 1–{h} из {n} — по порядку появления',
                            'en': 'TERMS 1–{h} of {n} — in order of appearance'},
    'd.ig.nm_terms_note': {'ru': 'Русское название крупно, оригинал мелко под ним, одна строка объяснения простыми словами. '
                                 'Если надпись видна в кадре по-английски — ведём оригиналом и переводим рядом.',
                           'en': 'Term name large, original spelling small beneath it, one line of plain-language explanation.'},
    'd.ig.nm_terms_foot': {'ru': 'ТЗ-75 · канон терминов', 'en': 'term canon'},
    'd.ig.nm_terms2_title': {'ru': 'ТЕРМИНЫ {a}–{n} из {n}', 'en': 'TERMS {a}–{n} of {n}'},
    'd.ig.nm_terms2_note': {'ru': 'Тот же канон: русское имя крупно, оригинал мелко, объяснение одной строкой.',
                            'en': 'Same canon: name large, original small, one-line explanation.'},
}
