"""End to end (slow): world, gate, deployment, measurement, evaluation."""

import json

import pytest

from cpokit import settings


@pytest.mark.slow
def test_the_whole_run_passes_its_gate_and_keeps_its_promises():
    from cpokit import pipeline

    res = pipeline.run(log=lambda *_: None)
    assert res["gate"]["passed"], res["gate"]
    from cpokit.kitstore import KitStore
    from cpokit.systems.store import Systems

    systems, store = Systems(settings.SYSTEMS), KitStore(settings.KIT_DB)
    postings = systems.erp_postings()
    assert postings and all(p["approval_id"] and p["approved_by"] for p in postings)
    big = [p for p in postings if p["kind"] == "refund" and p["amount"] > 40]
    assert all(p["approved_by"].startswith("approver-") for p in big)
    impact = json.loads((settings.REPORTS / "impact.json").read_text())
    assert impact["tender_answers"].get("rollout") is None, "no pre-launch cases: no impact claimed"
    assert store.events()
