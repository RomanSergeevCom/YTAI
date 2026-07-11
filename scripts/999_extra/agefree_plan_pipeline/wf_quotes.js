export const meta = {
  name: 'ytagefree-exact-quotes',
  description: 'Pick clean full-sentence boundaries per block so we can assemble EXACT complete verbatim quotes for the 03-06 pre-edit pages',
  phases: [{ title: 'Extract' }, { title: 'Verify' }],
}

// args = { dir, counts: {"03":20,"04":31,"05":39,"06":12} }  (may arrive as a JSON string)
const A = (typeof args === 'string') ? JSON.parse(args) : (args || {})
const DIR = A.dir || '/private/tmp/claude-501/-Users-romansergeev-YTAI/ef55ceeb-461d-4280-9fc6-05257ea4e213/scratchpad'
const COUNTS = A.counts || { '03': 20, '04': 31, '05': 39, '06': 12 }
const MAN = []
for (const nn of Object.keys(COUNTS))
  for (let bi = 0; bi < COUNTS[nn]; bi++)
    MAN.push({ key: `${nn}:${bi}`, path: `${DIR}/packets/${nn}_${bi}.json` })

const EXTRACT_SCHEMA = {
  type: 'object',
  properties: {
    keep_first: { type: 'integer', description: 'window index i of FIRST segment of the complete thought (start of sentence)' },
    keep_last:  { type: 'integer', description: 'window index i of LAST segment of the complete thought (ends on terminal punctuation, not mid-word)' },
    inner_cuts: { type: 'array', items: { type: 'object', properties: { a: { type: 'integer' }, b: { type: 'integer' } }, required: ['a','b'] },
                  description: 'ranges [a,b] of window indices INSIDE keep_first..keep_last to DROP (director talk «стоп/ещё раз/точку не поставила», retakes, off-topic). Empty if none.' },
    speaker: { type: 'string', description: 'human-readable speaker of the substantive content, e.g. «Мария Литвенова · психолог фонда», «Юрий Баев · эксперт», «Елизавета Олескина · директор фонда»' },
    note: { type: 'string', description: 'short flag if boundaries uncertain or block belongs elsewhere; else empty' },
  },
  required: ['keep_first','keep_last','speaker'],
}
const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' },
    final_first: { type: 'integer' },
    final_last: { type: 'integer' },
    inner_cuts: { type: 'array', items: { type: 'object', properties: { a: { type: 'integer' }, b: { type: 'integer' } }, required: ['a','b'] } },
    issue: { type: 'string', description: 'what was wrong (mid-sentence cut, included director talk, off-topic tail) or empty' },
  },
  required: ['ok','final_first','final_last'],
}

const res = await pipeline(
  MAN,
  (m) => agent(
`Ты — ассистент режиссёра монтажа образовательного видео фонда «Старость в радость» (аудитория 50+).
Задача: определить ГРАНИЦЫ одного смыслового блока в сыром транскрипте, чтобы вытащить ПОЛНУЮ дословную
реплику — законченную мысль, БЕЗ обрезки на полуслове, убрав только закадровые реплики режиссёра,
дубли-пересъёмы и явный мусор.

Прочитай пакет блока целиком:
  cat "${m.path}"
Поля: heading (раздел), why (замысел), source_file (клип), cur_quote (черновой приблизительный фрагмент —
может быть обрезан/перефразирован), window[] — пронумерованные сегменты {i,s,e,spk,text,in_span}.
Блок находится примерно там, где in_span=true.

Верни индексы i из window:
- keep_first / keep_last — первый и последний сегменты ПОЛНОЙ законченной мысли блока. Расширь до начала
  фразы и до конца предложения (терминальная пунктуация). НЕ обрывай на полуслове. НЕ прихватывай соседнюю
  ДРУГУЮ тему.
- inner_cuts — диапазоны [a,b] ВНУТРИ keep_first..keep_last на выброс: реплики режиссёра («стоп», «ещё раз»,
  «точку не поставила», «давай сначала»), пересъёмы одной фразы, посторонний разговор. Пусто если нет.
- speaker — кто по существу говорит.
Работай ТОЛЬКО индексами, ничего не выдумывай.`,
    { label: `ex:${m.key}`, phase: 'Extract', agentType: 'general-purpose', schema: EXTRACT_SCHEMA }
  ).then(r => ({ m, ex: r })).catch(() => ({ m, ex: null })),

  (prev) => {
    if (!prev || !prev.ex) return { key: prev?.m?.key, ex: null, vf: null }
    const { m, ex } = prev
    return agent(
`Ты — придирчивый контролёр монтажа. Проверь ГРАНИЦЫ блока по сырому транскрипту.
Открой пакет: cat "${m.path}"  (поле window[] — сегменты i/s/e/spk/text; heading/why — что за блок).

Предложенные границы: keep_first=${ex.keep_first}, keep_last=${ex.keep_last},
inner_cuts=${JSON.stringify(ex.inner_cuts || [])}.

Собери мысленно текст сегментов [keep_first..keep_last] минус inner_cuts и проверь:
1) Начало — с НАЧАЛА фразы (не с середины)? Если нет — сдвинь final_first раньше.
2) Конец — ЗАКОНЧЕННАЯ мысль (терминальная пунктуация, не обрыв)? Если нет — подвинь final_last.
3) Нет ли на краях/внутри ДРУГОЙ темы или закадровой реплики режиссёра? Если есть — сузь или добавь inner_cuts.
4) Мысль полна (не выкинут кусок в середине)?
Верни: ok (true если границы уже верны), final_first, final_last, inner_cuts (итог), issue (что не так, или пусто).
Только индексы, ничего не выдумывай.`,
      { label: `vf:${m.key}`, phase: 'Verify', agentType: 'general-purpose', schema: VERIFY_SCHEMA }
    ).then(vf => ({ key: m.key, ex, vf })).catch(() => ({ key: m.key, ex, vf: null }))
  }
)

const out = res.filter(Boolean).map(r => {
  const first = r.vf ? r.vf.final_first : (r.ex ? r.ex.keep_first : null)
  const last  = r.vf ? r.vf.final_last  : (r.ex ? r.ex.keep_last  : null)
  const cuts  = (r.vf && r.vf.inner_cuts) ? r.vf.inner_cuts : ((r.ex && r.ex.inner_cuts) ? r.ex.inner_cuts : [])
  return { key: r.key, first, last, inner_cuts: cuts, speaker: r.ex ? r.ex.speaker : '',
           note: r.ex ? r.ex.note : '', verify_ok: r.vf ? r.vf.ok : null, issue: r.vf ? r.vf.issue : '' }
})
log(`resolved ${out.length}/${MAN.length} blocks`)
return { blocks: out }
