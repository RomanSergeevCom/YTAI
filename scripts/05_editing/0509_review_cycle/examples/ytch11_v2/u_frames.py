#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Загрузка выбранных кадров v2 на Drive (папка _plan_v2_frames в папке проекта)
и манифест thumbnailLink'ов для вставки в док. Кадры НЕ шарятся публично —
Docs API забирает thumbnailLink и хранит свою копию.

Вход: frames_wanted.json — ["f0123.jpg", ...]
Выход: frames_manifest.json — {"f0123.jpg": "https://lh3...=s1400"}
"""
import json, os, sys, uuid, urllib.request, time
sys.path.insert(0, os.path.expanduser('~/YTAI/scripts/999_extra/ytuvi_doctabs'))
from doctab_lib import api, access_token

WORK = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(WORK, 'frames1s')
PARENT = '1wU-uPYIJojbZPjr54Ws3eswYZGGErmsS'  # YTCH S3/YTCH11_Liza_Vitalik
WANTED = sys.argv[1] if len(sys.argv) > 1 else os.path.join(WORK, 'frames_wanted.json')
MANIFEST = os.path.join(WORK, 'frames_manifest.json')


def ensure_folder(name, parent):
    import urllib.parse
    q = urllib.parse.quote(f"name = '{name}' and '{parent}' in parents and trashed = false")
    r = api('GET', f'https://www.googleapis.com/drive/v3/files?q={q}&corpora=drive&driveId=0AL5m1S49VznzUk9PVA'
                   '&includeItemsFromAllDrives=true&supportsAllDrives=true&fields=files(id)')
    if r.get('files'):
        return r['files'][0]['id']
    r = api('POST', 'https://www.googleapis.com/drive/v3/files?supportsAllDrives=true&fields=id',
            {'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent]})
    return r['id']


def upload_jpg(path, name, parent):
    meta = json.dumps({'name': name, 'parents': [parent]}).encode()
    data = open(path, 'rb').read()
    b = uuid.uuid4().hex
    body = (f'--{b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n').encode() + meta + \
           (f'\r\n--{b}\r\nContent-Type: image/jpeg\r\n\r\n').encode() + data + (f'\r\n--{b}--').encode()
    req = urllib.request.Request(
        'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true&fields=id,thumbnailLink',
        data=body, method='POST',
        headers={'Authorization': f'Bearer {access_token()}',
                 'Content-Type': f'multipart/related; boundary={b}'})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def thumb_of(fid):
    for _ in range(8):
        g = api('GET', f'https://www.googleapis.com/drive/v3/files/{fid}?fields=thumbnailLink&supportsAllDrives=true')
        t = g.get('thumbnailLink')
        if t:
            return t
        time.sleep(2)
    return None


def main():
    wanted = json.load(open(WANTED, encoding='utf-8'))
    man = {}
    if os.path.exists(MANIFEST):
        try:
            man = json.load(open(MANIFEST, encoding='utf-8'))
        except Exception:
            man = {}
    folder = ensure_folder('_plan_v2_frames', PARENT)
    print('folder:', folder, '| wanted:', len(wanted), '| have:', len(man), flush=True)
    for i, fn in enumerate(wanted):
        if fn in man:
            continue
        p = os.path.join(FRAMES, fn)
        if not os.path.exists(p):
            print('!! missing frame:', fn, flush=True)
            continue
        try:
            f = upload_jpg(p, fn, folder)
            t = f.get('thumbnailLink') or thumb_of(f['id'])
            if not t:
                print('!! no thumb:', fn, flush=True)
                continue
            man[fn] = t.replace('=s220', '=s1400')
        except Exception as e:
            print('!! upload err:', fn, str(e)[:120], flush=True)
            time.sleep(2)
        if i % 10 == 0:
            json.dump(man, open(MANIFEST, 'w'))
            print('  %d/%d' % (i, len(wanted)), flush=True)
    json.dump(man, open(MANIFEST, 'w'))
    print('manifest:', len(man), flush=True)


if __name__ == '__main__':
    main()
