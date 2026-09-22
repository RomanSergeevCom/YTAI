#!/usr/bin/env python3
"""Тесты обхода исходников и метаданных — color_media.py (CLR-01).

Модуль на одной стандартной библиотеке: он обязан отвечать, когда съёмная карта
размонтирована, а venv_vlm не поднят. Здесь же живут вещи, на которых слой цвета
уже обжигался, поэтому тесты идут по оплаченным ошибкам:

  CLR-01-A  normalize_gamma — один канон гаммы на весь слой; D-Log2 ≠ D-Log
  CLR-01-B  content_scenes — витрина и раскладка видят ОДИН набор сцен
  CLR-01-C  scene_clips — рекурсия до уровня камеры, мусор мимо, дубли = ошибка
  CLR-01-D  cam_of / frame_src — камера клипа и откуда декодировать кадр
  CLR-01-E  sony_gamma — гамма из сайдкара, а не из догадки по модели
  CLR-01-F  lut_arg — путь куба внутри filter-graph ffmpeg

Ни ffmpeg, ни сети, ни выхода за tmp_path: всё, что здесь трогается, — это
файлы фикстуры `fake_project` и то, что тест создал сам.
"""
from __future__ import annotations

import pytest

import color_media
import lut_select
import naming


# формат сайдкара взят с настоящей карты (RYA-FX3-0705M01.XML, T9-Black-RYA):
# Sony пишет гамму ОТДЕЛЬНЫМ элементом Item внутри CameraUnitMetadataSet
SONY_SIDECAR = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<NonRealTimeMeta>\n'
    '\t<AcquisitionRecord>\n'
    '\t\t<Group name="CameraUnitMetadataSet">\n'
    '\t\t\t<Item name="CaptureGammaEquation" value="s-log3-cine"/>\n'
    '\t\t\t<Item name="CaptureColorPrimaries" value="s-gamut3-cine"/>\n'
    '\t\t</Group>\n'
    '\t</AcquisitionRecord>\n'
    '</NonRealTimeMeta>\n'
)


def _names(paths):
    return [p.name for p in paths]


class TestNormalizeGamma:
    @pytest.mark.parametrize("raw,want", [
        ("s-log3-cine", "S-Log3"),     # как пишет сайдкар Sony
        ("slog3", "S-Log3"),           # как пишут имена кубов в коллекции
        ("S-Log3", "S-Log3"),          # как пишет манифест
        ("D-Log2", "D-Log2"),
        ("D-Log M", "D-Log M"),
        ("D-Log", "D-Log"),
        ("rec709", "Rec.709"),
        (None, None),
        ("", None),
        ("Foo", "Foo"),                # незнакомое отдаётся как есть — решать отбору
    ])
    def test_canon_of_one_gamma(self, raw, want):
        """CLR-01-A: камера, коллекция и манифест называют одну гамму по-разному —
        сводим к одному ключу.

        Без канона клип с живым сайдкаром ('s-log3-cine') не совпал бы ни с одной
        записью манифеста ('S-Log3'), и отбор честно вернул бы пусто на материале,
        для которого куб есть.
        """
        assert color_media.normalize_gamma(raw) == want

    def test_dlog2_does_not_collapse_into_dlog(self):
        """CLR-01-A: 'D-Log2' обязан остаться 'D-Log2' и НЕ схлопнуться в 'D-Log'.

        ⚠️ Порядок пар в таблице несущий: 'dlog2' и 'dlogm' стоят ДО 'dlog'.
        Переставь их — и подстрока 'dlog' поймает D-Log2 первой; клип Pocket 4P
        получит куб чужой гаммы, а в отчёте всё будет выглядеть здоровым.
        Этот тест — единственное, что держит DJI на своём кубе.
        """
        assert color_media.normalize_gamma("D-Log2") == "D-Log2"
        assert color_media.normalize_gamma("dlog2") == "D-Log2"
        assert color_media.normalize_gamma("D-Log M") != "D-Log"
        assert color_media.normalize_gamma("D-Log") == "D-Log"
        # и все три остаются различимы между собой
        assert len({color_media.normalize_gamma(g)
                    for g in ("D-Log", "D-Log2", "D-Log M")}) == 3

    def test_single_canon_for_the_whole_layer(self):
        """CLR-01-A: канон ОДИН физически — и у чтения метаданных, и у библиотеки.

        Две копии этой таблицы разъедутся, и вся история багов слоя именно про
        это. Поэтому проверяем тождество объекта, а не совпадение результатов.
        """
        assert color_media.normalize_gamma is naming.normalize_gamma
        assert lut_select.normalize_gamma is naming.normalize_gamma


class TestContentScenes:
    def test_returns_numbered_scenes(self, fake_project):
        """CLR-01-B: сцены съёмочного дня — пронумерованные папки 01_Source."""
        scenes = color_media.content_scenes(fake_project / "01_Source")
        assert _names(scenes) == ["01_Morning_Run", "02_Walk", "03_Office"]

    def test_service_scene_is_dropped(self, fake_project):
        """CLR-01-B: `00_Tests_And_Sync` — проверки, хлопушки и синхрон, не фильм.

        Правило живёт в одном месте именно потому, что витрина и раскладка обязаны
        видеть ОДИН И ТОТ ЖЕ набор клипов: разойдясь, они дали 163 против 172, и
        числа в отчёте перестали сходиться с тем, что реально покрашено.
        """
        scenes = color_media.content_scenes(fake_project / "01_Source")
        assert all(not p.name.startswith("00_") for p in scenes)
        assert "00_Tests_And_Sync" not in _names(scenes)

    def test_unnumbered_dirs_and_files_ignored(self, fake_project):
        """CLR-01-B: Transcription/, Sound/ и одиночные файлы сценами не считаются —
        иначе в план цвета поедут папки, где видео нет вовсе."""
        src = fake_project / "01_Source"
        (src / "Transcription").mkdir()
        (src / "notes.txt").write_text("не сцена", encoding="utf-8")
        assert _names(color_media.content_scenes(src)) == [
            "01_Morning_Run", "02_Walk", "03_Office"]


class TestSceneClips:
    def test_recurses_down_to_camera_folders(self, fake_project):
        """CLR-01-C: клипы лежат на уровень глубже — 01_Source/{сцена}/{CAM-*}/файл.

        ⚠️ До 21.09.2026 здесь был нерекурсивный glob. На YTEVO03 он находил 0
        клипов, писал ПУСТОЙ план и выходил с кодом 0 — тихий провал, который
        видно только в Premiere, уже на монтаже.
        """
        clips = color_media.scene_clips(fake_project / "01_Source" / "01_Morning_Run")
        assert _names(clips) == ["DJI_0008_D.MP4", "RYA-FX3-1212.MP4", "RYA-FX3-1213.MP4"]

    def test_non_video_and_dotfiles_dropped(self, fake_project):
        """CLR-01-C: .LRF (прокси DJI), .wav и dotfile'ы — не клипы.

        .LRF особенно коварен: это тот же кадр в мусорном качестве, и попади он в
        план, человек выбирал бы проявку по мыльной картинке.
        """
        clips = color_media.scene_clips(fake_project / "01_Source" / "01_Morning_Run")
        suffixes = {p.suffix.lower() for p in clips}
        assert suffixes == {".mp4"}
        assert not any(p.name.startswith(".") for p in clips)
        assert not any(p.suffix.upper() == ".LRF" for p in clips)
        assert not any(p.name.endswith("M01.XML") for p in clips)

    def test_sorted_by_name(self, fake_project):
        """CLR-01-C: порядок стабильный, по имени файла. План и витрина строятся
        разными проходами — плавающий порядок развёл бы их нумерацию."""
        clips = color_media.scene_clips(fake_project / "01_Source" / "01_Morning_Run")
        assert _names(clips) == sorted(_names(clips))

    def test_duplicate_basename_inside_scene_raises(self, tmp_path):
        """CLR-01-C: два файла с одним именем внутри сцены → DuplicateClip.

        ⚠️ Ключ плана — «сцена/файл.MP4», камеры в нём нет. Дубль сделал бы ключ
        неоднозначным: две записи молча затёрли бы друг друга, и один из клипов
        уехал бы в монтаж с чужой раскладкой. Поэтому это ошибка, а не
        предупреждение.
        """
        scene = tmp_path / "01_Morning_Run"
        for cam in ("CAM-A_FX3", "CAM-B_ZVE1"):
            (scene / cam).mkdir(parents=True)
            (scene / cam / "C0001.MP4").write_bytes(b"\x00")
        with pytest.raises(color_media.DuplicateClip) as e:
            color_media.scene_clips(scene)
        assert "01_Morning_Run" in str(e.value)
        assert "CAM-A_FX3" in str(e.value) and "CAM-B_ZVE1" in str(e.value)

    def test_same_name_in_different_scenes_is_fine(self, tmp_path):
        """CLR-01-C: одинаковые имена в РАЗНЫХ сценах законны — камеры нумеруют
        файлы с нуля каждый день, и ключ плана их уже различает сценой."""
        for scene in ("01_Morning_Run", "02_Walk"):
            d = tmp_path / scene / "CAM-A_FX3"
            d.mkdir(parents=True)
            (d / "C0001.MP4").write_bytes(b"\x00")
        for scene in ("01_Morning_Run", "02_Walk"):
            assert _names(color_media.scene_clips(tmp_path / scene)) == ["C0001.MP4"]


class TestCamOf:
    def test_three_levels_gives_camera_folder(self, fake_project):
        """CLR-01-D: камера клипа = папка между сценой и файлом.

        Имя камеры едет в витрину и в раскладку: по нему человек понимает, почему
        два кадра одной сцены выглядят по-разному.
        """
        src = fake_project / "01_Source"
        clip = src / "01_Morning_Run" / "CAM-A_FX3" / "RYA-FX3-1212.MP4"
        assert color_media.cam_of(clip, src) == "CAM-A_FX3"
        assert color_media.cam_of(
            src / "01_Morning_Run" / "CAM-C_Pocket" / "DJI_0008_D.MP4", src) == "CAM-C_Pocket"

    def test_clip_directly_in_scene_gives_empty_string(self, tmp_path):
        """CLR-01-D: раскладка YTCH13 — клип лежит прямо в сцене, уровня камеры нет.

        Возвращается пустая строка, а не падение: обе раскладки живые, и слой
        обязан работать на каждой.
        """
        src = tmp_path / "01_Source"
        (src / "01_Morning_Run").mkdir(parents=True)
        clip = src / "01_Morning_Run" / "C0001.MP4"
        clip.write_bytes(b"\x00")
        assert color_media.cam_of(clip, src) == ""


class TestFrameSrc:
    def test_proxy_mirror_hit(self, fake_project, tmp_path):
        """CLR-01-D: кадр берётся из зеркала прокси, если он там есть.

        Оригиналы YTEVO03 — симлинки на съёмную карту: кадр с неё идёт 0.72–0.84 с
        против 0.28–0.34 с с прокси, а карту дёргать нельзя, на ней держится
        проект. LUT в прокси не вшит, образ лог-плоский — картинка та же.
        """
        src = fake_project / "01_Source"
        clip = src / "01_Morning_Run" / "CAM-A_FX3" / "RYA-FX3-1212.MP4"
        mirror = tmp_path / "01_Source_Proxy"
        twin = mirror / clip.relative_to(src)
        twin.parent.mkdir(parents=True)
        twin.write_bytes(b"\x00")
        assert color_media.frame_src(clip, src, mirror) == (twin, "proxy")

    def test_mirror_miss_falls_back_to_original(self, fake_project, tmp_path):
        """CLR-01-D: прокси на этот клип не собрали → берём оригинал и ГОВОРИМ,
        что это фолбэк.

        Признак уходит в витрину: «кадр с оригинала» объясняет, почему проход
        вдруг идёт втрое дольше, — иначе это выглядит как зависание.
        """
        src = fake_project / "01_Source"
        clip = src / "02_Walk" / "CAM-B_ZVE1" / "RYA-ZVE1-1890.MP4"
        mirror = tmp_path / "01_Source_Proxy"
        mirror.mkdir()
        assert color_media.frame_src(clip, src, mirror) == (clip, "fallback")

    def test_no_mirror_means_original(self, fake_project):
        """CLR-01-D: зеркала нет вовсе → оригинал с признаком 'orig', не 'fallback'.

        Разные слова для разных ситуаций: «прокси не просили» и «прокси просили,
        но не нашли» — в отчёте это два разных разговора.
        """
        src = fake_project / "01_Source"
        clip = src / "03_Office" / "CAM-A_FX3" / "RYA-FX3-1300.MP4"
        assert color_media.frame_src(clip, src, None) == (clip, "orig")


class TestSonyGamma:
    def test_reads_gamma_from_camera_sidecar(self, tmp_path):
        """CLR-01-E: гамма берётся из сайдкара {stem}M01.XML, как его пишет камера.

        Формат сверен с настоящей карты (RYA-FX3-0705M01.XML): Sony кладёт гамму
        отдельным `<Item name="CaptureGammaEquation" value="s-log3-cine"/>`.
        Читать надо именно сайдкар, а не угадывать по модели тушки: MEDIAPRO.XML
        про камеру врёт, а догадка по имени камеры — ровно та ошибка, что
        покрасила 61 клип DJI чужой математикой.
        """
        clip = tmp_path / "RYA-FX3-1212.MP4"
        clip.write_bytes(b"\x00")
        (tmp_path / "RYA-FX3-1212M01.XML").write_text(SONY_SIDECAR, encoding="utf-8")
        assert color_media.sony_gamma(clip) == "s-log3-cine"
        # сырое значение камеры само по себе с манифестом не совпадает —
        # канон обязан привести его к ключу библиотеки
        assert color_media.normalize_gamma(color_media.sony_gamma(clip)) == "S-Log3"

    def test_sidecar_belongs_to_its_own_clip(self, tmp_path):
        """CLR-01-E: сайдкар ищется по ИМЕНИ клипа, а не «любой XML рядом».

        В папке камеры лежат сайдкары всех клипов; взяв соседний, мы приписали бы
        клипу чужую гамму — и это не было бы видно нигде, кроме цвета в мастере.
        """
        (tmp_path / "RYA-FX3-1212M01.XML").write_text(SONY_SIDECAR, encoding="utf-8")
        other = tmp_path / "RYA-FX3-1213.MP4"
        other.write_bytes(b"\x00")
        assert color_media.sony_gamma(other) is None

    def test_missing_sidecar_returns_none(self, fake_project):
        """CLR-01-E: сайдкара нет (DJI, GoPro, перекодированный файл) → None.

        None здесь — законный ответ «не знаю»; дальше гамму спросят у тега
        контейнера. Исключение оборвало бы обход всей сцены.
        """
        clip = (fake_project / "01_Source" / "01_Morning_Run"
                / "CAM-C_Pocket" / "DJI_0008_D.MP4")
        assert color_media.sony_gamma(clip) is None

    def test_garbage_sidecar_returns_none_not_exception(self, tmp_path):
        """CLR-01-E: битый или не-XML сайдкар → None, а не падение.

        Файл на карте может оборваться на записи. Проход по 449 клипам не имеет
        права умереть на одном битом сайдкаре — он обязан дойти до конца и
        показать человеку, где именно гамма не определилась.
        """
        clip = tmp_path / "RYA-FX3-1212.MP4"
        clip.write_bytes(b"\x00")
        side = tmp_path / "RYA-FX3-1212M01.XML"
        side.write_bytes(b"\xff\xfe\x00 not an xml at all <<<")
        assert color_media.sony_gamma(clip) is None
        side.write_text("<NonRealTimeMeta><VideoLayout/></NonRealTimeMeta>", encoding="utf-8")
        assert color_media.sony_gamma(clip) is None

    def test_fixture_sidecar_should_be_camera_shaped(self, fake_project):
        """CLR-01-E: сайдкар из fake_project обязан читаться так же, как настоящий.

        ⚠️ Тест появился как маркер найденного дефекта: первая версия фикстуры
        изображала сайдкар Sony атрибутом `CaptureGammaEquation="…"`, а камера
        пишет `<Item name=… value=…/>`. Регулярка такую форму не поднимает, и
        любой тест «по фикстуре» проверял бы не камеру, а выдумку. Фикстуру
        починили 22.09; тест остаётся сторожем на то, что её форма не уедет снова.
        """
        clip = (fake_project / "01_Source" / "01_Morning_Run"
                / "CAM-A_FX3" / "RYA-FX3-1212.MP4")
        assert color_media.sony_gamma(clip) == "s-log3-cine"


class TestLutArg:
    def test_escapes_colon_and_apostrophe(self):
        """CLR-01-F: путь куба едет внутрь filter-graph как lut3d=file='...'.

        00_LUT живёт на внешнем томе, где имена бывают любыми. Двоеточие в
        filter-graph разделяет опции, апостроф закрывает кавычку — незаэкранированный
        путь роняет ffmpeg ошибкой парсинга на КАЖДОМ кадре, то есть проход
        выглядит как «ничего не рендерится» без единого внятного сообщения.
        """
        raw = "/Volumes/T7 Blue/00_LUT/Roman's picks/look:travel.cube"
        esc = color_media.lut_arg(raw)
        assert "\\:" in esc and "\\'" in esc
        # ни одного НЕэкранированного спецсимвола не осталось
        assert ":" not in esc.replace("\\:", "")
        assert "'" not in esc.replace("\\'", "")
        # и ни одного ПЕРЕэкранированного: '\\:' — это «слэш, потом живое
        # двоеточие», ffmpeg рвёт filter-graph ровно по нему
        assert "\\\\:" not in esc and "\\\\'" not in esc

    def test_space_survives_inside_quotes(self):
        """CLR-01-F: пробел не экранируется и не выбрасывается — путь с пробелом
        обязан дойти до ffmpeg целым.

        Значение подставляется в одинарные кавычки (file='...'), внутри них пробел
        безопасен; вот потеря пробела переименовала бы файл в несуществующий.
        """
        esc = color_media.lut_arg("/Volumes/T7 Blue/00_LUT/look travel.cube")
        assert "T7 Blue" in esc and "look travel.cube" in esc

    def test_backslash_doubled_before_anything_else(self):
        """CLR-01-F: обратный слэш удваивается ПЕРВЫМ, до двоеточия и апострофа.

        Порядок замен несущий. Удвой слэши последними — и слэши, добавленные при
        экранировании двоеточия, удвоятся сами: '\\:' превратится в '\\\\:', то
        есть в «экранированный слэш, а за ним живое двоеточие», и ffmpeg снова
        рвёт filter-graph по этому двоеточию. Поэтому образец тут с обоими
        символами сразу — путь с одним только слэшем такую перестановку не ловит.
        """
        assert color_media.lut_arg("a\\b:c.cube") == "a\\\\b\\:c.cube"

    def test_accepts_path_objects(self, tmp_path):
        """CLR-01-F: на вход приходит Path (так его отдаёт store_path), а на выход
        нужна строка для командной строки ffmpeg."""
        out = color_media.lut_arg(tmp_path / "look travel.cube")
        assert isinstance(out, str)
        assert out.endswith("look travel.cube")
