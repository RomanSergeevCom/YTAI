#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""golden.py — RU-регрессия цепочки ревью на песочной копии YTUVI02 (0 токенов, без Google API и моделей).

    python3 shared/golden.py snapshot            # заморозить входы из реального YTUVI02 и снять эталон всех шагов
    python3 shared/golden.py compare              # свежая песочница → все шаги подряд → сверка с эталоном
    python3 shared/golden.py compare --only STEP  # свежие входы + эталонные выходы предыдущих шагов → STEP → сверка
    python3 shared/golden.py list                 # шаги, выходы, исключённые стадии

Зачем: локализация (i18n) не имеет права сдвинуть ни байта в русских поверхностях. Эталон снимается ДО правок
строк; после каждой правки `compare` обязан показать «идентично».

Песочница: ~/YTAI_work/_golden/YTUVI02/00_Setup/05_Review (вне всех проектов). Входы замораживаются в
_golden_in/ (реальный проект могут править другие сессии — эталон не должен плыть вместе с ним); сырые выходы
шагов — _golden_out/<step>/; хэши нормализованных выходов и список шагов — examples/ytuvi02_golden/golden.json.
Реальный 05_Review YTUVI02 только читается: до и после каждого прогона — find -newer, любая запись = отказ
(кроме notes/, куда пишет внешний notes-цикл, — там предупреждение).
Нормализация перед хэшем: пути песочницы/проекта/дома → плейсхолдеры, ISO-время → <TS>, ключ JSON «created» убран.
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

STAGE = Path(__file__).resolve().parent.parent
YTAI = STAGE.parent.parent.parent
REAL = Path('/Volumes/T7-Blue-2-RYA/YTUVI-Projects/YTUVI02_Ruby_Certificate/00_Setup/05_Review')
BASE = Path.home() / 'YTAI_work' / '_golden' / 'YTUVI02'
SB = BASE / '00_Setup' / '05_Review'
GIN = BASE / '_golden_in'
GOUT = BASE / '_golden_out'
GJSON = STAGE / 'examples' / 'ytuvi02_golden' / 'golden.json'
PY = sys.executable or 'python3'
PY_LLM = YTAI / 'environment' / '.venv_llm' / 'bin' / 'python'
NODE = '/opt/homebrew/bin/node' if Path('/opt/homebrew/bin/node').exists() else 'node'
CODE = 'YTUVI02'
CUT = 'v1'

S = STAGE / 'stages'
SH = STAGE / 'shared'

# (имя, argv, выходы (относительно песочницы; * = glob), доп. env) — порядок = порядок стадий review.py
STEPS = [
    ('route', lambda: [str(PY_LLM) if PY_LLM.exists() else PY, S / 'route_candidates.py', '--out', SB / 'work/v1/candidates.json'],
     ['work/v1/candidates.json', 'work/v1/candidates_summary.json'], {}),
    ('apply', lambda: [PY, S / 's8_apply_audit.py'], ['pravki/pravki_v2.json', 'work/v1/audit_v6.json'], {}),
    ('terms', lambda: [PY, S / 'terms_index.py'], ['work/v1/terms_v6.json'], {}),
    ('format_tz', lambda: [PY, S / 's10_format_tz.py'], ['pravki/pravki_v2.json', 'work/v1/lint_v7.json'], {}),
    ('sources', lambda: [PY, S / 's11_apply_sources.py'], ['pravki/pravki_v2.json'], {}),
    ('infographics_html', lambda: [PY, S / 'make_infographics_v6.py', 'all'], ['mockups/src/*.html'],
     {'YTAI_RENDER_HTML_ONLY': '1'}),
    ('review_json', lambda: [PY, S / 'make_review_v6.py'], [f'{CODE}_review_v6.json', f'{CODE}_review_v6_summary.md'], {}),
    ('mock', lambda: [NODE, S / 'mockbuild_v6.js'], [], {}),
    ('sheet_dump', lambda: [PY, S / 'tz_sheet.py', '--dump-rows', SB / '_dump/sheet_rows.json'], ['_dump/sheet_rows.json'], {}),
    ('tz_dump', lambda: [PY, S / 'doc_tab_tz_v4.py', '--dump-requests', SB / '_dump/tz_requests.json'],
     ['_dump/tz_requests.json'], {}),
    ('nav_dump', lambda: [PY, S / 'doc_tab_review_v1.py', '--dump-requests', SB / '_dump/nav_requests.json'],
     ['_dump/nav_requests.json'], {}),
    ('phone_brief', lambda: [PY, SH / 'phone_brief.py', '--out', SB / f'{CODE}_{CUT}_brief.html'],
     [f'{CODE}_{CUT}_brief.html'], {}),
    ('producer_page', lambda: [PY, SH / 'producer_page.py', '--out', SB / f'{CODE}_{CUT}_review_producer.html'],
     [f'{CODE}_{CUT}_review_producer.html', 'work/v1/review_page.html'], {}),
]
EXCLUDED = {
    'download/frames/ocr/transcript/vlm/llm/probe/selfcheck': 'Memex: кат, кадры и локальные модели (Apple Vision, Qwen) — '
                                                             'их выходы заморожены во входах песочницы',
    'cloud': 'облачный Workflow (агенты Claude) — audit_findings.json заморожен во входах',
    'align': 'у YTUVI02 нет align_against — стадия пустая',
    'risk / acts / verdict': 'нет sensitivity/structure_rules в профиле YTUVI; acts — Qwen3-8B, verdict — облачный агент',
    'polish': 's14_polish_local — Qwen3-8B (локальная модель)',
    'render (PNG)': 'chrome-headless → заменён шагом infographics_html (YTAI_RENDER_HTML_ONLY=1: HTML без chrome)',
    'previews': 's7/s12 --render: кадры hires и PIL-композиты (картинки не копируются в песочницу)',
    'drive': 's9_materials_drive + s12 --upload/--apply — Google Drive API',
    'verify / doc_qc': 'читают живой Google Doc / экспорт PDF — нет офлайн-режима',
}
WORK_SKIP_DIRS = True        # из work/v1 берём только *.json/*.jsonl верхнего уровня (кадры/превью не нужны шагам)


# ── охрана реального проекта ─────────────────────────────────────────────────
class RealGuard:
    def __init__(self):
        BASE.mkdir(parents=True, exist_ok=True)
        self.stamp = BASE / '_real_stamp'

    def __enter__(self):
        if not REAL.exists():
            raise SystemExit(f'нет {REAL} — подключи T7-Blue')
        self.stamp.write_text(str(time.time()))
        t = time.time() - 2
        os.utime(self.stamp, (t, t))
        return self

    # Что может записать сама цепочка эталона: файлы верхнего уровня 05_Review, work/v1/*, pravki/*, mockups/(src/)*.
    # Всё прочее (notes/ — внешний notes-цикл, logs/, подпапки work/v1 вроде kb_visuals/ — другие сессии) — предупреждение:
    # 15.09 чужая стадия kb_visuals писала work/v1/kb_visuals/verify.jsonl, и selftest ложно падал.
    WATCH = r'^/(?:[^/]+|work/v1/[^/]+|pravki/[^/]+|mockups/(?:src/)?[^/]+)$'

    def check(self, where):
        import re
        out = subprocess.run(['find', str(REAL), '-newer', str(self.stamp)], capture_output=True, text=True).stdout.splitlines()
        changed = [x for x in out if x and x != str(REAL) and not os.path.isdir(x)]
        bad = [x for x in changed if re.match(self.WATCH, x[len(str(REAL)):])]
        other = [x for x in changed if x not in bad]
        if other:
            print(f'  ⚠️ {where}: в реальном {REAL.name} писали вне файлов эталона (notes-цикл / другая сессия?): {other[:3]}')
        if bad:
            raise SystemExit(f'🛑 {where}: РЕАЛЬНЫЙ YTUVI02 05_Review изменился — {len(bad)} путей: {bad[:8]}')

    def __exit__(self, *exc):
        self.check('после прогона')
        return False


# ── входы ────────────────────────────────────────────────────────────────────
def freeze_inputs():
    """реальный 05_Review → _golden_in (только то, что читают шаги); карточка переписана на песочницу"""
    if GIN.exists():
        shutil.rmtree(GIN)
    GIN.mkdir(parents=True)
    card = json.loads((REAL / 'review_card.json').read_text(encoding='utf-8'))
    words = Path(card['words'])
    words = words if words.is_absolute() else REAL / words
    shutil.copy2(words, GIN / words.name)
    card['words'] = words.name
    tf = card.get('terms_file') or 'review_terms.json'
    if (REAL / tf).exists():
        shutil.copy2(REAL / tf, GIN / Path(tf).name)
        card['terms_file'] = Path(tf).name
    for k in ('review_dir',):
        card.pop(k, None)
    card['work_dir'] = 'work/v1'
    card['pravki_dir'] = 'pravki'
    card['mockups_dir'] = 'mockups'
    for p in ('src', 'render'):                                 # кат остаётся абсолютным (читается только ffprobe-ом при нужде)
        if card.get(p) and not Path(card[p]).is_absolute():
            card[p] = str((REAL / card[p]).resolve())
    (GIN / 'review_card.json').write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding='utf-8')
    if (REAL / 'review_state.json').exists():
        shutil.copy2(REAL / 'review_state.json', GIN / 'review_state.json')
    (GIN / 'pravki').mkdir()
    for f in sorted((REAL / 'pravki').glob('*.json')):
        shutil.copy2(f, GIN / 'pravki' / f.name)
    (GIN / 'work/v1').mkdir(parents=True)
    for f in sorted((REAL / 'work/v1').iterdir()):
        if f.is_file() and f.suffix in ('.json', '.jsonl'):
            shutil.copy2(f, GIN / 'work/v1' / f.name)
    (GIN / 'mockups').mkdir()
    for f in sorted((REAL / 'mockups').glob('*.png')):
        shutil.copy2(f, GIN / 'mockups' / f.name)
    return {str(p.relative_to(GIN)): sha(p.read_bytes()) for p in sorted(GIN.rglob('*')) if p.is_file() and p.suffix != '.png'}


def fresh_sandbox():
    if SB.exists():
        shutil.rmtree(SB)
    SB.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(GIN, SB)
    (BASE / '_ctl').mkdir(parents=True, exist_ok=True)


def env_for(extra):
    e = {k: v for k, v in os.environ.items() if not k.startswith('YTAI_') and k not in ('TZ_TAB',)}
    card = json.loads((SB / 'review_card.json').read_text(encoding='utf-8'))
    e.update({'YTAI_CARD': str(SB / 'review_card.json'), 'YTAI_CTL_DIR': str(BASE / '_ctl'),
              'PATH': '/opt/homebrew/bin:/usr/local/bin:' + e.get('PATH', ''), 'PYTHONUNBUFFERED': '1',
              'PYTHONHASHSEED': '0', 'HF_HOME': str(YTAI / 'models' / 'huggingface')})
    if card.get('tab_title'):
        e['TZ_TAB'] = str(card['tab_title'])                     # как review.py env(): имя вкладки из карточки
    e.update(extra)
    return e


# ── нормализация ─────────────────────────────────────────────────────────────
TS_RE = re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?'
                   r'|\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}')          # «собрано 15.09.2026 17:54» (phone_brief/producer_page)
MS_RE = re.compile(r'\bin \d+ ms\b')                              # mockbuild_v6.js: «placed=212 skipped=0 in 99 ms»


def sha(b):
    return hashlib.sha1(b).hexdigest()


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in ('created',)}
    if isinstance(o, list):
        return [_strip(x) for x in o]
    return o


def norm_text(t):
    for src, ph in ((str(SB), '<SB>'), (str(GIN), '<GIN>'), (str(REAL), '<REAL>'), (str(BASE), '<BASE>'),
                    (str(STAGE), '<STAGE>'), (str(Path.home()), '<HOME>')):
        t = t.replace(src, ph)
    return MS_RE.sub('in <N> ms', TS_RE.sub('<TS>', t))


def norm_file(path):
    raw = Path(path).read_bytes()
    try:
        txt = raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw
    if path.suffix == '.json':
        try:
            txt = json.dumps(_strip(json.loads(txt)), ensure_ascii=False, indent=1)
        except json.JSONDecodeError:
            pass
    return norm_text(txt).encode('utf-8')


def expand(outs, root):
    files = []
    for o in outs:
        if '*' in o:
            files += sorted(str(p.relative_to(root)) for p in root.glob(o) if p.is_file())
        elif (root / o).exists():
            files.append(o)
    return files


# ── шаг ──────────────────────────────────────────────────────────────────────
def run_step(step, capture_dir):
    name, argv, outs, extra = step
    for o in outs:                                  # чистим выходы-глобы, чтобы старые копии не маскировали отсутствие записи
        if '*' in o:
            for p in SB.glob(o):
                p.unlink()
    t0 = time.time()
    r = subprocess.run([str(a) for a in argv()], cwd=str(SB), env=env_for(extra), capture_output=True, text=True,
                       timeout=1800)
    dt = time.time() - t0
    if capture_dir.exists():
        shutil.rmtree(capture_dir)
    capture_dir.mkdir(parents=True)
    got = expand(outs, SB)
    for rel in got:
        (capture_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SB / rel, capture_dir / rel)
    (capture_dir / '_stdout.txt').write_text(r.stdout + ('\n[stderr]\n' + r.stderr if r.stderr.strip() else ''), encoding='utf-8')
    (capture_dir / '_rc.txt').write_text(str(r.returncode))
    print(f'  {name}: rc={r.returncode} · {dt:.1f} с · выходов {len(got)}', flush=True)
    if r.returncode != 0:
        print('    ' + '\n    '.join((r.stdout + r.stderr).strip().splitlines()[-8:]))
    return r.returncode


def hashes(capture_dir):
    return {str(p.relative_to(capture_dir)): sha(norm_file(p))
            for p in sorted(capture_dir.rglob('*')) if p.is_file()}


def overlay(step_names):
    """эталонные сырые выходы предыдущих шагов → песочница (как если бы шаги только что прошли)"""
    for n in step_names:
        d = GOUT / n
        for p in sorted(d.rglob('*')):
            if p.is_file() and not p.name.startswith('_'):
                dst = SB / p.relative_to(d)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst)


def diff_step(name, cap, gold):
    """→ число расходящихся файлов; печатает первые строки дифа"""
    g = json.loads(GJSON.read_text(encoding='utf-8'))
    want = next(s for s in g['steps'] if s['name'] == name)['outputs']
    have = hashes(cap)
    bad = 0
    for rel in sorted(set(want) | set(have)):
        if want.get(rel) == have.get(rel):
            continue
        bad += 1
        if rel not in have:
            print(f'    ✗ {rel}: выхода нет (в эталоне есть)')
            continue
        if rel not in want:
            print(f'    ✗ {rel}: лишний выход (в эталоне нет)')
            continue
        a = norm_file(gold / rel).decode('utf-8', 'replace').splitlines()
        b = norm_file(cap / rel).decode('utf-8', 'replace').splitlines()
        d = list(difflib.unified_diff(a, b, f'golden/{rel}', f'now/{rel}', n=1, lineterm=''))
        print(f'    ✗ {rel}: отличается ({len(d)} строк дифа), первые:')
        for ln in d[:24]:
            print('      ' + ln[:220])
    return bad


# ── команды ──────────────────────────────────────────────────────────────────
def cmd_snapshot():
    print(f'snapshot → {GJSON}\nвходы {REAL} → {GIN}')
    with RealGuard() as guard:
        inputs = freeze_inputs()
        fresh_sandbox()
        steps = []
        if GOUT.exists():
            shutil.rmtree(GOUT)
        for step in STEPS:
            rc = run_step(step, GOUT / step[0])
            guard.check(step[0])
            steps.append({'name': step[0], 'rc': rc, 'outputs': hashes(GOUT / step[0]),
                          'cmd': ' '.join(norm_text(str(a)) for a in step[1]()), 'env': step[3]})
    GJSON.parent.mkdir(parents=True, exist_ok=True)
    GJSON.write_text(json.dumps({'schema': 'review-golden-v1', 'project': CODE, 'real': str(REAL), 'sandbox': str(SB),
                                 'taken': datetime.now().isoformat(timespec='seconds'), 'code_version': _git(),
                                 'inputs': inputs, 'steps': steps, 'excluded': EXCLUDED},
                                ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'эталон: {len(steps)} шагов, выходов {sum(len(s["outputs"]) for s in steps)} → {GJSON}')
    return 0


def _git():
    try:
        return subprocess.run(['git', '-C', str(STAGE), 'rev-parse', '--short', 'HEAD'], capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:
        return ''


def cmd_compare(only=None):
    if not GJSON.exists() or not GIN.exists():
        raise SystemExit('эталона нет — сначала golden.py snapshot')
    names = [s[0] for s in STEPS]
    if only and only not in names:
        raise SystemExit(f'нет шага «{only}»; есть: {", ".join(names)}')
    g = json.loads(GJSON.read_text(encoding='utf-8'))
    drift = {k for k, v in g.get('inputs', {}).items() if not (GIN / k).exists() or sha((GIN / k).read_bytes()) != v}
    if drift:
        raise SystemExit(f'входы _golden_in изменились после snapshot: {sorted(drift)[:5]} — пересними snapshot')
    total_bad = 0
    with RealGuard() as guard:
        fresh_sandbox()
        sel = [only] if only else names
        if only:
            overlay(names[:names.index(only)])
        for step in STEPS:
            if step[0] not in sel:
                continue
            cap = BASE / '_compare' / step[0]
            run_step(step, cap)
            guard.check(step[0])
            bad = diff_step(step[0], cap, GOUT / step[0])
            total_bad += bad
            print(f'  {"✅" if not bad else "✗ "} {step[0]}: ' + ('идентично' if not bad else f'расходится файлов: {bad}'))
    print('ИТОГ golden:', 'идентично' if not total_bad else f'РАСХОЖДЕНИЯ ({total_bad})')
    return 0 if not total_bad else 1


def cmd_rehash():
    """пересчитать хэши эталона по сохранённым сырым выходам (после правки нормализации), без прогона шагов"""
    g = json.loads(GJSON.read_text(encoding='utf-8'))
    for s in g['steps']:
        s['outputs'] = hashes(GOUT / s['name'])
    g['rehashed'] = datetime.now().isoformat(timespec='seconds')
    GJSON.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'хэши пересчитаны: {len(g["steps"])} шагов → {GJSON}')
    return 0


def cmd_list():
    for name, argv, outs, extra in STEPS:
        print(f'{name:18s} {", ".join(outs) or "(stdout)"}' + (f'  env {extra}' if extra else ''))
    print('\nисключены:')
    for k, v in EXCLUDED.items():
        print(f'  {k}: {v}')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sp = ap.add_subparsers(dest='cmd', required=True)
    sp.add_parser('snapshot')
    c = sp.add_parser('compare')
    c.add_argument('--only')
    sp.add_parser('list')
    sp.add_parser('rehash')
    a = ap.parse_args()
    if a.cmd == 'snapshot':
        return cmd_snapshot()
    if a.cmd == 'rehash':
        return cmd_rehash()
    if a.cmd == 'compare':
        return cmd_compare(a.only)
    return cmd_list()


if __name__ == '__main__':
    sys.exit(main())
