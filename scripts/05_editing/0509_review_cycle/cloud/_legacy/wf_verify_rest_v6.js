// Догоняющая проверка находок аудита (Claude Code Workflow tool). Запуск:
//   Workflow({scriptPath: '.../wf_verify_rest_v6.js', args: {items:[…verify_pack/INDEX.json…],
//             state_file, inventory_file, inventory_count, existing_tz_file, film, sources}})
// items — verify_pack/INDEX.json от s6b_pack_verify.py: одна находка = один файл, агент читает только свой.
// Зачем отдельный скрипт: 11.09 verify-фаза wf_audit_v6.js упала по лимиту сессии на 51 находке из 79,
// и «ноль голосов» выглядел как «опровергнуто». Этот прогон добирает голоса и делает пропущенного критика.
// Результат → merge_verify_v6.py (сохранить СРАЗУ: у воркфлоу нет доступа к файловой системе).
export const meta = {
  name: 'verify-rest-v6',
  description: 'Catch up the adversarial 3-lens verify for findings left without votes + the missed completeness critic',
  phases: [
    { title: 'Verify', detail: '3 independent lenses per finding (visual / factual-linguistic / editorial), majority keeps' },
    { title: 'Critic', detail: 'completeness pass over screens nobody flagged, its candidates verified by the same lenses' },
  ],
}

// items можно передавать компактно (без путей), тогда args.pack_dir + id дают файл пакета
const ITEMS = args.items.map((it) => ({ ...it, file: it.file || `${args.pack_dir}/${it.id}.json` }))
const FILM = args.film || 'русскоязычный YouTube-док о рубинах (канал UVI / yuvi.ru)'
const SOURCES = args.sources || "GIA, Lotus Gemology, SSEF, Sotheby's, Britannica"
const EXISTING_TZ = `(полный список — файл ${args.existing_tz_file}, прочитай его Read'ом: строки «ТЗ-NN · tc · название»)`
const RULES = `
ПРАВИЛА КАНАЛА (Роман): валюта — знак ПЕРЕД числом и сокращение «$30,3 МЛН» / «$34,8 МЛН» (НЕ «30 300 000 $»), единый формат по всему фильму; русский титр главный, английский допустим только вторым/меньшим; названия локаций показывать НА КАРТЕ; имена/термины/даты без опечаток; числа должны совпадать с проверяемыми фактами (${SOURCES}).
Фильм — ${FILM}.`

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

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
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
          on_screen_text: { type: 'string' },
          problem: { type: 'string', description: 'RU: what is wrong, one-two sentences' },
          fix_text: { type: 'string', description: 'RU: the corrected text exactly as it should appear on screen' },
          evidence: { type: 'string' },
          bbox: {
            type: 'object',
            properties: { x: { type: 'number' }, y: { type: 'number' }, w: { type: 'number' }, h: { type: 'number' } },
            required: ['x', 'y', 'w', 'h'],
          },
          existing_tz: { type: 'string' },
          confidence: { type: 'number' },
        },
        required: ['screen_id', 'tc', 't0', 't1', 'frame', 'kind', 'severity', 'on_screen_text', 'problem', 'fix_text', 'evidence', 'bbox', 'existing_tz', 'confidence'],
      },
    },
    clean_screens: { type: 'array', items: { type: 'string' }, description: 'screen ids verified with no issues' },
    notes: { type: 'string' },
  },
  required: ['findings', 'clean_screens', 'notes'],
}

// ── линзы: каждая читает свой пакет находки сама (it.file), кадры открывает Read'ом ──
const PACKED = {
  visual: (it) => `Ты — скептик-«визуал». Прочитай Read'ом пакет находки: ${it.file} — там поле finding (что утверждается) и screen (кадры, OCR с bbox, VLM, озвучка).
ОТКРОЙ кадры сам: screen.frame_best, screen.frame_last и все screen.frames_all (это картинки 1920×1080, сек=кадр−1). При сомнении сделай кроп-зум нужной области (ImageMagick: magick <кадр> -crop …) — OCR и VLM путают Й/И, Щ/Ш, латиницу/кириллицу, а анимация «допечатки» даёт обрезанные слова.
Подтверди или опровергни: (а) текст на кадре действительно читается именно так, как в finding.on_screen_text, и ошибка видна глазами; (б) finding.bbox действительно накрывает ошибочный элемент — если нет, дай corrected_bbox (нормированные 0..1, origin левый верх).
Если ошибку глазами НЕ видно, или это полукадр анимации / артефакт OCR — refuted=true. Отвечай строго по схеме.`,
  factual: (it) => `Ты — скептик-«лингвист/факт-чекер». Прочитай Read'ом пакет находки: ${it.file} (поля finding и screen, в screen.voiceover_around — озвучка вокруг экрана).
Проверь НЕЗАВИСИМО от автора находки: для орфографии/грамматики — нормы русского языка (допустимые варианты написания, авторская стилистика, капслок-титры без точек — не ошибка); для фактов, чисел, дат, имён, географических названий — веб-поиском (WebSearch; если инструмента не видно — подгрузи через ToolSearch "select:WebSearch") по авторитетным источникам (${SOURCES}).
Если экранная форма допустима или «факт» защитим — refuted=true. Если ошибка реальна, но finding.fix_text неточен — дай corrected_fix_text (точный текст титра, как должно быть на экране). Источник укажи в reason. ${RULES}`,
  editorial: (it) => `Ты — скептик-«редактор выпуска». Прочитай Read'ом пакет находки: ${it.file}.
Вопрос: обязан ли монтажёр это править? Опровергни (refuted=true), если это вкусовщина, не влияет на понимание зрителя, или правка противоречит правилам канала. Если finding.existing_tz заполнен — находку НЕ опровергай: стрелка на кадре всё равно нужна.
Правила: ${RULES}
Существующие ТЗ: ${EXISTING_TZ}`,
}

// Критик возвращает находки без пакета — его кандидатов проверяем по тексту находки.
const INLINE = {
  visual: (f) => `Ты — скептик-«визуал». Утверждается, что на экране ${f.tc} (${f.frame}) есть ошибка типа ${f.kind}: «${f.on_screen_text}» — ${f.problem}. ОТКРОЙ кадр Read'ом сам и соседние секунды (h{sec+1:04d}.jpg для sec=${f.t0}..${f.t1}); при сомнении — кроп-зум. Подтверди или опровергни: (а) текст читается именно так и ошибка видна глазами; (б) bbox ${JSON.stringify(f.bbox)} накрывает элемент (иначе corrected_bbox). Не видно глазами — refuted=true.`,
  factual: (f) => `Ты — скептик-«лингвист/факт-чекер». Утверждается: на экране ${f.tc} текст «${f.on_screen_text}» ошибочен (${f.kind}): ${f.problem}. Предлагаемое исправление: «${f.fix_text}». Доказательства автора: ${f.evidence}. Проверь независимо (нормы русского языка; факты — WebSearch по ${SOURCES}). Допустимо или защитимо — refuted=true; неточный fix — corrected_fix_text. ${RULES}`,
  editorial: (f) => `Ты — скептик-«редактор выпуска». Находка: экран ${f.tc}, тип ${f.kind}, «${f.on_screen_text}» → «${f.fix_text}»; проблема: ${f.problem}. Обязан ли монтажёр это править? Вкусовщина или противоречие правилам канала — refuted=true. Правила: ${RULES}
Существующие ТЗ: ${EXISTING_TZ}`,
}

function tally(f, votes) {
  const vs = votes.filter(Boolean).filter((x) => x.v)
  const enough = vs.length >= 2          // меньше двух голосов — большинство не набирается в принципе
  const keep = enough && vs.filter((x) => !x.v.refuted).length >= 2
  const fixes = vs.map((x) => x.v.corrected_fix_text).filter((s) => s && s.trim())
  const bb = vs.map((x) => x.v.corrected_bbox).filter((b) => b && typeof b.x === 'number')
  return {
    confirmed: keep, status: enough ? 'verified' : 'unverified',
    votes: vs.map((x) => ({ lens: x.lens, refuted: x.v.refuted, reason: x.v.reason })),
    fix_text_final: fixes.length ? fixes[0] : f.fix_text, bbox_final: bb.length ? bb[0] : f.bbox,
  }
}

// ── Verify: по находке — три линзы; pipeline, чтобы следующая не ждала барьера ──
log(`findings to catch up: ${ITEMS.length}`)
const verdicts = (await pipeline(
  ITEMS,
  async (it) => {
    const votes = await parallel(Object.keys(PACKED).map((lens) => () =>
      agent(PACKED[lens](it), { label: `verify:${lens}:${it.tc}`, phase: 'Verify', schema: VERDICT_SCHEMA })
        .then((v) => ({ lens, v }))))
    const t = tally(it, votes)
    return { id: it.id, screen_id: it.screen_id, tc: it.tc, kind: it.kind, severity: it.severity, ...t }
  },
)).filter(Boolean)

const done = verdicts.filter((v) => v.status === 'verified')
log(`verify: ${done.filter((v) => v.confirmed).length} confirmed, ${done.filter((v) => !v.confirmed).length} refuted` +
  (verdicts.length - done.length ? ` · ⚠️ ${verdicts.length - done.length} снова без голосов` : ''))

// ── Critic: полнота по экранам, которых никто не отметил (читает инвентарь и состояние файлами) ──
const critic = await agent(`Ты — критик полноты аудита экранов фильма: ${FILM}.
Полный инвентарь экранов (${args.inventory_count} шт: id, tc, chapter, frame, ocr) — файл ${args.inventory_file} (прочитай Read'ом).
Что уже отметили аудиторы — файл ${args.state_file}: flagged (экраны с находками), clean (проверены и чисты), confirmed_brief (подтверждённые находки), unverified_brief (находки на перепроверке в этом же прогоне).
Твоя работа: экраны, которых НЕТ ни в flagged, ни в clean — проверь сам: открой каждый кадр Read'ом и примени 6 проверок (текст / факты / валюта / язык / экран ≠ озвучка / вёрстка). Затем отдельно пробегись по ВСЕМУ инвентарю по экранам с ЧИСЛАМИ, ДАТАМИ, ИМЕНАМИ, ГЕОГРАФИЕЙ и АНГЛИЙСКИМ текстом — не пропущено ли очевидное (единый формат валюты по всему фильму!), и по экранам из clean, где OCR показывает цифры или латиницу.
Верни ТОЛЬКО НОВЫЕ находки — не дублируй confirmed_brief и unverified_brief. Экраны, которые проверил и они чисты, — в clean_screens. Для каждой находки дай bbox ошибочного элемента (0..1, origin левый верх) и источник в evidence. Не выдумывай: лучше меньше находок, чем ложные.
${RULES}
Существующие ТЗ: ${EXISTING_TZ}`,
  { label: 'critic:completeness', phase: 'Critic', schema: FINDINGS_SCHEMA })

let extra = []
if (critic && critic.findings && critic.findings.length) {
  log(`critic proposed ${critic.findings.length} extra findings — verifying`)
  extra = (await pipeline(
    critic.findings,
    async (f) => {
      const votes = await parallel(Object.keys(INLINE).map((lens) => () =>
        agent(INLINE[lens](f), { label: `critic-verify:${lens}:${f.tc}`, phase: 'Critic', schema: VERDICT_SCHEMA })
          .then((v) => ({ lens, v }))))
      return { ...f, ...tally(f, votes), from_critic: true }
    },
  )).filter(Boolean)
} else {
  log(critic ? 'critic: новых находок нет' : '⚠️ критик полноты не вернулся — прогнать отдельно')
}

const extraConfirmed = extra.filter((f) => f.confirmed)
log(`final: ${done.filter((v) => v.confirmed).length} confirmed из догоняемых + ${extraConfirmed.length} от критика`)
return {
  verdicts,
  critic_done: !!critic,
  critic_notes: critic ? critic.notes : '',
  critic_clean: critic ? critic.clean_screens : [],
  critic_findings: extra,
  still_unverified: verdicts.filter((v) => v.status !== 'verified').map((v) => ({ id: v.id, screen_id: v.screen_id, tc: v.tc })),
}
