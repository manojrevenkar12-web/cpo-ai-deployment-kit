"""The ops copilot: a Microsoft Agent Framework agent people talk to in Teams ("what about case
D-MAIL-...?", "why no credit?"). It has three tools: run a use case on a case (a proposal, nothing
executed), show a stored proposal with its evidence, and ask an approver to approve an action. The
last one is marked as needing the user's confirmation in the agent loop, and even then it only
sends a request: the approval itself is a person with the role pressing Approve in Teams, and the
write needs the token that produces.

The chat model is whatever client is passed in: Claude through Microsoft Foundry in production,
a scripted client in the tests."""

from __future__ import annotations

import json
from typing import Any

from agent_framework import Agent, tool

from ..auth import Principal
from ..kitstore import KitStore
from ..llm.gateway import Gateway
from ..systems.store import Systems
from ..usecases import REGISTRY
from ..usecases.base import Context
from . import cards

INSTRUCTIONS = (
    "You help people in a charge point operator's back office with their cases. Use propose_for_case to "
    "get the tool's proposal for a case, show_proposal to explain one. Amounts, decisions and evidence come "
    "only from these tools; never state an amount they did not return. To move money or publish data, use "
    "request_approval; you cannot approve or execute anything yourself."
)


def build_agent(
    client: Any,
    principal: Principal,
    systems: Systems,
    store: KitStore,
    gateway: Gateway | None = None,
    outbox: list[dict[str, Any]] | None = None,
) -> Agent:
    gw = gateway or Gateway()
    sent = outbox if outbox is not None else []
    scoped = systems.scoped(principal.country_scope(["AT", "CZ", "DE", "DK", "GB", "HU", "IT", "NL", "PL", "RO", "SE"]))

    @tool(
        description="Run the use case on one case and return its proposal: decision, amounts, evidence, "
        "actions waiting for approval. Executes nothing."
    )
    def propose_for_case(case_id: str) -> str:
        case = scoped.case(case_id)
        if case is None:
            return json.dumps({"error": "no such case in your scope"})
        prop = REGISTRY[case["use_case"]](case, Context(scoped, gw, principal)).to_dict()
        store.save_proposal(prop)
        return json.dumps(
            {k: prop[k] for k in ("proposal_id", "decision", "detail", "review_reasons")}
            | {"actions": [{k: a[k] for k in ("action_id", "kind", "amount", "role")} for a in prop["actions"]]},
            default=str,
            ensure_ascii=False,
        )

    @tool(description="Show a stored proposal with its evidence.")
    def show_proposal(proposal_id: str) -> str:
        p = store.proposal(proposal_id)
        if p is None or not principal.sees(p["country"]):
            return json.dumps({"error": "no such proposal in your scope"})
        return json.dumps(
            {k: p[k] for k in ("decision", "detail", "evidence", "review_reasons")}, default=str, ensure_ascii=False
        )

    @tool(
        approval_mode="always_require",
        description="Ask the approver role named on an action to approve it (sends them a card).",
    )
    def request_approval(action_id: str) -> str:
        a = store.action(action_id)
        if a is None:
            return json.dumps({"error": "no such action"})
        card = cards.approval_card(a, store.proposal(a["proposal_id"]) or {})
        sent.append({"to_role": a["role"], "card": card})
        return json.dumps({"sent_to_role": a["role"], "action_id": action_id})

    return Agent(client, INSTRUCTIONS, name="ops-copilot", tools=[propose_for_case, show_proposal, request_approval])
