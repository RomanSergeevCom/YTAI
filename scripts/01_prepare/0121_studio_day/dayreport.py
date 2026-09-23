#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S9 · страница съёмочного дня: что снято, чем это доказано, что осталось.

Одна статическая страница, которую Роман открывает утром и за минуту понимает
состояние дня. Не отчёт о работе машины, а ответ на его вопросы: сколько сняли,
какие уроки закрыты, где привязка слабая, есть ли дыры в петличках, что ждёт
решения.

⚠️ Показываем и СОГЛАСИЕ, и РАСХОЖДЕНИЕ источников. Дубль, где выравнивание
последовательности и поодиночный счёт сошлись, и дубль, где они спорят, — это
разные вещи, и прятать второе за общим «готово» нельзя: именно там ошибка
привязки и живёт.

  python3 dayreport.py

Выход: {project}/00_Setup/{CODE}_day1.html
"""
from __future__ import annotations

import argparse
import html
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path.home() / "YTAI/scripts/13_preprod/shared"))
from common import dirs, load_day, load_json, log  # noqa: E402

try:
    from html_kit import page
    HAVE_KIT = True
except Exception:                                                  # noqa: BLE001
    HAVE_KIT = False

E = html.escape
CSS = """
.ok{color:#2E7D32;font-weight:700}.no{color:#C62828;font-weight:700}
.dim{color:var(--sec)}
table.t td,table.t th{font-size:12.5px;vertical-align:top}
td.n,th.n{font-family:'JetBrains Mono',monospace;white-space:nowrap}
td.r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.pill{display:inline-block;border-radius:999px;padding:1px 8px;font-size:11px;
  font-weight:700;white-space:nowrap}
.pv{background:#DCEFD8;color:#245C1B}.pb{background:#FFF0C7;color:#7A5A05}
.pu{background:#F6D9D9;color:#8C1F1F}.pj{background:var(--plate);color:var(--sec)}
.kw{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--sec)}
"""
PILL = {"proven": ("pv", "доказано"), "probable": ("pb", "вероятно"),
        "unmapped": ("pu", "не опознан"), "junk": ("pj", "обрывок"),
        "pending": ("pb", "не выровнен")}


def m(v, unit=""):
    return "—" if v in (None, "") else f"{v}{unit}"


def main():
    ap = argparse.ArgumentParser(description="страница съёмочного дня")
    ap.add_argument("--day", default=None)
    a = ap.parse_args()
    day = load_day(a.day)
    D = dirs(day)
    P = day["project"]

    idx = load_json(D["work"] / "index.json") or {}
    tm = load_json(P / "00_Setup/01_Ingest" / f"{day['code']}_day1_takemap.json") or {}
    gate = load_json(D["work"] / "days/full/Transcription/_wordsync/gate.json") or {}
    ws = load_json(D["work"] / "days/full/Transcription/_wordsync/wordsync_result.json") or {}
    sc = load_json(D["work"] / "screencasts.json") or {}
    tr = load_json(P / "01_Source/Transcription" / f"{day['code']}_day1_transcript.json") or {}
    lay = load_json(D["work"] / "layout.json") or {}
    pv = load_json(P / "00_Setup/logs" / f"{day['code']}_proxy_verify.json") or {}
    night = load_json(D["work"] / "night.json") or {}

    takes = tm.get("takes", [])
    lesson_ids = sorted({(t.get("lesson") or {}).get("id") for t in takes
                         if (t.get("lesson") or {}).get("id")}
                        | {i["lesson"] for i in sc.get("items", []) if i.get("lesson")})
    lessons_min = sum(t["duration"] for t in takes if not t.get("junk")) / 60
    st = {}
    for t in takes:
        st[t["status"]] = st.get(t["status"], 0) + 1

    b = [f'<p class=eyebrow>{E(day["code"])} · СЪЁМОЧНЫЙ ДЕНЬ {E(day["day"])} · '
         f'СОБРАНО {datetime.now():%d.%m.%Y %H:%M}</p>',
         "<h1>Что получилось за день</h1>"]

    # ── шапка
    b += ["<div class=grid>",
          f'<div class=kpi><b>{len(lesson_ids)}</b><span>уроков закрыто</span></div>',
          f'<div class=kpi><b>{len([t for t in takes if not t.get("junk")])}</b><span>дублей</span></div>',
          f'<div class=kpi><b>{lessons_min:.0f} мин</b><span>снято камерами</span></div>',
          f'<div class=kpi><b>{sum(i["dur"] for i in sc.get("items", []))/60:.0f} мин</b>'
          f'<span>скринкастов</span></div>',
          f'<div class=kpi><b>{tr.get("n_words", 0)}</b><span>слов в транскрипте</span></div>',
          f'<div class=kpi><b>{m(pv.get("n"))}</b><span>прокси собрано</span></div>',
          "</div>"]

    # ── что требует решения
    todo = []
    if (tm.get("warnings")):
        todo += [w for w in tm["warnings"] if "не опознан" in w.lower()]
    if gate.get("failures"):
        todo += [f"Гейт синхрона: {x}" for x in gate["failures"]]
    if gate.get("lav_gaps"):
        todo.append(f"Петлички не покрывают {len(gate['lav_gaps'])} мест — список ниже")
    prof = Path.home() / f"YTAI/YTs/{day['channel']}/color_profile.json"
    if not prof.exists():
        todo.append("Цвет: профиль канала ещё не рождён — нужен выбор в витрине "
                    "(проявка, покраска, экспозиция)")
    unplanned = [i for i in lesson_ids
                 if i not in {t.get("lesson", {}).get("id") for t in takes}]
    if todo:
        b.append('<div class=dark><p class=eyebrow>ЖДЁТ РЕШЕНИЯ</p><ul class=d>'
                 + "".join(f"<li>{E(x)}</li>" for x in todo) + "</ul></div>")

    # ── дубли
    b.append("<h2>Дубли и уроки</h2>")
    b.append('<p class=lead>Два независимых источника: выравнивание по порядку курса '
             'и поодиночный счёт по редким словам карточки. Где они сошлись — '
             '<b>доказано</b>; где спорят — смотреть глазами.</p>')
    b.append('<table class=t><tr><th class=n>№</th><th class=n>время</th><th class=r>мин</th>'
             '<th class=n>урок</th><th>название</th><th class=n>поодиночке</th>'
             '<th class=r>слов</th><th>статус</th></tr>')
    for t in takes:
        l, al = t.get("lesson") or {}, t.get("alone") or {}
        cls, lab = PILL.get(t["status"], ("pj", t["status"]))
        agree = l.get("agrees_with_alone")
        b.append(f'<tr><td class=n>{t["take"]}</td>'
                 f'<td class=n>{E(t["wall_start_local"][11:19])}</td>'
                 f'<td class=r>{t["duration"]/60:.1f}</td>'
                 f'<td class=n>{E(m(l.get("id")))}</td>'
                 f'<td>{E((l.get("title") or "")[:46])}</td>'
                 f'<td class=n>{"= " if agree else ""}{E(m(al.get("id")))}</td>'
                 f'<td class=r>{t["words"]["TX01"]}</td>'
                 f'<td><span class="pill {cls}">{lab}</span></td></tr>')
    b.append("</table>")

    # ── скринкасты
    if sc.get("items"):
        b.append("<h2>Скринкасты</h2>")
        b.append('<p class=lead>Имя файла — номер урока в схеме эксперта, с цифрой дня. '
                 'Это прямая привязка, её не надо доказывать словами.</p>')
        b.append('<table class=t><tr><th>файл</th><th class=n>услышан</th>'
                 '<th class=n>урок</th><th>название</th><th class=r>мин</th>'
                 '<th class=r>экранов</th><th>первый экран</th></tr>')
        for i in sc["items"]:
            s0 = (i.get("screens") or [{}])[0]
            cap = s0.get("caption") or ", ".join(s0.get("keywords", [])[:6])
            b.append(f'<tr><td>{E(i["file"])}</td><td class=n>{E(m(i.get("heard")))}</td>'
                     f'<td class=n>{E(m(i.get("lesson")))}</td>'
                     f'<td>{E((i.get("title") or "")[:40])}</td>'
                     f'<td class=r>{i["dur"]/60:.1f}</td>'
                     f'<td class=r>{len(i.get("screens") or [])}</td>'
                     f'<td class=kw>{E(cap[:90])}</td></tr>')
        b.append("</table>")

    # ── синхрон
    b.append("<h2>Синхрон</h2>")
    if ws.get("cameras"):
        b.append('<table class=t><tr><th class=n>камера</th><th class=r>Δ часов</th>'
                 '<th class=r>клипов</th><th class=r>по речи</th>'
                 '<th class=r>макс. остаток</th></tr>')
        for cam, c in ws["cameras"].items():
            b.append(f'<tr><td class=n>{E(cam)}</td><td class=r>{c["delta_sec"]:+.1f} с</td>'
                     f'<td class=r>{c["n_clips"]}</td><td class=r>{c["n_speech"]}</td>'
                     f'<td class=r>{c["resid_max_abs"]:.2f} с</td></tr>')
        b.append("</table>")
    for n in (gate.get("notes") or []):
        b.append(f'<p class=small>{E(n)}</p>')
    if gate.get("lav_gaps"):
        b.append('<p class=lead><b>Где петлички не покрыли дубль.</b> Считано из решённых '
                 'часов, а не из имён файлов — имена уже уличены в расхождении.</p>')
        b.append('<table class=t><tr><th class=n>клип</th><th class=n>дорожка</th>'
                 '<th class=r>не покрыто</th></tr>')
        for g in gate["lav_gaps"][:40]:
            b.append(f'<tr><td class=n>{E(g["clip"])}</td><td class=n>{E(g["tx"])}</td>'
                     f'<td class=r>{g["missing_sec"]:.0f} с</td></tr>')
        b.append("</table>")

    # ── транскрипт
    if tr:
        b.append("<h2>Транскрипт</h2>")
        who = {}
        for s in tr.get("segments", []):
            k = day["people"].get(s["tx"], {}).get("name", s["tx"])
            who[k] = who.get(k, 0) + len(s.get("words") or [])
        b.append("<ul class=d>" + "".join(
            f"<li>{E(k)} — {v} слов</li>" for k, v in sorted(who.items(), key=lambda x: -x[1]))
            + f"<li class=dim>проникание отсечено: {tr.get('segments_dropped_as_bleed', 0)} "
              f"сегментов, порог {tr.get('bleed_threshold_db')} дБ</li></ul>")
        b.append('<p class=small>Файлы: <span class=tc>'
                 f'{E(str(P / "01_Source/Transcription"))}</span></p>')

    # ── что где лежит
    b.append("<h2>Где что лежит</h2><ul class=d>")
    for label, pth in (("исходники (симлинки на карту)", P / "01_Source"),
                       ("прокси", P / "01_Source_Proxy"),
                       ("петлички, реальные копии", P / "99_Pipeline/DJI_Audio"),
                       ("карта дублей", P / "00_Setup/01_Ingest" / f"{day['code']}_day1_takemap.json"),
                       ("витрина лутов", P / "01_Source/00_LUT/_build"),
                       ("рабочее дерево дня", D["work"])):
        b.append(f'<li>{E(label)}: <span class=tc>{E(str(pth))}</span></li>')
    b.append("</ul>")

    if lay.get("counts"):
        b.append("<p class=small>Раскладка: " + " · ".join(
            f"{k} {v}" for k, v in lay["counts"].items()) + "</p>")
    if night.get("steps"):
        ok = [k for k, v in night["steps"].items() if v.get("rc") == 0]
        b.append(f'<p class=small class=dim>Ночь прошла шагов {len(ok)} из '
                 f'{len(night["steps"])}'
                 + (f", встала на <b>{E(night.get('stopped_at'))}</b>"
                    if night.get("stopped_at") else "") + "</p>")

    body = "".join(b)
    out = P / "00_Setup" / f"{day['code']}_day1.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    if HAVE_KIT:
        out.write_text(page(f"{day['code']} · съёмочный день {day['day']}", "🎬",
                            body, CSS), encoding="utf-8")
    else:
        out.write_text(f"<!DOCTYPE html><meta charset=utf-8><style>{CSS}</style>{body}",
                       encoding="utf-8")
    print(f"\n  уроков {len(lesson_ids)} · дублей {len(takes)} · "
          + " · ".join(f"{k} {v}" for k, v in sorted(st.items())))
    print(f"  → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
