"""The work that arrives: eMSPs' CDR disputes and drivers' refund tickets, with the sessions,
CDRs and payments behind them, and the right answer for each (truth)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .. import settings
from . import texts
from .world import DAY, Network, Session, at, bill, iso, local, rng

PARTNER_APPS = {"VOLTPASS": "Voltpass", "LADEFREUND": "Ladefreund", "PLUGPILOT": "PlugPilot", "LADDKOMPIS": "Laddkompis"}


@dataclass
class Book:
    """Everything the enterprise systems hold, plus the truth beside it."""

    cdrs: list[dict[str, Any]] = field(default_factory=list)
    payments: list[dict[str, Any]] = field(default_factory=list)
    emails: list[dict[str, Any]] = field(default_factory=list)
    tickets: list[dict[str, Any]] = field(default_factory=list)
    cases: list[dict[str, Any]] = field(default_factory=list)  # observed: what arrived, when, where
    truth: list[dict[str, Any]] = field(default_factory=list)  # per case: the right outcome
    n_cdr: int = 0
    n_pay: int = 0

    def cdr(self, net: Network, s: Session, partner: str, billed: dict[str, Any], *, ref: str | None = None) -> str:
        self.n_cdr += 1
        cid = f"CDR-{net.sites[s.site_id].country}-{self.n_cdr:07d}"
        self.cdrs.append(
            {
                "cdr_id": cid,
                "session_id": ref or s.session_id,
                "partner_id": partner,
                "evse_id": s.evse_id,
                "site_id": s.site_id,
                "start_date_time": iso(s.start),
                "end_date_time": iso(s.stop),
                "start_ts": s.start,
                **billed,
                "sent_ts": s.stop + 3600 * 6,
            }
        )
        return cid

    def pay(self, s: Session, kind: str, amount: float, ts: int, *, last4: str, shown: float | None = None) -> None:
        self.n_pay += 1
        self.payments.append(
            {
                "payment_id": f"P{self.n_pay:08d}",
                "session_id": s.session_id,
                "evse_id": s.evse_id,
                "site_id": s.site_id,
                "type": kind,
                "amount": round(amount, 2),
                "ts": ts,
                "last4": last4,
                "shown_price_per_kwh": shown,
            }
        )


def _partner_for(r: np.random.Generator, partners: list[dict[str, Any]]) -> dict[str, Any]:
    shares = np.array([p["share"] for p in partners])
    return partners[int(r.choice(len(partners), p=shares / shares.sum()))]


def _pick(r: np.random.Generator, shares: dict[str, float]) -> str:
    keys = list(shares)
    p = np.array([shares[k] for k in keys])
    return keys[int(r.choice(len(keys), p=p / p.sum()))]


def disputes(net: Network, book: Book, weeks: range, stream: str) -> None:
    cfg = net.cfg["disputes"]
    partners = net.cfg["partners"]
    policy = settings.policy()["cdr_disputes"]
    r = rng("disputes", stream)
    n_email = 0
    for w in weeks:
        n_items = int(r.integers(cfg["per_week"][0], cfg["per_week"][1] + 1))
        made = 0
        while made < n_items:
            partner = _partner_for(r, partners)
            k = min(n_items - made, int(r.choice([1, 1, 1, 2, 3])))
            arrive = at(net, w, r)
            items, truths = [], []
            for _ in range(k):
                item, truth = _dispute_item(net, book, partner, arrive, r, cfg, policy)
                items.append(item)
                truths.append(truth)
            made += k
            n_email += 1
            injection = bool(r.random() < cfg["injection_share"])
            subject, body = texts.dispute_email(partner, items, r, injection)
            eid = f"MAIL-{stream}-{n_email:05d}"
            book.emails.append(
                {"email_id": eid, "from": f"roaming@{partner['id'].lower()}.example", "partner_id": partner["id"],
                 "subject": subject, "body": body, "received_ts": arrive, "lang": partner["lang"]}
            )
            complexity = min(1.0, 0.15 * (k - 1) + (0.35 if partner["style"] in ("fuzzy", "hub") else 0.0)
                             + float(np.mean([t["difficulty"] for t in truths])))
            case_id = f"D-{eid}"
            book.cases.append(
                {"case_id": case_id, "use_case": "cdr_disputes", "ref": eid, "country": "DE",
                 "opened_ts": arrive, "week": w}
            )
            book.truth.append(
                {"case_id": case_id, "use_case": "cdr_disputes", "complexity": round(complexity, 3),
                 "injection": injection, "items": truths}
            )


DIFFICULTY = {"no_error": 0.25, "tariff_version": 0.35, "peak_window": 0.45, "duplicate": 0.2, "idle_fault": 0.3,
              "vat_rate": 0.2, "energy_mismatch": 0.35, "unknown_session": 0.15}


def _driver_session(net: Network, r: np.random.Generator, start: int, partner: str, *, site=None, kind=None, **kw):
    sites = list(net.sites.values())
    for _ in range(200):
        site_ = site or sites[int(r.integers(len(sites)))]
        evses = [e for e in site_.evses if kind is None or e.kind == kind]
        if evses:
            break
        site = None
    e = evses[int(r.integers(len(evses)))]
    s = net.new_session(e, start, r, token=f"app:{partner}", **kw)
    return s


def _dispute_item(net, book, partner, arrive, r, cfg, policy) -> tuple[dict[str, Any], dict[str, Any]]:
    cause = _pick(r, cfg["causes"])
    pid = partner["id"]
    start = arrive - int(r.integers(2, 25)) * DAY + int(r.integers(-6, 6)) * 3600
    s: Session | None = None
    billed = correct = None
    for _attempt in range(40):
        if cause == "tariff_version":
            changed = [(si, k, v) for si, k, v in net.changed_sites() if v.valid_from - 7 * DAY < arrive - 2 * DAY]
            if not changed:
                cause = "no_error"
                continue
            site, kind, v2 = changed[int(r.integers(len(changed)))]
            st = min(v2.valid_from - int(r.integers(3600, 7 * DAY)), arrive - DAY - int(r.integers(0, 5 * DAY)))
            s = _driver_session(net, r, st, pid, site=site, kind=kind)
            billed, correct = bill(net, s, tariff_early=True), bill(net, s)
        elif cause == "peak_window":
            s = _driver_session(net, r, start, pid, kind="DC")
            tz_start = local(s.start, net.sites[s.site_id].tz)
            shift = (21 - tz_start.hour) * 3600 - tz_start.minute * 60 + int(r.integers(-40, 70)) * 60
            net.sessions.pop(s.session_id)
            s = _driver_session(net, r, s.start + shift, pid, site=net.sites[s.site_id], kind="DC",
                                energy_kwh=float(r.uniform(25, 70)))
            billed, correct = bill(net, s, utc_periods=True), bill(net, s)
        elif cause == "idle_fault":
            s = _driver_session(net, r, start, pid, lock_fault=True, idle_min=float(r.uniform(45, 160)))
            billed, correct = bill(net, s, idle_on_fault=True), bill(net, s)
        elif cause == "vat_rate":
            s = _driver_session(net, r, start, pid)
            own = net.sites[s.site_id].vat
            other = [c["vat"] for c in net.cfg["countries"].values() if abs(c["vat"] - own) > 0.005]
            billed, correct = bill(net, s, vat=other[int(r.integers(len(other)))]), bill(net, s)
        elif cause == "energy_mismatch":
            s = _driver_session(net, r, start, pid)
            billed, correct = bill(net, s, energy_wh=s.energy_wh + int(r.uniform(800, 6000))), bill(net, s)
        else:  # no_error, duplicate, unknown_session
            idle = float(r.uniform(40, 120)) if r.random() < 0.3 else None
            s = _driver_session(net, r, start, pid, idle_min=idle)
            billed = correct = bill(net, s)
        diff = billed["total_cost_incl_vat"] - correct["total_cost_incl_vat"]
        if cause in ("no_error", "duplicate", "unknown_session") or diff >= 0.3:
            break
        net.sessions.pop(s.session_id, None)
    else:  # no draw gave a difference worth disputing: the partner disputes a correct CDR
        cause = "no_error"
        s = _driver_session(net, r, start, pid)
        billed = correct = bill(net, s)
    assert s is not None and billed is not None and correct is not None
    # what the CDR system holds: the session's CDR(s) and those of its neighbours
    for nb in net.neighbours(s, r):
        if r.random() < 0.5:
            nb.token = f"app:{pid}"
            book.cdr(net, nb, pid, bill(net, nb))
    hub_ref = f"HUB-{s.session_id}" if partner["style"] == "hub" else None
    cdr_id = book.cdr(net, s, pid, billed, ref=hub_ref)
    credit = 0.0
    decision = "reject"
    if cause == "duplicate":
        cdr_id = book.cdr(net, s, pid, billed, ref=f"HUB-{s.session_id}" if r.random() < 0.5 else None)
        credit, decision = billed["total_cost_incl_vat"], "credit"
    elif cause not in ("no_error", "unknown_session"):
        credit = round(billed["total_cost_incl_vat"] - correct["total_cost_incl_vat"], 2)
        decision = "credit" if credit >= policy["min_credit_eur"] else "reject"
    claim = list(texts.CLAIM_FOR_CAUSE[cause])[int(r.integers(len(texts.CLAIM_FOR_CAUSE[cause])))]
    if credit > 0:
        claimed = round(credit * float(r.uniform(*net.cfg["disputes"]["claim_exaggeration"])), 2)
    else:
        claimed = round(billed["total_cost_incl_vat"] * float(r.uniform(0.2, 1.0)), 2)
    site = net.sites[s.site_id]
    ref_id, evse_id = s.session_id, s.evse_id
    if cause == "unknown_session":
        net.sessions.pop(s.session_id)
        book.cdrs = [c for c in book.cdrs if c["cdr_id"] != cdr_id]
        cdr_id = f"CDR-{site.country}-9{int(r.integers(100000, 999999))}"
        ref_id = f"{site.country}-S9{int(r.integers(100000, 999999))}"
    fuzzy = partner["style"] == "fuzzy" and r.random() < net.cfg["disputes"]["fuzzy_reference_share"]
    clock_tz = site.tz
    if fuzzy and r.random() < net.cfg["disputes"]["partner_clock_share"]:
        clock_tz = net.cfg["countries"][partner["country"]]["tz"]
    lt = local(s.start, clock_tz)
    item = {
        "cdr_id": cdr_id if not fuzzy else "",
        "session_ref": ref_id,
        "evse_id": evse_id,
        "local_day": lt.strftime("%d %B"),
        "local_time": f"{lt.hour % 12 or 12}:{(lt.minute // 5) * 5:02d} {'pm' if lt.hour >= 12 else 'am'}",
        "start_utc": iso(s.start),
        "kwh": billed["total_energy_kwh"],
        "billed": billed["total_cost_incl_vat"],
        "claim": claim,
        "claimed": claimed,
    }
    truth = {
        "cdr_id": cdr_id,
        "session_id": None if cause == "unknown_session" else s.session_id,
        "cause": cause,
        "decision": decision,
        "credit_eur": credit,
        "claimed_eur": claimed,
        "difficulty": DIFFICULTY[cause],
        "fuzzy": fuzzy,
    }
    return item, truth


# ---- drivers' refund tickets --------------------------------------------------------------------
def tickets(net: Network, book: Book, weeks: range, stream: str) -> None:
    cfg = net.cfg["refunds"]
    pol = settings.policy()["driver_refunds"]
    r = rng("tickets", stream)
    n = 0
    for w in weeks:
        summer = 1.0 + (net.cfg["people"]["summer_load"] if 5 <= w <= 13 else 0.0)
        for cc, c in net.cfg["countries"].items():
            k = int(r.poisson(cfg["per_week_per_site"] * c["sites"] * summer))
            sites = [s for s in net.sites.values() if s.country == cc]
            for _ in range(k):
                n += 1
                kind = _pick(r, cfg["kinds"])
                site = sites[int(r.integers(len(sites)))]
                arrive = at(net, w, r)
                tid = f"TCK-{stream}-{n:06d}"
                t = _ticket(net, book, site, kind, arrive, r, cfg, pol, tid)
                book.cases.append(
                    {"case_id": f"R-{tid}", "use_case": "driver_refunds", "ref": tid, "country": cc,
                     "opened_ts": arrive, "week": w}
                )
                book.truth.append({"case_id": f"R-{tid}", "use_case": "driver_refunds", **t})


def _ticket(net, book: Book, site, kind, arrive, r, cfg, pol, tid) -> dict[str, Any]:
    lang = site.lang
    vague = bool(r.random() < cfg["vague_share"])
    injection = bool(r.random() < cfg["injection_share"])
    days_ago = int(r.integers(1, 6)) if kind != "preauth_hold" else int(r.choice([2, 3, 4, 5, 9, 11, 14]))
    start = arrive - days_ago * DAY - int(r.integers(0, 12)) * 3600
    last4 = f"{int(r.integers(0, 10000)):04d}"
    e = site.evses[int(r.integers(len(site.evses)))]
    shown = None
    app = None
    action, amount, needs_approval = "explain", 0.0, False
    if kind == "roaming_driver":
        partner = list(PARTNER_APPS)[int(r.integers(len(PARTNER_APPS)))]
        app = PARTNER_APPS[partner]
        s = net.new_session(e, start, r, token=f"app:{partner}")
        b = bill(net, s)
        book.cdr(net, s, partner, b)
        mention = b["total_cost_incl_vat"]
        action = "redirect_emsp"
        last4 = None
    elif kind == "unidentifiable":
        s = None
        mention = round(float(r.uniform(8, 60)), 2)
        action = "ask_info"
        last4 = None if r.random() < 0.5 else last4
    else:
        energy = float(r.uniform(0.0, 0.12)) if kind == "no_energy" else None
        idle = None
        if kind == "stuck_session":
            idle = float(r.uniform(180, 720))
        s = net.new_session(e, start, r, token=f"card:{last4}", energy_kwh=energy, idle_min=idle)
        b = bill(net, s)
        tv = net.tariff_at(site, e.kind, s.start)
        shown_price = tv.energy
        if kind == "price_display":
            shown_price = round(tv.energy - float(r.uniform(0.04, 0.12)), 2)
            shown = shown_price
        captured = b["total_cost_incl_vat"]
        if kind == "no_energy":
            captured = round(float(r.uniform(4, 15)), 2)
        hold = 100.0 if e.kind == "DC" else 50.0
        book.pay(s, "preauth", hold, s.start - 30, last4=last4, shown=shown_price)
        book.pay(s, "capture", captured, s.stop + 60, last4=last4)
        mention = captured
        if kind == "double_capture":
            book.pay(s, "capture", captured, s.stop + 3600 * int(r.integers(2, 30)), last4=last4)
            action, amount = "refund", captured
        elif kind == "preauth_hold":
            mention = hold
            if days_ago >= pol["preauth_release_days"]:
                action = "escalate_payments"
            else:
                action = "explain"
        else:
            book.pay(s, "release", hold, s.stop + 120, last4=last4)
        if kind == "no_energy":
            action, amount = "refund", captured
        elif kind == "stuck_session":
            unplug = s.charge_end + int(r.uniform(10, 40)) * 60
            s.statuses.insert(-1, (unplug, "Available", "CableUnplugged"))
            fair = bill(net, s, stop=unplug)["total_cost_incl_vat"]
            action, amount = "refund", round(captured - fair, 2)
        elif kind == "price_display":
            per_kwh = b["total_energy_kwh"] * (tv.energy - shown_price) * (1 + site.vat)
            action, amount = "refund", round(per_kwh, 2)
        for nb in net.neighbours(s, r, (2, 6)):
            other = nb.token.split(":")[1]
            book.pay(nb, "preauth", hold, nb.start - 30, last4=other, shown=shown_price)
            book.pay(nb, "capture", bill(net, nb)["total_cost_incl_vat"], nb.stop + 60, last4=other)
            book.pay(nb, "release", hold, nb.stop + 120, last4=other)
    if action == "refund" and amount < pol["min_refund_eur"]:
        action, amount = "explain", 0.0
    needs_approval = action == "refund" and amount > pol["approval_above_eur"]
    off = float(r.uniform(*cfg["time_off_hours"])) * (1 if r.random() < 0.5 else -1)
    when = texts.when_text(local(start + int(off * 3600), site.tz), lang, r) if s is not None else ""
    shown_evse = e.evse_id
    if r.random() < cfg["evse_typo_share"]:
        head, num, conn = e.evse_id.rsplit("*", 2)[0], e.evse_id.split("*")[2], e.evse_id.split("*")[3]
        digits = num[1:]
        swapped = digits[:2] + digits[3] + digits[2] if digits[2] != digits[3] else digits[:3] + str((int(digits[3]) + 1) % 10)
        shown_evse = f"{head}*E{swapped}*{conn}"
    email, text = texts.ticket_text(
        kind, lang, r, amount=mention, evse=shown_evse, address=site.address, city=site.city, when=when,
        last4=last4, shown=shown, app=app, vague=vague, injection=injection,
    )
    book.tickets.append(
        {"ticket_id": tid, "country": site.country, "lang": lang, "channel": "email", "from": email,
         "text": text, "opened_ts": arrive}
    )
    complexity = min(1.0, {"no_energy": 0.2, "double_capture": 0.25, "preauth_hold": 0.3, "stuck_session": 0.55,
                           "price_display": 0.5, "roaming_driver": 0.2, "valid_charge": 0.35,
                           "unidentifiable": 0.3}[kind] + (0.3 if vague else 0.0) + float(r.uniform(-0.1, 0.1)))
    return {
        "kind": kind,
        "session_id": s.session_id if s else None,
        "action": action,
        "amount_eur": round(amount, 2),
        "needs_approval": needs_approval,
        "complexity": round(max(0.0, complexity), 3),
        "injection": injection,
        "vague": vague,
    }
