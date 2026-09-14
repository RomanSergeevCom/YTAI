#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notes_sync — мост «Review notes»: панель UXP → Google Sheet → подбор Claude (обобщение YTUVI01).

Панель кладёт {REVIEW_DIR}/notes/RS_hhmmss.json | note_NNN.json (маркер уже стоит на таймлайне).
Все идентификаторы — из карточки фильма review_card.json (окружение YTAI_CARD), не из констант:
  notes_sheet_id   таблица заметок; пусто → создаётся в sprint_folder_id (или project_folder_id),
                   id пишется в notes/notes_sheet.json (и печатается — перенеси в карточку)
  shots_remote     rclone-remote публичной папки кадров для =IMAGE (пусто → колонка Frame пустая)
  doc_id           док сценария (для сообщений)
  notes_tab?       имя листа (по умолчанию «Notes {cut_version}»)
  render | src     рендер ката для кадров (P.RENDER → P.SRC)
  words            транскрипт {CODE}_{cut}.words.json → колонка «Transcript ±12s»
  chapters/ch_name главы → колонка «Chapter»
Опционально notes/tc_map.json = [[t_seq, offset], …] — карта «раздвинутая секвенция → время ката»
(как r2e у YTUVI01); без него время заметки = время ката.

usage:
  notes_sync.py push                          новые заметки → строки листа (v1-TC, глава, транскрипт, кадр)
  notes_sync.py pull                          строки с комментарием Романа без подбора → JSON в stdout
  notes_sync.py answer <id> "<текст>" [--status done]
  notes_sync.py fmt                           ревью-вёрстка листа (идемпотентно; push вызывает сам)
  notes_sync.py install-autopush [--dry-run] [--throttle 90]
        launchd-вотчер notes/ → push: templates/notes-push.plist.j2 (str.format) →
        ~/Library/LaunchAgents/ae.rya.{project}-notes-push.plist + launchctl bootstrap; лог logs/notes_push.log
  notes_sync.py uninstall-autopush            launchctl bootout + удалить plist

Токен Google — rscore (doctab_lib.access_token, ~/.config/rscore/token.json). Наружу пишут только
push / answer / fmt; install-autopush --dry-run лишь печатает plist.
"""
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from bisect import bisect_right
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'stages'))
from _bootstrap import P, W6, M, REVIEW_DIR  # noqa: E402

NOTES = REVIEW_DIR / 'notes'
FRAMES = NOTES / 'frames'
LOGS = REVIEW_DIR / 'logs'
STATE = NOTES / 'notes_sheet.json'          # id созданной таблицы, если в карточке пусто
LEGACY_STATE = M / 'notes_sheet.json'
TAB = str(P.get('notes_tab') or f'Notes {P.CUT_VERSION}')
TITLE = f'{P.CODE} Review Notes'
HDR = ['ID', 'When', 'Sequence', 'TC', 'v1 TC', 'Chapter', 'Transcript ±12s',
       'Роман — комментарий', 'Claude — подбор', 'Status', 'Frame']
RENDER = Path(P.RENDER or P.SRC) if (P.RENDER or P.SRC) else None
SHOTS_REMOTE = P.SHOTS_REMOTE
LABEL = f'ae.rya.{P.PROJECT}-notes-push'
PLIST = Path.home() / 'Library' / 'LaunchAgents' / f'{LABEL}.plist'
TEMPLATE = ROOT / 'templates' / 'notes-push.plist.j2'
FFMPEG = '/opt/homebrew/bin/ffmpeg' if Path('/opt/homebrew/bin/ffmpeg').exists() else 'ffmpeg'
RCLONE = '/opt/homebrew/bin/rclone' if Path('/opt/homebrew/bin/rclone').exists() else 'rclone'


# ── Google API ───────────────────────────────────────────────────────────────
def api(method, url, body=None):
    from doctab_lib import access_token  # rscore-токен; импорт лениво — dry-run без него работает
    req = urllib.request.Request(url, method=method,
                                 headers={'Authorization': f'Bearer {access_token()}',
                                          'Content-Type': 'application/json'})
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'Google API {e.code}: {e.read().decode("utf-8", "replace")[:600]}') from e


def sheet_url(sid, gid=None):
    return f'https://docs.google.com/spreadsheets/d/{sid}/edit' + (f'#gid={gid}' if gid is not None else '')


def ensure_sheet():
    """id таблицы: карточка → notes/notes_sheet.json → легаси pravki/notes_sheet.json → создать."""
    sid = str(P.get('notes_sheet_id') or '')
    if sid:
        return sid
    for f in (STATE, LEGACY_STATE):
        if f.exists():
            return json.loads(f.read_text(encoding='utf-8'))['id']
    parent = str(P.get('sprint_folder_id') or P.get('project_folder_id') or '')
    if not parent:
        raise SystemExit('В карточке пусты notes_sheet_id и sprint_folder_id/project_folder_id — '
                         'некуда создавать таблицу заметок.')
    created = api('POST', 'https://www.googleapis.com/drive/v3/files?supportsAllDrives=true',
                  {'name': TITLE, 'mimeType': 'application/vnd.google-apps.spreadsheet', 'parents': [parent]})
    sid = created['id']
    meta = api('GET', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}?fields=sheets.properties')
    first = meta['sheets'][0]['properties']['sheetId']
    api('POST', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}:batchUpdate', {'requests': [
        {'updateSheetProperties': {'properties': {'sheetId': first, 'title': TAB}, 'fields': 'title'}}]})
    api('PUT', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/'
        f'{urllib.parse.quote(TAB + "!A1:K1")}?valueInputOption=RAW', {'values': [HDR]})
    NOTES.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({'id': sid, 'gid': first, 'title': TITLE}, ensure_ascii=False))
    print(f'создана таблица: {sheet_url(sid)}\n   → впиши в карточку: "notes_sheet_id": "{sid}"')
    return sid


def ensure_tab(sid, title):
    """gid листа по названию; нет — создать с шапкой."""
    meta = api('GET', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}?fields=sheets.properties')
    for s in meta['sheets']:
        if s['properties']['title'] == title:
            return s['properties']['sheetId']
    r = api('POST', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}:batchUpdate',
            {'requests': [{'addSheet': {'properties': {'title': title, 'index': 0}}}]})
    gid = r['replies'][0]['addSheet']['properties']['sheetId']
    api('PUT', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/'
        f'{urllib.parse.quote(title + "!A1:K1")}?valueInputOption=RAW', {'values': [HDR]})
    print(f'создан лист «{title}» (gid {gid})')
    return gid


def write_sheet_link(sid, gid):
    """notes/sheet_link.txt — панель строит из него ссылку на строку (range=A{N})."""
    NOTES.mkdir(parents=True, exist_ok=True)
    (NOTES / 'sheet_link.txt').write_text(sheet_url(sid, gid), encoding='utf-8')


def col(sid, rng):
    got = api('GET', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/{urllib.parse.quote(rng)}')
    return got.get('values', [])


# ── обогащение: время, глава, транскрипт, кадр ──────────────────────────────
_tcmap = None


def seq2cut(t):
    """Время секвенции → время ката по notes/tc_map.json ([[t_seq, offset], …]); без карты — как есть."""
    global _tcmap
    if _tcmap is None:
        f = NOTES / 'tc_map.json'
        _tcmap = sorted((float(a), float(b)) for a, b in json.loads(f.read_text())) if f.exists() else []
    if not _tcmap:
        return t, ''
    i = bisect_right([a for a, _ in _tcmap], t) - 1
    if i < 0:
        return t, ''
    return t - _tcmap[i][1], ''


_ch = sorted((float(t), n) for t, n in P.CHAPTERS)
_ch_name = P.get('ch_name', {}) or {}


def chapter_at(v1):
    i = bisect_right([a for a, _ in _ch], v1) - 1
    if i < 0:
        return ''
    n = _ch[i][1]
    return f'{n} {_ch_name.get(n, "")}'.strip()


_words = None


def excerpt(v1, pad=12.0, cap=520):
    global _words
    if _words is None:
        try:
            _words = json.loads(Path(P.WORDS).read_text(encoding='utf-8'))['segments']
        except Exception as ex:
            print(f'  транскрипт {P.WORDS}: {ex}')
            _words = []
    segs = [s for s in _words if float(s['end']) >= v1 - pad and float(s['start']) <= v1 + pad]
    txt = ' '.join(str(s.get('text', '')).strip() for s in segs).strip()
    if len(txt) > cap:
        k = txt.find(' ', (len(txt) - cap) // 2)
        txt = '…' + txt[k:k + cap].strip() + '…'
    return txt


def tmm(sec):
    t = int(round(sec))
    return f'{t // 60}:{t % 60:02d}'


def note_frame(n, v1):
    """Кадр рендера @v1 → notes/frames/note{id}.jpg → rclone в shots_remote/notes/ → drive-id или None."""
    if not SHOTS_REMOTE or RENDER is None or not RENDER.exists():
        return None
    FRAMES.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'\W+', '', n['id'])
    jpg = FRAMES / f'note{safe}.jpg'
    if not jpg.exists():
        r = subprocess.run([FFMPEG, '-v', 'error', '-ss', str(v1), '-i', str(RENDER), '-frames:v', '1',
                            '-vf', 'scale=960:-2', '-y', str(jpg)], capture_output=True, text=True)
        if r.returncode != 0 or not jpg.exists():
            print(f'  кадр {n["id"]}: ffmpeg fail {r.stderr[:80]}')
            return None
    remote = f'{SHOTS_REMOTE.rstrip("/")}/notes'
    subprocess.run([RCLONE, 'copyto', str(jpg), f'{remote}/{jpg.name}'], check=True)
    ls = subprocess.run([RCLONE, 'lsjson', remote, '--files-only'], capture_output=True, text=True, check=True)
    ids = {f['Name']: f['ID'] for f in json.loads(ls.stdout)}
    return ids.get(jpg.name)


def all_notes():
    NOTES.mkdir(parents=True, exist_ok=True)
    ns = []
    for f in list(NOTES.glob('RS_*.json')) + list(NOTES.glob('note_*.json')):
        try:
            ns.append(json.loads(f.read_text(encoding='utf-8')))
        except Exception as ex:
            print(f'  {f.name}: битый JSON — {ex}')
    ns.sort(key=lambda n: n.get('ts', ''))
    return ns


def q(v):
    """USER_ENTERED-экранирование: «001»/«2:52» должны остаться текстом, не числом/временем."""
    v = str(v)
    return "'" + v if v and (v[0].isdigit() or v[0] in '=+') else v


# ── вёрстка листа ────────────────────────────────────────────────────────────
def _fmt_col(gid, c0, c1, width, wrap='CLIP', font=10, bold=False, fg=None, bg=None, halign='LEFT', valign='TOP'):
    fmt = {'wrapStrategy': wrap, 'verticalAlignment': valign, 'horizontalAlignment': halign,
           'textFormat': {'fontSize': font, 'bold': bold}}
    if fg:
        fmt['textFormat']['foregroundColor'] = fg
    if bg:
        fmt['backgroundColor'] = bg
    return [
        {'updateDimensionProperties': {
            'range': {'sheetId': gid, 'dimension': 'COLUMNS', 'startIndex': c0, 'endIndex': c1},
            'properties': {'pixelSize': width}, 'fields': 'pixelSize'}},
        {'repeatCell': {
            'range': {'sheetId': gid, 'startRowIndex': 1, 'endRowIndex': 1000, 'startColumnIndex': c0, 'endColumnIndex': c1},
            'cell': {'userEnteredFormat': fmt},
            'fields': 'userEnteredFormat(wrapStrategy,verticalAlignment,horizontalAlignment,textFormat,backgroundColor)'}},
    ]


def cmd_fmt(sid=None, gid=None):
    """Ревью-вёрстка: строки 135px под кадры, перенос, ширины, закреп шапки, фильтр. Идемпотентно."""
    sid = sid or ensure_sheet()
    gid = ensure_tab(sid, TAB) if gid is None else gid
    gray = {'red': 0.45, 'green': 0.45, 'blue': 0.45}
    reqs = [
        {'updateSheetProperties': {'properties': {'sheetId': gid, 'gridProperties': {'frozenRowCount': 1, 'frozenColumnCount': 1}},
                                   'fields': 'gridProperties.frozenRowCount,gridProperties.frozenColumnCount'}},
        {'updateDimensionProperties': {'range': {'sheetId': gid, 'dimension': 'ROWS', 'startIndex': 1, 'endIndex': 1000},
                                       'properties': {'pixelSize': 135}, 'fields': 'pixelSize'}},
        {'updateDimensionProperties': {'range': {'sheetId': gid, 'dimension': 'ROWS', 'startIndex': 0, 'endIndex': 1},
                                       'properties': {'pixelSize': 30}, 'fields': 'pixelSize'}},
        {'repeatCell': {'range': {'sheetId': gid, 'startRowIndex': 0, 'endRowIndex': 1},
                        'cell': {'userEnteredFormat': {'textFormat': {'bold': True, 'fontSize': 10},
                                                       'backgroundColor': {'red': 0.93, 'green': 0.94, 'blue': 0.95},
                                                       'wrapStrategy': 'CLIP', 'verticalAlignment': 'MIDDLE'}},
                        'fields': 'userEnteredFormat(textFormat,backgroundColor,wrapStrategy,verticalAlignment)'}},
        {'setBasicFilter': {'filter': {'range': {'sheetId': gid, 'startRowIndex': 0, 'endRowIndex': 1000,
                                                 'startColumnIndex': 0, 'endColumnIndex': 11}}}},
    ]
    reqs += _fmt_col(gid, 0, 1, 46)                                    # A ID
    reqs += _fmt_col(gid, 1, 2, 100, font=9, fg=gray)                  # B When
    reqs += _fmt_col(gid, 2, 3, 88, font=9, fg=gray)                   # C Sequence
    reqs += _fmt_col(gid, 3, 4, 52, halign='CENTER')                   # D TC
    reqs += _fmt_col(gid, 4, 5, 76, wrap='WRAP', bold=True, halign='CENTER')  # E v1 TC
    reqs += _fmt_col(gid, 5, 6, 118, wrap='WRAP', font=9)              # F Chapter
    reqs += _fmt_col(gid, 6, 7, 380, wrap='WRAP', font=9)              # G Transcript
    reqs += _fmt_col(gid, 7, 8, 300, wrap='WRAP', bg={'red': 1.0, 'green': 0.976, 'blue': 0.77})   # H Роман
    reqs += _fmt_col(gid, 8, 9, 340, wrap='WRAP', bg={'red': 0.945, 'green': 0.973, 'blue': 0.913})  # I Claude
    reqs += _fmt_col(gid, 9, 10, 64, halign='CENTER', valign='MIDDLE')  # J Status
    reqs += _fmt_col(gid, 10, 11, 240)                                 # K Frame
    api('POST', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}:batchUpdate', {'requests': reqs})
    print('fmt: применена ревью-вёрстка (строки 135px, перенос, фильтр, закреп)')


# ── команды ──────────────────────────────────────────────────────────────────
def cmd_push():
    import fcntl
    NOTES.mkdir(parents=True, exist_ok=True)
    lk = open(NOTES / '.push.lock', 'w')
    fcntl.flock(lk, fcntl.LOCK_EX)              # launchd-вотчер может дёрнуть push параллельно с ручным
    sid = ensure_sheet()
    gid = ensure_tab(sid, TAB)
    write_sheet_link(sid, gid)
    api('PUT', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/'
        f'{urllib.parse.quote(TAB + "!A1:K1")}?valueInputOption=RAW', {'values': [HDR]})
    have = {row[0] for row in col(sid, f'{TAB}!A2:A') if row}
    dur = float(P.get('duration_sec') or 0) or None
    new = []
    for n in all_notes():
        if n['id'] in have:
            continue
        sec = float(n.get('tc_sec', 0))
        v1, mark = seq2cut(sec)
        if dur and v1 > dur:
            v1, mark = dur, ' (хвост за концом ката)'
        did = note_frame(n, v1)
        img = f'=IMAGE("https://drive.google.com/uc?export=view&id={did}")' if did else ''
        new.append([q(n['id']), q(str(n.get('ts', ''))[:16].replace('T', ' ')), n.get('sequence', ''), q(n.get('tc', '')),
                    q(tmm(v1) + mark), chapter_at(v1), q(excerpt(v1)), q(n.get('comment', '')), '', '', img])
    if new:
        api('POST', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/'
            f'{urllib.parse.quote(TAB + "!A1")}:append?valueInputOption=USER_ENTERED', {'values': new})
    print(f'push: «{TAB}» +{len(new)} (было {len(have)})')
    cmd_fmt(sid, gid)
    print(sheet_url(sid, gid))


def cmd_pull():
    sid = ensure_sheet()
    rows = col(sid, f'{TAB}!A2:J')
    todo = []
    for i, row in enumerate(rows, start=2):
        row += [''] * (10 - len(row))
        if row[0] and row[7].strip() and not row[8].strip():
            todo.append({'row': i, 'id': row[0], 'sequence': row[2], 'tc': row[3], 'v1_tc': row[4],
                         'chapter': row[5], 'transcript': row[6], 'comment': row[7]})
    print(json.dumps(todo, ensure_ascii=False, indent=1))
    return todo


def cmd_answer(note_id, text, status='done'):
    sid = ensure_sheet()
    for i, row in enumerate(col(sid, f'{TAB}!A2:A'), start=2):
        if row and row[0] == note_id:
            api('PUT', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/'
                f'{urllib.parse.quote(f"{TAB}!I{i}:J{i}")}?valueInputOption=RAW', {'values': [[text, status]]})
            print(f'answer → строка {i} ({note_id})')
            return
    raise SystemExit(f'нет строки {note_id} на листе «{TAB}»')


def render_plist(throttle=90):
    """templates/notes-push.plist.j2 → текст plist (str.format, значения XML-экранированы)."""
    # стабильный путь brew (переживает апгрейд python@3.x), иначе — текущий интерпретатор
    python = '/opt/homebrew/bin/python3' if Path('/opt/homebrew/bin/python3').exists() else (sys.executable or 'python3')
    vals = {'label': LABEL, 'python': python, 'script': str(Path(__file__).resolve()),
            'notes_dir': str(NOTES), 'throttle': int(throttle),
            'path_env': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin',
            'card': str(P.CARD_PATH), 'log': str(LOGS / 'notes_push.log')}
    return TEMPLATE.read_text(encoding='utf-8').format(**{k: (xml_escape(v) if isinstance(v, str) else v) for k, v in vals.items()})


def cmd_install(dry_run=False, throttle=90):
    text = render_plist(throttle)
    if dry_run:
        print(text)
        print(f'# dry-run: plist НЕ записан ({PLIST}); notes: {NOTES}', file=sys.stderr)
        return
    NOTES.mkdir(parents=True, exist_ok=True)     # WatchPaths должен существовать, иначе первый триггер — его создание
    LOGS.mkdir(parents=True, exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_text(text, encoding='utf-8')
    uid = os.getuid()
    subprocess.run(['launchctl', 'bootout', f'gui/{uid}/{LABEL}'], capture_output=True)
    r = subprocess.run(['launchctl', 'bootstrap', f'gui/{uid}', str(PLIST)], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'launchctl bootstrap: rc={r.returncode} {r.stderr.strip()}')
    print(f'autopush установлен: {PLIST}\n   WatchPaths {NOTES} · throttle {throttle} с · лог {LOGS / "notes_push.log"}')


def cmd_uninstall():
    uid = os.getuid()
    r = subprocess.run(['launchctl', 'bootout', f'gui/{uid}/{LABEL}'], capture_output=True, text=True)
    if PLIST.exists():
        PLIST.unlink()
    print(f'autopush снят: {LABEL} (bootout rc={r.returncode}), plist {"удалён" if not PLIST.exists() else "остался"}')


def main(argv):
    cmd = argv[0] if argv else 'push'
    flags = [x for x in argv[1:] if x.startswith('--')]
    pos = [x for x in argv[1:] if not x.startswith('--')]
    if cmd == 'push':
        cmd_push()
    elif cmd == 'pull':
        cmd_pull()
    elif cmd == 'fmt':
        cmd_fmt()
    elif cmd == 'answer':
        if len(pos) < 2:
            raise SystemExit('usage: notes_sync.py answer <id> "<текст>" [--status done]')
        st = 'done'
        if '--status' in argv:
            st = argv[argv.index('--status') + 1]
        cmd_answer(pos[0], pos[1], st)
    elif cmd == 'install-autopush':
        th = int(argv[argv.index('--throttle') + 1]) if '--throttle' in argv else 90
        cmd_install(dry_run='--dry-run' in flags, throttle=th)
    elif cmd == 'uninstall-autopush':
        cmd_uninstall()
    else:
        raise SystemExit('usage: notes_sync.py push|pull|fmt|answer <id> <text> [--status S]|'
                         'install-autopush [--dry-run] [--throttle N]|uninstall-autopush')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
