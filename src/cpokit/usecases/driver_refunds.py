"""Drivers' refund tickets (owner: Customer Service, eleven countries).

The model reads the ticket (language, what the driver reports, the details given). Code finds the
session and its payments and decides by the refund policy from what the systems recorded, not from
what the driver says happened: a refund (and how much), an explanation, an escalation to payments,
a redirect to the driver's own provider, or a request for details. Refunds above the policy
threshold need a customer-service lead's approval. The model drafts the reply from the outcome."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .. import settings
from ..llm.gateway import GatewayError
from . import billing
from .base import Action, Context, Evidence, Proposal, check_access

USE_CASE = "driver_refunds"
DAY = 86400


def _ts(local_iso: str, tz: str) -> int:
    return int(datetime.fromisoformat(local_iso).replace(tzinfo=ZoneInfo(tz)).timestamp())


def find_session(ctx: Context, read: dict[str, Any], opened_ts: int, pol: dict[str, Any]) -> tuple[dict | None, str]:
    sys = ctx.systems
    window = pol["match_window_hours"] * 3600
    candidates: list[dict[str, Any]] = []
    how = ""
    if read.get("evse_id"):
        evse = sys.evse(read["evse_id"])
        if evse:
            site = sys.site(evse["site_id"])
            if read.get("local_time"):
                candidates = sys.sessions_near([evse["evse_id"]], _ts(read["local_time"], site["tz"]), window)
                how = "charge point and time"
            else:
                candidates = sys.sessions_near([evse["evse_id"]], opened_ts - 7 * DAY, 7 * DAY)
                how = "charge point, last week"
    elif read.get("city") and read.get("address"):
        sites = sys.sites_matching(city=read["city"], text=read["address"])
        evse_ids = [e["evse_id"] for s in sites for e in sys.evses_of(s["site_id"])]
        if sites and read.get("local_time"):
            candidates = sys.sessions_near(evse_ids, _ts(read["local_time"], sites[0]["tz"]), window)
            how = "address and time"
    if read.get("last4"):
        card = f"card:{read['last4']}"
        by_card = [c for c in candidates if c["token"] == card]
        if not candidates:
            # four card digits alone are shared by many drivers: never enough to pay anyone
            return None, "only card digits given; need the charge point or the time"
        candidates = by_card or candidates
    if read.get("app"):
        apps = [c for c in candidates if c["token"].startswith("app:")]
        candidates = apps or candidates
    if not candidates:
        return None, how or "no details to find the session"
    if read.get("local_time") and len(candidates) > 1:
        ref = candidates[0]
        site = sys.site(ref["site_id"])
        t = _ts(read["local_time"], site["tz"])
        candidates = sorted(candidates, key=lambda c: abs(c["start_ts"] - t))
        if abs(candidates[0]["start_ts"] - t) * 2 > abs(candidates[1]["start_ts"] - t) and not read.get("last4"):
            return None, f"{len(candidates)} sessions fit the details"
        return candidates[0], how
    if len(candidates) > 1:
        return None, f"{len(candidates)} sessions fit the details"
    return candidates[0], how


def decide(ctx: Context, session: dict[str, Any], opened_ts: int, pol: dict[str, Any]) -> dict[str, Any]:
    sys = ctx.systems
    ev = [
        Evidence(
            "session",
            {k: session[k] for k in ("session_id", "evse_id", "start_ts", "stop_ts", "token")},
            f"csms:session/{session['session_id']}",
        )
    ]
    if any(session["token"].startswith(t) for t in pol["roaming_tokens"]):
        return {
            "action": "redirect_emsp",
            "amount": 0.0,
            "evidence": ev,
            "why": f"paid through {session['token'].split(':', 1)[1]}, which bills the driver",
        }
    pays = sys.payments_for_session(session["session_id"])
    ev.append(
        Evidence(
            "payments",
            [{k: p[k] for k in ("type", "amount", "ts")} for p in pays],
            f"payments:session/{session['session_id']}",
        )
    )
    captures = [p for p in pays if p["type"] == "capture"]
    preauth = [p for p in pays if p["type"] == "preauth"]
    released = [p for p in pays if p["type"] == "release"]
    energy_kwh = (session["meter_stop_wh"] - session["meter_start_wh"]) / 1000
    if len(captures) > 1:
        return {
            "action": "refund",
            "amount": round(sum(c["amount"] for c in captures[1:]), 2),
            "evidence": ev,
            "why": "the payment was captured more than once",
        }
    if captures and energy_kwh < pol["no_energy_kwh"]:
        return {
            "action": "refund",
            "amount": round(captures[0]["amount"], 2),
            "evidence": ev,
            "why": f"only {energy_kwh:.2f} kWh were delivered",
        }
    if preauth and not released:
        age = (opened_ts - preauth[0]["ts"]) / DAY
        if age >= pol["preauth_release_days"]:
            return {
                "action": "escalate_payments",
                "amount": 0.0,
                "evidence": ev,
                "why": f"the card hold is {age:.0f} days old and was not released",
            }
        return {
            "action": "explain",
            "amount": 0.0,
            "evidence": ev,
            "why": f"the card hold is released by the bank within {pol['preauth_release_days']} days",
        }
    statuses = sys.status_events(session["evse_id"], session["start_ts"], session["stop_ts"])
    unplugged = [s for s in statuses if s["error_code"] == "CableUnplugged" and s["ts"] < session["stop_ts"] - 600]
    if unplugged and captures:
        fair = billing.rerate(sys, session, stop_ts=unplugged[0]["ts"])
        if fair:
            ev.append(
                Evidence(
                    "cable unplugged while the session ran", unplugged[0]["ts"], f"csms:status/{session['evse_id']}"
                )
            )
            return {
                "action": "refund",
                "amount": round(captures[0]["amount"] - fair["total_cost_incl_vat"], 2),
                "evidence": ev,
                "why": "billed after the cable was unplugged",
            }
    shown = next((p["shown_price_per_kwh"] for p in preauth if p["shown_price_per_kwh"] is not None), None)
    rated = billing.rerate(sys, session)
    if shown is not None and rated is not None:
        evse = sys.evse(session["evse_id"])
        tariff = billing.tariff_at(sys.tariffs(session["site_id"], evse["kind"]), session["start_ts"])
        if tariff and shown < tariff["energy"] - 1e-6:
            amount = rated["total_energy_kwh"] * (tariff["energy"] - shown) * (1 + rated["vat_rate"])
            ev.append(Evidence("price shown on the terminal", shown, f"payments:preauth/{session['session_id']}"))
            return {
                "action": "refund",
                "amount": round(amount, 2),
                "evidence": ev,
                "why": "charged above the price shown before charging",
            }
    return {"action": "explain", "amount": 0.0, "evidence": ev, "why": "the charge matches the tariff"}


def run(case: dict[str, Any], ctx: Context) -> Proposal:
    check_access(ctx, USE_CASE, case["country"])
    pol = settings.policy()[USE_CASE]
    t = ctx.systems.ticket(case["ref"])
    if t is None:
        raise LookupError(case["ref"])
    received = datetime.fromtimestamp(t["opened_ts"], UTC).date().isoformat()
    results, reasons = [], []
    try:
        r = ctx.gateway.call("ticket.read", {"ticket": t["text"], "received": received, "country": t["country"]})
        results.append(r)
        read = r.output
        quarantined = r.quarantined
    except GatewayError as e:
        read, quarantined = {"language": t["lang"], "intent": "other"}, []
        reasons.append(f"the ticket could not be read: {e}")
    if quarantined:
        reasons.append("instruction-like text in the ticket was quarantined")
    session, how = find_session(ctx, read, t["opened_ts"], pol)
    evidence: list[Evidence] = []
    if session is None:
        outcome = {"action": "ask_info", "amount": 0.0, "why": how}
    else:
        outcome = decide(ctx, session, t["opened_ts"], pol)
        evidence = outcome.pop("evidence")
    amount = outcome["amount"]
    action = outcome["action"]
    if action == "refund" and amount < pol["min_refund_eur"]:
        action, amount = "explain", 0.0
    if read.get("intent") not in (None, "other") and _mismatch(read["intent"], action):
        reasons.append(f"the driver reports {read['intent']} but the records show {action}")
    actions = []
    if action == "refund":
        role = pol["approval_role"] if amount > pol["approval_above_eur"] else None
        actions.append(
            Action(
                "refund",
                {
                    "case_id": case["case_id"],
                    "session_id": session["session_id"],
                    "amount_eur": amount,
                    "reason": outcome["why"],
                },
                role=role,
                amount=amount,
            )
        )
    elif action == "escalate_payments":
        actions.append(
            Action(
                "escalate",
                {"case_id": case["case_id"], "team": "payments", "session_id": session["session_id"]},
                role=None,
            )
        )
    draft = None
    try:
        rep = ctx.gateway.call(
            "ticket.reply",
            {
                "language": read.get("language", t["lang"]),
                "outcome": [f"{action}: {amount:.2f} EUR" if amount else action, outcome["why"]],
            },
        )
        results.append(rep)
        draft = rep.output
    except GatewayError as e:
        reasons.append(f"no reply draft: {e}")
    return Proposal(
        case_id=case["case_id"],
        use_case=USE_CASE,
        country=case["country"],
        decision=action,
        detail={
            "amount_eur": round(amount, 2),
            "session_id": session["session_id"] if session else None,
            "found_by": how,
            "why": outcome["why"],
            "read": read,
        },
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


EXPECTED = {
    "no_energy": {"refund"},
    "double_capture": {"refund"},
    "preauth_hold": {"explain", "escalate_payments"},
    "stuck_session": {"refund"},
    "price_display": {"refund"},
    "roaming_driver": {"redirect_emsp"},
    "valid_charge": {"explain"},
    "unidentifiable": {"ask_info"},
}


def _mismatch(intent: str, action: str) -> bool:
    return action not in EXPECTED.get(intent, {action})
