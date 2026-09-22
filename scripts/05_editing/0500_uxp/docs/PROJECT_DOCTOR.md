# Project Doctor — UXP panel feature (ticket + design)

_Ticket created 2026-06-01. Lives in the YTAI Assembly UXP panel (`scripts/05_editing/0500_uxp/`)._

## Problem (recurring)

Sources arrive **at any stage** (editor handoff, a collaborator's drop, a relinked project).
Opening such a project, Premiere throws a huge **Link Media** list (offline media) + a
**Resolve Fonts** dialog. But **not everything in those lists is actually used on the
timeline** — much is leftover bin clips / alternates. Manually figuring out *what I
actually need to chase down* is slow and error-prone.

Proven offline (CLI `scripts/999_extra/prproj_media_inventory.py`): on YTRF01 the editor's
`врач_2.prproj` referenced 133 media, **96 offline** — but the editor's Drive drop had only
43 files. We need the panel to say precisely: **of what's offline, what is on the timeline →
that's the list to request.**

## Goal

A **"Doctor" tab** in the YTAI Assembly panel: one click → analyze the open project →
**clear, English, exportable report** of what the project needs, what's missing, what's
present — with the key filter **missing ∩ used-on-timeline = Action Required**. Works at any
pipeline stage.

## Placement (decision)

**Separate `Doctor` tab** (not a button inside Review). Rationale: it's QC/health, used at
*any* stage, independent of the Ingest→Assembly→Pre-Edit→Review flow. Tab bar becomes:
`Ingest | Assembly | Pre-Edit | Review | Doctor`.

## What it analyzes (uses live Premiere API — accurate, unlike offline parse)

Reuses existing panel functions (already in `index.js`):
- `dumpBinTree(rootItem)` → full project media inventory (every item + `getMediaFilePath()`).
- `dumpSequence()` / `dumpTrackClips()` → per sequence, every track item → `getProjectItem()`
  → source name + media path = **what's actually on a timeline**.

Pipeline:
1. **Inventory** — recurse `project.getRootItem()`; for each clip: name, media path, type.
2. **Presence** — `present` if the referenced path exists on disk (`uxpfs.getEntryWithUrl`);
   else `offline` (= what Premiere's Link Media shows).
3. **Usage** — walk target sequence(s); collect project items placed on tracks → `used`.
4. **Classify** each media item:
   - `offline + used`  → **🔴 Action Required** (must obtain — the request list).
   - `offline + unused` → ⚪ Offline (bin only) — ignore.
   - `present + used`   → ✅ OK.
   - `present + unused` → ◽ Present (unused).
5. **Fonts** (v1 best-effort) — read the open `.prproj` (gzip XML via pako, like marker
   export already does) → list referenced font families. Mark "verify in Resolve Fonts".
   (Full font-availability cross-check = v2.)

### Usage scope (decision: user toggle)
- **Active sequence** (default) — the cut you have open = what you care about.
- **All sequences** — union across every sequence (conservative; for multi-seq projects).

## Output — quality English report (decision)

Two files written to `<project>/00_Setup/05_Review/` (created if absent), then auto-opened:
- `{CODE}_doctor_{ts}.html` — self-contained dark-theme report (matches existing panel
  report style). Sections:
  - **Summary** — project, date, scope, counts (total / present / offline / action-required).
  - **🔴 Action Required** — offline + used. Columns: File · Type · Used in (seq ×N) · Original path.
    This is the copy-paste list to send the editor.
  - **Offline (not on timeline)** — FYI, collapsible.
  - **Present** — OK (collapsible).
  - **Fonts referenced** — list + "check Resolve Fonts" note.
- `{CODE}_doctor_{ts}.json` — machine-readable (same data) for automation / "send to editor".

All UI labels + report text in **English**.

## Files
```
0500_uxp/
  index.html                      # + Doctor tab button + #tab-doctor content
  index.js                        # + analyzeForDoctor() (reuses dumpBinTree/dumpSequence) + handler
  src/doctor/doctorReport.js      # buildDoctorHtml(result) + buildDoctorJson(result)  [pure]
  docs/PROJECT_DOCTOR.md          # this ticket
```

## Build status
- v1: tab + media analysis (inventory/presence/usage/classify) + EN HTML+JSON report. ← done
- v2 (build D11, 2026-06-11): **Find & Relink local** — `onDoctorRelink()` indexes media by
  basename across the project root (+ optional extra folder, prefilled with the channel
  parent), then re-points every offline bin clip to its local twin via the live Premiere API
  `ClipProjectItem.changeMediaFilePath()`. Exact basename wins (project root first); copy-marker
  alias ("Копия Vostorg A4344.MP4" → "Vostorg A4344.MP4") is the fallback. Auto-saves the
  project, re-runs Analyze, lists what's still genuinely missing (no local copy → request editor).
  `doctorCollectMedia` now also carries the bin `item` ref (in-memory only). Solves the recurring
  editor-handoff case where the .prproj points at `/Users/<editor>/…` but the file already sits
  in 01_Source/02_Edit/03_Exports.
- v2 remaining: font availability cross-check; per-sequence breakdown; dedup of bin-vs-timeline
  sources whose only diff is the copy-marker (currently relinked, not merged).

## Relink — how it works (one bin relink fixes every timeline use)
1. Build a `{ basename → nativePath }` index over the search roots (`getEntries()` recursion,
   media extensions only, skips `*_transcription`/`per_clip`/Auto-Save/Previews/logs, depth ≤ 9).
2. For each bin media item that is **offline** (`getMediaFilePath()` path missing on disk):
   basename → exact index hit, else normalised (copy-marker-stripped) hit.
3. `ppro.ClipProjectItem.cast(item).changeMediaFilePath(target[, true])` — retry with
   `overrideCompatibilityCheck=true` if the first call returns false.
4. `project.save()`, then `onDoctorAnalyze()` regenerates the report so the new state is visible.
5. Safety: target is always a **same-name** file; project-root copies are preferred over the
   extra folder; `changeMediaFilePath` is **not undoable** → UI says review + ⌘S.

## Test (in Premiere — needs live pass)
1. Reload panel (UXP Developer Tool → Load/Reload) in Premiere 25.6+.
2. Open a project with known offline media (e.g. YTRF01 `врач_2.prproj`).
3. Doctor tab → pick scope → **Analyze Project**.
4. Confirm report opens; **Action Required** count ≈ offline-clips-on-timeline; spot-check a
   few against Premiere's Link Media. Fix any API method-name issues from the loop.
```

## D17 — Ghost offline: файл на месте, Premiere всё равно красный

**Кейс (YTUVI01, 09.09.2026, живой).** SSD проекта выдернули при открытом Premiere, потом
воткнули обратно (том пере-смонтировался на новый `/dev` node). Premiere залатчил клипы в
offline и больше их не перепроверял: на таймлайне красный `Media offline`, а путь в `.prproj`
совпадает с реально существующим файлом байт-в-байт (12,1 ГБ, читается на ~950 МБ/с,
`ffprobe` парсит). **Переоткрытие проекта не лечит** — протухшее состояние живёт в bin-item'е,
а не в пути.

**Почему Doctor D11–D16 не мог это починить в принципе:**

- `analyzeForDoctor` определял offline ТОЛЬКО проверкой диска (`present = doctorPathExists`).
  Отсюда отчёт «551 present · 4 offline» при полностью красном таймлайне — отчёт врал.
- `onDoctorRelink` начинался с `if (await doctorPathExists(m.mediaPath)) continue;` —
  каждый ghost-offline клип отбрасывался как «уже слинкован».

То есть единственный случай, где монтажёр реально застревает, был единственным, который
Doctor отказывался трогать.

**Что добавлено:**

| Функция | Что делает |
|---|---|
| `doctorIsOfflineInPremiere(it)` | спрашивает САМ Premiere, а не диск. Перебирает все известные написания флага (`isOffline` / `getIsOffline` / `isMediaOffline` / `isOfflineMedia`…) на item и на `ClipProjectItem.cast`. Возвращает `true` / `false` / `null` (`null` = билд флага не отдаёт) |
| `doctorAltPathForm(p)` | `/dir/name.mp4` → `/dir/./name.mp4` — та же строка для ОС, другая для Premiere |
| `doctorForceRefreshItem(it, path, log)` | лестница починки: `refreshMedia()` → если нет, **bounce** `changeMediaFilePath(alt)` → `changeMediaFilePath(canonical)` |
| `onDoctorForceRefresh()` | кнопка **🩹 Force refresh**: берёт только клипы, которые Premiere зовёт офлайновыми, и перецепляет каждый на его же путь |

**Почему bounce, а не `changeMediaFilePath(samePath)`.** Premiere сравнивает строки: перецепка
на тот же путь — no-op, ничего не переимпортируется. Обе формы пути (`/dir/f.mp4` и
`/dir/./f.mp4`) указывают на одни и те же байты, но для Premiere это два разных пути → он
честно переимпортирует дважды и снимает offline-латч.

**Безопасность.** Обе формы ведут на один файл, поэтому обрыв посреди bounce оставляет клип на
корректном медиа — никогда на чужом. Если возврат на канонический путь не прошёл, это пишется
в лог как `WARN … left on alt spelling (same file)`. Не-undoable → ⌘S после.

**Слепой режим.** Если билд не отдаёт offline-флаг вообще, кнопка НЕ угадывает: она отказывается
работать и просит включить галочку `blind sweep`. Бомбить bounce'ом 500 здоровых клипов ради
одного больного — молча такое делать нельзя. Отчёт в этом случае пишет
`ghost-offline: unknown`, а не `0` — разница принципиальная.

**Отчёт.** В items добавлены `premiereOffline` и `ghostOffline`, в counts — `ghostOffline` и
`ghostDetectable`. Саммари в панели показывает отдельную строку `N ghost-offline`.

**Разделение труда:** 🔗 Find & Relink local отвечает на «файл переехал, где он теперь»,
🩹 Force refresh — на «файл никуда не девался, Premiere просто перестал в него верить».
Клип, который И офлайн, И без файла, Force refresh не трогает, а отдаёт в Relink.

**Файлы:** `index.js` (`doctorIsOfflineInPremiere`, `doctorAltPathForm`, `doctorForceRefreshItem`,
`onDoctorForceRefresh`, правки `analyzeForDoctor` + `onDoctorRelink`), `index.html`
(`btn-doctor-forcerefresh`, `doctor-force-blind`). Build `D17`.

**Статус:** `node --check` проходит; тесты 430/437 (7 падений — предсущие, в `screenBuilder`,
к Doctor'у отношения не имеют). Живой прогон в Premiere — за Романом.
