# Контракт `feedback-v1` — «Обратная связь по кату vN»

_Версия контракта 2 · 22.09.2026 · единый интерфейс для модели, двух поверхностей и облачного сверщика._
_План и мотивы: `docs/TICKET_feedback_format.md`. Канон подачи — KB 5.6; жанра «сверка версий» в каноне нет, правила жанра — здесь._
_Версия 2: вкладка дока переведена на 6 колонок по решению Романа 22.09 (§8), добавлен слой визуалов (§9)._

## 0. Что это

Документ из двух частей, собираемый из ОДНОЙ модели `work/{cut}/feedback.json`:

- **Часть 1 «Новое в vN»** — пункты текущего ТЗ (`pravki/pravki_v2.json`).
- **Часть 2 «Проверка ТЗ v(N-1)»** — все пункты прошлого ТЗ, пересуженные заново по фактам нового ката.

Две поверхности, обе только читают модель и статусы не пересчитывают:

- HTML `{CODE}_{cut}_feedback.html` — продюсеру (кадры inline base64);
- вкладка Google Doc «Обратная связь · vN» — монтажёру (6 колонок, §8).

## 1. Ключи карточки (`review_card.json`)

| ключ | значение | по умолчанию |
|---|---|---|
| `prev_pravki` | путь к ТЗ прошлой версии, относительно `05_Review` (или абсолютный). Env `YTAI_PREV_PRAVKI` | нет → стадии сверки «пропущена» |
| `prev_cut_version` | `"v4"` | из `align_against` по `_v(\d+)\.words` |
| `images_mode` | `none` \| `public_folder` \| `temp_grant` | `public_folder` при непустом `shots_remote`, иначе `none` |
| `feedback_tab` | имя вкладки | `fb.tab_template` → «Обратная связь · {ver}» |
| `private_frames_folder_id` | Drive-папка для кадров дока, БЕЗ доступа `anyone` (ни прямого, ни унаследованного) | нет → `temp_grant` отказывает |
| `feedback_sensitive_extra` | номера `n` прошлого ТЗ, чувствительные по сути, но без флага `sensitive` в исходнике: список или строка `"86,97"`. Env `YTAI_FEEDBACK_SENSITIVE_EXTRA` | пусто |

Пункты из `feedback_sensitive_extra` получают `sensitive=true` со всеми следствиями: bucket `fund` или `blur` по обычному
правилу, `status_by=flag`, `sensitive_by="card"` (у размеченных в исходнике — `"prev"`), в облачный пакет не попадают.
Повод (YTCH12 v4): ТЗ-86 — выкидыш, ТЗ-97 — усыновлённые братья; в прошлом ТЗ флага у них не было.

`temp_grant` исполняется ТОЛЬКО интерактивно на Маке (`--images temp`); в автономном режиме и на Memex — принудительно `none`.
`images_mode` читается только из карточки (в обход env).

**Замер 21.09.2026 (шаг 0 плана), почему папка кадров — отдельный ключ, а не `materials_id`:**

- Папка спринта «YTCH S3» на Shared Drive YTCH открыта `anyone / reader` ПРЯМО на себе; всё под ней, включая
  `YTCH12_Sveta/Review_materials`, наследует этот доступ. Файл, залитый туда, отдаётся анониму сразу, а
  `permissions.delete` отвечает `403 … permission is inherited`. Протокол «выдать → вставить → отозвать» там невозможен.
- В папке без наследования («Мой диск» rs@rya.ae): до выдачи анониму отдаётся страница входа (не картинка);
  после `permissions.create` картинка доступна через ~2 с (`uc` 1,7 с · `lh3` 2,6 с); `permissions.delete` →
  **204 с пустым телом**; после отзыва `uc` перестаёт отдавать картинку через 3,4 с, `lh3` — через 7,7 с.
- Поэтому `doc_images` перед любой заливкой делает **предполётную проверку**: у `private_frames_folder_id`
  нет ни одного права `type=anyone` (в т.ч. `permissionDetails[].inherited`). Есть → отказ с текстом
  «папка открыта по ссылке: кадры были бы публичны постоянно», ничего не заливается.
- «Картинка отдаётся анониму» проверяется по `Content-Type: image/*`, а не по коду 200 (страница входа тоже 200).
- YTCH12: папка `_YTCH12_feedback_frames_private` = `1EhgT9F0uex0F01zWz7sIGgEivLVwubip` («Мой диск» rs@rya.ae, создана 22.09).

## 2. Файлы

| файл | кто пишет | что |
|---|---|---|
| `work/{cut}/feedback.json` | `shared/feedback_model.py` | модель (§3) |
| `work/{cut}/feedback_visuals/index.json` + `*.jpg` | `shared/feedback_visuals.py` | визуалы колонок 5–6 (§9) |
| `cloud/in/feedback_film.txt` | `shared/feedback_call.py --print-call` | лента фильма для агента (§6) |
| `cloud/in/feedback_items.json` | то же | пакет пунктов + `packet_sha` (§6) |
| `cloud/out/feedback_check.json` | облачный агент | вердикты (§6) |
| `{CODE}_{cut}_feedback.html` | `shared/feedback_page.py` | HTML-поверхность |
| `work/{cut}/feedback_doc_frames/` | `shared/doc_images.py` | JPEG для дока (подготовленные из визуалов) |
| `work/{cut}/feedback_grants.json` | `shared/doc_images.py` | журнал временных доступов (пишется ДО выдачи) |
| `pravki/feedback_frames_ids.json` | `shared/doc_images.py` | имя файла → Drive id |

## 3. Схема `feedback.json`

```jsonc
{
  "schema": "feedback-v1",
  "code": "YTCH12", "cut_version": "v5", "prev_cut_version": "v4",
  "built_at": "2026-09-21 22:40",          // локальное время сборки
  "build_no": 1,                            // прошлый feedback.json.build_no + 1
  "duration_sec": 3094.08,
  "prev_file": "v4_review/pravki_v4.json",
  "align": {"base": "YTCH12_v4", "moved": 0, "dropped_sec": 0.0, "coverage_pct": 99.0, "spans": 16},
  "thresholds": {"min_sig": 3, "sure": 0.80, "maybe": 0.50, "win_speech": 45, "win_screen": 120},
  "tally": {"new": 8, "prev_total": 162, "closed": 0, "open": 0, "blur": 0, "fund": 0, "unknown": 0},
  "summary_lines": ["…"],                   // pravki_lib.load_summary(W6)['lines'] или []
  "blockers": [                             // для первого экрана, ≤ 8, дубли между частями — один раз
    {"part": 1, "n": 4, "label": "ТЗ-04", "tc": "11:16", "do": "перенести вход фонда за 34-ю минуту"}
  ],
  "fund_topics": [{"key": "adoption", "title": "Тайна усыновления", "count": 5}],
  "frames_wanted": ["work/v5/hires/h0677.jpg"],   // все кадры, на которые ссылаются строки (пути от 05_Review) — для адресного
                                            // rsync с Memex: кадры 1 fps весят сотни МБ, целиком их не тянем
  "part1": [ /* row */ ],
  "part2": [ /* row */ ]
}
```

### Строка (одна форма для обеих частей)

```jsonc
{
  "part": 2,
  "n": 40,                                  // ИДЕНТИФИКАТОР: позиция в исходном списке, с 1. НЕ key (в ТЗ v4 key дублируется)
  "label": "ТЗ-40",                         // i18n.tz_label(n)
  "key": "must:…",                          // справочно
  "title": "Фонд входит слишком рано",      // очищенный заголовок
  "category": "structure",                  // graphics|cut|insert|structure|fund|check|color
  "severity": "must",                       // Часть 2: must|should · Часть 1: high|medium|low|""
  "sensitive": false,
  "blocker": true,                          // правило §4
  "sec_old": 657, "tc_old": "10:57",        // время в прошлом кате (null/"" если нет); у Части 1 — null
  "sec_new": 676.2, "tc_new": "11:16",      // время в НОВОМ кате; у Части 1 — родное время пункта
  "err": 1.2,                               // погрешность проекции, с
  "how": "span",                            // span|gap|dropped|none|native(Часть 1)
  "tc_fixed": false,                        // таймкод исходника был битым и восстановлен
  "parts": {                                // ВИДИМЫЙ текст: плоские списки строк, уже очищенные и пересчитанные на новый кат
    "now":   ["11:16 ▸ куратор объясняет работу фонда"],
    "do":    ["перенести вход фонда за 34-ю минуту"],
    "where": ["11:16–11:40"]
  },
  "more": 5,                                // сколько строк исходных блоков не вошло в parts → «ещё N строк — ТЗ v4, ТЗ-40»
  "status": "open",                         // new|closed|open|fund|unknown
  "status_by": "rule",                      // code|agent|flag|rule
  "evidence": {"kind": "rule", "tc": "11:16", "sec": 676, "text": "фонд впервые звучит на 11:16, правило канала — не раньше 34-й минуты"},
  "checks": [{"q": "…", "found": true, "tc": "1:32", "score": 0.92}],
  "bucket": "block",                        // new|block|open|blur|closed|fund|appendix
  "dup_of": 4,                              // n пункта Части 1, куда требование перенесено; иначе null
  "topic": null, "topic_title": null,       // для bucket fund / blur
  "frame": {"file": "work/v5/hires/h0677.jpg", "sec": 676, "what": "кадр ката v5"},   // путь от 05_Review; null если таймкода нет
  "typo": [{"was": "ЖУМАГУЛ", "now": "ЖИМАГУЛ"}],   // только Часть 1
  "agent_note": ""
}
```

Необязательные поля строки, появившиеся при доработке видимого текста:

| поле | смысл |
|---|---|
| `sensitive_by` | `"prev"` — флаг из прошлого ТЗ · `"card"` — из `feedback_sensitive_extra` |
| `see_n` | пункт отсылает к другому пункту той же части («полный список недостающего — ТЗ-01 · v4»); в `blockers[]` не идёт, пока блокером стоит адресат |
| `do_derived` | `true` — у исходного пункта не было ✅, действие сформулировано из ❌/заголовка без новых фактов |
| `ids` | карта внутренних ссылок прошлого ТЗ (`A4-12` → `ТЗ-40 · v4`) для замены в видимом тексте |
| `checks[].alt` | запасное написание цели для сверки по основе слова («куратор фонда» ↔ «куратор по семьям • фонд») |

У пункта с `checks`, где часть целей найдена, а часть нет, ПЕРВАЯ строка ✅ и `blockers[].do` формулируются из
НЕДОСТАЮЩЕГО («Добавить недостающее: подглавы — 1 из 17: «…», «…» и ещё 13»); ❌ такого пункта — «Сделано: …. Не хватает: ….»;
уже выполненные строки ✅ в видимый текст не идут. Текст прошлого ТЗ про «в кате нет X» нельзя печатать, если X в новом кате есть.

Пункты bucket `blur` имеют `status="open"`, `status_by="flag"`. `unknown` с `severity=must` идёт в `block`, не в `appendix`.
Видимая строка 📍 обязана содержать таймкод нового ката либо «весь фильм»; иначе она уходит в `more`.
Цитаты прошлого ТЗ режутся только по «;» — «в сомнении не резать»: строка с двумя таймкодами — допустимый WARN, обрубок — нет.

`frame.file` вычисляется по правилу (`work/{cut}/hires/h{int(sec_new)+1:04d}.jpg`; для Части 1 — лучший кадр пункта)
и пишется ДАЖЕ если файла локально нет: наличие проверяют рендереры и молча рисуют карточку без кадра.
Картинки `material_rich` прошлого ТЗ в Часть 2 не берутся — это кадры прошлого ката.

`evidence.text` — человеческая фраза БЕЗ таймкода внутри (таймкод живёт в `evidence.tc`), без жаргона
(`align`, `OCR`, `overlap 67%`, имена кадров запрещены). Примеры: «порядок сцен тот же, что в v4»,
«на экране 9 карточек из 13; нет: …», «реплика на месте: «…»».

## 4. Статусы, buckets, приоритет

| status | когда |
|---|---|
| `new` | все строки Части 1 |
| `closed` | найдены ВСЕ целевые цитаты пункта (или агент подтвердил с валидной цитатой) |
| `open` | требование не выполнено, есть доказательство |
| `fund` | `sensitive` и действие ждёт ответа фонда (статус по флагу, `status_by=flag`) |
| `unknown` | доказательства нет ни у кода, ни у агента |

| bucket | состав | как печатается |
|---|---|---|
| `new` | Часть 1 | полная строка; `blocker` → значок 🔴 в ячейке № |
| `block` | Часть 2, `blocker=true`, не closed | полная строка (при `dup_of` — одна строка) |
| `open` | остальное `open` без sensitive | полная строка (при `dup_of` — одна строка) |
| `blur` | `sensitive`, и в ✅/заголовке `блюр\|кроп\|обезлич\|размы` без условия | полная строка; must первыми |
| `closed` | `closed` | полная строка с зелёным вердиктом (§8) в доке; в HTML — список с мини-кадром |
| `fund` | остальные `sensitive` | список по темам: «таймкод ▸ что согласовать» |
| `appendix` | `unknown` | счётчик в теле; список свёрнут (HTML `<details>`, в доке — последняя строка-список) |

**`blocker` — только три вещи:** (1) привязан провал правила канала из `structure_checks.json`;
(2) ошибка факта или опечатка на экране (Часть 1: класс `fact|typo|mismatch`); (3) Часть 2: `severity=must`,
не `sensitive`, не `closed`, без `dup_of`. У Части 1 блокер НЕ выводится из `severity=high`.

**`dup_of`**: пункт Части 2 ↔ пункт Части 1, если у обоих привязан один и тот же провал правила, либо совпадает
`category` и `|sec_new(ч.2) − sec_new(ч.1)| ≤ 60`.

Сортировка внутри bucket — по `sec_new` (пункты без времени — первыми).

## 5. Лимиты видимого текста (одни для обеих поверхностей)

`feedback_view.short_blocks(row)`: ❌ 1 строка · ✅ до 4 · 📍 1 · затем строка «ещё N строк — вкладка ТЗ {prev}, ТЗ-NN».
Строка длиннее 240 знаков режется по границе предложения (хвост → в `more`), многоточия не ставятся.
Правило «≥2 таймкода в строке»: FAIL для Части 1 и для строк, порождённых кодом; WARN со счётчиком для цитат прошлого ТЗ.
Опечатки: «было» — красный жирный без зачёркивания, «стало» — зелёный жирный.

## 6. Облачный сверщик (один агент, только текст)

Кому: все `unknown` + все кодовые `closed` + кодовые `open` с `severity=must`. `sensitive` и кадры в облако НЕ идут.

`cloud/in/feedback_items.json`:
```jsonc
{"schema": "feedback-items-v1", "code": "YTCH12", "cut_version": "v5", "packet_sha": "ab12cd34",
 "film": "cloud/in/feedback_film.txt", "out": "cloud/out/feedback_check.json",
 "items": [{"n": 40, "title": "…", "category": "structure", "now": "…", "do": "…", "where": "…",
            "look": "10:30–12:00", "code_status": "open", "code_evidence": "…"}]}
```
`cloud/in/feedback_film.txt` — хронологическая лента нового ката: `M:SS [спикер] текст` · `ЭКРАН M:SS–M:SS «…»` · `VLM M:SS …`.

`cloud/out/feedback_check.json` (агент пишет сам ДО возврата):
```jsonc
{"schema": "feedback-check-v1", "cut_version": "v5", "packet_sha": "ab12cd34",
 "verdicts": [{"n": 40, "status": "closed|open|unknown", "tc": "11:16", "quote": "дословно из ленты, ≤120 знаков",
               "source": "speech|screen|vlm", "confidence": 0.9, "note": "одна человеческая фраза"}]}
```

Вливание (`feedback_call.py --apply`) — пессимистичное:

- `packet_sha` и `cut_version` обязаны совпасть с пакетом, иначе отказ (защита от устаревшего ответа);
- `n` обязан быть в пакете и уникален; `tc ≤ duration_sec`;
- `norm(quote)` обязана быть подстрокой ленты в ±20 с от `tc`, иначе вердикт отброшен, причина → `agent_note`;
- `closed` принимается только при `confidence ≥ 0.8` и валидной цитате; для `category=cut` — две соседние цитаты вокруг стыка;
- `open` поверх кодового `closed` принимается всегда; при сомнении — `unknown`;
- принятый вердикт: `status_by=agent`; после вливания buckets и `tally` пересчитываются.

## 7. Интерфейсы модулей

```
shared/feedback_model.py
  split_nado(text) -> dict[str, list[list[str]]]      # ключи now|do|list|where|src|tl; элемент = строки одного меченого куска
  join_parts(parts) -> str                             # для проверки lossless (после сведения пробелов)
  unwrap(lines) -> list[str]                           # склейка жёстких переносов по ~80 знаков
  clean_lines(lines) -> list[str]                      # JUNK, жаргон, резка строк с ≥2 таймкодами
  fix_tc(item, duration) -> (list[float], bool)        # секунды пункта в прошлом кате, признак «восстановлен»
  class Projector(base: dict); .project(sec) -> {"sec_new", "err", "how"}
  retime_text(line, projector, duration) -> str
  build(prev_path=None) -> dict ;  rebucket(fb) -> dict ;  CLI: [--prev PATH] [--out PATH] [--calibrate GOLD.json]

shared/feedback_call.py    CLI: --print-call | --apply [--from PATH] [--out PATH] [--exclude N,N] ;  validate(verdict, film_index, packet) -> (ok, why)
shared/feedback_view.py    load(path=None) · sections(fb) -> [(bucket, label, rows)] · head(fb) -> list[(kind, text)]
                           short_blocks(row) -> {"now": [...], "do": [...], "where": [...], "more_line": str|None}
                           list_line(row) -> str · caption(row) -> str · num_label(row) -> str · tc_label(row) -> str · fund_groups(rows) · dup_line(row)
shared/feedback_visuals.py build(fb, review_dir, out_dir, only_missing=False) -> index ;  CLI: --fb PATH --review-dir DIR [--out DIR] [--only-missing] [--selftest]   (§9)
shared/feedback_page.py    build(fb) -> (html, stats) ;  CLI: [--fb PATH] [--out PATH] [--max-kb 6000] [--send]
shared/tz_blocks.py        LBL, IND, IND2, render_block(key, lines, lang='ru') -> list[str], lint_line(s) -> list[str]   # копия s10:606-639
shared/doc_table.py        u16 · index_of · get_doc_retry · batch_update · lock · write_tab(...)
                           rows[i].imgs = [(col, line_idx, name)]  — картинки в ЛЮБОЙ колонке (v2: две колонки с картинками)
                           ключи спанов: label · title · was (красный жирный) · now (зелёный жирный) · warn (оранжевый жирный) · cap · muted · sec
shared/doc_images.py       prepare · upload_all · grant · revoke · insert_with_temp_grant · revoke_from_ledger · audit · preflight · resolve_mode ;  CLI: --audit | --revoke-ledger
shared/said.py             said(tc_range, v1_tc) -> {"text", "bold"}   # дословная речь нового ката вокруг таймкода (колонка «Говорит»)
stages/doc_tab_feedback_v1.py         build_rows(fb, lang, have_frames, tz_tab, visuals) -> (rows, head)  [чистая] ;  CLI: [--fb PATH] [--images none|temp] [--dump-requests FILE] [--force] [--frames-dir DIR]
stages/doc_tab_feedback_v1_verify.py  CLI: [--fb PATH] [--from-dump FILE] [--frames-dir DIR]   → печатает ALL PASS | FAIL …
```

Общие правила кода: никаких `P.need()` и чтения файлов на уровне модуля; идентификатор пункта — `n`;
`stages/doc_tab_tz_v3.py`, `stages/s9_materials_drive.py`, `stages/s10_format_tz.py` НЕ импортировать (побочные эффекты
модульного уровня) и не менять; человеческие строки — через `shared/i18n_strings/fb.py` (`T('fb.…')`).

## 8. Вкладка Google Doc — 6 колонок (решение Романа 22.09.2026)

Роман, дословно: «столбики: 1. Номер правки 2. Таймкод 3. Говорит (транскрипт) 4. Правильно / неправильно (цветов) и почему
5. Экран со стрелочкой показывает ошибку 6. Экраны с рекомендацией как надо и что можно сделать. Этот экран показываем,
даже если нет ошибки видимой, но надо добавить раздел или визуализацию. Обязательно ссылку и откуда взял визуализацию.
Ещё визуализацию можно создавать самому, не обязательно картинку подставлять».

ОДНА таблица. Колонки и ширины (сумма 676 pt):

| # | заголовок | pt | содержимое ячейки |
|---|---|---|---|
| 1 | № | 40 | `num_label(row)` («ТЗ-04» / «ТЗ-40 · v4»), 🔴 у блокера, второй строкой — значок категории |
| 2 | ⏱ TC | 44 | `tc_label(row)` (с «≈»); пусто, если времени нет |
| 3 | Говорит | 104 | дословная речь нового ката вокруг таймкода — `said.said(where_или_tc, tc_new)`, опорная фраза жирным; у пунктов без времени — пусто |
| 4 | Вердикт и почему | 168 | 1-я строка — вердикт ЦВЕТОМ: «❌ НЕПРАВИЛЬНО» (красный жирный, key `was`) для open/block/blur · «✅ ПРАВИЛЬНО» (зелёный жирный, `now`) для closed · «⚠️ ЖДЁТ ФОНДА» / «⚠️ БЛЮР — делает монтажёр» (оранжевый жирный, `warn`) · «👁 НЕ ПРОВЕРЕНО» (серый, `muted`); затем `【заголовок】` (жирный); затем «Почему:» + `evidence.text` (доказательство) + первая строка ❌ СЕЙЧАС; у Части 1 — строки опечаток «было «…» → стало «…»» (спаны was/now); внизу серым `more_line` |
| 5 | Экран с ошибкой | 160 | картинка `visuals[key].err` (кадр нового ката со стрелкой/рамкой на месте ошибки; для речевых пунктов — кадр на таймкоде) в своём абзаце + подпись «M:SS · что видно» (key `cap`); при отсутствии — пусто |
| 6 | Как надо | 160 | строки ✅ СДЕЛАТЬ (до 4) и 📍 ГДЕ (1); затем картинка `visuals[key].fix` (рекомендация: мокап/превью/наш драфт — ОБЯЗАТЕЛЬНА у каждого полного пункта, даже если ошибки на экране нет) + подпись + строка «Источник: …» (key `muted`; если есть URL — гиперссылка на него) |

Картинки 150 pt шириной в своём пустом абзаце-якоре. Канон 5.6 требует ≥250 pt для превью — при шести колонках
это невыполнимо; для ЭТОЙ вкладки минимум 140 pt (verify проверяет по `MIN_IMG_W` вкладки, а не канона).

Секции — строки с заливкой + HEADING_3 + [скобки], порядок `V.sections(fb)`: [ЧАСТЬ 1 · НОВОЕ В vN · n] → [ЧАСТЬ 2 · ПРОВЕРКА ТЗ v(N-1) · n]
→ [🔴 БЛОКИРУЕТ ВЫПУСК · n] → [❌ ОСТАЛОСЬ · n] → [⚠️ БЛЮР И ОБЕЗЛИЧИВАНИЕ · n] → [✅ ЗАКРЫТО · n] → [⚠️ ЖДЁТ ОТВЕТА ФОНДА · n] → [👁 НЕ ПРОВЕРЕНО · n].
Полные строки — buckets `new, block, open, blur, closed`. `fund` и `appendix` — одна строка-список в колонке 4 (по пункту на строку, темы фонда жирным).
Пункт с `dup_of` — одна короткая строка (`dup_line`) в колонке 4, без картинок.
Шапка над таблицей — `V.head(fb)` как есть (версия и дата сборки, итог, «держит выпуск», как читать) + строка про кадры при режиме `none`.

## 9. Слой визуалов (`shared/feedback_visuals.py`)

Строит картинки для колонок 5–6 и пишет `work/{cut}/feedback_visuals/index.json`:

```jsonc
{"schema": "feedback-visuals-v1", "built_at": "…", "rows": {
  "2:40": {                                          // ключ = "{part}:{n}"
    "err": {"file": "work/v5/feedback_visuals/p2_040_err.jpg", "caption": "11:16 · куратор объясняет работу фонда",
            "kind": "arrow|frame|none", "source": {"text": "кадр ката v5, 11:16", "url": null}},
    "fix": {"file": "work/v5/feedback_visuals/p2_040_fix.jpg", "caption": "11:16 · как надо: вход фонда после 34-й минуты",
            "kind": "mockup|preview|draft|reference|card",
            "source": {"text": "наш драфт по кадру v5 11:16; текст — ТЗ-40 · v4", "url": null}}}}}
```

Правила:
- JPEG, ширина 1000 px, ≤160 КБ; пути от `05_Review`. Кадры с людьми (в т.ч. ребёнок) бывают ТОЛЬКО в этих файлах и в док
  попадают ТОЛЬКО через `temp_grant`; на портал и в общий чат — никогда.
- `err` (колонка 5): Часть 1 — аннотированное превью стадии (`previews_doc/dp_*.jpg`, `err_frames/v6_err_*.jpg`) →
  кадр `frame.file` с рамкой и стрелкой по bbox экрана (когда `evidence.kind=screen` и bbox известен по OCR) → кадр на `sec_new`
  с подписью (речевые пункты) → `kind=none`, если времени нет.
- `fix` (колонка 6) — ОБЯЗАТЕЛЕН у каждой полной строки. Порядок: готовый мокап/превью стадии (`mockups/*.png`, `previews_doc`,
  `material_rich[].img` Части 1; для Части 2 — `mockups/card_NN.png` глав, `mockups/tz/tz_NN.png` из `tz_index.json`,
  `material_rich` прошлого ТЗ, если файл есть) → референс по URL (например, `burodd.ru/team` для имени куратора — картинка не
  качается, `kind=reference` печатается только ссылкой и текстом) → **наш драфт** (`kind=draft`): PIL-рендер на кадре нового ката
  в стиле канала (`style` профиля): для graphics — предлагаемый титр/подпись поверх кадра; для cut — кадр с полосой
  «✂ вырезать M:SS–M:SS»; для structure/insert — карточка «КАК НАДО» с первыми строками ✅ (текст без выдумок — только из модели).
- `source.text` обязателен всегда («кадр ката v5, 11:16» · «мокап стадии: mockups/card_07.png» · «наш драфт по кадру v5 …» ·
  «референс: burodd.ru/team»); `source.url` — если есть ссылка (Drive-ссылка на файл в `Review_materials`, URL референса).
- `--only-missing` дописывает в существующий индекс только отсутствующие ключи (двухпроходная сборка: часть кадров есть только на Memex).
