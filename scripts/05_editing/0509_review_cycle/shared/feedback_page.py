#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feedback_page — HTML «Обратная связь по кату vN» продюсеру: один самодостаточный файл {CODE}_{cut}_feedback.html.

Зачем: Роман читает сверку с телефона (файл уходит в Telegram) и с ноутбука двойным щелчком. Поэтому всё внутри
файла: кадры — data-URI, стили — inline, скриптов нет, внешних адресов нет. Первый экран — ДЕЙСТВИЯ (что держит
выпуск), а не цифры; дальше Часть 1 (новое ТЗ) и Часть 2 (пункты прошлого ТЗ, проверенные по новому кату).

Страница НИЧЕГО не решает: статусы, секции, блокеры — из work/{cut}/feedback.json; порядок, лимиты строк, подписи
кадров и слова — из shared/feedback_view.py (общий слой с вкладкой дока). Здесь только разметка.

Визуальный язык — «бумага» YTCH12_v4_structure.html (фон #f6f5f2, одна колонка ≤760 px, карточка с кадром,
моноширинный таймкод .tcx, якорь .anc) + блоки .blk/.now/.do/.where из YTCH12_v4_TZ_editor.html. Тёмной темы нет:
color-scheme=light, чтобы встроенный браузер Telegram страницу не инвертировал.

Бюджет размера: кадры 560 px q68; не влезли в --max-kb — ОДНА запасная ступень (480 px, q60); не влезли и так —
отказ с кодом 2, файл не пишется (молча ужимать кадры дальше нельзя: на них читают титры).
Кадра нет на диске (не приехал с Memex) — карточка выходит без кадра, без ошибки; счётчик — в выводе.

usage:
  YTAI_CARD=<…/05_Review/review_card.json> python3 feedback_page.py [--max-kb 6000] [--send]
  python3 feedback_page.py --fb PATH [--root DIR_05_Review] [--card PATH] [--out PATH]      # без карточки фильма
  python3 feedback_page.py --selftest
--send — после сборки отправить файл в Telegram (phone_brief.send_telegram, личный чат Романа). В конвейере стадия
только собирает файл; отправка — отдельной командой после «ок».
"""
import argparse
import html
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import i18n  # noqa: E402
import feedback_view as V  # noqa: E402
from pravki_lib import CAT_ICON, CAT_RU, favicon_href, jpeg_data_uri  # noqa: E402

E = html.escape
FAVICON = '🔁'
STEPS = ((560, 68), (480, 60))            # основная ступень и единственная запасная
EAGER = 3                                 # первые N кадров грузятся сразу, остальные — lazy
BLOCKS = (('now', 'core.lbl_now'), ('do', 'core.lbl_do'), ('where', 'core.lbl_where'))
_TC_HEAD = re.compile(rf'^({V.TC})$')

# «бумага»: :root и блоки — из YTCH12_v4_TZ_editor.html, каркас — из YTCH12_v4_structure.html
CSS = """
:root{--bg:#f6f5f2;--fg:#1d1d1f;--mut:#6b6b70;--card:#fff;--line:#e3e1dc;--acc:#c0392b;--ok:#1e8449;
--now:#fdecea;--do:#e8f6ec;--where:#eaf2fb;--warn:#fff1dc;--warnline:#f3c47a}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:760px;margin:0 auto;padding:14px 14px 60px}
h1{font-size:24px;line-height:1.2;margin:10px 0 4px}
h2{font-size:19px;margin:34px 0 6px;padding-top:8px;border-top:2px solid var(--fg)}
h3{font-size:17px;line-height:1.3;margin:26px 0 8px}
h4{font:800 13px/1.3 inherit;letter-spacing:.05em;color:var(--mut);margin:20px 0 6px}
.cnt{color:var(--mut);font-weight:600}
.mut{color:var(--mut);font-size:14px}
a{color:inherit}
.box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:10px 0}
.box ul{margin:4px 0;padding-left:20px}.box li{margin:3px 0;font-size:15px}
.warnbox{background:var(--warn);border:1px solid var(--warnline);border-radius:10px;padding:8px 12px;margin:10px 0;font-weight:700;font-size:14px}
.tally{font:700 17px/1.4 inherit;margin:14px 0 10px}
.lh{font-weight:800;margin:14px 0 4px}
ol.hold{margin:4px 0 8px;padding:0;list-style:none}
ol.hold li{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--acc);border-radius:10px;margin:5px 0}
ol.hold a{display:block;padding:8px 12px;text-decoration:none}
nav.chips{display:flex;flex-wrap:wrap;gap:6px;margin:16px 0 0}
nav.chips a{font:600 13px/1 inherit;padding:7px 10px;border-radius:999px;border:1px solid var(--line);background:var(--card);text-decoration:none}
.tcx{font:700 15px ui-monospace,Menlo,monospace}
.ch{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:12px 0;overflow:hidden;scroll-margin-top:10px}
.ch.red{border-left:6px solid var(--acc)}
.ch .imgs{background:#000}.ch .imgs img{width:100%;display:block}
.ch .in{padding:10px 12px}
.cap{font-size:12px;color:#9a9a9a;padding:2px 12px 0}
.no{font:800 13px/1.3 inherit;letter-spacing:.05em;color:var(--acc)}
.no .cat{color:var(--mut);font-weight:600;letter-spacing:0;margin-left:6px}
.t{font:800 19px/1.25 inherit;margin:3px 0}
.anc{background:var(--where);border-radius:8px;padding:6px 9px;margin:6px 0;font-size:15px}
.typo{margin:6px 0;font-size:16px}
.was{color:var(--acc);font-weight:800;text-decoration:none}
.fix{color:var(--ok);font-weight:800}
.blk{display:grid;grid-template-columns:108px 1fr;gap:8px;border-radius:8px;padding:6px 8px;margin:5px 0;font-size:15px}
.blk .lab{font:700 12px/1.6 inherit;white-space:nowrap}.blk p{margin:0 0 3px}.blk p:last-child{margin:0}
.now{background:var(--now)}.do{background:var(--do)}.where{background:var(--where)}
details{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:10px 0}
summary{font-weight:700;cursor:pointer}
.ch details{border:0;border-top:1px dashed var(--line);border-radius:0;padding:6px 0 0;margin:8px 0 0}
.ch summary,.moreline{font-weight:600;font-size:13px;color:var(--mut)}
.moreline{margin:8px 0 0}
.dup{background:var(--card);border:1px dashed var(--line);border-radius:10px;padding:8px 12px;margin:8px 0;font-size:15px;scroll-margin-top:10px}
.dup .num{color:var(--mut);font-size:13px;margin-left:6px}
.minis{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;margin:10px 0}
.mini{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:13px;line-height:1.35}
.mini img{width:100%;display:block;background:#000}.mini .in{padding:6px 8px}
.mini .tcx{font-size:13px}.mini .num{color:var(--mut);font-size:12px}.mini .mt{font-weight:700;margin:2px 0}.mini .ev{color:var(--mut)}
ul.lines{list-style:none;margin:6px 0 0;padding:0}
ul.lines li{padding:6px 0;border-top:1px solid var(--line);font-size:15px}
ul.lines li:first-child{border-top:0}
ul.lines .num{color:var(--mut);font-size:13px;margin-left:4px}
footer{margin-top:40px;color:var(--mut);font-size:13px}
@media(max-width:520px){.blk{grid-template-columns:1fr;gap:2px}.t{font-size:18px}}
"""


# ── кадры ────────────────────────────────────────────────────────────────────
class Frames:
    """data-URI кадров строки: путь из модели — от 05_Review. Нет файла / не читается → None (карточка без кадра)."""

    def __init__(self, root, width, quality):
        self.root, self.width, self.quality = (Path(root) if root else None), width, quality
        self.used = self.missing = self.bytes = 0
        self._cache = {}

    def uri(self, row, mini=False):
        f = (row.get('frame') or {}).get('file')
        if not f or self.root is None:
            return None
        p = Path(f) if os.path.isabs(f) else self.root / f
        w = self.width // 2 if mini else self.width            # мини-кадр в сетке 150–240 px: половины ширины хватает
        key = (str(p), w)
        if key not in self._cache:
            try:
                self._cache[key] = jpeg_data_uri(p, w, self.quality) if p.is_file() else None
            except Exception:                                  # битый файл — то же, что нет файла
                self._cache[key] = None
            if self._cache[key]:
                self.bytes += self._cache[key][1]
        got = self._cache[key]
        if got:
            self.used += 1
            return got[0]
        self.missing += 1
        return None

    def img(self, row, mini=False):
        u = self.uri(row, mini)
        if not u:
            return ''
        lazy = '' if self.used <= EAGER else ' loading="lazy"'
        return f'<img{lazy} src="{u}" alt="{E(V.caption(row))}">'


# ── кусочки разметки ─────────────────────────────────────────────────────────
def tc_line(text):
    """«11:16 ▸ что там» → таймкод моноширинным; прочее — как есть."""
    left, sep, right = str(text).partition(V.ARROW)
    if sep and _TC_HEAD.match(left.strip()):
        return f'<span class="tcx">{E(left.strip())}</span>{E(V.ARROW)}{E(right)}'
    return E(str(text))


def anchor_id(part, n):
    return f'p{part}-{n}'


def _cat(row):
    c = row.get('category') or ''
    word = CAT_RU.get(c, '') if i18n.LANG == 'ru' else c
    return f'<span class="cat">{E((CAT_ICON.get(c, "") + " " + word).strip())}</span>' if (word or CAT_ICON.get(c)) else ''


def _typo(row):
    pre, mid, post = i18n.T('core.was_pre'), i18n.T('core.was_mid'), i18n.T('core.was_post')
    return ''.join(f'<div class="typo">{E(pre)}<b class="was">{E(w)}</b>{E(mid)}<b class="fix">{E(n)}</b>{E(post)}</div>'
                   for w, n in V.typo_pairs(row))


def _evidence(row):
    ev = row.get('evidence') or {}
    if not ev.get('text'):
        return ''
    # время доказательства печатаем, только если оно не то же, что у самой карточки (иначе один таймкод дважды подряд)
    same = lambda x: str(x or '').strip().lstrip('≈~')
    show = ev.get('tc') and same(ev['tc']) != same(row.get('tc_new'))
    tc = f'<span class="tcx">{E(str(ev["tc"]))}</span> ' if show else ''
    return f'<div class="anc">{tc}{E(ev["text"])}</div>'


def _blk(key, label_key, lines):
    if not lines:
        return ''
    ps = ''.join(f'<p>{tc_line(x)}</p>' for x in lines)
    return f'<div class="blk {key}"><div class="lab">{E(i18n.T(label_key))}</div><div>{ps}</div></div>'


def card(row, fr, fb):
    """полная карточка: кадр, таймкод, номер (🔴 у блокера), заголовок, доказательство, блоки по лимитам, хвост — в <details>."""
    sb = V.short_blocks(row, fb)
    red = bool(row.get('blocker'))
    img = fr.img(row)
    h = [f'<article class="ch{" red" if red else ""}" id="{anchor_id(row.get("part"), row.get("n"))}">']
    if img:
        h.append(f'<div class="imgs">{img}</div><div class="cap">{E(V.caption(row))}</div>')
    h.append('<div class="in">')
    h.append(f'<div class="no">{"🔴 " if red else ""}{E(V.num_label(row, fb))}{_cat(row)}</div>')
    if row.get('tc_new'):
        h.append(f'<div class="tcx">{E(V.tc_label(row))}</div>')
    h.append(f'<div class="t">{E(row.get("title") or "")}</div>')
    h.append(_evidence(row))
    h.append(_typo(row))
    for key, label_key in BLOCKS:
        h.append(_blk(key, label_key, sb[key]))
    if sb['more_line'] and sb['rest']:
        inner = ''.join(_blk(k, lk, [x for kk, x in sb['rest'] if kk == k]) for k, lk in BLOCKS)   # одна метка на блок
        h.append(f'<details><summary>{E(sb["more_line"])}</summary>{inner}</details>')
    elif sb['more_line']:
        h.append(f'<div class="moreline">{E(sb["more_line"])}</div>')
    h.append('</div></article>')
    return ''.join(h)


def dup(row, fb):
    """пункт Части 2, переехавший в Часть 1: одна строка со ссылкой на новую карточку, без блока и кадра."""
    text = V.dup_line(row)
    label = i18n.tz_label(row.get('dup_of'))
    body = tc_line(text).replace(E(label), f'<a href="#{anchor_id(1, row.get("dup_of"))}">{E(label)}</a>', 1)
    return (f'<div class="dup" id="{anchor_id(2, row.get("n"))}">{body}'
            f'<span class="num">{E(V.num_label(row, fb))} · {E(row.get("title") or "")}</span></div>')


def mini(row, fr, fb):
    ev = (row.get('evidence') or {}).get('text') or ''
    ev = f'<div class="ev">{E(ev)}</div>' if ev else ''
    tc = f'<span class="tcx">{E(V.tc_label(row))}</span> ' if row.get('tc_new') else ''
    return (f'<div class="mini" id="{anchor_id(2, row.get("n"))}">{fr.img(row, mini=True)}<div class="in">{tc}'
            f'<span class="num">{E(V.num_label(row, fb))}</span><div class="mt">{E(row.get("title") or "")}</div>{ev}</div></div>')


def lines(rows, fb):
    li = ''.join(f'<li id="{anchor_id(2, r.get("n"))}">{tc_line(V.list_line(r))}<span class="num">{E(V.num_label(r, fb))}</span></li>'
                 for r in rows)
    return f'<ul class="lines">{li}</ul>'


def by_chapter(rows, chapters, ch_name):
    """→ [(подзаголовок|None, rows)] по главам фильма (chapters + ch_name карточки); пункты без времени — первой группой."""
    if not chapters:
        return [(None, rows)]
    chapters = sorted((int(t), str(n)) for t, n in chapters)
    groups, order = {}, []
    for r in rows:
        s = r.get('sec_new')
        if s is None:
            k = ''
        else:
            k = chapters[0][1]
            for t, n in chapters:
                if float(s) >= t:
                    k = n
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(r)
    out = []
    for k in order:
        if k == '':
            title = i18n.T('fb.no_tc_group')
        else:
            num = str(int(k)) if k.isdigit() else k
            name = (ch_name or {}).get(k, '')
            title = f'{i18n.T("core.chapter")} {num}' + (f' · {name}' if name else '')
        out.append((title, groups[k]))
    return out


# ── страница ─────────────────────────────────────────────────────────────────
def _head_html(fb, tz_tab):
    items = V.blocker_items(fb)
    h, i, how = [], 0, []
    in_list = False
    for kind, text in V.head(fb, surface='html', tz_tab=tz_tab):
        if kind != 'list_item' and in_list:
            h.append('</ol>')
            in_list = False
        if kind == 'h1':
            h.append(f'<h1>{E(text)}</h1>')
        elif kind == 'meta':
            h.append(f'<div class="mut">{E(text)}</div>')
        elif kind == 'warn':
            h.append(f'<div class="warnbox">{E(text)}</div>')
        elif kind == 'tally':
            h.append(f'<div class="tally">{E(text)}</div>')
        elif kind == 'list_head':
            h.append(f'<div class="lh">{E(text)}</div>')
        elif kind == 'list_item':
            if not in_list:
                h.append('<ol class="hold">')
                in_list = True
            it = items[i] if i < len(items) else {}
            i += 1
            h.append(f'<li><a href="#{anchor_id(it.get("part"), it.get("n"))}">{tc_line(text)}</a></li>')
        elif kind == 'how':
            how.append(text)
    if in_list:
        h.append('</ol>')
    if how:
        h.append(f'<div class="box"><b>{E(how[0])}</b><ul>' + ''.join(f'<li>{E(x)}</li>' for x in how[1:]) + '</ul></div>')
    return ''.join(h)


def build(fb, root=None, chapters=None, ch_name=None, width=STEPS[0][0], quality=STEPS[0][1], tz_tab=None):
    """→ (html, stats). root — папка 05_Review (от неё пути кадров); None → страница без кадров.
    chapters / ch_name — главы карточки для подзаголовков «Осталось»."""
    fr = Frames(root, width, quality)
    ver, prev = fb.get('cut_version', ''), fb.get('prev_cut_version', '')
    secs = V.sections(fb)
    body = [_head_html(fb, tz_tab)]
    summary = V.clean_summary(fb)                             # строки со словами движка не печатаем (они видны в lint)
    if summary:
        body.append(f'<div class="box"><b>{E(i18n.T("fb.verdict_head"))}</b><ul>'
                    + ''.join(f'<li>{E(x)}</li>' for x in summary) + '</ul></div>')
    body.append('<nav class="chips">' + ''.join(
        f'<a href="#sec-{b}">{E(i18n.T(f"fb.nav.{b}"))} <span class="cnt">{len(rows)}</span></a>' for b, _, rows in secs) + '</nav>')
    cards = 0
    part2_open = False
    for b, label, rows in secs:
        cnt = f' <span class="cnt">· {len(rows)}</span>'
        if b == 'new':
            body.append(f'<h2 id="sec-{b}">{E(label)}{cnt}</h2>')
        else:
            if not part2_open:
                body.append(f'<h2>{E(i18n.T("fb.part2", prev=prev))}</h2><div class="mut">{E(i18n.T("fb.part2_sub"))}</div>')
                part2_open = True
            body.append(f'<h3 id="sec-{b}">{E(label)}{cnt}</h3>')
        if b in ('new', 'block', 'open', 'blur'):
            groups = by_chapter(rows, chapters, ch_name) if b == 'open' else [(None, rows)]
            for title, grp in groups:
                if title:
                    body.append(f'<h4>{E(title)} <span class="cnt">· {len(grp)}</span></h4>')
                for r in grp:
                    if b != 'new' and r.get('dup_of') is not None:
                        body.append(dup(r, fb))
                    else:
                        body.append(card(r, fr, fb))
                        cards += 1
        elif b == 'closed':
            body.append('<div class="minis">' + ''.join(mini(r, fr, fb) for r in rows) + '</div>')
        elif b == 'fund':
            for _, title, grp in V.fund_groups(rows, fb):
                body.append(f'<details open><summary>{E(title)} <span class="cnt">· {len(grp)}</span></summary>'
                            f'{lines(grp, fb)}</details>')
        elif b == 'appendix':
            body.append(f'<details><summary>{E(i18n.T("fb.show_list"))} <span class="cnt">· {len(rows)}</span></summary>'
                        f'{lines(rows, fb)}</details>')
    meta = next((t for k, t in V.head(fb, surface='html', tz_tab=tz_tab) if k == 'meta'), '')
    body.append(f'<footer>{E(fb.get("code", ""))} · {E(meta)}</footer>')
    page = ('<!doctype html><html lang="' + i18n.LANG + '"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light">'
            f'<title>{E(i18n.T("fb.page_title", code=fb.get("code", ""), ver=ver))}</title>'
            f'<link rel="icon" href="{favicon_href(FAVICON)}"><style>{CSS}</style></head><body><main>'
            + ''.join(body) + '</main></body></html>')
    stats = {'kb': round(len(page.encode('utf-8')) / 1024), 'width': width, 'quality': quality, 'cards': cards,
             'frames': fr.used, 'frames_missing': fr.missing, 'frames_kb': round(fr.bytes / 1024),
             'rows': len(fb.get('part1') or []) + len(fb.get('part2') or [])}
    return page, stats


class TooBig(Exception):
    pass


def build_in_budget(fb, max_kb, **kw):
    """основная ступень → одна запасная → TooBig. Ниже 480 px титры на кадрах уже не читаются — дальше не ужимаем."""
    stats = {}
    for w, q in STEPS:
        page, stats = build(fb, width=w, quality=q, **kw)
        if stats['kb'] <= max_kb:
            return page, stats
    raise TooBig(i18n.T('fb.too_big', kb=stats['kb'], max_kb=max_kb))


def visible_text(page):
    """текст, который видит читатель: без стилей, тегов и data-URI (для самопроверки на жаргон)."""
    s = re.sub(r'<style>.*?</style>', ' ', page, flags=re.S)
    s = re.sub(r'<[^>]+>', ' ', s)
    return html.unescape(s)


def _card(path=None):
    """карточка фильма «налегке» (только главы и папка 05_Review): без proj_config, чтобы страница собиралась
    и из одного feedback.json."""
    p = path or os.environ.get('YTAI_CARD')
    if not p or not Path(p).expanduser().is_file():
        return {}, None
    p = Path(p).expanduser()
    try:
        return json.loads(p.read_text(encoding='utf-8')), p.parent
    except Exception:
        return {}, p.parent


# ── самопроверка ─────────────────────────────────────────────────────────────
def selftest():
    import tempfile
    from PIL import Image
    old = i18n.set_lang('ru')
    try:
        tmp_obj = tempfile.TemporaryDirectory(prefix='feedback_page_selftest_')   # шумовые кадры ~1 МБ каждый — не копим
        tmp = Path(tmp_obj.name)
        fb = V._synthetic()
        (tmp / 'work/v5/hires').mkdir(parents=True)
        rows = fb['part1'] + fb['part2']
        for r in rows:
            if r.get('frame') and r['n'] != 11:                            # у ТЗ-11 кадра на диске нет
                Image.effect_noise((1280, 720), 60).convert('RGB').save(tmp / r['frame']['file'], 'JPEG', quality=90)
        chapters, ch_name = [[0, '01'], [600, '02']], {'01': 'ТИЗЕР', '02': 'ДОМ'}
        page, st = build(fb, root=tmp, chapters=chapters, ch_name=ch_name)
        # кадры: 2 (Часть 1) + ТЗ-09 + 2 блюр + 2 мини; ТЗ-11 — нет файла; dup, фонд и приложение кадров не просят
        assert st['frames'] == 7 and st['frames_missing'] == 1, st
        assert not re.search(r'https?://', page), 'внешний адрес'
        assert '<script' not in page.lower() and ' onclick' not in page.lower()
        assert '<meta name="color-scheme" content="light">' in page and '<link rel="icon" href="data:image/svg+xml,' in page
        assert 'собрано 21.09.2026 22:40 · сборка 3' in page
        vis = visible_text(page)
        assert not any(rx.search(vis) for rx in V.JARGON), [rx.search(vis) for rx in V.JARGON]
        assert not re.search(r'\balign', re.sub(r'data:image/jpeg;base64,[A-Za-z0-9+/=]+', '', page)), 'слово движка в разметке'
        first = page.index('class="tally"'), page.index('<ol class="hold">'), page.index('Как читать')
        assert first == tuple(sorted(first)) and page.index('Как читать') < page.index('id="sec-new"')   # первый экран = действия
        for it in V.blocker_items(fb):                                     # ссылки шапки ведут на существующие карточки
            assert f'href="#{anchor_id(it["part"], it["n"])}"' in page and f'id="{anchor_id(it["part"], it["n"])}"' in page
        assert '<b class="was">ЖУМАГУЛ</b>' in page and '<b class="fix">ЖИМАГУЛ</b>' in page
        assert 'line-through' not in page and re.search(r'\.was\{[^}]*font-weight:800', CSS) and re.search(r'\.fix\{[^}]*font-weight:800', CSS)
        assert page.count('<article class="ch red"') == 2 and '🔴 ТЗ-01' in page and '🔴 ТЗ-09 · v4' in page
        assert 'id="p2-40"' in page and 'class="dup" id="p2-40"' in page and '<a href="#p1-2">ТЗ-02</a>' in page
        assert '<summary>ещё 9 строк — вкладка ТЗ v4, ТЗ-09</summary>' in page
        assert '<h4>БЕЗ ТАЙМКОДА <span class="cnt">· 1</span></h4>' in page and '<h4>ГЛАВА 2 · ДОМ <span class="cnt">· 1</span></h4>' in page
        assert page.count('<details open><summary>Тема') == 2
        assert '<h3 id="sec-appendix">Не проверено автоматически — смотрит Роман' in page and '<details><summary>показать список' in page
        assert page.count('class="mini"') == 2 and page.count('loading="lazy"') == st['frames'] - EAGER
        for pid in ('p2-12', 'p2-11'):                                     # без таймкода / без файла кадра — карточка без кадра
            i0 = page.index(f'id="{pid}"')
            assert '<div class="imgs">' not in page[i0:page.index('</article>', i0)]
        i9 = page.index('id="p2-9"')                                       # хвост: по ОДНОЙ метке на блок, не на строку
        tail = page[page.index('<details>', i9):page.index('</details>', i9)]
        assert tail.count('class="lab"') == 3 and tail.count('<p>') == 4, tail
        rough = V._synthetic()
        r11 = next(r for r in rough['part2'] if r['n'] == 11)
        r11.update(err=4.2, evidence={'tc': '≈15:00', 'text': 'реплика на месте'})
        rough['summary_lines'] = ['Кат стал плотнее.', 'правила листа нарушены: fund_entry_min']
        pr, _ = build(rough)
        c11 = pr[pr.index('id="p2-11"'):pr.index('</article>', pr.index('id="p2-11"'))]
        assert '<div class="tcx">≈15:00</div>' in c11 and c11.count('15:00') == 1, c11   # «≈» в шапке; время доказательства не дублируется
        assert 'Кат стал плотнее.' in pr and 'fund_entry_min' not in pr
        ids = re.findall(r' id="([^"]+)"', page)
        assert len(ids) == len(set(ids)) and set(re.findall(r'href="#([^"]+)"', page)) <= set(ids)   # якоря уникальны, ссылки не висят
        page0, st0 = build(fb)                                             # без папки кадров — страница всё равно собирается
        assert st0['frames'] == 0 and 'data:image/jpeg' not in page0
        only_new = dict(fb, part2=[], blockers=fb['blockers'][:1])
        p1, _ = build(only_new)
        assert 'ЧАСТЬ 2' not in p1 and 'Прошлого ТЗ для сверки нет' in p1

        assert STEPS == ((560, 68), (480, 60)), STEPS                      # основная + РОВНО одна запасная (задача, контракт)
        _, big = build(fb, root=tmp, width=560, quality=68)
        _, small = build(fb, root=tmp, width=480, quality=60)
        assert small['kb'] < big['kb'], (small, big)
        _, s1 = build_in_budget(fb, big['kb'], root=tmp)
        assert (s1['width'], s1['quality']) == STEPS[0]
        _, s2 = build_in_budget(fb, big['kb'] - 1, root=tmp)
        assert (s2['width'], s2['quality']) == STEPS[1], s2                # ровно одна запасная ступень
        try:
            build_in_budget(fb, small['kb'] - 1, root=tmp)
            raise AssertionError('бюджет не сработал')
        except TooBig as e:
            assert 'файл не записан' in str(e)

        i18n.set_lang('en')
        pe, _ = build(fb, root=tmp, chapters=chapters, ch_name=ch_name)
        assert 'PART 1 · NEW IN v5' in pe and 'FIX-09 · v4' in pe and 'Blocks release — editing:' in pe and '<html lang="en">' in pe
        tmp_obj.cleanup()
    finally:
        i18n.set_lang(old)
    print('SELFTEST OK')


# ── CLI ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description='HTML «Обратная связь по кату vN» — один самодостаточный файл')
    ap.add_argument('--fb', help='feedback.json (по умолчанию work/{cut}/feedback.json по карточке)')
    ap.add_argument('--out', help='куда писать (по умолчанию {05_Review}/{CODE}_{cut}_feedback.html)')
    ap.add_argument('--root', help='папка 05_Review — от неё пути кадров (по умолчанию папка карточки)')
    ap.add_argument('--card', help='review_card.json для глав (по умолчанию YTAI_CARD)')
    ap.add_argument('--max-kb', type=int, default=6000)
    ap.add_argument('--send', action='store_true', help='отправить готовый файл в Telegram (личный чат Романа)')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return 0

    card, card_dir = _card(a.card)
    if a.fb:
        fb_path = Path(a.fb).expanduser().resolve()
        root = Path(a.root).expanduser() if a.root else (card_dir or (fb_path.parents[2] if len(fb_path.parents) > 2 else fb_path.parent))
    else:                                                     # штатный путь стадии: всё по карточке фильма
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import proj_config as P
        fb_path = P.WORK / 'feedback.json'
        root = Path(a.root).expanduser() if a.root else P.REVIEW_DIR
        card = {k: card.get(k) or P.get(k) for k in ('chapters', 'ch_name', 'tab_title')}   # P.get знает и окружение
    fb = V.load(fb_path)
    out = Path(a.out).expanduser() if a.out else root / f'{fb.get("code", "FILM")}_{fb.get("cut_version", "v1")}_feedback.html'

    try:
        page, st = build_in_budget(fb, a.max_kb, root=root, chapters=card.get('chapters'), ch_name=card.get('ch_name'),
                                   tz_tab=card.get('tab_title') or None)
    except TooBig as e:
        print(f'ОТКАЗ: {e}', file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding='utf-8')
    step = '' if (st['width'], st['quality']) == STEPS[0] else ' · запасная ступень'
    print(f'{out}\n{st["kb"]} КБ из {a.max_kb} · пунктов {st["rows"]} · карточек {st["cards"]} · кадров {st["frames"]} '
          f'({st["width"]} px q{st["quality"]}{step}) · без кадра на диске {st["frames_missing"]}')
    problems = V.lint(fb)
    for lvl, who, msg in problems:
        print(f'{lvl} {who}: {msg}')
    if a.send:
        from phone_brief import send_telegram                 # импорт здесь: phone_brief тянет карточку фильма
        cap = E(i18n.T('fb.send_caption', code=fb.get('code', ''), ver=fb.get('cut_version', ''), n=fb.get('build_no', 1)))
        mid = send_telegram(out, cap)                         # без chat — личный чат Романа по умолчанию
        print(f'Telegram: отправлено, message_id={mid}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
