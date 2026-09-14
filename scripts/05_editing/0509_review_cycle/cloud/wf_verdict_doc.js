// Вердикт продюсерского ревью документального ката (Claude Code Workflow tool). ОДИН агент «verdict» +
// необязательный «tobe» (целевая структура, стиль «22 перестановки» YTCH12 v5) при args.want_tobe.
// Запуск — из вызова, который печатает shared/verdict_call.py --print-call:
//   Workflow({scriptPath: '.../cloud/wf_verdict_doc.js', args: {card, acts_compact, structure_checks, risk_top, transcript_path,
//            rules, existing_tz, chapters, out_path, want_tobe, tobe_out_path, film, code, cut_version, duration_sec}})
// Минимальный вызов review.py cloud verdict даёт только {card} — тогда агент читает карточку и берёт файлы из
// {review_dir}/work/{cut_version}/ (acts_compact.json, structure_checks.json, risk.json) и cloud/out/verdict.json.
// Транскрипт в промпт НЕ кладётся: агент получает ПУТЬ и читает диапазоны Read/Grep сам, проверяя каждый таймкод.
// Результат агент пишет Write'ом в out_path ДО возврата; приём — shared/verdict_call.py --apply.
export const meta = {
  name: 'review-verdict',
  description: 'Producer verdict for a documentary cut: mandatory edits, structure proposal, open questions, fund-sensitive notes',
  phases: [
    { title: 'Verdict', detail: 'один агент: акты + проверки структуры + риск-реестр + транскрипт по пути → вердикт' },
    { title: 'To-be', detail: 'по запросу: целевая структура с перестановками (как YTCH12 v5)' },
  ],
}

const A = args || {}
const CARD = A.card || ''
const CODE = A.code || 'кат'
const FILM = A.film || 'документальный фильм канала'
const OUT = A.out_path || ''
const TOBE_OUT = A.tobe_out_path || ''
const RULES = A.rules || 'правила канала — в YTs/{channel}/review_profile.json (rules_text, structure_rules, sensitivity).'
const RISK = Array.isArray(A.risk_top) ? A.risk_top : []
const EXISTING = Array.isArray(A.existing_tz) ? A.existing_tz : []
const CHAPTERS = Array.isArray(A.chapters) ? A.chapters : []

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', description: 'одно из: «принять» · «правки» · «серьёзные правки» · «пересборка» — и одно предложение почему' },
    headline: { type: 'string', description: 'одна фраза для продюсера: что с фильмом' },
    strengths: { type: 'array', items: { type: 'string' }, description: 'что работает — с таймкодами' },
    mandatory_edits: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          tc: { type: 'string', description: 'M:SS или M:SS–M:SS по кату, проверено по транскрипту' },
          what: { type: 'string', description: 'что сделать монтажёру — одно действие, одна мысль' },
          why: { type: 'string', description: 'почему — правило листа / канала или факт из транскрипта' },
        },
        required: ['tc', 'what', 'why'],
      },
    },
    structure_proposal: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string', description: 'название главы для зрителя (капс, 1–4 слова)' },
          tc_range: { type: 'string', description: 'M:SS–M:SS по кату' },
          note: { type: 'string', description: 'о чём глава / якорная фраза перед карточкой' },
        },
        required: ['title', 'tc_range'],
      },
    },
    open_questions: { type: 'array', items: { type: 'string' }, description: 'решения, которые может принять только продюсер' },
    sensitive_notes: { type: 'array', items: { type: 'string' }, description: '⚠️ на подтверждение фонда / блюр — с таймкодом; НЕ «вырезать»' },
    time_math: { type: 'string', description: 'арифметика хронометража: сейчас → после вырезов/вставок' },
  },
  required: ['verdict', 'mandatory_edits', 'structure_proposal', 'open_questions', 'sensitive_notes'],
}

const TOBE_SCHEMA = {
  type: 'object',
  properties: {
    chapters: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          n: { type: 'integer' },
          title: { type: 'string' },
          source: { type: 'string', description: 'откуда материал: диапазон ката M:SS–M:SS (или «вставка из исходников: сцена · файл · src-TC»)' },
          purpose: { type: 'string', description: 'зачем глава стоит здесь (драматургическая функция)' },
        },
        required: ['n', 'title', 'source'],
      },
    },
    moves: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          from_tc: { type: 'string' },
          what: { type: 'string' },
          to: { type: 'string', description: 'куда переставить: после какой фразы / главы' },
          why: { type: 'string' },
        },
        required: ['from_tc', 'what', 'to', 'why'],
      },
    },
    time_math: { type: 'string' },
    notes: { type: 'string' },
  },
  required: ['chapters', 'moves'],
}

const inputsBlock = [
  `Карточка фильма: ${CARD || '(нет — пути ниже абсолютные)'}`,
  `Акты (сводки локальной модели): ${A.acts_compact || '{review_dir}/work/{cut_version}/acts_compact.json — путь возьми из карточки'}`,
  `Проверки структуры (код, не мнение): ${A.structure_checks || '{review_dir}/work/{cut_version}/structure_checks.json'}`,
  `Транскрипт ката с пословными таймкодами (ПУТЬ, читать диапазонами Read offset/limit и Grep — целиком НЕ читать): ${A.transcript_path || 'ключ words в карточке'}`,
  `Хронометраж: ${A.duration_sec ? Math.round(A.duration_sec / 60) + ' мин' : 'см. карточку'} · главы карточки: ${CHAPTERS.join(' | ') || '—'}`,
].join('\n')

const riskBlock = RISK.length
  ? `РИСК-РЕЕСТР (top ${RISK.length}${A.risk_total ? ' из ' + A.risk_total : ''}; полный — work/{cut}/risk.json):\n` +
    RISK.map((r) => `- ${r.tc} ${r.action} · ${r.topic} · ${r.speaker || ''}: «…${r.phrase}…»`).join('\n')
  : 'РИСК-РЕЕСТР: пуст или не строился (risk_registry.py).'

const existingBlock = EXISTING.length
  ? `УЖЕ ЕСТЬ ТЗ (не дублируй; если правка покрыта — сошлись на номер в why):\n${EXISTING.join('\n')}`
  : 'Существующих ТЗ нет.'

phase('Verdict')
const verdict = await agent(
  `Ты — продюсерский ревьюер документального фильма ${FILM} (${CODE}${A.cut_version ? ', кат ' + A.cut_version : ''}).\n` +
  `Задача: вынести вердикт по кату и дать монтажёру ОБЯЗАТЕЛЬНЫЕ правки — как редактор, который смотрит фильм за зрителя,\n` +
  `а не как юрист. Работай по материалам ниже; смысл проверяй по транскрипту.\n\n` +
  `ВХОДЫ:\n${inputsBlock}\n\n${riskBlock}\n\n${existingBlock}\n\n` +
  `ПРАВИЛА КАНАЛА И ЛИСТА (обязательны, нарушение = правка):\n${RULES}\n\n` +
  `ПОРЯДОК РАБОТЫ:\n` +
  `1. Прочитай acts_compact.json и structure_checks.json (Read). Каждый fail в проверках структуры — это отдельная обязательная\n` +
  `   правка с таймкодом из проверки; pass — упомяни в strengths, если это заслуга монтажа.\n` +
  `2. По каждому акту реши: держит ли арку, есть ли дубли смысла, провисания, нарушения правил листа. Сомневаешься в цитате или\n` +
  `   таймкоде — Grep по транскрипту (поле "w" слов, "text" сегментов) и Read диапазона; таймкод в ответе = секунда первого слова\n` +
  `   фразы из транскрипта (M:SS). Ничего не цитируй по памяти.\n` +
  `3. Риск-реестр — чек-лист согласования, а не список вырезов: в sensitive_notes пиши «⚠️ на подтверждение фонда» / «блюр»\n` +
  `   с таймкодом и сутью; слово «вырезать» там допустимо только для дублей, техбрака и письменных запретов фонда.\n` +
  `4. structure_proposal — зрительские главы по существующему порядку ката (карточки на склейки), 8–15 штук, капс, каждая с\n` +
  `   tc_range и якорной фразой в note. Порядок ката не меняй (для перестановок есть отдельный агент to-be).\n` +
  `5. mandatory_edits — только то, без чего фильм нельзя выпускать: одно действие на запись, таймкод проверен, why — правило\n` +
  `   или факт. Желательное — не сюда. Всё, что уже покрыто существующим ТЗ, — не дублируй.\n` +
  `6. open_questions — решения, которые может принять только продюсер (переносить ли акт, резать ли монолог фонда).\n` +
  `7. verdict — одно из «принять» · «правки» · «серьёзные правки» · «пересборка» + одна фраза почему; time_math — арифметика.\n\n` +
  `ВЫХОД: ${OUT ? `запиши JSON ровно по схеме StructuredOutput в файл ${OUT} (Write) ДО возврата` : 'запиши JSON по схеме в {review_dir}/cloud/out/verdict.json (Write) ДО возврата'},\n` +
  `затем верни тот же объект. Русский язык, таймкоды M:SS, без внутреннего жаргона (ids кадров, имена файлов).`,
  { label: `verdict:${CODE}`, phase: 'Verdict', schema: VERDICT_SCHEMA, effort: 'high' })

if (!verdict) {
  log('агент вердикта не вернул результат (пропущен или упал) — см. journal.jsonl; повторный запуск возьмёт кэш')
  return { verdict: null, tobe: null }
}
log(`вердикт: ${String(verdict.verdict).slice(0, 80)} · обязательных правок ${verdict.mandatory_edits.length} · глав ${verdict.structure_proposal.length} · вопросов ${verdict.open_questions.length} · ⚠️ ${verdict.sensitive_notes.length}`)

let tobe = null
if (A.want_tobe) {
  phase('To-be')
  tobe = await agent(
    `Ты — режиссёр монтажа документального фильма ${FILM} (${CODE}). Ниже — вердикт ревью по текущему кату и материалы.\n` +
    `Задача: предложить ЦЕЛЕВУЮ структуру фильма (как план «v5» YTCH12: хребет истории с первых минут, фонд не раньше правила\n` +
    `листа и малыми кусками, последний звук — героя), выразив её списком ПЕРЕСТАНОВОК существующего материала ката.\n\n` +
    `ВХОДЫ:\n${inputsBlock}\n\nВЕРДИКТ РЕВЬЮ:\n${JSON.stringify(verdict, null, 1).slice(0, 12000)}\n\n` +
    `ПРАВИЛА:\n${RULES}\n\n` +
    `ПОРЯДОК: прочитай acts_compact.json; каждую главу целевой структуры привяжи к диапазону ката M:SS–M:SS (проверь по\n` +
    `транскрипту Grep/Read, что фраза-граница там есть); moves — каждая перестановка: откуда (from_tc), что (what — первые слова\n` +
    `куска), куда (to — после какой фразы/главы), зачем (why — правило или драматургия). Вставки из исходников допускаются\n` +
    `только если они названы в вердикте или карточке; иначе — только материал ката. time_math — итоговый хронометраж.\n` +
    `ВЫХОД: ${TOBE_OUT ? `запиши JSON по схеме в ${TOBE_OUT} (Write) ДО возврата` : 'запиши JSON по схеме в {review_dir}/cloud/out/tobe.json (Write) ДО возврата'}, затем верни тот же объект.`,
    { label: `tobe:${CODE}`, phase: 'To-be', schema: TOBE_SCHEMA, effort: 'high' })
  if (tobe) log(`to-be: глав ${tobe.chapters.length} · перестановок ${tobe.moves.length}`)
  else log('агент to-be не вернул результат')
}

return { verdict, tobe }
