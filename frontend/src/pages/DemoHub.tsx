// =============================================================================
// pages/DemoHub.tsx (/) — landing page. Route cards to the two demos + the
// token monitor. POC_SPEC §1 information architecture (4 routes total).
// =============================================================================
import { Link } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { colors } from "../theme";

interface CardDef {
  to: string;
  kicker: string;
  title: string;
  desc: string;
  glyph: string;
  color: string;
}

const CARDS: CardDef[] = [
  {
    to: "/credit-memo",
    kicker: "UC1 · Credit Memo",
    title: "Credit Memo Drafting Agent",
    desc:
      "Parent orchestrator + 4 sub-agents draft a credit memo from synthetic loan data. Read-only, with a human-in-the-loop approval gate before anything is final.",
    glyph: "MO",
    color: colors.agent,
  },
  {
    to: "/credit-memo-16bit",
    kicker: "UC1 · Arcade Mode",
    title: "Credit Memo 16 bit",
    desc:
      "The same Credit Memo orchestration, re-skinned as a 16-bit RPG. Every agent is an animated pixel sprite in a throne room — watch them work, pause at the human gate, and celebrate on approval. Same real run, tokens, audit & DSPM data.",
    glyph: "🎮",
    color: colors.gov,
  },
  {
    to: "/banking",
    kicker: "UC2 · Conversational Banking",
    title: "Conversational Banking Control",
    desc:
      "Probabilistic intent reasoning meets a deterministic control boundary: APIM tool scoping + a Policy Decision Point. The agent never moves money — it emits an auditable handoff object.",
    glyph: "▣",
    color: colors.tool,
  },
  {
    to: "/tokens",
    kicker: "Observability",
    title: "Token Usage Monitor",
    desc:
      "Cost-governance dashboard. Aggregates the gen_ai.token.usage records every model call writes to Cosmos — by agent, model, and run.",
    glyph: "∑",
    color: colors.obs,
  },
  {
    to: "/test-expectations",
    kicker: "Conformance",
    title: "Test Expectations Dashboard",
    desc:
      "Live conformance board for customer minimum expectations and assessment criteria, tagged as demonstrated, mocked, or documented.",
    glyph: "✓",
    color: colors.gov,
  },
];

export function DemoHub() {
  return (
    <AppShell
      hero={{
        crumb: "Demo Hub",
        title: "Agentic AI Platform — PoC",
        subtitle:
          "A Microsoft-native, multi-agent platform for TechX · DataX · SCBX · MS. Two banking use cases demonstrate orchestrated sub-agents, a deterministic tool/governance boundary, human-in-the-loop control, and full token-level observability. All data is synthetic.",
        tags: ["southeastasia", "agpoc · dev"],
      }}
    >
      <main className="page">
        <div className="hubgrid">
          {CARDS.map((c) => (
            <Link className="card" to={c.to} key={c.to}>
              <span className="ic" style={{ background: c.color }} aria-hidden>
                {c.glyph}
              </span>
              <div className="ck">{c.kicker}</div>
              <h3>{c.title}</h3>
              <p>{c.desc}</p>
              <span className="go">Open demo →</span>
            </Link>
          ))}
        </div>

        <div className="panel" style={{ marginTop: 18 }}>
          <h2>What this PoC proves</h2>
          <p className="sub" style={{ marginBottom: 10 }}>
            The platform pillars, each visible in the demos above.
          </p>
          <ul style={{ margin: 0, paddingLeft: 18, color: colors.muted, fontSize: 13, lineHeight: 1.9 }}>
            <li>
              <strong>Multi-agent orchestration</strong> — a parent agent plans and dispatches specialized sub-agents.
            </li>
            <li>
              <strong>Deterministic governance boundary</strong> — tools run through APIM with scope enforcement and a Policy Decision Point; guardrails are rule-based, not prompt-driven.
            </li>
            <li>
              <strong>Human-in-the-loop</strong> — Durable Functions suspend the workflow for human approval (UC1) and the banking agent only ever produces a handoff object (UC2).
            </li>
            <li>
              <strong>Token-level observability</strong> — every model call is metered to App Insights + Cosmos for cost governance.
            </li>
          </ul>
        </div>
      </main>
    </AppShell>
  );
}
