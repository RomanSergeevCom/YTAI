export const meta = {
  name: 'ytuvi01-listify-polish',
  description: 'YTUVI01 Review v7: переложить 26 ТЗ в формат «один таймкод — одна строка» + скептик-проверка (файлы + кодовый страж)',
  phases: [
    { title: 'Rewrite', detail: '7 батчей по 3–4 ТЗ → parts_replace, самопроверка guard_v7.py' },
    { title: 'Verify', detail: 'скептик на батч: смысл, факты, таймкоды, формат → финальный файл + guard' },
  ],
}
const SP = args.sp
const RULES = `${SP}/listify_rules.md`
const DATA = `${SP}/lint_tz_parts.json`
const GUARD = `${SP}/guard_v7.py`
const BATCHES = args.batches

const R_SCHEMA = {
  type: 'object',
  properties: {
    file: { type: 'string' },
    guard_ok: { type: 'boolean' },
    tz: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
  required: ['file', 'guard_ok', 'tz'],
}
const V_SCHEMA = {
  type: 'object',
  properties: {
    file_final: { type: 'string' },
    guard_ok: { type: 'boolean' },
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          tz: { type: 'string' },
          ok_as_is: { type: 'boolean' },
          problems: { type: 'array', items: { type: 'string' } },
          fixed: { type: 'boolean' },
        },
        required: ['tz', 'ok_as_is', 'problems', 'fixed'],
      },
    },
  },
  required: ['file_final', 'guard_ok', 'verdicts'],
}

const pyList = b => '[' + b.map(x => `'${x}'`).join(',') + ']'

const rewrite = (b, i) => `Ты — редактор ТЗ монтажёру (YouTube-фильм YTUVI01 «Корунд — Рубин»). Задача: переложить тексты ${b.length} ТЗ (${b.join(', ')}) в формат «как карта структуры» — одна строка = одна мысль, в строке не больше одного таймкода.

1. Прочитай правила ЦЕЛИКОМ: ${RULES}
2. Выведи свои ТЗ из ${DATA}:
   python3 -c "import json;d=json.load(open('${DATA}'));print(json.dumps({k:d[k] for k in ${pyList(b)}},ensure_ascii=False,indent=1))"
   Поле parts — источник истины; nado — как это печатается сейчас (с метками блоков); lint — что нарушено; roman_comment/decision — только контекст, в parts НЕ включать.
3. Для КАЖДОГО ТЗ собери новый parts_replace (все непустые блоки из parts: now, do, list, where, src, tl) строго по правилам: ни одной строки с двумя таймкодами; пункт с таймкодом начинается с «M:SS ▸ …»; «почему» — отдельной короткой строкой; длинные описания — заголовок + пункты; ссылки — по одной на пункт; ничего не потеряно и не выдумано (все факты, числа, цитаты, названия клипов, ссылки — дословно).
4. Запиши результат в ${SP}/listify/prop_B${i + 1}.json как {"ТЗ-NN": {<parts_replace>}, ...} (сначала mkdir -p ${SP}/listify).
5. Прогони: python3 ${GUARD} ${SP}/listify/prop_B${i + 1}.json ${DATA} — исправляй файл, пока не будет GUARD OK (HARD — обязательно; warn «много новых слов» = признак выдумки, перепроверь).
Верни путь к файлу, guard_ok и короткие notes (что было спорным).`

const verify = (r, b, i) => `Ты — придирчивый проверяющий-редактор. Коллега переложил ТЗ ${b.join(', ')} в формат «как карта структуры» (одна строка = одна мысль, в строке ≤ 1 таймкода). Найди ошибки и исправь их.

Правила формата (прочитай целиком): ${RULES}
Оригиналы: ${DATA} (поле parts = источник истины; nado — как печаталось). Предложение коллеги: ${r.file}
Сравни КАЖДЫЙ ТЗ по смыслу, строка за строкой (выведи оба python-скриптом). Ищи и исправляй:
- изменён смысл, число, имя, цитата «…», название клипа, ссылка; потеряна мысль, оговорка, предупреждение ⚠️, альтернатива (вариант А/Б); добавлено то, чего в оригинале не было;
- таймкод оказался не у того пункта; в строке больше одного таймкода; пункт с таймкодом не начинается с «M:SS ▸»;
- «почему» висит хвостом к действию; строки-простыни > ~220 знаков, которые можно разбить на пункты;
- в parts попали комментарии Романа, решение (decision) или строки «было → стало» — так нельзя;
- читаемость: понятен ли заголовок списка, логичен ли порядок пунктов (по времени), не раздроблено ли то, что должно читаться одной мыслью.
Правь в ${SP}/listify/final_B${i + 1}.json (скопируй предложение и исправляй там). Прогони python3 ${GUARD} ${SP}/listify/final_B${i + 1}.json ${DATA} до GUARD OK.
Верни file_final, guard_ok и вердикт по каждому ТЗ: ok_as_is (предложение было верным без правок), problems (что нашёл), fixed (исправил ли в final).`

const results = await pipeline(
  BATCHES,
  (b, _o, i) => agent(rewrite(b, i), { label: `rewrite:B${i + 1}`, phase: 'Rewrite', schema: R_SCHEMA }),
  (r, b, i) => (r
    ? agent(verify(r, b, i), { label: `verify:B${i + 1}`, phase: 'Verify', schema: V_SCHEMA })
        .then(v => ({ batch: b, rewrite: r, verify: v }))
    : null),
)
const done = results.filter(Boolean)
log(`готово батчей: ${done.length}/${BATCHES.length}`)
return { results }
