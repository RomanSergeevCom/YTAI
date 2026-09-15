// Вердикт продюсерского ревью документального ката (Claude Code Workflow tool). ОДИН агент «verdict» +
// необязательный «tobe» (целевая структура, стиль «22 перестановки» YTCH12 v5) при args.want_tobe.
// Запуск — из вызова, который печатает shared/verdict_call.py --print-call:
//   Workflow({scriptPath: '.../cloud/wf_verdict_doc.js', args: {card, acts_compact, structure_checks, risk_top, transcript_path,
//            rules, existing_tz, chapters, out_path, want_tobe, tobe_out_path, film, code, cut_version, duration_sec}})
// Минимальный вызов review.py cloud verdict даёт только {card} — тогда агент читает карточку и берёт файлы из
// {review_dir}/work/{cut_version}/ (acts_compact.json, structure_checks.json, risk.json) и cloud/out/verdict.json.
// Транскрипт в промпт НЕ кладётся: агент получает ПУТЬ и читает диапазоны Read/Grep сам, проверяя каждый таймкод.
// Результат агент пишет Write'ом в out_path ДО возврата; приём — shared/verdict_call.py --apply.
// Язык: const L = args.lang === 'en' ? EN : RU. RU (любое значение, кроме 'en') — промпты и схемы байт-в-байт как были
// (продюсерский вердикт YTCH: фонд, чувствительное, главы). EN — редакторский вердикт англоязычного интервью-дока
// (профиль verdict.kind 'editorial', YTCR): арка канала по 5 битам (args.arc), провисания → observations (не ТЗ),
// дословные повторы (args.align_duplicates / align_path), обязательные правки, открытые вопросы; exclusions карточки —
// известные дыры, не правки; без фонда; главы предлагаются только при args.propose_chapters (иначе несогласие → open_questions).
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
const OUT = A.out_path || ''
const TOBE_OUT = A.tobe_out_path || ''
const RISK = Array.isArray(A.risk_top) ? A.risk_top : []
const EXISTING = Array.isArray(A.existing_tz) ? A.existing_tz : []
const CHAPTERS = Array.isArray(A.chapters) ? A.chapters : []

// ── RU: продюсерский вердикт (YTCH) — тексты без изменений ─────────────────────────────────────────────
const RU = (() => {
  const CODE = A.code || 'кат'
  const FILM = A.film || 'документальный фильм канала'
  const RULES = A.rules || 'правила канала — в YTs/{channel}/review_profile.json (rules_text, structure_rules, sensitivity).'

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

  return {
    CODE,
    VERDICT_SCHEMA,
    TOBE_SCHEMA,
    verdictPrompt: () =>
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
    noVerdict: 'агент вердикта не вернул результат (пропущен или упал) — см. journal.jsonl; повторный запуск возьмёт кэш',
    verdictLog: (verdict) =>
      `вердикт: ${String(verdict.verdict).slice(0, 80)} · обязательных правок ${verdict.mandatory_edits.length} · глав ${verdict.structure_proposal.length} · вопросов ${verdict.open_questions.length} · ⚠️ ${verdict.sensitive_notes.length}`,
    tobePrompt: (verdict) =>
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
    tobeLog: (tobe) => `to-be: глав ${tobe.chapters.length} · перестановок ${tobe.moves.length}`,
    noTobe: 'агент to-be не вернул результат',
  }
})()

// ── EN: editorial verdict for an English interview documentary (profile verdict.kind 'editorial', e.g. YTCR) ──
const EN = (() => {
  const CODE = A.code || 'cut'
  const FILM = A.film || "the channel's interview documentary"
  const RULES = A.rules || 'channel rules — YTs/{channel}/review_profile.json (rules_text).'
  const PROPOSE = A.propose_chapters === true
  const EXCL = Array.isArray(A.exclusions) ? A.exclusions : []
  const DUPS = Array.isArray(A.align_duplicates) ? A.align_duplicates : []
  const n = (x) => (Array.isArray(x) ? x.length : 0)

  const EDIT_ITEM = {
    type: 'object',
    properties: {
      tc: { type: 'string', description: 'M:SS or M:SS–M:SS in the cut, verified in the transcript' },
      what: { type: 'string', description: 'what the editor must do — one action, one thought (cut / trim / remove / insert / restore / add title)' },
      why: { type: 'string', description: 'why — a channel rule or a fact from the transcript' },
    },
    required: ['tc', 'what', 'why'],
  }

  const VERDICT_SCHEMA = {
    type: 'object',
    properties: {
      verdict: { type: 'string', description: 'one of: «accept» · «fixes» · «major fixes» · «rebuild» — plus one sentence why' },
      headline: { type: 'string', description: 'one line for the producer: where the film stands' },
      strengths: { type: 'array', items: { type: 'string' }, description: 'what works — with timecodes' },
      arc_check: {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            beat: { type: 'string', description: 'beat name from the channel arc (e.g. Sacrifice, Turning point, Climb, Transition, Victory)' },
            status: { type: 'string', enum: ['present', 'weak', 'missing', 'out_of_order'] },
            tc: { type: 'string', description: 'M:SS or M:SS–M:SS where the beat lands in the cut; empty if missing' },
            note: { type: 'string', description: 'one line: how the beat plays, verified in the transcript' },
          },
          required: ['beat', 'status', 'note'],
        },
      },
      mandatory_edits: { type: 'array', items: EDIT_ITEM },
      observations: {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            tc: { type: 'string', description: 'M:SS–M:SS in the cut' },
            note: { type: 'string', description: 'sagging / static stretch: why the story does not move here — for the producer, not a fix' },
          },
          required: ['tc', 'note'],
        },
      },
      structure_proposal: {
        type: 'array',
        description: PROPOSE ? 'viewer chapters in the existing cut order' : 'must stay an empty array — the chapter plan is set in the card',
        items: {
          type: 'object',
          properties: {
            title: { type: 'string', description: 'viewer-facing chapter name (1–4 words)' },
            tc_range: { type: 'string', description: 'M:SS–M:SS in the cut' },
            note: { type: 'string', description: 'what the chapter is about / the anchor line before the card' },
          },
          required: ['title', 'tc_range'],
        },
      },
      open_questions: { type: 'array', items: { type: 'string' }, description: 'decisions only the producer can make — each with a timecode' },
      time_math: { type: 'string', description: 'runtime arithmetic: now → after the mandatory fixes' },
    },
    required: ['verdict', 'arc_check', 'mandatory_edits', 'open_questions'].concat(PROPOSE ? ['structure_proposal'] : []),
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
            source: { type: 'string', description: 'where the material comes from: cut range M:SS–M:SS (or «insert from sources: scene · file · src-TC»)' },
            purpose: { type: 'string', description: 'why the chapter sits here (its dramatic function in the arc)' },
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
            to: { type: 'string', description: 'where to move it: after which line / chapter' },
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
    `Film card: ${CARD || '(none — the paths below are absolute)'}`,
    `Acts (extractive digest per chapter, no model summaries — opening words, spread key sentences, numeric claims, on-screen text): ${A.acts_compact || '{review_dir}/work/{cut_version}/acts_compact.json — take the path from the card'}`,
    `Structure checks (code, not opinion): ${A.structure_checks || '{review_dir}/work/{cut_version}/structure_checks.json'}`,
    `Cut transcript with per-word timecodes (a PATH — read it in ranges with Read offset/limit and Grep, never whole): ${A.transcript_path || 'the words key in the card'}`,
    `Cut ↔ previous version alignment (align.json: cut_map, new, unused, moved, duplicates): ${A.align_path || 'none'}`,
    `Channel story document: ${A.channel_doc || '—'}`,
    `Runtime: ${A.duration_sec ? Math.round(A.duration_sec / 60) + ' min' : 'see the card'} · card chapters: ${CHAPTERS.join(' | ') || '—'}`,
  ].join('\n')

  const arcBlock = `CHANNEL STORY ARC (the beats every guest story must hit):\n` +
    (A.arc || `(not passed — read the "Story-arc template" section of ${A.channel_doc || 'YTs/{channel}/{channel}.md'})`)

  const exclBlock = EXCL.length
    ? `KNOWN GAPS (card exclusions — known and accepted, NOT edits; never report anything inside them and never ask about them):\n` +
      EXCL.map((e) => `- ${e.tc || 'timecode not set yet'} · ${e.reason || ''}`).join('\n')
    : 'KNOWN GAPS: none in the card.'

  const dupBlock = DUPS.length
    ? `VERBATIM REPEATS FOUND BY CODE (the same word run twice in the cut — first = second; verify each in the transcript):\n` +
      DUPS.map((d) => `- ${d}`).join('\n')
    : 'VERBATIM REPEATS: none found by code (align.json missing or clean) — still flag any you notice.'

  const existingBlock = EXISTING.length
    ? `FIXES ALREADY LOGGED (do not duplicate; if a fix is already covered, cite its number in why):\n${EXISTING.join('\n')}`
    : 'No fixes logged yet.'

  const chaptersRule = PROPOSE
    ? `6. structure_proposal — viewer chapters in the existing cut order (cards on cuts), 8–15 of them, each with tc_range and the\n` +
      `   anchor line in note. Do not reorder the cut (the to-be agent handles moves).\n`
    : `6. CHAPTERS: the chapter plan in the card is set by the producer — do NOT propose a chapter structure (structure_proposal = []).\n` +
      `   If you disagree with a chapter's position or name, put it in open_questions with the timecode.\n`

  return {
    CODE,
    VERDICT_SCHEMA,
    TOBE_SCHEMA,
    verdictPrompt: () =>
      `You are the producer-reviewer of an English-language interview documentary: ${FILM} (${CODE}${A.cut_version ? ', cut ' + A.cut_version : ''}).\n` +
      `Task: give a verdict on the cut and the editor's MANDATORY fixes — as an editor who watches the film on behalf of the viewer.\n` +
      `Work from the materials below; check meaning in the transcript. The editor reads English.\n\n` +
      `INPUTS:\n${inputsBlock}\n\n${arcBlock}\n\n${exclBlock}\n\n${dupBlock}\n\n${existingBlock}\n\n` +
      `CHANNEL RULES (binding):\n${RULES}\n\n` +
      `PROCEDURE:\n` +
      `1. Read acts_compact.json and structure_checks.json (Read). A check with status fail is a separate mandatory fix with the\n` +
      `   check's timecode; n/a checks are ignored. Unsure about a quote or a timecode — Grep the transcript ("w" field of words,\n` +
      `   "text" of segments) and Read the range; a timecode in the answer = the second of the phrase's first word (M:SS). Never quote from memory.\n` +
      `2. Arc check — for each beat of the channel arc: where it lands in the cut (M:SS, verified), status present · weak · missing ·\n` +
      `   out_of_order, one line why. A cold open that starts on the victory frame and cuts to the sacrifice beat is the channel's\n` +
      `   pattern, not a problem. An arc problem becomes a mandatory fix only when the material is in the cut and its placement breaks\n` +
      `   the story (a payoff before its setup, a beat referenced before it happens); otherwise it goes to open_questions.\n` +
      `3. Sagging / static stretches — roughly a minute or more where the story does not move (the same point restated, no new fact,\n` +
      `   turn or emotion): observations with a tc range and one line why. Pacing and taste are NEVER mandatory fixes.\n` +
      `4. Verbatim repeats — check every repeat found by code and any you notice: the same sentence or take heard twice = a mandatory\n` +
      `   fix (say which occurrence to remove). The cold open deliberately echoes lines from later in the film — an echo of a later line\n` +
      `   inside the opening is NOT a repeat.\n` +
      `5. mandatory_edits — only what blocks release: one action per entry, timecode verified, why = a channel rule or a transcript\n` +
      `   fact. Nothing already logged, nothing inside the known gaps, no taste / pacing / layout.\n` +
      chaptersRule +
      `7. open_questions — decisions only the producer (Roman) can make, each with a timecode.\n` +
      `8. verdict — one of «accept» · «fixes» · «major fixes» · «rebuild» + one sentence why; headline — one line for the producer;\n` +
      `   strengths — what works, with timecodes; time_math — runtime now → after the mandatory fixes.\n` +
      `There is no fund, sensitivity or blur logic on this channel — do not produce any.\n\n` +
      `OUTPUT: ${OUT ? `write the JSON exactly per the StructuredOutput schema to ${OUT} (Write) BEFORE returning` : 'write the JSON per the schema to {review_dir}/cloud/out/verdict.json (Write) BEFORE returning'},\n` +
      `then return the same object. English only, timecodes M:SS, no internal jargon (frame ids, file names).`,
    noVerdict: 'verdict agent returned nothing (skipped or failed) — see journal.jsonl; a rerun reuses the cache',
    verdictLog: (verdict) =>
      `verdict: ${String(verdict.verdict).slice(0, 80)} · mandatory fixes ${n(verdict.mandatory_edits)} · arc beats ${n(verdict.arc_check)} · observations ${n(verdict.observations)} · questions ${n(verdict.open_questions)} · chapters ${n(verdict.structure_proposal)}`,
    tobePrompt: (verdict) =>
      `You are the edit director of the interview documentary ${FILM} (${CODE}). Below: the review verdict on the current cut and the materials.\n` +
      `Task: propose the TARGET structure of the film along the channel story arc (open on the victory frame, cut to the sacrifice beat,\n` +
      `walk the audience through the climb; the last word belongs to the hero), expressed as a list of MOVES of existing cut material.\n\n` +
      `INPUTS:\n${inputsBlock}\n\n${arcBlock}\n\n${exclBlock}\n\nREVIEW VERDICT:\n${JSON.stringify(verdict, null, 1).slice(0, 12000)}\n\n` +
      `RULES:\n${RULES}\n\n` +
      `PROCEDURE: read acts_compact.json; tie every chapter of the target structure to a cut range M:SS–M:SS (check with Grep/Read in the\n` +
      `transcript that the boundary line is there); moves — each move: from_tc, what (first words of the piece), to (after which line /\n` +
      `chapter), why (arc or rule). Inserts from sources only if the verdict or the card names them; otherwise only cut material. Known\n` +
      `gaps stay where they are. time_math — the resulting runtime.\n` +
      `OUTPUT: ${TOBE_OUT ? `write the JSON per the schema to ${TOBE_OUT} (Write) BEFORE returning` : 'write the JSON per the schema to {review_dir}/cloud/out/tobe.json (Write) BEFORE returning'}, then return the same object. English only.`,
    tobeLog: (tobe) => `to-be: chapters ${n(tobe.chapters)} · moves ${n(tobe.moves)}`,
    noTobe: 'to-be agent returned nothing',
  }
})()

const L = A.lang === 'en' ? EN : RU

phase('Verdict')
const verdict = await agent(L.verdictPrompt(),
  { label: `verdict:${L.CODE}`, phase: 'Verdict', schema: L.VERDICT_SCHEMA, effort: 'high' })

if (!verdict) {
  log(L.noVerdict)
  return { verdict: null, tobe: null }
}
log(L.verdictLog(verdict))

let tobe = null
if (A.want_tobe) {
  phase('To-be')
  tobe = await agent(L.tobePrompt(verdict),
    { label: `tobe:${L.CODE}`, phase: 'To-be', schema: L.TOBE_SCHEMA, effort: 'high' })
  if (tobe) log(L.tobeLog(tobe))
  else log(L.noTobe)
}

return { verdict, tobe }
