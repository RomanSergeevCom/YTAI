# -*- coding: utf-8 -*-
"""a1.* — промпты и сообщения Memex-стадий: s3_vlm (Q_TEXT), s4_llm (PROMPT, тема по умолчанию, правила),
s3b_probe_vlm (Q_FOREIGN, Q_ZOOM), s5_selfcheck (проверка алфавита VLM).

RU — байт-в-байт литералы из этих стадий до перевода на i18n. EN — для английского канала (YTCR): оригинал
экранного текста английский, «английский без перевода» не ошибка, чужой алфавит в графике канала — ошибка.
Шаблоны с {полями} стадии форматируют сами (T без kw возвращает сырой шаблон).
"""

STRINGS = {
    # ── s3_vlm: дословная транскрипция экранного текста ─────────────────────
    'a1.vlm_q_text': {
        'ru': ("Transcribe ALL text visible in this video frame EXACTLY as written — keep the original "
               "language (Russian Cyrillic or English), letter case, digits, punctuation and currency signs. "
               "One text block per line. Do not translate, do not correct spelling. "
               "If there is no text, answer: NO TEXT."),
        'en': ("Transcribe ALL text visible in this video frame EXACTLY as written. The original language is "
               "English: keep letter case, digits and numbers (thousand separators, decimal points, K/M/B "
               "suffixes), currency codes and signs (e.g. AED, $) and punctuation exactly as shown. "
               "Text in any other script (e.g. Arabic) — copy it as written. "
               "One text block per line. Do not translate, do not correct spelling. "
               "If there is no text, answer: NO TEXT."),
    },

    # ── s4_llm: корректор/факт-чекер экрана ─────────────────────────────────
    'a1.llm_subject_default': {'ru': 'о рубинах', 'en': ''},
    'a1.llm_prompt': {
        'ru': """/no_think Ты корректор и факт-чекер русскоязычного YouTube-фильма {subject}.
Экран #{id} (таймкод {tc}). Текст на экране — два независимых распознавания:
OCR: {ocr}
VLM: {vlm}
Что за графика: {desc}
Озвучка в этот момент: {vo}

Правила канала: валюта — знак ПЕРЕД числом и сокращение: «$30,3 МЛН» (НЕ «30 300 000 $»); русский титр главный, английский допустим только вторым/меньше; термины и имена — без опечаток.
Игнорируй артефакты распознавания (обрезанные буквы, путаницу латиницы/кириллицы у OCR), если второе распознавание их не подтверждает.

Ответь СТРОГО одним JSON-объектом:
{{"typos": ["<слово с ошибкой → правильно>", ...],
 "grammar": ["<замечание или пусто>"],
 "currency_numbers": ["<нарушение формата: как на экране → как надо>"],
 "english_only": ["<английский текст/термин без русского перевода>"],
 "facts_to_check": ["<конкретное проверяемое утверждение: число/дата/имя>"],
 "mismatch_with_vo": "<экран противоречит озвучке — или пусто>",
 "severity": "none|low|high"}}""",
        'en': """/no_think You are a proofreader and fact-checker of an English-language YouTube documentary{subject}.
Screen #{id} (timecode {tc}). On-screen text — two independent recognitions:
OCR: {ocr}
VLM: {vlm}
What kind of graphic: {desc}
Voice-over at this moment: {vo}

{rules}
Ignore recognition artifacts (clipped letters, OCR confusing look-alike glyphs) unless the other recognition confirms them.
English on-screen text is correct language here — never report it as untranslated. Text in a non-English script (Cyrillic, Arabic, …) is an error ONLY when it is part of the channel's own graphics (titles, lower thirds, captions, charts); signage, documents or screens physically filmed in real b-roll (e.g. Arabic street signs) are NOT foreign.

Answer STRICTLY with one JSON object:
{{"typos": ["<misspelled word → correct spelling>", ...],
 "grammar": ["<remark, or empty>"],
 "currency_numbers": ["<format violation: as on screen → as it should be>"],
 "english_only": [],
 "foreign_script": ["<text of the channel's own graphics written in a non-English script>"],
 "facts_to_check": ["<a specific checkable claim: number/date/name>"],
 "mismatch_with_vo": "<the screen contradicts the voice-over — or empty>",
 "severity": "none|low|high"}}
"english_only" is ALWAYS an empty list for this channel.""",
    },
    'a1.llm_rules_default': {
        'en': ("CHANNEL RULES: English on-screen titles are primary; numbers and currency are written consistently "
               "across the video; names, companies and terms without typos."),
    },

    # ── s3b_probe_vlm: зонды «чужой след» и зум-перечитывание ────────────────
    'a1.probe_q_foreign': {
        'ru': ("This is a frame from a Russian-language YouTube video about gemstones. Does the frame contain any "
               "FOREIGN element that does not belong to the video's own graphics: a watermark or stock-site logo, "
               "a third-party brand or TV channel logo, Chinese/Japanese/Korean or other non-Russian characters, "
               "a mouse cursor, burned-in subtitles or captions from another video, a source credit line? "
               "The channel's own small 'uvi' logo, the presenter and the video's own Russian titles do NOT count. "
               "Answer strictly in the form: YES: <what and where> — or NO."),
        'en': ("This is a frame from an English-language YouTube video (channel: {own_logo}). Does the frame contain "
               "any FOREIGN element that does not belong to the video's own graphics: a watermark or stock-site logo, "
               "a third-party brand or TV channel logo, burned-in subtitles or captions from another video (e.g. "
               "YouTube player UI or overlays of a re-used clip), a mouse cursor, a source credit line? "
               "The channel's own '{own_logo}' logo, its lower thirds, the people on camera and the video's own "
               "English titles do NOT count; neither do signs or text physically present in the filmed scene. "
               "Answer strictly in the form: YES: <what and where> — or NO."),
    },
    'a1.probe_q_zoom': {
        'ru': ("This is a zoomed crop of one text line from a video frame. Transcribe the text EXACTLY, letter by letter, "
               "as it is written (Russian Cyrillic or Latin). Keep the letter case. Do NOT correct spelling, do NOT add "
               "or translate words. Output only the text."),
        'en': ("This is a zoomed crop of one text line from a video frame. Transcribe the text EXACTLY, letter by letter, "
               "as it is written (English, Latin letters). Keep the letter case, digits and punctuation. Do NOT correct "
               "spelling, do NOT add or translate words. Output only the text."),
    },

    # ── s5_selfcheck: алфавит транскрипций VLM ───────────────────────────────
    'a1.selfcheck_vlm_alpha': {
        'ru': 'vlm: кириллица только в {n}/{total} — транскрибирует не то',
        'en': 'vlm: латиница только в {n}/{total} — транскрибирует не то',
    },
}
