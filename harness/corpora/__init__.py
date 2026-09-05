"""The corpora generators (TS-01, issue #2).

Test-plan §8.1 names the corpora as one of the three things that must exist before most of
the plan can be written, and it states the property that matters in one word: the corpora are
*"generated from committed scripts so they are reproducible rather than archaeological"*.

That word is the whole design of this package. A fixture corpus that was produced once, by a
script nobody kept, decays into an artifact whose provenance is a guess — and then every
number computed against it is a guess too. So:

- every corpus in `fixtures/` is emitted by `python -m harness.corpora.build`;
- the generator is seeded per corpus with a constant that lives in the module (§4.6: seeded
  per concern, never the module-global), so a rebuild reproduces the same bytes;
- `python -m harness.corpora.build --check` regenerates into a scratch directory and diffs it
  against what is committed, which is what `tests/regression/test_corpora_are_reproducible.py`
  runs. A corpus edited by hand fails that check.

**Why the output is committed rather than built on demand.** `tests/artifact/test_heldout_disjoint.py`
(TS-00) reads `fixtures/F-FROZEN/manifest.json` straight off the repo root with no generation
hook, and nothing in `scripts/test.sh` or `conftest.py` bootstraps anything before pytest
runs. Committed is therefore the only reading that works today, and it has the better failure
mode besides: the corpus a result was computed against is in the history, not in whatever the
generator happens to emit after its next edit.

`.gitattributes` pins `fixtures/**` to LF. Content addressing is over bytes, so a CRLF
checkout on Windows would otherwise change every hash in every manifest.
"""

from __future__ import annotations

from harness.corpora.manifest import (
    CORPUS_ROOT,
    Manifest,
    ManifestEntry,
    content_hash,
    read_manifest,
    write_manifest,
)

__all__ = [
    "CORPUS_ROOT",
    "Manifest",
    "ManifestEntry",
    "content_hash",
    "read_manifest",
    "write_manifest",
]
