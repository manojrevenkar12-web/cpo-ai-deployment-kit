import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useState } from "react";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { type Proposal, useProposals } from "../../lib/data";
import { eur, words } from "../../lib/format";
import { DURATION, EASE } from "../../theme/motion";

function Value({ v }: { v: unknown }) {
  if (v !== null && typeof v === "object" && !Array.isArray(v)) {
    return (
      <dl className="kv">
        {Object.entries(v as Record<string, unknown>).map(([k, x]) => (
          <div key={k}>
            <dt>{words(k)}</dt>
            <dd>{typeof x === "object" ? JSON.stringify(x) : String(x)}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return <code>{Array.isArray(v) ? v.map(String).join(", ") : String(v)}</code>;
}

function Detail({ p }: { p: Proposal }) {
  return (
    <div className="detail">
      <h2>
        {p.case_id} <span className="row-sub">{words(p.use_case)}, {p.country}</span>
      </h2>
      <p className="decision">
        Proposed: <strong>{words(p.decision)}</strong>
      </p>
      {p.review_reasons.length > 0 && (
        <div className="review">
          <h3>Why a person should look closely</h3>
          <ul>
            {p.review_reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      {p.quarantined.length > 0 && (
        <p className="quarantine">
          {p.quarantined.length} line{p.quarantined.length > 1 ? "s" : ""} of instruction-like text were kept away
          from the model.
        </p>
      )}
      <h3>Actions waiting for approval</h3>
      {p.actions.length === 0 ? (
        <p className="note">None: nothing changes money or published data.</p>
      ) : (
        <ul className="actions">
          {p.actions.map((a) => (
            <li key={a.action_id}>
              {words(a.kind)} {a.amount != null && <strong>{eur(a.amount, 2)}</strong>}
              <span className="row-sub">
                {a.role ? `needs ${words(a.role)} in Teams; the write needs the approval token` : "the agent's own approval"}
              </span>
            </li>
          ))}
        </ul>
      )}
      <h3>Evidence</h3>
      <table className="evidence">
        <tbody>
          {p.evidence.map((e, i) => (
            <tr key={`${e.source}-${i}`}>
              <th scope="row">{e.label}</th>
              <td>
                <Value v={e.value} />
                <span className="row-sub">{e.source}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {p.draft && (
        <>
          <h3>Draft reply ({p.draft.language})</h3>
          <pre className="draft">{p.draft.text}</pre>
        </>
      )}
    </div>
  );
}

export function Proposals() {
  const q = useProposals();
  const [sel, setSel] = useState<string | null>(null);
  const reduce = useReducedMotion();
  if (q.isPending) return <Skeleton lines={8} label="Loading proposals" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data.length)
    return <EmptyState title="No proposals yet">Proposals appear here once a use case runs on a case.</EmptyState>;
  const current = q.data.find((p) => p.proposal_id === sel) ?? q.data[0]!;
  return (
    <section aria-labelledby="prop-title">
      <header className="page-head">
        <h1 id="prop-title">What the tool proposed, and why</h1>
        <p className="lede">
          A proposal never executes. Each one carries the records it was decided from; money and publishing wait for a
          person with the right role, and the write accepts only the token their approval produced.
        </p>
      </header>
      <div className="split">
        <ul className="list" aria-label="Proposals">
          {q.data.map((p) => (
            <li key={p.proposal_id}>
              <button
                type="button"
                aria-pressed={p.proposal_id === current.proposal_id}
                className="list__item"
                onClick={() => setSel(p.proposal_id)}
              >
                <span className="row-title">{p.case_id}</span>
                <span className="row-sub">
                  {words(p.use_case)}: {words(p.decision)}
                  {p.needs_review ? ", needs a closer look" : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
        <AnimatePresence mode="wait">
          <motion.div
            key={current.proposal_id}
            initial={reduce ? false : { opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={reduce ? undefined : { opacity: 0 }}
            transition={{ duration: DURATION.panel, ease: EASE }}
          >
            <Detail p={current} />
          </motion.div>
        </AnimatePresence>
      </div>
    </section>
  );
}
