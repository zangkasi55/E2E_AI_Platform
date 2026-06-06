// =============================================================================
// components/AppShell.tsx — global frame: dark top bar (brand + breadcrumb +
// nav + context tags), light hero strip (use-case pill + title + explainer).
// Wraps each route body. POC_SPEC §1 information architecture.
// =============================================================================
import { Link, useLocation } from "react-router-dom";
import { USE_MOCK } from "../lib";

const NAV = [
  { to: "/", label: "Hub" },
  { to: "/credit-memo", label: "Credit Memo" },
  { to: "/credit-memo-16bit", label: "Credit Memo 16 bit" },
  { to: "/banking", label: "Banking" },
  { to: "/governance", label: "Governance" },
  { to: "/test-expectations", label: "Test Expectations" },
  { to: "/tokens", label: "Tokens" },
];

export interface HeroProps {
  uc?: "credit_memo" | "banking" | "tokens";
  ucLabel?: string;
  title: string;
  subtitle: string;
  tags?: string[];
  crumb?: string;
}

export function AppShell({
  hero,
  children,
}: {
  hero: HeroProps;
  children: React.ReactNode;
}) {
  const loc = useLocation();
  const ucClass = hero.uc === "banking" ? "uc2" : hero.uc === "tokens" ? "tokens" : "";

  return (
    <>
      <header className="topbar">
        <span className="brand">
          <span className="dot" aria-hidden />
          Agentic AI Platform
        </span>
        <nav className="crumbs" aria-label="Breadcrumb">
          <Link to="/">PoC</Link>
          <span className="sep">›</span>
          <span className="cur">{hero.crumb ?? hero.title}</span>
        </nav>
        <nav className="nav" aria-label="Primary">
          {NAV.map((n) => (
            <Link key={n.to} to={n.to} className={loc.pathname === n.to ? "active" : ""}>
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="tags">
          <span className="tag">TechX · DataX · SCBX · MS</span>
          <span className="tag">{USE_MOCK ? "mock data" : "live orchestrator"}</span>
          {(hero.tags ?? []).map((t) => (
            <span className="tag" key={t}>
              {t}
            </span>
          ))}
        </div>
      </header>

      <section className="hero">
        <div className="wrap">
          {hero.ucLabel && <span className={`uc ${ucClass}`}>{hero.ucLabel}</span>}
          <h1>{hero.title}</h1>
          <p>{hero.subtitle}</p>
        </div>
      </section>

      {children}
    </>
  );
}
