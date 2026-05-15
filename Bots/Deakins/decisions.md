# Decisions journal — Roman Sergeev production gear

> Append-only log of gear-related decisions: what was considered, what was
> chosen, why, and how it worked out. Never edit past entries — history is
> the value. Newest at top.

**Convention:** date prefix `YYYY-MM-DD`, then short title. Each entry has
**Context**, **Considered**, **Chose**, **Reasoning**, **Outcome** (added
later when actual usage data accumulates), **Tags**.

---

## 2026-05-15 — bulk import инвентаря из docx

**Context:** Рома прислал docx (14.7 MB, 22 встроенные фото) со вкладками
Tab 4 (текущий парк), Tab 1 (старый Fuji setup), Идеи (wishlist), Brief
(field protocol пример для съёмки Amell в Alexandria VA), Tab 2 (YouTube
ref «My Entire YouTube Studio on One Desk»). Источник: `inbox/1778828032598-AgADJ5oAApheMEg.docx`.

**Considered:** N/A — это import, не gear-decision.

**Chose:** Структура inventory.md:
- Активный парк (Cameras / Lenses / Audio / Lighting / Support / Power / Cases
  / Transmission / Studio infra) — из Tab 4 (52 строки таблицы).
- Архивный раздел в конце — старый Fuji X-mount setup (Tab 1) сохранён
  как memory: если что-то «оживёт», переедет наверх.
- Wishlist полностью из «Идей» (19 строк таблицы) с трехуровневой
  приоритезацией (1/2/3) на основе наличия дублей в активном парке.

**Reasoning:** Без явной даты покупки или серийников нельзя датировать
каждую позицию — но базовый ground truth теперь зафиксирован. Дальше Рома
будет уточнять детали по мере того, как они всплывают в работе.

**Outcome (зафиксировать позже):** первая итерация может содержать ошибки
интерпретации (например, «ZV-E1 как FX3» — буквально «второй FX3-like
body» или «настройки имитируют FX3»? Допущено первое).

**Open questions to Roman:**
1. Mac/MBP/мониторы/recorders — docx не покрывает, дополни при оказии.
2. DJI Mic 3 — сколько TX, есть ли RX-плагин для FX3 hot-shoe?
3. 22 фото в `inventory_photos/` — соответствие к позициям не извлечено
   автоматически. Можно ли пройти визуально и подписать?

**Tags:** meta, inventory, import, docx

---

## 2026-05-15 — wishlist «Идеи» отброшен

**Context:** После import'а Рома пересмотрел импортированные «Идеи» (Sony
ZV-E10 II, Tamron 17-70, Sirui Aurora 35/85, Viltrox 27/1.2 X, Aputure
Amaran 200x S, параболик 85cm и др.) и сказал «убери идеи нафиг, они не
имеют смысла».

**Considered:** оставить с пометкой rejected vs полное удаление.

**Chose:** полное удаление позиций — оставлен только stub-шаблон. Журнал
этого решения остаётся как memory: какие позиции рассматривались и
отброшены оптом.

**Reasoning:** wishlist должен отражать актуальные намерения, а не
исторический dump. История теперь в этом entry.

**Tags:** meta, wishlist, cleanup

---

## 2026-05-15 — initialized decisions journal

**Context:** Deakins агент создан, журнал решений пуст. Дата старта работы — 15.05.2026.

**Considered:** N/A — meta-entry.

**Chose:** Структура `## YYYY-MM-DD — title` для append-friendly chronology,
newest-first reverse order для quick scan самых свежих решений.

**Reasoning:** Deakins ссылается на journal перед каждой рекомендацией —
структурированный markdown проще парсить.

**Outcome:** см. следующие записи.

**Tags:** meta
