#!/usr/bin/env python3
from pathlib import Path

def mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def touch_keep(p: Path) -> None:
    keep = p / ".keep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")

def main() -> None:
    base = Path.home() / "YTAI" / "YTDEMO"

    # верхний уровень (всё с номерами, кроме YouTube)
    top = [
        "01_Raw",
        "02_Transcripts",
        "03_Analysis",
        "04_Briefs",
        "05_Thumbnails",
        "06_Exports",
        "07_Scripts",
        "08_Logs",
        "09_Tmp",
        "YouTube",
    ]
    for d in top:
        mkdir(base / d)
        touch_keep(base / d)

    # вложенные папки: номер начинается с номера родителя
    sub = [
        ("01_Raw", ["01_01_Video", "01_02_Audio"]),
        ("02_Transcripts", ["02_01_Runs", "02_02_Clean"]),
        ("03_Analysis", ["03_01_Chapters", "03_02_Desc", "03_03_Shorts"]),
        ("04_Briefs", ["04_01_Edit"]),
        ("05_Thumbnails", ["05_01_Prompts", "05_02_Final"]),
        ("06_Exports", ["06_01_Review", "06_02_Final"]),
        # YouTube пока без вложенности, добавим позже при необходимости
    ]

    for parent, kids in sub:
        for kid in kids:
            p = base / parent / kid
            mkdir(p)
            touch_keep(p)

    print(f"OK: template created at {base}")

if __name__ == "__main__":
    main()
