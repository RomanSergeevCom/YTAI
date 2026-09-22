#!/usr/bin/env python3
"""build_structure_html.py — страница разбора YTEVO02 «Манифест платформы Эволюция».

Собирает статический HTML из локальных источников:
  • YTEVO02.words.json               — мастер транскрибации (дословно, по ролям)
  • analysis.json                    — многоагентный разбор исходника (блоки, диагноз)
  • montage.json                     — монтажный лист чистовика (build_montage.py)
  • 05_Review/mockups/manifest.json  — 4K-мокапы экранов (build_mockups.py)
Транскрипт никогда не перепечатывается руками — только из мастер-JSON.

  python3 build_structure_html.py [--portal]   # --portal: фавиконка портала вместо inline SVG
"""
import argparse
import html
import json
import re
from pathlib import Path

BASE = Path("/Volumes/T9-Black-RYA/YTEVO/YTEVO02_evolution_manifesto/00_Setup")
WORDS = BASE / "YTEVO02.words.json"
ANALYSIS = BASE / "analysis.json"
MONTAGE = BASE / "montage.json"
MANIFEST = BASE / "05_Review" / "mockups" / "manifest.json"
MOCK_REL = "05_Review/mockups"   # относительно 00_Setup, где лежит страница

SPEAKERS = {
    "Speaker 1": ("Дарья Благо", "d", "Ракурс A — крупный план · в общем плане B справа"),
    "Speaker 2": ("Анастасия Григорьева", "a", "Только общий план B — слева"),
    "Speaker 3": ("Мужчина за кадром", "m", "Режиссёр/оператор"),
}

CLIPS = [
    ("C0005.MP4", "5:42.72", "00:00.00", "05:42.72", "12:00:45", "4,19 ГБ"),
    ("C0006.MP4", "5:42.72", "05:42.72", "11:25.44", "12:06:27", "4,19 ГБ"),
    ("C0007.MP4", "5:41.76", "11:25.44", "17:07.20", "12:12:10", "4,19 ГБ"),
    ("C0008.MP4", "0:20.16", "17:07.20", "17:27.36", "12:17:52", "0,25 ГБ"),
    ("C0009.MP4", "5:41.76", "17:27.36", "23:09.12", "12:18:15", "4,19 ГБ"),
]

KIND_COLOR = {
    "полноэкранная карточка": "full", "lower-third плашка": "lt", "lower-third": "lt",
    "таймлайн": "tl", "схема-связей": "sch", "карта": "map",
    "типографика-цитата": "typo", "счётчик/цифра": "num", "список-чеклист": "list",
    "разбор слова по частям": "word", "сравнение до/после": "cmp",
    "экранный титр-поправка": "fix", "архивная/стоковая подложка": "stock", "ничего": "none",
}

ACT_COLOR = {"Крючок": "#F87171", "Кто мы": "#93C5FD", "Опора": "#C4B5FD", "Логика": "#A5B4FC",
             "Новость": "#86EFAC", "Продукт": "#67E8F9", "Зачем": "#FCA5A5", "Смысл": "#FCD34D",
             "Призыв": "#4ADE80", "Финал": "#F9A8D4"}

LINKS_BLOCK = (
    '<div class="sec" id="links">Материалы и ссылки</div>'
    '<div class="lks">'
    '<a class="lk" href="https://xn--b1amil5bzbkk.xn--p1acf/" target="_blank" rel="noopener">'
    '<b>🌐 эволюция.рус</b><span>Сайт платформы: шесть советов, реестр проектов, контакты. '
    'АНО «Центр развития социальных проектов „Эволюция“», ИНН 9734003957</span></a>'
    '<a class="lk" href="https://drive.google.com/open?id=1YK-n_ThNcDNITz9Ne58ReHUOGIs6xR0e" target="_blank" rel="noopener">'
    '<b>📊 Презентация «Ценностный суверенитет России»</b><span>18 слайдов, автор — Анастасия Григорьева. '
    'Из неё взяты слайды с указами, «Путём России» и расшифровкой СССР · Google Drive</span></a>'
    '<a class="lk" href="https://drive.google.com/open?id=14dO8sy3IAapispgtw-2wXUYW8xfvHRCJ" target="_blank" rel="noopener">'
    '<b>📁 Папка канала на Google Drive</b><span>YTEVO — материалы спринтов канала</span></a>'
    '<a class="lk" href="https://yt.rya.ae/ytevo/" target="_blank" rel="noopener">'
    '<b>🛠 Страница канала на портале</b><span>yt.rya.ae/ytevo/ — организация, советы, правовая опора, люди</span></a>'
    '<a class="lk" href="https://drive.google.com/drive/folders/1ZN_xiS2dwB6I6Pg_uSIWkgfulC9AjOKl" target="_blank" rel="noopener">'
    '<b>💾 Исходные видео — на Google Drive</b>'
    '<span>YTEVO → YTEVO S1 → YTEVO02_evolution_manifesto → 01_Source/Video. Манифест: крупный план A C0005–C0009 (17,0 ГБ) '
    'и общий план B A004_11201111_C010 (25:16, 140 ГБ). Вторая сцена «Эволюция ТВ»: C0014–C0015 (5,8 ГБ) и общий план '
    'A004_11201148_C013 (7:56, 44 ГБ). Общие планы B — только на Drive.</span></a>'
    '<div class="lk lk-off"><b>📄 Транскрипты и монтажные листы</b>'
    '<span>Там же, в 00_Setup: YTEVO02.diarized.txt и YTEVO02cam2.diarized.txt (дословно, по ролям), '
    'montage.json и montage_cam2.json (склейки), 05_Review/mockups (экраны в 4K)</span></div>'
    '</div>'
)

CHAPTERS2 = [("S01", "Новость: запуск «Эволюция ТВ»"), ("S05", "Что показываем"),
             ("S09", "Как это работает"), ("S12", "Как участвовать")]

CLIPS2 = [("C0014.MP4", "5:42.72", "00:00.00", "05:42.72", "12:37:12", "4,19 ГБ"),
          ("C0015.MP4", "2:14.40", "05:42.72", "07:57.12", "12:42:54", "1,65 ГБ")]

SCENE2_NOTE = (
    "<b>Отдельная сцена: снята в тот же день позже, той же камерой A.</b> Sony A7 III (C0014–C0015), "
    "12:37:12–12:45:09, одна непрерывная запись 7:57. В кадре снова Дарья, но говорят двое: "
    "она и <b>Михаил, генеральный продюсер «Эволюция ТВ»</b>. На крупном плане A его нет, но 15.09 пришёл "
    "общий план B (A004_11201148_C013.mov, Blackmagic): Михаил слева, Дарья справа — его реплики стоят на нём.<br><br>"
    "<b>Текст новый целиком.</b> Сравнение двух транскрибаций по словам: совпадений от пяти слов подряд — "
    "ноль, ни одна из 749 реплик этой сцены не звучит в манифесте. Значит заменить что-то в манифесте "
    "«более чистым дублем» отсюда нельзя — это дополнение, а не пересъём.<br><br>"
    "<b>Куда годится.</b> По смыслу сцена попадает ровно в три куска манифеста: анонс «Эволюция ТВ» "
    "(кусок 10), устройство платформы (кусок 11) и призыв (кусок 16), — и добавляет то, чего в манифесте "
    "нет: федеральное вещание, математическую модель соединения людей и проектов, автонарезку в рилсы. "
    "Отсюда развилка. <b>Вписать в манифест</b> — появляется второй голос и второй сет, лекарство от "
    "23 минут одного плана, но хронометраж уходит к 17 минутам и в ролике оказываются два призыва подряд. "
    "<b>Отдельный выпуск</b> — своя новость, свой герой, свой адресат, и манифест перестаёт конкурировать "
    "сам с собой. Рекомендую второе, поэтому ниже сцена собрана как самостоятельный ролик."
)

CHAPTERS = [("01", "Кто ваши герои?"), ("03", "Кто мы и зачем"),
            ("06", "Опора: Конституция, указы, шесть советов"), ("07", "СССР — Союз Созидательных Сил России"),
            ("10", "Запуск «Эволюция ТВ»"), ("11", "Как устроена платформа"),
            ("12", "Против чего: информация и страх"), ("13", "Что такое «эволюция»"),
            ("16", "Как участвовать: эволюция.рус"), ("17", "Всё рождается из вас самих · да здравствует эволюция")]

# как находки разбора закрываются этой страницей
FINDING_TAGS = {
    "ПРОДАКШЕН-ПРОБЛЕМА №1": "камера B пришла — общий план, реплики Анастасии на нём",
    "ПРОДАКШЕН-ПРОБЛЕМА №2": "вторая крупность есть — общий план B",
    "ПОРЯДОК ПЕРЕСБОРКИ": "реализовано в монтажном листе",
    "ЧЕТЫРЕ СТЫКА": "проверено по звуку общего плана: три шва непрерывны, на C0008/C0009 пропало 3,16 с",
    "ГРАФИКА ЗДЕСЬ": "экраны отрисованы — галерея выше",
    "ШЕСТЬ СОВЕТОВ": "закрыто экраном G08",
    "«СССР»": "закрыто слайдом клиента G09",
    "КОНТАКТОВ НЕТ": "закрыто экранами G16 и G20, есть QR",
    "ПРАВОВОЙ СЛОЙ": "закрыто слайдами клиента G06 · G07 · G15",
}
FINDING_SKIP = ("ТАЙМИНГ ГЛАВ",)

DEVIATIONS = [
    "«Почему Россия» взято одним куском 08:38–09:17 (39 с) вместо двух — без склейки и в целевом окне 40–55 с.",
    "В финал добавлена подводка 22:45 «Люди проживают всю жизнь…» — без неё «Но поймите» висит в воздухе.",
    "«Но героев у нас много» поставлено сразу после анонса «Эволюция ТВ» — это отсылка к холодному старту, кольцо замыкается там.",
    "Добавлены 02:20–02:33 («создать систему, которая помогала бы людям быть счастливыми») и 04:02–04:12 (формула жизни будущего) — их оставлял вердикт блока 2, но в порядок пересборки они не попали.",
    "Оговорки сняты по словам, а не кусками: «Платформа Эмолюция —», «спускается эволюция ТВ», «мы регистрируемся… начинаем ценностную путь».",
    "15.09 пришёл общий план B: реплики Анастасии переставлены на него (крупного плана Анастасии нет), финал достроен с B — C0010 камеры A не передан, а на B речь идёт до «Да здравствует эволюция!».",
]

RECOMMEND = {
    "G01": "A — панель поверх кадра: пауза после «мама с папой» играет на Анастасии (общий план B, она слева). "
           "Мокап разложен на крупный план A — на общем плане панель перенести в свободную зону, не на героинь. "
           "B — если на общем плане места под панель не окажется.",
    "G08": "Оба, в разных местах. A (сетка) — полноэкранная вставка-исправление в куске 06, читается за 7 секунд. "
           "B (вокруг человека) — повтор в призыве, кусок 16: рифмуется с «в центре всегда остаётся человек».",
    "G14": "B — буквицы на светлом: читается как последовательность и рифмуется с красными буквицами их слайда СССР. "
           "A — если между двумя светлыми экранами нужен тёмный.",
    "G16": "A — две карточки, почта и QR: самая ясная развилка с контактом. "
           "B — если финальному призыву нужна драма «или».",
}

PORTAL_HEAD = ('<!-- rya-site-v1 --><style id="rya-nf">html.rya-gating body{visibility:hidden}'
               '.rya-overlay,.rya-chrome{visibility:visible}</style><script>document.documentElement.className+='
               '" rya-gating";window.__ryaFailsafe=setTimeout(function(){document.documentElement.classList.remove('
               '"rya-gating")},3500);</script><link rel="stylesheet" href="/assets/site.css?v=21">')
PORTAL_BODY = '<script src="/assets/site.js?v=21" defer></script>'

SEAM_NOTE = (
    "<b>Пять файлов камеры A — одна запись, но не непрерывная: на шве C0008/C0009 (17:27.36) пропало 3,16 с.</b> "
    "Это показал общий план B, который писал без остановки: до шва его звук ложится на мастер со сдвигом +6,08 с, "
    "после — +2,92 с (46 окон по 6–10 с, невязка ≤16 мс); три других шва — без скачка. Прежний вывод «речь через шов "
    "идёт без пропуска» был ошибкой: распознавание склеило «создавать эту | форму эволюции ТВ», а на B фраза целая — "
    "«создавать этот путь и образ, который на самом деле уже есть. И платформа Эволюция ТВ». Расхождение времени "
    "создания C0009 (~2,6 с) было не артефактом метаданных, а этим пропуском. Сквозная ось A после 17:27 короче "
    "реального времени на 3,16 с; кусок 11 монтажного листа проходит через шов — он стоит на B и посчитан по B (+3,16 с).<br><br>"
    "<b>C0009 обрезан файлом</b> — ровно полный 4-ГБ кусок, речь до последней десятой секунды: камера A писала дальше, "
    "но C0010 не передан. Зато общий план B пишет ещё ≈2:10 после конца A, из них ≈1:49 — речь: «Попробуйте найти те "
    "желания… Будущее России создаётся созиданием каждого из нас… Да здравствует эволюция!» — финал в монтажном листе "
    "достроен с B. Хвост расшифрован отдельно: 05_Review/wide_tail/."
)

EXTRA_CSS = """
.toc{display:flex;flex-wrap:wrap;gap:7px;margin-top:16px}
.toc a{font-size:12px;padding:5px 11px;border-radius:7px;background:var(--bg-card);border:1px solid var(--border-soft);color:var(--text-dim);text-decoration:none}
.toc a:hover{border-color:var(--ch);color:var(--ch)}
.rbn{display:flex;height:46px;border-radius:10px;overflow:hidden;gap:2px;margin:6px 0 10px}
.rb{display:flex;align-items:center;justify-content:center;min-width:18px;text-decoration:none;color:#0A0D16;font:700 11px 'Space Grotesk',sans-serif;opacity:.9}
.rb:hover{opacity:1}
.lgs{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--text-mute);margin-bottom:16px}
.lg{display:inline-flex;align-items:center;gap:6px}.lg i{width:10px;height:10px;border-radius:3px;display:inline-block}
.mp{background:var(--bg-card);border:1px solid var(--border-soft);border-left:3px solid var(--border);border-radius:12px;padding:14px 18px;margin-bottom:10px}
.mp-h{display:flex;align-items:center;gap:11px;flex-wrap:wrap;margin-bottom:6px}
.mp-n{font:700 12px 'Space Grotesk',sans-serif;background:var(--bg-elev);border-radius:6px;padding:3px 8px;color:var(--text)}
.mp-tc{font-family:ui-monospace,Menlo,monospace;font-size:13px;color:var(--ch)}
.mp-h h3{font-size:15.5px;flex:1;min-width:220px}
.mp-act{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--text-mute)}
.mp-d{font-size:12px;color:var(--text-dim);font-family:ui-monospace,Menlo,monospace}
.mp-b{font-size:11px;color:var(--text-mute);text-decoration:none;border:1px solid var(--border-soft);border-radius:5px;padding:2px 7px}
.mp-b:hover{color:var(--ch);border-color:var(--ch)}
.pt{display:flex;flex-wrap:wrap;align-items:baseline;gap:5px 12px;padding:7px 0 7px 4px;border-top:1px dashed var(--border-soft);font-size:12.5px}
.pt-dst{font-family:ui-monospace,Menlo,monospace;color:var(--text-mute);min-width:44px}
.pt-src{font-family:ui-monospace,Menlo,monospace;color:var(--text)}
.pt-file{font-family:ui-monospace,Menlo,monospace;color:var(--text-mute);font-size:11.5px}
.pt-dur{color:var(--text-mute);font-size:11.5px}
.pt-txt{color:var(--text-dim);flex-basis:100%;padding-left:56px;font-size:13px}
.cam{font-size:11px;font-weight:700;padding:2px 8px;border-radius:5px}
.cam.ca{background:rgba(134,239,172,.14);color:var(--ch)}
.cam.cb{background:rgba(249,168,212,.14);color:var(--pink)}
.cam.cm{background:var(--bg-elev);color:var(--text-mute)}
.cam em{font-style:normal;font-weight:500;opacity:.8}
.gp{font-size:11px;color:var(--amber);cursor:help;border-bottom:1px dotted var(--amber)}
.xc{font-size:11px;color:var(--text-mute)}
.pt-ins .ins{color:var(--violet)}
.mp-g{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}
.gchip{font:700 11px 'Space Grotesk',sans-serif;padding:3px 9px;border-radius:6px;text-decoration:none;background:rgba(196,181,253,.12);color:var(--violet)}
.gchip.g-client{background:rgba(147,197,253,.12);color:var(--blue)}
.gchip span{font:500 11px ui-monospace,Menlo,monospace;margin-left:6px;opacity:.8}
.mp-note{margin-top:9px;font-size:12.8px;color:var(--text-dim);background:var(--bg-elev);border-radius:8px;padding:8px 12px}
.gal{display:grid;gap:14px}
.gc{background:var(--bg-card);border:1px solid var(--border-soft);border-radius:14px;padding:16px 18px}
.gc-h{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:11px}
.gc-id{font:700 12px 'Space Grotesk',sans-serif;color:var(--bg);background:var(--violet);border-radius:6px;padding:3px 8px}
.gc-h h4{font-size:15px;flex:1;min-width:200px}
.gk{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;padding:3px 8px;border-radius:5px}
.gk-new{background:rgba(196,181,253,.14);color:var(--violet)} .gk-client{background:rgba(147,197,253,.14);color:var(--blue)}
.gpl{font-size:11px;color:var(--text-mute)}
.gc-imgs{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(380px,1fr))}
.gc-imgs figure{margin:0}
.gc-imgs img{width:100%;border-radius:9px;border:1px solid var(--border-soft);display:block;aspect-ratio:16/9;object-fit:cover;background:#000}
.gc-imgs figcaption{font-size:12px;color:var(--text-dim);margin-top:6px}
.qc{font-size:10.5px;padding:1px 7px;border-radius:5px;margin-left:6px}
.qc.ok{background:rgba(74,222,128,.13);color:var(--ok)} .qc.bad{background:rgba(248,113,113,.13);color:var(--red)}
.gc-w{margin:10px 0 0;padding-left:18px;font-size:12.5px;color:var(--text-mute)}
.gc-w li{margin:2px 0} .gc-w a{color:var(--ch)}
.ftag{display:inline-block;font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:5px;margin-left:8px;background:rgba(74,222,128,.13);color:var(--ok);vertical-align:1px}
.devs{margin:8px 0 0;padding-left:20px} .devs li{margin:5px 0}
.lks{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(330px,1fr))}
.lk{display:block;background:var(--bg-card);border:1px solid var(--border-soft);border-radius:12px;padding:14px 17px;text-decoration:none}
a.lk:hover{border-color:var(--ch)}
.lk b{display:block;font-size:14px;color:var(--text);margin-bottom:5px;font-weight:600}
.lk span{font-size:12.5px;color:var(--text-mute);line-height:1.45;display:block}
.lk-off{opacity:.8;border-left:2px solid var(--amber)}
.st{border:1px solid var(--border-soft);border-radius:14px;overflow:hidden;background:var(--bg-card)}
.st-hd,.st-row{display:grid;grid-template-columns:64px minmax(0,1fr) minmax(0,1fr)}
.st-hd{background:var(--bg-elev);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--text-mute);font-weight:700}
.st-hd div{padding:10px 14px}
.st-row{border-top:1px solid var(--border-soft)}
.st-tc{padding:17px 0 0 14px;font-family:ui-monospace,Menlo,monospace;font-size:12.5px;color:var(--ch)}
.st-l{padding:15px 20px 17px 8px;border-right:1px solid var(--border-soft)}
.st-r{padding:15px 16px 17px}
.st-t{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:14.5px;color:var(--text);margin-bottom:8px}
.st-p{margin:0 0 9px;font-size:15px;line-height:1.62;color:var(--text)}
.st-ins{color:var(--violet);font-size:14px}
.st-src{font-size:11.8px;color:var(--text-mute);font-family:ui-monospace,Menlo,monospace;line-height:1.5}
.st-n{margin-top:10px;font-size:13px;color:var(--amber);background:rgba(252,211,77,.07);border-radius:8px;padding:8px 11px;line-height:1.5}
.st-f{margin:0 0 14px} .st-f:last-child{margin-bottom:0}
.st-f img{width:100%;display:block;border-radius:9px;border:1px solid var(--border-soft);aspect-ratio:16/9;object-fit:cover;background:#000}
.st-f figcaption{font-size:12.8px;color:var(--text-dim);margin-top:7px;line-height:1.45}
.st-meta{font-size:11.5px;color:var(--text-mute);margin-top:3px} .st-meta a{color:var(--ch)}
.st-im{position:relative}
.st-wait img{filter:grayscale(1) brightness(.5)}
.st-wl{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);font:700 12.5px 'Space Grotesk',sans-serif;letter-spacing:.1em;background:rgba(249,168,212,.9);color:#0A0D16;padding:6px 12px;border-radius:7px;white-space:nowrap}
.st-ch{background:color-mix(in srgb,var(--c) 20%,var(--bg-elev));border-top:1px solid var(--border-soft);padding:11px 16px}
.st-ch span{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:13px;letter-spacing:.06em;color:var(--text)}
.st-empty{font-size:12px;color:var(--text-mute);padding:8px 0}
details.dz{margin:12px 0;background:var(--bg-2);border:1px solid var(--border-soft);border-radius:12px;padding:2px 18px 6px}
details.dz>summary{cursor:pointer;padding:13px 0;font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:13px;letter-spacing:.06em;color:var(--text-dim)}
details.dz>summary:hover{color:var(--ch)}
@media(max-width:860px){.st-hd{display:none}.st-row{grid-template-columns:1fr}.st-l{border-right:0;padding-left:16px}.st-tc{padding:12px 16px 0}}
"""


def e(x):
    return html.escape(str(x if x is not None else ""))


def tc(t):
    m, s = divmod(float(t), 60)
    return f"{int(m):02d}:{int(s):02d}"


def mmss(t, ms=False):
    if t is None:
        return "—"
    t = max(0.0, float(t))
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:04.1f}" if ms else f"{int(m):02d}:{int(s):02d}"


def kind_slug(kind):
    k = (kind or "").strip().lower()
    for key, slug in KIND_COLOR.items():
        if key in k:
            return slug
    return "oth"


def verdict_slug(v):
    v = (v or "").lower()
    if v.startswith("вырезать"):
        return "cut"
    if "сжат" in v or "сокра" in v:
        return "trim"
    if "служеб" in v:
        return "svc"
    return "keep"


# ---------------- транскрипт ----------------
def build_transcript(words):
    rows = []
    for b in words.get("blocks", []):
        name, cls, _ = SPEAKERS.get(b["speaker"], (b["speaker"], "m", ""))
        rows.append(
            f'<div class="tr-row sp-{cls}">'
            f'<div class="tr-meta"><span class="tr-tc">{tc(b["start"])}</span>'
            f'<span class="tr-who">{e(name)}</span>'
            f'<span class="tr-dur">{b["end"] - b["start"]:.0f} с</span></div>'
            f'<div class="tr-text">{e(b["text"].strip())}</div></div>')
    return "\n".join(rows)


# ---------------- диагноз по блокам исходника ----------------
def build_blocks(canon, viz_by_n):
    out = []
    for b in canon.get("blocks", []):
        vs = verdict_slug(b.get("edit_verdict"))
        sp_raw = b.get("speaker", "") or ""
        cls = "d" if "Дарья" in sp_raw and "Анастас" not in sp_raw else ("a" if "Анастас" in sp_raw and "Дарья" not in sp_raw else "m")
        facts = b.get("facts") or []
        facts_html = ('<div class="b-facts"><div class="b-lbl">Фактура на экран</div><ul>'
                      + "".join(f"<li>{e(f)}</li>" for f in facts) + "</ul></div>") if facts else ""
        quote = f'<blockquote class="b-q">{e(b["key_quote"])}</blockquote>' if b.get("key_quote") else ""
        risk = f'<div class="b-risk"><b>Риск:</b> {e(b["risk"])}</div>' if b.get("risk") else ""
        viz = viz_by_n.get(b.get("n"))
        viz_html = ""
        if viz:
            cards = []
            for o in viz.get("options", []):
                data = o.get("data_on_screen") or []
                data_html = ('<div class="v-data"><div class="v-lbl">Что написано на экране</div><ul>'
                             + "".join(f"<li>{e(x)}</li>" for x in data) + "</ul></div>") if data else ""
                trig = f'<div class="v-trig">↳ реплика-триггер: «{e(o["trigger_quote"])}»</div>' if o.get("trigger_quote") else ""
                style = f'<div class="v-style"><b>В языке клиента:</b> {e(o["style_note"])}</div>' if o.get("style_note") else ""
                eff = e(o.get("effort", ""))
                effc = "h" if "выс" in eff.lower() else ("m" if "сред" in eff.lower() else "l")
                cards.append(
                    f'<div class="v-card k-{kind_slug(o.get("kind"))}">'
                    f'<div class="v-top"><span class="v-kind">{e(o.get("kind"))}</span>'
                    f'<span class="v-tc">{e(o.get("tc"))}</span><span class="v-eff eff-{effc}">{eff}</span></div>'
                    f'<h4>{e(o.get("name"))}</h4><p>{e(o.get("what_on_screen"))}</p>'
                    f'{data_html}{trig}{style}<div class="v-why"><b>Зачем:</b> {e(o.get("why"))}</div></div>')
            rec = f'<div class="v-rec"><b>Брать:</b> {e(viz["recommended"])}</div>' if viz.get("recommended") else ""
            viz_html = ('<div class="b-viz"><div class="b-lbl">Идеи графики из разбора (словами — '
                        'отрисованные экраны в галерее выше)</div>'
                        f'<div class="v-grid">{"".join(cards)}</div>{rec}</div>')
        out.append(
            f'<div class="blk v-{vs}" id="b{b.get("n")}"><div class="b-head">'
            f'<span class="b-n">{e(b.get("n"))}</span>'
            f'<span class="b-tc">{e(b.get("tc_in"))} — {e(b.get("tc_out"))}</span>'
            f'<h3>{e(b.get("title"))}</h3><span class="b-sp sp-{cls}">{e(sp_raw)}</span></div>'
            f'<div class="b-vd vb-{vs}">{e(b.get("edit_verdict"))}</div>'
            f'<div class="b-role">{e(b.get("role", ""))}</div>'
            f'<p class="b-sum">{e(b.get("summary"))}</p>{quote}{facts_html}{risk}{viz_html}</div>')
    return "\n".join(out)


def build_list(items, cls=""):
    if not items:
        return ""
    return f'<ul class="{cls}">' + "".join(f"<li>{e(x)}</li>" for x in items) + "</ul>"


def build_issues(res, title, tone, anchor):
    if not res:
        return ""
    parts = [f'<div class="sec" id="{anchor}">{e(title)}</div>']
    if res.get("verdict"):
        parts.append(f'<div class="note n-{tone}"><b>Вердикт:</b> {e(res["verdict"])}</div>')
    errs = res.get("errors") or []
    if errs:
        rows = "".join(f'<tr><td class="w">{e(x.get("where"))}</td><td>{e(x.get("problem"))}</td>'
                       f'<td class="fix">{e(x.get("fix"))}</td></tr>' for x in errs)
        parts.append('<div class="tblw"><table class="tbl"><thead><tr><th>Где</th><th>Что не так</th>'
                     f'<th>Как поправить</th></tr></thead><tbody>{rows}</tbody></table></div>')
    miss = res.get("missing") or []
    if miss:
        parts.append('<div class="note n-warn"><b>Чего не хватает</b>' + build_list(miss) + '</div>')
    return "\n".join(parts)


# ---------------- монтажный лист ----------------
def build_montage(mont):
    P, cat = mont["pieces"], mont["gfx_catalog"]
    ribbon = "".join(
        f'<a class="rb" href="#p{p["id"]}" style="flex:{max(p["dur"], 2):.2f};background:{ACT_COLOR.get(p.get("act"), "#8A92A8")}" '
        f'title="{e(p["id"])} · {e(p["title"])} · {p["dur"]:.0f} с"><span>{e(p["id"])}</span></a>' for p in P)
    acts = []
    for p in P:
        if p.get("act") and p["act"] not in acts:
            acts.append(p["act"])
    legend = "".join(f'<span class="lg"><i style="background:{ACT_COLOR.get(a, "#8A92A8")}"></i>{e(a)}</span>' for a in acts)

    rows = []
    for p in P:
        parts = []
        for x in p["parts"]:
            if x["kind"] == "say":
                cc = "ca" if x["camera"].startswith("A") else ("cb" if x["camera"].startswith("B") else "cm")
                alt = x.get("b") if x.get("angle") == "A" else x.get("a")
                pend = f' <em>· другой ракурс: {e(alt["file"])} +{mmss(alt["off_in"], True)}</em>' if alt else ""
                gaps = x.get("gaps") or []
                gap_title = ", ".join(f'{mmss(g["at"], True)} ({g["dur"]} с после «{g["after"]}»)' for g in gaps)
                gap_html = (f'<span class="gp" title="{e(gap_title)}">пауз ≥0,7 с: {len(gaps)} · −{x["trim_est"]:.1f} с</span>'
                            if gaps else "")
                cross = (f'<span class="xc">↔ внутри шов файлов {", ".join(mmss(c, True) for c in x["crosses_clip"])} — звук непрерывен</span>'
                         if x["crosses_clip"] else "")
                src_file = x["file_in"] + (f' → {x["file_out"]}' if x["file_out"] != x["file_in"] else "")
                parts.append(
                    f'<div class="pt"><span class="pt-dst">{mmss(x["dst_in"])}</span>'
                    f'<span class="pt-src">{mmss(x["src_in"], True)} – {mmss(x["src_out"], True)}</span>'
                    f'<span class="cam {cc}">{e(x["camera"])}{pend}</span>'
                    f'<span class="pt-file">{e(src_file)} +{mmss(x["off_in"], True)}</span>'
                    f'<span class="pt-dur">{x["dur"]:.1f} с</span>{gap_html}{cross}'
                    f'<span class="pt-txt">«{e(x["first"])} … {e(x["last"])}»</span></div>')
            elif x["kind"] == "gfx":
                parts.append(f'<div class="pt pt-ins"><span class="pt-dst">{mmss(x["dst_in"])}</span>'
                             f'<span class="ins">▣ полноэкранная вставка <a href="#g-{e(x["ref"])}" style="color:inherit">{e(x["ref"])}</a>'
                             f' · {e(cat[x["ref"]][1])}</span><span class="pt-dur">{x["dur"]:.1f} с</span></div>')
            else:
                parts.append(f'<div class="pt pt-ins"><span class="pt-dst">{mmss(x["dst_in"])}</span>'
                             f'<span class="ins">⏸ {e(x["ref"])}</span><span class="pt-dur">{x["dur"]:.1f} с</span></div>')
        chips = "".join(f'<a class="gchip g-{g["kind"]}" href="#g-{g["id"]}" title="{e(g["title"])}">{e(g["id"])}'
                        f'<span>{mmss(g["dst"])}</span></a>' for g in p["gfx"])
        blk = f'<a class="mp-b" href="#b{p["block"]}">блок {p["block"]} исходника</a>' if p.get("block") else ""
        rows.append(
            f'<div class="mp" id="p{p["id"]}" style="border-left-color:{ACT_COLOR.get(p.get("act"), "#8A92A8")}">'
            f'<div class="mp-h"><span class="mp-n">{e(p["id"])}</span>'
            f'<span class="mp-tc">{mmss(p["dst_in"])}–{mmss(p["dst_out"])}</span>'
            f'<h3>{e(p["title"])}</h3><span class="mp-act">{e(p.get("act", ""))}</span>'
            f'<span class="mp-d">{p["dur"]:.0f} с → ≈{p["dur_trimmed"]:.0f} с</span>{blk}</div>'
            + "".join(parts)
            + (f'<div class="mp-g">{chips}</div>' if chips else "")
            + (f'<div class="mp-note">{e(p["note"])}</div>' if p.get("note") else "")
            + '</div>')
    return (f'<div class="rbn">{ribbon}</div><div class="lgs">{legend}</div>' + "".join(rows))


# ---------------- галерея экранов ----------------
def build_gallery(mont, man, mock_rel=MOCK_REL, full_thumb=False):
    order, uses = [], {}
    for p in mont["pieces"]:
        for g in p["gfx"]:
            if g["id"] not in order:
                order.append(g["id"])
            uses.setdefault(g["id"], []).append((p["id"], g))
    cards = []
    for gid in order:
        kind, title, place = mont["gfx_catalog"][gid]
        vs = [m for m in man if m["id"] == gid]
        figs = []
        for m in vs:
            qc = m.get("qc", "")
            badge = ("" if m["kind"] == "client" else
                     ' <span class="qc ok">раскладка ок</span>' if qc == "ok" else
                     f' <span class="qc bad" title="{e(qc)}">QC: {e(qc[:60])}</span>')
            figs.append(f'<figure><a href="{mock_rel}/{e(m["thumb"] if full_thumb else m["png"])}" target="_blank">'
                        f'<img src="{mock_rel}/{e(m["thumb"])}" loading="lazy" alt="{e(m["title"])}"></a>'
                        f'<figcaption><b>{e(m["variant"])}</b> · {e(m["title"])}{badge}</figcaption></figure>')
        imgs = "".join(figs) or '<div class="note">мокап ещё не отрисован</div>'
        rec = f'<div class="v-rec"><b>Брать:</b> {e(RECOMMEND[gid])}</div>' if gid in RECOMMEND else ""
        items = []
        for pid, g in uses[gid]:
            link = f'<a href="#p{pid}">кусок {pid}</a>' if pid.isdigit() else f'кусок {pid} · вторая сцена'
            what = (f'на слове «{e(g["on_word"])}»' if g.get("on_word")
                    else f'полноэкранная вставка {g.get("insert", "")} с')
            items.append(f'<li>{link} · {mmss(g["dst"])} — {what}</li>')
        where = "".join(items)
        cards.append(
            f'<div class="gc" id="g-{gid}"><div class="gc-h"><span class="gc-id">{gid}</span><h4>{e(title)}</h4>'
            f'<span class="gk gk-{kind}">{"слайд клиента" if kind == "client" else "новый экран"}</span>'
            f'<span class="gpl">{e(place)}</span></div><div class="gc-imgs">{imgs}</div>{rec}'
            f'<ul class="gc-w">{where}</ul></div>')
    return '<div class="gal">' + "".join(cards) + '</div>'


def build_chapters(mont):
    by = {p["id"]: p for p in mont["pieces"]}
    acc, pos_tr = 0.0, {}
    for p in mont["pieces"]:
        pos_tr[p["id"]] = acc
        acc += p["dur_trimmed"]
    raw = "\n".join(f'{mmss(by[i]["dst_in"])} — {t}' for i, t in CHAPTERS if i in by)
    trm = "\n".join(f'{mmss(pos_tr[i])} — {t}' for i, t in CHAPTERS if i in by)
    return (f'<div class="note n-ok">Посчитаны по реальному монтажному листу: первая глава с 00:00, '
            f'каждая — от первого куска своего акта. Слева — тайминг листа как есть, справа — после '
            f'подрезки пауз (ориентир для финала).'
            f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">'
            f'<pre class="ch">{e(raw)}</pre><pre class="ch">{e(trm)}</pre></div></div>')


STORY_REC = {"G01": "A", "G14": "B", "G16": "A"}   # какой вариант показывать крупно в рассказе

HOW_TO_READ = (
    '<div class="note n-info"><b>Как читать</b><ul>'
    '<li>слева — рассказ чистовика дословно, в порядке монтажа; под каждым куском — файл и таймкод исходника</li>'
    '<li>справа — что на экране в этот момент: наш драфт графики, слайд клиента или кадр камеры; '
    'под картинкой — «таймкод · что на экране»</li>'
    '<li>✂ жёлтым — что убрано из куска и где графика правит оговорку</li>'
    '<li>главы — цветные строки [в скобках], по ним же главы YouTube</li>'
    '<li>узкая колонка слева — таймкод чистовика; клик по картинке — крупно</li>'
    '</ul></div>')

STORY_JS = ('<script>document.querySelectorAll("a").forEach(function(a){var h=a.getAttribute("href")||"";'
            'if(h.charAt(0)!=="#")return;a.addEventListener("click",function(){var t=document.getElementById(h.slice(1));'
            'for(var d=t&&t.closest("details");d;d=d.parentElement&&d.parentElement.closest("details"))d.open=true;});});'
            '</script>')


def tidy(t):
    t = re.sub(r" -(\w)", r"-\1", t)          # «чуть -чуть» → «чуть-чуть»
    return re.sub(r" \.(\w)", r".\1", t)      # «эволюция .рус» → «эволюция.рус»


def pick_variant(gid, pid, man):
    vs = [m for m in man if m["id"] == gid]
    if not vs:
        return None, []
    want = "B" if (gid == "G08" and pid == "16") else STORY_REC.get(gid, "A")
    main = next((m for m in vs if m["variant"] == want), vs[0])
    return main, [m for m in vs if m is not main]


def build_story(mont, man, mock_rel, full_thumb, frames_sub="story_frames", chapters=None):
    chapters = CHAPTERS if chapters is None else chapters
    fdir = BASE / "05_Review" / "mockups" / frames_sub
    frames = {f.name.split("__")[0]: f.name for f in fdir.glob("*.jpg")}
    wdir = BASE / "05_Review" / "mockups" / (frames_sub + "_wide")
    wframes = {f.name.split("__")[0]: f.name for f in wdir.glob("*.jpg")} if wdir.exists() else {}
    cat = mont["gfx_catalog"]
    by = {p["id"]: p for p in mont["pieces"]}
    chap = {pid: i for i, (pid, _) in enumerate(chapters)}
    rows = ['<div class="st-hd"><div>ТК</div><div>Рассказ</div><div>Что на экране</div></div>']
    for p in mont["pieces"]:
        if p["id"] in chap:
            i = chap[p["id"]]
            b = by[chapters[i + 1][0]]["dst_in"] if i + 1 < len(chapters) else mont["total"]
            rows.append(f'<div class="st-ch" style="--c:{ACT_COLOR.get(p.get("act"), "#8A92A8")}">'
                        f'<span>[{i + 1}. {e(chapters[i][1].upper())} · {mmss(p["dst_in"])}–{mmss(b)}]</span></div>')
        for k, x in enumerate(p["parts"]):
            head = f'<div class="st-t">【{e(p["id"])} · {e(p["title"])}】</div>' if k == 0 else ""
            note = f'<div class="st-n">✂ {e(p["note"])}</div>' if k == 0 and p.get("note") else ""
            cam_b = False
            if x["kind"] == "say":
                cam_b = x.get("angle") == "B" or x["camera"].startswith("B")
                cam = x["camera"]
                alt = x.get("b") if x.get("angle") == "A" else x.get("a")
                if alt:
                    cam += f' · другой ракурс {alt["file"]} +{mmss(alt["off_in"], True)}'

                gaps = x.get("gaps") or []
                src = (f'📄 {x["file_in"]} +{mmss(x["off_in"], True)} · исходник {mmss(x["src_in"], True)}–'
                       f'{mmss(x["src_out"], True)} · {x["dur"]:.1f} с · {cam}'
                       + (f' · пауз к подрезке {len(gaps)} (−{x["trim_est"]:.1f} с)' if gaps else ""))
                left = f'{head}<p class="st-p">{e(tidy(x["text"]))}</p><div class="st-src">{e(src)}</div>{note}'
                here = [g for g in p["gfx"] if not g.get("insert") and g.get("dst") is not None
                        and x["dst_in"] - 0.05 <= g["dst"] < x["dst_out"]]
            elif x["kind"] == "gfx":
                left = (f'{head}<p class="st-p st-ins">▣ Полноэкранная вставка {e(x["ref"])} · {x["dur"]:.0f} с — '
                        f'{e(cat[x["ref"]][1])}</p>{note}')
                here = [g for g in p["gfx"] if g.get("insert") and abs(g["dst"] - x["dst_in"]) < 0.05]
            else:
                left = f'{head}<p class="st-p st-ins">⏸ {e(x["ref"])} · {x["dur"]:.0f} с</p>{note}'
                here = []
            figs = []
            for g in here:
                main, others = pick_variant(g["id"], p["id"], man)
                if not main:
                    continue
                href = f'{mock_rel}/{main["thumb"] if full_thumb else main["png"]}'
                where = f'на слове «{e(g["on_word"])}»' if g.get("on_word") else f'полноэкранно, {g.get("insert", "")} с'
                if main.get("alpha") and cam_b:
                    where += " · подложка превью — крупный план A, в монтаже — общий план B"
                srcd = ("слайд клиента из презентации «Ценностный суверенитет России»" if main["kind"] == "client"
                        else "наш драфт — перерисовать в стиле клиента")
                var = f'вариант {main["variant"]}' + (f' · есть {", ".join(o["variant"] for o in others)}' if others else "")
                figs.append(f'<figure class="st-f"><a href="{e(href)}" target="_blank"><img src="{mock_rel}/{e(main["thumb"])}" '
                            f'loading="lazy" alt="{e(main["title"])}"></a><figcaption><b>{mmss(g["dst"])}</b> · {where} — '
                            f'{e(cat[g["id"]][1])}</figcaption><div class="st-meta">📚 {srcd} · '
                            f'<a href="#g-{g["id"]}">{g["id"]}: {var}</a></div></figure>')
            if not figs and x["kind"] == "say":
                mid = round((x["src_in"] + x["src_out"]) / 2, 2)
                key = "t" + f'{int(mid // 60):02d}m{mid % 60:06.3f}s'.replace(".", "_")
                fn, wfn = frames.get(key), wframes.get(key)
                if cam_b and wfn:
                    figs.append(f'<figure class="st-f"><div class="st-im"><img src="{mock_rel}/{frames_sub}_wide/{wfn}" '
                                f'loading="lazy" alt=""></div><figcaption><b>{mmss(x["dst_in"])}</b> · ракурс B, общий план — '
                                f'говорит {e(x.get("speaker_name", ""))}, графики нет</figcaption></figure>')
                elif fn and cam_b:
                    figs.append(f'<figure class="st-f"><div class="st-im st-wait"><img src="{mock_rel}/{frames_sub}/{fn}" '
                                f'loading="lazy" alt=""><span class="st-wl">{e(x["camera"].upper())} · КАДР B НЕ ИЗВЛЕЧЁН</span></div>'
                                f'<figcaption><b>{mmss(x["dst_in"])}</b> · на подложке крупный план A — кадр общего плана '
                                f'для превью не извлечён</figcaption></figure>')
                elif fn:
                    figs.append(f'<figure class="st-f"><div class="st-im"><img src="{mock_rel}/{frames_sub}/{fn}" '
                                f'loading="lazy" alt=""></div><figcaption><b>{mmss(x["dst_in"])}</b> · ракурс A, крупный план Дарьи — '
                                f'графики нет</figcaption></figure>')
            elif not figs:
                figs.append('<div class="st-empty">удержание кадра</div>')
            rows.append(f'<div class="st-row"><div class="st-tc">{mmss(x["dst_in"])}</div>'
                        f'<div class="st-l">{left}</div><div class="st-r">{"".join(figs)}</div></div>')
    return '<div class="st">' + "".join(rows) + '</div>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--portal", action="store_true")
    ap.add_argument("--out", default=str(BASE / "YTEVO02_structure.html"))
    ap.add_argument("--mock-rel", default=MOCK_REL, help="путь к мокапам относительно страницы")
    ap.add_argument("--full-res-thumbs", action="store_true", help="клик по превью ведёт на превью (4K не копируются)")
    a = ap.parse_args()

    words = json.loads(WORDS.read_text(encoding="utf-8"))
    an = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    mont = json.loads(MONTAGE.read_text(encoding="utf-8"))
    m2p = BASE / "montage_cam2.json"
    mont2 = json.loads(m2p.read_text(encoding="utf-8")) if m2p.exists() else None
    man = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else []
    canon = an["canon"]
    viz_by_n = {v["n"]: v for v in an.get("viz", []) if v}

    favicon = ('<link rel="icon" type="image/png" href="/favicon.png?v=1">'
               '<link rel="apple-touch-icon" href="/apple-touch-icon.png?v=1">' if a.portal else
               '<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' '
               'viewBox=\'0 0 100 100\'%3E%3Ctext y=\'.9em\' font-size=\'88\'%3E%F0%9F%8C%B1%3C/text%3E%3C/svg%3E">')

    clip_rows = "".join(
        f"<tr><td class='mono'>{e(n)}</td><td>{e(d)}</td><td class='mono'>{e(i)} → {e(o)}</td>"
        f"<td class='mono dim'>{e(ct)}</td><td>{e(sz)}</td></tr>" for n, d, i, o, ct, sz in CLIPS)

    spk = words.get("speakers_seconds", {})
    total_sp = sum(spk.values()) or 1
    spk_rows = "".join(
        f'<div class="sp-card sp-{SPEAKERS[k][1]}"><div class="sp-name">{e(SPEAKERS[k][0])}</div>'
        f'<div class="sp-bar"><i style="width:{v / total_sp * 100:.0f}%"></i></div>'
        f'<div class="sp-meta">{int(v // 60)} мин {v % 60:.0f} с · {v / total_sp * 100:.0f}% речи</div>'
        f'<div class="sp-note">{e(SPEAKERS[k][2])}</div></div>'
        for k, v in sorted(spk.items(), key=lambda x: -x[1]) if k in SPEAKERS)

    findings = []
    for f in canon.get("global_findings", []):
        if f.startswith(FINDING_SKIP):
            continue
        tag = next((t for k, t in FINDING_TAGS.items() if f.startswith(k)), None)
        findings.append(f'<div class="note n-warn">{e(f)}' + (f'<span class="ftag">✓ {e(tag)}</span>' if tag else "") + '</div>')

    n_new = sum(1 for m in man if m["kind"] == "new")
    n_client = sum(1 for m in man if m["kind"] == "client")
    n_qc_bad = sum(1 for m in man if m["kind"] == "new" and m.get("qc") != "ok")
    gal_src = {"gfx_catalog": {**mont["gfx_catalog"], **(mont2["gfx_catalog"] if mont2 else {})},
               "pieces": mont["pieces"] + (mont2["pieces"] if mont2 else [])}
    screens = len(set(mont.get("gfx_used", [])) | set(mont2.get("gfx_used", []) if mont2 else []))
    clip_rows2 = "".join(
        f"<tr><td class='mono'>{e(n)}</td><td>{e(d)}</td><td class='mono'>{e(i)} → {e(o)}</td>"
        f"<td class='mono dim'>{e(ct)}</td><td>{e(sz)}</td></tr>" for n, d, i, o, ct, sz in CLIPS2)
    spk2 = ("" if not mont2 else
            '<div class="sp-card" style="border-top-color:var(--blue)"><div class="sp-name">Михаил</div>'
            '<div class="sp-bar"><i style="width:37%;background:var(--blue)"></i></div>'
            '<div class="sp-meta">2 мин 33 с · 37% речи второй сцены</div>'
            '<div class="sp-note">Генеральный продюсер «Эволюция ТВ» · только общий план B — слева</div></div>')
    scene2 = ("" if not mont2 else
              f'<div class="sec" id="scene2">Вторая сцена · «Эволюция ТВ» — {mmss(mont2["total"])}</div>'
              f'<div class="note n-info">{SCENE2_NOTE}</div>'
              + build_story(mont2, man, a.mock_rel, a.full_res_thumbs, "story_frames_cam2", CHAPTERS2))
    devs = "".join(f"<li>{e(d)}</li>" for d in DEVIATIONS)

    # ракурсы: строки таблиц исходника и заметка — из angles.json (через montage*.json)
    def b_row(ang):
        return (f"<tr><td class='mono'>{e(ang['file'])}</td><td>{mmss(ang['duration'], True)}</td>"
                f"<td class='mono'>ракурс B · {e(ang.get('map_text', ''))}</td>"
                f"<td class='mono dim'>TC {e(ang.get('tc', ''))}</td><td>{e(ang.get('size', ''))}</td></tr>")
    angB = (mont.get("angles") or {}).get("B")
    angB2 = ((mont2 or {}).get("angles") or {}).get("B")
    if angB:
        clip_rows += b_row(angB)
    if angB2:
        clip_rows2 += b_row(angB2)
    n_b = sum(1 for p in mont["pieces"] for x in p["parts"] if x.get("angle") == "B")
    angles_note = (angB.get("note_html", "") + f"<br><br><b>В монтажном листе</b> {n_b} из {mont['n_say_parts']} "
                   "склеек речи стоят на общем плане B, остальные — на крупном плане Дарьи A; "
                   "у каждой указан и второй ракурс с точным смещением.") if angB else ""

    crumbs = ('<nav class="crumbs"><a href="https://yt.rya.ae/">Overview</a><span>›</span>'
              '<a href="https://yt.rya.ae/#channels">Channels</a><span>›</span>'
              '<a href="https://yt.rya.ae/ytevo/">YTEVO</a><span>›</span><b>YTEVO02</b></nav>')

    doc = f"""<!DOCTYPE html>
<html lang="ru" data-channel="ytevo" data-page="/ytevo/02/" data-rya-theme="core" data-rya-haschrome="1">
<head>
{favicon}
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>YTEVO02 · Манифест платформы «Эволюция» — структура и графика</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<style>
:root{{
  --bg:#0A0D16; --bg-2:#0F131E; --bg-card:#181D2B; --bg-elev:#232A3D;
  --border:#3A4258; --border-soft:#252B3D;
  --text:#F0F2F8; --text-dim:#C8CDD9; --text-mute:#8A92A8;
  --ch:#86EFAC; --ok:#4ADE80; --amber:#FCD34D; --red:#F87171; --violet:#C4B5FD; --blue:#93C5FD; --pink:#F9A8D4;
  --cl-red:#D0021B; --radius:14px;
}}
*{{box-sizing:border-box}}
html,body{{margin:0;background:var(--bg);color:var(--text);font-family:'Inter',-apple-system,sans-serif;font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased}}
h1,h2,h3,h4{{font-family:'Space Grotesk','Inter',sans-serif;margin:0;letter-spacing:-.01em}}
a{{color:inherit}}
.topbar{{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:14px 28px;border-bottom:1px solid var(--border);background:var(--bg-2);position:sticky;top:0;z-index:50;-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px)}}
.brand{{display:flex;align-items:center;gap:12px;text-decoration:none}}
.brand-mark{{width:36px;height:36px;border-radius:10px;display:grid;place-items:center;background:linear-gradient(135deg,#14532D,#0E1424);box-shadow:0 0 0 1px rgba(134,239,172,.25);font-family:'Space Grotesk';font-weight:700;color:var(--ch);font-size:13px}}
.brand-text{{font-family:'Space Grotesk';font-weight:700;font-size:16px;letter-spacing:.5px}}
.brand-text .dim{{color:var(--text-mute);font-weight:500}}
.crumbs{{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--text-dim);padding-left:16px;border-left:1px solid var(--border)}}
.crumbs a{{color:var(--text-mute);text-decoration:none}}.crumbs a:hover{{color:var(--ch)}}.crumbs b{{color:var(--text)}}
.hero{{padding:34px 28px 26px;border-bottom:1px solid var(--border-soft);background:linear-gradient(180deg,rgba(134,239,172,.05),transparent)}}
.hero-in{{max-width:1180px;margin:0 auto}}
.hero .id{{font-family:'Space Grotesk';font-weight:700;font-size:13px;letter-spacing:.14em;color:var(--ch)}}
.hero h1{{font-size:30px;margin:10px 0 12px}}
.hero p{{color:var(--text-dim);max-width:86ch;margin:0 0 16px;font-size:14.5px}}
.tags{{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:14px}}
.tags span{{font-size:12px;padding:4px 11px;border-radius:7px;background:var(--bg-card);border:1px solid var(--border-soft);color:var(--text-dim)}}
.kpis{{display:flex;flex-wrap:wrap;gap:10px;margin-top:6px}}
.kpi{{background:var(--bg-card);border:1px solid var(--border-soft);border-radius:10px;padding:12px 18px;min-width:118px}}
.kpi .v{{font-family:'Space Grotesk';font-size:23px;font-weight:700;color:var(--ch);line-height:1.1}}
.kpi .l{{font-size:11.5px;color:var(--text-mute);margin-top:4px}}
.wrap{{max-width:1180px;margin:0 auto;padding:26px 28px 70px}}
.sec{{font-family:'Space Grotesk';font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--text-mute);margin:38px 0 13px;display:flex;align-items:center;gap:10px;scroll-margin-top:80px}}
.sec::after{{content:"";flex:1;height:1px;background:var(--border-soft)}}
.sec:first-child{{margin-top:0}}
.note{{background:var(--bg-card);border:1px solid var(--border-soft);border-left:2px solid var(--amber);border-radius:0 10px 10px 0;padding:14px 17px;color:var(--text-dim);font-size:13.5px;margin-bottom:12px}}
.note b{{color:var(--text)}}
.note.n-ok{{border-left-color:var(--ok)}} .note.n-warn{{border-left-color:var(--amber)}}
.note.n-red{{border-left-color:var(--red)}} .note.n-info{{border-left-color:var(--blue)}}
.note ul{{margin:8px 0 0;padding-left:20px}} .note li{{margin:4px 0}}
.tblw{{overflow-x:auto}}
.tbl{{width:100%;border-collapse:collapse;background:var(--bg-card);border:1px solid var(--border-soft);border-radius:12px;overflow:hidden;font-size:13px}}
.tbl th{{text-align:left;padding:10px 14px;background:var(--bg-elev);color:var(--text-mute);font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;font-weight:700}}
.tbl td{{padding:9px 14px;border-top:1px solid var(--border-soft);color:var(--text-dim);vertical-align:top}}
.tbl td.mono,.mono{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;color:var(--text)}}
.tbl td.dim{{color:var(--text-mute)}} .tbl td.w{{color:var(--text);font-weight:600;white-space:nowrap}}
.tbl td.fix{{color:var(--ch)}}
.sp-grid{{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}}
.sp-card{{background:var(--bg-card);border:1px solid var(--border-soft);border-radius:12px;padding:15px 17px;border-top:2px solid var(--text-mute)}}
.sp-card.sp-d{{border-top-color:var(--ch)}} .sp-card.sp-a{{border-top-color:var(--pink)}}
.sp-name{{font-family:'Space Grotesk';font-weight:700;font-size:15px}}
.sp-bar{{height:6px;border-radius:4px;background:var(--bg-elev);margin:10px 0 7px;overflow:hidden}}
.sp-bar i{{display:block;height:100%;background:var(--ch)}}
.sp-a .sp-bar i{{background:var(--pink)}} .sp-m .sp-bar i{{background:var(--text-mute)}}
.sp-meta{{font-size:12.5px;color:var(--text-dim)}} .sp-note{{font-size:12px;color:var(--text-mute);margin-top:5px}}
.blk{{background:var(--bg-card);border:1px solid var(--border-soft);border-radius:var(--radius);padding:18px 20px;margin-bottom:14px;border-left:3px solid var(--border)}}
.blk.v-keep{{border-left-color:var(--ok)}} .blk.v-trim{{border-left-color:var(--amber)}}
.blk.v-cut{{border-left-color:var(--red);opacity:.8}} .blk.v-svc{{border-left-color:var(--text-mute);opacity:.72}}
.b-head{{display:flex;align-items:center;gap:11px;flex-wrap:wrap;margin-bottom:8px}}
.b-n{{font-family:'Space Grotesk';font-weight:700;font-size:12px;color:var(--bg);background:var(--ch);width:24px;height:24px;border-radius:7px;display:grid;place-items:center;flex-shrink:0}}
.b-tc{{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;color:var(--ch)}}
.b-head h3{{font-size:16.5px;flex:1;min-width:200px}}
.b-sp{{font-size:11.5px;padding:3px 9px;border-radius:6px;background:var(--bg-elev);border:1px solid var(--border-soft);color:var(--text-dim)}}
.b-sp.sp-d{{color:var(--ch)}} .b-sp.sp-a{{color:var(--pink)}}
.b-vd{{font-size:12.5px;padding:7px 12px;border-radius:8px;margin-bottom:9px}}
.vb-keep{{background:rgba(74,222,128,.09);color:var(--ok)}} .vb-trim{{background:rgba(252,211,77,.09);color:var(--amber)}}
.vb-cut{{background:rgba(248,113,113,.09);color:var(--red)}} .vb-svc{{background:var(--bg-elev);color:var(--text-mute)}}
.b-role{{font-size:11.5px;color:var(--text-mute);letter-spacing:.05em;text-transform:uppercase;margin-bottom:8px}}
.b-sum{{margin:0 0 10px;color:var(--text-dim);font-size:13.8px}}
.b-q{{margin:0 0 11px;padding:9px 15px;border-left:2px solid var(--cl-red);background:var(--bg-elev);border-radius:0 8px 8px 0;color:var(--text);font-size:13.5px;font-style:italic}}
.b-lbl{{font-family:'Space Grotesk';font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--text-mute);margin-bottom:7px}}
.b-facts ul{{margin:0 0 11px;padding-left:19px;color:var(--text-dim);font-size:13px}} .b-facts li{{margin:3px 0}}
.b-risk{{font-size:13px;color:var(--amber);background:rgba(252,211,77,.07);border-radius:8px;padding:8px 13px;margin-bottom:11px}}
.b-viz{{margin-top:14px;padding-top:14px;border-top:1px solid var(--border-soft)}}
.v-grid{{display:grid;gap:11px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}}
.v-card{{background:var(--bg-elev);border:1px solid var(--border-soft);border-radius:11px;padding:13px 15px;border-top:2px solid var(--blue)}}
.v-card.k-full{{border-top-color:var(--violet)}} .v-card.k-tl{{border-top-color:var(--ch)}} .v-card.k-num{{border-top-color:var(--amber)}}
.v-card.k-typo{{border-top-color:var(--pink)}} .v-card.k-fix{{border-top-color:var(--red)}} .v-card.k-none{{opacity:.72}}
.v-top{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px}}
.v-kind{{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--text-mute)}}
.v-tc{{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:var(--ch)}}
.v-eff{{font-size:10px;padding:2px 7px;border-radius:5px;margin-left:auto}}
.eff-l{{background:rgba(74,222,128,.13);color:var(--ok)}} .eff-m{{background:rgba(252,211,77,.13);color:var(--amber)}} .eff-h{{background:rgba(248,113,113,.13);color:var(--red)}}
.v-card h4{{font-size:14px;margin-bottom:6px}} .v-card p{{margin:0 0 8px;font-size:13px;color:var(--text-dim)}}
.v-lbl{{font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--text-mute);margin-bottom:4px}}
.v-data ul{{margin:0 0 8px;padding-left:18px;font-size:12.5px;color:var(--text)}} .v-data li{{margin:2px 0}}
.v-trig{{font-size:12px;color:var(--text-mute);font-style:italic;margin-bottom:7px}}
.v-style{{font-size:12.5px;color:var(--text-dim);margin-bottom:7px}}
.v-why{{font-size:12.5px;color:var(--text-dim);padding-top:7px;border-top:1px solid var(--border-soft)}}
.v-rec{{margin-top:11px;font-size:13px;color:var(--ch);background:rgba(134,239,172,.07);border-radius:8px;padding:9px 13px}}
.pal{{display:flex;flex-wrap:wrap;gap:10px}}
.sw{{border-radius:10px;padding:13px 15px;min-width:132px;border:1px solid var(--border-soft);font-size:12px}}
.sw b{{display:block;font-family:ui-monospace,Menlo,monospace;font-size:12.5px;margin-bottom:3px}}
.tr-wrap{{background:var(--bg-card);border:1px solid var(--border-soft);border-radius:12px;overflow:hidden}}
.tr-row{{display:flex;gap:16px;padding:11px 15px;border-bottom:1px solid var(--border-soft);align-items:baseline}}
.tr-row:last-child{{border-bottom:0}}
.tr-meta{{flex-shrink:0;width:210px;display:flex;gap:9px;align-items:baseline;flex-wrap:wrap}}
.tr-tc{{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--ch)}}
.tr-who{{font-size:12.5px;font-weight:600}}
.tr-row.sp-d .tr-who{{color:var(--ch)}} .tr-row.sp-a .tr-who{{color:var(--pink)}} .tr-row.sp-m .tr-who{{color:var(--text-mute)}}
.tr-dur{{font-size:11px;color:var(--text-mute)}}
.tr-text{{flex:1;color:var(--text-dim);font-size:13.5px}}
pre.ch{{background:var(--bg-elev);border-radius:9px;padding:13px 16px;margin:9px 0 0;font-family:ui-monospace,Menlo,monospace;font-size:12.5px;color:var(--text);overflow-x:auto;line-height:1.7}}
.foot{{margin-top:40px;padding-top:18px;border-top:1px solid var(--border-soft);color:var(--text-mute);font-size:12px}}
{EXTRA_CSS}
@media(max-width:760px){{.topbar{{padding:12px 16px}}.crumbs{{display:none}}.hero{{padding:24px 16px 20px}}.wrap{{padding:20px 16px 60px}}.tr-meta{{width:100%}}.tr-row{{flex-direction:column;gap:5px}}.pt-txt{{padding-left:0}}}}
</style>
{PORTAL_HEAD if a.portal else ''}
</head>
<body>

<div class="topbar">
  <a href="https://yt.rya.ae/" class="brand"><div class="brand-mark">EV</div><div class="brand-text">yt<span class="dim">.rya.ae</span></div></a>
  {crumbs}
</div>

<section class="hero"><div class="hero-in">
  <div><span class="id">YTEVO02</span></div>
  <h1>Манифест платформы «Эволюция» — структура и графика</h1>
  <div class="tags">
    <span>Съёмка 04.09.2026</span><span>23:09 материала → {mmss(mont["total"])} чистовика</span>
    <span>Ракурс A — крупный Дарьи · ракурс B — общий план</span><span>Разбор R.Y.A Media Lab</span>
  </div>
  <p>{e(canon.get("logline", ""))}</p>
  <div class="kpis">
    <div class="kpi"><div class="v">{mmss(mont["total"])}</div><div class="l">чистовик по листу</div></div>
    <div class="kpi"><div class="v">≈{mmss(mont["total_trimmed"])}</div><div class="l">после подрезки пауз</div></div>
    <div class="kpi"><div class="v">{len(mont["pieces"])} / {mont["n_say_parts"]}</div><div class="l">кусков / склеек речи</div></div>
    <div class="kpi"><div class="v">{screens}</div><div class="l">экранов графики</div></div>
    <div class="kpi"><div class="v">{n_new}+{n_client}</div><div class="l">мокапов 4K + слайдов клиента</div></div>
  </div>
  <div class="toc">
    <a href="#links">Материалы</a><a href="#story">Рассказ ↔ экран</a><a href="#chapters">Главы</a><a href="#scene2">Вторая сцена</a><a href="#montage">Монтажный лист</a><a href="#screens">Все экраны</a>
    <a href="#findings">Находки</a><a href="#source">Исходник</a><a href="#voices">Голоса</a>
    <a href="#blocks">Блоки исходника</a><a href="#style">Язык клиента</a><a href="#transcript">Транскрипт</a>
  </div>
</div></section>

<div class="wrap">

  {LINKS_BLOCK}

  <div class="sec" id="story">Сценарий чистовика · рассказ ↔ экран</div>
  {HOW_TO_READ}
  <div class="note n-info"><b>Где я отошёл от плана разбора и почему:</b><ul class="devs">{devs}</ul></div>
  {build_story(mont, man, a.mock_rel, a.full_res_thumbs)}

  <div class="sec" id="chapters">Главы для YouTube</div>
  {build_chapters(mont)}

  {scene2}

  <div class="sec">Технический слой и разбор</div>
  <details class="dz"><summary>Монтажный лист — склейки, файлы, паузы, стыки</summary>
  <div class="sec" id="montage">Структура чистовика — монтажный лист</div>
  <div class="note n-ok"><b>Это рабочая структура видео.</b> Порядок — тот, на котором независимо сошлись
  пять линз разбора: холодный старт с опроса подростков → кто мы → опора → логика советов → новость
  «Эволюция ТВ» → продукт → зачем → смысл → призыв → финал. Каждая склейка привязана к пословным
  таймкодам: начало первого слова и конец последнего плюс до 0,3 с воздуха. Для каждой указаны файл
  и смещение внутри него в обоих ракурсах, какой ракурс брать и паузы к подрезке. Цветная лента — хронометраж по актам, клик ведёт к куску.</div>
  {build_montage(mont)}
  </details>

  <details class="dz"><summary>Все экраны графики — варианты A/B и где стоят</summary>
  <div class="sec" id="screens">Экраны графики — {screens} шт.</div>
  <div class="note n-info">Отрисованы по правилам скилла <b>infographic</b>: нативные 3840×2160, текст версткой,
  плашки с альфой для Premiere, метка DRAFT. Язык — с презентации клиента: Gilroy Black капсом, их логотип
  (вырезан из PDF на 600 dpi), #0B1220 / #F0EFEA / #D0021B, призрачные буквы, точки синий→красный.
  Слайды клиента с указами, СССР и «Путём России» не перерисованы — они уже утверждены и берутся как есть, в 4K.
  На ключевые экраны — по два варианта, A и B. Плашки показаны поверх реального кадра съёмки.
  Раскладка проверена локально, без облака: title-safe 5 % и переполнение блоков
  ({"все экраны прошли" if n_qc_bad == 0 else f"замечания у {n_qc_bad} — подписаны красным"}).
  «2 из 60» собран по методу скилла <b>dataviz</b>: форма — герой-цифра плюс юнит-чарт, а не график;
  акцент клиента против приглушённого; валидатор — различимость для дальтоников ΔE 13,8 при пороге 8,
  контраст ≥3:1; вторичное кодирование — заливка против контура и прямые подписи. {"Клик по картинке — крупное превью; 4K-файлы лежат в проекте на SSD." if a.full_res_thumbs else "Клик по картинке — PNG в 4K."}</div>
  {build_gallery(gal_src, man, a.mock_rel, a.full_res_thumbs)}
  </details>

  <details class="dz"><summary>Разбор исходника — находки, файлы, голоса, блоки, язык клиента, транскрибация</summary>
  <div class="sec" id="findings">Что нашли в исходнике</div>
  {"".join(findings)}

  <div class="sec" id="source">Исходный материал</div>
  <div class="tblw"><table class="tbl">
    <thead><tr><th>Файл</th><th>Длительность</th><th>На сквозной таймлинии</th><th>Запись (UTC)</th><th>Размер</th></tr></thead>
    <tbody>{clip_rows}</tbody>
  </table></div>
  <div class="note n-info" style="margin-top:12px"><b>Вторая сцена — та же камера A (Sony A7 III), позже в тот же день.</b>
  Снята в тот же день позже, одной непрерывной записью; C0015 — хвост того же рулона.</div>
  <div class="tblw"><table class="tbl">
    <thead><tr><th>Файл</th><th>Длительность</th><th>На таймлинии сцены</th><th>Запись (UTC)</th><th>Размер</th></tr></thead>
    <tbody>{clip_rows2}</tbody>
  </table></div>
  <div class="note n-warn" style="margin-top:12px">{SEAM_NOTE}</div>

  <div class="sec" id="voices">Кто говорит</div>
  <div class="sp-grid">{spk_rows}{spk2}</div>
  <div class="note n-ok" style="margin-top:12px">{angles_note}</div>

  <div class="sec" id="blocks">Блоки исходника — диагноз</div>
  <div class="note n-info">Двенадцать смысловых блоков в порядке съёмки, с вердиктом монтажа. Это диагноз
  исходника; рабочая структура — монтажный лист выше, каждый его кусок ссылается на свой блок.</div>
  {build_blocks(canon, viz_by_n)}

  <div class="sec" id="style">Визуальный язык клиента</div>
  <div class="note n-info">Снят с их презентации «Ценностный суверенитет России» (18 слайдов, 1920×1080,
  автор — Анастасия Григорьева): тяжёлый гротеск капсом, «призрачная» цифра года за заголовком,
  трёхколонник «ВЫЗОВ ВРЕМЕНИ → ГОСУДАРСТВЕННЫЙ ОТВЕТ → СМЫСЛ УКАЗА», таймлайн с градиентными точками,
  уставная кириллица с красными буквицами на слайде-расшифровке СССР.</div>
  <div class="pal">
    <div class="sw" style="background:#0B1220;color:#fff"><b>#0B1220</b>тёмный фон</div>
    <div class="sw" style="background:#F0EFEA;color:#111"><b>#F0EFEA</b>светлый фон</div>
    <div class="sw" style="background:#D0021B;color:#fff"><b>#D0021B</b>акцент, буквицы</div>
    <div class="sw" style="background:#FF4D5E;color:#111"><b>#FF4D5E</b>красный для мелкого текста на тёмном</div>
    <div class="sw" style="background:#2C3E8F;color:#fff"><b>#2C3E8F</b>синий градиента</div>
  </div>

  <div class="note n-info" style="margin-top:18px"><b>Сверка и критика ниже сделаны 11.09 — до прихода общего плана B.</b>
  Пункты про «Анастасия вне кадра», «камеры B нет», плашку «ЗА КАДРОМ» и «мёртвый экран» закрыты 15.09: Анастасия
  в кадре на общем плане, её реплики в монтажном листе стоят на ракурсе B. Пункты про стыки клипов закрыты сверкой
  по звуку общего плана (три шва непрерывны, на C0008/C0009 пропало 3,16 с).</div>
  {build_issues(an.get("check"), "Сверка разбора: что проверено построчно", "ok", "check")}
  {build_issues(an.get("critic"), "Чего в разборе не хватало", "warn", "critic")}

  <div class="sec" id="transcript">Полная транскрибация по ролям</div>
  <div class="note n-info">Дословно, без правок. Таймкоды — по сквозной таймлинии съёмочного дня
  (C0005…C0009 встык). Роли — pyannote 3.1; в постановочной части 00:00–01:11 голоса накладываются,
  там разметка ролей условна.</div>
  <div class="tr-wrap">{build_transcript(words)}</div>

  </details>

  <div class="foot">
    <b>YTEVO02 · Манифест платформы «Эволюция».</b>
    Транскрибация — whisper large-v3 (MLX) с пословными таймкодами, 2 296 слов, 238 сегментов.
    Роли — pyannote/speaker-diarization-3.1, три прогона (auto, максимум 4, ровно 2) для проверки числа голосов.
    Фактура сверена с сайтом эволюция.рус и презентацией «Ценностный суверенитет России».
    Смысловой разбор — пять независимых линз и синтез; монтажный лист, 4K-мокапы, проверка раскладки
    и эта страница собраны локально скриптами в 00_Setup/. Собрано R.Y.A Media Lab.
  </div>
</div>
{STORY_JS}
{PORTAL_BODY if a.portal else ''}
</body>
</html>
"""
    out = Path(a.out)
    out.write_text(doc, encoding="utf-8")
    print(f"written: {out}  ({len(doc)} bytes)")


if __name__ == "__main__":
    main()
