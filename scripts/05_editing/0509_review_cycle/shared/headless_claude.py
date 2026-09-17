#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""headless_claude — облачный проход без открытой сессии: `claude -p` как задача launchd в GUI-домене пользователя.

Зачем: автономный режим Memex (`review.py run --host memex --autonomous`) сам выполняет напечатанный
`Workflow({...})` (судья J/F/V/S, вердикт). Через ssh / nohup `claude -p` отвечает «Not logged in»: OAuth лежит
в связке ключей macOS, а она доступна только процессам GUI-сессии. Задача, загруженная `launchctl bootstrap
gui/<uid>`, связку видит. Проверено 17.09.2026 на Memex: тестовый Workflow дошёл до конца за 13 с, агент записал файл.

    python3 headless_claude.py --prompt-file P [--add-dir D ...] [--tools Workflow,Read,Write] [--timeout-min 150]
    python3 headless_claude.py --ping                       # «OK» от модели — вход и launchd в порядке

API: run(prompt, add_dirs, tools, timeout_min, label, stop_file, log_file) -> (rc, text)
Нет launchd (не macOS) или bootstrap отказал → прямой `claude -p` (сработает в сессии с доступом к входу).
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
BASE = HOME / '.cache' / 'ytai' / 'headless'
DEFAULT_TOOLS = 'Workflow,Read,Write,Glob,Grep,WebSearch,WebFetch'
RC_MARK = '__HEADLESS_RC='


def claude_bin() -> str:
    for c in [HOME / '.local/bin/claude', *sorted(glob.glob(str(HOME / '.vscode/extensions/anthropic.claude-code-*/'
                                                                   'resources/native-binary/claude')))[::-1]]:
        if Path(c).exists():
            return str(c)
    return shutil.which('claude') or 'claude'


def extract_workflow_call(text: str) -> str:
    """Из CALL.txt (печать pack.py / verdict_call.py --print-call) — ровно строка `Workflow({...})`."""
    i = text.find('Workflow(')
    j = text.rfind(')')
    if i < 0 or j <= i:
        raise ValueError('в тексте нет вызова Workflow(...)')
    return text[i:j + 1]


def workflow_prompt(call: str, stage: str) -> str:
    return (
        f'You are running unattended on the review machine (no human is watching). Stage: {stage}.\n'
        'Run exactly ONE Workflow now, with exactly these arguments — do not change, shorten or re-order them:\n\n'
        f'{call}\n\n'
        'Wait until that workflow completes (you will be notified). Do not use any other tool yourself and do not '
        'edit files yourself: the workflow agents write their results to disk. When it has finished, print one '
        'final line exactly like: WORKFLOW_DONE runId=<run id> status=<completed|failed>'
    )


def _write_job(label: str, prompt: str, add_dirs, tools: str):
    ts = time.strftime('%Y%m%d-%H%M%S')
    job = BASE / f'{label}-{ts}'
    job.mkdir(parents=True, exist_ok=True)
    (job / 'prompt.txt').write_text(prompt, encoding='utf-8')
    dirs = ' '.join(f'--add-dir "{d}"' for d in add_dirs)
    sh = job / 'run.sh'
    sh.write_text(
        '#!/bin/bash\n'
        'export PATH=/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH\n'
        f'cd "{job}"\n'
        f'"{claude_bin()}" -p --allowedTools "{tools}" --permission-mode acceptEdits {dirs} '
        f'--output-format text < "{job / "prompt.txt"}"\n'
        f'echo "{RC_MARK}$?"\n', encoding='utf-8')
    sh.chmod(0o755)
    return job, sh


def _plist(job: Path, sh: Path, label: str) -> Path:
    p = job / f'{label}.plist'
    out = job / 'out.txt'
    p.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict>'
        f'<key>Label</key><string>{label}</string>'
        f'<key>ProgramArguments</key><array><string>/bin/bash</string><string>{sh}</string></array>'
        f'<key>StandardOutPath</key><string>{out}</string><key>StandardErrorPath</key><string>{out}</string>'
        '<key>RunAtLoad</key><true/></dict></plist>', encoding='utf-8')
    return p


def run(prompt: str, add_dirs=(), tools: str = DEFAULT_TOOLS, timeout_min: float = 150, label: str = 'review',
        stop_file=None, log_file=None, poll_s: int = 10):
    """→ (rc, text). rc 124 — таймаут, 130 — STOP, иначе код выхода claude."""
    safe = re.sub(r'[^A-Za-z0-9_.-]', '-', label)[:40]
    job, sh = _write_job(safe, prompt, add_dirs, tools)
    out = job / 'out.txt'
    uid = os.getuid()
    lab = f'ae.rya.headless.{safe}.{int(time.time())}'

    def log(msg):
        line = f'[{time.strftime("%H:%M:%S")}] headless {safe}: {msg}'
        print(line, flush=True)
        if log_file:
            with open(log_file, 'a', encoding='utf-8') as fh:
                fh.write(line + '\n')

    use_launchd = sys.platform == 'darwin' and shutil.which('launchctl')
    proc = None
    if use_launchd:
        pl = _plist(job, sh, lab)
        b = subprocess.run(['launchctl', 'bootstrap', f'gui/{uid}', str(pl)], capture_output=True, text=True)
        if b.returncode != 0:
            log(f'launchctl bootstrap не прошёл ({b.stderr.strip()[:120]}) — прямой claude -p')
            use_launchd = False
    if not use_launchd:
        proc = subprocess.Popen(['/bin/bash', str(sh)], stdout=open(out, 'w'), stderr=subprocess.STDOUT)
    log(f'старт ({"launchd gui/" + str(uid) if use_launchd else "прямой"}), job {job}')
    t0 = time.time()
    rc = None
    try:
        while True:
            time.sleep(poll_s)
            txt = out.read_text(encoding='utf-8', errors='replace') if out.exists() else ''
            m = re.search(re.escape(RC_MARK) + r'(\d+)', txt)
            if m:
                rc = int(m.group(1))
                break
            if proc is not None and proc.poll() is not None:
                rc = proc.returncode
                break
            if stop_file and Path(stop_file).exists():
                log('STOP — снимаю задачу')
                rc = 130
                break
            if time.time() - t0 > timeout_min * 60:
                log(f'таймаут {timeout_min:.0f} мин — снимаю задачу')
                rc = 124
                break
    finally:
        if use_launchd:
            subprocess.run(['launchctl', 'bootout', f'gui/{uid}/{lab}'], capture_output=True)
        elif proc is not None and proc.poll() is None:
            proc.terminate()
    txt = out.read_text(encoding='utf-8', errors='replace') if out.exists() else ''
    text = re.sub(re.escape(RC_MARK) + r'\d+\s*$', '', txt).strip()
    log(f'rc={rc}, {time.time() - t0:.0f} с · {text.splitlines()[-1][:160] if text else "(пусто)"}')
    if 'Not logged in' in text:
        log('⚠️ claude не залогинен в этом контексте (нужна GUI-сессия пользователя с входом)')
    return rc, text


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--prompt-file')
    ap.add_argument('--ping', action='store_true')
    ap.add_argument('--add-dir', action='append', default=[])
    ap.add_argument('--tools', default=DEFAULT_TOOLS)
    ap.add_argument('--timeout-min', type=float, default=150)
    ap.add_argument('--label', default='cli')
    a = ap.parse_args()
    if a.ping:
        rc, text = run('Reply with the single word OK', tools='Read', timeout_min=3, label='ping', poll_s=3)
        print(text)
        return 0 if rc == 0 and 'OK' in text else 1
    if not a.prompt_file:
        ap.error('--prompt-file или --ping')
    rc, text = run(Path(a.prompt_file).read_text(encoding='utf-8'), a.add_dir, a.tools, a.timeout_min, a.label)
    print(text)
    return rc or 0


if __name__ == '__main__':
    sys.exit(main())
