# Playbooks

How the AI unit takes a business problem to a live, measured use case in under ten person-days, and hands
it over when it outgrows the unit. Each step has an artefact in this repository.

| Step | Playbook | Artefact |
|---|---|---|
| Find and rank use cases with the business | [discovery.md](discovery.md) | `config/usecases/<id>.yaml` (discovery, score) |
| Plan and run the sprint | [sprint.md](sprint.md) | `sprint` section, `cpokit new` |
| Write evals with the team's own past cases | [evals.md](evals.md) | dev set, thresholds, `cpokit eval` |
| Go live | [go-live.md](go-live.md) | `cpokit ready`, `reports/readiness/` |
| Train people and drive adoption | [adoption.md](adoption.md) | rollout waves, usage events |
| Measure what changed | [measuring-impact.md](measuring-impact.md) | `reports/impact.json`, the desk |
| Hand over | [handover.md](handover.md) | `reports/handover/<id>.md`, runbooks |
