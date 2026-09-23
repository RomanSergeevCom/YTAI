"""Сторожа на JS витрины. Его код живёт внутри f-строки Python, тестов у него нет.

⚠️ Именно поэтому здесь понадобился отдельный файл: самый дорогой дефект ночи —
`persist()` не звался в ветке экспозиции — жил в JS, куда pytest обычно не смотрит.
162 клика давали 3 записи в localStorage, а страница после перезагрузки писала
«восстановлен выбор» и возвращала всё к машинному.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

BOARD = Path(__file__).resolve().parent.parent / "1502_lut_pick" / "lut_board.py"


@pytest.fixture(scope="module")
def handler() -> str:
    """Тело обработчика клика из исходника витрины."""
    src = BOARD.read_text(encoding="utf-8")
    m = re.search(r"document\.addEventListener\('click'.*?\n\}\}\);", src, re.S)
    assert m, "обработчик клика не найден — витрину переписали, проверь сторожа"
    return m.group(0)


class TestClickHandlerPersists:
    def test_exposure_branch_persists_before_return(self, handler):
        """CLR-21: ветка экспозиции сохраняет выбор ДО выхода.

        ⚠️ Она делала `refresh(); return;` — и клик жил только в памяти вкладки.
        Правки дня молча исчезали при перезагрузке, причём с надписью,
        уверяющей, что выбор восстановлен.
        """
        expo = [l for l in handler.split("\n") if "dataset.expo" in l]
        assert expo, "ветка экспозиции пропала из обработчика"
        line = expo[0]
        assert "persist()" in line, (
            "в ветке экспозиции нет persist() — клики по экспозиции снова "
            "не доживут до перезагрузки:\n  " + line.strip())
        assert line.index("persist()") < line.index("return"), (
            "persist() стоит ПОСЛЕ return — значит не выполнится")

    def test_every_branch_that_mutates_choice_persists(self, handler):
        """CLR-22: любая ветка, меняющая CH, обязана сохранять.

        Общее правило вместо перечисления: добавят третью ступень выбора —
        сторож напомнит про persist() сразу, а не через потерянный съёмочный день.
        """
        for line in handler.split("\n"):
            if re.search(r"\bCH\.(expo|develop|look)\s*[\[=]", line) and "persist()" not in line:
                assert "refresh(); persist();" in handler, (
                    "ветка меняет CH и не сохраняет:\n  " + line.strip())
