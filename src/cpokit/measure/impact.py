"""Business impact on handling time, from the CRM's worklog, measured three ways:

1. Rollout effect (staggered difference-in-differences). Where a use case reached countries in
   waves, each wave is compared with the countries that had not received it yet, week by week
   (Callaway & Sant'Anna style, not-yet-treated controls, base = mean of the two weeks before
   launch). It answers "what did launching it do to handling time per case", tool used or not, and
   it is robust to who chooses to use the tool. Confidence intervals: bootstrap over countries.
2. Per use (Wald): the rollout effect divided by the share of live cases that used the tool.
3. Naive comparison: cases handled with the tool against cases without, in live countries. People
   use the tool on easier cases and faster people adopt first, so this overstates the saving; it is
   reported because it is what a usage dashboard would show.

A use case run by one central team has no control group: its before/after change is reported as
an interrupted time series, with the caveat that anything else that changed at the same time
(season, workload) is in it. Without cases before launch there is no impact estimate at all."""

from __future__ import annotations

from typing import Any

import numpy as np
import polars as pl

from .. import settings
from ..kitstore import KitStore
from ..systems.store import Systems
from .adoption import rollout


def _prepare(systems: Systems, store: KitStore, uc: str) -> pl.DataFrame:
    cfg = settings.measure()["handling_time"]
    work = pl.DataFrame(systems.worklog(uc), infer_schema_length=None)
    shown = {e["case_id"] for e in store.events(uc) if e["event"] == "proposal_shown"}
    cap = float(work["minutes"].quantile(cfg["winsorize_quantile"]))
    live = rollout(uc)
    return work.with_columns(
        m=pl.col("minutes").clip(upper_bound=cap),
        y=pl.col("minutes").clip(upper_bound=cap).log(),
        launch=pl.col("country").replace_strict(live, default=10**6, return_dtype=pl.Int64),
        used=pl.col("case_id").is_in(list(shown)),
    ).with_columns(live=pl.col("week") >= pl.col("launch"))


def did(df: pl.DataFrame, countries: list[str] | None = None, col: str = "y") -> dict[str, Any] | None:
    """Group-time ATTs with not-yet-treated controls, aggregated by case counts."""
    cells = df.group_by("country", "week").agg(y=pl.col(col).mean(), n=pl.len(), launch=pl.col("launch").first())
    if countries is not None:
        cells = pl.concat(
            [
                cells.filter(pl.col("country") == c).with_columns(country=pl.lit(f"{c}#{k}"))
                for k, c in enumerate(countries)
            ]
        )
    y = {(r["country"], r["week"]): r["y"] for r in cells.iter_rows(named=True)}
    n = {(r["country"], r["week"]): r["n"] for r in cells.iter_rows(named=True)}
    launch = {r["country"]: r["launch"] for r in cells.iter_rows(named=True)}
    weeks = sorted({w for _, w in y})
    min_pre = settings.measure()["impact"]["min_pre_weeks"]
    cohorts = sorted({g for g in launch.values() if g < 10**6})
    atts, weights, by_e = [], [], {}
    for g in cohorts:
        treated = [c for c, gg in launch.items() if gg == g]
        pre = [w for w in (g - 2, g - 1) if w >= weeks[0]]
        if len(pre) < min_pre:
            continue
        for t in weeks:
            if t < g:
                continue
            controls = [c for c, gg in launch.items() if gg > t]
            if not controls:
                continue

            def change(cs: list[str], t: int = t, pre: list[int] = pre) -> float | None:
                vals = []
                for c in cs:
                    if (c, t) in y and all((c, p) in y for p in pre):
                        vals.append(y[(c, t)] - np.mean([y[(c, p)] for p in pre]))
                return float(np.mean(vals)) if vals else None

            dt, dc = change(treated), change(controls)
            if dt is None or dc is None:
                continue
            att = dt - dc
            wgt = sum(n.get((c, t), 0) for c in treated)
            atts.append(att)
            weights.append(wgt)
            by_e.setdefault(t - g, []).append((att, wgt))
    if not atts:
        return None
    overall = float(np.average(atts, weights=weights))
    event = {e: float(np.average([a for a, _ in v], weights=[w for _, w in v])) for e, v in sorted(by_e.items())}
    return {"att_log": overall, "cells": len(atts), "cases": int(sum(weights)), "event_time": event}


def bootstrap(df: pl.DataFrame, samples: int, seed: int, col: str = "y") -> list[float]:
    rng = np.random.default_rng(seed)
    launch = dict(df.group_by("country").agg(pl.col("launch").first()).iter_rows())
    by_cohort: dict[int, list[str]] = {}
    for c, g in launch.items():
        by_cohort.setdefault(g, []).append(c)
    out = []
    for _ in range(samples):
        pick = [str(rng.choice(cs)) for cs in by_cohort.values() for _ in cs]
        r = did(df, pick, col=col)
        if r is not None:
            out.append(r["att_log"])
    return out


def its(df: pl.DataFrame, col: str = "y") -> dict[str, Any] | None:
    g = int(df["launch"].min())
    pre = df.filter(pl.col("week") < g)
    post = df.filter(pl.col("week") >= g)
    if pre.height < 10 or post.height < 10:
        return None
    diff = float(post[col].mean() - pre[col].mean())
    se = float(np.sqrt(post[col].var() / post.height + pre[col].var() / pre.height))
    return {
        "att_log": diff,
        "ci_log": [diff - 1.96 * se, diff + 1.96 * se],
        "pre_cases": pre.height,
        "post_cases": post.height,
    }


def report(systems: Systems, store: KitStore) -> dict[str, Any]:
    cfg = settings.measure()
    out: dict[str, Any] = {}
    for uc in settings.USE_CASES:
        df = _prepare(systems, store, uc)
        live = df.filter(pl.col("live"))
        usage = float(live["used"].mean()) if live.height else 0.0
        naive = None
        if live.filter(pl.col("used")).height and live.filter(~pl.col("used")).height:
            naive = float(live.filter(pl.col("used"))["y"].mean() - live.filter(~pl.col("used"))["y"].mean())
        res: dict[str, Any] = {"usage_share_live": usage, "naive_log": naive}
        countries = df["country"].n_unique()
        baseline = (
            float(df.filter(~pl.col("live"))["minutes"].median() or 0.0) if df.filter(~pl.col("live")).height else None
        )
        res["baseline_minutes_median"] = baseline
        staggered = countries > 1 and len(set(rollout(uc).values())) > 1
        levels = did(df, col="m") if staggered else its(df, col="m")
        if staggered:
            d = did(df)
            if d:
                b = bootstrap(df, cfg["impact"]["bootstrap"]["samples"], cfg["impact"]["bootstrap"]["seed"])
                d["ci_log"] = [float(np.quantile(b, 0.025)), float(np.quantile(b, 0.975))] if b else None
                d["method"] = "staggered difference-in-differences"
                res["rollout"] = d
        else:
            s = its(df)
            if s:
                s["method"] = "interrupted time series (no control group)"
                res["rollout"] = s
        r = res.get("rollout")
        if r is None:
            res["note"] = "no cases before launch: the effect on handling time cannot be measured"
        else:
            r["pct"] = float(np.exp(r["att_log"]) - 1)
            if r.get("ci_log"):
                r["ci_pct"] = [float(np.exp(x) - 1) for x in r["ci_log"]]
            if usage > 0:
                res["per_use_log"] = r["att_log"] / usage
            if levels:  # hours from the same design on minutes, not from the % (savings sit on short cases)
                res["minutes_per_case"] = levels["att_log"]
                saved_h = -levels["att_log"] * live.height / 60
                res["hours_saved"] = round(saved_h, 1)
                if staggered:
                    b = bootstrap(df, cfg["impact"]["bootstrap"]["samples"], cfg["impact"]["bootstrap"]["seed"], "m")
                    lo, hi = (float(np.quantile(b, 0.025)), float(np.quantile(b, 0.975))) if b else (None, None)
                else:
                    lo, hi = levels["ci_log"]
                if lo is not None:
                    res["hours_saved_ci"] = sorted([round(-hi * live.height / 60, 1), round(-lo * live.height / 60, 1)])
                res["value_eur"] = round(saved_h * cfg["loaded_cost_eur_per_hour"], 0)
        out[uc] = res
    return out
