# Production Design Notes — Agentic AI Platform PoC

**Context:** DataX / TechX × Microsoft, SCBX Group · Demo 2026-06-19
**Purpose:** The *Scope Calibration* document permits capabilities that cannot be fully built in the PoC window to be delivered as **design notes**, and requires (for Azure Storage specifically) a documented production connectivity design. This file collects those notes.

Each note follows the customer's **Documentation-May-Supplement-Implementation** 10-point template:

1. Target production pattern · 2. Relevant CSP-native services · 3. Implementation steps · 4. Security & governance controls · 5. Observability & audit model · 6. Regional & data-residency considerations · 7. Known limitations · 8. Estimated complexity to productionize · 9. Dependencies on preview/roadmap features · 10. Open questions requiring follow-up.

> These notes are written to be **specific enough to assess feasibility**, per the customer's instruction that generic product descriptions are not sufficient.

---

## 1. Azure Storage connectivity (Blob / ADLS Gen2)

**Why a design note:** Per *Data and Integration Simplification*, the PoC does **not** connect to Azure Blob/ADLS Gen2. Azure remains the Group production storage layer; the PoC runs from local synthetic `data/`. This note documents the four points the customer explicitly requested — secure connectivity, authn/authz, data movement & residency, operational burden — plus the rest of the 10-point template.

### 1. Target production pattern
Orchestrator (Container Apps) and tool Functions read approved-source documents and synthetic→real datasets from **ADLS Gen2** (hierarchical namespace for the credit corpus and memo templates) and **Blob** (rendered memo drafts). Access is **private-only** (no public endpoint), brokered by **managed identity**, and every read/write is classified and audited. No storage account key or SAS is ever used by the agents.

### 2. Relevant CSP-native services
- **Azure Storage** (ADLS Gen2 + Blob), `agpocstoragedev` → prod `…stg`.
- **Private Endpoints + Private Link** for `blob` and `dfs` sub-resources.
- **Private DNS zones** `privatelink.blob.core.windows.net`, `privatelink.dfs.core.windows.net`.
- **Microsoft Entra ID** workload identities (orchestrator + per-Function identity).
- **Azure RBAC** data-plane roles (Storage Blob Data Reader / Contributor).
- **Microsoft Purview** for classification + lineage over the registered storage source.
- **Key Vault** (only for any unavoidable non-Entra secret; goal is keyless).

### 3. Implementation steps
1. Provision storage with `allowBlobPublicAccess=false`, `defaultToOAuthAuthentication=true`, HNS enabled on the Gen2 account.
2. Create Private Endpoints for `blob` and `dfs`; link the private DNS zones to the workload VNet.
3. Disable the public network path (`publicNetworkAccess=Disabled`); integrate Container Apps + Functions with the VNet (VNet-injected environment).
4. Assign **Storage Blob Data Reader** to the orchestrator identity at container scope (least privilege — readers cannot write); assign **Contributor** only to the memo-render Function on the `memos` container.
5. Register the account in Purview; run classification scans (§Purview note); export classifications to drive APIM PII filtering.
6. Switch the backend from `MOCK_MODE` local reads to `DefaultAzureCredential` + `azure-storage-blob` / `azure-storage-file-datalake` clients — **no code-path change in the tools**, only the data source binding.

### 4. Security & governance controls
- **Authentication:** managed identity via `DefaultAzureCredential`; **no keys, no SAS, no connection strings**. Storage account key access disabled (`allowSharedKeyAccess=false`).
- **Authorization:** Entra RBAC at container/path scope; reader vs contributor split by Function role. ABAC conditions can pin access to a specific container path prefix.
- **Network:** Private Link only; public access disabled; traffic stays on the Microsoft backbone.
- **Encryption:** platform-managed keys by default; customer-managed keys (Key Vault) optional for the Group's compliance posture.
- **Governance:** Purview classifications on every container; "approved sources" becomes a governed fact, not a convention (see Purview note).

### 5. Observability & audit model
- **Storage diagnostic logs** (`StorageRead` / `StorageWrite` / `StorageDelete`) → Log Analytics `agpoc-law-dev`; retained for audit.
- Each tool read emits a **per-step audit record** (`run_id, step, agent, tool_called, params_hash, result_summary, ts`) to Cosmos `steps`, so "which agent read which document" is queryable per run.
- **Purview lineage** captures source → AI Search index → tool → agent, answering "where did this fact come from?" (rendered in the demo Purview observability view — see §5 of the Purview note).
- Alert on anomalous read volume / denied-access spikes via Azure Monitor.

### 6. Regional & data-residency considerations
- All storage in **`southeastasia`**, co-located with AOAI, Search, Cosmos to keep data in-region and minimize egress.
- No cross-region replication of customer data unless the Group's BCDR policy requires it; if so, pair to `southeastasia` paired region with documented residency sign-off.
- Purview account in-region; classifications and lineage metadata also reside in-region.

### 7. Known limitations
- VNet injection for Container Apps + Functions adds networking surface (subnets, NSGs, private DNS) that must be operated.
- ADLS Gen2 POSIX ACLs vs Entra RBAC can overlap; pick one authorization model (recommend RBAC + ABAC) to avoid drift.
- Private DNS misconfiguration is the most common failure mode; validate resolution from the workload subnet before cutover.

### 8. Estimated complexity to productionize
**Low-to-medium.** Storage + Private Link + RBAC + managed identity is a well-trodden, fully native pattern. Estimate ~2–3 engineering days for infra (Bicep already models the account in `infra/modules/storage.bicep`) plus ~1 day to flip the backend binding from local to `DefaultAzureCredential`. The tool contracts do not change.

### 9. Dependencies on preview or roadmap features
None. ADLS Gen2 + Private Link + Entra RBAC + managed identity are all GA.

### 10. Open questions requiring follow-up
- Does the Group mandate customer-managed keys for this data class?
- Is VNet injection acceptable for Container Apps in the target subscription, or is a Private Link Service / App Gateway fronting required?
- Confirm the approved-source corpus owner and the classification taxonomy the Group's Purview already uses (to align, not reinvent).

---

## 2. Microsoft Purview — governance **and observability** design note

**Why this note:** Purview is the system of record for "approved sources," and — per the user's request — it is also an **observability surface**: it makes *data provenance, classification coverage, and the governance→runtime link* visible to a reviewer. This note designs both the production pattern and **how the PoC demonstrates Purview observability** (the offline view `ui/purview-observability.html`).

### 1. Target production pattern
A governed data estate where (a) every source the agents can touch is registered and scanned, (b) every sensitive field carries a classification, (c) those classifications **drive runtime PII filtering at the APIM boundary**, and (d) **lineage** links each fact from source → index → tool → agent → output. Governance is observable, not just configured: a reviewer can answer "is this source approved?", "what PII does it contain?", and "where did this number in the memo come from?".

### 2. Relevant CSP-native services
- **Microsoft Purview** — Data Map, classification (built-in + custom), scan rulesets, lineage, glossary, Data Estate Insights.
- **Azure AI Search**, **Azure Storage**, **Azure Functions** as lineage participants.
- **Azure API Management** as the runtime enforcement point fed by classifications.
- **App Insights / Log Analytics** for the runtime audit that complements Purview's design-time governance.

### 3. Implementation steps
1. Create Purview account `agpoc-purview-dev`; collection `agentic-poc`.
2. Register sources: storage (`synthetic`, `memos`, `templates`), the AI Search index, and (logically) the mock portco/bank APIs.
3. Author a scan ruleset with **custom classifications**: Person name, **Thai national ID**, account number, balance/amount, credit-bureau score.
4. Run scans; publish a small **business glossary** (Applicant, Financial Statement, Bureau Report, Memo Template, Payee, Account).
5. **Export classification results** (or mirror as config) into the APIM PII-filter policy and AI Search field-level security — this is the governance→runtime link.
6. Capture lineage from source → AI Search → tool → agent so provenance is queryable.

### 4. Security & governance controls
- Least-privilege Purview data-reader roles; collection-scoped.
- Classifications are **structurally real even on synthetic data** — they parameterize downstream PII filtering, so the governance loop is provable without real customer data.
- "Approved sources" is enforced because `doc_retrieval` can only query the governed AI Search index; there is no tool path to ungoverned data.

### 5. Observability & audit model — **how Purview observability is shown in the PoC**

This is the part the user asked for. Purview's observability is demonstrated through **four offline panels** in `ui/purview-observability.html` (driven by the same `window.AGPOC` mock backend so it runs from `file://` with no Azure):

1. **Data lineage graph** — a left-to-right provenance strip for a credit-memo fact:
   `Synthetic source (ADLS) → Purview classification → AI Search (approved index) → search_documents (APIM) → doc_retrieval agent → memo section`.
   Clicking a node shows "where did this fact come from?" — the core Purview lineage value, mirrored from what the production Data Map would render.

2. **Classification coverage** — a table of every synthetic field → its Purview classification → sensitivity → **the APIM PII action it drives** (allow / mask / redact). This makes the governance→runtime link visible: classification on the left literally selects the runtime filter on the right.

3. **Governance → runtime link** — a small diagram showing Purview classifications exported into the APIM `inbound-tool-call` PII-filter step, so a reviewer sees that the boundary's redaction is *driven by governance*, not hardcoded.

4. **Data-estate insights tiles** — Purview-Insights-style coverage KPIs: sources registered, % fields classified, sensitive-field count, approved-source count. This mirrors Purview's *Data Estate Insights* reports as the design-time observability complement to the runtime token/trace observability in `token-monitor.html`.

In production these four views are real Purview surfaces (Data Map lineage, Classification insights, Scan results, Data Estate Insights). The PoC reproduces their **information shape** so the demo communicates the capability faithfully.

**Two complementary observability planes** — state this explicitly to the reviewer:
- **Design-time / data governance observability = Purview** (provenance, classification, approved-source proof). → `ui/purview-observability.html`
- **Runtime / execution observability = App Insights + Cosmos audit + token metric.** → `ui/token-monitor.html`, per-step audit rails.
Together they answer both "is the data governed and where did it come from?" and "what did the agents do and what did it cost?".

### 6. Regional & data-residency considerations
Purview account in `southeastasia`; classification + lineage metadata in-region. No data movement out of region for governance.

### 7. Known limitations
- Automated classification→APIM export is not a turnkey Purview feature; the PoC wires it as a documented mapping (config mirror) and production would automate via a small sync job. (Disclosed under *Permitted Reduction §10 — custom-built.*)
- Lineage automation depends on connectors emitting lineage; the mock portco/bank APIs are logical sources, so their lineage is documented rather than auto-captured.

### 8. Estimated complexity to productionize
**Medium.** Purview registration, scanning, glossary, and insights are GA and low-effort. The **classification→APIM PII-filter sync** is the custom piece (~2–3 days for a sync job + APIM named-values/policy fragment generation).

### 9. Dependencies on preview or roadmap features
Core Purview governance is GA. The automated classification-to-runtime-policy export is **custom-built** (no GA turnkey path) — flagged per *Permitted Reduction §10*.

### 10. Open questions requiring follow-up
- Does the Group's existing Purview tenant already hold the canonical classification taxonomy we should align to?
- Preferred export mechanism for classification→APIM (event-driven vs scheduled sync)?
- Lineage depth expected by AI Foundation reviewers (field-level vs document-level)?

---

## 3. Other deferred capabilities (condensed design notes)

These follow the same template at summary depth; expand on request.

| Capability | Target pattern & native services | Security/Gov | Observability | Complexity | Preview/roadmap |
|---|---|---|---|---|---|
| **Live model serving** | AOAI in Foundry, `southeastasia`, deployments `gpt-4o`/`gpt-4o-mini`, version-locked, content filters on. | Entra `Cognitive Services OpenAI User`; no keys. | Model+version on every step + token record; `gen_ai.token.usage`. | Low | GA |
| **Tool execution (Functions)** | Python v2 Functions behind APIM product `agent-tools-*`; identity-bound. | Per-Function managed identity; scopes on `agpoc-tool-bridge`. | Per-call APIM log + step record. | Low–Med | GA |
| **HITL (Durable + Service Bus)** | Durable pause→Service Bus `hitl-approvals`→Teams reviewer→idempotent resume. | Reviewer authN via Entra; `final` gated on `approve`. | `handoffs`/approval audit in Cosmos. | Medium | GA (Teams reviewer UX is custom) |
| **Identity (Entra per-agent)** | App regs + user-assigned MIs + federated creds; scope-per-tool-family. | APIM `validate-jwt` + scope claim at the call. | 401/403 + audit on failure. | Medium | GA |
| **Defender for Cloud** | Subscription plan; posture + threat alerts. | CSPM/CWP. | Alerts → Log Analytics. | Low | GA |
| **CI/CD (GitHub Actions)** | OIDC `azure/login`; deploy infra/backend/functions/ui. | No stored cloud creds (OIDC federation). | Workflow run history. | Low | GA |

---

## 4. Consolidated production-readiness view

- **GA, low effort:** Storage+Private Link, AOAI, Functions, CI/CD, Defender.
- **GA, medium effort:** Entra per-agent identity, Durable HITL, Purview governance.
- **Custom-built (disclosed):** classification→APIM PII-filter export; Teams reviewer UX.
- **No hard blockers.** The PoC's `MOCK_MODE` boundary is a clean seam: flipping each capability from mock to live is a binding change, not a rewrite — which is the central feasibility claim of this PoC.
