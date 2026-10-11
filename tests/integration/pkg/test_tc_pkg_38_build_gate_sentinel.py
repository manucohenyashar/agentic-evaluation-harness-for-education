"""`TS-160` (issue #706) — `TC-PKG-38`: the build-gate placeholder-sentinel refusal
(`FR-PKG-28`, `CT-PKG-23`; test plan delta §5.3, written from design delta §3.4).

> **CT-PKG-23** (error). A spec containing the substring `<<PLACEHOLDER:` fails the build
> with an error naming file, field, and reason, raised before any other spec check and
> before any catalog write; not retryable, no state change.

The plan's row: sentinel in question text / answer key / points / a `[grades]` boundary;
variant: sentinel plus an odd band count; variant: catalog untouched after refusal; variant:
retry of the same build. Oracle: exact error text + file state.

**Every arm drives the real `aeh package build`** (`aeh.pipeline.cli.main`, in process, as
the operator types it) against a real store under `tmp_data_dir`, and the state assertions
are **file state around the call** — the data directory's files captured before the call and
byte-compared after — never the gate's intent.

The spec is a *file* on purpose: the sentinel lives in the spec's text (`<<PLACEHOLDER:
<field>>>` with the `# PLACEHOLDER(<reason>):` comment on the line above, `FR-AUTHOR-11`),
which no parsed mapping carries, so the gate that refuses it sits on the spec-text path —
`read_package_spec` in `pipeline/packages.py`, the only place in the build path the raw text
exists (`#688`'s technical note: the check is at the top of the build path, before
`plan_package`/`build_package` do any work).

**The refusal's three names are asserted by their exact strings.** The field is the text the
sentinel carries; the reason is the text the comment carries; the file is the spec path the
command was given. Each is planted to appear nowhere else in the sample spec, and the
discriminating arms additionally assert the structural refusal's own phrase is **absent**:
a sentinel-carrying spec that is also structurally defective (a string `points`, a key no
option matches, an odd band count, a taken package id) must be refused at the sentinel, not
at the defect. A golden full message is not pinnable ahead of the implementation — the
design pins the three names, not the wording — so "exact error text" is asserted as those
three exact names; a golden can be added at the unmark if the design wants one.

**Written ahead of #688; the marker came off when the story landed.** While red, the
registry pinned the gate's arrival on the invented refusal type
`aeh.pipeline.packages:PlaceholderSentinelError` (every name in `pipeline/packages.py`
predated the gate, so a `symbol` on any of them resolved immediately). #688 landed the
refusal under the existing `PackageSpecError` with no distinct type, so the declared rename
path was taken: the bodies now `require()` the gate's own new constant `PLACEHOLDER_SENTINEL`
— the marker the gate exists to find — and the registry entry came off.
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
from aeh.pipeline import cli
from tests.support.impl import PIPE_PACKAGES_MODULE, require

pytestmark = [pytest.mark.integration]

REPO = Path(__file__).resolve().parents[3]
SAMPLE_SPEC = REPO / "docs" / "live-tests" / "config" / "ps9-forces-01.package.toml"

#: C4's best band. Dropping it leaves three bands — the odd count `TC-PIPE-28` records as
#: refused by `M-PKG` itself, at publish, after the package file exists.
C4_FULL_BAND = (
    '  { name = "full", points = 3, descriptor = "Names the weight (gravity) pulling down '
    'AND the normal (support) force pushing up, AND says they are equal so the net force is '
    'zero." },\n'
)

#: One placement per graded field the plan names: `(arm id, the exact sample-spec text the
#: sentinel replaces, its replacement, the field text the sentinel carries, the reason the
#: comment above it carries, and the phrase the structural refusal for the same defect would
#: carry — `None` where the spec is otherwise well-formed and the gate is the only thing
#: standing between the sentinel and a published package)`. Each field and reason string is
#: planted to appear nowhere else in the sample spec, so the message assertions below cannot
#: pass on a structural refusal or on spec prose.
PLACEMENTS = [
    (
        "question-text",
        'text = "An object is moving at a steady speed in a straight line. The net force '
        'on it is zero. What will the object do next?"',
        "# PLACEHOLDER(the model reply did not determine it): the teacher must supply what "
        "is missing\n"
        'text = "<<PLACEHOLDER: question text>>>"',
        "question text",
        "the model reply did not determine it",
        None,
    ),
    (
        "answer-key",
        'question = "Q1"\nkey = "C"',
        'question = "Q1"\n'
        "# PLACEHOLDER(the draft could not determine the key): the teacher must supply what "
        "is missing\n"
        'key = "<<PLACEHOLDER: answer key>>>"',
        "answer key",
        "the draft could not determine the key",
        "is not among",
    ),
    (
        "points",
        'id = "Q4"\ntype = "open"\npoints = 3',
        'id = "Q4"\ntype = "open"\n'
        "# PLACEHOLDER(the draft could not determine the points): the teacher must supply "
        "what is missing\n"
        'points = "<<PLACEHOLDER: question points>>>"',
        "question points",
        "the draft could not determine the points",
        "must be a number",
    ),
    (
        "grade-boundary",
        "[grades]\nA = 8",
        "[grades]\n"
        "# PLACEHOLDER(the draft could not determine the boundary): the teacher must supply "
        "what is missing\n"
        'A = "<<PLACEHOLDER: grade boundary>>>"',
        "grade boundary",
        "the draft could not determine the boundary",
        "must be a number",
    ),
]


def _write_spec(tmp_path: Path, edits: list[tuple[str, str]]) -> Path:
    """The sample spec with each edit applied, as a draft file. Each anchor must occur
    exactly once — a silent replacement of the wrong line would test a spec that does not
    say what the case claims."""
    text = SAMPLE_SPEC.read_text(encoding="utf-8")
    for old, new in edits:
        assert text.count(old) == 1, f"anchor is not unique in the sample spec: {old!r}"
        text = text.replace(old, new)
    path = tmp_path / "draft.package.toml"
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


# --- TC-PKG-38: every placement refused, naming file + field + reason ---------------------------


@pytest.mark.parametrize("placement", PLACEMENTS, ids=lambda p: p[0])
def test_tc_pkg_38_a_sentinel_in_any_graded_field_refuses_the_build(
        tmp_data_dir, tmp_path, capsys, placement):
    """Every placement refused, naming file + field + reason (`FR-PKG-28`); where the same
    spec carries a structural defect too, the refusal is the sentinel's — the structural
    phrase is absent — and the data directory is byte-identical around the call."""
    require(PIPE_PACKAGES_MODULE, "PLACEHOLDER_SENTINEL", issue="#688")
    _, old, new, field, reason, structural = placement
    spec_path = _write_spec(tmp_path, [(old, new)])
    before = _data_state(tmp_data_dir)

    code = cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                     "--spec", str(spec_path)])
    err = capsys.readouterr().err

    assert code == 1, f"the sentinel-carrying spec built: {err!r}"
    assert str(spec_path) in err, f"the refusal does not name the file: {err!r}"
    assert field in err, f"the refusal does not name the field {field!r}: {err!r}"
    assert reason in err, f"the refusal does not name the reason {reason!r}: {err!r}"
    if structural is not None:
        assert structural not in err, (
            f"the structural check ran before the sentinel check ({structural!r} in the "
            f"refusal): {err!r}")
    assert _data_state(tmp_data_dir) == before, (
        "the refusal wrote to the data directory (file state around the call)")


# --- TC-PKG-38 variants -------------------------------------------------------------------------


def test_tc_pkg_38_a_sentinel_refusal_precedes_a_separate_structural_defect(
        tmp_data_dir, tmp_path, capsys):
    """Variant: a sentinel plus an odd band count is still refused at the sentinel. The odd
    count is `M-PKG`'s own publish-time rule (`TC-PIPE-28` — it fires after the package file
    exists), so if the gate ran anywhere after `plan_package` the operator would read the
    band-count refusal instead."""
    require(PIPE_PACKAGES_MODULE, "PLACEHOLDER_SENTINEL", issue="#688")
    _, old, new, _field, reason, _structural = PLACEMENTS[0]
    spec_path = _write_spec(
        tmp_path, [(C4_FULL_BAND, ""), (old, new)])
    before = _data_state(tmp_data_dir)

    code = cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                     "--spec", str(spec_path)])
    err = capsys.readouterr().err

    assert code == 1, f"the sentinel-carrying spec built: {err!r}"
    assert reason in err, f"the refusal is not the sentinel's: {err!r}"
    assert "odd" not in err, f"the band-count check ran before the sentinel check: {err!r}"
    assert _data_state(tmp_data_dir) == before, (
        "the refusal wrote to the data directory (file state around the call)")


def test_tc_pkg_38_the_catalog_is_untouched_after_the_refusal(tmp_data_dir, tmp_path, capsys):
    """Variant: catalog untouched after refusal. The well-formed spec builds first — the
    negative control: the gate does not false-positive on legal content, which is the
    design's own claim for the sentinel (`<<PLACEHOLDER:` sits outside every legal value
    domain, design delta §3.1). The sentinel-carrying spec for the same package id is then
    refused with the data directory byte-identical — and at the sentinel, not at the
    duplicate-id check `plan_package` would raise."""
    require(PIPE_PACKAGES_MODULE, "PLACEHOLDER_SENTINEL", issue="#688")
    _, old, new, _field, reason, _structural = PLACEMENTS[0]
    clean = _write_spec(tmp_path / "clean", [])
    sentinel = _write_spec(tmp_path / "sentinel", [(old, new)])

    code = cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                     "--spec", str(clean)])
    captured = capsys.readouterr()
    out, err = captured.out, captured.err
    assert code == 0, f"the well-formed spec without the sentinel did not build: {err!r}"
    assert '"package_version"' in out

    before = _data_state(tmp_data_dir)
    code = cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                     "--spec", str(sentinel)])
    err = capsys.readouterr().err
    assert code == 1, f"the sentinel-carrying spec built: {err!r}"
    assert reason in err, f"the refusal is not the sentinel's: {err!r}"
    assert "already exists" not in err, (
        f"the duplicate-id check ran before the sentinel check: {err!r}")
    assert _data_state(tmp_data_dir) == before, (
        "the refusal changed the data directory (file state around the call)")


def test_tc_pkg_38_retrying_the_refused_build_is_refused_identically(
        tmp_data_dir, tmp_path, capsys):
    """Variant: retry of the same build — the refusal is not retryable (`CT-PKG-23`'s last
    clause): a second attempt is refused again, identically, and nothing is written either
    time."""
    require(PIPE_PACKAGES_MODULE, "PLACEHOLDER_SENTINEL", issue="#688")
    _, old, new, _field, reason, _structural = PLACEMENTS[0]
    spec_path = _write_spec(tmp_path, [(old, new)])
    before = _data_state(tmp_data_dir)

    first_code = cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                           "--spec", str(spec_path)])
    first_err = capsys.readouterr().err
    state_after_first = _data_state(tmp_data_dir)
    assert first_code == 1 and reason in first_err, first_err
    assert state_after_first == before, (
        "the first refusal wrote to the data directory (file state around the call)")

    second_code = cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                            "--spec", str(spec_path)])
    second_err = capsys.readouterr().err

    assert second_code == 1, f"the retry did not refuse: {second_err!r}"
    assert second_err == first_err, (
        f"the retry was refused differently:\n  first: {first_err!r}\n  second: {second_err!r}")
    assert _data_state(tmp_data_dir) == state_after_first, (
        "the retry changed the data directory")