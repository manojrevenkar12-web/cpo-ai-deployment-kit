"""Carrying out an approved action: the only code that writes to the ERP or publishes a location.
It is called by the MCP write tools, the API and the Teams bot, always with an approval token."""

from __future__ import annotations

import time
import uuid
from typing import Any

from .approvals import Approvals
from .systems.store import Systems


class ActionError(RuntimeError):
    pass


def execute(
    action_id: str, payload: dict[str, Any], token: str, systems: Systems, approvals: Approvals, now: int | None = None
) -> dict[str, Any]:
    a = approvals.store.action(action_id)
    if a is None:
        raise ActionError("no such action")
    body = approvals.redeem(token, action_id, payload)  # raises if the token does not fit this exact call
    ts = now or int(time.time())
    kind = a["kind"]
    if kind in ("credit_note", "refund"):
        posting = {
            "posting_id": f"ERP-{uuid.uuid4().hex[:10]}",
            "kind": kind,
            "case_id": payload["case_id"],
            "ref": payload.get("cdr_id") or payload.get("session_id"),
            "amount": payload["amount_eur"],
            "payload": payload,
            "approved_by": body["by"],
            "approval_id": body["aid"],
            "posted_ts": ts,
        }
        systems.post_erp(posting)
        return {"posted": posting["posting_id"]}
    if kind == "publish_location":
        loc = payload["location"]
        systems.publish_location(loc["id"], loc, body["by"], body["aid"], ts)
        return {"published": loc["id"]}
    if kind in ("escalate", "send_answer"):
        return {"recorded": kind}
    raise ActionError(f"unknown action kind {kind}")
