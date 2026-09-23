#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Смысловая подпись экрана локальной VLM. Один вызов на ЭКРАН, не на кадр.

⚠️ Разделение слоёв не вкусовое, оно замерено. Дословный текст с экрана берёт
Apple Vision OCR: 924 кадра за 51 секунду, кириллица без галлюцинаций.
Агентский свип по тем же кадрам наврал — назвал плашку CTA заставкой главы
и слепил 42 экрана в 29 (YTAgeFree05, 10.08). Поэтому VLM здесь отвечает
ровно на один вопрос, на который OCR ответить не может: «что человек тут
ДЕЛАЕТ», — и получает уже сгруппированный экран, а не поток кадров.

Экономия не ради экономии: 126 минут скринкастов это ~1500 кадров, но экранов
из них выходит на порядок меньше, и длинных (≥ порога) — ещё меньше.

Вызывается из screencast.py --vlm; отдельно запускать незачем.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

VLM_PY = Path.home() / "YTAI/environment/.venv_vlm/bin/python3"
VLM_MODEL = "mlx-community/Qwen2.5-VL-7B-Instruct-4bit"
MIN_SEC = 15.0        # короче — проскок, а не состояние экрана
MAX_PER_FILE = 24     # потолок на файл: смысл важен, а не полнота

PROG = r'''
import json, os, sys
os.environ.setdefault("HF_HOME", os.path.expanduser("~/YTAI/models/huggingface"))
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config
tasks = json.load(open(sys.argv[1]))
model, processor = load(sys.argv[3])
config = load_config(sys.argv[3])
out = []
for t in tasks:
    f = apply_chat_template(processor, config, t["q"], num_images=1)
    r = generate(model, processor, f, [t["img"]], max_tokens=70,
                 temperature=0.0, verbose=False)
    out.append({"id": t["id"],
                "caption": (r.text if hasattr(r, "text") else str(r)).strip()})
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False)
'''

Q = ("Это кадр записи экрана обучающего урока. Одним предложением по-русски: "
     "в каком сервисе работает человек и что он в этот момент делает. "
     "Не перечисляй текст с экрана, назови действие.")


def caption_screens(items, frames_dir: Path, fps: float, day=None):
    """Дописывает screens[].caption на месте. Молча пропускает, если VLM нет."""
    if not VLM_PY.exists():
        print("  ⚠ нет .venv_vlm — смысловой слой пропущен")
        return items

    tasks, ref = [], {}
    for it in items:
        picked = 0
        for si, s in enumerate(it.get("screens") or []):
            if s.get("sec", 0) < MIN_SEC or picked >= MAX_PER_FILE:
                continue
            n = int(round(s["best"] * fps)) + 1
            img = frames_dir / Path(it["file"]).stem.replace(" ", "_") / f"f_{n:05d}.jpg"
            if not img.exists():
                continue
            tid = f"{it['file']}#{si}"
            tasks.append({"id": tid, "img": str(img), "q": Q})
            ref[tid] = (it, si)
            picked += 1

    if not tasks:
        print("  · длинных экранов не нашлось — VLM звать не за чем")
        return items
    print(f"  VLM: экранов к подписи {len(tasks)} "
          f"(из {sum(len(i.get('screens') or []) for i in items)} всего)", flush=True)

    tmp = Path(tempfile.mkdtemp(prefix="sc_vlm_"))
    (tmp / "in.json").write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([str(VLM_PY), "-c", PROG, str(tmp / "in.json"),
                        str(tmp / "out.json"), VLM_MODEL],
                       capture_output=True, text=True, timeout=7200)
    if p.returncode != 0 or not (tmp / "out.json").exists():
        print("  ⚠ VLM упал:", (p.stderr or "")[-500:])
        return items
    for r in json.loads((tmp / "out.json").read_text(encoding="utf-8")):
        tgt = ref.get(r["id"])
        if tgt:
            it, si = tgt
            it["screens"][si]["caption"] = r["caption"]
    done = sum(1 for i in items for s in (i.get("screens") or []) if s.get("caption"))
    print(f"  VLM: подписано {done}")
    return items


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
