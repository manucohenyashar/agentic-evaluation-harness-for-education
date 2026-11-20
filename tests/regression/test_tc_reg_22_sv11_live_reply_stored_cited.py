"""TC-REG-22 (#894): SV-11 pinned. A verbatim live judge reply that the 2026-11-13 walk refused is
now stored cited.

Traces: FR-JUDGE-40, FR-JUDGE-41 (→ TC-JUDGE-48, TC-JUDGE-49). Source:
`docs/design/statistical_validity_test_plan.md` §3.17.

**SV-11.** Under judge-prompt/3 the prompt declared `cited_spans` as `{start, end}`, the verifier
needed `text`, and every citing live reply was refused (365 of 409 in Run B).

**Departure from the plan's wording.** The plan asks for "the verbatim live Run B reply with a
mis-counted offset and a correct quote". No such reply exists: the live prompt never asked for a
quote, and none of Run A's 100 or Run B's 409 `ai_judge` replies carries `text` (counted over
`logs/ai-calls/eng7-class/2026-11-13.jsonl` in both data directories). Hand-writing one would break
the recording-honesty rule. So this case pins the verbatim Run B reply that the fix rescues
without any quote. The reply is call `843eca9f…`, the run's first judge call, for E7-001 / C1a,
replying `{"start":644,"end":671}`. Its offsets are exactly those of an extracted span the request
offered, a span that verifies and crosses no marker. FR-JUDGE-41 gives it that span's text, and
the verdict is stored cited. In the walk the same unit (work id `67dc3653…`) was struck three times
and quarantined with no verdict row.

Data: `tests/regression/data/sv11_live_citations.json`, copied verbatim from the walk's data
directories: the reply text, the request's offered evidence lines, E7-001's canonical document,
and C1a's band set. Nothing is edited.

Isolation: rung 1 on a real store (`tests/support/citation_world.py`), the live document seeded as
the submission's canonical bytes, the live offered evidence through the real extraction leg, and
the live reply recorded under the unit's request key. Of the two live offered spans, the one on
C1a's region-header bytes is left out: since #873 (FR-EXTRACT-14) the extraction leg refuses a
reply carrying it, so only the clean span the reply cites can still be offered.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from aeh.integ import clear_of_region_markup, verify_span
from aeh.store import open_store
from tests.support.citation_world import citation_world

pytestmark = pytest.mark.contract

LIVE = json.loads((Path(__file__).resolve().parent / "data" / "sv11_live_citations.json")
                  .read_text(encoding="utf-8"))["run_b_e7_001_c1a"]


def _bands() -> tuple[tuple[str, float, str], ...]:
    """C1a's band set as the live request rendered it (worst first; points as the spec gives)."""
    pairs = re.findall(r"^- ([^:\n]+): (.+)$", LIVE["bands_field"], re.M)
    assert [name for name, _ in pairs] == ["absent", "present"]
    return tuple((name, float(points), descriptor)
                 for (name, descriptor), points in zip(pairs, (0, 1)))


def test_tc_reg_22_the_live_run_b_reply_is_stored_cited(tmp_data_dir, make_fixture_provider):
    reply = json.loads(LIVE["response"])
    (cited,) = reply["cited_spans"]
    assert set(cited) == {"start", "end"}, "the live reply carries no quote (judge-prompt/3)"
    doc = LIVE["document"].encode("utf-8")
    live_offered = [{k: span[k] for k in ("start", "end", "text")}
                    for span in LIVE["offered_evidence"]]
    # The walk also offered a span inside C1a's region header (`question_id=Q1 conf=0.91 st`):
    # SV-11's second cause. Since #873 (FR-EXTRACT-14) the extraction leg refuses a reply that
    # carries it, so the live evidence that can still be offered is the clean span the reply cites.
    offered = [span for span in live_offered if clear_of_region_markup(doc, span)]
    assert len(offered) == len(live_offered) - 1, "precondition: one live span is on marker bytes"
    match = next(span for span in offered if (span["start"], span["end"]) == (cited["start"],
                                                                              cited["end"]))
    assert verify_span(doc, match) and clear_of_region_markup(doc, match), (
        "precondition: the offered span the reply copied is clean evidence")

    store = open_store(tmp_data_dir)
    try:
        world = citation_world(store, make_fixture_provider(), document=LIVE["document"],
                               criterion_id=LIVE["criterion_id"], question_id="Q1",
                               bands=_bands(), offered=offered, roster_name="E7-001")
        assert [(s["start"], s["end"]) for s in world.request.evidence] == [
            (s["start"], s["end"]) for s in offered], "precondition: the clean live evidence is offered"
        row = world.judge_and_store(LIVE["response"])  # the verbatim reply text
    finally:
        store.close()
    assert (row["band"], row["uncited"], row["reanchored"]) == ("present", 0, 0)
    assert [{k: s[k] for k in ("start", "end", "text")} for s in row["cited_spans"]] == [match]
