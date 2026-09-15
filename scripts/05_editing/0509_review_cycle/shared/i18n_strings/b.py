# -*- coding: utf-8 -*-
"""b.* — облачный судья (cloud/cloudlib.py, cloud/collect.py): строки, которые попадают в находки / ТЗ.

RU — байт-в-байт литералы из cloud/cloudlib.py (CHECK_SOURCE_FIX, пометка снятых ТЗ в existing_tz_lines).
Промпты агентов живут в cloud/wf_judge.js (таблицы RU/EN там же, язык — args.lang).
"""

STRINGS = {
    # fix_text находки, которую скептик пометил кодом H (текст титра не прочитать по тексту → kind check_source)
    'b.check_source_fix': {'ru': 'проверить исходник титра', 'en': 'check the title source'},
    # хвост строки существующего ТЗ для судьи: «ТЗ-NN · tc · заголовок (снята Романом)»
    'b.tz_rejected_suffix': {'ru': ' (снята Романом)', 'en': ' (rejected by Roman)'},
}
