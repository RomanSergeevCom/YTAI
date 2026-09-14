#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phone_brief — ОДИН лёгкий HTML-бриф по ревью ката, читаемый с телефона.

Канон (память feedback_phone_single_file_brief): ≤1 МБ, без JS, одна колонка, кадры маленькие
data-URI, списки — каждый пункт с новой строки, favicon inline-SVG. Первый слой для Романа:
«что обязательно, что убрать, что решить»; подробности — на странице продюсера и во вкладке дока.

usage:
  YTAI_CARD=<…/05_Review/review_card.json> python3 phone_brief.py [--send | --no-send] [--out path]
                                             [--max-kb 1000] [--img-width 480] [--quality 62]
→ {REVIEW_DIR}/{CODE}_{cut}_brief.html

Разделы: шапка (фильм · кат · дата · ссылки) → «Вердикт» (work/{cut}/producer_summary.json или авто)
→ «Обязательно» (severity high / класс fact·typo·mismatch: строка «ТЗ-NN · tc · заголовок», кадр,
строки ✅ СДЕЛАТЬ) → «Убрать / вырезать» (category cut) → «Решить Роману» (поле decision)
→ «Все ТЗ» (компакт, без картинок). Снятые Романом (status rejected) не показываются, ⚠️ = sensitive.

Размер держится в --max-kb: сначала падает качество/ширина JPEG, потом снимаются кадры с конца
списка «Обязательно». Итог печатается. --send → Telegram sendDocument в чат 155880671 с подписью
«{CODE} {cut} · бриф»; при успехе печатает «sent», при сбое — предупреждение (не роняет прогон).
"""
import argparse
import html
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'stages'))
from _bootstrap import P, W6, M, REVIEW_DIR, MOCK  # noqa: E402
from pravki_lib import (KIND_RU, CAT_RU, CAT_ICON, SEV_RANK, load_pravki, counts, verdict_lines,  # noqa: E402
                        load_summary, jpeg_data_uri, favicon_href, latest_review_json, sec_tc)

TG_CHAT = '155880671'
E = html.escape
FAVICON = '📱'


# ── Telegram ─────────────────────────────────────────────────────────────────
def _tg_token():
    for k in ('TG_BOT_TOKEN', 'TELEGRAM_BOT_TOKEN'):
        if os.environ.get(k, '').strip():
            return os.environ[k].strip()
    env = Path.home() / '.claude/channels/telegram-rya/.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if line.startswith('TELEGRAM_BOT_TOKEN='):
                return line.split('=', 1)[1].strip().strip('"\'')
    tok = Path.home() / '.config/rscore-tg/rya.token'
    if tok.exists():
        return tok.read_text(encoding='utf-8').strip()
    return ''


def send_telegram(path, caption, chat=TG_CHAT):
    """sendDocument через stdlib (multipart). → message_id. Исключение — если Telegram недоступен."""
    token = _tg_token()
    if not token:
        raise RuntimeError('токен бота не найден (TELEGRAM_BOT_TOKEN / rya.token)')
    boundary = '----ytai-phone-brief-7f3b91c4'
    parts = []
    for k, v in (('chat_id', chat), ('caption', caption), ('parse_mode', 'HTML')):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{Path(path).name}"\r\n'
                  'Content-Type: text/html\r\n\r\n').encode() + Path(path).read_bytes() + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    req = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendDocument', data=b''.join(parts))
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.load(r)
    if not resp.get('ok'):
        raise RuntimeError(str(resp.get('description', resp))[:200])
    return resp['result']['message_id']


# ── разметка ─────────────────────────────────────────────────────────────────
def css():
    st = {k: P.profile(f'style.{k}', d) for k, d in (('bg', '#101014'), ('ivory', '#F2EAD8'), ('red', '#C1272D'),
                                                       ('mut', '#CDC6B8'), ('font_stack', "Georgia,'Times New Roman',serif"))}
    return f"""
:root{{--bg:{st['bg']};--ink:{st['ivory']};--red:{st['red']};--mut:{st['mut']};--panel:#17171D;--line:#2B2B35;
--ok:#8BD48A;--amber:#E0B34A;--head:{st['font_stack']}}}
*{{box-sizing:border-box}}
html,body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;-webkit-text-size-adjust:100%}}
.wrap{{max-width:720px;margin:0 auto;padding:0 14px 60px}}
header{{padding:20px 0 8px}}
.tag{{display:inline-block;font-weight:800;font-size:12px;letter-spacing:.1em;color:#fff;background:var(--red);border-radius:6px;padding:3px 8px}}
h1{{font:700 23px/1.25 var(--head);margin:10px 0 6px}}
.sub{{color:var(--mut);font-size:14px;margin:0 0 8px}}
.links{{display:flex;flex-direction:column;gap:3px;font-size:14.5px}}
.links a{{color:var(--ink);text-decoration:underline;text-decoration-color:var(--line)}}
.links span{{color:var(--mut)}}
nav{{position:sticky;top:0;z-index:9;background:rgba(16,16,20,.94);backdrop-filter:blur(8px);display:flex;gap:6px;padding:10px 0;border-bottom:1px solid var(--line);margin-bottom:6px}}
nav a{{flex:1;text-align:center;text-decoration:none;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 2px;font-weight:700;font-size:13px}}
nav a small{{display:block;font-weight:500;color:var(--mut);font-size:11px}}
h2{{font:700 20px/1.3 var(--head);margin:30px 0 8px;scroll-margin-top:66px}}
h2 small{{color:var(--mut);font:500 13px/1 -apple-system,sans-serif;margin-left:8px}}
.box{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:8px 0}}
.box p{{margin:0}}
.v p{{margin:0 0 4px;padding-left:12px;text-indent:-12px}}
.v p::before{{content:'· ';color:var(--red)}}
.none{{color:var(--mut);font-style:italic}}
.mo{{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden;margin:12px 0}}
.mo img{{width:100%;display:block;background:#000}}
.mo .in{{padding:10px 14px 12px}}
.top{{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:4px}}
.tcb{{font-weight:800;font-size:13px;color:#fff;background:var(--red);border-radius:6px;padding:2px 8px;font-variant-numeric:tabular-nums}}
.num{{font-weight:800;font-size:13px;color:var(--mut)}}
.cls{{font-size:11.5px;font-weight:700;border-radius:6px;padding:2px 7px;background:rgba(224,179,74,.16);color:var(--amber)}}
.cls.c-fact,.cls.c-typo,.cls.c-mismatch{{background:rgba(193,39,45,.2);color:#F09A9E}}
.sev{{font-size:11px;border:1px solid currentColor;border-radius:999px;padding:0 7px;color:var(--mut)}}
.sev.s-high{{color:#F09A9E}}
.mo .t{{font-size:16.5px;font-weight:700;line-height:1.3;margin:4px 0 8px}}
.do{{background:rgba(139,212,138,.07);border:1px solid rgba(139,212,138,.3);border-radius:10px;padding:9px 12px;font-size:15px;line-height:1.5;margin:6px 0 0}}
.do b{{color:var(--ok)}}
details{{margin-top:6px}}
summary{{cursor:pointer;color:var(--mut);font-size:13.5px}}
.row{{display:grid;grid-template-columns:auto auto 1fr;gap:4px 10px;align-items:baseline;padding:7px 0;border-bottom:1px solid var(--line);font-size:14.5px}}
.row .n{{font-weight:800;color:var(--mut);font-size:13px;white-space:nowrap}}
.row .tc{{font-weight:800;color:var(--red);font-size:13.5px;white-space:nowrap;font-variant-numeric:tabular-nums}}
.row .tt{{font-weight:600}}
.row .cl{{grid-column:3;color:var(--mut);font-size:12.5px}}
.row.must .tt::before{{content:'● ';color:var(--red);font-size:10px;vertical-align:middle}}
.rm{{display:grid;grid-template-columns:auto 1fr;gap:4px 10px;background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--red);border-radius:12px;padding:10px 12px;margin:8px 0}}
.rm .tc{{font-weight:800;color:var(--red);font-size:14px;white-space:nowrap}}
.rm .w{{font-weight:600}}
.rm .h{{grid-column:2;color:var(--mut);font-size:14px}}
.dec{{border-left:3px solid var(--amber)}}
.dec b{{display:block;margin-bottom:2px;font-size:14px}}
.dec span{{color:var(--ink);font-size:15px}}
.fd{{color:var(--mut);font-size:13px;margin-top:40px;border-top:1px solid var(--line);padding-top:14px}}
"""


def link_rows():
    rows = []
    if P.DOC_ID:
        url = f'https://docs.google.com/document/d/{P.DOC_ID}/edit'
        tab = P.get('tab_title') or 'ТЗ монтажёру'
        rows.append(f'📄 <a href="{url}">док · вкладка «{E(tab)}»</a>')
        if P.get('nav_tab'):
            rows.append(f'🧭 <a href="{url}">док · вкладка «{E(P.get("nav_tab"))}»</a>')
    sheet = P.SHEET_URL or (f'https://docs.google.com/spreadsheets/d/{P.get("notes_sheet_id")}/edit'
                            if P.get('notes_sheet_id') else '')
    if sheet:
        rows.append(f'📋 <a href="{sheet}">лист ТЗ / заметок</a>')
    if P.MATERIALS_ID:
        rows.append(f'📁 <a href="https://drive.google.com/drive/folders/{P.MATERIALS_ID}">Drive · Review_materials</a>')
    if P.PROJECT_FOLDER_ID:
        rows.append(f'📁 <a href="https://drive.google.com/drive/folders/{P.PROJECT_FOLDER_ID}">Drive · папка проекта</a>')
    rj = latest_review_json(REVIEW_DIR, P.CODE)
    if rj:
        rows.append(f'🎬 ревью-таймлайн: <span>{E(rj)}</span> (05_Review, панель UXP → Review)')
    return rows


def cls_badge(p):
    c = p['class'] or 'other'
    return f'<span class="cls c-{E(c)}">{E(KIND_RU.get(c, c))}</span>'


def sev_badge(p):
    return f'<span class="sev s-{E(p["severity"])}">{E(p["severity"])}</span>' if p['severity'] else ''


def must_card(p, uri):
    o = [f'<div class="mo" id="{E(p["num"].lower().replace("тз-", "tz"))}">']
    if uri:
        o.append(f'<img src="{uri}" alt="кадр {E(sec_tc(p["_sec"]))}">')
    o.append('<div class="in">')
    o.append(f'<div class="top"><span class="tcb">{E(sec_tc(p["_sec"]))}</span><span class="num">{E(p["num"])}</span>'
             f'{cls_badge(p)}{sev_badge(p)}' + ('<span class="cls">⚠️ чувствительное</span>' if p['_sensitive'] else '') + '</div>')
    o.append(f'<div class="t">{E(p["_title"])}</div>')
    do = p['_do']
    if do:
        o.append(f'<div class="do"><b>✅ СДЕЛАТЬ</b> · {E(do[0])}</div>')
        if len(do) > 1:
            o.append(f'<details><summary>ещё {len(do) - 1}</summary>' +
                     ''.join(f'<div class="do">{E(x)}</div>' for x in do[1:]) + '</details>')
    else:
        o.append('<div class="do none">✅ СДЕЛАТЬ · см. полный текст ТЗ в доке</div>')
    o.append('</div></div>')
    return ''.join(o)


def build(pravki, img_width, quality, n_pics, cache):
    """→ (html, stats). n_pics — сколько карточек «Обязательно» с начала получают кадр."""
    act = [p for p in pravki if not p['_rejected']]
    must = [p for p in act if p['_must']]
    must.sort(key=lambda p: (SEV_RANK.get(p['severity'], 9), p['_sec']))
    cut = [p for p in act if p.get('category') == 'cut']
    dec = [p for p in act if str(p.get('decision') or '').strip()]
    summary = load_summary(W6)
    dur = P.get('duration_sec')
    vlines = verdict_lines(pravki, float(dur) if dur else None, summary)
    c = counts(pravki)
    n_img, img_bytes = 0, []

    o = ['<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         f'<title>{E(P.CODE)} {E(P.CUT_VERSION)} · бриф</title>',
         f'<link rel="icon" href="{favicon_href(FAVICON)}">',
         f'<style>{css()}</style></head><body><div class="wrap">']
    today = datetime.now().strftime('%d.%m.%Y')
    o.append(f'<header><span class="tag">{E(P.CODE)} · {E(P.CUT_VERSION)}</span>'
             f'<h1>{E(P.FILM or P.PROJECT_NAME)}</h1>'
             f'<p class="sub">Ревью ката {E(P.CUT_VERSION)} · {today}' + (f' · {E(sec_tc(dur))}' if dur else '') +
             f' · {E(P.CHANNEL)}</p>'
             '<div class="links">' + ''.join(f'<div>{r}</div>' for r in link_rows()) + '</div></header>')
    o.append('<nav>'
             f'<a href="#verdict">Вердикт</a>'
             f'<a href="#must">Обязательно<small>{len(must)}</small></a>'
             f'<a href="#cut">Убрать<small>{len(cut)}</small></a>'
             f'<a href="#decide">Решить<small>{len(dec)}</small></a>'
             f'<a href="#all">Все ТЗ<small>{len(act)}</small></a></nav>')

    # вердикт
    o.append('<h2 id="verdict">Вердикт</h2><div class="box v">')
    if summary and summary.get('verdict_short'):
        o.append(f'<p><b>{E(summary["verdict_short"])}</b></p>')
    o += [f'<p>{E(x)}</p>' for x in vlines]
    o.append('</div>')

    # обязательно
    o.append(f'<h2 id="must">Обязательно<small>{len(must)}</small></h2>')
    if not must:
        o.append('<div class="box none">Обязательных правок нет.</div>')
    for i, p in enumerate(must):
        uri = ''
        if i < n_pics and p['_frame']:
            key = (str(p['_frame']), img_width, quality)
            if key not in cache:
                try:
                    cache[key] = jpeg_data_uri(p['_frame'], img_width, quality)
                except Exception as ex:
                    print('!! кадр', p['_frame'].name, ex)
                    cache[key] = ('', 0)
            uri, nb = cache[key]
            if uri:
                n_img += 1
                img_bytes.append(nb)
        o.append(must_card(p, uri))

    # убрать
    o.append(f'<h2 id="cut">Убрать / вырезать<small>{len(cut)}</small></h2>')
    if not cut:
        o.append('<div class="box none">Вырезать ничего не предложено.</div>')
    for p in cut:
        rng = p.get('tc_range') or sec_tc(p['_sec'])
        o.append(f'<div class="rm"><div class="tc">{E(rng)}</div><div class="w">{E(p["num"])} · {E(p["_title"])}</div>'
                 + (f'<div class="h">{E(p["_do"][0])}</div>' if p['_do'] else '') + '</div>')

    # решить
    o.append(f'<h2 id="decide">Решить Роману<small>{len(dec)}</small></h2>')
    if summary and summary.get('decisions'):
        for d in summary['decisions']:
            o.append(f'<div class="box dec"><span>{E(str(d))}</span></div>')
    if not dec and not (summary and summary.get('decisions')):
        o.append('<div class="box none">Открытых вопросов нет.</div>')
    for p in dec:
        o.append(f'<div class="box dec"><b>{E(p["num"])} · {E(sec_tc(p["_sec"]))} · {E(p["_title"])}</b>'
                 f'<span>❓ {E(str(p["decision"]).strip())}</span></div>')

    # все ТЗ
    o.append(f'<h2 id="all">Все ТЗ<small>{len(act)}' + (f' · снято {c["n_rejected"]}' if c['n_rejected'] else '') + '</small></h2>')
    for p in act:
        cl = KIND_RU.get(p['class'] or 'other', p['class'])
        cat = CAT_ICON.get(p.get('category'), '') + ' ' + CAT_RU.get(p.get('category'), p.get('category') or '')
        o.append(f'<div class="row{" must" if p["_must"] else ""}"><span class="n">{E(p["num"])}</span>'
                 f'<span class="tc">{E(sec_tc(p["_sec"]))}</span>'
                 f'<span class="tt">{"⚠️ " if p["_sensitive"] else ""}{E(p["_title"])}</span>'
                 f'<span class="cl">{E(cl)} · {E(cat.strip())}' + (f' · {E(p["severity"])}' if p['severity'] else '') + '</span></div>')

    o.append(f'<div class="fd">Собрано {datetime.now().strftime("%d.%m.%Y %H:%M")} · phone_brief.py · '
             f'подробности — страница продюсера {E(P.CODE)}_{E(P.CUT_VERSION)}_review_producer.html и вкладка дока.</div>')
    o.append('</div></body></html>')
    page = ''.join(o)
    stats = {'must': len(must), 'cut': len(cut), 'decide': len(dec), 'all': len(act), 'verdict': len(vlines),
             'rejected': c['n_rejected'], 'imgs': n_img, 'img_max_kb': (max(img_bytes) // 1024 if img_bytes else 0)}
    return page, stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--send', action='store_true', help='отправить файл в Telegram (чат 155880671)')
    ap.add_argument('--no-send', action='store_true', help='явно не отправлять (по умолчанию тоже не шлём)')
    ap.add_argument('--out', default=str(REVIEW_DIR / f'{P.CODE}_{P.CUT_VERSION}_brief.html'))
    ap.add_argument('--max-kb', type=int, default=1000)
    ap.add_argument('--img-width', type=int, default=480)
    ap.add_argument('--quality', type=int, default=62)
    a = ap.parse_args()

    pravki, src = load_pravki(P, W6, M, MOCK)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cache = {}
    n_must = sum(1 for p in pravki if p['_must'])
    plans = [(a.img_width, a.quality)]
    for w, q in ((a.img_width, 50), (min(a.img_width, 400), 45), (min(a.img_width, 320), 40), (min(a.img_width, 320), 32)):
        if (w, q) not in plans:
            plans.append((w, q))
    page = stats = None
    n_pics = n_must
    for w, q in plans:                      # 1) качество и ширина кадров
        page, stats = build(pravki, w, q, n_pics, cache)
        if len(page.encode('utf-8')) <= a.max_kb * 1024:
            break
    w, q = plans[-1]
    while len(page.encode('utf-8')) > a.max_kb * 1024 and n_pics > 0:   # 2) снимаем кадры с конца списка
        n_pics -= 1
        page, stats = build(pravki, w, q, n_pics, cache)
    out.write_text(page, encoding='utf-8')
    size_kb = out.stat().st_size / 1024
    print(f'→ {out}  ({size_kb:.0f} КБ, лимит {a.max_kb}) · вердикт {stats["verdict"]} строк · обязательно {stats["must"]} '
          f'(кадров {stats["imgs"]}, макс {stats["img_max_kb"]} КБ) · убрать {stats["cut"]} · решить {stats["decide"]} · '
          f'всего ТЗ {stats["all"]} (снято {stats["rejected"]}) · источник {src.name}')
    if size_kb > a.max_kb:
        print(f'⚠️ размер {size_kb:.0f} КБ больше лимита {a.max_kb} КБ даже без кадров — уменьши --max-kb или текст ТЗ')
    if a.send and not a.no_send:
        try:
            mid = send_telegram(out, f'<b>{P.CODE} {P.CUT_VERSION}</b> · бриф')
            print(f'sent → Telegram message_id {mid}')
        except Exception as ex:
            # слово «sent» в тексте предупреждения недопустимо — review.py ищет его как признак успеха
            err = str(ex).replace('sent', 's·e·n·t')
            print(f'⚠️ Telegram: не отправлено — {err}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
