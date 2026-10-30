"""Roaming CDR disputes (owner: Roaming Finance).

The model reads the partner's email and lists what it disputes. Code finds each CDR (by id, by
session id with or without the hub's prefix, or by charge point and local time), re-rates the
session from the CSMS's signed meter values and the tariff version valid at the time, and decides:
credit the difference, credit a duplicate in full, or reject with the evidence. Credit notes are
posted to the ERP only after a finance approver approves each one. The model then drafts the reply
in the partner's language from the decisions; it never sets an amount."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .. import settings
from ..llm.gateway import GatewayError
from . import billing
from .base import Action, Context, Evidence, Proposal, check_access

USE_CASE = "cdr_disputes"


def _utc_ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _local_to_ts(local_iso: str, tz: str) -> int:
    return int(datetime.fromisoformat(local_iso).replace(tzinfo=ZoneInfo(tz)).timestamp())


def locate(ctx: Context, ref: dict[str, Any], partner_id: str, pol: dict[str, Any]) -> tuple[dict | None, str]:
    """Finds the CDR an item refers to. Returns (cdr, how) or (None, why not)."""
    sys = ctx.systems
    if ref.get("cdr_id"):
        c = sys.cdr(ref["cdr_id"])
        if c is not None:
            return c, "cdr id"
    if ref.get("session_ref"):
        cs = [c for c in sys.cdrs_for_session(ref["session_ref"]) if c["partner_id"] == partner_id]
        if len(cs) == 1:
            return cs[0], "session id"
        if len(cs) > 1:
            return cs[-1], "session id (several CDRs)"
    if ref.get("evse_id") and (ref.get("local_time") or ref.get("utc_time")):
        evse = sys.evse(ref["evse_id"])
        if evse is None:
            return None, "no such charge point"
        site = sys.site(evse["site_id"])
        window = pol["match_window_minutes"] * 60
        clocks = [("charge point's clock", site["tz"])]
        partner = sys.partner(partner_id)
        ptz = sys.country_tz(partner["country"]) if partner else None
        if ptz and ptz != site["tz"] and not ref.get("utc_time"):
            clocks.append(("partner's clock", ptz))  # partners often write times on their own clock
        reason = "no CDR of this partner at that charge point and time"
        for label, tz in clocks:
            ts = _utc_ts(ref["utc_time"]) if ref.get("utc_time") else _local_to_ts(ref["local_time"], tz)
            cands = [c for c in sys.cdrs_near(ref["evse_id"], ts, window) if c["partner_id"] == partner_id]
            sessions = {c["session_id"].split("HUB-")[-1] for c in cands}
            if len(sessions) == 1:
                return cands[-1], f"charge point and time ({label})"
            if len(sessions) > 1:
                return None, f"{len(sessions)} sessions match the charge point and time"
        return None, reason
    if ref.get("cdr_id") or ref.get("session_ref"):
        return None, "no CDR or session with this id"
    return None, "the email gives no usable reference"


def assess(ctx: Context, cdr: dict[str, Any], pol: dict[str, Any]) -> dict[str, Any]:
    """Re-rates the CDR's session and explains any difference."""
    sys = ctx.systems
    bare = cdr["session_id"].split("HUB-")[-1]
    session = sys.session(bare)
    ev: list[Evidence] = [
        Evidence(
            "CDR as billed",
            {
                k: cdr[k]
                for k in (
                    "tariff_id",
                    "total_energy_kwh",
                    "peak_energy_kwh",
                    "idle_minutes",
                    "idle_cost",
                    "vat_rate",
                    "total_cost_incl_vat",
                )
            },
            f"ocpi:cdr/{cdr['cdr_id']}",
        )
    ]
    if session is None:
        return {
            "cause": "unknown_session",
            "credit": 0.0,
            "decision": "reject",
            "evidence": ev,
            "note": "the CDR's session is not in the CSMS",
        }
    siblings = sys.cdrs_for_session(bare)
    first = min(siblings, key=lambda c: (c["sent_ts"], c["cdr_id"]))
    if len(siblings) > 1 and first["cdr_id"] != cdr["cdr_id"]:
        ev.append(Evidence("same session already billed", first["cdr_id"], f"ocpi:cdr/{first['cdr_id']}"))
        return {
            "cause": "duplicate",
            "credit": round(cdr["total_cost_incl_vat"], 2),
            "decision": "credit",
            "evidence": ev,
        }
    exp = billing.rerate(sys, session, peak_hours=tuple(pol["peak_hours_local"]))
    if exp is None:
        return {
            "cause": "no_data",
            "credit": 0.0,
            "decision": "review",
            "evidence": ev,
            "note": "meter values or tariff missing",
        }
    ev.append(
        Evidence(
            "re-rated from signed meter values",
            {
                k: exp[k]
                for k in (
                    "tariff_id",
                    "total_energy_kwh",
                    "peak_energy_kwh",
                    "idle_minutes",
                    "idle_cost",
                    "vat_rate",
                    "total_cost_incl_vat",
                )
            },
            f"csms:session/{bare}",
        )
    )
    causes = []
    if cdr["tariff_id"] != exp["tariff_id"]:
        causes.append("tariff_version")
    if abs(cdr["total_energy_kwh"] - exp["total_energy_kwh"]) > 0.01:
        causes.append("energy_mismatch")
    if abs(cdr["vat_rate"] - exp["vat_rate"]) > 1e-6:
        causes.append("vat_rate")
    if abs(cdr["peak_energy_kwh"] - exp["peak_energy_kwh"]) > 0.01 and "energy_mismatch" not in causes:
        causes.append("peak_window")
    if cdr["idle_cost"] > 0 and exp["lock_fault"]:
        causes.append("idle_fault")
        ev.append(Evidence("connector-lock fault while idle", True, f"csms:status/{session['evse_id']}"))
    credit = round(cdr["total_cost_incl_vat"] - exp["total_cost_incl_vat"], 2)
    if credit >= pol["min_credit_eur"]:
        return {
            "cause": causes[0] if causes else "other",
            "causes": causes,
            "credit": credit,
            "decision": "credit",
            "evidence": ev,
        }
    if credit < -pol["rounding_tolerance_eur"]:
        return {
            "cause": "undercharged",
            "causes": causes,
            "credit": 0.0,
            "decision": "reject",
            "evidence": ev,
            "note": "the CDR is lower than the re-rated price",
        }
    return {"cause": "no_error", "causes": causes, "credit": 0.0, "decision": "reject", "evidence": ev}


def run(case: dict[str, Any], ctx: Context) -> Proposal:
    check_access(ctx, USE_CASE, case["country"])
    pol = settings.policy()[USE_CASE]
    email = ctx.systems.email(case["ref"])
    if email is None:
        raise LookupError(case["ref"])
    partner = ctx.systems.partner(email["partner_id"]) or {"partner_id": email["partner_id"], "lang": "en"}
    received = datetime.fromtimestamp(email["received_ts"], UTC).date().isoformat()
    results = []
    reasons: list[str] = []
    try:
        read = ctx.gateway.call(
            "dispute.read", {"email": email["body"], "partner": partner["partner_id"], "received": received}
        )
        results.append(read)
        refs = read.output["items"]
    except GatewayError as e:
        refs = []
        reasons.append(f"the email could not be read: {e}")
        read = None
    quarantined = read.quarantined if read else []
    if quarantined:
        reasons.append("instruction-like text in the email was quarantined")
    if not refs and not reasons:
        reasons.append("no disputed record found in the email")
    items, evidence, actions = [], [], []
    seen: set[str] = set()
    for ref in refs:
        cdr, how = locate(ctx, ref, partner["partner_id"], pol)
        if cdr is None:
            unknown_id = bool(ref.get("cdr_id") or ref.get("session_ref")) and "no CDR or session" in how
            decision = "reject" if unknown_id or how.startswith("no CDR of this partner") else "ask_info"
            items.append(
                {
                    "ref": ref,
                    "cdr_id": ref.get("cdr_id"),
                    "decision": decision,
                    "cause": "unknown_session" if decision == "reject" else None,
                    "credit_eur": 0.0,
                    "note": how,
                }
            )
            if decision == "ask_info":
                reasons.append(f"cannot identify a disputed record: {how}")
            continue
        if cdr["cdr_id"] in seen:
            continue
        seen.add(cdr["cdr_id"])
        a = assess(ctx, cdr, pol)
        evidence += a["evidence"]
        item = {
            "ref": ref,
            "cdr_id": cdr["cdr_id"],
            "found_by": how,
            "decision": a["decision"],
            "cause": a["cause"],
            "credit_eur": a["credit"],
            "claimed_eur": ref.get("claimed_eur"),
            "note": a.get("note"),
        }
        items.append(item)
        if a["decision"] == "review":
            reasons.append(f"{cdr['cdr_id']}: {a.get('note')}")
        if a["decision"] == "credit":
            actions.append(
                Action(
                    "credit_note",
                    {
                        "case_id": case["case_id"],
                        "cdr_id": cdr["cdr_id"],
                        "partner_id": partner["partner_id"],
                        "amount_eur": a["credit"],
                        "reason": a["cause"],
                    },
                    role=pol["approval"]["role"],
                    amount=a["credit"],
                )
            )
        if ref.get("claimed_eur") and a["credit"] > 0 and abs(ref["claimed_eur"] - a["credit"]) > 0.5 * a["credit"] + 1:
            reasons.append(
                f"{cdr['cdr_id']}: partner claims {ref['claimed_eur']:.2f} EUR, re-rating gives {a['credit']:.2f} EUR"
            )
    decisions = [
        f"{i['cdr_id'] or i['ref'].get('evse_id')}: "
        + (
            {
                "credit": f"credit note {i['credit_eur']:.2f} EUR ({i['cause']})",
                "reject": f"no credit ({i['cause'] or 'not found'})",
                "ask_info": "please send the CDR id",
                "review": "under review",
            }[i["decision"]]
        )
        for i in items
    ]
    draft = None
    try:
        rep = ctx.gateway.call("dispute.reply", {"language": partner.get("lang", "en"), "decisions": decisions})
        results.append(rep)
        draft = rep.output
    except GatewayError as e:
        reasons.append(f"no reply draft: {e}")
    total = round(sum(i["credit_eur"] for i in items), 2)
    decision = "credit" if total > 0 else ("ask_info" if any(i["decision"] == "ask_info" for i in items) else "reject")
    return Proposal(
        case_id=case["case_id"],
        use_case=USE_CASE,
        country=case["country"],
        decision=decision,
        detail={"partner_id": partner["partner_id"], "items": items, "total_credit_eur": total},
        evidence=evidence,
        actions=actions,
        draft=draft,
        needs_review=bool(reasons),
        review_reasons=reasons,
        model_calls=ctx.calls(results),
        quarantined=quarantined,
        prepared_by=ctx.principal.oid,
        created_ts=ctx.now or case["opened_ts"],
    )
