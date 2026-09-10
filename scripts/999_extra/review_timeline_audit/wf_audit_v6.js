// Workflow-скрипт аудита экранов ката (Claude Code Workflow tool). Запуск:
//   Workflow({scriptPath: '.../wf_audit_v6.js', args: {packs:[{pack,file,chapter,n,range}], existing_tz_file, inventory_file, inventory_count}})
// packs — из s6_pack_chapters.py (audit_pack/INDEX.json); existing_tz_file — «ТЗ-NN · tc · название» построчно;
// inventory_file — [{id,tc,chapter,frame,ocr}] всех экранов. Результат → сохранить как audit_findings_v6.json (поле confirmed).
export const meta = {
  name: 'screen-audit-v6',
  description: 'Audit every on-screen title/graphic of a cut (chapter packs) → adversarial 3-lens verify → completeness critic',
  phases: [
    { title: 'Audit', detail: 'one agent per chapter pack: views every frame, checks text/facts/currency/language' },
    { title: 'Verify', detail: '3 independent lenses per finding (visual / factual-linguistic / editorial), majority keeps' },
    { title: 'Critic', detail: 'completeness pass over unflagged screens, extra candidates re-verified' },
  ],
}

const PACKS = args.packs
const EXISTING_TZ = `(полный список — файл ${args.existing_tz_file}, прочитай его Read'ом: строки «ТЗ-NN · tc · название»)`
const RULES = `
ПРАВИЛА КАНАЛА (Роман): валюта — знак ПЕРЕД числом и сокращение «$30,3 МЛН» / «$34,8 МЛН» (НЕ «30 300 000 $»), единый формат по всему фильму; русский титр главный, английский допустим только вторым/меньшим; названия локаций показывать НА КАРТЕ; имена/термины/даты без опечаток; числа должны совпадать с проверяемыми фактами (GIA, Lotus Gemology, SSEF, Sotheby's, Britannica).
Фильм — русскоязычный YouTube-док о рубинах (ведущая Наталья, канал UVI / yuvi.ru).`

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    pack: { type: 'string' },
    screens_reviewed: { type: 'integer' },
    frames_opened: { type: 'integer' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          screen_id: { type: 'string' },
          tc: { type: 'string' },
          t0: { type: 'integer' },
          t1: { type: 'integer' },
          frame: { type: 'string', description: 'absolute path of the hires frame where the error is visible' },
          kind: { type: 'string', enum: ['typo', 'grammar', 'fact', 'currency', 'language', 'mismatch', 'design', 'other'] },
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
          on_screen_text: { type: 'string', description: 'exact text as seen on the frame' },
          problem: { type: 'string', description: 'RU: what is wrong, one-two sentences' },
          fix_text: { type: 'string', description: 'RU: the corrected text exactly as it should appear on screen; empty if not applicable' },
          evidence: { type: 'string', description: 'sources (URLs) or orthographic rule; for facts — the authoritative figure' },
          bbox: {
            type: 'object',
            properties: { x: { type: 'number' }, y: { type: 'number' }, w: { type: 'number' }, h: { type: 'number' } },
            required: ['x', 'y', 'w', 'h'],
            description: 'normalised 0..1, origin top-left, box around the erroneous element on the frame',
          },
          existing_tz: { type: 'string', description: 'ТЗ-NN if this is already covered by an existing ТЗ, else empty' },
          confidence: { type: 'number' },
        },
        required: ['screen_id', 'tc', 't0', 't1', 'frame', 'kind', 'severity', 'on_screen_text', 'problem', 'fix_text', 'evidence', 'bbox', 'existing_tz', 'confidence'],
      },
    },
    clean_screens: { type: 'array', items: { type: 'string' }, description: 'screen ids verified with no issues' },
    notes: { type: 'string' },
  },
  required: ['pack', 'screens_reviewed', 'frames_opened', 'findings', 'clean_screens', 'notes'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    refuted: { type: 'boolean' },
    reason: { type: 'string' },
    corrected_fix_text: { type: 'string', description: 'better fix text if the finding stands but the proposed fix is wrong; else empty' },
    corrected_bbox: {
      type: 'object',
      properties: { x: { type: 'number' }, y: { type: 'number' }, w: { type: 'number' }, h: { type: 'number' } },
      description: 'only if the bbox clearly misses the erroneous element; else omit',
    },
    confidence: { type: 'number' },
  },
  required: ['refuted', 'reason', 'corrected_fix_text', 'confidence'],
}

function auditPrompt(p) {
  return `Ты — корректор, факт-чекер и графический редактор русскоязычного YouTube-фильма о рубинах. Аудит ВСЕХ экранов главы ${p.chapter} «${p.range}» (пакет ${p.pack}, ${p.n} экранов).

Прочитай пакет: ${p.file}
Для КАЖДОГО экрана ОТКРОЙ кадр frame_best инструментом Read (это картинка 1920×1080) и при необходимости frame_last и соседние секунды (hires/h{sec+1:04d}.jpg) — OCR и VLM в пакете лишь подсказка, они путают Й/И, Щ/Ш, латиницу/кириллицу, а анимация «допечатки» даёт обрезанные слова. Считай ошибкой только то, что видишь глазами на кадре.

Проверяй каждый титр/плашку/лоуэр/цифру:
1) ТЕКСТ — опечатки, орфография, грамматика, пунктуация, регистр, дефисы/тире, ё/е непоследовательность внутри одного экрана.
2) ФАКТЫ — каждое число, дата, имя, вес, цена, географическое название: проверь веб-поиском (WebSearch; если инструмент не виден — подгрузи через ToolSearch "select:WebSearch"). Авторитетные источники: GIA, Lotus Gemology, SSEF, Sotheby's/Christie's, Britannica, Wikipedia как вторичный. Укажи источник в evidence.
3) ВАЛЮТА/ЧИСЛА — формат по правилам канала; разнобой форматов между экранами.
4) ЯЗЫК — английские графики/термины/подписи без русского перевода или где английский стоит ПЕРВЫМ/крупнее русского.
5) ЭКРАН ≠ ОЗВУЧКА — титр противоречит тому, что говорится (voiceover_around).
6) ВЁРСТКА — текст обрезан кадром, наезд текста на лицо/объект, нечитаемый контраст (только очевидное).
${RULES}

Уже известные ТЗ (если находка попадает под одно из них — заполни existing_tz, находку всё равно верни, она нужна для стрелки на кадре):
${EXISTING_TZ}

Для каждой находки дай bbox ошибочного элемента в нормированных координатах 0..1 (origin — левый верх кадра). Используй ocr_lines_best_bbox из пакета, если строка совпадает; иначе оцени по кадру (1920×1080 → x/1920, y/1080). Точность важна — по bbox рисуется стрелка на V5.
fix_text — ТОЧНЫЙ правильный текст титра (как должно быть на экране). Для валюты — «$30,3 МЛН» и т.п.
Не выдумывай: если экран чист — добавь его id в clean_screens. Верни JSON строго по схеме. Отчитайся: сколько кадров реально открыл (frames_opened).`
}

const LENSES = {
  visual: (f) => `Ты — скептик-«визуал». Утверждается, что на экране ${f.tc} (${f.frame}) есть ошибка типа ${f.kind}: «${f.on_screen_text}» — ${f.problem}. ОТКРОЙ кадр Read'ом сам (и соседние секунды в той же папке: h{sec+1:04d}.jpg для sec=${f.t0}..${f.t1}, т.е. h${String(f.t0 + 1).padStart(4, '0')}.jpg…h${String(f.t1 + 1).padStart(4, '0')}.jpg). Подтверди или опровергни: (а) текст на кадре действительно читается именно так (не артефакт OCR, не полукадр анимации, не обрезка допечатки); (б) bbox ${JSON.stringify(f.bbox)} действительно накрывает этот элемент (если нет — дай corrected_bbox). Если ошибку глазами НЕ видно — refuted=true. Отвечай по схеме.`,
  factual: (f) => `Ты — скептик-«лингвист/факт-чекер». Утверждается: на экране ${f.tc} текст «${f.on_screen_text}» ошибочен (${f.kind}): ${f.problem}. Предлагаемое исправление: «${f.fix_text}». Доказательства автора: ${f.evidence}. Проверь независимо: для орфографии/грамматики — нормы русского языка (допустимые варианты написания, авторская стилистика, капслок-титры без точек — не ошибка); для фактов — веб-поиск (WebSearch; подгрузи через ToolSearch "select:WebSearch" при необходимости) по авторитетным источникам (GIA, Lotus Gemology, SSEF, Sotheby's, Britannica). Если экранная форма допустима или «факт» защитим — refuted=true. Если ошибка реальна, но fix_text неточен — дай corrected_fix_text. ${RULES}`,
  editorial: (f) => `Ты — скептик-«редактор выпуска». Находка: экран ${f.tc}, тип ${f.kind}, «${f.on_screen_text}» → «${f.fix_text}»; проблема: ${f.problem}. Вопрос: обязан ли монтажёр это править? Опровергни (refuted=true), если это вкусовщина, не влияет на понимание зрителя, уже полностью покрыто существующим ТЗ так, что отдельной стрелки не нужно (список ТЗ ниже; заметь: если existing_tz указан, стрелка на кадре всё равно полезна — тогда НЕ опровергай), или если правка противоречит правилам канала. Правила: ${RULES}
Существующие ТЗ: ${EXISTING_TZ}`,
}

function key(f) { return f.screen_id + '|' + f.kind + '|' + (f.on_screen_text || '').slice(0, 40) }

async function verify(f, phase) {
  const votes = await parallel(Object.keys(LENSES).map((lens) => () =>
    agent(LENSES[lens](f), { label: `verify:${lens}:${f.tc}`, phase, schema: VERDICT_SCHEMA }).then((v) => ({ lens, v }))))
  const vs = votes.filter(Boolean).filter((x) => x.v)
  const keep = vs.filter((x) => !x.v.refuted).length >= 2
  const fixes = vs.map((x) => x.v.corrected_fix_text).filter((s) => s && s.trim())
  const bb = vs.map((x) => x.v.corrected_bbox).filter((b) => b && typeof b.x === 'number')
  return { ...f, confirmed: keep, votes: vs.map((x) => ({ lens: x.lens, refuted: x.v.refuted, reason: x.v.reason })),
    fix_text_final: fixes.length ? fixes[0] : f.fix_text, bbox_final: bb.length ? bb[0] : f.bbox }
}

log(`packs: ${PACKS.length}`)
const perPack = await pipeline(
  PACKS,
  (p) => agent(auditPrompt(p), { label: `audit:${p.pack}`, phase: 'Audit', schema: FINDINGS_SCHEMA }),
  async (res, p) => {
    if (!res) return null
    log(`${p.pack}: ${res.findings.length} findings, ${res.clean_screens.length} clean, frames opened ${res.frames_opened}/${p.n}`)
    const verified = await parallel(res.findings.map((f) => () => verify(f, 'Verify')))
    return { pack: p.pack, screens_reviewed: res.screens_reviewed, frames_opened: res.frames_opened,
      clean_screens: res.clean_screens, notes: res.notes, findings: verified.filter(Boolean) }
  },
)

const packs = perPack.filter(Boolean)
const all = packs.flatMap((p) => p.findings)
const confirmed = all.filter((f) => f.confirmed)
log(`audit done: ${all.length} raw → ${confirmed.length} confirmed`)

// ── Critic: completeness over the whole inventory (reads the inventory file itself) ──
const flaggedIds = Array.from(new Set(all.map((f) => f.screen_id)))
const cleanIds = Array.from(new Set(packs.flatMap((p) => p.clean_screens)))
log(`critic: flagged ${flaggedIds.length}, clean ${cleanIds.length} of ${args.inventory_count} screens`)
const critic = await agent(`Ты — критик полноты аудита экранов фильма о рубинах. Полный инвентарь экранов (${args.inventory_count} шт: id, tc, кадр, OCR) — в файле ${args.inventory_file} (прочитай Read'ом). Аудиторы отметили как ОШИБКА экраны: ${flaggedIds.join(', ')}; как ЧИСТЫЕ: ${cleanIds.join(', ')}. Все остальные экраны инвентаря никто не отметил — ПРОВЕРЬ ИХ САМ: открой каждый такой кадр Read'ом и примени 6 проверок (текст/факты/валюта/язык/экран≠озвучка/вёрстка). Дополнительно пробегись по всему инвентарю по экранам с ЧИСЛАМИ, ДАТАМИ, ИМЕНАМИ и АНГЛИЙСКИМ текстом — не пропущено ли что-то очевидное (единый формат валют по всему фильму!). Верни ТОЛЬКО новые находки (не дублируй подтверждённые ниже); экраны, которые проверил и они чисты, — в clean_screens. ${RULES}
Существующие ТЗ: ${EXISTING_TZ}

ПОДТВЕРЖДЁННЫЕ НАХОДКИ (${confirmed.length}):
${confirmed.map((f) => `- ${f.screen_id} ${f.tc} [${f.kind}] «${f.on_screen_text}» → «${f.fix_text_final}»`).join('\n')}`,
  { label: 'critic:completeness', phase: 'Critic', schema: FINDINGS_SCHEMA })

let extra = []
if (critic && critic.findings.length) {
  log(`critic proposed ${critic.findings.length} extra findings — verifying`)
  const seen = new Set(all.map(key))
  const fresh = critic.findings.filter((f) => !seen.has(key(f)))
  extra = (await parallel(fresh.map((f) => () => verify(f, 'Critic').then((v) => ({ ...v, from_critic: true }))))).filter(Boolean)
}
const extraConfirmed = extra.filter((f) => f.confirmed)
log(`final: ${confirmed.length + extraConfirmed.length} confirmed (${extraConfirmed.length} from critic), ${all.length - confirmed.length + extra.length - extraConfirmed.length} refuted`)
return { packs, critic_notes: critic ? critic.notes : '', critic_clean: critic ? critic.clean_screens : [],
  findings: all.concat(extra), confirmed: confirmed.concat(extraConfirmed) }
