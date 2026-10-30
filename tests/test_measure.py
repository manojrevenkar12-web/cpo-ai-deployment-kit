"""Impact measurement on synthetic data with a planted effect: the staggered design recovers it
under a common trend and selection into use; the naive comparison does not."""

import math

import numpy as np
import polars as pl
from hypothesis import given, settings
from hypothesis import strategies as st

from cpokit.measure.impact import bootstrap, did, its


def synthetic(effect: float, seed: int, trend: float = 0.15, select: float = 0.8) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    launch = {"A": 5, "B": 5, "C": 9, "D": 9, "E": 13, "F": 13}
    rows = []
    for c, g in launch.items():
        level = rng.normal(3.0, 0.2)
        for w in range(1, 19):
            for _ in range(25):
                hard = rng.random()
                y0 = level + 0.6 * hard + (trend if 5 <= w <= 12 else 0) + rng.normal(0, 0.3)
                live = w >= g
                used = live and rng.random() < 1 / (1 + math.exp(-(1 - select * 3 * hard)))
                y = y0 + (effect if used else 0.0)
                rows.append({"country": c, "week": w, "launch": g, "live": live, "used": used, "y": y, "y0": y0})
    return pl.DataFrame(rows)


def test_staggered_did_recovers_the_rollout_effect_and_naive_overstates():
    df = synthetic(effect=-0.5, seed=1)
    live = df.filter(pl.col("live"))
    true_itt = float((live["y"] - live["y0"]).mean())
    est = did(df)
    assert abs(est["att_log"] - true_itt) < 0.05
    per_use_truth = -0.5
    naive = float(live.filter(pl.col("used"))["y"].mean() - live.filter(~pl.col("used"))["y"].mean())
    assert naive < per_use_truth - 0.1, "people pick easy cases: the naive comparison overstates the saving"


def test_bootstrap_interval_covers_the_truth():
    df = synthetic(effect=-0.4, seed=3)
    live = df.filter(pl.col("live"))
    true_itt = float((live["y"] - live["y0"]).mean())
    b = bootstrap(df, 200, seed=5)
    lo, hi = np.quantile(b, [0.025, 0.975])
    assert lo <= true_itt <= hi


@settings(max_examples=25, deadline=None, derandomize=True)
@given(st.floats(-0.8, 0.0), st.integers(0, 10_000))
def test_the_estimate_stays_within_noise_of_the_truth(effect, seed):
    # six countries, 25 cases per country-week: the standard error is about 0.08 log points
    df = synthetic(effect=effect, seed=seed)
    live = df.filter(pl.col("live"))
    true_itt = float((live["y"] - live["y0"]).mean())
    assert abs(did(df)["att_log"] - true_itt) < 0.25


def test_a_single_team_gets_an_interrupted_time_series_with_its_trend_bias():
    df = synthetic(effect=0.0, seed=7, trend=0.3).filter(pl.col("country") == "A")
    r = its(df)
    assert r is not None and r["att_log"] > 0.05, "a seasonal trend shows up as an 'effect' without a control group"


def test_no_cases_before_launch_means_no_estimate():
    df = synthetic(effect=-0.3, seed=2).filter(pl.col("week") >= 5).filter(pl.col("country") == "A")
    assert its(df) is None
