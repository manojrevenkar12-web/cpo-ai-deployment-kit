# cpo-ai-deployment-kit

How an AI unit takes a charge point operator's back-office problems to live, measured AI in sprints of
under ten person-days, and hands them over when they outgrow it.

The kit is a template, a set of gates and playbooks, and four use cases shipped through them for a
simulated pan-European charge point operator (11 countries, roaming partners, customer service, an
acquired network, a bid team):

| Use case | Owner | The model reads | Code decides | Approval |
|---|---|---|---|---|
| **Roaming CDR disputes** | Roaming Finance | eMSPs' dispute emails (5 languages, tables, prose, hub notices, "around 7 pm at …") | which CDR, re-rating from signed meter values and the tariff version valid at the time, the credit | finance approver, per credit note |
| **Driver refund tickets** | Customer Service, 11 countries | drivers' tickets in 10 languages | which session and payments, the refund by policy, explain / escalate / redirect to the eMSP | CS lead above €40 |
| **Acquired-site onboarding** | Integration Ops Italy | an acquired network's export and commissioning protocols | OCPI location, coordinates, power consistency, AFIR card payment, publish or a person | integration lead |
| **Tender and grant answers** | Business Development | the question | retrieval, newest source wins, every number checked against its citation, or "the library does not answer this" | bid manager |

![The rollout of driver refunds across eleven countries, and three ways to count the time saved](docs/screenshots/02-rollout-and-impact.png)

RESULTS

## How it works

```
 Teams (Agents SDK)   Power Automate (custom connector)   n8n   the desk
          │                     │                          │       │
          └──────────── API (FastAPI, Entra ID tokens) ────┴───────┘        Copilot Studio, Claude,
                                │                                            the kit's Agent Framework copilot
                     use case: read → find → decide → propose                        │
                        │            │        │                                     │
       LLM gateway ◄────┘   MCP servers (caller's identity and countries) ◄─────────┘
  (mask, quarantine,        CSMS · roaming (OCPI) · payments · documents · kit
   budgets, schemas,                 │
   Claude on Foundry)       ERP / publishing: write tools need an approval token
                                     │      bound to the exact action, single use,
                                     │      never issued to the action's preparer
              usage events (append-only) ──► adoption and staggered-rollout impact ──► handover pack
```

| Part | Where |
|---|---|
| The template: spec, scaffold, go-live gate, evals, handover pack | `config/usecases/`, `templates/usecase/`, `src/cpokit/kit/`, `cpokit new`, `cpokit ready` |
| Four use cases (models read, code decides) | `src/cpokit/usecases/`, rules in `config/policy.yaml` |
| LLM gateway: routes, daily budgets per use case, PII masking, injection quarantine, schemas, OpenTelemetry GenAI spans | `src/cpokit/llm/`, `config/gateway.yaml` |
| Access: Entra ID tokens, groups → functions, countries, roles | `src/cpokit/auth.py`, `config/access.yaml` |
| Approval tokens and the only code that writes | `src/cpokit/approvals.py`, `src/cpokit/actions.py` |
| MCP servers for each enterprise system | `src/cpokit/mcp_servers.py` (`cpokit serve-mcp <system>`) |
| Ops copilot on Microsoft Agent Framework, Teams approvals on the Microsoft 365 Agents SDK | `src/cpokit/agents/` |
| API, Power Platform connector, n8n workflow | `src/cpokit/service/`, `integrations/` |
| Adoption and impact measurement | `src/cpokit/measure/`, `config/measure.yaml` |
| The simulated organisation and its truth | `src/cpokit/sim/`, `config/org.yaml`, `src/cpokit/evaluation.py` |
| PostgreSQL store with row-level security by country, append-only usage | `sql/kit.sql`, `src/cpokit/kitstore.py` |
| Azure: Container Apps, PostgreSQL, Key Vault, Foundry, Bot Service, budget | `azure/main.bicep`, `azure/deploy.sh` |
| The desk: use cases, rollout and impact, proposals with evidence | `web/` (React 19, TypeScript, Motion) |
| Playbooks: discovery, sprint, evals, go-live, adoption, measuring impact, handover | `playbooks/` |

## Run it

```bash
uv sync
uv run pytest -q                 # 68 tests; PostgreSQL ones with CPOKIT_TEST_DATABASE_URL
uv run cpokit run                # world, gate per use case, 18-week deployment, measurement, evaluation, release gate
uv run cpokit eval driver_refunds
uv run cpokit new location_partner_statements --name "Location partner statements" --function partner_management --owner "Head of Partner Management"
uv run cpokit export-web && cd web && npm ci && npm run build && npx playwright test
uv run cpokit serve-api          # needs CPOKIT_JWKS_URL (Entra ID) ; serve-mcp <system> ; serve-teams
uv run cpokit heldout <pack>     # a blind held-out pack, run once
```

## Limits

- The organisation is simulated. Its people, partners, faults and handling times are assumptions in
  `config/org.yaml`; the numbers show the kit and its measurement work on an organisation built to behave
  like a real one, and say nothing about E.ON Drive Infrastructure.
- No model key was available, so model calls go to a deterministic stand-in that reads the same prompt
  inputs with rules and obeys injected instructions like a naive model. The stand-in was written by the
  same author as the case generator, which is why the dev-set scores are close to perfect; the blind
  held-out packs are the honest test of reading. With `CPOKIT_PROVIDER=foundry` the same prompts go to
  Claude in Microsoft Foundry. Costs are list prices for the estimated tokens.
- Sprint lengths in the specs are plans, not time records.
- The Azure templates compile and the image builds in CI; nothing has been deployed from this repository.
