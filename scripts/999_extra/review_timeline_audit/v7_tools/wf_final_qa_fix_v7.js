export const meta = {
  name: 'ytuvi01-final-qa-fix',
  description: 'YTUVI01 Review v7, 2-й проход: доводка текста 62 ТЗ по замечаниям финального QA (переписчик + скептик на батч, кодовый страж)',
  phases: [
    { title: 'Rewrite', detail: '16 батчей по 4 ТЗ: правила v2 + замечания QA → parts_replace, guard_v7b' },
    { title: 'Verify', detail: 'скептик на батч: смысл, факты, согласованность с 💬 Романа, формат → final + guard' },
  ],
}
const SP = args.sp
const RULES = `${SP}/listify_rules_v2.md`
const DATA = `${SP}/r3_data.json`
const GUARD = `${SP}/guard_v7b.py`
const BATCHES = args.batches
const DEC = { type: 'array', items: { type: 'object', properties: { tz: { type: 'string' }, text: { type: 'string' } }, required: ['tz', 'text'] } }
const R_SCHEMA = {
  type: 'object',
  properties: { file: { type: 'string' }, guard_ok: { type: 'boolean' }, tz: { type: 'array', items: { type: 'string' } },
                notes: { type: 'string' }, decisions: DEC },
  required: ['file', 'guard_ok', 'tz', 'decisions'],
}
const V_SCHEMA = {
  type: 'object',
  properties: {
    file_final: { type: 'string' }, guard_ok: { type: 'boolean' }, decisions: DEC,
    verdicts: { type: 'array', items: { type: 'object', properties: {
      tz: { type: 'string' }, ok_as_is: { type: 'boolean' }, problems: { type: 'array', items: { type: 'string' } }, fixed: { type: 'boolean' },
    }, required: ['tz', 'ok_as_is', 'problems', 'fixed'] } },
  },
  required: ['file_final', 'guard_ok', 'verdicts', 'decisions'],
}
const pyList = b => '[' + b.map(x => `'${x}'`).join(',') + ']'

const rewrite = (b, i) => `Ты — редактор ТЗ монтажёру (YouTube-фильм YTUVI01 «Корунд — Рубин», монтажёр Соня, заказчик Роман). Финальная приёмка дока нашла замечания по тексту ТЗ ${b.join(', ')}. Твоя задача — довести их текст.

1. Прочитай ЦЕЛИКОМ правила: ${RULES} (и базовые правила, на которые он ссылается).
2. Выведи свои ТЗ: python3 -c "import json;d=json.load(open('${DATA}'));print(json.dumps({k:d[k] for k in ${pyList(b)}},ensure_ascii=False,indent=1))"
   parts — источник истины; nado — как печатается сейчас; qa_issues — замечания приёмки по этому ТЗ (бери те, что про ТЕКСТ); audit_findings_full — полные тексты находок (для восстановления обрывков); roman_comment — пожелания Романа (главнее старого текста); typo — правки «было → стало» (их печатает скрипт, не дублируй).
3. Для КАЖДОГО ТЗ собери новый parts_replace (блоки now, do, list, where, src, tl; пустые не пиши; для ТЗ-30/74/75/76 без list). Исправь всё текстовое из qa_issues, что можно исправить без новых фактов. Не выдумывай факты, числа, названия. Сохрани все ссылки, если QA не назвал ссылку битой.
4. Запиши результат в ${SP}/r3/prop_B${i + 1}.json как {"ТЗ-NN": {<parts_replace>}, ...} (mkdir -p ${SP}/r3).
5. python3 ${GUARD} ${SP}/r3/prop_B${i + 1}.json ${DATA} — исправляй до GUARD OK; warn разбери по смыслу.
Верни путь к файлу, guard_ok, notes (что сделал со спорными замечаниями и что сознательно оставил) и decisions — вопросы Роману, без которых противоречие не снять (коротко, по одному на ТЗ; пустой список, если нет).`

const verify = (r, b, i) => `Ты — придирчивый редактор-приёмщик. Коллега довёл текст ТЗ ${b.join(', ')} по замечаниям финальной приёмки. Проверь и исправь.

Правила: ${RULES}. Данные (оригинал parts, nado, qa_issues, audit_findings_full, roman_comment): ${DATA}. Предложение коллеги: ${r.file}. Его заметки: ${JSON.stringify(r.notes || '').slice(0, 1500)}
Для КАЖДОГО ТЗ сравни предложение с оригиналом и с qa_issues:
- все ли текстовые замечания QA учтены (формат «таймкод ▸ пункт», нет перечислений в строку, нет обрывков и жаргона, есть ✅ СДЕЛАТЬ, нет противоречий, 💬 Романа учтён);
- не изменён ли смысл, не потеряны ли факт, число, цитата, оговорка ⚠️, вариант, ссылка; не добавлено ли выдуманное;
- таймкоды у своих пунктов, в строке не больше одного;
- не попали ли в parts комментарии Романа, решения или строки «было → стало».
Правь в ${SP}/r3/final_B${i + 1}.json (скопируй предложение). Прогони python3 ${GUARD} ${SP}/r3/final_B${i + 1}.json ${DATA} до GUARD OK.
Верни file_final, guard_ok, verdicts по каждому ТЗ и decisions (итоговый список вопросов Роману по этим ТЗ, если нужны).`

const results = await pipeline(
  BATCHES,
  (b, _o, i) => agent(rewrite(b, i), { label: `rewrite:B${i + 1}`, phase: 'Rewrite', schema: R_SCHEMA }),
  (r, b, i) => (r
    ? agent(verify(r, b, i), { label: `verify:B${i + 1}`, phase: 'Verify', schema: V_SCHEMA }).then(v => ({ batch: b, rewrite: r, verify: v }))
    : null),
)
log(`готово батчей: ${results.filter(Boolean).length}/${BATCHES.length}`)
return { results }
