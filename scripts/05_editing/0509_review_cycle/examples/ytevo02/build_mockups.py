#!/usr/bin/env python3
"""build_mockups.py — 4K-мокапы графики YTEVO02 в визуальном языке клиента.

Каждый экран: HTML (src/Gxx_V.html) → PNG 3840×2160 через infographic/render.py
(chrome-headless-shell). Язык снят с презентации клиента «Ценностный суверенитет России»:
Gilroy Black капсом, тёмно-синий #0B1220 / тёплый светлый #F0EFEA, красный #D0021B,
призрачные буквы, точки синий→красный, их логотип (вырезан из PDF на 600 dpi).

QC раскладки — локально, без облака: скрипт в странице после загрузки шрифтов ищет
текст за title-safe (5 %) и переполненные блоки и пишет отчёт в body[data-qc];
прогон chrome --dump-dom его читает.
Превью: плашки с альфой композитятся на реальный 4K-кадр съёмки — видно, как лягут
поверх Дарьи. Слайды клиента (указы, СССР, путь России) не перерисовываются —
берутся их же, отрендеренные из PDF в 4K.

  python3 build_mockups.py                 # все экраны
  python3 build_mockups.py --only G08,G14  # перерендер части (манифест собирается целиком)
"""
import argparse
import html as _html
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

BASE = Path("/Volumes/T9-Black-RYA/YTEVO/YTEVO02_evolution_manifesto/00_Setup")
MOCK = BASE / "05_Review" / "mockups"
SRC, THUMBS, CLIENT = MOCK / "src", MOCK / "thumbs", MOCK / "client_slides"
BG_FRAME = SRC / "t02m30_000s__C0005.jpg"
BG_OVERRIDE = {"G21": SRC / "bg_cam2.jpg"}   # плашка Михаила — на кадре второй сцены
FONTS = Path.home() / "Library" / "Fonts"
sys.path.insert(0, str(Path.home() / "YTAI/scripts/999_extra/infographic"))
from render import render, CHROME  # noqa: E402

W, H = 3840, 2160
NAVY, RED, RED_ON_DARK = "#0B1220", "#D0021B", "#FF4D5E"
PUNY_URL = "https://xn--b1amil5bzbkk.xn--p1acf/"   # эволюция.рус — камеры телефонов читают punycode надёжнее

COUNCILS = [("Труд", "ценностно-ориентированное предпринимательство"),
            ("Культура", "культурный код и смыслы"),
            ("Наука", "исследования и инновации"),
            ("Жизнь", "национальное здоровье и благополучие"),
            ("Среда", "развитие территорий и среды"),
            ("Будущее", "образование и духовно-нравственное воспитание")]

CLIENT_MAP = {"G06": ("s-03.jpg", "Слайд клиента: ст. 67.1 Конституции"),
              "G07a": ("s-12.jpg", "Слайд клиента: Указ №818"),
              "G07b": ("s-07.jpg", "Слайд клиента: Указ №809"),
              "G09": ("s-16.jpg", "Слайд клиента: СССР — три расшифровки"),
              "G15": ("s-14.jpg", "Слайд клиента: Путь России 2020→2036")}

BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:3840px;height:2160px;overflow:hidden}
body{font-family:GR,'Helvetica Neue',sans-serif;color:#fff;position:relative;-webkit-font-smoothing:antialiased}
body.dark{background:#0B1220}
body.light{background:#F0EFEA;color:#0B1220}
body.alpha{background:transparent}
.vig{position:absolute;inset:0;background:radial-gradient(ellipse 70% 60% at 30% 35%,rgba(44,62,143,.35),rgba(11,18,32,0) 70%),radial-gradient(ellipse at 50% 50%,rgba(0,0,0,0) 55%,rgba(0,0,0,.5) 100%)}
.ghost{position:absolute;font-family:GB;line-height:.78;letter-spacing:-.02em;color:rgba(255,255,255,.045);white-space:nowrap;text-transform:uppercase}
body.light .ghost{color:rgba(11,18,32,.05)}
.draft{position:absolute;right:60px;bottom:36px;font:30px GM;letter-spacing:.08em;color:rgba(255,255,255,.4)}
body.light .draft{color:rgba(11,18,32,.4)}
.logo{position:absolute;right:192px;top:130px;height:110px}
.over{font:600 52px GBo;letter-spacing:.16em;text-transform:uppercase;color:#D0021B}
body.dark .over{color:#FF4D5E}
.red{color:#D0021B}
.rule{width:180px;height:8px;background:#D0021B;margin:44px 0}
"""

QC_JS = """<script>
window.addEventListener('load',function(){document.fonts.ready.then(function(){
  var S=[192,108,3648,2052],out=[];
  document.querySelectorAll('.t,.box').forEach(function(el){
    var r=el.getBoundingClientRect(),n=el.getAttribute('data-n')||(el.textContent||el.tagName).trim().slice(0,22);
    if(r.width<1||r.height<1)return;
    if(r.left<S[0]-2||r.top<S[1]-2||r.right>S[2]+2||r.bottom>S[3]+2)
      out.push('за title-safe: '+n+' ['+[r.left,r.top,r.right,r.bottom].map(Math.round).join(',')+']');
    // у крупного текста при плотном интерлиньяже буквы выходят за строку — это задумано, не ошибка;
    // реальная беда — текст шире своего блока, а у карточек — содержимое выше карточки
    if(el.scrollWidth>el.clientWidth+4)out.push('шире блока: '+n);
    if(el.classList.contains('box')&&el.scrollHeight>el.clientHeight+4)out.push('не влезает по высоте: '+n);
  });
  document.body.setAttribute('data-qc',out.length?out.join(' | '):'ok');
});});
</script>"""

DRAFT = '<div class="draft">DRAFT · мокап R.Y.A — финал в стиле клиента</div>'


def font_face():
    faces = [("GB", "Gilroy-Black"), ("GX", "Gilroy-ExtraBold"), ("GBo", "Gilroy-Bold"),
             ("GM", "Gilroy-Medium"), ("GR", "Gilroy-Regular")]
    return "\n".join(f"@font-face{{font-family:{fam};src:url('{(FONTS / (f + '.ttf')).as_uri()}')}}"
                     for fam, f in faces)


def page(body, cls):
    return ("<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'><style>"
            + font_face() + BASE_CSS + "</style></head>"
            + f"<body class='{cls}'>" + body + DRAFT + QC_JS + "</body></html>")


# ---------------- элементы ----------------
def dots60(size, gap, ring="rgba(255,255,255,.5)", n_red=2, cols=10):
    cells = []
    for i in range(60):
        if i < n_red:
            cells.append(f'<i style="display:block;width:{size}px;height:{size}px;border-radius:50%;background:{RED}"></i>')
        else:
            cells.append(f'<i style="display:block;width:{size}px;height:{size}px;border-radius:50%;'
                         f'box-shadow:inset 0 0 0 {max(3, size // 16)}px {ring}"></i>')
    return (f'<div class="t" data-n="юнит-чарт" style="display:grid;grid-template-columns:repeat({cols},{size}px);'
            f'gap:{gap}px">' + "".join(cells) + "</div>")


def grad_dots(n=8):
    dots = "".join('<i style="position:relative;display:block;width:34px;height:34px;border-radius:50%;'
                   'background:linear-gradient(180deg,#3A4DB0,#E0506A)"></i>' for _ in range(n - 1))
    dots += (f'<i style="position:relative;display:block;width:56px;height:56px;border-radius:50%;'
             f'background:{RED};box-shadow:0 0 40px rgba(208,2,27,.55)"></i>')
    return ('<div style="display:inline-flex;align-items:center;gap:52px;position:relative">'
            '<div style="position:absolute;left:0;right:0;top:50%;height:4px;background:rgba(255,255,255,.2);'
            'transform:translateY(-50%)"></div>' + dots + '</div>')


def plate(inner, pos):
    return (f'<div class="box" data-n="плашка" style="position:absolute;{pos};display:flex;align-items:stretch;'
            f'border-radius:22px;overflow:hidden;background:rgba(11,18,32,.9);box-shadow:0 24px 70px rgba(0,0,0,.35)">'
            f'<div style="width:22px;background:{RED}"></div>{inner}</div>')


# ---------------- экраны ----------------
def g01a():
    return f'''
<div style="position:absolute;right:0;top:0;width:1760px;height:{H}px;background:linear-gradient(90deg,rgba(11,18,32,0) 0,rgba(11,18,32,.84) 16%,rgba(11,18,32,.92) 100%)"></div>
<div style="position:absolute;left:2300px;top:240px;width:1340px">
  <div class="over t" style="color:{RED_ON_DARK}">Опрос · около 60 подростков</div>
  <div class="t" style="font:150px GB;text-transform:uppercase;line-height:1;margin-top:30px">Кто ваши<br>герои?</div>
  <div style="margin-top:80px">{dots60(64, 28)}</div>
  <div style="display:flex;align-items:baseline;gap:36px;margin-top:70px">
    <div class="t" data-n="герой-цифра" style="font:360px GB;line-height:.8;color:{RED}">2</div>
    <div class="t" style="font:120px GB;line-height:1">из 60</div>
  </div>
  <div class="t" style="font:64px GM;line-height:1.3;margin-top:40px;color:#E6E9F2">назвали маму с папой.<br><span style="color:rgba(230,233,242,.62)">Остальные пожали плечами.</span></div>
</div>''', "alpha"


def g01b():
    return f'''
<img class="logo" src="logo_red.png">
<div style="position:absolute;left:192px;top:360px;width:1640px">
  <div class="over t">Опрос · около 60 подростков</div>
  <div class="t" style="font:210px GB;text-transform:uppercase;line-height:.98;margin-top:36px">Кто ваши<br>герои?</div>
  <div style="display:flex;align-items:baseline;gap:40px;margin-top:90px">
    <div class="t" data-n="герой-цифра" style="font:520px GB;line-height:.78;color:{RED}">2</div>
    <div class="t" style="font:170px GB;line-height:1">из 60</div>
  </div>
  <div class="t" style="font:70px GM;line-height:1.3;margin-top:50px">назвали маму с папой.<br><span style="opacity:.6">Остальные пожали плечами.</span></div>
</div>
<div style="position:absolute;left:2010px;top:560px">
  <div class="t" style="font:600 56px GBo;color:{RED};margin-bottom:44px">● 2 — мама с папой</div>
  {dots60(118, 44, ring="rgba(11,18,32,.38)")}
  <div class="t" style="font:600 56px GBo;color:rgba(11,18,32,.6);margin-top:44px">○ 58 — пожали плечами</div>
</div>''', "light"


def g02():
    return f'''
<div class="vig"></div>
<img class="t" data-n="логотип" src="logo_white.png" style="position:absolute;left:870px;top:720px;width:2100px">
<div class="t" style="position:absolute;left:192px;width:3456px;top:1240px;text-align:center;font:600 68px GBo;letter-spacing:.22em;text-transform:uppercase;color:#CDD3E0">Платформа объединения созидательных сил</div>
<div style="position:absolute;left:0;right:0;top:1460px;display:flex;justify-content:center">{grad_dots()}</div>
<div class="t" style="position:absolute;left:192px;width:3456px;top:1620px;text-align:center;font:64px GM;color:#AEB6C8">эволюция.рус</div>''', "dark"


def lower_third(name, role):
    inner = (f'<div style="padding:50px 90px 54px 70px">'
             f'<div class="t" style="font:112px GX;line-height:1;white-space:nowrap">{name}</div>'
             f'<div class="t" style="font:58px GM;color:#CDD3E0;margin-top:26px;white-space:nowrap">{role}</div></div>'
             f'<div style="display:flex;align-items:center;padding:0 80px;border-left:2px solid rgba(255,255,255,.12)">'
             f'<img src="logo_white.png" style="height:84px"></div>')
    return plate(inner, "left:192px;bottom:170px"), "alpha"


def g05():
    cols = [("Соединяем", "проекты, медиа, экспертов, предпринимателей и регионы"),
            ("Структурируем", "идеи — в рабочие форматы"),
            ("Продвигаем", "через реестр, медиа, события и партнёрства")]
    c = "".join(f'<div class="box" style="width:1020px"><div class="t" style="font:76px GB;text-transform:uppercase;'
                f'color:{RED}">{h}</div><div class="rule"></div><div class="t" style="font:64px GM;line-height:1.3">'
                f'{d}</div></div>' for h, d in cols)
    return f'''
<img class="logo" src="logo_red.png">
<div style="position:absolute;left:192px;top:300px;width:3000px">
  <div class="over t">Автономная некоммерческая организация</div>
  <div class="t" style="font:170px GB;text-transform:uppercase;line-height:.98;margin-top:40px">Центр развития<br>социальных проектов<br><span class="red">«Эволюция»</span></div>
</div>
<div style="position:absolute;left:192px;top:1320px;display:flex;gap:180px">{c}</div>
<div class="t" style="position:absolute;left:192px;top:1920px;font:50px GM;opacity:.6">ИНН 9734003957 · эволюция.рус</div>''', "light"


def g08a():
    cards = "".join(
        f'<div class="box" data-n="совет {n}" style="width:1080px;height:590px;padding:56px 64px;border-radius:28px;'
        f'background:rgba(255,255,255,.045);border:2px solid rgba(255,255,255,.1);display:flex;flex-direction:column;overflow:hidden">'
        f'<div class="t" style="font:70px GB;color:{RED_ON_DARK}">{i + 1:02d}</div>'
        f'<div class="t" style="font:130px GB;text-transform:uppercase;line-height:1;margin-top:24px">{n}</div>'
        f'<div class="t" style="font:50px GM;line-height:1.3;color:#CDD3E0;margin-top:30px">{d}</div></div>'
        for i, (n, d) in enumerate(COUNCILS))
    return f'''
<div class="vig"></div>
<img class="logo" src="logo_white.png">
<div style="position:absolute;left:192px;top:220px">
  <div class="over t">Платформа эволюция.рус</div>
  <div class="t" style="font:190px GB;text-transform:uppercase;line-height:1;margin-top:30px">Шесть советов</div>
</div>
<div style="position:absolute;left:192px;top:720px;display:grid;grid-template-columns:repeat(3,1080px);column-gap:108px;row-gap:70px">{cards}</div>''', "dark"


def g08b():
    cx, cy, R = 1920, 1300, 700
    angs = [-60, 0, 60, 120, 180, 240]
    svg, labels = [], []
    for (name, desc), a in zip(COUNCILS, angs):
        x, y = cx + R * math.cos(math.radians(a)), cy + R * math.sin(math.radians(a))
        svg.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.0f}" y2="{y:.0f}" stroke="rgba(11,18,32,.18)" stroke-width="4"/>')
        svg.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="34" fill="{RED}"/>')
        right = math.cos(math.radians(a)) > 0.01
        lx, al = (x + 70, "left") if right else (x - 770, "right")
        labels.append(f'<div class="t" data-n="{name}" style="position:absolute;left:{lx:.0f}px;top:{y - 95:.0f}px;'
                      f'width:700px;text-align:{al}"><div style="font:96px GB;text-transform:uppercase;line-height:1">'
                      f'{name}</div><div style="font:44px GM;line-height:1.3;margin-top:14px;opacity:.72">{desc}</div></div>')
    ring = (f'<svg width="{W}" height="{H}" style="position:absolute;left:0;top:0">'
            f'<circle cx="{cx}" cy="{cy}" r="{R}" fill="none" stroke="rgba(11,18,32,.12)" stroke-width="3" '
            f'stroke-dasharray="14 18"/>' + "".join(svg) + '</svg>')
    center = (f'<div class="t" data-n="центр" style="position:absolute;left:{cx - 260}px;top:{cy - 260}px;width:520px;'
              f'height:520px;border-radius:50%;background:{NAVY};color:#fff;display:flex;flex-direction:column;'
              f'align-items:center;justify-content:center"><div style="font:600 40px GBo;letter-spacing:.16em;'
              f'color:{RED_ON_DARK};text-transform:uppercase">в центре</div><div style="font:92px GB;'
              f'text-transform:uppercase;margin-top:14px">Человек</div></div>')
    title = ('<div style="position:absolute;left:192px;top:200px"><div class="over t">Платформа эволюция.рус</div>'
             '<div class="t" style="font:150px GB;text-transform:uppercase;line-height:1;margin-top:26px">'
             'Шесть советов</div></div>')
    return '<img class="logo" src="logo_red.png">' + title + ring + center + "".join(labels), "light"


def council_title(num, name, desc, extra):
    inner = (f'<div style="padding:46px 90px 52px 70px">'
             f'<div class="t" style="font:600 48px GBo;letter-spacing:.16em;text-transform:uppercase;color:{RED_ON_DARK}">Совет {num}</div>'
             f'<div class="t" style="font:150px GB;text-transform:uppercase;line-height:1;margin-top:18px">{name}</div>'
             f'<div class="t" style="font:58px GM;color:#E6E9F2;margin-top:24px;white-space:nowrap">{desc}</div>'
             f'<div class="t" style="font:46px GM;color:#AEB6C8;margin-top:14px;white-space:nowrap">{extra}</div></div>')
    return plate(inner, "left:192px;top:150px"), "alpha"


def g12():
    return f'''
<div class="vig"></div>
<div class="ghost" style="font-size:1800px;right:-100px;top:200px">ТВ</div>
<img class="logo" src="logo_white.png">
<div style="position:absolute;left:192px;top:600px">
  <div class="over t">Запускаем медиаплатформу</div>
  <div class="t" style="font:300px GB;text-transform:uppercase;line-height:.9;margin-top:40px;white-space:nowrap">Эволюция <span class="red">ТВ</span></div>
  <div class="t" style="font:600 76px GBo;margin-top:70px;color:#E6E9F2">Показать миру настоящую Россию — и её героев</div>
  <div style="margin-top:90px">{grad_dots()}</div>
  <div class="t" style="font:54px GM;color:#AEB6C8;margin-top:60px">Вещание 24/7 · реестр производителей контента</div>
</div>''', "dark"


def g13():
    rows = [("Кто он", .62), ("Как обратиться", .48), ("Наработки", .7),
            ("Чем может поделиться", .55), ("Что ему нужно", .5), ("Чем помочь друг другу", .66)]
    r = "".join(f'<div style="display:flex;align-items:center;gap:40px;padding:30px 0;border-top:2px solid rgba(11,18,32,.08)">'
                f'<div class="t" style="font:600 50px GBo;width:620px">{lab}</div>'
                f'<div style="height:30px;border-radius:15px;background:rgba(11,18,32,.1);width:{int(700 * f)}px"></div></div>'
                for lab, f in rows)
    return f'''
<img class="logo" src="logo_red.png">
<div style="position:absolute;left:192px;top:170px">
  <div class="over t">Эволюция ТВ · как устроено</div>
  <div class="t" style="font:150px GB;text-transform:uppercase;line-height:1;margin-top:26px">Не просто видео</div>
</div>
<div class="box" data-n="видео" style="position:absolute;left:192px;top:560px;width:1860px;height:1046px;border-radius:36px;overflow:hidden;background:linear-gradient(135deg,#1B2A55,#0B1220 60%,#3A0D16)">
  <div class="t" style="position:absolute;left:60px;top:56px;font:600 40px GBo;letter-spacing:.14em;padding:14px 26px;border-radius:12px;background:rgba(208,2,27,.9);text-transform:uppercase;color:#fff">Эволюция ТВ</div>
  <div style="position:absolute;left:840px;top:408px;width:0;height:0;border-left:200px solid rgba(255,255,255,.85);border-top:115px solid transparent;border-bottom:115px solid transparent"></div>
  <div style="position:absolute;left:0;right:0;bottom:0;padding:44px 60px;background:linear-gradient(0deg,rgba(0,0,0,.6),transparent)"><div class="t" style="font:600 56px GBo;color:#fff">Название проекта</div><div class="t" style="font:44px GM;color:#CDD3E0;margin-top:10px">Имя автора · регион</div></div>
</div>
<div class="box" data-n="карточка человека" style="position:absolute;left:2150px;top:560px;width:1498px;height:1300px;border-radius:36px;background:#fff;box-shadow:0 30px 80px rgba(11,18,32,.12);padding:64px 70px;overflow:hidden">
  <div class="t" style="font:600 48px GBo;letter-spacing:.14em;text-transform:uppercase;color:{RED}">За этим видео — человек</div>
  <div style="display:flex;align-items:center;gap:36px;margin:40px 0 34px"><div style="width:150px;height:150px;border-radius:50%;background:linear-gradient(135deg,#C9CEDA,#E7E9EF)"></div><div><div style="height:40px;width:520px;border-radius:20px;background:rgba(11,18,32,.18)"></div><div style="height:28px;width:340px;border-radius:14px;background:rgba(11,18,32,.1);margin-top:18px"></div></div></div>
  {r}
</div>
<div class="t" style="position:absolute;left:192px;top:1700px;width:1860px;font:46px GM;line-height:1.35;opacity:.62">Концепт по описанию из видео: под роликом — карточка автора, его наработки и потребности. Не реальный экран платформы.</div>''', "light"


def g14a():
    letters = [("Э", 1), ("В", 1), ("О", 0), ("Л", 1), ("Ю", 1), ("Ц", 1), ("И", 0), ("Я", 1)]
    word = "".join(f'<span style="color:{"#fff" if on else "rgba(255,255,255,.16)"}">{ch}</span>' for ch, on in letters)
    cols = [("Эва", ["развитие", "расширение", "раскрытие"]), ("Лю", ["люди", "любовь"]),
            ("Ц", ["циркуляция", "энергия", "сама жизнь"]), ("Я", ["частица творца", "ответственность", "сознание"])]
    c = "".join(f'<div class="box" style="width:780px"><div class="t" style="font:180px GB;text-transform:uppercase;'
                f'line-height:1;color:{RED_ON_DARK}">{s}</div><div class="rule" style="margin:34px 0"></div>'
                + "".join(f'<div class="t" style="font:58px GM;line-height:1.4;color:#E6E9F2">{x}</div>' for x in ms)
                + '</div>' for s, ms in cols)
    return f'''
<div class="vig"></div>
<img class="logo" src="logo_white.png">
<div class="over t" style="position:absolute;left:192px;top:200px">Как мы понимаем слово</div>
<div class="t" data-n="слово" style="position:absolute;left:192px;width:3456px;top:330px;text-align:center;font:330px GB;letter-spacing:.04em;line-height:1">{word}</div>
<div style="position:absolute;left:195px;top:1020px;display:flex;gap:110px">{c}</div>
<div class="t" style="position:absolute;left:192px;top:1900px;font:44px GM;color:#8A92A8">В авторский разбор входят не все буквы слова — «О» и «И» в нём не участвуют.</div>''', "dark"


def g14b():
    rows = [("Эва", "развитие · расширение · раскрытие"), ("Лю", "люди · любовь"),
            ("Ц", "циркуляция · энергия · сама жизнь"), ("Я", "частица творца · ответственность · сознание")]
    r = "".join(f'<div style="display:flex;align-items:center;gap:80px;height:330px;border-top:3px solid rgba(11,18,32,.1)">'
                f'<div class="t" style="width:760px;font:250px GB;text-transform:uppercase;line-height:1;color:{RED}">{s}</div>'
                f'<div class="t" style="font:74px GM;line-height:1.25">{m}</div></div>' for s, m in rows)
    return f'''
<img class="logo" src="logo_red.png">
<div style="position:absolute;left:192px;top:170px">
  <div class="over t">Как мы понимаем слово</div>
  <div class="t" style="font:150px GB;text-transform:uppercase;line-height:1;margin-top:26px">Эв<span style="opacity:.2">о</span>люц<span style="opacity:.2">и</span>я — из чего слово</div>
</div>
<div style="position:absolute;left:192px;top:620px;width:3456px">{r}</div>''', "light"



def g24():
    return f'''
<div class="vig"></div>
<img class="logo" src="logo_white.png">
<div class="over t" style="position:absolute;left:192px;top:240px">Эволюция ТВ</div>
<div style="position:absolute;left:192px;top:520px;width:3300px">
  <div class="t" style="font:140px GB;text-transform:uppercase;line-height:1.1">Чтобы Россия увидела<br>своих героев,<br>а мир увидел <span class="red">настоящую Россию</span></div>
  <div class="rule" style="margin:56px 0 0"></div>
  <div class="t" style="font:54px GM;color:#AEB6C8;margin-top:36px">Дарья Благо · директор АНО «Эволюция»</div>
</div>''', "dark"


def g25():
    arrow = (f'<div style="width:150px;height:8px;background:{RED};position:relative;flex-shrink:0">'
             f'<span style="position:absolute;right:-2px;top:-14px;width:0;height:0;border-left:30px solid {RED};'
             f'border-top:18px solid transparent;border-bottom:18px solid transparent"></span></div>')
    return f'''
<div class="vig"></div>
<div class="ghost" style="font-size:1400px;right:-40px;top:360px">24/7</div>
<img class="logo" src="logo_white.png">
<div style="position:absolute;left:192px;top:240px">
  <div class="over t">Что запускаем</div>
  <div class="t" style="font:170px GB;text-transform:uppercase;line-height:1;margin-top:28px">Ежедневные<br>созидательные новости</div>
</div>
<div style="position:absolute;left:192px;top:1000px;display:flex;align-items:center;gap:70px">
  <div class="box" style="width:1200px;padding:52px 56px;border-radius:26px;background:rgba(255,255,255,.05);border:2px solid rgba(255,255,255,.12)">
    <div class="t" style="font:120px GB;text-transform:uppercase;line-height:1">Стрим<br>24/7</div>
    <div class="t" style="font:48px GM;color:#CDD3E0;margin-top:22px">платформа «Эволюция ТВ»</div>
  </div>
  {arrow}
  <div class="box" style="width:1200px;padding:52px 56px;border-radius:26px;background:rgba(208,2,27,.12);border:2px solid rgba(208,2,27,.5)">
    <div class="t" style="font:120px GB;text-transform:uppercase;line-height:1">Федеральный<br>канал</div>
    <div class="t" style="font:48px GM;color:#CDD3E0;margin-top:22px">следующий шаг</div>
  </div>
</div>
<div class="t" style="position:absolute;left:192px;top:1730px;font:54px GM;color:#AEB6C8">Про российскую цивилизацию и её делателей — тех, кто создаёт уже сейчас</div>''', "dark"


def g27():
    items = [("Природоподобные технологии", "Наука"), ("Оздоровительные концепции", "Жизнь"),
             ("Образовательные инициативы", "Будущее"), ("Делатели и ремесленники", "Труд")]
    cards = "".join(
        f'<div class="box" style="width:810px;height:380px;padding:48px 46px;border-radius:26px;background:#fff;'
        f'box-shadow:0 24px 60px rgba(11,18,32,.08);display:flex;flex-direction:column;overflow:hidden">'
        f'<div class="t" style="font:600 36px GBo;letter-spacing:.12em;text-transform:uppercase;color:{RED}">Совет · {tag}</div>'
        f'<div class="t" style="font:58px GB;text-transform:uppercase;line-height:1.12;margin-top:24px">{name}</div></div>'
        for name, tag in items)
    return f'''
<img class="logo" src="logo_red.png">
<div style="position:absolute;left:192px;top:210px">
  <div class="over t">Эволюция ТВ · про кого снимаем</div>
  <div class="t" style="font:170px GB;text-transform:uppercase;line-height:1;margin-top:28px">Что показываем</div>
</div>
<div style="position:absolute;left:192px;top:790px;display:flex;gap:72px">{cards}</div>
<div class="t" style="position:absolute;left:192px;top:1500px;font:52px GM;opacity:.65">Каждое направление — один из шести советов платформы эволюция.рус</div>''', "light"


def g29():
    rows = "".join(f'<div class="t" style="font:200px GB;text-transform:uppercase;line-height:1.12">{w}'
                   f'<span class="red">.</span></div>' for w in ["Соучастие", "Созидание", "Сотворчество"])
    return f'''
<div class="vig"></div>
<img class="logo" src="logo_white.png">
<div class="over t" style="position:absolute;left:192px;top:260px">Приглашаем к</div>
<div style="position:absolute;left:192px;top:520px">{rows}</div>
<div style="position:absolute;left:192px;top:1700px">{grad_dots(7)}</div>''', "dark"


def g30():
    items = ["рассказ о вашем проекте", "предприятие или инициатива", "ваш жизненный путь",
             "художественный фильм, снятый своими силами", "короткий и полный метр",
             "любой созидательный формат"]
    lis = "".join(
        f'<div style="display:flex;align-items:baseline;gap:28px;margin-bottom:30px">'
        f'<span style="width:18px;height:18px;border-radius:50%;background:{RED};flex-shrink:0"></span>'
        f'<span class="t" style="font:62px GM;line-height:1.25">{x}</span></div>' for x in items)
    return f'''
<img class="logo" src="logo_red.png">
<div style="position:absolute;left:192px;top:200px">
  <div class="over t">Если вы производитель контента</div>
  <div class="t" style="font:170px GB;text-transform:uppercase;line-height:1;margin-top:26px">Что присылать</div>
</div>
<div style="position:absolute;left:192px;top:700px;width:2100px">{lis}</div>
<div class="box" style="position:absolute;left:2448px;top:700px;width:1200px;padding:56px 60px;border-radius:26px;background:{NAVY};color:#fff">
  <div class="t" style="font:600 46px GBo;letter-spacing:.12em;text-transform:uppercase;color:{RED_ON_DARK}">Куда писать</div>
  <div class="t" style="font:72px GX;margin-top:28px;line-height:1.2">ano@эволюция.рус</div>
  <div class="t" style="font:52px GM;color:#CDD3E0;margin-top:24px">эволюция.рус</div>
  <div class="t" style="font:46px GM;color:#AEB6C8;margin-top:36px;line-height:1.35">Нужен каждый регион России</div>
</div>''', "light"


def g31():
    return f'''
<div class="vig"></div>
<img class="logo" src="logo_white.png">
<div class="over t" style="position:absolute;left:192px;top:260px">Миссия центра</div>
<div style="position:absolute;left:192px;top:560px;width:3300px">
  <div class="t" style="font:170px GB;text-transform:uppercase;line-height:1.1">Россия — это <span class="red">ковчег</span>,<br>в котором мы все спасёмся</div>
  <div class="rule" style="margin:60px 0 0"></div>
  <div class="t" style="font:52px GM;color:#AEB6C8;margin-top:36px">Формулировка с сайта эволюция.рус</div>
</div>''', "dark"


def g21():
    inner = ('<div style="padding:50px 90px 54px 70px">'
             '<div class="t" style="font:112px GX;line-height:1;white-space:nowrap">Михаил Белавин</div>'
             '<div class="t" style="font:58px GM;color:#CDD3E0;margin-top:26px;white-space:nowrap">'
             'Генеральный продюсер «Эволюция ТВ»</div></div>'
             '<div style="display:flex;align-items:center;padding:0 80px;border-left:2px solid rgba(255,255,255,.12)">'
             '<img src="logo_white.png" style="height:84px"></div>')
    return plate(inner, "left:192px;bottom:170px"), "alpha"


def g22():
    rows = [("Человек", "Человек"), ("Человек", "Проект")]
    pairs = "".join(
        f'<div style="display:flex;align-items:center;gap:44px;margin-bottom:44px">'
        f'<div class="t" style="font:96px GB;text-transform:uppercase;line-height:1;width:560px">{a}</div>'
        f'<div style="width:180px;height:6px;background:{RED};position:relative">'
        f'<span style="position:absolute;right:-2px;top:-13px;width:0;height:0;border-left:28px solid {RED};'
        f'border-top:16px solid transparent;border-bottom:16px solid transparent"></span></div>'
        f'<div class="t" style="font:96px GB;text-transform:uppercase;line-height:1">{b}</div></div>'
        for a, b in rows)
    return f'''
<div class="vig"></div>
<img class="logo" src="logo_white.png">
<div style="position:absolute;left:192px;top:220px">
  <div class="over t">Внутри платформы</div>
  <div class="t" style="font:170px GB;text-transform:uppercase;line-height:1;margin-top:28px">Математическая<br>модель</div>
</div>
<div style="position:absolute;left:192px;top:820px">{pairs}</div>
<div class="t" style="position:absolute;left:192px;top:1310px;width:2600px;font:58px GM;line-height:1.4;color:#E6E9F2">
Соединяет по сильным врождённым предрасположенностям — алгоритмами, автоматически.
А дальше координационный совет собирает из этого сотворческий проект.</div>
<div class="t" style="position:absolute;left:192px;top:1640px;font:600 52px GBo;letter-spacing:.14em;text-transform:uppercase;color:{RED_ON_DARK}">Алгоритм → совет → проект</div>''', "dark"


def g23():
    steps = [("01", "Ваше видео", "поток на платформе"),
             ("02", "Автонарезка", "короткие хайлайты и рилсы + текстовое описание"),
             ("03", "Зрители делятся", "в любую соцсеть, в удобном формате")]
    cards = "".join(
        f'<div class="box" style="width:1080px;height:620px;padding:56px 60px;border-radius:28px;background:#fff;'
        f'box-shadow:0 30px 80px rgba(11,18,32,.1);display:flex;flex-direction:column;overflow:hidden">'
        f'<div class="t" style="font:70px GB;color:{RED}">{n}</div>'
        f'<div class="t" style="font:104px GB;text-transform:uppercase;line-height:1;margin-top:22px">{h}</div>'
        f'<div class="t" style="font:52px GM;line-height:1.35;margin-top:26px;opacity:.72">{d}</div></div>'
        for n, h, d in steps)
    return f'''
<img class="logo" src="logo_red.png">
<div style="position:absolute;left:192px;top:200px">
  <div class="over t">Эволюция ТВ · что дальше</div>
  <div class="t" style="font:170px GB;text-transform:uppercase;line-height:1;margin-top:28px">Из потока — в рилсы</div>
</div>
<div style="position:absolute;left:192px;top:760px;display:flex;gap:108px">{cards}</div>
<div class="t" style="position:absolute;left:192px;top:1500px;font:50px GM;opacity:.6">эволюция.рус · реестр производителей контента</div>''', "light"


def g16a():
    return f'''
<img class="logo" src="logo_red.png">
<div style="position:absolute;left:192px;top:190px"><div class="over t">Эволюция ТВ · эволюция.рус</div><div class="t" style="font:180px GB;text-transform:uppercase;line-height:1;margin-top:26px">Как участвовать</div></div>
<div style="position:absolute;left:192px;top:590px;display:flex;gap:156px">
 <div class="box" data-n="карточка реестр" style="width:1650px;height:1000px;border-radius:36px;background:{NAVY};color:#fff;padding:80px 84px;overflow:hidden">
   <div class="t" style="font:600 50px GBo;letter-spacing:.14em;text-transform:uppercase;color:{RED_ON_DARK}">Вы создаёте контент</div>
   <div class="t" style="font:130px GB;text-transform:uppercase;line-height:1;margin-top:34px">Попасть<br>в реестр</div>
   <div class="t" style="font:58px GM;line-height:1.35;margin-top:54px;color:#E6E9F2">Напишите нам — и попадёте в реестр производителей контента «Эволюция ТВ»: рассказы о проектах, созидательные фильмы короткого и полного метра.</div>
 </div>
 <div class="box" data-n="карточка заявка" style="width:1650px;height:1000px;border-radius:36px;background:#fff;padding:80px 84px;overflow:hidden;box-shadow:0 30px 80px rgba(11,18,32,.1)">
   <div class="t" style="font:600 50px GBo;letter-spacing:.14em;text-transform:uppercase;color:{RED}">Вы создаёте что-то на земле</div>
   <div class="t" style="font:130px GB;text-transform:uppercase;line-height:1;margin-top:34px">Оставить<br>заявку</div>
   <div class="t" style="font:58px GM;line-height:1.35;margin-top:54px">По любому из шести советов — и о вас снимут так, чтобы мы видели друг друга.</div>
 </div>
</div>
<div style="position:absolute;left:192px;top:1700px;display:flex;align-items:center;gap:60px">
 <div class="t" style="font:150px GB;color:{RED};line-height:1">эволюция.рус</div>
 <div class="t" style="font:56px GM;opacity:.7">ano@эволюция.рус</div>
</div>
<img class="t" data-n="QR" src="qr.png" style="position:absolute;left:3318px;top:1660px;width:330px;height:330px;image-rendering:pixelated">''', "light"


def g16b():
    return f'''
<div class="vig"></div>
<img class="logo" src="logo_white.png">
<div class="over t" style="position:absolute;left:192px;top:190px">Как участвовать</div>
<div style="position:absolute;left:1918px;top:380px;width:4px;height:1240px;background:rgba(255,255,255,.14)"></div>
<div class="t" data-n="или" style="position:absolute;left:1740px;top:820px;width:360px;height:360px;border-radius:50%;background:{RED};display:flex;align-items:center;justify-content:center;font:110px GB">или</div>
<div style="position:absolute;left:192px;top:520px;width:1460px">
  <div class="t" style="font:150px GB;text-transform:uppercase;line-height:1">Я снимаю</div>
  <div class="t" style="font:600 64px GBo;margin-top:60px;color:{RED_ON_DARK}">→ реестр производителей контента</div>
  <div class="t" style="font:54px GM;line-height:1.4;margin-top:34px;color:#CDD3E0">Рассказы о проектах, созидательные фильмы короткого и полного метра — в эфир «Эволюция ТВ» 24/7</div>
</div>
<div style="position:absolute;left:2188px;top:520px;width:1460px">
  <div class="t" style="font:150px GB;text-transform:uppercase;line-height:1">Снимите меня</div>
  <div class="t" style="font:600 64px GBo;margin-top:60px;color:{RED_ON_DARK}">→ заявка по одному из шести советов</div>
  <div class="t" style="font:54px GM;line-height:1.4;margin-top:34px;color:#CDD3E0">Делаете что-то на земле — в образовании, культуре, хозяйстве? Оставьте заявку, и о вас снимут</div>
</div>
<div class="t" style="position:absolute;left:192px;top:1780px;font:140px GB;line-height:1">эволюция.рус</div>
<div class="t" data-n="QR" style="position:absolute;left:3328px;top:1700px;width:320px;height:320px;background:#fff;border-radius:20px;padding:18px"><img src="qr.png" style="width:100%;height:100%;image-rendering:pixelated"></div>''', "dark"


def g17():
    return f'''
<div class="vig"></div>
<div style="position:absolute;left:192px;top:420px">
  <div class="t" style="font:380px GB;text-transform:uppercase;line-height:.88">Зависит<br>от нас<span class="red">.</span></div>
  <div style="margin-top:110px">{grad_dots(9)}</div>
</div>
<img class="t" data-n="логотип" src="logo_white.png" style="position:absolute;left:192px;top:1720px;width:1300px">
<div class="t" style="position:absolute;right:192px;top:1780px;font:110px GX;color:#fff">эволюция.рус</div>''', "dark"


def g18():
    return f'''
<div class="box" data-n="формула" style="position:absolute;left:520px;width:2800px;bottom:170px;border-radius:26px;background:rgba(11,18,32,.88);padding:54px 90px 64px;text-align:center;box-shadow:0 24px 70px rgba(0,0,0,.35)">
  <div class="t" style="font:600 52px GBo;letter-spacing:.16em;text-transform:uppercase;color:{RED_ON_DARK}">Жизнь будущего —</div>
  <div class="t" style="font:124px GB;text-transform:uppercase;line-height:1.05;margin-top:26px;white-space:nowrap">Любовь <span class="red">·</span> смысл <span class="red">·</span> созидание</div>
</div>''', "alpha"


def g20():
    return f'''
<div class="box" data-n="домен" style="position:absolute;right:192px;bottom:170px;display:flex;align-items:center;gap:44px;border-radius:22px;background:rgba(11,18,32,.9);padding:36px 60px 40px 50px;box-shadow:0 24px 70px rgba(0,0,0,.35)">
  <img src="logo_white.png" style="height:70px">
  <div style="width:3px;height:90px;background:rgba(255,255,255,.18)"></div>
  <div class="t" style="font:92px GX;line-height:1;white-space:nowrap">эволюция<span style="color:{RED_ON_DARK}">.рус</span></div>
</div>''', "alpha"


SCREENS = [
    ("G01", "A", "«Кто ваши герои?» — панель поверх кадра", g01a),
    ("G01", "B", "«Кто ваши герои?» — полный экран", g01b),
    ("G02", "A", "Заставка «ЭВОЛЮЦИЯ»", g02),
    ("G03", "A", "Плашка: Дарья Благо", lambda: lower_third("Дарья Благо", "Директор АНО «Эволюция»")),
    ("G04", "A", "Плашка: Анастасия Григорьева",
     lambda: lower_third("Анастасия Григорьева", "Соучредитель АНО «Эволюция»")),
    ("G05", "A", "Карточка АНО «Эволюция»", g05),
    ("G08", "A", "Шесть советов — сетка", g08a),
    ("G08", "B", "Шесть советов — вокруг человека", g08b),
    ("G10", "A", "Титр: Совет ТРУД",
     lambda: council_title("01", "Труд", "ценностно-ориентированное предпринимательство", "с него платформа начала работу")),
    ("G11", "A", "Титр: Совет КУЛЬТУРА",
     lambda: council_title("02", "Культура", "культурный код и смыслы", "«культура — это основа, это цивилизация»")),
    ("G12", "A", "Заставка «ЭВОЛЮЦИЯ ТВ»", g12),
    ("G13", "A", "Интерфейс: за каждым видео — человек", g13),
    ("G14", "A", "ЭВА · ЛЮ · Ц · Я — слово и слоги", g14a),
    ("G14", "B", "ЭВА · ЛЮ · Ц · Я — буквицы", g14b),
    ("G16", "A", "Как участвовать — две карточки", g16a),
    ("G16", "B", "Как участвовать — развилка «или»", g16b),
    ("G17", "A", "Финал: «Зависит от нас»", g17),
    ("G18", "A", "Формула: любовь · смысл · созидание", g18),
    ("G20", "A", "Плашка домена эволюция.рус", g20),
    ("G21", "A", "Плашка: Михаил Белавин — генеральный продюсер", g21),
    ("G24", "A", "Цитата: «увидела своих героев»", g24),
    ("G25", "A", "Что запускаем: стрим 24/7 → федеральный канал", g25),
    ("G27", "A", "Что показываем: четыре направления", g27),
    ("G29", "A", "Соучастие · Созидание · Сотворчество", g29),
    ("G30", "A", "Что присылать и куда писать", g30),
    ("G31", "A", "Цитата: «Россия — это ковчег»", g31),
    ("G22", "A", "Математическая модель платформы", g22),
    ("G23", "A", "Что дальше: автонарезка в рилсы", g23),
]


# ---------------- рендер / QC / превью ----------------
def qc(html_path):
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                            f"--window-size={W},{H}", "--force-device-scale-factor=1",
                            "--allow-file-access-from-files", "--virtual-time-budget=5000",
                            f"--user-data-dir={td}", "--dump-dom", html_path.resolve().as_uri()],
                           capture_output=True, text=True, timeout=120)
    m = re.search(r'data-qc="([^"]*)"', r.stdout)
    return _html.unescape(m.group(1)) if m else "нет отчёта QC"


def make_thumb(src_img, out, bg=None):
    im = Image.open(src_img).convert("RGBA")
    if bg is not None:
        base = bg.copy()
        base.alpha_composite(im)
        im = base
    im = im.convert("RGB")
    im.thumbnail((1600, 900))
    im.save(out, quality=86)


def make_qr():
    import qrcode
    q = qrcode.QRCode(border=1, box_size=20, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(PUNY_URL)
    q.make(fit=True)
    q.make_image(fill_color=NAVY, back_color="white").save(SRC / "qr.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--qc-only", action="store_true",
                    help="перегенерить HTML с текущим QC и перепроверить — без рендера PNG")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None

    THUMBS.mkdir(parents=True, exist_ok=True)
    if not a.qc_only:
        make_qr()
    bg = Image.open(BG_FRAME).convert("RGBA").resize((W, H))
    old = {}
    man_path = MOCK / "manifest.json"
    if man_path.exists():
        for m in json.loads(man_path.read_text(encoding="utf-8")):
            old[(m["id"], m["variant"])] = m

    manifest = []
    for gid, var, title, fn in SCREENS:
        key = f"{gid}_{var}"
        body, cls = fn()
        alpha = cls == "alpha"
        html_path, png = SRC / f"{key}.html", MOCK / f"{key}.png"
        if a.qc_only:
            html_path.write_text(page(body, cls), encoding="utf-8")
            report = qc(html_path)
        elif only is None or gid in only or not png.exists():
            html_path.write_text(page(body, cls), encoding="utf-8")
            render(html_path, png, size=f"{W}x{H}", alpha=alpha)
            report = qc(html_path)
            bgi = bg
            if alpha and gid in BG_OVERRIDE and BG_OVERRIDE[gid].exists():
                bgi = Image.open(BG_OVERRIDE[gid]).convert("RGBA").resize((W, H))
            make_thumb(png, THUMBS / f"{key}.jpg", bgi if alpha else None)
        else:
            report = old.get((gid, var), {}).get("qc", "не перепроверялся")
        manifest.append({"id": gid, "variant": var, "title": title, "kind": "new", "alpha": alpha,
                         "png": f"{key}.png", "thumb": f"thumbs/{key}.jpg", "qc": report})
        print(f"{key:<7} {'α' if alpha else ' '} {title:<44} QC: {report}")

    for gid, (fname, title) in CLIENT_MAP.items():
        key = f"{gid}_A"
        make_thumb(CLIENT / fname, THUMBS / f"{key}.jpg")
        manifest.append({"id": gid, "variant": "A", "title": title, "kind": "client", "alpha": False,
                         "png": f"client_slides/{fname}", "thumb": f"thumbs/{key}.jpg", "qc": "слайд клиента"})
        print(f"{key:<7}   {title:<44} (из PDF клиента, {fname})")

    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [m for m in manifest if m["kind"] == "new" and m["qc"] != "ok"]
    print(f"\nэкранов: {len(manifest)} · новых {sum(m['kind'] == 'new' for m in manifest)} · "
          f"слайдов клиента {len(CLIENT_MAP)} · QC с замечаниями: {len(bad)}")
    print(f"→ {man_path}")


if __name__ == "__main__":
    main()
