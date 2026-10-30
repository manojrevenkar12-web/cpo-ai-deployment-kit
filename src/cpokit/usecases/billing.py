"""Re-rating a session from what the CSMS recorded, by the operator's published billing rules:

- energy per metering interval is priced by the period its midpoint falls in (peak 17:00-21:00 in
  the charge point's local time, off-peak otherwise), with the tariff version valid at session start;
- idle time starts when energy stops flowing; minutes beyond the grace period are billed, unless the
  charge point reported a connector-lock fault in that time (the driver could not unplug);
- energy and idle costs are rounded to cents separately, then VAT of the site's country is added.

This is the kit's own implementation, written from the rules, not shared with the billing system
it checks (that one lives in the simulator); disagreements between the two are what disputes find."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..systems.store import Systems


def tariff_at(tariffs: list[dict[str, Any]], ts: int) -> dict[str, Any] | None:
    valid = [t for t in tariffs if t["valid_from"] <= ts]
    return valid[-1] if valid else None


def rerate(sys: Systems, session: dict[str, Any], *, peak_hours: tuple[int, int] = (17, 21),
           stop_ts: int | None = None) -> dict[str, Any] | None:
    evse = sys.evse(session["evse_id"])
    site = sys.site(session["site_id"])
    if evse is None or site is None:
        return None
    tv = tariff_at(sys.tariffs(site["site_id"], evse["kind"]), session["start_ts"])
    meter = sys.meter_values(session["session_id"])
    if tv is None or not meter:
        return None
    tz = ZoneInfo(site["tz"])
    signed_wh = session["meter_stop_wh"] - session["meter_start_wh"]
    peak_wh = 0
    for a, b in zip(meter, meter[1:], strict=False):
        mid = (a["ts"] + b["ts"]) // 2
        if peak_hours[0] <= datetime.fromtimestamp(mid, UTC).astimezone(tz).hour < peak_hours[1]:
            peak_wh += b["wh"] - a["wh"]
    peak_wh = min(peak_wh, signed_wh)
    charge_end = meter[-1]["ts"]
    end = session["stop_ts"] if stop_ts is None else stop_ts
    statuses = sys.status_events(session["evse_id"], charge_end, session["stop_ts"])
    lock_fault = any(s["error_code"] == "ConnectorLockFailure" for s in statuses)
    idle_min = max(0.0, (end - charge_end) / 60 - tv["idle_grace_min"])
    energy_cost = (signed_wh - peak_wh) / 1000 * tv["energy"] + peak_wh / 1000 * tv["peak"]
    idle_cost = 0.0 if lock_fault else idle_min * tv["idle_per_min"]
    excl = round(round(energy_cost, 2) + round(idle_cost, 2), 2)
    return {
        "tariff_id": tv["tariff_id"],
        "total_energy_kwh": round(signed_wh / 1000, 3),
        "peak_energy_kwh": round(peak_wh / 1000, 3),
        "idle_minutes": round(idle_min, 1),
        "lock_fault": lock_fault,
        "energy_cost": round(energy_cost, 2),
        "idle_cost": round(idle_cost, 2),
        "total_cost_excl_vat": excl,
        "vat_rate": site["vat"],
        "total_cost_incl_vat": round(excl * (1 + site["vat"]), 2),
        "charge_end_ts": charge_end,
        "tz": site["tz"],
    }
