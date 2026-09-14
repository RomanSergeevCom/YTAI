// Один воркфлоу режима montage_tz (ТЗ на монтаж из исходников, ката нет) — ДВА агента, по одному на задачу:
//   structure     — из локальных тезисов (segments.json, Qwen3-8B) собрать структуру фильма: порядок, что снять,
//                   где графика, финальные тезисы; пишет REVIEW_DIR/cloud/out/structure.json (Write) и возвращает по схеме.
//   design_review — ревью дизайна ВСЕХ мокапов по ОДНОМУ контактному листу 4×4 (≤1568 px), а не поштучно;
//                   пишет cloud/out/design_review.json и возвращает по схеме.
// Локально всё остальное: нарезка (segment_local.py), монтажный лист по якорям (build_montage.py), мокапы с DOM-QC
// (build_mockups.py). Облако — только на смысловой синтез и на взгляд дизайнера, одним проходом (feedback_local_first).
//
// Запуск — строку с args печатает montage/structure_call.py --print-call [--task structure|design_review|both]:
//   Workflow({scriptPath: '…/cloud/wf_structure_src.js', args: {task: 'structure', segments_file, film, rules, target,
//             plan_file, gfx_existing, out_file}})
//   Workflow({scriptPath: '…/cloud/wf_structure_src.js', args: {task: 'design_review', sheets: ['…/contact_sheet_01.jpg'],
//             screens_file, film, rules, out_file}})
// После прогона: structure_call.py --apply (structure.json → montage_plan.json, ручные note сохраняются),
//                structure_call.py --apply-design (design_review.json → замечания к экранам каталога).
// ⚠️ Агент пишет файл сам ДО возврата: в скрипте нет доступа к ФС, а единственная копия результата до записи —
//    task-output прогона (так однажды потерялись находки аудита). Возврат по схеме — вторая копия.
export const meta = {
  name: 'montage-structure',
  description: 'montage_tz: one agent orders local theses into a film structure with graphics; one agent reviews the mockup contact sheet',
  phases: [
    { title: 'Structure', detail: 'один агент: порядок тезисов, что снять и почему, графика на слово, финальные тезисы' },
    { title: 'Design review', detail: 'один агент: контактный лист всех мокапов → замечания и одно действие на экран' },
  ],
}

const TASK = args.task || 'structure'
const FILM = args.film || 'русскоязычное документальное видео'
const RULES = args.rules || 'один тезис — один экран; графика в языке клиента; имена и должности единообразны'
const TARGET = args.target || 'по смыслу (обычно 40–55 % исходника)'

const STRUCTURE_SCHEMA = {
  type: 'object',
  properties: {
    order: { type: 'array', items: { type: 'string' }, description: 'id тезисов в порядке ЧИСТОВИКА (только те, что остаются)' },
    cuts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          keep: { type: 'boolean' },
          why: { type: 'string', description: 'одна фраза: почему остаётся / почему снято' },
        },
        required: ['id', 'keep', 'why'],
      },
    },
    graphics: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string', description: 'G01, G02… (существующие id из gfx_existing переиспользовать)' },
          on: { type: 'array', items: { anyOf: [{ type: 'number' }, { type: 'string' }] }, minItems: 2, maxItems: 2,
                description: '[секунда, слово] — слово ДОСЛОВНО из text тезиса, секунда — оценка внутри t_in…t_out' },
          text: { type: 'string', description: 'что написано на экране (заголовок / строки через « · »)' },
          kind: { type: 'string', description: 'new | client' },
          place: { type: 'string', description: 'full | lower-third | overlay' },
        },
        required: ['id', 'on', 'text', 'kind', 'place'],
      },
    },
    theses: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          thesis: { type: 'string', description: 'финальная формулировка тезиса — заголовок куска' },
          act: { type: 'string', description: 'акт/роль в драматургии: Крючок · Кто мы · Опора · Логика · Новость · Продукт · Зачем · Смысл · Призыв · Финал' },
        },
        required: ['id', 'thesis'],
      },
    },
    chapters: {
      type: 'array',
      items: { type: 'object', properties: { id: { type: 'string' }, title: { type: 'string' } }, required: ['id', 'title'] },
      description: 'главы YouTube: id тезиса, с которого глава начинается, и название',
    },
    notes: { type: 'string', description: 'что важно знать монтажёру о структуре целиком (3–6 предложений)' },
  },
  required: ['order', 'cuts', 'graphics', 'theses'],
}

const DESIGN_SCHEMA = {
  type: 'object',
  properties: {
    items: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string', description: 'id экрана с вариантом: G08_B' },
          ok: { type: 'boolean' },
          problems: { type: 'array', items: { type: 'string' } },
          fix: { type: 'string', description: 'ОДНО действие, которое закрывает главную проблему; пусто если ok' },
        },
        required: ['id', 'ok', 'problems', 'fix'],
      },
    },
    summary: { type: 'string', description: 'общие замечания к серии экранов (единообразие, ритм тёмных/светлых, типографика)' },
  },
  required: ['items'],
}

function structurePrompt() {
  return `Ты режиссёр монтажа. Фильм: ${FILM}.
Ката нет — есть ИСХОДНИК, нарезанный локальной моделью на тезисы. Прочитай Read'ом файл ${args.segments_file}:
JSON-массив объектов {id, thesis, t_in, t_out, dur, speaker, quality (clean|retake|service), text (дословно), block}.
${args.plan_file ? `Есть предыдущий план ${args.plan_file} — прочитай его: ручные заметки (note) и уже придуманные экраны надо уважать, а не переизобретать.` : ''}
${args.gfx_existing ? `Уже существующие экраны графики (id → название), их id переиспользуй: ${JSON.stringify(args.gfx_existing)}` : ''}

ЗАДАЧА — собрать структуру чистовика:
1. order — id тезисов в порядке чистовика. Хронология исходника не обязательна: холодный старт с самого сильного места,
   потом «кто мы», опора, логика, новость, продукт, зачем, смысл, призыв, финал — если материал это даёт.
   Целевой хронометраж: ${TARGET}. Тезисы quality=service не берём; retake берём, только если та же мысль нигде не звучит чище.
2. cuts — ВЕРДИКТ НА КАЖДЫЙ id из файла (keep true/false + why одной фразой). Ни один тезис не должен остаться без вердикта.
3. graphics — где на экране нужна графика: id (G01, G02…), on = [секунда, слово] — слово ДОСЛОВНО из text тезиса
   (первое слово фразы, на которой экран должен встать), секунда — твоя оценка внутри t_in…t_out этого тезиса
   (код найдёт ближайшее вхождение слова в ±6 с); text — что написано на экране; kind new|client; place full|lower-third|overlay.
   Обязательно: плашки имён/должностей на первом появлении каждого говорящего; карточка-исправление там, где спикер
   ошибается в названии/перечислении; заставка; финальный экран с призывом/контактом.
4. theses — финальная формулировка каждого оставленного тезиса (заголовок куска) и act.
5. chapters — главы YouTube (id тезиса начала главы + название), 6–12 глав.
6. notes — 3–6 предложений монтажёру о структуре целиком.

ПРАВИЛА КАНАЛА: ${RULES}
Язык — русский. Ничего не выдумывай: все формулировки экранов — из слов спикеров или их материалов.

ПЕРЕД ВОЗВРАТОМ запиши результат (ровно тот же JSON-объект, что вернёшь по схеме) инструментом Write в файл
${args.out_file} — это единственная копия результата, если сессия оборвётся. Потом верни объект.`
}

function designPrompt() {
  const sheets = (args.sheets || []).join(', ')
  return `Ты арт-директор. Фильм: ${FILM}. Правила канала: ${RULES}.
Открой Read'ом контактный лист(ы) мокапов графики: ${sheets} — это JPEG-сетка 4×4, в каждой ячейке экран 4K (ужатый) и подпись
с его id (например G08_B). Список ячеек с названиями и типом (new — наш драфт, client — слайд клиента, alpha — плашка поверх кадра)
лежит в ${args.screens_file}. Смотри ВЕСЬ лист сразу, а не по одному экрану: единообразие, ритм тёмных/светлых, повторяющиеся ошибки.

Для КАЖДОГО экрана верни {id, ok, problems[], fix}: читаемость (крупность, контраст, длина строк), типографика и капс,
соответствие визуальному языку клиента, опечатки и переносы, композиция и воздух, у плашек — как ложатся на кадр
(перекрывают ли лицо). problems — конкретные («заголовок в 3 строки, третья висит одним словом»), fix — ОДНО действие.
Слайды клиента не критикуем — только отмечаем, если они спорят с нашими экранами. Вкусовщину без последствий для зрителя
не пиши. Язык — русский.

ПЕРЕД ВОЗВРАТОМ запиши результат инструментом Write в файл ${args.out_file} (тот же JSON, что вернёшь по схеме), потом верни объект.`
}

const out = {}

if (TASK === 'structure' || TASK === 'both') {
  if (!args.segments_file || !args.out_file) throw new Error('structure: нужны args.segments_file и args.out_file')
  phase('Structure')
  log(`структура: тезисы ${args.segments_file} → ${args.out_file}`)
  const r = await agent(structurePrompt(), { schema: STRUCTURE_SCHEMA, label: 'structure', phase: 'Structure' })
  if (r) {
    const kept = r.cuts.filter(c => c.keep).length
    log(`структура: в чистовике ${r.order.length} тезисов, keep ${kept}/${r.cuts.length}, экранов ${r.graphics.length}, глав ${(r.chapters || []).length}`)
  } else {
    log('структура: агент не вернул результат — проверь journal.jsonl и файл out_file')
  }
  out.structure = r
}

if (TASK === 'design_review' || TASK === 'both') {
  if (!args.sheets || !args.sheets.length || !args.out_file) throw new Error('design_review: нужны args.sheets и args.out_file')
  phase('Design review')
  log(`ревью дизайна: листов ${args.sheets.length} → ${args.design_out_file || args.out_file}`)
  const prevOut = args.out_file
  if (TASK === 'both' && args.design_out_file) args.out_file = args.design_out_file
  const r = await agent(designPrompt(), { schema: DESIGN_SCHEMA, label: 'design_review', phase: 'Design review' })
  args.out_file = prevOut
  if (r) log(`ревью дизайна: экранов ${r.items.length}, с замечаниями ${r.items.filter(i => !i.ok).length}`)
  else log('ревью дизайна: агент не вернул результат — проверь journal.jsonl')
  out.design_review = r
}

return out
