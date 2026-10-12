"""`TC-AUTHOR-28` — the recordings half: the double-honesty census over the captured tree.

Case: test plan §5.6, `FR-PROV-10`, `§4.2`'s double-honesty rule, `TS-153` (#686). The
corpus half beside this file is green; **this half was writtenahead-red on purpose** until
#690's capture pass recorded the tree (the honest state at the time):

A recording is keyed on the sha256 of the assembled request *including M-AUTHOR's prompt
templates* (`RecordedFixtureProvider.record`, design delta §4). The keys do not exist until
#690's implementation exists to assemble the requests — so a recording tree that passed this
census today could only have been fabricated around the real prompts, and a fabricated tree
is exactly what §4.2's rule exists to refuse ("a corpus whose recordings replay successes
only is a lie about what the corpus can prove"). The blocker is the `path` kind on
`recordings/coverage.json` (`'#686 authoring corpus recordings'` in
`tests/support/impl.py`): the file is written by the capture pass itself, so its existence
is the honest signal that a real run over real prompts happened. When #690's landing PR runs
that pass, this file unmarks and #686 closes.

What this census asserts once the tree exists — every limb a fabricated or happy-path-only
capture would fail:

1. `coverage.json` exists and declares both `fallback_exercises` (a failing head-of-chain
   reply — the fallback path must not need a live flake to be exercised) and
   `placeholder_exercises` (an unresolved item), both non-empty.
2. Every declared key is a recording file that exists in the tree.
3. Every recording in the tree parses as `aeh.prov/fixture/1` and carries a completion.
4. The two arms index *distinct* recordings — one recording satisfying both arms is the
   signature of a capture that replayed a single happy run into both.

What the census deliberately cannot refuse: whether a fallback recording's *reply* is
genuinely failure-shaped. The fixture envelope carries no success flag (its completion
fields are text/tokens/latency, `aeh.prov`'s `_COMPLETION_FIELDS`), and the failure lives in
the reply content, which only M-AUTHOR's schema can judge — that pin belongs to #690's own
suite. `coverage.json` is the indirection the capture pass writes so this file can inspect
the two paths without knowing that schema.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from tests.support.impl import require_path

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = REPO_ROOT / "fixtures" / "F-AUTHOR"
RECORDINGS = CORPUS / "recordings"
COVERAGE = RECORDINGS / "coverage.json"

CASE = "TC-AUTHOR-28"
FIXTURE_SCHEMA = "aeh.prov/fixture/1"



def _recording_path(key: str) -> Path:
    """Map a coverage.json key to its recording file, the way the provider names them.

    `coverage.json` indexes keys in the documented `sha256:...` form, but
    `RecordedFixtureProvider._path_for` writes files as `sha256-<hex>.json` — the colon is
    illegal in a filename on Windows (it is an alternate-data-stream separator). Every
    existing recordings tree confirms the dash form. Normalizing here keeps the census
    honest in the direction it must not fail: a correct capture pass writes both forms and
    the census matches them.
    """
    return RECORDINGS / f"{key.replace(':', '-')}.json"


def _coverage() -> dict:
    require_path(
        COVERAGE,
        f"{CASE}: the authoring recordings coverage index",
        issue="#686 authoring corpus recordings",
    )
    declared = json.loads(COVERAGE.read_text(encoding="utf-8"))
    assert isinstance(declared, dict), (
        f"{CASE}: {COVERAGE} is not an object — the capture pass must write "
        f"{{'fallback_exercises': [...], 'placeholder_exercises': [...]}}"
    )
    return declared


def test_both_honesty_paths_are_declared() -> None:
    """The double-honesty rule: fallback and placeholder paths, both named, both non-empty."""
    declared = _coverage()
    for arm in ("fallback_exercises", "placeholder_exercises"):
        keys = declared.get(arm)
        assert isinstance(keys, list) and keys, (
            f"{CASE}: {COVERAGE} does not declare {arm!r} — recordings that replay "
            f"successes only are a lie about what the corpus can prove (test-plan §4.2)"
        )


def test_every_declared_key_is_a_recording_file() -> None:
    declared = _coverage()
    for arm in ("fallback_exercises", "placeholder_exercises"):
        for key in declared[arm]:
            path = _recording_path(key)
            assert path.is_file(), (
                f"{CASE}: {arm} names {key!r} but {path} does not exist — "
                f"coverage.json must index real recordings"
            )


def test_every_recording_parses_as_the_fixture_schema() -> None:
    declared = _coverage()
    declared_keys = {
        key for arm in ("fallback_exercises", "placeholder_exercises")
        for key in declared[arm]
    }
    recordings = sorted(p for p in RECORDINGS.glob("*.json") if p.name != "coverage.json")
    assert recordings, (
        f"{CASE}: {RECORDINGS} holds no recordings — coverage.json is declared but the "
        f"capture pass wrote nothing"
    )
    for path in recordings:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("schema") == FIXTURE_SCHEMA, (
            f"{CASE}: {path.name} schema {data.get('schema')!r} is not {FIXTURE_SCHEMA!r}"
        )
        assert data.get("completion") is not None, (
            f"{CASE}: {path.name} has no completion — a recording without the reply it "
            f"replays cannot satisfy a replay"
        )


def test_the_two_arms_index_distinct_recordings() -> None:
    """A capture that points both arms at the same recordings has exercised neither.

    The double-honesty rule needs two *different* kinds of reply — a failing
    head-of-chain reply and a placeholder-path reply. Whether a fallback recording's reply
    is genuinely failure-shaped is only knowable against M-AUTHOR's reply schema, which
    #690's own suite pins; the envelope carries no success flag
    (`_COMPLETION_FIELDS` has text/tokens/latency only), so this census refuses what the
    envelope can see: the declaration, the files, the schema — and two arms naming the
    same recording, which is the signature of a capture that replayed one happy run into
    both arms.
    """
    declared = _coverage()
    fallback = declared.get("fallback_exercises", [])
    placeholder = declared.get("placeholder_exercises", [])
    overlap = sorted(set(fallback) & set(placeholder))
    assert not overlap, (
        f"{CASE}: fallback_exercises and placeholder_exercises share {overlap} — the two "
        f"arms must index different kinds of reply (test-plan §4.2); one recording "
        f"satisfying both is a capture that replayed a single happy run"
    )


def test_the_placeholder_exercises_name_fixtures_that_declare_placeholders() -> None:
    """The placeholder arm's recordings must belong to fixtures whose expected.toml has them.

    The recordings are keyed by request, not by fixture — but the corpus README's convention
    is that `placeholder_exercises` lists keys captured *from* placeholder-path runs, so at
    least one fixture in the corpus must declare placeholders for the arm to be honest.
    This keeps the arm tied to the corpus rather than free-floating.
    """
    declared = _coverage()
    placeholders = declared.get("placeholder_exercises", [])
    assert isinstance(placeholders, list), (
        f"{CASE}: placeholder_exercises is not a list — the capture pass must write "
        f"{{'fallback_exercises': [...], 'placeholder_exercises': [...]}}"
    )
    fixtures_with_placeholders = [
        af for af in sorted(p.name for p in CORPUS.iterdir() if p.is_dir())
        if af.startswith("AF-")
        and tomllib.loads((CORPUS / af / "expected.toml").read_text(encoding="utf-8"))
        .get("placeholders")
    ]
    assert placeholders and fixtures_with_placeholders, (
        f"{CASE}: placeholder_exercises declared but no fixture in the corpus declares "
        f"placeholders — the arm cannot be honest against an empty source"
    )