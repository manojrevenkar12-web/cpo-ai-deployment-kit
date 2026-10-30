"""Build a world: the enterprise systems' contents (observed), the right answers (truth), and the
labelled historical cases the business hands over for evals (the dev sets).

Dev sets come from the weeks before the deployment, labelled the way a team would label its own
past cases; the deployment's own cases are never labelled for the kit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import settings
from ..systems import store
from . import cases, sites, tenders
from .world import Network


def build(out: Path | None = None, log: Any = print) -> dict[str, Any]:
    build_dir = out or settings.BUILD
    truth_dir = build_dir / "truth"
    evals_dir = build_dir / "evals"
    net = Network()
    cfg = net.cfg
    book = cases.Book()
    weeks = cfg["weeks"]
    cases.disputes(net, book, range(-7, 1), "dev")
    cases.tickets(net, book, range(-3, 1), "dev")
    cases.disputes(net, book, range(1, weeks + 1), "live")
    cases.tickets(net, book, range(1, weeks + 1), "live")
    # the acquired network: a pilot export labelled before the deal, then the full export
    so = cfg["site_onboarding"]
    pilot_rows, pilot_docs, pilot_truth = sites.build(net, 40, "pilot", "PIL")
    main_rows, main_docs, main_truth = sites.build(net, so["sites"], "main", "RRN")
    site_rows = [{**r, "_batch": "pilot"} for r in pilot_rows] + [{**r, "_batch": "main"} for r in main_rows]
    per_week = 24
    for batch, truth_rows in (("pilot", pilot_truth), ("main", main_truth)):
        for k, t in enumerate(truth_rows):
            week = 0 if batch == "pilot" else so["arrive_week"] + k // per_week
            cid = f"S-{t['site_code']}"
            book.cases.append({"case_id": cid, "use_case": "site_onboarding", "ref": t["site_code"], "country": "IT",
                               "opened_ts": net.t0 + (week - 1) * 7 * 86400 + 9 * 3600, "week": week})
            complexity = min(1.0, 0.1 + 0.12 * sum(t["defects"].values()))
            book.truth.append({"case_id": cid, "use_case": "site_onboarding", "complexity": round(complexity, 3), **t})
    library, facts = tenders.library(net)
    tq_dev, tt_dev = tenders.questions(net, 60, (-5, 0), "dev")
    tc = cfg["tenders"]
    tq_live, tt_live = tenders.questions(net, tc["questions"], tuple(tc["arrive_weeks"]), "live")
    for q, t in [*zip(tq_dev, tt_dev, strict=True), *zip(tq_live, tt_live, strict=True)]:
        cid = f"T-{q['question_id']}"
        book.cases.append({"case_id": cid, "use_case": "tender_answers", "ref": q["question_id"], "country": "DE",
                           "opened_ts": net.t0 + (q["week"] - 1) * 7 * 86400 + 10 * 3600, "week": q["week"]})
        book.truth.append({"case_id": cid, "use_case": "tender_answers",
                           "complexity": 0.3 if t["answerable"] else 0.5, **t})

    tables: dict[str, list[dict[str, Any]]] = {
        "sites": [
            {"site_id": s.site_id, "country": s.country, "city": s.city, "address": s.address, "lat": s.lat,
             "lon": s.lon, "tz": s.tz, "vat": s.vat, "lang": s.lang}
            for s in net.sites.values()
        ],
        "evses": [{"evse_id": e.evse_id, "site_id": e.site_id, "kind": e.kind, "kw": e.kw} for e in net.evses.values()],
        "tariffs": [
            {"tariff_id": v.tariff_id, "site_id": s.site_id, "kind": k, "valid_from": v.valid_from, "energy": v.energy,
             "peak": v.peak, "idle_per_min": v.idle_per_min, "idle_grace_min": v.idle_grace_min}
            for s in net.sites.values() for k, vs in s.tariffs.items() for v in vs
        ],
        "sessions": [
            {"session_id": x.session_id, "evse_id": x.evse_id, "site_id": x.site_id, "start_ts": x.start,
             "stop_ts": x.stop, "meter_start_wh": x.meter_start_wh, "meter_stop_wh": x.meter_start_wh + x.energy_wh,
             "token": x.token}
            for x in net.sessions.values()
        ],
        "meter_values": [
            {"session_id": x.session_id, "ts": t, "wh": v} for x in net.sessions.values() for t, v in x.meter
        ],
        "status_events": [
            {"evse_id": x.evse_id, "ts": t, "status": st, "error_code": ec}
            for x in net.sessions.values() for t, st, ec in x.statuses
        ],
        "partners": [{"partner_id": p["id"], "name": p["name"], "lang": p["lang"], "country": p["country"]}
                     for p in cfg["partners"]],
        "cdrs": book.cdrs,
        "payments": book.payments,
        "emails": [{**e, "sender": e["from"]} for e in book.emails],
        "tickets": [{**t, "sender": t["from"]} for t in book.tickets],
        "cases": book.cases,
        "site_rows": [{"row_no": k + 1, "data": json.dumps(r, ensure_ascii=False)} for k, r in enumerate(site_rows)],
        "site_documents": [{"doc_id": d["doc_id"], "site_code": d["site_code"], "text": d["text"]}
                           for d in [*pilot_docs, *main_docs]],
        "tender_docs": [{k: d[k] for k in ("doc_id", "title", "date", "lang", "kind")} for d in library],
        "tender_passages": [{"pid": p["pid"], "doc_id": d["doc_id"], "text": p["text"]} for d in library
                            for p in d["passages"]],
        "tender_questions": [*tq_dev, *tq_live],
    }
    store.create(build_dir / "systems.sqlite", tables)
    truth_dir.mkdir(parents=True, exist_ok=True)
    (truth_dir / "cases.json").write_text(json.dumps(book.truth, ensure_ascii=False))
    (truth_dir / "facts.json").write_text(json.dumps(facts, ensure_ascii=False))
    (truth_dir / "world.json").write_text(json.dumps({"t0": net.t0, "weeks": weeks}))
    # labelled history for the kit's evals
    by_case = {t["case_id"]: t for t in book.truth}
    counts = {}
    for uc in settings.USE_CASES:
        dev = [c for c in book.cases if c["use_case"] == uc and c["week"] <= 0]
        labels = [_label(uc, c, by_case[c["case_id"]]) for c in dev]
        d = evals_dir / uc
        d.mkdir(parents=True, exist_ok=True)
        (d / "dev.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in labels) + "\n")
        counts[uc] = {"dev": len(dev), "live": sum(1 for c in book.cases if c["use_case"] == uc and c["week"] > 0)}
    summary = {"sessions": len(net.sessions), "cdrs": len(book.cdrs), "payments": len(book.payments), "cases": counts}
    log(f"world: {summary}")
    return summary


def _label(uc: str, case: dict[str, Any], t: dict[str, Any]) -> dict[str, Any]:
    """What a team's own resolution of a past case records (no simulator internals)."""
    base = {"case_id": case["case_id"], "use_case": uc}
    if uc == "cdr_disputes":
        return {**base, "expected": [
            {"cdr_id": i["cdr_id"], "cause": i["cause"], "decision": i["decision"], "credit_eur": i["credit_eur"]}
            for i in t["items"]
        ], "tags": {"injection": t["injection"]}}
    if uc == "driver_refunds":
        return {**base, "expected": {"action": t["action"], "amount_eur": t["amount_eur"],
                                     "session_id": t["session_id"]},
                "tags": {"kind": t["kind"], "vague": t["vague"], "injection": t["injection"]}}
    if uc == "site_onboarding":
        return {**base, "expected": {"location": t["location"], "needs_person": t["needs_person"]}}
    return {**base, "expected": {"answerable": t["answerable"], "value": t.get("value"),
                                 "value_it": t.get("value_it"), "stale_values": t["stale_values"]}}
