# -*- coding: utf-8 -*-
"""Единая точка путей для скриптов stages/.

    from _bootstrap import P, W6, M, HERE, ROOT  # noqa: E402

P    — proj_config (карточка фильма + профиль канала)
W6   — рабочая папка данных фильма  {project}/00_Setup/05_Review/work/{cut_version}
M    — папка правок                 {project}/00_Setup/05_Review/pravki
HERE — stages/ (код), ROOT — папка стадии (код). Данные рядом с кодом НЕ ищутся.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EXTRA = ROOT.parent.parent / '999_extra'
for _p in (HERE, ROOT, EXTRA / 'ytuvi_doctabs', EXTRA / 'infographic'):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

import proj_config as P  # noqa: E402

W6 = P.WORK
M = P.MONT
CLOUD = P.CLOUD
MOCK = P.MOCK
REVIEW_DIR = P.REVIEW_DIR
POLISH = W6 / 'polish'
