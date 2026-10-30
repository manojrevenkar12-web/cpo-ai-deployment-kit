"""A use case's specification (config/usecases/<id>.yaml), validated: the one-page contract between
the business owner and the deployment engineer, from discovery to handover."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .. import settings


class Discovery(BaseModel):
    problem: str
    users: str
    systems: list[str]
    baseline: dict[str, Any]
    value_hypothesis: str
    risks: list[str]
    score: dict[str, int]


class Sprint(BaseModel):
    person_days: float = Field(gt=0)
    plan: list[str]


class Spec(BaseModel):
    id: str
    name: str
    owner: dict[str, str]
    discovery: Discovery
    models_read: list[str]
    code_decides: list[str]
    approvals: dict[str, str]
    evals: dict[str, Any]
    access: dict[str, Any]
    monitoring: dict[str, Any]
    sprint: Sprint
    rollout: dict[str, Any]
    handover: dict[str, Any]

    def priority(self) -> float:
        """Value x feasibility / risk: the order in which use cases are worth building."""
        s = self.discovery.score
        return round(s["value"] * s["feasibility"] / max(1, s["risk"]), 2)


def load(uc: str) -> Spec:
    return Spec.model_validate(settings.usecase(uc))


def missing_sections(uc: str) -> list[str]:
    raw = settings.usecase(uc)
    return [k for k in settings.kit()["required_spec_sections"] if k not in raw]
