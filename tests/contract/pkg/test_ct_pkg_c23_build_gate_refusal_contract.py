"""`TS-160` (issue #706) — `TC-PKG-C23`: the clause suite for the build-gate refusal
contract (`CT-PKG-23`, `FR-PKG-28`; test plan delta §6.2).

> **CT-PKG-23** (error). A spec containing the substring `<<PLACEHOLDER:` fails the build
> with an error naming file, field, and reason, raised before any other spec check and
> before any catalog write; not retryable, no state change.

**On the plan's "Table §6.12 rows 4–6".** The delta plan's §6 ends at §6.2 — there is no
§6.12. Other delta plans use §6.12 for the blast-radius rows of their clause suites, and
#705's `TC-CONF-C23` suite takes §6.12 rows 1–3 there, so rows 4–6 here are read as
`CT-PKG-23`'s three break-conditions as §6.2 states them — the rows the suite exists to
hold, one test each:

- **Row 4** — the refusal names file, field, and reason; breaks if it stops naming the field.
- **Row 5** — the sentinel check precedes every other spec check; breaks if the check moves
  later.
- **Row 6** — the refusal precedes any catalog write, no state change, not retryable; breaks
  if the catalog write precedes the refusal.

**Doors.** Row 4 takes the library door: `read_package_spec` followed by `plan_package`
under one `pytest.raises` — the two are the whole of the build path that runs before any
write, and the gate needs the raw spec text (a parsed mapping carries neither the sentinel
nor the `# PLACEHOLDER(<reason>):` comment above it), so wherever in `pipeline/packages.py`
#688 puts the check, one of those two calls raises. Rows 5 and 6 drive the real
`aeh package build` (`aeh.pipeline.cli.main`, in process) because their discriminators are
placement and file state, which the library door cannot see: row 5 asserts the structural
refusal's own phrases are **absent** from a spec that is also structurally defective, and
row 6 hashes every file under the data directory around the call.

**Written ahead of #688** (`writtenahead`, keyed `#688 build-gate sentinel`): the registry
pins the gate's arrival on `aeh.pipeline.packages:PlaceholderSentinelError`, the refusal
type the story must add — the design names the file and the substring check and no Python
name, and a `symbol` on any name the module already has would resolve immediately. The type
is invented, but this file and
`tests/integration/pkg/test_tc_pkg_38_build_gate_sentinel.py` invent and use it together;
if #688 lands the refusal under `PackageSpecError` with no distinct type, the rename is one
line in `tests/support/impl.py` and one in each of the two files. Until then every body
fails on `require()` — `NotImplementedYet` naming #688 — which is the designed red.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
import aeh.pipeline.packages as packages_module
from aeh.pipeline import cli
from aeh.pipeline.packages import PackageSpecError, plan_package, read_package_spec
from tests.support.impl import PIPE_PACKAGES_MODULE, require

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]

REPO = Path(__file__).resolve().parents[3]
SAMPLE_SPEC = REPO / "docs" / "live-tests" / "config" / "ps9-forces-01.package.toml"

FIELD = "question text"
REASON = "the model reply did not determine it"
SENTINEL_COMMENT = (
    f"# PLACEHOLDER({REASON}): the teacher must supply what is missing\n"
)
SENTINEL_VALUE = f'text = "<<PLACEHOLDER: {FIELD}>>>"'

#: The sample spec's Q1 text — the anchor the sentinel replaces. Q1's text is otherwise the
#: spec's most ordinary content, which is the point: the gate fires on the sentinel, not on
#: anything wrong with the question.
Q1_TEXT = ('text = "An object is moving at a steady speed in a straight line. The net force '
           'on it is zero. What will the object do next?"')

#: The phrases the structural refusals for these defects carry (as `TC-PIPE-28` records
#: them). Row 5 plants the defects and asserts every phrase is absent — the gate ran first.
STRUCTURAL_PHRASES = (
    "is not among",       # a key no option matches
    "must be a number",   # a string where a number is required
    "odd",                # an odd band count (M-PKG's publish-time rule)
    "already exists",     # a taken package id (the duplicate-id check)
)


def _write_spec(tmp_path: Path, edits: list[tuple[str, str]], name: str = "draft.package.toml"
                ) -> Path:
    """The sample spec with each edit applied, as a draft file. Each anchor must occur
    exactly once — a silent replacement of the wrong line would test a spec that does not
    say what the case claims."""
    text = SAMPLE_SPEC.read_text(encoding="utf-8")
    for old, new in edits:
        assert text.count(old) == 1, f"anchor is not unique in the sample spec: {old!r}"
        text = text.replace(old, new)
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _data_state(data_dir: Path) -> list[tuple[str, int, str]]:
    """Every file under the data directory as `(relative path, size, sha256)`, sorted. The
    file-state oracle: equal before and after the refused call means nothing was written,
    however much of the build path ran first."""
    state = []
    for path in sorted(data_dir.rglob("*")):
        if path.is_file():
            state.append(
                (
                    path.relative_to(data_dir).as_posix(),
                    path.stat().st_size,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
    return state


# --- row 4: the refusal names file, field, and reason -------------------------------------------


def test_ct_pkg_c23_row_4_the_refusal_names_file_field_and_reason(tmp_path):
    """`CT-PKG-23`'s naming clause, at the library door.

    `read_package_spec` then `plan_package` under one `pytest.raises`: together they are the
    whole pre-write build path, so wherever in `pipeline/packages.py` the gate sits, one of
    the two raises — and the message names the three things the clause requires. The field is
    the text the sentinel carries and the reason is the text the comment above it carries
    (`FR-AUTHOR-11`), both planted to appear nowhere else in the sample spec, so the
    assertion cannot pass on a structural refusal or on spec prose. The exception type is
    read off the module after `require()`, not imported: before #688 lands, the name does not
    exist, and the module-level import of it would be a collection error rather than the
    designed red.
    """
    require(PIPE_PACKAGES_MODULE, "PlaceholderSentinelError", issue="#688")
    spec_path = _write_spec(tmp_path, [(Q1_TEXT,
                                        SENTINEL_COMMENT + SENTINEL_VALUE)])
    sentinel_error = packages_module.PlaceholderSentinelError

    with pytest.raises((PackageSpecError, sentinel_error)) as caught:
        spec = read_package_spec(spec_path)
        plan_package(spec, tmp_path / "packages")

    message = str(caught.value)
    assert str(spec_path) in message, f"the refusal does not name the file: {message!r}"
    assert FIELD in message, f"the refusal does not name the field: {message!r}"
    assert REASON in message, f"the refusal does not name the reason: {message!r}"


# --- row 5: the sentinel check precedes every other spec check -----------------------------------


def test_ct_pkg_c23_row_5_the_sentinel_check_precedes_every_other_spec_check(
        tmp_data_dir, tmp_path, capsys):
    """`CT-PKG-23`'s precedence clause, at the CLI door.

    The spec carries the sentinel in Q1's text **and** a structural defect at every layer the
    build path checks — a key no option matches, a string `points`, an odd band count — and
    is built against a data directory that already holds the same package id, so the
    duplicate-id check would fire too. Whichever structural check ran first would name its
    defect in the refusal; the assertion is that none of them does. (The odd count is
    `M-PKG`'s own publish-time rule, `TC-PIPE-28` — it fires after the package file exists,
    the farthest a moved gate could be caught before a package is published.)
    """
    require(PIPE_PACKAGES_MODULE, "PlaceholderSentinelError", issue="#688")
    edits: list[tuple[str, str]] = [(Q1_TEXT, SENTINEL_COMMENT + SENTINEL_VALUE)]
    # a key no option matches (C1's key, "C", is among Q1's options — "Z" is not)
    edits.append(('question = "Q1"\nkey = "C"', 'question = "Q1"\nkey = "Z"'))
    # a string where a number is required (Q4's points)
    edits.append(('id = "Q4"\ntype = "open"\npoints = 3',
                  'id = "Q4"\ntype = "open"\npoints = "three"'))
    # an odd band count (drop C4's best band; three bands remain)
    edits.append((
        '  { name = "full", points = 3, descriptor = "Names the weight (gravity) pulling down '
        'AND the normal (support) force pushing up, AND says they are equal so the net force '
        'is zero." },\n',
        "",
    ))
    spec_path = _write_spec(tmp_path, edits)

    # the duplicate-id check would also fire: the same package id is built once, cleanly, first
    clean = _write_spec(tmp_path / "clean", [], name="clean.package.toml")
    clean_code = cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                           "--spec", str(clean)])
    assert clean_code == 0, f"the clean spec did not build: {capsys.readouterr().err!r}"
    capsys.readouterr()

    code = cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                     "--spec", str(spec_path)])
    err = capsys.readouterr().err

    assert code == 1, f"the sentinel-carrying spec built: {err!r}"
    assert REASON in err, f"the refusal is not the sentinel's: {err!r}"
    for phrase in STRUCTURAL_PHRASES:
        assert phrase not in err, (
            f"the structural check for {phrase!r} ran before the sentinel check: {err!r}")


# --- row 6: the refusal precedes any catalog write, no state change, not retryable ---------------


def test_ct_pkg_c23_row_6_the_refusal_precedes_any_catalog_write_and_is_not_retryable(
        tmp_data_dir, tmp_path, capsys):
    """`CT-PKG-23`'s no-write and not-retryable clauses, at the CLI door.

    File state around the call, not intent: every file under the data directory is hashed
    before the refused build and byte-compared after — a half-built package file, a catalog
    row, a blob, anything. The retry arm is the clause's last sentence: a second attempt of
    the same spec is refused again, with the same message, and the data directory is still
    byte-identical. (The spec itself lives outside the data directory, so its own bytes are
    not part of the state the build must not change.)
    """
    require(PIPE_PACKAGES_MODULE, "PlaceholderSentinelError", issue="#688")
    spec_path = _write_spec(tmp_path, [(Q1_TEXT,
                                        SENTINEL_COMMENT + SENTINEL_VALUE)])
    before = _data_state(tmp_data_dir)

    first_code = cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                           "--spec", str(spec_path)])
    first_err = capsys.readouterr().err

    assert first_code == 1, f"the sentinel-carrying spec built: {first_err!r}"
    assert REASON in first_err, f"the refusal is not the sentinel's: {first_err!r}"
    state_after_first = _data_state(tmp_data_dir)
    assert state_after_first == before, (
        "the refusal wrote to the data directory (file state around the call)")

    second_code = cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                            "--spec", str(spec_path)])
    second_err = capsys.readouterr().err

    assert second_code == 1, f"the retry did not refuse: {second_err!r}"
    assert second_err == first_err, (
        f"the retry was refused differently:\n  first: {first_err!r}\n"
        f"  second: {second_err!r}")
    assert _data_state(tmp_data_dir) == state_after_first, (
        "the retry changed the data directory")