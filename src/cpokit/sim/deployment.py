"""The deployment, week by week: cases arrive, people work them, and once a use case reaches their
country some of them use the tool. When they do, the real use case code runs with their identity,
the proposal is stored, they accept or reject it, approvers approve, and approved actions write to
the ERP through the approval tokens, all as in production. What the simulator adds is the people:
who adopts, how trust moves, how long work really takes with and without the tool, which wrong
proposals they catch. That truth is written to build/truth/deployment.json for the evaluation only.

The kit sees what a real deployment sees: the CRM's handling time (noisy, sometimes inflated by
tickets left open), its own usage events, approvals and postings."""

from __future__ import annotations

import json
import math
from typing import Any

from .. import settings
from ..actions import execute
from ..approvals import Approvals
from ..auth import Principal
from ..kit import evals
from ..kitstore import KitStore
from ..llm.gateway import Gateway, GatewayError
from ..systems.store import Systems
from ..usecases import REGISTRY
from ..usecases.base import Context, NotAllowed
from .build import _label
from .world import org, rng

FUNCTION = {
    "cdr_disputes": "roaming_finance",
    "driver_refunds": "customer_service",
    "site_onboarding": "integration_ops",
    "tender_answers": "bid_team",
}
TEAM = {
    "roaming_finance": "roaming_finance",
    "customer_service": "customer_service",
    "integration_ops": "integration_ops",
    "bid_team": "bid_team",
}
APPROVER_ROLE = {
    "cdr_disputes": "finance_approver",
    "driver_refunds": "cs_lead",
    "site_onboarding": "integration_lead",
    "tender_answers": "bid_manager",
}


class Person:
    def __init__(self, oid: str, function: str, country: str, speed: float, trained: bool, trust: float) -> None:
        self.oid, self.function, self.country = oid, function, country
        self.speed, self.trained, self.trust = speed, trained, trust
        countries = frozenset({"*"}) if function != "customer_service" else frozenset({country})
        self.principal = Principal(oid, oid, frozenset({function}), countries, frozenset())


def people() -> dict[str, list[Person]]:
    cfg = org()["people"]
    r = rng("people")
    out: dict[str, list[Person]] = {}
    for team, by_country in cfg["teams"].items():
        for cc, n in by_country.items():
            for k in range(n):
                speed = float(math.exp(r.normal(0, cfg["speed_sd"])))
                trained = bool(r.random() < cfg["adoption"]["trained_share"])
                trust = cfg["adoption"]["initial_trust"] + (0.1 if trained else -0.05)
                out.setdefault(team, []).append(Person(f"{team}-{cc}-{k + 1:02d}", team, cc, speed, trained, trust))
    return out


def live_countries(use_case: str, week: int) -> set[str]:
    spec = settings.usecase(use_case)
    out: set[str] = set()
    for wave in spec["rollout"]["waves"]:
        if week >= wave["week"]:
            out.update(wave["countries"])
    return out


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def run(log: Any = print) -> dict[str, Any]:
    cfg = org()
    pc = cfg["people"]
    ad = pc["adoption"]
    systems = Systems(settings.SYSTEMS)
    systems.reset_operations()
    if settings.KIT_DB.exists():
        settings.KIT_DB.unlink()
    store = KitStore(settings.KIT_DB)
    world = json.loads((settings.TRUTH / "world.json").read_text())
    t0 = world["t0"]
    clock = {"now": t0}
    approvals = Approvals(store, now=lambda: clock["now"])
    gateway = Gateway(clock=lambda: clock["now"])
    truth = {t["case_id"]: t for t in json.loads((settings.TRUTH / "cases.json").read_text())}
    staff = people()
    approver = {
        uc: Principal(
            f"approver-{uc}",
            f"approver-{uc}",
            frozenset({FUNCTION[uc]}),
            frozenset({"*"}),
            frozenset({APPROVER_ROLE[uc]}),
        )
        for uc in FUNCTION
    }
    r = rng("deployment")
    rows: list[dict[str, Any]] = []
    worklog: list[dict[str, Any]] = []
    for week in range(1, world["weeks"] + 1):
        for uc in settings.USE_CASES:
            team = staff[TEAM[FUNCTION[uc]]]
            live = live_countries(uc, week)
            for case in systems.cases(uc, week):
                t = truth[case["case_id"]]
                clock["now"] = case["opened_ts"]
                local = [p for p in team if p.country == case["country"]] or team
                person = local[int(r.integers(len(local)))]
                complexity = float(t["complexity"])
                summer = 1 + pc["summer_load"] if 5 <= week <= 13 else 1.0
                t0_min = (
                    pc["handling_minutes"][uc]
                    * person.speed
                    * summer
                    * math.exp(r.normal(0, pc["minutes_sd"]))
                    * (1 + pc["complexity_effect"] * complexity)
                )
                eligible = case["country"] in live
                used = False
                correct = manual_ok = None
                caught = escaped = False
                over_eur = 0.0
                minutes = t0_min
                if eligible:
                    speed_z = math.log(person.speed) / pc["speed_sd"]
                    x = (
                        ad["intercept"]
                        + ad["trust"] * person.trust
                        + ad["trained"] * person.trained
                        + ad["complexity"] * complexity
                        + ad["speed"] * (-speed_z)
                    )
                    used = bool(r.random() < _sigmoid(x))
                if used:
                    ctx = Context(systems, gateway, person.principal, now=case["opened_ts"])
                    try:
                        prop = REGISTRY[uc](case, ctx)
                    except (GatewayError, NotAllowed, LookupError):
                        prop = None
                    if prop is None:
                        used = False
                    else:
                        d = prop.to_dict()
                        store.save_proposal(d)
                        store.event(
                            case["opened_ts"],
                            uc,
                            case["case_id"],
                            case["country"],
                            person.oid,
                            "proposal_shown",
                            detail={"needs_review": prop.needs_review},
                        )
                        label = _label(uc, case, t)
                        m = evals.SCORERS[uc]([(label, prop)])
                        acc_key = next(k for k in m if k.endswith("accuracy"))
                        correct = m[acc_key] >= 0.999
                        over_eur = float(m.get("over_credit_eur", m.get("over_refund_eur", 0.0)))
                        if correct:
                            minutes = t0_min * (1 - pc["saving_when_right"][uc])
                            person.trust += ad["trust_gain"] * (1 - person.trust)
                            accept = True
                        else:
                            p_catch = pc["review"]["catch_wrong_flagged" if prop.needs_review else "catch_wrong"]
                            caught = bool(r.random() < p_catch)
                            if caught:
                                minutes = t0_min * (1 + pc["cost_when_wrong"])
                                person.trust -= ad["trust_loss"] * person.trust
                                accept = False
                            else:
                                minutes = t0_min * (1 - pc["saving_when_right"][uc])
                                escaped = True
                                accept = True
                        store.event(
                            case["opened_ts"] + 60,
                            uc,
                            case["case_id"],
                            case["country"],
                            person.oid,
                            "accepted" if accept else "rejected",
                            value=float(r.uniform(0.0, 0.15) if correct else r.uniform(0.3, 0.9)),
                        )
                        if accept:
                            for a in d["actions"]:
                                who = approver[uc] if a["role"] else person.principal
                                try:
                                    token = approvals.approve(a["action_id"], who)
                                    if token:
                                        execute(
                                            a["action_id"],
                                            a["payload"],
                                            token,
                                            systems,
                                            approvals,
                                            now=case["opened_ts"] + 120,
                                        )
                                        store.event(
                                            case["opened_ts"] + 120,
                                            uc,
                                            case["case_id"],
                                            case["country"],
                                            who.oid,
                                            "action_executed",
                                            value=a.get("amount"),
                                            detail={"kind": a["kind"], "approved_by_role": a["role"]},
                                        )
                                except PermissionError:
                                    store.event(
                                        case["opened_ts"] + 120,
                                        uc,
                                        case["case_id"],
                                        case["country"],
                                        who.oid,
                                        "approval_refused",
                                    )
                if not used:
                    manual_ok = bool(r.random() >= cfg["manual_error"][uc])
                wrong_outcome = escaped or (manual_ok is False)
                reopened = wrong_outcome and bool(r.random() < cfg["reopen_share"])
                observed = minutes * math.exp(r.normal(0, pc["crm_noise_sd"]))
                if r.random() < pc["left_open_share"]:
                    observed *= float(r.uniform(3, 10))
                worklog.append(
                    {
                        "case_id": case["case_id"],
                        "user_oid": person.oid,
                        "use_case": uc,
                        "country": case["country"],
                        "week": week,
                        "minutes": round(observed, 1),
                        "closed_ts": case["opened_ts"] + int(observed * 60),
                        "reopened": reopened,
                    }
                )
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "use_case": uc,
                        "country": case["country"],
                        "week": week,
                        "user": person.oid,
                        "trained": person.trained,
                        "eligible": eligible,
                        "used": used,
                        "correct": correct,
                        "caught": caught,
                        "escaped": escaped,
                        "manual_ok": manual_ok,
                        "complexity": complexity,
                        "t0_min": t0_min,
                        "minutes": minutes,
                        "observed_min": observed,
                        "over_eur": over_eur,
                        "trust_after": person.trust,
                    }
                )
        store.commit()
    systems.log_work(worklog)
    write_directory()
    (settings.TRUTH / "deployment.json").write_text(json.dumps(rows))
    (settings.TRUTH / "people.json").write_text(
        json.dumps(
            [
                {
                    "oid": p.oid,
                    "function": p.function,
                    "country": p.country,
                    "speed": p.speed,
                    "trained": p.trained,
                    "trust": p.trust,
                }
                for team in staff.values()
                for p in team
            ]
        )
    )
    calls = gateway.calls
    used = sum(x["used"] for x in rows)
    summary = {
        "cases": len(rows),
        "used": used,
        "model_calls": len(calls),
        "llm_cost_eur": round(sum(c["cost_eur"] for c in calls), 3),
    }
    log(f"deployment: {summary}")
    return summary


def kit_users(staff: dict[str, list[Person]]) -> list[dict[str, Any]]:
    """The people directory the kit may see (who is in which team and country, who was trained)."""
    return [
        {"oid": p.oid, "function": p.function, "country": p.country, "trained": p.trained}
        for team in staff.values()
        for p in team
    ]


def write_directory() -> None:
    """Training attendance and team membership are HR facts the kit is given, not simulator truth."""
    (settings.BUILD / "directory.json").write_text(json.dumps(kit_users(people())))
