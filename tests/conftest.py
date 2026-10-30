import json
import shutil
from pathlib import Path

import pytest

from cpokit import settings
from cpokit.auth import Principal, service_principal
from cpokit.kitstore import KitStore
from cpokit.llm.gateway import Gateway
from cpokit.systems.store import Systems
from cpokit.usecases.base import Context


@pytest.fixture(scope="session")
def world() -> Path:
    """A built world (systems, truth, dev sets). Built once if missing."""
    if not settings.SYSTEMS.exists() or not (settings.BUILD / "evals" / "cdr_disputes" / "dev.jsonl").exists():
        from cpokit.sim.build import build

        build(log=lambda *_: None)
    return settings.BUILD


@pytest.fixture()
def systems(world: Path, tmp_path: Path) -> Systems:
    """A private copy of the systems database, so tests that write do not disturb others."""
    dst = tmp_path / "systems.sqlite"
    shutil.copy(settings.SYSTEMS, dst)
    return Systems(dst)


@pytest.fixture()
def store(tmp_path: Path) -> KitStore:
    return KitStore(tmp_path / "kit.sqlite")


@pytest.fixture()
def ctx(systems: Systems) -> Context:
    return Context(systems, Gateway(), service_principal())


def person(
    function: str, countries: tuple[str, ...] = ("*",), roles: tuple[str, ...] = (), oid: str = "p1"
) -> Principal:
    return Principal(oid, oid, frozenset({function}), frozenset(countries), frozenset(roles))


def labels(use_case: str) -> list[dict]:
    path = settings.BUILD / "evals" / use_case / "dev.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
