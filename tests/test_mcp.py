"""The MCP servers: scoped reads, refused writes without a token, one write with it."""

import pytest
from mcp.client.client import Client

from cpokit.approvals import Approvals
from cpokit.llm.gateway import Gateway
from cpokit.mcp_servers import build
from cpokit.usecases import REGISTRY
from cpokit.usecases.base import Context
from tests.conftest import labels, person


def _first(systems, country):
    return systems._rows("select session_id from sessions where site_id like ? limit 1", (f"{country}-%",))[0][
        "session_id"
    ]


async def test_reads_are_scoped_to_the_callers_countries(systems, store):
    agent = person("customer_service", ("DE",))
    server = build("csms", systems, store, principal=agent)
    async with Client(server) as c:
        de = await c.call_tool("get_session", {"session_id": _first(systems, "DE")})
        it = await c.call_tool("get_session", {"session_id": _first(systems, "IT")})
    assert de.structured_content["result"]["session_id"].startswith("DE-")
    assert it.structured_content["result"] is None


async def test_tools_are_marked_read_only_or_destructive(systems, store):
    async with Client(build("csms", systems, store, principal=person("roaming_finance"))) as c:
        tools = (await c.list_tools()).tools
    assert tools and all(t.annotations.read_only_hint for t in tools)
    async with Client(build("erp", systems, store, principal=person("roaming_finance"))) as c:
        tools = (await c.list_tools()).tools
    assert all(t.annotations.destructive_hint for t in tools)


async def test_a_function_without_access_is_refused(systems, store):
    async with Client(build("payments", systems, store, principal=person("bid_team"))) as c:
        res = await c.call_tool("payments_for_session", {"session_id": "x"})
    assert res.is_error


async def test_erp_write_needs_the_exact_approved_action(systems, store):
    lab = next(lb for lb in labels("cdr_disputes") if any(e["decision"] == "credit" for e in lb["expected"]))
    analyst = person("roaming_finance", oid="analyst")
    prop = REGISTRY["cdr_disputes"](systems.case(lab["case_id"]), Context(systems, Gateway(), analyst))
    d = prop.to_dict()
    store.save_proposal(d)
    action = d["actions"][0]
    approver = person("roaming_finance", roles=("finance_approver",), oid="approver")
    token = Approvals(store).approve(action["action_id"], approver)
    server = build("erp", systems, store, principal=analyst)
    async with Client(server) as c:
        bigger = {**action["payload"], "amount_eur": action["payload"]["amount_eur"] * 100}
        refused = await c.call_tool(
            "post_approved_action", {"action_id": action["action_id"], "payload": bigger, "approval_token": token}
        )
        ok = await c.call_tool(
            "post_approved_action",
            {"action_id": action["action_id"], "payload": action["payload"], "approval_token": token},
        )
        again = await c.call_tool(
            "post_approved_action",
            {"action_id": action["action_id"], "payload": action["payload"], "approval_token": token},
        )
    assert refused.is_error and not ok.is_error and again.is_error
    assert [p["approval_id"] for p in systems.erp_postings(lab["case_id"]) if p["approved_by"] == "approver"]


@pytest.mark.parametrize("missing", ["", "abc.def"])
async def test_erp_write_without_a_valid_token_is_refused(systems, store, missing):
    before = len(systems.erp_postings())
    async with Client(build("erp", systems, store, principal=person("roaming_finance"))) as c:
        res = await c.call_tool(
            "post_approved_action", {"action_id": "ACT-x", "payload": {}, "approval_token": missing}
        )
    assert res.is_error
    assert len(systems.erp_postings()) == before
