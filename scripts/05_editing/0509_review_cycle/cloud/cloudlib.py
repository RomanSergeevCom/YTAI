#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cloudlib — общий слой облачного прохода ревью (pack.py / collect.py / salvage.py).

Не запускается сам. Даёт: пути облака (`P.CLOUD/in|out|raw|crops`, `state.json`), чтение
локальных данных фильма (экраны, VLM, LLM, пробы, транскрипт, кандидаты, pravki), стабильные
идентификаторы (sha8, finding_id), разбор ответов агентов (JSON / python-repr / dict) и
вывод находок `review-findings-v8` из готовых батчей (`derive_findings`).

Все пути — из карточки фильма (proj_config через stages/_bootstrap):
    P.WORK   screens_v6.json · vlm_v6.jsonl · llm_v6.json · probes.jsonl · candidates.json · hires/
    P.MONT   pravki.json (или pravki_v2.json)
    P.CLOUD  in/ · out/ · raw/<runId>/ · crops/<batch>/ · state.json

Идентификаторы находок (детерминированы, считаются и в python, и в wf_judge.js):
    вердикт по кандидату      finding_id = cand_id            (c0012)
    новая находка судьи       finding_id = <J batch>.n<NN>    (J_01_ab12cd34.n03)
    факт без кандидата        finding_id = <F batch>.f<NN>    (F_9f8e7d6c.f02)
"""
import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # cloud/
ROOT = HERE.parent                                # папка стадии
YTAI_ROOT = ROOT.parent.parent.parent             # ~/YTAI (не зависит от карточки)
_stages = str(ROOT / 'stages')
if _stages not in sys.path:
    sys.path.insert(0, _stages)
try:
    from _bootstrap import P, W6, M, CLOUD, ROOT as STAGE_ROOT  # noqa: E402,F401
except SystemExit:
    # salvage.py --cost / --out работает и без карточки фильма (только сессии Claude Code)
    if os.environ.get('YTAI_CLOUD_NO_CARD') != '1':
        raise
    P = W6 = M = CLOUD = STAGE_ROOT = None
_shared = str(ROOT / 'shared')
if _shared not in sys.path:
    sys.path.insert(0, _shared)
import i18n  # noqa: E402  (после _bootstrap: язык из карточки; без карточки — YTAI_LANG / 'ru')

IN = CLOUD / 'in' if CLOUD else None
OUT = CLOUD / 'out' if CLOUD else None
RAW = CLOUD / 'raw' if CLOUD else None
CROPS = CLOUD / 'crops' if CLOUD else None
STATE_PATH = CLOUD / 'state.json' if CLOUD else None
STATE_SCHEMA = 'review-cloud-state-v1'
FINDINGS_PATH = W6 / 'audit_findings.json' if W6 else None
FINDINGS_SCHEMA = 'review-findings-v8'
LEGACY_FINDINGS_PATH = W6 / 'audit_findings_v6.json' if W6 else None
WF_JUDGE = HERE / 'wf_judge.js'
KINDS = ('typo', 'grammar', 'fact', 'currency', 'language', 'mismatch', 'foreign_trace')
SKEPTIC_CODES = ('T', 'V', 'H', 'C', 'F', 'D')
CHECK_SOURCE_FIX = i18n.T('b.check_source_fix')   # RU «проверить исходник титра»; finalize() берёт T() на момент вызова


def ensure_dirs():
    if CLOUD is None:
        raise SystemExit('нет карточки фильма (YTAI_CARD) — папка cloud/ проекта неизвестна')
    for d in (IN, OUT, RAW, CROPS):
        d.mkdir(parents=True, exist_ok=True)


def warn(msg):
    print(f'⚠️ {msg}', file=sys.stderr, flush=True)


# ── JSON / хеши ────────────────────────────────────────────────────────────
def load_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception as ex:
        warn(f'{p}: битый JSON — {ex}')
        return default


def save_json(path, data):
    P.write_json_atomic(path, data)


def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha8(obj):
    return hashlib.sha1(canon(obj).encode('utf-8')).hexdigest()[:8]


def norm_text(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip().lower()


def tc(sec):
    sec = int(float(sec or 0))
    return f'{sec // 60}:{sec % 60:02d}'


# ── состояние облака ───────────────────────────────────────────────────────
def state_load():
    st = load_json(STATE_PATH, None)
    if not isinstance(st, dict):
        st = {}
    st.setdefault('schema', STATE_SCHEMA)
    st.setdefault('run_ids', [])
    st.setdefault('batches', {})
    return st


def state_save(st):
    ensure_dirs()
    save_json(STATE_PATH, st)


def batch_kind(bid, b=None):
    return (b or {}).get('kind') or bid[:1]


def pending_ids(st):
    return [k for k, v in st.get('batches', {}).items() if v.get('status') != 'done']


def done_batches(st, kind=None):
    out = {}
    for bid, b in st.get('batches', {}).items():
        if b.get('status') == 'done' and (kind is None or batch_kind(bid, b) == kind):
            out[bid] = b
    return out


def batch_out_path(bid, b=None):
    p = (b or {}).get('out')
    return Path(p) if p else OUT / f'{bid}.json'


def batch_in_path(bid, b=None):
    p = (b or {}).get('in')
    return Path(p) if p else IN / f'{bid}.json'


# ── локальные данные фильма ────────────────────────────────────────────────
_cache = {}


def screens_list():
    if 'screens' not in _cache:
        ev = load_json(W6 / 'screens_v6.json', None)
        if ev is None:
            raise SystemExit(f'нет {W6 / "screens_v6.json"} — инвентарь экранов (s2_ocr_hires) ещё не готов')
        _cache['screens'] = sorted(ev, key=lambda e: (e.get('t0', 0), e.get('id', '')))
    return _cache['screens']


def screens_map():
    return {e['id']: e for e in screens_list()}


def vlm_map():
    if 'vlm' not in _cache:
        m = {}
        p = W6 / 'vlm_v6.jsonl'
        if p.exists():
            for ln in open(p, encoding='utf-8'):
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                    m[r['id']] = r
                except Exception:
                    pass
        _cache['vlm'] = m
    return _cache['vlm']


def llm_map():
    if 'llm' not in _cache:
        m = {}
        for r in load_json(W6 / 'llm_v6.json', []) or []:
            if isinstance(r, dict) and r.get('id'):
                m[r['id']] = r
        _cache['llm'] = m
    return _cache['llm']


def probes_map():
    """s3b_probe_vlm → probes.jsonl (схема ещё может меняться): ищем булев признак чужого следа."""
    if 'probes' not in _cache:
        m = {}
        p = W6 / 'probes.jsonl'
        if p.exists():
            for ln in open(p, encoding='utf-8'):
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                sid = r.get('id') or r.get('screen_id')
                if not sid:
                    continue
                flag = None
                for k in ('probe_foreign', 'foreign_trace', 'foreign', 'has_foreign', 'traces'):
                    if k in r:
                        v = r[k]
                        flag = bool(v) if not isinstance(v, dict) else bool(v.get('found') or v.get('yes'))
                        break
                m[sid] = {'foreign': flag, 'note': (r.get('note') or r.get('foreign_note') or '')[:160]}
        _cache['probes'] = m
    return _cache['probes']


def words_list():
    if 'words' not in _cache:
        ws = []
        d = load_json(P.WORDS, None)
        if d is None:
            raise SystemExit(f'нет транскрипта {P.WORDS}')
        for seg in d.get('segments') or []:
            for w in seg.get('words') or []:
                try:
                    ws.append((w['w'], float(w['s']), float(w.get('e', w['s']))))
                except Exception:
                    pass
        _cache['words'] = ws
    return _cache['words']


def vo(t0, t1, pad=8.0):
    """Озвучка вокруг экрана ±pad секунд (по стартам слов)."""
    return ' '.join(w for w, s, _e in words_list() if t0 - pad <= s <= t1 + pad)


def candidates_load(quiet=False):
    """work/{cut}/candidates.json (route_candidates.py) или None с предупреждением."""
    p = W6 / 'candidates.json'
    if not p.exists():
        if not quiet:
            warn(f'нет {p} — маршрутизации кандидатов ещё не было: пакеты уйдут с пустыми candidates[]')
        return None
    c = load_json(p, None)
    if isinstance(c, dict):
        c = c.get('candidates') or c.get('all') or []
    return [x for x in (c or []) if isinstance(x, dict) and x.get('cand_id')]


# ── pravki (ТЗ) ────────────────────────────────────────────────────────────
def pravki_path():
    for name in ('pravki.json', 'pravki_v2.json'):
        if (M / name).exists():
            return M / name
    return M / 'pravki_v2.json'


def pravki_load():
    p = pravki_path()
    pr = load_json(p, None)
    if not isinstance(pr, dict) or 'all' not in pr:
        return {'all': []}, []
    return pr, pr['all']


def tz_label(p, i):
    """Номер ТЗ записи: явный `num` (int или «ТЗ-NN»), иначе позиция в списке (как s10/tz_sheet)."""
    n = p.get('num')
    if isinstance(n, int):
        return f'ТЗ-{n:02d}'
    if isinstance(n, str) and n.strip():
        return n if n.startswith('ТЗ') else f'ТЗ-{int(n):02d}' if n.isdigit() else n
    return f'ТЗ-{i + 1:02d}'


def existing_tz_lines():
    """«ТЗ-NN · tc · заголовок» по всем ТЗ (снятые Романом помечены)."""
    _pr, allp = pravki_load()
    out = []
    for i, p in enumerate(allp):
        title = re.sub(r'\s+', ' ', str(p.get('title') or '')).strip()[:90]
        lab = tz_label(p, i)
        if i18n.LANG == 'en' and lab.startswith('ТЗ-'):
            lab = i18n.tz_label(lab)          # англоязычный судья видит FIX-07; в находки вернётся ТЗ-07 (norm_existing_tz)
        line = f"{lab} · {p.get('v1_tc') or p.get('tc_range') or '?'} · {title}"
        if p.get('status') == 'rejected':
            line += i18n.T('b.tz_rejected_suffix')
        out.append(line)
    return out


def norm_existing_tz(s):
    """existing_tz от агента → внутренний ключ «ТЗ-NN» (EN-судья отвечает «FIX-NN»); RU-ответы не меняются."""
    s = (s or '').strip()
    if s[:4].upper() == 'FIX-':
        return 'ТЗ-' + s[4:]
    return s


# ── карточка / профиль ─────────────────────────────────────────────────────
def film():
    return str(P.FILM or P.get('film_subject') or P.CODE)


def rules():
    return str(P.profile('rules_text', '') or '')


def sources():
    base = P.profile('sources_default', []) or []
    extra = P.get('sources') or []
    if isinstance(base, str):
        base = [s.strip() for s in base.split(',') if s.strip()]
    if isinstance(extra, str):
        extra = [s.strip() for s in extra.split(',') if s.strip()]
    out = []
    for s in list(base) + list(extra):
        if s and s not in out:
            out.append(s)
    return out


# ── разбор ответов агентов ─────────────────────────────────────────────────
def parse_result(x):
    """Результат агента: dict/list как есть; строка — JSON, затем python-repr; иначе None."""
    if isinstance(x, (dict, list)):
        return x
    if not isinstance(x, str):
        return None
    s = x.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        pass
    try:
        return ast.literal_eval(s)
    except Exception:
        pass
    m = re.search(r'[\{\[]', s)              # текст вокруг JSON («вот результат: {...}»)
    if m:
        for cut in (s[m.start():], s[m.start():s.rfind('}') + 1]):
            try:
                return json.loads(cut)
            except Exception:
                continue
    return None


def batch_id_of(obj):
    if isinstance(obj, dict):
        b = obj.get('batch_id')
        if isinstance(b, str) and re.match(r'^[JFVS]_', b):
            return b
    return None


# ── bbox по строкам OCR ────────────────────────────────────────────────────
def _bb(l):
    return {'x': l.get('x', 0), 'y': l.get('y', 0), 'w': l.get('bw', l.get('w', 0)), 'h': l.get('bh', l.get('h', 0))}


def line_bbox(scr, idx):
    lines = (scr or {}).get('lines_best') or []
    try:
        idx = int(idx)
    except Exception:
        return None
    if 0 <= idx < len(lines):
        return _bb(lines[idx])
    return None


def match_line(scr, text):
    """Индекс строки OCR, максимально похожей на текст (≥0.5), иначе None."""
    import difflib
    lines = (scr or {}).get('lines_best') or []
    t = norm_text(text)
    if not t or not lines:
        return None
    best, bi = 0.0, None
    for i, l in enumerate(lines):
        lt = norm_text(l.get('t'))
        if not lt:
            continue
        r = difflib.SequenceMatcher(None, lt, t).ratio()
        if lt in t or t in lt:
            r = max(r, 0.75)
        if r > best:
            best, bi = r, i
    return bi if best >= 0.5 else None


def union_bbox(scr):
    lines = (scr or {}).get('lines_best') or []
    if not lines:
        return None
    x0 = min(l['x'] for l in lines)
    y0 = min(l['y'] for l in lines)
    x1 = max(l['x'] + l.get('bw', 0) for l in lines)
    y1 = max(l['y'] + l.get('bh', 0) for l in lines)
    return {'x': round(x0, 4), 'y': round(y0, 4), 'w': round(x1 - x0, 4), 'h': round(y1 - y0, 4)}


def frame_path(scr):
    bf = (scr or {}).get('best_frame')
    return str(W6 / 'hires' / bf) if bf else ''


# ── сессии Claude Code (journal / task-output) ─────────────────────────────
def sessions_root(override=None):
    if override:
        return Path(override).expanduser()
    env = os.environ.get('YTAI_SESSIONS_DIR')
    if env:
        return Path(env).expanduser()
    slug = '-' + str(YTAI_ROOT).strip('/').replace('/', '-')
    return Path.home() / '.claude' / 'projects' / slug


def tasks_root(session, override=None):
    return Path('/private/tmp') / f'claude-{os.getuid()}' / sessions_root(override).name / session / 'tasks'


def wf_meta_light(mp):
    """Метаданные прогона из <session>/workflows/wf_*.json (скрипт не тянем в память дольше нужного)."""
    d = load_json(mp, {}) or {}
    return {'runId': d.get('runId') or Path(mp).stem, 'name': d.get('workflowName') or '',
            'scriptPath': d.get('scriptPath') or '', 'agents': d.get('agentCount'), 'tokens': d.get('totalTokens'),
            'durationMs': d.get('durationMs'), 'status': d.get('status') or '', 'timestamp': d.get('timestamp') or '',
            'taskId': d.get('taskId') or '', 'args': d.get('args') if isinstance(d.get('args'), dict) else {},
            'result': d.get('result'), 'logs': d.get('logs') or [], 'path': str(mp)}


def list_runs(session=None, latest=False, all_sessions=False, projects_dir=None):
    """[(session_id, run_id, meta_path)] — по сессии, по последней сессии с прогонами или по всем."""
    root = sessions_root(projects_dir)
    if session:
        sd = root / session
        if not (sd / 'workflows').is_dir():
            raise SystemExit(f'в сессии {session} нет workflows/ ({sd})')
        return [(session, mp.stem, mp) for mp in sorted((sd / 'workflows').glob('wf_*.json'))]
    cands = []
    for wd in root.glob('*/workflows'):
        mps = list(wd.glob('wf_*.json'))
        if mps:
            cands.append((max(m.stat().st_mtime for m in mps), wd.parent.name, sorted(mps)))
    cands.sort(reverse=True)
    if not cands:
        raise SystemExit(f'прогонов Workflow не найдено в {root}')
    if latest and not all_sessions:
        cands = cands[:1]
    return [(sid, mp.stem, mp) for _t, sid, mps in cands for mp in mps]


def find_run(run_id, projects_dir=None):
    """Сессия по runId (полному «wf_0965c2cf-962» или префиксу)."""
    root = sessions_root(projects_dir)
    rid = run_id if run_id.startswith('wf_') else 'wf_' + run_id
    hits = sorted(root.glob(f'*/workflows/{rid}.json')) or sorted(root.glob(f'*/workflows/{rid}*.json'))
    return [(mp.parent.parent.name, mp.stem, mp) for mp in hits]


def journal_rows(session, run_id, projects_dir=None):
    p = sessions_root(projects_dir) / session / 'subagents' / 'workflows' / run_id / 'journal.jsonl'
    rows = []
    if p.exists():
        for ln in open(p, encoding='utf-8'):
            ln = ln.strip()
            if ln:
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass
    return p, rows


def agent_structured_outputs(session, run_id, projects_dir=None):
    """(agent_id, obj, path) — последний StructuredOutput каждого agent-*.jsonl прогона."""
    d = sessions_root(projects_dir) / session / 'subagents' / 'workflows' / run_id
    for f in sorted(d.glob('agent-*.jsonl')):
        last = None
        try:
            for ln in open(f, encoding='utf-8'):
                if 'structured_output' not in ln and 'StructuredOutput' not in ln:
                    continue
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                att = r.get('attachment')
                if isinstance(att, dict) and att.get('type') == 'structured_output' and isinstance(att.get('data'), dict):
                    last = att['data']
                    continue
                msg = r.get('message')
                if r.get('type') == 'assistant' and isinstance(msg, dict):
                    for b in msg.get('content') or []:
                        if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') == 'StructuredOutput' \
                                and isinstance(b.get('input'), dict):
                            last = b['input']
        except Exception:
            continue
        if last is not None:
            yield f.stem.replace('agent-', ''), last, f


def _descr(obj, agent_id=''):
    if isinstance(obj, dict):
        return f'{agent_id[:8]} dict[{", ".join(list(obj)[:5])}]'
    return f'{agent_id[:8]} {type(obj).__name__}'


def harvest_run(session, run_id, meta_path, need=None, projects_dir=None):
    """Все результаты прогона с batch_id: journal → wf-meta.result.results → task-output → agent-файлы.

    need — множество batch_id, ради которых стоит читать тяжёлые agent-файлы (None = только если журнал
    неполон). Возвращает {'meta', 'payloads': {bid: (obj, source)}, 'legacy': [описания без batch_id],
    'failed': n, 'paths': {journal, task, agents: [...]}}.
    """
    meta = wf_meta_light(meta_path)
    payloads, legacy = {}, []
    jp, rows = journal_rows(session, run_id, projects_dir)
    failed = sum(1 for r in rows if r.get('type') == 'failed')
    n_res = 0
    for r in rows:
        if r.get('type') != 'result':
            continue
        n_res += 1
        obj = parse_result(r.get('result'))
        bid = batch_id_of(obj)
        if bid:
            payloads.setdefault(bid, (obj, 'journal'))
        else:
            legacy.append(_descr(obj, r.get('agentId', '')))
    res = meta.get('result')
    if isinstance(res, dict):
        rr = res.get('results')
        if isinstance(rr, dict):
            for bid, obj in rr.items():
                if batch_id_of(obj) or re.match(r'^[JFVS]_', str(bid)):
                    payloads.setdefault(bid, (obj, 'wf-meta'))
        elif not batch_id_of(res):
            legacy.append('wf-result ' + _descr(res))
    tpath = tasks_root(session, projects_dir) / f'{meta["taskId"]}.output' if meta.get('taskId') else None
    if tpath and tpath.exists():
        d = load_json(tpath, None)
        rr = (d.get('result') or {}).get('results') if isinstance(d, dict) and isinstance(d.get('result'), dict) else None
        if isinstance(rr, dict):
            for bid, obj in rr.items():
                if re.match(r'^[JFVS]_', str(bid)):
                    payloads.setdefault(bid, (obj, 'task-output'))
    agents_used = []
    missing = set(need or []) - set(payloads)
    if missing or (need is None and failed and n_res < len([r for r in rows if r.get('type') == 'started'])):
        for aid, obj, f in agent_structured_outputs(session, run_id, projects_dir):
            bid = batch_id_of(obj)
            if bid and bid not in payloads:
                payloads[bid] = (obj, 'agent-file')
                agents_used.append(str(f))
    return {'meta': meta, 'payloads': payloads, 'legacy': legacy, 'failed': failed,
            'paths': {'journal': str(jp) if jp.exists() else '', 'task': str(tpath) if tpath and tpath.exists() else '',
                      'agents': agents_used}}


def expected_batches(meta):
    """Какие батчи прогон должен был вернуть (по его args)."""
    a = meta.get('args') or {}
    ids = [p.get('batch_id') for p in (a.get('packs') or []) if isinstance(p, dict)]
    for k in ('facts_pack', 'crops_pack', 'skeptic'):
        v = a.get(k)
        if isinstance(v, dict) and v.get('batch_id'):
            ids.append(v['batch_id'])
    return [i for i in ids if i]


def is_ours(meta):
    return meta.get('scriptPath', '').endswith('wf_judge.js') or bool(expected_batches(meta)) \
        or (isinstance(meta.get('result'), dict) and 'batches_done' in meta['result'])


# ── находки из готовых батчей ──────────────────────────────────────────────
def fid_new(batch_id, i):
    return f'{batch_id}.n{i:02d}'


def fid_fact(batch_id, i):
    return f'{batch_id}.f{i:02d}'


def qid(batch_id, i):
    return f'{batch_id}.q{i:02d}'


def _clip(s, n=600):
    s = str(s or '')
    return s if len(s) <= n else s[:n - 1] + '…'


def derive_findings(st, legacy=None):
    """Все находки из done-батчей (J → F/V → S) + auto_confirm-кандидаты + legacy (если передан список).

    Возвращает (findings, extras): findings — список dict `review-findings-v8` в стабильном порядке;
    extras = {'facts_ok': [...], 'unmapped': [...]}. Вердикт скептика применяется тут же:
    T/V/C/F/D → статус refuted_by_skeptic, H → kind check_source (находка остаётся).
    """
    cands_list = candidates_load(quiet=True) or []
    cands = {c['cand_id']: c for c in cands_list}
    scr = screens_map()
    F, order = {}, []

    def put(fid, f):
        if fid not in F:
            order.append(fid)
        F[fid] = f

    for f in legacy or []:
        put(f['finding_id'], dict(f))

    batches = st.get('batches', {})
    done = {bid: b for bid, b in batches.items() if b.get('status') == 'done'}
    unmapped = []

    def out_of(bid, b):
        p = batch_out_path(bid, b)
        o = load_json(p, None) if p.exists() else None
        return o if isinstance(o, dict) else None

    # J: вердикты и новые находки
    for bid in sorted(done):
        b = done[bid]
        if batch_kind(bid, b) != 'J':
            continue
        o = out_of(bid, b)
        if not o:
            continue
        run_id = b.get('run_id') or o.get('run_id')
        for v in o.get('verdicts') or []:
            cid = v.get('cand_id')
            if not cid:
                continue
            c = cands.get(cid, {})
            sid = v.get('screen_id') or c.get('screen_id')
            put(cid, dict(
                finding_id=cid, screen_id=sid, kind=v.get('kind') or c.get('kind') or 'other',
                on_screen_text=v.get('on_screen_text') or c.get('on_screen_text') or '',
                line_idx=c.get('line_idx'), fix_text=v.get('fix_text') or c.get('fix_local') or '',
                problem=_clip(v.get('reason') or c.get('route_reason') or ''), why=_clip(v.get('reason') or ''),
                severity=v.get('severity') or 'medium', route='cloud', verdict=v.get('verdict') or 'confirm',
                confidence=v.get('confidence'), existing_tz=norm_existing_tz(v.get('existing_tz')),
                run_id=run_id, batch_id=bid))
        for i, n in enumerate(o.get('new_findings') or [], 1):
            fid = fid_new(bid, i)
            put(fid, dict(
                finding_id=fid, screen_id=n.get('screen_id'), kind=n.get('kind') or 'other',
                on_screen_text=n.get('on_screen_text') or '', line_idx=n.get('line_idx'),
                fix_text=n.get('fix_text') or '', problem=_clip(n.get('problem') or ''), why=_clip(n.get('why') or ''),
                severity=n.get('severity') or 'medium', route='cloud', verdict='new_finding', confidence=None,
                existing_tz=norm_existing_tz(n.get('existing_tz')), run_id=run_id, batch_id=bid))

    # auto_confirm кандидаты (0 токенов)
    for c in cands_list:
        if c.get('route') == 'auto_confirm' and c['cand_id'] not in F:
            put(c['cand_id'], dict(
                finding_id=c['cand_id'], screen_id=c.get('screen_id'), kind=c.get('kind') or 'other',
                on_screen_text=c.get('on_screen_text') or '', line_idx=c.get('line_idx'),
                fix_text=c.get('fix_local') or '', problem=_clip(c.get('route_reason') or ''),
                # why → «📚 ИСТОЧНИК» у монтажёра: RU как было (сигналы роутера); EN — сигналы отдельным полем, в ТЗ не идут
                why=', '.join(c.get('signals') or []) if i18n.LANG != 'en' else '', severity=c.get('severity') or 'medium',
                route='auto_confirm', verdict='confirm', confidence=None, existing_tz='', run_id=None, batch_id=None,
                **({'signals': list(c.get('signals') or [])} if i18n.LANG == 'en' else {})))

    # F: факты
    facts_ok = []
    for bid, b in done.items():
        if batch_kind(bid, b) != 'F':
            continue
        pack = load_json(batch_in_path(bid, b), {}) or {}
        o = out_of(bid, b)
        if not o:
            continue
        items = {it.get('fact_id'): it for it in pack.get('items') or []}
        for r in o.get('results') or []:
            it = items.get(r.get('fact_id')) or {k: r.get(k) for k in ('screen_id', 'cand_id', 'claim', 'on_screen_text')}
            fact = {'status': r.get('status') or 'unclear', 'correct_value': r.get('correct_value') or '',
                    'source_url': r.get('source_url') or '', 'note': _clip(r.get('note') or '', 300)}
            fid = it.get('cand_id') or r.get('cand_id') or r.get('fact_id')
            if not fid:
                continue
            if fid in F:
                F[fid]['fact'] = fact
            elif fact['status'] == 'wrong':
                put(fid, dict(
                    finding_id=fid, screen_id=it.get('screen_id'), kind='fact',
                    on_screen_text=it.get('on_screen_text') or '', line_idx=None, fix_text=fact['correct_value'],
                    problem=_clip(it.get('claim') or ''), why=_clip(fact['note'] or fact['source_url']),
                    severity='high', route='cloud', verdict='fact_check', confidence=None, existing_tz='',
                    run_id=b.get('run_id'), batch_id=bid, fact=fact))
            else:
                facts_ok.append({'fact_id': r.get('fact_id'), 'screen_id': it.get('screen_id'),
                                 'claim': _clip(it.get('claim') or '', 200), **fact})

    # V: кропы
    for bid, b in done.items():
        if batch_kind(bid, b) != 'V':
            continue
        pack = load_json(batch_in_path(bid, b), {}) or {}
        o = out_of(bid, b)
        if not o:
            continue
        items = {it.get('q_id'): it for it in pack.get('items') or []}
        for r in o.get('results') or []:
            it = items.get(r.get('q_id')) or {k: r.get(k) for k in ('screen_id', 'cand_id')}
            crop = {'text_as_seen': r.get('text_as_seen') or '', 'error_visible': bool(r.get('error_visible')),
                    'answer': _clip(r.get('answer') or '', 400), 'confidence': r.get('confidence')}
            cid = it.get('cand_id') or r.get('cand_id') or ''
            if cid:
                targets = [cid]
            else:
                targets = [fid for fid in order if F[fid].get('screen_id') == it.get('screen_id')
                           and F[fid].get('verdict') in ('new_finding', 'need_frame') and not F[fid].get('crop')]
            hit = False
            for t in targets:
                if t in F:
                    F[t]['crop'] = crop
                    hit = True
            if not hit:
                unmapped.append({'batch': bid, 'q_id': r.get('q_id'), 'why': 'нет находки под кроп'})

    # S: скептик
    for bid, b in done.items():
        if batch_kind(bid, b) != 'S':
            continue
        o = out_of(bid, b)
        if not o:
            continue
        for v in o.get('verdicts') or []:
            fid = v.get('finding_id')
            if fid in F:
                code = (v.get('code') or '').strip().upper()
                F[fid]['skeptic'] = {'real': v.get('real') if isinstance(v.get('real'), bool) else True,
                                     'code': code if code in SKEPTIC_CODES else '',
                                     'reason': _clip(v.get('reason') or '', 500),
                                     'corrected_fix_text': (v.get('corrected_fix_text') or '').strip(), 'batch_id': bid}
            else:
                unmapped.append({'batch': bid, 'finding_id': fid, 'why': 'скептик судил неизвестную находку'})

    for fid in order:
        finalize(F[fid], scr.get(F[fid].get('screen_id')))
    return [F[fid] for fid in order], {'facts_ok': facts_ok, 'unmapped': unmapped}


def finalize(f, scr):
    """Дополнить находку экраном (tc/t0/t1/кадр/bbox) и вычислить статус/confirmed."""
    if scr:
        f.setdefault('tc', scr.get('tc'))
        f.setdefault('t0', scr.get('t0'))
        f.setdefault('t1', scr.get('t1'))
        f.setdefault('chapter', scr.get('chapter'))
        if not f.get('frame') or not Path(f['frame']).exists():
            f['frame'] = frame_path(scr)
        li = f.get('line_idx')
        if li is None or (isinstance(li, int) and li < 0):
            li = match_line(scr, f.get('on_screen_text'))
            f['line_idx'] = li
        if not f.get('bbox'):
            f['bbox'] = line_bbox(scr, li) if li is not None else None
        if not f.get('bbox'):
            f['bbox'] = union_bbox(scr)
    sk = f.get('skeptic') or {}
    if sk.get('corrected_fix_text') and sk['corrected_fix_text'] != f.get('fix_text'):
        f['fix_text_judge'] = f.get('fix_text')
        f['fix_text'] = sk['corrected_fix_text']
    v = f.get('verdict')
    if v == 'fact_check':
        fact = f.get('fact')
        if fact and fact.get('status') == 'wrong':
            eff = 'confirm'
            if fact.get('correct_value') and not f.get('fix_text'):
                f['fix_text'] = fact['correct_value']
        elif fact and fact.get('status') == 'verified':
            eff = 'refute'
        elif fact:
            eff = 'unclear'
        else:
            eff = 'pending_fact'
    elif v == 'need_frame':
        crop = f.get('crop')
        eff = 'confirm' if (crop and crop.get('error_visible')) else ('refute' if crop else 'pending_frame')
    elif v in ('confirm', 'new_finding', 'refute'):
        eff = v
    else:
        eff = v or 'confirm'
    if sk:
        if sk.get('code') == 'H':
            f['kind'] = 'check_source'
            f['fix_text'] = i18n.T('b.check_source_fix')
            if eff in ('pending_frame', 'pending_fact', 'unclear'):
                eff = 'confirm'
        elif sk.get('real') is False and sk.get('code') in ('T', 'V', 'C', 'F', 'D'):
            eff = 'refuted_by_skeptic'
        elif sk.get('real') is False:
            eff = 'refuted_by_skeptic'
    f['status'] = eff
    f['confirmed'] = eff in ('confirm', 'new_finding')
    return f


def needs_skeptic(f):
    return f.get('status') in ('confirm', 'new_finding') and not f.get('skeptic')


def summarize_findings(findings):
    from collections import Counter
    c = Counter(f.get('status') for f in findings)
    k = Counter(f.get('kind') for f in findings if f.get('confirmed'))
    return {'total': len(findings), 'confirmed': sum(1 for f in findings if f.get('confirmed')),
            'by_status': dict(c), 'confirmed_by_kind': dict(k),
            'need_skeptic': sum(1 for f in findings if needs_skeptic(f))}
