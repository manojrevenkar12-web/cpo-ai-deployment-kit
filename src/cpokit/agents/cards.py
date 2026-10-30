"""Adaptive Cards for Teams: an approval request with the evidence, and Approve / Reject buttons
that call the API (which checks the approver's role before issuing a token)."""

from __future__ import annotations

from typing import Any

SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"


def approval_card(action: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    amount = action.get("amount")
    facts = [
        {"title": "Case", "value": str(proposal.get("case_id", action.get("case_id", "")))},
        {"title": "Action", "value": action["kind"].replace("_", " ")},
        {"title": "Approver role", "value": str(action.get("role") or "none")},
    ]
    if amount is not None:
        facts.insert(2, {"title": "Amount", "value": f"{amount:.2f} EUR"})
    evidence = [
        {"type": "TextBlock", "text": f"{e['label']}: {e['value']}", "wrap": True, "size": "Small", "isSubtle": True}
        for e in proposal.get("evidence", [])[:4]
    ]
    return {
        "type": "AdaptiveCard",
        "$schema": SCHEMA,
        "version": "1.5",
        "body": [
            {"type": "TextBlock", "text": "Approval needed", "weight": "Bolder", "size": "Medium"},
            {"type": "FactSet", "facts": facts},
            *evidence,
        ],
        "actions": [
            {
                "type": "Action.Execute",
                "title": "Approve",
                "verb": "approve",
                "data": {"action_id": action["action_id"]},
            },
            {"type": "Action.Execute", "title": "Reject", "verb": "reject", "data": {"action_id": action["action_id"]}},
        ],
    }
