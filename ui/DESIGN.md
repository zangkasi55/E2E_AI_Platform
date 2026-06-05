# UI / UX Design Spec — Agentic AI Platform PoC

Audience: developer continuing the build with **GitHub Copilot** in **React 18 + TypeScript + Vite**.
This spec describes the component tree, state model, color tokens, accessibility notes, and how to swap
the prototype's `mock-data.js` for the real FastAPI orchestrator routes. All names, tools, colors, and the
token contract are taken verbatim from `working/POC_SPEC.md` — do not rename them.

The self-contained prototype in this folder (`index.html`, `credit-memo.html`, `banking.html`,
`token-monitor.html`, `mock-data.js`) is the visual + interaction reference. The React app should be a
faithful rebuild with a real data layer.

---

## 1. Information architecture

```
/                         Demo Hub (landing)            → index.html
/credit-memo  (UC1)       Credit Memo Drafting Agent    → credit-memo.html
/banking      (UC2)       Conversational Banking Control→ banking.html
/tokens                   Token Usage Monitor           → token-monitor.html
```

Global frame on every route: dark top bar (breadcrumb + run/context tags), a light hero strip
(title + one-line explainer), then the route body. Two-column body for the two demos
(flow/work area on the left, observability rail on the right). Single scroll, laptop-first
(content max-width ~1120px), collapses to one column < 980px.

The **headline requirement** is that a viewer can always tell *which agent is working right now*.
Both demos express this the same way:
- **working** = colored fill + pulsing glow ring + a blinking `working…` chip
- **done** = green fill + check + solid green chip
- **pending** = dimmed (opacity) + neutral chip
The active state must be unmistakable even at a glance from across a room.

---

## 2. Component tree (React + TypeScript)

```
<App>                                  router + theme provider (color tokens)
├─ <AppShell>                          topbar, hero, breadcrumb, layout grid
│
├─ <DemoHub>                           landing cards → routes
│
├─ <CreditMemoPage>            (UC1)   owns useRunPlayer(runId="credit_memo")
│   ├─ <RunControls>                   Play / Step / Reset + run status
│   ├─ <AgentFlowGraph>                the live pipeline
│   │   ├─ <ParentAgentBanner>         memo_orchestrator (parent) active state
│   │   ├─ <AgentNode> × N             doc_retrieval, financial_ratio, bureau_summary, memo_assembler
│   │   ├─ <AgentNode variant="hitl">  human-review gate node
│   │   └─ <AgentNode variant="final"> final audited memo node
│   ├─ <StepTimeline>                  current step header + index/total
│   ├─ <ToolCallCard>                  tool + signature, APIM badge, params, result
│   ├─ <HITLApprovalBar>               Approve / Request edits (Durable Functions gate)
│   ├─ <AuditTrailPanel>               accumulating structured audit records
│   └─ <TokenCounter>                  live prompt/completion/total + consumer (agent · model · cost)
│
├─ <BankingPage>              (UC2)    owns useRunPlayer(runId="banking" | "banking_blocked")
│   ├─ <ChatPanel>                     mock chat thread + Send/Reset + UnsafeToggle
│   ├─ <ProbabilisticZone>            intent decomposition · slot filling · conditional logic
│   │   └─ <StageNode> × 3             active-state highlight (blue)
│   ├─ <DeterministicBoundary>        labeled divider "▲ probabilistic · deterministic ▼"
│   ├─ <DeterministicZone>            APIM bar + tool stages + PDP + Guardrails
│   │   ├─ <ApimControlBar>           tool-scope enforcement strip
│   │   ├─ <StageNode variant="tool"> get_balance, resolve_payee, check_transfer_eligibility, handoff
│   │   └─ <PolicyNode> × 2           PDP, Guardrails (active-state highlight)
│   ├─ <ToolCallCard>                  per-step detail (reused from UC1)
│   ├─ <HandoffObjectCard>            terminal auditable handoff JSON + flag chips
│   ├─ <GuardrailBlockBanner>         shown on the unsafe path
│   ├─ <AuditTrailPanel>             (reused)
│   └─ <TokenCounter>                (reused)
│
└─ <TokenMonitorDashboard>            /tokens
    ├─ <KpiCard> × 4                  total tokens · est. cost · prompt · completion
    ├─ <TokensByAgentChart>           inline-SVG horizontal bar chart (no chart libs)
    ├─ <TokensByModelDonut>           inline-SVG donut + <ChartLegend>
    └─ <RunTimelineTable>             per-run aggregation rows
```

Shared/leaf components: `<Badge>` (tool / apim / model / gov / blocked variants), `<StatusChip>`,
`<AnimatedNumber>` (token tick-up), `<JsonBlock>` (dark code panel), `<SvgBar>`, `<SvgDonutArc>`.

### Key component contracts (props)

```ts
type AgentStatus = "pending" | "working" | "done" | "blocked";

interface AgentNodeProps {
  id: string;                 // canonical agent id, e.g. "doc_retrieval"
  label: string;
  role: string;               // short descriptor
  status: AgentStatus;        // drives glow/check/dim — the headline behavior
  variant?: "subagent" | "parent" | "hitl" | "final";
}

interface ToolCallCardProps {
  step: number;
  agent: string;              // who is acting
  model?: ModelId;            // "gpt-4o" | "gpt-4o-mini" | undefined (deterministic, no model)
  tool?: ToolName;            // canonical tool catalog key
  viaApim: boolean;           // renders the "via APIM · scope-checked" badge
  params?: Record<string, unknown>;
  result: string;
  blocked?: boolean;
}

interface TokenRecord {       // canonical contract — POC_SPEC §Token monitoring
  run_id: string; agent: string; step: number; model: ModelId;
  prompt_tokens: number; completion_tokens: number; total_tokens: number;
  est_cost_usd: number; ts: string; use_case: "credit_memo" | "banking";
}

interface HandoffObject {     // UC2 terminal — POC_SPEC §UC2 hard rule
  handoff_id: string; intent: string; slots: Record<string, unknown>;
  policy_result: "permit" | "deny";
  requires_confirmation: true; requires_step_up_auth: true; money_moved: false;
  tool_trace: ToolName[];
}
```

---

## 3. State management

Keep it light — no Redux needed for a PoC.

- **`useRunPlayer(runId)`** — the central hook (the prototype's `AGPOC.player`). Holds
  `{ index, status, activeAgentId, tokens, audit[], handoff?, blocked }` in a reducer and exposes
  `play() / pause() / step() / reset() / approve()`. It walks an ordered `Step[]` either on a timer
  (`setInterval`) or one step at a time. The HITL step sets `status="awaiting_approval"` and stops the
  timer; `approve()` resumes to the final step.
- **Derived selectors**: node status map (`Record<agentId, AgentStatus>`) is computed from
  `index` + each step's target node so `<AgentFlowGraph>` stays a pure render of state.
- **Token state**: accumulate prompt/completion/total as steps emit `TokenRecord`s; `<AnimatedNumber>`
  eases the on-screen value to the new total. Deterministic tool steps emit no record (no model call).
- **Dashboard**: pure functions `aggregate(records)` → `{ total, byAgent, byModel, byRun }`
  (already implemented in `mock-data.js`); the dashboard is stateless given the record array.
- Context: a `<ThemeProvider>` exposes the color tokens; a `<RunContext>` can share the active run
  across panels on a page. Prefer React Query/SWR for the real data layer (see §5).

---

## 4. Color tokens (from POC_SPEC §Color language — reuse exactly)

```ts
export const colors = {
  agent:    "#0B5CAB",  // parent agent / orchestrator
  agent2:   "#2E7DD1",  // sub-agent / active working fill
  model:    "#5B2D8E",  // model calls (gpt-4o)
  tool:     "#0E7C7B",  // tools / APIM tool zone
  data:     "#2E7D32",  // data + "ok"
  gov:      "#7A1FA2",  // governance / PDP
  obs:      "#C25E00",  // observability / HITL pause / audit
  sec:      "#1A4E8A",  // security
  channel:  "#37474F",  // channels / user
  blocked:  "#B3261E",  // blocked + deterministic boundary
  ok:       "#2E7D32",  // success / done
  ink:      "#1A1A1A",  // text
  muted:    "#5F6B7A",  // secondary text
} as const;
```

Semantic mapping used by the UI: **working** uses `agent2` (UC1) / `tool` (UC2 deterministic);
**done** uses `ok`; **HITL pause** uses `obs`; **guardrail block** + the probabilistic/deterministic
boundary use `blocked`; **PDP / governance** uses `gov`; **model badges** use `model`.

---

## 5. Wiring to the real backend (swap out `mock-data.js`)

The prototype's `AGPOC` object is a stand-in for the FastAPI orchestrator (`agpoc-aca-orch-dev`) +
Cosmos containers (`runs`, `steps`, `handoffs`, `tokens`). Components map 1:1 to these routes —
replace the canned reads with `fetch`/React Query calls and keep the same shapes.

| Prototype call                         | Real route (FastAPI orchestrator)             | Cosmos source        | Used by |
|----------------------------------------|-----------------------------------------------|----------------------|---------|
| `AGPOC.getRun("credit_memo")`          | `POST /api/runs` (start) → `{ run_id }`       | `runs`               | UC1 page |
| run steps (canned array)               | `GET /api/runs/{run_id}` + SSE `/api/runs/{run_id}/stream` | `steps`  | AgentFlowGraph, ToolCallCard, AuditTrailPanel |
| HITL `player.resume()` on Approve      | `POST /api/runs/{run_id}/approve` `{ decision, reviewer, edits? }` | `runs` (Durable Functions resume) | HITLApprovalBar |
| `AGPOC.getRun("banking")` + steps      | `POST /api/runs` (use_case=banking) + stream  | `runs`/`steps`       | UC2 page |
| handoff object (terminal step)         | `GET /api/runs/{run_id}/handoff`              | `handoffs`           | HandoffObjectCard |
| unsafe path / guardrail block          | same start route; server returns `blocked` step | `steps` (policy)   | GuardrailBlockBanner |
| `AGPOC.getTokens()` + `aggregate()`    | `GET /api/tokens?from=&to=&use_case=`         | `tokens`             | TokenMonitorDashboard |

Notes for the integration:
- Each `step` event is a `StepRecord` from the orchestrator (Semantic Kernel function/tool result).
  Tool calls go **through APIM** (`agpoc-apim-dev`); the UI's `viaApim` badge mirrors the server's
  scope/PDP decision — never call tools directly from the client.
- Every model call writes a `TokenRecord` to Cosmos `tokens` and emits App Insights metric
  `gen_ai.token.usage`. The dashboard reads the same records — keep field names identical so no
  transform is needed.
- Prefer **SSE / WebSocket streaming** for the live flow so node highlighting reflects real
  orchestration timing; fall back to polling `GET /api/runs/{id}` for the PoC if streaming is not ready.
- Auth: the UI app registration is `agpoc-ui` (Entra ID); attach a bearer token to all `/api/*` calls.
- Replace the illustrative `PRICE` table with the deployment's real per-1K rates for `est_cost_usd`,
  or read `est_cost_usd` straight from the server records.

---

## 6. Accessibility & contrast

- **Do not rely on color alone** for agent state. Every state also carries a text chip
  (`working…` / `done` / `pending` / `blocked`) and an icon (pulse dot, check, ⛛, ⛔). This keeps the
  "which agent is working" signal legible for color-vision-deficient users.
- **Contrast**: body ink `#1A1A1A` on `#FFFFFF`/`#F3F6FB` ≈ 16:1. White text sits only on the deep
  brand fills (`agent`, `tool`, `blocked`, `ok`, `obs`, `#0B2A4A` bar), all ≥ 4.5:1. Avoid white text
  on `agent2` for small text — use it as a fill with dark labels beside it (as the prototype does).
- **Motion**: pulse/blink animations are decorative; gate them behind
  `@media (prefers-reduced-motion: reduce)` in the React build (the static state must still read as
  "working" via chip + ring without animation).
- **Semantics**: flow nodes are a list/`<ol>` with `aria-current="step"` on the active node and
  `aria-label` describing status; the audit trail is an `<ol>`; charts get `role="img"` + a text
  `aria-label` summarizing the data (the prototype SVGs already set this).
- **Keyboard**: Play/Step/Reset, Approve/Request-edits, Send, and the Unsafe toggle are real
  `<button>`/`<label><input>` elements — keep them focusable with visible focus rings.
- **Tabular numbers** (`font-variant-numeric: tabular-nums`) on all token counters and the timeline
  table so digits don't jitter as they tick.

---

## 7. Mapping the prototype files → React modules

| Prototype file        | Becomes (React)                                              |
|-----------------------|-------------------------------------------------------------|
| `index.html`          | `DemoHub.tsx` + route cards                                  |
| `credit-memo.html`    | `CreditMemoPage.tsx` + `AgentFlowGraph`, `HITLApprovalBar`   |
| `banking.html`        | `BankingPage.tsx` + `ProbabilisticZone`/`DeterministicZone`, `HandoffObjectCard` |
| `token-monitor.html`  | `TokenMonitorDashboard.tsx` + SVG chart components          |
| `mock-data.js`        | `lib/mockBackend.ts` (dev) **and** `lib/api.ts` (real fetch); both satisfy the same `RunPlayer` + `TokenRecord` interfaces |

Keep `mock-data.js`'s shapes as the TypeScript source of truth (`types.ts`). The dev mock and the real
API are interchangeable behind one interface, so the UI never changes when the backend lands.
