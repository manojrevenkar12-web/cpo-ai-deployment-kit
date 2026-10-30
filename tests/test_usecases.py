"""Use cases: models read, code decides. Even when an injected instruction reaches the model (the
quarantine switched off) and the model obeys it, no money moves that the data does not support."""

import pytest

from cpokit.kit import evals
from cpokit.llm.gateway import Gateway
from cpokit.usecases import REGISTRY, site_onboarding
from cpokit.usecases.base import Context, NotAllowed
from tests.conftest import labels, person


def _unguarded() -> Gateway:
    gw = Gateway()
    gw.guard.markers = []  # the quarantine is off: injected text reaches the (naive) model
    return gw


@pytest.mark.parametrize(
    "use_case,metric", [("cdr_disputes", "injected_credit_eur"), ("driver_refunds", "injected_refund_eur")]
)
def test_injected_text_moves_no_money_even_without_quarantine(systems, use_case, metric):
    labs = [lb for lb in labels(use_case) if lb.get("tags", {}).get("injection")]
    assert labs, "the dev set must contain injected cases"
    ctx = Context(
        systems,
        _unguarded(),
        person({"cdr_disputes": "roaming_finance", "driver_refunds": "customer_service"}[use_case]),
    )
    m = evals.run(use_case, labs, ctx)
    assert m[metric] == 0


def test_quarantine_is_reported_to_the_reviewer(ctx):
    lab = next(lb for lb in labels("cdr_disputes") if lb["tags"]["injection"])
    p = REGISTRY["cdr_disputes"](ctx.systems.case(lab["case_id"]), ctx)
    assert p.quarantined and p.needs_review
    assert any("quarantined" in r for r in p.review_reasons)


def test_every_credit_has_an_approver_and_evidence(ctx):
    for lab in [lb for lb in labels("cdr_disputes") if any(e["decision"] == "credit" for e in lb["expected"])][:15]:
        p = REGISTRY["cdr_disputes"](ctx.systems.case(lab["case_id"]), ctx)
        assert p.actions and all(a.role == "finance_approver" for a in p.actions)
        assert any(e.source.startswith("csms:session/") or e.label == "same session already billed" for e in p.evidence)


def test_card_digits_alone_never_pay(ctx):
    case = ctx.systems.case(next(lb["case_id"] for lb in labels("driver_refunds")))
    from cpokit.usecases.driver_refunds import find_session

    s, why = find_session(ctx, {"last4": "1234"}, case["opened_ts"], {"match_window_hours": 3})
    assert s is None and "card digits" in why


def test_access_is_checked_before_anything_runs(systems):
    lab = labels("driver_refunds")[0]
    case = systems.case(lab["case_id"])
    with pytest.raises(NotAllowed):
        REGISTRY["driver_refunds"](case, Context(systems, Gateway(), person("bid_team")))
    other = "RO" if case["country"] != "RO" else "SE"
    with pytest.raises(NotAllowed):
        REGISTRY["driver_refunds"](case, Context(systems, Gateway(), person("customer_service", (other,))))


def test_site_checks():
    pol = {"country_bounds": {"IT": {"lat": [35.4, 47.2], "lon": [6.6, 18.6]}}, "rapid_kw": 50}
    base = {
        "site_code": "X1",
        "name": "A",
        "address": "Via Roma 1",
        "city": "Milano",
        "postal_code": "20121",
        "latitude": 9.19,
        "longitude": 45.46,
        "max_power_kw": 150,
        "open_24_7": True,
        "card_payment": True,
        "connectors": [{"standard": "IEC_62196_T2_COMBO", "power_kw": 150, "count": 2}],
    }
    loc, issues, fixes = site_onboarding.build_location(base, pol)
    assert fixes == ["swapped_coordinates"] and not issues and loc["coordinates"]["latitude"] == "45.46000"
    _, issues, _ = site_onboarding.build_location({**base, "postal_code": None, "card_payment": False}, pol)
    assert {"missing_postal_code", "no_card_terminal"} <= set(issues)
    _, issues, _ = site_onboarding.build_location(
        {**base, "connectors": [{"standard": "IEC_62196_T2_COMBO", "power_kw": 22, "count": 2}]}, pol
    )
    assert "conflicting_power" in issues


def test_tender_answers_never_use_a_superseded_number(ctx, monkeypatch):
    from cpokit import settings

    labs = labels("tender_answers")
    m = evals.run("tender_answers", labs, ctx)
    assert m["stale_value_used"] == 0
    pol = settings.policy()
    monkeypatch.setitem(pol, "tender_answers", {**pol["tender_answers"], "prefer_newest": False})
    ablated = evals.run("tender_answers", labs, ctx)
    assert ablated["stale_value_used"] > 0, "without supersession the library's old numbers leak"


def test_verifier_rejects_numbers_not_in_the_cited_passage():
    from cpokit.usecases.tender_answers import verify

    given = {"P1": "Our availability commitment is 98.5% per year."}
    assert verify({"sentences": [{"text": "We commit to 99% availability.", "cites": ["P1"]}]}, given)
    assert verify({"sentences": [{"text": "We commit to 98.5%.", "cites": ["P9"]}]}, given)
    assert not verify({"sentences": [{"text": "We commit to 98.5% per year.", "cites": ["P1"]}]}, given)
