"""Controls for `console_vocabulary`'s four rules.

Every rule in this suite is a claim detector, and a claim detector fails in two directions. TS-74
shipped one that rejected the disclaimer its own clause required; TS-57 shipped one whose positive
control asserted only that *something* was flagged, and four of its six rules were dead. So each
rule here gets a **pair**: the copy a correct implementation renders, which must pass, and the copy
the clause forbids, which must be caught by name.

The "correct" fixtures are deliberately hard cases rather than empty strings — a narrative full of
numerals, an audit page that renders `finalized_by` and says what it is not. A rule that only
survives bland input has not been tested against the thing it will actually run over.
"""

from __future__ import annotations

# --- FR-CONSOLE-15: narrative before the mark, and no score claim in it ---------------------------

#: The narrative a correct implementation renders. **Full of numerals**, because that is what an
#: evidence-grounded narrative looks like: it cites question numbers, line numbers and quantities
#: out of the student's own work. A detector that condemns digits condemns this.
CORRECT_NARRATIVE = (
    "In Question 4, the derivation on line 12 substitutes 9.8 m/s^2 without stating the "
    "assumption it rests on. The answer to part (b) reaches 240 J by a route the working does "
    "not show. Two of the three required steps appear; the third is referenced but not carried "
    "out."
)

#: The same narrative with a score claim in it — the mark, stated in the place the clause reserves
#: for evidence.
NARRATIVE_WITH_A_SCORE_CLAIM = (
    "In Question 4, the derivation on line 12 substitutes 9.8 m/s^2 without stating the "
    "assumption it rests on. This scored 7 out of 10."
)

#: And with an overall-quality claim — the other half of the prohibition, and the one that reads
#: most like helpful copy.
NARRATIVE_WITH_AN_OVERALL_CLAIM = (
    "Overall this is excellent work. The derivation on line 12 omits its assumption."
)

#: A narrative naming a band. `band` is scoring vocabulary and the numeral is a criterion index,
#: so this is the near-miss that decides whether the rule reads context or counts digits.
NARRATIVE_NAMING_A_BAND = "Criterion 3 was placed in the met band by two of the three judges."

# --- CT-CONSOLE-13's DOM order ---------------------------------------------------------------------

#: A review item rendered correctly: group actions above per-item actions, narrative above the mark.
#:
#: Carries **two** traps for the ordering reader, both of them ordinary markup rather than
#: contrivances, and each one caught a real bug in `dom_order`:
#:
#: * `data-contains="mark narrative"` on the wrapper *enclosing* the narrative. A `str.find` check
#:   reports the mark first; so did the first version of `dom_order`, which read every attribute —
#:   and the test that was supposed to prove it was not fooled passed because both markers landed
#:   at the wrapper in the order they were asked for.
#: * `class="review-item mark-and-narrative-panel"`. Substring matching inside an identifying
#:   attribute registers both markers here too, which is why matching is by token.
CORRECT_REVIEW_ITEM_HTML = """
<section data-role="group-actions"><button>Accept all 12</button></section>
<article data-role="review-item" class="review-item mark-and-narrative-panel"
         data-contains="mark narrative">
  <div class="mark-summary"><span>Reviewed</span></div>
  <div data-role="narrative"><p>The derivation on line 12 omits its assumption.</p></div>
  <div data-role="mark"><select name="band"><option>met</option></select></div>
  <section data-role="item-actions"><button>Skip</button></section>
</article>
"""

#: A correct review item whose **mark** renders its points, as a rollup-style item does.
#:
#: The narrative is unchanged and clean; the mark carries "8 of 10 points", which is a numeral in
#: scoring company by definition — that is what a mark is. Run over the whole page, the narrative
#: rule condemns this correct item. Run over the narrative element, it passes. That difference is
#: the entire reason `CT-CONSOLE-13` slices before it sweeps, and this fixture is what proves the
#: slice is load-bearing rather than decoration.
REVIEW_ITEM_WHOSE_MARK_TRIPS_THE_RULE = """
<article data-role="review-item">
  <div data-role="narrative"><p>The derivation on line 12 omits its assumption.</p></div>
  <div data-role="mark"><span>8 of 10 points</span></div>
</article>
"""

#: The same item with the mark rendered first — read as the judgment, with the narrative below it
#: as justification. Functionally identical, and the thing the clause exists to forbid.
MARK_BEFORE_NARRATIVE_HTML = """
<section data-role="group-actions"><button>Accept all 12</button></section>
<article data-role="review-item">
  <div data-role="mark"><select name="band"><option>met</option></select></div>
  <div data-role="narrative"><p>The derivation on line 12 omits its assumption.</p></div>
</article>
"""

#: Per-item actions above the group action — `FR-CONSOLE-14`'s inversion.
ITEM_ACTIONS_ABOVE_GROUP_HTML = """
<section data-role="item-actions"><button>Skip</button></section>
<section data-role="group-actions"><button>Accept all 12</button></section>
"""

# --- CT-CONSOLE-23: the audit surface ----------------------------------------------------------------

#: What a correct audit surface renders. It **does** show `finalized_by` — it has to, the audit
#: record exists — and it says what that string is not. A sweep that forbade the field outright
#: would fail this, which is the whole reason the rule filters negations.
HONEST_AUDIT_SURFACE = (
    "Finalized by: r.mensah. This is a self-declared actor string supplied on the form and is not "
    "an authenticated identity; the console has no accounts and does not verify who acted."
)

#: The same surface presenting the string as proof. In a dispute this is a false claim (RISK-12).
DISHONEST_AUDIT_SURFACE = (
    "Finalized by r.mensah, the authenticated user for this action. Signed in as r.mensah at "
    "09:14. Identity verified."
)

# --- CT-CONSOLE-24: visible degradation ---------------------------------------------------------------

#: A page that renders the non-English text and says nothing about it. Not mojibake, not an error —
#: and exactly the silent degradation the clause is about, which is why "no mojibake present"
#: cannot be the predicate.
SILENTLY_DEGRADED_RENDERING = "<p>المدرسة الثانوية — إجابة الطالب</p>"

#: A page that names the limitation. `NFR-CONSOLE-07` calls the limitation deliberate; this is what
#: deliberate looks like from the operator's side.
HONESTLY_DEGRADED_RENDERING = (
    "<p>This submission contains right-to-left text. The MVP console renders English, "
    "left-to-right only; this content is shown unstyled and may be misordered.</p>"
)

#: Mojibake, which the clause forbids whatever else is on the page.
MOJIBAKE_RENDERING = "<p>Ã©lÃ¨ve: rÃ©ponse Ã  la question</p>"
