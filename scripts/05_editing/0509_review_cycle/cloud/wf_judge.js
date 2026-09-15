// wf_judge.js — облачный проход ревью ката (Claude Code Workflow tool). ОДИН скрипт на все фазы.
// Вызов печатает `cloud/pack.py --print-call` (review.py cloud judge --print-call):
//   Workflow({scriptPath: '<abs>/cloud/wf_judge.js', args: {
//     packs: [{batch_id, file}],            // pending J-пакеты (текст, без картинок), могут быть пустыми
//     facts_pack: {batch_id, file} | null,  // F: утверждения на веб-проверку
//     crops_pack: {batch_id, file} | null,  // V: кропы/контактные листы + вопросы
//     skeptic: {batch_id, file | null},     // S: file = пакет от pack.py --skeptic; null = судить результаты этого прогона
//     film, rules, sources: [...], out_dir, existing_tz_file, project, concurrency }})
// Фазы: Judge (агент на пакет, ≤4 одновременно) → Facts ‖ Crops (по агенту, если пакет есть) → Skeptic (1 агент).
// Каждый агент СНАЧАЛА пишет свой JSON в <out_dir>/<batch_id>.json (Write), потом возвращает его по схеме:
// результат переживает падение воркфлоу по лимиту сессии (11.09 так потерялись 51 находка из 79).
// Собирает результаты cloud/collect.py (out/*.json → journal → agent-файлы → task-output); руками сохранять не нужно.
// Args — только пути и короткие строки; пакеты агенты читают сами (Read).
export const meta = {
  name: 'review-judge-v8',
  description: 'Text-only judge of on-screen titles per pack → facts (web) ‖ crops (eyes) → one skeptic (T|V|H|C|F|D)',
  phases: [
    { title: 'Judge', detail: 'агент на пакет J (≤4 сразу): вердикты кандидатам, новые находки, чистые экраны — по тексту, без картинок' },
    { title: 'Facts', detail: 'один агент: веб-проверка утверждений по авторитетным источникам канала' },
    { title: 'Crops', detail: 'один агент: смотрит только приложенные кропы / контактные листы' },
    { title: 'Skeptic', detail: 'один агент: находка настоящая по умолчанию, опровержение только с кодом T|V|H|C|F|D' },
  ],
}

const A = args || {}
const PACKS = Array.isArray(A.packs) ? A.packs : []
const OUT = A.out_dir
const FILM = A.film || ''
const RULES = A.rules || ''
const SOURCES = Array.isArray(A.sources) ? A.sources.join(', ') : (A.sources || '')
const TZ_FILE = A.existing_tz_file || ''
const CONC = Math.max(1, Math.min(4, Number(A.concurrency) || 4))
if (!OUT) throw new Error('args.out_dir обязателен — агенты пишут результаты туда')
// язык промптов и ответов агентов: args.lang = 'en' → английский канал; любое другое значение → русский текст как был
const EN = A.lang === 'en'
// исключения карточки [{t0, t1, reason}] (секунды; null-интервалы игнорируются) — заведомо не ошибки
function tcOf(v) {
  if (typeof v !== 'number' || !isFinite(v)) return String(v)
  const s = Math.max(0, Math.floor(v)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = String(s % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`
}
const EXCLUSIONS = (Array.isArray(A.exclusions) ? A.exclusions : [])
  .filter((x) => x && x.t0 != null && x.t1 != null)
  .map((x) => `${tcOf(x.t0)}–${tcOf(x.t1)}${x.reason ? ` (${x.reason})` : ''}`)
  .join('; ')

const KINDS = ['typo', 'grammar', 'fact', 'currency', 'language', 'mismatch', 'foreign_trace']
const SEV = ['high', 'medium', 'low']

// ── схемы структурированных ответов (контракт docs/contracts.md §7) ──
const J_SCHEMA = {
  type: 'object',
  properties: {
    batch_id: { type: 'string' },
    sha8: { type: 'string' },
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          cand_id: { type: 'string' },
          screen_id: { type: 'string' },
          kind: { type: 'string', enum: KINDS.concat(['other']), description: 'класс ошибки (уточни, если кандидат отнесён неверно)' },
          verdict: { type: 'string', enum: ['confirm', 'refute', 'need_frame', 'fact_check'] },
          reason: { type: 'string', description: 'RU, 1–2 фразы: почему' },
          on_screen_text: { type: 'string', description: 'текст титра как в пакете (для стрелки)' },
          fix_text: { type: 'string', description: 'RU: точный правильный текст титра; пусто, если не применимо' },
          existing_tz: { type: 'string', description: '«ТЗ-NN», если уже покрыто существующим ТЗ, иначе пусто' },
          severity: { type: 'string', enum: SEV },
          confidence: { type: 'number' },
        },
        required: ['cand_id', 'screen_id', 'kind', 'verdict', 'reason', 'on_screen_text', 'fix_text', 'existing_tz', 'severity', 'confidence'],
      },
    },
    new_findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          screen_id: { type: 'string' },
          kind: { type: 'string', enum: KINDS },
          on_screen_text: { type: 'string', description: 'точный текст ошибочного элемента (строка OCR)' },
          line_idx: { type: 'integer', description: 'индекс строки ocr_lines[i]; -1, если не про строку' },
          problem: { type: 'string', description: 'RU: что не так' },
          fix_text: { type: 'string', description: 'RU: как должно быть на экране; пусто, если не применимо' },
          why: { type: 'string', description: 'RU: правило/факт/озвучка, на что опираешься' },
          severity: { type: 'string', enum: SEV },
          existing_tz: { type: 'string' },
        },
        required: ['screen_id', 'kind', 'on_screen_text', 'line_idx', 'problem', 'fix_text', 'why', 'severity', 'existing_tz'],
      },
    },
    need_frames: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          screen_id: { type: 'string' },
          cand_id: { type: 'string', description: 'cand_id кандидата; пусто, если вопрос к новой находке' },
          on_screen_text: { type: 'string' },
          what_to_look_at: { type: 'string', description: 'RU: конкретный вопрос глазам (какая буква / есть ли символ / что за знак)' },
        },
        required: ['screen_id', 'cand_id', 'on_screen_text', 'what_to_look_at'],
      },
    },
    facts_to_check: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          screen_id: { type: 'string' },
          cand_id: { type: 'string', description: 'cand_id, если факт — кандидат; иначе пусто' },
          claim: { type: 'string', description: 'RU: проверяемое утверждение с экрана (число, дата, имя, место)' },
          on_screen_text: { type: 'string' },
        },
        required: ['screen_id', 'cand_id', 'claim', 'on_screen_text'],
      },
    },
    clean_screens: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
  required: ['batch_id', 'sha8', 'verdicts', 'new_findings', 'need_frames', 'facts_to_check', 'clean_screens', 'notes'],
}

const F_SCHEMA = {
  type: 'object',
  properties: {
    batch_id: { type: 'string' },
    sha8: { type: 'string' },
    results: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          fact_id: { type: 'string' },
          screen_id: { type: 'string' },
          cand_id: { type: 'string' },
          claim: { type: 'string' },
          on_screen_text: { type: 'string' },
          status: { type: 'string', enum: ['verified', 'wrong', 'unclear'] },
          correct_value: { type: 'string', description: 'RU: как должно быть на экране, если wrong; иначе пусто' },
          source_url: { type: 'string' },
          note: { type: 'string', description: 'RU: одна фраза — что нашёл' },
        },
        required: ['fact_id', 'screen_id', 'cand_id', 'claim', 'on_screen_text', 'status', 'correct_value', 'source_url', 'note'],
      },
    },
  },
  required: ['batch_id', 'sha8', 'results'],
}

const V_SCHEMA = {
  type: 'object',
  properties: {
    batch_id: { type: 'string' },
    sha8: { type: 'string' },
    results: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          q_id: { type: 'string' },
          screen_id: { type: 'string' },
          cand_id: { type: 'string' },
          on_screen_text: { type: 'string', description: 'текст из вопроса (как утверждалось)' },
          text_as_seen: { type: 'string', description: 'что реально написано на кропе, буква в букву' },
          error_visible: { type: 'boolean', description: 'заявленная ошибка видна глазами' },
          answer: { type: 'string', description: 'RU: ответ на what_to_look_at, 1–2 фразы' },
          confidence: { type: 'number' },
        },
        required: ['q_id', 'screen_id', 'cand_id', 'on_screen_text', 'text_as_seen', 'error_visible', 'answer', 'confidence'],
      },
    },
  },
  required: ['batch_id', 'sha8', 'results'],
}

const S_SCHEMA = {
  type: 'object',
  properties: {
    batch_id: { type: 'string' },
    sha8: { type: 'string' },
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          finding_id: { type: 'string' },
          real: { type: 'boolean' },
          code: { type: 'string', enum: ['', 'T', 'V', 'H', 'C', 'F', 'D'], description: 'пусто при real=true; иначе код опровержения' },
          reason: { type: 'string', description: 'RU: 1–2 фразы' },
          corrected_fix_text: { type: 'string', description: 'RU: более точный fix_text, если находка стоит, а правка неточна; иначе пусто' },
        },
        required: ['finding_id', 'real', 'code', 'reason', 'corrected_fix_text'],
      },
    },
  },
  required: ['batch_id', 'sha8', 'verdicts'],
}

// EN: те же схемы (поля, enum, required — байт в байт), меняются только description
function localizeSchema(schema, map) {
  const c = JSON.parse(JSON.stringify(schema))
  for (const [arr, fields] of Object.entries(map)) {
    for (const [f, d] of Object.entries(fields)) {
      const prop = c.properties[arr].items.properties[f]
      if (!prop || prop.description == null) throw new Error(`localizeSchema: нет description у ${arr}.${f}`)
      prop.description = d
    }
  }
  return c
}
const SCH = EN ? {
  J: localizeSchema(J_SCHEMA, {
    verdicts: {
      kind: 'error class (correct it if the candidate was classified wrongly)',
      reason: 'English, 1–2 sentences: why',
      on_screen_text: 'title text as in the pack (for the arrow)',
      fix_text: 'English: the exact correct on-screen text; empty if not applicable',
      existing_tz: '"FIX-NN" if already covered by an existing fix, otherwise empty',
    },
    new_findings: {
      on_screen_text: 'exact text of the wrong element (OCR line)',
      line_idx: 'index of the line ocr_lines[i]; -1 if not about a line',
      problem: 'English: what is wrong',
      fix_text: 'English: how it must read on screen; empty if not applicable',
      why: 'English: the rule / fact / voice-over you rely on',
    },
    need_frames: {
      cand_id: 'cand_id of the candidate; empty if the question is about a new finding',
      what_to_look_at: 'English: a concrete question for the eyes (which letter / is a symbol there / what sign it is)',
    },
    facts_to_check: {
      cand_id: 'cand_id if the fact is a candidate; otherwise empty',
      claim: 'English: the checkable claim from the screen (number, date, name, place)',
    },
  }),
  F: localizeSchema(F_SCHEMA, {
    results: {
      correct_value: 'English: how it must read on screen if wrong; otherwise empty',
      note: 'English: one sentence — what you found',
    },
  }),
  V: localizeSchema(V_SCHEMA, {
    results: {
      on_screen_text: 'text from the question (as claimed)',
      text_as_seen: 'what is actually written on the crop, letter for letter',
      error_visible: 'the claimed error is visible to the eye',
      answer: 'English: answer to what_to_look_at, 1–2 sentences',
    },
  }),
  S: localizeSchema(S_SCHEMA, {
    verdicts: {
      code: 'empty when real=true; otherwise the refutation code',
      reason: 'English: 1–2 sentences',
      corrected_fix_text: 'English: a more exact fix_text if the finding stands but the fix is inexact; otherwise empty',
    },
  }),
} : { J: J_SCHEMA, F: F_SCHEMA, V: V_SCHEMA, S: S_SCHEMA }

// ── общие куски промптов ──
const NOT_ERRORS = `НЕ ошибка (не выноси, даже если очень хочется): вёрстка и композиция, контраст, кернинг, размер и стиль шрифта, наезд титра на лицо, «титр за головой ведущей» (приём этого канала), темп и длительность показа, палитра, капслок без точек в конце, ё/е, единообразие оформления между экранами, «можно было богаче», качество стокового кадра, «правка заказчика ещё не выполнена». Такие вещи в ТЗ не попадают — Роман просил «только ошибки и опечатки по смыслу».`
const CLASSES = `Классы ошибок — только семь: typo (опечатка/орфография/пунктуация внутри слова), grammar (согласование, падеж, пропущенное слово), fact (число/дата/имя/место расходится с проверяемым фактом), currency (формат валюты/числа против правил канала, разнобой по фильму), language (английский без русского или английский ПЕРВЫМ/крупнее русского; латинские сокращения из белого списка канала — не ошибка), mismatch (титр противоречит озвучке или показывает не то, о чём речь), foreign_trace (чужой след в кадре: подпись стока, водяной знак, чужой логотип, курсор, служебные маркеры).`
const PERSIST = (bid) => `ПОРЯДОК ВЫДАЧИ (обязательно, в этой последовательности): 1) собери итоговый JSON; 2) запиши его инструментом Write в файл ${OUT}/${bid}.json — ровно этот путь, ничего другого не создавай; 3) только после записи верни тот же JSON структурированным ответом. Файл — страховка от обрыва по лимиту сессии: без него результат пропадает.`
const TZ_NOTE = TZ_FILE ? `Существующие ТЗ (строки «ТЗ-NN · tc · заголовок») — файл ${TZ_FILE}, прочитай Read'ом. Находку, которая целиком под одним из них, всё равно верни, но заполни existing_tz «ТЗ-NN» — по ней рисуется стрелка на кадре, а нового номера она не получит.` : ''
// пусто без исключений карточки → RU-промпты байт в байт прежние
const EXCL_NOTE = EXCLUSIONS ? `\nИсключения карточки (заведомо не ошибки): ${EXCLUSIONS}. По экранам внутри этих интервалов ничего не выноси — они в clean_screens; находку внутри интервала скептик снимает кодом T (в reason — «исключение карточки»).` : ''

function judgePrompt(p) {
  return `Ты — корректор и факт-редактор фильма: ${FILM}. Пакет ${p.batch_id}.
Прочитай пакет инструментом Read: ${p.file}. Картинок нет и не нужно: на каждый экран у тебя три чтения текста (ocr_lines построчно, ocr_last — последний кадр допечатки, vlm_text), описание кадра (vlm_desc), озвучка вокруг экрана ±8 с (vo), локальные признаки (local_flags: подозрения на опечатки, доля латиницы, числа на экране и в озвучке, чужой след, дубль экрана) и кандидаты локальных моделей (candidates[] — могут быть пустыми: тогда ищи сам).
Твоя работа по КАЖДОМУ экрану пакета:
1) verdicts — вердикт каждому кандидату: confirm (ошибка есть и она видна по тексту), refute (не ошибка / допустимый вариант / артефакт OCR), need_frame (три чтения расходятся именно в спорных буквах — Й/И, Щ/Ш, латиница/кириллица, ё, дефис/тире, надстрочные знаки — и решить можно только по кадру: заполни need_frames с конкретным вопросом what_to_look_at), fact_check (число/дата/имя/место надо сверить с источниками: заполни facts_to_check с формулировкой claim). Веб-поиск сам не делай — это работа отдельного агента.
2) new_findings — то, что локальные модели пропустили. Ищи по классам ниже. Опирайся на согласие чтений: если ocr_lines и vlm_text читают одинаково — тексту можно верить; если расходятся — need_frames, а не находка. Обрезанное слово в ocr_lines при полном слове в ocr_last или vlm_text — полукадр анимации допечатки, НЕ ошибка. Экран с dup_of — дубль другого экрана: суди один раз (на первом), второй занеси в clean_screens.
3) clean_screens — id всех экранов пакета, по которым нет ни вердикта, ни новой находки. Покрытие обязано быть полным: каждый экран пакета должен оказаться в verdicts, new_findings или clean_screens — код это проверяет и досылает непокрытые экраны отдельным пакетом.
${CLASSES}
${NOT_ERRORS}
Правила канала: ${RULES}
Источники факт-чека (для fact_check): ${SOURCES}.
${TZ_NOTE}${EXCL_NOTE}
fix_text — ТОЧНЫЙ текст титра, как должно быть на экране (для валюты — по формату канала); не инструкция. reason/problem/why — по-русски, коротко, с опорой на конкретное чтение или слово озвучки.
Калибровка: у этого канала из сырых подозрений настоящими оказываются примерно каждое пятое; целевого размера списка нет — фильтруй по классу ошибки, не по количеству. Не выдумывай: лучше clean_screens, чем ложная находка; но пропущенная опечатка в титре дороже лишней проверки.
${PERSIST(p.batch_id)} batch_id и sha8 возьми из пакета.`
}

function factsPrompt(p) {
  return `Ты — факт-чекер фильма: ${FILM}. Пакет ${p.batch_id}.
Прочитай Read'ом пакет ${p.file}: items[] — утверждения с экранов (fact_id, screen_id, cand_id, claim, on_screen_text). Для КАЖДОГО утверждения сделай веб-проверку инструментом WebSearch (если инструмент не виден — подгрузи через ToolSearch "select:WebSearch"): сначала авторитетные источники канала — ${SOURCES}; Wikipedia/Britannica — как вторичные; ссылки только реальные, найденные поиском (не выдумывай URL).
Статусы: verified — экран верен (в пределах разумного округления); wrong — экран ошибается: дай correct_value ТОЧНО так, как должно быть на экране (формат валюты/числа по правилам канала), и source_url; unclear — источники расходятся или не нашёл (кратко почему в note).
Правила канала: ${RULES}
В results верни по одной записи на каждый fact_id пакета, эхо полей screen_id/cand_id/claim/on_screen_text — как в пакете.
${PERSIST(p.batch_id)} batch_id и sha8 возьми из пакета.`
}

function cropsPrompt(p) {
  return `Ты — «глаза» аудита фильма: ${FILM}. Пакет ${p.batch_id}.
Прочитай Read'ом пакет ${p.file}: images[] — картинки (кропы ≤800 px или контактные листы 4×4, где каждая ячейка подписана q_id), items[] — вопросы (q_id, screen_id, cand_id, on_screen_text — что утверждается, what_to_look_at — на что смотреть, image и cell — где искать).
Открывай Read'ом ТОЛЬКО картинки из images[] — других файлов не трогай. Для КАЖДОГО вопроса: text_as_seen — что реально написано (буква в букву, регистр и знаки сохрани; если несколько строк — через « | »), error_visible — видна ли заявленная ошибка глазами, answer — ответ на what_to_look_at в 1–2 фразах, confidence 0..1. Не додумывай: если ячейка нечитаема или обрезана — error_visible=false, низкая confidence, answer «нечитаемо». Помни: OCR путает Й/И, Щ/Ш, латиницу и кириллицу — ты видишь глифы, а он нет.
В results — по одной записи на каждый q_id пакета, поля screen_id/cand_id/on_screen_text — эхо из пакета.
${PERSIST(p.batch_id)} batch_id и sha8 возьми из пакета.`
}

function skepticPrompt(S, digest) {
  const inline = digest.length ? `\nНАХОДКИ ЭТОГО ПРОГОНА (${digest.length}):\n${JSON.stringify(digest, null, 0)}` : ''
  const packLine = S.file ? `Пакет находок для скепсиса — файл ${S.file} (прочитай Read'ом, поле items[]: finding_id, screen_id, tc, kind, on_screen_text, fix_text, problem, why, existing_tz, route, evidence, vo).` : ''
  return `Ты — скептик-«редактор выпуска» фильма: ${FILM}. Пакет ${S.batch_id}.
${packLine}${inline}
По умолчанию каждая находка НАСТОЯЩАЯ (real=true): её уже подтвердил судья по трём чтениям текста (или веб-факт, или глаза по кропу — см. evidence). Ты не ищешь поводов снять — ты ловишь четыре конкретных промаха. Опровергай (real=false) ТОЛЬКО с кодом и причиной:
T — это вкус, вёрстка, темп, палитра, оформление: не класс ошибки (${NOT_ERRORS.replace('НЕ ошибка (не выноси, даже если очень хочется): ', '')});
V — экранная форма допустима: вариант написания по нормам русского языка, допустимое сокращение, формат, разрешённый правилами канала (капслок без точек, латинское сокращение из белого списка, ё/е);
H — текст титра не прочитать по тексту: буквы за головой ведущей / полукадр анимации / обрезка — находку не снимаем, она превращается в «проверить исходник титра» (real=false, code H);
C — уже полностью покрыто существующим ТЗ-NN (укажи номер в reason) так, что отдельная стрелка не нужна; если existing_tz уже заполнен — НЕ опровергай: стрелка всё равно нужна;
F — «факт» защитим: источник в reason (только если уверен; спор источников — не повод снимать);
D — дубль другой находки в этом же списке (укажи её finding_id; сними именно дубль, а не обе).
Если ошибка реальна, но fix_text неточен — real=true и corrected_fix_text (точный текст титра, как должно быть на экране). Сомнение трактуй в пользу находки: пропущенная опечатка в титре дороже лишней стрелки — это правило Романа, а не пожелание.
${TZ_NOTE}${EXCL_NOTE}
Правила канала: ${RULES}
В verdicts — по одной записи на КАЖДЫЙ finding_id (из файла и из списка выше); real=true → code пусто.
${PERSIST(S.batch_id)} batch_id = «${S.batch_id}», sha8 = «${S.batch_id.slice(2)}».`
}

// ── EN: те же промпты для англоязычного канала (YTCR) — структура, порядок и контракт выдачи прежние ──
const EN_NOT_ERRORS_BODY = `layout and composition, contrast, kerning, font choice, size and style, a title overlapping a face or placed behind the speaker's head, pacing and on-screen duration, colour palette, ALL CAPS titles without a final period, design consistency between screens, "could be richer", stock footage quality, "a client change is not done yet", currency or number FORMAT variants of the same value (AED 2M vs 2M AED vs AED 2,000,000; 1.5M vs 1,500,000), British vs American spelling used consistently, Arabic (or any other script) on real-world signage, documents, phones or products inside filmed or archive footage, anything inside the card exclusions. None of this goes into the fix list — Roman asked for "only real errors and typos that change meaning".`
const EN_NOT_ERRORS = `NOT an error (do not report, however tempting): ${EN_NOT_ERRORS_BODY}`
const EN_CLASSES = `Error classes — only seven: typo (misspelling, wrong/missing/doubled letter, punctuation inside a word, broken apostrophe — "Dubia", "its" for "it's"), grammar (English grammar: agreement, tense, missing or wrong article or preposition, missing word, wrong capitalisation in a title — a proper noun in lower case, or one word breaking the title's own case style), fact (a number/date/name/place/company contradicts a verifiable fact), currency (a wrong number, amount, unit or currency on screen versus the voice-over or the facts — e.g. the voice says "two million dirhams" and the screen shows "AED 20M" or "$2M"; format variants of the same value are NOT errors), language (non-English script or untranslated foreign text in the channel's own graphics — titles, lower thirds, captions, chapter cards; names and terms from the channel whitelist are not errors), mismatch (the screen contradicts the voice-over or shows something other than what is being said), foreign_trace (someone else's trace in the frame: watermark, stock agency caption, another channel's or outlet's logo, YouTube/Instagram/TikTok interface, burned-in captions from a re-used clip, mouse cursor, editor's service markers; the channel's own logo is not a trace).`
const EN_PERSIST = (bid) => `OUTPUT ORDER (mandatory, in this sequence): 1) build the final JSON; 2) write it with the Write tool to the file ${OUT}/${bid}.json — exactly this path, create nothing else; 3) only after writing, return the same JSON as the structured answer. The file insures against a session-limit cutoff: without it the result is lost.`
const EN_TZ_NOTE = TZ_FILE ? `Existing fixes (lines "FIX-NN · tc · title") — file ${TZ_FILE}, read it with Read. A finding fully covered by one of them must still be returned, but fill existing_tz with that "FIX-NN" exactly as written in the file — it draws the arrow on the frame and gets no new number.` : ''
const EN_EXCL_NOTE = EXCLUSIONS ? `\nCard exclusions (known non-errors): ${EXCLUSIONS}. Report nothing on screens inside these ranges — put them into clean_screens; the skeptic refutes a finding inside a range with code T (reason: "card exclusion").` : ''

function judgePromptEn(p) {
  return `You are the proofreader and fact editor of the film: ${FILM}. Pack ${p.batch_id}.
Read the pack with the Read tool: ${p.file}. There are no images and none are needed: for each screen you have three readings of the text (ocr_lines line by line, ocr_last — the last frame of the type-on animation, vlm_text), a frame description (vlm_desc), the voice-over around the screen ±8 s (vo), local signals (local_flags: suspected typos, script mix, numbers on screen and in the voice-over, foreign trace, duplicate screen) and local-model candidates (candidates[] — may be empty: then search yourself).
Your job for EACH screen of the pack:
1) verdicts — a verdict for every candidate: confirm (the error is there and visible from the text), refute (not an error / acceptable variant / OCR artefact), need_frame (the three readings disagree exactly on the disputed characters — l/I/1, O/0, rn/m, cl/d, 5/S, apostrophe vs quote mark, hyphen vs dash, accents — and only the frame can decide: fill need_frames with a concrete what_to_look_at question), fact_check (a number/date/name/place must be checked against sources: fill facts_to_check with a claim). Do not web-search yourself — that is a separate agent's job.
2) new_findings — what the local models missed. Search by the classes below. Rely on agreement between readings: if ocr_lines and vlm_text read the same — trust the text; if they disagree — need_frames, not a finding. A word cut off in ocr_lines while ocr_last or vlm_text has it whole is a half-frame of the type-on animation, NOT an error. A screen with dup_of duplicates another screen: judge it once (on the first) and put the second into clean_screens.
3) clean_screens — ids of all screens of the pack with neither a verdict nor a new finding. Coverage must be complete: every screen of the pack must end up in verdicts, new_findings or clean_screens — the code checks this and re-sends uncovered screens as a separate pack.
${EN_CLASSES}
${EN_NOT_ERRORS}
Channel rules: ${RULES}
Fact-check sources (for fact_check): ${SOURCES}.
${EN_TZ_NOTE}${EN_EXCL_NOTE}
fix_text — the EXACT on-screen text as it must read (for currency — correct the value and keep the format the channel rules give); not an instruction. reason/problem/why — in English, short, grounded in a specific reading or a word of the voice-over. Judge by English norms (the film's own spelling variant, applied consistently).
Calibration: most raw suspicions turn out not to be errors; there is no target list size — filter by error class, not by count. Do not invent: clean_screens is better than a false finding; but a missed typo in a title costs more than an extra check.
${EN_PERSIST(p.batch_id)} Take batch_id and sha8 from the pack.`
}

function factsPromptEn(p) {
  return `You are the fact-checker of the film: ${FILM}. Pack ${p.batch_id}.
Read the pack ${p.file} with Read: items[] — claims from screens (fact_id, screen_id, cand_id, claim, on_screen_text). For EACH claim do a web check with the WebSearch tool (if the tool is not visible, load it via ToolSearch "select:WebSearch"): first the channel's authoritative sources — ${SOURCES}; Wikipedia/Britannica as secondary; only real links found by the search (do not invent URLs).
Statuses: verified — the screen is right (within reasonable rounding); wrong — the screen is wrong: give correct_value EXACTLY as it must read on screen (number/currency format per the channel rules) and source_url; unclear — sources disagree or nothing found (briefly why in note).
Channel rules: ${RULES}
In results return one record per fact_id of the pack, echoing screen_id/cand_id/claim/on_screen_text as in the pack; note in English.
${EN_PERSIST(p.batch_id)} Take batch_id and sha8 from the pack.`
}

function cropsPromptEn(p) {
  return `You are the "eyes" of the audit of the film: ${FILM}. Pack ${p.batch_id}.
Read the pack ${p.file} with Read: images[] — pictures (crops ≤800 px or 4×4 contact sheets where every cell is labelled with its q_id), items[] — questions (q_id, screen_id, cand_id, on_screen_text — what is claimed, what_to_look_at — what to look at, image and cell — where to look).
Open with Read ONLY the images from images[] — touch no other files. For EACH question: text_as_seen — what is actually written (letter for letter, keep case and punctuation; several lines joined with " | "), error_visible — whether the claimed error is visible to the eye, answer — the answer to what_to_look_at in 1–2 sentences in English, confidence 0..1. Do not guess: if the cell is unreadable or cut off — error_visible=false, low confidence, answer "unreadable". Remember: OCR confuses l/I/1, O/0, rn/m, straight and curly quotes, hyphens and dashes — you see the glyphs, it does not.
In results — one record per q_id of the pack, fields screen_id/cand_id/on_screen_text echoed from the pack.
${EN_PERSIST(p.batch_id)} Take batch_id and sha8 from the pack.`
}

function skepticPromptEn(S, digest) {
  const inline = digest.length ? `\nFINDINGS OF THIS RUN (${digest.length}):\n${JSON.stringify(digest, null, 0)}` : ''
  const packLine = S.file ? `Findings pack for the skeptic — file ${S.file} (read it with Read, field items[]: finding_id, screen_id, tc, kind, on_screen_text, fix_text, problem, why, existing_tz, route, evidence, vo).` : ''
  return `You are the skeptic "managing editor" of the film: ${FILM}. Pack ${S.batch_id}.
${packLine}${inline}
By default every finding is REAL (real=true): the judge has already confirmed it from three readings of the text (or a web fact, or eyes on a crop — see evidence). You are not looking for reasons to drop findings — you catch specific misses. Refute (real=false) ONLY with a code and a reason:
T — taste, layout, pacing, palette, design: not an error class (${EN_NOT_ERRORS_BODY});
V — the on-screen form is acceptable: a spelling variant valid in English (British or American, used consistently), an acceptable abbreviation, a format allowed by the channel rules (ALL CAPS without periods, a whitelisted name or term, a currency format variant of the same value such as AED 2M / 2M AED);
H — the title text cannot be read from the text: letters behind the speaker's head / half-frame of the animation / cropped — the finding is not dropped, it becomes "check the title source" (real=false, code H);
C — already fully covered by an existing FIX-NN (give the number in reason) so that a separate arrow is not needed; if existing_tz is already filled — do NOT refute: the arrow is still needed;
F — the "fact" is defensible: source in reason (only if sure; disagreement between sources is not a reason to drop);
D — a duplicate of another finding in this same list (give its finding_id; drop the duplicate, not both).
If the error is real but fix_text is inexact — real=true and corrected_fix_text (the exact on-screen text as it must read). Resolve doubt in favour of the finding: a missed typo in a title costs more than an extra arrow — this is Roman's rule, not a wish. Judge by English norms; reason in English.
${EN_TZ_NOTE}${EN_EXCL_NOTE}
Channel rules: ${RULES}
In verdicts — one record for EACH finding_id (from the file and from the list above); real=true → code empty.
${EN_PERSIST(S.batch_id)} batch_id = "${S.batch_id}", sha8 = "${S.batch_id.slice(2)}".`
}

const PR = EN
  ? { judge: judgePromptEn, facts: factsPromptEn, crops: cropsPromptEn, skeptic: skepticPromptEn }
  : { judge: judgePrompt, facts: factsPrompt, crops: cropsPrompt, skeptic: skepticPrompt }
// evidence в дайджесте скептика (часть его промпта)
const EV = EN
  ? { confirm: 'judge: confirm', neu: 'judge: new finding', fact: (note, url) => `fact: wrong · ${note} · ${url}`, crop: (seen, ans) => `crop: visible · "${seen}" · ${ans}` }
  : { confirm: 'судья: confirm', neu: 'судья: новая находка', fact: (note, url) => `факт: wrong · ${note} · ${url}`, crop: (seen, ans) => `кроп: видно · «${seen}» · ${ans}` }

// ── пул: ≤CONC агентов одновременно, без барьера между элементами ──
async function pool(items, worker) {
  const results = new Array(items.length).fill(null)
  let next = 0
  await parallel(Array.from({ length: Math.min(CONC, items.length) }, () => async () => {
    while (next < items.length) {
      const i = next++
      try { results[i] = await worker(items[i], i) } catch (e) { log(`[${items[i].batch_id}] failed: ${String(e).slice(0, 160)}`); results[i] = null }
    }
  }))
  return results
}

function pad2(n) { return String(n).padStart(2, '0') }
function clip(s, n) { s = String(s == null ? '' : s); return s.length > n ? s.slice(0, n - 1) + '…' : s }

// ── Judge ──
phase('Judge')
log(`J-пакетов: ${PACKS.length}${A.facts_pack ? ' · F' : ''}${A.crops_pack ? ' · V' : ''} · скептик ${A.skeptic ? A.skeptic.batch_id : '—'}`)
const judged = PACKS.length
  ? await pool(PACKS, (p) => agent(PR.judge(p), { label: `judge:${p.batch_id}`, phase: 'Judge', schema: SCH.J }))
  : []
const jres = []
judged.forEach((r, i) => {
  const p = PACKS[i]
  if (!r) { log(`⚠️ ${p.batch_id}: судья не вернулся — батч останется pending`); return }
  if (r.batch_id !== p.batch_id) { log(`${p.batch_id}: агент назвал batch_id «${r.batch_id}» — исправлено`); r.batch_id = p.batch_id }
  log(`${p.batch_id}: вердиктов ${r.verdicts.length} (confirm ${r.verdicts.filter((v) => v.verdict === 'confirm').length}), новых ${r.new_findings.length}, need_frame ${r.need_frames.length}, фактов ${r.facts_to_check.length}, чистых ${r.clean_screens.length}`)
  jres.push({ pack: p, res: r })
})

// ── Facts ‖ Crops ──
let fres = null
let vres = null
const fThunk = A.facts_pack ? () => agent(PR.facts(A.facts_pack), { label: `facts:${A.facts_pack.batch_id}`, phase: 'Facts', schema: SCH.F }) : null
const vThunk = A.crops_pack ? () => agent(PR.crops(A.crops_pack), { label: `crops:${A.crops_pack.batch_id}`, phase: 'Crops', schema: SCH.V }) : null
if (fThunk || vThunk) {
  phase(fThunk ? 'Facts' : 'Crops')
  const rr = await parallel([fThunk, vThunk].filter(Boolean))
  let k = 0
  if (fThunk) { fres = rr[k++]; if (fres) { fres.batch_id = A.facts_pack.batch_id; log(`F: ${fres.results.length} проверок — wrong ${fres.results.filter((x) => x.status === 'wrong').length}, verified ${fres.results.filter((x) => x.status === 'verified').length}`) } else log('⚠️ F: агент фактов не вернулся') }
  if (vThunk) { vres = rr[k++]; if (vres) { vres.batch_id = A.crops_pack.batch_id; log(`V: ${vres.results.length} ответов — ошибка видна в ${vres.results.filter((x) => x.error_visible).length}`) } else log('⚠️ V: агент кропов не вернулся') }
}

// ── Skeptic: находки этого прогона (подтверждённые судьёй / фактом / глазами) + пакет S, если дан ──
const digest = []
for (const { pack, res } of jres) {
  for (const v of res.verdicts) {
    if (v.verdict === 'confirm') digest.push({ finding_id: v.cand_id, screen_id: v.screen_id, kind: v.kind || '', on_screen_text: clip(v.on_screen_text, 160), fix_text: clip(v.fix_text, 160), problem: clip(v.reason, 300), existing_tz: v.existing_tz || '', route: 'cloud', evidence: EV.confirm })
  }
  res.new_findings.forEach((n, i) => digest.push({ finding_id: `${pack.batch_id}.n${pad2(i + 1)}`, screen_id: n.screen_id, kind: n.kind, on_screen_text: clip(n.on_screen_text, 160), fix_text: clip(n.fix_text, 160), problem: clip(n.problem, 300), why: clip(n.why, 200), existing_tz: n.existing_tz || '', route: 'cloud', evidence: EV.neu }))
}
if (fres) {
  for (const r of fres.results) {
    if (r.status === 'wrong') digest.push({ finding_id: r.cand_id || r.fact_id, screen_id: r.screen_id, kind: 'fact', on_screen_text: clip(r.on_screen_text, 160), fix_text: clip(r.correct_value, 160), problem: clip(r.claim, 300), existing_tz: '', route: 'cloud', evidence: EV.fact(clip(r.note, 160), r.source_url) })
  }
}
if (vres) {
  const newByScreen = {}
  for (const { pack, res } of jres) res.new_findings.forEach((n, i) => { (newByScreen[n.screen_id] = newByScreen[n.screen_id] || []).push(`${pack.batch_id}.n${pad2(i + 1)}`) })
  for (const r of vres.results) {
    if (!r.error_visible) continue
    const ids = r.cand_id ? [r.cand_id] : (newByScreen[r.screen_id] || [])
    for (const fid of ids) {
      const known = digest.find((d) => d.finding_id === fid)
      const ev = EV.crop(clip(r.text_as_seen, 120), clip(r.answer, 160))
      if (known) known.evidence += ' | ' + ev
      else digest.push({ finding_id: fid, screen_id: r.screen_id, kind: '', on_screen_text: clip(r.on_screen_text, 160), fix_text: '', problem: clip(r.answer, 300), existing_tz: '', route: 'cloud', evidence: ev })
    }
    if (!ids.length) log(`V: ответ ${r.q_id} без находки (нет cand_id и новых находок на ${r.screen_id}) — collect отметит`)
  }
}

let sres = null
const S = A.skeptic || null
if (!S) log('⚠️ args.skeptic не задан — фаза Skeptic пропущена (pack.py --print-call всегда его задаёт)')
else if (!S.file && !digest.length) log('Skeptic: судить нечего (ни пакета S, ни подтверждённых находок в этом прогоне)')
else {
  phase('Skeptic')
  sres = await agent(PR.skeptic(S, digest), { label: `skeptic:${S.batch_id}`, phase: 'Skeptic', schema: SCH.S })
  if (sres) { sres.batch_id = S.batch_id; log(`S: вердиктов ${sres.verdicts.length}, снято ${sres.verdicts.filter((v) => v.real === false && v.code !== 'H').length}, «проверить исходник» ${sres.verdicts.filter((v) => v.code === 'H').length}`) }
  else log('⚠️ S: скептик не вернулся — pack.py --skeptic соберёт пакет для догона')
}

// ── итог: список готовых батчей + сами результаты (страховка к файлам агентов) ──
const batches_done = []
const batches_failed = []
const results = {}
jres.forEach(({ pack, res }) => { batches_done.push(pack.batch_id); results[pack.batch_id] = res })
PACKS.forEach((p) => { if (!results[p.batch_id]) batches_failed.push(p.batch_id) })
if (A.facts_pack) { if (fres) { batches_done.push(A.facts_pack.batch_id); results[A.facts_pack.batch_id] = fres } else batches_failed.push(A.facts_pack.batch_id) }
if (A.crops_pack) { if (vres) { batches_done.push(A.crops_pack.batch_id); results[A.crops_pack.batch_id] = vres } else batches_failed.push(A.crops_pack.batch_id) }
if (S && (S.file || digest.length)) { if (sres) { batches_done.push(S.batch_id); results[S.batch_id] = sres } else batches_failed.push(S.batch_id) }
const summary = {
  project: A.project || '',
  packs: PACKS.length, judged: jres.length,
  verdicts: jres.reduce((n, x) => n + x.res.verdicts.length, 0),
  confirmed: jres.reduce((n, x) => n + x.res.verdicts.filter((v) => v.verdict === 'confirm').length, 0),
  new_findings: jres.reduce((n, x) => n + x.res.new_findings.length, 0),
  need_frames: jres.reduce((n, x) => n + x.res.need_frames.length, 0),
  facts_to_check: jres.reduce((n, x) => n + x.res.facts_to_check.length, 0),
  facts_wrong: fres ? fres.results.filter((x) => x.status === 'wrong').length : null,
  crops_visible: vres ? vres.results.filter((x) => x.error_visible).length : null,
  skeptic_removed: sres ? sres.verdicts.filter((v) => v.real === false && v.code !== 'H').length : null,
  next: batches_failed.length ? `pending: ${batches_failed.join(', ')} — collect.py, затем pack.py --print-call снова` : 'collect.py --run <runId> → s8_apply_audit.py',
}
log(`готово: батчей ${batches_done.length}, не вернулись ${batches_failed.length}${batches_failed.length ? ' (' + batches_failed.join(', ') + ')' : ''}`)
return { batches_done, batches_failed, summary, results }
