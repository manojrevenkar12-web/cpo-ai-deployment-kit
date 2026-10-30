/** A measured effect as an interval on a fixed scale: the estimate, its 95% interval, and optionally the
 * naive comparison (what a usage dashboard would claim) and the simulator's truth. */
export interface IntervalProps {
  estimate: number | null;
  ci?: [number, number] | null;
  naive?: number | null;
  truth?: number | null;
  min?: number;
  max?: number;
  label: string;
}

const pos = (x: number, min: number, max: number) => `${(((x - min) / (max - min)) * 100).toFixed(2)}%`;

export function Interval({ estimate, ci, naive, truth, min = -0.9, max = 0.1, label }: IntervalProps) {
  if (estimate == null) return <span className="interval interval--none">not measurable</span>;
  return (
    <span className="interval" role="img" aria-label={label}>
      <span className="interval__zero" style={{ left: pos(0, min, max) }} />
      {ci && <span className="interval__ci" style={{ left: pos(ci[0], min, max), right: `calc(100% - ${pos(ci[1], min, max)})` }} />}
      {naive != null && <span className="interval__naive" style={{ left: pos(naive, min, max) }} title="naive comparison" />}
      {truth != null && <span className="interval__truth" style={{ left: pos(truth, min, max) }} title="simulator's truth" />}
      <span className="interval__dot" style={{ left: pos(estimate, min, max) }} />
    </span>
  );
}
