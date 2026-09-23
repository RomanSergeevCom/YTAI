#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Контракт прокси — единственная точка правды по восьми параметрам.

Прокси — это **лёгкая копия, а не мелкая**. Единственное, ради чего она делается, —
вес файла. Всё остальное обязано совпадать с оригиналом, потому что прокси
подменяется на оригинал сменой одной корневой папки (Premiere «Attach Proxies» /
«Link Media»), без единого сдвига по кадрам, звуку и таймкоду.

Совпадать обязаны (проверяется на КАЖДОМ клипе, а не на выборке):

  1 разрешение      1:1 с источником, не уменьшать
  2 fps             1:1, СТРОКОЙ: 29.97 = '30000/1001' ≠ '30'
  3 число кадров    ровно то же, по пакетам, а не по длительности
  4 битность        ПО ИСТОЧНИКУ: 10 бит → main10/p010le, 8 бит → main/yuv420p.
                    Не повышать и не понижать
  5 имена и пути    имя файла и относительный путь сцены 1:1
  6 звук            столько же дорожек, тот же порядок, каналы не схлопывать —
                    у камер L и R часто разные микрофоны
  7 таймкод         перенести из источника
  8 цветовые теги   проносить как есть; НЕ форсить bt709 на логе

Отличаться имеет право только кодек с битрейтом (HEVC ~8 Мбит/с вместо H.264
~140 Мбит/с, ×17–18 по весу) и цветовая субдискретизация 4:2:2 → 4:2:0.

⚠️ Почему 4:2:0, а не 4:2:2. ffmpeg 8.1.1 умеет `-profile:v main42210 -pix_fmt
p210le`, то есть аппаратный кодер 4:2:2 **умеет** — старое объяснение «не умеет»
неверно. Замер 22.09.2026 на RYA-FX3-1107, 15 с, 8 Мбит/с, PSNR после рабочего
`02_normal_scene.cube`:

    8 бит  yuv420p   39.44 дБ (худший кадр 38.84), 15 925 747 Б
    10 бит p010le    40.99 дБ (худший кадр 40.27), 15 847 822 Б
    10 бит p210le    40.92 дБ (худший кадр 40.01), 15 824 082 Б

При равном битрейте 4:2:2 тратит биты на цветовое разрешение вместо яркости и
выходит чуть ХУЖЕ 4:2:0, да ещё и профилем `Rext`, который играет не везде.
Поэтому канон — `main10`/`p010le`, а `--chroma 422` оставлен дверью на случай,
если однажды понадобится.

Модуль держится на одной стандартной библиотеке: его импортируют и системный
python3 из день-ингеста, и прогон комплекта, и ночная пересборка. Ничего не
печатает и не пишет на диск — только читает файлы и зовёт ffprobe/ffmpeg.

См. KB 3.4 /kb/proxy/ и project_knowledge/contract.md.
"""
import json
import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass, asdict

# ── константы рецепта ────────────────────────────────────────────────────────
ENCODER = "hevc_videotoolbox"
DEFAULT_BITRATE = "8M"
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "256k"

#: битрейт по частоте кадров: вдвое больше кадров требуют больше.
#: Политика пришла из день-ингеста (s11_proxy), теперь общая.
FPS_BITRATE = {25.0: "8M", 30.0: "8M", 50.0: "12M", 60.0: "12M"}
FPS_BITRATE_FALLBACK = "10M"

#: коридор сжатия — ТОЛЬКО ДЛЯ ОТЧЁТА. Приговор по нему не выносим: он зашит
#: под исходник ~140 Мбит/с и врёт на коротких клипах (см. gate)
RATIO_WINDOW = (12.0, 25.0)

#: во сколько раз битрейт прокси имеет право отличаться от заказанного.
#: Аппаратный кодер на коротких и на статичных сценах промахивается в обе
#: стороны, и это нормально; ловим только настоящий промах.
BITRATE_WINDOW = (0.35, 2.5)

#: короче этого спрашивать битрейт бессмысленно — контейнер весит больше картинки
SHORT_CLIP_SEC = 4.0

#: клип уже лёгкий, если он HEVC и его битрейт не выше целевого в столько раз
LIGHT_HEVC_FACTOR = 1.6

#: ...а для готового Rec.709 8-бит HEVC (айфон) порог выше: такой материал и так
#: впятеро легче лог-исходника, а перекодирование ему только вредит
LIGHT_HEVC_REC709 = 6.0

VIDEO_EXT = (".mp4", ".mov", ".mxf", ".mts", ".m4v")

#: Спаннер — второй экземпляр клипа, живущего в двух сценах. Имя ему даёт
#: 0113_frame_align: `RYA-FX3-1071__S10.MP4` это второй экземпляр
#: `RYA-FX3-1071.MP4`. Кодировать его дважды незачем: на Drive копия делается
#: server-side, без единого байта трафика.
#:
#: ⚠️ Опознаётся ПО ИМЕНИ, и это принципиально. До 23.09.2026 признаком
#: спаннера был `os.path.islink`, и он врал в обе стороны. У YTCH спаннеры —
#: обычные файлы, а не ссылки, так что признак не срабатывал вовсе. А у
#: съёмочных дней, собранных стадией day_ingest, симлинками являются ВСЕ
#: исходники: `01_Source` там не файлы, а ссылки на карту. На YTEVO03 это
#: означало, что все 172 клипа объявлялись спаннерами и прогон собирал НОЛЬ,
#: отчитываясь «пропущено 172» — и приёмка считала это законным. Признак
#: «ссылка» говорит о том, где лежит файл, а не о том, что он такое.
SPANNER_RE = re.compile(r"^(.+)__S\d+\.(MP4|MOV|mp4|mov)$")

#: ⚠️ Имя формата НА ВХОДЕ кодера и НА ВЫХОДЕ в файле — разные строки.
#: '-pix_fmt p010le' даёт файл, который ffprobe читает как 'yuv420p10le'.
#: Сверять pix_fmt строкой нельзя: завернёт каждый правильный клип.
#: Сверяем класс глубины, а ожидаемое имя держим здесь — для отчёта.
PIX_OUT = {"p010le": "yuv420p10le", "p210le": "yuv422p10le", "yuv420p": "yuv420p"}

#: звуковые кодеки, которые ffmpeg читает заведомо — для них проба не нужна
KNOWN_AUDIO = {
    "aac", "ac3", "eac3", "alac", "flac", "mp2", "mp3", "opus", "vorbis",
    "dts", "truehd", "pcm_s16le", "pcm_s16be", "pcm_s24le", "pcm_s24be",
    "pcm_s32le", "pcm_s32be", "pcm_f32le", "pcm_f32be", "pcm_u8", "pcm_alaw",
    "pcm_mulaw",
}

#: временное расширение. ⚠️ НЕ '.part': ffmpeg не угадывает мукcер по такому
#: имени и падает «Invalid argument». Лечится явным '-f mp4', который мы всегда
#: и ставим, но осмысленное расширение дешевле спора с угадайкой.
TMP_SUFFIX = ".part.mp4"


# ── данные ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class AudioStream:
    """Одна звуковая дорожка. Порядок и число каналов значимы, кодек — нет."""
    index: int
    codec: str
    tag: str
    channels: int
    layout: str
    decodable: bool


@dataclass(frozen=True)
class ColorTags:
    """Цветовые теги. Пустая строка — значимое значение: тега НЕТ.

    Sony FX3 не несёт их вовсе, и прокси обязана остаться такой же пустой.
    Прокси, которая вдруг отрапортовала bt709, — это регрессия, а не починка.
    """
    space: str = ""
    primaries: str = ""
    transfer: str = ""

    def as_tuple(self):
        return (self.space, self.primaries, self.transfer)

    def empty(self):
        return not any(self.as_tuple())


@dataclass(frozen=True)
class ClipSpec:
    """Всё, что контракт знает о файле. Снимается одним проходом ffprobe."""
    path: str
    size: int
    duration: float
    container: str
    width: int
    height: int
    fps: str                 # r_frame_rate строкой: '30000/1001' ≠ '30'
    frames: int              # nb_read_packets; -1 если не считали
    pix_fmt: str
    profile: str
    bit_depth: int
    audio: tuple
    timecode: str            # '' если нет
    timecode_src: str        # на какой дорожке нашли: 'rtmd' / 'tmcd' / 'format'
    color: ColorTags
    vcodec: str
    vbitrate_bps: int
    is_symlink: bool
    rotation: int = 0        # градусы из Display Matrix; 0 — поворота нет

    @property
    def resolution(self):
        return (self.width, self.height)

    @property
    def fps_float(self):
        return _fps_to_float(self.fps)

    @property
    def audio_shape(self):
        """Форма звука для сверки: только то, что обязано совпасть."""
        return tuple((a.channels for a in self.audio))


@dataclass(frozen=True)
class Decision:
    action: str      # 'encode' | 'copy' | 'skip-symlink'
    reason: str      # человекочитаемо — едет в отчёт и в Telegram
    profile: str = ""
    pix_fmt: str = ""
    bitrate: str = ""


@dataclass(frozen=True)
class PointResult:
    ok: bool
    src: object
    dst: object
    note: str = ""


@dataclass(frozen=True)
class GateResult:
    ok: bool
    points: dict
    failed: tuple

    def summary(self):
        if self.ok:
            return "контракт сошёлся"
        return "не сошлось: " + ", ".join(self.failed)


# ── вспомогательное ──────────────────────────────────────────────────────────
def _run(cmd, timeout=1800):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _fps_to_float(fps):
    try:
        if "/" in str(fps):
            num, den = str(fps).split("/", 1)
            den = float(den)
            return float(num) / den if den else 0.0
        return float(fps)
    except Exception:
        return 0.0


def bit_depth_of(pix_fmt):
    """Глубина по имени формата: yuv422p10le → 10, p010le → 10, yuv420p → 8."""
    p = (pix_fmt or "").lower()
    for depth in (16, 14, 12, 10, 9):
        if f"{depth}le" in p or f"{depth}be" in p or p.startswith(f"p{depth:03d}"):
            return depth
    # p010le/p210le/p410le — три цифры после 'p', первая цифра это не глубина
    if p.startswith("p") and len(p) > 4 and p[1:4].isdigit():
        return int(p[2:4]) if p[2:4] != "00" else 10
    return 8


def parse_size(text):
    """'20G' / '512M' / '1500000000' → байты. Для потолка стейджинга."""
    s = str(text).strip().upper()
    mult = 1
    if s.endswith("T"):
        mult, s = 1024 ** 4, s[:-1]
    elif s.endswith("G"):
        mult, s = 1024 ** 3, s[:-1]
    elif s.endswith("M"):
        mult, s = 1024 ** 2, s[:-1]
    elif s.endswith("K"):
        mult, s = 1024, s[:-1]
    return int(float(s) * mult)


def norm_rel(path):
    """Относительный путь для сверки имён.

    macOS отдаёт имена в NFD («и» + «combining breve»), Drive и Linux — в NFC.
    Без нормализации пункт 5 контракта ложно расходится на кириллице.
    """
    return unicodedata.normalize("NFC", path)


def free_gb(path):
    """Свободно на томе, где лежит (или будет лежать) path.

    Меряем по ближайшему СУЩЕСТВУЮЩЕМУ предку: statvfs на ещё не созданной
    подпапке вернёт ноль, и сторож остановит прогон на ровном месте.
    """
    p = os.path.abspath(path)
    while p != "/" and not os.path.isdir(p):
        p = os.path.dirname(p)
    st = os.statvfs(p)
    return st.f_bavail * st.f_frsize / 1e9


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


# ── снятие параметров ────────────────────────────────────────────────────────
def audio_decodable(path, stream_index, seconds=1.0, timeout=120):
    """Читается ли дорожка вообще.

    ⚠️ Не проверять по имени кодека. У Apple spatial audio тег `apac`, и у
    ffmpeg 8.1.1 есть декодер с ТАКИМ ЖЕ именем («Marian's A-pac») — совсем
    другой кодек. Единственный честный ответ даёт попытка декодировать.
    """
    try:
        r = _run(["ffmpeg", "-v", "error", "-nostdin", "-xerror",
                  "-t", str(seconds), "-i", path,
                  "-map", f"0:{stream_index}", "-f", "null", "-"], timeout=timeout)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def probe(path, count_frames=True, check_audio=True, timeout=1800):
    """Все восемь параметров одним снимком.

    count_frames=False — дешёвый режим для планирования: считать пакеты на
    сотнях 4K-клипов дважды это минуты чистого ожидания.
    """
    r = _run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
              "-of", "json", path], timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe не прочитал {path}: {r.stderr.strip()[-300:]}")
    j = json.loads(r.stdout or "{}")
    streams = j.get("streams") or []
    fmt = j.get("format") or {}

    vs = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = []
    for s in streams:
        if s.get("codec_type") != "audio":
            continue
        codec = s.get("codec_name") or ""
        tag = s.get("codec_tag_string") or ""
        # Дешёвое первым: привычные кодеки ffmpeg читает, декодер зря не гоняем.
        # Всё остальное — пробуем декодировать. По ИМЕНИ не судим: у Apple
        # spatial audio тег `apac`, и у ffmpeg есть декодер с тем же именем,
        # но это другой кодек. Честный ответ даёт только попытка.
        dec = codec in KNOWN_AUDIO
        if check_audio and not dec:
            dec = audio_decodable(path, s.get("index", 0))
        audio.append(AudioStream(
            index=int(s.get("index", 0)), codec=codec, tag=tag,
            channels=int(s.get("channels") or 0),
            layout=s.get("channel_layout") or "", decodable=dec))

    # таймкод: Sony держит его на data-дорожке (`rtmd`), а не в контейнере —
    # `format_tags=timecode` у оригинала вернёт ПУСТО, и легко решить, что
    # таймкода нет вовсе. Поэтому читаем сперва дорожки, и только потом format.
    #
    # ⚠️ Замер 23.09.2026 по 172 прокси YTEVO03: `format_tags=timecode` несут
    # НОЛЬ из 172. Прежний комментарий обещал, что ffmpeg «дублирует TC в
    # format_tags» — это неверно, и сверка по одному format_tags дала бы
    # «таймкод потерян у 172 из 172». А у 108 оригиналов Sony format_tags пуст,
    # так что тот же промах с другой стороны дал бы вывод «у Sony таймкода нет,
    # терять нечего» — ложное оправдание битого комплекта. Оба места, всегда.
    timecode, tc_src = "", ""
    for s in streams:
        if s.get("codec_type") not in ("data", "video"):
            continue
        tc = ((s.get("tags") or {}).get("timecode") or "").strip()
        if tc:
            timecode = tc
            tc_src = s.get("codec_tag_string") or s.get("codec_type") or "stream"
            break
    if not timecode:
        tc = ((fmt.get("tags") or {}).get("timecode") or "").strip()
        if tc:
            timecode, tc_src = tc, "format"

    frames = -1
    if count_frames:
        rf = _run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                   "-count_packets", "-show_entries", "stream=nb_read_packets",
                   "-of", "csv=p=0", path], timeout=timeout)
        try:
            frames = int((rf.stdout or "0").strip().split(",")[0])
        except (ValueError, IndexError):
            frames = -1

    vbits = 0
    for cand in (vs.get("bit_rate"), fmt.get("bit_rate")):
        try:
            vbits = int(cand)
            break
        except (TypeError, ValueError):
            continue

    # ⚠️ Поворот живёт в Display Matrix, а не в размерах кадра. Портретное
    # видео с айфона лежит как 3840x2160 с матрицей −90°, и ffmpeg при
    # перекодировании поворот ПРИМЕНЯЕТ: на выходе 2160x3840, и пункт 1
    # контракта разъезжается. Поймано 23.09.2026 на десяти клипах.
    rotation = 0
    for sd in (vs.get("side_data_list") or []):
        try:
            rotation = int(sd.get("rotation") or 0) or rotation
        except (TypeError, ValueError):
            pass

    pix = vs.get("pix_fmt") or ""
    return ClipSpec(
        path=path,
        size=os.path.getsize(path) if os.path.exists(path) else 0,
        duration=float(fmt.get("duration") or 0),
        container=fmt.get("format_name") or "",
        width=int(vs.get("width") or 0), height=int(vs.get("height") or 0),
        fps=str(vs.get("r_frame_rate") or ""), frames=frames,
        pix_fmt=pix, profile=str(vs.get("profile") or ""),
        bit_depth=bit_depth_of(pix),
        audio=tuple(audio), timecode=timecode, timecode_src=tc_src,
        color=ColorTags(space=vs.get("color_space") or "",
                        primaries=vs.get("color_primaries") or "",
                        transfer=vs.get("color_transfer") or ""),
        vcodec=vs.get("codec_name") or "", vbitrate_bps=vbits,
        is_symlink=os.path.islink(path), rotation=rotation,
    )


def probe_fast(path):
    """Без счёта пакетов и без проверки звука — для планирования."""
    return probe(path, count_frames=False, check_audio=False)


# ── решения ──────────────────────────────────────────────────────────────────
def target_pix(spec, chroma="420"):
    """Битность и профиль ПО ИСТОЧНИКУ (пункт 4).

    Повышать так же неправильно, как понижать: 8-битный айфон в main10 —
    это лишние биты, которые нечем заполнить.
    """
    if spec.bit_depth >= 10:
        return ("main42210", "p210le") if chroma == "422" else ("main10", "p010le")
    return ("main", "yuv420p")


def is_spanner(path):
    """Второй экземпляр клипа из другой сцены — по ИМЕНИ, не по признаку ссылки.
    Одна точка правды: этим же выражением пользуется `rebuild.spanner_plan`,
    которая вдобавок проверяет, что донор действительно есть в наборе."""
    return bool(SPANNER_RE.match(os.path.basename(path or "")))


def bitrate_for(spec, override=None, table=None):
    if override and override != "auto":
        return override
    table = table or FPS_BITRATE
    return table.get(round(spec.fps_float, 0), FPS_BITRATE_FALLBACK)


def decide(spec, bitrate=DEFAULT_BITRATE, chroma="420", force=None):
    """Кодировать или взять как есть. Порядок правил значим, первое совпадение.

    Правило «не жать то, что уже лёгкое»: клип перекодируется, только если он
    тяжёлый материал с камеры. Айфон уже Rec.709, уже HEVC, уже лёгкий —
    перекодирование только портит.
    """
    if is_spanner(spec.path) and force != "encode":
        return Decision("skip-symlink",
                        "клип-спаннер: второй экземпляр клипа из другой сцены — "
                        "кодируем один раз, вторую копию делаем на Drive server-side")
    if force == "copy":
        return Decision("copy", "принудительно --force copy")

    bad = [a for a in spec.audio if not a.decodable]
    if bad:
        a = bad[0]
        return Decision("copy",
                        f"дорожка {a.tag or a.codec or '?'} {a.channels}ch не декодируется — "
                        f"перекодирование потеряет её и метаданные, ни одна дорожка "
                        f"пропасть не должна")
    if force == "encode":
        prof, pix = target_pix(spec, chroma)
        return Decision("encode", "принудительно --force encode", prof, pix, bitrate)

    if spec.rotation:
        # Повернём сами — и разъедется разрешение; не повернём — разъедется
        # картинка у монтажёра. Геометрию не переписываем: берём как есть.
        return Decision("copy",
                        f"кадр повёрнут на {spec.rotation}° матрицей — "
                        f"перекодирование меняет геометрию, берём как есть")

    target_bps = _bitrate_bps(bitrate)
    if spec.vcodec == "hevc" and 0 < spec.vbitrate_bps <= target_bps * LIGHT_HEVC_FACTOR:
        return Decision("copy",
                        f"уже лёгкий HEVC {spec.vbitrate_bps/1e6:.0f} Мбит/с — "
                        f"копируем байт-в-байт")

    # Айфонное: уже HEVC, уже 8 бит, уже Rec.709 с проставленными тегами.
    # Такой материал в 5 раз легче лог-исходника с камеры, и перекодировать его
    # незачем — а рискованно (повороты, spatial-звук, метадорожки).
    if (spec.vcodec == "hevc" and spec.bit_depth == 8 and not spec.color.empty()
            and 0 < spec.vbitrate_bps <= target_bps * LIGHT_HEVC_REC709):
        return Decision("copy",
                        f"готовый Rec.709 HEVC {spec.vbitrate_bps/1e6:.0f} Мбит/с — "
                        f"не жмём то, что уже лёгкое")

    prof, pix = target_pix(spec, chroma)
    return Decision("encode",
                    f"тяжёлый материал с камеры: {spec.vcodec} "
                    f"{spec.vbitrate_bps/1e6:.0f} Мбит/с, {spec.bit_depth} бит",
                    prof, pix, bitrate)


def _bitrate_bps(text, default=8_000_000):
    """'8M' → 8 000 000. Битрейт считается в десятичных, не в двоичных."""
    s = str(text).strip().upper()
    try:
        if s.endswith("M"):
            return int(float(s[:-1]) * 1_000_000)
        if s.endswith("K"):
            return int(float(s[:-1]) * 1_000)
        if s.endswith("G"):
            return int(float(s[:-1]) * 1_000_000_000)
        return int(float(s))
    except ValueError:
        return default


# ── команда ──────────────────────────────────────────────────────────────────
def build_cmd(spec, dst, dec, tmp_suffix=TMP_SUFFIX, force_bt709=False):
    """Эталонная команда. Параметры читаются с источника, не хардкодятся.

    Инварианты вшиты, а не оставлены на усмотрение:
    - '-f mp4' всегда: временное имя не даёт ffmpeg угадать мукcер;
    - '0:a?' уходит отдельным элементом списка и никогда через шелл — в zsh
      незакавыченный '?' съедается как глоб;
    - цветовые теги не подставляем: отсутствие тега это значение (см. ColorTags).
    """
    tmp = dst + tmp_suffix
    cmd = ["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", spec.path,
           "-map", "0:v:0", "-map", "0:a?",
           "-c:v", ENCODER, "-b:v", dec.bitrate, "-tag:v", "hvc1",
           "-profile:v", dec.profile, "-pix_fmt", dec.pix_fmt,
           "-c:a", AUDIO_CODEC, "-b:a", AUDIO_BITRATE]
    if spec.timecode:
        cmd += ["-timecode", spec.timecode]
    if force_bt709 and spec.color.empty():
        cmd += ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
    cmd += ["-movflags", "+faststart", "-f", "mp4", tmp]
    return cmd


# ── гейт приёмки ─────────────────────────────────────────────────────────────
def gate(src, dst, rel_src, rel_dst, dec, ratio_window=RATIO_WINDOW):
    """Восемь пунктов плюс коридор сжатия. Каждый — отдельной строкой в отчёте,
    чтобы было видно, ЧТО именно не сошлось."""
    p = {}

    p["resolution"] = PointResult(src.resolution == dst.resolution,
                                  f"{src.width}x{src.height}", f"{dst.width}x{dst.height}")

    p["fps"] = PointResult(src.fps == dst.fps, src.fps, dst.fps,
                           "сверяем строкой: 30000/1001 не равно 30")

    p["frames"] = PointResult(src.frames == dst.frames and src.frames > 0,
                              src.frames, dst.frames, "по пакетам, не по длительности")

    # ⚠️ Сверяем КЛАСС ГЛУБИНЫ, а не имя формата. '-pix_fmt p010le' на входе
    # кодера даёт в файле 'yuv420p10le' — сверка строкой завернёт правильный клип.
    depth_ok = dst.bit_depth == src.bit_depth
    note = "битность берётся с источника: не повышаем и не понижаем"
    if dec.action == "encode" and depth_ok:
        expected = PIX_OUT.get(dec.pix_fmt)
        if expected and dst.pix_fmt != expected:
            note += f"; ожидали {expected}, получили {dst.pix_fmt} — посмотреть руками"
    p["bit_depth"] = PointResult(depth_ok,
                                 f"{src.pix_fmt}/{src.profile} ({src.bit_depth} бит)",
                                 f"{dst.pix_fmt}/{dst.profile} ({dst.bit_depth} бит)",
                                 note)

    p["path"] = PointResult(norm_rel(rel_src) == norm_rel(rel_dst),
                            norm_rel(rel_src), norm_rel(rel_dst))

    audio_ok = (len(src.audio) == len(dst.audio)
                and src.audio_shape == dst.audio_shape)
    p["audio"] = PointResult(audio_ok,
                             [[a.codec or a.tag or "?", a.channels] for a in src.audio],
                             [[a.codec or a.tag or "?", a.channels] for a in dst.audio],
                             "кодек меняться может, число дорожек, их порядок "
                             "и каналы в каждой — нет")

    tc_ok = (not src.timecode) or (dst.timecode == src.timecode)
    p["timecode"] = PointResult(tc_ok, src.timecode or "(нет)", dst.timecode or "(нет)",
                                f"источник: {src.timecode_src or '—'}, "
                                f"прокси: {dst.timecode_src or '—'}")

    color_ok = src.color.as_tuple() == dst.color.as_tuple()
    p["color"] = PointResult(color_ok, list(src.color.as_tuple()), list(dst.color.as_tuple()),
                             "источник без тегов — прокси тоже без тегов"
                             if src.color.empty() else "теги проносятся как есть")

    if dec.action == "copy":
        p["size_ratio"] = PointResult(dst.size == src.size,
                                      f"{src.size} Б", f"{dst.size} Б",
                                      "копия обязана быть побайтово равной")
    else:
        # ⚠️ Коридор по ОТНОШЕНИЮ РАЗМЕРОВ врёт, и вот как. Он зашит под
        # исходник ~140 Мбит/с, но у коротких обрубков Sony пишет куда больше:
        # RYA-FX3-0868 длиной 0.96 с идёт на 563 Мбит/с, и честная прокси даёт
        # сжатие ×45 — «вне коридора», хотя с ней всё в порядке.
        # Проверяем то, что на самом деле обещали: битрейт прокси около целевого.
        # Отношение размеров считаем и печатаем, но приговор выносим не по нему.
        ratio = (src.size / dst.size) if dst.size else 0.0
        target = _bitrate_bps(dec.bitrate)
        got = (dst.size * 8 / dst.duration) if dst.duration > 0 else 0
        smaller = 0 < dst.size < src.size
        if dst.duration < SHORT_CLIP_SEC:
            # У секундного файла контейнер весит больше картинки — спрашивать
            # с него битрейт бессмысленно. Требуем только, что он легче оригинала.
            ok = smaller
            note = (f"клип короче {SHORT_CLIP_SEC:g} с ({dst.duration:.2f} с): "
                    f"битрейт не спрашиваем, сжатие ×{ratio:.1f}")
        else:
            lo, hi = BITRATE_WINDOW
            ok = smaller and (lo * target) <= got <= (hi * target)
            note = (f"целились в {target/1e6:.0f} Мбит/с, вышло {got/1e6:.1f}; "
                    f"сжатие ×{ratio:.1f}")
        p["size_ratio"] = PointResult(ok, f"{src.size} Б",
                                      f"{dst.size} Б ({got/1e6:.1f} Мбит/с)", note)

    failed = tuple(k for k, v in p.items() if not v.ok)
    return GateResult(ok=not failed, points=p, failed=failed)


# ── отчёт ────────────────────────────────────────────────────────────────────
def report_row(src, dst, dec, g, rel, attempts=1, encode_sec=0.0, at=""):
    """Строка отчёта. Ключи v1 сохранены: их читают chain.py, editor_html.py
    и run_all.sh — схема v2 обязана быть НАДмножеством, иначе ломается всё,
    что уже умеет читать proxy_report.json."""
    status = "FAIL" if not g.ok else ("copied" if dec.action == "copy" else "encoded")
    return {
        # ── v1 ──
        "src": src.path, "dst": dst.path if dst else "",
        "status": status,
        "frames_src": src.frames, "frames_dst": dst.frames if dst else 0,
        "dur_src": round(src.duration, 3), "dur_dst": round(dst.duration, 3) if dst else 0,
        "size": dst.size if dst else 0,
        "err": "" if g.ok else g.summary(),
        # ── v2 ──
        "rel": norm_rel(rel),
        "action": dec.action, "reason": dec.reason,
        "size_src": src.size,
        "ratio": round(src.size / dst.size, 2) if dst and dst.size else 0,
        "contract": {k: {"ok": v.ok, "src": v.src, "dst": v.dst, **({"note": v.note} if v.note else {})}
                     for k, v in g.points.items()},
        "attempts": attempts, "encode_sec": round(encode_sec, 1),
        "speed_x": round(src.duration / encode_sec, 2) if encode_sec else 0,
        "at": at,
    }


def skipped_row(src, dec, rel, note=""):
    """Клип, который в комплект не пойдёт (спаннер-симлинк)."""
    return {"src": src.path, "dst": "", "status": dec.action, "frames_src": src.frames,
            "frames_dst": 0, "dur_src": round(src.duration, 3), "dur_dst": 0, "size": 0,
            "err": "", "rel": norm_rel(rel), "action": dec.action, "reason": dec.reason,
            "size_src": src.size, "ratio": 0, "contract": {}, "attempts": 0,
            "encode_sec": 0, "speed_x": 0, "at": note}


def summarize(rows, run_meta=None):
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    fails = [r for r in rows if r["status"] == "FAIL"]
    total = sum(r["size"] for r in rows)
    frames_ok = sum(1 for r in rows
                    if r["frames_src"] > 0 and r["frames_src"] == r["frames_dst"])
    return {
        "schema": 2,
        "run": run_meta or {},
        # ── ключи v1, на них смотрит chain.py и editor_html.py ──
        "n": len(rows), "fails": len(fails), "frames_ok": frames_ok,
        "total_bytes": total,
        "bitrate": (run_meta or {}).get("bitrate", DEFAULT_BITRATE),
        # ── v2 ──
        "counts": counts,
        "clips": rows,
    }


def spec_dict(spec):
    """ClipSpec → JSON-пригодный словарь (для подробного следа)."""
    d = asdict(spec)
    d["audio"] = [asdict(a) for a in spec.audio]
    d["color"] = list(spec.color.as_tuple())
    return d
