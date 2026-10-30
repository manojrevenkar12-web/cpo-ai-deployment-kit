"""What every use case returns: a proposal a person reviews. It carries the decision code made
from system data, the evidence behind it (each item points at a record), the actions that would
change something (each needs an approval), a draft message, and why it may need a closer look."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from ..approvals import payload_hash
from ..auth import Principal
from ..llm.gateway import Gateway, Result
from ..systems.store import Systems


@dataclass
class Evidence:
    label: str
    value: Any
    source: str  # system:record, e.g. csms:session/DE-S0000123


@dataclass
class Action:
    kind: str  # credit_note | refund | escalate | publish_location | send_answer
    payload: dict[str, Any]
    role: str | None  # who must approve; None: no approval needed (nothing changes money or published data)
    amount: float | None = None
    action_id: str = field(default_factory=lambda: f"ACT-{uuid.uuid4().hex[:12]}")
    status: str = "proposed"

    @property
    def payload_hash(self) -> str:
        return payload_hash(self.payload)


@dataclass
class Proposal:
    case_id: str
    use_case: str
    country: str
    decision: str
    detail: dict[str, Any]
    evidence: list[Evidence]
    actions: list[Action]
    draft: dict[str, Any] | None
    needs_review: bool
    review_reasons: list[str]
    model_calls: list[dict[str, Any]]
    quarantined: list[str]
    prepared_by: str
    created_ts: int = field(default_factory=lambda: int(time.time()))
    proposal_id: str = field(default_factory=lambda: f"PRP-{uuid.uuid4().hex[:12]}")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["actions"] = [{**asdict(a), "payload_hash": a.payload_hash} for a in self.actions]
        return d


@dataclass
class Context:
    systems: Systems
    gateway: Gateway
    principal: Principal
    now: int | None = None

    def calls(self, results: list[Result]) -> list[dict[str, Any]]:
        return [r.summary() for r in results]


class NotAllowed(PermissionError):
    pass


def check_access(ctx: Context, use_case: str, country: str) -> None:
    if not ctx.principal.can_use(use_case):
        raise NotAllowed(f"{ctx.principal.name} may not use {use_case}")
    if not ctx.principal.sees(country):
        raise NotAllowed(f"{ctx.principal.name} does not see cases in {country}")
