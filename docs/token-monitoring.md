# Token & Cost Monitoring — Agentic AI Platform PoC

This is the full specification for **P8** (token & cost monitoring) and **G8** (live dashboard). It defines the record contract, the write path, the metric, the query API, and the UI aggregations. Every model call in the platform — in mock or live mode — produces exactly one token record.

---

## 1. Why this exists

Regulated AI workloads must answer two questions at any time:

1. **What did this run cost, and where did the cost go?** (per agent, per model, per step)
2. **Is any agent burning tokens abnormally?** (runaway loops, prompt bloat, model misassignment)

Token monitoring is not a nice-to-have here — it is part of the control story. The same per-step record that proves "the model only requested, never executed" also carries the token counts, so cost attribution and audit attribution share one spine.

---

## 2. The token record (canonical contract)

Every model call emits exactly one record. This schema is the single source of truth (mirrors `working/POC_SPEC.md`); backend, Cosmos, and UI all bind to it.

```json
{
  "run_id": "uuid",
  "agent": "doc_retrieval",
  "step": 3,
  "model": "gpt-4o",
  "prompt_tokens": 0,
  "completion_tokens": 0,
  "total_tokens": 0,
  "est_cost_usd": 0.0,
  "ts": "iso8601",
  "use_case": "credit_memo"
}
```

| Field | Type | Meaning |
|---|---|---|
| `run_id` | uuid | Correlates to the workflow run (Cosmos `runs` / `steps` partition key). |
| `agent` | string | Emitting agent — `memo_orchestrator`, `doc_retrieval`, `financial_ratio`, `bureau_summary`, `memo_assembler`, `banking_controller`. |
| `step` | int | Monotonic step index within the run (aligns with the per-step audit record, architecture §2.3). |
| `model` | string | Deployment used — `gpt-4o` or `gpt-4o-mini`. Recorded per call because model is assigned per step. |
| `prompt_tokens` | int | Input tokens. |
| `completion_tokens` | int | Output tokens. |
| `total_tokens` | int | `prompt_tokens + completion_tokens` (stored, not derived at read time). |
| `est_cost_usd` | float | Computed at write time from the price table (§4). Frozen so historical cost is stable even if prices change. |
| `ts` | iso8601 | UTC timestamp of the call completion. |
| `use_case` | string | `credit_memo` or `banking`. Enables per-use-case rollups. |

**Invariant:** one model call → one record. No batching, no sampling. If a step makes two model calls, that is two records with the same `run_id`/`step` and different `ts`.

---

## 3. Write path

```
Agent makes a model call
        │
        ▼
 backend/app/telemetry/tokens.py  (record_token_usage)
        │
        ├──► Cosmos DB  agpoc-cosmos-dev / agentaudit / tokens   (partition key /run_id)
        │
        └──► App Insights custom metric  gen_ai.token.usage
                 dimensions: agent, model, use_case
```

- **Source of counts (live mode):** the Azure OpenAI response `usage` object (`prompt_tokens`, `completion_tokens`, `total_tokens`).
- **Source of counts (mock mode):** estimated with the `len(text)/4` heuristic so the dashboard is fully populated with **zero Azure**. Records are flagged implicitly by `MOCK_MODE` in the run metadata; the schema is identical so the UI needs no special-casing.
- **Cost:** `est_cost_usd` is computed at write time (§4) and stored. Never recomputed on read.
- **Failure isolation:** token recording is best-effort and must never fail a run. A Cosmos write error is logged and swallowed; the App Insights emit is independent so one path failing does not lose the other.

---

## 4. Cost model

Cost is computed per record from a small, version-pinned price table (`backend/app/telemetry/pricing.py`). Prices are **illustrative PoC placeholders** — the table is the one place to update for real rates.

```python
# USD per 1K tokens — PoC placeholders, update for real pricing
PRICING = {
    "gpt-4o":      {"prompt": 0.0025, "completion": 0.010},
    "gpt-4o-mini": {"prompt": 0.00015, "completion": 0.0006},
}

def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    p = PRICING[model]
    return round(
        (prompt_tokens / 1000) * p["prompt"]
        + (completion_tokens / 1000) * p["completion"],
        6,
    )
```

Because model is assigned per step (gpt-4o for synthesis, gpt-4o-mini for cheap sub-steps — see `tech-stack.md` §5), the dashboard's by-model split directly shows the savings from that policy.

---

## 5. Custom metric — `gen_ai.token.usage`

- Emitted via `azure-monitor-opentelemetry` as a counter named **`gen_ai.token.usage`**.
- **Value:** `total_tokens` per call.
- **Dimensions:** `agent`, `model`, `use_case`.
- Enables Azure Monitor / Log Analytics charts and alerts without querying Cosmos — e.g., alert when tokens-per-run exceeds a threshold (runaway-loop guard, complements the APIM per-run rate limit).
- Saved KQL lives in `infra/observability/kql/token_usage.kql`.

Example KQL (tokens by agent over time):

```kusto
customMetrics
| where name == "gen_ai.token.usage"
| extend agent = tostring(customDimensions.agent),
         model = tostring(customDimensions.model),
         use_case = tostring(customDimensions.use_case)
| summarize tokens = sum(valueSum) by agent, bin(timestamp, 5m)
| order by timestamp asc
```

---

## 6. Query API (backend)

Two read endpoints back the dashboard. Both read from Cosmos `tokens` (point/range reads on `/run_id`).

### `GET /api/tokens/summary`
Cross-run rollup for the dashboard landing state.

```json
{
  "total_tokens": 0,
  "total_cost_usd": 0.0,
  "by_agent":  [{ "agent": "doc_retrieval", "total_tokens": 0, "est_cost_usd": 0.0 }],
  "by_model":  [{ "model": "gpt-4o", "total_tokens": 0, "est_cost_usd": 0.0 }],
  "by_use_case": [{ "use_case": "credit_memo", "total_tokens": 0, "est_cost_usd": 0.0 }],
  "runs": 0
}
```

### `GET /api/tokens/run/{id}`
Per-run drill-down — drives the timeline.

```json
{
  "run_id": "uuid",
  "use_case": "credit_memo",
  "total_tokens": 0,
  "total_cost_usd": 0.0,
  "by_agent": [{ "agent": "memo_orchestrator", "total_tokens": 0, "est_cost_usd": 0.0 }],
  "by_model": [{ "model": "gpt-4o", "total_tokens": 0, "est_cost_usd": 0.0 }],
  "timeline": [
    { "step": 1, "agent": "memo_orchestrator", "model": "gpt-4o",
      "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
      "est_cost_usd": 0.0, "ts": "iso8601" }
  ]
}
```

The per-run `timeline` is ordered by `step`/`ts`, so the UI can render a left-to-right strip showing **which agent ran when and how heavy each step was** — reinforcing G9 (show the agent flow and the active agent).

---

## 7. UI — Token Monitor panel (`ui/token-monitor.html`)

The prototype panel (offline HTML/CSS/JS; React target in `ui/DESIGN.md`) aggregates:

| Widget | Source | Shows |
|---|---|---|
| **Total tokens + est. cost** | `GET /api/tokens/summary` | Headline KPIs across all runs. |
| **Tokens by agent** | `summary.by_agent` | Bar chart — which agent is the cost driver. Bars use the agent color language (architecture / `POC_SPEC.md`). |
| **Tokens by model** | `summary.by_model` | gpt-4o vs gpt-4o-mini split — proves the per-step model policy pays off. |
| **Est. cost by use case** | `summary.by_use_case` | credit_memo vs banking cost. |
| **Per-run timeline** | `GET /api/tokens/run/{id}` | Step-by-step strip: step #, agent (colored), model, total tokens, cost — the active-agent narrative for one run. |

Color binding (from the canonical color language): agent `#0B5CAB`, agent2 `#2E7DD1`, model `#5B2D8E`, tool `#0E7C7B`, data `#2E7D32`, obs `#C25E00`. The token panel reuses these so a reviewer reads the same colors across the architecture deck, the agent-flow demo, and the cost view.

---

## 8. Mapping to requirements

| Requirement | Where satisfied |
|---|---|
| **P8** — token & cost per call/agent/model/run, surfaced in a dashboard | §2 record, §3 write path, §6 API, §7 UI |
| **G8** — live dashboard of tokens + cost by agent and model for a run | §6 `GET /api/tokens/run/{id}`, §7 timeline + by-agent/by-model widgets |
| **A1.4** — token usage retrievable and attributed per agent/model (UC1) | §6 per-run drill-down |
| Success criterion #5 — dashboard shows tokens + est. cost by agent and model for a run | §7 |

---

## 9. Demo checklist

1. Run a UC1 credit-memo flow (mock mode) → open Token Monitor → confirm totals, by-agent bars (orchestrator + 4 sub-agents), by-model split.
2. Open the run timeline → confirm each step shows agent + model + tokens in order.
3. Run a UC2 banking flow → confirm a second use-case appears in the by-use-case rollup.
4. (Live mode, if provisioned) confirm `gen_ai.token.usage` appears in App Insights with `agent`/`model`/`use_case` dimensions and the saved KQL renders.
