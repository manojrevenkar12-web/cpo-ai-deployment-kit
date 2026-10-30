"""Teams: the copilot answers messages, and approvers approve from an Adaptive Card.

`TeamsDesk` holds the logic and is tested directly; `create_app` wires it to the Microsoft 365
Agents SDK (an `AgentApplication` with a message route and an `Action.Execute` route), hosted by
`microsoft-agents-hosting-aiohttp` behind Azure Bot Service. The Teams user is resolved to a
Principal from their Entra ID object id and groups (Microsoft Graph in production, the directory
here); an approval is only issued to someone holding the action's role, never to its preparer."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..approvals import ApprovalError, Approvals
from ..auth import Principal
from ..kitstore import KitStore
from ..systems.store import Systems
from . import cards


class TeamsDesk:
    def __init__(
        self,
        systems: Systems,
        store: KitStore,
        resolve: Callable[[str], Principal | None],
        copilot: Callable[[Principal, str], Any] | None = None,
    ) -> None:
        self.systems, self.store, self.resolve = systems, store, resolve
        self.copilot = copilot
        self.approvals = Approvals(store)

    async def on_message(self, aad_object_id: str, text: str) -> str:
        who = self.resolve(aad_object_id)
        if who is None:
            return "You are not set up for the back-office assistant. Ask the AI unit to add you to a team group."
        if self.copilot is None:
            return "The assistant is not connected in this environment."
        res = await self.copilot(who, text)
        return res.text

    def on_card_action(self, aad_object_id: str, verb: str, data: dict[str, Any]) -> dict[str, Any]:
        """Approve or reject from the card. Returns the card to show instead (the outcome)."""
        who = self.resolve(aad_object_id)
        action_id = str(data.get("action_id", ""))
        if who is None:
            return _notice("You are not set up to approve.")
        try:
            if verb == "approve":
                token = self.approvals.approve(action_id, who)
                return _notice("Approved. The action runs with your approval.", token=token)
            if verb == "reject":
                self.approvals.approve(action_id, who, decision="rejected")
                return _notice("Rejected. The preparer sees your decision on the desk.")
        except ApprovalError as e:
            return _notice(f"Not approved: {e}.")
        return _notice("Unknown action.")


def _notice(text: str, token: str | None = None) -> dict[str, Any]:
    card = {
        "type": "AdaptiveCard",
        "$schema": cards.SCHEMA,
        "version": "1.5",
        "body": [{"type": "TextBlock", "text": text, "wrap": True}],
    }
    if token:
        card["_approval_token"] = token  # handed to the executor, not shown
    return card


def create_app(desk: TeamsDesk) -> Any:  # pragma: no cover - wiring to the hosting SDK
    from microsoft_agents.hosting.core import AgentApplication, MemoryStorage, TurnContext, TurnState

    app = AgentApplication[TurnState](storage=MemoryStorage())

    @app.message()
    async def message(context: TurnContext, state: TurnState) -> None:
        user = context.activity.from_property
        await context.send_activity(await desk.on_message(user.aad_object_id, context.activity.text or ""))

    @app.adaptive_card.action_execute("approve")
    async def approve(context: TurnContext, state: TurnState, data: dict[str, Any]) -> dict[str, Any]:
        return desk.on_card_action(context.activity.from_property.aad_object_id, "approve", data)

    @app.adaptive_card.action_execute("reject")
    async def reject(context: TurnContext, state: TurnState, data: dict[str, Any]) -> dict[str, Any]:
        return desk.on_card_action(context.activity.from_property.aad_object_id, "reject", data)

    return app
