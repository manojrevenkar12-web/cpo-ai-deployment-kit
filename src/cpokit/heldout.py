"""Blind held-out packs: cases written by someone who has not seen the kit (heldout/WRITING_CASES.md).

For each pack this builds a small world from the pack's description (charge points, tariffs,
sessions with meter values, CDRs as the CPO's billing produced them, payments, emails, tickets,
the export, the bid library), derives the right amounts from the billing rules and the policy
(the writer gives decisions, not amounts), runs every case through the kit once and scores it.

The first run of a pack is written to reports/heldout/<pack>/first_run.json and never rewritten;
later runs go to latest.json. A pack whose failures were studied is marked `regression` in its
STATUS file and a new blind pack is needed."""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from . import settings
from .auth import service_principal
from .kit import evals
from .llm.gateway import Gateway
from .sim.world import DAY, Evse, Network, Session, Site, TariffVersion, bill, org
from .systems import store
from .systems.store import Systems
from .usecases.base import Context


def _ts(local: str, tz: str) -> int:
    return int(datetime.strptime(local, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tz)).timestamp())


class PackWorld:
    def __init__(self, pack: dict[str, Any]) -> None:
        self.pack = pack
        self.countries = org()["countries"]
        self.net = Network.__new__(Network)
        self.net.cfg = org()
        self.net.sites, self.net.evses, self.net.sessions = {}, {}, {}
        self.net._n_sessions = 0
        today = date.fromisoformat(str(pack["today"]))
        self.today = int(datetime(today.year, today.month, today.day, 9, tzinfo=UTC).timestamp())
        self.cdrs: list[dict[str, Any]] = []
        self.payments: list[dict[str, Any]] = []
        self.partners: dict[str, dict[str, Any]] = {}
        self.n = 0

    def evse(self, evse_id: str, kind: str, tariff: dict[str, Any], change: dict[str, Any] | None, start: int) -> Evse:
        cc = evse_id[:2]
        station = evse_id.split("*")[2]
        site_id = f"{cc}-{station}"
        c = self.countries[cc]
        site = self.net.sites.get(site_id)
        if site is None:
            site = Site(
                site_id, cc, "Held-out city", f"Teststraße {station[-3:]}", 50.0, 8.0, c["tz"], c["vat"], c["lang"]
            )
            self.net.sites[site_id] = site
        e = self.net.evses.get(evse_id)
        if e is None:
            e = Evse(evse_id, site_id, kind, 150 if kind == "DC" else 22)
            self.net.evses[evse_id] = e
            site.evses.append(e)
        if kind not in site.tariffs:
            v1 = TariffVersion(
                f"T-{site_id}-{kind}-v1",
                0,
                tariff["energy"],
                tariff["peak"],
                tariff["idle_per_min"],
                tariff["idle_grace_min"],
            )
            site.tariffs[kind] = [v1]
            if change:
                site.tariffs[kind].append(
                    TariffVersion(
                        f"T-{site_id}-{kind}-v2",
                        start + int(change["days_after_start"] * DAY),
                        change["energy"],
                        change["peak"],
                        tariff["idle_per_min"],
                        tariff["idle_grace_min"],
                    )
                )
        return e

    def session(
        self,
        evse: Evse,
        start: int,
        charging_min: float,
        energy_kwh: float,
        idle_min: float,
        token: str,
        lock_fault: bool = False,
        unplugged_after: float | None = None,
    ) -> Session:
        self.n += 1
        site = self.net.sites[evse.site_id]
        charge_end = start + int(charging_min * 60)
        stop = charge_end + int(idle_min * 60)
        meter_start = 10_000_000 + self.n * 1000
        meter = []
        t = start
        while t < charge_end:
            meter.append((t, meter_start + int(energy_kwh * 1000 * (t - start) / max(1, charge_end - start))))
            t += 300
        e_wh = int(round(energy_kwh * 1000))
        meter.append((charge_end, meter_start + e_wh))
        statuses = [(start, "Occupied", ""), (start + 5, "Charging", ""), (charge_end, "SuspendedEV", "")]
        if lock_fault:
            statuses.append((charge_end + 120, "Faulted", "ConnectorLockFailure"))
        if unplugged_after is not None:
            statuses.append((charge_end + int(unplugged_after * 60), "Available", "CableUnplugged"))
        statuses.append((stop, "Available", ""))
        s = Session(
            f"{site.country}-H{self.n:07d}",
            evse.evse_id,
            site.site_id,
            start,
            stop,
            charge_end,
            e_wh,
            meter_start,
            meter,
            statuses,
            token,
            lock_fault,
        )
        self.net.sessions[s.session_id] = s
        return s

    def cdr(self, s: Session, partner: str, billed: dict[str, Any], cdr_id: str, ref: str, sent: int) -> None:
        self.cdrs.append(
            {
                "cdr_id": cdr_id,
                "session_id": ref,
                "partner_id": partner,
                "evse_id": s.evse_id,
                "site_id": s.site_id,
                "start_date_time": "",
                "end_date_time": "",
                "start_ts": s.start,
                **billed,
                "sent_ts": sent,
            }
        )


BILLING = {
    "correct": {},
    "early_tariff": {"tariff_early": True},
    "utc_peak": {"utc_periods": True},
    "idle_on_fault": {"idle_on_fault": True},
}


def build_pack(pack: dict[str, Any], out: Path) -> dict[str, list[dict[str, Any]]]:
    """Writes the pack's systems database to out/systems.sqlite and returns labels per use case."""
    w = PackWorld(pack)
    pol = settings.policy()
    cases, emails, tickets, labels = [], [], [], {uc: [] for uc in settings.USE_CASES}
    for d in pack.get("disputes", []):
        p = d["partner"]
        w.partners[p["id"]] = {
            "partner_id": p["id"],
            "name": p.get("name", p["id"]),
            "lang": p.get("lang", "en"),
            "country": p.get("country", "DE"),
        }
        computed: dict[str, float] = {}
        for rec in d.get("records", []):
            cc = rec["evse"][:2]
            start = _ts(rec["start_local"], w.countries[cc]["tz"])
            e = w.evse(rec["evse"], rec.get("kind", "DC"), rec["tariff"], rec.get("tariff_change"), start)
            if not rec.get("exists", True):
                for c in rec.get("cdrs", []):
                    computed[c["cdr_id"]] = 0.0
                continue
            s = w.session(
                e,
                start,
                rec["charging_minutes"],
                rec["energy_kwh"],
                rec.get("idle_minutes", 0),
                f"app:{p['id']}",
                rec.get("lock_fault", False),
            )
            for j in range(2):  # other drivers of the same partner on that charge point the same day
                other = w.session(e, start + (j + 1) * 3 * 3600 * (-1) ** j, 30, 20.0, 5, f"app:{p['id']}")
                w.cdr(other, p["id"], bill(w.net, other), f"CDR-HO-{w.n:07d}", other.session_id, other.stop + 3600)
            correct = bill(w.net, s)
            seen_session = False
            for i, c in enumerate(rec.get("cdrs", [])):
                kw = dict(BILLING.get(c.get("billing", "correct"), {}))
                if c.get("billing") == "wrong_vat":
                    kw["vat"] = c["wrong_vat"]
                if c.get("billing") == "energy_plus":
                    kw["energy_wh"] = s.energy_wh + int(round(c["energy_plus_kwh"] * 1000))
                billed = bill(w.net, s, **kw)
                ref = f"HUB-{s.session_id}" if c.get("session_ref") == "hub" else s.session_id
                w.cdr(s, p["id"], billed, c["cdr_id"], ref, s.stop + 3600 * (6 + i))
                if seen_session:
                    computed[c["cdr_id"]] = billed["total_cost_incl_vat"]  # a duplicate: credited in full
                else:
                    diff = round(billed["total_cost_incl_vat"] - correct["total_cost_incl_vat"], 2)
                    computed[c["cdr_id"]] = diff if diff >= pol["cdr_disputes"]["min_credit_eur"] else 0.0
                seen_session = True
        eid = f"MAIL-HO-{d['id']}"
        emails.append(
            {
                "email_id": eid,
                "sender": f"roaming@{p['id'].lower()}.example",
                "partner_id": p["id"],
                "subject": "dispute",
                "body": d["email"],
                "received_ts": w.today,
                "lang": p.get("lang", "en"),
            }
        )
        cid = f"D-{d['id']}"
        cases.append(
            {"case_id": cid, "use_case": "cdr_disputes", "ref": eid, "country": "DE", "opened_ts": w.today, "week": 1}
        )
        labels["cdr_disputes"].append(
            {
                "case_id": cid,
                "use_case": "cdr_disputes",
                "expected": [
                    {
                        "cdr_id": x["cdr_id"],
                        "cause": "pack",
                        "decision": x["decision"],
                        "credit_eur": computed.get(x["cdr_id"], 0.0) if x["decision"] == "credit" else 0.0,
                    }
                    for x in d["expected"]
                ],
            }
        )
    for r in pack.get("refunds", []):
        tid = f"TCK-HO-{r['id']}"
        cc = r["country"]
        amount = 0.0
        sid = None
        sp = r.get("session")
        if sp:
            start = _ts(sp["start_local"], w.countries[cc]["tz"])
            e = w.evse(sp["evse"], sp.get("kind", "DC"), sp["tariff"], None, start)
            token = (
                f"card:{sp.get('card_last4')}"
                if sp.get("paid_with", "card") == "card"
                else f"app:{(sp.get('app_partner') or 'EMSP').upper()}"
            )
            s = w.session(
                e,
                start,
                sp["charging_minutes"],
                sp["energy_kwh"],
                sp.get("idle_minutes", 0),
                token,
                unplugged_after=sp.get("unplugged_after_minutes"),
            )
            sid = s.session_id
            b = bill(w.net, s)
            if sp.get("paid_with", "card") == "card":
                pay = sp.get("payments") or {}
                tv = w.net.sites[s.site_id].tariffs[e.kind][0]
                shown = pay.get("shown_price") or tv.energy
                captured = pay.get("captured_override_eur") or b["total_cost_incl_vat"]
                _pay(w, s, "preauth", pay.get("preauth_eur", 100), s.start - 30, sp["card_last4"], shown)
                for k in range(int(pay.get("captures", 1))):
                    _pay(w, s, "capture", captured, s.stop + 60 + k * 7200, sp["card_last4"], None)
                if pay.get("released", True):
                    _pay(w, s, "release", pay.get("preauth_eur", 100), s.stop + 120, sp["card_last4"], None)
                if r["expected"]["action"] == "refund":
                    pol_r = pol["driver_refunds"]
                    if int(pay.get("captures", 1)) > 1:
                        amount = captured * (int(pay["captures"]) - 1)
                    elif sp["energy_kwh"] < pol_r["no_energy_kwh"]:
                        amount = captured
                    elif sp.get("unplugged_after_minutes") is not None:
                        unplug = s.charge_end + int(sp["unplugged_after_minutes"] * 60)
                        amount = captured - bill(w.net, s, stop=unplug)["total_cost_incl_vat"]
                    elif pay.get("shown_price") is not None and pay["shown_price"] < tv.energy:
                        amount = (
                            b["total_energy_kwh"] * (tv.energy - pay["shown_price"]) * (1 + w.net.sites[s.site_id].vat)
                        )
            for j in range(int(r.get("other_sessions_same_evse", 2))):
                last4 = f"{(j * 2731 + 1009) % 10000:04d}"
                o = w.session(e, start + (j + 1) * 2 * 3600 * (-1) ** j, 25, 15.0, 5, f"card:{last4}")
                ob = bill(w.net, o)
                _pay(w, o, "preauth", 100, o.start - 30, last4, w.net.sites[o.site_id].tariffs[e.kind][0].energy)
                _pay(w, o, "capture", ob["total_cost_incl_vat"], o.stop + 60, last4, None)
                _pay(w, o, "release", 100, o.stop + 120, last4, None)
        tickets.append(
            {
                "ticket_id": tid,
                "country": cc,
                "lang": w.countries[cc]["lang"],
                "channel": "email",
                "sender": "driver@example.com",
                "text": r["ticket"],
                "opened_ts": w.today,
            }
        )
        cid = f"R-{tid}"
        cases.append(
            {"case_id": cid, "use_case": "driver_refunds", "ref": tid, "country": cc, "opened_ts": w.today, "week": 1}
        )
        labels["driver_refunds"].append(
            {
                "case_id": cid,
                "use_case": "driver_refunds",
                "expected": {"action": r["expected"]["action"], "amount_eur": round(amount, 2), "session_id": sid},
                "tags": {"kind": r["expected"]["action"]},
            }
        )
    sites = pack.get("sites") or {}
    site_rows = [
        {"row_no": k + 1, "data": json.dumps(row, ensure_ascii=False)} for k, row in enumerate(sites.get("rows", []))
    ]
    site_docs = [
        {"doc_id": f"PROT-{p['site_code']}", "site_code": p["site_code"], "text": p["text"]}
        for p in sites.get("protocols", [])
    ]
    for exp in sites.get("expected", []):
        cid = f"S-{exp['site_code']}"
        cases.append(
            {
                "case_id": cid,
                "use_case": "site_onboarding",
                "ref": exp["site_code"],
                "country": "IT",
                "opened_ts": w.today,
                "week": 1,
            }
        )
        labels["site_onboarding"].append(
            {
                "case_id": cid,
                "use_case": "site_onboarding",
                "expected": {
                    "needs_person": ["pack"] if exp.get("needs_person") else [],
                    "location": _location(exp["site_code"], exp.get("location") or {}),
                },
            }
        )
    t = pack.get("tenders") or {}
    docs, passages, questions = [], [], []
    for d in t.get("library", []):
        docs.append({k: d[k] for k in ("doc_id", "title", "date", "lang")} | {"kind": "pack"})
        passages += [
            {"pid": f"{d['doc_id']}#{k + 1}", "doc_id": d["doc_id"], "text": x} for k, x in enumerate(d["passages"])
        ]
    for q in t.get("questions", []):
        qid = f"Q-HO-{q['id']}"
        questions.append(
            {
                "question_id": qid,
                "lang": "it" if " il " in f" {q['text'].lower()} " else "en",
                "text": q["text"],
                "week": 1,
            }
        )
        cid = f"T-{qid}"
        cases.append(
            {"case_id": cid, "use_case": "tender_answers", "ref": qid, "country": "DE", "opened_ts": w.today, "week": 1}
        )
        e = q["expected"]
        labels["tender_answers"].append(
            {
                "case_id": cid,
                "use_case": "tender_answers",
                "expected": {
                    "answerable": bool(e.get("answerable")),
                    "value": e.get("value"),
                    "value_it": e.get("value_it"),
                    "stale_values": e.get("stale_values", []),
                },
            }
        )
    net = w.net
    tables = {
        "sites": [
            {
                "site_id": s.site_id,
                "country": s.country,
                "city": s.city,
                "address": s.address,
                "lat": s.lat,
                "lon": s.lon,
                "tz": s.tz,
                "vat": s.vat,
                "lang": s.lang,
            }
            for s in net.sites.values()
        ],
        "evses": [{"evse_id": e.evse_id, "site_id": e.site_id, "kind": e.kind, "kw": e.kw} for e in net.evses.values()],
        "tariffs": [
            {
                "tariff_id": v.tariff_id,
                "site_id": s.site_id,
                "kind": k,
                "valid_from": v.valid_from,
                "energy": v.energy,
                "peak": v.peak,
                "idle_per_min": v.idle_per_min,
                "idle_grace_min": v.idle_grace_min,
            }
            for s in net.sites.values()
            for k, vs in s.tariffs.items()
            for v in vs
        ],
        "sessions": [
            {
                "session_id": x.session_id,
                "evse_id": x.evse_id,
                "site_id": x.site_id,
                "start_ts": x.start,
                "stop_ts": x.stop,
                "meter_start_wh": x.meter_start_wh,
                "meter_stop_wh": x.meter_start_wh + x.energy_wh,
                "token": x.token,
            }
            for x in net.sessions.values()
        ],
        "meter_values": [
            {"session_id": x.session_id, "ts": a, "wh": b} for x in net.sessions.values() for a, b in x.meter
        ],
        "status_events": [
            {"evse_id": x.evse_id, "ts": a, "status": b, "error_code": c}
            for x in net.sessions.values()
            for a, b, c in x.statuses
        ],
        "partners": list(w.partners.values()),
        "cdrs": w.cdrs,
        "payments": w.payments,
        "emails": emails,
        "tickets": tickets,
        "cases": cases,
        "site_rows": site_rows,
        "site_documents": site_docs,
        "tender_docs": docs,
        "tender_passages": passages,
        "tender_questions": questions,
    }
    store.create(out / "systems.sqlite", tables)
    return labels


def _pay(w: PackWorld, s: Session, kind: str, amount: float, ts: int, last4: str, shown: float | None) -> None:
    w.n += 1
    w.payments.append(
        {
            "payment_id": f"PH{w.n:07d}",
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


def _location(code: str, loc: dict[str, Any]) -> dict[str, Any]:
    if not loc:
        return {}
    if loc.get("open_24_7"):
        hours: dict[str, Any] = {"twentyfourseven": True}
    else:
        hours = {
            "twentyfourseven": False,
            "regular_hours": [
                {"weekday": d, "period_begin": h["open"], "period_end": h["close"]}
                for h in loc.get("hours", [])
                for d in h["weekdays"]
            ],
        }
    std = {"IEC_62196_T2_COMBO": "DC", "CHADEMO": "DC", "IEC_62196_T2": "AC_3_PHASE"}
    fmt = {"IEC_62196_T2_COMBO": "CABLE", "CHADEMO": "CABLE", "IEC_62196_T2": "SOCKET"}
    return {
        "id": f"IT-{code}",
        "name": loc.get("name"),
        "address": loc.get("address"),
        "city": loc.get("city"),
        "postal_code": str(loc["postal_code"]) if loc.get("postal_code") else None,
        "country_code": "IT",
        "coordinates": {"latitude": f"{float(loc['latitude']):.5f}", "longitude": f"{float(loc['longitude']):.5f}"},
        "connectors": [
            {
                "standard": c["standard"],
                "format": fmt[c["standard"]],
                "power_type": std[c["standard"]],
                "max_electric_power": int(round(float(c["power_kw"]) * 1000)),
            }
            for c in loc.get("connectors", [])
            for _ in range(int(c.get("count", 1)))
        ],
        "opening_times": hours,
        "card_payment": bool(loc.get("card_payment")),
    }


def run_pack(name: str, log: Any = print) -> dict[str, Any]:
    folder = settings.HELDOUT / name
    pack = yaml.safe_load((folder / "pack.yaml").read_text())
    status = (folder / "STATUS").read_text().strip() if (folder / "STATUS").exists() else "blind"
    out = settings.BUILD / "heldout" / name
    out.mkdir(parents=True, exist_ok=True)
    labels = build_pack(pack, out)
    ctx = Context(Systems(out / "systems.sqlite"), Gateway(), service_principal())
    t0 = time.time()
    result: dict[str, Any] = {
        "pack": name,
        "status_at_run": status,
        "ran": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "use_cases": {},
    }
    for uc, labs in labels.items():
        if not labs:
            continue
        m = evals.run(uc, labs, ctx)
        result["use_cases"][uc] = {"metrics": m, "thresholds": evals.check(uc, m)}
        acc = next(v for k, v in m.items() if k.endswith("accuracy"))
        log(f"{name} {uc}: {acc:.0%} of {len(labs)}")
    result["seconds"] = round(time.time() - t0, 1)
    dest = settings.REPORTS / "heldout" / name
    dest.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, indent=1, ensure_ascii=False, default=str) + "\n"
    if not (dest / "first_run.json").exists():
        (dest / "first_run.json").write_text(text)
    (dest / "latest.json").write_text(text)
    return result
