#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Нормализатор раскладки лутов: у лутов в проекте ОДИН дом.

Дом — `{проект}/01_Source/00_LUT/`. Рабочая тройка кубов лежит ПЛОСКО на верхнем
уровне: монтажёр открывает папку и видит ровно три файла, которые ему нужны, —
светлая сцена, нормальная, тёмная. Никакой навигации, никакого выбора «а этот
зачем».

Всё остальное про луты — доска выбора, кадры к ней, json этапа цвета — лежит
там же, но в `_build/`. Не потому что «мусор», а потому что это наша кухня:
монтажёру она не нужна, а через полгода нам самим понадобится ответ на вопрос
«почему выбрали именно этот куб» — и он должен лежать рядом с кубами, а не в
`00_Setup`, куда никто не пойдёт.

    {проект}/01_Source/00_LUT/
    ├── 01_bright_scene.cube      рабочая тройка, ПЛОСКО
    ├── 02_normal_scene.cube
    ├── 03_dark_scene.cube
    ├── README.md                 что это, откуда, почему выбрано
    └── _build/                   как выбирали
        ├── {CODE}_lut_board.html + {CODE}_lut_board_files/
        ├── {CODE}_color_choice.json
        ├── {CODE}_color_plan.json
        └── {CODE}_gamma_cache.json

⚠️ `{CODE}_lut_plan.json` остаётся в `00_Setup/01_Ingest/` — это легаси-файл,
его читают UXP-панель и `lut_board.py`. Переносить его — сломать чужой код.

⚠️ Медиа и луты здесь НИКОГДА не удаляются. Разрешено ровно три удаления:
дубль, совпавший БАЙТ В БАЙТ, мусор macOS (`.DS_Store`, `._*`) и пустой
каталог. Всё остальное при одинаковом имени — оставляем оба файла и говорим об
этом вслух, потому что угадать, какой из них нужный, скрипт не может.

⚠️ Одного размера для решения «это дубль» НЕ хватает. `.cube` пишется числами
фиксированной ширины, поэтому два РАЗНЫХ лута одной сетки весят одинаково до
байта — и удаление «по совпадению размера» однажды сотрёт чужую покраску, а
узнать об этом будет уже не по чему. Поэтому там, где решается удаление,
сверяем содержимое.

Сухой прогон по умолчанию: без `--apply` ни один байт не двигается.

    python3 lut_home.py selftest
    python3 lut_home.py --scan                      # что БЫ сделал по всем дискам
    python3 lut_home.py --project YTCR02 --apply    # сделать в одном проекте
    python3 lut_home.py --scan --apply --json /tmp/lut_home.json
"""
import argparse
import gzip
import json
import os
import re
import shutil
import sys
import time

# kit.py — единственный держатель таблицы канонических имён. Своей копии здесь
# быть не должно: разъедутся — и прокси-комплект начнёт спорить с проектом.
sys.path.insert(0, os.path.expanduser("~/YTAI/scripts/16_proxy/1601_build"))
try:
    import kit
except ImportError as exc:  # pragma: no cover — видно сразу при запуске
    sys.exit("не найден kit.py в ~/YTAI/scripts/16_proxy/1601_build: %s" % exc)

VERSION = "1.1"

SRC_DIR = "01_Source"
PROXY_DIR = "01_Source_Proxy"
HOME = kit.LUT_DIR                 # «00_LUT»
OLD_HOME = "LUT"                   # как называлось до префикса
BUILD = kit.LUT_BUILD_DIR          # «_build»; kit знает про неё, чтобы не
                                   # тащить кухню в комплект монтажёру
INGEST = os.path.join("00_Setup", "01_Ingest")

#: файлы этапа цвета узнаём по корню имени после кода проекта
BUILD_STEMS = ("lut_board", "lut_review", "color_choice", "color_plan", "gamma_cache")
#: ...кроме вот этого: его читает UXP-панель, он остаётся в 01_Ingest
LEGACY_KEEP = "{code}_lut_plan.json"

JUNK_NAMES = {".DS_Store"}
JUNK_PREFIX = "._"

# канон — `YT` + 2–4 буквы, но на дисках живёт и YTRSCEN (пять букв),
# поэтому верхнюю границу держим с запасом: лучше узнать код, чем пропустить проект
CODE_RE = re.compile(r"^(YT[A-Z]{2,6}\d+)(?:_|$)")

DEFAULT_ROOTS = ("/Volumes",)
#: тома, куда ходить незачем: загрузочный и сетевые времянки
SKIP_VOLUMES = {"Macintosh HD", "com.apple.TimeMachine.localsnapshots"}


# ────────────────────────────────────────────────────────────── чистая логика
# Всё, что ниже до класса Tree, работает со строками и числами. Это та часть,
# которую проверяет selftest: она не должна зависеть от того, что смонтировано.

def project_code(folder_name):
    """Код проекта из имени папки. `YTCR02_Kamran` → YTCR02, `YTRSCEN01` → YTRSCEN01.

    Имена вроде `YTAgeFree_Oleskina` канону не отвечают (буквы вперемешку с
    регистром, номера нет) — возвращаем None, код потом добираем с диска.
    """
    m = CODE_RE.match(folder_name)
    return m.group(1) if m else None


def is_junk(name):
    """Мусор macOS. Его можно удалять — это не медиа."""
    return name in JUNK_NAMES or name.startswith(JUNK_PREFIX)


def is_build_artifact(name, code):
    """Файл (или каталог) этапа цвета, которому место в `_build/`."""
    if not code:
        return False
    if name == LEGACY_KEEP.format(code=code):
        return False
    if not name.startswith(code + "_"):
        return False
    rest = name[len(code) + 1:]
    # точное совпадение, «.» для суффиксов (`color_plan.20260922.bak.json`)
    # и «_» для спутников (`lut_board_files`, `lut_board_version.json`)
    return any(rest == s or rest.startswith(s + ".") or rest.startswith(s + "_")
               for s in BUILD_STEMS)


def decide_landing(src, dst):
    """Что делать с файлом src, который хочет лечь туда, где уже лежит dst.

    src и dst — ('f', размер[, путь]) для файла, ('d', None[, путь]) для
    каталога, None — если в месте назначения пусто. Возвращает (решение,
    пояснение). Здесь только арифметика: размер равный — КАНДИДАТ в дубли,
    окончательное слово за settle(), которая смотрит байты.
    """
    if dst is None:
        return "move", ""
    if src[0] == "d" and dst[0] == "d":
        return "merge", "каталог уже есть — сливаю по файлам"
    if src[0] != dst[0]:
        return "conflict", "файл и каталог с одинаковым именем"
    if src[1] == dst[1]:
        return "drop_dup", "тот же размер, %d Б" % src[1]
    return "conflict", "размеры разные: %d Б и %d Б" % (src[1], dst[1])


def path_of(entry):
    """Где файл лежит НА ДИСКЕ прямо сейчас (переезды ещё только запланированы)."""
    return entry[2] if entry and len(entry) > 2 else None


def same_bytes(a, b, chunk=1 << 20):
    """Совпадают ли два файла побайтно. Не прочиталось — считаем, что НЕ совпали.

    Осторожность здесь одностороняя намеренно: ошибка «не смог прочесть» обязана
    приводить к «оставляю оба», а не к удалению вслепую.
    """
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            while True:
                ca, cb = fa.read(chunk), fb.read(chunk)
                if ca != cb:
                    return False
                if not ca:
                    return True
    except OSError:
        return False


def settle(src, dst):
    """decide_landing плюс сверка байтов там, где решается УДАЛЕНИЕ.

    Размер у кубов — плохой отпечаток (см. шапку модуля), поэтому «тот же
    размер» понижается до конфликта, если содержимое разошлось: два файла
    остаются на месте, а человек получает строку, по которой видно, что это
    не одно и то же.
    """
    what, note = decide_landing(src, dst)
    if what != "drop_dup":
        return what, note
    a, b = path_of(src), path_of(dst)
    if a and b and same_bytes(a, b):
        return what, note
    return "conflict", "размер тот же (%d Б), а содержимое РАЗНОЕ" % src[1]


# ─────────────────────────────────────────────────────── снимок каталога в уме
class Tree:
    """Каталог, каким он СТАНЕТ после запланированных действий.

    Нужен, чтобы сухой прогон не врал. Если переименование папки только
    запланировано, на диске её ещё нет, — и проверка «а что внутри» дала бы
    пустоту, а отчёт потерял бы половину работы. Поэтому состояние ведём в уме
    и обновляем на каждое действие.
    """

    def __init__(self, path):
        self.path = path
        self.items = {}
        self.junk = []
        if not os.path.isdir(path):
            return
        # ⚠️ Третьим полем несём РЕАЛЬНЫЙ путь: после планового переезда запись
        # переезжает в дерево получателя, а байты всё ещё лежат по старому
        # адресу — без него сверить содержимое было бы негде.
        with os.scandir(path) as it:
            entries = sorted(it, key=lambda x: x.name)
        for e in entries:
            if is_junk(e.name):
                self.junk.append(e.name)
                continue
            if e.is_dir(follow_symlinks=False):
                self.items[e.name] = ("d", None, e.path)
            else:
                try:
                    self.items[e.name] = ("f", e.stat().st_size, e.path)
                except OSError:
                    self.items[e.name] = ("f", -1, e.path)

    def get(self, name):
        return self.items.get(name)

    def put(self, name, entry):
        self.items[name] = entry

    def drop(self, name):
        self.items.pop(name, None)

    def empty(self):
        return not self.items


# ───────────────────────────────────────────────────────────────────── план
class Plan:
    """Список действий по одному проекту плюс предупреждения.

    Планирование и исполнение разведены намеренно: один и тот же список и
    печатается в сухом прогоне, и выполняется под `--apply`. Иначе отчёт и
    работа начинают расходиться — ровно та ловушка, про которую написано в
    kit.canon_luts.
    """

    def __init__(self, project, code):
        self.project = project
        self.code = code
        self.actions = []
        self.warnings = []
        self._trees = {}

    def tree(self, path):
        if path not in self._trees:
            self._trees[path] = Tree(path)
        return self._trees[path]

    def rel(self, path):
        try:
            return os.path.relpath(path, self.project)
        except ValueError:
            return path

    def add(self, kind, src=None, dst=None, note=""):
        self.actions.append({"kind": kind, "src": src, "dst": dst, "note": note,
                             "src_rel": self.rel(src) if src else None,
                             "dst_rel": self.rel(dst) if dst else None})

    def warn(self, text):
        self.warnings.append(text)

    def touched(self):
        return bool(self.actions) or bool(self.warnings)


def plan_land(plan, src_dir, name, dst_dir, entry=None):
    """Запланировать переезд одного имени из src_dir в dst_dir.

    Каталог, который уже есть в месте назначения, сливаем рекурсивно: кадры
    доски при повторном прогоне совпадают байт в байт, и терять их незачем.
    """
    src_tree, dst_tree = plan.tree(src_dir), plan.tree(dst_dir)
    entry = entry or src_tree.get(name)
    if entry is None:
        return
    src_p, dst_p = os.path.join(src_dir, name), os.path.join(dst_dir, name)
    what, note = settle(entry, dst_tree.get(name))
    if what == "move":
        plan.add("move", src_p, dst_p)
        src_tree.drop(name)
        dst_tree.put(name, entry)
    elif what == "drop_dup":
        plan.add("drop_dup", src_p, dst_p, note)
        src_tree.drop(name)
    elif what == "merge":
        inner = plan.tree(src_p)
        for sub in list(inner.items):
            plan_land(plan, src_p, sub, dst_p)
        plan_clear_dir(plan, src_p)
        if plan.tree(src_p).empty():
            src_tree.drop(name)
    else:
        plan.add("conflict", src_p, dst_p, note)
        plan.warn("%s: %s — оставляю оба, разберись руками"
                  % (plan.rel(src_p), note))


def drop_unused_mkdir(plan, mark):
    """Убрать «завести папку», если в неё в итоге ничего не поехало.

    Пустая папка сама по себе не вредна, но в отчёте она КАЖДЫЙ прогон
    выглядит несделанной работой — а по отчёту решают, закончено ли. Случай
    живой: все файлы упёрлись в конфликт, переезжать нечему, а строка
    «завести папку» остаётся.
    """
    if not any(a["kind"] == "move" for a in plan.actions[mark:]):
        del plan.actions[mark - 1]


def plan_clear_dir(plan, path):
    """Прибрать и снести каталог, если в нём остался только мусор macOS."""
    tree = plan.tree(path)
    if not tree.empty():
        return False
    for j in tree.junk:
        plan.add("drop_junk", os.path.join(path, j), note="мусор macOS")
    tree.junk = []
    plan.add("rmdir", path, note="пусто после переезда")
    # ⚠️ Родитель обязан узнать, что папки больше нет. Иначе в нашей модели он
    # остаётся «непустым», переживает прогон и сносится только на следующем —
    # то есть второй прогон по уже разобранному проекту снова находит работу,
    # а монтажёр до тех пор видит в 00_LUT пустую папку-призрак.
    parent = os.path.dirname(path)
    if parent and parent != path:
        plan.tree(parent).drop(os.path.basename(path))
    return True


def prune_empty(plan, path):
    """Снести опустевшее поддерево снизу вверх — за ОДИН прогон, а не по этажу.

    Обход строго снизу вверх: пока не решена судьба `sub/deep`, про `sub`
    сказать нечего.
    """
    for root, _dirs, _files in os.walk(path, topdown=False):
        rel = os.path.relpath(root, path)
        if rel != "." and any(p.startswith(".") for p in rel.split(os.sep)):
            continue        # в скрытые папки не лезем: они не наши
        plan_clear_dir(plan, root)


def lift_cubes(plan, container, home, skip=()):
    """Поднять кубы из подпапок `container` прямо в `home`, подпапки прибрать.

    Куб в подпапке монтажёр не найдёт, а искать не станет: он возьмёт то, что
    видно сразу, и покрасит не тем.
    """
    if not os.path.isdir(container):
        return
    for name, entry in list(plan.tree(container).items.items()):
        if entry[0] != "d" or name in skip or name.startswith("."):
            continue
        sub = os.path.join(container, name)
        for root, dirs, files in os.walk(sub):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in sorted(files):
                if f.lower().endswith(".cube"):
                    plan_land(plan, root, f, home)
        prune_empty(plan, sub)


# ──────────────────────────────────────────────────────────── шаги нормализации
def step_old_dir(plan, source):
    """`01_Source/LUT/` → `01_Source/00_LUT/`.

    Переносим по файлу, а не одним переименованием папки: если обе папки уже
    есть (а такое на дисках встречается), одним `rename` мы бы либо упали, либо
    затёрли содержимое.
    """
    old, home = os.path.join(source, OLD_HOME), os.path.join(source, HOME)
    if not os.path.isdir(old):
        return
    plan.add("mkdir", dst=home, note="дом лутов")
    mark = len(plan.actions)
    # ⚠️ Кубы из подпапок СТАРОГО дома поднимаем ДО того, как переносить
    # остальное. Наоборот нельзя: подпапка уехала бы в 00_LUT целиком, а
    # поднять из неё куб в этот же прогон уже не выйдет — на диске её там ещё
    # нет, а ходим мы по диску. Куб остался бы этажом ниже, то есть невидимым.
    lift_cubes(plan, old, home)
    for name in list(plan.tree(old).items):
        plan_land(plan, old, name, home)
    plan_clear_dir(plan, old)
    drop_unused_mkdir(plan, mark)
    warn_prproj_luts(plan)


def step_lift_cubes(plan, source):
    """Поднять кубы из подпапок `00_LUT` наверх — кроме `_build`."""
    home = os.path.join(source, HOME)
    lift_cubes(plan, home, home, skip=(BUILD,))


def step_canon_names(plan, source):
    """Старые имена кубов → канон. Таблица имён берётся из kit.LUT_CANON."""
    home = os.path.join(source, HOME)
    tree = plan.tree(home)
    for old, new in kit.LUT_CANON.items():
        entry = tree.get(old)
        if entry is None:
            continue
        what, note = settle(entry, tree.get(new))
        src_p, dst_p = os.path.join(home, old), os.path.join(home, new)
        if what == "move":
            plan.add("rename", src_p, dst_p, "канон имени")
            tree.drop(old)
            tree.put(new, entry)
        elif what == "drop_dup":
            plan.add("drop_dup", src_p, dst_p, "дубль под старым именем, " + note)
            tree.drop(old)
        else:
            plan.add("conflict", src_p, dst_p, note)
            plan.warn("%s и %s: %s — оставляю оба" % (old, new, note))


def step_build(plan, source):
    """Доску, кадры и json этапа цвета — из `00_Setup/01_Ingest` в `00_LUT/_build`.

    Доска и её каталог кадров переезжают вместе и сохраняют взаимное положение:
    html ссылается на кадры относительным путём, разлучи их — и страница
    откроется пустой.
    """
    if not plan.code:
        return
    ingest = os.path.join(plan.project, INGEST)
    if not os.path.isdir(ingest):
        return
    build = os.path.join(source, HOME, BUILD)
    names = [n for n in sorted(plan.tree(ingest).items)
             if is_build_artifact(n, plan.code)]
    if not names:
        return
    plan.add("mkdir", dst=build, note="как выбирали")
    mark = len(plan.actions)
    for name in names:
        plan_land(plan, ingest, name, build)
    drop_unused_mkdir(plan, mark)


def step_readme(plan, source):
    """README рядом с кубами — чтобы не пересказывать это в переписке каждый раз."""
    home = os.path.join(source, HOME)
    path = os.path.join(home, "README.md")
    # Дом мог быть заведён и косвенно — mkdir на `_build` создаёт и его,
    # и без этой оговорки такой проект остался бы с кухней, но без README.
    planned = any(a["kind"] == "mkdir" and a["dst"]
                  and (a["dst"] == home or a["dst"].startswith(home + os.sep))
                  for a in plan.actions)
    if not os.path.isdir(home) and not planned:
        return
    if os.path.exists(path):
        # ⚠️ Читаем БАЙТАМИ и декодируем с заменой: README в чужой кодировке
        # (или просто не текст) уронил бы UnicodeDecodeError — а это не OSError,
        # и обвалился бы весь `--scan`, то есть из-за одного проекта не
        # разобрались бы ни в одном.
        try:
            with open(path, "rb") as fh:
                head = fh.read(200).decode("utf-8", "replace")
        except OSError:
            head = ""
        if README_MARK in head:
            return          # наш и свежий — переписывать нечего
        if README_ANY not in head:
            # чужой текст в нашей папке ценнее нашего шаблона
            plan.warn("00_LUT/README.md написан руками — не трогаю")
            return
        plan.add("write", dst=path, note="README устарел, версия шаблона новее")
        return
    plan.add("write", dst=path, note="обзор папки")


def warn_prproj_luts(plan):
    """Проверить, не указывает ли .prproj на куб по старому пути.

    Premiere запоминает Input LUT путём к файлу. Если монтажёр когда-то выбрал
    куб мышкой из `01_Source/LUT/`, после переименования папки он его не
    найдёт. Смотрим честно, а не пугаем на всякий случай.
    """
    for f in sorted(os.listdir(plan.project)):
        if not f.endswith(".prproj"):
            continue
        if find_in_prproj(os.path.join(plan.project, f), (b".cube", b"/LUT/")):
            plan.warn("%s ссылается на кубы — после переименования проверь "
                      "Input LUT в Lumetri" % f)


def find_in_prproj(path, needles):
    """Есть ли в .prproj хоть одна из подстрок.

    Читаем кусками: распакованный проект бывает на гигабайт, целиком в память
    его тянуть незачем. Хвост предыдущего куска приклеиваем к следующему, иначе
    искомое, попавшее на стык, потеряется.
    """
    keep = max(len(n) for n in needles) - 1
    fh = None
    try:
        fh = gzip.open(path, "rb")
        fh.peek(2)  # не gzip — узнаём здесь, а не на середине файла
    except OSError:
        # ⚠️ Закрыть обязательно: несжатых .prproj на дисках половина, и без
        # этого при `--scan` мы тихо копим открытые дескрипторы на каждый
        # осмотренный проект, пока не упрёмся в лимит.
        if fh is not None:
            fh.close()
        try:
            fh = open(path, "rb")
        except OSError:
            return False
    try:
        tail = b""
        while True:
            chunk = fh.read(4 << 20)
            if not chunk:
                return False
            buf = tail + chunk
            if any(n in buf for n in needles):
                return True
            tail = buf[-keep:] if keep else b""
    except OSError:
        return False
    finally:
        fh.close()


# ──────────────────────────────────────────────────────────────────── README
# Метка с версией: по ней отличаем свой README от написанного руками и
# понимаем, надо ли его обновлять. Без версии пришлось бы переписывать файл
# каждый прогон — лишняя правка в проекте, который потом синхронится на Drive.
README_ANY = "<!-- lut_home"
README_MARK = "<!-- lut_home v%s -->" % VERSION

README_TMPL = """{mark}
# Луты проекта {code}

Здесь живут луты. Рабочая тройка лежит ПЛОСКО, прямо в этой папке — открыл и
взял. В подпапку `_build/` убрано то, как эти луты выбирали: она нужна нам, а
не монтажу.

## Что здесь лежит

{cubes}

## Откуда они

Это луты одноступенчатой схемы: проявка (log → Rec.709) и покраска слиты в один
куб, и все три посчитаны под **S-Log3**. Материал, снятый в другой гамме
(D-Log2 у DJI), таким лутом не просто «обесцвечивается» — у него топится
экспозиция. Если в проекте есть клипы не с Sony, тройку на них не вешать.

Новая схема цвета разведена на ступени (pre-lut → проявка по камере и гамме →
экспозиция числом → покраска) и живёт в `~/YTAI/scripts/15_color/`.

## Как выбирали

{build}

## Правила папки

- Кубы лежат ПЛОСКО наверху. Подпапки с кубами не заводим: чего не видно сразу,
  того для монтажа не существует.
- Ничего отсюда не удаляем. Лишнее — в `_build/`.
- Раскладку чинит `python3 ~/YTAI/scripts/15_color/lut_home.py --project <путь>`
  (без `--apply` он только расскажет, что сделал бы).

---
lut_home v{ver} · собрано {when}
"""


#: что значит каждый куб канонической тройки
CUBE_WHAT = {
    "01_bright_scene.cube": "кадр снят светло — лут не тянет тени, держит лицо",
    "02_normal_scene.cube": "нормальная экспозиция, рабочий вариант по умолчанию",
    "03_dark_scene.cube": "кадр снят темно — лут вытягивает, не ломая цвет",
}

CUBES_EMPTY = ("Кубов в папке пока нет. Тройка канала кладётся при заведении\n"
               "проекта, раскладка цвета — `1503_color_apply/color_apply.py "
               "--install --apply`.")


def cubes_section(home, code):
    """Таблица «что здесь лежит» — ПО ФАКТУ, а не по шаблону.

    Жёстко вписанная тройка врёт ровно в том сценарии, ради которого дом и
    заводился: `color_apply.py --install` кладёт сюда кубы раскладки
    (`YTAI_*.cube`), и README, обещающий ровно три файла, отправляет монтажёра
    искать то, чего в папке нет. Перечень файлов, которых нет, хуже пустого.
    """
    try:
        have = sorted(n for n in os.listdir(home)
                      if n.lower().endswith(".cube") and not is_junk(n))
    except OSError:
        have = []
    if not have:
        return CUBES_EMPTY
    rows = ["| файл | когда берём |", "|---|---|"]
    for n in have:
        if n in CUBE_WHAT:
            what = CUBE_WHAT[n]
        elif n.startswith("YTAI_"):
            what = ("куб раскладки цвета — какому клипу он достаётся, написано "
                    "в `_build/%s_color_plan.json`" % (code or "{CODE}"))
        else:
            what = "не наш канон — откуда он, знает тот, кто его положил"
        rows.append("| `%s` | %s |" % (n, what))
    # Оговорка про выбор по клипу имеет смысл только когда тройка тут лежит:
    # под пустой папкой она звучит как обещание того, чего нет.
    if any(n in have for n in CUBE_WHAT):
        rows += ["", "Выбор делается ПО КЛИПУ, а не по проекту: в одном дне "
                     "бывают все три."]
    return "\n".join(rows)


#: что означает каждый файл кухни — пишем только про те, что реально лежат
BUILD_WHAT = (
    ("_lut_board.html", "доска выбора, открывается двойным кликом — это обычная "
                        "страница. Кадры к ней лежат рядом в каталоге "
                        "`{code}_lut_board_files/`: без него страница пустая, "
                        "переносить их можно только вместе"),
    ("_lut_board_files", None),          # про кадры сказано строкой выше
    ("_lut_board_version.json", "какой по счёту прогон доски собран"),
    ("_lut_review.html", "доска прошлого поколения — оставлена как история"),
    ("_lut_review_files", None),
    ("_color_choice.json", "что выбрал человек по этому дню"),
    ("_color_plan.json", "раскладка по клипам из выбора и ДНК канала"),
    ("_gamma_cache.json", "измеренные гаммы клипов, чтобы не считать заново"),
)

BUILD_EMPTY = ("Доска выбора по этому проекту не собиралась: луты положены\n"
               "тройкой канала, как есть. Собрать доску — "
               "`scripts/15_color/1502_lut_pick/`.")


def build_section(build_dir, code):
    """Раздел «как выбирали» — по тому, что в `_build/` лежит на самом деле.

    Перечислять файлы, которых нет, — хуже, чем не перечислять ничего: человек
    пойдёт их искать.
    """
    try:
        have = sorted(os.listdir(build_dir))
    except OSError:
        have = []
    have = [n for n in have if not is_junk(n)]
    if not have:
        return BUILD_EMPTY
    lines = ["`_build/` — как выбирали эти луты:", ""]
    known = set()
    for suffix, what in BUILD_WHAT:
        name = (code or "") + suffix
        if name in have:
            known.add(name)
            if what:
                lines.append("- `%s` — %s." % (name, what.format(code=code)))
    other = [n for n in have if n not in known]
    if other:
        lines.append("- и ещё: " + ", ".join("`%s`" % n for n in other) + ".")
    return "\n".join(lines)


def readme_text(code, build_dir):
    home = os.path.dirname(build_dir)
    return README_TMPL.format(mark=README_MARK, code=code or "проекта", ver=VERSION,
                              cubes=cubes_section(home, code),
                              build=build_section(build_dir, code),
                              when=time.strftime("%d.%m.%Y %H:%M"))


# ────────────────────────────────────────────────────────────────── исполнение
def execute(plan, apply):
    """Выполнить запланированное. Без apply — не трогаем ничего."""
    if not apply:
        return
    for a in plan.actions:
        k = a["kind"]
        try:
            if k == "mkdir":
                os.makedirs(a["dst"], exist_ok=True)
            elif k in ("move", "rename"):
                os.makedirs(os.path.dirname(a["dst"]), exist_ok=True)
                shutil.move(a["src"], a["dst"])
            elif k in ("drop_dup", "drop_junk"):
                os.remove(a["src"])
            elif k == "rmdir":
                os.rmdir(a["src"])
            elif k == "write":
                # README пишем ПОСЛЕ переездов — он описывает итог, а не замысел
                with open(a["dst"], "w", encoding="utf-8") as fh:
                    fh.write(readme_text(
                        plan.code, os.path.join(os.path.dirname(a["dst"]), BUILD)))
        except OSError as exc:
            a["note"] = (a["note"] + " ⚠️ не вышло: %s" % exc).strip()
            plan.warn("%s: %s" % (a["src_rel"] or a["dst_rel"], exc))
    # ⚠️ Здесь стояла «страховка» — повторный kit.canon_luts(apply=True) по дому
    # лутов. Она убрана, и намеренно. Во-первых, таблица имён у неё та же самая
    # (kit.LUT_CANON, по ней работает step_canon_names) — узнать что-то сверх
    # плана ей неоткуда. Во-вторых, она переименовывала и УДАЛЯЛА файлы мимо
    # плана: в отчёте этих действий нет, в сухом прогоне их не увидеть, а
    # решение об удалении она принимает по одному размеру — то есть снесла бы
    # ровно тот файл, который мы строкой выше сознательно оставили как конфликт.
    # Инструмент, который делает не то, что напечатал, хуже, чем не делает ничего.


# ───────────────────────────────────────────────────────────────── один проект
def resolve_code(project):
    """Код проекта: из имени папки, а если имя нестандартное — с диска."""
    code = project_code(os.path.basename(project.rstrip(os.sep)))
    if code:
        return code
    ingest = os.path.join(project, INGEST)
    if os.path.isdir(ingest):
        for n in sorted(os.listdir(ingest)):
            for stem in ("_lut_board.html", "_color_plan.json", "_lut_plan.json",
                         "_ingest.json"):
                if n.endswith(stem):
                    return n[:-len(stem)]
    return None


def plan_project(project):
    project = os.path.abspath(project)
    plan = Plan(project, resolve_code(project))
    source = os.path.join(project, SRC_DIR)
    if not os.path.isdir(source):
        plan.warn("нет %s — не похоже на проект" % SRC_DIR)
        return plan
    step_old_dir(plan, source)
    step_lift_cubes(plan, source)
    step_canon_names(plan, source)
    step_build(plan, source)
    step_readme(plan, source)
    # Комплект монтажёра — та же папка и то же правило имён; сборка в _build
    # туда не едет, ему нужны только кубы.
    proxy = os.path.join(project, PROXY_DIR)
    if os.path.isdir(os.path.join(proxy, HOME)):
        step_canon_names(plan, proxy)
    return plan


# ─────────────────────────────────────────────────────────────────── обход дисков
def find_projects(roots, max_depth=3):
    """Проекты — каталоги на «YT...», внутри которых есть `01_Source`.

    По симлинкам не ходим: в проектах встречаются ссылки на карты, а карту
    трогать нельзя.
    """
    found, near = [], []
    for root in roots:
        if not os.path.isdir(root):
            continue
        stack = [(root, 0)]
        while stack:
            d, depth = stack.pop()
            try:
                with os.scandir(d) as it:
                    entries = sorted(it, key=lambda x: x.name)
            except OSError:
                continue
            for e in entries:
                if not e.is_dir(follow_symlinks=False) or e.name.startswith("."):
                    continue
                if e.name in SKIP_VOLUMES:
                    continue
                if os.path.isdir(os.path.join(e.path, SRC_DIR)):
                    (found if e.name.startswith("YT") else near).append(e.path)
                    continue  # внутрь проекта на поиски других проектов не лезем
                if depth + 1 < max_depth:
                    stack.append((e.path, depth + 1))
    return sorted(set(found)), sorted(set(near))


def resolve_project_arg(arg, roots):
    """`--project` принимает и путь, и код: по коду ищем по смонтированным дискам."""
    if os.path.isdir(arg):
        return [os.path.abspath(arg)]
    found, _ = find_projects(roots)
    hit = [p for p in found if os.path.basename(p) == arg
           or os.path.basename(p).startswith(arg + "_")
           or resolve_code(p) == arg]
    return hit


# ──────────────────────────────────────────────────────────────────────── отчёт
VERB = {
    "mkdir": "завести папку",
    "move": "перенести",
    "rename": "переименовать",
    "drop_dup": "убрать дубль",
    "drop_junk": "убрать мусор",
    "rmdir": "снести пустую папку",
    "write": "записать",
    "conflict": "⚠️ КОНФЛИКТ, не трогаю",
}


def report(plans, apply, near):
    done = "сделано" if apply else "СУХОЙ ПРОГОН — ничего не тронуто"
    print("lut_home v%s · %s" % (VERSION, done))
    print("=" * 78)
    n_act = n_warn = n_conf = 0
    for plan in plans:
        if not plan.touched():
            continue
        print("\n%s  %s" % (plan.code or "код не найден", plan.project))
        rows = []
        for a in plan.actions:
            was = a["src_rel"] or "—"
            now = a["dst_rel"] or "—"
            if a["kind"] in ("drop_dup", "drop_junk", "rmdir"):
                now = "убрано"
            rows.append((VERB.get(a["kind"], a["kind"]), was, now, a["note"]))
            n_act += 1
            n_conf += a["kind"] == "conflict"
        if rows:
            w1 = max(len(r[0]) for r in rows)
            w2 = min(max(len(r[1]) for r in rows), 46)
            print("  %-*s  %-*s  →  %s" % (w1, "что", w2, "было", "стало"))
            for verb, was, now, note in rows:
                line = "  %-*s  %-*s  →  %s" % (w1, verb, w2, was, now)
                print(line + ("   (%s)" % note if note else ""))
        for w in plan.warnings:
            print("  ⚠️  " + w)
            n_warn += 1
    print("\n" + "=" * 78)
    touched = [p for p in plans if p.touched()]
    print("проектов осмотрено: %d, требуют работы: %d, действий: %d, "
          "конфликтов: %d, предупреждений: %d"
          % (len(plans), len(touched), n_act, n_conf, n_warn))
    if near:
        print("рядом лежат папки с 01_Source, но имя не на «YT» — пропущены:")
        for p in near:
            print("   " + p)
    if not apply and touched:
        print("повтори с --apply, чтобы сделать")
    if apply and n_conf:
        # ⚠️ Раньше здесь висело «писатели по-прежнему кладут всё в 01_Ingest —
        # прогоняй lut_home после каждого подбора». Это уже неправда: и
        # lut_board.py, и color_apply.py пишут в `_build` сами, а звать заново
        # инструмент, которому нечего делать, — приучать не читать его вывод.
        print("⚠️ конфликты выше не рассасываются сами: пока два файла с одним "
              "смыслом лежат рядом, каждый прогон будет напоминать о них.")


def as_json(plans, apply):
    return {
        "tool": "lut_home", "version": VERSION, "apply": apply,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "projects": [{
            "code": p.code, "path": p.project,
            "actions": [{k: a[k] for k in ("kind", "src_rel", "dst_rel", "note")}
                        for a in p.actions],
            "warnings": p.warnings,
        } for p in plans if p.touched()],
    }


# ────────────────────────────────────────────────────────────────────── selftest
def selftest():
    """Проверка чистой логики: имена, дубли, слияние, путь с пробелом."""
    ok = []

    def check(name, cond):
        ok.append((name, bool(cond)))

    # разбор имён
    check("YTCR02_Kamran → YTCR02", project_code("YTCR02_Kamran_Sharaf") == "YTCR02")
    check("YTRSCEN01 без подчёркивания", project_code("YTRSCEN01") == "YTRSCEN01")
    check("YTUAE01_Igor → YTUAE01", project_code("YTUAE01_Igor_Kaloshin") == "YTUAE01")
    check("YTAgeFree_... кода не даёт", project_code("YTAgeFree_Oleskina") is None)
    check("чужая папка не проект", project_code("RYA-Premiere-Project") is None)

    # что едет в _build, а что остаётся
    c = "YTEVO03"
    check("доска едет", is_build_artifact("YTEVO03_lut_board.html", c))
    check("кадры доски едут", is_build_artifact("YTEVO03_lut_board_files", c))
    check("версия доски едет", is_build_artifact("YTEVO03_lut_board_version.json", c))
    check("бэкап раскладки едет",
          is_build_artifact("YTEVO03_color_plan.20260922_234159.bak.json", c))
    check("старая доска едет", is_build_artifact("YTEVO03_lut_review.html", c))
    check("ЛЕГАСИ lut_plan остаётся", not is_build_artifact("YTEVO03_lut_plan.json", c))
    check("чужой код не трогаем", not is_build_artifact("YTCR02_color_plan.json", c))
    check("ингест не трогаем", not is_build_artifact("YTEVO03_ingest.json", c))

    # решение о дубле
    check("пусто → переносим", decide_landing(("f", 10), None)[0] == "move")
    check("равные размеры → дубль", decide_landing(("f", 572349), ("f", 572349))[0]
          == "drop_dup")
    check("разные размеры → конфликт", decide_landing(("f", 10), ("f", 11))[0]
          == "conflict")
    check("каталог на каталог → слияние", decide_landing(("d", None), ("d", None))[0]
          == "merge")
    check("файл против каталога → конфликт",
          decide_landing(("f", 1), ("d", None))[0] == "conflict")

    # слияние двух папок и путь с пробелом — на одноразовой времянке
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        proj = os.path.join(td, "YTUAE PEOPLE", "YTUAE01_Igor_Kaloshin")
        old = os.path.join(proj, SRC_DIR, OLD_HOME)
        home = os.path.join(proj, SRC_DIR, HOME)
        os.makedirs(old)
        os.makedirs(home)
        open(os.path.join(old, "bright.cube"), "w").write("x" * 10)
        open(os.path.join(old, "normal.cube"), "w").write("y" * 20)
        # тот же самый файл под каноном уже лежит дома — вот это дубль:
        # совпадает не размер, а БАЙТЫ (размер у разных .cube одинаков сам по себе)
        open(os.path.join(old, "dark.cube"), "w").write("z" * 30)
        open(os.path.join(home, "03_dark_scene.cube"), "w").write("z" * 30)
        open(os.path.join(old, ".DS_Store"), "w").write("junk")

        plan = plan_project(proj)
        kinds = [(a["kind"], os.path.basename(a["src"] or a["dst"]))
                 for a in plan.actions]
        # путь с пробелом («YTUAE PEOPLE») обязан доезжать целиком: если бы
        # где-то путь склеивался через строку команды, он бы тут порвался
        moved = [a for a in plan.actions if a["kind"] == "move"]
        check("путь с пробелом доехал целиком",
              moved and all(a["src"].startswith(proj) and " " in a["src"]
                            for a in moved))
        check("сухой прогон ничего не тронул", os.path.exists(
            os.path.join(old, "bright.cube")))
        check("старую папку сносим", ("rmdir", OLD_HOME) in kinds)
        check("мусор убираем", ("drop_junk", ".DS_Store") in kinds)
        check("дубль по канону убран", ("drop_dup", "dark.cube") in kinds
              or ("drop_dup", "03_dark_scene.cube") in kinds)
        check("README запланирован", any(a["kind"] == "write" for a in plan.actions))

        execute(plan_project(proj), apply=True)
        after = sorted(os.listdir(home))
        check("после apply дома канон",
              after == ["01_bright_scene.cube", "02_normal_scene.cube",
                        "03_dark_scene.cube", "README.md"])
        check("старой папки нет", not os.path.exists(old))
        check("ничего не потеряли",
              os.path.getsize(os.path.join(home, "01_bright_scene.cube")) == 10
              and os.path.getsize(os.path.join(home, "02_normal_scene.cube")) == 20)

        # ВТОРОЙ прогон по разобранному проекту обязан молчать: иначе «сделано»
        # никогда не наступает, и по отчёту не понять, осталась работа или нет
        again = plan_project(proj)
        check("второй прогон ничего не находит",
              not again.actions and not again.warnings)

        # куб, зарытый в подпапке СТАРОГО дома, обязан оказаться наверху за ОДИН
        # прогон: иначе монтажёр открывает 00_LUT и видит папку вместо куба
        proj3 = os.path.join(td, "YTCR08_Sub")
        os.makedirs(os.path.join(proj3, SRC_DIR, OLD_HOME, "old", "deep"))
        open(os.path.join(proj3, SRC_DIR, OLD_HOME, "old", "deep",
                          "normal.cube"), "w").write("n" * 20)
        execute(plan_project(proj3), apply=True)
        home3 = os.path.join(proj3, SRC_DIR, HOME)
        check("куб из подпапки поднят наверх",
              os.path.exists(os.path.join(home3, "02_normal_scene.cube")))
        check("вложенные пустые папки снесены за один прогон",
              sorted(os.listdir(home3)) == ["02_normal_scene.cube", "README.md"])
        check("и повторять нечего", not plan_project(proj3).actions)

        # ⚠️ Главное про удаление: у .cube размер совпадает у РАЗНЫХ лутов, и
        # решать по нему — значит однажды стереть чужую покраску
        proj4 = os.path.join(td, "YTCR10_SameSize")
        old4 = os.path.join(proj4, SRC_DIR, OLD_HOME)
        home4 = os.path.join(proj4, SRC_DIR, HOME)
        os.makedirs(old4)
        os.makedirs(home4)
        open(os.path.join(old4, "normal.cube"), "w").write("A" * 40)
        open(os.path.join(home4, "02_normal_scene.cube"), "w").write("B" * 40)
        p4 = plan_project(proj4)
        execute(p4, apply=True)
        check("тот же размер, другое содержимое — НЕ удалено",
              os.path.exists(os.path.join(home4, "normal.cube"))
              and open(os.path.join(home4, "02_normal_scene.cube")).read()
              == "B" * 40)
        check("про подмену сказано вслух",
              any("содержимое РАЗНОЕ" in w for w in p4.warnings))

        # README в чужой кодировке не должен ронять прогон целиком
        proj5 = os.path.join(td, "YTCR11_Cp1251")
        home5 = os.path.join(proj5, SRC_DIR, HOME)
        os.makedirs(home5)
        open(os.path.join(home5, "01_bright_scene.cube"), "w").write("x")
        with open(os.path.join(home5, "README.md"), "wb") as fh:
            fh.write("# Луты".encode("cp1251"))
        try:
            p5 = plan_project(proj5)
            check("чужая кодировка README прогон не роняет",
                  any("руками" in w for w in p5.warnings))
        except UnicodeDecodeError:
            check("чужая кодировка README прогон не роняет", False)

        # разные размеры под одним смыслом — оба на месте, нас предупредили
        proj2 = os.path.join(td, "YTCR09_Test")
        old2 = os.path.join(proj2, SRC_DIR, OLD_HOME)
        home2 = os.path.join(proj2, SRC_DIR, HOME)
        os.makedirs(old2)
        os.makedirs(home2)
        open(os.path.join(old2, "bright.cube"), "w").write("a" * 5)
        open(os.path.join(home2, "01_bright_scene.cube"), "w").write("b" * 7)
        p2 = plan_project(proj2)
        execute(p2, apply=True)
        check("разные размеры — оба живы",
              os.path.exists(os.path.join(home2, "bright.cube"))
              and os.path.exists(os.path.join(home2, "01_bright_scene.cube")))
        check("и нас предупредили", any("оставляю оба" in w for w in p2.warnings))

    bad = [n for n, good in ok if not good]
    for n, good in ok:
        print("  %s %s" % ("✓" if good else "✗", n))
    print("selftest: %d/%d" % (len(ok) - len(bad), len(ok)))
    return 1 if bad else 0


# ──────────────────────────────────────────────────────────────────────── main
def main(argv):
    if argv and argv[0] == "selftest":
        return selftest()
    ap = argparse.ArgumentParser(
        description="нормализатор раскладки лутов: один дом 01_Source/00_LUT")
    ap.add_argument("--project", help="путь к проекту или его код (YTCR02)")
    ap.add_argument("--scan", action="store_true",
                    help="обойти смонтированные диски и найти все проекты")
    ap.add_argument("--root", action="append", default=[],
                    help="где искать при --scan (по умолчанию /Volumes)")
    ap.add_argument("--apply", action="store_true",
                    help="сделать (без флага — только рассказать)")
    ap.add_argument("--json", dest="json_out", help="машиночитаемый отчёт в файл")
    a = ap.parse_args(argv)

    roots = a.root or list(DEFAULT_ROOTS)
    near = []
    if a.project:
        projects = resolve_project_arg(a.project, roots)
        if not projects:
            print("не нашёл проект: %s" % a.project)
            return 2
    elif a.scan:
        projects, near = find_projects(roots)
    else:
        ap.error("нужен --project или --scan")

    plans = []
    for p in projects:
        plan = plan_project(p)
        execute(plan, a.apply)
        plans.append(plan)

    report(plans, a.apply, near)
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as fh:
            json.dump(as_json(plans, a.apply), fh, ensure_ascii=False, indent=2)
        print("json: %s" % a.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
