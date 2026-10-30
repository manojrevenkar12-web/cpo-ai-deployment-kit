"""Low-code artefacts stay consistent with the API: the Power Platform connector validates as
Swagger 2.0 and carries the operations flows need; the n8n workflow's connections point at nodes
that exist and only call API paths that exist."""

import json
import re

from openapi_spec_validator import validate

from cpokit import settings
from cpokit.auth import DevIssuer
from cpokit.powerplatform import OPERATIONS, connector
from cpokit.service.app import create_app


def test_power_platform_connector_is_valid_swagger_2():
    swagger, props = connector()
    validate(swagger)
    ops = {op["operationId"] for p in swagger["paths"].values() for op in p.values()}
    assert ops == set(OPERATIONS)
    assert props["properties"]["connectionParameters"]["token"]["oAuthSettings"]["identityProvider"] == "aad"


def test_committed_connector_matches_the_api():
    swagger, _ = connector()
    committed = json.loads((settings.ROOT / "integrations/power-platform/apiDefinition.swagger.json").read_text())
    assert committed == swagger, "run `cpokit power-platform` after changing the API"


def test_n8n_workflow_is_wired_and_calls_real_paths():
    wf = json.loads((settings.ROOT / "integrations/n8n/dispute-intake.json").read_text())
    names = {n["name"] for n in wf["nodes"]}
    for src, outs in wf["connections"].items():
        assert src in names
        for branch in outs["main"]:
            assert all(c["node"] in names for c in branch)
    paths = set(create_app(DevIssuer().verifier()).openapi()["paths"])
    for n in wf["nodes"]:
        url = n["parameters"].get("url", "")
        if "/v1/" in url:
            p = re.sub(r"\{\{[^}]*\}\}", "{case_id}", url.split("}}", 1)[1])
            assert p in paths, p
