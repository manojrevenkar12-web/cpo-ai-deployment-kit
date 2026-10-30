# Working in this repository

## Fast feedback
- `uv run pytest -q -m "not slow"`: seconds (builds the simulated world once if missing).
- `uv run pytest -q`: adds the end-to-end run; with `CPOKIT_TEST_DATABASE_URL` also the PostgreSQL tests.
- `uv run cpokit run`: world, go-live gate, 18-week deployment, measurement, evaluation, handover packs,
  release gate (about 20 seconds). `uv run cpokit export-web`, then `cd web && npm test && npx playwright test`.
- `uv run ruff check src tests && uv run ruff format --check src tests`.

## Invariants (each has a test)
- **Truth isolation.** Only `src/cpokit/sim` and `src/cpokit/evaluation.py` read `config/org.yaml` or
  `build/truth`. Use cases, gateway, measurement, API, MCP servers and agents never import the simulator
  (`tests/test_isolation.py`).
- **Models read, code decides.** A model's output is a reading (ids, intent, fields) or a draft; amounts,
  decisions and checks are code over system data and `config/policy.yaml`
  (`tests/test_usecases.py::test_injected_text_moves_no_money_even_without_quarantine`).
- **Nothing moves money or publishes without an approval token** bound to the exact action, single-use,
  expiring, issued only to the action's role and never to its preparer (`tests/test_approvals.py`,
  `tests/test_mcp.py`, `tests/test_service.py`).
- **Every call to a model goes through the gateway** (masking, quarantine, budget per use case, schema).
- **Usage events are append-only** (SQLite trigger and PostgreSQL trigger; `tests/test_store_pg.py`).
- **Settings live in `config/`**: business rules in `policy.yaml`, access in `access.yaml`, models and
  budgets in `gateway.yaml`, measurement in `measure.yaml`, the kit's gates in `kit.yaml`, each use case in
  `config/usecases/<id>.yaml`.
- **A new use case starts from the template** (`cpokit new`) and goes live only through `cpokit ready`.
- **Generated files**: `reports/`, `web/public/data/`, `integrations/power-platform/` are written by
  commands; do not edit them by hand.

## Held-out packs
`heldout/<pack>/` packs are written blind from `heldout/WRITING_CASES.md` by someone who has not seen the
code. Never change code to pass a pack. Its first run (`reports/heldout/<pack>/first_run.json`) is never
rewritten. If you study a pack's failures, write `regression` into its `STATUS` and have someone who has not
seen the code write a new pack from the guide only.
