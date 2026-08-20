#!/usr/bin/env python3
"""YTFP footage structure page — yt.rya.ae portal style (dark, YTFP violet)."""
import base64, json, os

SP = os.path.dirname(os.path.abspath(__file__))
local = json.load(open(os.path.join(SP, "local_meta.json")))
drive = json.load(open(os.path.join(SP, "drive_meta.json")))
vid_ids_path = os.path.join(SP, "video_ids.json")
VID_IDS = json.load(open(vid_ids_path)) if os.path.exists(vid_ids_path) else {}

DRIVE_IDS = {
    "00_Lyudmila_Chibireva_Home_Archive": "1vM2FOYo7hS0W9qkPy8Pxisd3gx1IOrhw",
    "01_Lyudmila_Chibireva_Family_Story_Part1": "168izVKmTZffF_630xCFJb1ApN0hiq-CT",
    "02_Lyudmila_Chibireva_Cochlear_Implant": "1a3cmGQbpwCwGt4fuRewI9H2sN4SfWipB",
    "03_Lyudmila_Chibireva_Family_Story_Part2": "1LHseQpcM0FnMJCPdgiYQg8lur5TS6MUN",
    "04_Center_BTS": "1noE3jTnFnbXUWJxmuRT8Yd3TqiY3-eSu",
    "05_Yulia_Reznik_Interview": "1iarR3nDPLht3LiDXoiYM1nwdcKRfTf5E",
    "06_Yulia_Reznik_Kids_Session": "1uzvLIoDnDqrHoaCS8W16zStcl2PUaV9J",
    "07_Tatyana_Nesterenko_Neuroplasticity": "1HCtdSCsx60-Gk5UqWCAh3BLdWtTK6Jwl",
    "08_Tatyana_Nesterenko_Center_Tour": "19RkqpRz-SnWUCN7hiP37Uy5Mkai6_OJU",
    "09_Maria_Gaidarova_Kids_Session": "1MzlzWe8nLXafov8PjWsKP7GHw9CgV_R8",
    "10_Maria_Gaidarova_Interview": "1YI147AUaeIRpuRtKtAUxqgwoF1OapN7g",
    "11_Tatyana_Kislyakova_Director_Vision": "1zPpmv5XKsxcFebod_9wrTeumLkyJA7aE",
    "12_Anastasia_Laricheva_Funding": "1FJpFViAoGq5daUv_N4528HN22zWXMUXb",
    "13_Olga_Gritsay_Legal_Rights": "1NaCoUNiteSIezbkJZKereZUw8zrM2PyO",
}

RU = {
    "00_Lyudmila_Chibireva_Home_Archive": (
        "Людмила Чибирева — домашний видеоархив",
        "Вертикальные съёмки с телефона из семейного архива, разложены по датам (декабрь 2023 — сентябрь 2025). Бытовые сцены дома и на прогулках — архивный материал для истории семьи."),
    "01_Lyudmila_Chibireva_Family_Story_Part1": (
        "Людмила Чибирева — семейная история, часть 1",
        "Основная съёмка истории семьи (Sony ZV-E1): длинные интервью-подходы дома. В подпапке Youtube — смонтированный ролик YTFP01_v3, в Audio — звук с рекордера."),
    "02_Lyudmila_Chibireva_Cochlear_Implant": (
        "Людмила Чибирева — кохлеарный имплант",
        "Съёмочный день про кохлеарный имплант: длинные подходы в центре (Sony ZV-E1). Внутри Audio и расшифровки в Transcripts."),
    "03_Lyudmila_Chibireva_Family_Story_Part2": (
        "Людмила Чибирева — семейная история, часть 2",
        "Досъём семейной истории: три клипа (Sony ZV-E1), включая длинное интервью ~40 минут."),
    "04_Center_BTS": (
        "Центр — жизнь и перебивки (BTS)",
        "43 коротких клипа из жизни центра (Sony ZV-E1): занятия, коридоры, детали, атмосфера. Основной источник перебивок (B-roll) для всех выпусков."),
    "05_Yulia_Reznik_Interview": (
        "Юлия Резник — интервью",
        "Два длинных подхода по 1–1,5 часа плюс короткий клип (Sony ZV-E1). Audio + пословные расшифровки per_clip."),
    "06_Yulia_Reznik_Kids_Session": (
        "Юлия Резник — занятие с детьми",
        "42 клипа занятия с детьми (Sony ZV-E1): упражнения, игры, работа специалиста с ребёнком. Много коротких перебивочных кусков."),
    "07_Tatyana_Nesterenko_Neuroplasticity": (
        "Татьяна Нестеренко — нейропластичность",
        "Интервью о нейропластичности (Sony ZV-E1): два съёмочных подхода, 5 клипов, включая два длинных по 45–70 минут. Audio + расшифровки."),
    "08_Tatyana_Nesterenko_Center_Tour": (
        "Татьяна Нестеренко — экскурсия по центру",
        "Проходка-экскурсия по центру с Татьяной Нестеренко (Sony ZV-E1): 10 клипов по помещениям и зонам."),
    "09_Maria_Gaidarova_Kids_Session": (
        "Мария Гайдарова — занятие с детьми",
        "18 клипов занятия Марии Гайдаровой с детьми (Sony ZV-E1). Audio + расшифровки per_clip."),
    "10_Maria_Gaidarova_Interview": (
        "Мария Гайдарова — интервью",
        "4 клипа (Sony ZV-E1), основной подход ~22 минуты. На Drive также полная транскрибация (*_transcription) и заготовка сборки в 00_Setup."),
    "11_Tatyana_Kislyakova_Director_Vision": (
        "Татьяна Кислякова — видение директора",
        "Интервью с директором центра (Sony ZV-E1): один длинный подход ~66 минут. Audio + расшифровки."),
    "12_Anastasia_Laricheva_Funding": (
        "Анастасия Ларичева — финансирование",
        "Интервью о финансировании (Sony FX3): основной подход ~16 минут + короткий клип. Audio + расшифровки."),
    "13_Olga_Gritsay_Legal_Rights": (
        "Ольга Грицай — юридические права",
        "Интервью о юридических правах (Sony FX3): 19 клипов, самый большой съёмочный день (~156 ГБ). Audio + пословные расшифровки per_clip."),
}

def gb(n):
    v = n / 1e9
    s = f"{v:.2f}".rstrip("0").rstrip(".") if v < 10 else f"{v:.1f}"
    return s + " ГБ"

def mins(sec):
    if sec >= 3600:
        return f"{int(sec//3600)}:{int(sec%3600//60):02d}:{int(sec%60):02d}"
    return f"{int(sec//60)}:{int(sec%60):02d}"

def cover(thumb_name, src):
    """Prefer picked cover frame; fall back to original mid-frame thumb."""
    key = thumb_name.rsplit(".", 1)[0]
    p = os.path.join(SP, "chosen", key + ".jpg")
    if not os.path.exists(p):
        p = os.path.join(SP, "thumbs" if src == "local" else "thumbs_drive", thumb_name)
    if not os.path.exists(p):
        return None
    return "data:image/jpeg;base64," + base64.b64encode(open(p, "rb").read()).decode()

all_folders = {}
for name, items in local.items():
    all_folders[name] = ("local", items)
for name, items in drive.items():
    all_folders[name] = ("drive", items)

order = sorted(DRIVE_IDS.keys())
tot_clips = sum(len(v[1]) for v in all_folders.values())
tot_dur = sum(i["dur"] for v in all_folders.values() for i in v[1])
tot_size = sum(i["size"] for v in all_folders.values() for i in v[1])

STATUS = {
    "01": ("st-drive", "только Drive"), "03": ("st-drive", "только Drive"),
    "10": ("st-drive", "только Drive"), "12": ("st-drive", "только Drive"),
}
# 07/13 are uploading to Drive; once every clip has a Drive ID they become "SSD + Drive"
for _num, _folder in (("07", "07_Tatyana_Nesterenko_Neuroplasticity"),
                      ("13", "13_Olga_Gritsay_Legal_Rights")):
    _clips = local[_folder]
    if not all(VID_IDS.get(f"{_num}_{c['rel']}") for c in _clips):
        STATUS[_num] = ("st-up", "SSD → Drive…")

cards = []
for name in order:
    src, items = all_folders[name]
    title, desc = RU[name]
    n, dur, size = len(items), sum(i["dur"] for i in items), sum(i["size"] for i in items)
    link = f"https://drive.google.com/drive/folders/{DRIVE_IDS[name]}"
    num = name[:2]
    st = STATUS.get(num)
    status_chip = f'<span class="fstate {st[0]}">{st[1]}</span>' if st else '<span class="fstate st-ok">SSD + Drive</span>'
    cells = []
    for it in items:
        cap = it["rel"].split("/")[-1]
        sub = it["rel"].rsplit("/", 1)[0] if "/" in it["rel"] else ""
        fid_v = VID_IDS.get(f"{num}_{it['rel']}")
        href = f"https://drive.google.com/file/d/{fid_v}/view" if fid_v else link
        data = cover(it["thumb"], src) if it["thumb"] else None
        img = (f'<img loading="lazy" src="{data}" alt="">' if data
               else '<div class="noimg">нет кадра</div>')
        subline = f'<span class="sub">{sub}</span>' if sub else ""
        cells.append(
            f'<figure><a href="{href}" target="_blank" rel="noopener">{img}</a>'
            f'<figcaption><a class="vlink" href="{href}" target="_blank" rel="noopener">{cap}</a>{subline}'
            f'<span>{mins(it["dur"])} · {gb(it["size"])}</span></figcaption></figure>')
    if num == "00" and len(cells) > 5:
        more = len(cells) - 5
        cells = cells[:5] + [
            f'<a class="more-tile" href="{link}" target="_blank" rel="noopener">'
            f'+{more} видео<span>смотреть в папке на Drive</span></a>']
    cards.append(f"""
<section class="fcard" id="f{num}">
  <div class="fhead">
    <span class="fnum">{num}</span>
    <h2>{title}</h2>{status_chip}
    <a class="dlink" href="{link}" target="_blank" rel="noopener">Google Drive ↗</a>
  </div>
  <div class="fcode">{name}</div>
  <p class="fdesc">{desc}</p>
  <div class="fstats">{n} видео · {mins(dur)} · {gb(size)}</div>
  <div class="grid">{''.join(cells)}</div>
</section>""")

toc = "".join(
    f'<a class="toc-chip" href="#f{n[:2]}"><b>{n[:2]}</b><span>{RU[n][0]}</span></a>'
    for n in order)

html = f"""<!DOCTYPE html>
<html lang="ru" data-channel="ytfp">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YTFP · Съёмочный материал — структура папок</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<style>
:root{{
  --bg:#0A0D16; --bg-2:#0F131E; --bg-card:#181D2B; --bg-elev:#232A3D;
  --border:#3A4258; --border-soft:#252B3D;
  --text:#F0F2F8; --text-dim:#C8CDD9; --text-mute:#8A92A8;
  --ch:#C4B5FD; --ch-ink:#0A0D16; --ch-soft:rgba(196,181,253,.14);
  --radius:14px;
}}
*{{box-sizing:border-box}}
html,body{{margin:0;background:var(--bg);color:var(--text);font-family:'Inter',-apple-system,sans-serif;font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased}}
h1,h2,h3{{font-family:'Space Grotesk','Inter',sans-serif;margin:0;letter-spacing:-.01em}}
a{{color:inherit;text-decoration:none}}
.topbar{{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 28px;border-bottom:1px solid var(--border);background:var(--bg-2);position:sticky;top:0;z-index:50;backdrop-filter:blur(10px)}}
.brand{{display:flex;align-items:center;gap:12px}}
.brand-mark{{width:36px;height:36px;border-radius:10px;display:grid;place-items:center;background:linear-gradient(135deg,#1A2350,#0E1424);box-shadow:0 0 0 1px rgba(196,181,253,.25);font-family:'Space Grotesk';font-weight:700;color:var(--ch);font-size:13px}}
.brand-text{{font-family:'Space Grotesk';font-weight:700;font-size:16px;letter-spacing:.5px}}
.brand-text .dim{{color:var(--text-mute);font-weight:500}}
.crumbs{{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--text-dim);margin-left:16px;padding-left:16px;border-left:1px solid var(--border)}}
.crumbs b{{color:var(--text);font-weight:600}}
.pill{{display:flex;align-items:center;gap:8px;background:var(--bg-card);border:1px solid var(--border);padding:6px 12px 6px 8px;border-radius:999px;font-size:12px;color:var(--text-dim);white-space:nowrap}}
.pill .dot{{width:7px;height:7px;border-radius:50%;background:var(--ch);box-shadow:0 0 0 3px var(--ch-soft)}}
.ch-header{{padding:34px 36px 26px;border-bottom:1px solid var(--border);background:
  radial-gradient(80% 60% at 0% 0%, rgba(196,181,253,.10), transparent 60%),
  radial-gradient(70% 60% at 100% 0%, rgba(196,181,253,.06), transparent 55%)}}
.ch-inner{{max-width:1180px;margin:0 auto}}
.ch-id{{display:inline-block;font-family:'Space Grotesk';font-weight:700;font-size:12px;letter-spacing:.12em;color:var(--ch-ink);background:var(--ch);border-radius:6px;padding:4px 10px;margin-bottom:12px}}
.ch-header h1{{font-size:28px;margin-bottom:8px}}
.ch-tags{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}}
.ch-tag{{font-size:11px;color:var(--text-dim);background:var(--bg-card);border:1px solid var(--border);padding:3px 9px;border-radius:5px}}
.ch-header p{{color:var(--text-dim);max-width:800px;font-size:14.5px;margin:0 0 14px}}
.ch-links{{display:flex;gap:9px;flex-wrap:wrap}}
.ch-links a{{font-size:12.5px;font-weight:600;color:var(--text-dim);background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:7px 12px}}
.ch-links a:hover{{border-color:var(--ch);color:var(--text)}}
.ch-links a.primary{{background:var(--ch);color:var(--ch-ink);border-color:var(--ch)}}
.ch-links a.primary:hover{{filter:brightness(1.08);color:var(--ch-ink)}}
.wrap{{max-width:1180px;margin:0 auto;padding:26px 36px 70px}}
.note{{background:var(--bg-card);border:1px solid var(--border);border-left:3px solid var(--ch);border-radius:12px;padding:14px 18px;color:var(--text-dim);font-size:13.5px;margin-bottom:22px}}
.note b{{color:var(--text)}}
.note code{{font-family:ui-monospace,'SF Mono',Menlo,monospace;font-size:12px;background:var(--bg-2);border:1px solid var(--border-soft);padding:1px 6px;border-radius:5px;color:var(--text-dim)}}
.sec{{font-family:'Space Grotesk';font-size:12px;letter-spacing:1px;text-transform:uppercase;color:var(--text-mute);margin:8px 0 14px;display:flex;gap:10px;align-items:baseline}}
.sec .meta{{font-size:11px;letter-spacing:0;text-transform:none;color:var(--text-mute);font-family:'Inter'}}
.toc{{display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(5,auto);grid-auto-flow:column;gap:8px;margin-bottom:26px}}
@media(max-width:980px){{.toc{{grid-template-columns:repeat(2,1fr);grid-template-rows:repeat(7,auto)}}}}
@media(max-width:600px){{.toc{{grid-template-columns:1fr;grid-template-rows:none;grid-auto-flow:row}}}}
.toc-chip{{display:flex;align-items:center;gap:10px;background:var(--bg-card);border:1px solid var(--border-soft);border-radius:9px;padding:8px 12px;font-size:12.5px;color:var(--text-dim);transition:.15s}}
.toc-chip:hover{{border-color:var(--ch);color:var(--text)}}
.toc-chip b{{font-family:'Space Grotesk';color:var(--ch);font-size:13px;min-width:20px}}
.toc-chip span{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.fcard{{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px 20px;margin-bottom:18px;position:relative;overflow:hidden;scroll-margin-top:76px}}
.fcard::before{{content:"";position:absolute;left:0;top:0;width:3px;height:100%;background:var(--ch);opacity:.7}}
.fhead{{display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
.fnum{{font-family:'Space Grotesk';font-weight:700;font-size:13px;letter-spacing:.08em;color:var(--ch-ink);background:var(--ch);border-radius:6px;padding:3px 9px;flex-shrink:0}}
.fhead h2{{font-size:17.5px;flex:1;min-width:200px}}
.fstate{{font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;padding:2.5px 8px;border-radius:4px;white-space:nowrap}}
.st-ok{{background:rgba(74,222,128,.14);color:#86EFAC}}
.st-drive{{background:rgba(147,197,253,.16);color:#93C5FD}}
.st-up{{background:rgba(252,211,77,.16);color:#FCD34D}}
.dlink{{font-size:12px;font-weight:700;color:var(--ch);background:var(--ch-soft);border:1px solid var(--ch);border-radius:8px;padding:6px 12px;white-space:nowrap;transition:.15s}}
.dlink:hover{{background:var(--ch);color:var(--ch-ink)}}
.fcode{{font-family:ui-monospace,'SF Mono',Menlo,monospace;font-size:11.5px;color:var(--text-mute);margin:4px 0 0 0}}
.fdesc{{color:var(--text-dim);font-size:13.5px;max-width:900px;margin:8px 0 4px}}
.fstats{{font-size:12px;color:var(--text-mute);margin-bottom:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:11px}}
figure{{margin:0}}
figure img{{width:100%;border-radius:8px;display:block;background:var(--bg-2);border:1px solid var(--border-soft)}}
.noimg{{width:100%;aspect-ratio:16/9;border-radius:8px;background:var(--bg-2);border:1px solid var(--border-soft);display:flex;align-items:center;justify-content:center;color:var(--text-mute);font-size:11px}}
figcaption{{font-size:10.5px;color:var(--text-mute);line-height:1.4;padding-top:4px}}
figcaption .vlink{{color:var(--text-dim);font-weight:600;font-family:ui-monospace,'SF Mono',Menlo,monospace;font-size:10.5px;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
figcaption .vlink:hover{{color:var(--ch);text-decoration:underline}}
figure a:hover img{{border-color:var(--ch)}}
.more-tile{{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;aspect-ratio:16/10.6;border:1px dashed var(--border);border-radius:8px;background:var(--bg-2);color:var(--ch);font-family:'Space Grotesk';font-weight:700;font-size:16px;transition:.15s}}
.more-tile span{{font-family:'Inter';font-weight:500;font-size:10.5px;color:var(--text-mute)}}
.more-tile:hover{{border-color:var(--ch)}}
figcaption .sub{{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
figcaption span{{display:block}}
.extras{{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;margin-top:26px}}
.extras h2{{font-size:17px;margin-bottom:10px}}
.extras ul{{margin:0;padding-left:20px;color:var(--text-dim);font-size:13.5px}}
.extras li{{margin:6px 0}}
.extras a{{color:var(--ch);font-weight:600}}
.extras a:hover{{text-decoration:underline}}
.extras code{{font-family:ui-monospace,'SF Mono',Menlo,monospace;font-size:12px;background:var(--bg-2);border:1px solid var(--border-soft);padding:1px 6px;border-radius:5px}}
.foot{{text-align:center;color:var(--text-mute);font-size:12px;padding:30px;border-top:1px solid var(--border);margin-top:34px}}
@media(max-width:700px){{.ch-header,.wrap{{padding-left:16px;padding-right:16px}}.ch-header h1{{font-size:22px}}.crumbs{{display:none}}}}
</style>
</head>
<body>
<div class="topbar">
  <div class="brand">
    <div class="brand-mark">ФП</div>
    <div class="brand-text">yt<span class="dim">.rya.ae</span></div>
    <nav class="crumbs"><span>YTFP</span><span>›</span><b>Съёмочный материал</b></nav>
  </div>
  <div class="pill"><span class="dot"></span> Фонд Правмир · Ассистент Здоровья</div>
</div>

<section class="ch-header">
  <div class="ch-inner">
    <div><span class="ch-id">YTFP</span></div>
    <h1>Съёмочный материал — структура папок</h1>
    <div class="ch-tags">
      <span class="ch-tag">14 папок</span>
      <span class="ch-tag">{tot_clips} видео</span>
      <span class="ch-tag">{mins(tot_dur)} материала</span>
      <span class="ch-tag">{tot_size/1e9:.0f} ГБ</span>
      <span class="ch-tag">Sony ZV-E1 · FX3</span>
    </div>
    <p>Все исходники канала разложены по 14 съёмочным папкам <b>00–13</b>: одна папка = один съёмочный
    день или сюжет. У каждого видео ниже — кадр-заставка (выбран автоматически: самый содержательный
    кадр клипа), хронометраж и размер. Кнопка у каждой папки открывает её на Google Drive.</p>
    <div class="ch-links">
      <a class="primary" href="https://drive.google.com/drive/folders/1ArawQAkQSbxiO6ghDmIiu9-6F0h81KxP" target="_blank" rel="noopener">📁 Корневая папка YTFP на Drive</a>
    </div>
  </div>
</section>

<div class="wrap">
  <div class="note">
    <b>Как устроены папки.</b> Папки <b>00–13</b> — исходный съёмочный материал. Внутри каждой:
    видеофайлы, подпапка <code>Audio</code> (звук с петличек/рекордера, WAV) и <code>Transcripts</code>
    (текстовые расшифровки). Папки вида <code>YTFP01…</code>, <code>YTFP05…</code> и <code>[Script]…</code> —
    монтажные проекты и сценарии, не исходники: у них своя структура (Premiere-проект, экспорты, обложки).
    Метка у каждой папки показывает, где лежит материал: <b>SSD + Drive</b> — есть в обоих местах,
    <b>только Drive</b> — на рабочем SSD отсутствует, <b>SSD → Drive…</b> — загрузка на Drive идёт прямо сейчас.
  </div>
  <div class="sec">Папки <span class="meta">00–13, кликните для перехода</span></div>
  <nav class="toc">{toc}</nav>
  {''.join(cards)}
  <section class="extras">
    <h2>Проекты и служебные папки — это не исходники</h2>
    <ul>
      <li><a href="https://drive.google.com/drive/folders/1bVa0-MLCliARqLTkXOqswmIpocZuS2zY" target="_blank" rel="noopener">[Script] YTFP01-The_Story_of_Katya_and_Matvey</a> — сценарные материалы первого выпуска (история Людмилы Чибиревой).</li>
      <li><a href="https://drive.google.com/drive/folders/1FZEqix1RKpqIr4xmqBuO68Tz97yo1si-" target="_blank" rel="noopener">[Script] YTFP03_Elena_Galkina</a> — сценарные материалы выпуска с Еленой Галкиной.</li>
      <li><a href="https://drive.google.com/drive/folders/1ZaBSYuBx_azeoLIvc3h_KWAaZVllhuLH" target="_blank" rel="noopener">[Script] YTFP05_Maria_Gaidarova</a> — сценарные материалы выпуска с Марией Гайдаровой.</li>
      <li>Папки <a href="https://drive.google.com/drive/folders/1VSJEhG3fxRdhonRwWFtMHAbPJ_RxunLv" target="_blank" rel="noopener">20260212</a>, <a href="https://drive.google.com/drive/folders/1DMTRXwmZENwyGvsnGZZsfOORZGvEvku8" target="_blank" rel="noopener">20260214</a>, <a href="https://drive.google.com/drive/folders/1R2Sq13EiUL99rWCjHRR33xFRoO4I5Fz5" target="_blank" rel="noopener">20260216</a> — технические папки съёмочных дат.</li>
      <li>Монтажные проекты (<code>YTFP01-The_Story_of_Katya_and_Matvey</code>, <code>YTFP05_Maria_Gaidarova</code>) живут на рабочем SSD: Premiere-проект, 02_Edit, экспорты, обложки, YouTube-материалы.</li>
    </ul>
  </section>
  <div class="foot">YTFP · съёмочный материал · превью — автоматически выбранный содержательный кадр каждого клипа · хронометраж и размеры фактические · 20.08.2026</div>
</div>
</body>
</html>"""

out = os.path.join(SP, "YTFP_structure.html")
open(out, "w").write(html)
print(out, f"{os.path.getsize(out)/1e6:.1f} MB")
