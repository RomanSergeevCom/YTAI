#!/usr/bin/env python3
"""Rebuild the hand-maintained «Эпизоды» section of the YTAgeFree hub: clear production
statuses (done vs planned) + all links. Leaves the auto blocks (VIDEOS/PAGES) untouched."""
import re
HUB = "/Users/romansergeev/RYA/yt-rya-ae/web/ytagefree/index.html"
t = open(HUB, encoding="utf-8").read()

def card(nn, code, title, sub, state_cls, state_lbl, links):
    ll = "".join(links)
    return (f'    <article class="ep">\n'
            f'      <div class="ep-top"><span class="ep-id">{code}</span><span class="ep-state {state_cls}">{state_lbl}</span></div>\n'
            f'      <h3>{title}</h3>\n      <div class="sub">{sub}</div>\n'
            f'      <div class="ep-links">\n{ll}      </div>\n    </article>\n')

def L(href, label, kind="page", ext=False, disabled=False):
    if disabled:
        return f'        <a class="ep-link disabled">{label} <span class="k k-repo">—</span></a>\n'
    tgt = ' target="_blank" rel="noopener"' if ext else ' target="_blank"'
    kcls = {"page":"k-page","doc":"k-doc","pages":"k-pages","yt":"k-doc"}.get(kind,"k-page")
    return f'        <a class="ep-link" href="{href}"{tgt}>{label} <span class="k {kcls}">{kind}</span></a>\n'

GH = "https://romansergeevcom.github.io/YTAgeFree-S1/"
SHEET = "https://docs.google.com/spreadsheets/d/1a4pgTpFy9meyFtwT6svsv-Crokky79XdvFU701Ipiig/edit#gid=780090520"

sec = []
sec.append('  <div class="sec">Эпизоды — статус производства <span class="meta">план сборки → монтаж → публикация · клик по карточке открывает страницу</span></div>\n')
# legend
sec.append('  <div style="display:flex;gap:16px;flex-wrap:wrap;margin:0 0 18px;font-size:12px;color:var(--text-mute)">'
           '<span><b style="color:#86EFAC">● Опубликован</b> — вышел на YouTube</span>'
           '<span><b style="color:#C4B5FD">● В монтаже</b> — идёт сборка/премонтаж</span>'
           '<span><b style="color:#93C5FD">● План сборки готов</b> — ТЗ монтажёру готово, ждёт монтажа</span>'
           '<span><b style="color:#8A92A8">● Объединён</b> — слит с другим роликом</span></div>\n')

# ---- GROUP 1: published ----
sec.append('  <div class="tv-glabel" style="margin:6px 0 8px"><span class="tv-st s-pub">Опубликовано на YouTube</span><span class="c">4</span></div>\n')
sec.append('  <div class="eps">\n')
sec.append(card("07","YTAgeFree07","Помощь слабовидящему","Монтажный лист (вер. 2) · опубликован","es-live","Опубликован",
                [L("/ytagefree/07/","▶ Монтажный лист")]))
sec.append(card("09","YTAgeFree09","Ходунки-роллаторы","Монтажный лист (вер. 2) · 8:09 · опубликован","es-live","Опубликован",
                [L("/ytagefree/09/","▶ Монтажный лист")]))
sec.append(card("10","YTAgeFree10","Подбор трости","Монтажный лист (вер. 3) · 7:21 · опубликован","es-live","Опубликован",
                [L("/ytagefree/10/","▶ Монтажный лист"), L("/ytagefree/10/transcript.html","📝 Транскрипт","doc")]))
sec.append(card("11","YTAgeFree11","Статичные ходунки","12:11 · опубликован (страницы-разбора нет)","es-live","Опубликован",
                [L("","📁 SSD · local",disabled=True)]))
sec.append('  </div>\n')

# ---- GROUP 2: in production ----
sec.append('  <div class="tv-glabel" style="margin:22px 0 8px"><span class="tv-st s-editing">В производстве</span><span class="c">2</span></div>\n')
sec.append('  <div class="eps">\n')
sec.append(card("01","YTAgeFree01","Как накормить пожилого","Готов к публикации · план сборки + монтажный лист","es-review","Готов",
                [L("/ytagefree/01/","📋 План сборки"), L("/ytagefree/01/montage/","▶ Монтажный лист")]))
sec.append(card("02","YTAgeFree02","Контроль приёма лекарств","В монтаже · план + ТЗ-премонтаж + сборка v2","es-edit","В монтаже",
                [L("/ytagefree/02/","📋 План сборки"), L("/ytagefree/02/premontage/","🎬 ТЗ премонтаж"), L("/ytagefree/02/montage/","▶ Сборка v2")]))
sec.append('  </div>\n')

# ---- GROUP 3: plan ready (my v2 work) ----
sec.append('  <div class="tv-glabel" style="margin:22px 0 8px"><span class="tv-st s-script">План сборки готов · ждёт монтажа</span><span class="c">4</span>'
           '<span class="c" style="background:rgba(228,255,110,.10);color:#E4FF6E">дословные цитаты + сквозной хроно</span></div>\n')
sec.append('  <div class="eps">\n')
sec.append(card("03","YTAgeFree03","Выгорание ухаживающего","План сборки · дословные полные цитаты · хроно ≈8:00","es-pre","План готов",
                [L("/ytagefree/03/","📋 План сборки")]))
sec.append(card("04","YTAgeFree04","Как не срываться на близком","План сборки · дословные полные цитаты · хроно ≈8:53","es-pre","План готов",
                [L("/ytagefree/04/","📋 План сборки")]))
sec.append(card("05","YTAgeFree05","Безопасный дом: ванная и полы","План сборки · дословные цитаты · хроно ≈13:07 (длинный — под подрезку)","es-pre","План готов",
                [L("/ytagefree/05/","📋 План сборки")]))
sec.append(card("06","YTAgeFree06","Дом при деменции","План сборки · дословные цитаты · хроно ≈3:11 (ёмкий)","es-pre","План готов",
                [L("/ytagefree/06/","📋 План сборки")]))
sec.append('  </div>\n')

# ---- GROUP 4: other ----
sec.append('  <div class="tv-glabel" style="margin:22px 0 8px"><span class="tv-st s-source">Прочее</span></div>\n')
sec.append('  <div class="eps">\n')
sec.append(card("08","YTAgeFree08","Снижение слуха + умные краны","Объединён с другим роликом — отдельно не выпускается","es-shoot","Объединён",
                [L("","—",disabled=True)]))
sec.append(card("S1","Season 1","Сезон 1 — 11 роликов","01 Кормление · 02 Лекарства · 03 Выгорание · 04 Срывы · 05 Ванная · 06 Деменция · 07 Зрение · 08 Слух · 09 Ходунки · 10 Трость · 11 Статичные","es-edit","план",
                [L(GH,"📚 План сезона (repo)","pages",ext=True), L(SHEET,"📊 ContentList (Sheet)","doc",ext=True)]))
sec.append(card("S2","Season 2","Сезон 2 — тизер","В работе · сенсорная стимуляция при деменции и др.","es-shoot","teaser",
                [L("","📁 SSD · local",disabled=True)]))
sec.append('  </div>\n')

new_section = "".join(sec)

# replace from `<div class="sec">Эпизоды` up to just before `<div class="sec" style="margin-top:40px">Repos`
pat = re.compile(r'  <div class="sec">Эпизоды.*?(?=  <div class="sec" style="margin-top:40px">Repos)', re.S)
if not pat.search(t):
    print("ERR: section markers not found"); raise SystemExit(1)
t2 = pat.sub(new_section + "\n", t)

# add ContentList + board links to channel header (after starikam link) if not present
if "ContentList" not in t2.split("VIDEOS:START")[0]:
    t2 = t2.replace(
        '<a href="https://starikam.org" target="_blank" rel="noopener">🔗 starikam.org</a>',
        '<a href="https://starikam.org" target="_blank" rel="noopener">🔗 starikam.org</a>\n'
        f'        <a href="{SHEET}" target="_blank" rel="noopener">📊 ContentList</a>\n'
        '        <a href="https://trello.com/b/qDIWB2bi/ytagefree" target="_blank" rel="noopener">📋 Trello</a>', 1)

open(HUB, "w", encoding="utf-8").write(t2)
ncards = t2.count('article class="ep"')
print(f"hub rebuilt: {len(t)} -> {len(t2)} bytes; ep cards={ncards}")
