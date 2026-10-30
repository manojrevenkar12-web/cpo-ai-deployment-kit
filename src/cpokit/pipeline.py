"""`cpokit run`: build the world, run the go-live gate for every use case on its dev set, run the
deployment, measure adoption and impact from observed data, evaluate those measurements against
the truth, write the reports and handover packs, and apply the gate."""

from __future__ import annotations

import json
from typing import Any

from . import evaluation, settings
from .auth import service_principal
from .kit import evals, handover, ready
from .kitstore import KitStore
from .llm.gateway import Gateway
from .measure import adoption, impact
from .sim import build, deployment
from .systems.store import Systems
from .usecases.base import Context


def _write(name: str, data: Any) -> None:
    path = settings.REPORTS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str) + "\n")


def readiness(log: Any = print) -> dict[str, Any]:
    ctx = Context(Systems(settings.SYSTEMS), Gateway(), service_principal())
    out = {}
    for uc in settings.USE_CASES:
        labels = evals.load_labels(settings.BUILD / "evals" / uc / "dev.jsonl")
        m = evals.run(uc, labels, ctx)
        r = ready.check(uc, ctx, m)
        out[uc] = r
        _write(f"readiness/{uc}.json", r)
        log(
            f"{uc}: {'ready' if r['passed'] else 'NOT READY'} "
            + ", ".join(c["check"] for c in r["checks"] if not c["passed"])
        )
    return out


def measure(log: Any = print) -> tuple[dict[str, Any], dict[str, Any]]:
    systems, store = Systems(settings.SYSTEMS), KitStore(settings.KIT_DB)
    a = adoption.report(systems, store)
    i = impact.report(systems, store)
    _write("adoption.json", a)
    _write("impact.json", i)
    return a, i


def gate(rd: dict[str, Any], ev: dict[str, Any]) -> dict[str, Any]:
    cfg = settings.kit()["gate"]
    checks = []
    if cfg["all_use_cases_ready"]:
        bad = [uc for uc, r in rd.items() if not r["passed"]]
        checks.append(
            {"id": "all-use-cases-ready", "passed": not bad, "detail": f"not ready: {bad}" if bad else "all ready"}
        )
    moved = sum(e["tool_quality"]["over_paid_eur"] for e in ev.values())
    checks.append(
        {
            "id": "no-money-moved-wrongly",
            "passed": moved <= cfg["max_money_moved_wrongly_eur"],
            "detail": f"{moved:.2f} EUR above the right amounts",
        }
    )
    if cfg["measurement_truth_in_ci"]:
        miss = [uc for uc, e in ev.items() if e["rollout_effect"]["truth_in_ci"] is False]
        checks.append(
            {
                "id": "measurement-covers-truth",
                "passed": not miss,
                "detail": f"interval misses truth: {miss}" if miss else "every reported interval contains the truth",
            }
        )
    return {"passed": all(c["passed"] for c in checks), "checks": checks}


def run(log: Any = print) -> dict[str, Any]:
    world = build.build(log=log)
    rd = readiness(log)
    dep = deployment.run(log=log)
    a, i = measure(log)
    ev = evaluation.evaluate(i, a)
    _write("evaluation.json", ev)
    for uc in settings.USE_CASES:
        path = settings.REPORTS / "handover" / f"{uc}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(handover.pack(uc, rd[uc], a, i))
    g = gate(rd, ev)
    _write("gate.json", g)
    _write("summary.json", {"world": world, "deployment": dep, "gate": g["passed"]})
    for c in g["checks"]:
        log(f"{'ok  ' if c['passed'] else 'FAIL'} {c['id']}: {c['detail']}")
    return {"gate": g, "evaluation": ev}
