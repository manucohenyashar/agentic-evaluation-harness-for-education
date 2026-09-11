"""`TC-STATS-13` — the surface-proxy analysis consumes the
ingestion-recorded confidence, closing the loop `NFR-INGEST-07` opens.

Test plan §5.16 (`TC-STATS-13`), issue #120 (TS-43). Traces to `FR-STATS-07`
and `NFR-INGEST-07`. The plan's row: *"Per-region OCR confidence from a real
ingest. The surface-proxy analysis actually consumes the ingestion-recorded
confidence, closing the loop `NFR-INGEST-07` opens."* Integration assertion,
P1 — the consumer half `TC-INGEST-43`'s F5 deferral named:

- **the loop's producer half** is the ingest suite's (`TC-INGEST-43`): a real
  `Ingestor` run over scripted scans records per-region `ocr_conf` into the
  durable store, and the join (`submission.student_ref` ×
  `document_region.ocr_conf`) is recorded in a form the analysis can consume;
- **the consumer half is this file**: the recorded join is read back, the
  OCR-quality correlation is computed **from the recorded rows** (the test's
  own arithmetic, not a call into the module — the pipeline's computation,
  `M-STATS`'s interpretation), and the declared channel drives
  `surface_proxies` to the flag. The confidences are the ones the ingest
  recorded — one region per paper, so the recorded value is the scripted one
  exactly, including the marginal paper's 0.3, below the 0.70 floor;
- **the discriminating control**: the same recorded confidences paired
  against the *wrong* students' bands produce a different correlation, below
  the threshold, and no flag — detection reads the recorded *pairing*, not
  the presence of OCR numbers. The labels for the two criteria carry the
  same band population; only which student's recorded confidence each band
  is paired with differs.

The planted spread is affine (confs 0.9/0.7/0.5/0.3 against bands
4/3/2/1), so the tracking criterion's Pearson r is exactly 1 — a derivation
the test asserts before leaning on it. The floor's own boundary (0.7 exactly
is not `low_confidence_ocr`) is `TC-INGEST-43`'s pinned discipline; here it
only keeps the second paper's status `ok` so every submission stays
available and the loop's population is not quarantined.

Isolation: rung 2 for the ingest half (real `Ingestor`, real store rows);
rung 0 for the analysis half (the labels and channel in memory through
`build_stats`, the declared pattern — `open_stats` carries no correlations
channel). No provider is reachable (`network_guard` is autouse and each
case asserts it); the ingest runs against the scripted doubles.
"""

from __future__ import annotations

import pytest

from aeh.conf import ModelRef
from aeh.ingest import (
    Ingestor,
    PageImage,
    PdfSanitizer,
    ResidencySlot,
    SanitizeResult,
)
from aeh.prov import Completion, SamplingParams
from aeh.store import open_store
from tests.support import broken_stats_fixtures as broken
from tests.support.impl import STATS_MODULE, require

pytestmark = pytest.mark.integration

COHORT = "coh-13"

#: The four students and their papers' scripted transcription confidences —
#: legible to marginal, spanning the 0.70 floor (the ladder's recorded
#: outcome for the below-floor ones is `low_confidence_ocr`, available; the
#: exactly-at paper stays `ok`).
STUDENTS = ("hana-w", "ivar-k", "noor-t", "bram-c")
SCRIPTED_CONF = {"hana-w": 0.9, "ivar-k": 0.7, "noor-t": 0.5, "bram-c": 0.3}

#: The planted assignment: each student's band tracks *their own* recorded
#: confidence — affine in it (band = 5·conf − 0.5), so the tracking
#: correlation is exactly 1.0.
TRACKING_BANDS = {"hana-w": 4, "ivar-k": 3, "noor-t": 2, "bram-c": 1}
#: The scramble: each student's band paired with the *previous* student's
#: recorded confidence — the same four recorded values, none with its own
#: band. Hand-computed: confs (0.3, 0.9, 0.7, 0.5) against bands (4, 3, 2, 1)
#: is cov = −0.2 over σx·σy = 1.0 → r = −0.2, below the threshold.

TRACKING_CRITERION = "C-01"
SCRAMBLED_CRITERION = "C-02"
FEATURE = "ocr_quality_score"


# --- the ingest fixture (the ladder's pattern, trimmed to the loop's needs) ---------------------

class ThroughSanitizer(PdfSanitizer):
    """The fast-tier sanitizer double: no constructs, the bytes pass through."""

    def sanitize(self, pdf_bytes, *, strip=True, max_decompressed_bytes=None,
                 max_embedded_objects=None, deadline=None):
        return SanitizeResult(pdf_bytes=pdf_bytes)


class ScriptedRasterizer:
    """A rasterizer double: one page per source, no text layer (the
    transcription is the provider's script)."""

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        return [PageImage(page_no=1, png=b"page-one", width_px=1000, height_px=1400)]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        return b"crop"

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        return ""


class ScriptedProvider:
    """A provider double keyed per (source blob, page): the scripted
    transcript, one deterministic `Completion` per call."""

    def __init__(self) -> None:
        self.texts: dict = {}

    def complete(self, prompt, model_ref, params) -> Completion:
        fields = dict(prompt.fields)
        key = (fields["source_blob_hash"], int(fields["page_no"]))
        text = self.texts.get(key, "plain page")
        return Completion(text=text, tokens_in=1, tokens_out=1, latency_ms=1,
                          resolved_build=model_ref.build_id,
                          cached_prefix_tokens=0, cost=None)


class _Fixture:
    """One fresh store, cohort, blob dir and ingestor over them — the ingest
    suite's fixture (`test_ingest_telemetry_and_medium.py`), trimmed to what
    the recorded-confidence loop needs."""

    def __init__(self, tmp_data_dir) -> None:
        # The store's tier migration chains are concatenated at import time
        # by the modules that own the schema they add (CLAUDE.md): this
        # fixture's open must not be the first open in a process that skipped
        # the imports (the same completion `open_stats` does for its own).
        import aeh.agg  # noqa: F401
        import aeh.det  # noqa: F401
        import aeh.extract  # noqa: F401
        import aeh.grade  # noqa: F401
        import aeh.integ  # noqa: F401
        import aeh.judge  # noqa: F401
        import aeh.orch  # noqa: F401
        import aeh.pkg  # noqa: F401
        import aeh.review  # noqa: F401
        import aeh.synth  # noqa: F401

        self.root = tmp_data_dir / "stats-13-recorded-conf"
        self.store = open_store(self.root)
        self.blobs = self.store.blobs()
        self.cohort_id = COHORT
        self.handle = self.store.cohort(COHORT)
        with self.handle.transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO cohort (cohort_id, consent_class, "
                       "created_at) VALUES (:c, 'synthetic', 'x')", c=COHORT)
        self.rasterizer = ScriptedRasterizer()
        self.provider = ScriptedProvider()
        slot = ResidencySlot.for_policy(("transcriber",))
        self.ingestor = Ingestor(
            self.handle, self.blobs, self.provider,
            ModelRef(role="transcriber", provider="local",
                     build_id="vlm@sha256:bbbb", quantization="q4"),
            SamplingParams(temperature=0.0),
            self.rasterizer, residency=slot, sanitizer=ThroughSanitizer(),
        )

    def ingest_paper(self, ref: str) -> None:
        """One roster'd student's one-page paper, transcribed at their
        scripted confidence."""
        source = self.blobs.put(f"scan-{ref}".encode())
        self.provider.texts[(source, 1)] = (
            f"Student: {ref}\n"
            "<!-- region: kind=transcribed_text question_id=Q1 state=present "
            f"conf={SCRIPTED_CONF[ref]} -->\n"
            f"the answer from {ref}, written out\n"
            "<!-- /region -->"
        )
        self.ingestor.ingest_submission([source], cohort_id=self.cohort_id,
                                        package_version="v0",
                                        filenames={source: "scan-01.md"})


def _ingest_cohort(tmp_data_dir):
    """The real ingest: four papers, roster'd, transcribed, recorded."""
    fixture = _Fixture(tmp_data_dir)
    with fixture.handle.transaction() as tx:
        for ref in STUDENTS:
            tx.execute("INSERT INTO roster (cohort_id, student_ref) "
                       "VALUES (:c, :r)", c=COHORT, r=ref)
    for ref in STUDENTS:
        fixture.ingest_paper(ref)
    return fixture


def _recorded_conf_by_ref(handle) -> dict[str, float]:
    """The producer join the analysis consumes, read back: per student ref,
    the mean of their regions' recorded `ocr_conf` — with the loop's
    prerequisite asserted (every region carried a reading)."""
    rows = handle.query(
        "SELECT s.student_ref, r.ocr_conf "
        "FROM submission s "
        "JOIN document d ON d.submission_id = s.submission_id "
        "JOIN document_region r ON r.document_id = d.document_id "
        "WHERE s.cohort_id = :c", c=COHORT)
    confs: dict[str, list[float]] = {}
    for row in rows:
        assert row["ocr_conf"] is not None, (
            f"the region for {row['student_ref']!r} recorded no OCR "
            "confidence; the consumer loop's prerequisite is that the "
            "recorded join carries a reading per region (the producer half, "
            "TC-INGEST-43) — nothing to consume is not a finding"
        )
        confs.setdefault(row["student_ref"], []).append(row["ocr_conf"])
    return {ref: sum(values) / len(values) for ref, values in confs.items()}


def _pearson(xs, ys) -> float:
    """The test's own correlation — deliberately an independent
    implementation, not a call into the module (the pipeline's computation
    is the pipeline's, and this file plays it)."""
    count = len(xs)
    mean_x = sum(xs) / count
    mean_y = sum(ys) / count
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    return cov / ((var_x * var_y) ** 0.5)


def _report(channel):
    """The analysis over the declared channel — the loop's consumer call,
    over the blind judged labels the scores came from (rung 0's in-memory
    shape; `open_stats` carries no correlations channel to combine)."""
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(
        labels=[
            broken.Label(
                label_id=f"conf-{criterion}-{ref}",
                criterion_id=criterion,
                band=TRACKING_BANDS[ref],
                teacher_band=3,
            )
            for criterion in (TRACKING_CRITERION, SCRAMBLED_CRITERION)
            for ref in STUDENTS
        ],
        scoring_models={
            TRACKING_CRITERION: "atomic",
            SCRAMBLED_CRITERION: "atomic",
        },
        band_counts={TRACKING_CRITERION: 4, SCRAMBLED_CRITERION: 4},
        surface_correlations=channel,
    )
    return stats, stats.surface_proxies()


# --- the loop closes: recorded confidence → consumed --------------------------------------------


def test_tc_stats_13_the_analysis_consumes_the_ingestion_recorded_confidence(
    tmp_data_dir, network_guard
):
    """The recorded join drives the flag: real ingest → recorded rows →
    channel → `surface_proxy_flags`.

    The tracking criterion's bands are affine in each student's own recorded
    confidence, so the correlation computed from the recorded rows is exactly
    1 — flagged. The stored flag is the derived value verbatim: the record
    carries the pipeline's measurement, not a re-rounded one (the
    verbatim-measured-rate discipline `TC-JUDGE-C17`'s limb 3 fixed)."""
    fixture = _ingest_cohort(tmp_data_dir)
    try:
        recorded = _recorded_conf_by_ref(fixture.handle)
        assert recorded == {ref: SCRIPTED_CONF[ref] for ref in STUDENTS}, (
            f"the recorded join read back {recorded!r}; the loop's input is "
            "the ingest's own recorded confidence — one region per paper, so "
            "the recorded value is the scripted one exactly, marginal paper "
            "included"
        )

        tracking_r = _pearson(
            [recorded[ref] for ref in STUDENTS],
            [TRACKING_BANDS[ref] for ref in STUDENTS],
        )
        assert tracking_r == pytest.approx(1.0), (
            f"the derivation over the recorded rows computed r={tracking_r!r}; "
            "bands affine in recorded confidence is a perfect correlation, and "
            "a derivation that does not land on 1 is pairing against the "
            "wrong rows"
        )

        stats, report = _report(
            {TRACKING_CRITERION: {FEATURE: tracking_r}},
        )

        assert report.n == 2 * len(STUDENTS), (
            "the report's n is the labelled population's, not the four "
            "papers' regions — the correlations are about the labels the "
            "scores came from"
        )
        assert report.surface_proxy_flags == {
            TRACKING_CRITERION: {FEATURE: tracking_r},
        }, (
            f"the flags were {report.surface_proxy_flags!r}; the correlation "
            "derived from the ingestion-recorded confidences reaches the "
            "declared threshold and the flag carries it verbatim — the loop "
            "NFR-INGEST-07 opens is closed here (FR-STATS-07, TC-STATS-13)"
        )
        assert FEATURE in report.captured_features, (
            "the recorded channel's coverage did not reach the disclosure; "
            "captured_features is what the analysis can say the regression "
            "measured"
        )
        assert require(STATS_MODULE, "SURFACE_PROXY_ALERT", issue="#117") in [
            alert.name for alert in stats.alerts()
        ], (
            "the recorded-confidence finding did not fire the surface-proxy "
            "alert — the detector that sees a score tracking a surface "
            "feature, of which OCR quality is the equity direction "
            "NFR-INGEST-07 names"
        )
        network_guard.assert_no_network()
    finally:
        fixture.store.close()


# --- the discriminating control: the pairing is what detection reads ---------------------------


def test_tc_stats_13_the_same_recorded_confs_scrambled_across_students_do_not_flag(
    tmp_data_dir, network_guard
):
    """The same recorded confidences paired against the wrong students'
    bands: no flag.

    Detection that fired on the mere presence of OCR numbers would flag
    either pairing — the loop would close on any store noise. The scramble
    pairs every band with a different student's recorded confidence; the
    derived correlation drops below the threshold and the report is silent
    on the scrambled criterion while still disclosing its (below-threshold)
    value. The recorded *pairing* is what the analysis consumed in the
    planted case — not the feature's presence in the channel."""
    fixture = _ingest_cohort(tmp_data_dir)
    try:
        recorded = _recorded_conf_by_ref(fixture.handle)

        # The mispairing: each student's own band against the *previous*
        # student's recorded confidence — every band off its own paper.
        shifted_confs = [
            recorded[STUDENTS[(index - 1) % len(STUDENTS)]]
            for index in range(len(STUDENTS))
        ]
        scrambled_r = _pearson(
            shifted_confs,
            [TRACKING_BANDS[ref] for ref in STUDENTS],
        )
        assert scrambled_r == pytest.approx(-0.2), (
            f"the scrambled pairing computed r={scrambled_r!r}; the same "
            "recorded confidences against the wrong students' bands is a "
            "weak negative — a derivation landing elsewhere is not pairing "
            "the recorded rows the way this control names"
        )

        _stats, report = _report(
            {SCRAMBLED_CRITERION: {FEATURE: scrambled_r}},
        )

        assert report.surface_proxy_flags == {}, (
            f"the scrambled pairing flagged {report.surface_proxy_flags!r}; "
            f"its derived correlation ({scrambled_r:.3f}) is below the "
            "declared threshold — a flag here is the detector firing on the "
            "presence of OCR numbers rather than on the recorded pairing, "
            "and the planted case would mean nothing (FR-STATS-07)"
        )
        assert report.correlations[SCRAMBLED_CRITERION][FEATURE] == pytest.approx(
            scrambled_r
        ), (
            "the below-threshold value vanished from the disclosure; the "
            "flags are the decision, the correlations are the measurement"
        )
        network_guard.assert_no_network()
    finally:
        fixture.store.close()