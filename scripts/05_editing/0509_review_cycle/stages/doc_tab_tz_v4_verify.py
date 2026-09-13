#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка вкладки «ТЗ монтажёру · v4».
v3 заморожена: в ней правки Романа от 11.09 (он удалял неактуальные ТЗ руками)."""
import os
import sys
from pathlib import Path

os.environ.setdefault('TZ_TAB', 'ТЗ монтажёру · v4')
sys.path.insert(0, str(Path(__file__).parent))
import runpy  # noqa: E402

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).parent / "doc_tab_tz_v3_verify.py"), run_name="__main__")
