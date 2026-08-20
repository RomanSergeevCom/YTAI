#!/usr/bin/env python3
"""Build map {"NN_<rel>": drive_file_id} for every video in the 14 footage folders."""
import json, os, subprocess

SP = os.path.dirname(os.path.abspath(__file__))
DRIVE_IDS = {
    "00_Lyudmila_Chibireva_Home_Archive": "1vM2FOYo7hS0W9qkPy8Pxisd3gx1IOrhw",
    "01_Lyudmila_Chibireva_Family_Story_Part1": "168izVKmTZffF_630xCFJb1ApN0hiq-CT",
    "02_Lyudmila_Chibireva_Cochlear_Implant": "1a3cmGQbpwCwGt4fuRewI9H2sN4SfWipB",
    "03_Lyudmila_Chibireva_Family_Story_Part2": "1LHseQpcM0FnMJCPdgiYQg8lur5TS6MUN",
    "04_Center_BTS": "1noE3jTnFnbXUWJxmuRT8Yd3TqiY3-eSu",
    "05_Yulia_Reznik_Interview": "1iarR3nDPLht3LiDXoiYM1nwdcKRfTf5E",
    "06_Yulia_Reznik_Kids_Session": "1uzvLIoDnDqrHoaCS8W16zStcl2PUaV9J",
    "07_Tatyana_Nesterenko_Neuroplasticity": "1HCtdSCsx60-Gk5UqWCAh3BLdWtTK6Jwl",
    "08_Tatyana_Nesterenko_Center_Tour": "19RkqpRz-SnWUCN7hiP37Uy5Mkai6_OJU",
    "09_Maria_Gaidarova_Kids_Session": "1MzlzWe8nLXafov8PjWsKP7GHw9CgV_R8",
    "10_Maria_Gaidarova_Interview": "1YI147AUaeIRpuRtKtAUxqgwoF1OapN7g",
    "11_Tatyana_Kislyakova_Director_Vision": "1zPpmv5XKsxcFebod_9wrTeumLkyJA7aE",
    "12_Anastasia_Laricheva_Funding": "1FJpFViAoGq5daUv_N4528HN22zWXMUXb",
    "13_Olga_Gritsay_Legal_Rights": "1NaCoUNiteSIezbkJZKereZUw8zrM2PyO",
}

ids = {}
for folder, fid in DRIVE_IDS.items():
    out = subprocess.check_output(
        ["rclone", "lsjson", "-R", "--files-only",
         "--drive-root-folder-id", fid, "gdrive:"], text=True)
    num = folder[:2]
    for f in json.loads(out):
        if f["Name"].lower().endswith((".mp4", ".mov", ".mts")):
            ids[f"{num}_{f['Path']}"] = f["ID"]

json.dump(ids, open(os.path.join(SP, "video_ids.json"), "w"), ensure_ascii=False, indent=0)
print(f"{len(ids)} video ids")
