"""Truth isolation: only the simulator and the evaluation read the truth or the organisation file;
the use cases, gateway, measurement, API and agents never import the simulator."""

import ast
from pathlib import Path

from cpokit import settings

SRC = settings.ROOT / "src" / "cpokit"
MAY_READ_TRUTH = {"sim", "evaluation.py", "settings.py"}
ORCHESTRATION = {"pipeline.py", "cli.py", "heldout.py"}  # wire things together, decide nothing
TRUTH_WORDS = ("TRUTH", '"org"', "'org'", "org.yaml", "deployment.json", "people.json")


def _modules():
    for p in SRC.rglob("*.py"):
        rel = p.relative_to(SRC)
        yield rel, p.read_text()


def test_only_the_simulator_and_evaluation_read_truth():
    offenders = []
    for rel, text in _modules():
        if rel.parts[0] in MAY_READ_TRUTH or str(rel) in ORCHESTRATION:
            continue
        offenders += [f"{rel}: {w}" for w in TRUTH_WORDS if w in text]
    assert not offenders, offenders


def test_decision_code_never_imports_the_simulator():
    offenders = []
    for rel, text in _modules():
        if rel.parts[0] == "sim" or str(rel) in ORCHESTRATION:
            continue
        for node in ast.walk(ast.parse(text)):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and ("sim" in node.module.split(".") or node.module == "evaluation")
            ):
                offenders.append(f"{rel}: from {node.module}")
            if isinstance(node, ast.ImportFrom) and node.level and node.module is None:
                offenders += [f"{rel}: import {a.name}" for a in node.names if a.name in ("sim", "evaluation")]
    assert not offenders, offenders


def test_measurement_reads_only_observed_sources():
    text = (SRC / "measure" / "impact.py").read_text() + (SRC / "measure" / "adoption.py").read_text()
    assert "truth" not in text.lower().replace("the truth", "")
    assert Path(settings.ROOT / "config" / "measure.yaml").exists()
