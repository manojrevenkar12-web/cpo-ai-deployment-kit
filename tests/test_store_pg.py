"""PostgreSQL: row-level security by country and append-only usage events (needs CPOKIT_TEST_DATABASE_URL)."""

import os

import pytest

from cpokit import settings

psycopg = pytest.importorskip("psycopg")
URL = os.environ.get("CPOKIT_TEST_DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not URL, reason="CPOKIT_TEST_DATABASE_URL not set")]


@pytest.fixture()
def db():
    con = psycopg.connect(URL, autocommit=True)
    con.execute("drop table if exists approvals, actions, proposals, usage_events cascade")
    con.execute((settings.ROOT / "sql" / "kit.sql").read_text())
    for c in ("DE", "IT"):
        con.execute(
            "insert into proposals values (%s,%s,'driver_refunds',%s,0,'p','refund',false,'{}')",
            (f"P-{c}", f"C-{c}", c),
        )
        con.execute(
            "insert into usage_events (ts,use_case,case_id,country,user_oid,event) "
            "values (0,'driver_refunds',%s,%s,'u','accepted')",
            (f"C-{c}", c),
        )
    yield con
    con.close()


def _as_app(con, countries):
    con.execute("set role kit_app")
    con.execute("select set_config('kit.countries', %s, false)", (countries,))


def test_rows_of_other_countries_are_invisible(db):
    _as_app(db, "DE")
    assert [r[0] for r in db.execute("select country from proposals")] == ["DE"]
    assert [r[0] for r in db.execute("select country from usage_events")] == ["DE"]
    db.execute("reset role")


def test_writing_into_another_country_is_refused(db):
    _as_app(db, "DE")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("insert into proposals values ('P-X','C-X','driver_refunds','IT',0,'p','refund',false,'{}')")
    db.execute("reset role")


def test_usage_events_cannot_be_rewritten(db):
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute("update usage_events set event='rejected'")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute("delete from usage_events")


def test_approvals_work_on_postgres(db):
    from cpokit.approvals import ApprovalError, Approvals
    from cpokit.kitstore import PostgresKitStore
    from cpokit.usecases.base import Action
    from tests.conftest import person

    store = PostgresKitStore(URL)
    a = Action("refund", {"case_id": "C-DE", "session_id": "S", "amount_eur": 55.0}, role="cs_lead", amount=55.0)
    store.save_proposal(
        {
            "proposal_id": "P-PG",
            "case_id": "C-DE",
            "use_case": "driver_refunds",
            "country": "DE",
            "created_ts": 0,
            "prepared_by": "agent",
            "decision": "refund",
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
    ap = Approvals(store)
    tok = ap.approve(a.action_id, person("customer_service", roles=("cs_lead",), oid="lead"))
    ap.redeem(tok, a.action_id, a.payload)
    with pytest.raises(ApprovalError, match="already used"):
        ap.redeem(tok, a.action_id, a.payload)
