"""Тесты эмиттера раскладки цвета — scripts/15_color/1503_color_apply/color_apply.py.

Что стережём:
  CLR-09  форма раскладки: у каждого клипа дня есть запись, ключ «сцена/клип.MP4»,
          значение — ОБЪЕКТ из трёх ступеней (проявка, экспозиция, покраска);
  CLR-10  сухой прогон не пишет ничего — ни план, ни кэш гамм;
  CLR-11  отказ громче тишины: непустой refused → файла нет и код выхода ≠ 0;
          --allow-refused пишет, но отказной клип в план НЕ попадает;
  CLR-11b Rec.709 — это skipped, а не отказ, и записи он не мешает;
  CLR-11c куба нет в store (или в манифесте) → отказ: план не указывает в пустоту;
  CLR-12  контракт панели: index.js:2504-2507 пере-ключует план по basename —
          повторяем это в Python и проверяем, что ни один ключ не теряется.
плюс арифметика экспозиции (×2,4 без зажима), имена установки кубов и флаг
честности exposure_verified_against_premiere.

⚠️ Мир строится целиком в tmp_path: свой манифест и свой store кубов, свой профиль
канала, свой файл выбора. Настоящую библиотеку и настоящий ~/YTAI/YTs тесты не
трогают. ffprobe подменён заглушкой — ни одного внешнего процесса.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

import color_apply
import color_media
import color_plan
import lut_select

CODE = "YTEVO99"

# Кубы из фикстуры small_manifest, которыми пользуется профиль канала.
SLOG3_DEV = "sony__slog3_sgamut3cine__rec709__neutral__legacy"
DLOG2_DEV = "dji_pocket4p__dlog2__rec709__minus"
LOOK = "look__travel"

# Ключи плана для базового мира. ⚠️ Захардкожены НАМЕРЕННО: формат ключа —
# внешний контракт с панелью UXP, вычислять его теми же функциями, что и код под
# тестом, значит проверять, что код равен сам себе.
EXPECTED_KEYS = {
    "01_Morning_Run/RYA-FX3-1212.MP4",
    "01_Morning_Run/RYA-FX3-1213.MP4",
    "01_Morning_Run/DJI_0008_D.MP4",
    "02_Walk/RYA-ZVE1-1890.MP4",
    "03_Office/RYA-FX3-1300.MP4",
}


# ─────────────────────────────────────────────────────────── инструменты ──

class _FakeProc:
    """Ответ вместо ffprobe: у настоящего кода берётся только .stdout."""

    def __init__(self, stdout=""):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_sidecar(clip: Path, gamma: str):
    """Сайдкар Sony рядом с клипом — в том виде, в каком его пишет камера.

    ⚠️ Форма несущая: color_media.sony_gamma ищет `CaptureGammaEquation" value="…"`,
    то есть АТРИБУТ name у элемента Item, а не одноимённый атрибут у VideoFrame.
    Сайдкар второго вида парсер молча не узнаёт и отдаёт None (см. отчёт: ровно
    так устроен сайдкар в общей фикстуре fake_project).
    """
    clip.with_name(clip.stem + "M01.XML").write_text(
        '<?xml version="1.0"?><NonRealTimeMeta><AcquisitionRecord>'
        '<Group name="CameraUnitMetadataSet">'
        f'<Item name="CaptureGammaEquation" value="{gamma}"/>'
        '</Group></AcquisitionRecord></NonRealTimeMeta>', encoding="utf-8")


def _rekey_like_panel(plan: dict):
    """Ровно то, что делает панель в index.js:2504-2507.

        var planByClip = {};
        Object.keys(plan).forEach(function (k) {
          planByClip[k.split('/').pop()] = plan[k];
        });

    Возвращает (карта basename → значение, список столкнувшихся basename).
    JS молча затирает предыдущее значение, поэтому столкновения считаем сами.
    """
    by_base: dict[str, object] = {}
    collisions: list[str] = []
    for key in plan:                       # JS: Object.keys(plan).forEach
        base = key.split("/")[-1]          # JS: k.split('/').pop()
        if base in by_base:
            collisions.append(base)
        by_base[base] = plan[key]
    return by_base, collisions


class World:
    """Мир одного прогона: проект, библиотека кубов, профиль канала, выбор Романа.

    Всё внутри tmp_path. Тест может дописать клип (`add_clip`), передвинуть
    экспозицию (`set_exposure`), сломать библиотеку — и позвать `build()` или
    `run()` (то есть main() с аргументами командной строки).
    """

    def __init__(self, project, store, manifest_path, profile_path, monkeypatch):
        self.project = project
        self.store = store
        self.manifest_path = manifest_path
        self.profile_path = profile_path
        self._mp = monkeypatch
        self.ingest = project / "00_Setup" / "01_Ingest"
        self.tags: dict[str, str] = {}        # basename → что «ffprobe» скажет про тег DJI
        self.exposure: dict[str, float] = {}  # слаг → стопы витрины
        self.corrected: dict[str, float] = {}

    # ── пути результатов ──
    @property
    def plan_path(self) -> Path:
        return self.ingest / f"{CODE}_color_plan.json"

    @property
    def cache_path(self) -> Path:
        return self.ingest / f"{CODE}_gamma_cache.json"

    @property
    def choice_path(self) -> Path:
        return self.ingest / f"{CODE}_color_choice.json"

    # ── наполнение мира ──
    def add_clip(self, scene, cam, name, sidecar_gamma=None, dji_tag=None, stops=0.0):
        """Ещё один клип съёмочного дня + его экспозиция в выборе."""
        d = self.project / "01_Source" / scene / cam
        d.mkdir(parents=True, exist_ok=True)
        clip = d / name
        clip.write_bytes(b"\x00" * 64)
        if sidecar_gamma:
            _write_sidecar(clip, sidecar_gamma)
        if dji_tag:
            self.tags[name] = dji_tag
        if stops is not None:
            self.exposure[color_plan.clip_slug(scene, clip.stem)] = stops
        self.save_choice()
        return clip

    def set_exposure(self, scene, clip_name, stops):
        self.exposure[color_plan.clip_slug(scene, Path(clip_name).stem)] = stops
        self.save_choice()

    def set_look(self, look_id):
        prof = json.loads(self.profile_path.read_text(encoding="utf-8"))
        prof["look"] = {"id": look_id, "decided_by": "roman"}
        self.profile_path.write_text(json.dumps(prof, ensure_ascii=False),
                                     encoding="utf-8")

    def drop_cube(self, lut_id):
        """Убрать файл куба из store, оставив запись в манифесте."""
        man = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        entry = next(l for l in man["luts"] if l["id"] == lut_id)
        (self.store / entry["file"]).unlink()

    def save_choice(self):
        color_plan.save_json_atomic(self.choice_path, {
            "schema": "color-choice-v1",
            "stage": {"done": True, "decided_by": "roman"},
            "project": CODE,
            "exposure": dict(self.exposure),
            "corrected": dict(self.corrected),
            "saved": "2026-09-22T12:00:00+0400",
            "doc_version": 3,
        })

    # ── запуск кода под тестом ──
    def build(self) -> dict:
        return color_apply.build(self.project, CODE)

    def run(self, *flags):
        """main() с подменённым sys.argv — так же, как его зовёт Роман из терминала."""
        self._mp.setattr(sys, "argv",
                         ["color_apply.py", "--project", str(self.project), *flags])
        color_apply.main()


@pytest.fixture
def world(tmp_path, fake_project, small_manifest, ytevo_profile, monkeypatch):
    """Здоровый мир YTEVO99: 5 клипов в трёх сценах, две гаммы, все кубы на месте.

    ⚠️ Гамму DJI настоящий код читает тегом контейнера через ffprobe. Внешних
    процессов в тестах нет, поэтому `color_media.run` подменён заглушкой, которая
    отвечает по имени файла. Заглушка ПАДАЕТ на любой команде кроме ffprobe —
    это и есть страж «никакого ffmpeg в тестах».
    """
    project = fake_project

    # 1. Библиотека: манифест + store с настоящими файлами (sha256 считается по ним,
    #    иначе verify_cube честно скажет «файл подменён»).
    store = tmp_path / "lut_store"
    luts = json.loads(json.dumps(small_manifest["luts"]))   # копия, фикстуру не портим
    for entry in luts:
        f = store / entry["file"]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"# YTAI test cube {entry['id']}\nLUT_3D_SIZE 2\n", encoding="utf-8")
        entry["sha256"] = _sha256(f)
        entry["bytes"] = f.stat().st_size
    manifest_path = tmp_path / "manifest_test.json"
    manifest_path.write_text(json.dumps({"luts": luts}, ensure_ascii=False),
                             encoding="utf-8")
    monkeypatch.setattr(lut_select, "MANIFEST", manifest_path)
    monkeypatch.setattr(lut_select, "STORE", store)

    # 2. Профиль канала: берём настоящую ДНК YTEVO, но покраску переводим на куб,
    #    который есть в манифесте фикстуры (в настоящей ДНК это look__newstar).
    profile = json.loads(json.dumps(ytevo_profile))
    profile["look"]["id"] = LOOK
    profile_path = tmp_path / "YTs" / "YTEVO" / "color_profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(color_plan, "profile_path", lambda project, code: profile_path)

    w = World(project, store, manifest_path, profile_path, monkeypatch)

    # 3. ffprobe → заглушка.
    def _fake_run(cmd, timeout=None):
        assert cmd[0] == "ffprobe", f"тест не имеет права запускать {cmd[0]}"
        return _FakeProc(w.tags.get(Path(str(cmd[-1])).name, ""))

    monkeypatch.setattr(color_media, "run", _fake_run)

    # 4. Клипы дня. ⚠️ Сайдкар у RYA-FX3-1212 общая фикстура кладёт в форме,
    #    которую sony_gamma не разбирает, — перезаписываем его настоящей.
    src = project / "01_Source"
    for scene, cam, name in (("01_Morning_Run", "CAM-A_FX3", "RYA-FX3-1212.MP4"),
                             ("01_Morning_Run", "CAM-A_FX3", "RYA-FX3-1213.MP4"),
                             ("02_Walk", "CAM-B_ZVE1", "RYA-ZVE1-1890.MP4"),
                             ("03_Office", "CAM-A_FX3", "RYA-FX3-1300.MP4")):
        _write_sidecar(src / scene / cam / name, "s-log3-cine")
    w.tags["DJI_0008_D.MP4"] = "D-Log2"

    w.exposure = {
        "01_Morning_Run_RYA_FX3_1212": 0.0,
        "01_Morning_Run_RYA_FX3_1213": 0.5,
        "01_Morning_Run_DJI_0008_D": -1.0,
        "02_Walk_RYA_ZVE1_1890": 1.5,
        "03_Office_RYA_FX3_1300": -0.5,
    }
    w.corrected = {"02_Walk_RYA_ZVE1_1890": 1.5}
    w.save_choice()
    return w


# ────────────────────────────────── CLR-09: форма здоровой раскладки ──

class TestPlanShape:
    def test_every_clip_has_an_entry(self, world):
        """CLR-09: у каждого клипа дня есть запись, и лишних записей нет.

        Клип, потерянный раскладкой, — это клип без слоя на таймлайне: в Premiere
        он выглядит как обычный, просто некрашеный, и всплывает уже на сдаче.
        Служебная 00_Tests_And_Sync в план не идёт — отбор сцен общий с витриной,
        иначе два инструмента дадут монтажёру разные числа.
        """
        doc = world.build()
        assert set(doc["plan"]) == EXPECTED_KEYS
        assert doc["stats"]["clips"] == len(EXPECTED_KEYS)
        assert doc["stats"]["planned"] == len(EXPECTED_KEYS)
        assert not doc["refused"] and not doc["skipped"]
        assert not any(k.startswith("00_Tests_And_Sync/") for k in doc["plan"])

    def test_key_is_scene_slash_clip_with_extension(self, world):
        """CLR-09: ключ — «сцена/клип.MP4», ровно один слэш и полное имя файла.

        Формат читает панель UXP. Потеря расширения или появление уровня камеры в
        ключе («01_Morning_Run/CAM-A_FX3/…») ломает сопоставление с таймлайном
        целиком — панель не найдёт ни одного клипа.
        """
        doc = world.build()
        for key in doc["plan"]:
            scene, slash, name = key.partition("/")
            assert slash == "/" and "/" not in name, key
            assert name.upper().endswith(".MP4"), key
            assert (world.project / "01_Source" / scene).is_dir(), key

    def test_value_is_an_object_of_three_steps(self, world):
        """CLR-09: значение — объект {develop, exposure, look}, а НЕ строка.

        ⚠️ Объект и есть причина, по которой это отдельный файл, а не старый
        lut_plan.json: там значением было имя клипа-донора, и панель кладёт его
        прямо в имя слоя. Положить объект в старый формат — получить «[object
        Object]» в имени Look на таймлайне.
        """
        doc = world.build()
        for key, val in doc["plan"].items():
            assert isinstance(val, dict), f"{key}: значение стало {type(val).__name__}"
            assert set(val) == {"develop", "exposure", "look"}, key
            assert isinstance(val["develop"], str) and val["develop"]
            assert isinstance(val["exposure"], (int, float))
            assert isinstance(val["look"], str) and val["look"]

    def test_develop_follows_gamma_and_look_is_one_per_channel(self, world):
        """CLR-09: проявка выводится из гаммы клипа, покраска одна на канал.

        Проявка — технический шаг: S-Log3 обязан получить сониевский куб, D-Log2 —
        дижейный. ⚠️ Именно снисходительность «гамма не совпала, поедем дальше»
        покрасила 61 клип DJI из 163 чужой математикой.
        """
        doc = world.build()
        by_gamma = {k: v["develop"] for k, v in doc["plan"].items()}
        assert by_gamma["01_Morning_Run/DJI_0008_D.MP4"] == DLOG2_DEV
        assert by_gamma["01_Morning_Run/RYA-FX3-1212.MP4"] == SLOG3_DEV
        assert by_gamma["02_Walk/RYA-ZVE1-1890.MP4"] == SLOG3_DEV
        assert {v["look"] for v in doc["plan"].values()} == {LOOK}
        assert doc["develops"][SLOG3_DEV]["clips"] == 4
        assert doc["develops"][DLOG2_DEV]["clips"] == 1


# ──────────────────────────────────── CLR-10: сухой прогон молчалив ──

class TestDryRun:
    def test_dry_run_writes_nothing_at_all(self, world):
        """CLR-10: без --apply на диске не появляется НИ ОДНОГО файла.

        Сухой прогон зовут, чтобы посмотреть на числа до решения. Если он попутно
        перезаписывает план, «посмотреть» становится «применить», а утверждённый
        Романом файл уезжает молча.
        """
        before = sorted(p.name for p in world.ingest.iterdir())
        world.run()                                  # без --apply
        after = sorted(p.name for p in world.ingest.iterdir())
        assert after == before
        assert not world.plan_path.exists()
        assert not world.cache_path.exists(), "кэш гамм тоже не должен появляться"

    def test_apply_does_write_plan_and_gamma_cache(self, world):
        """CLR-10 (обратная сторона): с --apply файлы появляются.

        Без этой проверки предыдущий тест был бы зелёным и на сломанной записи —
        «ничего не записано» выполняется идеально, если не пишешь никогда.
        """
        world.run("--apply")
        assert world.plan_path.exists()
        assert world.cache_path.exists()
        doc = json.loads(world.plan_path.read_text(encoding="utf-8"))
        assert doc["schema"] == "color-plan-v1"
        assert set(doc["plan"]) == EXPECTED_KEYS
        cache = json.loads(world.cache_path.read_text(encoding="utf-8"))
        assert set(cache["clips"]) == EXPECTED_KEYS


# ─────────────────────────────── CLR-11: отказ громче тишины ──

class TestRefusal:
    def test_unknown_gamma_refuses_and_leaves_no_file(self, world):
        """CLR-11: клип без гаммы → refused, файла нет, код выхода ≠ 0.

        ⚠️ Клип без слоя в Premiere выглядит как обычный клип. Молча пропустить
        его хуже, чем не собрать план вовсе: неокрашенный кадр в середине фильма
        находится на сдаче, а не на прогоне.
        """
        world.add_clip("04_Evening", "CAM-D_New", "RYA-NEW-0001.MP4", stops=0.0)
        doc = world.build()
        assert "04_Evening/RYA-NEW-0001.MP4" in doc["refused"]

        with pytest.raises(SystemExit) as e:
            world.run("--apply")
        assert e.value.code != 0
        assert not world.plan_path.exists()

    def test_allow_refused_writes_but_drops_the_clip(self, world):
        """CLR-11: с --allow-refused файл пишется, отказной клип в plan НЕ попадает.

        Осознанный обход не должен превращаться в тихое «как-нибудь покрасим»:
        клип обязан остаться в refused и не получить ни проявки, ни экспозиции.
        """
        world.add_clip("04_Evening", "CAM-D_New", "RYA-NEW-0001.MP4", stops=0.0)
        world.run("--apply", "--allow-refused")

        doc = json.loads(world.plan_path.read_text(encoding="utf-8"))
        assert "04_Evening/RYA-NEW-0001.MP4" in doc["refused"]
        assert "04_Evening/RYA-NEW-0001.MP4" not in doc["plan"]
        assert set(doc["plan"]) == EXPECTED_KEYS, "здоровые клипы обязаны уцелеть"

    def test_rec709_is_skipped_not_refused(self, world):
        """CLR-11b: Rec.709 → skipped, и запись файла не блокирует.

        Клип не в логе — проявлять нечего, это законный случай, а не поломка.
        На YTEVO03 такой ровно один: 162 из 163 — правильное число, не потеря.
        Если бы он падал в refused, каждый прогон дня требовал бы --allow-refused,
        и флаг обхода стал бы привычкой.
        """
        world.add_clip("05_Street", "CAM-E_A7", "RYA-A7-0002.MP4",
                       sidecar_gamma="rec709", stops=0.5)
        doc = world.build()
        key = "05_Street/RYA-A7-0002.MP4"
        assert key in doc["skipped"]
        assert key not in doc["refused"]
        assert key not in doc["plan"]
        assert not doc["refused"], "Rec.709 не имеет права порождать отказ"

        world.run("--apply")                       # без --allow-refused
        assert world.plan_path.exists()

    def test_clip_absent_from_the_choice_refuses(self, world):
        """CLR-11: клипа нет в выборе Романа → отказ, а не экспозиция 0,0.

        Клип, снятый после того, как витрина собрана, человек не видел и не
        утверждал. Подставить ему ноль — выдать за решение то, чего решением не
        было: на таймлайне он ляжет ровно так же уверенно, как утверждённые.
        Отказ называет слаг, по которому искали, — по нему видно, что чинить.
        """
        world.exposure.pop("02_Walk_RYA_ZVE1_1890")
        world.save_choice()
        doc = world.build()
        key = "02_Walk/RYA-ZVE1-1890.MP4"
        assert key in doc["refused"]
        assert "02_Walk_RYA_ZVE1_1890" in doc["refused"][key]
        assert key not in doc["plan"]

        with pytest.raises(SystemExit) as e:
            world.run("--apply")
        assert e.value.code != 0
        assert not world.plan_path.exists()

    def test_missing_cube_in_store_refuses(self, world):
        """CLR-11c: куба нет на диске → отказ, план не указывает в пустоту.

        План адресует кубы по store_path и ставит их именем файла в Lumetri.
        Запись о кубе, которого нет, всплывёт в Premiere пустым Input LUT —
        картинкой, похожей на «просто плоскую», а не на ошибку.
        """
        world.drop_cube(SLOG3_DEV)
        doc = world.build()
        assert f"__lut__{SLOG3_DEV}" in doc["refused"]

        with pytest.raises(SystemExit) as e:
            world.run("--apply")
        assert e.value.code != 0
        assert not world.plan_path.exists()

    def test_look_missing_from_manifest_refuses(self, world):
        """CLR-11c: покраски нет в манифесте библиотеки → отказ, а не «без look».

        Молчаливое «покраски не нашлось — поедем без неё» отдаёт монтажёру день
        без ДНК канала, и заметно это станет только рядом с прошлым выпуском.
        """
        world.set_look("look__nikogda_ne_bylo")
        doc = world.build()
        assert "__lut__look__nikogda_ne_bylo" in doc["refused"]
        assert doc["look"] is None

        with pytest.raises(SystemExit) as e:
            world.run("--apply")
        assert e.value.code != 0
        assert not world.plan_path.exists()


# ───────────────────────── CLR-12: контракт с панелью UXP по basename ──

class TestPanelContract:
    def test_plan_survives_the_panels_rekeying(self, world):
        """CLR-12: повторяем index.js:2504-2507 — план пере-ключуется по basename.

        Панель берёт `k.split('/').pop()` и кладёт значение в плоскую карту, где
        клип с таймлайна ищется по имени файла. Два одинаковых basename в разных
        сценах — и один клип молча затирает другой: он получит проявку и
        экспозицию соседа, а JS об этом ничего не скажет.
        Это единственный автоматический страж того места.
        """
        doc = world.build()
        by_base, collisions = _rekey_like_panel(doc["plan"])
        assert collisions == []
        assert len(by_base) == len(doc["plan"])
        for key, val in doc["plan"].items():
            assert by_base[key.split("/")[-1]] is val

    def test_rekeying_helper_actually_detects_a_collision(self):
        """CLR-12: сам страж работает — на двух одинаковых basename он кричит.

        Без этой проверки предыдущий тест зелёный по построению: «столкновений
        нет» верно и у детектора, который не умеет их находить.
        """
        by_base, collisions = _rekey_like_panel({
            "01_Morning_Run/RYA-FX3-1212.MP4": {"develop": "a"},
            "03_Office/RYA-FX3-1212.MP4": {"develop": "b"},
        })
        assert collisions == ["RYA-FX3-1212.MP4"]
        assert len(by_base) == 1


# ───────────────────────────────────── экспозиция: ×2,4 и без зажима ──

class TestExposure:
    def test_every_value_is_preview_stops_times_2_4(self, world):
        """Экспозиция в плане = стопы витрины × 2,4 — у КАЖДОГО клипа.

        ⚠️ Витрина считала экспозицию фильтром ffmpeg поверх гамма-кодированного
        Rec.709 (умножение кода на 2^X), Lumetri линеаризует ДО экспозиции.
        Кадры, которые Роман смотрел и утверждал, верны как изображение, но число
        в Premiere другое. Положить сюда стопы витрины как есть — отдать
        монтажёру день, который на глаз «почти такой же», и это худший вид ошибки.
        """
        doc = world.build()
        assert doc["exposure_units"] == "stops_lumetri"
        assert doc["exposure_multiplier"] == 2.4
        for key, val in doc["plan"].items():
            slug = doc["clips"][key]["slug"]
            preview = world.exposure[slug]
            assert val["exposure"] == pytest.approx(preview * 2.4, abs=5e-5), key
            assert doc["clips"][key]["exposure_preview"] == preview

    def test_out_of_range_clip_is_refused_not_clamped(self, world):
        """Клип, у которого |2,4·X| > 7, уходит в refused, а НЕ зажимается в ±7.

        Ползунок Exposure в Basic Correction кончается на ±7. Зажать молча — выдать
        картинку, которая не совпадёт с утверждённым кадром, и никто об этом не
        узнает: в плане будет честное число, просто не то, что видел человек.
        """
        world.set_exposure("03_Office", "RYA-FX3-1300.MP4", 3.0)   # ×2,4 = 7,2
        doc = world.build()
        key = "03_Office/RYA-FX3-1300.MP4"
        assert key in doc["refused"]
        assert key not in doc["plan"]
        assert "7" in doc["refused"][key], "причина должна называть предел ползунка"
        assert all(abs(v["exposure"]) <= 7.0 for v in doc["plan"].values())
        assert all(abs(v["exposure"]) != 7.0 for v in doc["plan"].values()), \
            "ровно ±7 означало бы зажим вместо отказа"

    def test_boundary_value_still_planned(self, world):
        """Клип у самой границы (2,9 × 2,4 = 6,96) остаётся в плане.

        Отказ обязан быть точным: если граница сдвинется внутрь, честные клипы
        начнут требовать --allow-refused, и флаг обхода станет привычкой.
        """
        world.set_exposure("03_Office", "RYA-FX3-1300.MP4", 2.9)
        doc = world.build()
        assert not doc["refused"]
        assert doc["plan"]["03_Office/RYA-FX3-1300.MP4"]["exposure"] == \
            pytest.approx(6.96, abs=5e-5)


# ─────────────────────────────── имена установки кубов и честность ──

class TestInstallNames:
    def test_install_name_is_prefixed_and_cube(self, world):
        """install_name всегда «YTAI_*.cube» — и у проявок, и у покраски.

        ⚠️ Lumetri ссылается на ИМЯ ФАЙЛА в общей папке Adobe. `look__travel.cube`,
        положенный туда без префикса, — столкновение с чужим кубом, ждущее своего
        часа: день покрасится чем-то похожим по имени, и следов не останется.
        """
        doc = world.build()
        files = doc["install"]["files"]
        assert len(files) == 3, "две проявки и покраска"
        for f in files:
            assert f["install_name"].startswith("YTAI_"), f
            assert f["install_name"].endswith(".cube"), f
            assert f["sha256"] and f["dir"] in ("input_dir", "creative_dir")
        for block in list(doc["develops"].values()) + [doc["look"]]:
            assert block["install_name"].startswith("YTAI_")
            assert block["install_name"].endswith(".cube")
            assert block["slot"] in ("basic_input_lut", "creative_look")

    def test_install_name_differs_from_the_store_filename(self, world):
        """Имя установки не равно имени файла в store — префикс реально спасает.

        Проверка не косметическая: она падает ровно в тот момент, когда кто-то
        «упростит» install_name до basename из манифеста и вернёт столкновение.
        """
        doc = world.build()
        for f in doc["install"]["files"]:
            assert f["install_name"] != Path(f["store_path"]).name

    def test_install_name_comes_from_id_not_orig_name(self, world):
        """Имя выводится из id куба, а не из его исходного имени в коллекции.

        Переименовывать луты в сданных проектах нельзя никогда, значит имя обязано
        быть выводимым и вечным. orig_name у этих кубов — «Neutral A7s3-Legacy.cube».
        """
        doc = world.build()
        assert doc["develops"][SLOG3_DEV]["install_name"] == f"YTAI_{SLOG3_DEV}.cube"
        assert doc["look"]["install_name"] == f"YTAI_{LOOK}.cube"
        assert doc["look"]["id"] == LOOK


class TestHonesty:
    def test_exposure_not_verified_against_premiere(self, world):
        """В документе лежит exposure_verified_against_premiere == False.

        ⚠️ Страж честности. Множитель 2,4 ВЫВЕДЕН из блоба шаблона Lumetri, а не
        замерен на живой программе: проба Input LUT / Exposure в Premiere ещё не
        сделана. Пока флаг false, утверждать перенос один в один нельзя — и
        перевести его в true имеет право только сама проба, а не правка кода.
        """
        doc = world.build()
        assert doc["exposure_verified_against_premiere"] is False

    def test_sources_point_at_the_real_inputs(self, world):
        """План называет, из чего собран: выбор дня и ДНК канала с их версиями.

        Файл производный, руками его править нельзя. Через месяц по одному словарю
        экспозиций не восстановить, откуда он взялся и можно ли на него опираться.
        """
        doc = world.build()
        src = doc["sources"]
        assert src["choice"] == str(world.choice_path)
        assert src["profile"] == str(world.profile_path)
        assert src["choice_doc_version"] == 3
        assert doc["project"] == CODE and doc["channel"] == "YTEVO"
