#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка вкладки «ТЗ монтажёру · v4».
v3 заморожена: в ней правки Романа от 11.09 (он удалял неактуальные ТЗ руками).
Имя вкладки по умолчанию — шаблон профиля doc.tab_tz_template с ver='v4' (как doc_tab_tz_v4.py)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import P, T  # noqa: E402

os.environ.setdefault('TZ_TAB', str(P.profile('doc.tab_tz_template', T('c2.tz_tab_template'))).format(ver='v4'))
import runpy  # noqa: E402

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).parent / "doc_tab_tz_v3_verify.py"), run_name="__main__")
