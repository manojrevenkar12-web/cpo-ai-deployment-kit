"""Where things live, and the settings files. Business settings are in config/, never in code.

`config/org.yaml` describes the simulated organisation, including how its people really behave and
how long their work really takes. Only the simulator (`cpokit.sim`) and the evaluation
(`cpokit.evaluation`) may read it, or anything under build/truth; `tests/test_isolation.py` checks."""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"
BUILD = Path(os.environ.get("CPOKIT_BUILD", ROOT / "build"))
REPORTS = Path(os.environ.get("CPOKIT_REPORTS", ROOT / "reports"))
SYSTEMS = BUILD / "systems.sqlite"  # what the enterprise systems hold (observed)
KIT_DB = BUILD / "kit.sqlite"  # what the kit records: proposals, decisions, approvals, usage
TRUTH = BUILD / "truth"  # the simulator's answers; sim and evaluation only
EVALS = ROOT / "evals"
HELDOUT = ROOT / "heldout"


@cache
def load(name: str) -> dict[str, Any]:
    """config/<name>.yaml, with an optional override file (CPOKIT_SETTINGS_OVERRIDE) merged on top."""
    data = yaml.safe_load((CONFIG / f"{name}.yaml").read_text())
    override = os.environ.get("CPOKIT_SETTINGS_OVERRIDE")
    if override:
        extra = yaml.safe_load(Path(override).read_text()) or {}
        if name in extra:
            data = _merge(data, extra[name])
    return data


def _merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def policy() -> dict[str, Any]:
    return load("policy")


def access() -> dict[str, Any]:
    return load("access")


def gateway() -> dict[str, Any]:
    return load("gateway")


def measure() -> dict[str, Any]:
    return load("measure")


def kit() -> dict[str, Any]:
    return load("kit")


def usecase(uc: str) -> dict[str, Any]:
    return yaml.safe_load((CONFIG / "usecases" / f"{uc}.yaml").read_text())


USE_CASES = ("cdr_disputes", "driver_refunds", "site_onboarding", "tender_answers")
