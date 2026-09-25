# -*- coding: utf-8 -*-
"""chp.* — вкладка «Главы · {ver}» (stages/doc_tab_chapters_v1.py): карта выпуска, варианты заставки,
панели перечислений, таблица глав и подглав.

Вкладка писалась 22.09.2026 под YTUVI (русский канал) литералами, и на английском канале отдавала
русский текст монтажёру (22.09.2026, YTCR04 v5: 185 кириллических слов в собранной вкладке).
RU-значения здесь — байт-в-байт прежние литералы. Операторские логи скрипта остаются русскими:
они для Романа, а не для монтажёра (канон §10 contracts.md).
"""

STRINGS = {
    # ── шапка вкладки и колонки таблицы ──────────────────────────────────────────────────────────
    'chp.tab_title': {'ru': 'Главы · {ver}', 'en': 'Chapters · {ver}'},
    'chp.hdr_frame': {'ru': 'Кадр из ката', 'en': 'Frame from the cut'},
    'chp.hdr_body': {'ru': 'Глава и подглавы', 'en': 'Chapter and subchapters'},
    'chp.hdr_now': {'ru': 'Что сейчас', 'en': 'What it is now'},
    'chp.hdr_do': {'ru': 'Как надо', 'en': 'What it should be'},
    'chp.hdr_card': {'ru': 'Заставка · пример', 'en': 'Title card · example'},
    'chp.map_h_nosub': {'ru': 'КАРТА ВЫПУСКА — глав: {ch}', 'en': 'EPISODE MAP — chapters: {ch}'},
    # шапка режима заставок считается по фильму: `chp.lead`/`lead2` — утверждения про YTUVI01
    # («несогласованы», «светлый по светлому»), на другом фильме они врут
    'chp.lead_cards': {'ru': 'Кат {ver}, {dur}. Глав {n}: заставки в кате есть у {have}, создать {new}. '
                             'У каждой главы и подглавы ниже — готовая заставка крупно, на своём кадре из ката. '
                             'Где под карточку нет паузы — это сказано в «Как надо».',
                       'en': 'Cut {ver}, {dur}. {n} chapters: {have} have a plate in the cut, {new} to create. '
                             'Every chapter and subchapter below shows its ready plate, large, on its own frame. '
                             'Where the cut has no pause for the plate, “What it should be” says so.'},
    'chp.film_h': {'ru': 'НАЗВАНИЕ ФИЛЬМА «{title}» — выбрать вариант',
                   'en': 'FILM TITLE “{title}” — pick a variant'},
    'chp.film_lead': {'ru': 'Название встаёт сразу после хука, как ты просил. Три подачи на одном кадре '
                            'начала фильма; шрифт фонда Montserrat 900, кегль подобран под кадр.',
                      'en': 'The title goes right after the hook. Three treatments on the same opening '
                            'frame; fund typeface Montserrat 900, size fitted to the frame.'},
    'chp.head_title': {'ru': '{code} · {tab} — все главы фильма и дизайн заставок',
                       'en': '{code} · {tab} — every chapter of the film and the plate design'},
    'chp.lead': {'ru': 'Кат {ver}, {dur}. Заставки глав в кате несогласованы. ',
                 'en': 'Cut {ver}, {dur}. The chapter plates in the cut are inconsistent. '},
    'chp.lead2': {'ru': 'Оба приёма — светлый текст по светлому кадру, контраста не хватает. ',
                  'en': 'Both devices put light text over a light frame — not enough contrast. '},
    'chp.lead3': {'ru': 'Здесь всё про главы в одном месте: что в кате сейчас, что надо, '
                        'и как выглядит новая заставка.',
                  'en': 'Everything about the chapters in one place: what the cut has now, what it needs, '
                        'and how the new plate looks.'},
    'chp.no_num_note': {'ru': 'У глав {list} номера на заставке нет, у остальных есть — '
                              'два разных приёма в одном фильме. ',
                        'en': 'Chapters {list} carry no number on the plate while the others do — '
                              'two different devices in one film. '},
    'chp.mark_no_num': {'ru': 'НЕТ НОМЕРА', 'en': 'NO NUMBER'},
    # ── карта выпуска ───────────────────────────────────────────────────────────────────────────
    'chp.map_h': {'ru': 'КАРТА ВЫПУСКА — {ch} глав · {sub} подглав',
                  'en': 'CUT MAP — {ch} chapters · {sub} subchapters'},
    'chp.map_note': {'ru': 'Нумерация: содержательных глав {ch}, они и нумеруются 01–{last}; вступление и финал — '
                           'без номера. На заставках ката номера пока другие, это отдельная правка (см. таблицу ниже).',
                     'en': 'Numbering: {ch} content chapters, numbered 01–{last}; the opening and the finale carry '
                           'no number. The plates in the cut still show different numbers — that is a separate fix '
                           '(see the table below).'},
    'chp.map_link': {'ru': 'Та же карта одним кадром (4K, открывать в полный экран): ',
                     'en': 'The same map as one frame (4K, open it full screen): '},
    'chp.map_missing': {'ru': '— карта ещё не залита', 'en': '— the map has not been uploaded yet'},
    # ── строки глав и подглав ───────────────────────────────────────────────────────────────────
    'chp.chapter_pfx': {'ru': 'ГЛАВА {n}. ', 'en': 'CHAPTER {n}. '},
    'chp.panel_line': {'ru': '\n▸ панель «{title}» · {n} пунктов', 'en': '\n▸ panel “{title}” · {n} items'},
    'chp.cut_no': {'ru': 'на заставке ката стоит «{no}. {name}»',
                   'en': 'the plate in the cut reads “{no}. {name}”'},
    'chp.want_no': {'ru': 'номер сменить на {n}', 'en': 'change the number to {n}'},
    'chp.want_no_drop': {'ru': 'номер убрать — это не глава, а хук/финал',
                         'en': 'drop the number — this is the hook / finale, not a chapter'},
    'chp.sub_no_title': {'ru': '⚠️ титра подтемы в кате нет', 'en': '⚠️ no subchapter title in the cut'},
    'chp.sub_has_title': {'ru': 'титр подтемы есть', 'en': 'subchapter title is there'},
    'chp.sub_by_panel': {'ru': 'подтему несёт панель перечисления', 'en': 'the list panel carries this subchapter'},
    'chp.no_subs': {'ru': '▸ подглав в кате нет', 'en': '▸ no subchapters in this stretch'},
    'chp.extra_now': {'ru': 'ПОХОЖЕ НА ЗАСТАВКУ, но это не глава', 'en': 'LOOKS LIKE A PLATE but is not a chapter'},
    'chp.extra_do': {'ru': 'решить: переоформить или оставить', 'en': 'decide: restyle or leave as is'},
    # ── варианты заставки ───────────────────────────────────────────────────────────────────────
    'chp.var_h_picked': {'ru': 'ВАРИАНТЫ ЗАСТАВКИ — выбран {v}', 'en': 'CHAPTER PLATE VARIANTS — {v} chosen'},
    'chp.var_h_ask': {'ru': 'ВАРИАНТЫ ЗАСТАВКИ — выбери букву', 'en': 'CHAPTER PLATE VARIANTS — pick a letter'},
    'chp.var_lead': {'ru': 'Все три нарисованы поверх настоящего кадра этого фильма, глава {ch}. ',
                     'en': 'All three are drawn over a real frame of this film, chapter {ch}. '},
    'chp.var_picked': {'ru': 'Роман выбрал {v} — все {n} глав собраны в этом стиле и стоят на таймлайне.',
                       'en': 'Variant {v} is chosen — all {n} chapters are built in this style '
                             'and sit on the timeline.'},
    'chp.var_ask': {'ru': 'Скажи букву — соберу все {n} глав в этом стиле и поставлю на таймлайн.',
                    'en': 'Name a letter and all {n} chapters will be built in that style and put on the timeline.'},
    'chp.chosen': {'ru': ' ✔ ВЫБРАН', 'en': ' ✔ CHOSEN'},
    'chp.demo_a_t': {'ru': 'ПОЛОТНО', 'en': 'FULL CANVAS'},
    'chp.demo_a_d': {'ru': 'кадр уходит в затемнение, номер и имя по центру — максимум контраста, '
                           'кадр почти не виден',
                     'en': 'the frame fades to black, number and name centred — maximum contrast, '
                           'the frame is almost gone'},
    'chp.demo_b_t': {'ru': 'ШТОРКА', 'en': 'SIDE CURTAIN'},
    'chp.demo_b_d': {'ru': 'плотная левая треть, ведущая и кадр справа остаются чистыми',
                     'en': 'a solid left third; the speaker and the frame on the right stay clean'},
    'chp.demo_c_t': {'ru': 'НИЖНЯЯ ТРЕТЬ', 'en': 'LOWER THIRD'},
    'chp.demo_c_d': {'ru': 'кадр цел целиком, подложка только снизу — мягче всех, но и слабее по акценту',
                     'en': 'the frame stays whole, the plate sits along the bottom — the gentlest of the three, '
                           'and the weakest accent'},
    # ── панели перечислений ─────────────────────────────────────────────────────────────────────
    'chp.pan_h': {'ru': 'ПОДГЛАВЫ — ПАНЕЛИ ПЕРЕЧИСЛЕНИЙ', 'en': 'SUBCHAPTERS — LIST PANELS'},
    'chp.pan_lead': {'ru': 'Там, где ведущая перечисляет по пунктам, зритель теряет счёт. Панель слева '
                           'держит весь список на экране и подсвечивает текущий пункт; справа — «ЧТО ДАЛЬШЕ» '
                           'или «k из n». Связь с главой держат две вещи: подпись «ГЛАВА NN» в шапке '
                           'панели и цветная планка слева — та же, что у плашки подглавы.',
                     'en': 'Where the speaker counts items out loud, the viewer loses track. The panel on the left '
                           'holds the whole list on screen and highlights the current item; on the right — '
                           '“WHAT’S NEXT” or “k of n”. Two things tie it to the chapter: the “CHAPTER NN” line in '
                           'the panel header and the coloured bar on the left — the same one the subchapter '
                           'plate uses.'},
    'chp.pan_ask': {'ru': 'Где панель стоит — на выбор, скажи букву:',
                    'en': 'Which page the panel sits on — your pick, name a letter:'},
    'chp.pan_foot': {'ru': 'Ниже — обзорный кадр каждой панели (ни один пункт ещё не подсвечен); '
                           'полный набор кадров и таймкоды — в ТЗ монтажёру.',
                     'en': 'Below — an overview frame of each panel (no item highlighted yet); the full set of '
                           'frames and timecodes is in the edit notes.'},
    'chp.pan_block': {'ru': 'ГЛАВА {no} · {name} — «{title}»', 'en': 'CHAPTER {no} · {name} — “{title}”'},
    'chp.pan_items': {'ru': '{n} пунктов: ', 'en': '{n} items: '},
    'chp.pd_z_t': {'ru': 'ТЁМНАЯ СТРАНИЦА — ПРИНЯТ', 'en': 'DARK PAGE — ACCEPTED'},
    'chp.pd_z_d': {'ru': 'непрозрачная тёплая темнота: свежий пункт слоновой костью (15,7 : 1), пройденные '
                         'приглушены до 45 %, рубин канала держит черту, тире и цифру счётчика',
                   'en': 'opaque warm dark: the fresh item in ivory (15.7 : 1), passed items dimmed to 45 %, '
                         'the channel accent holds the rule, the dash and the counter'},
    'chp.pd_h_t': {'ru': 'СВЕТЛАЯ СТРАНИЦА — для примера', 'en': 'LIGHT PAGE — for comparison'},
    'chp.pd_h_d': {'ru': 'та же вёрстка на странице слоновой кости, собственном приёме фильма: свежий пункт '
                         'рубиновый (4,9 : 1), пройденные графитом',
                   'en': 'the same layout on an ivory page, the film’s own device: the fresh item in the channel '
                         'accent (4.9 : 1), passed items in graphite'},
}
