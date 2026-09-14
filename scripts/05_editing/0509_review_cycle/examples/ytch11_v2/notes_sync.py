#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Мост «Review notes» YTCH11: панель UXP → Google Sheet → подбор Claude.

Панель кладёт {project}/00_Setup/05_Review/notes/RS_hhmmss.json (маркер уже на
таймлайне). Этот скрипт:
  push   — новые заметки → строки листа «Notes» (v2-TC, глава, транскрипт ±12с, кадр);
  pull   — строки, где есть комментарий Романа и нет подбора → JSON для Claude;
  answer — записать подбор: notes_sync.py answer RS#hhmmss "текст" [--status done]
  fmt    — ревью-вёрстка листа (идемпотентно, гоняется после каждого push).

Секвенция ревью YTCH11 (Review_v2_full) — рендер v2 целиком БЕЗ раздвижки,
поэтому tc плейхеда == время рендера v2 (маппинга r2e нет — в отличие от YTUVI01).
Таблица создаётся при первом push в Drive-папке проекта (YTCH S3/YTCH11_Liza_Vitalik);
id хранится в notes_sheet.json рядом. Токен: rscore (doctab_lib).
Кадры нот: ffmpeg из рендера → публичная папка gdrive:YTCH11_review_frames → =IMAGE.
Адаптация YTUVI01 ~/Downloads/YTUVI01_Sonya_cut/work/montage/notes_sync.py."""
import json
import re
import sys
import urllib.parse
import urllib.request
from bisect import bisect_right
from pathlib import Path

sys.path.insert(0, str(Path.home() / 'YTAI/scripts/999_extra/ytuvi_doctabs'))
from doctab_lib import access_token  # noqa: E402

M = Path(__file__).parent
PROJECT = Path('/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik')
NOTES = PROJECT / '00_Setup/05_Review/notes'
WORDS = PROJECT / '00_Setup/05_Review/YTCH11_v2.words.json'
STATE = M / 'notes_sheet.json'
PARENT = '1wU-uPYIJojbZPjr54Ws3eswYZGGErmsS'   # YTCH S3/YTCH11_Liza_Vitalik
TITLE = 'YTCH11 Review Notes'
TAB = 'Notes'
HDR = ['ID', 'When', 'Sequence', 'TC', 'v2 TC', 'Chapter', 'Transcript ±12s',
       'Роман — комментарий', 'Claude — подбор', 'Status', 'Frame']
RENDER = PROJECT / '03_Exports/YTCH11_v2_Liza_Vitalik.mp4'
SHOTS_REMOTE = 'gdrive:YTCH11_review_frames'


def api(method, url, body=None):
    req = urllib.request.Request(url, method=method,
                                 headers={'Authorization': f'Bearer {access_token()}',
                                          'Content-Type': 'application/json'})
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(req, data) as r:
        return json.load(r)


def sheet_url(sid):
    return f'https://docs.google.com/spreadsheets/d/{sid}/edit'


def ensure_sheet():
    if STATE.exists():
        return json.loads(STATE.read_text())['id']
    created = api('POST', 'https://www.googleapis.com/drive/v3/files?supportsAllDrives=true',
                  {'name': TITLE, 'mimeType': 'application/vnd.google-apps.spreadsheet',
                   'parents': [PARENT]})
    sid = created['id']
    meta = api('GET', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}?fields=sheets.properties')
    first = meta['sheets'][0]['properties']['sheetId']
    api('POST', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}:batchUpdate', {'requests': [
        {'updateSheetProperties': {'properties': {'sheetId': first, 'title': TAB},
                                   'fields': 'title'}},
        {'updateDimensionProperties': {
            'range': {'sheetId': first, 'dimension': 'COLUMNS', 'startIndex': 6, 'endIndex': 9},
            'properties': {'pixelSize': 340}, 'fields': 'pixelSize'}},
    ]})
    api('PUT', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/'
        f'{urllib.parse.quote(TAB + "!A1:K1")}?valueInputOption=RAW',
        {'values': [HDR]})
    STATE.write_text(json.dumps({'id': sid, 'gid': first}))
    print('создана таблица:', sheet_url(sid))
    return sid


def write_sheet_link(sid):
    """sheet_link.txt в notes/ — панель строит из него ссылку на строку (range=A{N})."""
    st = json.loads(STATE.read_text())
    gid = st.get('gid')
    if gid is None:
        meta = api('GET', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}?fields=sheets.properties')
        gid = next(s['properties']['sheetId'] for s in meta['sheets']
                   if s['properties']['title'] == TAB)
        st['gid'] = gid
        STATE.write_text(json.dumps(st))
    NOTES.mkdir(exist_ok=True)
    (NOTES / 'sheet_link.txt').write_text(f'{sheet_url(sid)}#gid={gid}')


# ---------- обогащение ----------
_ch = [(c['tc_sec'], c['name']) for c in
       json.loads((M / 'chapters_cards.json').read_text())]
_ch.sort()
_words = json.loads(WORDS.read_text())['segments']


def chapter_at(v2):
    i = bisect_right([a for a, _ in _ch], v2) - 1
    return _ch[i][1] if i >= 0 else ''


def excerpt(v2, pad=12.0, cap=520):
    segs = [s for s in _words if s['end'] >= v2 - pad and s['start'] <= v2 + pad]
    txt = ' '.join(s['text'].strip() for s in segs).strip()
    if len(txt) > cap:
        k = txt.find(' ', (len(txt) - cap) // 2)
        txt = '…' + txt[k:k + cap].strip() + '…'
    return txt


def tmm(sec):
    t = int(round(sec))
    return f'{t // 60}:{t % 60:02d}'


def col(sid, rng):
    got = api('GET', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/'
              f'{urllib.parse.quote(rng)}')
    return got.get('values', [])


def note_frame(n, v2):
    """Кадр к заметке: рендер v2 @ v2_sec → публичная папка Drive → drive-id."""
    import subprocess
    frames = NOTES / 'frames'
    frames.mkdir(exist_ok=True)
    safe = re.sub(r'\W+', '', n['id'])
    jpg = frames / f'note{safe}.jpg'
    if not jpg.exists():
        if not RENDER.exists():
            return None
        r = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(v2), '-i', str(RENDER),
                            '-frames:v', '1', '-vf', 'scale=960:-2', '-y', str(jpg)],
                           capture_output=True, text=True)
        if r.returncode != 0 or not jpg.exists():
            print(f'  кадр {n["id"]}: ffmpeg fail {r.stderr[:80]}')
            return None
    subprocess.run(['rclone', 'copyto', str(jpg), f'{SHOTS_REMOTE}/{jpg.name}'], check=True)
    ls = subprocess.run(['rclone', 'lsjson', SHOTS_REMOTE, '--files-only'],
                        capture_output=True, text=True, check=True)
    ids = {f['Name']: f['ID'] for f in json.loads(ls.stdout)}
    return ids.get(jpg.name)


def all_notes():
    NOTES.mkdir(exist_ok=True)
    ns = []
    for f in list(NOTES.glob('RS_*.json')) + list(NOTES.glob('note_*.json')):
        ns.append(json.loads(f.read_text()))
    ns.sort(key=lambda n: n.get('ts', ''))
    return ns


def q(v):
    """USER_ENTERED-экранирование: «001»/«2:52» должны остаться текстом, не числом/временем."""
    v = str(v)
    return "'" + v if v and (v[0].isdigit() or v[0] in "=+") else v


def _fmt_col(gid, c0, c1, width, wrap='CLIP', font=10, bold=False, fg=None,
             bg=None, halign='LEFT', valign='TOP'):
    """Пара запросов на колонку: ширина + формат данных (строки 2..1000)."""
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
            'range': {'sheetId': gid, 'startRowIndex': 1, 'endRowIndex': 1000,
                      'startColumnIndex': c0, 'endColumnIndex': c1},
            'cell': {'userEnteredFormat': fmt},
            'fields': 'userEnteredFormat(wrapStrategy,verticalAlignment,horizontalAlignment,'
                      'textFormat,backgroundColor)'}},
    ]


def cmd_fmt():
    """Ревью-вёрстка листа: высокие строки под кадры, перенос текста, ширины по
    содержимому, закреп шапки, фильтр. Идемпотентно — гоняется после каждого push."""
    sid = ensure_sheet()
    gid = json.loads(STATE.read_text())['gid']
    gray = {'red': 0.45, 'green': 0.45, 'blue': 0.45}
    reqs = [
        # шапка + первая колонка закреплены; строки 135px (кадр 240x135 впритык)
        {'updateSheetProperties': {'properties': {'sheetId': gid, 'gridProperties': {
            'frozenRowCount': 1, 'frozenColumnCount': 1}},
            'fields': 'gridProperties.frozenRowCount,gridProperties.frozenColumnCount'}},
        {'updateDimensionProperties': {
            'range': {'sheetId': gid, 'dimension': 'ROWS', 'startIndex': 1, 'endIndex': 1000},
            'properties': {'pixelSize': 135}, 'fields': 'pixelSize'}},
        {'updateDimensionProperties': {
            'range': {'sheetId': gid, 'dimension': 'ROWS', 'startIndex': 0, 'endIndex': 1},
            'properties': {'pixelSize': 30}, 'fields': 'pixelSize'}},
        {'repeatCell': {
            'range': {'sheetId': gid, 'startRowIndex': 0, 'endRowIndex': 1},
            'cell': {'userEnteredFormat': {
                'textFormat': {'bold': True, 'fontSize': 10},
                'backgroundColor': {'red': 0.93, 'green': 0.94, 'blue': 0.95},
                'wrapStrategy': 'CLIP', 'verticalAlignment': 'MIDDLE'}},
            'fields': 'userEnteredFormat(textFormat,backgroundColor,wrapStrategy,verticalAlignment)'}},
        # фильтр по шапке (сортировка по v2 TC / фильтр по главе и статусу — из дропдаунов)
        {'setBasicFilter': {'filter': {'range': {
            'sheetId': gid, 'startRowIndex': 0, 'endRowIndex': 1000,
            'startColumnIndex': 0, 'endColumnIndex': 11}}}},
    ]
    reqs += _fmt_col(gid, 0, 1, 46)                                    # A ID
    reqs += _fmt_col(gid, 1, 2, 100, font=9, fg=gray)                  # B When
    reqs += _fmt_col(gid, 2, 3, 88, font=9, fg=gray)                   # C Sequence
    reqs += _fmt_col(gid, 3, 4, 52, halign='CENTER')                   # D TC
    reqs += _fmt_col(gid, 4, 5, 76, wrap='WRAP', bold=True, halign='CENTER')  # E v2 TC
    reqs += _fmt_col(gid, 5, 6, 118, wrap='WRAP', font=9)              # F Chapter
    reqs += _fmt_col(gid, 6, 7, 380, wrap='WRAP', font=9)              # G Transcript
    reqs += _fmt_col(gid, 7, 8, 300, wrap='WRAP',                      # H Роман — жёлтый фон
                     bg={'red': 1.0, 'green': 0.976, 'blue': 0.77})
    reqs += _fmt_col(gid, 8, 9, 340, wrap='WRAP',                      # I Claude — подбор
                     bg={'red': 0.945, 'green': 0.973, 'blue': 0.913})
    reqs += _fmt_col(gid, 9, 10, 64, halign='CENTER', valign='MIDDLE')  # J Status
    reqs += _fmt_col(gid, 10, 11, 240)                                 # K Frame
    api('POST', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}:batchUpdate',
        {'requests': reqs})
    print('fmt: применена ревью-вёрстка (строки 135px, перенос, фильтр, закреп)')


def cmd_push():
    # сериализация: launchd-вотчер может дёрнуть push параллельно с ручным запуском
    import fcntl
    _lk = open(M / '.push.lock', 'w')
    fcntl.flock(_lk, fcntl.LOCK_EX)
    sid = ensure_sheet()
    write_sheet_link(sid)
    api('PUT', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/'
        f'{urllib.parse.quote(TAB + "!A1:K1")}?valueInputOption=RAW', {'values': [HDR]})
    have = {row[0] for row in col(sid, f'{TAB}!A2:A') if row}
    new = []
    for n in all_notes():
        if n['id'] in have:
            continue
        v2 = n['tc_sec']         # Review_v2_full = рендер целиком, маппинга нет
        did = note_frame(n, v2)
        img = f'=IMAGE("https://drive.google.com/uc?export=view&id={did}")' if did else ''
        new.append([q(n['id']), q(n['ts'][:16].replace('T', ' ')), n['sequence'], q(n['tc']),
                    q(tmm(v2)), chapter_at(v2), q(excerpt(v2)),
                    q(n.get('comment', '')), '', '', img])
    if new:
        api('POST', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/'
            f'{urllib.parse.quote(TAB + "!A1")}:append?valueInputOption=USER_ENTERED',
            {'values': new})
    print(f'push: +{len(new)} (в листе было {len(have)})')
    cmd_fmt()
    print(sheet_url(sid))


def cmd_pull():
    sid = ensure_sheet()
    rows = col(sid, f'{TAB}!A2:J')
    todo = []
    for i, row in enumerate(rows, start=2):
        row += [''] * (10 - len(row))
        if row[0] and row[7].strip() and not row[8].strip():
            todo.append({'row': i, 'id': row[0], 'sequence': row[2], 'tc': row[3],
                         'v2_tc': row[4], 'chapter': row[5], 'transcript': row[6],
                         'comment': row[7]})
    print(json.dumps(todo, ensure_ascii=False, indent=1))
    return todo


def cmd_answer(note_id, text, status='done'):
    sid = ensure_sheet()
    rows = col(sid, f'{TAB}!A2:A')
    for i, row in enumerate(rows, start=2):
        if row and row[0] == note_id:
            api('PUT', f'https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/'
                f'{urllib.parse.quote(f"{TAB}!I{i}:J{i}")}?valueInputOption=RAW',
                {'values': [[text, status]]})
            print(f'answer → строка {i} ({note_id})')
            return
    raise SystemExit(f'нет строки {note_id}')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'push'
    if cmd == 'push':
        cmd_push()
    elif cmd == 'pull':
        cmd_pull()
    elif cmd == 'fmt':
        cmd_fmt()
    elif cmd == 'answer':
        cmd_answer(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else 'done')
    else:
        raise SystemExit('usage: notes_sync.py push|pull|fmt|answer <id> <text> [status]')
