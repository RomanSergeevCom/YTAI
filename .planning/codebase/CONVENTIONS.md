# Coding Conventions

**Analysis Date:** 2026-03-17

## Naming Patterns

**Files:**
- JavaScript source files: camelCase with descriptive names, e.g., `briefParser.js`, `timelineBuilder.js`, `screenParser.js`
- Python source files: snake_case with numeric prefixes for pipeline scripts, e.g., `0102_extract_audio.py`, `0103_sync_dji_audio.py`
- Test files: `{moduleName}.test.js` pattern, co-located with source in `tests/` directory

**Functions:**
- JavaScript: camelCase for all functions (async and sync), e.g., `findProjectItemByName()`, `parseTimecode()`, `buildBlocks()`
- Python: snake_case for all functions, e.g., `natural_key()`, `format_size()`, `ffmpeg_exists()`
- Private/internal functions: prefixed with underscore in Python (`_find_video_path()`, `_scene_out_dir()`, `_strip_ansi()`)
- JavaScript does not use underscore prefix; internal functions are documented with comments instead

**Variables:**
- JavaScript: camelCase throughout (constants still use camelCase, not SCREAMING_SNAKE_CASE)
- Python: snake_case for variables and local constants, SCREAMING_SNAKE_CASE only for module-level configuration constants
- Examples:
  - JavaScript: `projectName`, `segments`, `MARKER_COLOR_INDEX` (constants in camelCase)
  - Python: `project_name`, `video_exts`, `CLIPS_SUBDIR` (module config in SCREAMING)

**Types and Constants:**
- JavaScript: Configuration dictionaries use descriptive object literal names, e.g., `LABEL_COLOR_INDEX`, `MARKER_COLOR_INDEX`, `BLOCK_VALID_COLORS`
- Constants grouped logically and exported together via `module.exports` at file end
- `SEQUENCE_DEFAULTS` for default object structures

## Code Style

**Formatting:**
- No formatter detected; manual consistency maintained
- JavaScript: 2-space indentation (observed in all `.js` files)
- Python: 4-space indentation (observed in all `.py` files)
- Line length: no strict limit enforced; lines range from 80–120+ characters
- Trailing whitespace: preserved as-is

**Linting:**
- No linter configuration detected (no `.eslintrc`, `eslint.config.js`, `.flake8`, `setup.cfg`)
- Code style is enforced through code review and manual consistency

**JavaScript style notes:**
- Variable declaration uses `var`, `let`, and `const` mixed; `const` preferred for immutable references
- Use semicolons consistently (present on nearly all statements)
- Callback-heavy code with explicit error handling via try-catch blocks

**Python style notes:**
- Type hints used throughout (e.g., `def format_size(size_bytes: int) -> str:`)
- Modern Python 3.10+ syntax with `Path` objects and union types (`str | None`)
- f-strings for formatting (no `.format()` or `%` strings)
- Module-level docstrings in triple quotes describe script purpose, usage, and output

## Import Organization

**JavaScript Order:**
1. Built-in `require()` statements (e.g., `const { describe, it } = require('node:test')`)
2. Local module imports (e.g., `const briefParser = require('../../src/assembly/briefParser')`)
3. Configuration/constants imports (e.g., `const ppro = require('../mocks/premierepro')`)

Example from `briefParser.test.js`:
```javascript
const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { parseBrief, parseTimecode, formatTimecode, buildBlocks, fixAdjacentColors } = require('../../src/assembly/briefParser');
const { MARKER_COLOR_INDEX } = require('../../src/shared/constants');
```

**Python Order:**
1. Built-in imports (`import sys`, `from pathlib import Path`)
2. Third-party imports (`import numpy as np`)
3. Local imports (relative paths with `from module import ...`)
4. `from __future__ import annotations` at top for forward compatibility

**Path Aliases:**
- No aliasing detected in JavaScript projects
- Python uses absolute `Path` objects with `.resolve()` for consistency

## Error Handling

**Patterns:**

**JavaScript:**
- Try-catch blocks used explicitly for JSON parsing and async operations
- Example: `var raw = JSON.parse(jsonString)` wrapped in try-catch
- Throws `Error` with descriptive messages for validation failures
- Silent fallback with comments in some cases (e.g., `} catch (ex) { /* ignore */ }`)
- Conditional logging for warnings and errors

**Python:**
- Context managers (`with` statements) used for file operations
- Explicit error handling for subprocess calls with `subprocess.run()` and `check=True`
- Exit with `sys.exit(1)` for fatal errors
- Logging to both console and file via `tee_print()` utility function
- Try-except blocks catch exceptions but often continue gracefully

Examples:
- JavaScript: `if (rc != 0 && !verbose) { tee_print(log_f, "    FFmpeg output:"); }`
- Python: Explicit stderr messages before exit: `print(f"ERROR: {message}", file=sys.stderr); sys.exit(1)`

## Logging

**Framework:** Native `console` in JavaScript, native `print()` with logging utilities in Python

**Patterns:**

**JavaScript:**
- No centralized logging framework detected
- Comments document intent and invariants
- JSDoc comments for public functions
- Example from `timelineBuilder.js`: `if (logger) logger.debug(...)` for optional logging

**Python:**
- `tee_print(log_f, msg)` utility writes to both console and log file simultaneously
- Log files created with timestamp: `{project_name}_{operation}_20260311_120000.log`
- Lines are explicitly flushed: `log_f.flush()`
- Error messages prefixed with "ERROR:" or "INFO:" for clarity

## Comments

**When to Comment:**

**JavaScript:**
- File header comments explain module purpose and usage
- Inline comments document non-obvious logic or workarounds
- Docstring comments for public functions (JSDoc-like)
- Example: `// Parse timecode string "MM:SS.s" or "HH:MM:SS.s" → seconds`

**JSDoc/TSDoc:**
- Extensive JSDoc used for public functions
- Includes `@param`, `@returns` tags
- Example from `timelineBuilder.js`:
  ```javascript
  /**
   * Find a project item by name (recursively searches bins).
   * Uses FolderItem.cast() to traverse into bins (required by Premiere UXP API).
   * @param {Object} project - Premiere Pro project
   * @param {string} name - Item name to find
   * @param {Object} [logger] - Optional logger for debug output
   * @returns {Object|null} The found project item or null
   */
  ```

**Python:**
- Module-level docstrings (triple quotes) describe script purpose, usage, output, and examples
- Inline comments explain logic, especially around timestamps and file handling
- Docstrings use imperative language ("Reads...", "Returns...")
- Example from `0102_extract_audio.py`:
  ```python
  def natural_key(s: str):
      """Natural sort for strings with numbers: clip1, clip2, clip10."""
  ```

## Function Design

**Size:**
- Utility functions: 5–20 lines (lean, single purpose)
- Parser/builder functions: 30–50 lines (moderate complexity, clear step-by-step logic)
- Main orchestration functions: longer but heavily commented

**Parameters:**
- Prefer explicit parameters over config objects (in JavaScript)
- Python uses `Path` objects extensively instead of strings for file paths
- Optional parameters documented with JSDoc `[name]` syntax
- Type hints in Python; types documented in JSDoc for JavaScript

**Return Values:**
- Single return type per function (no overloading)
- JavaScript often returns objects with multiple properties for complex results
- Python uses tuples or dataclasses for multi-value returns
- Null/None returns explicitly documented and tested

## Module Design

**Exports:**

**JavaScript:**
- CommonJS `module.exports` at end of file
- Exports specific functions and constants, never default exports
- Example from `src/shared/constants.js`:
  ```javascript
  module.exports = {
    LABEL_COLOR_INDEX,
    MARKER_COLOR_INDEX,
    VALID_COLORS,
    // ... more exports
  };
  ```

**Python:**
- Functions and classes marked as public; no explicit `__all__` pattern observed
- Modules imported with `from module import func` or `import module`
- No barrel/index file pattern

**Barrel Files:**
- No barrel files detected in JavaScript codebase
- Each module exports its own functions; consumers import from source directly

---

*Convention analysis: 2026-03-17*
