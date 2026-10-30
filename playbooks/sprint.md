# The sprint (under ten person-days)

| Day | Work | Done when |
|---|---|---|
| 1 | Discovery, baseline, spec | Owner signed the spec's discovery section |
| 2-4 | Data access through the MCP servers, rules in `config/policy.yaml`, the use case module | It produces proposals with evidence for real past cases |
| 5-6 | Evals with the team's labelled past cases; thresholds agreed with the owner | `cpokit eval <id>` passes |
| 7 | Approvals, review reasons, reply drafts; Teams card and Power Automate flow if the team works there | An approver approved a test action in Teams |
| 8 | `cpokit ready <id>`, runbook, training for the first wave | The gate passes |
| 9-10 | Launch wave one; watch the desk daily | First week of usage events |

Rules: no use case starts without an owner and a baseline; no model decides an amount; the limit is in
`config/kit.yaml` and the gate refuses a spec that plans more.
