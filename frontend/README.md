# Agentic AI Platform PoC — UI (`frontend/`)

React 18 + TypeScript + Vite rebuild of the prototype in `../ui/`, per
[`../ui/DESIGN.md`](../ui/DESIGN.md). Faithful to `working/POC_SPEC.md` — same
agent names, tools, color tokens, and the canonical token contract.

## Run

```powershell
cd frontend
npm install
npm run dev      # http://localhost:5173  (mock data by default)
npm run build    # tsc --noEmit && vite build  → dist/
```

## Routes (4 total — POC_SPEC §1)

| Route          | Page                      | Use case |
|----------------|---------------------------|----------|
| `/`            | Demo Hub                  | landing  |
| `/credit-memo` | Credit Memo Drafting Agent| UC1 (HITL) |
| `/banking`     | Conversational Banking    | UC2 (deterministic boundary, handoff-only) |
| `/tokens`      | Token Usage Monitor       | observability |

## Headline behavior

A viewer can always tell **which agent is working**: working = colored fill +
glow + blinking `working…` chip; done = green + check; pending = dimmed. State is
never conveyed by color alone (text chip + icon always present). Animations are
gated behind `prefers-reduced-motion`.

## Architecture

- `src/types.ts` — canonical contracts (mirror the Cosmos containers).
- `src/theme.ts` — color tokens + price/cost helpers (mirrored in `styles.css` `:root`).
- `src/data/mockData.ts` — canned runs + token records (the simulated backend).
- `src/lib/` — one `Backend` interface, two implementations:
  - `mockBackend.ts` (dev, canned), `api.ts` (real FastAPI orchestrator).
  - selected by `VITE_USE_MOCK` in `src/lib/index.ts`.
- `src/hooks/useRunPlayer.ts` — the run state machine (play / step / reset /
  approve; pauses at the HITL gate; accumulates tokens + audit).
- `src/components/` — `AppShell`, `flow` (UC1 graph), `panels` (controls / tool
  card / HITL bar / audit / token counter), `banking` (zones / handoff /
  guardrail), `charts` (inline-SVG bar + donut), `primitives`.
- `src/pages/` — `DemoHub`, `CreditMemoPage`, `BankingPage`, `TokenMonitorDashboard`.

## Wiring to the real backend

Set `VITE_USE_MOCK=false` and `VITE_API_BASE_URL` (see `.env.example`). The
`Backend` interface maps 1:1 to the orchestrator routes (POC_SPEC §5):
`POST /api/runs`, `GET /api/runs/{id}` (+ SSE `/stream`),
`POST /api/runs/{id}/approve`, `GET /api/tokens`. Tool calls always go through
APIM server-side — the client never calls tools. Attach the `agpoc-ui` Entra
bearer token to all `/api/*` calls (MSAL; `VITE_ENTRA_CLIENT_ID` / `VITE_ENTRA_TENANT_ID`).

## Hard rules preserved

- UC1: the memo is **never final without human approval**.
- UC2: the agent **never moves money** — the terminal artifact is an auditable
  handoff object (`requires_confirmation` + `requires_step_up_auth`, `money_moved: false`).
- Guardrails are deterministic, not prompt-driven. All data is synthetic.
