"""Adoption, from the kit's own usage events and the directory of who was trained.

For each use case and week: how many people could use it (their country was live), how many did,
what share of live cases went through the tool, and how often people accepted or rejected what it
proposed. Trained and untrained people are reported apart, so enablement can be judged."""

from __future__ import annotations

import json
from typing import Any

import polars as pl

from .. import settings
from ..kitstore import KitStore
from ..systems.store import Systems


def rollout(use_case: str) -> dict[str, int]:
    """country -> week the use case went live there."""
    out: dict[str, int] = {}
    for wave in settings.usecase(use_case)["rollout"]["waves"]:
        for c in wave["countries"]:
            out[c] = min(out.get(c, 10**6), wave["week"])
    return out


def frames(systems: Systems, store: KitStore) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    work = pl.DataFrame(systems.worklog(), infer_schema_length=None)
    ev = pl.DataFrame(store.events(), infer_schema_length=None)
    directory = pl.DataFrame(json.loads((settings.BUILD / "directory.json").read_text()))
    return work, ev, directory


def report(systems: Systems, store: KitStore) -> dict[str, Any]:
    work, ev, directory = frames(systems, store)
    out: dict[str, Any] = {}
    for uc in settings.USE_CASES:
        live = rollout(uc)
        w = work.filter(pl.col("use_case") == uc).with_columns(
            live=pl.col("country").replace_strict(live, default=10**6, return_dtype=pl.Int64) <= pl.col("week")
        )
        e = ev.filter(pl.col("use_case") == uc)
        shown = e.filter(pl.col("event") == "proposal_shown").select("case_id", "user_oid").unique()
        decided = e.filter(pl.col("event").is_in(["accepted", "rejected"]))
        w = w.join(shown.with_columns(used=pl.lit(True)).select("case_id", "used"), on="case_id", how="left") \
            .with_columns(pl.col("used").fill_null(False))
        weekly = (
            w.filter(pl.col("live"))
            .group_by("week")
            .agg(cases=pl.len(), used=pl.col("used").sum(), users=pl.col("user_oid").n_unique(),
                 active=pl.col("user_oid").filter(pl.col("used")).n_unique())
            .sort("week")
            .with_columns(usage_share=pl.col("used") / pl.col("cases"))
        )
        team = directory.filter(pl.col("function") == _function(uc))
        eligible_people = team.filter(pl.col("country").is_in(list(live)))
        users = w.filter(pl.col("used")).select("user_oid").unique()
        by_training = (
            w.filter(pl.col("live"))
            .join(team.select(pl.col("oid").alias("user_oid"), "trained"), on="user_oid", how="left")
            .group_by("trained").agg(people=pl.col("user_oid").n_unique(), cases=pl.len(),
                                     usage_share=pl.col("used").mean())
            .sort("trained")
        )
        last = int(w["week"].max())
        recent = w.filter(pl.col("live") & (pl.col("week") > last - settings.measure()["adoption"]["windows_weeks"]))
        active_recent = recent.filter(pl.col("used"))["user_oid"].n_unique()
        acc = decided.group_by("event").agg(n=pl.len())
        n_acc = int(acc.filter(pl.col("event") == "accepted")["n"].sum())
        n_rej = int(acc.filter(pl.col("event") == "rejected")["n"].sum())
        executed = e.filter(pl.col("event") == "action_executed")
        out[uc] = {
            "eligible_people": eligible_people.height,
            "adopted_people": int(users.height),
            "active_last_4_weeks": int(active_recent),
            "live_cases": int(w["live"].sum()),
            "tool_cases": int(w["used"].sum()),
            "usage_share_live": float(w.filter(pl.col("live"))["used"].mean() or 0.0),
            "acceptance": n_acc / max(1, n_acc + n_rej),
            "rejected": n_rej,
            "actions_executed": executed.height,
            "money_moved_eur": round(float(executed["value"].fill_null(0).sum()), 2),
            "weekly": weekly.to_dicts(),
            "by_training": by_training.to_dicts(),
            "reopened_share": {
                "with_tool": float(w.filter(pl.col("used"))["reopened"].mean() or 0.0),
                "without_tool": float(w.filter(~pl.col("used"))["reopened"].mean() or 0.0),
            },
        }
    return out


def _function(uc: str) -> str:
    return settings.access()["use_case_functions"][uc][0]
