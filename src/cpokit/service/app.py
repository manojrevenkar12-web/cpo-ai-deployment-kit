"""The kit's HTTP API: what Teams, Power Automate, n8n and the desk call. Every request carries an
Entra ID bearer token; the caller's groups decide which cases they see and which actions they may
approve. Proposals never execute; execution needs the approval token issued to an approver."""

from __future__ import annotations

import json
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from .. import settings
from ..actions import ActionError, execute
from ..approvals import ApprovalError, Approvals
from ..auth import Principal, TokenError, Verifier
from ..kitstore import KitStore
from ..llm.gateway import Gateway, GatewayError
from ..systems.store import Systems
from ..usecases import REGISTRY
from ..usecases.base import Context, NotAllowed

ALL = ["AT", "CZ", "DE", "DK", "GB", "HU", "IT", "NL", "PL", "RO", "SE"]


def caller(request: Request, authorization: Annotated[str | None, Header()] = None) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "bearer token required")
    try:
        return request.app.state.verifier.principal(authorization.split(" ", 1)[1])
    except TokenError as e:
        raise HTTPException(401, f"invalid token: {e}") from e


Who = Annotated[Principal, Depends(caller)]


class Execute(BaseModel):
    payload: dict[str, Any]
    approval_token: str


class Usage(BaseModel):
    case_id: str
    event: str
    value: float | None = None


def create_app(
    verifier: Verifier, systems: Systems | None = None, store: KitStore | None = None, gateway: Gateway | None = None
) -> FastAPI:
    app = FastAPI(
        title="CPO AI deployment kit",
        version="1.0.0",
        description="Use cases with evals, approvals and measured adoption for a charge point operator.",
    )
    systems = systems or Systems(settings.SYSTEMS)
    store = store or KitStore(settings.KIT_DB)
    gateway = gateway or Gateway()
    approvals = Approvals(store)
    app.state.verifier = verifier

    @app.get("/health", operation_id="Health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/use-cases", operation_id="ListUseCases", summary="Use cases and their go-live status")
    def use_cases(who: Who) -> list[dict[str, Any]]:
        out = []
        for uc in settings.USE_CASES:
            spec = settings.usecase(uc)
            path = settings.REPORTS / "readiness" / f"{uc}.json"
            ready = json.loads(path.read_text())["passed"] if path.exists() else None
            out.append(
                {"id": uc, "name": spec["name"], "owner": spec["owner"], "ready": ready, "allowed": who.can_use(uc)}
            )
        return out

    @app.get("/v1/cases", operation_id="ListCases", summary="Open cases of a use case in your scope")
    def cases(who: Who, use_case: str, week: int | None = None) -> list[dict[str, Any]]:
        if not who.can_use(use_case):
            raise HTTPException(403, "not your use case")
        return systems.scoped(who.country_scope(ALL)).cases(use_case, week)[:200]

    @app.post(
        "/v1/cases/{case_id}/propose",
        operation_id="ProposeForCase",
        summary="Run the use case on a case; returns a proposal, executes nothing",
    )
    def propose(case_id: str, who: Who) -> dict[str, Any]:
        sys = systems.scoped(who.country_scope(ALL))
        case = sys.case(case_id)
        if case is None:
            raise HTTPException(404, "no such case in your scope")
        try:
            prop = REGISTRY[case["use_case"]](case, Context(sys, gateway, who)).to_dict()
        except NotAllowed as e:
            raise HTTPException(403, str(e)) from e
        except GatewayError as e:
            raise HTTPException(503, f"model unavailable, the case stays with a person: {e}") from e
        store.save_proposal(prop)
        store.event(int(time.time()), case["use_case"], case_id, case["country"], who.oid, "proposal_shown")
        store.commit()
        return prop

    @app.get("/v1/proposals/{proposal_id}", operation_id="GetProposal")
    def proposal(proposal_id: str, who: Who) -> dict[str, Any]:
        p = store.proposal(proposal_id)
        if p is None or not who.sees(p["country"]):
            raise HTTPException(404, "no such proposal in your scope")
        return p

    @app.post(
        "/v1/actions/{action_id}/approve",
        operation_id="ApproveAction",
        summary="Approve an action (needs its role; not the preparer)",
    )
    def approve(action_id: str, who: Who) -> dict[str, Any]:
        try:
            return {"approval_token": approvals.approve(action_id, who)}
        except ApprovalError as e:
            raise HTTPException(403, str(e)) from e

    @app.post("/v1/actions/{action_id}/reject", operation_id="RejectAction")
    def reject(action_id: str, who: Who) -> dict[str, Any]:
        try:
            approvals.approve(action_id, who, decision="rejected")
        except ApprovalError as e:
            raise HTTPException(403, str(e)) from e
        return {"status": "rejected"}

    @app.post(
        "/v1/actions/{action_id}/execute",
        operation_id="ExecuteAction",
        summary="Carry out an approved action with its approval token",
    )
    def run_action(action_id: str, body: Execute, who: Who) -> dict[str, Any]:
        try:
            return execute(action_id, body.payload, body.approval_token, systems, approvals)
        except (ApprovalError, ActionError) as e:
            raise HTTPException(403, str(e)) from e

    @app.post("/v1/usage", operation_id="RecordUsage", summary="Record that a person accepted or rejected a proposal")
    def usage(body: Usage, who: Who) -> dict[str, str]:
        case = systems.scoped(who.country_scope(ALL)).case(body.case_id)
        if case is None:
            raise HTTPException(404, "no such case in your scope")
        if body.event not in ("accepted", "rejected", "edited"):
            raise HTTPException(422, "event must be accepted, rejected or edited")
        store.event(int(time.time()), case["use_case"], body.case_id, case["country"], who.oid, body.event, body.value)
        store.commit()
        return {"status": "recorded"}

    @app.get("/v1/metrics/{name}", operation_id="GetMetrics", summary="adoption, impact or evaluation report")
    def metrics(name: str, who: Who) -> Any:
        if name not in ("adoption", "impact", "gate"):
            raise HTTPException(404, "unknown report")
        path = settings.REPORTS / f"{name}.json"
        if not path.exists():
            raise HTTPException(404, "not measured yet")
        return json.loads(path.read_text())

    return app
