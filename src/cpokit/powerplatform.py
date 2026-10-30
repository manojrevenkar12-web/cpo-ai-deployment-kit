"""A Power Automate / Power Apps custom connector for the kit's API, generated from its OpenAPI so it
never drifts: Swagger 2.0 (what Power Platform imports) with Entra ID OAuth, plus apiProperties.json.
Business users can then build flows ("when a dispute email arrives, get a proposal, post it to the
finance channel") without the deployment team writing code."""

from __future__ import annotations

import json
from typing import Any

from . import settings
from .auth import DevIssuer
from .service.app import create_app

OPERATIONS = [
    "ListUseCases",
    "ListCases",
    "ProposeForCase",
    "GetProposal",
    "ApproveAction",
    "RejectAction",
    "RecordUsage",
    "GetMetrics",
]


def _schema(s: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """OpenAPI 3.1 schema -> Swagger 2.0 schema (the subset FastAPI emits here)."""
    if "$ref" in s:
        return {"$ref": s["$ref"].replace("#/components/schemas/", "#/definitions/")}
    if "anyOf" in s:
        non_null = [x for x in s["anyOf"] if x.get("type") != "null"]
        out = _schema(non_null[0], defs) if non_null else {"type": "string"}
        out["x-nullable"] = True
        return out
    out = {k: v for k, v in s.items() if k in ("type", "title", "description", "format", "enum", "default")}
    if s.get("type") == "array":
        out["items"] = _schema(s.get("items", {"type": "string"}), defs)
    if s.get("type") == "object" or "properties" in s:
        out["type"] = "object"
        if "properties" in s:
            out["properties"] = {k: _schema(v, defs) for k, v in s["properties"].items()}
        if "required" in s:
            out["required"] = s["required"]
    if not out.get("type") and "$ref" not in out:
        out["type"] = "object"
    return out


def connector() -> tuple[dict[str, Any], dict[str, Any]]:
    oa = create_app(DevIssuer().verifier()).openapi()
    defs = oa.get("components", {}).get("schemas", {})
    paths: dict[str, Any] = {}
    for path, item in oa["paths"].items():
        for method, op in item.items():
            if op.get("operationId") not in OPERATIONS:
                continue
            params = []
            for p in op.get("parameters", []):
                if p["in"] == "header":
                    continue
                params.append(
                    {
                        "name": p["name"],
                        "in": p["in"],
                        "required": p.get("required", False),
                        **{k: v for k, v in _schema(p.get("schema", {}), defs).items() if k in ("type", "format")},
                    }
                )
            if "requestBody" in op:
                schema = op["requestBody"]["content"]["application/json"]["schema"]
                params.append({"name": "body", "in": "body", "required": True, "schema": _schema(schema, defs)})
            ok = op.get("responses", {}).get("200", {}).get("content", {}).get("application/json", {}).get("schema", {})
            paths.setdefault(path, {})[method] = {
                "operationId": op["operationId"],
                "summary": op.get("summary") or op["operationId"],
                "description": op.get("description") or op.get("summary") or op["operationId"],
                "parameters": params,
                "responses": {"200": {"description": "OK", "schema": _schema(ok, defs) if ok else {"type": "object"}}},
            }
    access = settings.access()
    swagger = {
        "swagger": "2.0",
        "info": {
            "title": "CPO AI deployment kit",
            "version": "1.0.0",
            "description": "Proposals with evidence, approvals and usage for the operator's back-office use cases.",
        },
        "host": "cpo-ai-kit.example.azurecontainerapps.io",
        "basePath": "/",
        "schemes": ["https"],
        "consumes": ["application/json"],
        "produces": ["application/json"],
        "paths": paths,
        "definitions": {k: _schema(v, defs) for k, v in defs.items()},
        "securityDefinitions": {
            "oauth2-auth": {
                "type": "oauth2",
                "flow": "accessCode",
                "authorizationUrl": f"https://login.microsoftonline.com/{access['tenant']}/oauth2/v2.0/authorize",
                "tokenUrl": f"https://login.microsoftonline.com/{access['tenant']}/oauth2/v2.0/token",
                "scopes": {f"{access['audience']}/user_impersonation": "Act as the signed-in user"},
            }
        },
        "security": [{"oauth2-auth": [f"{access['audience']}/user_impersonation"]}],
    }
    props = {
        "properties": {
            "connectionParameters": {
                "token": {
                    "type": "oauthSetting",
                    "oAuthSettings": {
                        "identityProvider": "aad",
                        "clientId": "<app registration client id>",
                        "scopes": [f"{access['audience']}/user_impersonation"],
                        "redirectMode": "GlobalPerConnector",
                        "properties": {"IsFirstParty": "False", "AzureActiveDirectoryResourceId": access["audience"]},
                    },
                }
            },
            "iconBrandColor": "#0F4C5C",
            "capabilities": [],
            "publisher": "AI Unit",
        }
    }
    return swagger, props


def write() -> None:
    swagger, props = connector()
    out = settings.ROOT / "integrations" / "power-platform"
    out.mkdir(parents=True, exist_ok=True)
    (out / "apiDefinition.swagger.json").write_text(json.dumps(swagger, indent=1) + "\n")
    (out / "apiProperties.json").write_text(json.dumps(props, indent=1) + "\n")
