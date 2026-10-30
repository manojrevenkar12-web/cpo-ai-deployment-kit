"""The kit's re-rating is written from the billing rules, independently of the billing system it
checks; on every CDR the billing system got right, the two must agree to the cent."""

import json

from cpokit import settings
from cpokit.usecases import billing


def test_rerating_agrees_with_correct_billing(world, systems):
    truth = json.loads((settings.TRUTH / "cases.json").read_text())
    correct = [
        i["cdr_id"] for t in truth if t["use_case"] == "cdr_disputes" for i in t["items"] if i["cause"] == "no_error"
    ]
    assert len(correct) > 50
    disagreements = []
    for cdr_id in correct:
        cdr = systems.cdr(cdr_id)
        session = systems.session(cdr["session_id"].split("HUB-")[-1])
        r = billing.rerate(systems, session)
        if abs(r["total_cost_incl_vat"] - cdr["total_cost_incl_vat"]) > 0.01:
            disagreements.append((cdr_id, r["total_cost_incl_vat"], cdr["total_cost_incl_vat"]))
    assert not disagreements, disagreements[:5]


def test_peak_is_local_time(systems):
    row = systems._rows(
        "select s.* from sessions s join sites t on s.site_id=t.site_id where t.tz='Europe/London' limit 1"
    )[0]
    r = billing.rerate(systems, row)
    assert r["tz"] == "Europe/London"
