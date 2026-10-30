"""Approval tokens: role, four eyes, bound to the payload, single use, expiry."""

import pytest

from cpokit.approvals import ApprovalError, Approvals
from cpokit.usecases.base import Action
from tests.conftest import person


def _proposal(store, prepared_by="prep", country="DE", role="finance_approver"):
    a = Action("credit_note", {"case_id": "C1", "cdr_id": "CDR-1", "amount_eur": 12.4}, role=role, amount=12.4)
    store.save_proposal(
        {
            "proposal_id": "P1",
            "case_id": "C1",
            "use_case": "cdr_disputes",
            "country": country,
            "created_ts": 0,
            "prepared_by": prepared_by,
            "decision": "credit",
            "needs_review": False,
            "actions": [
                {
                    "action_id": a.action_id,
                    "kind": a.kind,
                    "amount": a.amount,
                    "payload": a.payload,
                    "payload_hash": a.payload_hash,
                    "role": a.role,
                }
            ],
        }
    )
    return a


def test_role_is_required(store):
    a = _proposal(store)
    with pytest.raises(ApprovalError, match="role"):
        Approvals(store).approve(a.action_id, person("roaming_finance", oid="x"))


def test_four_eyes(store):
    a = _proposal(store, prepared_by="boss")
    with pytest.raises(ApprovalError, match="prepared"):
        Approvals(store).approve(a.action_id, person("roaming_finance", roles=("finance_approver",), oid="boss"))


def test_country_scope_of_the_approver(store):
    a = _proposal(store, country="IT", role="cs_lead")
    with pytest.raises(ApprovalError, match="countries"):
        Approvals(store).approve(a.action_id, person("customer_service", ("DE",), ("cs_lead",), oid="lead"))


def test_token_is_bound_to_payload_single_use_and_expires(store):
    clock = {"t": 1000}
    ap = Approvals(store, now=lambda: clock["t"])
    a = _proposal(store)
    tok = ap.approve(a.action_id, person("roaming_finance", roles=("finance_approver",), oid="ok"))
    with pytest.raises(ApprovalError, match="differs"):
        ap.redeem(tok, a.action_id, {**a.payload, "amount_eur": 124.0})
    with pytest.raises(ApprovalError, match="another action"):
        ap.redeem(tok, "ACT-other", a.payload)
    clock["t"] += 31 * 60
    with pytest.raises(ApprovalError, match="expired"):
        ap.redeem(tok, a.action_id, a.payload)
    clock["t"] = 1000
    ap.redeem(tok, a.action_id, a.payload)
    with pytest.raises(ApprovalError, match="already used"):
        ap.redeem(tok, a.action_id, a.payload)


def test_a_forged_token_is_refused(store):
    a = _proposal(store)
    tok = Approvals(store).approve(a.action_id, person("roaming_finance", roles=("finance_approver",), oid="ok"))
    raw, sig = tok.split(".")
    with pytest.raises(ApprovalError, match="signature"):
        Approvals(store).redeem(f"{raw}.{sig[::-1]}", a.action_id, a.payload)


def test_usage_events_are_append_only(store):
    import sqlite3

    store.event(1, "cdr_disputes", "C1", "DE", "u", "accepted")
    store.commit()
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.db.execute("update usage_events set event='rejected'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.db.execute("delete from usage_events")
