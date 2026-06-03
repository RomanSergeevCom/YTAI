#!/usr/bin/env python3
"""civ_recon_html.py — generate the civilizatia.com domain-recon findings page.

Outputs:
  1) ~/RYA/yt-rya-ae/web/civ/index.html        -> deploys to yt.rya.ae/civ
     (portal repo RomanSergeevCom/yt-rya-ae; push web/** -> GH Actions rsync
      -> forgotten-cable:/root/rya/yt-content/ -> rya-caddy behind Cloudflare)
  2) <recon>/findings.md                       -> markdown report
  3) <recon>/civ_domain_findings.json          -> merged machine-readable data

Data source: deterministic multi-host crawl (/tmp/civ_sweep.py) + targeted
/file/ crawl + 12-agent verification workflow (wf_1a6b9685-e80). All media
HEAD-verified HTTP 200. See README for regeneration.
"""
import json, os, html, datetime

RECON = "/Volumes/RYA Beige/YTCIV/00_Reference_Analysis/_domain_recon"
PORTAL = os.path.expanduser("~/RYA/yt-rya-ae/web/civ")
GEN_DATE = "2026-06-03"

# ---------------- DATA ----------------
DOWNLOADABLE = [
  {"group":"«Интродакция Цивилизации» — фильм (~7:53, 4K 60fps)", "host":"imporatia.civilizatia.com",
   "page":"https://imporatia.civilizatia.com/file/introdakciya-civilizacii-6qzmf",
   "note":"Несписочная /file/ страница (открывается только по прямому слагу). 5 вариантов качества — это ОДНО видео. 2160p уже скачан.",
   "files":[
     {"q":"2160p (4K)","url":"https://imporatia.civilizatia.com/uploads/all/4c/a0/b5/4ca0b5c1722bd12967cf942be5165f68.mp4","mb":1135.3,"got":True},
     {"q":"1080p","url":"https://imporatia.civilizatia.com/uploads/all/4e/40/85/4e4085b1d99612664ded09518a1b807e.mp4","mb":234.4},
     {"q":"720p","url":"https://imporatia.civilizatia.com/uploads/all/c4/70/2a/c4702ab6dd5c207cc4cbd553c06958f2.mp4","mb":121.3},
     {"q":"480p","url":"https://imporatia.civilizatia.com/uploads/all/66/a8/7f/66a87f66889fd8ff76308689c1027c78.mp4","mb":64.8},
     {"q":"360p","url":"https://imporatia.civilizatia.com/uploads/all/de/9e/8f/de9e8f85cb06df9d6dbdd6c330aa33c8.mp4","mb":42.2},
   ]},
  {"group":"Promo-ролик «Цивилизация»", "host":"new.civilizatia.com",
   "page":"https://new.civilizatia.com/",
   "note":"Встроен на главной (sx-video-modal). Одно разрешение.",
   "files":[
     {"q":"mp4","url":"https://new.civilizatia.com/assets/4047ff06/media/promo.mp4?v=1778102322","mb":127.2},
   ]},
  {"group":"CIV_FLY — интро-облёт (фон логин-лендинга)", "host":"civilizatia.com",
   "page":"https://civilizatia.com/",
   "note":"Один и тот же клип в 2 форматах (фоновое видео на закрытом лендинге).",
   "files":[
     {"q":"mp4 720p","url":"https://civilizatia.com/video/CIV_FLY_mp4.mp4","mb":24.2},
     {"q":"webm 720p","url":"https://civilizatia.com/video/CIV_FLY_50_720p.webm","mb":4.7},
   ]},
]

AUDIO = [
  {"title":"Martin Gore — Vervet (фоновая музыка лендинга, 128k −4dB)","url":"https://civilizatia.com/audio/Martin-Gore-Vervet_128-4db.mp3","mb":8.1},
]

YOUTUBE = {
  "channel":"https://youtube.com/channel/UCiLuLvN1FoXX2gJ_SnXc8og",
  "groups":[
    {"where":"imporatia · отзывы в «книге» (/book/.../rekongiciya)","ids":["3oNKZLZWwwo","60VYXd9RVJ0","h3TjfE0DvIY"]},
    {"where":"aqwa · фестивали плавания (новости)","ids":["ByUYveO347c","GOc_JJWKUAE","9_9T4UaZisE","nZ_49o7jwSA","xLuDUGWT41A"]},
  ]
}

SUBDOMAINS = [
  {"host":"civilizatia.com","ip":"5.101.114.75","title":"Цивилизация (апекс)","state":"login","tag":"Лендинг + логин",
   "desc":"Главный сайт-визитка. «Цивилизация» — предприятие для сбалансированного развития личности, бизнеса и общества. За паролем — закрытая зона участников. Фоновое видео CIV_FLY + музыка Martin Gore.","media":"2 видео · 1 аудио"},
  {"host":"imporatia.civilizatia.com","ip":"45.135.92.150","title":"Civilization — environment of success","state":"open","tag":"«Книга» / манифест",
   "desc":"Публичная иерархическая «книга»-энциклопедия (146 глав /book + /stati) на эзотерико-философском новоязе. Здесь же лежит фильм «Интродакция» (несписочная /file/). 3 встроенных YouTube-отзыва.","media":"1 фильм (5 кач.) · 3 YT"},
  {"host":"constantia.civilizatia.com","ip":"45.135.92.150","title":"Civilization — environment of success","state":"mirror","tag":"Зеркало imporatia",
   "desc":"Полная копия «книги» imporatia (canonical → imporatia, 146 глав). Своего медиа нет.","media":"—"},
  {"host":"new.civilizatia.com","ip":"45.135.92.150","title":"Цивилизация (корпоративный)","state":"dev","tag":"Корп-сайт / staging",
   "desc":"Корпоративный сайт «Уникальные решения, передовые разработки, совместный рост». © Олег Леонов. Контент — заглушки (новый билд). Promo-ролик 127 МБ на главной.","media":"1 промо-видео"},
  {"host":"aqwa.civilizatia.com","ip":"45.135.92.150","title":"Acceleration Civilization Aqwa","state":"open","tag":"НКО · плавание",
   "desc":"Алиас → acceleratia.aqwa. Благотворительный проект «Акселерация Цивилизация Аква» — адаптивное плавание/гидрореабилитация для особенных детей, фестивали «Сообщество первых». Видео — на YouTube.","media":"YouTube-канал"},
  {"host":"acceleratia.aqwa.civilizatia.com","ip":"45.135.92.150","title":"Acceleration Civilization Aqwa","state":"open","tag":"НКО · плавание (canon)",
   "desc":"Канонический хост НКО. 4 новости с YouTube-роликами фестивалей, портреты тренеров и семей. Спонсоры: atlantika, ФОК Газпром.","media":"4 YouTube-ролика"},
  {"host":"competentia.civilizatia.com","ip":"45.135.92.150","title":"Competentia","state":"login","tag":"Методология · логин",
   "desc":"Портал структурированных документов (/dokumenty: Генеральная/Специальная/Панеральная). Реальный контент за логином (Номен/Пароль, POST /~login). Видны и SkeekS-UPA админ-роуты.","media":"—"},
  {"host":"comporatia.civilizatia.com","ip":"45.135.92.150","title":"Comporatia","state":"login","tag":"Скелет · логин",
   "desc":"Ранний каркас SkeekS. Дерево документов — пустые заглушки («текст ещё не написан»). Логин Номен/Пароль. Плеер видео/аудио подключён в шаблоне, но медиа нет.","media":"—"},
  {"host":"congress.civilizatia.com","ip":"45.135.92.150","title":"Civilizatia Congress","state":"dev","tag":"Конгресс · стройка",
   "desc":"Почти пустой/недостроенный сайт «конгресс/манифест». Все /dokumenty — заглушки. Медиа нет, контактов проекта нет (только футер вендора CMS).","media":"—"},
  {"host":"proponatia.civilizatia.com","ip":"45.135.92.150","title":"Proponatia","state":"dev","tag":"Манифест · каркас",
   "desc":"Каркас «манифеста». Один тестовый пост. Пустые <video>/<audio> плейсхолдеры без src. Медиа нет.","media":"—"},
  {"host":"ligata.civilizatia.com","ip":"45.135.92.150","title":"Легион (Legion)","state":"login","tag":"Закрытая платформа",
   "desc":"Полностью закрытая платформа участников «Легион». Вход по Телефон+Пароль, catch-all отдаёт логин-сплэш на любой путь. Контент (вкл. возможные видео/книги) недоступен без аккаунта.","media":"за логином"},
  {"host":"recruitment.civilizatia.com","ip":"45.135.92.150","title":"Civilizatia Recruitment","state":"open","tag":"HR-воронка",
   "desc":"Лендинг найма (роль «HR-директор», A/B варианты /hr-director и /hr-director-v1). Медиа — только графика.","media":"—"},
  {"host":"mail.civilizatia.com","ip":"5.101.114.75","title":"Coming Soon","state":"idle","tag":"Заглушка",
   "desc":"Пустая страница-заглушка хостинга (fastvps). Контента нет.","media":"—"},
]

PEOPLE = [
  ("Олег Леонов","Основатель / правообладатель (© на апексе и new.civilizatia.com)"),
  ("Viktor Remez","Автор отзыва в «книге» (imporatia)"),
  ("Sergej Cherenkov","Автор отзыва в «книге» (imporatia)"),
  ("Александр Семёнов","Автор отзыва в «книге» (imporatia)"),
  ("Никифоров Даниил, Е. Шевченко, В. Тарасова, В. Алексеев","Команда/тренеры НКО Aqwa"),
]
CONTACTS = [("Телефон","+7 495 981 3333"),("E-mail","civilizatia@civilizatia.com")]

STATE_LABEL = {"open":"открыт","login":"логин-волл","dev":"в разработке","mirror":"зеркало","idle":"заглушка"}
STATE_CLASS = {"open":"live","login":"dev","dev":"dev","mirror":"idle","idle":"idle"}

# ---------------- HTML ----------------
def esc(s): return html.escape(str(s))

def dl_section():
    rows=[]
    for g in DOWNLOADABLE:
        files="".join(
          f"""<div class="file{' got' if f.get('got') else ''}">
            <span class="q">{esc(f['q'])}</span>
            <span class="sz">{f['mb']:.1f} МБ</span>
            <a class="dl" href="{esc(f['url'])}" target="_blank" rel="noopener">скачать ↓</a>
            <button class="cp" data-u="{esc(f['url'])}">копировать URL</button>
            {'<span class="got-badge">✓ скачано</span>' if f.get('got') else ''}
          </div>""" for f in g['files'])
        rows.append(f"""<div class="dl-group">
          <div class="dl-head"><div><div class="dl-title">{esc(g['group'])}</div>
          <div class="dl-host">{esc(g['host'])} · <a href="{esc(g['page'])}" target="_blank" rel="noopener">страница ↗</a></div></div></div>
          <div class="dl-note">{esc(g['note'])}</div>
          <div class="files">{files}</div></div>""")
    return "".join(rows)

def yt_section():
    cards=[]
    for grp in YOUTUBE["groups"]:
        chips="".join(f'<a class="yt" href="https://youtu.be/{esc(i)}" target="_blank" rel="noopener">▶ {esc(i)}</a>' for i in grp["ids"])
        cards.append(f'<div class="yt-grp"><div class="yt-where">{esc(grp["where"])}</div><div class="yt-chips">{chips}</div></div>')
    return f'<div class="yt-channel">YouTube-канал проекта (Aqwa): <a href="{esc(YOUTUBE["channel"])}" target="_blank" rel="noopener">{esc(YOUTUBE["channel"])}</a></div>' + "".join(cards)

def sub_cards():
    out=[]
    for s in SUBDOMAINS:
        out.append(f"""<div class="ch">
          <div class="ch-top"><div>
            <div class="ch-id">{esc(s['tag'])}</div>
            <div class="ch-name">{esc(s['host'])}</div>
            <div class="ch-sub">{esc(s['title'])} · {esc(s['ip'])}</div>
          </div><div class="ch-state {STATE_CLASS[s['state']]}">{STATE_LABEL[s['state']]}</div></div>
          <div class="ch-body">{esc(s['desc'])}</div>
          <div class="ch-foot"><span class="media-pill">{esc(s['media'])}</span></div>
        </div>""")
    return "".join(out)

def people_rows():
    return "".join(f'<div class="pr"><b>{esc(n)}</b><span>{esc(r)}</span></div>' for n,r in PEOPLE)

n_live=sum(1 for s in SUBDOMAINS if s['state']!='idle')
n_video_files=sum(len(g['files']) for g in DOWNLOADABLE)
total_gb=sum(f['mb'] for g in DOWNLOADABLE for f in g['files'])/1024
n_yt=sum(len(g['ids']) for g in YOUTUBE['groups'])

PAGE = f"""<!DOCTYPE html><html lang="ru"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>civ recon — yt.rya.ae</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:#0A1029;--bg-2:#111A45;--bg-card:#1B2557;--bg-elev:#26326B;--border:#3D4A8A;--border-soft:#2D386F;
--text:#fff;--text-dim:#D6DDF2;--text-mute:#94A0C8;--accent:#E4FF6E;--accent-2:#C9E852;--accent-ink:#0A1029;
--green:#4ADE80;--amber:#FCD34D;--red:#FF7A7F;--blue:#93C5FD;--radius:14px}}
*{{box-sizing:border-box}}html,body{{margin:0;background:var(--bg);color:var(--text);font-family:'Inter',sans-serif;font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased}}
h1,h2,h3{{font-family:'Space Grotesk','Inter',sans-serif;margin:0;letter-spacing:-0.01em}}a{{color:inherit;text-decoration:none}}
.topbar{{display:flex;align-items:center;justify-content:space-between;padding:14px 28px;border-bottom:1px solid var(--border);background:var(--bg-2);position:sticky;top:0;z-index:50;backdrop-filter:blur(10px)}}
.brand{{display:flex;align-items:center;gap:12px}}.brand-text{{font-family:'Space Grotesk';font-weight:700;font-size:16px;letter-spacing:.5px}}.brand-text .dim{{color:var(--text-mute);font-weight:500}}
.mark{{width:36px;height:36px;border-radius:9px;background:var(--accent);color:var(--accent-ink);display:grid;place-items:center;font-family:'Space Grotesk';font-weight:700;font-size:15px}}
.crumb{{font-size:12px;color:var(--text-mute)}}
.main{{padding:28px 32px 70px;max-width:1280px;margin:0 auto}}
.hero h1{{font-size:28px;font-weight:700;margin-bottom:6px}}.hero .sub{{color:var(--text-dim);max-width:760px}}
.hero .meta{{color:var(--text-mute);font-size:12px;margin-top:8px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:24px 0 30px}}
.kpi{{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px}}
.kpi .lbl{{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--text-mute);font-weight:600;margin-bottom:6px}}
.kpi .val{{font-family:'Space Grotesk';font-size:26px;font-weight:700}}
.kpi .val small{{font-size:13px;color:var(--text-mute);font-weight:500}}
.section{{margin-bottom:34px}}.section>h2{{font-size:18px;margin-bottom:6px}}
.section .lead{{color:var(--text-mute);font-size:13px;margin-bottom:16px}}
.dl-group{{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;margin-bottom:14px}}
.dl-title{{font-family:'Space Grotesk';font-weight:700;font-size:15px}}.dl-host{{font-size:12px;color:var(--text-mute);margin-top:2px}}.dl-host a{{color:var(--blue)}}
.dl-note{{font-size:12.5px;color:var(--text-dim);margin:10px 0 12px;padding-left:10px;border-left:2px solid var(--border)}}
.files{{display:flex;flex-direction:column;gap:8px}}
.file{{display:flex;align-items:center;gap:12px;background:var(--bg-2);border:1px solid var(--border-soft);border-radius:9px;padding:9px 12px;flex-wrap:wrap}}
.file.got{{border-color:rgba(74,222,128,.4)}}
.file .q{{font-family:'Space Grotesk';font-weight:600;min-width:90px}}
.file .sz{{color:var(--text-mute);min-width:80px;font-size:13px}}
.file .dl{{color:var(--accent-ink);background:var(--accent);padding:5px 12px;border-radius:7px;font-weight:600;font-size:12px}}
.file .cp{{background:var(--bg-elev);border:1px solid var(--border);color:var(--text-dim);padding:5px 10px;border-radius:7px;font-size:12px;cursor:pointer;font-family:inherit}}
.file .cp:hover{{color:var(--text)}}.file .cp.ok{{color:var(--green);border-color:var(--green)}}
.got-badge{{color:var(--green);font-size:12px;font-weight:600}}
.aud{{display:flex;align-items:center;gap:12px;background:var(--bg-card);border:1px solid var(--border);border-radius:9px;padding:11px 14px;margin-bottom:8px;flex-wrap:wrap}}
.aud .dl{{color:var(--accent-ink);background:var(--accent);padding:5px 12px;border-radius:7px;font-weight:600;font-size:12px}}
.yt-channel{{font-size:13px;margin-bottom:14px}}.yt-channel a{{color:var(--blue)}}
.yt-grp{{background:var(--bg-card);border:1px solid var(--border);border-radius:11px;padding:13px 16px;margin-bottom:10px}}
.yt-where{{font-size:12px;color:var(--text-mute);margin-bottom:9px}}.yt-chips{{display:flex;flex-wrap:wrap;gap:8px}}
.yt{{background:var(--bg-2);border:1px solid var(--border-soft);border-radius:7px;padding:6px 11px;font-size:12.5px;font-family:'Space Grotesk';color:var(--text-dim)}}.yt:hover{{color:#fff;border-color:var(--red)}}
.channels{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
.ch{{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);display:flex;flex-direction:column;overflow:hidden}}
.ch-top{{padding:15px 16px 12px;border-bottom:1px solid var(--border-soft);display:flex;justify-content:space-between;gap:10px;align-items:flex-start}}
.ch-id{{font-family:'Space Grotesk';font-weight:700;font-size:10px;letter-spacing:.08em;color:var(--accent);text-transform:uppercase;margin-bottom:4px}}
.ch-name{{font-size:13.5px;font-weight:600;word-break:break-all}}.ch-sub{{font-size:11px;color:var(--text-mute);margin-top:3px}}
.ch-state{{font-size:10px;font-weight:600;padding:3px 8px;border-radius:999px;border:1px solid var(--border);white-space:nowrap}}
.ch-state.live{{background:rgba(34,197,94,.1);color:#86EFAC;border-color:rgba(34,197,94,.25)}}
.ch-state.dev{{background:rgba(245,158,11,.1);color:#FCD34D;border-color:rgba(245,158,11,.25)}}
.ch-state.idle{{background:rgba(154,166,184,.08);color:var(--text-dim)}}
.ch-body{{padding:13px 16px;font-size:12.5px;color:var(--text-dim);flex:1}}
.ch-foot{{padding:11px 16px;border-top:1px solid var(--border-soft)}}
.media-pill{{font-size:11px;font-weight:600;color:var(--accent);background:rgba(228,255,110,.08);border:1px solid rgba(228,255,110,.2);padding:3px 9px;border-radius:6px}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.card{{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px}}
.card h3{{font-size:14px;margin-bottom:12px}}
.pr{{display:flex;justify-content:space-between;gap:14px;padding:8px 0;border-bottom:1px solid var(--border-soft);font-size:13px}}.pr:last-child{{border:0}}.pr span{{color:var(--text-mute);text-align:right;max-width:60%}}
.note{{background:rgba(228,255,110,.05);border:1px solid rgba(228,255,110,.18);border-radius:11px;padding:14px 16px;font-size:12.5px;color:var(--text-dim)}}
.note b{{color:var(--accent)}}
.foot{{margin-top:40px;padding-top:18px;border-top:1px solid var(--border);color:var(--text-mute);font-size:12px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}}
@media(max-width:920px){{.kpis,.channels,.two{{grid-template-columns:1fr 1fr}}}}
@media(max-width:620px){{.kpis,.channels,.two{{grid-template-columns:1fr}}}}
</style></head><body>
<div class="topbar"><div class="brand"><div class="mark">CIV</div>
<div class="brand-text">yt.rya.ae <span class="dim">/ civ · domain recon</span></div></div>
<div class="crumb">YTCIV · референс-разведка</div></div>
<div class="main">
<div class="hero">
  <h1>civilizatia.com — карта домена и все открытые ссылки</h1>
  <div class="sub">Разведка экосистемы проекта «Цивилизация» (Олег Леонов): {len(SUBDOMAINS)} поддоменов, все открытые медиа-файлы, скачиваемые видео и YouTube-ролики. Материал для стратегии канала <b>YTCIV</b>.</div>
  <div class="meta">Сгенерировано {GEN_DATE} · источник: двойной независимый обход + верификация 12-агентным workflow · все ссылки HEAD-проверены (HTTP 200)</div>
</div>
<div class="kpis">
  <div class="kpi"><div class="lbl">Поддоменов</div><div class="val">{len(SUBDOMAINS)} <small>/ {n_live} живых</small></div></div>
  <div class="kpi"><div class="lbl">Скачиваемых видео-файлов</div><div class="val">{n_video_files} <small>≈ {total_gb:.1f} ГБ</small></div></div>
  <div class="kpi"><div class="lbl">YouTube-роликов</div><div class="val">{n_yt} <small>+ канал</small></div></div>
  <div class="kpi"><div class="lbl">Открытых PDF / книг</div><div class="val">0</div></div>
</div>

<div class="section"><h2>📥 Скачиваемые видео (self-hosted)</h2>
<div class="lead">Прямые ссылки на файлы. «Интродакция» = одно видео в 5 качествах. Жми «скачать» или копируй URL.</div>
{dl_section()}
</div>

<div class="section"><h2>🎵 Аудио</h2>
{''.join(f'<div class="aud"><span class="q">{esc(a["title"])}</span><span class="sz" style="color:var(--text-mute)">{a["mb"]:.1f} МБ</span><a class="dl" href="{esc(a["url"])}" target="_blank" rel="noopener">скачать ↓</a></div>' for a in AUDIO)}
</div>

<div class="section"><h2>▶️ YouTube-ролики (встроены на поддоменах)</h2>
<div class="lead">Не self-hosted — отдаются с YouTube. Скачивать через yt-dlp при необходимости.</div>
{yt_section()}
</div>

<div class="section"><h2>🗺 Карта поддоменов</h2>
<div class="lead">Вся сеть civilizatia.com. Named-наврояз: Imporatia · Comporatia · Proponatia · Competentia · Constantia · Acceleratia · Ligata.</div>
<div class="channels">{sub_cards()}</div>
</div>

<div class="section"><div class="two">
  <div class="card"><h3>👤 Люди</h3>{people_rows()}</div>
  <div class="card"><h3>📞 Контакты</h3>{''.join(f'<div class="pr"><b>{esc(k)}</b><span>{esc(v)}</span></div>' for k,v in CONTACTS)}
  <h3 style="margin-top:16px">🧩 Что это</h3>
  <div style="font-size:12.5px;color:var(--text-dim)">Мульти-сайтовая экосистема одного проекта «Цивилизация»: публичная «книга»-манифест (imporatia/constantia), корп-визитка (апекс/new), закрытые платформы участников (ligata/competentia/comporatia), конгресс, HR-воронка (recruitment) и благотворительное НКО по плаванию для особенных детей (aqwa).</div>
  </div>
</div></div>

<div class="section"><div class="note">
<b>Замечания по полноте.</b> Видео «Интродакция» лежит на <b>несписочной</b> /file/ странице — её нет ни в sitemap, ни в навигации (ссылку дал заказчик). Значит на закрытых поддоменах (ligata, competentia, comporatia) и за логином апекса могут быть <b>ещё видео/книги</b>, недоступные без аккаунта. Открытых PDF/книг по всему домену — <b>0</b> (всё содержимое «книги» — HTML-текст, не файл). Прямой листинг директорий (/uploads, /video, /audio) закрыт (403).
</div></div>

<div class="foot"><div>yt.rya.ae · civ recon · для R.Y.A Media Lab FZE</div><div>{GEN_DATE}</div></div>
</div>
<script>
document.querySelectorAll('.cp').forEach(b=>b.addEventListener('click',async()=>{{
  try{{await navigator.clipboard.writeText(b.dataset.u);b.textContent='✓ скопировано';b.classList.add('ok');
  setTimeout(()=>{{b.textContent='копировать URL';b.classList.remove('ok')}},1400)}}catch(e){{}}
}}));
</script>
</body></html>"""

# ---------------- MARKDOWN ----------------
def md():
    L=[f"# civilizatia.com — разведка домена\n",
       f"_Сгенерировано {GEN_DATE}. Источник: двойной независимый обход + 12-агентный workflow. Все ссылки HEAD-проверены (HTTP 200)._\n",
       f"Сеть проекта «Цивилизация» (Олег Леонов): **{len(SUBDOMAINS)} поддоменов**, **{n_video_files} скачиваемых видео-файлов** (≈{total_gb:.1f} ГБ), **{n_yt} YouTube-роликов**, **0 открытых PDF**.\n",
       "## 📥 Скачиваемые видео (self-hosted)\n"]
    for g in DOWNLOADABLE:
        L.append(f"### {g['group']}\n`{g['host']}` — {g['page']}\n\n> {g['note']}\n")
        for f in g['files']:
            got=" ✓ скачано" if f.get('got') else ""
            L.append(f"- **{f['q']}** — {f['mb']:.1f} МБ{got}\n  {f['url']}")
        L.append("")
    L.append("## 🎵 Аудио\n")
    for a in AUDIO: L.append(f"- {a['title']} — {a['mb']:.1f} МБ\n  {a['url']}")
    L.append("\n## ▶️ YouTube\n")
    L.append(f"- Канал (Aqwa): {YOUTUBE['channel']}")
    for grp in YOUTUBE['groups']:
        L.append(f"- {grp['where']}: " + ", ".join(f"https://youtu.be/{i}" for i in grp['ids']))
    L.append("\n## 🗺 Поддомены\n")
    for s in SUBDOMAINS:
        L.append(f"- **{s['host']}** ({s['ip']}, {STATE_LABEL[s['state']]}) — {s['title']} · {s['tag']}: {s['desc']} [{s['media']}]")
    L.append("\n## 👤 Люди\n")
    for n,r in PEOPLE: L.append(f"- **{n}** — {r}")
    L.append("\n## 📞 Контакты\n")
    for k,v in CONTACTS: L.append(f"- {k}: {v}")
    L.append("\n## ⚠️ Полнота\n- «Интродакция» — несписочная /file/ страница; на закрытых поддоменах (ligata/competentia/comporatia) и за логином апекса могут быть ещё видео/книги.\n- Открытых PDF/книг — 0. Листинг директорий закрыт (403).")
    return "\n".join(L)

# ---------------- WRITE ----------------
os.makedirs(PORTAL, exist_ok=True)
os.makedirs(RECON, exist_ok=True)
open(os.path.join(PORTAL,"index.html"),"w",encoding="utf-8").write(PAGE)
open(os.path.join(RECON,"findings.md"),"w",encoding="utf-8").write(md())
merged={"generated":GEN_DATE,"downloadable_video":DOWNLOADABLE,"audio":AUDIO,"youtube":YOUTUBE,
        "subdomains":SUBDOMAINS,"people":PEOPLE,"contacts":CONTACTS}
json.dump(merged,open(os.path.join(RECON,"civ_domain_findings.json"),"w"),ensure_ascii=False,indent=2)
print("WROTE:")
print(" ", os.path.join(PORTAL,"index.html"))
print(" ", os.path.join(RECON,"findings.md"))
print(" ", os.path.join(RECON,"civ_domain_findings.json"))
print(f"KPIs: subdomains={len(SUBDOMAINS)} live={n_live} video_files={n_video_files} (~{total_gb:.1f}GB) youtube={n_yt}")
