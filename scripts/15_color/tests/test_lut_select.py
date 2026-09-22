#!/usr/bin/env python3
"""Тесты отбора кубов из библиотеки — lut_select.py (CLR-07).

Проверяем ПРАВИЛА БИБЛИОТЕКИ, то есть то, что решает, какой куб человеку вообще
покажут:

  CLR-07-A  develop_candidates: только своя гамма, только нетонирующая проявка,
            порядок — по цене в тенях
  CLR-07-B  строгость: незнакомая гамма = отказ, а не «подберём похожее»
  CLR-07-C  look_candidates: показываем ВСЕ покрасочные, выбор за человеком
  CLR-07-D  рекомендации: минимум зажатого чёрного / максимум характера без вреда
  CLR-07-E  файл куба на диске: store_path/verify_cube отказывают внятно
  CLR-07-F  short_name: подпись под кадром короче полного id

Тесты живут на фикстуре `small_luts` (12 записей настоящего манифеста) и ничего
не читают с диска, кроме taxonomy.json самой библиотеки.
"""
from __future__ import annotations

import hashlib

import pytest

import lut_select
import naming


# порог «проявка не имеет права красить» берётся ОТТУДА ЖЕ, откуда его берёт код:
# из taxonomy.json. Хардкод 3.0 в тесте разошёлся бы с калибровкой на 166 кубах.
DRIFT_MAX = naming.taxonomy()["stage_detect"]["neutral_drift255_develop_max"]


def _drift(lut):
    return lut["metrics"].get("neutral_drift255", 0.0)


def _black(lut):
    return lut["metrics"].get("black_share", 0.0)


def _slog3_develops(luts):
    """Все проявки S-Log3 в фикстуре — ищем ПО ДАННЫМ, а не по знакомым именам."""
    return [l for l in luts
            if l["stage"] == "develop"
            and naming.normalize_gamma((l.get("input") or {}).get("gamma")) == "S-Log3"]


class TestDevelopCandidates:
    def test_only_own_gamma(self, small_luts):
        """CLR-07-A: в кандидатах на S-Log3 нет ни одной чужой гаммы.

        Куб чужой гаммы — это не «немного другой контраст», а другая математика
        разжатия лога. Именно так 61 клип DJI получил математику Sony.
        """
        picked = lut_select.develop_candidates(small_luts, "S-Log3")
        assert picked, "фикстура обязана содержать хотя бы одну проявку S-Log3"
        assert all(naming.normalize_gamma(l["input"]["gamma"]) == "S-Log3" for l in picked)
        assert all(l["stage"] == "develop" for l in picked)

    def test_gamma_spelling_from_camera_is_accepted(self, small_luts):
        """CLR-07-A: сайдкар камеры пишет 's-log3-cine', манифест — 'S-Log3'.

        Отбор обязан свести их к одному ключу сам, иначе клип с живым сайдкаром
        останется без кандидатов и раскладка откажется на ровном месте.
        """
        assert (lut_select.develop_candidates(small_luts, "s-log3-cine")
                == lut_select.develop_candidates(small_luts, "S-Log3"))

    def test_tinted_develop_is_filtered_out(self, small_luts):
        """CLR-07-A: проявка с покраской внутри (большой neutral_drift255) в
        кандидаты не идёт, спокойная — идёт.

        Проявка обязана быть тональной: разжать логарифм и не трогать серое.
        Куб, который красит, протаскивает чужой вкус в технический шаг — а потом
        ещё и складывается со следующей ступенью, где вкус уже выбран.
        Кандидатов ищем по метрикам, не по именам: имя куба врёт (проверено на
        DJI Action basic.cube).
        """
        pool = _slog3_develops(small_luts)
        loud = max(pool, key=_drift)
        calm = min(pool, key=_drift)
        assert _drift(loud) > DRIFT_MAX, "фикстура должна содержать тонирующую проявку"
        assert _drift(calm) <= DRIFT_MAX

        ids = [l["id"] for l in lut_select.develop_candidates(small_luts, "S-Log3")]
        assert loud["id"] not in ids
        assert calm["id"] in ids

    def test_all_candidates_below_taxonomy_threshold(self, small_luts):
        """CLR-07-A: порог берётся из taxonomy (neutral_drift255_develop_max),
        и соблюдается для всех кандидатов, а не только для отсортированных сверху."""
        for g in ("S-Log3", "D-Log2"):
            for l in lut_select.develop_candidates(small_luts, g):
                assert _drift(l) <= DRIFT_MAX, f"{l['id']} тонирует серое на {_drift(l)}"

    def test_sorted_by_black_share(self, small_luts):
        """CLR-07-A: порядок — по возрастанию black_share.

        Зажатую тень не вернуть ничем, пережог светов у log→709 идёт по ролловфу.
        Первым в витрине должен стоять куб, который дешевле всего стоит в тенях:
        человек смотрит верхние варианты, и порядок здесь — это рекомендация.
        """
        for g in ("S-Log3", "D-Log2"):
            shares = [_black(l) for l in lut_select.develop_candidates(small_luts, g)]
            assert shares == sorted(shares), f"{g}: порядок кандидатов не по теням"

    def test_whole_gamma_tinted_gives_empty(self, small_luts):
        """CLR-07-A: если ВСЕ проявки гаммы тонируют — отдаём пусто, а не
        «ладно, покажем тонирующие».

        В фикстуре так устроена D-Log: обе проявки за порогом. Отказ здесь честный:
        лучше пустая клетка в витрине, чем куб с покраской под видом проявки.
        """
        pool = [l for l in small_luts
                if l["stage"] == "develop"
                and naming.normalize_gamma((l.get("input") or {}).get("gamma")) == "D-Log"]
        assert pool and all(_drift(l) > DRIFT_MAX for l in pool), "фикстура изменилась"
        assert lut_select.develop_candidates(small_luts, "D-Log") == []

    def test_limit_trims_tail(self, small_luts):
        """CLR-07-A: limit режет хвост, а не голову — остаётся самый дешёвый в тенях."""
        full = lut_select.develop_candidates(small_luts, "S-Log3")
        assert len(full) >= 2, "фикстура должна давать минимум двух кандидатов"
        assert lut_select.develop_candidates(small_luts, "S-Log3", limit=1) == full[:1]


class TestUnknownGammaIsRefusal:
    """CLR-07-B: СТРОГОСТЬ — в этом смысл всей системы.

    Правило дословно: незнакомая гамма = ОТКАЗ, а не «mismatch и поехали дальше».
    Снисходительность старого кода (поставить флаг mismatch и всё равно подобрать
    куб) покрасила 61 клип из 163 чужой математикой — это оплаченная ошибка, и
    эти два теста стоят ровно над ней.
    """

    def test_none_gamma_returns_empty(self, small_luts):
        """Гамма не определена → пустой список. Пустая клетка в витрине —
        это вопрос человеку, а подставленный куб — тихий брак в мастере."""
        assert lut_select.develop_candidates(small_luts, None) == []

    def test_unknown_gamma_returns_empty(self, small_luts):
        """Гамма есть, но библиотека её не знает → тоже пусто.
        Никакого «похожего» подбора: похожих логарифмических кривых не бывает."""
        assert lut_select.develop_candidates(small_luts, "Foo") == []

    def test_empty_string_returns_empty(self, small_luts):
        """Пустая строка из метаданных — та же незнакомая гамма, не «любая»."""
        assert lut_select.develop_candidates(small_luts, "") == []


class TestLookCandidates:
    def test_returns_every_look(self, small_luts):
        """CLR-07-C: отдаются ВСЕ покрасочные из библиотеки и только они."""
        looks = lut_select.look_candidates(small_luts)
        assert {l["id"] for l in looks} == {l["id"] for l in small_luts if l["stage"] == "look"}
        assert all(l["stage"] == "look" for l in looks)

    def test_no_silent_cut_to_eight(self):
        """CLR-07-C, РЕГРЕСС-СТРАЖ: первая версия резала список до восьми
        «репрезентативных», и Роман выбрал look, не увидев девятнадцати остальных.

        Фикстура из трёх look'ов такую регрессию не поймала бы, поэтому кормим
        функцию библиотекой из 27 покрасочных: по умолчанию обязаны вернуться все 27.
        """
        many = [{"id": f"look__synthetic_{i:02d}", "stage": "look",
                 "metrics": {"neutral_drift255": float(i)}} for i in range(27)]
        many.append({"id": "sony__slog3__rec709__neutral", "stage": "develop",
                     "input": {"gamma": "S-Log3"}, "metrics": {"neutral_drift255": 0.5}})
        assert len(lut_select.look_candidates(many)) == 27

    def test_sorted_from_calm_to_loud(self, small_luts):
        """CLR-07-C: порядок — по возрастанию neutral_drift255.
        Витрина читается слева направо: сначала спокойные, потом характерные."""
        drifts = [_drift(l) for l in lut_select.look_candidates(small_luts)]
        assert drifts == sorted(drifts)

    def test_explicit_limit_still_works(self):
        """CLR-07-C: явно попрошенный limit уважается — урезание осталось
        инструментом вызывающего, просто перестало быть поведением по умолчанию."""
        many = [{"id": f"look__synthetic_{i:02d}", "stage": "look",
                 "metrics": {"neutral_drift255": float(i)}} for i in range(27)]
        assert len(lut_select.look_candidates(many, limit=4)) == 4


class TestRecommendations:
    def test_develop_picks_minimal_black_share(self, small_luts):
        """CLR-07-D: рекомендуется проявка с минимумом зажатых теней.

        Это не вкус, а измеримый ущерб: замер 22.09 — neutral топит 14.9 % тёмного
        кадра, neutral legacy 0.01 %. Если рекомендация поедет на «первый в списке»
        или на «родную семью», человек будет по умолчанию получать убитые тени.
        """
        devs = lut_select.develop_candidates(small_luts, "S-Log3")
        best = lut_select.recommend_develop(devs)
        assert best is not None
        assert _black(best) == min(_black(d) for d in devs)

    def test_develop_on_empty_list_is_none(self):
        """CLR-07-D: кандидатов нет → рекомендации нет. Не исключение и не
        «возьмём хоть что-нибудь»: пустота здесь — законный ответ отказа."""
        assert lut_select.recommend_develop([]) is None

    def test_look_drops_damaged_and_takes_most_saturated(self, small_luts):
        """CLR-07-D: пережог > 2 % и зажатое чёрное > 1 % выбрасывают look из
        рассмотрения ДО сравнения насыщенности.

        Самый «характерный» кадр часто самый повреждённый — если сравнивать по
        sat без отсева, рекомендацией станет куб, который режет картинку.
        """
        looks = lut_select.look_candidates(small_luts)
        assert len(looks) >= 3, "фикстура должна давать минимум три look'а"
        a, b, c = looks[0], looks[1], looks[2]
        metrics = {
            a["id"]: {"clip": 0.1, "black": 0.1, "sat": 0.30},
            b["id"]: {"clip": 9.0, "black": 0.1, "sat": 0.99},   # пережог
            c["id"]: {"clip": 0.1, "black": 5.0, "sat": 0.98},   # зажатый чёрный
        }
        assert lut_select.recommend_look(looks, metrics)["id"] == a["id"]

    def test_look_when_everything_is_damaged_still_answers(self, small_luts):
        """CLR-07-D: если повреждены ВСЕ, функция всё равно возвращает куб, не None.

        Витрина обязана показать рекомендацию всегда: человек имеет право увидеть
        «лучшее из плохого» и решить сам. None здесь превратился бы в пустое место
        без объяснения.
        """
        looks = lut_select.look_candidates(small_luts)
        metrics = {l["id"]: {"clip": 50.0, "black": 50.0, "sat": i}
                   for i, l in enumerate(looks)}
        best = lut_select.recommend_look(looks, metrics)
        assert best is not None
        assert best["id"] == looks[-1]["id"], "из повреждённых берётся самый насыщенный"

    def test_look_without_metrics_still_answers(self, small_luts):
        """CLR-07-D: метрик ещё не замерили (кадры не отрендерены) → не падаем."""
        assert lut_select.recommend_look(lut_select.look_candidates(small_luts), {}) is not None

    def test_look_on_empty_list_is_none(self):
        """CLR-07-D: покрасочных нет вовсе → None, без обращения к пустому max()."""
        assert lut_select.recommend_look([], {}) is None


class TestCubeOnDisk:
    def test_store_path_is_relative_to_store_root(self, small_luts, monkeypatch, tmp_path):
        """CLR-07-E: поле file в манифесте — путь ОТ КОРНЯ store, а не от cwd.

        Ошибись тут, и путь соберётся от текущей папки: запуск из другого места
        начнёт «терять» кубы, которые лежат на месте.
        """
        monkeypatch.setattr(lut_select, "STORE", tmp_path)
        entry = small_luts[0]
        assert lut_select.store_path(entry) == tmp_path / entry["file"]
        assert lut_select.store_path(entry).is_absolute()

    def test_missing_file_refusal_names_the_path(self, monkeypatch, tmp_path):
        """CLR-07-E: запись есть, а куба на диске нет (чужой id, не из манифеста)
        → отказ с ПУТЁМ внутри.

        Причину читает человек и идёт по ней руками, поэтому путь в тексте —
        часть контракта, а не украшение.
        """
        monkeypatch.setattr(lut_select, "STORE", tmp_path)
        entry = {"id": "look__nikogda_ne_bylo", "file": "look/look__nikogda_ne_bylo.cube",
                 "sha256": "0" * 64}
        ok, why = lut_select.verify_cube(entry)
        assert ok is False
        assert str(tmp_path / entry["file"]) in why

    def test_entry_without_sha_is_refused(self, monkeypatch, tmp_path):
        """CLR-07-E: файл на месте, но в манифесте нет sha256 → всё равно отказ,
        и в причине сказано про sha.

        «Файл есть» не равно «файл тот самый». Куб — это математика в мастере:
        подменённый или побитый файл красит молча и до конца фильма.
        """
        monkeypatch.setattr(lut_select, "STORE", tmp_path)
        (tmp_path / "look").mkdir()
        (tmp_path / "look" / "look__travel.cube").write_text("TITLE \"travel\"\n", encoding="utf-8")
        ok, why = lut_select.verify_cube({"id": "look__travel", "file": "look/look__travel.cube"})
        assert ok is False
        assert "sha" in why.lower()

    def test_matching_sha_passes(self, monkeypatch, tmp_path):
        """CLR-07-E: файл на месте и sha сходится → (True, "") без лишних слов."""
        monkeypatch.setattr(lut_select, "STORE", tmp_path)
        (tmp_path / "look").mkdir()
        body = b"LUT_3D_SIZE 2\n0 0 0\n1 1 1\n"
        (tmp_path / "look" / "look__travel.cube").write_bytes(body)
        entry = {"id": "look__travel", "file": "look/look__travel.cube",
                 "sha256": hashlib.sha256(body).hexdigest()}
        assert lut_select.verify_cube(entry) == (True, "")

    def test_tampered_file_is_caught(self, monkeypatch, tmp_path):
        """CLR-07-E: содержимое изменилось при том же имени → отказ.

        Ровно этот случай молчаливый: имя прежнее, размер похожий, а числа внутри
        куба другие. Без сверки sha такой куб уезжает в мастер незамеченным.
        """
        monkeypatch.setattr(lut_select, "STORE", tmp_path)
        (tmp_path / "look").mkdir()
        entry = {"id": "look__travel", "file": "look/look__travel.cube",
                 "sha256": hashlib.sha256(b"original").hexdigest()}
        (tmp_path / "look" / "look__travel.cube").write_bytes(b"podmenili")
        ok, why = lut_select.verify_cube(entry)
        assert ok is False
        assert "sha256" in why


class TestShortName:
    @pytest.mark.parametrize("lut_id", [
        "sony__slog3_sgamut3cine__rec709__neutral__legacy",
        "dji_pocket4p__dlog2__rec709__plus",
        "look__ritter_sport",
        "pre__any__wdr",
    ])
    def test_short_name_is_short_and_not_empty(self, lut_id):
        """CLR-07-F: подпись под кадром не пустая и короче полного id.

        Полный id — для манифеста, не для глаза. Пустая подпись в витрине
        оставляет человека выбирать между безымянными картинками.
        """
        short = lut_select.short_name(lut_id)
        assert short.strip()
        assert len(short) < len(lut_id)

    def test_short_name_keeps_the_distinguishing_part(self):
        """CLR-07-F: в подписи остаётся то, что РАЗЛИЧАЕТ кубы (семья и вариант),
        и уходит служебное — префикс look__ и технический rec709.

        Две соседние карточки витрины отличаются именно вариантом: «neutral» и
        «neutral legacy» — разные кубы с разной ценой в тенях.
        """
        assert lut_select.short_name("look__ritter_sport") == "ritter sport"
        neutral = lut_select.short_name("sony__slog3_sgamut3cine__rec709__neutral")
        legacy = lut_select.short_name("sony__slog3_sgamut3cine__rec709__neutral__legacy")
        assert "rec709" not in legacy
        assert "legacy" in legacy
        assert neutral != legacy
