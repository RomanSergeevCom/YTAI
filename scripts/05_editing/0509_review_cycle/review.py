#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""review.py — единый CLI стадии «Ревью ката + ТЗ на монтаж» (0509_review_cycle).

Стейт-машина по образцу 999_extra/ytch_chain/chain.py: стадии идемпотентны, у каждой
гейт по артефактам на диске, состояние — атомарный review_state.json в 05_Review проекта,
перезапуск продолжает с первой незакрытой стадии. Скрипты живут в репо, данные — в проекте.

    review.py init    --project <path|CODE> --channel YTUVI --mode cut_review|montage_tz [--cut <mp4|gdrive:…>] [--from-prep-config <json>]
    review.py status  --project P
    review.py run     --project P [--from S] [--until S] [--only S] [--force] [--dry-run] [--host mac|memex] [--tg] [--no-drive] [--no-doc]
    review.py resume  --project P                     # = run без флагов
    review.py stage   --project P <name> start|pause|resume|stop|status
    review.py cloud   --project P judge --print-call  # печатает Workflow({...}) для сессии
    review.py cloud   --project P collect [--run <runId>] | salvage [--session <id>|--latest] | cost
    review.py edits   --project P                     # правки Романа из дока → pravki (гейт перед регенерацией)
    review.py ticket  --project P                     # REVIEW_STATE.md для новой сессии
    review.py memex   --project P push|pull|start|status|pause|resume|stop
    review.py card    --project P check
    review.py docs                                    # таблица стадий → README.md (+ KB 6.2) между маркерами

Режимы: cut_review (кат монтажёра → ревью + ТЗ) и montage_tz (исходники → монтажный лист).
Хосты: Memex — «глаза» (download…probe, локальные модели), Mac — «руки» (route…phone_brief).
Контракты — docs/contracts.md. Человеческий ранбук — KB 6.2 /kb/review-cycle/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGES_DIR = ROOT / 'stages'
CLOUD_DIR = ROOT / 'cloud'
SHARED = ROOT / 'shared'
MONTAGE = ROOT / 'montage'
MEMEX = ROOT / 'memex'
YTAI = ROOT.parent.parent.parent
EXTRA = YTAI / 'scripts' / '999_extra'
ENV = YTAI / 'environment'
PY = sys.executable if sys.executable else 'python3'
PY_VLM = str(ENV / '.venv_vlm/bin/python')
PY_LLM = str(ENV / '.venv_llm/bin/python')
PY_TR = str(ENV / '.venv_transcribe/bin/python')
NODE = '/opt/homebrew/bin/node' if Path('/opt/homebrew/bin/node').exists() else 'node'
FFMPEG = '/opt/homebrew/bin/ffmpeg' if Path('/opt/homebrew/bin/ffmpeg').exists() else 'ffmpeg'
RCLONE = '/opt/homebrew/bin/rclone' if Path('/opt/homebrew/bin/rclone').exists() else 'rclone'
TG_CHAT = '155880671'
MAX_ATTEMPTS = 3
CODE_RE = re.compile(r'^(YT[A-Z]{2,4}\d+)_')
STATE_SCHEMA = 'review-state-v1'


def now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ══════════════════════════════════════════════════════════════════════════════
# 0. Проект, карточка, состояние
# ══════════════════════════════════════════════════════════════════════════════

def resolve_project(spec: str) -> Path:
    """Корень проекта по пути (корень / 05_Review / карточка) или по коду (поиск по томам)."""
    p = Path(spec).expanduser()
    if p.is_file() and p.name.endswith('.json'):
        return p.parent.parent.parent
    if p.is_dir():
        if (p / '00_Setup').is_dir():
            return p
        if p.name == '05_Review':
            return p.parent.parent
    name = p.name
    m = CODE_RE.match(name) or re.match(r'^(YT[A-Z]{2,4}\d+)$', name)
    if m:
        code = m.group(1)
        for base in [Path.home() / 'YTAI_work', *sorted(Path('/Volumes').glob('*'))]:
            for cand in sorted(base.glob(f'*/{code}_*')) + sorted(base.glob(f'{code}_*')) + sorted(base.glob(f'*/*/{code}_*')):
                if (cand / '00_Setup').is_dir():
                    return cand
    raise SystemExit(f'проект не найден: {spec} (путь к папке с 00_Setup или код YTXX00)')


class Review:
    def __init__(self, root: Path, dry: bool = False, tg_on: bool = False):
        self.root = root
        self.dry = dry
        self.tg_on = tg_on
        self.review_dir = root / '00_Setup' / '05_Review'
        self.card_path = self.review_dir / 'review_card.json'
        self.card = json.loads(self.card_path.read_text(encoding='utf-8')) if self.card_path.exists() else {}
        self.code = self.card.get('code') or (CODE_RE.match(root.name).group(1) if CODE_RE.match(root.name) else root.name)
        self.mode = self.card.get('mode', 'cut_review')
        self.cut = self.card.get('cut_version', 'v1')
        self.project = self.card.get('project', self.code.lower())
        self.work = self.review_dir / 'work' / self.cut
        self.pravki = self.review_dir / 'pravki'
        self.cloud = self.review_dir / 'cloud'
        self.logs = self.review_dir / 'logs'
        self.ctl = Path(os.path.expanduser(self.card.get('ctl_dir', f'~/.cache/{self.project}')))
        for d in (self.work, self.pravki, self.cloud, self.logs, self.ctl):
            d.mkdir(parents=True, exist_ok=True)
        self.state_f = self.review_dir / 'review_state.json'
        self.pidf = self.ctl / 'review.pid'
        self.hb = self.ctl / 'heartbeat.txt'
        self.pause_f = self.ctl / 'PAUSE'
        self.stop_f = self.ctl / 'STOP'
        self.host = 'mac'                 # cmd_run подставляет --host / автономный режим / --images
        self.autonomous = False
        self.images = 'none'
        self.S = self.load()

    # ── env для дочерних процессов ────────────────────────────────────────────
    def env(self) -> dict:
        e = dict(os.environ)
        e['YTAI_CARD'] = str(self.card_path)
        e['YTAI_CTL_DIR'] = str(self.ctl)
        e.setdefault('HF_HOME', str(YTAI / 'models' / 'huggingface'))
        e['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + e.get('PATH', '')
        e['PYTHONUNBUFFERED'] = '1'
        e['YTAI_HOST'] = self.host        # стадии с кадрами наружу (doc_feedback) сами решают по хосту и режиму
        if self.autonomous:
            e['YTAI_AUTONOMOUS'] = '1'
        # имя вкладки ТЗ — из карточки (doc_tab_tz_v4 иначе подставляет «· v4» первого фильма через setdefault)
        tab = os.environ.get('YTAI_TAB_TITLE') or self.card.get('tab_title')
        if tab and not os.environ.get('TZ_TAB'):
            e['TZ_TAB'] = str(tab)
        return e

    def tab_title(self) -> str:
        return os.environ.get('TZ_TAB') or os.environ.get('YTAI_TAB_TITLE') or str(self.card.get('tab_title') or '')

    # ── состояние ─────────────────────────────────────────────────────────────
    def load(self) -> dict:
        if self.state_f.exists():
            try:
                return json.loads(self.state_f.read_text(encoding='utf-8'))
            except json.JSONDecodeError:
                pass
        return {'schema': STATE_SCHEMA, 'code': self.code, 'cut_version': self.cut, 'mode': self.mode,
                'host_policy': {'prep': 'memex', 'surfaces': 'mac'}, 'created': now(),
                'stages': {}, 'cloud': {'run_ids': [], 'batches': {}, 'unverified': 0},
                'pravki': {}, 'surfaces': {}, 'edits': {}, 'notes': [], 'updated': now()}

    def save(self):
        self.S['updated'] = now()
        if self.dry:                      # dry-run ничего не пишет на диск
            return
        tmp = self.state_f.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(self.S, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(tmp, self.state_f)

    def st(self, name: str) -> dict:
        return self.S['stages'].setdefault(name, {'status': 'todo'})

    def note(self, msg: str):
        self.S['notes'] = (self.S.get('notes') or [])[-40:] + [f'{now()[-8:]} {msg}']
        self.log('   ' + msg)

    def log(self, msg: str):
        line = f'[{now()}] {msg}'
        print(line, flush=True)
        if self.dry:                      # dry-run ничего не пишет на диск — в том числе в лог проекта
            return
        with open(self.logs / 'review.log', 'a', encoding='utf-8') as fh:
            fh.write(line + '\n')

    def beat(self):
        try:
            self.hb.write_text(str(int(time.time())))
        except OSError:
            pass

    def checkpoint(self, stage: str):
        if self.stop_f.exists():
            raise Stopped(stage)
        if self.pause_f.exists():
            self.log(f'⏸ {stage}: пауза по флагу {self.pause_f}')
            while self.pause_f.exists():
                if self.stop_f.exists():
                    raise Stopped(stage)
                self.beat()
                time.sleep(5)
            self.log(f'▶️ {stage}: продолжаю')
        self.beat()

    # ── Telegram: только вехи, никогда не фатален ──────────────────────────────
    def tg(self, text: str):
        if not self.tg_on or self.dry:
            return
        token = ''
        for src in (Path.home() / '.config/rscore-tg/rya.token', Path.home() / '.claude/channels/telegram-rya/.env'):
            try:
                raw = src.read_text().strip()
                if src.suffix == '.env':
                    for ln in raw.splitlines():
                        if ln.startswith('TELEGRAM_BOT_TOKEN='):
                            raw = ln.split('=', 1)[1].strip().strip('\'"')
                if raw:
                    token = raw
                    break
            except OSError:
                continue
        if not token:
            return
        data = urllib.parse.urlencode({'chat_id': TG_CHAT, 'text': text, 'parse_mode': 'HTML',
                                       'disable_web_page_preview': 'true'}).encode()
        for attempt in range(3):
            try:
                urllib.request.urlopen(f'https://api.telegram.org/bot{token}/sendMessage', data=data, timeout=30).read()
                return
            except Exception:
                time.sleep(5 * (attempt + 1))

    # ── запуск подпроцесса с логом и heartbeat ────────────────────────────────
    def run_cmd(self, argv: list, stage: str, timeout_min: int = 240, cwd: Path | None = None) -> tuple[int, str]:
        argv = [str(a) for a in argv]
        logf = self.logs / f'{stage}.log'
        if self.dry:
            self.log(f'[dry] {stage}: ' + ' '.join(argv))
            return 0, ''
        buf: list[str] = []
        with open(logf, 'a', encoding='utf-8') as lf:
            lf.write(f'\n##### {now()} {" ".join(argv)}\n')
            t0 = time.time()
            p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 env=self.env(), cwd=str(cwd or self.review_dir), start_new_session=True)
            try:
                for line in p.stdout:
                    lf.write(line)
                    buf.append(line)
                    self.beat()
                    if self.stop_f.exists():
                        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                        raise Stopped(stage)
                    if time.time() - t0 > timeout_min * 60:
                        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                        return 124, ''.join(buf[-200:]) + '\nTIMEOUT'
            except KeyboardInterrupt:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                raise
            p.wait()
        return p.returncode, ''.join(buf[-200:])

    # ── карточка → значения ───────────────────────────────────────────────────
    def cpath(self, key: str, default: str = '') -> Path | None:
        v = self.card.get(key) or default
        if not v:
            return None
        p = Path(str(v)).expanduser()
        return p if p.is_absolute() else (self.review_dir / p)

    def src(self) -> Path | None:
        return self.cpath('src')

    def words(self) -> Path | None:
        return self.cpath('words', f'{self.code}_{self.cut}.words.json')

    def expect_frames(self) -> int:
        d = self.card.get('duration_sec')
        if d:
            return int(float(d))
        s = self.src()
        if s and s.exists():
            out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(s)],
                                 capture_output=True, text=True).stdout.strip()
            return int(float(out or 0))
        return 0

    def inputs_hash(self) -> str:
        h = hashlib.sha1()
        s = self.src()
        if s and s.exists():
            stt = s.stat()
            h.update(f'{stt.st_size}:{int(stt.st_mtime)}'.encode())
        core = {k: v for k, v in self.card.items() if k not in ('doc_id', 'materials_id', 'project_folder_id', 'sprint_folder_id',
                                                              'sheet_url', 'notes_sheet_id', 'notes', 'tab_title', 'nav_tab')}
        h.update(json.dumps(core, sort_keys=True, ensure_ascii=False).encode())
        h.update(version().encode())
        return h.hexdigest()[:12]

    def profile(self) -> dict:
        ch = str(self.card.get('channel', '')).upper()
        p = YTAI / 'YTs' / ch / 'review_profile.json'
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}

    def lang(self) -> str:
        """язык поверхностей — как proj_config.LANG: YTAI_LANG → карточка lang → профиль lang → ru"""
        v = os.environ.get('YTAI_LANG') or self.card.get('lang') or self.profile().get('lang') or 'ru'
        return 'en' if str(v).strip().lower() == 'en' else 'ru'

    def verdict_cfg(self) -> dict:
        v = self.profile().get('verdict')
        return v if isinstance(v, dict) else {}

    def verdict_on(self) -> bool:
        """вердикт/акты нужны: структурные правила канала (YTCH) ИЛИ редакторский вердикт профиля (verdict.enabled, YTCR)"""
        return bool(self.profile().get('structure_rules')) or bool(self.verdict_cfg().get('enabled'))


class Fatal(Exception):
    """Гейт закрыт намертво — дальше вести нельзя."""


class Stopped(Exception):
    """Роман нажал stop."""


class AwaitCloud(Exception):
    """Стадия ждёт облачный прогон из сессии Claude."""


class Warn(Exception):
    """Стадия не выполнена по понятной причине: сразу warn со своим текстом (без повторов), цепочка идёт дальше."""


def version() -> str:
    """В репо — git sha (истина); на Memex (rsync-копия без .git) — файл VERSION, записанный push.sh."""
    try:
        sha = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, timeout=5).stdout.strip()
        if sha:
            return sha
    except Exception:
        pass
    vf = ROOT / 'VERSION'
    return vf.read_text().strip() if vf.exists() else 'dev'


# ══════════════════════════════════════════════════════════════════════════════
# 1. Стадии: работа + гейт по артефактам
# ══════════════════════════════════════════════════════════════════════════════

def _count(glob_dir: Path, pat: str) -> int:
    return len(list(glob_dir.glob(pat))) if glob_dir.exists() else 0


def _jsonl_lines(p: Path) -> int:
    if not p.exists():
        return 0
    with open(p, encoding='utf-8') as fh:
        return sum(1 for ln in fh if ln.strip())


def _screens(r: Review) -> int:
    p = r.work / 'screens_v6.json'
    if not p.exists():
        return 0
    try:
        return len(json.loads(p.read_text(encoding='utf-8')))
    except Exception:
        return 0


def selfcheck(r: Review, what: str) -> bool:
    rc, _ = r.run_cmd([PY, STAGES_DIR / 's5_selfcheck.py', what], f'selfcheck_{what}', 10)
    return rc == 0


# --- download ---------------------------------------------------------------
def st_download(r: Review):
    s = r.src()
    if s and s.exists() and s.stat().st_size > 0:
        return True, f'кат на месте: {s.name} ({s.stat().st_size // 2**20} МБ)'
    remote = r.card.get('cut_drive')
    if not remote:
        raise Fatal(f'ката нет ({s}) и cut_drive в карточке пуст — положи кат или укажи gdrive-путь')
    dst = s or (r.review_dir / 'cut' / Path(remote).name)
    if r.dry:                                  # dry-run: только показать команду, ничего не создавать
        r.run_cmd([RCLONE, 'copyto', remote, dst, '--progress', '--stats-one-line', '--stats', '30s'], 'download', 180)
        return True, f'[dry] скачал бы {Path(remote).name} → {dst}'
    dst.parent.mkdir(parents=True, exist_ok=True)
    rc, out = r.run_cmd([RCLONE, 'copyto', remote, dst, '--progress', '--stats-one-line', '--stats', '30s'], 'download', 180)
    if rc != 0:
        return False, f'rclone rc={rc}: {out[-300:]}'
    if not r.card.get('src'):
        r.card['src'] = str(dst.relative_to(r.review_dir)) if dst.is_relative_to(r.review_dir) else str(dst)
        r.card_path.write_text(json.dumps(r.card, ensure_ascii=False, indent=1), encoding='utf-8')
    return True, f'скачан {dst.name} ({dst.stat().st_size // 2**20} МБ)'


def v_download(r: Review) -> bool:
    s = r.src()
    return bool(s and s.exists() and s.stat().st_size > 0)


# --- frames -----------------------------------------------------------------
def st_frames(r: Review):
    s = r.src()
    if not s or not s.exists():
        raise Fatal('нет ката для кадров')
    hires = r.work / 'hires'
    need = r.expect_frames() - int(r.card.get('frames_tolerance', 2))
    have = _count(hires, 'h*.jpg')
    if have >= need:
        return True, f'кадры уже есть: {have}'
    if r.dry:                                  # dry-run не стирает недокачанные кадры
        return True, f'[dry] перегнал бы кадры: есть {have}, нужно ≥{need}'
    hires.mkdir(parents=True, exist_ok=True)
    for f in hires.glob('h*.jpg'):
        f.unlink()
    argv = [FFMPEG, '-hide_banner', '-v', 'error']
    if sys.platform == 'darwin':
        argv += ['-hwaccel', 'videotoolbox']
    argv += ['-i', str(s), '-vf', 'fps=1,scale=1920:-2', '-q:v', '2', str(hires / 'h%04d.jpg')]
    rc, out = r.run_cmd(argv, 'frames', 120)
    have = _count(hires, 'h*.jpg')
    return (rc == 0 and have >= need), f'кадров {have} (ожидали ≥{need})'


def v_frames(r: Review) -> bool:
    return _count(r.work / 'hires', 'h*.jpg') >= r.expect_frames() - int(r.card.get('frames_tolerance', 2)) > 0


# --- static (где кадр не меняется) ------------------------------------------
def st_static(r: Review):
    """Места «кадр не меняется» по кадрам 1 fps → вход вердикта (Роман, YTCR04 v5: долгий проезд в машине)."""
    rc, out = r.run_cmd([PY, STAGES_DIR / 'static_stretches.py'], 'static', 20)
    return rc == 0, (out.strip().splitlines()[-1][:120] if out.strip() else 'static_stretches.json')


def v_static(r: Review) -> bool:
    return (r.work / 'static_stretches.json').exists() or _count(r.work / 'hires', 'h*.jpg') == 0


# --- ocr / vlm / llm / probe / transcript ------------------------------------
def st_ocr(r: Review):
    rc, out = r.run_cmd([PY, STAGES_DIR / 's2_ocr_hires.py'], 'ocr', 60)
    return rc == 0 and selfcheck(r, 'ocr'), f'экранов {_screens(r)}'


def v_ocr(r: Review) -> bool:
    return _screens(r) > 0 and (r.work / 'ocr_hires.jsonl').exists()


def _src_stamp(s: Path) -> str:
    st = s.stat()
    return f'{st.st_size}:{int(st.st_mtime)}'


def _transcript_stale(r: Review, s: Path, base: str) -> list:
    """Кэш транскрайбера (_wordrole_work/{base}_*, {base}.* в 05_Review) от ДРУГОГО файла ката с тем же именем.
    17.09 YTCR04: новая версия ката под тем же именем v5 — wordrole отдал WAV/слова/диаризацию черновика за 1 с.
    Штамп источника (размер:mtime) пишется после транскрибации; нет штампа — устаревшим считаем кэш старше ката."""
    work = r.review_dir / '_wordrole_work'
    stamp_f = work / f'{base}.src_stamp'
    files = sorted(work.glob(f'{base}_*')) + sorted(r.review_dir.glob(f'{base}.*'))
    files = [f for f in files if f.is_file() and f != stamp_f]
    if not files:
        return []
    if stamp_f.exists():
        return [] if stamp_f.read_text().strip() == _src_stamp(s) else files
    src_mtime = s.stat().st_mtime
    return files if any(f.stat().st_mtime < src_mtime for f in files) else []


def st_transcript(r: Review):
    s = r.src()
    w = r.words()
    base = w.name.replace('.words.json', '') if w else f'{r.code}_{r.cut}'
    if s and s.exists() and not r.dry:
        stale = _transcript_stale(r, s, base)
        if stale:
            dst = r.review_dir / '_wordrole_work' / f'_stale_{datetime.now().strftime("%Y%m%d-%H%M%S")}'
            dst.mkdir(parents=True, exist_ok=True)
            for f in stale:
                shutil.move(str(f), str(dst / f.name))
            r.note(f'transcript: кэш от другого файла ката ({len(stale)} файлов) перенесён в {dst.name} — транскрибирую заново')
    if w and w.exists():
        return True, f'транскрипт на месте: {w.name}'
    if not s or not s.exists():
        raise Fatal('нет ката для транскрибации')
    argv = [PY_TR, EXTRA / 'wordrole_transcribe.py', '--media', s, '--plain', '--out-dir', r.review_dir, '--base', base]
    # язык озвучки: card.language → card.lang → profile.lang; «auto» не передаём никогда (whisper путает языки),
    # ключей нет — флага нет (RU-проекты без ключа ведут себя как раньше)
    lang = next((str(v) for v in (r.card.get('language'), r.card.get('lang'), r.profile().get('lang'))
                 if v and str(v).strip().lower() != 'auto'), None)
    if lang:
        argv += ['--language', lang]
    rc, out = r.run_cmd(argv, 'transcript', 180)
    if rc == 0 and w.exists() and not r.dry:
        (r.review_dir / '_wordrole_work').mkdir(exist_ok=True)
        (r.review_dir / '_wordrole_work' / f'{base}.src_stamp').write_text(_src_stamp(s))
    return (rc == 0 and w.exists()), f'{w.name} ({"есть" if w.exists() else "нет"})'


def v_transcript(r: Review) -> bool:
    w = r.words()
    return bool(w and w.exists() and w.stat().st_size > 1000)


def st_vlm(r: Review):
    rc, out = r.run_cmd([PY_VLM, STAGES_DIR / 's3_vlm.py'], 'vlm', 400)
    return rc == 0 and selfcheck(r, 'vlm'), f'vlm строк {_jsonl_lines(r.work / "vlm_v6.jsonl")}/{_screens(r)}'


def v_vlm(r: Review) -> bool:
    n = _screens(r)
    return n > 0 and _jsonl_lines(r.work / 'vlm_v6.jsonl') >= n


def st_llm(r: Review):
    rc, out = r.run_cmd([PY_LLM, STAGES_DIR / 's4_llm.py'], 'llm', 300)
    return rc == 0 and selfcheck(r, 'llm'), 'llm_v6.json готов'


def v_llm(r: Review) -> bool:
    p = r.work / 'llm_v6.json'
    return p.exists() and p.stat().st_size > 100


def st_probe(r: Review):
    script = STAGES_DIR / 's3b_probe_vlm.py'
    if not script.exists():
        return True, 'probe: скрипта ещё нет — пропуск (мягкий гейт)'
    rc, out = r.run_cmd([PY_VLM, script], 'probe', 400)
    return rc == 0, f'probes {_jsonl_lines(r.work / "probes.jsonl")}/{_screens(r)}'


def v_probe(r: Review) -> bool:
    n = _screens(r)
    return n > 0 and _jsonl_lines(r.work / 'probes.jsonl') >= n


def st_selfcheck(r: Review):
    ok = selfcheck(r, 'all')
    return ok, 'селфчек ALL OK' if ok else 'селфчек не прошёл — см. prep_check_all.json'


def v_selfcheck(r: Review) -> bool:
    p = r.work / 'prep_check_all.json'
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        return not d.get('bad')
    except Exception:
        return False


# --- route / cloud / apply --------------------------------------------------
def st_route(r: Review):
    script = STAGES_DIR / 'route_candidates.py'
    if not script.exists():
        raise Fatal('нет stages/route_candidates.py')
    rc, out = r.run_cmd([PY_LLM if Path(PY_LLM).exists() else PY, script], 'route', 30)
    return rc == 0, out.strip().splitlines()[-1][:120] if out.strip() else 'candidates.json'


def v_route(r: Review) -> bool:
    return (r.work / 'candidates.json').exists()


def cloud_state(r: Review) -> dict:
    p = r.cloud / 'state.json'
    try:
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
    except Exception:
        return {}


def pending_batches(r: Review) -> list:
    return [k for k, v in (cloud_state(r).get('batches') or {}).items() if v.get('status') != 'done']


def st_cloud(r: Review):
    """Составная стадия: pack → (ждём воркфлоу) → collect → facts/crops/skeptic → (ждём) → collect."""
    pack = CLOUD_DIR / 'pack.py'
    collect = CLOUD_DIR / 'collect.py'
    if not pack.exists() or not collect.exists():
        raise Fatal('нет cloud/pack.py или cloud/collect.py')
    # 1) собрать всё, что уже вернулось
    if (r.cloud / 'out').exists() and any((r.cloud / 'out').glob('*.json')):
        rc, out = r.run_cmd([PY, collect], 'cloud_collect', 20)
        if rc not in (0, 3):
            return False, f'collect rc={rc}: {out[-200:]}'
    # 2) пакеты J (идемпотентно) и, если J готовы, — F/V/S
    rc, out = r.run_cmd([PY, pack], 'cloud_pack', 20)
    if rc != 0:
        return False, f'pack rc={rc}: {out[-200:]}'
    cs = cloud_state(r)
    batches = cs.get('batches') or {}
    j_all_done = batches and all(v.get('status') == 'done' for k, v in batches.items() if v.get('kind', k[:1]) == 'J')
    if j_all_done and not any(v.get('kind', k[:1]) in ('F', 'V', 'S') for k, v in batches.items()):
        rc, out = r.run_cmd([PY, pack, '--facts', '--crops', '--skeptic'], 'cloud_pack2', 20)
    pend = pending_batches(r)
    r.S['cloud']['batches'] = cloud_state(r).get('batches', {})
    if pend:
        rc, call = r.run_cmd([PY, pack, '--print-call'], 'cloud_call', 5)
        if not r.dry:
            (r.cloud / 'CALL.txt').write_text(call, encoding='utf-8')
        r.S['cloud']['awaiting'] = pend
        r.save()
        raise AwaitCloud(f'{len(pend)} пакетов ждут воркфлоу — вызов в {r.cloud / "CALL.txt"}: review.py cloud judge --print-call')
    rc, out = r.run_cmd([PY, collect], 'cloud_collect', 20)
    if rc != 0:
        return False, f'collect rc={rc}: {out[-200:]}'
    # легаси-потребители (s10, review_page, doc_tab_review_v1) читают audit_findings_v6.json
    r.run_cmd([PY, collect, '--emit-legacy'], 'cloud_collect_legacy', 5)
    return True, 'облачный проход собран: audit_findings.json (+ legacy v6)'


def _cloud_compound(r: Review, script: Path, stage: str, out_name: str, apply_args: list, call_args: list | None = None):
    """Общий шаблон для одноагентных облачных стадий (вердикт YTCH, структура YTEVO):
    нет результата → печатаем вызов и ждём сессию; есть → применяем."""
    if not script.exists():
        return True, f'{script.name}: скрипта ещё нет — пропуск'
    out = r.cloud / 'out' / out_name
    if not out.exists():
        rc, call = r.run_cmd([PY, script, *(call_args or ['--print-call'])], f'{stage}_call', 5)
        if not r.dry:
            (r.cloud / f'CALL_{stage}.txt').write_text(call, encoding='utf-8')
        raise AwaitCloud(f'нет {out.name} — выполни вызов из {r.cloud / f"CALL_{stage}.txt"}')
    rc, res = r.run_cmd([PY, script, *apply_args], f'{stage}_apply', 10)
    return rc == 0, (res.strip().splitlines()[-1][:120] if res.strip() else f'{out_name} применён')


def st_verdict(r: Review):
    if not r.verdict_on():
        # без ключа verdict в профиле (YTUVI/YTCH/YTEVO) — прежний литерал: его показывает страница продюсера
        return True, ('вердикт-агент не нужен (нет structure_rules в профиле)' if 'verdict' not in r.profile()
                      else 'вердикт-агент не нужен (нет structure_rules / verdict.enabled в профиле)')
    # profile verdict.want_tobe — вторым агентом целевая структура и перестановки материала (YTCR: «не хватает структуры»)
    call = ['--print-call'] + (['--want-tobe'] if r.verdict_cfg().get('want_tobe') else [])
    return _cloud_compound(r, SHARED / 'verdict_call.py', 'verdict', 'verdict.json', ['--apply'], call)


def v_verdict(r: Review) -> bool:
    return not r.verdict_on() or (r.cloud / 'out' / 'verdict.json').exists()


def st_acts(r: Review):
    if not r.verdict_on():
        return True, ('acts_compact не нужен (нет structure_rules)' if 'verdict' not in r.profile()
                      else 'acts_compact не нужен (нет structure_rules / verdict.enabled)')
    script = SHARED / 'acts_compact.py'
    if not script.exists():
        return True, 'acts_compact.py нет — пропуск'
    if not r.profile().get('structure_rules'):
        # редакторский вердикт (profile verdict.enabled, YTCR): акты экстрактивно, без Qwen — на Mac, секунды
        rc, out = r.run_cmd([PY, script, '--no-llm'], 'acts', 20)
        return rc == 0, 'acts_compact.json (--no-llm, редакторский вердикт) + structure_checks.json'
    rc, out = r.run_cmd([PY_LLM, script], 'acts', 120)
    return rc == 0, 'acts_compact.json + structure_checks.json'


def v_acts(r: Review) -> bool:
    return not r.verdict_on() or (r.work / 'acts_compact.json').exists()


def st_align(r: Review):
    targets = r.card.get('align_against') or []
    if not targets:
        return True, 'align: в карточке нет align_against — пропуск'
    argv = [PY, SHARED / 'align.py', '--against', *[str(r.cpath(t) or t) for t in targets]] if False else \
        [PY, SHARED / 'align.py', '--against', *[str(Path(t) if Path(t).is_absolute() else r.review_dir / t) for t in targets]]
    rc, out = r.run_cmd(argv, 'align', 30)
    return rc == 0, 'align.json'


def v_align(r: Review) -> bool:
    return not r.card.get('align_against') or (r.work / 'align.json').exists()


def rebuild_screen_chapters(r: Review) -> int:
    """главы в карточке поменялись → поле chapter у экранов screens_v6.json и находок audit_findings.json
    по тем же правилам, что proj_config.chapter (int-секунда начала, порядок карточки). OCR не перегоняется:
    s2_ocr_hires ставит главу при сборке инвентаря, а пересборка на Mac могла бы догнать OCR недостающих кадров.
    → сколько записей перепомечено."""
    bounds = [(int(float(t)), str(n)) for t, n in (r.card.get('chapters') or [[0, '01']])]

    def chap(sec):
        c = bounds[0][1] if bounds else '01'
        for t, n in bounds:
            if sec >= t:
                c = n
        return c

    changed, by_sid = 0, {}
    for name, key in (('screens_v6.json', None), ('audit_findings.json', 'findings')):
        p = r.work / name
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        rows = d.get(key) if key and isinstance(d, dict) else d
        n = 0
        for e in rows if isinstance(rows, list) else []:
            if not isinstance(e, dict) or 'chapter' not in e:
                continue
            if key is None and e.get('t0') is not None:
                c = chap(float(e['t0']))
                by_sid[e.get('id')] = c
            elif e.get('screen_id') in by_sid:
                c = by_sid[e['screen_id']]
            elif e.get('t0') is not None:
                c = chap(float(e['t0']))
            else:
                continue
            if e['chapter'] != c:
                e['chapter'] = c
                n += 1
        if n:
            tmp = p.with_suffix('.json.tmp')
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
            os.replace(tmp, p)
        changed += n
    return changed


def st_chapters(r: Review):
    """главы ката по плану частей (card.chapters_plan): chapters_from_plan --apply через align.json с прошлым рендером.
    После смены глав стадии terms → … → review_json идут дальше по порядку сами; если главы переставлены позже
    (план поправлен) — `run --only chapters`, затем `run --from terms`."""
    if not r.card.get('chapters_plan'):
        return True, 'chapters: в карточке нет chapters_plan — пропуск'
    script = SHARED / 'chapters_from_plan.py'
    if not script.exists():
        return True, 'chapters_from_plan.py нет — пропуск'
    if not (r.work / 'align.json').exists() and not r.dry:
        return True, 'chapters: нет align.json (стадия align / card.align_against) — пропуск, главы карточки не тронуты'
    rc, out = r.run_cmd([PY, script, '--apply'], 'chapters', 10)
    if r.dry:
        return True, '[dry] chapters_from_plan --apply'
    head = out.strip().splitlines()[0][:110] if out.strip() else 'chapters_proposal.json'
    if rc == 2:
        msg = '⛔ инверсия порядка глав: карточка не тронута — chapters_proposal.json, решает Роман'
        r.note(msg)
        r.tg(f'⛔ <b>{r.code}</b>: {msg}')
        return True, msg
    if rc != 0:
        return False, f'chapters_from_plan rc={rc}: {out[-200:]}'
    r.card = json.loads(r.card_path.read_text(encoding='utf-8'))
    n = rebuild_screen_chapters(r)
    return True, f'{head} · chapter перепомечен у {n} записей'


def v_chapters(r: Review) -> bool:
    return (not r.card.get('chapters_plan') or (r.work / 'chapters_proposal.json').exists()
            or not (r.work / 'align.json').exists())


def st_mt_structure(r: Review):
    return _cloud_compound(r, MONTAGE / 'structure_call.py', 'structure', 'structure.json', ['--apply'])


def v_mt_structure(r: Review) -> bool:
    return (r.cloud / 'out' / 'structure.json').exists()


def st_mt_design(r: Review):
    return _cloud_compound(r, MONTAGE / 'structure_call.py', 'design_review', 'design_review.json',
                           ['--apply-design'], ['--contact-sheet', '--print-call'])


def v_mt_design(r: Review) -> bool:
    return (r.cloud / 'out' / 'design_review.json').exists()


def v_cloud(r: Review) -> bool:
    p = r.work / 'audit_findings.json'
    return p.exists() and not pending_batches(r) and bool(cloud_state(r).get('batches'))


def st_apply(r: Review):
    rc, out = r.run_cmd([PY, STAGES_DIR / 's8_apply_audit.py'], 'apply', 20)
    return rc == 0, out.strip().splitlines()[-1][:120] if out.strip() else 'pravki обновлены'


def v_apply(r: Review) -> bool:
    return (r.work / 'audit_v6.json').exists() and (r.pravki / 'pravki_v2.json').exists()


def st_risk(r: Review):
    script = SHARED / 'risk_registry.py'
    if not script.exists() or not r.profile().get('sensitivity'):
        return True, 'риск-реестр не нужен (нет sensitivity в профиле)'
    rc, out = r.run_cmd([PY, script, '--apply'], 'risk', 20)
    return rc == 0, (out.strip().splitlines()[-1][:120] if out.strip() else 'risk.json')


def v_risk(r: Review) -> bool:
    return not r.profile().get('sensitivity') or (r.work / 'risk.json').exists()


# --- текст ТЗ, графика, таймлайн ---------------------------------------------
def st_terms(r: Review):
    rc, out = r.run_cmd([PY, STAGES_DIR / 'terms_index.py'], 'terms', 20)
    return rc == 0, 'terms_v6.json'


def v_terms(r: Review) -> bool:
    return (r.work / 'terms_v6.json').exists()


def lint_long(r: Review) -> int:
    """lint_v7.json = {"ТЗ-NN": {"multi": [...], "long": [...]}, ...} — считаем длинные строки по всем ТЗ."""
    p = r.work / 'lint_v7.json'
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        if not isinstance(d, dict):
            return 0
        if 'long' in d and isinstance(d['long'], list):
            return len(d['long'])
        return sum(len((v or {}).get('long') or []) + len((v or {}).get('multi') or []) for v in d.values() if isinstance(v, dict))
    except Exception:
        return 0


def st_format_tz(r: Review):
    rc, out = r.run_cmd([PY, STAGES_DIR / 's10_format_tz.py'], 'format_tz', 20)
    return rc == 0, f'lint: длинных строк {lint_long(r)}'


def v_format_tz(r: Review) -> bool:
    return (r.work / 'lint_v7.json').exists()


def st_polish(r: Review):
    if r.lang() == 'en':                       # s14 — русская модель-полировщик строк; английский ТЗ не полируем
        return True, 'EN: polish skipped'
    if lint_long(r) == 0:
        return True, 'полировка не нужна (lint 0)'
    rc0, out0 = r.run_cmd([PY, STAGES_DIR / 'polish_todo.py'], 'polish_todo', 5)
    if rc0 != 0:
        return False, f'polish_todo rc={rc0}'
    if 'строк 0' in out0:
        return True, 'полировка: нарушения не найдены в parts (нечего править)'
    rc, out = r.run_cmd([PY_LLM, STAGES_DIR / 's14_polish_local.py'], 'polish', 120)
    if rc != 0:
        return False, f's14 rc={rc}'
    rc, out = r.run_cmd([PY, STAGES_DIR / 'merge_local_fixes.py'], 'polish_merge', 10)
    if rc != 0:
        return False, f'merge_local_fixes rc={rc}'
    rc2, out2 = r.run_cmd([PY, STAGES_DIR / 's10_format_tz.py'], 'format_tz', 20)
    return rc2 == 0, f'после полировки длинных строк {lint_long(r)} (слито: {out.strip().splitlines()[-2][:60] if len(out.strip().splitlines()) > 1 else "?"})'


def v_polish(r: Review) -> bool:
    return (r.work / 'lint_v7.json').exists()


def st_sources(r: Review):
    rc, out = r.run_cmd([PY, STAGES_DIR / 's11_apply_sources.py'], 'sources', 10)
    return rc == 0, 'источники материалов проставлены' if 'нет' not in out else 'sources_research.json нет — источники не проставлены (мягко)'


def v_sources(r: Review) -> bool:
    return True


def st_sub(r: Review):
    rc, out = r.run_cmd([PY, STAGES_DIR / 'sub_from_prev.py'], 'sub', 10)
    n = len(r.card.get('sub') or [])
    if not (r.card.get('prev_pravki') or ''):
        return True, 'подглавы: в карточке нет prev_pravki — переносить нечего'
    return rc in (0, 2), f'подглав перенесено: {n}' + (' · часть просит сверки глазами' if rc == 2 else '')


def v_sub(r: Review) -> bool:
    return bool(r.card.get('sub')) or not (r.card.get('prev_pravki') or '')


def st_claims(r: Review):
    rc, out = r.run_cmd([PY, STAGES_DIR / 'claims_pick.py'], 'claims', 10)
    return rc == 0, f'крупных фраз: {len(r.card.get("claims") or [])}'


def v_claims(r: Review) -> bool:
    return (r.work / 'claims_pick.json').exists()


def st_screens_plan(r: Review):
    rc, out = r.run_cmd([PY, STAGES_DIR / 'screens_plan.py'], 'screens_plan', 10)
    return rc in (0, 2), (out.strip().splitlines()[0][:120] if out.strip() else 'раскладка экранов')


def v_screens_plan(r: Review) -> bool:
    return (r.work / 'screens_plan.json').exists()


def st_structure(r: Review):
    rc, out = r.run_cmd([PY, STAGES_DIR / 'structure_text.py'], 'structure', 10)
    return rc == 0, (out.strip().splitlines()[0][:120] if out.strip() else 'структура текстом')


def v_structure(r: Review) -> bool:
    return (r.work / 'structure.json').exists()


def st_screens_page(r: Review):
    rc, out = r.run_cmd([PY, SHARED / 'screens_page.py'], 'screens_page', 15)
    return rc == 0, (out.strip().splitlines()[-1][:120] if out.strip() else 'витрина экранов')


def v_screens_page(r: Review) -> bool:
    return (r.review_dir / f'{r.code}_{r.cut}_screens.html').exists()


def st_doc_chapters(r: Review):
    if not r.card.get('doc_id'):
        return True, 'вкладка «Главы»: в карточке нет doc_id — пропуск'
    # кадры наружу — только вручную с Мака, ровно как у doc_feedback: в кадрах бывает человек,
    # которого нельзя показывать по ссылке, и автономный прогон такое решение принимать не должен
    temp = r.images == 'temp' and r.host == 'mac' and not r.autonomous
    if r.images == 'temp' and not temp:
        r.note('doc_chapters: --images temp отброшен — на Memex и в автономном режиме вкладка пишется без кадров')
    argv = [PY, STAGES_DIR / 'doc_tab_chapters_v1.py', '--images', 'temp' if temp else 'none']
    rc, out = r.run_cmd(argv, 'doc_chapters', 20)
    return rc == 0, (out.strip().splitlines()[-1][:120] if out.strip() else 'вкладка «Главы» записана')


def v_doc_chapters(r: Review) -> bool:
    return True                                   # внешняя запись: гейт — глазами и PDF-снимком


def st_render(r: Review):
    stages = str(r.card.get('render_stages', 'all')).split()
    rc, out = r.run_cmd([PY, STAGES_DIR / 'make_infographics_v6.py', *stages], 'render', 90)
    return rc == 0, f'PNG в mockups: {_count(r.review_dir / "mockups", "*.png")}'


def v_render(r: Review) -> bool:
    return _count(r.review_dir / 'mockups', '*.png') > 0


def st_review_json(r: Review):
    rc, out = r.run_cmd([PY, STAGES_DIR / 'make_review_v6.py'], 'review_json', 10)
    return rc == 0, (out.strip().splitlines()[0][:120] if out.strip() else 'review json')


def v_review_json(r: Review) -> bool:
    return (r.review_dir / f'{r.code}_review_v6.json').exists()


def st_mock(r: Review):
    uxp = Path.home() / 'YTAI/scripts/05_editing/0500_uxp/src/parts/partsBuilder.js'
    if not (shutil.which(NODE) or Path(NODE).exists()) or not uxp.exists():
        # автономный Memex без node / мок-панели: сборку не проверяем, но и цепочку не роняем (честная пометка)
        msg = 'mock: node или 0500_uxp нет на этом хосте — проверочная сборка НЕ выполнена (прогнать на маке: run --only mock)'
        r.tg(f'⚠️ <b>{r.code}</b>: {msg}')
        if not r.dry:
            (r.work / 'mock_result.json').write_text(json.dumps({'ok': None, 'skipped': msg, 'at': now()}, ensure_ascii=False))
        return True, msg
    rc, out = r.run_cmd([NODE, STAGES_DIR / 'mockbuild_v6.js'], 'mock', 10)
    ok = rc == 0 and 'error 0' in out
    m = re.search(r'placed=(\d+)', out)
    if ok and not r.dry:
        (r.work / 'mock_result.json').write_text(json.dumps({'ok': True, 'placed': m.group(1) if m else None, 'at': now()}))
    return ok, f'mock: placed {m.group(1) if m else "?"}, {"0 ошибок" if ok else "есть ошибки"}'


def v_mock(r: Review) -> bool:
    # раньше всегда True: run_stage засчитывал mock «по артефактам» и проверочная сборка не запускалась вовсе (17.09)
    res, rj = r.work / 'mock_result.json', r.review_dir / f'{r.code}_review_v6.json'
    return res.exists() and (not rj.exists() or res.stat().st_mtime >= rj.stat().st_mtime)


def st_previews(r: Review):
    rc, out = r.run_cmd([PY, STAGES_DIR / 's7_preview_sheet.py'], 'previews_sheet', 30)
    rc2, out2 = r.run_cmd([PY, STAGES_DIR / 's12_doc_previews.py', '--render'], 'previews_render', 30)
    qc = STAGES_DIR / 'preview_qc_local.py'
    msg = f'превью: {_count(r.work / "previews_doc", "*.jpg")}'
    if qc.exists():
        rc3, out3 = r.run_cmd([PY, qc], 'preview_qc', 30)
        msg += ' · qc ' + ('0 high' if rc3 == 0 else f'rc={rc3} (см. preview_qc.json)')
    return rc == 0 and rc2 == 0, msg


def v_previews(r: Review) -> bool:
    return _count(r.work / 'previews_doc', '*.jpg') > 0


# --- внешние поверхности ------------------------------------------------------
def _ext(r: Review, key: str) -> bool:
    """Внешний id задан в карточке или окружением YTAI_<KEY> (тестовые док/папка/лист)."""
    return bool(r.card.get(key) or os.environ.get('YTAI_' + key.upper()))


def st_drive(r: Review):
    if not _ext(r, 'materials_id'):
        return True, 'materials_id пуст — Drive пропущен'
    rc, out = r.run_cmd([PY, STAGES_DIR / 's9_materials_drive.py'], 'drive', 60)
    rc2, _ = r.run_cmd([PY, STAGES_DIR / 's12_doc_previews.py', '--upload'], 'drive_previews', 30)
    rc3, _ = r.run_cmd([PY, STAGES_DIR / 's12_doc_previews.py', '--apply'], 'drive_previews_apply', 10)
    rc4, _ = r.run_cmd([PY, STAGES_DIR / 'ensure_shots.py'], 'drive_shots', 10)     # все картинки pravki — в shots_remote
    r.S['surfaces']['drive'] = {'at': now(), 'rc': rc}
    return rc == 0 and rc2 == 0 and rc3 == 0 and rc4 == 0, 'материалы и превью на Drive'


def v_drive(r: Review) -> bool:
    return not _ext(r, 'materials_id') or bool(r.S['surfaces'].get('drive'))


def st_sheet(r: Review):
    if not (_ext(r, 'notes_sheet_id') or (r.pravki / 'notes_sheet.json').exists()):
        return True, 'notes_sheet_id пуст — лист пропущен'
    rc, out = r.run_cmd([PY, STAGES_DIR / 'tz_sheet.py'], 'sheet', 20)
    r.S['surfaces']['sheet'] = {'at': now(), 'rc': rc}
    return rc == 0, 'лист «ТЗ монтажёру» обновлён'


def v_sheet(r: Review) -> bool:
    return (not (_ext(r, 'notes_sheet_id') or (r.pravki / 'notes_sheet.json').exists())
            or bool(r.S['surfaces'].get('sheet')))


def st_carry(r: Review):
    """Долг прошлого круга → строки вкладки ТЗ (shared/tz_carry.py, contracts.md §13).
    Стоит ПЕРЕД doc_tz и ПОСЛЕ sheet: облако здесь не ждём (сверщик работает в хвосте цепочки),
    поэтому жёсткую стадию doc_tz ничто не запирает."""
    if not _fb_on(r):
        return True, 'prev_pravki нет — переносить нечего'
    if not (r.work / 'feedback.json').exists():
        return True, 'модель сверки ещё не собрана — перенос пропущен (соберётся стадией feedback)'
    rc, out = r.run_cmd([PY, SHARED / 'tz_carry.py', '--apply'], 'carry', 10)
    if rc != 0:
        return False, 'перенос не собрался — см. logs/carry.log'
    head = next((ln for ln in out.splitlines() if ln.startswith('перенос:')), 'перенос собран')
    return True, head


def _carry_fresh(r: Review) -> bool:
    """перенос считается свежим, пока он собран из ТОЙ ЖЕ сборки модели сверки."""
    try:
        c = json.loads((r.pravki / 'tz_carry.json').read_text(encoding='utf-8'))
        fb = json.loads((r.work / 'feedback.json').read_text(encoding='utf-8'))
    except Exception:                                              # noqa: BLE001
        return False
    return c.get('build_of') == fb.get('build_no')


def v_carry(r: Review) -> bool:
    return (not _fb_on(r) or not (r.work / 'feedback.json').exists()
            or ((r.pravki / 'tz_carry.json').exists() and _carry_fresh(r)))


def edits_guard(r: Review, surface: str):
    """Перед регенерацией вкладки — правки Романа должны быть сняты (review.py edits).
    Гейт действует только для той же вкладки (имя) и того же дока, что писались в прошлый раз."""
    prev = r.S['surfaces'].get(surface) or {}
    # Отметка ставится и на неудачной записи (503 от Docs, обрыв сети) — но тогда во вкладке
    # НИЧЕГО не появилось, и правок Романа там взяться неоткуда. Считать такую запись
    # состоявшейся значит запереть стадию навсегда: повтор упирается в гейт, а снимать нечего.
    written = prev.get('at') if prev.get('rc') == 0 else None
    same_target = (prev.get('doc') or '') == (os.environ.get('YTAI_DOC_ID') or r.card.get('doc_id') or '') and \
                  (surface != 'doc_tz' or (prev.get('tab') or '') == r.tab_title())
    last_edits = (r.S.get('edits') or {}).get('at')
    if written and same_target and (not last_edits or last_edits < written) and not os.environ.get('YTAI_SKIP_EDITS_GUARD'):
        raise Fatal(f'вкладка {surface} писалась {written}, а правки Романа с тех пор не снимались — '
                    f'сначала `review.py edits`, либо YTAI_SKIP_EDITS_GUARD=1')


def st_doc_tz(r: Review):
    if not _ext(r, 'doc_id'):
        return True, 'doc_id пуст — вкладка ТЗ пропущена'
    edits_guard(r, 'doc_tz')
    # кадры закрытого фильма (YTCH12: в кадре ребёнок) попадают во вкладку через временный доступ —
    # те же четыре условия, что у вкладки обратной связи: карточка + флаг + Мак + человек рядом
    temp = r.images == 'temp' and r.host == 'mac' and not r.autonomous
    if r.images == 'temp' and not temp:
        r.note('doc_tz: --images temp отброшен — на Memex и в автономном режиме вкладка пишется без кадров')
    imgs = ['--images', 'temp'] if temp else []
    rc0, _ = r.run_cmd([PY, STAGES_DIR / 'ensure_shots.py'] + imgs, 'doc_tz_shots', 10)  # без id картинка молча не встанет
    if rc0 != 0:
        return False, 'в pravki есть картинки без файла и без id в реестре кадров — см. logs/doc_tz_shots.log'
    rc, out = r.run_cmd([PY, STAGES_DIR / 'doc_tab_tz_v4.py'] + imgs, 'doc_tz', 40)
    r.S['surfaces']['doc_tz'] = {'at': now(), 'rc': rc, 'tab': r.tab_title(), 'images': 'temp' if temp else 'none',
                                 'doc': os.environ.get('YTAI_DOC_ID') or r.card.get('doc_id')}
    return rc == 0, f'вкладка «{r.tab_title()}»'


def v_doc_tz(r: Review) -> bool:
    return not _ext(r, 'doc_id') or bool(r.S['surfaces'].get('doc_tz'))


def st_doc_nav(r: Review):
    if not _ext(r, 'doc_id'):
        return True, 'doc_id пуст — навигатор пропущен'
    # Навигатор нужен не каждому фильму: на YTUVI01 v2 Роман попросил всё держать в одной
    # вкладке ТЗ (22.09.2026). Пустой `nav_tab` в карточке = вкладку не собираем.
    if 'nav_tab' in r.card and not str(r.card.get('nav_tab') or '').strip():
        return True, 'nav_tab пуст — навигатор не нужен этому фильму'
    edits_guard(r, 'doc_nav')
    rc, out = r.run_cmd([PY, STAGES_DIR / 'doc_tab_review_v1.py'], 'doc_nav', 40)
    r.S['surfaces']['doc_nav'] = {'at': now(), 'rc': rc, 'tab': os.environ.get('YTAI_NAV_TAB') or r.card.get('nav_tab'),
                                  'doc': os.environ.get('YTAI_DOC_ID') or r.card.get('doc_id')}
    return rc == 0, f'вкладка-навигатор «{os.environ.get("YTAI_NAV_TAB") or r.card.get("nav_tab", "")}»'


def v_doc_nav(r: Review) -> bool:
    return not _ext(r, 'doc_id') or bool(r.S['surfaces'].get('doc_nav'))


def st_verify(r: Review):
    if not _ext(r, 'doc_id'):
        return True, 'doc_id пуст — verify пропущен'
    rc, out = r.run_cmd([PY, STAGES_DIR / 'doc_tab_tz_v4_verify.py'], 'verify', 20)
    ok = rc == 0 and 'ALL PASS' in out
    (r.S['surfaces'].setdefault('doc_tz', {}))['verify'] = 'ALL PASS' if ok else 'FAIL'
    return ok, 'doc verify ALL PASS' if ok else 'doc verify FAIL — см. logs/verify.log'


def v_verify(r: Review) -> bool:
    return not _ext(r, 'doc_id') or (r.S['surfaces'].get('doc_tz') or {}).get('verify') == 'ALL PASS'


def st_doc_qc(r: Review):
    qc = STAGES_DIR / 'doc_pdf_qc.py'
    if not qc.exists() or not _ext(r, 'doc_id'):
        return True, 'doc_pdf_qc пропущен'
    rc, out = r.run_cmd([PY, qc], 'doc_qc', 20)
    return True, ('doc QA 0 high' if rc == 0 else f'doc QA: есть замечания (rc={rc}, doc_qc.json)')


def v_doc_qc(r: Review) -> bool:
    return True


def st_phone_brief(r: Review):
    script = SHARED / 'phone_brief.py'
    if not script.exists():
        return True, 'phone_brief: скрипта ещё нет — пропуск'
    rc, out = r.run_cmd([PY, script, '--send'], 'phone_brief', 10)
    return rc == 0, 'бриф для телефона собран' + (' и отправлен' if 'sent' in out else '')


def v_phone_brief(r: Review) -> bool:
    return (r.review_dir / f'{r.code}_{r.cut}_brief.html').exists()


def st_producer_page(r: Review):
    script = SHARED / 'producer_page.py' if (SHARED / 'producer_page.py').exists() else STAGES_DIR / 'review_page.py'
    rc, out = r.run_cmd([PY, script], 'producer_page', 20)
    return rc == 0, 'страница продюсера'


def v_producer_page(r: Review) -> bool:
    return (r.work / 'review_page.html').exists() or (r.review_dir / f'{r.code}_{r.cut}_review_producer.html').exists()


# --- обратная связь по кату: сверка с прошлым ТЗ (docs/feedback_v1.md) -------------
FB_SKIP = 'prev_pravki нет — сверка пропущена'


def _fb_prev(r: Review) -> Path | None:
    v = os.environ.get('YTAI_PREV_PRAVKI') or r.card.get('prev_pravki')
    if not v:
        return None
    p = Path(str(v)).expanduser()
    return p if p.is_absolute() else r.review_dir / p


def _fb_on(r: Review) -> bool:
    p = _fb_prev(r)
    return bool(p and p.is_file())


def _fb_missing(r: Review) -> str:
    """ключ задан, а файла нет — это не «сверка не нужна», а потерянный вход (на Memex — не доехал в aux/)"""
    p = _fb_prev(r)
    return f'prev_pravki указан, файла нет: {p}' if p and not p.is_file() else ''


def _fb_stale_name(out: Path) -> Path:
    try:
        sha = re.sub(r'[^0-9A-Za-z]', '', str(json.loads(out.read_text(encoding='utf-8')).get('packet_sha') or ''))[:16]
    except Exception:
        sha = ''
    dst = out.with_name(f'feedback_check.stale-{sha or "unknown"}.json')
    i = 1
    while dst.exists():
        i += 1
        dst = out.with_name(f'feedback_check.stale-{sha or "unknown"}.{i}.json')
    return dst


def st_feedback(r: Review):
    """Составная: модель → пакет сверщику → (ждём воркфлоу) → вливание. Модель пересобирается ВСЕГДА перед
    вливанием: сборка затирает влитое, вливание вливает снова — порядок один, результат детерминирован."""
    if _fb_missing(r):
        raise Warn(_fb_missing(r))
    if not _fb_on(r):
        return True, FB_SKIP
    call_py = SHARED / 'feedback_call.py'
    rc, res = r.run_cmd([PY, SHARED / 'feedback_model.py'], 'feedback_build', 20)
    if rc != 0:
        return False, f'сборка модели rc={rc}: {res.strip()[-200:]}'
    rc, call = r.run_cmd([PY, call_py, '--print-call'], 'feedback_call', 5)
    if rc != 0:
        return False, f'пакет сверщику rc={rc}: {call.strip()[-200:]}'
    if r.dry:
        return True, '[dry] модель → пакет сверщику → облако (1 агент) → вливание'
    if not any(ln.startswith('Workflow(') for ln in call.splitlines()):
        r.S['surfaces']['feedback'] = {'at': now(), 'cloud': 'skipped'}
        return True, 'модель собрана; сверщику отправлять нечего — облако пропущено'
    out = r.cloud / 'out' / 'feedback_check.json'
    if out.exists():
        rc, res = r.run_cmd([PY, call_py, '--apply'], 'feedback_apply', 10)
        if rc == 0:
            r.S['surfaces']['feedback'] = {'at': now(), 'cloud': 'applied'}
            return True, (res.strip().splitlines()[-1][:120] if res.strip() else 'ответ сверщика влит')
        if rc != 2:
            return False, f'вливание rc={rc}: {res.strip()[-200:]}'
        stale = _fb_stale_name(out)                          # ответ устарел: не удаляем, откладываем и зовём заново
        os.replace(out, stale)
        r.note(f'feedback: ответ сверщика устарел → {stale.name}; нужен новый облачный проход')
    return _cloud_compound(r, call_py, 'feedback', 'feedback_check.json', ['--apply'])


def v_feedback(r: Review) -> bool:
    if _fb_missing(r):            # ключ задан, файла нет: гейт закрыт — иначе resume/автономный прогон «подтвердит по артефактам» молча
        return False
    return not _fb_on(r) or ((r.work / 'feedback.json').exists()
                             and (r.S['surfaces'].get('feedback') or {}).get('cloud') in ('applied', 'skipped'))


def st_feedback_page(r: Review):
    if not _fb_on(r):
        return True, _fb_missing(r) or FB_SKIP
    # без --send: в Telegram страница уходит только отдельной командой после «ок» (shared/feedback_page.py --send)
    rc, out = r.run_cmd([PY, SHARED / 'feedback_page.py'], 'feedback_page', 20)
    return rc == 0, (out.strip().splitlines()[-1][:120] if out.strip() else 'страница обратной связи')


def v_feedback_page(r: Review) -> bool:
    return not _fb_on(r) or (r.review_dir / f'{r.code}_{r.cut}_feedback.html').exists()


def memex_busy(r: Review) -> tuple[bool | None, str]:
    """Жив ли на Memex прогон ЭТОГО проекта: pid-файл прогона либо процесс review.py run с его папкой.
    → (True/False, пояснение); None = проверить не удалось (сеть, таймаут). Тот же ssh, что у memex/common.sh."""
    ctl = str(r.card.get('ctl_dir') or f'~/.cache/{r.project}')
    ctl = ctl if ctl.startswith(('~', '/')) else f'~/.cache/{r.project}'
    remote = (f'p=$(cat {ctl}/review.pid 2>/dev/null); if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then echo "MEMEX_ALIVE pid $p"; '
              f'elif pgrep -fl "review.py run" | grep -F "YTAI_work/{r.code}" >/dev/null; then echo "MEMEX_ALIVE process"; '
              f'else echo MEMEX_IDLE; fi')
    try:
        p = subprocess.run(['ssh', '-o', 'ConnectTimeout=8', '-o', 'BatchMode=yes', os.environ.get('MX_HOST', 'memex'), remote],
                           capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError) as e:
        return None, f'{type(e).__name__}'
    if 'MEMEX_ALIVE' in p.stdout:
        return True, p.stdout.strip().splitlines()[-1]
    if 'MEMEX_IDLE' in p.stdout:
        return False, ''
    return None, (p.stderr.strip().splitlines()[-1][:120] if p.stderr.strip() else f'ssh rc={p.returncode}')


def st_doc_feedback(r: Review):
    if not _fb_on(r):
        return True, _fb_missing(r) or FB_SKIP
    if not _ext(r, 'doc_id'):
        return True, 'doc_id пуст — вкладка обратной связи пропущена'
    # edits_guard не нужен: вкладка целиком пересобирается кодом, правки Романа снимаются только с вкладки ТЗ
    if r.host == 'mac' and not r.dry and os.environ.get('YTAI_SKIP_MEMEX_CHECK') != '1':
        busy, why = memex_busy(r)
        if busy:
            raise Fatal(f'на Memex идёт прогон этого же проекта ({why}) — два писателя в один док. '
                        f'Дождись конца (review.py memex status) или останови: review.py memex stop')
        if busy is None:
            raise Fatal(f'не удалось проверить, идёт ли прогон этого проекта на Memex ({why}) — в док не пишу. '
                        f'Проверь сеть до Memex; если там точно пусто — повтори с YTAI_SKIP_MEMEX_CHECK=1')
    temp = r.images == 'temp' and r.host == 'mac' and not r.autonomous      # кадры наружу — только вручную с Мака
    if r.images == 'temp' and not temp:
        r.note('doc_feedback: --images temp отброшен — на Memex и в автономном режиме вкладка пишется без кадров')
    # Вкладка обратной связи ЦЕЛИКОМ принадлежит коду (правки Романа снимаются только с вкладки ТЗ),
    # поэтому на втором и следующих кругах её надо перезаписывать: без --force write_tab отказывается
    # трогать непустую вкладку, и стадия навсегда застревала бы на «перезаписать только с force».
    # Заморозку (frozen_tabs) это не снимает — вкладки прошлых кругов по-прежнему неприкосновенны.
    argv = ([PY, STAGES_DIR / 'doc_tab_feedback_v1.py', '--force']
            + (['--images', 'temp'] if temp else []))
    rc, out = r.run_cmd(argv, 'doc_feedback', 60)
    if r.dry:
        r.run_cmd([PY, STAGES_DIR / 'doc_tab_feedback_v1_verify.py'], 'doc_feedback_verify', 20)
        return True, '[dry] вкладка обратной связи → проверка'
    surf = {'at': now(), 'rc': rc, 'doc': os.environ.get('YTAI_DOC_ID') or r.card.get('doc_id'), 'images': 'temp' if temp else 'none'}
    r.S['surfaces']['doc_feedback'] = surf
    if rc != 0:
        return False, 'вкладка обратной связи не записана или записана с замечаниями — см. logs/doc_feedback.log'
    rc, out = r.run_cmd([PY, STAGES_DIR / 'doc_tab_feedback_v1_verify.py'], 'doc_feedback_verify', 20)
    ok = rc == 0 and 'ALL PASS' in out
    surf['verify'] = 'ALL PASS' if ok else 'FAIL'
    return ok, ('вкладка обратной связи записана, проверка ALL PASS' if ok
                else 'проверка вкладки обратной связи FAIL — см. logs/doc_feedback_verify.log')


def v_doc_feedback(r: Review) -> bool:
    return (not _fb_on(r) or not _ext(r, 'doc_id')
            or (r.S['surfaces'].get('doc_feedback') or {}).get('verify') == 'ALL PASS')


# --- montage_tz -----------------------------------------------------------------
def _mt(name: str) -> Path:
    return MONTAGE / name


def st_mt_generic(script: str, stage: str, py: str = PY, timeout: int = 60):
    def fn(r: Review):
        p = _mt(script)
        if not p.exists():
            return True, f'{script}: скрипта ещё нет — пропуск'
        rc, out = r.run_cmd([py, p], stage, timeout)
        return rc == 0, (out.strip().splitlines()[-1][:120] if out.strip() else stage)
    return fn


def v_true(r: Review) -> bool:
    return True


# name → (host, work, gate, kind)   kind: HARD | SOFT
# стадии, которые ПИШУТ во внешний документ: их снимает --no-doc (и по ним же считается хвост цепочки)
NO_DOC_STAGES = ('doc_tz', 'doc_nav', 'verify', 'doc_qc', 'doc_feedback', 'doc_chapters')

STAGES_CUT = [
    ('download',      'memex', st_download,      v_download,      'HARD'),
    ('frames',        'memex', st_frames,        v_frames,        'HARD'),
    ('static',        'mac',   st_static,        v_static,        'SOFT'),
    ('ocr',           'memex', st_ocr,           v_ocr,           'HARD'),
    ('transcript',    'memex', st_transcript,    v_transcript,    'HARD'),
    ('vlm',           'memex', st_vlm,           v_vlm,           'HARD'),
    ('llm',           'memex', st_llm,           v_llm,           'HARD'),
    ('probe',         'memex', st_probe,         v_probe,         'SOFT'),
    ('selfcheck',     'memex', st_selfcheck,     v_selfcheck,     'SOFT'),
    ('route',         'mac',   st_route,         v_route,         'HARD'),
    ('cloud',         'mac',   st_cloud,         v_cloud,         'HARD'),
    ('apply',         'mac',   st_apply,         v_apply,         'HARD'),
    ('align',         'mac',   st_align,         v_align,         'SOFT'),
    ('chapters',      'mac',   st_chapters,      v_chapters,      'SOFT'),
    ('risk',         'mac',   st_risk,          v_risk,          'SOFT'),
    ('acts',          'mac',   st_acts,          v_acts,          'SOFT'),
    # структура фильма: подглавы и крупные фразы — ДО format_tz и render, они их читают
    ('sub',           'mac',   st_sub,           v_sub,           'SOFT'),
    ('claims',        'mac',   st_claims,        v_claims,        'SOFT'),
    ('verdict',       'mac',   st_verdict,       v_verdict,       'SOFT'),
    ('terms',         'mac',   st_terms,         v_terms,         'HARD'),
    ('format_tz',     'mac',   st_format_tz,     v_format_tz,     'HARD'),
    ('polish',        'mac',   st_polish,        v_polish,        'SOFT'),
    ('sources',       'mac',   st_sources,       v_sources,       'SOFT'),
    ('render',        'mac',   st_render,        v_render,        'HARD'),
    ('review_json',   'mac',   st_review_json,   v_review_json,   'HARD'),
    ('mock',          'mac',   st_mock,          v_mock,          'HARD'),
    ('previews',      'mac',   st_previews,      v_previews,      'SOFT'),
    ('drive',         'mac',   st_drive,         v_drive,         'SOFT'),
    ('sheet',         'mac',   st_sheet,         v_sheet,         'SOFT'),
    # перенос долга прошлого ТЗ — строго ПЕРЕД вкладкой: облако здесь не ждём, жёсткий doc_tz не запирается
    ('carry',         'mac',   st_carry,         v_carry,         'SOFT'),
    ('doc_tz',        'mac',   st_doc_tz,        v_doc_tz,        'HARD'),
    ('doc_nav',       'mac',   st_doc_nav,       v_doc_nav,       'SOFT'),
    ('verify',        'mac',   st_verify,        v_verify,        'HARD'),
    ('doc_qc',        'mac',   st_doc_qc,        v_doc_qc,        'SOFT'),
    ('phone_brief',   'mac',   st_phone_brief,   v_phone_brief,   'SOFT'),
    ('producer_page', 'mac',   st_producer_page, v_producer_page, 'SOFT'),
    # сверка с прошлым ТЗ — строго ПОСЛЕ producer_page: ожидание облака не должно запирать основную цепочку
    # экраны и структура текстом — ПЕРЕД обратной связью: её шапка берёт короткий текст структуры
    ('screens_plan',  'mac',   st_screens_plan,  v_screens_plan,  'SOFT'),
    ('structure',     'mac',   st_structure,     v_structure,     'SOFT'),
    ('screens_page',  'mac',   st_screens_page,  v_screens_page,  'SOFT'),
    ('doc_chapters',  'mac',   st_doc_chapters,  v_doc_chapters,  'SOFT'),
    ('feedback',      'mac',   st_feedback,      v_feedback,      'SOFT'),
    ('feedback_page', 'mac',   st_feedback_page, v_feedback_page, 'SOFT'),
    ('doc_feedback',  'mac',   st_doc_feedback,  v_doc_feedback,  'SOFT'),
]

STAGES_MONTAGE = [
    ('transcript',    'memex', st_transcript, v_transcript, 'HARD'),
    ('segment',       'memex', st_mt_generic('segment_local.py', 'segment', PY_LLM, 120),
                               lambda r: (r.review_dir / 'segments.json').exists(), 'SOFT'),
    ('montage',       'mac',   st_mt_generic('build_montage.py', 'montage'),
                               lambda r: (r.review_dir / 'montage.json').exists(), 'HARD'),
    ('structure',     'mac',   st_mt_structure, v_mt_structure, 'SOFT'),
    ('mockups',       'mac',   st_mt_generic('build_mockups.py', 'mockups', PY, 120),
                               lambda r: _count(r.review_dir / 'mockups', '*.png') > 0, 'SOFT'),
    ('design_review', 'mac',   st_mt_design, v_mt_design, 'SOFT'),
    ('structure_html', 'mac',  st_mt_generic('build_structure_html.py', 'structure_html'), v_true, 'SOFT'),
    ('standalone',    'mac',   st_mt_generic('make_standalone.py', 'standalone'), v_true, 'SOFT'),
    ('phone_brief',   'mac',   st_phone_brief, v_phone_brief, 'SOFT'),
]

STAGE_DESC = {
    'download': ('rclone из cut_drive напрямую', 'кат на диске'),
    'frames': ('ffmpeg 1 fps 1080p', 'кадров ≥ длительность − допуск'),
    'static': ('static_stretches: где кадр не меняется (PIL, 0 токенов)', 'static_stretches.json'),
    'ocr': ('s2_ocr_hires (Apple Vision, bbox)', 'селфчек ocr + якоря'),
    'transcript': ('wordrole_transcribe --plain (.venv_transcribe)', 'words.json'),
    'vlm': ('s3_vlm Qwen2.5-VL-7B', 'селфчек vlm'),
    'llm': ('s4_llm Qwen3-8B (признаки, не вердикты)', 'селфчек llm'),
    'probe': ('s3b_probe_vlm: чужие следы, обрезка, zoom-перечит', 'probes на всех экранах'),
    'selfcheck': ('s5_selfcheck all', 'ALL OK'),
    'route': ('route_candidates: auto / cloud / drop', 'candidates.json'),
    'cloud': ('pack → Workflow wf_judge (J≤4, F, V, S) → collect', 'все пакеты done, покрытие 100 %'),
    'apply': ('s8_apply_audit: классовый фильтр, одна ТЗ на экран', 'audit_v6.json + pravki'),
    'align': ('align: n-gram кат ↔ план/прошлые версии (card.align_against)', 'align.json'),
    'chapters': ('chapters_from_plan --apply: главы ката по плану частей (card.chapters_plan) через align; chapter экранов '
                 'перепомечается', 'chapters_proposal.json (инверсия → карточка не тронута)'),
    'risk': ('risk_registry (YTCH): ⚠️ на подтверждение фонда, не ⛔', 'risk.json'),
    # тексты существующих стадий не менять: их показывает RU-страница продюсера (golden producer_page);
    # EN-поведение acts (--no-llm при verdict.enabled), verdict (редакторский) и polish (пропуск) — README «Грабли», contracts §2
    'acts': ('acts_compact Qwen3-8B по актам + проверки структуры (YTCH)', 'acts_compact.json'),
    'verdict': ('1 облачный агент: вердикт, обязательные правки, структура (YTCH)', 'verdict.json применён'),
    'design_review': ('1 облачный агент по контактному листу мокапов', 'design_review.json применён'),
    'terms': ('terms_index', 'terms_v6.json'),
    'format_tz': ('s10_format_tz + lint', 'lint_v7.json'),
    'polish': ('s14_polish_local Qwen3-8B по одной строке + guard', 'длинных строк 0'),
    'sources': ('s11_apply_sources', '—'),
    'render': ('make_infographics_v6 (chrome-headless 4K PNG)', 'PNG в mockups'),
    'review_json': ('make_review_v6 (ytai-part-v1, 6 слоёв)', '{CODE}_review_v6.json'),
    'mock': ('mockbuild_v6.js через partsBuilder', '0 ошибок'),
    'previews': ('s7 + s12 --render + preview_qc_local', 'qc 0 high'),
    'drive': ('s9_materials_drive + s12 --upload/--apply + ensure_shots', 'файлы с комментами, все картинки pravki в shots_ids'),
    'sheet': ('tz_sheet', 'лист обновлён'),
    'carry': ('shared/tz_carry.py: несделанное из прошлого ТЗ → строки вкладки (номера своего круга)',
              'tz_carry.json собран из текущей модели сверки'),
    'doc_tz': ('ensure_shots → doc_tab_tz_v4, 9 колонок с «Говорит»; кадры закрытого фильма — '
               'только run --images temp, с Мака (гейт: review.py edits)', 'вкладка записана'),
    'doc_nav': ('doc_tab_review_v1 (навигатор)', 'вкладка записана'),
    'verify': ('doc_tab_tz_v4_verify', 'ALL PASS'),
    'doc_qc': ('doc_pdf_qc (pdftotext/pdfimages/PIL)', '0 high'),
    'phone_brief': ('phone_brief → Telegram', 'файл ≤1 МБ отправлен'),
    'producer_page': ('producer_page / review_page', 'HTML'),
    'sub': ('sub_from_prev: подглавы прошлого круга → card.sub на ось этого ката (проекция + речь + пауза)',
            'card.sub заполнен (или в карточке нет prev_pravki)'),
    'claims': ('claims_pick: крупные фразы фильма → card.claims (дословно из ката, без чувствительных тем)',
               'claims_pick.json'),
    'screens_plan': ('screens_plan: каждому экрану — таймкод, длительность и макет',
                     'screens_plan.json, все экраны внутри длины ката'),
    'structure': ('structure_text: структура фильма человеческим текстом (шапка сверки + вкладка «Главы»)',
                  'structure.json, гейт текста пройден'),
    'screens_page': ('screens_page: витрина экранов одним самодостаточным HTML',
                     '{CODE}_{cut}_screens.html, ноль внешних адресов'),
    'doc_chapters': ('doc_tab_chapters_v1: вкладка «Главы» — структура текстом, все главы и подглавы, варианты заставки',
                     'вкладка записана (кадры — временным доступом)'),
    'feedback': ('feedback_model → 1 облачный агент-сверщик (feedback_call) → вливание; только при card.prev_pravki',
                 'feedback.json, ответ сверщика влит'),
    'feedback_page': ('feedback_page: HTML «Обратная связь по кату» продюсеру (в Telegram — отдельной командой)',
                      '{CODE}_{cut}_feedback.html'),
    'doc_feedback': ('doc_tab_feedback_v1 (кадры — только run --images temp, с Мака) → doc_tab_feedback_v1_verify', 'ALL PASS'),
    'segment': ('segment_local Qwen3-8B: тезисы + якоря', 'segments.json'),
    'montage': ('build_montage по пословным якорям', 'montage.json'),
    'structure': ('1 облачный агент: структура/тезисы/графика', 'montage_plan обновлён'),
    'mockups': ('build_mockups + DOM-QC', 'PNG 4K'),
    'structure_html': ('build_structure_html', 'HTML'),
    'standalone': ('make_standalone (для телефона)', 'один HTML'),
}


def stages_for(r: Review):
    return STAGES_MONTAGE if r.mode == 'montage_tz' else STAGES_CUT


# ══════════════════════════════════════════════════════════════════════════════
# 2. Исполнение
# ══════════════════════════════════════════════════════════════════════════════

LOAD_FLAG = Path.home() / '.cache' / 'ytai' / 'LOAD.json'
HEAVY = {'frames': 15, 'ocr': 10, 'transcript': 20, 'vlm': 90, 'llm': 40, 'probe': 70, 'render': 10, 'segment': 30, 'acts': 40, 'polish': 30}


LOAD_STALE_MIN = 60           # чужой флаг старше started + expected_min + 60 мин считаем брошенным


def _flag_read() -> dict | None:
    """LOAD.json → dict; нет файла → None; битый JSON → {} (чужой: не наш и не снимаем)."""
    try:
        return json.loads(LOAD_FLAG.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except Exception:
        return {}


def _flag_ours(r: Review, cur: dict | None) -> bool:
    return bool(cur) and cur.get('job') == 'review' and cur.get('code') == r.code


def _flag_stale(cur: dict) -> bool:
    """started + expected_min + 60 мин уже прошли (время старта нечитаемо — берём mtime файла)."""
    started = None
    try:
        started = datetime.fromisoformat(str(cur.get('started'))).timestamp()
    except (TypeError, ValueError):
        try:
            started = LOAD_FLAG.stat().st_mtime
        except OSError:
            return True
    try:
        exp = float(cur.get('expected_min') or 0)
    except (TypeError, ValueError):
        exp = 0.0
    return time.time() > started + (exp + LOAD_STALE_MIN) * 60


def foreign_load(r: Review) -> dict | None:
    """Живой чужой флаг нагрузки (другая работа или другой фильм) → его содержимое, иначе None."""
    cur = _flag_read()
    if cur is None or _flag_ours(r, cur) or _flag_stale(cur):
        return None
    return cur


def wait_load(r: Review, reason: str, max_wait_min: float = 480) -> bool:
    """Очередь на Memex: пока лежит живой чужой LOAD.json — стоим (checkpoint + heartbeat, сон 60 с).
    TG — один раз «занят» и один раз «свободен» за эпизод ожидания. → True (свободно) / False (таймаут)."""
    t0 = time.time()
    waited = False
    while True:
        cur = foreign_load(r)
        if cur is None:
            if waited:
                r.log(f'▶ wait_load ({reason}): Memex свободен — начинаю {r.code}')
                r.tg(f'▶ Memex свободен — начинаю {r.code}')
            return True
        if not waited:
            job, started, exp = cur.get('job') or '?', cur.get('started') or '?', cur.get('expected_min') or '?'
            if cur.get('code') and cur.get('code') != r.code:
                job = f'{job} {cur.get("code")}'
            r.log(f'⏳ wait_load ({reason}): LOAD.json занят — {job} (с {started}, ~{exp} мин), жду')
            r.tg(f'⏳ Memex занят: {job} (с {started}, ~{exp} мин) — {r.code} в очереди')
            waited = True
        if time.time() - t0 >= max_wait_min * 60:
            r.log(f'🛑 wait_load ({reason}): Memex занят дольше {max_wait_min:.0f} мин — выхожу (rc 5)')
            r.tg(f'🛑 {r.code}: Memex занят дольше {max_wait_min:.0f} мин ({cur.get("job") or "?"}) — прогон не начат, '
                 f'повтори review.py memex start позже')
            return False
        r.checkpoint('wait_load')
        r.beat()
        time.sleep(60)


def load_flag(r: Review, stage: str | None, expected_min: int = 0):
    """Флаг нагрузки для мониторинга Memex (memex-temp-check.sh читает его и подписывает тревоги
    «идёт разбор {CODE}: {stage}»). stage=None — снять флаг. Чужой живой флаг не перезаписывается
    и не снимается (очередь — wait_load). dry-run флаг не трогает."""
    if r.dry:
        return
    try:
        cur = _flag_read()
        if stage is None:
            if cur is not None and _flag_ours(r, cur):
                LOAD_FLAG.unlink(missing_ok=True)
            elif cur is not None:
                r.log(f'   LOAD.json чужой ({cur.get("job")}/{cur.get("code")}) — не снимаю')
            return
        if cur is not None and not _flag_ours(r, cur) and not _flag_stale(cur):
            r.log(f'   LOAD.json занят ({cur.get("job")}/{cur.get("code")}) — свой флаг «{stage}» не пишу')
            return
        LOAD_FLAG.parent.mkdir(parents=True, exist_ok=True)
        LOAD_FLAG.write_text(json.dumps({'job': 'review', 'code': r.code, 'stage': stage, 'started': now(),
                                         'expected_min': expected_min, 'host': os.uname().nodename,
                                         'note': f'локальный разбор {r.code}: {stage} — высокая нагрузка ожидаема'},
                                        ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def run_stage(r: Review, name: str, host: str, fn, vfn, gate: str, force: bool = False) -> bool:
    stg = r.st(name)
    stg['host'] = host
    if not force and stg.get('status') in ('done', 'warn') and vfn(r):
        r.log(f'— {name}: уже сделано (артефакты на месте) → пропуск')
        return True
    if not force and stg.get('status') in ('todo', 'failed', None) and vfn(r) and name not in ('cloud',):
        stg.update(status='done', msg='подтверждено по артефактам', finished=now())
        r.save()
        r.log(f'— {name}: подтверждено по артефактам на диске → пропуск')
        return True
    for attempt in range(1, MAX_ATTEMPTS + 1):
        r.checkpoint(name)
        stg.update(status='running', attempts=attempt, started=now(), inputs_hash=r.inputs_hash(), log=str(r.logs / f'{name}.log'))
        r.save()
        r.log(f'▶ {name} ({attempt}/{MAX_ATTEMPTS})')
        if name in HEAVY:
            load_flag(r, name, HEAVY[name])
        if attempt == 1:
            r.tg(f'▶ <b>{r.code}</b>: {name}' + (f' — тяжёлая стадия, ~{HEAVY[name]} мин, температура Memex будет высокой (это разбор, не сбой)'
                                                 if name in HEAVY and host == 'memex' else ''))
        try:
            ok, msg = fn(r)
            if ok and (vfn(r) or r.dry):
                stg.update(status='done', msg=msg, finished=now())
                r.save()
                r.log(f'✅ {name}: {msg}')
                r.tg(f'✅ <b>{r.code}</b>: {name} — {msg}')
                return True
            r.log(f'✗ {name}: {msg}')
        except AwaitCloud as e:
            stg.update(status='awaiting_cloud', msg=str(e)[:300])
            r.save()
            r.log(f'☁️ {name}: {e}')
            r.tg(f'☁️ <b>{r.code}</b>: {name} ждёт облачный проход из сессии Claude')
            return False
        except Warn as e:
            stg.update(status='warn', msg=str(e)[:300], finished=now())
            r.save()
            r.log(f'⚠️ {name}: {e}')
            r.tg(f'⚠️ <b>{r.code}</b>: {name} — {e}')
            return True
        except Fatal as e:
            stg.update(status='failed', msg=str(e)[:300], finished=now())
            r.save()
            r.log(f'🛑 {name}: {e}')
            r.tg(f'🛑 <b>{r.code}</b>: стоп на «{name}»\n{e}')
            return False
        except Stopped:
            raise
        except Exception as e:
            import traceback
            r.log(f'✗ {name} исключение: {e}\n{traceback.format_exc()}')
        stg.update(status='failed', finished=now())
        r.save()
        if r.dry:
            break
        time.sleep(15 * attempt)
    if gate == 'SOFT':
        stg.update(status='warn', msg='не сошлось, идём дальше', finished=now())
        r.save()
        r.tg(f'⚠️ <b>{r.code}</b>: {name} не сошёлся — идём дальше (лог logs/{name}.log)')
        return True
    r.tg(f'🛑 <b>{r.code}</b>: «{name}» провалился {MAX_ATTEMPTS} раза — цепочка стоит (logs/{name}.log)')
    return False


AUTO_CLOUD_ROUNDS = 4          # автономный режим: сколько раз подряд самому выполнить Workflow на одной стадии
AUTO_CLOUD_ROUNDS_BY_STAGE = {'feedback': 1}     # сверщик — один пакет, второго нет (docs/feedback_v1.md §6)


def auto_cloud(r: Review, stage: str) -> bool:
    """Автономный режим: выполнить напечатанный стадией Workflow({...}) безголовым Claude (shared/headless_claude.py,
    launchd gui-домен Memex). Агенты сами пишут cloud/out/*.json; после возврата стадия перезапускается и сама
    собирает результат (collect) или печатает следующий вызов (F/V/S, повтор pending)."""
    call_f = r.cloud / ('CALL.txt' if stage == 'cloud' else f'CALL_{stage}.txt')
    if not call_f.exists():
        r.log(f'☁️ auto_cloud {stage}: нет {call_f.name}')
        return False
    sys.path.insert(0, str(SHARED))
    import headless_claude as HC
    try:
        call = HC.extract_workflow_call(call_f.read_text(encoding='utf-8'))
    except ValueError as e:
        r.log(f'☁️ auto_cloud {stage}: {e} ({call_f.name})')
        return False
    r.log(f'☁️ auto_cloud {stage}: headless Claude выполняет Workflow из {call_f.name}')
    rc, text = HC.run(HC.workflow_prompt(call, f'{r.code} {stage}'),
                      add_dirs=[str(r.review_dir), str(ROOT), str(YTAI / 'YTs')],
                      timeout_min=180, label=f'{r.project}-{stage}', stop_file=r.stop_f,
                      log_file=r.logs / f'{stage}_headless.log')
    (r.logs / f'{stage}_headless_last.txt').write_text(text, encoding='utf-8')
    if rc == 130:
        raise Stopped(stage)
    ok = rc == 0 and 'WORKFLOW_DONE' in text
    r.log(f'☁️ auto_cloud {stage}: rc={rc} {"ok" if ok else "без WORKFLOW_DONE — стадия сама проверит, что вернулось"}')
    return ok


def cmd_run(r: Review, a) -> int:
    autonomous = bool(getattr(a, 'autonomous', False)) or (r.ctl / 'AUTONOMOUS').exists() and a.host == 'memex'
    r.host, r.autonomous, r.images = a.host, autonomous, (getattr(a, 'images', None) or 'none')
    stages = stages_for(r)
    names = [s[0] for s in stages]
    sel = names[:]
    if a.only:
        if a.only not in names:
            raise SystemExit(f'нет стадии «{a.only}»; есть: {", ".join(names)}')
        sel = [a.only]
    else:
        if a.start:
            sel = sel[names.index(a.start):]
            for s in sel:
                r.st(s)['status'] = 'todo'
        if a.until:
            sel = sel[:sel.index(a.until) + 1]
    if a.host == 'memex' and not autonomous:
        sel = [s for s in sel if dict((n, h) for n, h, *_ in stages)[s] == 'memex']
    if a.no_drive:
        sel = [s for s in sel if s != 'drive']
    if a.no_doc:
        sel = [s for s in sel if s not in NO_DOC_STAGES]
    if r.pidf.exists() and not r.dry:
        try:
            os.kill(int(r.pidf.read_text()), 0)
            print(f'уже идёт прогон, pid {r.pidf.read_text()} — review.py stage <name> status')
            return 1
        except (OSError, ValueError):
            pass
    r.pidf.write_text(str(os.getpid()))
    r.stop_f.unlink(missing_ok=True)
    if autonomous and not r.dry:
        (r.ctl / 'AUTONOMOUS').write_text(now())             # сторож поднимает прогон тоже с --autonomous
    r.log(f'######## {r.code} run {sel[0]}…{sel[-1]} pid={os.getpid()} host={a.host}'
          f'{" autonomous" if autonomous else ""} version={version()}')
    rc = 0
    # --from S / --only S = регенерация: выбранные стадии гоняются заново, даже если артефакты на месте;
    # resume / run без флагов = продолжить, пропуская готовое по артефактам.
    force_range = bool(a.start or a.only or a.force or a.force_all)
    # очередь Memex: чужой живой LOAD.json (другая работа / другой фильм) — ждём, а не грузим вторую модель
    queue = a.host == 'memex' and not getattr(a, 'no_wait_load', False) and not r.dry     # dry-run очередь не ждёт
    max_wait = float(getattr(a, 'max_wait_min', 480) or 480)
    try:
        if queue and not wait_load(r, 'старт прогона', max_wait):
            rc = 5
            sel = []
        if a.host == 'memex' and sel:
            heavy = [s for s in sel if s in HEAVY]
            r.tg(f'🔥 <b>Memex</b>: начинаю локальный разбор <b>{r.code}</b> ({" → ".join(heavy) or "стадии без моделей"}), '
                 f'ожидаемо ~{sum(HEAVY[s] for s in heavy) // 60} ч {sum(HEAVY[s] for s in heavy) % 60} мин. '
                 f'Тревоги о температуре в это время — это рендер, не сбой. Пауза: review.py memex pause')
        for name, host, fn, vfn, gate in stages:
            if name not in sel:
                continue
            if queue and name in HEAVY and host == 'memex' and not wait_load(r, f'стадия {name}', max_wait):
                rc = 5
                break
            rounds = 0
            while True:
                if run_stage(r, name, host, fn, vfn, gate, force=force_range and rounds == 0):
                    ok_stage = True
                    break
                ok_stage = False
                if (autonomous and not r.dry and r.st(name).get('status') == 'awaiting_cloud'
                        and rounds < AUTO_CLOUD_ROUNDS_BY_STAGE.get(name, AUTO_CLOUD_ROUNDS)):
                    rounds += 1
                    r.tg(f'☁️ <b>{r.code}</b>: {name} — облачный проход запускаю сам (headless Claude, раунд {rounds})')
                    auto_cloud(r, name)
                    continue
                break
            if not ok_stage:
                rc = 4 if r.st(name).get('status') == 'awaiting_cloud' else 1
                if r.dry:                         # dry-run показывает весь план, а не стоит на первой закрытой стадии
                    r.log(f'[dry] {name}: гейт не закрылся бы — дальше по списку')
                    continue
                break
    except Stopped:
        r.log('STOP — состояние сохранено; продолжить: review.py resume')
        rc = 3
    finally:
        r.pidf.unlink(missing_ok=True)
        load_flag(r, None)
        r.save()
        if not r.dry:
            write_ticket(r)
    if a.host == 'memex' and rc != 5:                     # rc 5 = не дождались очереди, нагрузку не давали
        r.tg(f'🧊 <b>Memex</b>: локальный разбор <b>{r.code}</b> закончен (rc={rc}) — нагрузка снята.')
    # --no-doc: хвост цепочки считаем по тому же набору, что и выбрасываем, иначе автономный прогон
    # ждёт стадию, которую сам же и выкинул, и 🏁 не приходит
    last = [n for n in names if not (a.no_doc and n in NO_DOC_STAGES)][-1]
    if autonomous and not r.dry and rc == 0 and sel and sel[-1] == last:
        (r.ctl / 'AUTONOMOUS').unlink(missing_ok=True)
        r.tg(f'🏁 <b>{r.code}</b>: автономный разбор на Memex закончен целиком — ТЗ, таймлайн ревью и бриф готовы. '
             f'На маке: review.py memex pull --all')
    print_status(r)
    return rc


# ══════════════════════════════════════════════════════════════════════════════
# 3. status / ticket / docs
# ══════════════════════════════════════════════════════════════════════════════

SYM = {'done': '✅', 'running': '▶ ', 'failed': '✗ ', 'warn': '⚠️', 'awaiting_cloud': '☁️', 'blocked_gui': '🖐', 'skipped': '· ', 'todo': '· '}


def print_status(r: Review):
    lines = [f'{r.code} · {r.mode} · кат {r.cut} · версия кода {version()} · {now()}', '=' * 72]
    cur = r.inputs_hash()
    for name, host, fn, vfn, gate in stages_for(r):
        st = r.st(name)
        drift = ' ⚠ вход изменился' if st.get('status') == 'done' and st.get('inputs_hash') and st['inputs_hash'] != cur else ''
        lines.append(f'{SYM.get(st.get("status", "todo"), "· ")} {name:14s} {host:5s} {st.get("msg", "")[:60]}{drift}')
    pend = pending_batches(r)
    if pend:
        lines.append(f'☁️ облако: ждут {len(pend)} пакетов — {", ".join(pend[:6])}')
    nxt = next((n for n, *_ in stages_for(r) if r.st(n).get('status') not in ('done', 'warn')), None)
    lines.append(f'→ следующая стадия: {nxt or "всё готово"}')
    if r.S.get('edits', {}).get('at'):
        lines.append(f'правки Романа сняты: {r.S["edits"]["at"]}')
    for ledger in (r.work / 'feedback_grants.json', r.work / 'tz_grants.json',
                   r.work / 'chapters_grants.json'):                             # у каждой вкладки свой журнал
        if not ledger.exists():
            continue
        try:
            n_open = len(json.loads(ledger.read_text(encoding='utf-8')).get('open') or [])
        except Exception:
            n_open = '? (журнал не читается)'
        if n_open:
            lines.append(f'⚠️ незакрытые временные доступы к кадрам ({ledger.name}): {n_open} — выполни '
                         f'python3 {SHARED / "doc_images.py"} --revoke-ledger {ledger}')
    print('\n'.join(lines))


def write_ticket(r: Review):
    st = r.S['stages']
    stages = stages_for(r)
    nxt = next((n for n, *_ in stages if st.get(n, {}).get('status') not in ('done', 'warn')), None)
    card = r.card
    L = [f'# {r.code} · {card.get("project_name", r.root.name)} — REVIEW_STATE ({r.mode}, кат {r.cut})',
         f'_генерится `review.py ticket`; обновлено {now()}; версия кода {version()}_', '',
         '## Запуск в новом чате', '```',
         f'/review {r.code}',
         f'python3 ~/YTAI/scripts/05_editing/0509_review_cycle/review.py status --project "{r.root}"',
         f'python3 ~/YTAI/scripts/05_editing/0509_review_cycle/review.py resume --project "{r.root}"', '```', '',
         '## Факты', f'- проект: `{r.root}`', f'- канал: {card.get("channel")} · режим: {r.mode} · кат: {card.get("src", "")} ({card.get("duration_sec", "?")} с)',
         f'- транскрипт: `{card.get("words", "")}` · главы: {len(card.get("chapters", []))}',
         f'- док: `{card.get("doc_id", "")}` · вкладки: «{card.get("tab_title", "")}», «{card.get("nav_tab", "")}»',
         f'- Drive: материалы `{card.get("materials_id", "")}` · проект `{card.get("project_folder_id", "")}`',
         f'- фильм: {card.get("film", "")}', '', '## Состояние стадий', '| стадия | хост | статус | результат |', '|---|---|---|---|']
    for name, host, *_ in stages:
        s = st.get(name, {})
        L.append(f'| {name} | {host} | {SYM.get(s.get("status", "todo"), "·").strip()} {s.get("status", "todo")} | {s.get("msg", "")[:70]} |')
    L += ['', f'## Следующий шаг', f'- {nxt or "всё готово — отдать Роману бриф и ссылки"}']
    pend = pending_batches(r)
    if pend:
        L += [f'- облако ждёт {len(pend)} пакетов: `review.py cloud judge --print-call --project "{r.root}"` → Workflow → '
              f'`review.py cloud collect --run <runId> --project "{r.root}"` → `review.py resume`']
    if card.get('notes'):
        L += ['', '## Грабли проекта'] + [f'- {n}' for n in card['notes']]
    if r.S.get('notes'):
        L += ['', '## Последние заметки цепочки'] + [f'- {n}' for n in r.S['notes'][-8:]]
    L += ['', '## Готово, когда', '- селфчек ALL OK · candidates.json · все облачные пакеты done · pravki обновлены',
          '- mock 0 ошибок · вкладки дока ALL PASS · doc QA 0 high · бриф ушёл в Telegram',
          '- секвенция построена в Premiere (кнопка Build — Роман)']
    (r.review_dir / 'REVIEW_STATE.md').write_text('\n'.join(L) + '\n', encoding='utf-8')


def stage_table_md(mode: str) -> str:
    stages = STAGES_MONTAGE if mode == 'montage_tz' else STAGES_CUT
    L = ['| # | стадия | хост | инструмент | гейт |', '|---|---|---|---|---|']
    for i, (name, host, *_r) in enumerate(stages, 1):
        d = STAGE_DESC.get(name, ('', ''))
        L.append(f'| {i} | {name} | {host} | {d[0]} | {d[1]} |')
    return '\n'.join(L)


def cmd_docs() -> int:
    md = ('<!-- stages:begin -->\n### Стадии cut_review (генерится `review.py docs`)\n' + stage_table_md('cut_review') +
          '\n\n### Стадии montage_tz\n' + stage_table_md('montage_tz') + '\n<!-- stages:end -->')
    targets = [ROOT / 'README.md', Path.home() / 'RYA/yt-rya-ae/web/kb/review-cycle/index.html']
    for t in targets:
        if not t.exists():
            print(f'нет {t} — пропуск')
            continue
        txt = t.read_text(encoding='utf-8')
        if '<!-- stages:begin -->' not in txt:
            print(f'{t.name}: нет маркеров stages:begin/end — вставь их, где должна быть таблица')
            continue
        body = md
        if t.suffix == '.html':
            body = '<!-- stages:begin -->\n' + md_table_html(md) + '\n<!-- stages:end -->'
        new = re.sub(r'<!-- stages:begin -->.*?<!-- stages:end -->', lambda m: body, txt, flags=re.S)
        t.write_text(new, encoding='utf-8')
        print(f'{t}: таблица стадий обновлена')
    return 0


def md_table_html(md: str) -> str:
    out = []
    for block in md.split('\n\n'):
        rows = [ln for ln in block.splitlines() if ln.startswith('|')]
        head = [ln for ln in block.splitlines() if ln.startswith('###')]
        if head:
            out.append(f'<h3>{head[0][4:].strip()}</h3>')
        if not rows:
            continue
        cells = [[c.strip() for c in r.strip('|').split('|')] for r in rows if not re.match(r'^\|[-| ]+\|$', r)]
        # .tbl — скроллер: без него длинный токен в «инструменте» выдавливает таблицу за карточку
        # и даёт горизонтальный скролл всей странице вместе со sticky-шапкой (проверка на 375 px).
        out.append('<div class="tbl"><table class="stages"><thead><tr>' + ''.join(f'<th>{c}</th>' for c in cells[0]) + '</tr></thead><tbody>' +
                   ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in cells[1:]) + '</tbody></table></div>')
    return '\n'.join(out)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Команды
# ══════════════════════════════════════════════════════════════════════════════

def sub(argv, env=None, check=False) -> int:
    return subprocess.run([str(a) for a in argv], env=env).returncode


def cmd_init(a) -> int:
    root = Path(a.project).expanduser()
    if not root.is_dir():
        root = resolve_project(a.project)
    review_dir = root / '00_Setup' / '05_Review'
    review_dir.mkdir(parents=True, exist_ok=True)
    ct = SHARED / 'card_tools.py'
    if a.from_prep_config:
        rc = sub([PY, ct, 'from-prep', a.from_prep_config, '--project-dir', root, '--channel', a.channel, '--mode', a.mode,
                 '--cut-version', a.cut_version] + (['--force'] if a.force else []))
    else:
        rc = sub([PY, ct, 'new', '--project-dir', root, '--channel', a.channel, '--mode', a.mode, '--cut-version', a.cut_version]
                 + (['--force'] if a.force else []))
    if rc != 0:
        return rc
    card_p = review_dir / 'review_card.json'
    card = json.loads(card_p.read_text(encoding='utf-8'))
    if a.cut:
        if a.cut.startswith('gdrive') or ':' in a.cut.split('/')[0]:
            card['cut_drive'] = a.cut
            card['src'] = f'cut/{Path(a.cut).name}'
        else:
            card['src'] = a.cut
        card_p.write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding='utf-8')
    r = Review(root)
    r.save()
    write_ticket(r)
    print(f'готово: {card_p}\n       {review_dir / "review_state.json"}\n       {review_dir / "REVIEW_STATE.md"}')
    return 0


def cmd_cloud(r: Review, a) -> int:
    env = r.env()
    if a.what == 'judge':
        if a.print_call:
            return sub([PY, CLOUD_DIR / 'pack.py', '--print-call'], env)
        return sub([PY, CLOUD_DIR / 'pack.py'], env)
    if a.what == 'collect':
        argv = [PY, CLOUD_DIR / 'collect.py'] + (['--run', a.run] if a.run else []) + (['--session', a.session] if a.session else [])
        rc = sub(argv, env)
        if rc == 0:
            # тот же легаси-файл, что пишет стадия cloud: s10_format_tz / review_page / doc_tab_review_v1 читают
            # audit_findings_v6.json. Без этого ручной collect + `run --from apply` (в обход стадии cloud) роняет
            # format_tz на пустом месте — 22.09.2026, YTCR04 v5.
            sub([PY, CLOUD_DIR / 'collect.py', '--emit-legacy'], env)
            r.st('cloud')['status'] = 'todo'
            r.save()
            print('все пакеты собраны → review.py resume продолжит с apply')
        return rc
    if a.what == 'salvage':
        argv = [PY, CLOUD_DIR / 'salvage.py'] + (['--session', a.session] if a.session else ['--latest'])
        return sub(argv, env)
    if a.what == 'cost':
        argv = [PY, CLOUD_DIR / 'salvage.py', '--cost'] + (['--session', a.session] if a.session else [])
        return sub(argv, env)
    if a.what == 'feedback':
        if getattr(a, 'apply', False):
            rc = sub([PY, SHARED / 'feedback_call.py', '--apply'], env)
            if rc == 0:
                r.S['surfaces']['feedback'] = {'at': now(), 'cloud': 'applied'}
                r.st('feedback').update(status='done', msg='ответ сверщика влит (cloud feedback --apply)', finished=now())
                r.save()
                print('ответ сверщика влит → review.py resume продолжит со страницы (feedback_page)')
            elif rc == 2:
                print('ответ сверщика не подходит к текущему пакету — review.py run --only feedback отложит его и напечатает новый вызов')
            return rc
        return sub([PY, SHARED / 'feedback_call.py', '--print-call'], env)
    if a.what in ('verdict', 'structure'):
        script = CLOUD_DIR / ('wf_verdict_doc.js' if a.what == 'verdict' else 'wf_structure_src.js')
        print(f'Workflow({{scriptPath: "{script}", args: {{card: "{r.card_path}"}}}})')
        return 0
    raise SystemExit(f'cloud: неизвестная команда {a.what}')


def cmd_edits(r: Review) -> int:
    """Правки Романа в доке → pravki. SINCE = момент последней записи вкладки ТЗ (из стейта), в ISO UTC —
    s13 сравнивает с modifiedTime ревизий Drive; без него правки считались бы с чужой даты."""
    argv = [PY, STAGES_DIR / 's13_doc_edits.py']
    at = (r.S['surfaces'].get('doc_tz') or {}).get('at') or r.card.get('tab_built_at')
    if at and 'T' not in str(at):
        from datetime import timezone
        try:
            at = datetime.strptime(at, '%Y-%m-%d %H:%M:%S').astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            pass
    if at:
        argv.append(str(at))
    else:
        print('вкладка ТЗ этим проектом ещё не писалась (нет surfaces.doc_tz.at) — снимать правки не с чего')
        return 0
    rc = sub(argv, r.env())
    if rc == 0:
        r.S['edits'] = {'at': now()}
        r.save()
        write_ticket(r)
    return rc


def cmd_stage(r: Review, a) -> int:
    if a.action == 'status':
        print_status(r)
        return 0
    if a.action == 'pause':
        r.pause_f.write_text(now())
        print(f'PAUSE поставлен: {r.pause_f} (стадии остановятся на границе экрана)')
        return 0
    if a.action == 'resume':
        r.pause_f.unlink(missing_ok=True)
        print('PAUSE снят')
        return 0
    if a.action == 'stop':
        r.stop_f.write_text(now())
        print(f'STOP поставлен: {r.stop_f} — текущий подпроцесс получит SIGTERM, состояние сохранится')
        return 0
    if a.action == 'start':
        return sub([PY, __file__, 'run', '--project', r.root, '--only', a.name])
    raise SystemExit('stage: start|pause|resume|stop|status')


def cmd_memex(r: Review, a) -> int:
    script = MEMEX / f'{a.action}.sh'
    if not script.exists():
        raise SystemExit(f'нет {script} (memex/{a.action}.sh)')
    env = r.env()
    env['YTAI_PROJECT_ROOT'] = str(r.root)
    env['YTAI_CODE'] = r.code
    return sub(['bash', script, r.root] + list(a.rest or []), env)


def cmd_selftest(a) -> int:
    """Регрессия без токенов: синтаксис всех скриптов, импорт стадий с карточкой, маршрутизация, мок-сборка,
    golden-тест монтажного листа. Гонять после любой правки кода, до commit и memex push."""
    import py_compile
    rows = []

    def ok(name, cond, msg=''):
        rows.append((name, bool(cond), msg))
        return bool(cond)

    bad = []
    for p in ROOT.rglob('*.py'):
        if any(x in p.parts for x in ('examples', '_legacy_runners', '_legacy', '__pycache__')):
            continue
        try:
            py_compile.compile(str(p), doraise=True)
        except Exception as e:
            bad.append(f'{p.relative_to(ROOT)}: {str(e)[:80]}')
    ok('python: синтаксис всех стадий', not bad, '; '.join(bad)[:200])
    js = [p for p in ROOT.rglob('*.js') if '_legacy' not in p.parts and 'examples' not in p.parts]
    badjs = [str(p.relative_to(ROOT)) for p in js if subprocess.run([NODE, '--check', str(p)], capture_output=True).returncode != 0]
    ok('node: синтаксис воркфлоу и мок-сборки', not badjs, ', '.join(badjs))
    ok('bash: синтаксис memex/*.sh', all(subprocess.run(['bash', '-n', str(p)], capture_output=True).returncode == 0 for p in MEMEX.glob('*.sh')))

    proj = a.project or '/Volumes/T7-Blue-2-RYA/YTUVI-Projects/YTUVI02_Ruby_Certificate'
    root = Path(proj)
    card = root / '00_Setup/05_Review/review_card.json'
    if card.exists():
        r = Review(root)
        env = r.env()
        rc = subprocess.run([PY, SHARED / 'card_tools.py', 'check', card], capture_output=True, text=True, env=env)
        ok(f'карточка {r.code}: card check', rc.returncode == 0, rc.stdout.strip().splitlines()[-1][:100] if rc.stdout.strip() else '')
        rc = subprocess.run([PY, STAGES_DIR / 'terms_catalog.py'], capture_output=True, text=True, env=env, cwd=str(r.review_dir))
        ok('каталог терминов грузится', rc.returncode == 0, rc.stdout.strip()[:100])
        legacy = r.work / 'audit_findings_v6.json'
        if legacy.exists():
            rc = subprocess.run([PY_LLM if Path(PY_LLM).exists() else PY, STAGES_DIR / 'route_candidates.py', '--eval', str(legacy)],
                                capture_output=True, text=True, env=env, cwd=str(r.review_dir))
            m = re.search(r'ложн\w*[^\d]*(\d+)', rc.stdout)
            ok('маршрутизация --eval (0 ложных auto)', rc.returncode == 0 and (m is None or m.group(1) == '0'),
               (rc.stdout.strip().splitlines()[-1][:110] if rc.stdout.strip() else ''))
        if (r.review_dir / f'{r.code}_review_v6.json').exists():
            rc = subprocess.run([NODE, STAGES_DIR / 'mockbuild_v6.js'], capture_output=True, text=True, env=env, cwd=str(r.review_dir))
            ok('мок-сборка таймлайна: 0 ошибок', rc.returncode == 0 and 'error 0' in rc.stdout, (rc.stdout.strip().splitlines()[-2:][0][:100] if rc.stdout.strip() else ''))
    else:
        rows.append(('карточка проекта для прогона (нет — пропуск)', True, str(card)))

    ev = Path('/Volumes/T9-Black-RYA/YTEVO/YTEVO02_evolution_manifesto')
    golden = ROOT / 'examples/ytevo02/montage.golden.json'
    if (ev / '00_Setup/05_Review/review_card.json').exists() and golden.exists():
        env = dict(os.environ, YTAI_CARD=str(ev / '00_Setup/05_Review/review_card.json'))
        env['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + env.get('PATH', '')
        rc = subprocess.run([PY, MONTAGE / 'build_montage.py'], capture_output=True, text=True, env=env, cwd=str(ev / '00_Setup/05_Review'))
        try:
            g = json.loads(golden.read_text(encoding='utf-8'))
            m = json.loads((ev / '00_Setup/05_Review/montage.json').read_text(encoding='utf-8'))
            m.pop('schema', None); g.pop('schema', None)
            ok('golden YTEVO02: montage.json без расхождений', rc.returncode == 0 and m == g)
        except Exception as e:
            ok('golden YTEVO02: montage.json без расхождений', False, str(e)[:100])
    else:
        rows.append(('golden YTEVO02 (диск не смонтирован — пропуск)', True, ''))

    # (a) RU golden: цепочка YTUVI02 на песочной копии байт-в-байт с эталоном (только при подключённом T7-Blue)
    gold_real = Path('/Volumes/T7-Blue-2-RYA/YTUVI-Projects/YTUVI02_Ruby_Certificate/00_Setup/05_Review')
    gold_json = ROOT / 'examples/ytuvi02_golden/golden.json'
    if gold_real.exists() and gold_json.exists() and (Path.home() / 'YTAI_work/_golden/YTUVI02/_golden_in').exists():
        rc = subprocess.run([PY, SHARED / 'golden.py', 'compare'], capture_output=True, text=True, timeout=1800)
        bad_steps = [ln.strip() for ln in rc.stdout.splitlines() if ln.strip().startswith('✗')]
        ok('golden RU YTUVI02: все шаги идентичны', rc.returncode == 0 and 'ИТОГ golden: идентично' in rc.stdout,
           '; '.join(bad_steps)[:180] or (rc.stdout + rc.stderr).strip()[-180:])
    else:
        rows.append(('golden RU YTUVI02 (диск/эталон не на месте — пропуск)', True, ''))

    # (b) EN-фикстура YTCR: route → облако (канон) → apply → format_tz → review_json → mockbuild во временной копии
    fx = ROOT / 'examples/ytcr_en_fixture/run_fixture.py'
    if fx.exists():
        rc = subprocess.run([PY, fx, '--json'], capture_output=True, text=True, timeout=1800)
        line = next((ln for ln in reversed(rc.stdout.splitlines()) if ln.startswith('ROWS ')), '')
        try:
            for name, good, msg in json.loads(line[5:]):
                ok(name, good, msg)
        except ValueError:
            ok('EN-фикстура YTCR: прогон', False, (rc.stdout + rc.stderr).strip()[-200:])
    else:
        ok('EN-фикстура YTCR: run_fixture.py на месте', False, str(fx))

    # (b2) обратная связь по кату (feedback-v1): самотесты модулей, синтаксис воркфлоу сверщика, офлайн-фикстура.
    # Окружение без YTAI_*: самотесты и фикстура не должны видеть карточку/прошлое ТЗ вызывающей сессии.
    fb_env = {k: v for k, v in os.environ.items() if not k.startswith('YTAI_') and k != 'TZ_TAB'}
    for mod in ('shared/feedback_model.py', 'shared/tz_diff.py', 'shared/feedback_view.py', 'shared/feedback_page.py',
                'shared/feedback_call.py', 'shared/doc_table.py', 'shared/tz_blocks.py', 'shared/doc_images.py',
                'shared/tz_carry.py',
                'stages/doc_tab_feedback_v1.py', 'stages/doc_tab_feedback_v1_verify.py',
                # карта выпуска и предложения экранов (вне конвейера, запускаются руками):
                # ловят переименование видов в bdd_plates.py и схлопывание веток .xmind
                'stages/screens_spots.py', 'stages/screens_proposal.py', 'stages/structure_xmind.py',
                'stages/doc_notes_read.py', 'stages/pravki_page.py'):
        try:
            rc = subprocess.run([PY, ROOT / mod, '--selftest'], capture_output=True, text=True, env=fb_env, timeout=900)
            ok(f'feedback: {mod} --selftest', rc.returncode == 0 and 'SELFTEST OK' in rc.stdout, (rc.stdout + rc.stderr).strip()[-200:])
        except (subprocess.TimeoutExpired, OSError) as e:
            ok(f'feedback: {mod} --selftest', False, f'{type(e).__name__}: {e}'[:200])
    wf = CLOUD_DIR / 'wf_feedback_check.js'
    if shutil.which(NODE):
        rc = subprocess.run([NODE, '--check', str(wf)], capture_output=True, text=True)
        ok('feedback: node --check cloud/wf_feedback_check.js', wf.exists() and rc.returncode == 0, (rc.stderr or str(wf)).strip()[-200:])
    else:
        rows.append(('feedback: node --check cloud/wf_feedback_check.js (node не найден — пропуск)', True, ''))
    fx = ROOT / 'examples/feedback_fixture/run_fixture.py'
    if fx.exists():
        try:
            rc = subprocess.run([PY, fx, '--json'], capture_output=True, text=True, env=fb_env, timeout=1800)
            line = next((ln for ln in reversed(rc.stdout.splitlines()) if ln.startswith('ROWS ')), '')
            try:
                for name, good, msg in json.loads(line[5:]):
                    ok(name, good, msg)
            except ValueError:
                ok('feedback: фикстура — прогон', False, (rc.stdout + rc.stderr).strip()[-200:])
        except (subprocess.TimeoutExpired, OSError) as e:
            ok('feedback: фикстура — прогон', False, f'{type(e).__name__}: {e}'[:200])
    else:
        ok('feedback: examples/feedback_fixture/run_fixture.py на месте', False, str(fx))

    # (c) i18n: таблицы грузятся (владельцы/дубли), у каждого ключа с ru есть en
    try:
        sys.path.insert(0, str(SHARED))
        import i18n as _i18n
        miss = sorted(k for k, v in _i18n.STRINGS.items() if 'ru' in v and 'en' not in v)
        ok(f'i18n: {len(_i18n.STRINGS)} ключей, у каждого ru есть en', not miss, ', '.join(miss[:8]))
    except Exception as e:
        ok('i18n: таблицы грузятся', False, f'{type(e).__name__}: {e}'[:200])

    print(f'selftest {version()} · {now()}')
    for name, good, msg in rows:
        print(f'{"✅" if good else "✗ "} {name}' + (f'  — {msg}' if msg else ''))
    failed = [n for n, g, _ in rows if not g]
    print('ИТОГ:', 'OK' if not failed else f'FAIL {len(failed)}')
    return 0 if not failed else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('selftest'); p.add_argument('--project')

    p = sp.add_parser('init'); p.add_argument('--project', required=True); p.add_argument('--channel', required=True)
    p.add_argument('--mode', default='cut_review', choices=['cut_review', 'montage_tz']); p.add_argument('--cut')
    p.add_argument('--cut-version', default='v1'); p.add_argument('--from-prep-config'); p.add_argument('--force', action='store_true')

    for name in ('status', 'resume', 'edits', 'ticket'):
        q = sp.add_parser(name); q.add_argument('--project', required=True)

    p = sp.add_parser('run'); p.add_argument('--project', required=True); p.add_argument('--from', dest='start')
    p.add_argument('--until'); p.add_argument('--only'); p.add_argument('--force', action='store_true')
    p.add_argument('--force-all', action='store_true'); p.add_argument('--dry-run', action='store_true')
    p.add_argument('--host', default='mac', choices=['mac', 'memex']); p.add_argument('--tg', action='store_true')
    p.add_argument('--no-drive', action='store_true'); p.add_argument('--no-doc', action='store_true')
    p.add_argument('--no-wait-load', action='store_true', help='host memex: не ждать чужой LOAD.json (очередь Memex)')
    p.add_argument('--autonomous', action='store_true',
                   help='host memex: вся цепочка на Memex, облачные проходы — headless Claude (shared/headless_claude.py)')
    p.add_argument('--max-wait-min', type=float, default=480, help='host memex: сколько ждать чужую нагрузку, мин (таймаут → rc 5)')
    p.add_argument('--images', default='none', choices=['none', 'temp'],
                   help='doc_feedback: temp — кадры в док под временным доступом (только с Мака, вручную, после «примени»)')

    p = sp.add_parser('stage'); p.add_argument('--project', required=True); p.add_argument('name')
    p.add_argument('action', choices=['start', 'pause', 'resume', 'stop', 'status'])

    p = sp.add_parser('cloud'); p.add_argument('--project', required=True)
    p.add_argument('what', choices=['judge', 'collect', 'salvage', 'cost', 'verdict', 'structure', 'feedback'])
    p.add_argument('--print-call', action='store_true'); p.add_argument('--run'); p.add_argument('--session')
    p.add_argument('--apply', action='store_true', help='cloud feedback: влить ответ сверщика (cloud/out/feedback_check.json)')

    p = sp.add_parser('memex'); p.add_argument('--project', required=True)
    p.add_argument('action', choices=['push', 'pull', 'start', 'status', 'pause', 'resume', 'stop']); p.add_argument('rest', nargs='*')

    p = sp.add_parser('card'); p.add_argument('--project', required=True); p.add_argument('action', choices=['check'])
    sp.add_parser('docs')

    a = ap.parse_args()
    if a.cmd == 'docs':
        return cmd_docs()
    if a.cmd == 'selftest':
        return cmd_selftest(a)
    if a.cmd == 'init':
        return cmd_init(a)
    root = resolve_project(a.project)
    if not (root / '00_Setup' / '05_Review' / 'review_card.json').exists():
        raise SystemExit(f'нет карточки {root}/00_Setup/05_Review/review_card.json — review.py init …')
    r = Review(root, dry=getattr(a, 'dry_run', False), tg_on=getattr(a, 'tg', False) or os.environ.get('YTAI_TG') == '1')
    if a.cmd == 'status':
        print_status(r)
        return 0
    if a.cmd == 'ticket':
        write_ticket(r)
        print(r.review_dir / 'REVIEW_STATE.md')
        return 0
    if a.cmd == 'resume':
        class A:  # noqa: D401
            start = until = only = None; force = force_all = dry_run = no_drive = no_doc = tg = no_wait_load = False; host = 'mac'
            max_wait_min = 480
        return cmd_run(r, A())
    if a.cmd == 'run':
        return cmd_run(r, a)
    if a.cmd == 'stage':
        return cmd_stage(r, a)
    if a.cmd == 'cloud':
        return cmd_cloud(r, a)
    if a.cmd == 'edits':
        return cmd_edits(r)
    if a.cmd == 'memex':
        return cmd_memex(r, a)
    if a.cmd == 'card':
        return sub([PY, SHARED / 'card_tools.py', 'check', r.card_path])
    return 0


if __name__ == '__main__':
    sys.exit(main())
