"""Тесты color_plan.py — арифметика цвета без картинок.

Покрываемые требования:
  CLR-02: ключи клипов — clip_key / clip_slug / slug_index (контракт с панелью
          UXP и с ~1100 именами кадров витрины)
  CLR-03: ДНК канала — resolve_develop / resolve_look (отказ вместо догадки)
  CLR-04: кэш гамм — load / save / stale / посев из старого lut_plan
  CLR-05: безопасная запись — save_json_atomic / backup

⚠️ Модуль под тестом обязан быть чистым stdlib: он считает при РАЗМОНТИРОВАННОЙ
карте и на машине без медиатеки. Поэтому здесь нет ни ffmpeg, ни Vision, ни
numpy/PIL, и ни один тест не выходит за tmp_path.

Запуск:  /opt/homebrew/bin/pytest scripts/15_color/tests/test_color_plan.py -q
"""
from __future__ import annotations

import json

import pytest

# conftest.py уже положил папки всех трёх этапов в sys.path.
import color_plan as _plan


# ─────────────────────────────────────────────────── CLR-02: ключи клипов ──

class TestClipKey:
    def test_key_format_is_scene_slash_filename(self):
        """CLR-02: ключ — ровно "сцена/имя.MP4", без нормализации имени.

        Этот формат читает панель UXP: она пере-ключует раскладку по basename
        ключа. Любая «косметика» (нижний регистр, срез расширения, обратный
        слэш) — и панель не найдёт на таймлайне ни одного клипа.
        """
        assert _plan.clip_key("01_Morning_Run", "RYA-FX3-1212.MP4") == \
            "01_Morning_Run/RYA-FX3-1212.MP4"

    def test_key_keeps_dots_dashes_and_case(self):
        """CLR-02: имя файла попадает в ключ ДОСЛОВНО.

        Панель сравнивает `key.split("/")[-1]` с именем файла на таймлайне —
        значит правая часть ключа обязана совпадать с ним байт в байт.
        """
        name = "DJI_20260918072725_0008_D.MP4"
        key = _plan.clip_key("05_Isaakiy_Cathedral_Service", name)
        assert key.split("/")[-1] == name
        assert key.count("/") == 1

    def test_key_separator_is_forward_slash(self):
        """CLR-02: разделитель — прямой слэш, а не os.sep.

        Тест стережёт от «улучшения» через os.path.join: на Windows-сборке
        Premiere ключ стал бы с обратным слэшем и разъехался с JSON раскладки.
        """
        assert "\\" not in _plan.clip_key("02_Walk", "RYA-ZVE1-1890.MP4")


class TestClipSlug:
    def test_slug_format(self):
        """CLR-02: слаг — "сцена_стем", без расширения.

        Слаг вшит в ~1100 имён уже отрендеренных кадров витрины: изменишь
        правило — все готовые кадры разом станут «чужими».
        """
        assert _plan.clip_slug("01_Morning_Run", "RYA-FX3-1212") == \
            "01_Morning_Run_RYA_FX3_1212"

    def test_slug_collapses_non_alnum_runs(self):
        """CLR-02: любая пачка не-латиницы/не-цифр схлопывается в ОДНО "_".

        Важно именно «в одно»: пара точек или дефис-с-пробелом не имеют права
        дать разную длину слага, иначе имя кадра поедет от версии к версии.
        """
        assert _plan.clip_slug("01 Morning--Run", "RYA..FX3 -1212") == \
            "01_Morning_Run_RYA_FX3_1212"

    def test_slug_survives_cyrillic_scene(self):
        """CLR-02: кириллица в имени сцены не ломает слаг и не течёт в файл.

        Имя файла кадра должно оставаться латинским (правило слоя), поэтому
        нелатинские буквы обязаны стать подчёркиванием, а не остаться как есть.
        """
        slug = _plan.clip_slug("01_Утро", "RYA-FX3-1212")
        assert slug == "01_RYA_FX3_1212"
        assert slug.replace("_", "").isalnum()


class TestSlugIndex:
    def test_real_day_has_no_collisions(self, legacy_plan):
        """CLR-02: 163 клипа настоящего дня YTEVO03 дают 163 разных слага.

        Это проверка на реальном материале: если правило слага когда-нибудь
        станет «жаднее» (например, схлопнет и цифры), на этом дне сразу
        появятся дубли и тест упадёт.
        """
        keys = list(legacy_plan["clips"])
        assert len(keys) == 163
        idx = _plan.slug_index(keys)
        assert len(idx) == 163

    def test_index_maps_slug_back_to_key(self, legacy_plan):
        """CLR-02: обратный путь слаг → канонический ключ работает.

        Слаг ЛОССОВЫЙ, восстановить ключ разбором строки нельзя — только через
        эту карту. Значит карта обязана содержать полный ключ с расширением.
        """
        idx = _plan.slug_index(legacy_plan["clips"])
        assert idx["01_Morning_Run_RYA_FX3_1212"] == "01_Morning_Run/RYA-FX3-1212.MP4"

    def test_collision_raises(self):
        """CLR-02: два РАЗНЫХ клипа с одним слагом → SlugCollision.

        Оплаченная ошибка, которую стережёт тест: молча взять первый — значит
        положить кадры второго клипа поверх кадров первого, и витрина покажет
        Роману чужую картинку под правильной подписью.
        """
        keys = ["01_Morning_Run/RYA-FX3-1212.MP4",
                "01_Morning_Run/RYA.FX3.1212.MP4"]
        with pytest.raises(_plan.SlugCollision):
            _plan.slug_index(keys)

    def test_collision_message_names_both_clips(self):
        """CLR-02: в тексте отказа названы ОБА виновника.

        Отказ без имён заставляет искать виновный файл среди 163 клипов
        руками — тогда проще «временно» снять проверку, а это и есть тот путь,
        которым баг возвращается.
        """
        keys = ["02_Walk/A-1.MP4", "02_Walk/A_1.MP4"]
        with pytest.raises(_plan.SlugCollision) as e:
            _plan.slug_index(keys)
        assert "02_Walk/A-1.MP4" in str(e.value)
        assert "02_Walk/A_1.MP4" in str(e.value)

    def test_same_key_twice_is_not_collision(self):
        """CLR-02: повтор ОДНОГО И ТОГО ЖЕ ключа — не коллизия.

        На вход карте приходят ключи из разных источников (план, кэш, диск), и
        дубликаты там норма. Падать на них — значит останавливать прогон
        на пустом месте.
        """
        keys = ["01_Morning_Run/RYA-FX3-1212.MP4"] * 3
        assert _plan.slug_index(keys) == {
            "01_Morning_Run_RYA_FX3_1212": "01_Morning_Run/RYA-FX3-1212.MP4"}


# ────────────────────────────────────────────────────── CLR-03: ДНК канала ──

class TestResolveDevelop:
    def test_slog3_from_profile(self, ytevo_profile):
        """CLR-03: по гамме S-Log3 отдаётся ровно тот id, что в профиле."""
        lut, why = _plan.resolve_develop(ytevo_profile, "S-Log3")
        assert lut == ytevo_profile["develop"]["S-Log3"]["lut"]
        assert "S-Log3" in why

    def test_dlog2_from_profile(self, ytevo_profile):
        """CLR-03: D-Log2 получает СВОЙ куб, а не соседний.

        Это и есть суть слоя: до сентября 2026 весь DJI красился S-Log3-лутом —
        61 клип из 163 на дне YTEVO03. Тест падает, если D-Log2 снова начнёт
        получать проявку другой гаммы.
        """
        lut, _ = _plan.resolve_develop(ytevo_profile, "D-Log2", "CAM-C_Pocket")
        assert lut == ytevo_profile["develop"]["D-Log2"]["lut"]
        assert lut != ytevo_profile["develop"]["S-Log3"]["lut"]

    def test_unknown_gamma_refuses(self, ytevo_profile):
        """CLR-03: гамма, которой нет в профиле ("V-Log") → DevelopUnknown.

        ⚠️ Оплаченная ошибка: снисходительность «гамма не совпала — ставим флаг
        mismatch и едем дальше» покрасила 61 клип чужой математикой. Отказ
        вместо догадки — смысл всей системы.
        """
        with pytest.raises(_plan.DevelopUnknown):
            _plan.resolve_develop(ytevo_profile, "V-Log")

    def test_refusal_lists_known_gammas(self, ytevo_profile):
        """CLR-03: отказ перечисляет, какие гаммы профиль ЗНАЕТ.

        Человеку нужно за один взгляд понять: снято в новой гамме или профиль
        просто ещё не дополнен.
        """
        with pytest.raises(_plan.DevelopUnknown) as e:
            _plan.resolve_develop(ytevo_profile, "V-Log")
        assert "S-Log3" in str(e.value) and "D-Log2" in str(e.value)

    def test_gamma_none_refuses(self, ytevo_profile):
        """CLR-03: гамма не определена (None) → отказ, а не «проявка по умолчанию».

        Незамеренная гамма — это ровно тот клип, которому нельзя угадывать куб:
        сайдкара нет, карта размонтирована, кэш пуст. Он обязан остановить
        прогон и назваться по имени.
        """
        with pytest.raises(_plan.DevelopUnknown):
            _plan.resolve_develop(ytevo_profile, None)

    def test_empty_gamma_string_refuses(self, ytevo_profile):
        """CLR-03: пустая строка гаммы — тот же отказ, что и None.

        Метаданные отдают "" ничуть не реже, чем None: ffprobe на клипе без
        тега возвращает пустое поле.
        """
        with pytest.raises(_plan.DevelopUnknown):
            _plan.resolve_develop(ytevo_profile, "")

    @pytest.mark.parametrize("profile", [{}, None, {"develop": {}}])
    def test_empty_profile_refuses(self, profile):
        """CLR-03: пустой профиль (первый день канала) → отказ, не падение.

        День без ДНК канала обязан упереться в понятный DevelopUnknown, а не
        в KeyError/AttributeError из середины эмиттера.
        """
        with pytest.raises(_plan.DevelopUnknown):
            _plan.resolve_develop(profile, "S-Log3")

    def test_entry_without_lut_refuses(self):
        """CLR-03: запись гаммы есть, а поле lut пустое → отказ.

        Полупустой профиль (гамму записали, куб не выбрали) не имеет права
        отдать None вниз по течению: None доедет до Lumetri как «без проявки».
        """
        profile = {"develop": {"S-Log3": {"cameras": ["CAM-A_FX3"]}}}
        with pytest.raises(_plan.DevelopUnknown):
            _plan.resolve_develop(profile, "S-Log3")


class TestResolveDevelopByCamera:
    """Одна гамма у РАЗНЫХ тушек может означать разные кубы.

    Не теория: taxonomy._body_independent прямо говорит, что у Sony гамма от
    тушки не зависит, а у DJI зависит — «Pocket 4 и Pocket 4P — разные кубы под
    одним именем D-Log». Сегодня не бьёт только потому, что под D-Log2 в парке
    одна тушка; завтра появится вторая.
    """

    @staticmethod
    def _profile():
        return {"develop": {"D-Log": {
            "lut": "dji_pocket4__dlog__rec709__neutral",
            "by_camera": {"CAM-D_Pocket4P": "dji_pocket4p__dlog__rec709__neutral"},
            "cameras": ["CAM-C_Pocket4", "CAM-D_Pocket4P"],
        }}}

    def test_by_camera_beats_gamma_lut(self):
        """CLR-03: by_camera[роль] сильнее develop[гамма].lut.

        Если порядок перевернётся, вторая тушка получит куб первой — ровно тот
        класс ошибки, ради которого слой и переписан.
        """
        lut, why = _plan.resolve_develop(self._profile(), "D-Log", "CAM-D_Pocket4P")
        assert lut == "dji_pocket4p__dlog__rec709__neutral"
        assert "CAM-D_Pocket4P" in why

    def test_known_body_without_override_takes_gamma_lut(self):
        """CLR-03: тушка без персональной записи берёт общий куб гаммы.

        Иначе by_camera пришлось бы заполнять на КАЖДУЮ камеру канала, и
        обычный случай (гамма решает) стал бы дороже исключения.
        """
        lut, why = _plan.resolve_develop(self._profile(), "D-Log", "CAM-C_Pocket4")
        assert lut == "dji_pocket4__dlog__rec709__neutral"
        assert "D-Log" in why

    def test_unknown_body_without_gamma_lut_refuses(self):
        """CLR-03: только by_camera, роль незнакомая → отказ.

        Профиль, где расписаны лишь конкретные тушки, не должен тихо
        подставлять чужой куб новой камере — она приедет в парк раньше, чем
        Роман успеет дополнить ДНК.
        """
        profile = {"develop": {"D-Log": {
            "by_camera": {"CAM-D_Pocket4P": "dji_pocket4p__dlog__rec709__neutral"}}}}
        with pytest.raises(_plan.DevelopUnknown):
            _plan.resolve_develop(profile, "D-Log", "CAM-Z_New")


class TestResolveLook:
    def test_look_from_profile(self, ytevo_profile):
        """CLR-03: покраска берётся из ДНК канала — ОДНА на канал."""
        assert _plan.resolve_look(ytevo_profile) == "look__newstar"

    @pytest.mark.parametrize("profile", [{}, None, {"look": None}, {"look": {}}])
    def test_look_absent_is_none_not_error(self, profile):
        """CLR-03: нет look — это ЗАКОННЫЙ план, а не ошибка.

        Проявка без покраски — нормальная сдача (например, документальный день).
        Если отсутствие look когда-нибудь начнёт бросать, слой встанет на ровном
        месте.
        """
        assert _plan.resolve_look(profile) is None


# ──────────────────────────────────────────────────────── CLR-04: кэш гамм ──

class TestGammaCacheIO:
    def test_load_on_empty_place_is_empty_dict(self, fake_project):
        """CLR-04: кэша ещё нет → {} (не None, не исключение).

        Вызывающий делает cache.get(key) сразу после загрузки: None здесь
        означал бы AttributeError на каждом первом прогоне дня.
        """
        assert _plan.load_gamma_cache(fake_project, "YTEVO99") == {}

    def test_save_then_load_roundtrip(self, fake_project):
        """CLR-04: записанное читается обратно один в один.

        Кэш — единственный источник гаммы при размонтированной карте; потеря
        хоть одного поля на круге означает отказ проявки на следующий день.
        """
        clips = {"01_Morning_Run/RYA-FX3-1212.MP4": {
            "gamma": "S-Log3", "gamma_raw": "s-log3-cine", "source": "sidecar_m01xml",
            "cam": "CAM-A_FX3", "pix_fmt": "yuv422p10le", "size": 64, "mtime": 1.0}}
        _plan.save_gamma_cache(fake_project, "YTEVO99", clips)
        assert _plan.load_gamma_cache(fake_project, "YTEVO99") == clips

    def test_saved_file_lives_in_lut_home_and_names_itself(self, fake_project):
        """CLR-04: файл лежит в доме лутов, в `_build`, и описывает сам себя.

        Через месяц по голому словарю гамм не восстановить, откуда он взялся:
        поэтому в файле обязаны быть schema, project и пояснение. А место —
        `01_Source/00_LUT/_build`: у лутов один дом, и «как выбирали» хранится
        рядом с «чем красим», но этажом ниже, чтобы не мешалось на глазах.
        """
        p = _plan.save_gamma_cache(fake_project, "YTEVO99", {})
        assert p == (fake_project / "01_Source" / "00_LUT" / "_build"
                     / "YTEVO99_gamma_cache.json")
        doc = json.loads(p.read_text(encoding="utf-8"))
        assert doc["schema"] == "gamma-cache-v1"
        assert doc["project"] == "YTEVO99"
        assert doc["_note"]

    def test_old_address_is_still_read_but_never_written(self, fake_project):
        """CLR-04b: проект, собранный ДО переезда, продолжает собираться.

        ⚠️ Кэш гамм заведён ровно затем, чтобы пережить размонтированную карту.
        Потерять его на переезде — отменить его смысл именно в тот день, когда
        он нужен. Поэтому чтение знает оба адреса, а запись — только новый:
        файл в старом месте остаётся нетронутым, как и любая наша копия.
        """
        old = _plan.legacy_build_dir(fake_project) / "YTEVO99_gamma_cache.json"
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_text(json.dumps({"clips": {"01_A/x.MP4": {"gamma": "S-Log3"}}}),
                       encoding="utf-8")
        assert _plan.load_gamma_cache(fake_project, "YTEVO99") == {
            "01_A/x.MP4": {"gamma": "S-Log3"}}

        new = _plan.save_gamma_cache(fake_project, "YTEVO99",
                                     {"02_B/y.MP4": {"gamma": "D-Log2"}})
        assert new == _plan.lut_build_dir(fake_project) / "YTEVO99_gamma_cache.json"
        assert old.exists(), "старый файл не удаляем никогда"
        # слияние произошло через старый адрес — записи прошлого дня не потеряны
        got = _plan.load_gamma_cache(fake_project, "YTEVO99")
        assert set(got) == {"01_A/x.MP4", "02_B/y.MP4"}


class TestGammaCacheStale:
    @staticmethod
    def _clip(fake_project):
        return (fake_project / "01_Source" / "01_Morning_Run" / "CAM-A_FX3"
                / "RYA-FX3-1212.MP4")

    def test_unchanged_clip_is_fresh(self, fake_project):
        """CLR-04: размер и mtime совпали → запись свежая, замер не повторяем.

        Иначе каждый прогон заново гонял бы ffprobe по всем 163 клипам дня.
        """
        clip = self._clip(fake_project)
        st = clip.stat()
        rec = {"size": st.st_size, "mtime": st.st_mtime}
        assert _plan.gamma_cache_stale(rec, clip) is False

    def test_size_change_is_stale(self, fake_project):
        """CLR-04: размер файла разошёлся с кэшем → запись устарела.

        Тот же путь после перезаливки карты — это ДРУГОЙ материал; взять его
        гамму из кэша значит проявить новый клип по чужому замеру.
        """
        clip = self._clip(fake_project)
        rec = {"size": clip.stat().st_size + 1, "mtime": clip.stat().st_mtime}
        assert _plan.gamma_cache_stale(rec, clip) is True

    def test_mtime_drift_is_stale(self, fake_project):
        """CLR-04: тот же размер, но другая дата → тоже устарела.

        Перекодированный клип часто совпадает по размеру случайно; дата ловит
        такие случаи.
        """
        clip = self._clip(fake_project)
        st = clip.stat()
        assert _plan.gamma_cache_stale({"size": st.st_size, "mtime": st.st_mtime - 500},
                                       clip) is True

    def test_record_without_size_is_never_stale(self, fake_project):
        """CLR-04: ⚠️ size=None в записи → ВСЕГДА False.

        Оплаченная ошибка, которую стережёт тест: посев из старого плана кладёт
        size=None (файлов тогда не видели). Если такую запись объявить
        устаревшей, кэш выбросит именно то, ради чего заведён.
        """
        clip = self._clip(fake_project)
        assert _plan.gamma_cache_stale({"size": None, "mtime": None}, clip) is False
        assert _plan.gamma_cache_stale({"gamma": "S-Log3"}, clip) is False

    def test_missing_clip_is_never_stale(self, fake_project):
        """CLR-04: ⚠️ оригинала нет на месте (карта размонтирована) → False.

        Это главный сценарий кэша: симлинк на съёмную карту, карты нет. Если
        недоступный файл считать «изменившимся», кэш самоуничтожится ровно в
        тот момент, ради которого его завели, и слой встанет.
        """
        gone = fake_project / "01_Source" / "01_Morning_Run" / "CAM-A_FX3" / "нет.MP4"
        assert _plan.gamma_cache_stale({"size": 64, "mtime": 1.0}, gone) is False


class TestSeedFromLegacyPlan:
    def test_seeds_every_clip_of_the_day(self, legacy_plan):
        """CLR-04: из старого плана поднимаются все 163 клипа.

        Старый lut_plan — единственное место, где гаммы этого дня записаны, пока
        карта не примонтирована. Потерять часть на посеве = отказ проявки на эти
        клипы.
        """
        seeded = _plan.seed_gamma_cache_from_lut_plan(legacy_plan, {})
        assert len(seeded) == 163

    def test_source_marks_origin(self, legacy_plan):
        """CLR-04: у каждой записи source == "legacy_lut_plan".

        По этой метке видно, что гамма не замерена, а унаследована: доверие к
        ней ниже, и живой сайдкар обязан её перебить.
        """
        seeded = _plan.seed_gamma_cache_from_lut_plan(legacy_plan, {})
        assert {r["source"] for r in seeded.values()} == {"legacy_lut_plan"}

    def test_raw_gamma_kept_verbatim(self, legacy_plan):
        """CLR-04: сырая строка сохраняется ДОСЛОВНО рядом с нормализованной.

        Sony пишет в сайдкар "s-log3-cine", библиотека знает "S-Log3". Если
        завтра найдётся баг в нормализации, его переприменят по gamma_raw, не
        поднимая карту.
        """
        seeded = _plan.seed_gamma_cache_from_lut_plan(legacy_plan, {})
        rec = seeded["01_Morning_Run/RYA-FX3-1212.MP4"]
        assert rec["gamma_raw"] == "s-log3-cine"
        assert rec["gamma"] == "S-Log3"

    def test_dlog2_does_not_collapse_to_dlog(self, legacy_plan):
        """CLR-04: "D-Log2" остаётся D-Log2, а не схлопывается в D-Log.

        ⚠️ Оплаченная ошибка нормализации: порядок пар в normalize_gamma
        несущий, и при 'dlog' раньше 'dlog2' весь DJI дня получил бы куб чужой
        гаммы — те самые 61 клип из 163.
        """
        seeded = _plan.seed_gamma_cache_from_lut_plan(legacy_plan, {})
        rec = seeded["01_Morning_Run/DJI_20260918072725_0008_D.MP4"]
        assert rec["gamma_raw"] == "D-Log2"
        assert rec["gamma"] == "D-Log2"

    def test_keys_are_canonical_when_map_given(self):
        """CLR-04: ключ старого плана переводится в канонический по basename.

        Сцены между старым планом и сегодняшней раскладкой переименовывают;
        привязка идёт по имени файла, иначе гаммы не найдут свои клипы.
        """
        plan = {"clips": {"старая_сцена/RYA-FX3-1212.MP4": {"gamma": "s-log3-cine"}}}
        seeded = _plan.seed_gamma_cache_from_lut_plan(
            plan, {"RYA-FX3-1212.MP4": "01_Morning_Run/RYA-FX3-1212.MP4"})
        assert list(seeded) == ["01_Morning_Run/RYA-FX3-1212.MP4"]

    def test_key_kept_when_clip_not_on_disk(self):
        """CLR-04: клипа нет в сегодняшней карте — ключ плана сохраняется как есть.

        Выбрасывать такие записи нельзя: карта могла быть просто не
        примонтирована, а гамма из них ещё пригодится.
        """
        plan = {"clips": {"07_Gone/RYA-FX3-9999.MP4": {"gamma": "s-log3-cine"}}}
        seeded = _plan.seed_gamma_cache_from_lut_plan(plan, {})
        assert list(seeded) == ["07_Gone/RYA-FX3-9999.MP4"]

    def test_clips_without_gamma_are_skipped(self):
        """CLR-04: запись без гаммы в посев не идёт.

        Пустая гамма в кэше выглядела бы как замеренная и не дала бы слою
        честно отказаться на этом клипе (см. CLR-03).
        """
        plan = {"clips": {"01/A.MP4": {"cam": "CAM-A_FX3"},
                          "01/B.MP4": {"gamma": None},
                          "01/C.MP4": {"gamma": "D-Log2"}}}
        assert list(_plan.seed_gamma_cache_from_lut_plan(plan, {})) == ["01/C.MP4"]

    def test_seeded_record_survives_unmounted_card(self, fake_project, legacy_plan):
        """CLR-04: посеянная запись не считается устаревшей ни при каком файле.

        Связка двух правил: посев кладёт size=None, а gamma_cache_stale на
        size=None отвечает False. Тест держит именно связку — порознь их легко
        «починить» по отдельности и потерять смысл.
        """
        seeded = _plan.seed_gamma_cache_from_lut_plan(legacy_plan, {})
        rec = seeded["01_Morning_Run/RYA-FX3-1212.MP4"]
        assert rec["size"] is None and rec["mtime"] is None
        clip = fake_project / "01_Source" / "01_Morning_Run" / "CAM-A_FX3" / "RYA-FX3-1212.MP4"
        assert _plan.gamma_cache_stale(rec, clip) is False


# ────────────────────────────────────────────────── CLR-05: запись на диск ──

class TestSaveJsonAtomic:
    def test_writes_and_creates_parents(self, tmp_path):
        """CLR-05: файл пишется вместе с недостающими папками, читается обратно."""
        target = tmp_path / "00_Setup" / "01_Ingest" / "plan.json"
        _plan.save_json_atomic(target, {"кадры": 163, "look": "look__newstar"})
        assert json.loads(target.read_text(encoding="utf-8"))["кадры"] == 163

    def test_no_tmp_left_after_success(self, tmp_path):
        """CLR-05: после успешной записи .tmp рядом не остаётся.

        Забытый .tmp попадает в зеркало на Drive и в глаза монтажёру как
        «второй план» — ровно та путаница, из-за которой красят не тем кубом.
        """
        target = tmp_path / "plan.json"
        _plan.save_json_atomic(target, {"a": 1})
        assert list(tmp_path.glob("*.tmp")) == []

    def test_failed_serialisation_keeps_old_file(self, tmp_path, monkeypatch):
        """CLR-05: сериализация упала → СТАРЫЙ файл цел и .tmp не остался.

        Оплаченная ошибка, которую стережёт тест: до 21.09 здесь был
        безусловный write_text(), затиравший утверждённый Романом план вместе с
        ручными правками. Провалившаяся запись обязана не тронуть ничего.
        """
        target = tmp_path / "plan.json"
        _plan.save_json_atomic(target, {"approved": "roman", "clips": 163})
        before = target.read_text(encoding="utf-8")

        def _boom(*a, **kw):
            raise TypeError("объект не сериализуется")

        monkeypatch.setattr(_plan.json, "dumps", _boom)
        with pytest.raises(TypeError):
            _plan.save_json_atomic(target, {"clips": object()})

        assert target.read_text(encoding="utf-8") == before
        assert list(tmp_path.glob("*.tmp")) == []


class TestBackup:
    def test_backup_copies_file_next_to_original(self, tmp_path):
        """CLR-05: backup() кладёт копию РЯДОМ и возвращает её путь.

        «Рядом» — не деталь: копия на том же томе переживает и отключение
        сетевого диска, и переезд проекта целиком.
        """
        target = tmp_path / "YTEVO03_color_plan.json"
        target.write_text('{"approved": "roman"}', encoding="utf-8")
        bak = _plan.backup(target)
        assert bak.parent == target.parent
        assert bak.name.startswith("YTEVO03_color_plan.")
        assert bak.name.endswith(".bak.json")
        assert bak.read_text(encoding="utf-8") == '{"approved": "roman"}'

    def test_backup_does_not_touch_original(self, tmp_path):
        """CLR-05: оригинал после бэкапа не изменился и остался на месте.

        Копия — не перемещение: вызывающий пишет в оригинал сразу после.
        """
        target = tmp_path / "plan.json"
        target.write_text("{}", encoding="utf-8")
        _plan.backup(target)
        assert target.exists() and target.read_text(encoding="utf-8") == "{}"

    def test_backup_of_missing_file_returns_none(self, tmp_path):
        """CLR-05: копировать нечего → None, без исключения и без пустого файла.

        Первая запись плана — это нормальный случай, и он не должен падать.
        """
        assert _plan.backup(tmp_path / "нет.json") is None
        assert list(tmp_path.iterdir()) == []


class TestFoundBugsStayFixed:
    """Сторожа на пять дефектов, найденных тестами 22.09 при первом же прогоне.

    Все пять — в коде, который написан в ту же сессию. Тесты нашли их раньше
    Premiere, и это главное, ради чего набор заводился.
    """

    def test_backup_never_overwrites_a_previous_copy(self, tmp_path):
        """CLR-05-F: две копии в одну секунду — две РАЗНЫЕ копии.

        ⚠️ Метка имела точность до секунды, и второй вызов затирал первую копию.
        Это ровно тот сценарий, ради которого backup() заведён: перезапись
        утверждённого плана. Копия, молча затёршая другую копию, хуже отсутствия.
        """
        p = tmp_path / "plan.json"
        p.write_text('{"a":1}', encoding="utf-8")
        b1 = _plan.backup(p)
        p.write_text('{"a":2}', encoding="utf-8")
        b2 = _plan.backup(p)
        assert b1 != b2, "вторая копия легла поверх первой"
        assert b1.read_text(encoding="utf-8") == '{"a":1}'
        assert b2.read_text(encoding="utf-8") == '{"a":2}'

    def test_cache_record_without_mtime_is_not_stale(self, tmp_path):
        """CLR-04-F: совпал размер, mtime отсутствует → запись НЕ устарела.

        ⚠️ `rec.get("mtime") or 0` сравнивал с нулём и всегда давал «устарела»:
        ручная правка кэша или частичная миграция схемы приводили к лишнему
        перезамеру. Защита обязана быть симметрична той, что есть для size.
        """
        clip = tmp_path / "c.MP4"
        clip.write_bytes(b"\x00" * 64)
        assert _plan.gamma_cache_stale({"size": 64}, clip) is False
        assert _plan.gamma_cache_stale({"size": 99}, clip) is True

    def test_seed_refuses_when_basename_repeats_across_scenes(self):
        """CLR-04-G: одно имя файла в двух сценах → отказ, а не чужая гамма.

        ⚠️ Посев переключал ключи по basename без проверки, тогда как slug_index
        в такой же ситуации отказывается работать. Счётчик Sony сбрасывается, и
        одно имя реально встречается дважды — гамма легла бы на клип другой
        сцены молча, то есть чужая проявка без единого сообщения.
        """
        keys = {"a": "01_Scene/RYA-FX3-1000.MP4", "b": "02_Other/RYA-FX3-1000.MP4"}
        with pytest.raises(_plan.SlugCollision):
            _plan.seed_gamma_cache_from_lut_plan({"clips": {}}, keys)

    def test_stop_tag_refuses_off_grid_step(self):
        """CLR-06-F: ступень вне сетки 0,1 — отказ, а не молчаливое схлопывание.

        ⚠️ `0,15` и `0,25` округлялись в один тег `expp02`, и два кадра лестницы
        записались бы в один файл. Через ladder_for такие ступени сейчас не
        рождаются, но класс ошибки — ровно тот, что стоил слою трёх багов:
        имя файла обязано нести всё, от чего зависит содержимое.
        """
        assert _plan.stop_tag(0.5) == "expp05"
        assert _plan.stop_tag(-1.0) == "expm10"
        with pytest.raises(ValueError):
            _plan.stop_tag(0.15)


class TestAuditFindingsFixed:
    """Сторожа на находки состязательного аудита 23.09. Каждая была воспроизведена."""

    def test_foreign_payload_is_refused_not_nulled(self, tmp_path):
        """CLR-15: payload старого формата отвергается, а не зануляет день.

        ⚠️ `doc.update(...)` клал пришедшее не глядя, и выгрузка архивного
        подборщика (`{type:'lut_feedback', choices, notes}` — ровно так он и
        писал) превращала exposure/develop/look/machine в None, поднимая при этом
        doc_version. День занулялся молча и выглядел сохранённым.
        """
        with pytest.raises(_plan.BadFeedback):
            _plan.check_feedback({"type": "lut_feedback", "choices": {}, "notes": {}}, "YTEVO03")
        with pytest.raises(_plan.BadFeedback):
            _plan.check_feedback({"type": "lut_board", "project": "YTCH13",
                                  "exposure": {"a": 0}}, "YTEVO03")
        with pytest.raises(_plan.BadFeedback):
            _plan.check_feedback({"type": "lut_board", "project": "YTEVO03"}, "YTEVO03")
        _plan.check_feedback({"type": "lut_board", "project": "YTEVO03",
                              "exposure": {"a": 0.5}}, "YTEVO03")

    def test_unreadable_profile_stops_instead_of_wiping(self, tmp_path, monkeypatch):
        """CLR-16: нечитаемый профиль канала — отказ, а не пересборка с нуля.

        ⚠️ Профиль лежит ПОД GIT: маркеры конфликта делают его нечитаемым.
        `load_json_safe` возвращал None, код шёл дальше с {} и сносил проявки,
        look и выученную цель СРАЗУ ПО ВСЕМ проектам канала. Восстановить неоткуда.
        """
        prof = tmp_path / "color_profile.json"
        prof.write_text("<<<<<<< HEAD\n{}\n=======\n{}\n>>>>>>> other", encoding="utf-8")
        monkeypatch.setattr(_plan, "profile_path", lambda p, c: prof)
        prj = tmp_path / "YTEVO99_X"
        (prj / "00_Setup" / "01_Ingest").mkdir(parents=True)
        with pytest.raises(_plan.ProfileUnreadable):
            _plan.save_choice(prj, "YTEVO99", {"type": "lut_board", "project": "YTEVO99",
                                               "look": "look__x"}, {})
        assert "<<<<<<<" in prof.read_text(encoding="utf-8"), "профиль всё-таки переписали"

    def test_gamma_cache_merges_and_keeps_old_records(self, tmp_path):
        """CLR-17: запись кэша СЛИВАЕТСЯ, старые ключи не пропадают.

        ⚠️ Словарь клался как есть: переименовали сцену — замер по её клипам
        исчез навсегда, копии тоже не делалось. Кэш существует затем, чтобы
        пережить недоступность карты; терять записи — отменять его смысл.
        """
        prj = tmp_path / "YTEVO99_X"
        (prj / "00_Setup" / "01_Ingest").mkdir(parents=True)
        _plan.save_gamma_cache(prj, "YTEVO99", {"01_A/x.MP4": {"gamma": "S-Log3"}})
        _plan.save_gamma_cache(prj, "YTEVO99", {"02_B/y.MP4": {"gamma": "D-Log2"}})
        got = _plan.load_gamma_cache(prj, "YTEVO99")
        assert set(got) == {"01_A/x.MP4", "02_B/y.MP4"}, "слияния не произошло"
        assert got["01_A/x.MP4"]["gamma"] == "S-Log3"

    def test_atomic_write_uses_unique_tmp_name(self, tmp_path):
        """CLR-18: имя временного файла уникально на процесс.

        ⚠️ Общий `.tmp` давал гонку: первый писатель делал replace, второй падал
        необработанным FileNotFoundError на уже переименованном файле. Битого
        JSON не получалось, но save_choice пишет ДВА файла подряд, и обрыв между
        ними оставлял половину сохранения.
        """
        import os
        p = tmp_path / "x.json"
        _plan.save_json_atomic(p, {"a": 1})
        assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
        assert not list(tmp_path.glob("*.tmp")), "временный файл остался рядом с данными"
        assert str(os.getpid()) in f"{p.suffix}.{os.getpid()}.tmp"
