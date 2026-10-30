# Handover to the Full-Stack and AI/ML engineers

A use case is handed over when its spec's `handover.when` criteria are met (volume, a new system,
running without a person in the loop). The pack in `reports/handover/<id>.md` is generated from the spec,
the gate, the evals and the live numbers, so it is never older than the last run. It names: what it does,
who decides what, the gate results, usage and measured effect with intervals, known failure modes from the
evals, monitoring and alerts, and the runbook. The receiving team owns the use case from the day they
accept the pack; the AI unit keeps the template and the playbooks.
