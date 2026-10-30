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


def sdk_config(client_id: str, tenant_id: str, secret: str = "") -> dict[str, Any]:
    """The Agents SDK's connection settings (from environment variables in production)."""
    return {
        "CONNECTIONS": {
            "SERVICE_CONNECTION": {
                "SETTINGS": {
                    "CLIENTID": client_id,
                    "TENANTID": tenant_id,
                    "AUTHTYPE": "ClientSecret" if secret else "UserManagedIdentity",
                    "CLIENTSECRET": secret,
                }
            }
        }
    }


def create_app(desk: TeamsDesk, config: dict[str, Any]) -> tuple[Any, Any]:
    """Returns (AgentApplication, CloudAdapter) with the message and Action.Execute routes."""
    from microsoft_agents.authentication.msal import MsalConnectionManager
    from microsoft_agents.hosting.aiohttp import CloudAdapter
    from microsoft_agents.hosting.core import AgentApplication, Authorization, MemoryStorage, TurnContext, TurnState

    connections = MsalConnectionManager(**config)
    storage = MemoryStorage()
    adapter = CloudAdapter(connection_manager=connections)
    app = AgentApplication[TurnState](
        storage=storage, adapter=adapter, authorization=Authorization(storage, connections, **config), **config
    )

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

    return app, adapter


def serve(port: int = 3978) -> None:  # pragma: no cover - needs Azure Bot Service credentials
    """The Teams endpoint (/api/messages) behind Azure Bot Service, on aiohttp."""
    import json as _json
    import os

    from aiohttp import web
    from microsoft_agents.hosting.aiohttp import jwt_authorization_middleware, start_agent_process

    from .. import settings
    from ..auth import principal_from_claims

    directory = (
        {p["oid"]: p for p in _json.loads((settings.BUILD / "directory.json").read_text())}
        if (settings.BUILD / "directory.json").exists()
        else {}
    )

    def resolve(aad_object_id: str) -> Principal | None:
        # production: the user's groups from Microsoft Graph (transitive memberOf); here: the directory
        entry = directory.get(aad_object_id)
        return principal_from_claims({"oid": aad_object_id, "groups": entry.get("groups", [])}) if entry else None

    desk = TeamsDesk(Systems(settings.SYSTEMS), KitStore(settings.KIT_DB), resolve)
    agent, adapter = create_app(
        desk, sdk_config(os.environ["CLIENT_ID"], os.environ["TENANT_ID"], os.environ.get("CLIENT_SECRET", ""))
    )

    async def messages(request: web.Request) -> web.Response:
        return await start_agent_process(request, agent, adapter) or web.Response(status=202)

    app = web.Application(middlewares=[jwt_authorization_middleware])
    app.router.add_post("/api/messages", messages)
    web.run_app(app, port=port)
