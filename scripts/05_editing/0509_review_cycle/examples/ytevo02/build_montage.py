#!/usr/bin/env python3
"""build_montage.py — монтажный лист YTEVO02 «Манифест платформы Эволюция».

Целевой порядок сборки (сошлись все пять линз разбора) превращается в список склеек,
привязанных к ПОСЛОВНЫМ таймкодам мастер-транскрибации:
  tc_in  = начало первого слова куска
  tc_out = конец последнего слова + min(зазор до следующего слова, 0,3 с)
Для каждой склейки считается: какой ракурс брать и файл-источник со смещением в КАЖДОМ
ракурсе, кто говорит (по большинству слов), паузы ≥0,7 с внутри куска, пересечение стыка
клипов. Экраны графики получают таймкод в ЧИСТОВИКЕ.

Ракурсы (с 15.09.2026, синхрон по звуку — 05_Review/angles.json):
  A — Sony A7 III, крупный план Дарьи: C0005…C0009 встык, это и есть мастер-ось времени;
  B — Blackmagic ProRes UHD, общий план: Анастасия слева, Дарья справа (A004_11201111_C010.mov).
Правило выбора: говорит Дарья → A; Анастасия или голос за кадром → B (крупного плана
Анастасии не снимали); всё, что после конца A (23:09.12), — только B. Время в B:
off = мастер − offset.

Границы задаются якорями (подсказка_сек, "слово"): берётся ближайшее к подсказке
вхождение слова — поэтому правка на полсекунды не ломает склейку.

  python3 build_montage.py           → montage.json + таблица в консоль
"""
import json
import re
from pathlib import Path

BASE = Path("/Volumes/T9-Black-RYA/YTEVO/YTEVO02_evolution_manifesto/00_Setup")
WORDS = BASE / "YTEVO02.words.json"
OUT = BASE / "montage.json"

CLIPS = [("C0005.MP4", 0.0, 342.72), ("C0006.MP4", 342.72, 685.44),
         ("C0007.MP4", 685.44, 1027.20), ("C0008.MP4", 1027.20, 1047.36),
         ("C0009.MP4", 1047.36, 1389.12)]
A_END = CLIPS[-1][2]                                   # конец ракурса A на мастер-оси
ANGLES = BASE / "05_Review" / "angles.json"             # синхрон ракурса B (xcorr по звуку)
TAIL_WORDS = BASE / "YTEVO02wide_tail.words.json"       # речь B после конца A, время клипа B
GAP_WORDS = BASE / "YTEVO02wide_gap.words.json"         # речь B внутри дыры записи A (шов C0008/C0009)
ANGLE_LABEL = {"A": "A · крупный · Дарья", "B": "B · общий · Анастасия и Дарья"}
SPEAKER_ANGLE = {"Speaker 1": "A", "Speaker 2": "B", "Speaker 3": "B"}
SPEAKER_NAME = {"Speaker 1": "Дарья", "Speaker 2": "Анастасия", "Speaker 3": "за кадром"}
GAP_MIN, GAP_KEEP, PAD = 0.7, 0.35, 0.3


def m(mm, ss):
    return mm * 60 + ss


# ---------------- целевой порядок ----------------
# part: ("say", (in_hint, in_word), (out_hint, out_word))
#       ("gfx", "Gxx", сек)   — полноэкранная вставка со своим хронометражем
#       ("hold", "текст", сек) — тишина / удержание
# gfx:  ("Gxx", (hint, word)) — экран поверх речи, встаёт на это слово
PIECES = [
    dict(id="01", title="Холодный старт · «Кто ваши герои?»", block=8, act="Крючок",
         parts=[("say", (m(16, 51.76), "потому"), (m(17, 9.0), "плечами"))],
         gfx=[("G01", (m(17, 2.3), "двое"))],
         note="Паузу после «мама с папой» держать целиком — это и есть удар. Кусок на общем плане B: "
              "у B нет швов файлов, а стык C0007/C0008 камеры A (17:07.20) по звуку B непрерывен."),
    dict(id="02", title="Заставка «ЭВОЛЮЦИЯ»", act="Крючок",
         parts=[("gfx", "G02", 4.0)]),
    dict(id="03", title="«Не делать это мы не можем»", block=2, act="Кто мы",
         parts=[("say", (m(3, 24.6), "и"), (m(3, 33.4), "можем"))],
         note="Самая честная фраза первой трети — сразу после заставки задаёт интонацию."),
    dict(id="04", title="Кто говорит и чего хотели", block=2, act="Кто мы",
         parts=[("say", (m(1, 11.68), "дорогие"), (m(1, 20.4), "годы")),
                ("say", (m(2, 20.58), "мы"), (m(2, 33.3), "счастливыми"))],
         gfx=[("G03", (m(1, 12.5), "дорогие"))],
         note="Вторая половина — единственная внятная мотивация из вводных 3:37."),
    dict(id="05", title="АНО «Эволюция» и единая среда", block=3, act="Кто мы",
         parts=[("say", (m(4, 48.5), "два"), (m(5, 42.5), "друга"))],
         gfx=[("G04", (m(4, 49.0), "два")), ("G05", (m(4, 53.7), "мы"))],
         note="Кусок на общем плане B (говорит Анастасия): швов файлов у B нет, стык C0005/C0006 камеры A "
              "по звуку непрерывен. Внутри пауза после «объединять людей» — подрезать."),
    dict(id="06", title="Национальная цель: Конституция, указы, шесть советов", block=6, act="Опора",
         parts=[("say", (m(11, 1.32), "большое"), (m(11, 23.3), "поправка")),
                ("say", (m(11, 30.18), "что"), (m(12, 5.6), "целостность")),
                ("say", (m(12, 7.3), "это"), (m(12, 13.5), "отраслях")),
                ("gfx", "G08", 7.0),
                ("say", (m(12, 22.06), "и"), (m(12, 37.4), "дополнять")),
                ("say", (m(12, 54.64), "и"), (m(12, 59.5), "нас"))],
         gfx=[("G06", (m(11, 14.0), "году")), ("G07a", (m(11, 43.5), "818")),
              ("G07b", (m(11, 47.5), "809")), ("G15", (m(11, 54.5), "и"))],
         note="Первый дубль цитаты Конституции (11:23–11:30) снят, берём второй — медленнее и чище. "
              "«Платформа Эмолюция —» отрезано, кусок начинается с «это собор шести советов». "
              "Неверное перечисление советов (12:13–12:21) заменено полноэкранной карточкой G08. "
              "Хвост с повтором неверных названий (12:37–12:54) снят."),
    dict(id="07", title="СССР — Союз Созидательных Сил России", block=7, act="Логика",
         parts=[("say", (m(13, 1.92), "изначально"), (m(13, 27.3), "федерации"))],
         gfx=[("G09", (m(13, 10.0), "ссср"))],
         note="Карточка-расшифровка обязана встать ВПРИТЫК к слову «СССР» — без неё фраза "
              "читается буквально. Следующие 13 с (13:27–13:40, «социальная рация») сняты."),
    dict(id="08", title="Совет ТРУД — почему первым", block=7, act="Логика",
         parts=[("say", (m(13, 40.36), "мы"), (m(14, 3.7), "россии")),
                ("say", (m(14, 30.74), "но"), (m(14, 44.1), "преодолеть")),
                ("say", (m(14, 44.2), "поэтому"), (m(14, 50.4), "предпринимательства")),
                ("say", (m(15, 5.64), "мы"), (m(15, 21.4), "будущего"))],
         gfx=[("G10", (m(14, 45.0), "советом"))],
         note="Сняты «создают новые годы» (14:03–14:12) и «база, которая будет разрываться» "
              "(14:16–14:30). В речи «ценностно-инвентированного» — титр G10 даёт верное название. "
              "Мероприятия 14:50–15:05 ужаты до одного тезиса."),
    dict(id="09", title="Совет КУЛЬТУРА — основа цивилизации", block=7, act="Логика",
         parts=[("say", (m(15, 38.66), "и"), (m(16, 21.3), "общего"))],
         gfx=[("G11", (m(15, 46.0), "совет"))],
         note="В речи «Совет Культурного Хода» — титр G11 правит на «КУЛЬТУРА · культурный код». "
              "16:00–16:21 — 27 слов на 21 с, паузы подрезать."),
    dict(id="10", title="Запуск «Эволюция ТВ»", block=8, act="Новость",
         parts=[("say", (m(16, 21.34), "и"), (m(16, 45.6), "россию")),
                ("hold", "2 с тишины — дать новости осесть", 2.0),
                ("say", (m(16, 45.76), "эволюция"), (m(16, 51.6), "платформой")),
                ("say", (m(17, 9.08), "но"), (m(17, 22.2), "видимое"))],
         gfx=[("G12", (m(16, 26.0), "тв"))],
         note="«Но героев у нас много» — отсылка к холодному старту: кольцо замыкается здесь, "
              "а не в финале."),
    dict(id="11", title="Как устроена платформа: человек за видео", block=9, act="Продукт",
         parts=[("say", (m(17, 22.34), "мы"), (m(17, 59.6), "другу")),
                ("say", (m(18, 8.1), "когда"), (m(18, 26.8), "видели"))],
         gfx=[("G13", (m(17, 42.1), "потому"))],
         note="Снят фальстарт «первокультурную…» (17:59–18:06). Четырёхкратное «чтобы у нас "
              "появилась…» оставлено целиком — ритмический якорь второй половины. ⚠ Внутри первой склейки "
              "шов C0008/C0009 (17:27.36): камера A не писала 3,16 с и склеила «создавать эту | форму эволюции ТВ». "
              "На общем плане B фраза целая (расшифровано по звуку B) — «создавать этот путь и образ, который на самом деле "
              "уже есть. И платформа Эволюция ТВ, и это её часть». Кусок стоит на B и в листе посчитан по B: "
              "на 3,16 с длиннее мастер-отрезка, все таймкоды после него сдвинуты. Мокап G13 разложен на крупный план A — "
              "на общем плане проверить свободную зону."),
    dict(id="12", title="Информация и страх — против чего всё это", block=10, act="Зачем",
         parts=[("say", (m(18, 28.54), "да"), (m(18, 36.1), "миром")),
                ("say", (m(18, 47.7), "и"), (m(19, 31.7), "будущего"))],
         note="Снята оборванная фраза «новости должны быть столько, сколько» (18:36–18:47). "
              "В субтитрах править «в водосостоянии» → «в благосостоянии»."),
    dict(id="13", title="Что такое «эволюция»: ЭВА · ЛЮ · Ц · Я", block=4, act="Смысл",
         parts=[("say", (m(6, 5.56), "если"), (m(6, 12.6), "сталкивается")),
                ("say", (m(7, 36.9), "хочется"), (m(8, 25.3), "вокруг"))],
         gfx=[("G14", (m(7, 50.4), "эва"))],
         note="Из двух объяснений оставлено одно — разбор по слогам. 06:33–07:36 (развал речи) "
              "снят целиком. Слоги держатся ТОЛЬКО с анимированной G14 — на слух не считываются."),
    dict(id="14", title="Почему Россия", block=5, act="Смысл",
         parts=[("say", (m(8, 38.08), "почему"), (m(9, 16.9), "человека"))],
         note="Взято одним куском без склеек — 39 с, в целевом окне 40–55 с. Самоповтор "
              "09:32–10:24 и сбитый хвост 10:35–11:01 сняты."),
    dict(id="15", title="Жизнь будущего — формула", block=2, act="Смысл",
         parts=[("say", (m(4, 2.8), "и"), (m(4, 13.1), "созиданием"))],
         gfx=[("G18", (m(4, 7.0), "жизнь"))],
         note="Единственное чистое определение в материале — перед призывом задаёт, куда зовут."),
    dict(id="16", title="Призыв: эволюция.рус · реестр · заявка", block=11, act="Призыв",
         parts=[("say", (m(20, 24.86), "мы"), (m(20, 42.9), "советов")),
                ("say", (m(20, 57.58), "мы"), (m(21, 33.7), "людям")),
                ("say", (m(21, 34.3), "если"), (m(22, 4.8), "вместе"))],
         gfx=[("G20", (m(20, 29.28), "эволюция")),("G08", (m(20, 33.5), "шесть")),
              ("G16", (m(21, 35.0), "если"))],
         note="Снято «мы регистрируемся… начинаем ценностную путь» (20:43–20:53) — регистрацию "
              "(физлицо / проект) показывает графика. Снято «спускается эволюция ТВ» — кусок "
              "начинается с «Мы ищем создателей». «Развестить» (21:19) — в субтитрах «разместить»."),
    dict(id="17", title="Финал: «всё рождается из вас самих» → «Да здравствует эволюция!»", block=12, act="Финал",
         parts=[("say", (m(19, 31.8), "потому"), (m(19, 53.3), "всевышний")),
                ("say", (m(22, 45.5), "люди"), (m(23, 5.7), "ресурсов")),
                ("say", (m(23, 6.19), "попробуйте"), (m(23, 21.6), "творчеством")),
                ("say", (m(24, 11.27), "будущее"), (m(24, 19.6), "миру")),
                ("say", (m(24, 47.99), "всё"), (m(24, 57.11), "эволюция")),
                ("gfx", "G17", 6.0)],
         note="Финал достроен с общего плана B. C0010 камеры A не передан: C0009 — ровно полный 4-ГБ кусок, запись "
              "шла дальше, а последние слова A распознаны на обрезанном звуке («истинно вас дарят»). На B речь идёт ещё "
              "≈1:49 до «Да здравствует эволюция!»: с «Попробуйте найти те желания…» только ракурс B, переход A→B на "
              "границе фраз (пауза 0,34 с). Звук: чтобы монолог не менял микрофон, для второй склейки тоже взять звук B "
              "(у неё есть B-ссылка) или сгладить стык атмосферой. Взяты «…двигайтесь вместе с ними, тем самым вы будете "
              "усиливать процесс совместным творчеством», «Будущее России создаётся созиданием каждого из нас. И поймите, "
              "что у вас есть то, что нужно стране, у вас есть то, что нужно миру» и «Всё уже происходит, всё уже случается. "
              "Да здравствует эволюция!». Не взяты: «И если вам нужны инструменты… присоединяйтесь к нам… с соборными силами "
              "России…» (23:22–23:49; призыв уже в куске 16, «соборными» распознано как «оборными» — проверить на слух), "
              "«Не будем ждать ничего от нашего управляющего звена…» (23:49–24:11, политический тон), «почувствуйте в себе "
              "это качество…» и молитва «Господи, каким качеством я могу служить миру» (24:20–24:47). «Ура!» после "
              "«эволюция» отрезано, выход за 0,1 с до него, — проверить на слух; вход на «Всё» (без «И»): метка «И» "
              "ненадёжна. «Она» в первой склейке — это «жизнь будущего» из куска 12; если на слух не держится — начать "
              "с 19:29.4 («…и мы ждём жизни будущего»). Сняты «мы сами в это не верим» (22:11) и богословская вставка "
              "22:27–22:45."),
]

GFX = {
    "G01": ("new", "«Кто ваши герои?» — 2 из 60", "overlay"),
    "G02": ("new", "Заставка «ЭВОЛЮЦИЯ»", "full"),
    "G03": ("new", "Плашка: Дарья Благо", "lower-third"),
    "G04": ("new", "Плашка: Анастасия Григорьева", "lower-third"),
    "G05": ("new", "Карточка АНО «Эволюция»", "full"),
    "G06": ("client", "Слайд клиента: ст. 67.1 Конституции", "full"),
    "G07a": ("client", "Слайд клиента: Указ №818", "full"),
    "G07b": ("client", "Слайд клиента: Указ №809", "full"),
    "G08": ("new", "Шесть советов — верные названия", "full"),
    "G09": ("client", "Слайд клиента: СССР — три расшифровки", "full"),
    "G10": ("new", "Титр: Совет ТРУД", "lower-third"),
    "G11": ("new", "Титр: Совет КУЛЬТУРА", "lower-third"),
    "G12": ("new", "Заставка «ЭВОЛЮЦИЯ ТВ»", "full"),
    "G13": ("new", "Интерфейс: за каждым видео — человек", "full"),
    "G14": ("new", "ЭВА · ЛЮ · Ц · Я", "full"),
    "G15": ("client", "Слайд клиента: Путь России 2020→2036", "full"),
    "G16": ("new", "Развилка: я снимаю / снимите меня", "full"),
    "G17": ("new", "Финал: «Зависит от нас» · эволюция.рус", "full"),
    "G18": ("new", "Формула: любовь · смысл · созидание", "overlay"),
    "G20": ("new", "Плашка домена эволюция.рус", "lower-third"),
}


# ---------------- слова ----------------
def to_sec(v):
    if isinstance(v, (int, float)):
        return float(v)
    p = str(v).split(":")
    return float(p[0]) * 60 + float(p[1]) if len(p) == 2 else float(p[0])


def norm(w):
    return re.sub(r"[^\w.]+", "", str(w).lower().replace("ё", "е")).strip(".")


def load_angle_b():
    if not ANGLES.exists():
        return None
    return json.loads(ANGLES.read_text(encoding="utf-8"))["scene1"]["angles"]["B"]


def ang_segments(ang):
    """кусочная карта: у каждого непрерывного участка записи A своё смещение B (дыры A между участками)"""
    return ang.get("segments") or [{"master_from": 0.0, "master_to": 1e9, "offset": ang["offset"],
                                    "rate": ang.get("rate", 1.0)}]


def seg_at(ang, t):
    segs = ang_segments(ang)
    for sg in segs:
        if sg["master_from"] - 1e-6 <= t <= sg["master_to"] + 1e-6:
            return sg
    return segs[-1] if t > segs[-1]["master_to"] else segs[0]


def to_master(ang, c):
    """время клипа B → мастер-ось; хвост после A — по последнему участку"""
    sg = ang_segments(ang)[-1]
    return sg["offset"] + c * sg.get("rate", 1.0)


def to_b(ang, t):
    sg = seg_at(ang, t)
    return (t - sg["offset"]) / sg.get("rate", 1.0)


def b_ref(ang, t0, t1):
    if ang is None:
        return None
    c0, c1 = to_b(ang, t0), to_b(ang, t1)
    if c0 < 0 or c1 > ang["duration"]:
        return None
    ref = {"file": ang["file"], "off_in": round(c0, 3), "off_out": round(c1, 3)}
    s0, s1 = seg_at(ang, t0), seg_at(ang, t1)
    if s0 is not s1:
        # кусок перекрывает дыру записи A: в B эта речь идёт на (разница смещений) дольше
        ref["a_gap_inside"] = round(s0["offset"] - s1["offset"], 3)
        ref["a_gap_at"] = s0["master_to"]
    return ref


def load_words(ang=None):
    d = json.loads(WORDS.read_text(encoding="utf-8"))
    ws = []
    for seg in d["segments"]:
        for w in seg.get("words", []):
            ws.append({"w": w["w"].strip(), "n": norm(w["w"]), "s": to_sec(w["s"]),
                       "e": to_sec(w["e"]), "sp": w.get("speaker") or seg.get("speaker")})
    ws.sort(key=lambda x: x["s"])
    if ang and TAIL_WORDS.exists():
        # хвост есть только в ракурсе B: слова переводятся на мастер-ось; с switch_master они заменяют
        # слова A (конец C0009 распознан на обрезанном звуке)
        t = json.loads(TAIL_WORDS.read_text(encoding="utf-8"))
        switch = t.get("switch_master", ws[-1]["e"] + 0.05)
        ws = [w for w in ws if w["s"] < switch]
        for seg in t["segments"]:
            for w in seg.get("words", []):
                s0 = to_master(ang, to_sec(w["s"]))
                if s0 >= switch:
                    ws.append({"w": w["w"].strip(), "n": norm(w["w"]), "s": s0,
                               "e": to_master(ang, to_sec(w["e"])), "sp": w.get("speaker") or seg.get("speaker"),
                               "tail": True})
        ws.sort(key=lambda x: x["s"])
    if ang and GAP_WORDS.exists():
        # слова, которых на оси A нет вовсе (дыра записи): для текста куска вписываются в окно
        # replace_master вместо склеенных распознаванием слов A; время куска считает main() по B
        g = json.loads(GAP_WORDS.read_text(encoding="utf-8"))
        for sp in g["splices"]:
            m0, m1 = sp["replace_master"]
            bw = sp["words"]
            c0, c1 = to_sec(bw[0]["s"]), to_sec(bw[-1]["e"])
            k = (m1 - m0) / max(c1 - c0, 1e-6)
            ws = [w for w in ws if not (m0 <= w["s"] < m1)]
            for w in bw:
                ws.append({"w": w["w"].strip(), "n": norm(w["w"]), "s": m0 + (to_sec(w["s"]) - c0) * k,
                           "e": m0 + (to_sec(w["e"]) - c0) * k, "sp": w.get("speaker") or sp.get("speaker"),
                           "gap_b": True})
        ws.sort(key=lambda x: x["s"])
    return ws


ERRORS = []


def anchor(ws, hint, word, edge):
    """индекс слова: ближайшее к подсказке вхождение word (по началу для in, по концу для out)"""
    key = "s" if edge == "in" else "e"
    cand = [i for i, w in enumerate(ws) if abs(w[key] - hint) < 6.0 and
            (word is None or w["n"] == norm(word) or w["n"].startswith(norm(word)))]
    if not cand:
        ERRORS.append(f"якорь не найден: {word!r} около {tc(hint)} ({edge})")
        # ближайшее по времени слово — прогон доходит до конца и показывает ВСЕ промахи разом
        return min(range(len(ws)), key=lambda i: abs(ws[i][key] - hint))
    return min(cand, key=lambda i: abs(ws[i][key] - hint))


def tc(t, ms=True):
    t = max(0.0, float(t))
    mm, ss = divmod(t, 60)
    return f"{int(mm):02d}:{ss:05.2f}" if ms else f"{int(mm):02d}:{int(ss):02d}"


def clip_at(t):
    for name, a, b in CLIPS:
        if a <= t < b:
            return name, t - a
    name, a, b = CLIPS[-1]
    return name, b - a


# ---------------- сборка ----------------
def main():
    ang = load_angle_b()
    ws = load_words(ang)
    cursor = 0.0            # позиция в чистовике
    trimmed_cursor = 0.0    # то же после подрезки пауз
    pieces_out = []
    for p in PIECES:
        parts_out, piece_start, piece_start_tr = [], cursor, trimmed_cursor
        spoken_ranges = []
        for part in p["parts"]:
            if part[0] in ("gfx", "hold"):
                dur = float(part[2])
                parts_out.append({"kind": part[0], "ref": part[1], "dur": dur,
                                  "dst_in": round(cursor, 3), "dst_out": round(cursor + dur, 3)})
                cursor += dur
                trimmed_cursor += dur
                continue
            i0 = anchor(ws, part[1][0], part[1][1], "in")
            i1 = anchor(ws, part[2][0], part[2][1], "out")
            if i1 < i0:
                raise SystemExit(f"{p['id']}: конец раньше начала")
            s_in = ws[i0]["s"]
            gap_next = ws[i1 + 1]["s"] - ws[i1]["e"] if i1 + 1 < len(ws) else PAD
            s_out = ws[i1]["e"] + max(0.0, min(gap_next, PAD))
            seg = ws[i0:i1 + 1]
            sp = {}
            for w in seg:
                sp[w["sp"]] = sp.get(w["sp"], 0) + 1
            major = max(sp, key=sp.get)
            gaps = []
            for a, b in zip(seg, seg[1:]):
                g = b["s"] - a["e"]
                if g >= GAP_MIN:
                    gaps.append({"at": a["e"], "dur": round(g, 2), "after": a["w"]})
            trim = sum(g["dur"] - GAP_KEEP for g in gaps)
            ref_b = b_ref(ang, s_in, s_out)
            ref_a = None
            if s_out <= A_END + 0.05:
                fa_in, oa_in = clip_at(s_in)
                fa_out, oa_out = clip_at(min(s_out, A_END - 0.001))
                ref_a = {"file": fa_in, "off_in": round(oa_in, 3), "file_out": fa_out, "off_out": round(oa_out, 3)}
            angle = SPEAKER_ANGLE.get(major, "A")
            if ref_a is None:
                angle = "B"
            elif ref_b is None:
                angle = "A"
            if angle == "B" and ref_b is None:
                raise SystemExit(f"{p['id']}: кусок {tc(s_in)}–{tc(s_out)} вне обоих ракурсов")
            if angle == "A":
                f_in, o_in, f_out, o_out = ref_a["file"], ref_a["off_in"], ref_a["file_out"], ref_a["off_out"]
                crosses = [c[1] for c in CLIPS[1:] if s_in < c[1] < s_out]
            else:
                f_in, o_in, f_out, o_out = ref_b["file"], ref_b["off_in"], ref_b["file"], ref_b["off_out"]
                crosses = []
            # кусок на B через дыру записи A длиннее мастер-отрезка на эту дыру — считаем по B
            extra = ref_b["a_gap_inside"] if (angle == "B" and ref_b.get("a_gap_inside")) else 0.0
            dur = s_out - s_in + extra
            parts_out.append({
                "kind": "say", "src_in": round(s_in, 3), "src_out": round(s_out, 3),
                "dur": round(dur, 3), "dur_master": round(s_out - s_in, 3),
                "dst_in": round(cursor, 3), "dst_out": round(cursor + dur, 3),
                "file_in": f_in, "off_in": round(o_in, 3), "file_out": f_out, "off_out": round(o_out, 3),
                "crosses_clip": [round(c, 2) for c in crosses],
                "angle": angle, "camera": ANGLE_LABEL[angle], "speaker": major,
                "speaker_name": SPEAKER_NAME.get(major, major), "a": ref_a, "b": ref_b,
                "tail_only_b": ref_a is None,
                "words": len(seg), "first": " ".join(w["w"] for w in seg[:6]),
                "last": " ".join(w["w"] for w in seg[-5:]),
                "text": " ".join(w["w"] for w in seg),
                "gaps": gaps, "trim_est": round(trim, 2)})
            spoken_ranges.append((s_in, s_out, cursor, ref_b.get("a_gap_at") if extra else None, extra))
            cursor += dur
            trimmed_cursor += dur - trim
        gfx_out = []
        for gid, (hint, word) in p.get("gfx", []):
            i = anchor(ws, hint, word, "in")
            t_src = ws[i]["s"]
            dst = None
            for a, b, c0, gat, gex in spoken_ranges:
                if a - 0.01 <= t_src <= b + 0.01:
                    dst = c0 + (t_src - a) + (gex if gat is not None and t_src >= gat else 0.0)
                    break
            kind, title, place = GFX[gid]
            gfx_out.append({"id": gid, "src": round(t_src, 3), "dst": round(dst, 3) if dst is not None else None,
                            "on_word": ws[i]["w"], "kind": kind, "title": title, "place": place})
        for part in parts_out:
            if part["kind"] == "gfx":
                kind, title, place = GFX[part["ref"]]
                gfx_out.append({"id": part["ref"], "src": None, "dst": round(part["dst_in"], 3),
                                "on_word": None, "kind": kind, "title": title, "place": place,
                                "insert": part["dur"]})
        gfx_out.sort(key=lambda g: g["dst"] if g["dst"] is not None else 1e9)
        pieces_out.append({**{k: v for k, v in p.items() if k not in ("parts", "gfx")},
                           "dst_in": round(piece_start, 3), "dst_out": round(cursor, 3),
                           "dur": round(cursor - piece_start, 3),
                           "dur_trimmed": round(trimmed_cursor - piece_start_tr, 3),
                           "parts": parts_out, "gfx": gfx_out})

    if ERRORS:
        print("\n".join(ERRORS))
        raise SystemExit(f"{len(ERRORS)} якорей не найдено — поправить PIECES")
    total, total_tr = cursor, trimmed_cursor
    n_cuts =sum(1 for p in pieces_out for x in p["parts"] if x["kind"] == "say")
    n_gaps = sum(len(x.get("gaps", [])) for p in pieces_out for x in p["parts"])
    gfx_ids = sorted({g["id"] for p in pieces_out for g in p["gfx"]})
    data = {"total": round(total, 2), "total_trimmed": round(total_tr, 2),
            "source_total": A_END,
            "angles": {"A": {"label": ANGLE_LABEL["A"], "files": [c[0] for c in CLIPS], "end": A_END},
                       "B": ({**ang, "label": ANGLE_LABEL["B"]} if ang else None)},
            "pieces": pieces_out, "gfx_catalog": GFX,
            "gfx_used": gfx_ids, "n_say_parts": n_cuts, "n_gaps": n_gaps}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    for p in pieces_out:
        print(f"{p['id']} {tc(p['dst_in'], False)}–{tc(p['dst_out'], False)} "
              f"{p['dur']:5.1f}s → {p['dur_trimmed']:5.1f}s  [{p.get('act', '')}] {p['title']}")
        for x in p["parts"]:
            if x["kind"] == "say":
                flag = f"  ⚠ стык {x['crosses_clip']}" if x["crosses_clip"] else ""
                print(f"     {tc(x['src_in'])}–{tc(x['src_out'])} {x['camera']:<14} "
                      f"{x['file_in']}+{tc(x['off_in'])}  пауз {len(x['gaps'])}{flag}")
                print(f"        «{x['first']} … {x['last']}»")
            else:
                print(f"     [{x['kind']}] {x['ref']} {x['dur']} с")
        for g in p["gfx"]:
            print(f"     ▣ {g['id']} @ {tc(g['dst'], False) if g['dst'] is not None else '—'} "
                  f"на «{g['on_word'] or 'вставка'}» — {g['title']}")
    print(f"\nИТОГО: {tc(total, False)} до подрезки пауз · ~{tc(total_tr, False)} после "
          f"· склеек речи {n_cuts} · пауз ≥{GAP_MIN} с: {n_gaps} · экранов {len(gfx_ids)}")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
