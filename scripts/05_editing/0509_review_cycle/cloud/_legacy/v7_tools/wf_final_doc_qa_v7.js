export const meta = {
  name: 'ytuvi01-final-doc-qa',
  description: 'YTUVI01 Review v7: глазная проверка 64 страниц вкладки «ТЗ монтажёру · v3» по 5 критериям тикета + визуальные дефекты',
  phases: [{ title: 'QA', detail: '8 агентов по 8 страниц PDF-экспорта вкладки' }],
}
const DIR = args.dir
const N = args.pages
const PER = 8
const SCHEMA = {
  type: 'object',
  properties: {
    pages: { type: 'array', items: { type: 'integer' } },
    ok_pages: { type: 'array', items: { type: 'integer' } },
    issues: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          page: { type: 'integer' },
          tz: { type: 'string' },
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
          criterion: { type: 'string' },
          what: { type: 'string' },
        },
        required: ['page', 'tz', 'severity', 'criterion', 'what'],
      },
    },
  },
  required: ['pages', 'ok_pages', 'issues'],
}
const pad = n => String(n).padStart(2, '0')
const prompt = (a, b) => `Ты — придирчивый редактор-приёмщик. Проверяешь страницы ${a}–${b} PDF-экспорта вкладки Google-дока «ТЗ монтажёру · v3» (фильм YTUVI01 «Корунд — Рубин»). Открой КАЖДУЮ страницу инструментом Read — это PNG: ${Array.from({ length: b - a + 1 }, (_, i) => `${DIR}/p-${pad(a + i)}.png`).join(' ')}
Устройство вкладки: одна таблица — № | ⏱ TC | тип | «ТЗ монтажёру» | «Материал / ссылки». Строки глав — с заливкой и [скобками]. В ТЗ блоки с жирными метками ❌ СЕЙЧАС · ✅ СДЕЛАТЬ · 📋 СПИСОК · 📍 ГДЕ · 📚 ИСТОЧНИК · 🎬 НА ТАЙМЛАЙНЕ; 💬 — комментарии заказчика (фиолетовым); ❓ — решение заказчика.

Критерии приёмки (заказчик Роман, 10.09):
1. «ТЗ монтажёру» — никаких сплошных абзацев: каждый таймкод — ОТДЕЛЬНОЙ строкой, как в оглавлении: «таймкод ▸ пункт», таймкоды столбиком слева; одна строка — одна мысль; ничего не перечислено в строку через «·», «,», «→».
2. Справа у каждого ТЗ — КРУПНАЯ картинка-превью, по которой видно, о чём речь (наш драфт на реальном кадре, «было/стало», кадр со стрелкой). Картинка стоит отдельно, текст к ней не прилипает сбоку. Под картинкой короткая подпись «таймкод · что видно».
3. Суммы — цифрами (например «$30,3 МЛН (= $30 300 000)»).
4. Опечатки — строка «было «…» → стало «…»», изменённые буквы выделены (красным/зачёркнуто).
5. Прочее: обрывки, наезды, пустые или битые картинки, дубли строк, мусорные символы («▸ ▸», «@», лишние скобки), непонятные подписи, сломанные ссылки, текст не того ТЗ, разрыв строки ТЗ между страницами, делающий её нечитаемой.
Для каждой проблемы укажи страницу, номер ТЗ (как в колонке №; если не видно — «?»), severity (high — нарушает критерий 1–4 или вводит в заблуждение; medium — заметно мешает; low — косметика), criterion (1–5) и что именно. Страницы без замечаний перечисли в ok_pages. Не выдумывай: если мелко и не разобрать — так и пиши, не додумывай.`

const tasks = []
for (let a = 1; a <= N; a += PER) {
  const b = Math.min(N, a + PER - 1)
  tasks.push(() => agent(prompt(a, b), { label: `qa:p${pad(a)}-${pad(b)}`, phase: 'QA', schema: SCHEMA }))
}
const res = await parallel(tasks)
const issues = res.filter(Boolean).flatMap(r => r.issues)
log(`страниц проверено: ${res.filter(Boolean).flatMap(r => r.pages).length}/${N}; замечаний: ${issues.length} (high ${issues.filter(i => i.severity === 'high').length})`)
return { results: res, issues }
