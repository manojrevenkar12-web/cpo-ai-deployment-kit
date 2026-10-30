"""The handover pack: what the Full-Stack and AI/ML engineers get when a use case outgrows the
deployment team. Written from the spec, the gate, the evals and the live numbers, so it is never
out of date with what was measured."""

from __future__ import annotations

from typing import Any

from .. import settings
from . import spec


def pack(uc: str, ready: dict[str, Any], adoption: dict[str, Any], impact: dict[str, Any]) -> str:
    s = spec.load(uc)
    raw = settings.usecase(uc)
    a, i = adoption[uc], impact[uc]
    r = i.get("rollout") or {}
    lines = [
        f"# Handover: {s.name}",
        "",
        f"Owner: {s.owner['person']} ({s.owner['function']}). Spec: `config/usecases/{uc}.yaml`. "
        f"Runbook: `{raw['handover']['runbook']}`.",
        "",
        "## What it does",
        s.discovery.problem.strip(),
        "",
        f"Models read: {', '.join(s.models_read)}. Code decides: {', '.join(s.code_decides)}. "
        f"Approvals: {', '.join(f'{k} by {v}' for k, v in s.approvals.items()) or 'none'}.",
        "",
        "## Why it is handed over now",
        *[f"- {w}" for w in raw["handover"]["when"]],
        "",
        "## Go-live gate",
        *[f"- {'pass' if c['passed'] else 'FAIL'}: {c['check']} ({c['detail']})" for c in ready["checks"]],
        "",
        "## In use",
        f"- {a['adopted_people']} of {a['eligible_people']} people have used it; "
        f"{a['usage_share_live']:.0%} of live cases go through it; {a['acceptance']:.0%} of proposals accepted.",
        f"- Usage share by training: " + ", ".join(
            f"{'trained' if b['trained'] else 'not trained'} {b['usage_share']:.0%}" for b in a["by_training"]),
    ]
    if r:
        ci = r.get("ci_pct")
        lines.append(f"- Handling time per case: {r['pct']:+.0%}"
                     + (f" (95% interval {ci[0]:+.0%} to {ci[1]:+.0%})" if ci else "") + f", {r['method']}.")
    else:
        lines.append(f"- Handling time: {i.get('note', 'not measured')}.")
    if i.get("hours_saved") is not None:
        lines.append(f"- Hours saved so far: {i['hours_saved']:.0f}"
                     + (f" (interval {i['hours_saved_ci'][0]:.0f} to {i['hours_saved_ci'][1]:.0f})"
                        if i.get("hours_saved_ci") else ""))
    m = ready["metrics"]
    lines += [
        "",
        "## Known failure modes (from the evals)",
        *[f"- {k}: {v}" for k, v in m.items() if k in ("by_cause", "by_kind", "errors", "field_errors")],
        f"- Share of cases sent to a person for review: {m.get('review_share', 0):.0%}",
        "",
        "## Monitoring",
        *[f"- {k}: {v}" for k, v in raw["monitoring"].items()],
    ]
    return "\n".join(lines) + "\n"
