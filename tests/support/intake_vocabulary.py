"""The console-redesign intake surface of `aeh.author` (`M-AUTHOR` intake, #754) — one place.

Design delta `console_redesign_design_delta.md` §3.1.1 (ADR-46) pins the intake's *value
types* by name in its interface listing — `NormalizedDocument`, `Block`, `IntakeWarning` —
and names the fields each carries. It pins **no entry-point name**: §3.1.1 says only that
`AuthoringService.draft` consumes the representation, so the function a test calls to get one
is not design-named. The TC-AUTHOR-32..38 fixture-half cases (#753) cannot each guess a
different surface, so — the `extract_vocabulary` / `author_vocabulary` precedent — every name
those cases resolve is declared HERE, once, with its status, and the tests import from here.
If #754 ships a name differently, the rename is one line in this file and nowhere else.

| Name in this file | Assumed `aeh.author` name | Status |
|---|---|---|
| `INTAKE_ISSUE` | #754 | design-named — the story the intake tier belongs to |
| `INTAKE_MODULE` | `aeh.author` | **design-named** (§3.1 module inventory; `aeh.author` itself is shipped, #690) — disclosed risk: if #754 ships the intake as a submodule (`aeh.author.intake`), the rename is this one line |
| `INTAKE_SURFACE` | `NormalizedDocument`, `Block`, `IntakeWarning` | **design-named** (§3.1.1 Interfaces listing, verbatim names) |
| `INTAKE_ENTRY` | `normalize_document(path) -> NormalizedDocument` | **invented here** — one call per file, the smallest surface the §3.1.1 field list supports; the design says only that `draft` consumes the result, so the entry point's name is this suite's disclosed bet |
| `INTAKE_REFUSAL` | `DocumentRefusedError` | **resolved** — the bet was `IntakeRefused`; #754 shipped `DocumentRefusedError` (in `aeh.author.errors`, re-exported from the package root), and the rename is this one line, the path this file exists for |
| `WARNING_CODES` | the five §3.1.1 codes | **design-named** (§3.1.1's IntakeWarning listing) |
| `SOURCE_FORMATS` | `docx` / `txt` / `pdf` | **design-named** (§3.1.1's `source_format` domain) |

The assumed *member* surface of the value types, per §3.1.1's field list:

- `NormalizedDocument(source_name, source_format, source_sha256, byte_size, blocks, warnings,
  stats)` with `stats` carrying at least `word_count`, `block_count`, `table_count`,
  `image_count`.
- `Block(kind, level, text, ordinal)` with `kind` in `heading` / `paragraph` / `list_item` /
  `table` / `image_ref`; a table's text is one row per line, cells tab-separated.
- `IntakeWarning(code, message, detail)` with `code` in `WARNING_CODES`; each message names
  its nearest heading/ordinal location, and an `encoding_fallback` message names the encoding
  actually used.

Nothing in this file imports `aeh.author`; resolution happens inside the test bodies via
`tests.support.impl.require`, so a missing symbol is a stated failure naming #754, not a
collection error.
"""

from __future__ import annotations

#: The implementing story that owns the intake tier (design delta §3.1.1, ADR-46).
INTAKE_ISSUE = "#754"

#: The module the intake surface is assumed to live in.
INTAKE_MODULE = "aeh.author"

#: The three §3.1.1-declared value types, in declaration order.
INTAKE_SURFACE = ("NormalizedDocument", "Block", "IntakeWarning")

#: The assumed one-file entry point (invented here — see the table above).
INTAKE_ENTRY = "normalize_document"

#: The refusal exception (`DocumentRefusedError`, the name #754 shipped — see the table
#: above; the `IntakeRefused` bet this name replaced was wrong and the rename is this line).
INTAKE_REFUSAL = "DocumentRefusedError"

#: §3.1.1's IntakeWarning code vocabulary, exactly.
WARNING_CODES = (
    "image_not_carried",
    "equation_not_carried",
    "structure_guessed",
    "formatting_dropped",
    "encoding_fallback",
)

#: §3.1.1's `NormalizedDocument.source_format` domain, exactly.
SOURCE_FORMATS = ("docx", "txt", "pdf")

#: Every symbol the TC-AUTHOR-32..38 fixture-half cases resolve from `aeh.author`, in one
#: tuple — the test file's `require()` argument lists are built from this (or spelled to
#: match), so the tests cannot resolve a name this file stopped declaring. (The writtenahead
#: registry entry that once keyed on this surface LANDED and is gone: #754 shipped every
#: name here, the fixture-half cases unmarked, and the history lives in
#: `tests/support/impl.py`'s registry comments.)
INTAKE_SYMBOLS = (*INTAKE_SURFACE, INTAKE_ENTRY, INTAKE_REFUSAL)
