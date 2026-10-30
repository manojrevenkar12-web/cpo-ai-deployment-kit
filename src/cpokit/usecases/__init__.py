"""The use cases. Each is a module with `run(case, ctx) -> Proposal`."""

from collections.abc import Callable
from typing import Any

from . import cdr_disputes, driver_refunds, site_onboarding, tender_answers
from .base import Context, Proposal

REGISTRY: dict[str, Callable[[dict[str, Any], Context], Proposal]] = {
    "cdr_disputes": cdr_disputes.run,
    "driver_refunds": driver_refunds.run,
    "site_onboarding": site_onboarding.run,
    "tender_answers": tender_answers.run,
}
