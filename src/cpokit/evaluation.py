"""How good were the kit's own measurements? The evaluation compares what the kit reported (from
observed data only) with what really happened in the simulated organisation (truth): the effect of
each rollout on handling time, the effect per use, the hours saved, and the quality of the tool's
proposals in live use. Only this module and the simulator read build/truth."""

from __future__ import annotations

import json
import math
from typing import Any

import polars as pl

from . import settings


def truth_frame() -> pl.DataFrame:
    rows = json.loads((settings.TRUTH / "deployment.json").read_text())
    return pl.DataFrame(rows, infer_schema_length=None).with_columns(
        effect=(pl.col("minutes").log() - pl.col("t0_min").log())
    )


def evaluate(impact: dict[str, Any], adoption: dict[str, Any]) -> dict[str, Any]:
    d = truth_frame()
    out: dict[str, Any] = {}
    for uc in settings.USE_CASES:
        t = d.filter(pl.col("use_case") == uc)
        live = t.filter(pl.col("eligible"))
        used = t.filter(pl.col("used"))
        m = impact[uc]
        true_itt = float(live["effect"].mean()) if live.height else None
        true_per_use = float(used["effect"].mean()) if used.height else None
        est = m.get("rollout", {}).get("att_log") if m.get("rollout") else None
        ci = m.get("rollout", {}).get("ci_log") if m.get("rollout") else None
        res = {
            "rollout_effect": {
                "estimate_pct": _pct(est), "truth_pct": _pct(true_itt),
                "ci_pct": [_pct(x) for x in ci] if ci else None,
                "truth_in_ci": (ci[0] <= true_itt <= ci[1]) if ci and true_itt is not None else None,
                "method": m.get("rollout", {}).get("method") if m.get("rollout") else None,
            },
            "per_use_effect": {"estimate_pct": _pct(m.get("per_use_log")), "truth_pct": _pct(true_per_use),
                               "naive_pct": _pct(m.get("naive_log"))},
            "hours_saved": {"estimate": m.get("hours_saved"), "ci": m.get("hours_saved_ci"),
                            "truth": round(float((live["t0_min"] - live["minutes"]).sum()) / 60, 1)},
            "tool_quality": {
                "used": used.height,
                "correct": float(used["correct"].mean()) if used.height else None,
                "wrong_caught": int(used["caught"].sum()),
                "wrong_escaped": int(used["escaped"].sum()),
                "over_paid_eur": round(float(used["over_eur"].sum()), 2),
            },
            "manual_quality": {"cases": t.filter(~pl.col("used")).height,
                               "wrong": int((t.filter(~pl.col("used"))["manual_ok"] == False).sum())},  # noqa: E712
            "adoption": {"usage_share_live_reported": adoption[uc]["usage_share_live"],
                         "usage_share_live_truth": float(live["used"].mean()) if live.height else None},
        }
        out[uc] = res
    return out


def _pct(x: float | None) -> float | None:
    return None if x is None else round(math.exp(x) - 1, 4)
