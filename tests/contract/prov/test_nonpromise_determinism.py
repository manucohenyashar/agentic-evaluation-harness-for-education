"""`TC-PROV-C16` — identical inputs are not promised to produce identical text.

Case: `TC-PROV-C16` (`CT-PROV-16`, **non-promise**, P0, rung 2 / rung 3, test plan §6.11.2
block form). Issue #25 (TS-59).

A non-promise is verified by proving **no consumer depends on it** — so the case never
asserts that output varies. It makes the unpromised thing vary and asserts every consumer
in the `Consumers` column still behaves correctly. The block form's five steps, and where
each lives:

- **Step 1** (the provider double that varies its text over byte-identical requests, with no
  caching or dedup anywhere in the module) is the §6.11.2 suite's parametrized cell:
  `test_tc_prov_c16_the_provider_half_varying_text_no_caching_no_dedup` in
  `test_ct_prov_clauses.py`, run over both live implementations under both `FR-PROV-15`
  constructions. This file does not duplicate it; it is the other four steps.
- **Steps 2–4** (the consumer sweep over `M-JUDGE`, `M-EXTRACT`, `M-CONFORM` at rung 3) need
  those modules, none of which exist yet — `src/aeh` today is conf, ingest, pkg, prov and
  store. They are the consuming stories' obligation the moment those modules land, and the
  sweep's technique is stated here so whoever lands it inherits the assertion rather than
  reinventing it: run each consumer across responses that vary in wording, whitespace and
  key order; assert verdicts stay parseable, spans stay correct, and conformance reasoning
  rests on `deterministic_at_temperature_zero` (`CT-PROV-04`, the backend's *claim*) plus
  `M-STATS`'s measurement — never on textual reproducibility. Nothing anywhere may compare
  two *generated* strings for equality, and no code path may cache or dedupe on response
  text. (The sweep's `automatable` path is this file; extend it, do not fork it.)
- **Step 5** is implementable today and runs below: no golden file in the repository holds
  generated text as an exact-match expectation **for a live tier** — and the recorded-fixture
  exemption is asserted in its constructive form: fixtures are keyed *by request*, not
  compared *as output*.

Why step 5 is a tier claim, not a content claim
-----------------------------------------------
The baselines include text a model produced — `TC-REG-01`'s canonical Markdown is assembled
from transcriptions of a fixed synthetic corpus. That is not the violation. The violation is
a golden whose *producing tier* is a live model call: such a baseline breaks when the
backend's wording changes, and whoever owns it is then invited to "regenerate until green" —
the exact failure §6.9's reviewer-and-grounds governance exists to prevent, and the same
dependence on the unpromised dimension that steps 2–4 sweep consumers for. So the assertion
below is about the tier: no baseline is produced through a live backend, no golden file
exists outside the registry that governs it, and no live-marked regression test performs an
*exact-match* golden comparison.

That last boundary is drawn precisely because the plan mandates one live-tier baseline
consumer: `TC-REG-05`'s nightly half re-runs the frozen set on the real backends and compares
**per-criterion score distributions** — aggregates, with a declared tolerance and a stated n —
against the fixture-tier baseline, where a shift under an unchanged package is *build
substitution* (`FR-CONFORM-08`), not a diff to accept. That is a statistical detector riding
on the golden, not a golden expectation of generated text, and forbidding it would outlaw the
drift alarm §6.9 exists for. What the scan below refuses is the combination that actually
breaks on wording: a `live`-marked test asserting a golden **match** (`assert_matches_golden`)
or writing one. The comparison a live tier is allowed is the statistical one, tolerance
declared, shift reported.

`RecordedFixtureProvider` fixtures are exempt by construction — the second test pins what
that exemption actually is, because "keyed by request, not compared as output" is easy to
write and easy to drift away from: a per-request store means a changed prompt *misses*
(`FixtureMissingError`) rather than being answered by a stale recording, and one recording's
removal leaves the others intact.
"""

from __future__ import annotations

import ast

import pytest

from aeh.prov import FixtureMissingError, PromptPayload, RecordedFixtureProvider, request_key
from tests.support.baselines import BASELINE_ROOT, registry
from tests.support.prov_contract import completion, model_ref, params

pytestmark = pytest.mark.contract

#: The live-backend seams, by name. A baseline producer that referenced any of these would be
#: a golden whose content depends on a live tier — the thing step 5 forbids.
LIVE_BACKEND_MARKERS = (
    "OPENROUTER_API_KEY",
    "LOCAL_INFERENCE_BASE_URL",
    "HARNESS_LIVE_BUILD_ID",
    "HARNESS_LIVE_RETENTION_CONFIRMED",
    "OPENROUTER_BASE_URL",
    "LOCAL_SERVER_BASE_URL",
)

#: The exact-match golden helpers. In a `live`-marked test, a call to one of these is a
#: generated-text expectation compared exactly against a live tier — the combination step 5
#: forbids. Statistical comparison against a baseline (a declared tolerance over aggregates)
#: is not on this list: that is `TC-REG-05`'s substitution detector, and it is allowed.
#: A hand-rolled `==` against a golden's bytes would evade any name list; what bounds it is
#: `assert_matches_golden` being the repository's only golden-comparison path (deliberately,
#: per `tests/support/baselines.py` — there is no `record_golden`), plus the governance scan
#: above closing the unregistered-artifact route.
GOLDEN_MATCH_HELPERS = ("assert_matches_golden",)


#: On-disk baseline artifacts the registry deliberately does not list as goldens, with the
#: reason each is not one — or, where the artifact IS an expectation, why C16's concern
#: (live-tier wording dependence) cannot reach it. Bounded like `KNOWN_UNIMPORTABLE` in
#: `test_import_graph.py`: a new entry here is a decision made on a PR, not a growing
#: category — and a generated-text golden must not hide in it: every entry states the tier
#: its content is produced at and who reviews a diff to it.
NON_GOLDEN_BASELINE_ARTIFACTS = {
    # TC-REG-06's reference INPUT tuples (the nine FR-ORCH-01 fields). The golden over them
    # (`work-id-reference.json`) is blocked on #57; the inputs ship ahead of it because they
    # are the run's inputs, not an expectation of any output — the exact distinction
    # CT-PROV-16 step 5 turns on.
    "TC-REG-06/work-id-reference.inputs.json",
    # TC-E2E-01's published-package manifest — an expectation, not an input, but its
    # producing tier is the journey's own RecordedFixtureProvider (request-keyed, per the
    # constructive exemption below), so no live backend's wording can move it. §6.9's
    # registry is the plan's six `TC-REG-*` producer rows and is closed by its drift test,
    # so the manifest is governed inline in the journey module instead: reviewer "The
    # package owner", grounds a schema-version bump or a declared setup-mapping change,
    # never "the model changed its mind" — and no regenerate helper exists.
    "TC-E2E-01/published-manifest.json",
}


def test_tc_prov_c16_no_baseline_holds_generated_text_as_a_live_tier_expectation(repo_root):
    """`TC-PROV-C16` step 5, registry half: every artifact under `fixtures/baselines/` is
    governed, and no golden is produced through a live tier.

    Three artifact assertions, all exact — this is a prohibition:

    1. Every on-disk artifact is either a golden named in the §6.9 registry or one of the
       bounded, declared non-golden inputs (`NON_GOLDEN_BASELINE_ARTIFACTS` above). A golden
       the registry does not govern has no reviewer and no grounds — regenerating it is
       exactly the "regenerate until green" affordance §6.9 refuses to build, arrived at
       through the filesystem instead.
    2. The registry itself names no live-backend seam.
    3. No baseline producer under `tests/regression/` — the directory every producer lives
       in — references a live-backend environment variable; and no `live`-marked test
       **anywhere in the test tree** performs an exact-match golden comparison
       (`GOLDEN_MATCH_HELPERS`). Both scans are structural — the seam scan is a source scan
       (a dormant reference is already the dependence), the helper scan is over the AST (a
       call from a live-marked body is found wherever it hides). The two scan different
       scopes on purpose: the producers' directory is where a seam reference would be a
       violation, while a live-marked golden *match* is repository-wide — a nightly in
       `tests/contract/` or `tests/integration/` could grow one as easily as a regression
       test could. (The reverse is also why the seam scan stays narrow: the live nightlies
       themselves legitimately reference the seams, so widening that half would build the
       false-positive gate the sole-egress case warns gets switched off.)
       `TC-REG-05`'s mandated statistical detector (tolerance-declared aggregates, shift
       reported as substitution) stays allowed — it is not a match.
    """
    entries = registry()
    assert entries, "the §6.9 baseline registry is empty; step 5 would be vacuous."

    governed = {golden for entry in entries.values() for golden in entry.golden}
    on_disk = {
        path.relative_to(BASELINE_ROOT).as_posix()
        for path in BASELINE_ROOT.rglob("*")
        if path.is_file() and path.name != "registry.json"
    }
    ungoverned = on_disk - governed - NON_GOLDEN_BASELINE_ARTIFACTS
    assert not ungoverned, (
        "CT-PROV-16 step 5: baseline artifacts exist outside the §6.9 registry: "
        f"{sorted(ungoverned)}. An ungoverned golden has no named reviewer and no stated "
        "grounds, so it can be regenerated until green — the exact dependence on produced "
        "output the non-promise and the registry both exist to prevent. If the artifact is "
        "an input rather than an expectation, declare it in NON_GOLDEN_BASELINE_ARTIFACTS "
        "on the PR that adds it."
    )

    registry_text = (BASELINE_ROOT / "registry.json").read_text(encoding="utf-8")
    for marker in LIVE_BACKEND_MARKERS:
        assert marker not in registry_text, (
            f"CT-PROV-16 step 5: the baseline registry references {marker!r}. A baseline "
            "produced through a live backend holds generated text as an exact-match "
            "expectation for that tier — the violation the step names."
        )

    regression_dir = repo_root / "tests" / "regression"
    # The assembled form, so this file's own literals cannot match the scan it performs.
    live_decorator = "pytest.mark." + "live"

    # The seam scan: the producers' directory. Narrowed deliberately — see the docstring.
    for path in sorted(regression_dir.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for marker in LIVE_BACKEND_MARKERS:
            assert marker not in source, (
                f"CT-PROV-16 step 5: {path.name} references {marker!r}. A baseline producer "
                "must run entirely through RecordedFixtureProvider (the recorded double is "
                "request-keyed, so its answers are the run's inputs, not expectations of a "
                "live tier)."
            )

    # The exact-match scan: the whole test tree, because the clause is repository-wide.
    for path in sorted((repo_root / "tests").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = [ast.unparse(dec) for dec in node.decorator_list]
            if not any(live_decorator in rendered for rendered in decorators):
                continue
            for call in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                assert name not in GOLDEN_MATCH_HELPERS, (
                    f"CT-PROV-16 step 5: {path.name}::{node.name} asserts an exact match "
                    f"against a golden from the live tier ({name}). A live backend's wording "
                    "is the unpromised dimension (CT-PROV-16); an exact-match expectation on "
                    "it breaks on the backend's next rewording and invites regeneration "
                    "until green. Live tiers compare statistically, with the tolerance "
                    "declared — TC-REG-05's detector is the form."
                )


def test_tc_prov_c16_the_recorded_fixture_exemption_is_request_keying(tmp_path):
    """`CT-PROV-16` step 5's exemption, asserted constructively: recorded fixtures are
    exempt *because they are keyed by request, not compared as output* — and this is what
    that difference is in behaviour.

    Three consequences of keying, each asserted against the real store:

    1. Two requests that differ in one payload field get two independent recordings — the
       key covers the assembled request (FR-PROV-10), so variation on the input side is not
       collapsed into one artifact.
    2. Removing one recording leaves the other replayable. The fixtures are not one golden
       output with a comparison against it; they are per-request answers.
    3. A request that was never recorded misses, even though recordings exist — a keyed
       lookup, not a fallback that answers from whatever is nearest. This is the half that
       makes the fast tier's "no live call in CI" a fact: a stale recording cannot pose as
       an answer to a request its backend never saw.
    """
    provider = RecordedFixtureProvider(fixture_dir=tmp_path / "fixtures")
    ref = model_ref()
    first = PromptPayload(fields=(("task", "score"), ("submission", "the first request")))
    second = PromptPayload(fields=(("task", "score"), ("submission", "the second request")))
    unrecorded = PromptPayload(fields=(("task", "score"), ("submission", "never recorded")))

    provider.record(first, ref, params(), completion(text="first answer"))

    def fixture_files() -> set:
        """The store's on-disk recordings, identified by directory state rather than by the
        store's internal layout."""
        return {path for path in (tmp_path / "fixtures").rglob("*.json")}

    first_files = fixture_files()
    assert len(first_files) == 1

    provider.record(second, ref, params(), completion(text="second answer"))
    keys = {request_key(first, ref, params()), request_key(second, ref, params())}
    assert len(keys) == 2, (
        "CT-PROV-16 step 5: two different requests produced one key. The key covers the "
        "assembled request (FR-PROV-10); collapsing a payload difference is a hash collision "
        "at best and a separator-join defect at worst."
    )

    all_files = fixture_files()
    assert len(all_files) == 2 and len({p.name for p in all_files}) == 2, (
        f"CT-PROV-16 step 5: expected one artifact per recorded request, found "
        f"{sorted(p.name for p in all_files)}. A shared artifact would be a golden output "
        "being compared, not a keyed store."
    )
    # The first request's artifact is the one file that existed before the second recording.
    first_file = next(iter(first_files))

    # (2) Removing one recording leaves the other intact.
    first_file.unlink()

    replayed = provider.complete(second, ref, params())
    assert replayed.text == "second answer", (
        "CT-PROV-16 step 5: removing one recording broke another. The exemption rests on "
        "per-request keying; shared state between recordings would make the fixture store "
        "an output golden under another name."
    )

    # (3) An unrecorded request misses; nothing answers in its place.
    with pytest.raises(FixtureMissingError):
        provider.complete(unrecorded, ref, params())
