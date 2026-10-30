import { motion, useReducedMotion } from "motion/react";
import { Interval } from "../../components/Interval";
import { ErrorState, Skeleton } from "../../components/States";
import { useRollout, useUseCase } from "../../lib/data";
import { COUNTRY, num, pct, signedPct } from "../../lib/format";
import { DURATION, EASE } from "../../theme/motion";

function level(share: number): string {
  if (share >= 0.6) return "l4";
  if (share >= 0.4) return "l3";
  if (share >= 0.2) return "l2";
  return "l1";
}

function Grid() {
  const q = useRollout();
  const reduce = useReducedMotion();
  if (q.isPending) return <Skeleton lines={8} label="Loading the rollout" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const { weeks, countries } = q.data;
  return (
    <figure className="grid-figure">
      <div className="grid" role="table" aria-label="Share of driver refund tickets handled with the tool, by country and week">
        <div role="row" className="grid__row grid__row--head">
          <span role="columnheader" className="grid__label">Week</span>
          {weeks.map((w) => (
            <span role="columnheader" key={w} className="grid__week">
              {w}
            </span>
          ))}
        </div>
        {countries.map((c) => (
          <div role="row" key={c.country} className="grid__row">
            <span role="rowheader" className="grid__label" title={COUNTRY[c.country]}>
              {c.country}
            </span>
            {c.cells.map((cell) => {
              const live = c.launch != null && cell.week >= c.launch;
              const share = cell.cases ? cell.used / cell.cases : 0;
              const cls = live ? `cell cell--${level(share)}` : "cell cell--before";
              return (
                <motion.span
                  role="cell"
                  key={cell.week}
                  className={`${cls}${c.launch === cell.week ? " cell--launch" : ""}`}
                  aria-label={`${COUNTRY[c.country]} week ${cell.week}: ${live ? `${pct(share)} of ${cell.cases} tickets` : "before launch"}`}
                  initial={reduce ? false : { opacity: 0, scale: 0.6 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: DURATION.reveal, ease: EASE, delay: reduce ? 0 : cell.week * DURATION.cellStep }}
                />
              );
            })}
          </div>
        ))}
      </div>
      <figcaption className="legend">
        <span><i className="cell cell--before" /> before launch</span>
        <span><i className="cell cell--l1" /> under 20% of tickets</span>
        <span><i className="cell cell--l2" /> 20 to 40%</span>
        <span><i className="cell cell--l3" /> 40 to 60%</span>
        <span><i className="cell cell--l4" /> 60% or more</span>
        <span><i className="cell cell--l2 cell--launch" /> launch week</span>
      </figcaption>
    </figure>
  );
}

function ThreeWays() {
  const q = useUseCase("driver_refunds");
  if (q.isPending) return <Skeleton lines={5} label="Loading the measurements" />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const e = q.data.evaluation;
  const i = q.data.impact;
  const rows = [
    {
      name: "What a usage dashboard would show",
      how: "Tickets handled with the tool against tickets without, in live countries.",
      est: e.per_use_effect.naive_pct,
      ci: null,
      truth: e.per_use_effect.truth_pct,
      warn: "People keep the tool for easier tickets, and faster agents adopt first.",
    },
    {
      name: "Effect per use",
      how: `The rollout effect divided by the share of live tickets that used the tool (${pct(i.usage_share_live)}).`,
      est: e.per_use_effect.estimate_pct,
      ci: null,
      truth: e.per_use_effect.truth_pct,
      warn: null,
    },
    {
      name: "Effect of the rollout",
      how: "Each wave against the countries that did not have it yet, week by week, on all tickets.",
      est: e.rollout_effect.estimate_pct,
      ci: e.rollout_effect.ci_pct,
      truth: e.rollout_effect.truth_pct,
      warn: null,
    },
  ];
  return (
    <div className="three">
      {rows.map((r) => (
        <div key={r.name} className="three__row">
          <div className="three__text">
            <h3>{r.name}</h3>
            <p>{r.how}</p>
            {r.warn && <p className="warn">{r.warn}</p>}
          </div>
          <div className="three__plot">
            <Interval estimate={r.est} ci={r.ci} truth={r.truth} label={`${r.name}: ${signedPct(r.est)}`} />
            <span className="three__nums">
              <strong>{signedPct(r.est)}</strong>
              {r.ci && (
                <span className="row-sub">
                  {signedPct(r.ci[0])} to {signedPct(r.ci[1])}
                </span>
              )}
              <span className="row-sub truth-text">truth {signedPct(r.truth)}</span>
            </span>
          </div>
        </div>
      ))}
      <p className="note">
        Hours saved so far: {num(e.hours_saved.estimate)} h (interval {num(e.hours_saved.ci?.[0])} to{" "}
        {num(e.hours_saved.ci?.[1])} h); the simulator's truth is {num(e.hours_saved.truth)} h.
      </p>
    </div>
  );
}

export function RolloutPage() {
  return (
    <section aria-labelledby="rollout-title">
      <header className="page-head">
        <h1 id="rollout-title">Driver refunds reached eleven countries in three waves</h1>
        <p className="lede">
          Staggering the launch is what makes the saving measurable: until a country's wave arrives, it is the
          comparison for the countries that already have it. Each square is one country in one week, coloured by
          the share of tickets agents handled with the tool.
        </p>
      </header>
      <Grid />
      <section aria-labelledby="three-title" className="block">
        <h2 id="three-title">Three ways to count the time saved</h2>
        <p className="lede lede--small">
          The violet mark is the simulator's truth, which exists only because this organisation is simulated; in
          production only the estimates and their intervals are known.
        </p>
        <ThreeWays />
      </section>
    </section>
  );
}
