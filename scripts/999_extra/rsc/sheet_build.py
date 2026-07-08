#!/usr/bin/env python3
"""
sheet_build.py — перестроить гугл-таблицу «Production Projects» (RSC) под клиентскую сдачу
анимации, «как в ютуб-каналах»: цветной выпадающий Статус (11 этапов + CF-цвета канона),
DV, шапка, заморозка, безбордюрность. Колонки адаптированы (без YouTube/Shorts).

Канон статусов/цветов дословно из contentlist_reform_v2.py (та же палитра → sheet ↔ Trello
↔ кокпит одним языком). Нумерация трёхзначная RSC001+.

Колонки (A..L):
  A №/Батч(полоса)  B Проект  C Клиент  D Сценарий  E Раскадровка/Дизайн
  F Статус▼(цвет)   G Дедлайн(дата)  H Готовый ролик  I Папка проекта
  J Хрон.([m]:ss)   K Договор/Прил.   L Note

Смарт-чипы (I папка, K договор, при желании D/E/H) ставит отдельно sheets_chip_links.py.
textRotation 90° НЕ используем (REST-угол ненадёжен) — A-полоса горизонтальным текстом.

Токен: ~/.config/rscore/token.json (rs@rya.ae). Scope drive покрывает Sheets v4.
Запуск:  ~/YTAI/environment/.venv_transcribe/bin/python3 scripts/999_extra/rsc/sheet_build.py [--dry-run]
Идемпотентно: перезаписывает шапку/строки/DV/CF/формат; повторный прогон даёт то же.
"""
from __future__ import annotations
import argparse
import os
import sys
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN = os.path.expanduser("~/.config/rscore/token.json")
SPREADSHEET = "1Qmfxdabd6GCc_ynW-HKscWYr3iI4q4GC08a20nf7BGs"
TAB_TITLE = "Projects"
NROWS = 200  # запас строк под будущие проекты

HEADERS = ["№", "Проект", "Клиент", "Сценарий", "Раскадровка/Дизайн", "Статус",
           "Дедлайн", "Готовый ролик", "Папка проекта", "Хрон.", "Договор/Прил.", "Note"]
STATUS_COL = 5   # F (0-based)
DATE_COL = 6     # G
DUR_COL = 9      # J
NCOLS = len(HEADERS)

# --- канон дословно из contentlist_reform_v2.py ---
STATUS = ["01Created", "02Script", "03Shooting", "04PreEditing", "05Editing",
          "06Review", "07Revisions", "08Gate", "09Ready", "10Published", "11Archived"]
STATUS_CF = [
    ("01Created", "#8A92A8", False), ("02Script", "#A5B4FC", False),
    ("03Shooting", "#93C5FD", False), ("04PreEditing", "#5EEAD4", False),
    ("05Editing", "#C4B5FD", False), ("06Review", "#FCD34D", False),
    ("07Revisions", "#FDBA74", False), ("08Gate", "#F87171", False),
    ("09Ready", "#4ADE80", False), ("10Published", "#E4FF6E", False),
    ("11Archived", "#334155", True),
]
PALETTE0 = "#E7D1BB"   # абрикос — «продакшн»
HEADER_BG = "#FCE5CD"

# --- данные 3 существующих проектов (миграция в трёхзначный код) ---
ROWS = [
    ["Проекты", "RSC001_Teplyj_Dom", "Тёплый Дом",
     "Сценарий ролика Тёплый Дом №2. Бюджетные организации", "", "02Script",
     "", "", "", "", "", "B2B-ролик для бюджетных организаций · RU/EN"],
    ["", "RSC002_AJAX_ARGO", "Токио Боэки Евразия", "Сценарий ролика AJAX ARGO №1", "",
     "02Script", "", "", "", "00:02:00", "",
     "Договор К-17, Прил.№2 · 329 000 ₽ (70/30) · 2D+изометрия · 2 мин · RU/EN"],
    ["", "RSC003_AJAX_ASP7011", "Токио Боэки Евразия", "Сценарий ролика AJAX НАСОС ASP 7011", "",
     "02Script", "", "", "", "00:02:00", "", "Стационарный бетононасос · моушн-дизайн · RU/EN"],
]
NDATA = len(ROWS)


def hexcolor(h):
    h = h.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def rng(sid, r0, r1, c0, c1):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1}


def svc():
    creds = Credentials.from_authorized_user_file(TOKEN, ["https://www.googleapis.com/auth/drive"])
    if not creds.valid:
        creds.refresh(Request())
        open(TOKEN, "w").write(creds.to_json())
    return build("sheets", "v4", credentials=creds)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    s = svc().spreadsheets()

    meta = s.get(spreadsheetId=SPREADSHEET,
                 fields="sheets(properties(sheetId,title,gridProperties),conditionalFormats,merges)").execute()
    sheet = meta["sheets"][0]
    sid = sheet["properties"]["sheetId"]
    cf_count = len(sheet.get("conditionalFormats", []))
    merges = sheet.get("merges", [])
    print(f"tab «{sheet['properties']['title']}» sid={sid} · CF={cf_count} · merges={len(merges)}")

    if args.dry_run:
        print("[dry-run] перестроил бы вкладку в канон RSC (шапка 12 колонок, Статус-DV+CF, полоса A).")
        return

    # 1) rename + resize + freeze; unmerge; clear DV; delete old CF
    reqs = [
        {"updateSheetProperties": {"properties": {"sheetId": sid, "title": TAB_TITLE,
            "gridProperties": {"rowCount": NROWS, "columnCount": NCOLS,
                               "frozenRowCount": 1, "frozenColumnCount": 2}},
            "fields": "title,gridProperties(rowCount,columnCount,frozenRowCount,frozenColumnCount)"}},
    ]
    for m in merges:
        reqs.append({"unmergeCells": {"range": m}})
    reqs.append({"setDataValidation": {"range": rng(sid, 0, NROWS, 0, NCOLS)}})  # clear all DV
    for _ in range(cf_count):
        reqs.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}})
    s.batchUpdate(spreadsheetId=SPREADSHEET, body={"requests": reqs}).execute()

    # 2) values: header + data
    s.values().update(spreadsheetId=SPREADSHEET, range=f"{TAB_TITLE}!A1",
                      valueInputOption="USER_ENTERED",
                      body={"values": [HEADERS] + ROWS}).execute()

    # 3) formatting + DV + CF
    reqs = []
    # header style
    reqs.append({"repeatCell": {"range": rng(sid, 0, 1, 0, NCOLS),
        "cell": {"userEnteredFormat": {"backgroundColor": hexcolor(HEADER_BG),
            "textFormat": {"bold": True}, "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"}},
        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)"}})
    # strip borders across used range
    reqs.append({"updateBorders": {"range": rng(sid, 0, NROWS, 0, NCOLS),
        "top": {"style": "NONE"}, "bottom": {"style": "NONE"}, "left": {"style": "NONE"},
        "right": {"style": "NONE"}, "innerHorizontal": {"style": "NONE"}, "innerVertical": {"style": "NONE"}}})
    # Status: center align + DV + 11 CF
    reqs.append({"repeatCell": {"range": rng(sid, 1, NROWS, STATUS_COL, STATUS_COL + 1),
        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
        "fields": "userEnteredFormat.horizontalAlignment"}})
    reqs.append({"setDataValidation": {"range": rng(sid, 1, NROWS, STATUS_COL, STATUS_COL + 1),
        "rule": {"condition": {"type": "ONE_OF_LIST",
            "values": [{"userEnteredValue": v} for v in STATUS]},
            "strict": True, "showCustomUi": True}}})
    for label, bg, white in STATUS_CF:
        fmt = {"backgroundColor": hexcolor(bg)}
        if white:
            fmt["textFormat"] = {"foregroundColor": hexcolor("#FFFFFF")}
        reqs.append({"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [rng(sid, 1, NROWS, STATUS_COL, STATUS_COL + 1)],
            "booleanRule": {"condition": {"type": "TEXT_EQ",
                "values": [{"userEnteredValue": label}]}, "format": fmt}}}})
    # date format G
    reqs.append({"repeatCell": {"range": rng(sid, 1, NROWS, DATE_COL, DATE_COL + 1),
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}},
        "fields": "userEnteredFormat.numberFormat"}})
    reqs.append({"setDataValidation": {"range": rng(sid, 1, NROWS, DATE_COL, DATE_COL + 1),
        "rule": {"condition": {"type": "DATE_IS_VALID"}, "strict": False}}})
    # duration format J
    reqs.append({"repeatCell": {"range": rng(sid, 1, NROWS, DUR_COL, DUR_COL + 1),
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "[m]:ss"}}},
        "fields": "userEnteredFormat.numberFormat"}})
    # A band: merge data rows, fill palette, centered horizontal (no rotation)
    reqs.append({"mergeCells": {"range": rng(sid, 1, 1 + NDATA, 0, 1), "mergeType": "MERGE_ALL"}})
    reqs.append({"repeatCell": {"range": rng(sid, 1, 1 + NDATA, 0, 1),
        "cell": {"userEnteredFormat": {"backgroundColor": hexcolor(PALETTE0),
            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
            "textFormat": {"bold": True}, "wrapStrategy": "WRAP"}},
        "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat,wrapStrategy)"}})
    # column widths
    widths = {0: 90, 1: 190, 2: 160, 3: 260, 4: 190, 5: 110, 6: 100, 7: 150, 8: 150, 9: 70, 10: 160, 11: 300}
    for c, px in widths.items():
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
            "startIndex": c, "endIndex": c + 1}, "properties": {"pixelSize": px}, "fields": "pixelSize"}})
    s.batchUpdate(spreadsheetId=SPREADSHEET, body={"requests": reqs}).execute()

    print(f"✓ вкладка «{TAB_TITLE}» перестроена: {NCOLS} колонок, Статус-DV+11 CF, "
          f"{NDATA} строк мигрировано. Чипы I/K поставит sheets_chip_links.py.")
    print(f"  https://docs.google.com/spreadsheets/d/{SPREADSHEET}/edit#gid={sid}")


if __name__ == "__main__":
    main()
