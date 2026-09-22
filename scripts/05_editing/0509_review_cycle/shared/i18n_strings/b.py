# -*- coding: utf-8 -*-
"""b.* — облачный судья (cloud/cloudlib.py, cloud/collect.py): строки, которые попадают в находки / ТЗ.

RU — байт-в-байт литералы из cloud/cloudlib.py (CHECK_SOURCE_FIX, пометка снятых ТЗ в existing_tz_lines).
Промпты агентов живут в cloud/wf_judge.js (таблицы RU/EN там же, язык — args.lang).
"""

STRINGS = {
    # fix_text находки, которую скептик пометил кодом H (текст титра не прочитать по тексту → kind check_source)
    'b.check_source_fix': {'ru': 'проверить исходник титра', 'en': 'check the title source'},
    # хвост строки существующего ТЗ для судьи: «ТЗ-NN · tc · заголовок (снята Романом)»
    # ТЗ ПРОШЛОГО круга в пакете судьи: без них он проверяет кат вслепую и не помнит,
    # о чём сам просил в прошлый раз (YTUVI01 v2 — подмена человека на плашке, 22.09.2026)
    'b.prev_tz_head': {'ru': 'ТЗ ПРОШЛОГО КРУГА ({n}) — именно их монтажёр и выполнял:',
                       'en': 'PREVIOUS ROUND NOTES ({n}) — this is what the editor was asked to do:'},
    'b.tz_rejected_suffix': {'ru': ' (снята Романом)', 'en': ' (rejected by Roman)'},
}
