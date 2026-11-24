"""The plain-bands draft for Validity T20 (issue #904; TC-AUTHOR-49/50, TC-PKG-42).

**Why not AF-07.** The plan names `fixtures/F-AUTHOR/AF-07` ("plain bands, no descriptors"),
but AF-07's recorded rubric replies carry a descriptor on every band: its draft asks only
`model_answer` (`AF-07/expected.toml`), and no recorded reply in F-AUTHOR drafts a band
without one. A recording is never hand-written, so the draft here is the shipped assembler's
(`aeh.author.spec.assemble` + `render_draft`, the drafter's own last, deterministic step) over
the ENG7 inventory and rubric (`tests.support.clarity_world`), with only the model's outputs
stood in:

| question | line | what the draft carries |
|---|---|---|
| Q1 | `C_Q1` evidence checklist, aspects `C_Q1_aspect1/2` | each aspect's `present` band described; `absent` exempt |
| Q2 | `C_Q2`, four bands | **plain bands**: `none`, `limited`, `adequate`, `full`, no descriptor |
| Q3 | `C_Q3`, `general` | every band described (ENG7's own) |
| Q4 | `C_Q4_key`, multiple choice, key `A` | no bands in the draft; the build makes `incorrect`/`correct` |

So exactly four descriptor questions stand, all on Q2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.support.clarity_world import eng7_inventory, eng7_rubric_values

PACKAGE = "DESC-01"
APPROVER = "Dana Teacher"
#: Q2's plain bands, worst first, with their points.
PLAIN_BANDS: tuple[tuple[str, int], ...] = (
    ("none", 0), ("limited", 1), ("adequate", 2), ("full", 3))
GRADES: dict[str, float | None] = {"pass": 6, "not yet": 0}


def plain_bands_assembly() -> Any:
    """The draft as the shipped assembler builds it (the module docstring's table)."""
    from aeh.author.spec import assemble

    inventory = eng7_inventory()
    inventory.append({"id": "Q4", "type": "mcq", "points": 1,
                      "text": "Where does Tomas live?",
                      "options": {"A": "a lighthouse", "B": "a ship"}})
    rubric = eng7_rubric_values()
    rubric["Q2"] = {"bands": [{"name": name, "points": points}
                              for name, points in PLAIN_BANDS]}
    return assemble(PACKAGE, inventory, rubric, {}, {"Q4": ["A"]}, dict(GRADES))


def write_plain_bands_draft(authoring_dir: Path, *, declare_q3: str | None = None) -> Path:
    """Render the draft into `<authoring_dir>/<draft file>` (the console's layout).

    `declare_q3` adds `scoring = "<model>"` to Q3's line, so the spec declares that one
    line's model (TC-PKG-42's `declared` partition)."""
    from aeh.author.report import draft_filename
    from aeh.author.spec import render_draft

    authoring_dir.mkdir(parents=True, exist_ok=True)
    text = render_draft(plain_bands_assembly())
    if declare_q3 is not None:
        anchor = 'id = "C_Q3"\nquestion = "Q3"\n'
        assert text.count(anchor) == 1, "the draft's Q3 line moved; re-anchor the declaration"
        text = text.replace(anchor, f'{anchor}scoring = "{declare_q3}"\n')
    path = authoring_dir / draft_filename(PACKAGE)
    path.write_text(text, encoding="utf-8")
    return path


__all__ = ["APPROVER", "GRADES", "PACKAGE", "PLAIN_BANDS", "plain_bands_assembly",
           "write_plain_bands_draft"]
