#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_structure_html.py — страница структуры фильма (режим montage_tz): рассказ чистовика ↔ экран.

Собирает статический HTML только из локальных данных проекта (REVIEW_DIR = {project}/00_Setup/05_Review):
  • words.json карточки            — мастер транскрибации (дословно, по ролям)
  • montage_plan.json              — главы, тексты страницы (page.*), сцены, вердикты структуры (cuts)
  • montage.json (+ сцен)          — монтажный лист чистовика (build_montage.py)
  • mockups/manifest.json          — 4K-мокапы экранов (build_mockups.py), story_frames — кадры середин склеек
  • analysis.json (необязательно)  — многоагентный разбор исходника (collect_analysis.py)
Транскрипт никогда не перепечатывается руками — только из мастер-JSON. Ни одного литерала проекта
в коде: имена, камеры, ссылки, заметки — из карточки (`speakers`, `clips`, `film`) и plan.page.

  python3 build_structure_html.py [--portal] [--out …] [--full-res-thumbs]
      --portal: фавиконка портала + site.css/site.js вместо inline SVG (страница едет на yt.rya.ae)
Выход: REVIEW_DIR/{CODE}_structure.html (превью — по относительному пути к P.MOCK).
"""
import argparse
import html
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mt_common import (P, REVIEW_DIR, load_plan, load_words_doc, plan_words, plan_clips, scene_plans,  # noqa: E402
                       speakers_map, speaker_parts, find_clip_file, relpath, gfx_catalog_dict)

KIND_COLOR = {
    'полноэкранная карточка': 'full', 'lower-third плашка': 'lt', 'lower-third': 'lt',
    'таймлайн': 'tl', 'схема-связей': 'sch', 'карта': 'map',
    'типографика-цитата': 'typo', 'счётчик/цифра': 'num', 'список-чеклист': 'list',
    'разбор слова по частям': 'word', 'сравнение до/после': 'cmp',
    'экранный титр-поправка': 'fix', 'архивная/стоковая подложка': 'stock', 'ничего': 'none',
}
ACT_COLOR = {'Крючок': '#F87171', 'Кто мы': '#93C5FD', 'Опора': '#C4B5FD', 'Логика': '#A5B4FC',
             'Новость': '#86EFAC', 'Продукт': '#67E8F9', 'Зачем': '#FCA5A5', 'Смысл': '#FCD34D',
             'Призыв': '#4ADE80', 'Финал': '#F9A8D4'}
ACT_FALLBACK = ['#F87171', '#93C5FD', '#C4B5FD', '#A5B4FC', '#86EFAC', '#67E8F9', '#FCA5A5', '#FCD34D', '#4ADE80', '#F9A8D4']
SPK_COLORS = ['var(--ch)', 'var(--pink)', 'var(--text-mute)', 'var(--blue)', 'var(--amber)', 'var(--violet)']
SPK_RGBA = ['rgba(134,239,172,.14)', 'rgba(249,168,212,.14)', 'var(--bg-elev)', 'rgba(147,197,253,.14)',
            'rgba(252,211,77,.14)', 'rgba(196,181,253,.14)']

PORTAL_HEAD = ('<!-- rya-site-v1 --><style id="rya-nf">html.rya-gating body{visibility:hidden}'
               '.rya-overlay,.rya-chrome{visibility:visible}</style><script>document.documentElement.className+='
               '" rya-gating";window.__ryaFailsafe=setTimeout(function(){document.documentElement.classList.remove('
               '"rya-gating")},3500);</script><link rel="stylesheet" href="/assets/site.css?v=20">')
PORTAL_BODY = '<script src="/assets/site.js?v=20" defer></script>'

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

CSS = """
:root{
  --bg:#0A0D16; --bg-2:#0F131E; --bg-card:#181D2B; --bg-elev:#232A3D;
  --border:#3A4258; --border-soft:#252B3D;
  --text:#F0F2F8; --text-dim:#C8CDD9; --text-mute:#8A92A8;
  --ch:#86EFAC; --ok:#4ADE80; --amber:#FCD34D; --red:#F87171; --violet:#C4B5FD; --blue:#93C5FD; --pink:#F9A8D4;
  --cl-red:#D0021B; --radius:14px;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text);font-family:'Inter',-apple-system,sans-serif;font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased}
h1,h2,h3,h4{font-family:'Space Grotesk','Inter',sans-serif;margin:0;letter-spacing:-.01em}
a{color:inherit}
.topbar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:14px 28px;border-bottom:1px solid var(--border);background:var(--bg-2);position:sticky;top:0;z-index:50;-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px)}
.brand{display:flex;align-items:center;gap:12px;text-decoration:none}
.brand-mark{width:36px;height:36px;border-radius:10px;display:grid;place-items:center;background:linear-gradient(135deg,#14532D,#0E1424);box-shadow:0 0 0 1px rgba(134,239,172,.25);font-family:'Space Grotesk';font-weight:700;color:var(--ch);font-size:13px}
.brand-text{font-family:'Space Grotesk';font-weight:700;font-size:16px;letter-spacing:.5px}
.brand-text .dim{color:var(--text-mute);font-weight:500}
.crumbs{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--text-dim);padding-left:16px;border-left:1px solid var(--border)}
.crumbs a{color:var(--text-mute);text-decoration:none}.crumbs a:hover{color:var(--ch)}.crumbs b{color:var(--text)}
.hero{padding:34px 28px 26px;border-bottom:1px solid var(--border-soft);background:linear-gradient(180deg,rgba(134,239,172,.05),transparent)}
.hero-in{max-width:1180px;margin:0 auto}
.hero .id{font-family:'Space Grotesk';font-weight:700;font-size:13px;letter-spacing:.14em;color:var(--ch)}
.hero h1{font-size:30px;margin:10px 0 12px}
.hero p{color:var(--text-dim);max-width:86ch;margin:0 0 16px;font-size:14.5px}
.tags{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:14px}
.tags span{font-size:12px;padding:4px 11px;border-radius:7px;background:var(--bg-card);border:1px solid var(--border-soft);color:var(--text-dim)}
.kpis{display:flex;flex-wrap:wrap;gap:10px;margin-top:6px}
.kpi{background:var(--bg-card);border:1px solid var(--border-soft);border-radius:10px;padding:12px 18px;min-width:118px}
.kpi .v{font-family:'Space Grotesk';font-size:23px;font-weight:700;color:var(--ch);line-height:1.1}
.kpi .l{font-size:11.5px;color:var(--text-mute);margin-top:4px}
.wrap{max-width:1180px;margin:0 auto;padding:26px 28px 70px}
.sec{font-family:'Space Grotesk';font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--text-mute);margin:38px 0 13px;display:flex;align-items:center;gap:10px;scroll-margin-top:80px}
.sec::after{content:"";flex:1;height:1px;background:var(--border-soft)}
.sec:first-child{margin-top:0}
.note{background:var(--bg-card);border:1px solid var(--border-soft);border-left:2px solid var(--amber);border-radius:0 10px 10px 0;padding:14px 17px;color:var(--text-dim);font-size:13.5px;margin-bottom:12px}
.note b{color:var(--text)}
.note.n-ok{border-left-color:var(--ok)} .note.n-warn{border-left-color:var(--amber)}
.note.n-red{border-left-color:var(--red)} .note.n-info{border-left-color:var(--blue)}
.note ul{margin:8px 0 0;padding-left:20px} .note li{margin:4px 0}
.tblw{overflow-x:auto}
.tbl{width:100%;border-collapse:collapse;background:var(--bg-card);border:1px solid var(--border-soft);border-radius:12px;overflow:hidden;font-size:13px}
.tbl th{text-align:left;padding:10px 14px;background:var(--bg-elev);color:var(--text-mute);font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;font-weight:700}
.tbl td{padding:9px 14px;border-top:1px solid var(--border-soft);color:var(--text-dim);vertical-align:top}
.tbl td.mono,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;color:var(--text)}
.tbl td.dim{color:var(--text-mute)} .tbl td.w{color:var(--text);font-weight:600;white-space:nowrap}
.tbl td.fix{color:var(--ch)}
.sp-grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}
.sp-card{background:var(--bg-card);border:1px solid var(--border-soft);border-radius:12px;padding:15px 17px;border-top:2px solid var(--text-mute)}
.sp-name{font-family:'Space Grotesk';font-weight:700;font-size:15px}
.sp-bar{height:6px;border-radius:4px;background:var(--bg-elev);margin:10px 0 7px;overflow:hidden}
.sp-bar i{display:block;height:100%;background:var(--ch)}
.sp-meta{font-size:12.5px;color:var(--text-dim)} .sp-note{font-size:12px;color:var(--text-mute);margin-top:5px}
.blk{background:var(--bg-card);border:1px solid var(--border-soft);border-radius:var(--radius);padding:18px 20px;margin-bottom:14px;border-left:3px solid var(--border)}
.blk.v-keep{border-left-color:var(--ok)} .blk.v-trim{border-left-color:var(--amber)}
.blk.v-cut{border-left-color:var(--red);opacity:.8} .blk.v-svc{border-left-color:var(--text-mute);opacity:.72}
.b-head{display:flex;align-items:center;gap:11px;flex-wrap:wrap;margin-bottom:8px}
.b-n{font-family:'Space Grotesk';font-weight:700;font-size:12px;color:var(--bg);background:var(--ch);width:24px;height:24px;border-radius:7px;display:grid;place-items:center;flex-shrink:0}
.b-tc{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;color:var(--ch)}
.b-head h3{font-size:16.5px;flex:1;min-width:200px}
.b-sp{font-size:11.5px;padding:3px 9px;border-radius:6px;background:var(--bg-elev);border:1px solid var(--border-soft);color:var(--text-dim)}
.b-vd{font-size:12.5px;padding:7px 12px;border-radius:8px;margin-bottom:9px}
.vb-keep{background:rgba(74,222,128,.09);color:var(--ok)} .vb-trim{background:rgba(252,211,77,.09);color:var(--amber)}
.vb-cut{background:rgba(248,113,113,.09);color:var(--red)} .vb-svc{background:var(--bg-elev);color:var(--text-mute)}
.b-role{font-size:11.5px;color:var(--text-mute);letter-spacing:.05em;text-transform:uppercase;margin-bottom:8px}
.b-sum{margin:0 0 10px;color:var(--text-dim);font-size:13.8px}
.b-q{margin:0 0 11px;padding:9px 15px;border-left:2px solid var(--cl-red);background:var(--bg-elev);border-radius:0 8px 8px 0;color:var(--text);font-size:13.5px;font-style:italic}
.b-lbl{font-family:'Space Grotesk';font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--text-mute);margin-bottom:7px}
.b-facts ul{margin:0 0 11px;padding-left:19px;color:var(--text-dim);font-size:13px} .b-facts li{margin:3px 0}
.b-risk{font-size:13px;color:var(--amber);background:rgba(252,211,77,.07);border-radius:8px;padding:8px 13px;margin-bottom:11px}
.b-viz{margin-top:14px;padding-top:14px;border-top:1px solid var(--border-soft)}
.v-grid{display:grid;gap:11px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.v-card{background:var(--bg-elev);border:1px solid var(--border-soft);border-radius:11px;padding:13px 15px;border-top:2px solid var(--blue)}
.v-card.k-full{border-top-color:var(--violet)} .v-card.k-tl{border-top-color:var(--ch)} .v-card.k-num{border-top-color:var(--amber)}
.v-card.k-typo{border-top-color:var(--pink)} .v-card.k-fix{border-top-color:var(--red)} .v-card.k-none{opacity:.72}
.v-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px}
.v-kind{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--text-mute)}
.v-tc{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:var(--ch)}
.v-eff{font-size:10px;padding:2px 7px;border-radius:5px;margin-left:auto}
.eff-l{background:rgba(74,222,128,.13);color:var(--ok)} .eff-m{background:rgba(252,211,77,.13);color:var(--amber)} .eff-h{background:rgba(248,113,113,.13);color:var(--red)}
.v-card h4{font-size:14px;margin-bottom:6px} .v-card p{margin:0 0 8px;font-size:13px;color:var(--text-dim)}
.v-lbl{font-size:10.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--text-mute);margin-bottom:4px}
.v-data ul{margin:0 0 8px;padding-left:18px;font-size:12.5px;color:var(--text)} .v-data li{margin:2px 0}
.v-trig{font-size:12px;color:var(--text-mute);font-style:italic;margin-bottom:7px}
.v-style{font-size:12.5px;color:var(--text-dim);margin-bottom:7px}
.v-why{font-size:12.5px;color:var(--text-dim);padding-top:7px;border-top:1px solid var(--border-soft)}
.v-rec{margin-top:11px;font-size:13px;color:var(--ch);background:rgba(134,239,172,.07);border-radius:8px;padding:9px 13px}
.pal{display:flex;flex-wrap:wrap;gap:10px}
.sw{border-radius:10px;padding:13px 15px;min-width:132px;border:1px solid var(--border-soft);font-size:12px}
.sw b{display:block;font-family:ui-monospace,Menlo,monospace;font-size:12.5px;margin-bottom:3px}
.tr-wrap{background:var(--bg-card);border:1px solid var(--border-soft);border-radius:12px;overflow:hidden}
.tr-row{display:flex;gap:16px;padding:11px 15px;border-bottom:1px solid var(--border-soft);align-items:baseline}
.tr-row:last-child{border-bottom:0}
.tr-meta{flex-shrink:0;width:210px;display:flex;gap:9px;align-items:baseline;flex-wrap:wrap}
.tr-tc{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--ch)}
.tr-who{font-size:12.5px;font-weight:600}
.tr-dur{font-size:11px;color:var(--text-mute)}
.tr-text{flex:1;color:var(--text-dim);font-size:13.5px}
pre.ch{background:var(--bg-elev);border-radius:9px;padding:13px 16px;margin:9px 0 0;font-family:ui-monospace,Menlo,monospace;font-size:12.5px;color:var(--text);overflow-x:auto;line-height:1.7}
.foot{margin-top:40px;padding-top:18px;border-top:1px solid var(--border-soft);color:var(--text-mute);font-size:12px}
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
.cam{font-size:11px;font-weight:700;padding:2px 8px;border-radius:5px;background:var(--bg-elev);color:var(--text-mute)}
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
.gc-rev{margin-top:9px;font-size:12.5px;color:var(--amber);background:rgba(252,211,77,.07);border-radius:8px;padding:8px 12px}
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
.cut{display:flex;gap:10px;align-items:baseline;padding:6px 0;border-top:1px dashed var(--border-soft);font-size:13px}
.cut .id{font-family:ui-monospace,Menlo,monospace;color:var(--text-mute);min-width:44px}
.cut.keep .vd{color:var(--ok)} .cut.drop .vd{color:var(--red)} .cut .vd{font-weight:700;min-width:70px}
@media(max-width:860px){.st-hd{display:none}.st-row{grid-template-columns:1fr}.st-l{border-right:0;padding-left:16px}.st-tc{padding:12px 16px 0}}
@media(max-width:760px){.topbar{padding:12px 16px}.crumbs{display:none}.hero{padding:24px 16px 20px}.wrap{padding:20px 16px 60px}.tr-meta{width:100%}.tr-row{flex-direction:column;gap:5px}.pt-txt{padding-left:0}}
"""


def e(x):
    return html.escape(str(x if x is not None else ''))


def tc(t):
    m, s = divmod(float(t), 60)
    return f'{int(m):02d}:{int(s):02d}'


def mmss(t, ms=False):
    if t is None:
        return '—'
    t = max(0.0, float(t))
    m, s = divmod(t, 60)
    return f'{int(m):02d}:{s:04.1f}' if ms else f'{int(m):02d}:{int(s):02d}'


def act_color(act, acts):
    if act in ACT_COLOR:
        return ACT_COLOR[act]
    if act in acts:
        return ACT_FALLBACK[acts.index(act) % len(ACT_FALLBACK)]
    return '#8A92A8'


def kind_slug(kind):
    k = (kind or '').strip().lower()
    for key, slug in KIND_COLOR.items():
        if key in k:
            return slug
    return 'oth'


def verdict_slug(v):
    v = (v or '').lower()
    if v.startswith('вырезать'):
        return 'cut'
    if 'сжат' in v or 'сокра' in v:
        return 'trim'
    if 'служеб' in v:
        return 'svc'
    return 'keep'


def tidy(t):
    t = re.sub(r' -(\w)', r'-\1', t)          # «чуть -чуть» → «чуть-чуть»
    return re.sub(r' \.(\w)', r'.\1', t)      # «эволюция .рус» → «эволюция.рус»


# ---------------- спикеры ----------------
class Speakers:
    """Карта спикеров: ключ words.json → имя, камера, css-класс, заметка; главная камера = в кадре."""

    def __init__(self, cam_map, page, words_doc):
        self.info = {}
        secs = words_doc.get('speakers_seconds', {}) if words_doc else {}
        notes = (page.get('speakers') or {})
        for i, (key, label) in enumerate(cam_map.items()):
            cam, name = speaker_parts(label)
            n = notes.get(key) or {}
            self.info[key] = {'name': n.get('name') or name or key, 'cam': cam, 'cls': f'sp{i + 1}',
                              'note': n.get('note', ''), 'label': label, 'secs': float(secs.get(key, 0))}
        self.main_cam = page.get('main_camera') or (max(self.info.values(), key=lambda v: v['secs'])['cam'] if self.info else '')
        self.main = next((v for v in self.info.values() if v['cam'] == self.main_cam), None)

    def get(self, key):
        return self.info.get(key) or {'name': key, 'cam': '', 'cls': 'sp0', 'note': '', 'label': key, 'secs': 0}

    def cls_by_label(self, camera_label):
        for v in self.info.values():
            if v['label'] == camera_label:
                return v['cls']
        return 'sp0'

    def is_offscreen(self, camera_label):
        """Говорит не тот, кто в кадре: другая камера или «за кадром»."""
        cam, _ = speaker_parts(camera_label)
        return cam != self.main_cam

    def css(self):
        rules = []
        for v in self.info.values():
            i = int(v['cls'][2:]) - 1
            col, bg = SPK_COLORS[i % len(SPK_COLORS)], SPK_RGBA[i % len(SPK_RGBA)]
            rules.append(f'.sp-card.{v["cls"]}{{border-top-color:{col}}} .{v["cls"]} .sp-bar i{{background:{col}}} '
                         f'.tr-row.{v["cls"]} .tr-who{{color:{col}}} .b-sp.{v["cls"]}{{color:{col}}} '
                         f'.cam.{v["cls"]}{{background:{bg};color:{col}}}')
        return '\n'.join(rules)


# ---------------- транскрипт ----------------
def build_transcript(words, spk):
    rows = []
    for b in words.get('blocks', []):
        s = spk.get(b['speaker'])
        rows.append(
            f'<div class="tr-row {s["cls"]}">'
            f'<div class="tr-meta"><span class="tr-tc">{tc(b["start"])}</span>'
            f'<span class="tr-who">{e(s["name"])}</span>'
            f'<span class="tr-dur">{b["end"] - b["start"]:.0f} с</span></div>'
            f'<div class="tr-text">{e(b["text"].strip())}</div></div>')
    return '\n'.join(rows)


# ---------------- диагноз по блокам исходника ----------------
def build_blocks(canon, viz_by_n, spk):
    out = []
    names = [(v['name'], v['cls']) for v in spk.info.values()]
    for b in canon.get('blocks', []):
        vs = verdict_slug(b.get('edit_verdict'))
        sp_raw = b.get('speaker', '') or ''
        hits = [cls for name, cls in names if name.split()[0] in sp_raw]
        cls = hits[0] if len(hits) == 1 else 'sp0'
        facts = b.get('facts') or []
        facts_html = ('<div class="b-facts"><div class="b-lbl">Фактура на экран</div><ul>'
                      + ''.join(f'<li>{e(f)}</li>' for f in facts) + '</ul></div>') if facts else ''
        quote = f'<blockquote class="b-q">{e(b["key_quote"])}</blockquote>' if b.get('key_quote') else ''
        risk = f'<div class="b-risk"><b>Риск:</b> {e(b["risk"])}</div>' if b.get('risk') else ''
        viz = viz_by_n.get(b.get('n'))
        viz_html = ''
        if viz:
            cards = []
            for o in viz.get('options', []):
                data = o.get('data_on_screen') or []
                data_html = ('<div class="v-data"><div class="v-lbl">Что написано на экране</div><ul>'
                             + ''.join(f'<li>{e(x)}</li>' for x in data) + '</ul></div>') if data else ''
                trig = f'<div class="v-trig">↳ реплика-триггер: «{e(o["trigger_quote"])}»</div>' if o.get('trigger_quote') else ''
                style = f'<div class="v-style"><b>В языке клиента:</b> {e(o["style_note"])}</div>' if o.get('style_note') else ''
                eff = e(o.get('effort', ''))
                effc = 'h' if 'выс' in eff.lower() else ('m' if 'сред' in eff.lower() else 'l')
                cards.append(
                    f'<div class="v-card k-{kind_slug(o.get("kind"))}">'
                    f'<div class="v-top"><span class="v-kind">{e(o.get("kind"))}</span>'
                    f'<span class="v-tc">{e(o.get("tc"))}</span><span class="v-eff eff-{effc}">{eff}</span></div>'
                    f'<h4>{e(o.get("name"))}</h4><p>{e(o.get("what_on_screen"))}</p>'
                    f'{data_html}{trig}{style}<div class="v-why"><b>Зачем:</b> {e(o.get("why"))}</div></div>')
            rec = f'<div class="v-rec"><b>Брать:</b> {e(viz["recommended"])}</div>' if viz.get('recommended') else ''
            viz_html = ('<div class="b-viz"><div class="b-lbl">Идеи графики из разбора (словами — '
                        'отрисованные экраны в галерее выше)</div>'
                        f'<div class="v-grid">{"".join(cards)}</div>{rec}</div>')
        out.append(
            f'<div class="blk v-{vs}" id="b{b.get("n")}"><div class="b-head">'
            f'<span class="b-n">{e(b.get("n"))}</span>'
            f'<span class="b-tc">{e(b.get("tc_in"))} — {e(b.get("tc_out"))}</span>'
            f'<h3>{e(b.get("title"))}</h3><span class="b-sp {cls}">{e(sp_raw)}</span></div>'
            f'<div class="b-vd vb-{vs}">{e(b.get("edit_verdict"))}</div>'
            f'<div class="b-role">{e(b.get("role", ""))}</div>'
            f'<p class="b-sum">{e(b.get("summary"))}</p>{quote}{facts_html}{risk}{viz_html}</div>')
    return '\n'.join(out)


def build_list(items, cls=''):
    if not items:
        return ''
    return f'<ul class="{cls}">' + ''.join(f'<li>{e(x)}</li>' for x in items) + '</ul>'


def build_issues(res, title, tone, anchor):
    if not res:
        return ''
    parts = [f'<div class="sec" id="{anchor}">{e(title)}</div>']
    if res.get('verdict'):
        parts.append(f'<div class="note n-{tone}"><b>Вердикт:</b> {e(res["verdict"])}</div>')
    errs = res.get('errors') or []
    if errs:
        rows = ''.join(f'<tr><td class="w">{e(x.get("where"))}</td><td>{e(x.get("problem"))}</td>'
                       f'<td class="fix">{e(x.get("fix"))}</td></tr>' for x in errs)
        parts.append('<div class="tblw"><table class="tbl"><thead><tr><th>Где</th><th>Что не так</th>'
                     f'<th>Как поправить</th></tr></thead><tbody>{rows}</tbody></table></div>')
    miss = res.get('missing') or []
    if miss:
        parts.append('<div class="note n-warn"><b>Чего не хватает</b>' + build_list(miss) + '</div>')
    return '\n'.join(parts)


def build_cuts(cuts, segments):
    """Вердикты облачного агента структуры: что оставлено / снято и почему (plan.cuts + segments.json)."""
    if not cuts:
        return ''
    by = {s['id']: s for s in segments}
    rows = []
    for c in cuts:
        s = by.get(c.get('id'), {})
        rows.append(f'<div class="cut {"keep" if c.get("keep") else "drop"}"><span class="id">{e(c.get("id"))}</span>'
                    f'<span class="vd">{"оставить" if c.get("keep") else "снять"}</span>'
                    f'<span>{e(s.get("thesis", ""))}'
                    + (f' <span class="mono">{mmss(s["t_in"], True)}–{mmss(s["t_out"], True)}</span>' if s else '')
                    + f' — {e(c.get("why", ""))}</span></div>')
    n_keep = sum(1 for c in cuts if c.get('keep'))
    return (f'<div class="sec" id="cuts">Вердикты по тезисам исходника — оставлено {n_keep} из {len(cuts)}</div>'
            f'<div class="note n-info">Нарезка на тезисы — локальная модель (segment_local.py), вердикты — один облачный агент структуры.</div>'
            + ''.join(rows))


# ---------------- монтажный лист ----------------
def build_montage(mont, spk, acts):
    Pc, cat = mont['pieces'], mont['gfx_catalog']
    ribbon = ''.join(
        f'<a class="rb" href="#p{p["id"]}" style="flex:{max(p["dur"], 2):.2f};background:{act_color(p.get("act"), acts)}" '
        f'title="{e(p["id"])} · {e(p["title"])} · {p["dur"]:.0f} с"><span>{e(p["id"])}</span></a>' for p in Pc)
    legend = ''.join(f'<span class="lg"><i style="background:{act_color(a, acts)}"></i>{e(a)}</span>' for a in acts)
    rows = []
    for p in Pc:
        parts = []
        for x in p['parts']:
            if x['kind'] == 'say':
                cc = spk.cls_by_label(x['camera'])
                pend = ' <em>· ракурс будет</em>' if spk.is_offscreen(x['camera']) else ''
                gaps = x.get('gaps') or []
                gap_title = ', '.join(f'{mmss(g["at"], True)} ({g["dur"]} с после «{g["after"]}»)' for g in gaps)
                gap_html = (f'<span class="gp" title="{e(gap_title)}">пауз ≥0,7 с: {len(gaps)} · −{x["trim_est"]:.1f} с</span>'
                            if gaps else '')
                cross = (f'<span class="xc">↔ внутри шов файлов {", ".join(mmss(c, True) for c in x["crosses_clip"])} — звук непрерывен</span>'
                         if x['crosses_clip'] else '')
                src_file = x['file_in'] + (f' → {x["file_out"]}' if x['file_out'] != x['file_in'] else '')
                parts.append(
                    f'<div class="pt"><span class="pt-dst">{mmss(x["dst_in"])}</span>'
                    f'<span class="pt-src">{mmss(x["src_in"], True)} – {mmss(x["src_out"], True)}</span>'
                    f'<span class="cam {cc}">{e(x["camera"])}{pend}</span>'
                    f'<span class="pt-file">{e(src_file)} +{mmss(x["off_in"], True)}</span>'
                    f'<span class="pt-dur">{x["dur"]:.1f} с</span>{gap_html}{cross}'
                    f'<span class="pt-txt">«{e(x["first"])} … {e(x["last"])}»</span></div>')
            elif x['kind'] == 'gfx':
                parts.append(f'<div class="pt pt-ins"><span class="pt-dst">{mmss(x["dst_in"])}</span>'
                             f'<span class="ins">▣ полноэкранная вставка <a href="#g-{e(x["ref"])}" style="color:inherit">{e(x["ref"])}</a>'
                             f' · {e(cat[x["ref"]][1])}</span><span class="pt-dur">{x["dur"]:.1f} с</span></div>')
            else:
                parts.append(f'<div class="pt pt-ins"><span class="pt-dst">{mmss(x["dst_in"])}</span>'
                             f'<span class="ins">⏸ {e(x["ref"])}</span><span class="pt-dur">{x["dur"]:.1f} с</span></div>')
        chips = ''.join(f'<a class="gchip g-{g["kind"]}" href="#g-{g["id"]}" title="{e(g["title"])}">{e(g["id"])}'
                        f'<span>{mmss(g["dst"])}</span></a>' for g in p['gfx'])
        blk = f'<a class="mp-b" href="#b{p["block"]}">блок {p["block"]} исходника</a>' if p.get('block') else ''
        rows.append(
            f'<div class="mp" id="p{p["id"]}" style="border-left-color:{act_color(p.get("act"), acts)}">'
            f'<div class="mp-h"><span class="mp-n">{e(p["id"])}</span>'
            f'<span class="mp-tc">{mmss(p["dst_in"])}–{mmss(p["dst_out"])}</span>'
            f'<h3>{e(p["title"])}</h3><span class="mp-act">{e(p.get("act", ""))}</span>'
            f'<span class="mp-d">{p["dur"]:.0f} с → ≈{p["dur_trimmed"]:.0f} с</span>{blk}</div>'
            + ''.join(parts)
            + (f'<div class="mp-g">{chips}</div>' if chips else '')
            + (f'<div class="mp-note">{e(p["note"])}</div>' if p.get('note') else '')
            + '</div>')
    return f'<div class="rbn">{ribbon}</div><div class="lgs">{legend}</div>' + ''.join(rows)


# ---------------- галерея экранов ----------------
def build_gallery(monts, man, mock_rel, full_thumb, page, reviews):
    order, uses, cat = [], {}, {}
    for scene_label, mont in monts:
        cat.update(mont['gfx_catalog'])
        for p in mont['pieces']:
            for g in p['gfx']:
                if g['id'] not in order:
                    order.append(g['id'])
                uses.setdefault(g['id'], []).append((p['id'], g, scene_label))
    recommend = page.get('recommend') or {}
    cards = []
    for gid in order:
        kind, title, place = cat[gid]
        vs = [m for m in man if m['id'] == gid]
        figs = []
        for m in vs:
            qc = m.get('qc', '')
            badge = ('' if m['kind'] == 'client' else
                     ' <span class="qc ok">раскладка ок</span>' if qc == 'ok' else
                     f' <span class="qc bad" title="{e(qc)}">QC: {e(qc[:60])}</span>')
            figs.append(f'<figure><a href="{mock_rel}/{e(m["thumb"] if full_thumb else m["png"])}" target="_blank">'
                        f'<img src="{mock_rel}/{e(m["thumb"])}" loading="lazy" alt="{e(m["title"])}"></a>'
                        f'<figcaption><b>{e(m["variant"])}</b> · {e(m["title"])}{badge}</figcaption></figure>')
        imgs = ''.join(figs) or '<div class="note">мокап ещё не отрисован</div>'
        rec = f'<div class="v-rec"><b>Брать:</b> {e(recommend[gid])}</div>' if gid in recommend else ''
        rv = ''
        for m in vs:
            r = reviews.get(f'{m["id"]}_{m["variant"]}')
            if r and not r.get('ok'):
                rv += (f'<div class="gc-rev"><b>Ревью дизайна · {e(m["variant"])}:</b> {e("; ".join(r.get("problems") or []))}'
                       + (f' → <b>{e(r["fix"])}</b>' if r.get('fix') else '') + '</div>')
        items = []
        for pid, g, scene_label in uses[gid]:
            link = f'<a href="#p{pid}">кусок {pid}</a>' if not scene_label else f'кусок {pid} · {e(scene_label)}'
            what = (f'на слове «{e(g["on_word"])}»' if g.get('on_word')
                    else f'полноэкранная вставка {g.get("insert", "")} с')
            items.append(f'<li>{link} · {mmss(g["dst"])} — {what}</li>')
        cards.append(
            f'<div class="gc" id="g-{gid}"><div class="gc-h"><span class="gc-id">{gid}</span><h4>{e(title)}</h4>'
            f'<span class="gk gk-{kind}">{"слайд клиента" if kind == "client" else "новый экран"}</span>'
            f'<span class="gpl">{e(place)}</span></div><div class="gc-imgs">{imgs}</div>{rec}{rv}'
            f'<ul class="gc-w">{"".join(items)}</ul></div>')
    return '<div class="gal">' + ''.join(cards) + '</div>'


def build_chapters(mont, chapters):
    by = {p['id']: p for p in mont['pieces']}
    acc, pos_tr = 0.0, {}
    for p in mont['pieces']:
        pos_tr[p['id']] = acc
        acc += p['dur_trimmed']
    raw = '\n'.join(f'{mmss(by[i]["dst_in"])} — {t}' for i, t in chapters if i in by)
    trm = '\n'.join(f'{mmss(pos_tr[i])} — {t}' for i, t in chapters if i in by)
    return (f'<div class="note n-ok">Посчитаны по реальному монтажному листу: первая глава с 00:00, '
            f'каждая — от первого куска своего акта. Слева — тайминг листа как есть, справа — после '
            f'подрезки пауз (ориентир для финала).'
            f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px">'
            f'<pre class="ch">{e(raw)}</pre><pre class="ch">{e(trm)}</pre></div></div>')


def pick_variant(gid, pid, man, story_variant):
    vs = [m for m in man if m['id'] == gid]
    if not vs:
        return None, []
    want = story_variant.get(f'{gid}@{pid}') or story_variant.get(gid, 'A')
    main = next((m for m in vs if m['variant'] == want), vs[0])
    return main, [m for m in vs if m is not main]


def build_story(mont, man, mock_rel, full_thumb, frames_dir, frames_rel, chapters, page, spk, acts):
    frames = {f.name.split('__')[0]: f.name for f in Path(frames_dir).glob('*.jpg')} if Path(frames_dir).exists() else {}
    cat = mont['gfx_catalog']
    by = {p['id']: p for p in mont['pieces']}
    chap = {pid: i for i, (pid, _) in enumerate(chapters)}
    story_variant = page.get('story_variant') or {}
    client_label = page.get('client_source_label', 'слайд клиента')
    draft_label = page.get('draft_label', 'наш драфт — перерисовать в стиле клиента')
    main_name = spk.main['name'] if spk.main else 'спикер'
    main_cam = spk.main_cam or '—'
    rows = ['<div class="st-hd"><div>ТК</div><div>Рассказ</div><div>Что на экране</div></div>']
    for p in mont['pieces']:
        if p['id'] in chap:
            i = chap[p['id']]
            b = by[chapters[i + 1][0]]['dst_in'] if i + 1 < len(chapters) and chapters[i + 1][0] in by else mont['total']
            rows.append(f'<div class="st-ch" style="--c:{act_color(p.get("act"), acts)}">'
                        f'<span>[{i + 1}. {e(chapters[i][1].upper())} · {mmss(p["dst_in"])}–{mmss(b)}]</span></div>')
        for k, x in enumerate(p['parts']):
            head = f'<div class="st-t">【{e(p["id"])} · {e(p["title"])}】</div>' if k == 0 else ''
            note = f'<div class="st-n">✂ {e(p["note"])}</div>' if k == 0 and p.get('note') else ''
            cam_b = False
            if x['kind'] == 'say':
                cam_b = spk.is_offscreen(x['camera'])
                cam = x['camera'] + (' — встречный ракурс будет' if cam_b else '')
                gaps = x.get('gaps') or []
                src = (f'📄 {x["file_in"]} +{mmss(x["off_in"], True)} · исходник {mmss(x["src_in"], True)}–'
                       f'{mmss(x["src_out"], True)} · {x["dur"]:.1f} с · {cam}'
                       + (f' · пауз к подрезке {len(gaps)} (−{x["trim_est"]:.1f} с)' if gaps else ''))
                left = f'{head}<p class="st-p">{e(tidy(x["text"]))}</p><div class="st-src">{e(src)}</div>{note}'
                here = [g for g in p['gfx'] if not g.get('insert') and g.get('dst') is not None
                        and x['dst_in'] - 0.05 <= g['dst'] < x['dst_out']]
            elif x['kind'] == 'gfx':
                left = (f'{head}<p class="st-p st-ins">▣ Полноэкранная вставка {e(x["ref"])} · {x["dur"]:.0f} с — '
                        f'{e(cat[x["ref"]][1])}</p>{note}')
                here = [g for g in p['gfx'] if g.get('insert') and abs(g['dst'] - x['dst_in']) < 0.05]
            else:
                left = f'{head}<p class="st-p st-ins">⏸ {e(x["ref"])} · {x["dur"]:.0f} с</p>{note}'
                here = []
            figs = []
            for g in here:
                main, others = pick_variant(g['id'], p['id'], man, story_variant)
                if not main:
                    continue
                href = f'{mock_rel}/{main["thumb"] if full_thumb else main["png"]}'
                where = f'на слове «{e(g["on_word"])}»' if g.get('on_word') else f'полноэкранно, {g.get("insert", "")} с'
                if main.get('alpha') and cam_b:
                    where += f' · подложка превью — кадр камеры {e(main_cam)}'
                srcd = client_label if main['kind'] == 'client' else draft_label
                var = f'вариант {main["variant"]}' + (f' · есть {", ".join(o["variant"] for o in others)}' if others else '')
                figs.append(f'<figure class="st-f"><a href="{e(href)}" target="_blank"><img src="{mock_rel}/{e(main["thumb"])}" '
                            f'loading="lazy" alt="{e(main["title"])}"></a><figcaption><b>{mmss(g["dst"])}</b> · {where} — '
                            f'{e(cat[g["id"]][1])}</figcaption><div class="st-meta">📚 {e(srcd)} · '
                            f'<a href="#g-{g["id"]}">{g["id"]}: {var}</a></div></figure>')
            if not figs and x['kind'] == 'say':
                mid = round((x['src_in'] + x['src_out']) / 2, 2)
                fn = frames.get('t' + f'{int(mid // 60):02d}m{mid % 60:06.3f}s'.replace('.', '_'))
                if fn and cam_b:
                    figs.append(f'<figure class="st-f"><div class="st-im st-wait"><img src="{frames_rel}/{fn}" '
                                f'loading="lazy" alt=""><span class="st-wl">{e(x["camera"].upper())} · РАКУРСА ПОКА НЕТ</span></div>'
                                f'<figcaption><b>{mmss(x["dst_in"])}</b> · говорит не тот, кто в кадре: на подложке '
                                f'{e(main_name)}, встречный ракурс будет</figcaption></figure>')
                elif fn:
                    figs.append(f'<figure class="st-f"><div class="st-im"><img src="{frames_rel}/{fn}" '
                                f'loading="lazy" alt=""></div><figcaption><b>{mmss(x["dst_in"])}</b> · в кадре {e(main_name)}, '
                                f'камера {e(main_cam)} — графики нет</figcaption></figure>')
            elif not figs:
                figs.append('<div class="st-empty">удержание кадра</div>')
            rows.append(f'<div class="st-row"><div class="st-tc">{mmss(x["dst_in"])}</div>'
                        f'<div class="st-l">{left}</div><div class="st-r">{"".join(figs)}</div></div>')
    return '<div class="st">' + ''.join(rows) + '</div>'


# ---------------- исходные файлы ----------------
def clip_meta(name, meta):
    """(запись UTC, размер) — из plan.page.clips_meta, иначе ffprobe/stat по файлу проекта."""
    m = (meta or {}).get(name)
    if m:
        return m.get('rec_utc', '—'), m.get('size', '—')
    p = find_clip_file(name)
    if not p:
        return '—', '—'
    size = f'{p.stat().st_size / 1e9:.2f} ГБ'.replace('.', ',')
    rec = '—'
    try:
        out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format_tags=creation_time', '-of', 'default=nw=1:nk=1', str(p)],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        if out:
            rec = out[11:19]
    except Exception:
        pass
    return rec, size


def clips_table(clips, meta, header):
    rows = ''

    def t2(t):
        m, s = divmod(float(t), 60)
        return f'{int(m):02d}:{s:05.2f}'
    for name, a, b in clips:
        rec, size = clip_meta(name, meta)
        rows += (f"<tr><td class='mono'>{e(name)}</td><td>{t2(b - a)}</td><td class='mono'>{t2(a)} → {t2(b)}</td>"
                 f"<td class='mono dim'>{e(rec)}</td><td>{e(size)}</td></tr>")
    return ('<div class="tblw"><table class="tbl">'
            f'<thead><tr><th>Файл</th><th>Длительность</th><th>{header}</th><th>Запись (UTC)</th><th>Размер</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


def speaker_cards(spk, extra=''):
    total_sp = sum(v['secs'] for v in spk.info.values()) or 1
    rows = ''.join(
        f'<div class="sp-card {v["cls"]}"><div class="sp-name">{e(v["name"])}</div>'
        f'<div class="sp-bar"><i style="width:{v["secs"] / total_sp * 100:.0f}%"></i></div>'
        f'<div class="sp-meta">{int(v["secs"] // 60)} мин {v["secs"] % 60:.0f} с · {v["secs"] / total_sp * 100:.0f}% речи{e(extra)}</div>'
        f'<div class="sp-note">{e(v["note"] or ("в кадре · камера " + v["cam"] if v["cam"] == spk.main_cam and v["cam"] else v["label"]))}</div></div>'
        for v in sorted(spk.info.values(), key=lambda x: -x['secs']) if v['secs'] > 0)
    return rows


def links_block(page):
    if page.get('links_html'):
        return page['links_html']
    links = page.get('links') or []
    if not links:
        return ''
    items = ''.join(
        (f'<a class="lk" href="{e(l["href"])}" target="_blank" rel="noopener"><b>{e(l.get("title", ""))}</b><span>{e(l.get("text", ""))}</span></a>'
         if l.get('href') else f'<div class="lk lk-off"><b>{e(l.get("title", ""))}</b><span>{e(l.get("text", ""))}</span></div>')
        for l in links)
    return f'<div class="sec" id="links">Материалы и ссылки</div><div class="lks">{items}</div>'


# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--portal', action='store_true')
    ap.add_argument('--out', default=str(REVIEW_DIR / f'{P.CODE}_structure.html'))
    ap.add_argument('--mock-rel', default=None, help='путь к мокапам относительно страницы (по умолчанию считается)')
    ap.add_argument('--full-res-thumbs', action='store_true', help='клик по превью ведёт на превью (4K не копируются)')
    a = ap.parse_args()
    out = Path(a.out)
    mock_rel = a.mock_rel or relpath(P.MOCK, out.parent).replace('\\', '/')

    plan = load_plan()
    page = plan.get('page') or {}
    words = load_words_doc(plan_words(plan))
    mont_path = REVIEW_DIR / (plan.get('out') or 'montage.json')
    if not mont_path.exists():
        raise SystemExit(f'нет {mont_path} — сначала build_montage.py')
    mont = json.loads(mont_path.read_text(encoding='utf-8'))
    an_path = REVIEW_DIR / 'analysis.json'
    an = json.loads(an_path.read_text(encoding='utf-8')) if an_path.exists() else {}
    canon = an.get('canon') or {}
    viz_by_n = {v['n']: v for v in an.get('viz', []) if v}
    man_path = P.MOCK / 'manifest.json'
    man = json.loads(man_path.read_text(encoding='utf-8')) if man_path.exists() else []
    seg_path = REVIEW_DIR / 'segments.json'
    segments = json.loads(seg_path.read_text(encoding='utf-8')) if seg_path.exists() else []
    spk = Speakers(speakers_map(plan), page, words)
    clips = plan_clips(plan)
    chapters = [tuple(c) for c in plan.get('chapters') or []]
    acts = []
    for p in mont['pieces']:
        if p.get('act') and p['act'] not in acts:
            acts.append(p['act'])

    # замечания ревью дизайна из каталогов
    reviews = {}
    scenes = []
    for sp_path, sc in scene_plans(plan):
        if not sp_path.exists():
            continue
        s_plan = load_plan(sp_path)
        s_mont_path = REVIEW_DIR / (sc.get('out') or s_plan.get('out') or 'montage_scene.json')
        s_mont = json.loads(s_mont_path.read_text(encoding='utf-8')) if s_mont_path.exists() else None
        s_words = load_words_doc(plan_words(s_plan)) if s_plan.get('words') else None
        scenes.append((sc, s_plan, s_mont, s_words))
    for pl in [plan] + [s[1] for s in scenes]:
        for g in pl.get('gfx_catalog') or []:
            if isinstance(g, dict):
                for scr in g.get('screens') or []:
                    if scr.get('review'):
                        reviews[f'{g["id"]}_{scr.get("variant", "A")}'] = scr['review']

    ch = P.CHANNEL.lower()
    num = P.CODE[len(P.CHANNEL):] if P.CODE.startswith(P.CHANNEL) else ''
    favicon = ('<link rel="icon" type="image/png" href="/favicon.png?v=1">'
               '<link rel="apple-touch-icon" href="/apple-touch-icon.png?v=1">' if a.portal else
               '<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' '
               'viewBox=\'0 0 100 100\'%3E%3Ctext y=\'.9em\' font-size=\'88\'%3E%F0%9F%8E%AC%3C/text%3E%3C/svg%3E">')
    crumbs = ('<nav class="crumbs"><a href="https://yt.rya.ae/">Overview</a><span>›</span>'
              '<a href="https://yt.rya.ae/#channels">Channels</a><span>›</span>'
              f'<a href="https://yt.rya.ae/{ch}/">{e(P.CHANNEL)}</a><span>›</span><b>{e(P.CODE)}</b></nav>')

    findings = []
    tags_map, skip = page.get('finding_tags') or {}, tuple(page.get('finding_skip') or [])
    for f in canon.get('global_findings', []):
        if skip and f.startswith(skip):
            continue
        tag = next((t for k, t in tags_map.items() if f.startswith(k)), None)
        findings.append(f'<div class="note n-warn">{e(f)}' + (f'<span class="ftag">✓ {e(tag)}</span>' if tag else '') + '</div>')

    n_new = sum(1 for m in man if m['kind'] == 'new')
    n_client = sum(1 for m in man if m['kind'] == 'client')
    n_qc_bad = sum(1 for m in man if m['kind'] == 'new' and m.get('qc') != 'ok')
    monts = [('', mont)] + [(sc.get('title') or 'сцена', s_mont) for sc, _, s_mont, _ in scenes if s_mont]
    screens = len(set().union(*[set(m.get('gfx_used', [])) for _, m in monts]))
    source_total = mont.get('source_total') or (clips[-1][2] if clips else 0)

    scene_html = ''
    for sc, s_plan, s_mont, s_words in scenes:
        if not s_mont:
            continue
        s_spk = Speakers(speakers_map(s_plan), sc, s_words or words)
        s_chapters = [tuple(c) for c in s_plan.get('chapters') or []]
        fsub = sc.get('frames_sub', 'story_frames_' + Path(sc['plan']).stem.replace('montage_plan_', ''))
        scene_html += (f'<div class="sec" id="scene-{Path(sc["plan"]).stem}">{e(sc.get("title") or s_mont.get("scene") or "Сцена")} — {mmss(s_mont["total"])}</div>'
                       + (f'<div class="note n-info">{sc["note"]}</div>' if sc.get('note') else '')
                       + build_story(s_mont, man, mock_rel, a.full_res_thumbs, P.MOCK / fsub, f'{mock_rel}/{fsub}',
                                     s_chapters, page, s_spk, acts))
    scene_clip_tables = ''
    scene_spk = ''
    for sc, s_plan, s_mont, s_words in scenes:
        if s_plan.get('clips'):
            scene_clip_tables += ((f'<div class="note n-info" style="margin-top:12px">{sc["clips_note"]}</div>' if sc.get('clips_note') else '')
                                  + clips_table(plan_clips(s_plan), page.get('clips_meta'), 'На таймлинии сцены'))
        if s_words and s_plan.get('speakers'):
            s_spk = Speakers(speakers_map(s_plan), sc, s_words)
            scene_spk += speaker_cards(s_spk, f' · {sc.get("title") or "сцена"}')
    toc_scene = ''.join(f'<a href="#scene-{Path(sc["plan"]).stem}">{e(sc.get("title") or "Сцена")}</a>' for sc, _, s_mont, _ in scenes if s_mont)

    hero_tags = [f'{mmss(source_total)} материала → {mmss(mont["total"])} чистовика'] + list(page.get('hero_tags') or [])
    if not page.get('hero_tags'):
        hero_tags += [' · '.join(f'камера {v["cam"]} — {v["name"]}' for v in spk.info.values() if v['cam'])]
    logline = canon.get('logline') or plan.get('structure_notes') or P.FILM
    h1 = page.get('h1') or f'{P.PROJECT_NAME.split("_", 1)[-1].replace("_", " ")} — структура и графика'
    devs = ''.join(f'<li>{e(d)}</li>' for d in page.get('deviations') or [])
    dev_html = f'<div class="note n-info"><b>Где я отошёл от плана разбора и почему:</b><ul class="devs">{devs}</ul></div>' if devs else ''
    notes_html = f'<div class="note n-ok"><b>О структуре целиком:</b> {e(plan["structure_notes"])}</div>' if plan.get('structure_notes') and not canon else ''
    montage_note = page.get('montage_note') or (
        '<div class="note n-ok"><b>Это рабочая структура видео.</b> Каждая склейка привязана к пословным таймкодам: '
        'начало первого слова и конец последнего плюс до 0,3 с воздуха. Для каждой указаны файл и смещение внутри него, '
        'камера и паузы к подрезке. Цветная лента — хронометраж по актам, клик ведёт к куску.</div>')
    gallery_note = page.get('gallery_note') or (
        '<div class="note n-info">Отрисованы по правилам скилла <b>infographic</b>: нативные 3840×2160, текст версткой, '
        'плашки с альфой для Premiere, метка DRAFT. Раскладка проверена локально, без облака: title-safe 5 % и переполнение блоков '
        + ('(все экраны прошли).' if n_qc_bad == 0 else f'(замечания у {n_qc_bad} — подписаны красным).') + '</div>')
    blocks_note = page.get('blocks_note') or ('<div class="note n-info">Смысловые блоки в порядке съёмки, с вердиктом монтажа. Это диагноз '
                                              'исходника; рабочая структура — монтажный лист выше.</div>')
    transcript_note = page.get('transcript_note') or ('<div class="note n-info">Дословно, без правок. Таймкоды — по сквозной таймлинии '
                                                      'съёмочного дня (клипы встык). Роли — диаризация.</div>')
    foot = page.get('foot') or (f'<b>{e(P.CODE)} · {e(P.FILM)}.</b> Транскрибация — whisper large-v3 (MLX) с пословными таймкодами, '
                                f'{words.get("n_words", "—")} слов, {words.get("n_segments", "—")} сегментов. Монтажный лист, 4K-мокапы, '
                                'проверка раскладки и эта страница собраны локально (scripts/05_editing/0509_review_cycle/montage). Собрано R.Y.A Media Lab.')
    style_html = f'<div class="sec" id="style">Визуальный язык клиента</div>{page["style_html"]}' if page.get('style_html') else ''
    voices_note = page.get('voices_note') or ''
    seam_note = f'<div class="note n-warn" style="margin-top:12px">{page["seam_note"]}</div>' if page.get('seam_note') else ''
    an_details = ''
    if canon:
        an_details = (f'<div class="sec" id="findings">Что нашли в исходнике</div>{"".join(findings)}')
    blocks_html = (f'<div class="sec" id="blocks">Блоки исходника — диагноз</div>{blocks_note}{build_blocks(canon, viz_by_n, spk)}' if canon else '')
    cuts_html = build_cuts(plan.get('cuts'), segments)

    doc = f"""<!DOCTYPE html>
<html lang="ru" data-channel="{e(ch)}" data-page="/{e(ch)}/{e(num)}/" data-rya-theme="core" data-rya-haschrome="1">
<head>
{favicon}
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{e(P.CODE)} · {e(h1)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<style>{CSS}
{spk.css()}
</style>
{PORTAL_HEAD if a.portal else ''}
</head>
<body>

<div class="topbar">
  <a href="https://yt.rya.ae/" class="brand"><div class="brand-mark">{e(P.CHANNEL[2:4] if len(P.CHANNEL) > 3 else P.CHANNEL[-2:])}</div><div class="brand-text">yt<span class="dim">.rya.ae</span></div></a>
  {crumbs}
</div>

<section class="hero"><div class="hero-in">
  <div><span class="id">{e(P.CODE)}</span></div>
  <h1>{e(h1)}</h1>
  <div class="tags">{''.join(f'<span>{e(t)}</span>' for t in hero_tags if t)}</div>
  <p>{e(logline)}</p>
  <div class="kpis">
    <div class="kpi"><div class="v">{mmss(mont["total"])}</div><div class="l">чистовик по листу</div></div>
    <div class="kpi"><div class="v">≈{mmss(mont["total_trimmed"])}</div><div class="l">после подрезки пауз</div></div>
    <div class="kpi"><div class="v">{len(mont["pieces"])} / {mont["n_say_parts"]}</div><div class="l">кусков / склеек речи</div></div>
    <div class="kpi"><div class="v">{screens}</div><div class="l">экранов графики</div></div>
    <div class="kpi"><div class="v">{n_new}+{n_client}</div><div class="l">мокапов 4K + слайдов клиента</div></div>
  </div>
  <div class="toc">
    {'<a href="#links">Материалы</a>' if links_block(page) else ''}<a href="#story">Рассказ ↔ экран</a><a href="#chapters">Главы</a>{toc_scene}<a href="#montage">Монтажный лист</a><a href="#screens">Все экраны</a>
    {'<a href="#cuts">Вердикты</a>' if cuts_html else ''}{'<a href="#findings">Находки</a>' if canon else ''}<a href="#source">Исходник</a><a href="#voices">Голоса</a>
    {'<a href="#blocks">Блоки исходника</a>' if canon else ''}{'<a href="#style">Язык клиента</a>' if style_html else ''}<a href="#transcript">Транскрипт</a>
  </div>
</div></section>

<div class="wrap">

  {links_block(page)}

  <div class="sec" id="story">Сценарий чистовика · рассказ ↔ экран</div>
  {HOW_TO_READ}
  {dev_html}{notes_html}
  {build_story(mont, man, mock_rel, a.full_res_thumbs, P.MOCK / 'story_frames', f'{mock_rel}/story_frames', chapters, page, spk, acts)}

  <div class="sec" id="chapters">Главы для YouTube</div>
  {build_chapters(mont, chapters) if chapters else '<div class="note">главы ещё не назначены (plan.chapters)</div>'}

  {scene_html}

  <div class="sec">Технический слой и разбор</div>
  <details class="dz"><summary>Монтажный лист — склейки, файлы, паузы, стыки</summary>
  <div class="sec" id="montage">Структура чистовика — монтажный лист</div>
  {montage_note}
  {build_montage(mont, spk, acts)}
  </details>

  <details class="dz"><summary>Все экраны графики — варианты A/B и где стоят</summary>
  <div class="sec" id="screens">Экраны графики — {screens} шт.</div>
  {gallery_note}
  {build_gallery(monts, man, mock_rel, a.full_res_thumbs, page, reviews)}
  </details>

  <details class="dz"><summary>Разбор исходника — вердикты, файлы, голоса, блоки, транскрибация</summary>
  {cuts_html}
  {an_details}

  <div class="sec" id="source">Исходный материал</div>
  {clips_table(clips, page.get('clips_meta'), 'На сквозной таймлинии')}
  {scene_clip_tables}
  {seam_note}

  <div class="sec" id="voices">Кто говорит</div>
  <div class="sp-grid">{speaker_cards(spk)}{scene_spk}</div>
  {voices_note}

  {blocks_html}
  {style_html}
  {build_issues(an.get("check"), "Сверка разбора: что проверено построчно", "ok", "check")}
  {build_issues(an.get("critic"), "Чего в разборе не хватало", "warn", "critic")}

  <div class="sec" id="transcript">Полная транскрибация по ролям</div>
  {transcript_note}
  <div class="tr-wrap">{build_transcript(words, spk)}</div>
  </details>

  <div class="foot">{foot}</div>
</div>
{STORY_JS}
{PORTAL_BODY if a.portal else ''}
</body>
</html>
"""
    out.write_text(doc, encoding='utf-8')
    print(f'written: {out}  ({len(doc)} bytes) · кусков {len(mont["pieces"])} · экранов {screens} · мокапов {len(man)} · сцен {len(scenes)}')


if __name__ == '__main__':
    main()
