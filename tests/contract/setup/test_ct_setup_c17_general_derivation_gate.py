"""`CT-SETUP-17` — the `general` derivation read-back is a blocking gate (`TC-SETUP-C17`, P0).

The clause: "no publish while a `general` criterion lacks confirmed derivation, and the card
shows the derived bands before confirmation." Run as the provider's clause suite over
TC-SETUP-24 (b)'s matrix (operator-requirements test plan §5.5, §6). **Breaks if** the gate
becomes advisory — so the matrix is a biconditional: pending refuses, confirmed publishes, and a
mixed draft refuses naming only the pending criterion. A blanket refusal fails the confirmed arm;
an advisory card fails the pending arm.

Written ahead of #624 (TS-145, #623): `writtenahead`, keyed to #624. The assumed setup surface is
named once, in `tests/support/setup_rubric_methods.py`. The card's BROWSER rendering (the E6 arm)
is M-UI's and is not implemented here; this suite asserts the card the module hands the console.
"""

from __future__ import annotations

import pytest

from tests.support import setup_rubric_methods as rm

pytestmark = [pytest.mark.contract]


def test_tc_setup_c17_the_card_shows_the_derived_bands_before_confirmation(tmp_data_dir):
    """Before any confirmation, the card — as returned and as read back by a resuming
    console — carries the teacher's description verbatim and exactly the derived band set, and
    says it is unconfirmed."""
    chain = rm.confirmed_chain(tmp_data_dir)
    shown = rm.derive(chain, rm.GENERAL)
    for where, record in (("returned", shown), ("read back", rm.card(chain, rm.GENERAL))):
        assert rm.field(record, "criterion_id") == rm.GENERAL, where
        assert rm.field(record, "description") == rm.DESCRIPTION, (
            f"TC-SETUP-C17: the {where} card does not show the teacher's description")
        assert rm.comparable(rm.field(record, "bands")) == rm.comparable(rm.DERIVED_BANDS), (
            f"TC-SETUP-C17: the {where} card does not show the derived bands — got "
            f"{rm.band_tuples(rm.field(record, 'bands'))}")
        assert rm.field(record, "confirmed") is False, (
            f"TC-SETUP-C17: the {where} card reads confirmed before the teacher confirmed it")


def test_tc_setup_c17_pending_derivation_refuses_publish(tmp_data_dir):
    """Pending: refused, naming the criterion; the version stays an unlocked draft."""
    chain = rm.confirmed_chain(tmp_data_dir)
    rm.derive(chain, rm.GENERAL)
    refusal = rm.publish_refusal(chain)
    rm.assert_derivation_gate(chain, refusal)
    assert rm.GENERAL in str(refusal), f"TC-SETUP-C17: refusal names no criterion: {refusal}"
    assert not rm.locked(chain)
    assert chain.catalog.draft_version() == chain.version


def test_tc_setup_c17_confirmed_derivation_publishes_the_derived_bands(tmp_data_dir):
    """Confirmed as shown: publishes, and the stored band set is the derived one — the half
    that stops a blanket refusal from satisfying the clause."""
    chain = rm.confirmed_chain(tmp_data_dir)
    rm.derive(chain, rm.GENERAL)
    rm.confirm_general(chain, rm.GENERAL)
    assert rm.field(rm.card(chain, rm.GENERAL), "confirmed") is True
    assert chain.service.publish(rm.TEACHER) == chain.version
    assert rm.locked(chain)
    stored = rm.stored_bands(chain)[rm.GENERAL]
    assert rm.comparable(stored) == rm.comparable(rm.DERIVED_BANDS)
    assert rm.criteria_rows(chain)[rm.GENERAL].get("score_method") == "general"


def test_tc_setup_c17_one_pending_of_two_refuses_naming_only_the_pending_one(tmp_data_dir):
    """Two `general` criteria, one confirmed: refused, naming the pending one and not the
    confirmed one — the gate is per criterion. Confirming the second opens it."""
    chain = rm.confirmed_chain(tmp_data_dir)
    rm.derive(chain, rm.GENERAL)
    rm.derive(chain, rm.GENERAL_2, question_id="Q3",
              replies=[rm.derivation_reply(rm.GENERAL_2, rm.DERIVED_BANDS_Q3)])
    rm.confirm_general(chain, rm.GENERAL)

    refused = rm.publish_refusal(chain)
    rm.assert_derivation_gate(chain, refused)
    refusal = str(refused)
    assert rm.GENERAL_2 in refusal, f"TC-SETUP-C17: the pending criterion is not named: {refusal}"
    # `CRIT-GEN` is a prefix of `CRIT-GEN-2`: strip the pending id before looking for it.
    assert rm.GENERAL not in refusal.replace(rm.GENERAL_2, ""), (
        f"TC-SETUP-C17: the refusal names the confirmed criterion as pending: {refusal}")
    assert not rm.locked(chain)

    rm.confirm_general(chain, rm.GENERAL_2)
    assert chain.service.publish(rm.TEACHER) == chain.version
    assert rm.locked(chain)
