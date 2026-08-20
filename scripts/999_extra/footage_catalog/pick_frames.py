#!/usr/bin/env python3
"""Pick the most representative cover frame per clip.

For each video: extract candidate frames spread across the clip, score each
locally (face presence via OpenCV cascades, sharpness, exposure, colorfulness),
keep the winner + all candidates for later manual/agent swap.
"""
import json, os, shutil, subprocess, sys
from multiprocessing import Pool

import cv2
import numpy as np

SP = os.path.dirname(os.path.abspath(__file__))
ROOT = "/Volumes/T7-Beige-RYA/YTFP"
CAND = os.path.join(SP, "cands")
CHOSEN = os.path.join(SP, "chosen")
os.makedirs(CAND, exist_ok=True)
os.makedirs(CHOSEN, exist_ok=True)

FRACS = [0.12, 0.25, 0.38, 0.50, 0.62, 0.75, 0.88]

face_front = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
face_prof = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")


def score_frame(path):
    img = cv2.imread(path)
    if img is None:
        return -1e9, {}
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # sharpness
    sharp = cv2.Laplacian(gray, cv2.CV_64F).var()
    sharp_n = min(sharp / 300.0, 1.5)

    # exposure: mean in comfortable range, penalize clipping
    mean = gray.mean()
    expo = 1.0 - min(abs(mean - 118) / 118, 1.0)
    dark_frac = (gray < 16).mean()
    bright_frac = (gray > 240).mean()
    expo -= 0.8 * max(dark_frac - 0.25, 0) + 0.8 * max(bright_frac - 0.25, 0)

    # colorfulness (Hasler-Süsstrunk, scaled)
    b, g, r = img[:, :, 0].astype(float), img[:, :, 1].astype(float), img[:, :, 2].astype(float)
    rg = np.abs(r - g); yb = np.abs(0.5 * (r + g) - b)
    colorful = min((np.sqrt(rg.std() ** 2 + yb.std() ** 2)
                    + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)) / 60.0, 1.0)

    # faces
    eq = cv2.equalizeHist(gray)
    faces = list(face_front.detectMultiScale(eq, 1.1, 5, minSize=(int(h * 0.08), int(h * 0.08))))
    faces += list(face_prof.detectMultiScale(eq, 1.1, 5, minSize=(int(h * 0.08), int(h * 0.08))))
    face_s = 0.0
    if faces:
        fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        area = (fw * fh) / (w * h)                      # 0..1
        size_s = min(area / 0.06, 1.0)                  # ~6% of frame = full marks
        cx = (fx + fw / 2) / w
        center_s = 1.0 - min(abs(cx - 0.5) * 2, 1.0)    # centered is better
        face_s = size_s * (0.7 + 0.3 * center_s)

    total = 3.0 * face_s + 1.0 * sharp_n + 1.2 * expo + 0.5 * colorful
    return total, {"face": round(face_s, 3), "sharp": round(sharp_n, 3),
                   "expo": round(expo, 3), "color": round(colorful, 3)}


def extract(src, ss, out, headers=None):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if headers:
        cmd += ["-headers", headers]
    cmd += ["-ss", str(ss), "-i", src, "-frames:v", "1",
            "-vf", "scale=480:-2", "-q:v", "7", "-strict", "unofficial", "-y", out]
    r = subprocess.run(cmd, capture_output=True, timeout=180)
    return r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0


def process_clip(job):
    key, src, dur, headers = job
    cdir = os.path.join(CAND, key)
    os.makedirs(cdir, exist_ok=True)
    results = []
    for i, fr in enumerate(FRACS):
        ss = max(dur * fr, 0.3)
        if dur > 1 and ss > dur - 0.5:
            ss = max(dur - 1.0, 0.3)
        out = os.path.join(cdir, f"c{i}.jpg")
        if not os.path.exists(out):
            try:
                ok = extract(src, ss, out, headers)
            except Exception:
                ok = False
            if not ok:
                continue
        s, parts = score_frame(out)
        results.append({"idx": i, "ss": round(ss, 2), "score": round(s, 3), **parts})
    if not results:
        return key, None
    best = max(results, key=lambda r: r["score"])
    shutil.copyfile(os.path.join(cdir, f"c{best['idx']}.jpg"),
                    os.path.join(CHOSEN, key + ".jpg"))
    return key, {"best": best["idx"], "cands": results}


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "local"
    jobs = []
    if which == "local":
        meta = json.load(open(os.path.join(SP, "local_meta.json")))
        for folder, items in meta.items():
            for it in items:
                key = it["thumb"].rsplit(".", 1)[0]
                jobs.append((key, os.path.join(ROOT, folder, it["rel"]), it["dur"], None))
    else:  # drive
        import urllib.request, urllib.parse
        TOK = json.load(open("/Users/romansergeev/.config/rscore/token.json"))
        data = urllib.parse.urlencode({
            "client_id": TOK["client_id"], "client_secret": TOK["client_secret"],
            "refresh_token": TOK["refresh_token"], "grant_type": "refresh_token"}).encode()
        AT = json.load(urllib.request.urlopen(
            urllib.request.Request(TOK["token_uri"], data=data)))["access_token"]
        headers = f"Authorization: Bearer {AT}\r\n"
        FOLDERS = {
            "01_Lyudmila_Chibireva_Family_Story_Part1": "168izVKmTZffF_630xCFJb1ApN0hiq-CT",
            "03_Lyudmila_Chibireva_Family_Story_Part2": "1LHseQpcM0FnMJCPdgiYQg8lur5TS6MUN",
            "10_Maria_Gaidarova_Interview": "1YI147AUaeIRpuRtKtAUxqgwoF1OapN7g",
            "12_Anastasia_Laricheva_Funding": "1FJpFViAoGq5daUv_N4528HN22zWXMUXb",
        }
        meta = json.load(open(os.path.join(SP, "drive_meta.json")))
        for folder, fid in FOLDERS.items():
            q = urllib.parse.quote(
                f"'{fid}' in parents and mimeType contains 'video/' and trashed=false")
            url = (f"https://www.googleapis.com/drive/v3/files?q={q}"
                   f"&fields=files(id,name)&supportsAllDrives=true&includeItemsFromAllDrives=true")
            res = json.load(urllib.request.urlopen(
                urllib.request.Request(url, headers={"Authorization": f"Bearer {AT}"})))
            ids = {f["name"]: f["id"] for f in res["files"]}
            for it in meta[folder]:
                key = f"{folder[:2]}_{it['rel'].rsplit('.', 1)[0]}"
                media = (f"https://www.googleapis.com/drive/v3/files/{ids[it['rel']]}"
                         f"?alt=media&supportsAllDrives=true")
                jobs.append((key, media, it["dur"], headers))

    nproc = 5 if which == "local" else 3
    picked = {}
    with Pool(nproc) as pool:
        for i, (key, res) in enumerate(pool.imap_unordered(process_clip, jobs)):
            picked[key] = res
            print(f"[{i+1}/{len(jobs)}] {key} -> {res['best'] if res else 'FAIL'}", flush=True)
    outp = os.path.join(SP, f"picked_{which}.json")
    old = json.load(open(outp)) if os.path.exists(outp) else {}
    old.update(picked)
    json.dump(old, open(outp, "w"), ensure_ascii=False, indent=1)
    print("DONE", which)


if __name__ == "__main__":
    main()
