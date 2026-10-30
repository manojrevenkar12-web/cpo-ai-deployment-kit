"""The ops copilot on Microsoft Agent Framework, with a scripted chat model: it proposes through the
use case, and asking for an approval stops for the user's confirmation."""

import json

from agent_framework import BaseChatClient, ChatResponse, Content, FunctionInvocationLayer, Message

from cpokit.agents.copilot import build_agent
from tests.conftest import labels, person


class Scripted(FunctionInvocationLayer, BaseChatClient):
    """Calls the tools it is told to, in order, then summarises the last tool result."""

    def __init__(self, calls: list[tuple[str, dict]]) -> None:
        super().__init__()
        self.calls = list(calls)
        self.seen: list[str] = []

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        results = [c for m in messages for c in m.contents if c.type == "function_result"]
        if self.calls:
            name, args = self.calls.pop(0)
            self.seen.append(name)
            msg = Message("assistant", [Content.from_function_call(f"call-{len(self.seen)}", name, arguments=args)])
        else:
            last = results[-1].result if results else ""
            msg = Message("assistant", [f"Result: {last}"])
        return ChatResponse(messages=[msg], response_id="r")


def _case(use_case: str, decision: str) -> str:
    return next(lb["case_id"] for lb in labels(use_case) if any(e.get("decision") == decision for e in lb["expected"]))


async def test_the_copilot_proposes_through_the_use_case(systems, store):
    case_id = _case("cdr_disputes", "credit")
    agent = build_agent(
        Scripted([("propose_for_case", {"case_id": case_id})]), person("roaming_finance"), systems, store
    )
    res = await agent.run(f"What should we do with {case_id}?")
    assert '"decision": "credit"' in res.text
    assert store.proposals("cdr_disputes")


async def test_the_copilot_cannot_see_other_countries(systems, store):
    case_id = next(lb["case_id"] for lb in labels("driver_refunds") if systems.case(lb["case_id"])["country"] == "IT")
    agent = build_agent(
        Scripted([("propose_for_case", {"case_id": case_id})]), person("customer_service", ("DE",)), systems, store
    )
    res = await agent.run(f"Look at {case_id}")
    assert "no such case in your scope" in res.text


async def test_requesting_an_approval_waits_for_the_user(systems, store):
    case_id = _case("cdr_disputes", "credit")
    outbox: list = []
    first = build_agent(
        Scripted([("propose_for_case", {"case_id": case_id})]), person("roaming_finance"), systems, store, outbox=outbox
    )
    out = json.loads((await first.run("propose")).text.removeprefix("Result: "))
    action_id = out["actions"][0]["action_id"]
    agent = build_agent(
        Scripted([("request_approval", {"action_id": action_id})]),
        person("roaming_finance"),
        systems,
        store,
        outbox=outbox,
    )
    res = await agent.run("ask for approval")
    assert res.user_input_requests, "the agent must stop for confirmation"
    assert outbox == []
