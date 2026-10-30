import { Interval } from "../../components/Interval";
import { ErrorState, Skeleton } from "../../components/States";
import { type UseCaseDetail, useUseCase } from "../../lib/data";
import { eur, num, pct, signedPct, words } from "../../lib/format";

function Usage({ d }: { d: UseCaseDetail }) {
  const weeks = d.adoption.weekly;
  if (!weeks.length) return <p className="note">Not live in any country yet.</p>;
  const max = 1;
  return (
    <div className="usage" role="img" aria-label={`Weekly share of live cases handled with the tool, ${weeks.length} weeks`}>
      {weeks.map((w) => (
        <span key={w.week} className="usage__col" title={`week ${w.week}: ${pct(w.usage_share)} of ${w.cases} cases`}>
          <span className="usage__bar" style={{ height: `${(w.usage_share / max) * 100}%` }} />
          <span className="usage__wk">{w.week}</span>
        </span>
      ))}
    </div>
  );
}

function Metric({ k, v }: { k: string; v: unknown }) {
  if (typeof v !== "number") return null;
  const share = k.includes("share") || k.includes("accuracy") || k.includes("routing");
  return (
    <div className="metric">
      <span className="metric__k">{words(k)}</span>
      <span className="metric__v">{share ? pct(v, 1) : num(v, Number.isInteger(v) ? 0 : 2)}</span>
    </div>
  );
}

export function UseCasePage({ id, onBack }: { id: string; onBack: () => void }) {
  const q = useUseCase(id);
  if (q.isPending) return <Skeleton lines={8} label="Loading the use case" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data;
  const r = d.readiness;
  const e = d.evaluation;
  const thresholds = (r.metrics as Record<string, unknown>) ?? {};
  return (
    <article aria-labelledby="uc-title">
      <button type="button" className="back" onClick={onBack}>
        All use cases
      </button>
      <header className="page-head">
        <h1 id="uc-title">{d.name}</h1>
        <p className="lede">{d.discovery.problem}</p>
        <p className="byline">
          Owner {d.owner.person}. Models read: {d.models_read.join(", ")}. Code decides: {d.code_decides.join(", ")}.
        </p>
      </header>
      <div className="cols">
        <section aria-labelledby="gate-uc">
          <h2 id="gate-uc">Go-live gate</h2>
          <ul className="checks">
            {r.checks.map((c) => (
              <li key={c.check} className={c.passed ? "ok" : "bad"}>
                <span className="gate__mark">{c.passed ? "pass" : "fail"}</span> {words(c.check)}
                <span className="row-sub">{c.detail}</span>
              </li>
            ))}
          </ul>
          <h3>On the labelled dev set</h3>
          <div className="metrics">
            {Object.entries(thresholds)
              .filter(([k]) => !["missing_cases", "cost_eur"].includes(k))
              .map(([k, v]) => (
                <Metric key={k} k={k} v={v} />
              ))}
          </div>
        </section>
        <section aria-labelledby="use-uc">
          <h2 id="use-uc">In use</h2>
          <p>
            {d.adoption.adopted_people} of {d.adoption.eligible_people} people have used it;{" "}
            {pct(d.adoption.usage_share_live)} of live cases went through it and {pct(d.adoption.acceptance)} of its
            proposals were accepted.
          </p>
          <Usage d={d} />
          <table className="mini">
            <caption>Usage by training</caption>
            <thead>
              <tr>
                <th scope="col">People</th>
                <th scope="col" className="num">Cases</th>
                <th scope="col" className="num">With the tool</th>
              </tr>
            </thead>
            <tbody>
              {d.adoption.by_training.map((b) => (
                <tr key={String(b.trained)}>
                  <th scope="row">{b.trained ? "trained" : "not trained"} ({b.people})</th>
                  <td className="num">{num(b.cases)}</td>
                  <td className="num">{pct(b.usage_share)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>Handling time</h3>
          {d.impact.rollout ? (
            <div className="effect effect--big">
              <Interval
                estimate={d.impact.rollout.pct}
                ci={d.impact.rollout.ci_pct}
                truth={e.rollout_effect.truth_pct}
                label={`handling time ${signedPct(d.impact.rollout.pct)}`}
              />
              <span>
                <strong>{signedPct(d.impact.rollout.pct)}</strong> per case ({d.impact.rollout.method})
              </span>
            </div>
          ) : (
            <p className="note">{d.impact.note}</p>
          )}
          <p className="note">
            Live quality (simulator's truth): {e.tool_quality.used} proposals used, {pct(e.tool_quality.correct)} right,{" "}
            {e.tool_quality.wrong_caught} wrong ones caught by people, {e.tool_quality.wrong_escaped} not caught,{" "}
            {eur(e.tool_quality.over_paid_eur, 2)} paid above the right amount. People without the tool got{" "}
            {e.manual_quality.wrong} of {e.manual_quality.cases} wrong.
          </p>
        </section>
      </div>
      <section aria-labelledby="sprint-uc" className="block">
        <h2 id="sprint-uc">Sprint plan: {num(d.sprint.person_days)} person-days</h2>
        <ol className="plan">
          {d.sprint.plan.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ol>
      </section>
      <section aria-labelledby="handover-uc" className="block">
        <h2 id="handover-uc">Handover pack for {d.handover.to}</h2>
        <pre className="pack">{d.handover_pack}</pre>
      </section>
    </article>
  );
}
