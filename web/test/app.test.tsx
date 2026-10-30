import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Interval } from "../src/components/Interval";
import { Portfolio } from "../src/features/portfolio/Portfolio";
import { Proposals } from "../src/features/proposals/Proposals";
import { signedPct } from "../src/lib/format";

const portfolio = {
  generated: { world: { cases: {} }, deployment: { cases: 2478, used: 736, llm_cost_eur: 0.32 } },
  gate: { passed: true, checks: [{ id: "no-money-moved-wrongly", passed: true, detail: "0.00 EUR" }] },
  use_cases: [
    {
      id: "driver_refunds", name: "Driver refund tickets", owner: { function: "customer_service", person: "Head of CS" },
      priority: 6.7, score: { value: 5, feasibility: 4, risk: 3 }, person_days: 9, ready: true, users: "43 agents",
      eligible_people: 43, adopted_people: 40, usage_share_live: 0.38, acceptance: 0.95, impact_pct: -0.2,
      impact_ci: [-0.32, -0.07], impact_method: "staggered difference-in-differences", impact_note: null,
      hours_saved: 100, hours_saved_ci: [30, 180], value_eur: 5500, money_moved_eur: 5400, first_live_week: 5,
    },
    {
      id: "tender_answers", name: "Tender and grant questionnaires", owner: { function: "bid_team", person: "Head of BD" },
      priority: 4, score: { value: 4, feasibility: 4, risk: 4 }, person_days: 6, ready: true, users: "4",
      eligible_people: 4, adopted_people: 4, usage_share_live: 0.63, acceptance: 0.88, impact_pct: null,
      impact_ci: null, impact_method: null, impact_note: "no cases before launch", hours_saved: null,
      hours_saved_ci: null, value_eur: null, money_moved_eur: 0, first_live_week: 10,
    },
  ],
};

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function mockFetch(body: unknown, status = 200) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));
}

afterEach(() => vi.unstubAllGlobals());

describe("portfolio", () => {
  it("orders by priority and says when an effect cannot be measured", async () => {
    mockFetch(portfolio);
    wrap(<Portfolio onOpen={() => {}} />);
    const rows = await screen.findAllByRole("row");
    expect(rows[1]).toHaveTextContent("Driver refund tickets");
    expect(screen.getByText("no cases before launch")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Release gate: passed/ })).toBeInTheDocument();
  });

  it("shows an error with a retry when the data is missing", async () => {
    mockFetch({}, 404);
    wrap(<Portfolio onOpen={() => {}} />);
    expect(await screen.findByRole("alert", {}, { timeout: 5000 })).toHaveTextContent("HTTP 404");
    expect(screen.getByRole("button", { name: "Load again" })).toBeInTheDocument();
  });

  it("shows a skeleton while loading", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    wrap(<Portfolio onOpen={() => {}} />);
    expect(screen.getByRole("status", { name: "Loading the use cases" })).toBeInTheDocument();
  });

  it("invites a first use case when there is none", async () => {
    mockFetch({ ...portfolio, use_cases: [] });
    wrap(<Portfolio onOpen={() => {}} />);
    expect(await screen.findByText("No use cases yet")).toBeInTheDocument();
  });
});

describe("proposals", () => {
  it("names the approver role for money and says nothing executes", async () => {
    mockFetch([
      {
        proposal_id: "P1", case_id: "D-1", use_case: "cdr_disputes", country: "DE", decision: "credit",
        detail: {}, evidence: [{ label: "CDR as billed", value: { total: 12.4 }, source: "ocpi:cdr/CDR-1" }],
        actions: [{ action_id: "A1", kind: "credit_note", amount: 3.1, role: "finance_approver", status: "proposed", payload: {} }],
        draft: { language: "de", text: "Vielen Dank" }, needs_review: false, review_reasons: [], quarantined: ["x"],
        model_calls: [], created_ts: 0,
      },
    ]);
    wrap(<Proposals />);
    expect(await screen.findByText(/needs finance approver in Teams/)).toBeInTheDocument();
    expect(screen.getByText(/kept away from the model/)).toBeInTheDocument();
    expect(screen.getByText("ocpi:cdr/CDR-1")).toBeInTheDocument();
  });
});

describe("interval", () => {
  it("says when there is no estimate", () => {
    render(<Interval estimate={null} label="x" />);
    expect(screen.getByText("not measurable")).toBeInTheDocument();
  });

  it("formats signed percentages with a real minus", () => {
    expect(signedPct(-0.2)).toBe("−20%");
    expect(signedPct(0.05)).toBe("+5%");
  });
});
