# -*- coding: utf-8 -*-
"""fix.* — s11_apply_sources: авто-источники материалов (material_rich[].src → «📚 источник: …» в доке и листе),
названия книг архива UVI по имени PDF и хвост «файл книги в архиве».

RU — байт-в-байт прежние литералы s11_apply_sources.py. EN — для английских каналов (YTCR): слой V1 = кат монтажёра.
"""

STRINGS = {
    # ── auto_src(img): источник картинки по префиксу имени ──────────────────
    'fix.src_cafe': {'ru': 'кадр рендера v1 @39:46 — общий план в кафе',
                     'en': "frame of the editor's cut — wide shot in the café"},
    'fix.src_err': {'ru': 'кадр рендера v1 + наша отметка ошибки (стрелка — слой V5)',
                    'en': "frame of the editor's cut (layer V1) + our error mark (arrow — layer V5)"},
    'fix.src_fix': {'ru': 'наш драфт исправления поверх кадра v1 (слой V3) — перерисовать в стиле канала',
                    'en': "our draft of the fix over the cut frame (layer V3) — redraw in the channel style"},
    'fix.src_map': {'ru': 'наш драфт — перерисовать в стиле канала · карта: Natural Earth 50m (public domain)',
                    'en': 'our draft — redraw in the channel style · map: Natural Earth 50m (public domain)'},
    'fix.src_draft': {'ru': 'наш драфт — перерисовать в стиле канала',
                      'en': 'our draft — redraw in the channel style'},
    'fix.src_chapter': {'ru': 'стоп-кадр заставки главы из рендера v1',
                        'en': "still of the chapter title card from the editor's cut"},

    # ── книги/журналы по имени PDF (дефолты архива UVI; карточка book_titles — сверху) ──
    'fix.book_ssef_acg_1': {'ru': 'SSEF «Advanced Coloured Gemstones», книга 1 «Ruby» (Швейцарский геммологический институт)',
                            'en': 'SSEF “Advanced Coloured Gemstones”, book 1 “Ruby” (Swiss Gemmological Institute)'},
    'fix.book_ssef_acg_3': {'ru': 'SSEF «Advanced Coloured Gemstones», книга 3 «Corundum Treatments»',
                            'en': 'SSEF “Advanced Coloured Gemstones”, book 3 “Corundum Treatments”'},
    'fix.book_jog_1965': {'ru': 'журнал Gem-A «The Journal of Gemmology», июль 1965, т.9 №11',
                          'en': 'Gem-A journal “The Journal of Gemmology”, July 1965, vol. 9 no. 11'},
    'fix.book_file': {'ru': '{title} — файл книги в архиве: {link}',
                      'en': '{title} — book file in the archive: {link}'},
}
