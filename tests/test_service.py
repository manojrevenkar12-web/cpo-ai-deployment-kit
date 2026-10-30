"""The API: Entra tokens required, scope enforced, approval by role, execution only with the token."""

import pytest
from fastapi.testclient import TestClient

from cpokit.auth import DevIssuer
from cpokit.service.app import create_app
from tests.conftest import labels


@pytest.fixture()
def api(systems, store):
    issuer = DevIssuer()
    client = TestClient(create_app(issuer.verifier(), systems, store))
    return client, issuer


def h(issuer, name, groups):
    return {"Authorization": f"Bearer {issuer.token(name, groups)}"}


def test_no_token_no_access(api):
    client, _ = api
    assert client.get("/v1/use-cases").status_code == 401
    assert client.get("/v1/use-cases", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_a_token_for_another_audience_is_refused(api):
    client, issuer = api
    tok = issuer.token("anna", ["sg-cs-dach"], audience="api://something-else")
    assert client.get("/v1/use-cases", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_an_agent_sees_only_their_countries(api, systems):
    client, issuer = api
    rows = client.get(
        "/v1/cases", params={"use_case": "driver_refunds"}, headers=h(issuer, "anna", ["sg-cs-dach"])
    ).json()
    assert rows and {r["country"] for r in rows} <= {"DE", "AT"}
    it_case = next(lb["case_id"] for lb in labels("driver_refunds") if systems.case(lb["case_id"])["country"] == "IT")
    r = client.post(f"/v1/cases/{it_case}/propose", headers=h(issuer, "anna", ["sg-cs-dach"]))
    assert r.status_code == 404


def test_propose_approve_execute(api, systems):
    client, issuer = api
    case = next(
        lb["case_id"] for lb in labels("cdr_disputes") if any(e["decision"] == "credit" for e in lb["expected"])
    )
    analyst = h(issuer, "ben", ["sg-roaming-finance"])
    prop = client.post(f"/v1/cases/{case}/propose", headers=analyst).json()
    action = prop["actions"][0]
    # the analyst cannot approve (no role), the approver can
    assert client.post(f"/v1/actions/{action['action_id']}/approve", headers=analyst).status_code == 403
    tok = client.post(
        f"/v1/actions/{action['action_id']}/approve", headers=h(issuer, "carla", ["sg-roaming-finance-approvers"])
    ).json()["approval_token"]
    tampered = {**action["payload"], "amount_eur": 999.0}
    assert (
        client.post(
            f"/v1/actions/{action['action_id']}/execute",
            headers=analyst,
            json={"payload": tampered, "approval_token": tok},
        ).status_code
        == 403
    )
    ok = client.post(
        f"/v1/actions/{action['action_id']}/execute",
        headers=analyst,
        json={"payload": action["payload"], "approval_token": tok},
    )
    assert ok.status_code == 200 and "posted" in ok.json()


def test_the_preparer_cannot_approve_their_own_action(api):
    client, issuer = api
    case = next(
        lb["case_id"] for lb in labels("cdr_disputes") if any(e["decision"] == "credit" for e in lb["expected"])
    )
    both = h(issuer, "dora", ["sg-roaming-finance", "sg-roaming-finance-approvers"])
    prop = client.post(f"/v1/cases/{case}/propose", headers=both).json()
    r = client.post(f"/v1/actions/{prop['actions'][0]['action_id']}/approve", headers=both)
    assert r.status_code == 403 and "prepared" in r.json()["detail"]


def test_openapi_is_complete(api):
    client, _ = api
    spec = client.get("/openapi.json").json()
    ops = {op["operationId"] for p in spec["paths"].values() for op in p.values()}
    assert {"ProposeForCase", "ApproveAction", "ExecuteAction", "RecordUsage"} <= ops
