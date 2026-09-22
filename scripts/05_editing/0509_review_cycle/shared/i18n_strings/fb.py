# -*- coding: utf-8 -*-
"""fb.* — «Обратная связь по кату vN» (контракт docs/feedback_v1.md): общий слой shared/feedback_view.py и две его
поверхности — HTML-страница продюсера (shared/feedback_page.py) и вкладка дока монтажёру (stages/doc_tab_feedback_v1.py).

Зачем отдельный владелец: жанра «сверка версий» в каноне 5.6 нет, его слова живут здесь и нигде не дублируются.
Метки блоков (❌ СЕЙЧАС / ✅ СДЕЛАТЬ / 📍 ГДЕ), «было → стало», «ГЛАВА», префикс ТЗ — в core.py.
RU — полные рабочие строки; EN — короткие рабочие (selftest review.py требует en у каждого ru).
Значения-списки — формы числа: ru [1, 2–4, 5+], en [1, много]; их выбирает feedback_view.plural().
Запрещено в видимом тексте: жаргон движка (имена кадров, названия проходов и полей модели).
"""

STRINGS = {
    # ── имена и шапка ────────────────────────────────────────────────────────
    'fb.tab_template': {'ru': 'Обратная связь · {ver}', 'en': 'Feedback · {ver}'},
    'fb.doc_title': {'ru': 'Обратная связь по кату {ver} · {code}', 'en': 'Feedback on cut {ver} · {code}'},
    'fb.page_title': {'ru': '{code} · обратная связь {ver}', 'en': '{code} · feedback {ver}'},
    'fb.version_line': {'ru': 'кат {ver} против {prev} · собрано {dt} · сборка {n}',
                        'en': 'cut {ver} vs {prev} · built {dt} · build {n}'},
    'fb.version_line_noprev': {'ru': 'кат {ver} · собрано {dt} · сборка {n}', 'en': 'cut {ver} · built {dt} · build {n}'},
    'fb.tally_line': {'ru': 'Из {total} пунктов прошлого ТЗ: закрыто {closed} · осталось {open} · {fund} ждёт ответа '
                            'фонда · {unknown} не проверено. Новых — {new}.',
                      'en': 'Of {total} previous notes: closed {closed} · still open {open} · {fund} waiting for the '
                            'foundation · {unknown} not checked. New — {new}.'},
    'fb.tally_new_only': {'ru': 'Прошлого ТЗ для сверки нет. Новых пунктов — {new}.',
                          'en': 'No previous notes to check against. New notes — {new}.'},
    'fb.hold_edit': {'ru': 'Держит выпуск — монтаж:', 'en': 'Blocks release — editing:'},
    'fb.hold_edit_none': {'ru': 'Держит выпуск — монтаж: таких пунктов нет', 'en': 'Blocks release — editing: nothing'},
    'fb.hold_other': {'ru': ['Держит выпуск — не монтаж: {n} пункт ждёт ответа юриста фонда (Роман)',
                             'Держит выпуск — не монтаж: {n} пункта ждут ответа юриста фонда (Роман)',
                             'Держит выпуск — не монтаж: {n} пунктов ждёт ответа юриста фонда (Роман)'],
                      'en': ['Blocks release — not editing: {n} note waits for the foundation lawyer (Roman)',
                             'Blocks release — not editing: {n} notes wait for the foundation lawyer (Roman)']},
    'fb.warn_copy': {'ru': 'Часть 1 — копия вкладки „{tz_tab}“ на момент сборки; отметки и комментарии — только там, '
                           'эта вкладка пересобирается кодом',
                     'en': 'Part 1 is a copy of the “{tz_tab}” tab at build time; marks and comments go there only — '
                           'this tab is rebuilt by code'},
    'fb.warn_copy_html': {'ru': 'Часть 1 — копия вкладки „{tz_tab}“ на момент сборки; отметки и комментарии — только '
                                'там, эта страница пересобирается кодом',
                          'en': 'Part 1 is a copy of the “{tz_tab}” tab at build time; marks and comments go there '
                                'only — this page is rebuilt by code'},
    'fb.frames_in_html': {'ru': 'кадры — в HTML-файле', 'en': 'frames — in the HTML file'},

    # ── «Как читать» (первая строка — заголовок) ─────────────────────────────
    'fb.how_head': {'ru': 'Как читать:', 'en': 'How to read:'},
    'fb.how_tc': {'ru': 'все таймкоды — по новому кату {ver}; знак «≈» перед таймкодом — место найдено '
                        'приблизительно, сверь по кадру',
                  'en': 'all timecodes refer to the new cut {ver}; “≈” before a timecode — the spot is approximate, '
                        'check the frame'},
    'fb.how_blocks': {'ru': 'в пункте: ❌ СЕЙЧАС — что в кате, ✅ СДЕЛАТЬ — действие, 📍 ГДЕ — место; строка под '
                            'заголовком — на чём основан вывод',
                      'en': 'in a note: ❌ NOW — what is in the cut, ✅ DO — the action, 📍 WHERE — the spot; the line '
                            'under the title — what the conclusion rests on'},
    'fb.how_typo': {'ru': 'опечатки: красным жирным — как «было», зелёным жирным — как «стало»',
                    'en': 'typos: bold red — as it was, bold green — as it should be'},
    'fb.how_nums': {'ru': '🔴 у номера — без этой правки фильм не выпускаем; «{label_new}» — номер в новом ТЗ, '
                          '«{label_prev}» — номер в прошлом ТЗ',
                    'en': '🔴 next to a number — no release without this fix; “{label_new}” — number in the new notes, '
                          '“{label_prev}” — number in the previous notes'},

    # ── секции (порядок — feedback_view.ORDER) ───────────────────────────────
    'fb.sec.new': {'ru': 'ЧАСТЬ 1 · НОВОЕ В {ver}', 'en': 'PART 1 · NEW IN {ver}'},
    'fb.part2': {'ru': 'ЧАСТЬ 2 · ПРОВЕРКА ТЗ {prev}', 'en': 'PART 2 · CHECK OF {prev} NOTES'},
    'fb.part2_sub': {'ru': 'каждый пункт прошлого ТЗ проверен заново по новому кату',
                     'en': 'every previous note re-checked against the new cut'},
    'fb.sec.block': {'ru': '🔴 БЛОКИРУЕТ ВЫПУСК', 'en': '🔴 BLOCKS RELEASE'},
    'fb.sec.open': {'ru': '❌ ОСТАЛОСЬ', 'en': '❌ STILL OPEN'},
    'fb.sec.blur': {'ru': '⚠️ БЛЮР И ОБЕЗЛИЧИВАНИЕ — делает монтажёр, не дожидаясь фонда',
                    'en': '⚠️ BLUR AND ANONYMISING — the editor does it without waiting for the foundation'},
    'fb.sec.closed': {'ru': '✅ ЗАКРЫТО', 'en': '✅ CLOSED'},
    'fb.sec.fund': {'ru': '⚠️ ЖДЁТ ОТВЕТА ФОНДА', 'en': '⚠️ WAITING FOR THE FOUNDATION'},
    'fb.sec.appendix': {'ru': 'Не проверено автоматически — смотрит Роман',
                        'en': 'Not checked automatically — Roman looks'},
    # короткие имена для строки навигации HTML
    'fb.nav.new': {'ru': 'Новое', 'en': 'New'},
    'fb.nav.block': {'ru': '🔴 Блокирует', 'en': '🔴 Blocks'},
    'fb.nav.open': {'ru': '❌ Осталось', 'en': '❌ Open'},
    'fb.nav.blur': {'ru': '⚠️ Блюр', 'en': '⚠️ Blur'},
    'fb.nav.closed': {'ru': '✅ Закрыто', 'en': '✅ Closed'},
    'fb.nav.fund': {'ru': '⚠️ Фонд', 'en': '⚠️ Foundation'},
    'fb.nav.appendix': {'ru': 'Не проверено', 'en': 'Not checked'},

    # ── строки пунктов ───────────────────────────────────────────────────────
    'fb.more_line': {'ru': ['ещё {n} строка — вкладка ТЗ {prev}, {label}', 'ещё {n} строки — вкладка ТЗ {prev}, {label}',
                            'ещё {n} строк — вкладка ТЗ {prev}, {label}'],
                     'en': ['{n} more line — notes tab {prev}, {label}', '{n} more lines — notes tab {prev}, {label}']},
    'fb.more_line_nover': {'ru': ['ещё {n} строка — {label}', 'ещё {n} строки — {label}', 'ещё {n} строк — {label}'],
                           'en': ['{n} more line — {label}', '{n} more lines — {label}']},
    'fb.dup_line': {'ru': 'не закрыто · перенесено в новое {label} (Часть 1)',
                    'en': 'not closed · moved to the new {label} (Part 1)'},
    'fb.num_prev': {'ru': '{label} · {prev}', 'en': '{label} · {prev}'},
    # строки ✅, которые модель формулирует сама (feedback_model: частично выполненный пункт, отсылка, пустой ✅)
    'fb.do_missing': {'ru': 'Добавить недостающее: ', 'en': 'Add what is missing: '},
    'fb.do_more': {'ru': ' и ещё {n}', 'en': ' and {n} more'},
    'fb.do_more_only': {'ru': 'нет {n}', 'en': '{n} missing'},
    'fb.do_see': {'ru': 'Полный список недостающего — {label}', 'en': 'Full list of what is missing — {label}'},
    'fb.now_done': {'ru': 'Сделано: {what}.', 'en': 'Done: {what}.'},
    'fb.now_lack': {'ru': 'Не хватает: {what}.', 'en': 'Missing: {what}.'},
    'fb.do_derived': {'ru': 'Исправить: {what}', 'en': 'Fix: {what}'},
    # правила канала человеческими словами (строки вердикта)
    'fb.rule.fund_entry_min': {'ru': 'фонд входит раньше {thr}-й минуты', 'en': 'the foundation enters before minute {thr}'},
    'fb.rule.fund_entry_min_nothr': {'ru': 'фонд входит слишком рано', 'en': 'the foundation enters too early'},
    'fb.rule.last_sound_rule': {'ru': 'фильм кончается призывом о деньгах', 'en': 'the film ends on a call for money'},
    'fb.rule.teaser_rule': {'ru': 'тизер целиком из бед', 'en': 'the teaser is all hardship'},
    'fb.rule.fund_piece_max_sec': {'ru': 'непрерывный кусок фонда длиннее {thr} с',
                                   'en': 'an unbroken foundation piece is longer than {thr} s'},
    'fb.rule.fund_piece_max_sec_nothr': {'ru': 'непрерывный кусок фонда слишком длинный',
                                         'en': 'an unbroken foundation piece is too long'},
    'fb.topic_other': {'ru': 'Прочие согласования', 'en': 'Other approvals'},
    'fb.no_tc_group': {'ru': 'БЕЗ ТАЙМКОДА', 'en': 'NO TIMECODE'},
    'fb.show_list': {'ru': 'показать список', 'en': 'show the list'},
    'fb.verdict_head': {'ru': 'Вердикт по новому кату', 'en': 'Verdict on the new cut'},

    # ── вкладка дока, 6 колонок (контракт §8, решение Романа 22.09.2026) ─────
    'fb.col.num': {'ru': '№', 'en': '№'},
    'fb.col.tc': {'ru': '⏱ TC', 'en': '⏱ TC'},
    'fb.col.said': {'ru': 'Говорит', 'en': 'Says'},
    'fb.col.verdict': {'ru': 'Вердикт и почему', 'en': 'Verdict and why'},
    'fb.col.err': {'ru': 'Экран с ошибкой', 'en': 'Screen with the error'},
    'fb.col.fix': {'ru': 'Как надо', 'en': 'How it should be'},
    # первая строка колонки «Вердикт и почему» — цветом: was / now / warn / muted (doc_table)
    'fb.verdict.wrong': {'ru': '❌ НЕПРАВИЛЬНО', 'en': '❌ WRONG'},
    'fb.verdict.right': {'ru': '✅ ПРАВИЛЬНО', 'en': '✅ RIGHT'},
    'fb.verdict.fund': {'ru': '⚠️ ЖДЁТ ФОНДА', 'en': '⚠️ WAITING FOR THE FOUNDATION'},
    'fb.verdict.blur': {'ru': '⚠️ БЛЮР — делает монтажёр', 'en': '⚠️ BLUR — the editor does it'},
    'fb.verdict.unchecked': {'ru': '👁 НЕ ПРОВЕРЕНО', 'en': '👁 NOT CHECKED'},
    'fb.why': {'ru': 'Почему:', 'en': 'Why:'},
    'fb.source': {'ru': 'Источник:', 'en': 'Source:'},
    'fb.how_fix': {'ru': 'Как надо', 'en': 'How it should be'},
    'fb.how_verdict': {'ru': 'колонка «Вердикт и почему»: первая строка — вердикт цветом (красный — неправильно, '
                             'зелёный — правильно, оранжевый — ждёт фонда или блюр, серый — не проверено); '
                             '«Говорит» — дословная речь ката вокруг таймкода, опорная фраза жирным',
                       'en': '“Verdict and why” column: the first line is the verdict in colour (red — wrong, green — '
                             'right, orange — waiting for the foundation or blur, grey — not checked); “Says” — verbatim '
                             'speech of the cut around the timecode, the anchor phrase in bold'},
    'fb.how_screens': {'ru': '«Экран с ошибкой» — кадр нового ката, где ошибка; «Как надо» — действие, место и картинка-'
                             'рекомендация с источником',
                       'en': '“Screen with the error” — the frame of the new cut with the error; “How it should be” — '
                             'the action, the spot and a recommendation picture with its source'},

    # ── подписи кадров (шаблон канона «M:SS · что видно») ────────────────────
    'fb.cap': {'ru': '{tc} · {what}', 'en': '{tc} · {what}'},
    'fb.cap_default': {'ru': 'кадр ката {ver}', 'en': 'frame of cut {ver}'},
    'fb.cap_default_nover': {'ru': 'кадр нового ката', 'en': 'frame of the new cut'},

    # ── сообщения страницы и отправки ────────────────────────────────────────
    'fb.send_caption': {'ru': '{code} · обратная связь по кату {ver} · сборка {n}',
                        'en': '{code} · feedback on cut {ver} · build {n}'},
    'fb.too_big': {'ru': 'страница {kb} КБ больше бюджета {max_kb} КБ даже на запасной ступени — файл не записан',
                   'en': 'page {kb} KB exceeds the {max_kb} KB budget even at the fallback step — file not written'},

    # ── визуалы колонок 5–6 (shared/feedback_visuals.py, контракт §9) ────────
    'fb.vis.cap_fix': {'ru': 'как надо: {what}', 'en': 'should be: {what}'},
    'fb.vis.src_frame': {'ru': 'кадр ката {ver}, {tc}', 'en': 'frame of cut {ver}, {tc}'},
    'fb.vis.src_preview': {'ru': 'превью стадии: {path}', 'en': 'stage preview: {path}'},
    'fb.vis.src_mockup': {'ru': 'мокап стадии: {path}', 'en': 'stage mockup: {path}'},
    'fb.vis.src_on_frame': {'ru': '{src} поверх кадра {ver} {tc}', 'en': '{src} over frame {ver} {tc}'},
    'fb.vis.src_reference': {'ru': 'референс: {url}', 'en': 'reference: {url}'},
    'fb.vis.src_draft': {'ru': 'наш драфт по кадру {ver} {tc}; текст — {label}',
                         'en': 'our draft on frame {ver} {tc}; text — {label}'},
    'fb.vis.src_draft_noframe': {'ru': 'наш драфт; текст — {label}', 'en': 'our draft; text — {label}'},
    'fb.vis.src_plus_ref': {'ru': '{src} · референс: {url}', 'en': '{src} · reference: {url}'},
    'fb.vis.none_no_tc': {'ru': 'у пункта нет времени в новом кате', 'en': 'the note has no time in the new cut'},
    'fb.vis.none_no_frame': {'ru': 'кадра нового ката на {tc} нет на этом компьютере',
                             'en': 'no frame of the new cut at {tc} on this computer'},
    'fb.vis.draft_head': {'ru': 'КАК НАДО', 'en': 'SHOULD BE'},
    'fb.vis.draft_cut': {'ru': 'вырезать {rng}', 'en': 'cut {rng}'},
    'fb.vis.draft_badge': {'ru': 'DRAFT · перерисовать в стиле канала', 'en': 'DRAFT · redraw in channel style'},
    'fb.vis.what_frame': {'ru': 'кадр на месте пункта', 'en': 'frame at the note'},
}
