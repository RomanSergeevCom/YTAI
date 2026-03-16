# Testing Patterns

**Analysis Date:** 2026-03-17

## Test Framework

**Runner:**
- Node.js native `node:test` module (built-in, no external test framework)
- Version: Node.js 18+ (uses `require('node:test')` syntax)
- Config: None; tests run directly via `node --test`

**Assertion Library:**
- Node.js native `assert` module (`require('node:assert/strict')`)
- Strict mode ensures `==` comparisons use `===` semantics

**Run Commands:**
```bash
npm test                    # Run all tests (tests/**/*.test.js)
npm run test:ingest         # Run ingest-specific tests (tests/ingest/*.test.js)
npm run test:assembly       # Run assembly-specific tests (tests/assembly/*.test.js)
npm run test:review         # Run review-specific tests (tests/review/*.test.js)
```

From `package.json` at `/Users/romansergeev/YTAI/scripts/05_editing/0500_uxp/package.json`:
```json
"scripts": {
  "test": "node --test tests/**/*.test.js",
  "test:ingest": "node --test tests/ingest/*.test.js",
  "test:assembly": "node --test tests/assembly/*.test.js",
  "test:review": "node --test tests/review/*.test.js"
}
```

## Test File Organization

**Location:**
- Co-located in `tests/` directory structure mirroring source code
- Example structure:
  - Source: `src/assembly/briefParser.js`
  - Test: `tests/assembly/briefParser.test.js`
  - Source: `src/review/reviewBuilder.js`
  - Test: `tests/review/reviewBuilder.test.js`

**Naming:**
- Pattern: `{moduleName}.test.js`
- Files: `briefParser.test.js`, `constants.test.js`, `screenParser.test.js`, `reviewBuilder.test.js`

**Structure:**
```
scripts/05_editing/0500_uxp/
├── tests/
│   ├── assembly/
│   │   ├── briefParser.test.js
│   │   ├── constants.test.js
│   │   ├── assemblyBuilder.test.js
│   │   └── ...
│   ├── ingest/
│   │   ├── ingestLoader.test.js
│   │   ├── binManager.test.js
│   │   └── ...
│   ├── review/
│   │   └── reviewBuilder.test.js
│   ├── screens/
│   │   ├── screenParser.test.js
│   │   └── screenBuilder.test.js
│   ├── shared/
│   │   └── archiver.test.js
│   ├── fixtures/
│   │   ├── sample_brief.json
│   │   ├── sample_ingest.json
│   │   └── ...
│   └── mocks/
│       └── premierepro.js
└── src/
    ├── assembly/
    ├── ingest/
    ├── screens/
    ├── review/
    └── shared/
```

## Test Structure

**Suite Organization:**

From `tests/assembly/briefParser.test.js`:
```javascript
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { parseBrief, parseTimecode, formatTimecode, buildBlocks, fixAdjacentColors } = require('../../src/assembly/briefParser');

// --- parseTimecode ---

describe('parseTimecode', () => {
  it('parses MM:SS.s format', () => {
    assert.equal(parseTimecode('01:28.8'), 88.8);
  });

  it('parses MM:SS.s with zero minutes', () => {
    assert.equal(parseTimecode('00:01.5'), 1.5);
  });
  // ... more tests
});

describe('formatTimecode', () => {
  it('formats seconds to MM:SS.s', () => {
    const result = formatTimecode(88.8);
    assert.ok(result.startsWith('01:'));
  });
  // ... more tests
});

describe('parseBrief — errors', () => {
  it('throws on invalid JSON', () => {
    assert.throws(() => parseBrief('not json'), /JSON/);
  });
  // ... more tests
});
```

**Patterns:**

**Setup/Teardown:**
- No explicit `beforeEach()`/`afterEach()` used
- Tests are stateless and isolated
- Fixtures (JSON files) loaded at test suite start if needed
- Example from `briefParser.test.js`:
  ```javascript
  const FIXTURE_PATH = path.join(__dirname, '..', 'fixtures', 'sample_brief.json');
  const sampleJSON = fs.readFileSync(FIXTURE_PATH, 'utf8');
  ```

**Assertion Pattern:**
- Strict equality with `assert.equal(actual, expected)`
- Deep equality with `assert.deepEqual(actual, expected)` for objects/arrays
- Boolean checks with `assert.ok(condition, message)`
- `assert.throws(() => fn(), expectedErrorRegex)` for error validation
- `assert.notEqual()` and `assert.throws()` for negative cases

Example from `constants.test.js`:
```javascript
it('all indices are unique (no duplicate assignments)', () => {
  const values = Object.values(LABEL_COLOR_INDEX);
  const unique = new Set(values);
  assert.equal(values.length, unique.size, 'Duplicate color indices found');
});
```

## Mocking

**Framework:**
- Custom `CallRecorder` class in `tests/mocks/premierepro.js`
- No external mocking library (Jest, Sinon) detected

**Patterns:**

From `tests/mocks/premierepro.js`:
```javascript
class CallRecorder {
  constructor() {
    this.calls = [];
  }

  record(method, args) {
    this.calls.push({ method, args: [...args] });
  }

  getCalls(method) {
    return this.calls.filter(c => c.method === method);
  }

  reset() {
    this.calls = [];
  }
}

const recorder = new CallRecorder();

class MockTickTime {
  constructor(seconds) {
    this.seconds = seconds;
    this.ticks = String(Math.round(seconds * 254016000000));
  }

  equals(other) {
    return this.seconds === other.seconds;
  }
  // ... more methods
}
```

**What to Mock:**
- Adobe Premiere Pro API (unavailable outside Premiere; mocked entirely)
- File system operations (when testing logic, not I/O)
- External services: none detected in current test suite

**What NOT to Mock:**
- Core business logic functions (parsers, builders)
- Constants and configuration
- Utility functions (timecode parsing, etc.)
- Tests exercise real implementations, only mocking external APIs

Example from `constants.test.js` showing mock usage:
```javascript
const ppro = require('../mocks/premierepro');

describe('LABEL_COLOR_INDEX', () => {
  it('confirmed indices match mock ppro.Constants.ProjectItemColorLabel', () => {
    const labels = ppro.Constants.ProjectItemColorLabel;
    assert.equal(LABEL_COLOR_INDEX.Green, labels.GREEN);
    assert.equal(LABEL_COLOR_INDEX.Blue, labels.BLUE);
  });
});
```

## Fixtures and Factories

**Test Data:**

From `tests/screens/screenParser.test.js`:
```javascript
function makeSegments() {
  return [
    { id: 'seg_001', sourceFile: 'RYA-FX3-0099.MP4', inSec: 0, outSec: 10, duration: 10, tcIn: '00:00.0', use: true, block: 1 },
    { id: 'seg_002', sourceFile: 'RYA-FX3-0099.MP4', inSec: 10, outSec: 25, duration: 15, tcIn: '00:10.0', use: true, block: 1 },
    { id: 'seg_003', sourceFile: 'RYA-FX3-0100.MP4', inSec: 5, outSec: 20, duration: 15, tcIn: '00:05.0', use: true, block: 2 },
    { id: 'seg_004', sourceFile: 'RYA-FX3-0100.MP4', inSec: 30, outSec: 45, duration: 15, tcIn: '00:30.0', use: false, block: 99 }
  ];
}

describe('parseScreens', () => {
  it('parses valid screens correctly', () => {
    var segs = makeSegments();
    var raw = [
      { screen_id: 'scr_001', type: 'full_overlay', segment_id: 'seg_001', tc_in: '00:00.0', title: 'Introduction' },
      // ... more test data
    ];
    var result = parseScreens(raw, segs);
    assert.equal(result.screens.length, 2);
  });
});
```

**Location:**
- Fixture JSON files in `tests/fixtures/` directory
- Factory functions (helper functions that generate test data) defined at top of test files
- Example fixtures:
  - `tests/fixtures/sample_brief.json` — complete brief structure for parser testing
  - `tests/fixtures/sample_ingest.json` — ingest structure

**Fixtures loaded once per suite:**
```javascript
const FIXTURE_PATH = path.join(__dirname, '..', 'fixtures', 'sample_brief.json');
const sampleJSON = fs.readFileSync(FIXTURE_PATH, 'utf8');  // Loaded once, reused in multiple tests

describe('parseBrief — Format A (segments array)', () => {
  it('parses valid brief JSON', () => {
    const result = parseBrief(sampleJSON);
    assert.ok(result);
  });
  // ... more tests using sampleJSON
});
```

## Coverage

**Requirements:**
- No coverage requirements detected (no thresholds in config)
- No coverage reporting tool configured

**View Coverage:**
- No built-in coverage command
- To add coverage: would use `node --coverage` with Node.js 20+ or `c8` package

## Test Types

**Unit Tests:**
- Scope: Individual functions and parsers (parseTimecode, formatTimecode, buildBlocks, fixAdjacentColors)
- Approach: Direct function calls with inputs/outputs
- Location: `tests/assembly/`, `tests/screens/`, `tests/review/`
- Example from `briefParser.test.js`:
  ```javascript
  it('parses MM:SS.s format', () => {
    assert.equal(parseTimecode('01:28.8'), 88.8);
  });
  ```

**Integration Tests:**
- Scope: Multi-step workflows (parsing brief → building blocks → fixing colors)
- Approach: Call one public function that exercises multiple internals
- Example from `briefParser.test.js`:
  ```javascript
  it('computes used segment count per block', () => {
    const result = parseBrief(sampleJSON);  // Exercises parsing + block building
    const hookBlock = result.blocks.find(b => b.id === 1);
    assert.equal(hookBlock.usedCount, 1);
  });
  ```

**E2E Tests:**
- Not detected in current test suite
- No end-to-end tests for full Premiere Pro workflow

## Common Patterns

**Async Testing:**
- No async/await detected in test code
- No promises in test assertions
- Premiere Pro API is async (timelineBuilder.js uses `async function`), but mocks are synchronous

**Error Testing:**
- Use `assert.throws()` with regex matching on error message
- Pattern: `assert.throws(() => functionCall(), /expectedErrorMessage/)`

Example from `briefParser.test.js`:
```javascript
describe('parseBrief — errors', () => {
  it('throws on invalid JSON', () => {
    assert.throws(() => parseBrief('not json'), /JSON/);
  });

  it('throws on unknown format', () => {
    assert.throws(() => parseBrief('{"foo": "bar"}'), /Unknown brief format/);
  });
});
```

**Boundary/Edge Case Testing:**
- Extensive edge case testing for parsing logic
- Examples from `constants.test.js`:
  - All colors have unique indices
  - Out-of-range indices are caught
  - Missing/undefined values handled gracefully

```javascript
it('handles empty array without error', () => {
  fixAdjacentColors([]);
});

it('handles single block without error', () => {
  var blocks = [{ id: 1, color: 'Purple', segments: [] }];
  fixAdjacentColors(blocks);
  assert.equal(blocks[0].color, 'Purple');
});
```

**Data Format Testing:**
- Multiple format variants tested (Format A vs Format B for brief parsing)
- String encoding variations (comma vs period as decimal separator in timecode)
- Boolean string variants ("TRUE" vs `true`, "FALSE" vs `false`)

Example from `briefParser.test.js`:
```javascript
it('parses use="FALSE" as boolean false', () => {
  const result = parseBrief(sampleJSON);
  const seg = result.segments[1]; // seg_002 has use=FALSE
  assert.equal(seg.use, false);
});

it('handles comma as decimal separator', () => {
  assert.equal(parseTimecode('01:28,8'), 88.8);
});
```

---

*Testing analysis: 2026-03-17*
