"""`cpokit export-web`: the desk's data files (web/public/data), written from the reports, the specs
and the kit's own store. The comparison with the simulator's truth comes from reports/evaluation.json
and is labelled as such on the desk: it exists only because this organisation is simulated."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from . import settings
from .kit import spec
from .kitstore import KitStore
from .measure.adoption import rollout
from .systems.store import Systems

OUT = settings.ROOT / "web" / "public" / "data"


def _read(name: str) -> Any:
    return json.loads((settings.REPORTS / name).read_text())


def _put(name: str, data: Any) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":")) + "\n")


def write() -> None:
    adoption, impact, evaluation, gate = _read("adoption.json"), _read("impact.json"), _read("evaluation.json"), _read("gate.json")
    summary = _read("summary.json")
    store = KitStore(settings.KIT_DB)
    systems = Systems(settings.SYSTEMS)
    portfolio = []
    for uc in settings.USE_CASES:
        s = spec.load(uc)
        raw = settings.usecase(uc)
        ready = _read(f"readiness/{uc}.json")
        a, i, e = adoption[uc], impact[uc], evaluation[uc]
        r = i.get("rollout") or {}
        portfolio.append({
            "id": uc, "name": s.name, "owner": s.owner, "priority": s.priority(), "score": s.discovery.score,
            "person_days": s.sprint.person_days, "ready": ready["passed"], "users": s.discovery.users,
            "eligible_people": a["eligible_people"], "adopted_people": a["adopted_people"],
            "usage_share_live": a["usage_share_live"], "acceptance": a["acceptance"],
            "impact_pct": r.get("pct"), "impact_ci": r.get("ci_pct"), "impact_method": r.get("method"),
            "impact_note": i.get("note"), "hours_saved": i.get("hours_saved"), "hours_saved_ci": i.get("hours_saved_ci"),
            "value_eur": i.get("value_eur"), "money_moved_eur": a["money_moved_eur"],
            "first_live_week": min(w["week"] for w in raw["rollout"]["waves"]),
        })
        _put(f"usecases/{uc}.json", {
            "id": uc, "name": s.name, "owner": s.owner,
            "discovery": s.discovery.model_dump(), "models_read": s.models_read, "code_decides": s.code_decides,
            "approvals": s.approvals, "sprint": s.sprint.model_dump(), "rollout": raw["rollout"],
            "handover": raw["handover"], "monitoring": raw["monitoring"],
            "readiness": ready, "adoption": a, "impact": i, "evaluation": e,
            "handover_pack": (settings.REPORTS / "handover" / f"{uc}.md").read_text(),
        })
    _put("portfolio.json", {"generated": summary, "gate": gate, "use_cases": portfolio})
    # the staggered rollout of driver refunds: who could use it when, and how much they did
    live = rollout("driver_refunds")
    shown = {e["case_id"] for e in store.events("driver_refunds") if e["event"] == "proposal_shown"}
    cells: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])
    for w in systems.worklog("driver_refunds"):
        c = cells[(w["country"], w["week"])]
        c[0] += 1
        c[1] += w["case_id"] in shown
    weeks = sorted({w for _, w in cells})
    _put("rollout.json", {
        "use_case": "driver_refunds", "weeks": weeks,
        "countries": [{"country": cc, "launch": live.get(cc),
                       "cells": [{"week": w, "cases": cells[(cc, w)][0], "used": cells[(cc, w)][1]} for w in weeks]}
                      for cc in sorted({c for c, _ in cells}, key=lambda c: (live.get(c, 99), c))],
        "event_time": impact["driver_refunds"].get("rollout", {}).get("event_time", {}),
    })
    picks: list[dict[str, Any]] = []
    for uc in settings.USE_CASES:
        props = store.proposals(uc, limit=400)
        flagged = [p for p in props if p["needs_review"]][:5]
        acting = [p for p in props if p["actions"] and not p["needs_review"]][:5]
        picks += flagged + acting
    picks.sort(key=lambda p: -p["created_ts"])
    _put("proposals.json", [{k: p[k] for k in ("proposal_id", "case_id", "use_case", "country", "decision", "detail",
                                               "evidence", "actions", "draft", "needs_review", "review_reasons",
                                               "quarantined", "model_calls", "created_ts")} for p in picks])
