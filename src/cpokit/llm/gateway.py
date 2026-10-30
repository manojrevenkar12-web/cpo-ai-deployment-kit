"""The one door to models. Every call names a task; the gateway picks the model route, refuses
calls over the use case's daily budget, masks personal data and quarantines instruction-like text
before the model sees anything, validates the answer against the task's schema, and records cost,
latency and an OpenTelemetry GenAI span. A failure never becomes a decision: the caller gets an
error and the case goes to a person."""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol

from opentelemetry import trace
from pydantic import ValidationError

from .. import settings
from . import prompts, simreader
from .guard import Guard

tracer = trace.get_tracer("cpokit.gateway")
TEXT_FIELDS = {
    "dispute.read": ("email",),
    "ticket.read": ("ticket",),
    "site.map": ("protocol",),
    "tender.query": ("question",),
    "tender.answer": ("question",),
    "dispute.reply": (),
    "ticket.reply": (),
}


class GatewayError(RuntimeError):
    pass


class Provider(Protocol):
    name: str

    def complete(
        self, model: str, task: str, messages: list[dict[str, str]], inputs: dict[str, Any], max_tokens: int
    ) -> tuple[str, int, int]: ...


class SimulatedProvider:
    name = "simulated"

    def complete(self, model, task, messages, inputs, max_tokens):
        out = json.dumps(simreader.answer(task, inputs), ensure_ascii=False)
        return out, _tokens(messages), max(20, len(out) // 4)


class AnthropicProvider:
    """Claude through the Anthropic API, or through Microsoft Foundry when CPOKIT_FOUNDRY_RESOURCE is set."""

    name = "anthropic"

    def __init__(self) -> None:
        import anthropic

        resource = os.environ.get("CPOKIT_FOUNDRY_RESOURCE")
        self.client = anthropic.AnthropicFoundry(resource=resource) if resource else anthropic.Anthropic()

    def complete(self, model, task, messages, inputs, max_tokens):
        system = messages[0]["content"]
        msg = self.client.messages.create(
            model=model,
            system=system,
            max_tokens=max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": messages[1]["content"]}],
        )
        text = "".join(getattr(b, "text", "") for b in msg.content)
        start, end = text.find("{"), text.rfind("}")
        return text[start : end + 1], msg.usage.input_tokens, msg.usage.output_tokens


def _tokens(messages: list[dict[str, str]]) -> int:
    return sum(len(m["content"]) for m in messages) // 4


@dataclass
class Result:
    task: str
    output: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int
    cost_eur: float
    latency_ms: float
    masked: dict[str, int] = field(default_factory=dict)
    quarantined: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "model": self.model,
            "cost_eur": round(self.cost_eur, 6),
            "latency_ms": round(self.latency_ms, 1),
            "masked": self.masked,
            "quarantined": len(self.quarantined),
            "prompt_version": prompts.VERSION,
        }


class Gateway:
    def __init__(self, provider: Provider | None = None, clock: Any = time.time) -> None:
        self.cfg = settings.gateway()
        self.guard = Guard(self.cfg["guardrails"])
        name = os.environ.get("CPOKIT_PROVIDER", self.cfg["provider"])
        self.provider = provider or (AnthropicProvider() if name in ("anthropic", "foundry") else SimulatedProvider())
        self.clock = clock
        self.spent: dict[tuple[str, int], float] = defaultdict(float)
        self.failures: dict[str, int] = defaultdict(int)
        self.calls: list[dict[str, Any]] = []

    def day(self) -> int:
        return int(self.clock() // 86400)

    def call(self, task: str, inputs: dict[str, Any], *, day: int | None = None) -> Result:
        spec = self.cfg["tasks"][task]
        uc = spec["use_case"]
        d = self.day() if day is None else day
        clean, cleaned = self.guard.clean_inputs(inputs, TEXT_FIELDS[task])
        messages = prompts.render(task, clean)
        budget = self.cfg["budgets_eur_per_day"][uc]
        errors = []
        for model in spec["route"]:
            m = self.cfg["models"][model]
            if self.failures[model] >= 3:  # open circuit
                errors.append(f"{model}: circuit open")
                continue
            est = self._cost(m, _tokens(messages), spec["max_output_tokens"])
            if self.spent[(uc, d)] + est > budget:
                errors.append(f"{model}: daily budget of {budget} EUR for {uc} reached")
                continue
            with tracer.start_as_current_span(f"chat {model}") as span:
                span.set_attribute("gen_ai.operation.name", "chat")
                span.set_attribute("gen_ai.request.model", model)
                span.set_attribute("gen_ai.system", "anthropic")
                span.set_attribute("cpokit.task", task)
                span.set_attribute("cpokit.use_case", uc)
                t0 = time.perf_counter()
                try:
                    raw, tin, tout = self.provider.complete(model, task, messages, clean, spec["max_output_tokens"])
                    parsed = prompts.SCHEMAS[task].model_validate_json(raw).model_dump()
                except (ValidationError, ValueError, KeyError) as e:
                    self.failures[model] += 1
                    errors.append(f"{model}: answer did not match the schema ({type(e).__name__})")
                    continue
                except Exception as e:  # provider down, timeout
                    self.failures[model] += 1
                    errors.append(f"{model}: {type(e).__name__}")
                    continue
                self.failures[model] = 0
                latency = (time.perf_counter() - t0) * 1000
                if self.provider.name == "simulated":  # a modelled latency, not a measurement
                    lo, hi = m["latency_ms"]
                    latency = lo + (hi - lo) * ((tin * 7 + tout * 13) % 100) / 100
                cost = self._cost(m, tin, tout)
                self.spent[(uc, d)] += cost
                span.set_attribute("gen_ai.usage.input_tokens", tin)
                span.set_attribute("gen_ai.usage.output_tokens", tout)
                res = Result(task, parsed, model, tin, tout, cost, latency, cleaned.masked, cleaned.quarantined)
                self.calls.append({**res.summary(), "use_case": uc, "day": d})
                return res
        raise GatewayError("; ".join(errors) or "no route")

    def _cost(self, m: dict[str, Any], tin: int, tout: int) -> float:
        return (tin * m["input"] + tout * m["output"]) / 1e6 * self.cfg["usd_to_eur"]
