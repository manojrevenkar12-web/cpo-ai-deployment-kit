"""Onboarding an acquired network's sites (owner: Integration Operations, Italy).

The model maps each export row (or commissioning protocol) to location fields: headers, number
formats, connector names, opening hours. Code builds the OCPI-shaped location and checks it: the
coordinates lie in the country (and are swapped back when they are clearly swapped), power units,
connector power consistent with the site, a postal code present, and the AFIR rule that rapid
points take card payment. A location is proposed for publishing only without open issues, and
publishing needs an integration lead's approval; issues go to a person, never to a guess."""

from __future__ import annotations

from typing import Any

from .. import settings
from ..llm.gateway import GatewayError
from .base import Action, Context, Evidence, Proposal, check_access

USE_CASE = "site_onboarding"
FORMAT = {"IEC_62196_T2_COMBO": "CABLE", "IEC_62196_T2": "SOCKET", "CHADEMO": "CABLE"}
POWER_TYPE = {"IEC_62196_T2_COMBO": "DC", "IEC_62196_T2": "AC_3_PHASE", "CHADEMO": "DC"}
NEEDS_PERSON = {
    "missing_postal_code",
    "conflicting_power",
    "no_card_terminal",
    "missing_coordinates",
    "coordinates_outside_country",
    "no_connectors",
}


def build_location(m: dict[str, Any], pol: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    """Returns (location, issues that need a person, automatic fixes)."""
    issues, fixes = [], []
    lat, lon = m.get("latitude"), m.get("longitude")
    b = pol["country_bounds"]["IT"]

    def inside(la: float, lo: float) -> bool:
        return b["lat"][0] <= la <= b["lat"][1] and b["lon"][0] <= lo <= b["lon"][1]

    if lat is None or lon is None:
        issues.append("missing_coordinates")
    elif not inside(lat, lon):
        if inside(lon, lat):
            lat, lon = lon, lat
            fixes.append("swapped_coordinates")
        else:
            issues.append("coordinates_outside_country")
    connectors = []
    for c in m.get("connectors", []):
        for _ in range(int(c["count"])):
            connectors.append(
                {
                    "standard": c["standard"],
                    "format": FORMAT[c["standard"]],
                    "power_type": POWER_TYPE[c["standard"]],
                    "max_electric_power": int(round(c["power_kw"] * 1000)),
                }
            )
    if not connectors:
        issues.append("no_connectors")
    max_kw = m.get("max_power_kw") or 0
    dc = [c for c in connectors if c["power_type"] == "DC" and c["standard"] == "IEC_62196_T2_COMBO"]
    if dc and max_kw >= 100 and any(c["max_electric_power"] < pol["rapid_kw"] * 1000 for c in dc):
        issues.append("conflicting_power")
    rapid = any(c["power_type"] == "DC" and c["max_electric_power"] >= pol["rapid_kw"] * 1000 for c in connectors)
    if rapid and not m.get("card_payment"):
        issues.append("no_card_terminal")
    if not m.get("postal_code"):
        issues.append("missing_postal_code")
    if m.get("open_24_7"):
        hours: dict[str, Any] = {"twentyfourseven": True}
    elif m.get("hours"):
        hours = {
            "twentyfourseven": False,
            "regular_hours": [
                {"weekday": d, "period_begin": h["open"], "period_end": h["close"]}
                for h in m["hours"]
                for d in h["weekdays"]
            ],
        }
    else:
        hours = {}
        issues.append("missing_opening_hours")
    loc = {
        "id": f"IT-{m['site_code']}",
        "name": (m.get("name") or "").title() if (m.get("name") or "").isupper() else m.get("name"),
        "address": m.get("address"),
        "city": m.get("city"),
        "postal_code": m.get("postal_code"),
        "country_code": "IT",
        "coordinates": {"latitude": f"{lat:.5f}", "longitude": f"{lon:.5f}"}
        if lat is not None and lon is not None
        else None,
        "connectors": connectors,
        "opening_times": hours,
        "card_payment": bool(m.get("card_payment")) or not rapid,
    }
    return loc, issues, fixes


def run(case: dict[str, Any], ctx: Context) -> Proposal:
    check_access(ctx, USE_CASE, case["country"])
    pol = settings.policy()[USE_CASE]
    code = case["ref"]
    # the export's own column names vary by network: a row belongs to the site whose code it carries
    rows = [r for r in ctx.systems.site_rows() if any(str(v).strip() == code for k, v in r.items() if k != "row_no")]
    docs = [d for d in ctx.systems.site_documents() if d["site_code"] == code]
    results, reasons = [], []
    evidence = [Evidence("export rows", len(rows), f"docs:site_rows/{code}")]
    if len(rows) > 1:
        evidence.append(Evidence("duplicate rows merged", len(rows), f"docs:site_rows/{code}"))
    source: dict[str, Any] = (
        {"row": {k: v for k, v in rows[0].items() if not k.startswith("_") and k != "row_no"}}
        if rows
        else {"protocol": docs[0]["text"]}
        if docs
        else {}
    )
    if not source:
        raise LookupError(code)
    if "protocol" in source:
        evidence.append(
            Evidence("commissioning protocol", docs[0]["doc_id"], f"docs:site_documents/{docs[0]['doc_id']}")
        )
    try:
        r = ctx.gateway.call("site.map", source)
        results.append(r)
        mapped = r.output
    except GatewayError as e:
        return Proposal(
            case["case_id"],
            USE_CASE,
            case["country"],
            "review",
            {"error": str(e)},
            evidence,
            [],
            None,
            True,
            [f"the row could not be mapped: {e}"],
            [],
            [],
            ctx.principal.oid,
            created_ts=ctx.now or case["opened_ts"],
        )
    mapped["site_code"] = mapped.get("site_code") or code
    loc, issues, fixes = build_location(mapped, pol)
    if fixes:
        evidence.append(Evidence("fixed automatically", fixes, f"docs:site_rows/{code}"))
    blocking = [i for i in issues if i in NEEDS_PERSON or i == "missing_opening_hours"]
    if blocking:
        reasons += [f"needs a person: {i}" for i in blocking]
    actions = []
    if not blocking:
        actions.append(
            Action("publish_location", {"case_id": case["case_id"], "location": loc}, role="integration_lead")
        )
    return Proposal(
        case_id=case["case_id"],
        use_case=USE_CASE,
        country=case["country"],
        decision="publish" if not blocking else "needs_person",
        detail={"location": loc, "issues": issues, "fixes": fixes, "mapped": mapped},
        evidence=evidence,
        actions=actions,
        draft=None,
        needs_review=bool(blocking),
        review_reasons=reasons,
        model_calls=ctx.calls(results),
        quarantined=[],
        prepared_by=ctx.principal.oid,
        created_ts=ctx.now or case["opened_ts"],
    )
