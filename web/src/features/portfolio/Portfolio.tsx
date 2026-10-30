import { Interval } from "../../components/Interval";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { usePortfolio, type UseCaseRow } from "../../lib/data";
import { eur, num, pct, signedPct, words } from "../../lib/format";

const SPRINT_LIMIT = 10;

function SprintBar({ days }: { days: number }) {
  return (
    <span className="sprint" role="img" aria-label={`${days} of ${SPRINT_LIMIT} person-days planned`}>
      <span className="sprint__fill" style={{ width: `${(days / SPRINT_LIMIT) * 100}%` }} />
      <span className="sprint__text">{num(days, 0)} d</span>
    </span>
  );
}

function Row({ u, onOpen }: { u: UseCaseRow; onOpen: (id: string) => void }) {
  return (
    <tr>
      <th scope="row">
        <button type="button" className="link-row" onClick={() => onOpen(u.id)}>
          <span className="row-title">{u.name}</span>
          <span className="row-sub">{u.owner.person}</span>
        </button>
      </th>
      <td className="num">{num(u.priority, 1)}</td>
      <td>
        <SprintBar days={u.person_days} />
      </td>
      <td>{u.ready ? <span className="tag tag--live">passed</span> : <span className="tag tag--risk">blocked</span>}</td>
      <td className="num">
        {u.adopted_people} of {u.eligible_people}
        <span className="row-sub">{pct(u.usage_share_live)} of live cases</span>
      </td>
      <td>
        <span className="effect">
          <Interval estimate={u.impact_pct} ci={u.impact_ci} label={`handling time ${signedPct(u.impact_pct)}`} />
          <span className="effect__num">{u.impact_pct == null ? "–" : signedPct(u.impact_pct)}</span>
        </span>
        {u.impact_note && <span className="row-sub">no cases before launch</span>}
      </td>
      <td className="num">
        {u.hours_saved == null ? "–" : `${num(u.hours_saved)} h`}
        {u.hours_saved_ci && (
          <span className="row-sub">
            {num(u.hours_saved_ci[0])} to {num(u.hours_saved_ci[1])} h
          </span>
        )}
      </td>
      <td className="num">{eur(u.money_moved_eur)}</td>
    </tr>
  );
}

export function Portfolio({ onOpen }: { onOpen: (id: string) => void }) {
  const q = usePortfolio();
  if (q.isPending) return <Skeleton lines={6} label="Loading the use cases" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const rows = [...q.data.use_cases].sort((a, b) => b.priority - a.priority);
  if (!rows.length) {
    return (
      <EmptyState title="No use cases yet">
        Start one with <code>cpokit new</code>: it writes the spec, the code skeleton and the runbook.
      </EmptyState>
    );
  }
  const d = q.data.generated.deployment;
  return (
    <section aria-labelledby="portfolio-title">
      <header className="page-head">
        <h1 id="portfolio-title">Four use cases, each shipped in under ten person-days</h1>
        <p className="lede">
          Ordered by value times feasibility over risk. Every one passed its go-live gate on cases its team had
          already resolved; the handling-time effect is measured from the CRM after rollout, with its interval, not
          read off a usage counter. Over 18 weeks {num(d.used)} of {num(d.cases)} cases went through the tool, for{" "}
          {eur(d.llm_cost_eur, 2)} of model calls.
        </p>
      </header>
      <div className="table-wrap">
        <table className="ledger">
          <caption className="sr-only">Use cases with their sprint, gate, adoption and measured effect</caption>
          <thead>
            <tr>
              <th scope="col">Use case</th>
              <th scope="col" className="num">Priority</th>
              <th scope="col">Sprint (limit 10 d)</th>
              <th scope="col">Go-live gate</th>
              <th scope="col" className="num">People using it</th>
              <th scope="col">Handling time per case, 95% interval</th>
              <th scope="col" className="num">Hours saved</th>
              <th scope="col" className="num">Money moved</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((u) => (
              <Row key={u.id} u={u} onOpen={onOpen} />
            ))}
          </tbody>
        </table>
      </div>
      <section className="gate" aria-labelledby="gate-title">
        <h2 id="gate-title">Release gate: {q.data.gate.passed ? "passed" : "failed"}</h2>
        <ul>
          {q.data.gate.checks.map((c) => (
            <li key={c.id} className={c.passed ? "ok" : "bad"}>
              <span className="gate__mark">{c.passed ? "pass" : "fail"}</span> {words(c.id)}
              <span className="row-sub">{c.detail}</span>
            </li>
          ))}
        </ul>
      </section>
    </section>
  );
}
