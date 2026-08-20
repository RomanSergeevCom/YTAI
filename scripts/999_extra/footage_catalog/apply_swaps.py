#!/usr/bin/env python3
"""Apply cover swaps chosen by the QC pass: swaps.json = [{"key":..., "swap_to": int}]"""
import json, os, shutil, sys

SP = os.path.dirname(os.path.abspath(__file__))
swaps = json.load(open(os.path.join(SP, sys.argv[1] if len(sys.argv) > 1 else "swaps.json")))
n = 0
for s in swaps:
    src = os.path.join(SP, "cands", s["key"], f"c{s['swap_to']}.jpg")
    dst = os.path.join(SP, "chosen", s["key"] + ".jpg")
    if os.path.exists(src):
        shutil.copyfile(src, dst)
        n += 1
    else:
        print("MISSING", src)
print(f"applied {n}/{len(swaps)}")
