# RSC — Production Projects (тулинг канала)

**RSC** = разовые продакшн-проекты (в основном 2D/моушн-анимация для клиентов: AJAX,
«Тёплый Дом» и др.). Это НЕ YouTube-канал, но живёт в той же экосистеме, что и YT-каналы:
одна Trello-доска = один Shared Drive = одна ContentList-таблица = одна hub-страница `/rsc/`.

**Режим Hybrid** (решение 2026-07-08): код `RSC` сохранён (зашит в договоры ИП, папки Drive,
сценарии), но этапы — **стандартные YT** (`01Created…11Archived`), чтобы кокпит `/production/`
подхватывал доску без правок `STAGE_MAP`. Нумерация проектов **трёхзначная**: `RSC001`, `RSC002`…

## Ресурсы канала

| Что | Ресурс |
|---|---|
| Trello-доска | `RSC — Production Projects` · id `6a4e5a196fc86abdfdfbf32a` · https://trello.com/b/yLPi5CuM/rsc-production-projects |
| Shared Drive | `0AAFIdBrcup6QUk9PVA` (папки `RSC001-…`, `RSC002-…`, `RSC003-…`) |
| Таблица (ContentList) | `1Qmfxdabd6GCc_ynW-HKscWYr3iI4q4GC08a20nf7BGs`, вкладка `Projects` |
| Hub на портале | https://yt.rya.ae/rsc/ (гейт: пароль `prod-…`) |
| Кокпит | https://yt.rya.ae/production/ (пилюля RSC) |

## Скрипты

### `create_board.py`
Заводит Trello-доску из шаблона «YT Template» (`66fc09fff3a55640376df3db`) → 11 стандартных
списков + метка Blocked. Идемпотентно (переиспользует доску с тем же именем). Заводит 3
карточки `RSC001…003` в `02Script`. Печатает `board.id`/shortLink для `channels.json`.
```
python3 create_board.py [--dry-run]
```
Креды: `~/.config/rya/trello.env` (`TRELLO_KEY`, `TRELLO_TOKEN`).

### `sheet_build.py`
Перестраивает таблицу под клиентскую сдачу анимации: цветной Статус-дропдаун (11 этапов +
CF-цвета канона дословно из `contentlist_reform_v2.py`), DV даты, шапка, заморозка (строка 1
+ колонки A:B), безбордюрность, полоса A. Колонки A..L:
`№ · Проект · Клиент · Сценарий · Раскадровка/Дизайн · Статус · Дедлайн · Готовый ролик ·
Папка проекта · Хрон. · Договор/Прил. · Note`. Смарт-чипы ставит отдельно `sheets_chip_links.py`.
```
~/YTAI/environment/.venv_transcribe/bin/python3 sheet_build.py [--dry-run]
```
Токен: `~/.config/rscore/token.json` (rs@rya.ae). Грабля: длительность писать как `00:02:00`
(h:mm:ss), иначе `2:00` парсится как 2 часа → формат `[m]:ss` покажет `120:00`.

Чипы папок/договоров (пример):
```
python3 ../sheets_chip_links.py --sheet 1Qmfxdabd6… --tab Projects \
  --chip "I2=<folderId>" --chip "K3=<contractId>" --verify
```

## Правки в общем коде (вне этой папки)
- `../production_trello.py` — `BOARD_RE/CH_RE/CODE_RE` принимают `RSC`; `FALLBACK_COLORS["RSC"]="#F59E0B"`.
- `../patch_site_chrome.py` + `~/RYA/yt-rya-ae/scripts/site/patch_site_chrome.py` — `rsc` в `CH_CODES`.
- `../gen_access.py` — `rsc` в `CH_CODES`, `"rsc":"prod"` в `CHWORD` (пароль `prod-quartz`).
- `~/RYA/yt-rya-ae/web/_data/channels.json` — запись `id:"RSC"`.
- `~/RYA/yt-rya-ae/web/rsc/index.html` — hub-страница (статик, стиль портала, amber #F59E0B).

## Обновление статусов
Источник правды — Trello. После перемещения карточек:
```
cd ~/YTAI && source environment/.venv_transcribe/bin/activate
python3 scripts/999_extra/production_trello.py --out ~/RYA/yt-rya-ae/web/_data/production.json
python3 scripts/999_extra/production_render.py --repo ~/RYA/yt-rya-ae
```
(или дождаться суточного refresh Winston). Статус в таблице `Projects` — вручную из дропдауна.
