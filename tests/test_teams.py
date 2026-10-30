"""Teams: approvals from the Adaptive Card go through the same role and four-eyes checks."""

from cpokit.agents.cards import approval_card
from cpokit.agents.teams import TeamsDesk
from cpokit.llm.gateway import Gateway
from cpokit.usecases import REGISTRY
from cpokit.usecases.base import Context
from tests.conftest import labels, person


def _action(systems, store):
    lab = next(lb for lb in labels("cdr_disputes") if any(e["decision"] == "credit" for e in lb["expected"]))
    p = REGISTRY["cdr_disputes"](
        systems.case(lab["case_id"]), Context(systems, Gateway(), person("roaming_finance", oid="prep"))
    )
    d = p.to_dict()
    store.save_proposal(d)
    return d, d["actions"][0]


def test_card_shows_amount_role_and_evidence(systems, store):
    d, a = _action(systems, store)
    card = approval_card(a, d)
    facts = {f["title"]: f["value"] for f in card["body"][1]["facts"]}
    assert facts["Amount"].endswith("EUR") and facts["Approver role"] == "finance_approver"
    assert [x["verb"] for x in card["actions"]] == ["approve", "reject"]


def test_only_the_role_can_approve_from_teams(systems, store):
    d, a = _action(systems, store)
    people = {
        "aad-prep": person("roaming_finance", oid="prep"),
        "aad-boss": person("roaming_finance", roles=("finance_approver",), oid="boss"),
    }
    desk = TeamsDesk(systems, store, people.get)
    refused = desk.on_card_action("aad-prep", "approve", {"action_id": a["action_id"]})
    assert "Not approved" in refused["body"][0]["text"]
    ok = desk.on_card_action("aad-boss", "approve", {"action_id": a["action_id"]})
    assert ok["_approval_token"] and "Approved" in ok["body"][0]["text"]
    unknown = desk.on_card_action("aad-nobody", "approve", {"action_id": a["action_id"]})
    assert "not set up" in unknown["body"][0]["text"]


def test_the_teams_app_wires_to_the_agents_sdk(systems, store):
    from microsoft_agents.hosting.core import AgentApplication

    from cpokit.agents.teams import create_app, sdk_config

    app, adapter = create_app(
        TeamsDesk(systems, store, lambda _: None), sdk_config("00000000-0000-0000-0000-000000000000", "t", "x")
    )
    assert isinstance(app, AgentApplication) and adapter is not None
