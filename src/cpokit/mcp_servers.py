"""The enterprise systems as MCP servers, so any agent (the kit's own, Copilot Studio, Claude, an n8n
AI Agent node) reaches them the same governed way.

- Every tool runs with the caller's identity: over HTTP the Entra ID token is validated (signature,
  issuer, audience) and its groups become the caller's functions and countries; in process the
  server is built for a given principal. Data outside the caller's countries is not returned.
- Read tools are marked read-only. The two write tools (post to the ERP, publish a location) need an
  approval token bound to the exact action; without one they refuse, with one they write once.
- The `kit` server exposes the use cases themselves: `propose` returns a proposal with its evidence,
  never executes it."""

from __future__ import annotations

import os
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import settings
from .actions import execute
from .approvals import Approvals
from .auth import Principal, TokenError, Verifier, issuer_url, principal_from_claims
from .kitstore import KitStore
from .llm.gateway import Gateway
from .systems.store import Systems
from .usecases import REGISTRY
from .usecases.base import Context

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)
SYSTEM_FUNCTIONS = {
    "csms": {"roaming_finance", "customer_service", "integration_ops"},
    "roaming": {"roaming_finance"},
    "payments": {"customer_service"},
    "erp": {"roaming_finance", "customer_service"},
    "documents": {"integration_ops", "bid_team"},
    "kit": {"roaming_finance", "customer_service", "integration_ops", "bid_team"},
}
ALL_COUNTRIES = ["AT", "CZ", "DE", "DK", "GB", "HU", "IT", "NL", "PL", "RO", "SE"]


class EntraTokenVerifier:
    """MCP's TokenVerifier over the kit's Entra ID verifier."""

    def __init__(self, verifier: Verifier) -> None:
        self.verifier = verifier

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = self.verifier.claims(token)
        except TokenError:
            return None
        return AccessToken(
            token=token,
            client_id=str(claims.get("azp", "entra")),
            scopes=[],
            expires_at=int(claims["exp"]),
            resource=str(claims["aud"]),
            subject=str(claims.get("oid")),
            claims=claims,
        )


def _caller(fixed: Principal | None) -> Principal:
    if fixed is not None:
        return fixed
    tok = get_access_token()
    if tok is None or not tok.claims:
        raise PermissionError("no authenticated caller")
    return principal_from_claims(tok.claims)


def build(
    system: str,
    systems: Systems,
    store: KitStore,
    principal: Principal | None = None,
    gateway: Gateway | None = None,
    auth: tuple[EntraTokenVerifier, AuthSettings] | None = None,
) -> MCPServer:
    kwargs: dict[str, Any] = {}
    if auth:
        kwargs = {"token_verifier": auth[0], "auth": auth[1]}
    mcp = MCPServer(
        name=f"cpo-{system}", instructions=f"The operator's {system} system, scoped to the caller.", **kwargs
    )
    approvals = Approvals(store)

    def scope() -> tuple[Principal, Systems]:
        p = _caller(principal)
        if not (p.functions & SYSTEM_FUNCTIONS[system]) and "kit_admin" not in p.roles:
            raise PermissionError(f"{p.name} has no access to {system}")
        return p, systems.scoped(p.country_scope(ALL_COUNTRIES))

    if system == "csms":

        @mcp.tool(annotations=READ)
        def get_session(session_id: str) -> dict[str, Any] | None:
            """A charging session as the CSMS recorded it (signed meter start and stop, token)."""
            return scope()[1].session(session_id.split("HUB-")[-1])

        @mcp.tool(annotations=READ)
        def sessions_near(evse_id: str, utc_ts: int, window_minutes: int = 60) -> list[dict[str, Any]]:
            """Sessions at a charge point that started within the window around a time (UTC epoch)."""
            return scope()[1].sessions_near([evse_id], utc_ts, window_minutes * 60)

        @mcp.tool(annotations=READ)
        def meter_values(session_id: str) -> list[dict[str, Any]]:
            """Cumulative energy (Wh) every five minutes while charging."""
            return scope()[1].meter_values(session_id)

        @mcp.tool(annotations=READ)
        def status_events(evse_id: str, from_ts: int, to_ts: int) -> list[dict[str, Any]]:
            """Connector status notifications and error codes."""
            return scope()[1].status_events(evse_id, from_ts, to_ts)

    elif system == "roaming":

        @mcp.tool(annotations=READ)
        def get_cdr(cdr_id: str) -> dict[str, Any] | None:
            """A CDR as sent to the partner (OCPI)."""
            return scope()[1].cdr(cdr_id)

        @mcp.tool(annotations=READ)
        def cdrs_for_session(session_ref: str) -> list[dict[str, Any]]:
            """All CDRs sent for a session, with or without a hub's prefix."""
            return scope()[1].cdrs_for_session(session_ref)

    elif system == "payments":

        @mcp.tool(annotations=READ)
        def payments_for_session(session_id: str) -> list[dict[str, Any]]:
            """Card pre-authorisations, captures and releases of a session."""
            return scope()[1].payments_for_session(session_id)

    elif system == "erp":

        @mcp.tool(annotations=WRITE)
        def post_approved_action(action_id: str, payload: dict[str, Any], approval_token: str) -> dict[str, Any]:
            """Posts a credit note or refund that a person with the right role approved. The token must
            belong to this action and this exact payload; it works once."""
            _, sys = scope()
            return execute(action_id, payload, approval_token, sys, approvals)

    elif system == "documents":

        @mcp.tool(annotations=READ)
        def site_export_rows(site_code: str) -> list[dict[str, Any]]:
            """Rows of the acquired network's export for one site."""
            return [r for r in scope()[1].site_rows() if r.get("Codice sito") == site_code]

        @mcp.tool(annotations=WRITE)
        def publish_location(action_id: str, payload: dict[str, Any], approval_token: str) -> dict[str, Any]:
            """Publishes an approved location to roaming partners. Needs an integration lead's token."""
            _, sys = scope()
            return execute(action_id, payload, approval_token, sys, approvals)

    elif system == "kit":

        @mcp.tool(annotations=READ)
        def propose(use_case: str, case_id: str) -> dict[str, Any]:
            """Runs a use case on a case and returns the proposal (decision, evidence, actions waiting
            for approval, draft). Nothing is executed."""
            p, sys = scope()
            case = sys.case(case_id)
            if case is None:
                raise LookupError("no such case in your scope")
            prop = REGISTRY[use_case](case, Context(sys, gateway or Gateway(), p))
            d = prop.to_dict()
            store.save_proposal(d)
            return d

    else:
        raise ValueError(system)
    return mcp


def serve(system: str) -> None:
    import anyio
    import httpx

    cfg = settings.access()
    jwks_url = os.environ.get(
        "CPOKIT_JWKS_URL", f"https://login.microsoftonline.com/{cfg['tenant']}/discovery/v2.0/keys"
    )
    verifier = Verifier(httpx.get(jwks_url, timeout=10).json(), issuer_url(cfg["tenant"]), cfg["audience"])
    public = os.environ.get("CPOKIT_PUBLIC_URL", "http://localhost:8100")
    auth = (
        EntraTokenVerifier(verifier),
        AuthSettings(issuer_url=issuer_url(cfg["tenant"]), resource_server_url=f"{public}/mcp"),
    )
    server = build(system, Systems(settings.SYSTEMS), KitStore(settings.KIT_DB), auth=auth)
    anyio.run(lambda: server.run_streamable_http_async(host="0.0.0.0", port=int(os.environ.get("PORT", 8100))))
