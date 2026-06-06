# site_chrome — единая система yt.rya.ae (цвет + навигация + клиент-гейт)

Три парных скрипта + два ассета реализуют единый слой для сайта `yt.rya.ae`
(прод-репо `~/RYA/yt-rya-ae/`, деплой через GH Actions rsync → Hetzner/Caddy).

## Что это даёт
1. **Единая палитра** — `web/assets/site.css` пишет канонические токены под
   `html[data-rya-theme="core"]` (выигрывает у инлайнового `:root`). Брендовые
   страницы (`brand`) сохраняют свой вид — им добавляется только навигация.
2. **Единая навигация** — `web/assets/site.js` вставляет верхнюю полосу:
   «Все каналы» → `/`, «<Канал> — домой» → `/<channel>/`, хлебные крошки.
3. **Клиент-гейт (soft)** — иерархия portal → channel → page. localStorage
   запоминает разблокировку (на своём Chrome — без пароля). Пароль страницы/канала
   показывается в share-bar для копирования/шеринга.
   ⚠️ Soft/sharing-gate: контент клиентский (виден в исходнике упорному человеку).
   Портальные пароли (`rs`/`winston`) и personal-bypass — SHA-256; пароли
   каналов/страниц — plaintext (по решению — показываются для шеринга).

## Файлы
| Файл | Роль |
|---|---|
| `~/RYA/yt-rya-ae/web/assets/site.css` | палитра-токены, акцент канала `--ch`, namespaced компоненты (`.rya-topbar/.rya-sharebar/.rya-overlay`), no-flash |
| `~/RYA/yt-rya-ae/web/assets/site.js` | identity → fetch access.json → гейт (scope из localStorage) → оверлей ИЛИ reveal+навигация+share-bar |
| `~/RYA/yt-rya-ae/web/_data/access.json` | конфиг паролей (portal hashes, bypass hash, channels/pages plaintext) |
| `~/RYA/yt-rya-ae/web/_data/channels.json` | (существующий) имена/цвета каналов для навигации |
| `site_chrome.py` | единый `ASSET_V` + хелперы `head_block()/body_script()/html_attrs()` для генераторов |
| `patch_site_chrome.py` | **первичный механизм** — патчит все `web/**/*.html` (маркер `rya-site-v1`) |
| `gen_access.py` | сидер `access.json` — чеканит пароли новым страницам (идемпотентно) |

## Рабочий цикл

### Добавилась/перегенерировалась страница
```
python3 gen_access.py            # выдать пароль новой странице (старые не трогает)
python3 patch_site_chrome.py     # вставить шапку+гейт во все страницы (идемпотентно)
```
`patch_site_chrome.py` — главный механизм: после ЛЮБОЙ регенерации страниц
прогон возвращает соответствие. Опционально генераторы импортируют `site_chrome.py`,
чтобы страницы рождались уже совместимыми — но прогон патчера всё равно обязателен.

### Изменил site.css / site.js (cache-busting)
Caddy отдаёт `*.css/*.js` как `immutable, max-age=1y` → нужно сменить версию:
```
# 1) поднять ASSET_V в site_chrome.py (1 → 2)
# 2) прогнать патчер — перепишет ?v= на всех страницах
python3 patch_site_chrome.py
```

### Ротация паролей
- Портал (`rs`/`winston`): меняются в `gen_access.py` (PORTAL_PWS) → перегенерировать.
- Канал/страница: править plaintext прямо в `access.json` (share-bar покажет новое).
- Personal-bypass: хранится хэшем; секрет печатается ОДИН раз при первом `gen_access.py`.
  Роман вводит его на своём устройстве → больше не спросит (переживает ротацию).

### Откатить всё
```
python3 patch_site_chrome.py --revert      # снять шапку/гейт со всех страниц
```

## Классификация core/brand (в патчере)
- `core` (палитра унифицируется): инлайн содержит `#0A0D16` или `--bg-card`.
- `brand` (только навигация, цвет свой): `Orbitron`/`Montserrat`/`data-theme=`/`#0A1420`
  и НЕ core. Это ytmsen (Orbitron) и ytuvi (светлая тема).
- Ручной opt-out страницы: добавить в её `<head>` комментарий `rya-site-optout`.

## Исключения патчера
`/_generated/deck/` (брендовые артборды), `/thumbnail/` (full-bleed инструмент),
файлы с маркером `rya-site-optout`.

## Деплой
Каддификейшн + git push → Winston (см. `feedback_delegate_infra_to_winston`).
Caddy `basic_auth @root` снимается (единый гейт заменяет серверный пароль портала).
Деплой = `git push` repo `~/RYA/yt-rya-ae/` → GH Actions rsync `web/` → сервер.
