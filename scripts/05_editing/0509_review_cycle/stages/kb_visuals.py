#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb_visuals — визуал на места ката, где его не хватает: картинки базы знаний канала (YTUVI-Digital_Originals/_KB)
и свои съёмочные клипы (каталог FOOTAGE_ROUTING.md + папки макро-каталога по камням).

Шаги (каждый возобновляемый, всё локально, 0 токенов):
  needs   транскрипт ката → «биты» 8–18 с → ПРЕДМЕТЫ по словарю терминов канала (terms + places + VIS_EXTRA,
          регэкспы) → запросы EN. Модель не решает «что показать»: Qwen3-8B на YTUVI02 в 63 из 97 битов
          выдумал «включения под микроскопом» — словарь честнее. Биты под графикой ката и card.disabled_ranges — пропуск.
  pick    FTS5 _KB/index.sqlite по запросам предметов → фильтр профиля kb (exclude_sources: у YTUVI 01_SSEF вкл.
          01_Book — плохие сканы; min_side) → зрелищность fig_scores, дедуп phash; + свои клипы: описание/цитата
          FOOTAGE_ROUTING.md совпала с регэкспом предмета, или папка камня (…_Spinel/…) для камней.
  verify  Qwen2.5-VL-7B (.venv_vlm) по картинкам базы: совпадение с темой, фото/страница, качество 1–5, подпись RU.
  sheets  контактные листы по главам → work/{cut}/kb_visuals/sheet_chNN_pP.jpg (отбор делает сессия глазами).

Выход: work/{cut}/kb_visuals/{needs.json, candidates.json, verify.jsonl, sheet_*.jpg, cache/}.
Настройки: профиль `kb` {root, exclude_sources, min_side, per_beat, footage_root}; карточка `disabled_ranges`,
`footage_routing` (путь к FOOTAGE_ROUTING.md, по умолчанию {project}/00_Setup/FOOTAGE_ROUTING.md).

usage:  python3 stages/kb_visuals.py needs | pick | sheets
        ~/YTAI/environment/.venv_vlm/bin/python stages/kb_visuals.py verify
"""
import json, os, re, sqlite3, subprocess, sys
from pathlib import Path

os.environ.setdefault('HF_HOME', str(Path.home() / 'YTAI/models/huggingface'))
from _bootstrap import P, W6  # noqa: E402

OUT = W6 / 'kb_visuals'
OUT.mkdir(parents=True, exist_ok=True)
KB_CFG = P.profile('kb') or {}
KB_ROOT = Path(KB_CFG.get('root') or '/nonexistent')
KB = KB_ROOT / '_KB'
EXCLUDE = tuple(KB_CFG.get('exclude_sources') or ())
MIN_SIDE = int(KB_CFG.get('min_side') or 1000)
PER_BEAT = int(KB_CFG.get('per_beat') or 6)
FOOT_ROOT = Path(KB_CFG.get('footage_root') or '/nonexistent')
VLM = 'mlx-community/Qwen2.5-VL-7B-Instruct-4bit'
TERMS_BASE = Path(P.ROOT_YTAI if hasattr(P, 'ROOT_YTAI') else Path.home() / 'YTAI') / 'YTs' / P.get('channel', '') / 'review_terms_base.json'

# Предметы, которые зритель должен УВИДЕТЬ: заголовок термина/места → запросы в подписи журналов (EN).
# Термины без визуала (формулы, «бренд», поинт) сюда не входят — для них визуал базы не ищется.
VIS_QUERIES = {
    'КОРУНД': ['corundum crystal', 'ruby rough'], 'САПФИР': ['blue sapphire', 'sapphire faceted'],
    'ШПИНЕЛЬ': ['red spinel', 'spinel faceted'], 'РУБЕЛЛИТ': ['rubellite tourmaline', 'rubellite'],
    'ВКЛЮЧЕНИЯ': ['ruby inclusions', 'inclusions corundum'], '«ШЁЛК»': ['rutile silk ruby', 'silk inclusions'],
    'АСТЕРИЗМ': ['star ruby', 'asterism corundum'], 'КАБОШОН': ['cabochon ruby'],
    'ОГРАНКА': ['faceted ruby', 'gem cutting'], 'ГОЛУБИНАЯ КРОВЬ': ['pigeon blood ruby'],
    'ФЛУОРЕСЦЕНЦИЯ': ['ruby fluorescence ultraviolet', 'fluorescence ruby'],
    'ГЕММОЛОГИЧЕСКАЯ ЛАБОРАТОРИЯ': ['gemmological report', 'laboratory report ruby'],
    'СОТБИС': ['auction ruby necklace'], 'КРИСТИС': ['auction ruby necklace'],
    'ВЫСОКОЕ ЮВЕЛИРНОЕ ИСКУССТВО': ['ruby necklace', 'high jewellery ruby'], 'ГАРРИ УИНСТОН': ['Harry Winston ruby'],
    'КАРТЬЕ': ['Cartier ruby'], 'ОГЮСТ ВЕРНЕЙЛЬ': ['Verneuil synthetic ruby', 'Verneuil boule'],
    '«БУЛЯ»': ['synthetic ruby boule'], 'ФЛЮС': ['flux grown synthetic ruby'],
    'ГИДРОТЕРМАЛЬНЫЙ СИНТЕЗ': ['hydrothermal synthetic ruby'], 'СИНТЕТИЧЕСКИЙ РУБИН': ['synthetic ruby', 'synthetic ruby crystal'],
    'НАГРЕВ': ['heated ruby', 'heat treatment corundum'], 'ДИФФУЗИЯ': ['diffusion treated sapphire'],
    'БЕРИЛЛИЙ (Be)': ['beryllium diffusion corundum'], 'СВИНЦОВОЕ СТЕКЛО': ['lead glass filled ruby', 'glass filled ruby'],
    'ДУБЛЕТ': ['doublet', 'garnet glass doublet'], 'СИАМСКИЕ РУБИНЫ': ['Thai ruby'],
    '«17 КАМНЕЙ» В ЧАСАХ': ['watch jewel bearing'], 'ЛАЗЕР НА РУБИНЕ': ['ruby laser'], 'ШКАЛА МООСА': ['Mohs hardness'],
    'МРАМОРНЫЕ И БАЗАЛЬТОВЫЕ': ['marble hosted ruby', 'basalt ruby'], 'ПАДПАРАДЖА': ['padparadscha sapphire'],
    'ГЕММОЛОГ': ['gemmologist microscope'], 'ДВОЙНОЕ ЛУЧЕПРЕЛОМЛЕНИЕ': ['refractometer', 'doubling facets'],
    'ПОЛЯРИСКОП': ['polariscope'], 'БЛЕСК': ['lustre gemstone'],
}
# Камни и предметы вне словаря терминов (он делался под экранные плашки)
VIS_EXTRA = [
    {'title': 'АЛМАЗ', 'rx': r'\bалмаз|бриллиант', 'queries': ['diamond faceted']},
    {'title': 'ИЗУМРУД', 'rx': r'изумруд', 'queries': ['emerald faceted', 'emerald']},
    {'title': 'ГРАНАТ', 'rx': r'\bгранат', 'queries': ['red garnet', 'garnet faceted']},
    {'title': 'АЛЕКСАНДРИТ', 'rx': r'александрит', 'queries': ['alexandrite']},
    {'title': 'СТЕКЛЯННАЯ ИМИТАЦИЯ', 'rx': r'имитаци|стекляшк|крашен\w* стекл|страз', 'queries': ['glass imitation ruby', 'red glass imitation']},
    {'title': 'РУБИН', 'rx': r'\bрубин', 'queries': ['fine ruby', 'ruby faceted'], 'weak': True},
]
STONE_FOLDERS = {'РУБИН': 'Ruby', 'ШПИНЕЛЬ': 'Spinel', 'РУБЕЛЛИТ': 'Tourmaline', 'САПФИР': 'Sapphire', 'ИЗУМРУД': 'Emerald'}


def jl(p):
    return [json.loads(x) for x in open(p, encoding='utf-8') if x.strip()] if Path(p).exists() else []


def mmss(t):
    return f'{int(t // 60)}:{int(t % 60):02d}'


def chapter_at(t):
    cur = '01'
    for t0, ch in P.get('chapters', []):
        if t >= float(t0):
            cur = ch
    return cur


def disabled(t0, t1):
    return any(min(t1, float(r['t1'])) - max(t0, float(r['t0'])) > 0.5 * (t1 - t0) for r in P.get('disabled_ranges', []))


def vocab():
    base = json.load(open(TERMS_BASE, encoding='utf-8')) if TERMS_BASE.exists() else {}
    out = []
    for t in base.get('terms', []):
        if t['title'] in VIS_QUERIES:
            out.append({'title': t['title'], 'rx': t['rx'], 'queries': VIS_QUERIES[t['title']], 'def': t.get('def', ''), 'kind': 'term'})
    for p in base.get('places', []):
        en = (p.get('en') or [])[:1]
        out.append({'title': p['ru'], 'rx': p['rx'], 'queries': [f'{en[0]} ruby', f'{en[0]} mine'] if en else [],
                    'def': p.get('sub', ''), 'kind': 'place'})
    for e in VIS_EXTRA:
        out.append({'def': '', 'kind': 'gem', **e})
    return out


# ── needs ────────────────────────────────────────────────────────────────────────────────────
def beats():
    words = [(w['w'], float(w['s']), float(w['e'])) for sg in json.load(open(P.WORDS, encoding='utf-8'))['segments']
             for w in sg.get('words') or []]
    sents, cur = [], []
    for w in words:
        cur.append(w)
        if re.search(r'[.?!…]["»)]?$', w[0]):
            sents.append(cur)
            cur = []
    if cur:
        sents.append(cur)
    out, acc = [], []
    for s in sents:
        if acc and (s[-1][2] - acc[0][1] > 18):
            out.append(acc)
            acc = []
        acc = acc + s
        if acc[-1][2] - acc[0][1] >= 8:
            out.append(acc)
            acc = []
    if acc:
        out.append(acc)
    screens = json.load(open(W6 / 'screens_v6.json', encoding='utf-8')) if (W6 / 'screens_v6.json').exists() else []
    res = []
    for i, b in enumerate(out):
        t0, t1 = b[0][1], b[-1][2]
        cov = sum(max(0, min(t1, e['t1'] + 1) - max(t0, e['t0'])) for e in screens
                  if e.get('faces_avg', 1) < 0.5 and len(re.sub(r'\W', '', e.get('text_best', ''))) >= 3)
        res.append({'id': f'b{i + 1:03d}', 't0': round(t0, 2), 't1': round(t1, 2), 'tc': mmss(t0), 'chapter': chapter_at(t0),
                    'text': ' '.join(x[0] for x in b), 'graphic_cover': round(min(1.0, cov / max(0.1, t1 - t0)), 2),
                    'disabled': disabled(t0, t1)})
    return res


def cmd_needs():
    voc = vocab()
    res = []
    for b in beats():
        low = b['text'].lower().replace('ё', 'е')
        ents = []
        for v in voc:
            m = re.search(v['rx'].replace('ё', 'е'), low)
            if m:
                ents.append({'title': v['title'], 'kind': v['kind'], 'queries': v['queries'], 'def': v['def'],
                             'weak': bool(v.get('weak')), 'at': m.start()})
        ents.sort(key=lambda e: (e['weak'], e['at']))
        strong = [e for e in ents if not e['weak']]
        need = 0 if b['disabled'] else (3 if strong else (1 if ents else 0))
        res.append({**b, 'entities': ents, 'need': need})
    P.write_json_atomic(OUT / 'needs.json', res)
    import collections
    c = collections.Counter(e['title'] for r in res for e in r['entities'] if not e['weak'])
    print(f'needs: {len(res)} beats · need=3 {sum(1 for r in res if r["need"] == 3)} · предметы: {dict(c.most_common(20))}', flush=True)


# ── pick ─────────────────────────────────────────────────────────────────────────────────────
def footage_catalog():
    path = Path(P.resolve(P.get('footage_routing'))) if P.get('footage_routing') else Path(P.PROJECT_DIR) / '00_Setup/FOOTAGE_ROUTING.md'
    clips = {}
    if path.exists():
        cur = None
        for ln in open(path, encoding='utf-8'):
            m = re.match(r'- \*\*(RYA-[A-Z0-9]+-\d{4})\*\* `([^`]+)` \((\w+)\)( ⭐)? — (.+)', ln)
            if m:
                cur = clips.setdefault(m.group(1), {'clip': m.group(1), 'scene': m.group(2), 'type': m.group(3),
                                                    'gold': bool(m.group(4)), 'desc': m.group(5).strip(), 'quotes': []})
                continue
            q = re.match(r'\s+- `([^`]+)` «(.+)»', ln)
            if q and cur:
                cur['quotes'].append({'tc': q.group(1), 'q': q.group(2)})
    files = {}
    if FOOT_ROOT.exists():
        for f in FOOT_ROOT.rglob('*'):
            if f.suffix.upper() in ('.MP4', '.MOV') and '_Light' not in f.parts and '_pipeline' not in f.parts:
                files.setdefault(f.stem, f)
    return clips, files


def fts(con, q):
    toks = [t for t in re.findall(r'[A-Za-z0-9]+', q) if len(t) > 1]
    if not toks:
        return []
    for mode in (' '.join(toks), ' OR '.join(toks)):
        rows = con.execute('SELECT id, kind, source, path, locator, gems, text FROM records WHERE records MATCH ? '
                           "AND kind IN ('figure','image','video-scene') ORDER BY rank LIMIT 60", [mode]).fetchall()
        if rows:
            return rows
    return []


def cmd_pick():
    needs = json.load(open(OUT / 'needs.json', encoding='utf-8'))
    con = sqlite3.connect(KB / 'index.sqlite')
    scores = {r['path']: r for r in jl(KB / 'fig_scores.jsonl')}
    vlm = {r['path']: r.get('desc', '') for r in jl(KB / 'vlm_captions.jsonl')}
    phash = {r['p']: r['h'] for r in jl(KB / 'fig_phash.jsonl')}
    clips, files = footage_catalog()
    voc = {v['title']: v for v in vocab()}
    out, cache_q = [], {}
    for b in needs:
        if b['need'] < 3 or b.get('graphic_cover', 0) >= 0.6 or b.get('disabled'):
            continue
        cands, seen = [], set()
        for ei, e in enumerate([x for x in b['entities'] if not x['weak']][:3]):
            for qi, q in enumerate(e['queries'][:2]):
                rows = cache_q.setdefault(q, fts(con, q))
                for rank, (rid, kind, source, path, loc, gems, text) in enumerate(rows):
                    if path in seen or str(source).startswith(EXCLUDE or ('\0',)) or str(path).startswith(EXCLUDE or ('\0',)):
                        continue
                    seen.add(path)
                    sc = scores.get(path) or {}
                    wh = sc.get('wh') or [0, 0]
                    if max(wh or [0]) < MIN_SIDE:
                        continue
                    desc = vlm.get(path, '')
                    if re.search(r'Type:\s*(map|chart|document)', desc or '', re.I) or re.search(r'\b(page|table|graph|spectr|diagram)', (desc or '').lower()):
                        continue
                    score = float(sc.get('score') or 0) + 3.0 / (1 + rank) + min(max(wh) / 1500, 1.5) - ei * 1.5 - qi * 0.5
                    cands.append({'src': 'kb', 'entity': e['title'], 'path': path, 'kind': kind, 'source': source, 'locator': loc,
                                  'wh': wh, 'fts': (text or '')[:240], 'vlm_desc': (desc or '')[:240], 'score': round(score, 3), 'query': q})
        cands.sort(key=lambda c: -c['score'])
        picked = []
        for c in cands:
            h = phash.get(c['path'].replace('_KB/figures/', ''))
            if h and any(sum(x != y for x, y in zip(h, u)) <= 12 for u in
                         [phash.get(p['path'].replace('_KB/figures/', ''), '') for p in picked] if u):
                continue
            picked.append(c)
            if len(picked) >= PER_BEAT:
                break
        own = []
        for ei, e in enumerate([x for x in b['entities'] if not x['weak']][:3]):
            rx = voc[e['title']]['rx'].replace('ё', 'е')
            stone = STONE_FOLDERS.get(e['title'])
            for cl in clips.values():
                desc = cl['desc'].lower().replace('ё', 'е')
                blob = (desc + ' ' + ' '.join(q['q'] for q in cl['quotes'])).lower().replace('ё', 'е')
                m = re.search(rx, blob)
                if cl['type'] != 'working' and m and cl['clip'] in files:
                    # слово в начале описания = клип ПРО это; глобус/разговор, где камень упомянут вскользь, — ниже
                    rank = ei * 10 + (0 if m.start() < 80 else 4) + (0 if cl['gold'] else 2) + (3 if stone and 'Globe' in cl['scene'] else 0)
                    own.append({'src': 'own', 'entity': e['title'], 'clip': cl['clip'], 'path': str(files[cl['clip']]), 'scene': cl['scene'],
                                'gold': cl['gold'], 'desc': cl['desc'][:200], 'quotes': cl['quotes'][:2], 'rank': rank})
            if stone:
                for stem, f in files.items():
                    if f.parent.name.endswith('_' + stone) or f.parent.name == stone:
                        own.append({'src': 'own', 'entity': e['title'], 'clip': stem, 'path': str(f), 'scene': f.parent.name,
                                    'gold': False, 'desc': f'макро: папка {f.parent.name}', 'quotes': [], 'rank': ei * 10 + 1})
        dedup, seen_c = [], set()
        for o in sorted(own, key=lambda o: o['rank']):
            if o['clip'] not in seen_c:
                seen_c.add(o['clip'])
                dedup.append(o)
        out.append({**{k: b[k] for k in ('id', 't0', 't1', 'tc', 'chapter', 'text')},
                    'entities': [e['title'] for e in b['entities'] if not e['weak']], 'cands': picked, 'own': dedup[:4]})
    P.write_json_atomic(OUT / 'candidates.json', out)
    print(f'pick: {len(out)} beats · kb {sum(len(b["cands"]) for b in out)} · own {sum(len(b["own"]) for b in out)} · '
          f'пустых {sum(1 for b in out if not b["cands"] and not b["own"])}', flush=True)


# ── verify ───────────────────────────────────────────────────────────────────────────────────
VERIFY_PROMPT = """Topic needed on screen: {subject}.
Answer in exactly four lines:
MATCH: yes | partly | no   (does the image clearly show the topic?)
FORM: photo | micro-photo | page-with-text | diagram | collage
QUALITY: 1-5   (sharpness and beauty as a full-screen 4K video cutaway)
RU: <short Russian caption for viewers, up to 10 words>"""


def cmd_verify():
    from PIL import Image
    from mlx_vlm import load, generate
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.utils import load_config
    cands = json.load(open(OUT / 'candidates.json', encoding='utf-8'))
    path = OUT / 'verify.jsonl'
    done = {(r['beat'], r['path']) for r in jl(path)}
    cache = OUT / 'cache'
    cache.mkdir(exist_ok=True)
    model, processor = load(VLM)
    config = load_config(VLM)
    total = sum(len(b['cands']) for b in cands)
    n = 0
    with open(path, 'a', encoding='utf-8') as fh:
        for b in cands:
            for c in b['cands']:
                n += 1
                if (b['id'], c['path']) in done:
                    continue
                P.pause_gate('kb_visuals')
                small = cache / (re.sub(r'[^A-Za-z0-9_.-]', '_', c['path'])[-120:] + '.jpg')
                try:
                    if not small.exists():
                        im = Image.open(KB_ROOT / c['path']).convert('RGB')
                        im.thumbnail((1024, 1024))
                        im.save(small, quality=88)
                    f = apply_chat_template(processor, config, VERIFY_PROMPT.format(subject=f"{c['query']} ({c['entity']})"), num_images=1)
                    r = generate(model, processor, f, [str(small)], max_tokens=80, temperature=0.0, verbose=False)
                    r = getattr(r, 'text', r)
                except Exception as e:
                    r = f'ERROR {e}'
                g = lambda k: (re.search(rf'{k}:\s*(.+)', r) or [None, ''])[1].strip()
                qd = re.search(r'\d', g('QUALITY'))
                rec = {'beat': b['id'], 'path': c['path'], 'match': (g('MATCH').split() or [''])[0].lower(),
                       'form': g('FORM'), 'quality': int(qd.group(0)) if qd else 0, 'ru': g('RU'), 'raw': r[:300]}
                fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
                fh.flush()
                if n % 10 == 0:
                    print(f'  verify {n}/{total} {b["tc"]} {rec["match"]} q{rec["quality"]} {rec["ru"][:40]}', flush=True)
    print('verify done', flush=True)


# ── sheets ───────────────────────────────────────────────────────────────────────────────────
def frame_of(video, cache):
    out = cache / (Path(video).stem + '_mid.jpg')
    if not out.exists():
        try:
            dur = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', video],
                                       capture_output=True, text=True, timeout=30).stdout.strip() or 0)
            subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{dur * 0.4:.2f}', '-i', video, '-frames:v', '1', '-vf', 'scale=480:-2',
                            '-y', str(out)], capture_output=True, timeout=60)
        except Exception:
            pass
    return out


def cmd_sheets():
    from PIL import Image, ImageDraw, ImageFont
    cands = json.load(open(OUT / 'candidates.json', encoding='utf-8'))
    ver = {(r['beat'], r['path']): r for r in jl(OUT / 'verify.jsonl')}
    cache = OUT / 'cache'
    cache.mkdir(exist_ok=True)
    font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Unicode.ttf', 18)
    big = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Unicode.ttf', 22)
    TH, KBN, OWNN, ROWS = 230, PER_BEAT, 3, 6
    W = 330 + (KBN + OWNN) * (TH + 8) + 20
    rank = lambda b, c: (-(ver.get((b['id'], c['path'])) or {}).get('quality', 0) *
                         {'yes': 2, 'partly': 1}.get((ver.get((b['id'], c['path'])) or {}).get('match'), 0), -c['score'])
    by_ch = {}
    for b in cands:
        b['cands'] = sorted(b['cands'], key=lambda c: rank(b, c))
        by_ch.setdefault(b['chapter'], []).append(b)
    files = []
    for ch, bs in sorted(by_ch.items()):
        for pg in range(0, len(bs), ROWS):
            chunk = bs[pg:pg + ROWS]
            img = Image.new('RGB', (W, len(chunk) * (TH + 56) + 10), (24, 24, 28))
            d = ImageDraw.Draw(img)
            for ri, b in enumerate(chunk):
                y = 10 + ri * (TH + 56)
                d.text((10, y), f"{b['id']} {b['tc']}", fill=(242, 234, 216), font=big)
                d.multiline_text((10, y + 32), '\n'.join(re.findall('.{1,26}', ' · '.join(b['entities'])))[:150], fill=(205, 198, 184), font=font)
                tiles = [('K', ci + 1, c) for ci, c in enumerate(b['cands'][:KBN])] + [('O', oi + 1, o) for oi, o in enumerate(b['own'][:OWNN])]
                for ti, (tag, num, c) in enumerate(tiles):
                    x = 330 + ti * (TH + 8) + (20 if tag == 'O' else 0)
                    try:
                        src = (KB_ROOT / c['path']) if tag == 'K' else frame_of(c['path'], cache)
                        im = Image.open(src).convert('RGB')
                        im.thumbnail((TH, TH))
                        img.paste(im, (x, y))
                    except Exception:
                        pass
                    if tag == 'K':
                        v = ver.get((b['id'], c['path'])) or {}
                        lab1 = f"K{num} {v.get('match', '?')} q{v.get('quality', '?')} {max(c['wh'])}px"
                        lab2 = str(c['source'])[:24]
                    else:
                        lab1 = f"O{num} {'⭐' if c['gold'] else ''}{c['clip'][-9:]}"
                        lab2 = c['scene'][:24]
                    d.rectangle([x, y + TH, x + TH, y + TH + 42], fill=(10, 10, 12) if tag == 'K' else (40, 10, 14))
                    d.text((x + 4, y + TH + 1), lab1, fill=(228, 255, 110) if tag == 'K' else (255, 170, 170), font=font)
                    d.text((x + 4, y + TH + 21), lab2, fill=(160, 160, 170), font=font)
            f = OUT / f'sheet_ch{ch}_p{pg // ROWS + 1}.jpg'
            img.save(f, quality=85)
            files.append(str(f))
    P.write_json_atomic(OUT / 'candidates_ranked.json', cands)
    print('sheets:', len(files), *files, sep='\n  ')


# ── cards / apply: отбор сессии (picks.json) → карточки 4K, V2 карточки фильма, ТЗ «вставка», кадры для дока ──────
# picks.json: {"inserts": [{id, group, t, dur, src: kb|own, path, in?, out?, title, desc, credit?}],
#              "groups": [{group, title, tc_range, v1_tc, now, do: [..], notes: [..]}],
#              "tz": [готовые записи pravki (source notes/timeline) — заметки Романа, вырезки]}
CREDIT = [('02_GemA/02_GaJ', 'Gems & Jewellery (Gem-A)'), ('02_GemA', 'The Journal of Gemmology (Gem-A)'),
          ('17_ICA', 'InColor (ICA)'), ('16_WGF', 'Gemmology Today'), ('18_GAHK', 'GAHK Journal'), ('04_GRS', 'GRS'),
          ('06_GGTL', 'GGTL Laboratories'), ('05_AGL', 'AGL'), ('15_Lotus', 'Lotus Gemology'), ('03_Gubelin', 'Gübelin'),
          ('19_IGC', 'IGC'), ('08_GAA', 'GAA'), ('12_SJH', 'SJH'), ('20_LMHC', 'LMHC'), ('09_Rivista', 'Rivista Italiana di Gemmologia'),
          ('10_PalaGems', 'Pala International'), ('11_Scottish', 'Scottish Gemmological Association'), ('07_DGemG', 'DGemG')]


def credit_of(c):
    src = str(c.get('source') or c.get('path') or '')
    name = next((n for k, n in CREDIT if src.startswith(k)), src.split('/')[0])
    year = re.search(r'(19|20)\d{2}', src)
    return f"{name}{', ' + year.group(0) if year else ''}{', ' + c['locator'] if c.get('locator') else ''}"


# Ссылка на само издание (Роман 16.09.2026: «показывай и добавляй ссылки на страницу и на журналы сами»).
# Ключ — префикс пути источника; в `_KB/figures/...` слэши заменены подчёркиваниями, поэтому сверяем обе формы.
JOURNAL_URL = [('02_GemA/02_GaJ', 'https://gem-a.com/publications/gaj-archive/'),
               ('02_GemA/01_JoG', 'https://gem-a.com/publications/jog-archive/'),
               ('02_GemA', 'https://gem-a.com/publications/'),
               ('03_Gubelin', 'https://gubelingemlab.com/gemstone-profile/'),
               ('06_GGTL', 'https://ggtl-lab.org/en/other-publications'),
               ('16_WGF', 'https://worldgemfoundation.com'),
               ('15_Lotus', 'https://lotusgemology.com/index.php/library'),
               ('04_GRS', 'https://www.gemresearch.ch/research/contributions-to-gemology'),
               ('20_LMHC', 'https://lmhc-gemmology.org/information-sheets/'),
               ('19_IGC', 'https://www.igc-gemmology.org/'),
               ('01_SSEF', 'https://www.ssef.ch/publications/')]


def journal_url(c):
    """ссылка на издание по источнику картинки; нет в карте — пусто (ссылку не выдумываем)"""
    src = str(c.get('source') or c.get('path') or '').replace('_KB/figures/', '')
    flat = src.replace('/', '_')
    return next((u for k, u in JOURNAL_URL if src.startswith(k) or flat.startswith(k.replace('/', '_'))), '')


CARD_CSS = """html,body{margin:0;width:3840px;height:2160px;overflow:hidden;background:#101014}
.bg{position:absolute;inset:-80px;background-size:cover;background-position:center;filter:blur(70px) brightness(.32) saturate(1.2)}
.shade{position:absolute;inset:0;background:linear-gradient(180deg,rgba(8,8,12,.15) 0%,rgba(8,8,12,.55) 70%,rgba(8,8,12,.85) 100%)}
.img{position:absolute;left:50%;top:150px;transform:translateX(-50%);height:1420px;width:auto;max-width:2800px;object-fit:contain;
     border-radius:14px;box-shadow:0 40px 120px rgba(0,0,0,.7)}
.plate{position:absolute;left:260px;right:260px;bottom:150px}
.t{font:150px/1.02 Georgia,'Times New Roman',serif;color:#F2EAD8;text-transform:uppercase;letter-spacing:.03em}
.d{font:62px/1.25 'Helvetica Neue',Helvetica,Arial,sans-serif;color:#CDC6B8;margin-top:26px;max-width:2900px}
.c{font:38px 'Helvetica Neue',Helvetica,Arial,sans-serif;color:rgba(242,234,216,.55);margin-top:26px}
.bar{width:220px;height:10px;background:#C1272D;margin-bottom:40px}
.badge{position:absolute;top:50px;right:60px;font:30px 'Helvetica Neue',Arial;color:rgba(255,255,255,.5)}"""


def cmd_cards():
    from PIL import Image
    picks = json.load(open(OUT / 'picks.json', encoding='utf-8'))
    src_dir, doc = P.MOCK / 'src', OUT / 'doc'
    src_dir.mkdir(parents=True, exist_ok=True)
    doc.mkdir(exist_ok=True)
    render = Path.home() / 'YTAI/scripts/999_extra/infographic/render.py'
    import html as _h
    for ins in picks['inserts']:
        if ins['src'] == 'kb':
            img = KB_ROOT / ins['path']
            url = ins.get('url') or journal_url(ins)
            body = (f"<style>{CARD_CSS}</style><div class='bg' style=\"background-image:url('file://{img}')\"></div><div class='shade'></div>"
                    f"<img class='img' src='file://{img}'><div class='plate'><div class='bar'></div><div class='t'>{_h.escape(ins['title'])}</div>"
                    f"<div class='d'>{_h.escape(ins['desc'])}</div>"
                    f"<div class='c'>Фото: {_h.escape(ins.get('credit') or '')}{' · ' + _h.escape(url) if url else ''}</div></div>"
                    f"<div class='badge'>DRAFT · макет монтажёру</div>")
            # сама страница-источник отдельным файлом — её вставляет в док s-материал (Роман 16.09: «сами картинки вставляй в документ»)
            try:
                s = Image.open(img).convert('RGB')
                s.thumbnail((1600, 1600))
                s.save(doc / f"kbvsrc_{ins['id']}.jpg", quality=86)
            except Exception as e:                                    # noqa: BLE001 — картинка базы битая: карточка всё равно нужна
                print('src-jpg FAIL', ins['id'], e)
            html = src_dir / f"kbv_{ins['id']}.html"
            html.write_text(body, encoding='utf-8')
            png = P.MOCK / f"kbv_{ins['id']}.png"
            r = subprocess.run(['python3', str(render), str(html), str(png)], capture_output=True, text=True)
            if r.returncode or not png.exists():
                print('render FAIL', ins['id'], r.stderr[-200:])
                continue
            im = Image.open(png).convert('RGB')
        elif ins['src'] == 'mock':
            im = Image.open(P.MOCK / ins['path']).convert('RGB')     # готовый макет сессии в mockups/
        else:
            out = cache_frame = OUT / 'cache' / f"own_{ins['id']}.jpg"
            (OUT / 'cache').mkdir(exist_ok=True)
            mid = float(ins.get('in', 0)) + float(ins.get('dur', 4)) / 2
            subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{mid:.2f}', '-i', str(Path(ins['path']).resolve()), '-frames:v', '1',
                            '-vf', 'scale=1920:-2', '-y', str(cache_frame)], capture_output=True, timeout=120)
            if not out.exists():
                print('frame FAIL', ins['id'])
                continue
            im = Image.open(out).convert('RGB')
        im.thumbnail((1600, 1600))
        im.save(doc / f"kbv_{ins['id']}.jpg", quality=86)
        print('card', ins['id'], ins['src'], ins['title'])


def cmd_apply():
    picks = json.load(open(OUT / 'picks.json', encoding='utf-8'))
    card_path = P.CARD_PATH
    card = json.load(open(card_path, encoding='utf-8'))
    foot = Path(P.PROJECT_DIR) / '01_Source'
    v2 = []
    for ins in picks['inserts']:
        if ins.get('doc_only'):          # макет только для дока (раскадровка, сравнение) — на таймлайн не ставим
            continue
        mk = {'name': ins['title'], 'comment': f"{ins['title']} — {ins['desc']}" + (f"\nФото: {ins['credit']}" if ins.get('credit') else '')}
        if ins['src'] in ('kb', 'mock'):
            png = f"MOCK/kbv_{ins['id']}.png" if ins['src'] == 'kb' else f"MOCK/{ins['path']}"
            v2.append({'kind': 'still', 'sid': f"v2_kbv_{ins['id']}", 'path': png, 't': float(ins['t']),
                       'opts': {'dur': float(ins.get('dur', 4.0)), 'item_marker': mk}})
        else:
            p = Path(ins['path'])
            rel = p.relative_to(foot) if str(p).startswith(str(foot)) else None
            v2.append({'kind': 'seg', 'sid': f"v2_own_{ins['id']}", 'path': f"FOOT/{rel}" if rel else str(p), 't': float(ins['t']),
                       'in': float(ins['in']), 'out': float(ins['in']) + float(ins.get('dur', 4.0)),
                       'opts': {'keep_audio': False, 'item_marker': mk}})
    card['v2'] = v2
    P.write_json_atomic(card_path, card)
    pr = json.load(open(P.MONT / 'pravki_v2.json', encoding='utf-8'))
    keep = [p for p in pr['all'] if p.get('source') not in ('kb_visuals', 'roman_notes_1509', 'roman_timeline_1509')]
    added = []
    by_group = {}
    for ins in picks['inserts']:
        by_group.setdefault(ins['group'], []).append(ins)
    for g in picks['groups']:
        mats, credits = [], []
        for i in by_group.get(g['group'], []):
            if i['src'] == 'kb':
                url = i.get('url') or journal_url(i)
                mats.append({'t': f"{i['title']} — {i['desc']}", 'img': f"kbv_{i['id']}.jpg", 'src': f"Фото: {i['credit']}"})
                # сама страница издания картинкой в доке + ссылка на журнал (Роман 16.09.2026: права на фото из журналов — можно)
                mats.append({'t': f"страница источника: {i['credit']}", 'img': f"kbvsrc_{i['id']}.jpg",
                             'src': (f"издание: {url}" if url else 'издание: см. базу знаний канала')})
                credits.append(f"{i['credit']}{' — ' + url if url else ''}")
            else:
                mats.append({'t': f"{i['title']} — {i['desc']}", 'img': f"kbv_{i['id']}.jpg",
                             'src': ('макет ревью (DRAFT)' if i['src'] == 'mock'
                                     else f"свой клип {Path(i['path']).stem} @ {mmss(float(i['in']))}")})
        added.append({'notes': g.get('notes', []) + ['kb_visuals_1509'], 'v1_tc': g['v1_tc'], 'tc_range': g['tc_range'],
                      'title': g['title'], 'category': g.get('category', 'insert'), 'source': g.get('source', 'kb_visuals'), 'est': g['now'],
                      'nado': '', 'material_rich': mats, 'typo': [], 'sheet_answer': '', 'decision': g.get('decision', ''),
                      'parts': {'now': [g['now']], 'do': [{'h': g.get('do_h', ''), 'items': g['do']}],
                                'src': ([f'📚 {c}' for c in credits] or g.get('src', [])),
                                'tl': ([f"слой V2 ревью-секвенции: {', '.join(i['title'] for i in by_group.get(g['group'], []) if not i.get('doc_only'))}"]
                                       if any(not i.get('doc_only') for i in by_group.get(g['group'], [])) else [])}})
    for t in picks.get('tz', []):
        added.append(t)
    pr['all'] = keep + added
    P.write_json_atomic(P.MONT / 'pravki_v2.json', pr)
    shots = P.MONT / 'shots_ids.json'
    doc = OUT / 'doc'
    remote = P.need('shots_remote')
    subprocess.run(['rclone', 'copy', str(doc), remote, '--include', 'kbv*.jpg', '--transfers', '4'], check=True)
    ls = subprocess.run(['rclone', 'lsjson', remote, '--files-only', '--include', 'kbv*.jpg'], capture_output=True, text=True, check=True)
    ids = {f['Name']: f['ID'] for f in json.loads(ls.stdout)}
    sh = json.load(open(shots, encoding='utf-8'))
    sh.update(ids)
    P.write_json_atomic(shots, sh)
    print(f'apply: card.v2 {len(v2)} · pravki +{len(added)} (всего {len(pr["all"])}) · shots +{len(ids)}')


if __name__ == '__main__':
    {'needs': cmd_needs, 'pick': cmd_pick, 'verify': cmd_verify, 'sheets': cmd_sheets, 'cards': cmd_cards,
     'apply': cmd_apply}[sys.argv[1]]()
