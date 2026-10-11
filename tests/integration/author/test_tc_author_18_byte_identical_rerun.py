"""`TC-AUTHOR-18` (FR-AUTHOR-15, CT-AUTHOR-07, P0) — the byte-identical re-run (#715, the
package-authoring test plan §5.1; design delta §3.1).

Written ahead of #698: `aeh.author` does not exist yet, so the case is red until the
service lands. The file carries `writtenahead`, keyed `#698 determinism snapshots` in
`WRITTEN_AHEAD_BLOCKERS` (`symbol`, `aeh.author:AuthoringService`); the marker comes off —
never the test — when the blocker's unmark re-check passes (the registry entry's comment
holds the landing-timing disclosure and the re-key path).

Rung 1, oracle: hash equality. For each of AF-01 and AF-05 the draft runs twice into the
**same** output directory — the second run from a fresh `AuthoringService` (a re-run is a
fresh call with identical inputs, not a second call into a warm object) — and both
artifacts' SHA-256 must be identical across the runs, while an unrelated file placed in the
output directory before the first run survives both runs byte-identical. That last limb is
FR-AUTHOR-15's second sentence ("shall overwrite only its own two artifacts") and is what
distinguishes determinism from wipe-and-rewrite: a run that cleared the output directory
would produce identical hashes and still break the clause.

Non-vacuity, stated: the hashes are over artifacts assembled from **recorded** replies, so
the guards require the recordings' `coverage.json` (the `#686` registry entry's own marker)
and the run's provider-call count is asserted — a run that made no call and wrote
placeholder-only artifacts would satisfy hash equality while proving nothing about replay
determinism.

Disclosed assumption (the vocabulary's `FORCE_KWARG`, recorded there): FR-AUTHOR-22 pins
the CLI's `--force` but not the library form the same-directory re-run needs; the keyword
mirror of the flag is the smallest bet. If #697/#698 spell the library kwarg differently,
the rename is one line in `tests/support/author_vocabulary.py`. The mechanism itself is
#697's: the design pins `draft(self, documents, output_dir)` with no third parameter, so
until #697 ships the overwrite-confirmation form the second call below is this case's bet,
not a conformance claim — the `#698` registry entry's disclosure carries the re-key path
if the mechanism lands as a settings field, a confirm callback or CLI-only confirmation.
"""

from __future__ import annotations

import pytest

from tests.support.author_vocabulary import (
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    CountingProvider,
    FORCE_KWARG,
    RECORDINGS,
    af,
    chain_from_config,
    make_service,
    sha256_of,
)
from tests.support.impl import require, require_path

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

#: The story whose closure removes this file's marker (`#698 determinism snapshots` in
#: `tests/support/impl.py`). The `aeh.author` surface itself lands with #690; the registry
#: entry's comment carries that disclosure.
ISSUE = "#698"

#: The fixtures the oracle names, in the plan's order.
DETERMINISM_FIXTURES = ("AF-01", "AF-05")

#: The unrelated file the oracle places in the output directory before the first run.
NEIGHBOUR = "keep-me.txt"
NEIGHBOUR_BYTES = b"unrelated file, present before both runs\n"


def _guards(make_fixture_provider) -> tuple:
    """The require-style gate: the module surface (#698), the corpus (#686), the recordings
    and their coverage marker — the designed red names its issue, never a bare miss."""
    author = require(AUTHOR_MODULE, issue=ISSUE)
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=ISSUE)
    fixtures = {
        af_id: require_path(af(af_id), f"the {af_id} authored fixture", issue=CORPUS_ISSUE)
        for af_id in DETERMINISM_FIXTURES
    }
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    require_path(RECORDINGS / "coverage.json", "the authoring recordings' coverage marker",
                 issue=CORPUS_ISSUE)
    return author, fixtures, recordings


def test_tc_author_18_reruns_are_byte_identical_and_overwrite_only_their_two_artifacts(
        tmp_path, make_fixture_provider, network_guard):
    """AF-01 and AF-05, drafted twice each into the same directory: identical SHA-256 for
    the draft and the report across the runs, the unrelated neighbour file untouched by
    both, and no third file created or removed."""
    author, fixtures, recordings = _guards(make_fixture_provider)

    for af_id, fixture in fixtures.items():
        documents = sorted(fixture.glob("*.pdf"))
        out = tmp_path / f"out-{af_id}"
        out.mkdir()
        neighbour = out / NEIGHBOUR
        neighbour.write_bytes(NEIGHBOUR_BYTES)

        first_provider = CountingProvider(make_fixture_provider(recordings))
        first = make_service(author, chain_from_config(), first_provider).draft(
            documents=documents, output_dir=out)
        assert first_provider.calls, (
            f"{af_id}: the first run made no model call, so the hash equality below would "
            "be vacuous (the artifacts must come from the recorded replay)")
        first_hashes = {p.name: sha256_of(p) for p in out.iterdir()}

        # A re-run is a fresh call with identical inputs — fresh service, fresh provider,
        # same documents, same recordings, same output directory. The overwrite of an
        # existing draft for the same package id is forced, not confirmed (rung 1 has no
        # terminal to confirm in; the library kwarg is the vocabulary's `FORCE_KWARG` bet).
        second_provider = CountingProvider(make_fixture_provider(recordings))
        second = make_service(author, chain_from_config(), second_provider).draft(
            documents=documents, output_dir=out, **{FORCE_KWARG: True})
        assert second_provider.calls, (
            f"{af_id}: the re-run made no model call")
        second_hashes = {p.name: sha256_of(p) for p in out.iterdir()}

        assert (second.draft_path.name, second.report_path.name) == (
            first.draft_path.name, first.report_path.name), (
            f"{af_id}: the re-run named its artifacts differently")
        assert set(second_hashes) == set(first_hashes), (
            f"{af_id}: the re-run created or removed files: "
            f"{set(second_hashes) ^ set(first_hashes)} (FR-AUTHOR-15)")
        assert second_hashes[NEIGHBOUR] == first_hashes[NEIGHBOUR] == sha256_of(neighbour), (
            f"{af_id}: the unrelated file in the output directory was touched or replaced "
            "(FR-AUTHOR-15: a re-run overwrites only its own two artifacts)")
        for name in (first.draft_path.name, first.report_path.name):
            assert second_hashes[name] == first_hashes[name], (
                f"{af_id}: {name}'s SHA-256 differs across the re-run (FR-AUTHOR-15, "
                "CT-AUTHOR-07 — identical inputs and identical recordings must produce "
                "byte-identical output)")

    network_guard.assert_no_network()