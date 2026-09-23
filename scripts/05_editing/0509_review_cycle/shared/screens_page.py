#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Витрина экранов фильма — один самодостаточный HTML: виды экранов канала + все экраны на таймлайне.

Зачем. Роман 22.09.2026: «сделай дизайн глав и фраз и расположи их (экранов), экраны как здесь»
— и дал образцом библиотеку видов экранов YTUVIE (yt.rya.ae/ytuvie/s1/screens/). Оттуда взята
подача: у каждого вида имя, одна строка сути, пример на настоящем кадре с таймкодом и цитатой
речи, «когда применять / когда НЕ применять» и живое превью макета.

Две части:
  1. ВИДЫ ЭКРАНОВ КАНАЛА — редакторский текст из `shared/screen_kinds_{канал}.py` + канон из
     профиля канала (его меряет `shared/style_probe.py`) + макеты с диска;
  2. ЭКРАНЫ ФИЛЬМА — всё, что расставил `stages/screens_plan.py`: по главам, с таймкодом,
     длительностью, цитатой речи на этой секунде и кадром ката.

Правила файла (память `feedback_html_page_favicon`, `feedback_phone_single_file_brief`):
  · ноль внешних адресов — картинки inline base64, шрифты системные;
  · favicon — inline SVG-эмодзи;
  · в шапке номер версии и дата-время сборки;
  · бумага светлая, как у `shared/feedback_page.py`.

⚠️ На портал не выкладывается: в кадрах бывает человек, которого нельзя показывать по ссылке.
Файл открывается локально и уходит Роману в личный чат телеграма.

usage: screens_page.py [--out FILE] [--max-kb 6000] [--send]
"""
import argparse
import datetime
import html
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / 'shared', ROOT / 'stages', ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from pravki_lib import favicon_href, jpeg_data_uri  # noqa: E402

VERSION = 'v1'
E = html.escape

CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1a1a1a;--mut:#6b6b6b;--line:#e2e0da;--acc:#C1272D;--ok:#2f7d32}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:26px 18px 60px}
h1{font-size:30px;line-height:1.15;margin:0 0 6px}
h2{font-size:22px;margin:34px 0 10px;padding-top:16px;border-top:2px solid var(--line)}
.mut{color:var(--mut);font-size:14px}
.lede{font-size:17px;margin:10px 0 0;max-width:72ch}
.canons{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:12px;margin:14px 0 0}
.canon{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.canon b{display:block;margin-bottom:3px}
.canon span{color:var(--mut);font-size:14px}
.kind{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:14px 0}
.khd{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.kid{font:700 13px/1 ui-monospace,SFMono-Regular,Menlo,monospace;color:#fff;background:var(--acc);
     border-radius:6px;padding:5px 7px}
.knm{font-size:21px;font-weight:700}
.pill{font-size:12px;color:var(--mut);border:1px solid var(--line);border-radius:999px;padding:2px 9px}
.kone{margin:8px 0 12px;font-size:17px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:10px 26px;margin:10px 0 0}
@media(max-width:760px){.cols{grid-template-columns:1fr}}
.cols h4{margin:0 0 4px;font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut)}
.cols ul{margin:0;padding-left:18px}
.cols li{padding:1px 0}
.warn{color:var(--acc)}
.where{margin-top:12px;padding:10px 12px;background:#faf9f6;border-left:3px solid var(--line);
       border-radius:0 8px 8px 0;font-size:15px}
.exrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:12px 0 0}
.ex{border:1px solid var(--line);border-radius:10px;overflow:hidden;background:#fbfaf8}
.ex img{display:block;width:100%;height:auto}
.exm{padding:7px 10px;font-size:13px;color:var(--mut);border-top:1px solid var(--line)}
.exm b{color:var(--ink)}
.chosen{outline:2px solid var(--acc);outline-offset:-2px}
.chip{display:inline-block;font-size:12px;font-weight:700;color:#fff;background:var(--acc);
      border-radius:5px;padding:1px 6px;margin-left:6px}
.chip.off{background:var(--mut)}
table.plan{width:100%;border-collapse:collapse;margin:10px 0 0;background:var(--card)}
table.plan th{text-align:left;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);
              padding:7px 9px;border-bottom:2px solid var(--line)}
table.plan td{padding:9px;border-bottom:1px solid var(--line);vertical-align:top;font-size:15px}
table.plan tr.ch td{background:#f1efe9;font-weight:700}
td.tc{white-space:nowrap;font:600 14px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}
td.thumb{width:170px}
td.thumb img{display:block;width:100%;border-radius:6px;border:1px solid var(--line)}
.q{color:var(--mut);font-size:14px;font-style:italic;margin-top:3px}
.nopic{padding:10px;font-size:12px;color:var(--mut);background:#efede7;border-radius:6px;text-align:center}
.foot{margin-top:34px;color:var(--mut);font-size:13px;border-top:1px solid var(--line);padding-top:12px}
"""


def kinds_module(channel):
    """→ модуль текстов видов этого канала; нет такого — None (витрина соберётся без первой части)"""
    try:
        return importlib.import_module(f'screen_kinds_{str(channel).lower()}')
    except ImportError:
        return None


def quote_at(words, sec, limit=14, window=4.0):
    """→ что звучит на этой секунде: до limit слов; пусто — если рядом не говорят.

    ⚠️ Без окна это ловушка: в паузе (а экран часто и ставят в паузу) первое же слово «после»
    может звучать через минуту, и подпись «вот что здесь говорят» показывала бы речь из другого
    места фильма. Молчание честнее выдуманной цитаты."""
    out = []
    for w in words:
        if w['s'] >= sec - 0.2:
            if not out and w['s'] > sec + window:
                return ''
            out.append(w['w'])
            if len(out) >= limit:
                break
    return ' '.join(out).strip()


def load_words(path):
    try:
        d = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return [{'w': str(w.get('w', '')), 's': float(w.get('s', 0))}
            for s in (d.get('segments') or []) for w in (s.get('words') or [])]


def img(path, width, quality, budget):
    """→ (html-картинка или подпись вместо неё, потраченные байты).

    Пустая ячейка — худший вид молчания: читатель понимает её как «кадра для этого экрана нет»,
    хотя кадр есть и просто не влез. Поэтому оба отказа подписаны в самой витрине и посчитаны
    в бюджете, а `main()` печатает их и возвращает ненулевой код."""
    p = Path(path)
    if not p.is_file():
        budget['missing'].append(p.name or str(path))
        return '<div class="nopic">макета нет на диске</div>', 0
    if budget['left'] <= 0:
        budget['skipped'] += 1
        return '<div class="nopic">кадр не влез в размер файла</div>', 0
    uri, n = jpeg_data_uri(p, width, quality)
    budget['left'] -= n
    budget['put'] += 1
    return f'<img src="{uri}" alt="">', n


def tcf(sec):
    m, s = divmod(int(sec), 60)
    return f'{m}:{s:02d}'


def build(plan, card, kinds, mock_dir, hires, words, budget):
    ch_name = card.get('ch_name') or {}
    code, ver = plan.get('code', ''), plan.get('cut_version', '')
    n = {}
    for s in plan.get('screens', []):
        n[s['kind']] = n.get(s['kind'], 0) + 1
    built = datetime.datetime.now().strftime('%d.%m.%Y %H:%M')

    h = [f'<!doctype html><html lang="ru"><head><meta charset="utf-8">',
         f'<meta name="viewport" content="width=device-width,initial-scale=1">',
         f'<title>{E(code)} · экраны {E(ver)}</title>',
         f'<link rel="icon" href="{favicon_href("🎬")}">',
         f'<style>{CSS}</style></head><body><div class="wrap">']
    ed = getattr(kinds, 'EDITORIAL', {}) if kinds else {}
    h.append(f'<h1>{E(code)} · экраны ката {E(ver)}</h1>')
    h.append(f'<div class="mut">Витрина {VERSION} · собрана {built} · '
             f'{n.get("chapter", 0)} заставок глав · {n.get("sub", 0)} плашек подглав · '
             f'{n.get("claim", 0)} крупных фраз · всего {len(plan.get("screens", []))} экранов</div>')
    if ed.get('lede'):
        h.append(f'<p class="lede">{E(ed["lede"])}</p>')

    # ── 1. канон и виды ──
    if kinds:
        h.append(f'<h2>{E(ed.get("canon_head", "Канон канала"))}</h2>')
        if ed.get('canon_lede'):
            h.append(f'<div class="mut">{E(ed["canon_lede"])}</div>')
        h.append('<div class="canons">')
        for head_, why in ed.get('canons', []):
            h.append(f'<div class="canon"><b>{E(head_)}</b><span>{E(why)}</span></div>')
        h.append('</div>')

        h.append('<h2>Виды экранов канала</h2>')
        picked = str(card.get('ch_plate_variant', '') or '').lower()
        for letter, k in kinds.KIND.items():
            h.append('<div class="kind">')
            h.append(f'<div class="khd"><span class="kid">{E(letter)}</span>'
                     f'<span class="knm">{E(k["name"])}</span>'
                     f'<span class="pill">{"в фильме" if k.get("cat") == "F" else "в ревью"}</span></div>')
            h.append(f'<div class="kone">{E(k["one"])}</div>')
            h.append('<div class="cols"><div><h4>Когда применять</h4><ul>'
                     + ''.join(f'<li>{E(x)}</li>' for x in k.get('use', [])) + '</ul></div>')
            h.append('<div><h4>Когда НЕ применять</h4><ul>' + ''.join(
                f'<li>{E(c)}<span class="warn">{" → " + E(kinds.KIND[r]["name"]) if r else " → не ставим вовсе"}</span></li>'
                for c, r in k.get('avoid', [])) + '</ul></div></div>')
            vs = k.get('variants') or []
            if vs:
                h.append('<div class="exrow">')
                for v, nm, why, fname in vs:
                    tag, cls = ('ВЫБРАН', ' chosen') if v == picked else ('отклонён', '')
                    pic, _ = img(Path(mock_dir) / fname, 520, 66, budget)
                    h.append(f'<div class="ex{cls}">{pic}<div class="exm"><b>{E(nm)}</b>'
                             f'<span class="chip{"" if v == picked else " off"}">{tag}</span><br>{E(why)}</div></div>')
                h.append('</div>')
            else:
                ex = [s for s in plan.get('screens', []) if _kind_letter(s['kind']) == letter][:2]
                if ex:
                    h.append('<div class="exrow">')
                    for s in ex:
                        pic, _ = img(Path(mock_dir) / (s.get('mockup') or ''), 520, 66, budget)
                        q = quote_at(words, s['tc_in'])
                        h.append(f'<div class="ex">{pic}<div class="exm"><b>{E(s["tc"])}</b> · {E(s["text"][:60])}'
                                 + (f'<br>«{E(q)}…»' if q else '') + '</div></div>')
                    h.append('</div>')
            if k.get('where'):
                h.append(f'<div class="where">{E(k["where"])}</div>')
            h.append('</div>')

    # ── 2. экраны фильма ──
    h.append('<h2>Экраны фильма — где что стоит</h2>')
    h.append('<div class="mut">Таймкоды — по кату ' + E(ver) + '. Длительность — сколько экран висит. '
             'Кадр слева — то место ката, куда он встаёт.</div>')
    h.append('<table class="plan"><tr><th>Время</th><th>Кадр</th><th>Экран</th><th>Что на нём</th></tr>')
    cur = None
    for s in plan.get('screens', []):
        if s['chapter'] != cur:
            cur = s['chapter']
            h.append(f'<tr class="ch"><td class="tc">гл. {E(cur)}</td><td></td>'
                     f'<td colspan="2">{E(str(ch_name.get(cur, "")))}</td></tr>')
        frame = _frame_for(s, hires)
        pic, _ = img(frame, 300, 60, budget) if frame else ('<div class="nopic">кадра ката нет</div>', 0)
        q = quote_at(words, s['tc_in'])
        h.append(f'<tr><td class="tc">{E(s["tc"])}<br><span class="mut">+{s["dur"]} с</span></td>'
                 f'<td class="thumb">{pic}</td>'
                 f'<td>{E(_kind_ru(s["kind"]))}'
                 + ('' if s.get('on_screen') else '<br><span class="warn">в кате нет</span>') + '</td>'
                 f'<td>{E(s["text"])}' + (f'<div class="q">«{E(q)}…»</div>' if q else '') + '</td></tr>')
    h.append('</table>')
    h.append(f'<div class="foot">{E(code)} · кат {E(ver)} · витрина {VERSION} · {built}. '
             'Файл самодостаточный: ни одного внешнего адреса, все картинки внутри. '
             'На портал не выкладывается.</div>')
    h.append('</div></body></html>')
    return ''.join(h)


def _kind_letter(kind):
    return {'chapter': 'J', 'sub': 'C', 'claim': 'N', 'lower': 'L'}.get(kind, '')


def _kind_ru(kind):
    return {'chapter': 'Заставка главы', 'sub': 'Плашка подглавы',
            'claim': 'Крупная фраза', 'lower': 'Подпись человека'}.get(kind, kind)


def _frame_for(s, hires):
    """кадр ката на секунде экрана: кадр N — это секунда N−1, отсюда +1"""
    sec = int(float(s.get('tc_in', 0)))
    f = Path(hires) / f'h{sec + 1:04d}.jpg'
    return f if f.is_file() else None


def main():
    ap = argparse.ArgumentParser(description='витрина экранов фильма — один HTML')
    ap.add_argument('--out')
    ap.add_argument('--max-kb', type=int, default=6000)
    ap.add_argument('--send', action='store_true', help='отправить готовый файл в Telegram (личный чат Романа)')
    a = ap.parse_args()

    import proj_config as P
    plan_p = P.WORK / 'screens_plan.json'
    if not plan_p.exists():
        print(f'!! нет {plan_p} — сначала stages/screens_plan.py')
        return 1
    plan = json.loads(plan_p.read_text(encoding='utf-8'))
    card = {k: P.get(k) for k in ('ch_name', 'ch_plate_variant', 'channel')}
    kinds = kinds_module(P.get('channel', ''))
    if not kinds:
        print(f'⚠️ нет shared/screen_kinds_{str(P.get("channel", "")).lower()}.py — '
              'витрина будет без раздела «виды экранов»')
    words = load_words(P.WORDS)
    budget = {'left': a.max_kb * 1024 - 60 * 1024, 'put': 0, 'skipped': 0, 'missing': []}
    page = build(plan, card, kinds, P.MOCK, P.WORK / 'hires', words, budget)
    out = Path(a.out) if a.out else Path(P.REVIEW_DIR) / f'{P.CODE}_{P.CUT_VERSION}_screens.html'
    out.write_text(page, encoding='utf-8')
    kb = len(page.encode('utf-8')) // 1024
    ext = page.count('http://') + page.count('https://')
    miss = sorted(set(budget['missing']))
    print(f'{out}\n{kb} КБ из {a.max_kb} · экранов {len(plan.get("screens", []))} · '
          f'картинок вставлено {budget["put"]}'
          + (f' · не влезло по размеру {budget["skipped"]}' if budget['skipped'] else '')
          + (f' · нет файла ({len(miss)}): {", ".join(miss[:6])}' if miss else '')
          + f' · внешних адресов {ext} · favicon {"есть" if "rel=\"icon\"" in page else "НЕТ"}')
    if ext:
        print('⚠️ в файле есть внешние адреса — витрина обязана быть самодостаточной')
    if a.send:
        from phone_brief import send_telegram
        mid = send_telegram(out, f'{P.CODE} · экраны ката {P.CUT_VERSION} — виды экранов канала и где что стоит')
        print(f'отправлено в телеграм, message_id={mid}')
    return 2 if (ext or budget['skipped'] or miss) else 0


if __name__ == '__main__':
    sys.exit(main())
