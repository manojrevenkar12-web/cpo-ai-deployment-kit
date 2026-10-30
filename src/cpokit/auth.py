"""Who is calling: Entra ID access tokens become a Principal with functions, countries and roles.

In production the API, the MCP servers and the Teams bot validate Entra ID v2 tokens against the
tenant's JWKS. Locally and in tests a `DevIssuer` signs tokens with a key of its own and serves the
same JWKS shape, so the validation path is the same code."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from . import settings


@dataclass(frozen=True)
class Principal:
    oid: str
    name: str
    functions: frozenset[str] = field(default_factory=frozenset)
    countries: frozenset[str] = field(default_factory=frozenset)  # "*" means all
    roles: frozenset[str] = field(default_factory=frozenset)

    def can_use(self, use_case: str) -> bool:
        allowed = settings.access()["use_case_functions"].get(use_case, [])
        return bool(self.functions & set(allowed)) or "kit_admin" in self.roles

    def sees(self, country: str) -> bool:
        return "*" in self.countries or country in self.countries

    def country_scope(self, all_countries: list[str]) -> list[str]:
        return list(all_countries) if "*" in self.countries else sorted(self.countries)

    def has_role(self, role: str) -> bool:
        return role in self.roles


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    groups = settings.access()["groups"]
    functions: set[str] = set()
    countries: set[str] = set()
    roles: set[str] = set()
    for g in claims.get("groups", []):
        spec = groups.get(g)
        if spec is None:
            continue
        functions.add(spec["function"])
        countries.update(spec.get("countries", []))
        roles.update(spec.get("roles", []))
    return Principal(
        oid=str(claims.get("oid") or claims.get("sub")),
        name=str(claims.get("name") or claims.get("preferred_username") or "unknown"),
        functions=frozenset(functions),
        countries=frozenset(countries),
        roles=frozenset(roles),
    )


class TokenError(PermissionError):
    pass


class Verifier:
    """Validates RS256 tokens: signature against the JWKS, issuer, audience, expiry."""

    def __init__(self, jwks: dict[str, Any], issuer: str, audience: str) -> None:
        self.keys = {k["kid"]: RSAAlgorithm.from_jwk(k) for k in jwks["keys"]}
        self.issuer, self.audience = issuer, audience

    def claims(self, token: str) -> dict[str, Any]:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            key = self.keys.get(kid)
            if key is None:
                raise TokenError("unknown signing key")
            return jwt.decode(
                token, key=key, algorithms=["RS256"], audience=self.audience, issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.PyJWTError as e:
            raise TokenError(str(e)) from e

    def principal(self, token: str) -> Principal:
        return principal_from_claims(self.claims(token))


def issuer_url(tenant: str) -> str:
    return f"https://login.microsoftonline.com/{tenant}/v2.0"


class DevIssuer:
    """A stand-in for Entra ID: signs tokens and publishes its JWKS."""

    def __init__(self) -> None:
        cfg = settings.access()
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = uuid.uuid4().hex[:16]
        self.issuer = issuer_url(cfg["tenant"])
        self.audience = cfg["audience"]

    def jwks(self) -> dict[str, Any]:
        jwk = RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        return {"keys": [{**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def token(self, name: str, groups: list[str], *, ttl: int = 3600, audience: str | None = None,
              oid: str | None = None) -> str:
        now = int(time.time())
        claims = {
            "iss": self.issuer, "aud": audience or self.audience, "iat": now, "nbf": now, "exp": now + ttl,
            "oid": oid or str(uuid.uuid5(uuid.NAMESPACE_DNS, name)), "name": name, "groups": groups,
            "tid": settings.access()["tenant"],
        }
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": self.kid})

    def verifier(self) -> Verifier:
        return Verifier(self.jwks(), self.issuer, self.audience)


def service_principal(name: str = "kit-service") -> Principal:
    """The kit's own identity for batch jobs (evals, the deployment simulation): all scopes, no roles."""
    return Principal(oid=f"svc-{name}", name=name, functions=frozenset(settings.access()["use_case_functions"]
                     and {f for fs in settings.access()["use_case_functions"].values() for f in fs}),
                     countries=frozenset({"*"}), roles=frozenset())
