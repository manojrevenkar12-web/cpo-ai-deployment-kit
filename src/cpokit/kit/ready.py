"""The go-live gate. A use case reaches users only when every check passes; the result is written
to reports/readiness/<id>.json and shown on the desk."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import settings
from ..auth import Principal
from ..usecases import REGISTRY
from ..usecases.base import Context, NotAllowed
from . import evals, spec


def access_checks(uc: str, ctx: Context) -> list[str]:
    """Someone from another function, and someone from another country, must be refused."""
    problems = []
    cases = ctx.systems.cases(uc, None)
    if not cases:
        return ["no cases to test access with"]
    case = cases[0]
    outsider = Principal(
        "t-outsider",
        "outsider",
        frozenset({"bid_team" if uc != "tender_answers" else "customer_service"}),
        frozenset({"*"}),
        frozenset(),
    )
    try:
        REGISTRY[uc](case, Context(ctx.systems, ctx.gateway, outsider))
        problems.append("a person from another function was not refused")
    except NotAllowed:
        pass
    function = settings.access()["use_case_functions"][uc][0]
    elsewhere = "RO" if case["country"] != "RO" else "SE"
    foreign = Principal("t-foreign", "foreign", frozenset({function}), frozenset({elsewhere}), frozenset())
    try:
        REGISTRY[uc](case, Context(ctx.systems, ctx.gateway, foreign))
        problems.append("a person from another country was not refused")
    except NotAllowed:
        pass
    return problems


def check(uc: str, ctx: Context, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = settings.kit()
    raw = settings.usecase(uc)
    results: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        results.append({"check": name, "passed": bool(ok), "detail": detail})

    miss = spec.missing_sections(uc)
    try:
        s = spec.load(uc)
        add("spec_complete", not miss, "all sections present" if not miss else f"missing: {miss}")
    except Exception as e:  # pydantic validation
        add("spec_complete", False, str(e)[:200])
        s = None
    days = raw.get("sprint", {}).get("person_days", 99)
    add(
        "sprint_within_budget",
        days <= cfg["sprint_max_person_days"],
        f"{days} person-days planned (limit {cfg['sprint_max_person_days']})",
    )
    labels = evals.load_labels(settings.BUILD / "evals" / uc / "dev.jsonl")
    m = metrics or evals.run(uc, labels, ctx)
    th = evals.check(uc, m)
    failed = [t for t in th if not t["passed"]]
    add(
        "evals_pass",
        not failed,
        "all thresholds met"
        if not failed
        else "; ".join(f"{t['metric']}={t['value']} vs {t['target']}" for t in failed),
    )
    inj = [k for k in m if k.startswith("injected_")]
    add(
        "no_money_from_injected_text",
        all(m[k] == 0 for k in inj),
        ", ".join(f"{k}={m[k]}" for k in inj) or "no money moves in this use case",
    )
    probs = access_checks(uc, ctx)
    add("access_enforced", not probs, "outsiders refused" if not probs else "; ".join(probs))
    kinds = set(cfg["money_actions"]) | set(cfg["publish_actions"])
    sample = [REGISTRY[uc](ctx.systems.case(lab["case_id"]), ctx) for lab in labels[:60]]
    unguarded = [
        a
        for p in sample
        for a in p.actions
        if a.kind in kinds
        and a.role is None
        and not (a.kind == "refund" and (a.amount or 0) <= settings.policy()["driver_refunds"]["approval_above_eur"])
    ]
    add(
        "approvals_on_money_and_publishing",
        not unguarded,
        "every money or publishing action names an approver role" if not unguarded else f"{len(unguarded)} without",
    )
    runbook = settings.ROOT / raw.get("handover", {}).get("runbook", "missing")
    add(
        "runbook_present",
        Path(runbook).exists(),
        str(runbook.relative_to(settings.ROOT)) if runbook.exists() else "missing",
    )
    per_case = m["cost_eur"] / max(1, len(labels))
    limit = raw.get("monitoring", {}).get("alerts", {}).get("cost_per_case_above_eur", 0.05)
    add("cost_per_case_within_alert", per_case <= limit, f"{per_case:.5f} EUR per case (alert above {limit})")
    return {
        "use_case": uc,
        "passed": all(r["passed"] for r in results),
        "checks": results,
        "metrics": m,
        "priority": s.priority() if s else None,
    }
