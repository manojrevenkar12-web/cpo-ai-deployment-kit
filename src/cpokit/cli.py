"""The command line: `cpokit run` builds and checks everything; the other commands run one part."""

from __future__ import annotations

import json

import typer

from . import settings

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def run() -> None:
    """World, go-live gate, deployment, measurement, evaluation, handover packs, gate."""
    from . import pipeline

    res = pipeline.run()
    raise typer.Exit(0 if res["gate"]["passed"] else 1)


@app.command()
def world() -> None:
    """Build the simulated organisation's systems and the labelled dev sets."""
    from .sim import build

    build.build()


@app.command("eval")
def eval_(use_case: str) -> None:
    """Run one use case on its dev set and check its thresholds."""
    from .auth import service_principal
    from .kit import evals
    from .llm.gateway import Gateway
    from .systems.store import Systems
    from .usecases.base import Context

    ctx = Context(Systems(settings.SYSTEMS), Gateway(), service_principal())
    m = evals.run(use_case, evals.load_labels(settings.BUILD / "evals" / use_case / "dev.jsonl"), ctx)
    typer.echo(json.dumps(m, indent=1))
    th = evals.check(use_case, m)
    for t in th:
        typer.echo(f"{'ok  ' if t['passed'] else 'FAIL'} {t['metric']} = {t['value']} ({t['kind']} {t['target']})")
    raise typer.Exit(0 if all(t["passed"] for t in th) else 1)


@app.command()
def ready() -> None:
    """The go-live gate for every use case."""
    from . import pipeline

    rd = pipeline.readiness()
    raise typer.Exit(0 if all(r["passed"] for r in rd.values()) else 1)


@app.command()
def new(
    use_case: str, name: str = typer.Option(...), function: str = typer.Option(...), owner: str = typer.Option(...)
) -> None:
    """Start a new use case from the template (spec, code, runbook)."""
    from .kit import scaffold

    for p in scaffold.new(use_case, name, function, owner):
        typer.echo(f"wrote {p.relative_to(settings.ROOT)}")


@app.command()
def heldout(name: str) -> None:
    """Run a blind held-out pack once; the first run is recorded and never rewritten."""
    from . import heldout as H

    H.run_pack(name)


@app.command("export-web")
def export_web() -> None:
    """Write the desk's data files from the reports."""
    from . import export

    export.write()


@app.command("power-platform")
def power_platform() -> None:
    """Write the Power Automate custom connector (Swagger 2.0) from the API."""
    from . import powerplatform

    powerplatform.write()


@app.command("serve-api")
def serve_api(port: int = 8000) -> None:
    import os

    import httpx
    import uvicorn

    from .auth import Verifier, issuer_url
    from .service.app import create_app

    cfg = settings.access()
    jwks = os.environ.get("CPOKIT_JWKS_URL", f"https://login.microsoftonline.com/{cfg['tenant']}/discovery/v2.0/keys")
    verifier = Verifier(httpx.get(jwks, timeout=10).json(), issuer_url(cfg["tenant"]), cfg["audience"])
    uvicorn.run(create_app(verifier), host="0.0.0.0", port=port)


@app.command("serve-mcp")
def serve_mcp(system: str = typer.Argument(..., help="csms | roaming | payments | erp | documents")) -> None:
    """Serve one enterprise system as an MCP server (streamable HTTP, Entra ID tokens)."""
    from .mcp_servers import serve

    serve(system)
