"""Issue #637 (TS-150) — `M-HELP`'s rung-1/2 cases: the manuals page (TC-HELP-01), grounded and
not-found answers (TC-HELP-02), the answers-only census (TC-HELP-03) and corpus isolation
(TC-HELP-04). Operator test plan §5.6; design 1.10-delta §3.4.4.

**Written ahead of #636** (and #629's route table beneath it): every case is `writtenahead`,
keyed in `WRITTEN_AHEAD_BLOCKERS` on `help_vocabulary.BLOCKER_TARGET`, and red today on
`NotImplementedYet` naming #636 — before any store opens. The names they call are invented in
`tests/support/help_vocabulary.py`, once.

The model is the recorded QA double (operator plan §4 rule 7), replaying through
`RecordedFixtureProvider`; never a live model. Where a reply text is asserted (the action
question naming the Run start page, the student question pointing at Results) it is the double's
*scripted* text — that half proves the assistant passes prose through; the weight of each case
sits on what the assistant controls: citations, the request sweep, row counts and the log.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest

from tests.support import help_vocabulary as hv
from tests.support.help_vocabulary import get

pytestmark = [pytest.mark.integration]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _fetch_json(port: int, path: str):
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        assert response.status == 200, f"GET {path} -> {response.status}: {body[:200]!r}"
        return json.loads(body)
    finally:
        connection.close()


def _serve_manuals(data_dir: Path) -> dict[str, dict]:
    """One console start: the manuals list, then every manual, over HTTP from the real server."""
    from aeh.console import serve_console
    from aeh.store import open_store

    store = open_store(data_dir)
    server = serve_console(store=store)
    try:
        listing = _fetch_json(server.port, hv.MANUALS_ROUTE)
        listing = listing.get("manuals", listing) if isinstance(listing, dict) else listing
        served = {}
        for entry in listing:
            mid = str(get(entry, "manual_id"))
            served[mid] = _fetch_json(
                server.port, hv.MANUAL_ROUTE.format(manual_id=urllib.parse.quote(mid, safe="")))
        return served
    finally:
        server.terminate()
        store.close()


_ANCHOR_DUMP = (
    "import json, aeh.help as h\n"
    "print(json.dumps([[str(m.manual_id if hasattr(m, 'manual_id') else m['manual_id']),"
    " [str(s.anchor if hasattr(s, 'anchor') else s['anchor'])"
    " for s in (m.sections if hasattr(m, 'sections') else m['sections'])]]"
    " for m in h.load_manuals()]))\n"
)


def _anchors_in_a_fresh_process(hash_seed: str) -> list:
    env = dict(os.environ, PYTHONHASHSEED=hash_seed, PYTHONPATH=os.pathsep.join(
        [str(REPO_ROOT / "src"), str(REPO_ROOT)]))
    done = subprocess.run([sys.executable, "-c", _ANCHOR_DUMP], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


@pytest.mark.writtenahead
def test_tc_help_01_every_packaged_manual_renders_with_toc_search_and_stable_anchors(tmp_path):
    """`TC-HELP-01` / FR-HELP-01, Q-O2 (P0) — manifest equality. Two console starts over the
    packaged set: the served manuals are exactly the packaged manifest (and that manifest is the
    operator-facing set Q-O2 names); each has a TOC whose entries resolve to sections with unique
    anchors; a phrase seeded from each manual's own packaged source is found in the served manual,
    in the section it was taken from; anchors are identical across the two starts — and across two
    fresh interpreters with different hash seeds, so a per-process cache cannot make them equal.

    The in-page search *widget* is the SPA's (E6, TC-UI-06); at this rung "search finds" is the
    phrase being present, under the right anchor, in what the page is served."""
    entries = list(hv.manifest())
    manuals_dir = hv.packaged_manuals_dir()
    problems: list[str] = []

    manifest_ids = [str(get(e, "manual_id")) for e in entries]
    assert manifest_ids, "the packaged manuals manifest is empty"
    assert len(set(manifest_ids)) == len(manifest_ids), f"duplicate manual ids: {manifest_ids}"
    titles = " | ".join(str(get(e, "title")) for e in entries)
    for kind, pattern in hv.OPERATOR_MANUAL_KINDS.items():
        if not any(pattern.search(str(get(e, "title"))) for e in entries):
            problems.append(f"Q-O2: no {kind} in the packaged manifest ({titles})")

    first = _serve_manuals(tmp_path / "start-1")
    second = _serve_manuals(tmp_path / "start-2")
    if sorted(first) != sorted(manifest_ids):
        problems.append(f"served set {sorted(first)} != packaged manifest {sorted(manifest_ids)}")

    for entry in entries:
        mid = str(get(entry, "manual_id"))
        manual = first.get(mid)
        if manual is None:
            continue
        problems += hv.problems_with_manual(manual)
        raw = (manuals_dir / str(get(entry, "path"))).read_text(encoding="utf-8")
        phrase, heading = hv.seeded_phrase(raw)
        if not phrase:
            problems.append(f"{mid}: no prose line to seed a search phrase from")
            continue
        holding = [s for s in get(manual, "sections") or () if phrase in hv.norm(str(get(s, "text")))]
        if not holding:
            problems.append(f"{mid}: search for {phrase!r} (from the packaged source) finds nothing")
        elif not any(hv.norm(str(get(s, "heading"))) == hv.norm(heading) for s in holding):
            problems.append(f"{mid}: {phrase!r} is served under "
                            f"{[get(s, 'heading') for s in holding]}, not its source section {heading!r}")

    def anchors(served):
        return {mid: [str(get(s, "anchor")) for s in get(m, "sections") or ()]
                for mid, m in served.items()}

    if anchors(first) != anchors(second):
        problems.append("anchors differ between two console starts")
    if _anchors_in_a_fresh_process("1") != _anchors_in_a_fresh_process("2"):
        problems.append("anchors differ between two fresh interpreters (PYTHONHASHSEED 1 vs 2)")
    served_pairs = {(mid, a) for mid, values in anchors(first).items() for a in values}
    if served_pairs != hv.anchors_of(hv.load_manuals()):
        problems.append("the served anchors are not the anchors load_manuals() gives citations")
    assert not problems, "\n".join(problems)


@pytest.mark.writtenahead
def test_tc_help_02_a_grounded_answer_cites_the_recorded_grounding_sections(tmp_path, tmp_data_dir):
    """`TC-HELP-02(a)` / FR-HELP-02 (P0) — recorded differential. The manuals question returns
    the recorded reply with citations that (i) are non-empty, (ii) every one resolves to a real
    manual anchor, (iii) every one names a section that was *in the assembled request* — the
    model was grounded on exactly what is cited — and (iv) include a section that carries the
    grounding phrase. The log records `grounded` with those anchors."""
    manuals = hv.load_manuals()
    by_anchor = hv.sections_by_anchor(manuals)
    grounding = [k for k, s in by_anchor.items() if hv.GROUNDING_PHRASE in hv.norm(str(get(s, "text")))]
    assert grounding, (f"precondition: no packaged manual section mentions {hv.GROUNDING_PHRASE!r}, "
                       f"so {hv.QA_MANUALS_QUESTION!r} cannot be grounded — re-pick the question")

    rig = hv.build_rig(tmp_data_dir, tmp_path / "rec")
    result = rig.assistant.ask(hv.QA_MANUALS_QUESTION)

    problems = []
    if len(rig.double.calls) != 1:
        problems.append(f"expected exactly one model call, saw {len(rig.double.calls)}")
    if hv.GROUNDED_T.reply not in hv.answer_text(result):
        problems.append(f"the answer is not the recorded reply: {hv.answer_text(result)!r}")
    cited = hv.citations(result)
    if not cited:
        problems.append("a grounded answer carries no citation")
    request = hv.norm(rig.double.payloads()[0]) if rig.double.calls else ""
    for pair in cited:
        section = by_anchor.get(pair)
        if section is None:
            problems.append(f"citation {pair} resolves to no manual anchor")
        elif not hv.contains_window(request, str(get(section, "text"))):
            problems.append(f"citation {pair} names a section that was not in the model request")
    if cited and not set(cited) & set(grounding):
        problems.append(f"no citation is a section carrying {hv.GROUNDING_PHRASE!r}: {cited}")
    log = hv.read_log(rig.store)
    if not log or log[-1].get("outcome") != hv.GROUNDED:
        problems.append(f"the log does not record a grounded exchange: {log[-1:] }")
    elif hv.logged_anchors(log[-1]) != hv.cited_anchor_strings(result):
        problems.append(f"logged anchors {log[-1].get('cited_anchors')} != cited {cited}")
    assert not problems, "\n".join(problems)


@pytest.mark.writtenahead
def test_tc_help_02_b_a_no_grounding_question_gets_the_explicit_not_found_answer(tmp_path, tmp_data_dir):
    """`TC-HELP-02(b)` / FR-HELP-02 (P0). A question no manual grounds: no citation, an answer that
    says so and points at the manuals page, `not-found` in the log — and the double's recorded
    reply, a confident hallucination, never reaches the answer whether or not the model was called."""
    corpus = " ".join(hv.norm(str(get(s, "text"))) for s in hv.sections_by_anchor(hv.load_manuals()).values())
    content_words = [w for w in hv.norm(hv.NOT_FOUND_T.question).split()
                     if len(w) > 4 and w not in hv.STOPWORDS]
    assert not [w for w in content_words if f" {w} " in f" {corpus} "], (
        "precondition: the not-found question shares content words with the manuals — re-pick it")

    rig = hv.build_rig(tmp_data_dir, tmp_path / "rec")
    result = rig.assistant.ask(hv.NOT_FOUND_T.question)
    text = hv.answer_text(result)
    problems = []
    if hv.citations(result):
        problems.append(f"a not-found answer carries citations: {hv.citations(result)}")
    if hv.norm(hv.NOT_FOUND_T.reply) in hv.norm(text) or "442" in text:
        problems.append(f"the unsourced model reply reached the answer: {text!r}")
    if "manual" not in text.lower():
        problems.append(f"the not-found answer does not point at the manuals page: {text!r}")
    log = hv.read_log(rig.store)
    if not log or log[-1].get("outcome") != hv.NOT_FOUND:
        problems.append(f"the log does not record not-found: {log[-1:]}")
    assert not problems, "\n".join(problems)


@pytest.mark.writtenahead
def test_tc_help_03_one_read_only_endpoint_and_an_action_question_changes_nothing(tmp_path, tmp_data_dir):
    """`TC-HELP-03` / FR-HELP-04, CT-HELP-01 (P0) — census + row counts. (a) The assistant's only
    public operation is `ask`; the console's route table carries exactly one help route, a read
    (GET, no control row), and every manuals route is a read. (b) "Start the run for me": the
    answer names the console page (scripted reply); across every tier only the Q&A log changed,
    by exactly one row; `qa_log` gained exactly one entry."""
    rig = hv.build_rig(tmp_data_dir, tmp_path / "rec", seed=True)
    problems = []

    public = sorted(n for n in dir(rig.assistant)
                    if not n.startswith("_") and callable(getattr(rig.assistant, n)))
    if public != [hv.ASK]:
        problems.append(f"the assistant's public operations are {public}, not exactly ['ask']")
    routes = hv.route_table()
    help_routes = [r for r in routes if r[1].startswith(hv.HELP_API_PREFIX)]
    if [(m, p) for m, p, _ in help_routes] != [hv.ASK_ROUTE]:
        problems.append(f"help routes {help_routes} != exactly one {hv.ASK_ROUTE}")
    problems += [f"help route {r} writes control {r[2]!r}" for r in help_routes if r[2] is not None]
    for method, path, control in routes:
        if path.startswith(hv.MANUALS_ROUTE) and (method not in ("GET", "HEAD") or control is not None):
            problems.append(f"manuals route {method} {path} is not a read (control {control!r})")

    log_before = len(hv.read_log(rig.store))
    before = hv.settled_snapshot(rig)
    result = rig.assistant.ask(hv.ACTION_T.question)
    after = hv.settled_snapshot(rig)
    problems += hv.only_the_log_grew(hv.snapshot_diff(before, after), added=1)
    if len(hv.read_log(rig.store)) != log_before + 1:
        problems.append("qa_log did not gain exactly one entry")
    if "run start" not in hv.answer_text(result).lower():
        problems.append(f"the answer does not name the console page: {hv.answer_text(result)!r}")
    rig.store.close()
    assert not problems, "\n".join(problems)


@pytest.mark.writtenahead
def test_tc_help_04_a_student_question_reaches_the_model_with_no_student_data(tmp_path, tmp_data_dir):
    """`TC-HELP-04` / FR-HELP-03, FR-CONF-31 (P0) — sweep. Over a store seeded with a scored run
    and two roster students: "What did Zelda Quartermaine get?" is answered by pointing at the
    results screen (scripted reply); the assembled request carries none of the store's identifiers
    (cohort, package, submission ids, student refs) and Zelda's name appears only inside the
    teacher's own question; Ignatius — never mentioned — appears nowhere; and the retrieval index,
    built from the packaged manuals, holds none of those tokens either.

    Grades are not swept as numbers: a bare score collides with manual text. They cannot reach the
    request without the ids around them, which are swept. `roster.full_name` lands with Cohort
    migration 33; until then the names are seeded only as the question carries them."""
    rig = hv.build_rig(tmp_data_dir, tmp_path / "rec", seed=True)
    result = rig.assistant.ask(hv.STUDENT_T.question)
    problems = []
    if "results" not in hv.answer_text(result).lower():
        problems.append(f"the answer does not point at the results screen: {hv.answer_text(result)!r}")
    if hv.citations(result) and not all(p in hv.anchors_of(hv.load_manuals()) for p in hv.citations(result)):
        problems.append(f"a citation resolves to no manual anchor: {hv.citations(result)}")
    # No model call at all also satisfies the clause (nothing egressed); every call that IS made
    # is swept. The "results" pointer above is asserted either way.
    for index, text in enumerate(rig.double.payloads()):
        problems += [f"request {index}: {hit}" for hit in hv.sweep(text, rig.world.forbidden)]
        problems += [f"request {index}: Zelda's name outside the question"
                     for _ in hv.sweep(text, {"name": rig.world.zelda_name}, allow_in=hv.STUDENT_T.question)]

    # The index the assistant ANSWERS from, not one this test builds, is swept, and must equal
    # the manuals-only index: a store-fed index fails either half.
    index = getattr(rig.assistant, hv.ASSISTANT_INDEX, None)
    build_index = getattr(hv.help_module(), hv.BUILD_INDEX, None)
    if index is None or build_index is None:
        problems.append(f"the assistant's {hv.ASSISTANT_INDEX!r} or {hv.BUILD_INDEX} is missing: "
                        "the index is not inspectable")
    else:
        texts = [str(get(p, "text")) for p in get(index, "passages")]
        problems += [f"retrieval index: {hit}" for hit in hv.sweep(
            "\n".join(texts), {**rig.world.forbidden, "Zelda's name": rig.world.zelda_name})]
        manuals_only = sorted(str(get(p, "text"))
                              for p in get(build_index(hv.load_manuals()), "passages"))
        if sorted(texts) != manuals_only:
            problems.append("the assistant's index is not the manuals-only index")
    rig.store.close()
    assert not problems, "\n".join(problems)
