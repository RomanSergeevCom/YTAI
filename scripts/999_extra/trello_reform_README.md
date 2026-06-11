# trello_reform.py — привести YT-доски Trello к playbook-схеме

Реформа 2026-06-12: все 16 YT-досок → схема плейбука https://yt.rya.ae/playbook/ §2/§5.

## Что делает

- Доска → имя **«YTXX — Название»** (карта `BOARD_NAMES` внутри скрипта)
- Списки → ровно 11 статусов **01Created → … → 11Archived** (Trello list = Status 1:1):
  - rename по карте (`Start`→01Created, `Script`/`Script Approved`→02Script,
    `Source`→03Shooting, `Editing`→05Editing, `Ready`→09Ready, `YT`/`YouTube`→10Published,
    `Archive`/`Archived`→11Archived) — **rename сохраняет историю карточек** (days-in-stage)
  - недостающие списки создаются, порядок выставляется 01→11
  - `VK`/`end` → карточки переносятся в 10Published (VK-карточки получают зелёную метку `VK`),
    список архивируется
- Красная метка → **`Blocked`** (playbook: Blocked = override, не стадия)
- Booking-листы YTCR (`Not booked yet`/`Under review`/`Tentatively agreed`) остаются слева от 01Created
- `YT Demo`/`YT Test` закрываются; `RomanSergeevCom` (личный, без YT-кода) — skip

## Запуск

```bash
python3 scripts/999_extra/trello_reform.py            # dry-run
python3 scripts/999_extra/trello_reform.py --apply    # применить
python3 scripts/999_extra/trello_reform_verify.py     # инварианты после
```

Креды: `~/.config/rya/trello.env` (TRELLO_KEY/TRELLO_TOKEN, провижинит Winston).

## Новая доска нового канала

Добавь канал в `BOARD_NAMES`, запусти dry-run → `--apply`. Скрипт идемпотентен
(уже-нумерованные списки не трогает, только порядок).

## Сопряжённое

- `production_trello.py` извлекает код канала из ПРЕФИКСА имени доски (`CH_RE`),
  STAGE_MAP знает и старые, и нумерованные имена списков.
- `trello_reform_verify.py` сравнивает с снапшотом `/tmp/trello_inventory.json`
  (карточки «Это название папки в гугл диске» на закрытых списках — известный junk,
  в счёт «открытых на открытых списках» не входят).
