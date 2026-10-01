"""The adversarial tier: one adversarial corpus through the real ingest ladder."""

from __future__ import annotations

from typing import Any

from harness.corpora.manifest import read_manifest

from .fixtures import _fixture_root
from .reports import AdversarialTierReport
from .divergence import _derive_units, _load_set_memo
from .backends import recorded_provider_for_fixture_set
from .suite import ConformanceSuite


def run_adversarial_tier(corpus: str, provider: Any = None) -> AdversarialTierReport:
    """Run one adversarial corpus through the conformance tier (TC-CONFORM-09).

    `F-ADV-INJ` derives the differential outcomes for every member from the declared reference
    bands — twins carry identical declarations, so the three paired properties compare equal
    (the confidence inequality holds at equality: the recorded transport cannot distinguish the
    pair, and a *lower* confidence is the live tier's honest possibility). `F-ADV-PDF` drives
    the real ingest ladder per construct through `ingest_one`; the provider is accepted but
    never called — quarantine at V0 precedes any transcription.
    """
    fixture_set = _load_set_memo(corpus)
    manifest = read_manifest(_fixture_root() / corpus / "manifest.json")
    consent_class = str(manifest.get("consent_class") or "")
    if corpus == "F-ADV-PDF":
        suite = ConformanceSuite(provider=provider or recorded_provider_for_fixture_set(corpus))
        ingest_outcomes = {
            submission.submission_id: suite.ingest_one(submission)
            for submission in fixture_set.submissions
        }
        return AdversarialTierReport(
            fixture_set_id=str(manifest["fixture_set_id"]),
            outcomes={},
            ingest_outcomes=ingest_outcomes,
            consent_class=consent_class,
        )
    bands_by_id = {
        submission.submission_id: dict(bands)
        for submission, bands in (
            (s, (fixture_set.reference_bands or {}).get(s.submission_id, {}))
            for s in fixture_set.submissions
        )
        if bands
    }
    units = _derive_units(fixture_set.submissions, bands_by_id, substituted=False)
    return AdversarialTierReport(
        fixture_set_id=str(manifest["fixture_set_id"]),
        outcomes={sid: unit for sid, (_, unit) in units.items()},
        ingest_outcomes={},
        consent_class=consent_class,
    )
