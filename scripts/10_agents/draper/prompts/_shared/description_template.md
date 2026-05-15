---
artifact: description
inputs: [keep_chapters, key_quotes, channel_dna, channel_ctas, channel_links]
outputs: [description.txt, chapters.txt]
---

# Description structure

Two files. Both stem from chapters[] where verdict=KEEP.

## chapters.txt

One chapter per line. Format:

```
M:SS Title — конкретное обещание этой главы
```

Rules:
- Time format M:SS (or H:MM:SS if >60 min total).
- First chapter starts at 0:00 (YouTube requires this for chapter detection).
- Title — what's in the chapter. Not "Intro", not "Outro", never just a topic
  word. The title has to make a promise: "Дубай 2021 — почему ненавидел",
  not "Дубай 2021".
- Em-dash and one-line summary AFTER the title. Summary tells the viewer
  what they'll get if they jump here.
- 8–15 chapters typical for a 15–60 min video. If more — bundle similar.
- If less than 3 KEEP chapters — flag back to Roman, the video may not need
  chapters at all.

Example:
```
0:00 Cold Open — серия фраз-крючков из видео
0:32 Что будет дальше — структура разговора
1:10 Первое впечатление от Дубая — почему ненавидел
2:45 Adjustment — Palm Jumeirah и хобби, переломный момент
4:55 Переход в Core Realty — как Max-партнёр по волейболу всё изменил
```

## description.txt

YouTube description has 5,000 char limit but is mostly seen at 150 chars in
preview, ~5,000 if expanded. So write for two audiences: the preview viewer
(first 150 chars MUST sell) and the engaged viewer (rest gives depth).

Structure — 5 blocks in this order:

### 1. Hook (lines 1–2, ≤150 chars total)

Two-line hook that closes a curiosity loop OR states a contradiction. This
is what's visible in search results before expansion.

Examples:
```
5 лет назад он хотел сбежать из Дубая. Сегодня — учит брокеров зарабатывать.
В этом разговоре — почему он передумал.
```

```
ROI 25-35% на ремонте офисов в Дубае. Реальная схема, без воды.
Иван продал 6 офисов по этой стратегии. Делится цифрами и риском.
```

Do NOT start with "В этом видео…" or "Today we'll discuss…". Start with the
contradiction or the specific claim.

### 2. Value bullets (3–5 lines)

What the viewer learns. One outcome per bullet. Each bullet starts with
"-", "—" or "▶". No emoji in bullets.

Examples:
```
— Как Арти перешёл из ритейл-сектора в недвижимость за 3 месяца
— Стратегия "офисы под ремонт": почему 25-35% ROI реальный
— Что отличает Core Realty от средней брокерской в Дубае
— Дубайский bubble: разбор 5-летнего цикла на данных
```

### 3. Chapters block

Pull chapters.txt verbatim into description. YouTube auto-detects chapters
from description if first timestamp is 0:00 and there are 3+. Format:

```
00:00 Cold Open
00:32 Что будет дальше
01:10 Первое впечатление — ненависть к Дубаю
…
```

Format ALL timestamps as HH:MM:SS or MM:SS — YouTube is picky. Use leading
zeroes ("01:10" not "1:10"). 

### 4. CTA block (4–6 lines)

Pull from channel DNA. Always include:
- Channel subscribe nudge (one sentence, not "smash that subscribe button")
- Booking / contact link (if channel has one in DNA)
- Other channels in fleet (cross-promo if appropriate)
- Social media (if listed in DNA)

Format:
```
🔗 Узнать про Core Realty: https://corerealty.com
🔗 Стать брокером: https://corerealty.com/join
🔗 Следить за каналом — подпишись, если работаешь в Дубае с недвижимостью.
```

(Emoji only in CTA block — link prefix only — as visual anchor for the eye.)

### 5. Hashtags (line 1 max)

3–5 tags, no fluff. One line at the bottom.

```
#DubaiRealEstate #CoreRealty #BrokerLife #PropertyInvestment #UAE
```

## Total length target

- Description: 800–1,500 знаков. Beyond 1,500 = no one reads.
- Hook + bullets + chapters + CTA + hashtags = whole.

## What NOT to include

- "If you liked this video, leave a like" — automatic skip-zone
- "Don't forget to subscribe" — assume the viewer can read a button
- "Comment below" without specific question
- Any reference to "this video" / "today's video"
- Generic phrases: "stay tuned", "more on the way"

## Per-channel overrides

The channel-specific prompt (`prompts/{CHANNEL}.md`) may override:
- Output language (EN/RU)
- CTA links (channel-specific URLs)
- Hashtag set
- Specific forbidden phrases for that brand
- Whether to include a disclaimer (e.g., YTFP — благотворительный disclaimer)

Channel overrides take precedence over this template.
