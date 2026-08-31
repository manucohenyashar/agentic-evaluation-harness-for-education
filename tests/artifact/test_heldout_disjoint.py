"""The held-out set stays held out.

Case: `TC-CONFORM-10` (test plan §5.18), `NFR-CONFORM-01`, P0, artifact assertion, rung 0.

§4.4: *"`F-FROZEN` is the held-out evaluation set and is never used during development. A
separate `F-DEV` subset of 8 submissions, drawn from the same generator but disjoint, is what
developers iterate against. `TC-CONFORM-10` asserts the two sets are disjoint by content
hash, which is the only mechanism that keeps 'held out' true after six months."*

Nothing else enforces this. Held-out-ness decays silently: someone copies a stubborn fixture
into the dev set to reproduce a bug, the conformance number quietly starts measuring training
data, and no test fails. This one does.

**Written ahead of the corpora** (issue #2, TS-01, which owns `F-FROZEN` and `F-DEV`).
Expected to fail with `NotImplementedYet` until they land. Remove the `writtenahead` marker —
not the test — when #2 closes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.support.impl import NotImplementedYet, require_path

pytestmark = pytest.mark.writtenahead

ISSUE = "#2"
FROZEN_MANIFEST = Path("fixtures/F-FROZEN/manifest.json")
DEV_MANIFEST = Path("fixtures/F-DEV/manifest.json")


def _content_hashes(manifest_path: Path, corpus: str) -> set[str]:
    """Every submission's content hash, **recomputed from the submission bytes**.

    The manifest is the artifact under assertion: `NFR-CONFORM-01` requires the fixture set to
    be content-addressed and version-pinned "so a conformance result names exactly which
    fixtures produced it".

    The declared `content_hash` is verified rather than trusted, because trusting it would
    reopen the exact leak this case exists to close. If the generator ever salts the hash with
    the submission id or filename — a natural choice, since a manifest keys by id — then the
    same bytes copied into `F-DEV` under a new name would carry a *different* declared hash
    and a disjointness check over declared values would pass. Comparing recomputed digests
    makes the assertion about content, which is what §4.4 means by "disjoint by content hash".
    """
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = data.get("submissions")
    if not entries:
        raise NotImplementedYet(
            f"{corpus} manifest at {manifest_path} declares no submissions (blocked on "
            f"{ISSUE})."
        )

    corpus_root = manifest_path.parent
    hashes: set[str] = set()
    for entry in entries:
        submission = require_path(
            corpus_root / entry["path"],
            f"{corpus} submission {entry.get('id', entry['path'])!r}",
            issue=ISSUE,
        )
        actual = hashlib.sha256(submission.read_bytes()).hexdigest()
        declared = entry["content_hash"].removeprefix("sha256:")
        assert actual == declared, (
            f"{corpus} manifest declares content_hash {declared} for {entry['path']}, but "
            f"the file hashes to {actual}. The manifest is the content-addressing "
            f"(NFR-CONFORM-01); if it can disagree with the bytes, every disjointness and "
            f"provenance claim built on it is unfounded."
        )
        hashes.add(actual)

    if len(hashes) != len(entries):
        raise AssertionError(
            f"{corpus} contains duplicate submissions by content hash: "
            f"{len(entries)} entries, {len(hashes)} distinct hashes"
        )
    return hashes


def test_tc_conform_10_frozen_and_dev_corpora_are_disjoint_by_content_hash(repo_root):
    """TC-CONFORM-10 — `F-FROZEN` and `F-DEV` share no submission.

    Oracle (§5.18): set-disjointness assertion.

    Asserted on content hash rather than on filename or id, because the failure mode is a
    *copy*: the same submission under a different name in the dev set is exactly the leak,
    and a name-based check would pass through it.
    """
    frozen_path = require_path(
        repo_root / FROZEN_MANIFEST, "F-FROZEN manifest", issue=ISSUE
    )
    dev_path = require_path(repo_root / DEV_MANIFEST, "F-DEV manifest", issue=ISSUE)

    frozen = _content_hashes(frozen_path, "F-FROZEN")
    dev = _content_hashes(dev_path, "F-DEV")

    # Composition, per FR-CONFORM-01 and §4.4 — a "disjoint" assertion over an empty dev set
    # is vacuously true, so the sizes are asserted first.
    assert 30 <= len(frozen) <= 50, (
        f"F-FROZEN must hold 30-50 submissions (FR-CONFORM-01), found {len(frozen)}"
    )
    assert len(dev) == 8, f"F-DEV is a subset of 8 submissions (§4.4), found {len(dev)}"

    overlap = frozen & dev
    assert not overlap, (
        f"{len(overlap)} submission(s) appear in both F-FROZEN and F-DEV: "
        f"{sorted(overlap)}. The held-out set is no longer held out, so every conformance "
        f"figure computed against it is measuring data the system was developed on "
        f"(NFR-CONFORM-01, test plan §4.4)."
    )
