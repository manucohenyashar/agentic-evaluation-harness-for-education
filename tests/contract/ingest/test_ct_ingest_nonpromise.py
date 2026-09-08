"""`CT-INGEST-20` — the non-promise: transcription accuracy is not warranted
(`TC-INGEST-C20`).

Case of test plan §6.11.5; issue #49 (TS-62). Green by design — the clause is
a RESTRICTION on what the module may claim, and the shipped module claims
nothing; the case's job is to keep it that way.

The clause: **not promised** — transcription accuracy is checked by M-INTEG
against source bytes and by the operator, never asserted here; `ocr_conf` is a
signal, not a warranty; and `document.markdown` is NOT stable across
transcriber builds — `transcriber_ref` is on the row precisely because it is
not.

Asserted here, probed:

1. **The module makes the variance HONEST, not forbidden.** The same source
   bytes transcribed under two different `transcriber_ref` builds produce two
   DIFFERENT, both-plausible markdowns, and BOTH are accepted: no gate
   rejects the difference, no finding flags it, no comparison against the
   first reading happens. Each document row records its OWN build, and the
   two readings coexist — the record is "what build X read", never "the
   text".
2. **The module asserts no correctness.** A low-confidence region (conf at
   0.05) ingests `ok` with no correctness column, no verdict flag, no
   thresholded claim — the conf is recorded and nothing is concluded. (The
   flip side is disclosed G1: no aggregate lowers confidence into a status
   either — the module neither warrants nor warns.)
3. **No golden file pins `document.markdown` across builds** — the module
   cannot consult a pin (no statement in its registry reads a
   golden/baseline/fixtures path, and the source knows no golden at all), and
   the repo's golden governance agrees: the §6.9 registry's ingest-output
   baseline (`TC-REG-01`, produced by M-INGEST) names a reviewer and grounds
   that **refuse** "the model changed its mind" — a build change alone is
   never grounds to move the golden — and its producer runs on the recorded
   tier (no live-backend seam), so the golden pins the ASSEMBLY of fixed
   scripted transcripts, never a build's reading. This is the tier form the
   `CT-PROV-16` suite (`tests/contract/prov/test_nonpromise_determinism.py`)
   established for the same clause family.

Consumer halves deferred with disclosure: M-INTEG checks correctness against
source bytes (stories #73..#74, contract suite #77); M-STATS attributes
nothing to a transcript it did not scope by `transcriber_ref` (stories
#115..#118); M-EXTRACT consumes spans, never "the" text (#68..#69). What the
producer holds here is the fact they rely on: the transcript is a
per-build reading with its build recorded — variation is expected and
attributable, never a defect.
"""
from __future__ import annotations

import pytest

from aeh.ingest import Ingestor
from aeh.prov import SamplingParams
from tests.contract.ingest._doubles import (
    COHORT,
    Contract,
    ScriptedProvider,
    ThroughSanitizer,
    answer_text,
    model_ref,
    student_answer,
)

pytestmark = pytest.mark.contract

BUILD_A = "vlm@sha256:cccc"
BUILD_B = "vlm@sha256:dddd"


def test_tc_ingest_c20_a_second_builds_reading_is_accepted_and_recorded(
        tmp_data_dir):
    """`TC-INGEST-C20` (the variance is honest) — the same source bytes under
    two transcriber builds produce two different plausible markdowns, both
    accepted with `ok`, no finding, no comparison; each row records its own
    build; the content hashes differ and the readings coexist. A module that
    pinned today's output as *the* text would reject the second reading, flag
    it, or overwrite the first — any of those turns this red."""
    fx = Contract(tmp_data_dir, "c20-builds")
    fx.add_roster("gus")
    source = fx.put(b"c20 same source bytes")
    fx.script(source, {1: student_answer("gus", answer_text(
        "Q1", "the reading the first build produced"))})
    first = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "a.pdf"})
    assert first.ingest_status == "ok" and first.detail["findings"] == [], (
        f"TC-INGEST-C20: the first build's ingest was not clean: "
        f"{first.ingest_status} / {first.detail['findings']}."
    )
    doc_a = fx.documents("submission_id = :s", s=first.submission_id)[0]
    assert doc_a["transcriber_ref"] == BUILD_A, (
        f"TC-INGEST-C20: the first reading's build is "
        f"{doc_a['transcriber_ref']!r}, not {BUILD_A!r}."
    )
    # The second build re-reads the SAME source bytes and produces a different
    # — equally plausible — markdown. No golden comparison exists to refuse it.
    second_provider = ScriptedProvider()
    second_provider.texts[(source, 1)] = student_answer("gus", answer_text(
        "Q1", "the reading the second build produced"))
    fx.ingestor = Ingestor(
        fx.handle, fx.blobs, second_provider, model_ref(BUILD_B),
        SamplingParams(temperature=0.0), fx.rasterizer,
        residency=fx.residency, sanitizer=ThroughSanitizer())
    second = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "a.pdf"})
    assert second.ingest_status == "ok" and second.detail["findings"] == [], (
        f"TC-INGEST-C20: the second build's DIFFERENT reading was not "
        f"accepted cleanly: {second.ingest_status} / "
        f"{second.detail['findings']} — the module compared it against the "
        "first instead of recording it."
    )
    documents = fx.documents()
    assert len(documents) == 2, (
        f"TC-INGEST-C20: {len(documents)} document row(s) — one reading "
        "replaced the other instead of coexisting."
    )
    doc_b = fx.documents("submission_id = :s", s=second.submission_id)[0]
    assert doc_b["document_id"] != doc_a["document_id"], (
        "TC-INGEST-C20: the second build wrote into the first reading's "
        "document — the record is not per-reading."
    )
    assert doc_b["markdown"] != doc_a["markdown"], (
        "TC-INGEST-C20: the two builds produced identical markdown — the "
        "variance the clause names was not exercised (fix the fixture, not "
        "the assertion)."
    )
    assert doc_a["content_hash"] != doc_b["content_hash"], (
        "TC-INGEST-C20: different markdown hashed the same — the identity is "
        "not over the canonical markdown."
    )
    assert doc_b["transcriber_ref"] == BUILD_B, (
        f"TC-INGEST-C20: the second reading's build is "
        f"{doc_b['transcriber_ref']!r}, not {BUILD_B!r} — the variance is not "
        "attributable."
    )
    # The same source, claimed by both rows: the record is per-build readings
    # over shared bytes, never one canonical text.
    assert doc_a["source_blobs"] == doc_b["source_blobs"], (
        "TC-INGEST-C20: the two readings claim different sources — the "
        "variation must be over the SAME bytes."
    )
    # And no correctness opinion anywhere: equal gates, no verdict-shaped
    # value on either row.
    assert dict(first.gates) == dict(second.gates), (
        f"TC-INGEST-C20: the gates differ across builds {dict(first.gates)} "
        f"vs {dict(second.gates)} — a build-dependent verdict is a "
        "correctness claim."
    )
    fx.close()


def test_tc_ingest_c20_low_confidence_never_becomes_a_correctness_claim(
        tmp_data_dir):
    """`TC-INGEST-C20` (the conf is a signal, not a warranty) — a region at
    conf 0.05 ingests `ok`: the low confidence is recorded and NOTHING is
    concluded — no correctness flag, no verdict column, no thresholded claim
    anywhere on the row or the region. The flip side is disclosed G1: no
    aggregate lowers confidence into a status either — the module neither
    warrants nor warns; both are M-INTEG/M-CONSOLE's to build on the
    signal."""
    fx = Contract(tmp_data_dir, "c20-lowconf")
    fx.add_roster("gus")
    source = fx.put(b"c20 low conf pdf")
    fx.script(source, {1: student_answer("gus", answer_text(
        "Q1", "the barely legible answer", conf="0.05"))})
    report = fx.ingestor.ingest_submission(
        [source], cohort_id=COHORT, package_version="v0",
        filenames={source: "a.pdf"})
    assert report.ingest_status == "ok", (
        f"TC-INGEST-C20: conf 0.05 became a status ({report.ingest_status}) — "
        "the module thresholded the signal into a claim."
    )
    regions = fx.regions(fx.documents()[0]["document_id"])
    tagged = [row for row in regions if row["element_kind"] == "Q1"]
    assert len(tagged) == 1 and tagged[0]["ocr_conf"] is not None \
        and tagged[0]["ocr_conf"] < 0.1, (
        f"TC-INGEST-C20: the low conf was not recorded: {tagged}."
    )
    # No correctness-shaped column carries a value: the region row's fields
    # are the declared ones, and none of them is a verdict.
    correctness_shaped = [
        key for key, value in dict(tagged[0]).items()
        if key in ("verdict", "correct", "confirmed", "is_correct")]
    assert not correctness_shaped, (
        f"TC-INGEST-C20: correctness-shaped columns appeared: "
        f"{correctness_shaped} — the module started warranting."
    )
    fx.close()


#: The live-backend seams, mirrored from the `CT-PROV-16` suite
#: (`tests/contract/prov/test_nonpromise_determinism.py`, which scans this
#: repo-wide for baseline producers). Here the scan is scoped to the producer
#: of the ingest-output golden: a live transcriber build behind a golden would
#: pin one build's reading as *the* text — the exact violation this clause
#: forbids.
LIVE_SEAM_MARKERS = (
    "OPENROUTER_API_KEY",
    "LOCAL_INFERENCE_BASE_URL",
    "HARNESS_LIVE_BUILD_ID",
    "HARNESS_LIVE_RETENTION_CONFIRMED",
    "OPENROUTER_BASE_URL",
    "LOCAL_SERVER_BASE_URL",
)


def test_tc_ingest_c20_no_golden_file_pins_the_transcript(repo_root):
    """`TC-INGEST-C20` (no golden pin) — three artifact assertions:

    1. The module cannot consult a pin: no statement in its registry reads a
       golden/baseline/fixtures path, and the module source knows no golden at
       all.
    2. The §6.9 registry's ingest-output baseline (`TC-REG-01`, produced by
       M-INGEST) is governed — reviewer and grounds named — and its grounds
       REFUSE "the model changed its mind": a transcriber-build change alone is
       never grounds to move the golden. Every registered golden names both.
    3. That baseline's producer runs on the recorded tier: the regression
       producer emitting it references no live-backend seam, so the golden pins
       the ASSEMBLY of fixed scripted transcripts — never a build's reading,
       and test 1's two coexisting readings cannot be a golden failure.
    """
    from tests.contract.ingest._doubles import statement_texts
    from tests.support.baselines import registry

    # (1) The module's pin surface.
    texts = statement_texts()
    assert texts, "TC-INGEST-C20: the statement registry is empty."
    pinned = [name for name, sql in texts.items() if any(
        word in sql.lower() for word in ("golden", "baseline", "fixtures"))]
    assert not pinned, (
        f"TC-INGEST-C20: statements read golden/baseline paths: {pinned} — "
        "the module consults a pin."
    )
    module_text = (repo_root / "src" / "aeh" / "ingest.py").read_text(
        encoding="utf-8").lower()
    assert "golden" not in module_text, (
        "TC-INGEST-C20: the module source mentions a golden — a pin mechanism "
        "appeared in the transcriber's own code."
    )

    # (2) The registry half: the ingest-output golden is governed, and model
    # drift is explicitly NOT grounds.
    entries = registry()
    assert entries, "TC-INGEST-C20: the §6.9 baseline registry is empty."
    ungoverned = [entry.case_id for entry in entries.values()
                  if not entry.reviewer.strip() or not entry.grounds.strip()]
    assert not ungoverned, (
        f"TC-INGEST-C20: golden baselines without a reviewer or grounds: "
        f"{ungoverned} — a pin nobody owns."
    )
    ingest_entries = [entry for entry in entries.values()
                      if "M-INGEST" in entry.produced_by]
    assert ingest_entries, (
        "TC-INGEST-C20: no registry entry is produced by M-INGEST — the "
        "ingest-output golden the clause speaks to is unaccounted for."
    )
    for entry in ingest_entries:
        lowered = entry.grounds.lower()
        assert "never" in lowered and "model" in lowered, (
            f"TC-INGEST-C20: {entry.case_id}'s grounds accept model drift: "
            f"{entry.grounds!r} — the golden became today's transcript."
        )

    # (3) The tier half: the ingest golden's producer runs on the recorded
    # tier — no live seam behind the artifact test 1 relies on varying.
    case_ids = {entry.case_id for entry in ingest_entries}
    producers = [path for path in sorted((repo_root / "tests" / "regression")
                                         .glob("*.py"))
                 if any(case_id in path.read_text(encoding="utf-8")
                        for case_id in case_ids)]
    assert producers, (
        f"TC-INGEST-C20: no regression producer names {sorted(case_ids)} — "
        "the scan would be vacuous."
    )
    for path in producers:
        source = path.read_text(encoding="utf-8")
        for marker in LIVE_SEAM_MARKERS:
            assert marker not in source, (
                f"TC-INGEST-C20: {path.name} references {marker!r} — the "
                "ingest-output golden is produced through a live backend, so "
                "it pins one build's reading as the text."
            )
