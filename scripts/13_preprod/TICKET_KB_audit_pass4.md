# ТИКЕТ · Четвёртая независимая проверка базы знаний yt.rya.ae после вставки главы Pre-Production

✅ **ЗАКРЫТ 22.09.2026.** Итог — §9 в `TICKET_KB_preprod_chapter.md` рядом. Коммиты: `9f5b8039` (аудит),
`9c294ce7` + `ba702d45` (галерея 1.2 по замечаниям Романа). Ниже — исходное задание, как оно было поставлено.

**Версия:** v1 · **Собран:** 21.09.2026 15:50 · **Тип:** аудит (сначала разбор, потом правки)
**Написано для:** отдельной сессии Claude Code, которая НЕ участвовала в работе 21.09. Самодостаточно: в прошлый чат заглядывать не нужно.
**Состояние перед стартом:** `origin/main` = `19b015d9`, всё задеплоено, три прохода аудита закрыты. Хроника — `TICKET_KB_preprod_chapter.md` рядом (разделы 6–8), читать её только за подробностями.

---

## 0. ФРАЗА ДЛЯ СТАРТА

> Проведи четвёртую независимую проверку базы знаний yt.rya.ae по тикету
> `~/YTAI/scripts/13_preprod/TICKET_KB_audit_pass4.md`. Ничего не правь, пока не покажешь мне разбор.
> Ищи там, где три прошлых прохода не искали. Деплой через Винстона, в конце открой сайт.

## 0.1 ГДЕ СМОТРЕТЬ

| что | где |
|---|---|
| этот тикет | `~/YTAI/scripts/13_preprod/TICKET_KB_audit_pass4.md` |
| хроника трёх проходов, решения Романа, находки по источникам | `~/YTAI/scripts/13_preprod/TICKET_KB_preprod_chapter.md` |
| хэндофф деплоя (как пушить, что знать про грязное дерево) | `~/YTAI/scripts/13_preprod/HANDOFF_kb_preprod_deploy.md` |
| утренний тикет (граница Pre-Editing / Ingest, правило примеров) | `~/YTAI/scripts/01_prepare/0120_day_ingest/TICKET_KB_chapters.md` |
| репозиторий сайта | `~/RYA/yt-rya-ae/` (рабочее дерево чужое и грязное — см. §5) |
| единственный источник правды KB | `~/RYA/yt-rya-ae/web/_data/kb.json` |
| генераторы | `~/RYA/yt-rya-ae/scripts/site/gen_kb.py` · `gen_index.py` · `patch_site_chrome.py` |
| инструмент перенумерации и аудита ссылок | `~/RYA/yt-rya-ae/scripts/site/kb_renumber.py` |
| правила KB (главы заморожены, правило примеров, worktree) | `~/RYA/yt-rya-ae/docs/handoffs/HANDOFF_kb_structure.md` |
| память про устройство KB | `reference_kb_system_yt_rya` |
| прод | `https://yt.rya.ae/kb/` |

---

## 1. КОНТЕКСТ — что это и что сделано 21.09.2026

`yt.rya.ae/kb/` — база знаний продакшна RYA Media Lab. Страницы нумеруются `глава.страница` (3.8, 5.7), номера
**не входят в URL** — пути `/kb/<slug>/` стабильны. Хаб, крошки, `next:`, `<title>`, бейджи карточек «N.M · k» и
сайдбар главной генерируются из `kb.json`. Руками пишутся только тексты страниц — и ссылки по номеру внутри них.

За день сделано два структурных изменения, оба по решению Романа:

1. **Утро — граница Pre-Editing / Ingest.** Прокси, расшифровки, Drive-синхрон и луты переехали в Pre-Editing;
   луты вынесены отдельной страницей Scene LUTs; Audio Enhance — в Ingest. Коммит `3551694d`.
2. **Вечер — вставлена глава 1 Pre-Production** (1.1 Screen Kinds Library · 1.2 Animation Templates · 1.3 Narrator Script),
   главы 1–7 стали 2–8. Коммиты `1868f481` (глава), `38a598d7` и `19b015d9` (хвосты двух аудитов).
   После этого **главы заморожены**: новые стадии — страницами внутри глав.

### Актуальная карта (52 записи, 9 глав)

```
0 Setup & Foundations   0.1 channel-launch · 0.2 storage · 0.3 team · 0.4 drive-quota · 0.5 media-prep
1 Pre-Production        1.1 screens · 1.2 templates · 1.3 narrator-script
2 Production            2.1 gear (2.1.1 fx3a · 2.1.2 zve1 · 2.1.3 videomicntg · 2.1.4 tetherhub · 2.1.5 incoming · 2.1.6 wishlist) · 2.2 shootday
3 Pre-Editing           3.1 day-ingest · 3.2 transcription · 3.3 source-restructure · 3.4 proxy · 3.5 transcript-doc ·
                        3.6 drive-sync · 3.7 footage-catalog · 3.8 luts · 3.9 preediting · 3.10 source-enrichment
4 Ingest                4.1 ingest · 4.2 multicam-wordsync · 4.3 fine-sync · 4.4 frame-align · 4.5 audio-enhance
5 Editing               5.1 playbook · 5.2 editor-handoff · 5.3 editor-montage · 5.4 manifest · 5.5 assembly-brief ·
                        5.6 review-timeline · 5.7 review-cycle · 5.8 montage-tz
6 Package & Publish     6.1 thumbnail (6.1.1 thumbnail/preview) · 6.2 yt-upload (6.2.1 contentlist)
7 Method & Reference    7.1 method (7.1.1–7.1.6) · 7.2 dna — архив, внешняя ссылка
8 Deal & Documents      8.1 contracts
```
Якоря хаба: `#ch0`…`#ch8` в том же порядке. Старые номера, которые ещё могут всплыть: до утра 21.09 — proxy 3.5,
drive-sync 3.7 (ещё раньше 3.3/3.6), transcript-doc 3.6, day-ingest 1.3/2.7, audio-enhance 2.2/2.8, preediting 2.3/2.9;
до вечера 21.09 — всё из глав 1–7 на единицу меньше (review-cycle 4.7, contracts 7.1, gear 1.1, luts 2.8);
совсем старые — yt-upload 3.2, contentlist 3.2.1, thumbnail 3.1, method 4.1, dna 4.2.

### Что нашёл каждый проход — и почему нужен четвёртый

| проход | где искал | что нашёл |
|---|---|---|
| сборка | ссылки `<a href="/kb/…">N.M …</a>` в `web/kb/`, `KB N.M` в памяти и `*.md/*.py` | 145 ссылок, ~70 упоминаний вне сайта |
| 1-й аудит | то же + проза страниц, план против артефактов | номер в скобках в конце ссылки, относительный href, якоря `#chN`, страница-сирота `thumbnail/preview`, 0509-кластер, `pipeline_ch3` STEPS, `build_incoming.py` |
| 2-й аудит | + `*.sh`, f-строки, страницы вне `/kb/` | «KB 2.7» на `/ytevo/03/`, зашитая подпись главной, «гейт 3.4 / глава 3» в shell-обёртках и корневой копии `rebuild_ingest…`, ссылки на лутовый SOP в ingest §7 |

Каждый проход искал шире предыдущего и каждый находил. Остановились не потому, что стало чисто, а потому что
третий раз подряд что-то нашлось. Задача этого тикета — искать **под другими углами**, а не повторять те же grep'ы.

---

## 2. ЧТО ПРОВЕРИТЬ

В каждом пункте: что проверить → как → что считать нормой → что чинить. Находки называть поимённо (файл:строка, цитата).

### 2.1 Номера KB там, где ещё никто не искал

Проверено и чисто (не повторять целиком, только выборочно): `~/.claude/projects/-Users-romansergeev-YTAI/memory/`,
`~/YTAI/CLAUDE.md`, `~/YTAI/CODEX.md`, `~/YTAI/.claude/skills/`, `~/YTAI/scripts/**` (`*.md *.py *.sh *.js *.html *.json`),
`~/.claude/agents/`, `~/YTAI/Bots/`, `~/YTAI/YTs/`, `~/Desktop/YTUVIE/**/*.md`, страницы сайта вне `/kb/` по шаблону `KB N.M`.

Не проверено:
- память **других** проектов: `~/.claude/projects/*/memory/` кроме YTAI;
- `~/RSCore/Bots/*/` (CLAUDE.md и DESCRIPTION.md ботов), `~/.claude/channels/*/`, плагины `~/.claude/plugins/marketplaces/local-rs-bots/`;
- `~/YTAI/scripts/**` в форматах `*.jsx *.txt *.yaml *.yml *.toml *.plist *.css` и UXP-панель `05_editing/0500_uxp/**` (строки интерфейса);
- launchd: `~/Library/LaunchAgents/com.romansergeev.*.plist` (аргументы и комментарии);
- `/Volumes/T9-Black-RYA/YTAI_Templates/**/*.md|*.html` и другие смонтированные тома с README;
- остальные репозитории под `~/RYA/` и старое зеркало `~/YTAI/yt-rya-ae/public/` (его только отметить, не чинить);
- сайт вне `/kb/`: номера KB **в прозе, не в ссылке** и без префикса «KB» («см. 4.7», «этап 3», «глава Ingest (3)») —
  `web/ytuvie/`, `web/ytch/`, `web/ytcr/`, `web/ytevo/`, `web/production/`, `web/_data/channels.json` (поля `pages`, `tools`);
- `web/assets/site.js` и `site.css` — строки и комментарии с номерами глав;
- Google-документы, на которые ссылаются страницы KB («Материалы» YTUVIE01 и т.п.) — только если в них есть «KB N.M»; править НЕ надо, записать.

Норма: каждое упоминание совпадает с картой §1 либо стоит в файле, помеченном сверху как исторический.
Чинить: точной заменой строки (assert-скрипт с проверкой числа вхождений), не слепым sed.

### 2.2 Генераторы, которые вернут старый номер при следующем запуске

Уже пойманы и исправлены: `999_extra/incoming_gear/build_incoming.py` (`<title>`), `0120_day_ingest/publish_review_to_site.py` (баннер).
Проверить остальные генераторы страниц сайта на зашитые номера KB, главы или якоря:
`~/RYA/yt-rya-ae/scripts/site/*.py` (в т.ч. `gen_gear.py` — стейл, `gen_team.py`, `patch_hub_pages.py`, `gear_device_page.py`),
`~/YTAI/scripts/13_preprod/1300_channel_setup/sprint_page.py`, `1304_visual_tz/build_dna_page.py` и `build_tz_page.py`,
`0120_day_ingest/s14_review_page.py` и `s16_day_passport.py`, `999_extra/*_page*.py`, `999_extra/ytuvi_shoot_plan.py`.
Отдельно выяснить, **чем собраны** `web/ytevo/03/index.html` и `web/ytevo/03/review/index.html`: там «KB 2.7» поправлено
прямо в HTML (коммит `19b015d9`); если у них есть генератор с шаблоном — следующий прогон вернёт 2.7.
Норма: ни один генератор не содержит номера KB строкой; если содержит — либо берёт из `kb.json`, либо номер верный.

### 2.3 Страница 3.8 Scene LUTs и карточка в 4.1 Ingest — не проходили фактчек

Три новые страницы главы 1 прошли адверсариальный фактчек (найдено 13 расхождений). Страница `/kb/luts/`, написанная
утром, и переписанный §7 `/kb/ingest/` — **нет**. Проверить каждое утверждение против кода:
`~/YTAI/scripts/999_extra/lut_face_score.py` и его README, `~/YTAI/scripts/05_editing/0500_uxp/docs/HANDOFF_adjust_lut.md`,
`0500_uxp_spec.md → ADJUST`, исходники панели (имена кнопок «Build LUT Donor», «Apply LUT Layers», «Active Sequence Only»,
«Probe Donor Clone», статусные строки `LUT layers (donor clones): +N new … · Look N`, `legacy — no donor seq!`),
пути (`00_Setup/01_Ingest/{CODE}_lut_plan.json`, `99_Pipeline/lut_layers_manifest.json`, `99_Pipeline/logs/adjust_last.log`),
четыре места хранения LUT, `LEGACY_LUT_ALIASES`, число тестов (45), цифры YTCH13 (26/26, «глаз поправил 11 из 26»).
Норма: каждое число, имя файла, кнопки и строки статуса находится в источнике. Что не подтверждается — в разбор.

### 2.4 Функциональная проверка прода обходом, а не выборкой

Прошлые проверки курлили 10–25 URL. Нужен полный обход:
- пройти цепочку `next:` от `/kb/channel-launch/` до `/kb/contracts/`: каждая не-leaf страница посещена ровно один раз,
  порядок равен порядку номеров; leaf-цепочки (2.1.x, 6.1.1, 6.2.1, 7.1.x) замыкаются на `next` родителя;
- все внутренние ссылки всех 51 локальной страницы + хаба + главной отвечают 200 (с браузерным User-Agent; `Python-urllib` получает 403);
  все `#якоря` внутри страниц существуют; картинки и шрифты новых страниц отдают 200;
- `<title>`, `kb-pg`, `Stage N` в крошке и номер на тайле хаба совпадают между собой и с `kb.json` для каждой страницы;
- прод равен `origin/main` после патчера CI: сравнить тела 5 случайных страниц (кроме строк `?v=`);
- поиск на хабе находит «screens», «шаблоны», «диктора»; кнопка «🔗 ссылка на этап» у главы 1 даёт `/kb/#ch1`;
- 390 px: три новые страницы и `/kb/luts/` — без горизонтального скролла страницы, таблицы скроллятся внутри `.tbl`
  (честные 390 — через iframe `width:390`, headless Chrome не делает окно уже 500 px).

### 2.5 Правило примеров и сироты

- `gen_kb.py` печатает `EXAMPLES ⚠` для 0.4 drive-quota (YTCR04, YTEVO02, YTFP03) и 5.7 review-cycle (YTCH12, YTEVO02, YTUVI01, YTUVI02).
  Подготовить Роману предложение: какие два примера оставить на каждой странице и что вычистить. Без его решения не править.
- Единственная сирота под `web/kb/` — `gear/camera/index.html`, намеренный редирект на `/kb/gear/fx3a/`. Убедиться, что других не появилось.
- Страницы, на которые в KB никто не ссылается, кроме хаба, — список (не ошибка, наблюдение).

### 2.6 Целостность документов и памяти после трёх волн правок

Одни и те же файлы правились до четырёх раз. Проверить на противоречия внутри файла:
`reference_kb_system_yt_rya.md` (карта, правило заморозки, история ревизий), `TICKET_KB_preprod_chapter.md` (шапка против §7–8),
`TICKET_KB_chapters.md` (v3-пометка против тела), `HANDOFF_kb_structure.md` в репо, `CODEX.md` (52 маршрута, дата, раздел «Current known mismatch»),
`999_extra/pipeline_ch3.py` и его README (докстринг, STEPS, Telegram-строки — везде глава 4, гейт 4.4, прокси 3.4, зеркало 3.6).
Норма: файл не противоречит сам себе и карте.

---

## 3. КАК ВЕСТИ РАБОТУ

- **Сначала разбор, потом правки.** Показать Роману список находок с цитатами и предложением по каждой; править после его «да».
- Метод — несколько независимых искателей с разными углами (по контейнеру, по шаблону, по сущности «страница X», по времени изменения)
  и отдельный проход-опровергатель по каждой находке; повторять, пока два раунда подряд не дадут ничего нового.
- Правки сайта — в отдельном `git worktree` от `origin/main`; `patch_site_chrome.py` вызывать с явным `web` worktree.
- После правок страниц: `gen_kb.py` → `gen_index.py` → `patch_site_chrome.py web` → `gen_kb.py` ещё раз (диффа быть не должно) → `kb_renumber.py` (0 странных).
- Патчер нормализует `?v=` к `ASSET_V` из HEAD и задевает чужие страницы — откатить всё вне своей зоны (`git checkout -- web/<чужое>`). `ASSET_V` не бампать.
- **Деплой — через Винстона** (агент `winston-smith`), пуш из worktree `git push origin HEAD:main`; статус run смотреть через
  `gh api …/actions/runs?head_sha=<sha>` — фильтр `--branch` в этом репо показывает старые run'ы.
- **В конце открыть обновлённый сайт** в браузере (`open https://yt.rya.ae/kb/` и изменённые страницы).
- Главы не вставлять и не двигать. Номера страниц менять только если это прямо решит Роман.

### Известные ложные срабатывания (не чинить)

`manifest/index.html` — ~60 внутренних номеров правил монтажа 1.1–7.6 · `audio-enhance` «7.1» — каналы FLAC ·
«Шаг 4.5 / 4.6 ранбука», «ГЕЙТ 6.5» — шаги `WORDSYNC_RUNBOOK.md` · версии `v2.0`, `v2.2`, `Qwen2.5`, «5.6 Sol» ·
спецификации техники (`USB 3.2`, `CFexpress 4.0`, `FW 2.02`) · `4.8·fps` в `contracts.md` · id анимаций `2.1.3` в каталоге шаблонов (это номера карточек каталога, не KB) ·
`queue_ytch13_ytch14.sh` «зеркало 3.6» и `#ch3` — совпадают с картой случайно, верны · исторические файлы с пометкой сверху:
`0120_day_ingest/{HANDOFF_kb_deploy,HANDOFF_kb_chapters_deploy,TICKET_KB_chapters,TICKET_KB_day_ingest,TICKET_NEXT_SESSION}.md`.

---

## 4. КОМАНДЫ

```bash
# копия задеплоенного состояния для аудита (основное дерево не трогать)
A=<scratchpad>/audit4 && mkdir -p $A && cd ~/RYA/yt-rya-ae && git fetch -q origin \
  && git archive origin/main web scripts/site docs | tar -x -C $A && cd $A

python3 scripts/site/kb_renumber.py --old web/_data/kb.json            # карта «старый = новый»: странных 0, проза — глазами
find web -name '*.html' | sort | xargs md5 -q > /tmp/m1 && python3 scripts/site/gen_kb.py >/dev/null \
  && find web -name '*.html' | sort | xargs md5 -q > /tmp/m2 && diff -q /tmp/m1 /tmp/m2   # генератор воспроизводит задеплоенное

# прод: браузерный UA обязателен
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/148 Safari/537.36'
G(){ curl -s -A "$UA" --max-time 25 "https://yt.rya.ae$1"; }
G /kb/ | grep -o 'chap-n">[0-9]' | tr '\n' ' '                         # 0 1 2 3 4 5 6 7 8

# правки сайта — только так
cd ~/RYA/yt-rya-ae && git worktree add ~/RYA/yt-rya-ae-kb -b fix/kb-audit-pass4 origin/main
cd ~/RYA/yt-rya-ae-kb && python3 scripts/site/gen_kb.py && python3 scripts/site/gen_index.py \
  && python3 scripts/site/patch_site_chrome.py web && python3 scripts/site/gen_kb.py && git status --short
```

Скриншот закрытой страницы: копия `web/` в scratchpad, в `<head>` вписать `localStorage.setItem("rya_bypass","1")`,
поднять `python3 -m http.server` (file:// ломает `/assets`), снимать `~/.cache/puppeteer/chrome-headless-shell/…/chrome-headless-shell --headless --screenshot=…`.

---

## 5. ЧТО ЗНАТЬ И НЕ ТРОГАТЬ

- Рабочее дерево `~/RYA/yt-rya-ae` **чужое и грязное**: незакоммиченный бамп `ASSET_V` 22→23 в `scripts/site/site_chrome.py`,
  ~248 файлов с `?v=23`, правки `web/kb/storage/` и `web/kb/review-cycle/`. Там не коммитить, не `git add -A`, не bare `git stash`.
  Бот production-refresh коммитит в этом дереве `web/index.html` с `?v=23` при `ASSET_V = 22` в HEAD; CI на деплое приводит всё к 22 — прод консистентен.
- Чужой worktree `…/scratchpad/ytch-pub` (detached `9d66c67c`) — не трогать.
- Вторая копия патчера `~/YTAI/scripts/999_extra/{site_chrome,patch_site_chrome}.py` стоит на `ASSET_V = 22`; синкать тому, кто закоммитит бамп.
- `scripts/13_preprod/` не в git (решение Романа 16.09) — тикеты и хэндоффы этой стадии живут только локально.
- Находки по **источникам** (не по KB) уже записаны и ждут Романа — `TICKET_KB_preprod_chapter.md` §6: несуществующая `YTMSEN/_fonts/`,
  слово «урок» в `screen_kinds_uvie.py`, 15 превью против «14» в докстринге, тайминг занятия 57:47. Их не перепроверять.

---

## 6. КРИТЕРИИ ПРИЁМКИ

- [ ] Роману показан разбор ДО правок: находки поимённо, по каждой — предложение и цена
- [ ] пройдены все шесть пунктов §2; по каждому записано «что смотрел, сколько совпадений, что нашёл»
- [ ] два раунда поиска подряд не дали ничего нового (или явно сказано, на чём остановились и почему)
- [ ] 3.8 Scene LUTs и §7 в 4.1 Ingest сверены с кодом; расхождения исправлены или отданы Роману
- [ ] полный обход прода: цепочка `next:`, все внутренние ссылки 200, якоря существуют, номера согласованы на каждой странице
- [ ] `kb_renumber.py` — 0 странных; `gen_kb.py` дважды без диффа
- [ ] если были правки сайта — задеплоено Винстоном, прод сверен, сайт открыт в браузере; worktree и ветка сняты
- [ ] итог дописан разделом §9 в `TICKET_KB_preprod_chapter.md`; память `reference_kb_system_yt_rya` обновлена, если появились новые слепые зоны

## 7. ОТКРЫТЫЕ ВОПРОСЫ

1. Чистить ли примеры на 0.4 и 5.7 — и какие два оставить (решает Роман).
2. Нужен ли `kb_renumber.py` режим «весь `~/YTAI`» — сейчас он видит только `web/`, всё вне сайта ищется руками.
3. Оставлять ли имена `pipeline_ch3.py` и `ytch_chain` «по старому номеру главы» или переименовать в `pipeline_ingest.py` (задевает launchd и память).
4. Чем собраны `/ytevo/03/` лендинг и индекс ревью — руками или генератором (см. §2.2).
