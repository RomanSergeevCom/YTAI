#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка «ТЗ монтажёру · v4» — тот же сборщик, другая вкладка.
v3 заморожена: в ней правки Романа от 11.09 (он удалял неактуальные ТЗ руками).
Имя вкладки по умолчанию — шаблон профиля doc.tab_tz_template с ver='v4' (YTUVI: «ТЗ монтажёру · v4»,
YTCR: «Edit notes · v4»); review.py всегда передаёт TZ_TAB из tab_title карточки."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import P, T  # noqa: E402

os.environ.setdefault('TZ_TAB', str(P.profile('doc.tab_tz_template', T('c2.tz_tab_template'))).format(ver='v4'))
import doc_tab_tz_v3 as D  # noqa: E402

if __name__ == '__main__':
    D.cli()                     # --dump-requests FILE → офлайн-дамп запросов (см. doc_tab_tz_v3.dump_main)
