"""`TC-CALIB-10` — back-translation: a construction is evidence, a failure is not proof.

Test plan §5.17, `TC-CALIB-10` (FR-CALIB-09, Integration / rung 3).

The contract suite carries the construction half (`TC-CALIB-C08`: a constructed divergence
rejects, and is not an advisory note). What no green test carried before this file is the other
half of the precondition — "where it cannot" — and the two shapes the construction half's
fixtures do not reach:

* the **pass verdict**: every attempt fails to construct and the gate passes — with the note
  that says why the pass is weak (§6.6: *absence of evidence is not evidence the construct did
  not change*) and the `attempts` record naming every angle probed, so the pass is inspectable
  next to what was tried rather than a bare success (`GateResult`, seam 4);
* the **unavailable** modes: nothing declared, and declared-but-no-bound-transport — the gate
  never invents an adversary, and both refusals are `OffPanelUnavailable`, ending at R₀ like
  every other failure mode;
* the **reject note's fallback**: a constructed divergence whose attempt did not *name* the
  divergence does not render a literal `None` into the note — the note says the attempt did not
  name it. A note reading "…different scores (None)" is the template's blank showing, and it
  would sit in every record the gate writes.

The sessions arrive through the module's own registration seam (`_off_panel_model_ref` and the
`_OFF_PANEL_SESSIONS` registry — in this build the registration route *is* the test seam, per
the module docstring). No network, no real upstream.
"""

from __future__ import annotations

import pytest

from tests.support.impl import CALIB_MODULE, require

OFF_PANEL_ENV = "HARNESS_CALIB_OFF_PANEL_MODEL"


# --- the pass verdict ----------------------------------------------------------------------------


def test_tc_calib_10_no_construction_passes_with_the_weak_evidence_note():
    """Every attempt fails → `pass`, and the note does not overclaim (`FR-CALIB-09`).

    The verdict is the case: the gate passes on the attempts' failure, and the note says what
    that is and is not — §6.6's weak sense of preservation, not a clean bill. A pass note that
    read as "the construct is preserved" would convert an unresolved search into a quality
    claim, which is exactly the overclaim `CT-CALIB-16` exists to forbid.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "back_translate", issue="#140")

    ref = calib._off_panel_model_ref(constructs=False)
    result = calib.back_translate(r0="pkg-v1", r1="pkg-v2", off_panel=ref)

    assert result.gate == "back_translation"
    assert result.outcome == "pass", (
        f"a gate over three failed attempts returned {result.outcome!r}; with nothing "
        "constructed there is no evidence the construct changed, and the revision is not "
        "rejected (FR-CALIB-09)"
    )
    assert result.divergent_response_found is False
    assert result.advisory_only is False, (
        "the pass marked itself advisory — no outcome on this surface attaches a note to a "
        "revision that ships; advisory_only is structurally False"
    )
    assert result.revert_to is None, (
        "a passing gate recorded a revert target; revert_to is R₀ only on a refusal"
    )
    assert "absence of evidence is not evidence" in result.notes[0], (
        f"the pass note reads {result.notes[0]!r}; §6.6's honest reading — several angles "
        "probed, none found the seam, which is evidence of preservation only in the weak "
        "sense — is part of the verdict, not a footnote a consumer must supply"
    )


def test_tc_calib_10_the_pass_record_names_every_angle_probed():
    """The `attempts` record renders every angle with its outcome — the pass is inspectable.

    Three angles bound, three rendered, each as "<angle>: no construction" — so a reader of the
    result can see the search was real and where it probed. A gate that passed without showing
    its attempts would be indistinguishable from one that never probed at all, which is the
    silent-success shape seam 4 exists to prevent.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "back_translate", issue="#140")

    ref = calib._off_panel_model_ref(constructs=False)
    result = calib.back_translate(r0="pkg-v1", r1="pkg-v2", off_panel=ref)

    assert result.attempts == (
        "probing the top band's boundary: no construction",
        "probing the bottom band's boundary: no construction",
        "probing a mid-band response the clarifications touch: no construction",
    ), (
        f"the attempts record is {result.attempts!r}; the fixture bound three angles and every "
        "one must appear with its outcome, so the pass shows what was actually tried"
    )


# --- the unavailable modes -----------------------------------------------------------------------


def test_tc_calib_10_nothing_declared_is_unavailable_not_invented(monkeypatch):
    """No checker declared → `OffPanelUnavailable` — the gate never invents an adversary.

    The enumerated failure mode (`CT-CALIB-02`'s off_panel_model_unavailable): with nothing
    declared and no checker passed, the refusal names where a checker is declared
    (`CALIB_OFF_PANEL_MODEL` or its env channel) rather than reaching for some convenient model.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "back_translate", issue="#140")
    monkeypatch.delenv(OFF_PANEL_ENV, raising=False)

    with pytest.raises(calib.OffPanelUnavailable) as exc:
        calib.back_translate(r0="pkg-v1", r1="pkg-v2")
    assert OFF_PANEL_ENV in str(exc.value) or "CALIB_OFF_PANEL_MODEL" in str(exc.value), (
        f"the refusal does not name where to declare the checker ({exc.value!s}); 'no "
        "checker' without the knob name sends the operator hunting"
    )


def test_tc_calib_10_declared_but_no_bound_transport_is_also_unavailable():
    """A declared checker with no bound construction transport → `OffPanelUnavailable` too.

    The second unavailable shape: the deployment named a checker, but no construction session is
    bound for its build. The gate refuses with the same failure mode — unavailable is
    unavailable, whether nothing was declared or what was declared cannot run here — and both
    paths end at R₀ like every other failure mode (`CT-CALIB-02`).
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(
        CALIB_MODULE, "back_translate", "OffPanelModelRef", issue="#140"
    )

    never_bound = calib.OffPanelModelRef(
        provider="fixture",
        build_id="off-panel-never-bound@sha256:dead",
    )
    assert never_bound.build_key not in calib._OFF_PANEL_SESSIONS, (
        "the fixture ref collides with a bound session; the precondition is a declared "
        "checker with no transport"
    )
    with pytest.raises(calib.OffPanelUnavailable) as exc:
        calib.back_translate(r0="pkg-v1", r1="pkg-v2", off_panel=never_bound)
    assert "no construction transport is bound" in str(exc.value), (
        f"the refusal reads {exc.value!s}; the declared-but-unbound shape is the same "
        "enumerated unavailable mode, and the message must say what is missing"
    )


# --- the reject note's fallback ------------------------------------------------------------------


def test_tc_calib_10_a_divergence_without_a_note_does_not_render_none():
    """A constructed divergence whose attempt names no divergence → the note says so, in words.

    The #139 carry-forward gap: the reject note interpolates the attempt's divergence note, and
    an attempt that carries `None` used to render the literal string "None" into a record every
    downstream consumer reads. The fallback text names the gap — *the attempt did not name the
    divergence* — so the record shows the construction succeeded and its explanation is missing,
    which is a fact about the attempt, not a rendering bug.
    """
    calib = require(CALIB_MODULE, issue="#140")
    require(CALIB_MODULE, "back_translate", issue="#140")

    ref = calib._off_panel_model_ref(constructs=None)  # registered, unbound — the id is ours
    calib._OFF_PANEL_SESSIONS[ref.build_key] = calib._BackTranslationSession(
        attempts=(
            calib._ConstructionAttempt(
                angle="a response the clarified descriptor reads differently",
                response=(
                    "The student restates the criterion accurately but stops short of the "
                    "worked example: R0 bands it 1 and R1 bands it 0."
                ),
                divergence_note=None,  # the whole case: the construction named nothing
            ),
        )
    )
    result = calib.back_translate(r0="pkg-v1", r1="pkg-v2", off_panel=ref)

    assert result.outcome == "reject", (
        "a constructed divergence did not reject — the construction is evidence the construct "
        "changed regardless of how well the attempt explained itself (FR-CALIB-09)"
    )
    assert result.divergent_response_found is True
    assert result.constructed_response is not None
    assert result.revert_to == "pkg-v1", (
        "the rejection did not record the revert target R₀ (CT-CALIB-02)"
    )
    assert "the attempt did not name the divergence" in result.notes[0], (
        f"the reject note reads {result.notes[0]!r}; an attempt that constructed a divergence "
        "without naming it must produce the fallback wording, not an interpolation of None"
    )
    assert "None" not in result.notes[0], (
        f"the reject note still renders a literal None ({result.notes[0]!r}) — the template's "
        "blank shows in the record every consumer reads"
    )