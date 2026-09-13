export const meta = {
  name: 'ytuvi01-preview-qa',
  description: 'YTUVI01 Review v7: проверить 65 превью для дока — видно ли, о чём ТЗ; поправки кадра/кропа/подписи',
  phases: [{ title: 'QA', detail: '11 батчей по 6 превью: оценка + пробный кроп + подпись' }],
}
const SP = args.sp
const W6 = args.w6
const N = args.n

const SCHEMA = {
  type: 'object',
  properties: {
    batch: { type: 'integer' },
    items: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          preview: { type: 'string' },
          tz: { type: 'string' },
          ok: { type: 'boolean' },
          problems: { type: 'array', items: { type: 'string' } },
          fix: {
            type: 'object',
            properties: {
              t: { type: 'number' },
              box: { type: 'array', items: { type: 'number' } },
              minw: { type: 'number' },
              note: { type: 'string' },
            },
          },
          cap_suggest: { type: 'string' },
        },
        required: ['preview', 'tz', 'ok', 'problems', 'cap_suggest'],
      },
    },
  },
  required: ['batch', 'items'],
}

const prompt = i => `Ты — QA превью-картинок для Google-дока «ТЗ монтажёру» (фильм YTUVI01 «Корунд — Рубин», монтажёр Соня). Роман: «справа картинки создавай бОльшего размера, чтобы видно было, про что ты говоришь». В доке каждое превью стоит в колонке шириной ~262pt (≈350 px на обычном экране), под ним короткая подпись «таймкод · что видно».

Твой батч №${i} (6 превью):
python3 -c "import json;print(json.dumps(json.load(open('${SP}/pqa/batches.json'))[${i}],ensure_ascii=False,indent=1))"
Поля: preview — готовое превью (JPG 1600 px; ОТКРОЙ его инструментом Read — он показывает картинку); kind: overlay (наш прозрачный драфт наложен на реальный кадр, кроп по драфту), fix (БЫЛО/СТАЛО или БЫЛО/ВАРИАНТ А/Б — исправление титра, кроп по месту титра), err (кадр со стрелкой «где ошибка», кроп), frame (кадр в таймкод ТЗ, у которого не было картинки); t — секунда кадра; material_t — что это за картинка по тексту ТЗ; title — заголовок ТЗ; src_png — исходный драфт (4K PNG), если есть.
Текст ТЗ целиком: python3 -c "import json;p=json.load(open('${W6}/../montage/pravki_v2.json'))['all'];print(p[NN-1]['nado'])" (NN — номер ТЗ без «ТЗ-»).

Оцени каждое превью:
1) видно ли сразу, о чём ТЗ — объект речи (панель, плашка, титр с ошибкой, место кадра, карта) крупно и в центре внимания?
2) кроп: не обрезано важное (панель, стрелка, титр целиком), нет пустого поля на пол-кадра?
3) читается ли главный текст при ширине ~350 px?
4) для frame: правильный ли момент — на кадре то, о чём ТЗ (титр/объект виден; не переход, не затемнение, не случайный план)? Кадры рендера 1 fps: ${W6}/hires/hNNNN.jpg, где NNNN = секунда+1 (4 цифры, 1920×1080). Если кадр неудачный — посмотри соседние секунды (±1…5) и выбери лучший.
Если нужна правка — дай fix: t (секунда кадра), box [x0,y0,x1,y1] в пикселях 4K (3840×2160; hires ×2) для кропа 16:9, minw (минимальная доля ширины кадра для автокропа), note. ПЕРЕД тем как предложить рамку, сделай пробный кроп python-скриптом (PIL: кадр hires → resize(3840,2160) → crop(box) → сохрани в ${SP}/pqa/try_B${i}_*.jpg) и посмотри его через Read.
Всегда дай cap_suggest — подпись «M:SS · что видно» (≤ 70 знаков, по-русски, конкретно: «29:17 · панель „1 из 3 · Вернейль“», «27:03 · вес 3450 → 8500 карат»).
ok = true, если превью хорошее без правок (подпись всё равно дай).`

const res = await parallel(Array.from({ length: N }, (_, i) => () =>
  agent(prompt(i), { label: `qa:B${i + 1}`, phase: 'QA', schema: SCHEMA })))
const got = res.filter(Boolean)
log(`QA батчей: ${got.length}/${N}; превью с правками: ${got.flatMap(r => r.items).filter(x => !x.ok).length}`)
return { results: res }
