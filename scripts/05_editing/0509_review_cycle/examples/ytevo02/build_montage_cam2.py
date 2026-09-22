#!/usr/bin/env python3
"""build_montage_cam2.py — монтажный лист ВТОРОЙ сцены: «Эволюция ТВ» (C0014+C0015).

Съёмка 04.09.2026, 12:37:12–12:45:09, одна непрерывная запись 7:57, два ракурса:
  A — Sony A7 III, крупный план Дарьи (C0014+C0015 встык — мастер-ось времени);
  B — Blackmagic ProRes UHD, общий план: Михаил слева, Дарья справа (A004_11201148_C013.mov,
      пришёл 15.09.2026; синхрон по звуку — 05_Review/angles.json, off = мастер − offset).
Михаил — генеральный продюсер «Эволюция ТВ»: в крупном плане его нет, его реплики — ракурс B.
Пересечения текста с манифестом нет ни на одну фразу: это отдельный материал про запуск вещания.

Схема данных и правила те же, что в build_montage.py: границы кусков привязаны к
пословным таймкодам через якоря «подсказка + слово», tc_out = конец последнего слова
плюс до 0,3 с воздуха, паузы ≥0,7 с считаются отдельно.

  python3 build_montage_cam2.py     → montage_cam2.json + таблица
"""
import json
import re
from pathlib import Path

BASE = Path("/Volumes/T9-Black-RYA/YTEVO/YTEVO02_evolution_manifesto/00_Setup")
WORDS = BASE / "YTEVO02cam2.words.json"
OUT = BASE / "montage_cam2.json"

CLIPS = [("C0014.MP4", 0.0, 342.72), ("C0015.MP4", 342.72, 477.12)]
A_END = CLIPS[-1][2]
ANGLES = BASE / "05_Review" / "angles.json"
ANGLE_LABEL = {"A": "A · крупный · Дарья", "B": "B · общий · Михаил и Дарья"}
SPEAKER_ANGLE = {"Speaker 1": "A", "Speaker 2": "B"}
SPEAKER_NAME = {"Speaker 1": "Дарья", "Speaker 2": "Михаил"}
GAP_MIN, GAP_KEEP, PAD = 0.7, 0.35, 0.3


def m(mm, ss):
    return mm * 60 + ss


PIECES = [
    dict(id="S01", title="«Время пришло» — представляем «Эволюция ТВ»", act="Новость",
         parts=[("say", (m(1, 27.28), "друзья"), (m(1, 42.0), "россию"))],
         gfx=[("G24", (m(1, 37.5), "увидела"))],
         note="Самая чистая формулировка всей съёмки — сильнее, чем анонс в манифесте на 16:21. "
              "Ставится первой репликой сцены."),
    dict(id="S02", title="Заставка «ЭВОЛЮЦИЯ ТВ»", act="Новость",
         parts=[("gfx", "G12", 3.0)]),
    dict(id="S03", title="Генеральный продюсер: запуск вещания", act="Новость",
         parts=[("say", (m(0, 19.5), "друзья"), (m(0, 47.5), "детей"))],
         gfx=[("G21", (m(0, 19.5), "друзья")), ("G25", (m(0, 25.8), "федеральном"))],
         note="Первое появление Михаила. Служебная реплика до него (00:01 «Генеральный продюсер "
              "сейчас задаст вопрос») снята."),
    dict(id="S04", title="Кто такой Михаил", act="Новость",
         parts=[("say", (m(6, 57.5), "михаил"), (m(7, 7.2), "контента"))],
         note="Взято с 06:57 и переставлено сюда — представление должно идти сразу за первой "
              "репликой. Рыхлый хвост 07:07–07:34 («крысиное время», «анонимизированное решение») снят."),
    dict(id="S05", title="Что показываем: направления", act="Продукт",
         parts=[("say", (m(0, 47.6), "это"), (m(1, 24.8), "миру"))],
         gfx=[("G27", (m(0, 48.0), "проекты")), ("G08", (m(1, 5.5), "делателей"))],
         note="Перечисленные направления ложатся на шесть советов платформы: природоподобные "
              "технологии → НАУКА, оздоровительные концепции → ЖИЗНЬ, образовательные инициативы → "
              "БУДУЩЕЕ, ремесленники → ТРУД. Тот же экран G08, что и в манифесте, — связывает две сцены."),
    dict(id="S06", title="Почему сейчас: информация управляет миром", act="Зачем",
         parts=[("say", (m(1, 42.08), "и"), (m(2, 12.9), "коммуникации"))],
         note="⚠ Дублирует кусок 12 манифеста («информация управляет миром»). Если сцены сводятся "
              "в один ролик — этот кусок снять, он там уже есть."),
    dict(id="S07", title="Чем станет платформа", act="Продукт",
         parts=[("say", (m(2, 12.92), "поэтому"), (m(2, 53.74), "приглашаем"))],
         note="Ядро обещания: место, где рождаются новые герои, производства и решения."),
    dict(id="S08", title="«Приглашаем к соучастию»", act="Призыв",
         parts=[("say", (m(2, 54.58), "приглашаем"), (m(2, 58.12), "сотворчеству"))],
         gfx=[("G29", (m(2, 55.2), "соучастию"))],
         note="Три с половиной секунды, но это лучшая короткая реплика Михаила — оставить целиком."),
    dict(id="S09", title="Математическая модель платформы", act="Продукт",
         parts=[("say", (m(4, 51.8), "немаловажно"), (m(5, 25.56), "проект"))],
         gfx=[("G22", (m(4, 54.0), "математическая"))],
         note="Новый факт, которого нет в манифесте. Вводное «Да,» снято — оно отвечало на "
              "вырезанное обсуждение 04:30–04:50 («нужно ли говорить про технологии»)."),
    dict(id="S10", title="Агрегатор смысла: 24/7 и федеральный канал", act="Продукт",
         parts=[("say", (m(5, 26.98), "и"), (m(5, 54.94), "территории")),
                ("say", (m(6, 10.34), "ведь"), (m(6, 19.4), "лучше"))],
         note="Между кусками снято 05:55–06:10: там дважды тёмное место — «решении, которое будет "
              "в их тюрьме» и «пройти эти тюрьмы». Послушать ушами, распознаванию не верить."),
    dict(id="S11", title="Что дальше: автонарезка в рилсы", act="Продукт",
         parts=[("say", (m(6, 20.3), "и"), (m(6, 54.76), "ли"))],
         gfx=[("G23", (m(6, 25.0), "преобразование"))],
         note="Второй новый факт. В речи «хайлайцы» — на экране писать «хайлайты»."),
    dict(id="S12", title="ПРИЗЫВ: если вы производитель контента", act="Призыв",
         parts=[("say", (m(3, 0.34), "и"), (m(4, 2.6), "перспективным"))],
         gfx=[("G30", (m(3, 5.5), "производитель")), ("G20", (m(3, 26.5), "свяжитесь"))],
         note="Самый операционный кусок сцены: кто нужен, что присылать, куда писать. "
              "В субтитрах править «вдохновлены смотром в будущее» → «смотреть в будущее»."),
    dict(id="S13", title="Финал: «Россия — это ковчег»", act="Финал",
         parts=[("say", (m(4, 4.6), "мы"), (m(4, 30.24), "всех")),
                ("gfx", "G17", 5.0)],
         gfx=[("G31", (m(4, 11.5), "ковчег"))],
         note="«Россия — это ковчег, в котором мы все спасёмся» — дословно миссия с их сайта. "
              "Точка на «Ждём вас всех». Дальше только болтовня, в монтаж не идёт."),
]

GFX = {
    "G08": ("new", "Шесть советов — верные названия", "full"),
    "G12": ("new", "Заставка «ЭВОЛЮЦИЯ ТВ»", "full"),
    "G16": ("new", "Развилка: я снимаю / снимите меня", "full"),
    "G17": ("new", "Финал: «Зависит от нас» · эволюция.рус", "full"),
    "G20": ("new", "Плашка домена эволюция.рус", "lower-third"),
    "G21": ("new", "Плашка: Михаил — генеральный продюсер «Эволюция ТВ»", "lower-third"),
    "G22": ("new", "Математическая модель: человек ↔ человек, человек ↔ проект", "full"),
    "G23": ("new", "Что дальше: автонарезка в хайлайты и рилсы", "full"),
    "G24": ("new", "Цитата: «увидела своих героев»", "full"),
    "G25": ("new", "Что запускаем: стрим 24/7 → федеральный канал", "full"),
    "G27": ("new", "Что показываем: четыре направления", "full"),
    "G29": ("new", "Соучастие · Созидание · Сотворчество", "full"),
    "G30": ("new", "Что присылать и куда писать", "full"),
    "G31": ("new", "Цитата: «Россия — это ковчег»", "full"),
}

ERRORS = []


def to_sec(v):
    if isinstance(v, (int, float)):
        return float(v)
    p = str(v).split(":")
    return float(p[0]) * 60 + float(p[1]) if len(p) == 2 else float(p[0])


def norm(w):
    return re.sub(r"[^\w.]+", "", str(w).lower().replace("ё", "е")).strip(".")


def tc(t, ms=True):
    t = max(0.0, float(t))
    mm, ss = divmod(t, 60)
    return f"{int(mm):02d}:{ss:05.2f}" if ms else f"{int(mm):02d}:{int(ss):02d}"


def load_words():
    d = json.loads(WORDS.read_text(encoding="utf-8"))
    ws = [{"w": w["w"].strip(), "n": norm(w["w"]), "s": to_sec(w["s"]), "e": to_sec(w["e"]),
           "sp": w.get("speaker") or seg.get("speaker")}
          for seg in d["segments"] for w in seg.get("words", [])]
    return sorted(ws, key=lambda x: x["s"])


def anchor(ws, hint, word, edge):
    key = "s" if edge == "in" else "e"
    cand = [i for i, w in enumerate(ws) if abs(w[key] - hint) < 6.0 and
            (word is None or w["n"] == norm(word) or w["n"].startswith(norm(word)))]
    if not cand:
        ERRORS.append(f"якорь не найден: {word!r} около {tc(hint)} ({edge})")
        return min(range(len(ws)), key=lambda i: abs(ws[i][key] - hint))
    return min(cand, key=lambda i: abs(ws[i][key] - hint))


def load_angle_b():
    if not ANGLES.exists():
        return None
    return json.loads(ANGLES.read_text(encoding="utf-8"))["scene2"]["angles"]["B"]


def seg_at(ang, t):
    segs = ang.get("segments") or [{"master_from": 0.0, "master_to": 1e9, "offset": ang["offset"],
                                    "rate": ang.get("rate", 1.0)}]
    for sg in segs:
        if sg["master_from"] - 1e-6 <= t <= sg["master_to"] + 1e-6:
            return sg
    return segs[-1] if t > segs[-1]["master_to"] else segs[0]


def b_ref(ang, t0, t1):
    if ang is None:
        return None
    s0, s1 = seg_at(ang, t0), seg_at(ang, t1)
    c0 = (t0 - s0["offset"]) / s0.get("rate", 1.0)
    c1 = (t1 - s1["offset"]) / s1.get("rate", 1.0)
    if c0 < 0 or c1 > ang["duration"]:
        return None
    ref = {"file": ang["file"], "off_in": round(c0, 3), "off_out": round(c1, 3)}
    if s0 is not s1:
        ref["a_gap_inside"] = round(s0["offset"] - s1["offset"], 3)
        ref["a_gap_at"] = s0["master_to"]
    return ref


def clip_at(t):
    for name, a, b in CLIPS:
        if a <= t < b:
            return name, t - a
    name, a, b = CLIPS[-1]
    return name, b - a


def main():
    ang = load_angle_b()
    ws = load_words()
    cursor = trimmed = 0.0
    out = []
    for p in PIECES:
        parts, p0, t0 = [], cursor, trimmed
        spoken = []
        for part in p["parts"]:
            if part[0] == "gfx":
                dur = float(part[2])
                parts.append({"kind": "gfx", "ref": part[1], "dur": dur,
                              "dst_in": round(cursor, 3), "dst_out": round(cursor + dur, 3)})
                cursor += dur
                trimmed += dur
                continue
            i0 = anchor(ws, part[1][0], part[1][1], "in")
            i1 = anchor(ws, part[2][0], part[2][1], "out")
            s_in = ws[i0]["s"]
            gap = ws[i1 + 1]["s"] - ws[i1]["e"] if i1 + 1 < len(ws) else PAD
            s_out = ws[i1]["e"] + max(0.0, min(gap, PAD))
            seg = ws[i0:i1 + 1]
            sp = {}
            for w in seg:
                sp[w["sp"]] = sp.get(w["sp"], 0) + 1
            major = max(sp, key=sp.get)
            gaps = [{"at": a["e"], "dur": round(b["s"] - a["e"], 2), "after": a["w"]}
                    for a, b in zip(seg, seg[1:]) if b["s"] - a["e"] >= GAP_MIN]
            trim = sum(g["dur"] - GAP_KEEP for g in gaps)
            fa_in, oa_in = clip_at(s_in)
            fa_out, oa_out = clip_at(s_out)
            ref_a = {"file": fa_in, "off_in": round(oa_in, 3), "file_out": fa_out, "off_out": round(oa_out, 3)}
            ref_b = b_ref(ang, s_in, s_out)
            angle = SPEAKER_ANGLE.get(major, "A") if ref_b else "A"
            if angle == "A":
                f_in, o_in, f_out, o_out = fa_in, oa_in, fa_out, oa_out
                crosses = [round(c[1], 2) for c in CLIPS[1:] if s_in < c[1] < s_out]
            else:
                f_in, o_in, f_out, o_out = ref_b["file"], ref_b["off_in"], ref_b["file"], ref_b["off_out"]
                crosses = []
            dur = s_out - s_in
            parts.append({"kind": "say", "src_in": round(s_in, 3), "src_out": round(s_out, 3),
                          "dur": round(dur, 3), "dst_in": round(cursor, 3), "dst_out": round(cursor + dur, 3),
                          "file_in": f_in, "off_in": round(o_in, 3), "file_out": f_out,
                          "off_out": round(o_out, 3),
                          "crosses_clip": crosses,
                          "angle": angle, "camera": ANGLE_LABEL[angle], "speaker": major,
                          "speaker_name": SPEAKER_NAME.get(major, major), "a": ref_a, "b": ref_b,
                          "words": len(seg),
                          "first": " ".join(w["w"] for w in seg[:6]),
                          "last": " ".join(w["w"] for w in seg[-5:]),
                          "text": " ".join(w["w"] for w in seg),
                          "gaps": gaps, "trim_est": round(trim, 2)})
            spoken.append((s_in, s_out, cursor))
            cursor += dur
            trimmed += dur - trim
        gfx = []
        for gid, (hint, word) in p.get("gfx", []):
            i = anchor(ws, hint, word, "in")
            t_src = ws[i]["s"]
            dst = next((c0 + (t_src - a) for a, b, c0 in spoken if a - 0.01 <= t_src <= b + 0.01), None)
            k, title, place = GFX[gid]
            gfx.append({"id": gid, "src": round(t_src, 3), "dst": round(dst, 3) if dst is not None else None,
                        "on_word": ws[i]["w"], "kind": k, "title": title, "place": place})
        for part in parts:
            if part["kind"] == "gfx":
                k, title, place = GFX[part["ref"]]
                gfx.append({"id": part["ref"], "src": None, "dst": round(part["dst_in"], 3),
                            "on_word": None, "kind": k, "title": title, "place": place, "insert": part["dur"]})
        gfx.sort(key=lambda g: g["dst"] if g["dst"] is not None else 1e9)
        out.append({**{k: v for k, v in p.items() if k not in ("parts", "gfx")},
                    "dst_in": round(p0, 3), "dst_out": round(cursor, 3), "dur": round(cursor - p0, 3),
                    "dur_trimmed": round(trimmed - t0, 3), "parts": parts, "gfx": gfx})
    if ERRORS:
        print("\n".join(ERRORS))
        raise SystemExit(f"{len(ERRORS)} якорей не найдено")
    n_say = sum(1 for p in out for x in p["parts"] if x["kind"] == "say")
    data = {"scene": "Эволюция ТВ · вторая сцена (C0014+C0015)", "total": round(cursor, 2),
            "total_trimmed": round(trimmed, 2), "source_total": A_END,
            "angles": {"A": {"label": ANGLE_LABEL["A"], "files": [c[0] for c in CLIPS], "end": A_END},
                       "B": ({**ang, "label": ANGLE_LABEL["B"]} if ang else None)},
            "pieces": out,
            "gfx_catalog": GFX, "gfx_used": sorted({g["id"] for p in out for g in p["gfx"]}),
            "n_say_parts": n_say,
            "n_gaps": sum(len(x.get("gaps", [])) for p in out for x in p["parts"])}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for p in out:
        print(f"{p['id']} {tc(p['dst_in'], False)}–{tc(p['dst_out'], False)} {p['dur']:5.1f}s "
              f"[{p.get('act', '')}] {p['title']}")
        for x in p["parts"]:
            if x["kind"] == "say":
                print(f"     {tc(x['src_in'])}–{tc(x['src_out'])} {x['camera']:<20} {x['file_in']}+{tc(x['off_in'])}")
            else:
                print(f"     [вставка] {x['ref']} {x['dur']} с")
        for g in p["gfx"]:
            print(f"     ▣ {g['id']} @ {tc(g['dst'], False)} на «{g['on_word'] or 'вставка'}»")
    print(f"\nИТОГО сцена 2: {tc(cursor, False)} · после подрезки ~{tc(trimmed, False)} · "
          f"склеек {n_say} · из 07:57 исходника")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
