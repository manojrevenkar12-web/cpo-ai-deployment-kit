"""The kit: the template, the specs, the go-live gate failing when it should."""

import json

import pytest

from cpokit import settings
from cpokit.kit import ready, scaffold, spec
from cpokit.usecases import REGISTRY


@pytest.mark.parametrize("uc", settings.USE_CASES)
def test_every_spec_is_complete_and_within_the_sprint_budget(uc):
    s = spec.load(uc)
    assert not spec.missing_sections(uc)
    assert s.sprint.person_days <= settings.kit()["sprint_max_person_days"]
    assert (settings.ROOT / settings.usecase(uc)["handover"]["runbook"]).exists()
    assert uc in REGISTRY


def test_priority_orders_by_value_feasibility_and_risk():
    order = sorted(settings.USE_CASES, key=lambda u: -spec.load(u).priority())
    assert order[-1] == "tender_answers", "the riskiest, least feasible one comes last"


def test_scaffold_writes_a_complete_use_case(tmp_path):
    written = scaffold.new(
        "location_partner_statements",
        "Location partner statements",
        "partner_management",
        "Head of Partner Management",
        root=tmp_path,
    )
    assert len(written) == 3
    text = (tmp_path / "config/usecases/location_partner_statements.yaml").read_text()
    assert "person_days: 8" in text and "runbook: playbooks/runbooks/location_partner_statements.md" in text
    with pytest.raises(FileExistsError):
        scaffold.new("location_partner_statements", "x", "y", "z", root=tmp_path)


def test_the_gate_fails_when_a_threshold_is_not_met(ctx, monkeypatch):
    real = settings.usecase

    def stricter(uc):
        s = real(uc)
        if uc == "tender_answers":
            s["evals"]["thresholds"]["answer_accuracy"] = 0.999
        return s

    monkeypatch.setattr(settings, "usecase", stricter)
    r = ready.check("tender_answers", ctx)
    failed = {c["check"] for c in r["checks"] if not c["passed"]}
    assert not r["passed"] and failed == {"evals_pass"}


def test_the_gate_passes_on_the_committed_specs(ctx):
    r = ready.check("site_onboarding", ctx)
    assert r["passed"], [c for c in r["checks"] if not c["passed"]]
    assert json.dumps(r, default=str)
