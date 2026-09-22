"""Арифметика экспозиции в color_plan — требование CLR-06.

Что здесь стережётся (главное знание слоя цвета):

  Витрина и Premiere считают экспозицию в РАЗНЫХ пространствах.
  Превью витрины вешает фильтр `exposure` в ffmpeg ПОВЕРХ уже проявленного,
  гамма-кодированного Rec.709 — то есть просто умножает код пикселя на 2^X.
  Lumetri сначала линеаризует (Linearize Gamma 2.4 to Linear) и только потом
  двигает экспозицию. Поэтому стопы Lumetri = 2.4 × стопы витрины.

  Замер, ради которого всё это писалось: код 64 при +1 EV в ffmpeg даёт 128,
  а Lumetri с теми же «+1» дал бы ≈85. Число из витрины, вставленное в
  Lumetri как есть, — это картинка, которая НЕ совпадает с тем, что человек
  выбрал глазами.

Покрыто:
  • stops_to_target   — промах в стопах, зажим ±3, ValueError на битой цели
  • эквивалентность   — переписанная на math арифметика == старой на numpy
  • to_lumetri_stops  — множитель 2.4 и округление
  • ФИЗИКА            — тождество, из которого этот множитель следует
  • check_lumetri_stops — предел ползунка ±7, отказ с числом в причине
  • stop_tag          — канон имени ступени
  • УНИКАЛЬНОСТЬ ТЕГОВ — два кадра лестницы не имеют права затереть друг друга
  • ladder_for        — лестница достраивается до промаха

Запуск:  /opt/homebrew/bin/pytest scripts/15_color/tests/test_exposure.py -q
⚠️ numpy здесь нужен только как ЭТАЛОН для сверки; сам модуль под тестом
   обязан считать на голой стандартной библиотеке.
"""
from __future__ import annotations

import math
import random

import numpy as np
import pytest

import color_plan as cp


# ─────────────────────────────────────────────────────────────── stops_to_target

class TestStopsToTarget:
    """Промах в стопах: на сколько удвоений света кадр не дотягивает до цели."""

    def test_half_target_is_one_stop_up(self):
        """Лицо вдвое темнее цели — ровно +1 стоп.

        Стоп — это удвоение света. Если это перестанет быть log2, вся витрина
        начнёт предлагать не те ступени, а человек выберет «на глаз» не ту.
        """
        assert cp.stops_to_target(67.0, 134.0) == 1.0

    def test_on_target_is_zero(self):
        """Лицо ровно на цели — промаха нет. Ноль обязан быть настоящим нулём:
        именно по нулю витрина решает, что клип трогать не надо."""
        assert cp.stops_to_target(134.0, 134.0) == 0.0

    def test_double_target_is_one_stop_down(self):
        """Лицо вдвое ярче цели — ровно −1 стоп (знак не перепутан)."""
        assert cp.stops_to_target(268.0, 134.0) == -1.0

    @pytest.mark.parametrize("luma", [0.0, 0.5, 1.0])
    def test_almost_black_frame_returns_max(self, luma):
        """Кадр почти чёрный (luma ≤ 1) — сразу +3, без логарифма.

        Делить цель на околонулевую яркость нельзя: получится астрономический
        промах или деление на ноль. Граница именно ≤ 1.0, а не < 1.0.
        """
        assert cp.stops_to_target(luma, 134.0) == 3.0

    def test_almost_black_boundary_is_inclusive(self):
        """Граница ветки — именно `luma <= 1.0`, а не `< 1.0`.

        На рабочих целях (50–220) разницу не видно: зажим ±3 её съедает.
        Поэтому граница пинуется синтетической целью 4.0, где ветки
        расходятся: `<=` даёт +3.0, `<` дало бы ровно +2.0. Пин нужен, потому
        что функция переехала из lut_board.py дословно и множество «почти
        чёрных» кадров обязано остаться тем же.
        """
        assert cp.stops_to_target(1.0, 4.0) == 3.0

    def test_clamped_from_above(self):
        """Чудовищный недосвет зажимается в +3 — предел фильтра exposure ffmpeg.

        Без зажима витрина отрендерила бы ступень, которую ffmpeg не умеет,
        и кадр молча уехал бы в белое.
        """
        assert cp.stops_to_target(2.0, 220.0) == 3.0        # log2(110) ≈ 6.78

    def test_clamped_from_below(self):
        """Чудовищный пересвет зажимается в −3 (тот же предел, другой знак)."""
        assert cp.stops_to_target(255.0, 10.0) == -3.0      # log2(0.039) ≈ −4.67

    @pytest.mark.parametrize("target", [0.0, -0.0, -5.0, -134.0])
    def test_broken_target_raises(self, target):
        """Цель ≤ 0 — это ValueError, а НЕ тихий зажим.

        ⚠️ Оплаченная ошибка. На numpy тут получался -inf, который молча
        уезжал в зажим −3.0: битая цель выглядела как честное «притушить на
        три стопа», и клип красился по мусорному числу.
        """
        with pytest.raises(ValueError):
            cp.stops_to_target(100.0, target)

    def test_broken_target_names_the_value(self):
        """В тексте ошибки стоит само битое число — чтобы было видно, ОТКУДА
        оно пришло (профиль канала, выбор, дефолт), а не просто «плохая цель»."""
        with pytest.raises(ValueError) as e:
            cp.stops_to_target(100.0, -7.5)
        assert "-7.5" in str(e.value)

    def test_black_frame_wins_over_broken_target(self):
        """Порядок веток зафиксирован: почти чёрный кадр проверяется ПЕРВЫМ,
        поэтому при luma ≤ 1 битая цель до ValueError не доходит.

        Это не небрежность, а совместимость с lut_board.py — код переехал
        дословно. Тест держит порядок: если ветки поменять местами, старые
        прогоны начнут падать там, где раньше отдавали +3.
        """
        assert cp.stops_to_target(0.5, -7.0) == 3.0


class TestMathMatchesNumpy:
    """Переписанная на math арифметика обязана совпасть со старой на numpy."""

    def test_equivalence_on_10k_points(self):
        """10 000 точек: math-версия == np.clip(np.log2(target/luma), −3, 3).

        ⚠️ Страж переписывания. stops_to_target переехала с numpy на math;
        видимых изменений быть не должно НИ В ОДНОМ знаке. Сдвиг округления
        тут не заметен глазом, но меняет выбранную ступень на границе и
        расходится с уже сохранёнными выборами Романа.

        Диапазоны взяты рабочие: luma от почти чёрного до белого,
        цель по лицу — как в профилях каналов.
        """
        rnd = random.Random(20260922)
        worst = 0.0
        worst_point = None
        black_frames = 0
        for _ in range(10_000):
            luma = rnd.uniform(0.1, 255.0)
            target = rnd.uniform(50.0, 220.0)
            if luma <= 1.0:
                black_frames += 1
            ref = float(np.clip(np.log2(target / luma), -3.0, 3.0))
            got = cp.stops_to_target(luma, target)
            diff = abs(got - ref)
            if diff > worst:
                worst, worst_point = diff, (luma, target, got, ref)
        assert worst < 1e-12, f"расхождение {worst} на {worst_point}"
        # ветка «почти чёрный кадр» на этих диапазонах тоже обязана совпадать
        # с эталоном (цель ≥ 50 при luma ≤ 1 всегда уезжает в зажим +3),
        # и она должна быть реально пройдена, иначе сверка её не покрыла
        assert black_frames > 0


# ──────────────────────────────────────────────────── витрина → Lumetri

class TestToLumetriStops:
    """Пересчёт стопов витрины в стопы ползунка Lumetri."""

    @pytest.mark.parametrize("preview, lumetri", [
        (-1.0, -2.4),
        (-0.5, -1.2),
        (0.0, 0.0),
        (0.5, 1.2),
        (1.0, 2.4),
        (1.5, 3.6),
        (2.0, 4.8),
        (2.5, 6.0),
    ])
    def test_multiplier_is_24(self, preview, lumetri):
        """Множитель ровно 2.4 на всей рабочей лестнице.

        ⚠️ Это число — не настройка вкуса, а следствие того, что Lumetri
        линеаризует ДО экспозиции (см. тест физики ниже). Поменять его =
        покрасить весь фильм не той яркостью, какую человек выбрал в витрине.
        """
        assert cp.to_lumetri_stops(preview) == pytest.approx(lumetri, abs=1e-9)

    def test_result_is_clean_for_json_and_captions(self):
        """1.5 × 2.4 в double = 3.5999999999999996; наружу обязано уйти 3.6.

        Число уходит в подпись монтажёру и в JSON раскладки как есть —
        «3.5999999999999996 стопа» в ТЗ читать нельзя.
        """
        assert repr(cp.to_lumetri_stops(1.5)) == "3.6"

    def test_zero_stays_zero(self):
        """Ноль стопов — ноль и в Lumetri: клип, который не трогают, не должен
        получить ползунок «−0.0» и лишнюю правку в раскладке."""
        assert cp.to_lumetri_stops(0.0) == 0.0


class TestExposurePhysics:
    """Доказательство множителя 2.4, а не вера в него."""

    # Гамма передаточной функции Rec.709-контейнера, в котором живёт превью.
    # ⚠️ Специально вбита числом, а не взята из cp.LUMETRI_GAMMA: это ЗАМЕР
    # физики, и он обязан ловить подмену константы в модуле.
    TRANSFER_GAMMA = 2.4

    @pytest.mark.parametrize("code", [20, 40, 64, 100, 128, 160])
    @pytest.mark.parametrize("preview_stops", [-1.0, -0.5, 0.5, 1.0, 2.5])
    def test_gamma_encoded_gain_equals_linear_gain(self, code, preview_stops):
        """Тождество: code·2^X == ((code/255)^2.4 · 2^(2.4·X))^(1/2.4)·255.

        Слева — что делает ffmpeg: умножает гамма-кодированный код на 2^X.
        Справа — что делает Lumetri: линеаризует, двигает экспозицию на
        to_lumetri_stops(X) стопов, кодирует обратно.

        Равенство выполняется ТОЛЬКО когда стопы Lumetri = 2.4 × стопы
        витрины. Это и есть доказательство множителя — тест обязан его
        удерживать при любой правке to_lumetri_stops.
        """
        g = self.TRANSFER_GAMMA
        ffmpeg_code = code * 2.0 ** preview_stops

        linear = (code / 255.0) ** g
        linear_lifted = linear * 2.0 ** cp.to_lumetri_stops(preview_stops)
        lumetri_code = linear_lifted ** (1.0 / g) * 255.0

        assert math.isclose(ffmpeg_code, lumetri_code, rel_tol=1e-9)

    def test_measured_anchor_64_at_plus_one(self):
        """Тот самый замер: код 64, +1 EV.

        В ffmpeg получается 128 (ровное удвоение кода). Если те же «+1»
        вбить в Lumetri без пересчёта — выйдет ≈85, картинка заметно темнее
        выбранной. Разница между 128 и 85 — цена ошибки.
        """
        g = self.TRANSFER_GAMMA
        assert 64 * 2.0 ** 1.0 == 128.0

        naive = ((64 / 255.0) ** g * 2.0 ** 1.0) ** (1.0 / g) * 255.0
        assert round(naive) == 85

        correct = ((64 / 255.0) ** g * 2.0 ** cp.to_lumetri_stops(1.0)) ** (1.0 / g) * 255.0
        assert correct == pytest.approx(128.0, abs=1e-9)


class TestCheckLumetriStops:
    """Влезает ли пересчитанная экспозиция в ползунок Lumetri (±7)."""

    def test_fits_at_two_and_half(self):
        """2.5 витрины = 6.0 в Lumetri — влезает, работаем."""
        ok, why = cp.check_lumetri_stops(2.5)
        assert ok is True
        assert "6.00" in why

    def test_refuses_above_limit(self):
        """3.0 витрины = 7.2 в Lumetri — НЕ влезает, отказ.

        ⚠️ Зажимать молча нельзя: зажатая экспозиция даёт картинку, которая
        не совпадёт с витриной, и человек об этом не узнает. Такой клип надо
        переснимать на другой проявке, а не тянуть одной экспозицией.
        """
        ok, why = cp.check_lumetri_stops(3.0)
        assert ok is False
        assert "7.20" in why, f"в причине нет самого числа: {why}"

    def test_refuses_below_limit(self):
        """−3.0 витрины = −7.2 — отказ и в минус: предел двусторонний."""
        ok, why = cp.check_lumetri_stops(-3.0)
        assert ok is False
        assert "-7.20" in why, f"в причине нет самого числа: {why}"

    def test_reason_names_both_numbers(self):
        """В причине отказа стоят ОБА числа — и что выбрали в витрине, и во
        что это превратилось. Иначе по логу не понять, откуда взялся отказ."""
        _, why = cp.check_lumetri_stops(3.0)
        assert "3.00" in why and "7.20" in why

    def test_limit_boundary_is_inclusive(self):
        """Ровно на пределе (7.0 = 2.9166… витрины) ползунок ещё берёт.

        Граница задана как `abs(st) <= LIMIT`; сдвинуть её на строгое «<»
        значит отказать в решении, которое Premiere исполняет честно.
        """
        exact = cp.LUMETRI_EXPOSURE_LIMIT / cp.LUMETRI_GAMMA
        ok, _ = cp.check_lumetri_stops(exact)
        assert ok is True


# ───────────────────────────────────────────────── имена ступеней и лестница

class TestStopTag:
    """Канон имени ступени экспозиции в имени файла кадра."""

    @pytest.mark.parametrize("stop, tag", [
        (-1.0, "expm10"),
        (-0.5, "expm05"),
        (-0.0, "exp00"),
        (0.0, "exp00"),
        (0.5, "expp05"),
        (1.0, "expp10"),
        (2.5, "expp25"),
    ])
    def test_canonical_tags(self, stop, tag):
        """Тег ступени — формат, а не украшение: он вшит в имена кадров
        витрины, по нему панель находит, какой кадр какой ступени."""
        assert cp.stop_tag(stop) == tag

    def test_minus_zero_is_not_a_separate_step(self):
        """−0.0 и 0.0 — одна и та же ступень «не трогаем».

        Отрицательный ноль приезжает из арифметики (например, 0 × −1) и не
        имеет права породить второй, «минусовой» кадр нуля.
        """
        assert cp.stop_tag(-0.0) == cp.stop_tag(0.0) == "exp00"


class TestTagUniqueness:
    """Тег обязан РАЗЛИЧАТЬ все ступени, какие лестница вообще может родить."""

    def test_all_reachable_stops_get_distinct_tags(self):
        """Перебор промахов от −3 до +3 шагом 0.1: у всех собранных ступеней
        теги разные.

        ⚠️ Оплаченная ошибка, и не один раз. Коллизия тега = два кадра
        лестницы пишутся в один файл, второй затирает первый, и человек
        выбирает ступень, глядя на чужую картинку. Ровно этот класс
        («имя файла обязано нести ВСЁ, от чего зависит содержимое») стоил
        слою трёх отдельных багов за одну сессию.
        """
        stops = set()
        for i in range(-30, 31):
            stops.update(cp.ladder_for(i / 10.0))
        stops.update(cp.ladder_for(None))

        tags = {}
        for st in sorted(stops):
            tag = cp.stop_tag(st)
            assert tag not in tags, (
                f"коллизия тега {tag!r}: ступени {tags[tag]} и {st} "
                "пишутся в один файл кадра")
            tags[tag] = st
        assert len(tags) == len(stops)


class TestLadderFor:
    """Лестница ступеней: базовые ±1 всем, дальше — до промаха."""

    BASE = [-1.0, -0.5, 0.0, 0.5, 1.0]

    def test_no_miss_gives_base_five(self):
        """Промах не измерен (None) — ровно пять базовых ступеней.

        Это случай «кадра ещё нет»: гадать вслепую и рендерить лишнее не надо.
        """
        assert cp.ladder_for(None) == self.BASE

    def test_small_miss_gives_base_five(self):
        """Промах 0.3 укладывается в базовые — достраивать нечего."""
        assert cp.ladder_for(0.3) == self.BASE

    def test_big_positive_miss_extends_up(self):
        """Промах +2.7 — лестница дотягивается вверх до +3.

        ⚠️ Раньше такой клип получал те же пять ступеней и подпись
        «лестницы не хватает»: машина ЗНАЛА, что нужно больше, и всё равно
        предлагала потолок. Теперь нужные ступени просто есть.
        """
        assert cp.ladder_for(2.7) == [-1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]

    def test_big_negative_miss_extends_down(self):
        """Промах −2.2 — лестница достраивается вниз (и только вниз).

        ⚠️ До 22.09 вниз она упиралась в −2,0, хотя вверх дотягивалась до +3:
        набор доборных ступеней был несимметричен. Промах −2,5 достижим —
        `stops_to_target(255, 45) = −2,50`, то есть выбитое в белое лицо при
        тёмной выученной цели, — и такой клип получал потолок вместо нужной
        ступени. Ровно та болезнь, которую докстринг `ladder_for` объявляет
        вылеченной; теперь вылечена с обеих сторон.
        """
        assert cp.ladder_for(-2.2) == [-2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0]

    def test_ladder_is_symmetric(self):
        """Лестница тянется вниз ровно настолько же, насколько вверх.

        Страж на несимметричный EXPOSURE_EXTRA: пока набор правили руками,
        минусовая сторона отстала от плюсовой на две ступени и никто не заметил.
        """
        for miss in (1.2, 1.6, 2.2, 2.7, 3.0):
            up, down = cp.ladder_for(miss), cp.ladder_for(-miss)
            assert max(up) == -min(down), (
                f"промах ±{miss}: вверх до {max(up)}, вниз до {min(down)}")

    def test_ladder_never_exceeds_filter_limit(self):
        """Ни на каком промахе лестница не вылезает за ±3 — предел exposure
        в ffmpeg. Ступень за пределом отрендерить нечем."""
        for i in range(-60, 61):
            for st in cp.ladder_for(i / 10.0):
                assert -cp.EXPOSURE_MAX <= st <= cp.EXPOSURE_MAX

    def test_ladder_is_sorted_and_unique(self):
        """Лестница отсортирована и без повторов: по её порядку витрина
        раскладывает кадры слева направо."""
        for i in range(-30, 31):
            steps = cp.ladder_for(i / 10.0)
            assert steps == sorted(set(steps))
