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
import collections, json, os, re, sqlite3, subprocess, sys
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


# ── книги (Роман 16.09.2026: «нужно больше такого из книг и из журналов») ────────────────────
# Книги в базе — сканы страниц, встроенных фигур в них нет (`gem_kb/pdf_figures.py` их пропускает),
# зато половины страниц уже нарезаны и размечены: книга, модуль, печатная страница, заголовок, краткое
# содержание, тип (photo_plate / content / table …). Ищем по этой разметке текстом — модель не нужна.
# Роман 16.09.2026: сканы вынесены из базы в 01_ScanBook-SSEF («качество плохое, старайся не использовать») —
# books_policy `fallback`: книга идёт в кандидаты бита, только если ни одна картинка базы не прошла verify.
BOOKS_MANIFEST = Path(KB_CFG['books_manifest']) if KB_CFG.get('books_manifest') else Path('/nonexistent')
BOOKS_POLICY = KB_CFG.get('books_policy') or 'always'
BOOK_NAME = {'SSEF_ACG': 'SSEF, курс Advanced Coloured Gemstones', 'SSEF': 'SSEF, курс гемологии',
             'GEMA_PH': 'Gem-A, Practical Handbook', 'GEMA_FW': 'Gem-A, Foundation Workbook'}
BOOK_URL = {'SSEF_ACG': 'https://www.ssef.ch/education/', 'SSEF': 'https://www.ssef.ch/education/',
            'GEMA_PH': 'https://gem-a.com/education/', 'GEMA_FW': 'https://gem-a.com/education/'}
BOOK_TYPES = {'photo_plate': 4.0, 'content': 1.0, 'summary': 0.5}       # нужны иллюстрации, не таблицы и не оглавления
# свой клип годится в перебивку, только если это съёмка предмета, а не говорящая голова
BROLL_SCENE = re.compile(r'(Macro|Broll|B_?roll|Closeup|Showcase|Try_?On|Globe|Catalog|Store)', re.I)
TALKING = re.compile(r'(CAM\d|интервью|монолог|комментар|консультант|говорит|рассказывает|Commentary|Consultant|Interview)', re.I)
PHOTO_WORDS = ('photo', 'photograph', 'image', 'microscop', 'inclusion', 'crystal', 'rough', 'cut stone',
               'specimen', 'ring', 'necklace', 'faceted', 'cabochon', 'plate', 'montage')


def book_pages():
    """половины страниц книг с разметкой → [{file, book, module, page, heading, summary, type, w, h}]"""
    if not BOOKS_MANIFEST.exists():
        return []
    root = BOOKS_MANIFEST.parent.parent                                 # …/01_Book/02_Pages/manifest → корень книги (file = «02_Pages/…»)
    out = []
    for p in json.load(open(BOOKS_MANIFEST, encoding='utf-8')).get('pages', []):
        if (p.get('content_type') or '') not in BOOK_TYPES or not p.get('file'):
            continue
        f = root / p['file'] if not str(p['file']).startswith('/') else Path(p['file'])
        if max(int(p.get('w') or 0), int(p.get('h') or 0)) < MIN_SIDE:
            continue
        out.append({'path': str(f.relative_to(KB_ROOT)) if str(f).startswith(str(KB_ROOT)) else str(f),
                    'book': p.get('book') or '', 'module': p.get('module') or '', 'page': p.get('printed_page_no'),
                    'heading': p.get('heading') or '', 'summary': p.get('summary') or '',
                    'type': p.get('content_type'), 'wh': [int(p.get('w') or 0), int(p.get('h') or 0)]})
    return out


def book_candidates(pages, entities, limit):
    """подбор страниц книги под предметы бита: слова запросов в заголовке/содержании + бонус фотоплате"""
    res = []
    for ei, e in enumerate(entities):
        toks = {t.lower() for q in e['queries'] for t in re.findall(r'[A-Za-z]{4,}', q)}
        if not toks:
            continue
        for pg in pages:
            blob = (pg['heading'] + ' ' + pg['summary']).lower()
            hits = sum(1 for t in toks if t in blob)
            if not hits:
                continue
            score = hits * 2.0 + BOOK_TYPES.get(pg['type'], 0) + sum(0.4 for w in PHOTO_WORDS if w in blob) - ei * 1.5
            name = BOOK_NAME.get(pg['book'], pg['book'] or 'книга')
            credit = f"{name}{', модуль ' + pg['module'].title() if pg['module'] else ''}" \
                     f"{', с. ' + str(pg['page']) if pg['page'] else ''}"
            res.append({'src': 'kb', 'from': 'book', 'entity': e['title'], 'path': pg['path'], 'kind': 'book-page',
                        'ptype': pg['type'],
                        'source': pg['path'], 'locator': f"с. {pg['page']}" if pg['page'] else '', 'wh': pg['wh'],
                        'fts': pg['summary'][:240], 'vlm_desc': '', 'credit': credit,
                        'url': BOOK_URL.get(pg['book'], ''), 'score': round(score, 3), 'query': pg['heading'][:60]})
    res.sort(key=lambda c: -c['score'])
    seen, top = set(), []
    for c in res:
        if c['path'] in seen:
            continue
        seen.add(c['path'])
        top.append(c)
        if len(top) >= limit:
            break
    return top


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


_WORDS = None


def all_words():
    global _WORDS
    if _WORDS is None:
        _WORDS = [(w['w'], float(w['s']), float(w['e'])) for sg in json.load(open(P.WORDS, encoding='utf-8'))['segments']
                  for w in sg.get('words') or []]
    return _WORDS


def word_time(t0, t1, rx):
    """время первого слова предмета в [t0, t1] (Роман 16.09.2026, ТЗ-65: вставка «слишком рано» — начало бита не
    годится, картинка встаёт на само слово); None — слово не нашлось (многословный регэксп, другая форма)"""
    if not rx:
        return None
    r = re.compile(rx.replace('ё', 'е'))
    for w, s, e in all_words():
        if t0 - 0.05 <= s <= t1 and r.search(w.lower().replace('ё', 'е')):
            return s
    return None


def tc_sec(s):
    m = re.match(r'\s*(\d+):(\d{2})(?:\.(\d+))?', str(s or ''))
    return int(m.group(1)) * 60 + int(m.group(2)) + (float('0.' + m.group(3)) if m.group(3) else 0) if m else None


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


def arg(name, default=None):
    """--name=value из командной строки"""
    return next((a.split('=', 1)[1] for a in sys.argv if a.startswith(f'--{name}=')), default)


class KbSearch:
    """FTS5 по подписям базы → фильтр профиля (exclude_sources, min_side; карты/таблицы/страницы — вон, если не просили
    схем) → зрелищность fig_scores + ранг FTS + размер → дедуп phash. Общий для pick (биты) и targets (свои запросы)."""

    def __init__(self):
        self.con = sqlite3.connect(KB / 'index.sqlite')
        self.scores = {r['path']: r for r in jl(KB / 'fig_scores.jsonl')}
        self.vlm = {r['path']: r.get('desc', '') for r in jl(KB / 'vlm_captions.jsonl')}
        self.phash = {r['p']: r['h'] for r in jl(KB / 'fig_phash.jsonl')}
        self.cache = {}

    def search(self, ents, limit, diagrams=False, skip=()):
        """ents: [(заголовок предмета, [запросы EN])] по убыванию важности"""
        cands, seen = [], set(skip)
        for ei, (title, queries) in enumerate(ents):
            for qi, q in enumerate(queries):
                rows = self.cache.setdefault(q, fts(self.con, q))
                for rank, (rid, kind, source, path, loc, gems, text) in enumerate(rows):
                    if path in seen or str(source).startswith(EXCLUDE or ('\0',)) or str(path).startswith(EXCLUDE or ('\0',)):
                        continue
                    seen.add(path)
                    sc = self.scores.get(path) or {}
                    wh = sc.get('wh') or [0, 0]
                    if max(wh or [0]) < MIN_SIDE:
                        continue
                    desc = self.vlm.get(path, '')
                    if not diagrams and (re.search(r'Type:\s*(map|chart|document)', desc or '', re.I)
                                         or re.search(r'\b(page|table|graph|spectr|diagram)', (desc or '').lower())):
                        continue
                    score = float(sc.get('score') or 0) + 3.0 / (1 + rank) + min(max(wh) / 1500, 1.5) - ei * 1.5 - qi * 0.5
                    cands.append({'src': 'kb', 'entity': title, 'path': path, 'kind': kind, 'source': source, 'locator': loc,
                                  'wh': wh, 'fts': (text or '')[:240], 'vlm_desc': (desc or '')[:240], 'score': round(score, 3),
                                  'query': q})
        cands.sort(key=lambda c: -c['score'])
        picked = []
        for c in cands:
            h = self.phash.get(c['path'].replace('_KB/figures/', ''))
            if h and any(sum(x != y for x, y in zip(h, u)) <= 12 for u in
                         [self.phash.get(p['path'].replace('_KB/figures/', ''), '') for p in picked] if u):
                continue
            picked.append(c)
            if len(picked) >= limit:
                break
        return picked


def want_books(pages, bid, picked, ver, min_q):
    """книги-сканы: при books_policy fallback — только когда картинки базы уже проверены и ни одна не годится"""
    if not pages:
        return False
    if BOOKS_POLICY != 'fallback':
        return True
    rec = [ver.get((bid, c['path'])) for c in picked]
    base_ok = any(r and r.get('match') == 'yes' and int(r.get('quality') or 0) >= min_q for r in rec)
    return (any(rec) and not base_ok) or (not picked and bool(ver))


def cmd_pick():
    needs = json.load(open(OUT / 'needs.json', encoding='utf-8'))
    S = KbSearch()
    clips, files = footage_catalog()
    voc = {v['title']: v for v in vocab()}
    out = []
    min_need = int(next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--min-need=')), 3))
    pages = book_pages() if '--no-books' not in sys.argv else []
    min_q = int(next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--min-q=')), 4))
    ver = {(r['beat'], r['path']): r for r in jl(OUT / 'verify.jsonl')}
    print(f'pick: порог need ≥ {min_need} · страниц книг в разметке: {len(pages)} · книги: {BOOKS_POLICY}', flush=True)
    for b in needs:
        if b['need'] < min_need or b.get('graphic_cover', 0) >= 0.6 or b.get('disabled'):
            continue
        picked = S.search([(e['title'], e['queries'][:2]) for e in [x for x in b['entities'] if not x['weak']][:3]], PER_BEAT)
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
        # у слабых битов (need 1) сильных предметов нет — для книг берём и слабые, иначе бит остался бы пустым
        ents = [x for x in b['entities'] if not x['weak']][:3] or b['entities'][:2]
        books = book_candidates(pages, ents, 4) if want_books(pages, b['id'], picked, ver, min_q) else []
        out.append({**{k: b[k] for k in ('id', 't0', 't1', 'tc', 'chapter', 'text')},
                    'entities': [e['title'] for e in b['entities'] if not e['weak']], 'cands': picked,
                    'own': dedup[:4], 'books': books})
    P.write_json_atomic(OUT / 'candidates.json', out)
    print(f'pick: {len(out)} beats · kb {sum(len(b["cands"]) for b in out)} · own {sum(len(b["own"]) for b in out)} · '
          f'книги {sum(len(b["books"]) for b in out)} · '
          f'пустых {sum(1 for b in out if not b["cands"] and not b["own"] and not b["books"])}', flush=True)


def cmd_targets():
    """Адресный поиск по СВОИМ запросам (заметки Романа, замена книжных сканов, «найди картинку, где синтетика видна»)
    → кандидаты в формате candidates.json, дальше те же verify / sheets.
    usage: kb_visuals.py targets --in=targets_<name>.json [--per=12] [--min-q=4]
    targets_<name>.json: [{id, t0, t1, chapter?, text, subject (EN, вопрос VLM), queries: [EN…], diagrams?: bool,
                          skip?: [path…]}] → candidates_<name>.json"""
    inp = OUT / arg('in')
    name = inp.stem.replace('targets_', '')
    per, min_q = int(arg('per', 12)), int(arg('min-q', 4))
    S = KbSearch()
    pages = book_pages() if '--no-books' not in sys.argv else []
    ver = {(r['beat'], r['path']): r for r in jl(OUT / 'verify.jsonl')}
    out = []
    for tg in json.load(open(inp, encoding='utf-8')):
        subj = tg.get('subject') or tg['id']
        picked = S.search([(subj, tg['queries'])], per, diagrams=bool(tg.get('diagrams')), skip=tg.get('skip') or ())
        ents = [{'title': subj, 'queries': tg['queries']}]
        books = book_candidates(pages, ents, 4) if want_books(pages, tg['id'], picked, ver, min_q) else []
        t0 = float(tg['t0'])
        out.append({'id': tg['id'], 't0': t0, 't1': float(tg.get('t1', t0 + 8)), 'tc': mmss(t0),
                    'chapter': tg.get('chapter') or chapter_at(t0), 'text': tg.get('text', ''), 'entities': [subj],
                    'cands': picked, 'own': [], 'books': books})
        print(f"  {tg['id']} {mmss(t0)} кандидатов {len(picked)}" + (f' · книги {len(books)}' if books else ''), flush=True)
    P.write_json_atomic(OUT / f'candidates_{name}.json', out)
    print(f'targets: {len(out)} → candidates_{name}.json', flush=True)


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
    cands = json.load(open(OUT / arg('in', 'candidates.json'), encoding='utf-8'))    # --in=candidates_<name>.json (targets)
    path = OUT / 'verify.jsonl'
    done = {(r['beat'], r['path']) for r in jl(path)}
    cache = OUT / 'cache'
    cache.mkdir(exist_ok=True)
    model, processor = load(VLM)
    config = load_config(VLM)
    total = sum(len(b['cands']) + len(b.get('books') or []) for b in cands)
    n = 0
    with open(path, 'a', encoding='utf-8') as fh:
        for b in cands:
            for c in b['cands'] + (b.get('books') or []):      # книги проверяем так же, как журналы
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
                rec = {'beat': b['id'], 'path': c['path'], 'from': c.get('from', 'journal'),
                       'credit': c.get('credit', ''), 'match': (g('MATCH').split() or [''])[0].lower(),
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
    src_name = arg('in', 'candidates.json')                   # --in=candidates_<name>.json → sheet_<name>_…
    tag_name = '' if src_name == 'candidates.json' else Path(src_name).stem.replace('candidates_', '') + '_'
    cands = json.load(open(OUT / src_name, encoding='utf-8'))
    ver = {(r['beat'], r['path']): r for r in jl(OUT / 'verify.jsonl')}
    cache = OUT / 'cache'
    cache.mkdir(exist_ok=True)
    font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Unicode.ttf', 18)
    big = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Unicode.ttf', 22)
    TH, KBN, OWNN, BOOKN, ROWS = 230, int(arg('per', PER_BEAT)), 3, 3, int(arg('rows', 6))
    W = 330 + (KBN + OWNN + BOOKN) * (TH + 8) + 40
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
                books = sorted(b.get('books') or [], key=lambda c: rank(b, c))
                tiles = ([('K', ci + 1, c) for ci, c in enumerate(b['cands'][:KBN])]
                         + [('B', bi + 1, c) for bi, c in enumerate(books[:BOOKN])]
                         + [('O', oi + 1, o) for oi, o in enumerate(b['own'][:OWNN])])
                for ti, (tag, num, c) in enumerate(tiles):
                    x = 330 + ti * (TH + 8) + (20 if tag == 'B' else 40 if tag == 'O' else 0)
                    try:
                        src = (KB_ROOT / c['path']) if tag in ('K', 'B') else frame_of(c['path'], cache)
                        im = Image.open(src).convert('RGB')
                        im.thumbnail((TH, TH))
                        img.paste(im, (x, y))
                    except Exception:
                        pass
                    if tag in ('K', 'B'):
                        v = ver.get((b['id'], c['path'])) or {}
                        lab1 = f"{tag}{num} {v.get('match', '?')} q{v.get('quality', '?')} {max(c['wh'])}px"
                        lab2 = (c.get('credit') or str(c['source']))[:24]
                    else:
                        lab1 = f"O{num} {'⭐' if c['gold'] else ''}{c['clip'][-9:]}"
                        lab2 = c['scene'][:24]
                    d.rectangle([x, y + TH, x + TH, y + TH + 42],
                                fill=(10, 10, 12) if tag == 'K' else (12, 22, 36) if tag == 'B' else (40, 10, 14))
                    d.text((x + 4, y + TH + 1), lab1,
                           fill=(228, 255, 110) if tag == 'K' else (150, 215, 255) if tag == 'B' else (255, 170, 170), font=font)
                    d.text((x + 4, y + TH + 21), lab2, fill=(160, 160, 170), font=font)
            f = OUT / f'sheet_{tag_name}ch{ch}_p{pg // ROWS + 1}.jpg'
            img.save(f, quality=85)
            files.append(str(f))
    if not tag_name:
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


def cmd_propose():
    """Черновик вставок на пустые биты: лучший проверенный кадр (журнал/книга) или свой клип.
    Выбирает КОД по оценке локальной VLM, а сессия смотрит один контактный лист и правит.
    usage: kb_visuals.py propose [--gap=12] [--min-q=4]"""
    gap = float(next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--gap=')), 12))
    min_q = int(next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--min-q=')), 4))
    cands = json.load(open(OUT / 'candidates.json', encoding='utf-8'))
    ver = {(r['beat'], r['path']): r for r in jl(OUT / 'verify.jsonl')}
    picks = json.load(open(OUT / 'picks.json', encoding='utf-8')) if (OUT / 'picks.json').exists() else {'inserts': [], 'groups': []}
    busy = sorted(float(i['t']) for i in picks['inserts'])                 # уже занятые места ката
    used = {i['path'] for i in picks['inserts']}
    inserts, groups, last = [], [], -99.0
    used_near = set()

    def near_key(c):
        """книга + соседняя страница = тот же разворот (…/acg03/s020_bottom.jpg → acg03/s020)"""
        m = re.search(r'/([^/]+)/s(\d+)', str(c.get('path') or ''))
        return f'{m.group(1)}/{int(m.group(2)) // 2}' if m else str(c.get('path'))

    voc = {v['title']: v for v in vocab()}
    for b in sorted(cands, key=lambda x: x['t0']):
        ent0 = (b['entities'] or [''])[0]
        ws = word_time(float(b['t0']), float(b['t1']), (voc.get(ent0) or {}).get('rx'))
        t = round(max(float(b['t0']), ws - 0.2), 2) if ws is not None else round(float(b['t0']) + 0.4, 2)
        if any(abs(t - u) < gap for u in busy) or t - last < gap:
            continue
        pool = []
        for c in b['cands'] + (b.get('books') or []):
            v = ver.get((b['id'], c['path'])) or {}
            if v.get('match') != 'yes' or int(v.get('quality') or 0) < min_q or c['path'] in used:
                continue
            ru = (v.get('ru') or '').strip()
            if not ru or not re.search(r'[А-Яа-я]', ru) or len(ru) < 8:      # модель иногда уходит в чужой язык
                continue
            form = (v.get('form') or '').lower()
            # VLM зовёт «полосой с текстом» почти всё (407 из 542 на YTUVI02), поэтому у книг верим своей
            # разметке: photo_plate — это разворот с фотографиями, его и берём.
            if not (form.startswith(('photo', 'micro', 'collage')) or c.get('ptype') == 'photo_plate'):
                continue
            pool.append((int(v['quality']) + (1 if form.startswith('photo') else 0), float(c.get('score') or 0), c, ru))
        pool.sort(key=lambda x: (-x[0], -x[1]))
        pool = [p for p in pool if near_key(p[2]) not in used_near]         # соседние страницы одной книги — это один и тот же разворот
        ent = (b['entities'] or ['ВСТАВКА'])[0]
        gid = f'gp{len(groups) + 1:02d}'
        iid = f'p_{b["id"]}'
        dur = round(min(4.0, max(2.5, float(b['t1']) - float(b['t0']) - 1.0)), 1)
        dur_txt = f'{dur:.0f}' if dur % 1 == 0 else f'{dur:.1f}'.replace('.', ',')     # «4 с» / «2,5 с», как в каноне ТЗ
        if pool:
            q, sc, c, ru = pool[0]
            inserts.append({'id': iid, 'group': gid, 't': t, 'dur': dur, 'src': 'kb', 'path': c['path'],
                            'title': ent, 'desc': ru, 'credit': c.get('credit') or credit_of(c),
                            'url': c.get('url') or journal_url(c), 'from': c.get('from', 'journal'), 'q': q})
            used_near.add(near_key(c))
        else:                                                              # картинки нет — ставим свою съёмку
            # только перебивочные сцены: интервью и монологи (CAM1/CAM2, комментарии, консультанты) — не вставка
            # и только там, где предмет реально снят: камень из макро-каталога или место на глобусе;
            # процессы («нагрев», «имитация») своим кадром не покажешь — будет вставка мимо смысла
            own = [o for o in (b.get('own') or [])
                   if o['path'] not in used and BROLL_SCENE.search(o.get('scene') or '')
                   and not TALKING.search((o.get('desc') or '') + ' ' + (o.get('scene') or ''))
                   and (o.get('entity') in STONE_FOLDERS or 'Globe' in (o.get('scene') or ''))]
            if not own:
                continue
            o = own[0]
            c, ru, q = o, f"{ent.lower()} — свой кадр", 0
            inserts.append({'id': iid, 'group': gid, 't': t, 'dur': dur, 'src': 'own', 'path': o['path'],
                            'in': 0.5, 'title': ent, 'desc': (o.get('desc') or '')[:120], 'from': 'own', 'q': 0})
        groups.append({'group': gid, 'source': 'kb_visuals', 'category': 'insert', 'notes': ['kb_visuals_1609'],
                       'v1_tc': mmss(t), 'tc_range': f"{mmss(b['t0'])}–{mmss(b['t1'])}",
                       'title': f'ВСТАВКА: {ent}', 'now': f"На {mmss(b['t0'])} про «{ent.lower()}» — в кадре этого нет.",
                       'do_h': f'Показать: {ru.rstrip(".")}',
                       'do': [f"{mmss(t)} ▸ {ru.rstrip('.')}, {dur_txt} с — карточка V2"]})
        used.add(c['path'])
        last = t
    P.write_json_atomic(OUT / 'proposals.json', {'inserts': inserts, 'groups': groups})
    # контактный лист предложений: сессия смотрит ОДИН файл вместо десятков картинок
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Unicode.ttf', 17)
    TH, COLS = 300, 4
    for pg in range(0, len(inserts), COLS * 4):
        chunk = inserts[pg:pg + COLS * 4]
        rows = (len(chunk) + COLS - 1) // COLS
        img = Image.new('RGB', (COLS * (TH + 10) + 10, rows * (TH + 64) + 10), (22, 22, 26))
        d = ImageDraw.Draw(img)
        for k, ins in enumerate(chunk):
            x, y = 10 + (k % COLS) * (TH + 10), 10 + (k // COLS) * (TH + 64)
            try:
                im = Image.open(KB_ROOT / ins['path']).convert('RGB')
                im.thumbnail((TH, TH))
                img.paste(im, (x, y))
            except Exception:                                  # noqa: BLE001 — битая картинка базы: плитка останется пустой
                pass
            d.text((x, y + TH + 2), f"{mmss(ins['t'])} {ins['from']} q{ins['q']} · {ins['title'][:20]}", fill=(228, 255, 110), font=font)
            d.text((x, y + TH + 22), ins['desc'][:40], fill=(226, 218, 200), font=font)
            d.text((x, y + TH + 42), (ins.get('credit') or '')[:44], fill=(150, 150, 160), font=font)
        f = OUT / f'sheet_proposals_p{pg // (COLS * 4) + 1}.jpg'
        img.save(f, quality=86)
        print('лист предложений:', f)
    if '--apply' in sys.argv:                                  # влить черновик в отбор сессии (с бэкапом picks.json)
        pf = OUT / 'picks.json'
        if pf.exists():
            (OUT / f'picks.before_propose.json').write_text(pf.read_text(encoding='utf-8'), encoding='utf-8')
        picks['inserts'] = picks['inserts'] + inserts
        picks['groups'] = picks['groups'] + groups
        P.write_json_atomic(pf, picks)
        print(f'picks.json: вставок {len(picks["inserts"])}, групп {len(picks["groups"])} (бэкап picks.before_propose.json)')
    by_src = collections.Counter(i['from'] for i in inserts)
    print(f'propose: вставок {len(inserts)} (журналы {by_src.get("journal", 0)} · книги {by_src.get("book", 0)}), '
          f'пауза ≥{gap:g} с, качество ≥{min_q} → proposals.json', flush=True)
    for i in inserts[:8]:
        print(f'  {mmss(i["t"])} {i["title"][:22]:24} q{i["q"]} {i["from"]:7} {i["desc"][:52]}')


def cmd_retime():
    """Переставить уже отобранные вставки на слово предмета (picks.json, с бэкапом).
    usage: kb_visuals.py retime --ids=p_b014[,…] [--word=синтет] [--pad=5]
    окно поиска = tc_range группы (+pad с справа); регэксп = --word или словарь по заголовку вставки"""
    ids = set(next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--ids=')), '').split(',')) - {''}
    word = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--word=')), '')
    pad = float(next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--pad=')), 5))
    pf = OUT / 'picks.json'
    picks = json.load(open(pf, encoding='utf-8'))
    voc = {v['title']: v for v in vocab()}
    groups = {g['group']: g for g in picks['groups']}
    changed = 0
    for ins in picks['inserts']:
        if ids and ins['id'] not in ids:
            continue
        g = groups.get(ins.get('group')) or {}
        rng = re.split(r'\s*[–-]\s*', g.get('tc_range') or '')
        t0 = tc_sec(rng[0]) if rng and rng[0] else float(ins['t']) - 3
        t1 = (tc_sec(rng[1]) if len(rng) > 1 else float(ins['t'])) + pad
        rx = word or (voc.get(ins.get('title')) or {}).get('rx')
        ws = word_time(t0 - 3, t1, rx)
        if ws is None:
            print(f"  {ins['id']}: слово «{rx}» в {mmss(t0)}–{mmss(t1)} не нашлось — оставляю {mmss(float(ins['t']))}")
            continue
        new_t = round(max(0.0, ws - 0.2), 2)
        old = mmss(float(ins['t']))
        ins['t'] = new_t
        if g:
            g['v1_tc'] = mmss(new_t)
            g['do'] = [re.sub(rf'^{re.escape(old)}\b', mmss(new_t), x) for x in g.get('do') or []]
        changed += 1
        print(f"  {ins['id']}: {old} → {mmss(new_t)} (слово в {ws:.2f} с)")
    if changed:
        (OUT / 'picks.before_retime.json').write_text(pf.read_text(encoding='utf-8'), encoding='utf-8')
        P.write_json_atomic(pf, picks)
    print(f'retime: переставлено {changed}')


def is_scan(path):
    """скан книги SSEF — запасной источник (Роман 16.09.2026: только если в Digital_Originals ничего не нашлось)"""
    return '01_ScanBook-SSEF' in str(path) or '/01_Book/' in str(path)


SCAN_MARK = '⚠️ скан книги — в базе не нашлось'


def source_name(s):
    """короткое имя исходника макета для плашки: клип RYA-… или файл"""
    if isinstance(s, dict) and s.get('url') and not (s.get('clip') or s.get('kb')):
        from urllib.parse import urlparse
        return urlparse(s['url']).netloc.replace('www.', '')           # «kremlin.ru», а не хвост адреса «12117»
    if isinstance(s, dict) and s.get('note') and not (s.get('clip') or s.get('kb')):
        return 'схема'
    s = s if isinstance(s, str) else (s.get('clip') or s.get('kb') or s.get('url') or s.get('note') or '')
    m = re.search(r'RYA-[A-Z0-9]+-\d{3,4}', s)
    return m.group(0) if m else Path(s).name[:40]


def source_links(s):
    """ссылки на один исходник макета: {clip|kb|url|note} или строка (id клипа / путь картинки базы)"""
    import drive_links as DL
    if isinstance(s, str):
        s = {'clip': s} if re.search(r'RYA-[A-Z0-9]+-\d{3,4}', s) else {'kb': s}
    if s.get('clip'):
        return f"{source_name(s)}: {DL.line(DL.clip_links(s['clip'])) or 'оригинал в Drive не найден'}"
    if s.get('kb'):
        lk = DL.kb_links(s['kb'])
        return f"{Path(lk.get('source') or s['kb']).name}: {DL.line(lk) or 'файл в Drive не найден'}"
    return ' · '.join(x for x in (s.get('note'), s.get('url')) if x)


def source_line(ins, links=False):
    """строка «откуда картинка». links=False — коротко, для плашки на самом макете; links=True — со ссылками на САМИ
    файлы в Drive (Роман 16.09.2026): весь PDF со страницей + папка, оригинал клипа, исходники макета"""
    import drive_links as DL
    if ins['src'] == 'kb':
        head = f"Фото: {ins.get('credit') or '—'}" + (f' · {SCAN_MARK}' if is_scan(ins['path']) else '')
        if not links:
            return head
        url = ins.get('url') or journal_url(ins)
        return ' · '.join(x for x in (head, DL.line(DL.kb_links(ins['path'])), f'издание: {url}' if url else '') if x)
    if ins['src'] == 'mock':
        srcs = ins.get('sources') or []
        if not links:
            return 'Макет ревью (DRAFT)' + (' · исходники: ' + ', '.join(source_name(s) for s in srcs) if srcs else '')
        return ' · '.join(['Макет ревью (DRAFT)'] + [source_links(s) for s in srcs])
    stem = Path(ins['path']).stem
    scene = Path(ins['path']).parent.name
    head = f"Свой клип: {stem} @ {mmss(float(ins.get('in', 0)))}" + (f" · сцена {scene}" if scene else '')
    if not links:
        return head
    return ' · '.join(x for x in (head, DL.line(DL.clip_links(ins['path'])),
                                  f"фрагмент: {ins['clip_url']}" if ins.get('clip_url') else '') if x)


def upload_own_clips(picks, remote):
    """Фрагменты своих клипов (вход −2 с … выход +2 с) → Drive, чтобы у макета была ссылка на исходник.
    Роман 16.09.2026: «когда собираешь макеты, нужно чтобы все ссылки на исходники»."""
    out = OUT / 'clips'
    out.mkdir(exist_ok=True)
    made = {}
    for ins in picks['inserts']:
        if ins['src'] != 'own' or ins.get('doc_only'):
            continue
        t0 = max(0.0, float(ins.get('in', 0)) - 2.0)
        dur = float(ins.get('dur', 4.0)) + 4.0
        f = out / f"src_{ins['id']}_{Path(ins['path']).stem}.mp4"
        if not f.exists():
            r = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t0:.2f}', '-i', str(ins['path']), '-t', f'{dur:.2f}',
                                '-vf', 'scale=1280:-2', '-c:v', 'h264_videotoolbox', '-b:v', '3M', '-an', '-y', str(f)],
                               capture_output=True, text=True, timeout=300)
            if r.returncode or not f.exists():
                print('фрагмент FAIL', ins['id'], r.stderr[-160:])
                continue
        made[ins['id']] = f.name
    if not made:
        return {}
    subprocess.run(['rclone', 'copy', str(out), remote, '--include', 'src_*.mp4', '--transfers', '4'], check=True)
    ls = json.loads(subprocess.run(['rclone', 'lsjson', remote, '--files-only', '--include', 'src_*.mp4'],
                                   capture_output=True, text=True, check=True).stdout)
    ids = {f['Name']: f['ID'] for f in ls}
    urls = {k: f"https://drive.google.com/file/d/{ids[v]}/view" for k, v in made.items() if v in ids}
    dc_path = P.MONT / 'drive_clips.json'                       # чтобы вкладка и лист тоже ставили ссылку на клип
    dc = json.loads(dc_path.read_text(encoding='utf-8')) if dc_path.exists() else {}
    for ins in picks['inserts']:
        fid = ids.get(made.get(ins['id'], ''))
        m = re.search(r'RYA-[A-Z0-9]+-\d{3,4}', Path(ins.get('path', '')).stem)
        if fid and m:
            dc.setdefault(m.group(0) + '.MP4', [{'id': fid, 'name': made[ins['id']], 'note': 'фрагмент ревью'}])
    P.write_json_atomic(dc_path, dc)
    print(f'фрагменты своих клипов: {len(urls)} → Drive · drive_clips {len(dc)}')
    return urls


def stamp_source(im, text):
    """плашка с источником по низу картинки (макет монтажёру читается без дока)"""
    from PIL import Image, ImageDraw, ImageFont
    if not text:
        return im
    w, h = im.size
    size = max(13, w // 58)
    try:
        font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', size)
    except Exception:                                          # noqa: BLE001 — шрифта нет: пишем системным
        font = ImageFont.load_default()
    pad = size // 2
    bar = size + pad * 2
    out = Image.new('RGB', (w, h + bar), (18, 18, 22))
    out.paste(im, (0, 0))
    d = ImageDraw.Draw(out)
    while font.getlength(text) > w - pad * 2 and len(text) > 20:
        text = text[:-4] + '…'
    d.text((pad, h + pad), text, fill=(226, 218, 200), font=font)
    return out


def cmd_cards():
    from PIL import Image
    picks = json.load(open(OUT / 'picks.json', encoding='utf-8'))
    src_dir, doc = P.MOCK / 'src', OUT / 'doc'
    src_dir.mkdir(parents=True, exist_ok=True)
    doc.mkdir(exist_ok=True)
    render = Path.home() / 'YTAI/scripts/999_extra/infographic/render.py'
    import html as _h
    removed = {g['group'] for g in picks['groups'] if g.get('removed')}
    for ins in [i for i in picks['inserts'] if i.get('group') not in removed]:   # снятые группы не рисуем
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
        im = stamp_source(im, source_line(ins))               # Роман 16.09: на макете видно, откуда картинка
        im.save(doc / f"kbv_{ins['id']}.jpg", quality=86)
        print('card', ins['id'], ins['src'], ins['title'], '·', source_line(ins)[:60])


KBV_SOURCES = ('kb_visuals', 'roman_notes_', 'roman_timeline_')


def tz_key(t):
    """ключ готовой записи из picks['tz'] (вырезки, заметки без вставок)"""
    return t.get('kbv_group') or t.get('group') or f"tz:{t.get('title', '')}"


def place_records(old_all, new_by_key, order, removed, tz_keys=()):
    """Номер ТЗ = позиция в pravki['all'] на ВСЕХ поверхностях (s10, вкладка, verify, лист, таймлайн), а tz_overrides
    привязаны к номерам. Раньше apply выкидывал все свои записи и дописывал их в конец — номера ехали, оверрайды
    били мимо (YTUVI02 v2). Теперь: запись группы встаёт на своё прежнее место; убранная группа (`removed`) остаётся
    на месте снятой (status rejected — номер сохранён, строки нет); новые группы — только в конец.
    Старые записи без `kbv_group` один раз сопоставляются: с готовыми ТЗ из picks['tz'] — по точному заголовку (они
    копируются дословно), с группами — по порядку (группы в picks.json только дописываются; ключи tz в `order` стоят
    после ВСЕХ групп, включая новые, поэтому по порядку их сопоставлять нельзя — YTUVI02 v3: вырезка ТЗ-78 уехала бы на 98)."""
    have = {p.get('kbv_group') for p in old_all if p.get('kbv_group')}
    tz_keys = set(tz_keys)
    legacy_groups = iter([k for k in order if k not in have and k not in tz_keys])
    tz_by_title = {}
    for k in order:
        if k in tz_keys and k not in have:
            tz_by_title.setdefault((new_by_key.get(k) or {}).get('title'), []).append(k)
    out, placed = [], set()
    for p in old_all:
        mine = bool(p.get('kbv_group')) or str(p.get('source') or '').startswith(KBV_SOURCES)
        if not mine:
            out.append(p)
            continue
        key = p.get('kbv_group')
        if not key:
            same = tz_by_title.get(p.get('title')) or []
            key = same.pop(0) if same else next(legacy_groups, None)
        if key is None or (key not in new_by_key and key not in removed):
            key = key or f"lost:{p.get('title', '')}"
            p = {**p, 'kbv_group': key, 'status': 'rejected', 'rejected_by': 'kb_visuals'}
            print(f'  !! {key}: группы больше нет в picks.json — ТЗ снято, номер сохранён')
            out.append(p)
            placed.add(key)
            continue
        if key in removed:
            new = {**p, 'kbv_group': key, 'status': 'rejected', 'rejected_by': 'kb_visuals', 'removed_why': removed[key]}
        else:
            new = dict(new_by_key[key])
            if p.get('status') == 'rejected' and p.get('rejected_by') != 'kb_visuals':    # Роман снял строку в доке
                new['status'], new['rejected_by'] = 'rejected', p.get('rejected_by')
            for k in ('roman_comment', 'replies'):                                       # его комменты не теряем
                if p.get(k) and not new.get(k):
                    new[k] = p[k]
        out.append(new)
        placed.add(key)
    for key in order:
        if key not in placed and key in new_by_key and key not in removed:
            out.append(new_by_key[key])
    return out


def cmd_apply():
    picks = json.load(open(OUT / 'picks.json', encoding='utf-8'))
    removed = {g['group']: g['removed'] for g in picks['groups'] if g.get('removed')}
    picks['inserts'] = [i for i in picks['inserts'] if i.get('group') not in removed]
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
    added = []
    by_group = {}
    for ins in picks['inserts']:
        by_group.setdefault(ins['group'], []).append(ins)
    clip_urls = {} if '--no-clips' in sys.argv else upload_own_clips(picks, P.need('shots_remote'))
    for ins in picks['inserts']:
        if clip_urls.get(ins['id']):
            ins['clip_url'] = clip_urls[ins['id']]
    for g in picks['groups']:
        if g['group'] in removed:
            continue
        mats, credits = [], []
        for i in by_group.get(g['group'], []):
            if i['src'] == 'kb':
                import drive_links as DL
                url = i.get('url') or journal_url(i)
                scan = f' · {SCAN_MARK}' if is_scan(i['path']) else ''
                files = DL.line(DL.kb_links(i['path']))
                mats.append({'t': f"{i['title']} — {i['desc']}", 'img': f"kbv_{i['id']}.jpg", 'src': f"Фото: {i['credit']}{scan}"})
                # сама страница источника картинкой в доке + ссылки на САМ файл (весь PDF со страницей) и папку
                # (Роман 16.09.2026: «ссылки на исходники — на сами файлы»; права на фото из журналов — можно)
                mats.append({'t': f"страница источника: {i['credit']}", 'img': f"kbvsrc_{i['id']}.jpg",
                             'src': ' · '.join(x for x in (files, f'издание: {url}' if url else '') if x)
                                    or 'файл в Drive-зеркале базы не найден'})
                credits.append(' — '.join(x for x in (f"{i['credit']}{scan}", files or url) if x))
            elif i['src'] == 'mock':
                mats.append({'t': f"{i['title']} — {i['desc']}", 'img': f"kbv_{i['id']}.jpg", 'src': 'Макет ревью (DRAFT)'})
                for s in i.get('sources') or []:                     # каждый исходник макета — своей строкой со ссылкой
                    mats.append({'t': f'исходник макета: {source_name(s)}', 'src': source_links(s)})
            else:
                mats.append({'t': f"{i['title']} — {i['desc']}", 'img': f"kbv_{i['id']}.jpg", 'src': source_line(i, links=True)})
        added.append({'kbv_group': g['group'], 'notes': g.get('notes', []) + ['kb_visuals_1509'], 'v1_tc': g['v1_tc'], 'tc_range': g['tc_range'],
                      'title': g['title'], 'category': g.get('category', 'insert'), 'source': g.get('source', 'kb_visuals'), 'est': g['now'],
                      'nado': '', 'material_rich': mats, 'typo': [], 'sheet_answer': '', 'decision': g.get('decision', ''),
                      'parts': {'now': [g['now']], 'do': [{'h': g.get('do_h', ''), 'items': g['do']}],
                                'src': ([f'📚 {c}' for c in credits] or g.get('src', [])),
                                'tl': ([f"слой V2 ревью-секвенции: {', '.join(i['title'] for i in by_group.get(g['group'], []) if not i.get('doc_only'))}"]
                                       if any(not i.get('doc_only') for i in by_group.get(g['group'], [])) else [])}})
    for t in picks.get('tz', []):
        added.append({**t, 'kbv_group': tz_key(t)})
    order = [g['group'] for g in picks['groups']] + [tz_key(t) for t in picks.get('tz', [])]
    n_before = len(pr['all'])
    pr['all'] = place_records(pr['all'], {a['kbv_group']: a for a in added}, order, removed,
                              tz_keys=[tz_key(t) for t in picks.get('tz', [])])
    P.write_json_atomic(P.MONT / 'pravki_v2.json', pr)
    print(f'apply: ТЗ было {n_before}, стало {len(pr["all"])} (новые — в конце, снятых групп {len(removed)})')
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
    {'needs': cmd_needs, 'pick': cmd_pick, 'verify': cmd_verify, 'sheets': cmd_sheets, 'propose': cmd_propose,
     'cards': cmd_cards, 'apply': cmd_apply, 'retime': cmd_retime, 'targets': cmd_targets}[sys.argv[1]]()
