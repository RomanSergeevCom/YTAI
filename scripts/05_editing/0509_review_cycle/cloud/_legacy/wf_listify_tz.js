// Листификация текстов ТЗ (Claude Code Workflow tool). Запуск:
//   Workflow({scriptPath: '.../wf_listify_tz.js', args: {data_file, rules_files:[…], batches:[[«ТЗ-03»,…],…], film}})
// data_file — listify_in.json: по каждому ТЗ его parts, строки-нарушители (multi_lines) и ПОЛНЫЕ находки
// аудита (чтобы не выдумывать факты). Результат → tz_overrides.json (parts_replace) и повторный s10.
// Канон Романа: «каждый таймкод — отдельной строкой „tc ▸ пункт"», одна строка — одна мысль.
export const meta = {
  name: 'listify-tz',
  description: 'Rewrite ТЗ texts into one-timecode-per-line lists, then have a skeptic check nothing was invented or lost',
  phases: [
    { title: 'Rewrite', detail: 'батч ТЗ → parts в формате «tc ▸ пункт»' },
    { title: 'Verify', detail: 'скептик на батч: смысл и факты сохранены, таймкоды не выдуманы' },
  ],
}

const DATA = args.data_file
const RULES = (args.rules_files || []).join(' , ')
const FILM = args.film || 'русскоязычный YouTube-док о рубинах'

const PARTS_SCHEMA = {
  type: 'object',
  properties: {
    tz: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          num: { type: 'string' },
          parts: { type: 'string', description: 'JSON строки: объект parts целиком (now/do/list/where/src/tl), как в data_file' },
          note: { type: 'string' },
        },
        required: ['num', 'parts'],
      },
    },
  },
  required: ['tz'],
}

const V_SCHEMA = {
  type: 'object',
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          num: { type: 'string' },
          ok: { type: 'boolean' },
          problems: { type: 'string', description: 'что потеряно/выдумано/не по канону; пусто если ok' },
          parts_fixed: { type: 'string', description: 'исправленный parts JSON, если сам поправил; иначе пусто' },
        },
        required: ['num', 'ok', 'problems'],
      },
    },
  },
  required: ['verdicts'],
}

const CANON = `
КАНОН (Роман):
• Каждый таймкод — отдельной строкой или пунктом, в НАЧАЛЕ: «M:SS ▸ что сделать» / «M:SS–M:SS ▸ …».
• Одна строка — одна мысль. Две ошибки, два слоя, две задачи через «;» — разнести на пункты.
• Никаких перечислений в строку через «→», «/», «|», «;», «·» (кроме дословной цитаты титра в «…», где «/» = перенос строки).
• Ничего не выдумывать: факты, числа и таймкоды берём ТОЛЬКО из parts и audit_findings_full этого же ТЗ.
• Внутренний жаргон (h0036, s128, слой V5) оставляем только в блоке «НА ТАЙМЛАЙНЕ».
• Секунды «166.0–168.6 с» → таймкоды «2:46–2:48».
• Структура parts не меняется: те же ключи (now/do/list/where/src/tl), элемент — строка или {"h","items":[…]}.
• «было → стало» и комментарии Романа в parts НЕ писать — их подставляет код.
Фильм: ${FILM}.`

const bundles = args.batches

phase('Rewrite')
const done = await pipeline(
  bundles,
  (b, _orig, i) => agent(
    `Ты — редактор ТЗ монтажёру. Прочитай Read'ом ${DATA} — это массив ТЗ с полями num, v1_tc, title, parts, ` +
    `multi_lines (строки, которые нарушают канон: в одной строке несколько таймкодов) и audit_findings_full.\n` +
    (RULES ? `Также прочитай правила формата: ${RULES}\n` : '') +
    `Перепиши parts ТОЛЬКО для этих ТЗ: ${b.join(', ')}.\n${CANON}\n` +
    `Верни для каждого ТЗ поле parts — JSON-СТРОКУ объекта parts целиком (json.dumps), а не текст. ` +
    `Ключи и порядок блоков сохрани, меняй только формулировки и разбиение на пункты.`,
    { label: `listify:${i + 1}`, phase: 'Rewrite', schema: PARTS_SCHEMA }),
  async (res, b, i) => {
    if (!res || !res.tz || !res.tz.length) return null
    const v = await agent(
      `Ты — скептик-редактор. В файле ${DATA} лежат исходные ТЗ (${b.join(', ')}) с полными находками аудита. ` +
      `Ниже — переписанные parts. Проверь по каждому ТЗ: (1) ни один факт, таймкод или число не выдуман и не потерян; ` +
      `(2) каждый таймкод стоит в начале своей строки/пункта, в одной строке не больше одного места действия; ` +
      `(3) одна строка — одна мысль, перечислений в строку нет; (4) структура parts не сломана и ключи те же; ` +
      `(5) действие монтажёра («✅ СДЕЛАТЬ») читается однозначно.\n${CANON}\n` +
      `Если что-то не так — дай parts_fixed (исправленный JSON-строкой) и опиши problems. Не переписывай то, что уже по канону.\n\n` +
      res.tz.map((t) => `### ${t.num}\n${t.parts}`).join('\n\n'),
      { label: `verify:${i + 1}`, phase: 'Verify', schema: V_SCHEMA })
    const fixed = {}
    for (const vv of (v && v.verdicts) || []) {
      if (vv.parts_fixed && vv.parts_fixed.trim()) fixed[vv.num] = vv.parts_fixed
    }
    return res.tz.map((t) => ({ num: t.num, parts: fixed[t.num] || t.parts,
      note: t.note || '', verdict: (v && v.verdicts || []).find((x) => x.num === t.num) || null }))
  },
)

const flat = done.filter(Boolean).flat()
const bad = flat.filter((t) => t.verdict && !t.verdict.ok && !t.verdict.parts_fixed)
log(`переписано ТЗ: ${flat.length} из ${bundles.flat().length}` +
  (bad.length ? ` · ⚠️ скептик недоволен без правки: ${bad.map((t) => t.num).join(', ')}` : ''))
return { tz: flat }
