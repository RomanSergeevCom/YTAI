// eslint.config.mjs — гейт панели 0500_uxp (ESLint 10, flat config).
//
// Зачем: 25.09.2026 ReferenceError в живом коде (v1Items в exportAudioMap) искали
// два дня руками; парсер ловит его за секунду. Регулярками область видимости
// 25 000 строк не разбирается (два подхода дали 1160 и 2529 ложных срабатываний).
//
// Глобалы перечислены руками: панель живёт в UXP, а не в браузере — globals.browser
// спрятал бы реальные no-undef (в UXP нет alert/localStorage/fetch-как-в-браузере).
// sourceType 'commonjs' даёт require/module/exports.
//
// Каждый блок с languageOptions/rules ограничен files: ['**/*.js'] — сам конфиг
// (.mjs) под commonjs попадать не должен.
import { defineConfig } from 'eslint/config';

const RULES = {
  'no-undef': 'error',
  'no-unused-vars': ['error', { args: 'none', caughtErrors: 'none', varsIgnorePattern: '^_' }],
  // Пустой блок запрещён; блок с комментарием-причиной — не пустой (ровно
  // «no-empty кроме catch с комментарием» из тикета).
  'no-empty': 'error',
  'eqeqeq': ['error', 'always', { null: 'ignore' }],
  'no-fallthrough': 'error',
  'no-redeclare': 'error',
  // Инвариант версии (тикет, задача 3): у панели ОДНА версия — src/shared/version.js.
  // Строковый литерал «vX.Y.Z» в коде = вторая версия, которая начнёт врать.
  // String.raw обязателен: в обычной строке \b и \d схлопнутся, и правило
  // молча перестанет срабатывать. Комментарии могут цитировать старые версии.
  'no-restricted-syntax': ['error',
    { selector: String.raw`Literal[value=/\bv\d+\.\d+\.\d+\b/]`,
      message: 'Версия панели живёт только в src/shared/version.js' },
    { selector: String.raw`TemplateElement[value.raw=/\bv\d+\.\d+\.\d+\b/]`,
      message: 'Версия панели живёт только в src/shared/version.js' },
  ],
};

const RO = 'readonly';
const UXP_HOST = {
  document: RO, window: RO, navigator: RO, console: RO,
  setTimeout: RO, clearTimeout: RO, setInterval: RO, clearInterval: RO, globalThis: RO,
};
const UXP_MODULE = { window: RO, document: RO, console: RO, setTimeout: RO, __dirname: RO, globalThis: RO };
const NODE = {
  process: RO, console: RO, __dirname: RO, __filename: RO, Buffer: RO, globalThis: RO,
  setTimeout: RO, clearTimeout: RO, setInterval: RO, clearInterval: RO,
};

export default defineConfig([
  { ignores: ['lib/**', 'logs/**', 'node_modules/**', 'docs/**', '_research_audio_sync/**', 'LUTs/**', 'eslint.config.mjs'] },
  { files: ['**/*.js'], languageOptions: { ecmaVersion: 2022, sourceType: 'commonjs' }, rules: RULES },
  { files: ['index.js'], languageOptions: { globals: UXP_HOST } },
  { files: ['src/**/*.js'], languageOptions: { globals: UXP_MODULE } },
  { files: ['tests/**/*.js', 'tools/**/*.js'], languageOptions: { globals: NODE } },
]);
