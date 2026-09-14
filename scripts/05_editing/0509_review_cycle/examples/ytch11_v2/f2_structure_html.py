#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""YTCH11_v3_structure.html — структура целевого фильма v3 как страница-борд.

Вход: tobe_acts.json (акты→главы→блоки, тексты дословные из Plan_v3_TOBE ред.3:
      кат — words.json рендера v2, вставки — транскрипты исходников), кадры
      tobe_frames/, склейки v2_cuts.json (scdet 0.30), words.json (спикеры).
Слои: оглавление, лента фильма + полоса динамики, акты с карточками блоков —
ПОЛНАЯ транскрибация (подписи спикеров через выравнивание с words.json, абзацы,
все опорные фразы подсвечены), директивы сбоку. Файл самодостаточный (base64).
Выход: {project}/00_Setup/05_Review/YTCH11_v3_structure.html
"""
import base64
import html as H
import json
import os
import re

SCR = os.path.dirname(os.path.abspath(__file__))
S = os.path.dirname(SCR)
OUT = os.path.join(S, 'YTCH11_v3_structure.html')
acts = json.load(open(f'{SCR}/tobe_acts.json'))

ARC = ['Хук: жесть + «попрошайничаем» + тиктоки + Виталик-отец',
       'Мама Лизы — полный треш (ядро директивы)',
       'Виталик — коротко, после мамы',
       'Как росла Лиза — вся жесть, кода «никто не приехал»',
       'Они нашли друг друга (новая глава)',
       '«Я написала сама» + фонд мелкими кусками',
       'Жизнь сейчас и планы (выдох, кольцо с блогерством)',
       'Напутствие → CTA → последнее слово героев']

NAME = {'Speaker 1': 'Лиза', 'Speaker 2': 'Гуля', 'Speaker 3': 'Виталик',
        'Speaker 4': 'Маша', 'Speaker 5': 'Люба'}
SPCLS = {'Лиза': 'sp1', 'Гуля': 'sp2', 'Виталик': 'sp3', 'Маша': 'sp4',
         'Люба': 'sp5', 'Роман (ЗК)': 'sp0'}

w = json.load(open(f'{S}/YTCH11_v2.words.json'))
FLAT = []
for seg in w['segments']:
    for wd in seg['words']:
        sp = wd.get('speaker') or seg.get('speaker')
        nm = 'Роман (ЗК)' if (sp == 'Speaker 5' and 2364 <= wd['s'] <= 2371) else NAME[sp]
        FLAT.append((wd['w'], wd['s'], nm))

def norm(t):
    m = re.findall(r'[А-Яа-яЁёA-Za-z0-9]+', t.lower().replace('ё', 'е'))
    return m[0] if m else None

FN = [norm(x[0]) for x in FLAT]

def fmt(s):
    s = int(round(s))
    return f'{s // 60}:{s % 60:02d}'

def b64(img):
    p = f'{SCR}/tobe_frames/{img}'
    if not img or not os.path.exists(p):
        return None
    return 'data:image/jpeg;base64,' + base64.b64encode(open(p, 'rb').read()).decode()

def akind(action):
    a = action.replace('реш. фонда', '').strip()
    if a.startswith('⛔'):
        return 'cut'
    if a.startswith('➕'):
        return 'ins'
    if a.startswith('✂️'):
        return 'trim'
    if a.startswith('⇄'):
        return 'move'
    return 'keep'

KCOL = {'keep': '#7d93b8', 'move': '#d9a441', 'trim': '#e2833a', 'ins': '#4faa72',
        'cut': '#b23a3a'}
KNAME = {'keep': '= кат v2', 'move': '⇄ перенос', 'trim': '✂️ сжатие',
         'ins': '➕ вставка', 'cut': '⛔ вырез'}


# ---------- спикеры: выравнивание текста блока с words.json ----------
def align_speakers(text, v2a=None, v2b=None):
    """Токены текста → имена спикеров (выравнивание с FLAT). Текст не меняется.
    Возврат: список (word, speaker|None) по словам текста."""
    words = text.split()
    nws = [norm(x) for x in words]
    # стартовая позиция: первые 6 значимых токенов в окне вокруг v2a (или глобально)
    sig = [(i, t) for i, t in enumerate(nws) if t]
    if not sig:
        return [(x, None) for x in words]

    def find_at(idx_from, need, lo, hi):
        pat = [t for _, t in need]
        for j in range(max(0, lo), min(len(FN) - len(pat), hi)):
            if all(FN[j + k] == pat[k] for k in range(len(pat))):
                return j
        return -1

    out = [None] * len(words)
    ti = 0          # позиция в sig
    wj = -1
    lo, hi = 0, len(FN)
    if v2a is not None:
        lo = max(0, next((i for i, x in enumerate(FLAT) if x[1] >= v2a - 45), 0))
        hi = next((i for i, x in enumerate(FLAT) if x[1] > (v2b or v2a) + 45), len(FN))
    while ti < len(sig):
        chunk = sig[ti:ti + 6]
        j = find_at(ti, chunk, lo if wj < 0 else wj, hi if wj < 0 else min(len(FN), wj + 250))
        if j < 0 and wj >= 0:
            j = find_at(ti, chunk, 0, len(FN))     # ресинк глобально (составные блоки)
        if j < 0:
            ti += 1
            continue
        # жадно тянем совпадение дальше
        k = 0
        while ti + k < len(sig) and j + k < len(FN) and sig[ti + k][1] == FN[j + k]:
            out[sig[ti + k][0]] = FLAT[j + k][2]
            k += 1
        wj = j + k
        ti += max(k, 1)
    cov = sum(1 for x in out if x) / max(1, len(sig))
    if cov < 0.7:
        return [(x, None) for x in words]
    # дырки заполняем соседним спикером (пунктуация/непойманные)
    last = None
    for i in range(len(out)):
        if out[i] is None:
            out[i] = last
        else:
            last = out[i]
    return list(zip(words, out))


def paragraphs_v2(text, v2a, v2b):
    """Абзацы: смена спикера + разрез длинных прогонов по границе предложения."""
    pairs = align_speakers(text, v2a, v2b)
    runs = []
    for word, sp in pairs:
        if runs and runs[-1][0] == sp:
            runs[-1][1].append(word)
        else:
            runs.append([sp, [word]])
    # поглощение 1-словных чужих вкраплений без финальной пунктуации
    merged = []
    for sp, ws in runs:
        if merged and len(ws) == 1 and not ws[0].rstrip().endswith(('.', '?', '!')) \
                and merged[-1][0] == sp:
            merged[-1][1] += ws
        elif merged and merged[-1][0] == sp:
            merged[-1][1] += ws
        else:
            merged.append([sp, list(ws)])
    paras = []
    for sp, ws in merged:
        # длинный прогон → резать по предложению каждые ~55-80 слов
        start = 0
        while len(ws) - start > 80:
            cut = -1
            for i in range(start + 50, min(start + 82, len(ws) - 8)):
                if ws[i].rstrip().endswith(('.', '?', '!')):
                    cut = i + 1
                    break
            if cut < 0:
                break
            paras.append((sp if start == 0 else None, ' '.join(ws[start:cut])))
            start = cut
        paras.append((sp if start == 0 else None, ' '.join(ws[start:])))
    return paras


def paragraphs_plain(text):
    return [(None, p.strip()) for p in re.split(r'\n+', text) if p.strip()]


def render_transcript(b):
    if 'v2a' in b:
        paras = paragraphs_v2(b['text'], b['v2a'], b['v2b'])
    else:
        paras = paragraphs_plain(b['text'])
    # подсветка опорных фраз: по абзацам, без учёта регистра, первое вхождение
    todo = list(b.get('bold') or [])
    outp = []
    for sp, ptxt in paras:
        esc = H.escape(ptxt)
        for ph in list(todo):
            pe = H.escape(ph)
            m = re.search(re.escape(pe), esc, re.IGNORECASE)
            if not m:
                # токенный fallback: те же слова, любая пунктуация/пробелы между ними
                tk = re.findall(r'[А-Яа-яЁёA-Za-z0-9]+', pe)
                if tk:
                    m = re.search(r'\b' + r'[^А-Яа-яЁёA-Za-z0-9]{1,4}'.join(
                        re.escape(t) for t in tk), esc, re.IGNORECASE)
            if m:
                esc = esc[:m.start()] + '<mark>' + esc[m.start():m.end()] + '</mark>' + esc[m.end():]
                todo.remove(ph)
        lbl = (f'<span class="spk {SPCLS.get(sp, "sp0")}">{H.escape(sp)}:</span> '
               if sp else '')
        outp.append(f'<p>{lbl}{esc}</p>')
    return ''.join(outp)


film_acts = [a for a in acts if not a['title'].startswith('⛔')]
basket = [a for a in acts if a['title'].startswith('⛔')]

blocks_flat = []
for ai, a in enumerate(film_acts):
    for ch in a['chapters']:
        for b in ch['blocks']:
            b['_act'] = ai
            b['_kind'] = akind(b['action'])
            blocks_flat.append(b)
total = sum(b['dur'] for b in blocks_flat if b['_kind'] != 'cut')
n_ins = sum(1 for b in blocks_flat if '➕' in b['action'])

def dynclass(b):
    if 'cpm' not in b:
        return 'new'
    if b['cpm'] >= 8:
        return 'hi'
    if b['cpm'] >= 4:
        return 'mid'
    return 'lo'


# ---------- оглавление ----------
toc = []
for ai, a in enumerate(film_acts):
    chs = ''.join(f'<a href="#c{ai}_{ci}">{H.escape(re.sub(r" · .*$", "", ch["title"]))}</a>'
                  for ci, ch in enumerate(a['chapters']) if ch['title'])
    short = re.sub(r'^АКТ \d+ · ', '', a['title']).split(' · ~')[0]
    toc.append(f'<div class="tocact"><a class="ta" href="#act{ai}">'
               f'<b>{ai + 1}</b> {H.escape(short)}</a><div class="tch">{chs}</div></div>')

# ---------- лента фильма + полоса динамики ----------
ruler, strip = [], []
for ai, a in enumerate(film_acts):
    ad = sum(b['dur'] for ch in a['chapters'] for b in ch['blocks']
             if akind(b['action']) != 'cut')
    ruler.append(f'<div class="ract" style="width:{ad / total * 100:.2f}%">'
                 f'<span>АКТ {ai + 1}</span><em>{fmt(ad)}</em></div>')
for b in blocks_flat:
    if b['_kind'] == 'cut':
        strip.append(f'<div class="bcut" title="⛔ вырез {fmt(b["dur"])} — '
                     f'{H.escape(b["note"][:80])}"></div>')
        continue
    w_ = b['dur'] / total * 100
    h = 6 if 'cpm' not in b else max(6, min(34, b['cpm'] * 2))
    warn = '<i class="w"></i>' if b.get('maxgap', 0) > 40 else ''
    tip = (f'№{b["num"]} · {fmt(b["dur"])} · {KNAME[b["_kind"]]}'
           + (f' · {b["cpm"]} скл/мин, макс. прогон {b["maxgap"]}с' if 'cpm' in b
              else ' · новый материал'))
    strip.append(
        f'<a class="bl" href="#b{b["num"]}" style="width:{w_:.2f}%" title="{H.escape(tip)}">'
        f'<span class="mat" style="background:{KCOL[b["_kind"]]}"></span>'
        f'<span class="dyn {dynclass(b)}" style="height:{h}px">{warn}</span></a>')

# ---------- ритм-выводы ----------
plateau = [b for b in blocks_flat if b.get('maxgap', 0) > 40 and b['_kind'] != 'cut']
rhythm_rows = []
for b in plateau:
    fix = {'trim': 'сжимается + перекрывается', 'move': 'переносится',
           'keep': 'держим осознанно (атмосфера)', 'ins': ''}[b['_kind']]
    if b['num'] == '36':
        fix = 'пересказ заменяют сами вертикали Лизы'
    if b['num'] in ('20', '22'):
        fix = 'осознанно: интерьер-жесть длинными кусками (канон ТЗ)'
    if b['num'] == '41':
        fix = 'остаётся коротким куском между перебивками'
    rhythm_rows.append(f'<tr><td><a href="#b{b["num"]}">№{b["num"]}</a></td>'
                       f'<td>{b.get("maxgap")}с без склейки · {b.get("cpm")} скл/мин</td>'
                       f'<td>{H.escape(fix)}</td></tr>')


# ---------- карточка блока ----------
def block_card(b):
    img = b64(b.get('img'))
    imtag = f'<img src="{img}" loading="lazy">' if img else '<div class="noimg"></div>'
    if 'cpm' in b:
        dyn = f'<span class="chip {dynclass(b)}">{b["cpm"]} скл/мин · макс {b["maxgap"]}с</span>'
        if b.get('maxgap', 0) > 40 and b['_kind'] == 'trim':
            dyn += '<span class="chip fix">темп ↑ после сжатия</span>'
    else:
        dyn = '<span class="chip new">новый материал — перебивка</span>'
    src = H.escape(re.sub(r'\s*\n\s*', ' · ', b['src']))
    quotes = ''.join(f'<span class="q">«{H.escape(ph)}»</span>'
                     for ph in (b.get('bold') or []))
    cls = 'card' + (' cardcut' if b['_kind'] == 'cut' else '')
    return (f'<div class="{cls}" id="b{b["num"]}">'
            f'<div class="chead">'
            f'<div class="thumb">{imtag}<b class="dur">{fmt(b["dur"])}</b></div>'
            f'<div class="cmeta"><div class="l1"><span class="num">№{b["num"]}</span>'
            f'<span class="act-badge" style="background:{KCOL[b["_kind"]]}1a;'
            f'color:{KCOL[b["_kind"]]}">{H.escape(b["action"])}</span>'
            f'<span class="src">{src}</span>{dyn}</div>'
            + (f'<div class="quotes">{quotes}</div>' if quotes else '')
            + f'<div class="note">{H.escape(b["note"])}</div></div></div>'
            f'<div class="tr">{render_transcript(b)}</div>'
            f'</div>')


sections = []
for ai, a in enumerate(film_acts):
    ad = sum(b['dur'] for ch in a['chapters'] for b in ch['blocks']
             if akind(b['action']) != 'cut')
    parts = [f'<section class="act" id="act{ai}">'
             f'<div class="acthead"><h2>{H.escape(a["title"])}</h2>'
             f'<div class="actmeta"><b>{fmt(ad)}</b> · {H.escape(ARC[ai])}</div></div>']
    for ci, ch in enumerate(a['chapters']):
        if ch['title']:
            parts.append(f'<h3 id="c{ai}_{ci}">{H.escape(ch["title"])}</h3>')
        for b in ch['blocks']:
            parts.append(block_card(b))
    parts.append('</section>')
    sections.append('\n'.join(parts))

basket_rows = []
for a in basket:
    for ch in a['chapters']:
        for b in ch['blocks']:
            basket_rows.append(
                f'<div class="brow"><span class="num">№{b["num"]}</span>'
                f'<span class="src">{H.escape(b["src"])}</span>'
                f'<span>{H.escape(b["note"])}</span></div>')

# ---------- 💎 резерв из исходников (source_gems_final.json, если готов) ----------
GEM_GROUPS = [
    ('Закатное интервью пары (0841/0842)',
     lambda f: f in ('CLIP/RYA-FX3-0841.srt', 'CLIP/RYA-FX3-0842.srt')),
    ('Лысково — камера (0808/0809 и клипы дня)',
     lambda f: f.startswith('CLIP/') and 'RYA-FX3-08' in f),
    ('Лысково и день — петлички (TX MIC044–052)',
     lambda f: f.startswith('Audio/') and re.search(r'MIC0(4[4-9]|5[0-2])', f)),
    ('Вечер дома — петлички (TX MIC001–004)',
     lambda f: f.startswith('Audio/') and re.search(r'MIC00[1-4]', f)),
    ('Фонд: Гуля и Маша (синхроны)',
     lambda f: f.startswith(('D_Sync', 'D_Channel'))),
    ('Прочее', lambda f: True),
]
STAR = {5: '★★★★★', 4: '★★★★', 3: '★★★'}


def gem_card(g, i):
    alt = (' <span class="galt">дубль: ' + ' · '.join(H.escape(x) for x in g['alt'])
           + '</span>') if g.get('alt') else ''
    sens = ' <span class="chip lo">⚠️ фонд/блюр</span>' if g.get('sensitive') else ''
    unj = ' <span class="chip mid">не суджено</span>' if g.get('unjudged') else ''
    note = g.get('judge_note') or ''
    fl = g['file'].split('/')[-1].replace('.srt', '')
    return (f'<div class="gem" id="g{i}">'
            f'<div class="gl1"><b class="gstar s{g["strength"]}">{STAR.get(g["strength"], "★")}</b>'
            f'<span class="gcat">{H.escape(g["category"])}</span>'
            f'<span class="gsrc">{H.escape(fl)} @ {H.escape(g["tc"])}</span>'
            f'<span class="gspk">{H.escape(g["speaker"])}</span>{sens}{unj}{alt}</div>'
            f'<div class="gquote">«{H.escape(g["quote"])}»</div>'
            f'<div class="gwhy">{H.escape(g["why"])}'
            + (f' <i>· судья: {H.escape(note)}</i>' if note else '') + '</div></div>')


gems_html = ''
gems_path = os.path.join(SCR, 'source_gems_final.json')
if os.path.exists(gems_path):
    gems = [g for g in json.load(open(gems_path)) if g['strength'] >= 3]
    n5 = sum(1 for g in gems if g['strength'] == 5)
    n4 = sum(1 for g in gems if g['strength'] == 4)
    n3 = sum(1 for g in gems if g['strength'] <= 3)
    parts = [f'<section class="act" id="gems"><div class="acthead">'
             f'<h2>💎 Резерв из исходников — НЕ в кате и НЕ в плане v3</h2>'
             f'<div class="actmeta">полный свип 01_Source/Transcription (майнинг → дуги → '
             f'судьи): ★5 — {n5} · ★4 — {n4} · ★3 (резерв) — {n3}. '
             f'Дубли одной сцены с разных микрофонов схлопнуты (адреса дублей указаны). '
             f'Цитаты дословные, whisper как есть.</div></div>']
    gi = 0
    used = set()
    for title, pred in GEM_GROUPS:
        grp = [g for g in gems if id(g) not in used and pred(g['file'])]
        if not grp:
            continue
        for g in grp:
            used.add(id(g))
        parts.append(f'<h3>{H.escape(title)} · {len(grp)}</h3>')
        for g in sorted(grp, key=lambda x: (-x['strength'], x['file'], x['tc'])):
            parts.append(gem_card(g, gi))
            gi += 1
    parts.append('</section>')
    gems_html = '\n'.join(parts)

css = '''
*{box-sizing:border-box;margin:0}
html{scroll-behavior:smooth}
body{font:14px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif;color:#26282c;
 background:#f4f4f2;padding:0 0 80px}
.wrap{max-width:1160px;margin:0 auto;padding:0 28px}
header{padding:34px 0 10px}
h1{font-size:25px;letter-spacing:-.3px}
.sub{color:#6b6f76;margin-top:6px}
.stats{display:flex;gap:26px;flex-wrap:wrap;margin:16px 0 4px}
.stat b{font-size:19px;display:block}.stat span{font-size:11.5px;color:#8a8e94;
 text-transform:uppercase;letter-spacing:.4px}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:#555;margin:12px 0 8px}
.legend i{display:inline-block;width:11px;height:11px;border-radius:2px;
 vertical-align:-1px;margin-right:5px}
.toc{background:#fff;border:1px solid #e3e3df;border-radius:10px;padding:14px 18px;
 margin:10px 0 14px;display:grid;grid-template-columns:repeat(4,1fr);gap:10px 22px}
.tocact .ta{font-weight:600;font-size:12.5px;color:#26282c;text-decoration:none}
.tocact .ta b{display:inline-block;width:17px;height:17px;border-radius:50%;
 background:#26282c;color:#fff;font-size:10.5px;text-align:center;line-height:17px;
 margin-right:5px}
.tch{margin:4px 0 0 22px;display:flex;flex-direction:column;gap:1px}
.tch a{font-size:11px;color:#7a7e84;text-decoration:none}
.tch a:hover,.tocact .ta:hover{color:#1156a8}
.stripbox{background:#fff;border:1px solid #e3e3df;border-radius:10px;
 padding:16px 18px 12px;margin:0 0 22px}
.ruler{display:flex;margin-bottom:4px}
.ract{border-left:2px solid #c9cbc7;padding:0 0 2px 6px;font-size:10.5px;
 color:#7a7e84;white-space:nowrap;overflow:hidden}
.ract em{font-style:normal;color:#b0b3b0;margin-left:5px}
.strip{display:flex;align-items:flex-end;height:64px}
.bl{display:flex;flex-direction:column;justify-content:flex-end;height:100%;
 padding:0 .5px;min-width:3px;text-decoration:none}
.bl .mat{height:14px;border-radius:2px;order:2;margin-top:2px}
.bl .dyn{border-radius:2px 2px 0 0;order:1;position:relative;opacity:.85}
.dyn.hi{background:#69b98a}.dyn.mid{background:#e0b45a}.dyn.lo{background:#d97878}
.dyn.new{background:repeating-linear-gradient(45deg,#bcd9c8 0 4px,#e6f2ea 4px 8px)}
.dyn .w{position:absolute;top:-7px;left:50%;margin-left:-3px;width:6px;height:6px;
 border-radius:50%;background:#c0392b}
.bcut{width:4px;background:#b23a3a;height:22px;align-self:flex-end;border-radius:1px;
 margin:0 1px}
.striplabels{display:flex;justify-content:space-between;font-size:10.5px;
 color:#a0a3a0;margin-top:6px}
.rhythm{background:#fff;border:1px solid #e3e3df;border-radius:10px;
 padding:16px 18px;margin-bottom:28px}
.rhythm h2{font-size:15px;margin-bottom:8px}
.rhythm table{border-collapse:collapse;width:100%;font-size:12.5px}
.rhythm td{padding:4px 10px 4px 0;border-top:1px solid #efefec;vertical-align:top}
.rhythm a{color:#26282c}
.act{margin:34px 0 8px}
.acthead{position:sticky;top:0;z-index:20;background:#f4f4f2;
 border-left:4px solid #26282c;padding:8px 0 8px 12px;margin-bottom:12px}
.acthead h2{font-size:16.5px}
.actmeta{color:#6b6f76;font-size:12.5px;margin-top:2px}
h3{font-size:13px;color:#55585e;margin:18px 0 8px}
.card{background:#fff;border:1px solid #e5e5e1;border-radius:9px;
 padding:12px;margin-bottom:10px;scroll-margin-top:66px}
.cardcut{opacity:.62;background:#fbf1f1;border-color:#ecd6d6}
.chead{display:flex;gap:14px}
.thumb{position:relative;flex:0 0 148px}
.thumb img{width:148px;border-radius:6px;display:block}
.noimg{width:148px;height:83px;border-radius:6px;background:#e8e8e4}
.dur{position:absolute;right:5px;bottom:5px;background:rgba(0,0,0,.66);color:#fff;
 font-size:10.5px;font-weight:600;padding:1px 5px;border-radius:3px}
.cmeta{flex:1;min-width:0}
.l1{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
.num{font-weight:700;font-size:12.5px}
.act-badge{font-size:11px;font-weight:600;padding:1px 7px;border-radius:9px;
 white-space:nowrap}
.src{font-size:11.5px;color:#8a8e94}
.chip{font-size:10.5px;padding:1px 7px;border-radius:8px;white-space:nowrap}
.chip.hi{background:#e4f2e9;color:#2e7d4f}.chip.mid{background:#faf0d8;color:#94700f}
.chip.lo{background:#f9e4e4;color:#b03535}
.chip.new{background:#e6f2ea;color:#3d8a63}.chip.fix{background:#eef;color:#4b5aa8}
.quotes{margin:6px 0 2px;display:flex;flex-wrap:wrap;gap:4px 10px}
.quotes .q{font-size:12.5px;font-style:italic;color:#3a3d42;font-weight:600}
.note{font-size:12px;color:#65686e;margin-top:5px;white-space:pre-line}
.tr{margin-top:10px;border-top:1px solid #eeeeea;padding-top:8px;
 columns:2 340px;column-gap:34px}
.tr p{font-size:12.8px;line-height:1.58;color:#33363b;margin:0 0 8px;
 break-inside:avoid}
.tr mark{background:#ffe9a8;padding:0 2px;border-radius:2px;font-weight:600}
.spk{font-weight:700;font-size:11.5px}
.sp1{color:#b0447d}.sp3{color:#2b6cb0}.sp2{color:#2e7d4f}.sp4{color:#0e8074}
.sp5{color:#7b52ab}.sp0{color:#6b6f76}
.gem{background:#fff;border:1px solid #e5e5e1;border-left:3px solid #b8a24a;
 border-radius:8px;padding:10px 14px;margin-bottom:8px}
.gl1{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:11.5px}
.gstar{letter-spacing:1px}.gstar.s5{color:#b8860b}.gstar.s4{color:#8a7a30}
.gstar.s3{color:#a5a08a}
.gcat{background:#f0efe9;border-radius:8px;padding:1px 8px;color:#6b6a5e}
.gsrc{color:#8a8e94}.gspk{font-weight:600}
.galt{color:#a0a3a0;font-size:10.5px}
.gquote{font-size:13px;line-height:1.55;color:#2f3236;margin:6px 0 4px}
.gwhy{font-size:11.5px;color:#75786e}
.gwhy i{color:#9a8f5f}
.basket{background:#faf0f0;border:1px solid #ebd5d5;border-radius:10px;
 padding:16px 18px;margin:34px 0 0}
.basket h2{font-size:15px;color:#8c3232;margin-bottom:10px}
.brow{display:flex;gap:12px;font-size:12.5px;padding:5px 0;border-top:1px solid #f0dddd}
.brow .src{flex:0 0 190px}
.ask{background:#fff;border:1px solid #e3e3df;border-radius:10px;padding:16px 18px;
 margin-top:18px;font-size:13px}
.ask h2{font-size:15px;margin-bottom:8px}
.ask li{margin:4px 0 4px 18px}
footer{color:#a3a6a3;font-size:11.5px;margin-top:34px}
@media(max-width:820px){.toc{grid-template-columns:repeat(2,1fr)}
 .chead{flex-direction:column}.tr{columns:1}}
'''

stats = f'''
<div class="stats">
<div class="stat"><b>{fmt(total)}</b><span>целевой хронометраж</span></div>
<div class="stat"><b>8</b><span>актов</span></div>
<div class="stat"><b>{sum(1 for b in blocks_flat if b['_kind'] != 'cut')}</b><span>блоков</span></div>
<div class="stat"><b>{n_ins}</b><span>вставок ➕</span></div>
<div class="stat"><b>−6:55&thinsp;/&thinsp;+6:20</b><span>вырезы / вставки vs v2</span></div>
<div class="stat"><b>7.6с</b><span>средняя склейка v2</span></div>
</div>'''

legend = ('<div class="legend">'
          + ''.join(f'<span><i style="background:{KCOL[k]}"></i>{KNAME[k]}</span>'
                    for k in ('keep', 'move', 'trim', 'ins', 'cut'))
          + '<span style="margin-left:14px"><i style="background:#69b98a"></i>живо (≥8 скл/мин)</span>'
            '<span><i style="background:#e0b45a"></i>средне</span>'
            '<span><i style="background:#d97878"></i>статично (&lt;4)</span>'
            '<span><i style="background:repeating-linear-gradient(45deg,#bcd9c8 0 3px,#e6f2ea 3px 6px)"></i>новый материал</span>'
            '<span>● прогон &gt;40с</span>'
            '<span style="margin-left:14px"><span class="spk sp1">Лиза</span> · '
            '<span class="spk sp3">Виталик</span> · <span class="spk sp2">Гуля</span> · '
            '<span class="spk sp4">Маша</span> · <span class="spk sp5">Люба</span> · '
            '<span class="spk sp0">Роман (ЗК)</span></span></div>')

doc = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>YTCH11 · Структура фильма v3</title><style>{css}</style></head><body>
<div class="wrap">
<header>
<h1>YTCH11 · Лиза и Виталик — структура фильма v3</h1>
<div class="sub">Целевая картинка по директивам Романа 27.08 (Plan v3 TO-BE ред.3).
Транскрибации ПОЛНЫЕ и дословные: кат — из words.json рендера v2 (подписи спикеров),
вставки — из транскриптов исходников проекта (адрес: сцена · файл · TC в шапке блока).
Жёлтым подсвечены опорные фразы. Динамика — из склеек рендера v2 (scdet 0.30, 385 склеек).</div>
{stats}
{legend}
</header>

<div class="toc">{''.join(toc)}</div>

<div class="stripbox">
<div class="ruler">{''.join(ruler)}</div>
<div class="strip">{''.join(strip)}</div>
<div class="striplabels"><span>0:00</span><span>лента будущего фильма — клик по блоку ведёт к карточке</span><span>{fmt(total)}</span></div>
</div>

<div class="rhythm">
<h2>Ритм: где v2 стоит на месте — и что с этим делает v3</h2>
<table>{''.join(rhythm_rows)}</table>
<div style="font-size:12px;color:#8a8e94;margin-top:8px">Худшие плато v2 живут в
фонд-монолите (распаковки 79с, Маша 71с, Гуля 49с) — в v3 монолит распущен на 6 коротких
кусков, между ними герои и быт. Длинные планы в Лысково (53с, 46с) — осознанные:
интерьер-жесть держим длинными кусками по канону ТЗ. Каждая ➕-вставка — сама по себе
смена кадра: {n_ins} новых перебивок по всей ленте.</div>
</div>

{''.join(sections)}

{gems_html}

<div class="basket"><h2>⛔ Корзина — уходит из v2 совсем (≈ −6:55)</h2>
{''.join(basket_rows)}</div>

<div class="ask"><h2>Запросить для v3</h2><ol>
<li>Тиктоки Лизы (экспорт с телефона / ссылки) — акт 1 и кольцо с блогерством.</li>
<li>Видео-распаковки и сторис благодарности (у Лизы/фонда) — заменяют пересказ Гули.</li>
<li>Письменное согласие отца/опекуна на Любу (иначе блюр + вырез реплик).</li>
<li>Решение фонда: доксинг-вставка (0809 · 1:21:24), формулировки треш-кластера (37–41),
интерьеры после вскрытия.</li>
<li>Прослушать 0842 · 46:38 («месть/проклятье») и 04 · 9:41 («он от нас ушёл в 13 лет»).</li>
</ol></div>

<footer>YTCH11_v3_structure.html · собрано 06.09.2026 из Plan_v3_TOBE (ред.3) ·
транскрибации: words.json v2 + транскрипты исходников · динамика: scdet рендера v2 ·
Ревью v2 по видео и Montage_Plan_v2 — соседние доки в Drive-папке проекта</footer>
</div></body></html>'''

open(OUT, 'w').write(doc)
n_marks = doc.count('<mark>')
n_spk = doc.count('class="spk')
print('→', OUT, f'({os.path.getsize(OUT) // 1024} KB)')
print(f'подсвечено фраз: {n_marks} | подписей спикеров: {n_spk}')
