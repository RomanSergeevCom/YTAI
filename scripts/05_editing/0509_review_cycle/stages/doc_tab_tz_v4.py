#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка «ТЗ монтажёру · v4» — тот же сборщик, другая вкладка.
v3 заморожена: в ней правки Романа от 11.09 (он удалял неактуальные ТЗ руками)."""
import os
import sys
from pathlib import Path

os.environ.setdefault('TZ_TAB', 'ТЗ монтажёру · v4')
sys.path.insert(0, str(Path(__file__).parent))
import doc_tab_tz_v3 as D  # noqa: E402

if __name__ == '__main__':
    D.main()
