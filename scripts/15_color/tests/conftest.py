"""Общие фикстуры слоя цвета.

Тесты живут на уровне СЛОЯ, а не этапа: проверяемые модули лежат в трёх этапах
(`lut_select` в 1501, `color_media`/`color_frames`/`color_plan` в 1502, эмиттер в
1503), а фикстура «маленький манифест» нужна сразу троим. Три копии conftest
были бы хуже одного общего.

⚠️ `sys.path.insert` обязателен: папки этапов начинаются с цифры, поэтому
`import lut_select` обычным способом не находится. Танец с
`importlib.util.spec_from_file_location`, как в тестах 0104, здесь НЕ нужен —
имена модулей латинские и импортируются нормально, стоит лишь добавить папки.

Запуск:  /opt/homebrew/bin/pytest scripts/15_color/tests/ -q
⚠️ pyobjc Vision в этом окружении НЕТ — ни один тест не имеет права его требовать.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

LAYER = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
for _p in (LAYER / "1501_lut_library", LAYER / "1502_lut_pick", LAYER / "1503_color_apply"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def small_manifest():
    """12 записей, вырезанных из настоящего манифеста: 7 проявок (три гаммы,
    включая ОДНУ гамму у разных тушек), 3 покрасочных, pre и legacy."""
    return _load("manifest_small.json")


@pytest.fixture
def small_luts(small_manifest):
    return small_manifest["luts"]


@pytest.fixture
def ytevo_choice():
    """Настоящий выбор Романа по YTEVO03: 162 экспозиции, 18 правок."""
    return _load("choice_ytevo03.json")


@pytest.fixture
def ytevo_profile():
    """Настоящая ДНК канала YTEVO."""
    return _load("profile_ytevo.json")


@pytest.fixture
def legacy_plan():
    """Срез старого lut_plan.json: 163 клипа с гаммой и камерой."""
    return _load("lut_plan_gamma.json")


@pytest.fixture
def fake_project(tmp_path):
    """Проект в раскладке YTEVO03: сцены, папки камер, один сайдкар, мусор.

    Специально кладём то, что должно быть ОТБРОШЕНО: `.LRF`, `.wav`, dotfile и
    служебную сцену `00_Tests_And_Sync` — она не фильм и в план цвета не идёт.
    """
    prj = tmp_path / "YTEVO99_Test_Day"
    src = prj / "01_Source"
    (prj / "00_Setup" / "01_Ingest").mkdir(parents=True)
    layout = {
        "01_Morning_Run": {"CAM-A_FX3": ["RYA-FX3-1212.MP4", "RYA-FX3-1213.MP4"],
                           "CAM-C_Pocket": ["DJI_0008_D.MP4"]},
        "02_Walk":        {"CAM-B_ZVE1": ["RYA-ZVE1-1890.MP4"]},
        "03_Office":      {"CAM-A_FX3": ["RYA-FX3-1300.MP4"]},
        "00_Tests_And_Sync": {"CAM-A_FX3": ["RYA-FX3-0001.MP4"]},   # ← не фильм
    }
    for scene, cams in layout.items():
        for cam, clips in cams.items():
            d = src / scene / cam
            d.mkdir(parents=True)
            for c in clips:
                (d / c).write_bytes(b"\x00" * 64)
            (d / "junk.LRF").write_bytes(b"\x00")
            (d / "sound.wav").write_bytes(b"\x00")
            (d / ".DS_Store").write_bytes(b"\x00")
    # Сайдкар Sony рядом с клипом — источник гаммы.
    # ⚠️ Форма ровно такая, как пишет камера: <Item name=… value=…/>, а НЕ атрибут
    # CaptureGammaEquation="…". Регулярка в color_media.sony_gamma ищет
    # `CaptureGammaEquation"? value="…"`, и фикстура «похожей формы» её не поднимает —
    # тест тогда стережёт не код, а собственную выдумку.
    (src / "01_Morning_Run" / "CAM-A_FX3" / "RYA-FX3-1212M01.XML").write_text(
        '<?xml version="1.0"?><NonRealTimeMeta>'
        '<AcquisitionRecord><Group name="CameraUnitMetadataSet">'
        '<Item name="CaptureGammaEquation" value="s-log3-cine"/>'
        '</Group></AcquisitionRecord></NonRealTimeMeta>', encoding="utf-8")
    return prj
