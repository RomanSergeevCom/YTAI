#!/usr/bin/env python3
"""Fetch Drive video thumbnails for footage folders that exist only on Drive."""
import json, os, urllib.request, urllib.parse

TOK = json.load(open("/Users/romansergeev/.config/rscore/token.json"))

def access_token():
    data = urllib.parse.urlencode({
        "client_id": TOK["client_id"], "client_secret": TOK["client_secret"],
        "refresh_token": TOK["refresh_token"], "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOK["token_uri"], data=data)
    return json.load(urllib.request.urlopen(req))["access_token"]

AT = access_token()
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thumbs_drive")
os.makedirs(OUT, exist_ok=True)

FOLDERS = {
    "01_Lyudmila_Chibireva_Family_Story_Part1": "168izVKmTZffF_630xCFJb1ApN0hiq-CT",
    "03_Lyudmila_Chibireva_Family_Story_Part2": "1LHseQpcM0FnMJCPdgiYQg8lur5TS6MUN",
    "10_Maria_Gaidarova_Interview": "1YI147AUaeIRpuRtKtAUxqgwoF1OapN7g",
    "12_Anastasia_Laricheva_Funding": "1FJpFViAoGq5daUv_N4528HN22zWXMUXb",
}

def api(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {AT}"})
    return json.load(urllib.request.urlopen(req))

meta = {}
for name, fid in FOLDERS.items():
    q = urllib.parse.quote(f"'{fid}' in parents and mimeType contains 'video/' and trashed=false")
    fields = urllib.parse.quote("files(id,name,size,thumbnailLink,videoMediaMetadata)")
    res = api(f"https://www.googleapis.com/drive/v3/files?q={q}&fields={fields}&pageSize=100&supportsAllDrives=true&includeItemsFromAllDrives=true")
    meta[name] = []
    for f in sorted(res.get("files", []), key=lambda x: x["name"]):
        thumb = None
        tl = f.get("thumbnailLink")
        if tl:
            tl = tl.replace("=s220", "=s320")
            thumb = f"{name[:2]}_{f['name'].rsplit('.',1)[0]}.jpg"
            tp = os.path.join(OUT, thumb)
            try:
                req = urllib.request.Request(tl, headers={"Authorization": f"Bearer {AT}"})
                open(tp, "wb").write(urllib.request.urlopen(req).read())
            except Exception as e:
                print("thumb fail", f["name"], e)
                thumb = None
        dur = 0
        vmm = f.get("videoMediaMetadata") or {}
        if vmm.get("durationMillis"):
            dur = int(vmm["durationMillis"]) / 1000
        meta[name].append({"rel": f["name"], "size": int(f.get("size", 0)),
                           "dur": dur, "thumb": thumb})
        print(name, f["name"], dur, "thumb" if thumb else "NO-THUMB", flush=True)

with open(os.path.join(os.path.dirname(OUT), "drive_meta.json"), "w") as f:
    json.dump(meta, f, ensure_ascii=False, indent=1)
print("DONE")
