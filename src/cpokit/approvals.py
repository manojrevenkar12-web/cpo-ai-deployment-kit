"""Approvals: nothing changes money or published data until a person with the right role approves
the exact action, and the write tools accept only a token bound to that action.

A token is an HMAC over (approval id, action id, hash of the action's payload, approver, expiry). A
write tool recomputes the hash from the arguments it was called with, so a token for a credit of
12.40 EUR cannot post 1,240 EUR; it is single-use and expires."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

from . import settings
from .auth import Principal
from .kitstore import KitStore


class ApprovalError(PermissionError):
    pass


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _secret() -> bytes:
    s = os.environ.get("CPOKIT_APPROVAL_SECRET")
    if s:
        return s.encode()
    path = settings.BUILD / ".approval_secret"  # dev only; Key Vault in Azure
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(uuid.uuid4().hex + uuid.uuid4().hex)
    return path.read_text().encode()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Approvals:
    def __init__(self, store: KitStore, now: Any = time.time) -> None:
        self.store = store
        self.now = now
        self.cfg = settings.access()["approvals"]

    def approve(self, action_id: str, approver: Principal, *, decision: str = "approved") -> str | None:
        """Records the decision; returns a token when approved."""
        a = self.store.action(action_id)
        if a is None:
            raise ApprovalError("no such action")
        if a["status"] not in ("proposed",):
            raise ApprovalError(f"action is {a['status']}")
        if a["role"] and not approver.has_role(a["role"]):
            raise ApprovalError(f"approving this needs the role {a['role']}")
        prop = self.store.proposal(a["proposal_id"])
        if a["role"] and self.cfg["four_eyes"] and prop and prop["prepared_by"] == approver.oid:
            raise ApprovalError("the person who prepared an action cannot approve it")
        if prop and not approver.sees(prop["country"]):
            raise ApprovalError("outside the approver's countries")
        ts = int(self.now())
        approval_id = f"APR-{uuid.uuid4().hex[:12]}"
        token = None
        token_id = None
        if decision == "approved":
            token_id = uuid.uuid4().hex
            body = {
                "tid": token_id,
                "aid": approval_id,
                "act": action_id,
                "h": a["payload_hash"],
                "by": approver.oid,
                "exp": ts + self.cfg["token_ttl_minutes"] * 60,
            }
            raw = json.dumps(body, sort_keys=True).encode()
            sig = hmac.new(_secret(), raw, hashlib.sha256).digest()
            token = f"{_b64(raw)}.{_b64(sig)}"
        self.store.record_approval(
            {
                "approval_id": approval_id,
                "action_id": action_id,
                "approver": approver.oid,
                "decided_ts": ts,
                "decision": decision,
                "token_id": token_id,
            }
        )
        self.store.set_action_status(action_id, decision)
        return token

    def redeem(self, token: str, action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Checks a token against the call it is presented with, and uses it up."""
        try:
            raw_s, sig_s = token.split(".")
            raw, sig = _unb64(raw_s), _unb64(sig_s)
        except ValueError as e:
            raise ApprovalError("malformed approval token") from e
        if not hmac.compare_digest(hmac.new(_secret(), raw, hashlib.sha256).digest(), sig):
            raise ApprovalError("approval token signature does not match")
        body = json.loads(raw)
        if body["act"] != action_id:
            raise ApprovalError("approval token is for another action")
        if body["h"] != payload_hash(payload):
            raise ApprovalError("the call differs from what was approved")
        if body["exp"] < int(self.now()):
            raise ApprovalError("approval token expired")
        if not self.store.consume(body["tid"], int(self.now())):
            raise ApprovalError("approval token already used")
        self.store.set_action_status(action_id, "executed")
        return body
