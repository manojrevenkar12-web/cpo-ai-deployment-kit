"""`cpokit new`: a new use case starts from the template (spec, code, runbook), so every use case
has the same sections, gates and handover from day one."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .. import settings


def new(use_case: str, name: str, function: str, owner: str, root: Path | None = None) -> list[Path]:
    base = root or settings.ROOT
    env = Environment(
        loader=FileSystemLoader(settings.ROOT / "templates" / "usecase"),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    values = {"id": use_case, "name": name, "function": function, "owner": owner}
    targets = {
        "spec.yaml.j2": base / "config" / "usecases" / f"{use_case}.yaml",
        "usecase.py.j2": base / "src" / "cpokit" / "usecases" / f"{use_case}.py",
        "runbook.md.j2": base / "playbooks" / "runbooks" / f"{use_case}.md",
    }
    written = []
    for tpl, path in targets.items():
        if path.exists():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(env.get_template(tpl).render(**values))
        written.append(path)
    return written
