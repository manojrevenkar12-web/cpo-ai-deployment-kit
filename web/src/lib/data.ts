import { useQuery } from "@tanstack/react-query";

/** The files `cpokit export-web` writes to public/data. */
export interface GateCheck { id: string; passed: boolean; detail: string }

export interface UseCaseRow {
  id: string;
  name: string;
  owner: { function: string; person: string };
  priority: number;
  score: { value: number; feasibility: number; risk: number };
  person_days: number;
  ready: boolean;
  users: string;
  eligible_people: number;
  adopted_people: number;
  usage_share_live: number;
  acceptance: number;
  impact_pct: number | null;
  impact_ci: [number, number] | null;
  impact_method: string | null;
  impact_note: string | null;
  hours_saved: number | null;
  hours_saved_ci: [number, number] | null;
  value_eur: number | null;
  money_moved_eur: number;
  first_live_week: number;
}

export interface Portfolio {
  generated: { world: { cases: Record<string, { dev: number; live: number }> }; deployment: { cases: number; used: number; llm_cost_eur: number } };
  gate: { passed: boolean; checks: GateCheck[] };
  use_cases: UseCaseRow[];
}

export interface Threshold { metric: string; value: number | null; target: number; kind: "min" | "max"; passed: boolean }
export interface ReadyCheck { check: string; passed: boolean; detail: string }

export interface Weekly { week: number; cases: number; used: number; users: number; active: number; usage_share: number }

export interface UseCaseDetail {
  id: string;
  name: string;
  owner: { function: string; person: string };
  discovery: { problem: string; users: string; systems: string[]; value_hypothesis: string; risks: string[]; baseline: Record<string, unknown> };
  models_read: string[];
  code_decides: string[];
  approvals: Record<string, string>;
  sprint: { person_days: number; plan: string[] };
  rollout: { waves: { week: number; countries: string[] }[] };
  handover: { to: string; when: string[]; runbook: string };
  readiness: { passed: boolean; checks: ReadyCheck[]; metrics: Record<string, unknown> };
  adoption: {
    eligible_people: number; adopted_people: number; usage_share_live: number; acceptance: number; rejected: number;
    weekly: Weekly[]; by_training: { trained: boolean | null; people: number; cases: number; usage_share: number }[];
    reopened_share: { with_tool: number; without_tool: number };
  };
  impact: {
    usage_share_live: number; naive_log: number | null; per_use_log?: number;
    rollout?: { pct: number; ci_pct?: [number, number]; method: string };
    note?: string; hours_saved?: number; hours_saved_ci?: [number, number]; value_eur?: number;
  };
  evaluation: {
    rollout_effect: { estimate_pct: number | null; truth_pct: number | null; ci_pct: [number, number] | null; truth_in_ci: boolean | null };
    per_use_effect: { estimate_pct: number | null; truth_pct: number | null; naive_pct: number | null };
    hours_saved: { estimate: number | null; ci: [number, number] | null; truth: number };
    tool_quality: { used: number; correct: number | null; wrong_caught: number; wrong_escaped: number; over_paid_eur: number };
    manual_quality: { cases: number; wrong: number };
  };
  handover_pack: string;
}

export interface Rollout {
  use_case: string;
  weeks: number[];
  countries: { country: string; launch: number | null; cells: { week: number; cases: number; used: number }[] }[];
  event_time: Record<string, number>;
}

export interface Evidence { label: string; value: unknown; source: string }
export interface ProposalAction { action_id: string; kind: string; amount: number | null; role: string | null; status: string; payload: Record<string, unknown> }
export interface Proposal {
  proposal_id: string;
  case_id: string;
  use_case: string;
  country: string;
  decision: string;
  detail: Record<string, unknown>;
  evidence: Evidence[];
  actions: ProposalAction[];
  draft: { language: string; text: string } | null;
  needs_review: boolean;
  review_reasons: string[];
  quarantined: string[];
  model_calls: { task: string; model: string; cost_eur: number; latency_ms: number }[];
  created_ts: number;
}

async function load<T>(path: string): Promise<T> {
  const res = await fetch(`./data/${path}`);
  if (!res.ok) throw new Error(`Could not load ${path} (HTTP ${res.status}). Run \`cpokit export-web\` and reload.`);
  return (await res.json()) as T;
}

export const usePortfolio = () => useQuery({ queryKey: ["portfolio"], queryFn: () => load<Portfolio>("portfolio.json") });
export const useUseCase = (id: string) => useQuery({ queryKey: ["usecase", id], queryFn: () => load<UseCaseDetail>(`usecases/${id}.json`) });
export const useRollout = () => useQuery({ queryKey: ["rollout"], queryFn: () => load<Rollout>("rollout.json") });
export const useProposals = () => useQuery({ queryKey: ["proposals"], queryFn: () => load<Proposal[]>("proposals.json") });
