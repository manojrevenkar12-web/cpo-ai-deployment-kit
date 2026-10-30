import { useEffect, useState } from "react";
import { usePortfolio } from "./lib/data";
import { Portfolio } from "./features/portfolio/Portfolio";
import { Proposals } from "./features/proposals/Proposals";
import { RolloutPage } from "./features/rollout/Rollout";
import { UseCasePage } from "./features/usecase/UseCase";

type Route = { page: "portfolio" } | { page: "rollout" } | { page: "proposals" } | { page: "usecase"; id: string };

const parse = (hash: string): Route => {
  const [page, id] = hash.replace(/^#\/?/, "").split("/");
  if (page === "rollout") return { page: "rollout" };
  if (page === "proposals") return { page: "proposals" };
  if (page === "use-case" && id) return { page: "usecase", id };
  return { page: "portfolio" };
};

const TABS: { page: Route["page"]; label: string; hash: string }[] = [
  { page: "portfolio", label: "Use cases", hash: "#/" },
  { page: "rollout", label: "Rollout and impact", hash: "#/rollout" },
  { page: "proposals", label: "Proposals", hash: "#/proposals" },
];

function GateBadge() {
  const q = usePortfolio();
  if (!q.data) return null;
  return (
    <span className={`badge ${q.data.gate.passed ? "badge--ok" : "badge--bad"}`}>
      Release gate {q.data.gate.passed ? "passed" : "failed"}
    </span>
  );
}

export function App() {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));
  useEffect(() => {
    const on = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = (hash: string) => {
    window.location.hash = hash;
  };
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="band">
        <div className="band__inner">
          <p className="brand">
            <span className="brand__name">Deployment desk</span>
            <span className="brand__unit">AI unit of a charge point operator (simulated)</span>
          </p>
          <GateBadge />
        </div>
        <nav className="tabs" aria-label="Sections">
          {TABS.map((t) => (
            <a
              key={t.page}
              href={t.hash}
              className="tab"
              aria-current={route.page === t.page || (route.page === "usecase" && t.page === "portfolio") ? "page" : undefined}
            >
              {t.label}
            </a>
          ))}
        </nav>
      </header>
      <main id="main" className="page">
        {route.page === "portfolio" && <Portfolio onOpen={(id) => go(`#/use-case/${id}`)} />}
        {route.page === "rollout" && <RolloutPage />}
        {route.page === "proposals" && <Proposals />}
        {route.page === "usecase" && <UseCasePage id={route.id} onBack={() => go("#/")} />}
      </main>
    </>
  );
}
