"""The held-out pack loader, on a small pack written for this test (not a held-out set): it builds
the world the pack describes, derives the amounts from the rules, and the kit scores on it."""

import yaml

from cpokit import settings
from cpokit.auth import service_principal
from cpokit.heldout import build_pack
from cpokit.kit import evals
from cpokit.llm.gateway import Gateway
from cpokit.systems.store import Systems
from cpokit.usecases.base import Context


def test_mini_pack(tmp_path):
    pack = yaml.safe_load((settings.ROOT / "tests/fixtures/mini_pack.yaml").read_text())
    labels = build_pack(pack, tmp_path)
    credit = labels["cdr_disputes"][0]["expected"][0]["credit_eur"]
    assert credit == round(40.0 * 0.08 * 1.19, 2)  # billed with the next version: 8 cents per kWh too much
    assert labels["cdr_disputes"][1]["expected"][0]["credit_eur"] > 10
    assert labels["driver_refunds"][0]["expected"]["amount_eur"] == 9.80
    ctx = Context(Systems(tmp_path / "systems.sqlite"), Gateway(), service_principal())
    for uc, labs in labels.items():
        m = evals.run(uc, labs, ctx)
        acc = next(v for k, v in m.items() if k.endswith("accuracy"))
        assert acc == 1.0, (uc, m)
