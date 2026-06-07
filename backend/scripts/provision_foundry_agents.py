"""Provision the 6 SCBX agents into a Microsoft Foundry project.

Uses the **new** Foundry Agents API (``/agents?api-version=v1``), which creates
first-class, versioned agents (NOT the legacy "Classic"/Assistants surface).

New-agent facts that shape this script:
  * Agent names must be alphanumeric with hyphens only (no underscores), <= 63
    chars. We map each in-code logical name (``memo_orchestrator``) to a Foundry
    name (``memo-orchestrator``).
  * Create body is ``{"name", "description", "metadata",
    "definition": {"kind": "prompt", "model", "instructions"}}``.
  * Agents are versioned: the resource id is the agent name; the active version
    id looks like ``memo-orchestrator:1``. New agents have no ``asst_*`` id.
  * Create is not idempotent (HTTP 409 if the name already exists), so we list
    first and skip existing agents.

It also registers the **workflow agents** (Foundry agents with
``definition.kind = "workflow"``) that orchestrate the agents above:
  * ``credit-memo-workflow`` (UC1) chains the five credit-memo agents in sequence.
  * ``banking-control-workflow`` (UC2) wraps the banking-controller agent.
Each workflow's CSDL YAML lives next to this script and surfaces in the portal
Workflows (Preview) tab. Workflow agents are a preview feature, so the create
call carries the ``Foundry-Features: WorkflowAgents=V1Preview`` opt-in header.

Idempotent: creates an agent if one with the same name does not exist, otherwise
reuses the existing latest version. Writes the resulting
``logical_name -> agent_version_id`` mapping to
``backend/app/foundry_agent_ids.json`` so the backend can bind in-code agents to
their live Foundry counterparts.

Usage (from repo root, using the project venv):
  $env:FOUNDRY_PROJECT_ENDPOINT="https://<acct>.services.ai.azure.com/api/projects/<project>"
  .venv\\Scripts\\python.exe backend\\scripts\\provision_foundry_agents.py
  # optional: also delete the old Classic (asst_*) assistants it replaces
  .venv\\Scripts\\python.exe backend\\scripts\\provision_foundry_agents.py --delete-classic

Auth: DefaultAzureCredential (az login user must have the "Azure AI User" /
project data-plane role on the Foundry project). Data-plane token scope is
``https://ai.azure.com/.default``.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from azure.identity import DefaultAzureCredential

API_VERSION = "v1"
TOKEN_SCOPE = "https://ai.azure.com/.default"
# Workflow agents are in preview and require this opt-in header on create.
WORKFLOW_OPT_IN_HEADER = ("Foundry-Features", "WorkflowAgents=V1Preview")

_SCRIPT_DIR = Path(__file__).resolve().parent

# --- Tool catalog (single source of truth: app/tools/mcp_schemas.py) ----------
# Loaded directly by file path so this standalone script does NOT import the
# backend ``app`` package (and its pydantic settings) just to read the schemas.
import importlib.util as _ilu

_MCP_PATH = Path(__file__).resolve().parents[1] / "app" / "tools" / "mcp_schemas.py"
_mcp_spec = _ilu.spec_from_file_location("scbx_mcp_schemas", _MCP_PATH)
_mcp_mod = _ilu.module_from_spec(_mcp_spec)
_mcp_spec.loader.exec_module(_mcp_mod)  # type: ignore[union-attr]
TOOL_SCHEMAS: dict[str, dict] = _mcp_mod.TOOL_SCHEMAS


def _function_tool_defs(tool_names: list[str]) -> list[dict]:
    """Build Foundry function-tool definitions for the given catalog tool names.

    These declare the agent's actions to Foundry so they surface in the portal /
    Microsoft 365 admin center "Data & tools" tab (the action is still executed
    by the backend through APIM; the definition makes the capability visible).
    """
    defs: list[dict] = []
    for tname in tool_names:
        schema = TOOL_SCHEMAS[tname]
        defs.append(
            {
                "type": "function",
                "function": {
                    "name": schema["name"],
                    "description": schema["description"],
                    "parameters": schema["parameters"],
                },
            }
        )
    return defs


def _knowledge_tool_defs(use_case: str) -> list[dict]:
    """Optional Azure AI Search knowledge tool (surfaces as a Data source).

    Only emitted when a project search connection id is supplied via
    ``FOUNDRY_SEARCH_CONNECTION_ID`` (and the agent is a credit-memo agent), so
    default runs never depend on a connection that may not exist yet.
    """
    conn = os.environ.get("FOUNDRY_SEARCH_CONNECTION_ID", "").strip()
    if use_case != "credit_memo" or not conn:
        return []
    return [
        {
            "type": "azure_ai_search",
            "azure_ai_search": {
                "indexes": [
                    {
                        "index_connection_id": conn,
                        "index_name": os.environ.get("FOUNDRY_SEARCH_INDEX", "memo-corpus"),
                        "query_type": "simple",
                    }
                ]
            },
        }
    ]


def _agent_tools(spec: dict) -> list[dict]:
    """Full Foundry ``tools`` array for an agent: function tools + knowledge."""
    return _function_tool_defs(list(spec.get("tools", []))) + _knowledge_tool_defs(
        str(spec["use_case"])
    )


def _tool_sig(tools: list[dict] | None) -> tuple:
    """Order-independent signature of a tools array, for drift detection."""
    sig: list[str] = []
    for tool in tools or []:
        ttype = tool.get("type")
        if ttype == "function":
            sig.append("function:" + tool.get("function", {}).get("name", ""))
        else:
            sig.append(str(ttype))
    return tuple(sorted(sig))


# Foundry workflow agents (definition.kind = "workflow"). Each chains one or more
# of the agents below and surfaces in the portal Workflows (Preview) tab.
WORKFLOWS: list[dict[str, object]] = [
    {
        # UC1 - Credit Memo Drafting (5 agents in sequence).
        "name": "credit-memo-workflow",
        "yaml_path": _SCRIPT_DIR / "credit_memo_workflow.yaml",
        "description": (
            "SCBX UC1 sequential credit-memo drafting orchestration "
            "(memo-orchestrator -> doc-retrieval -> financial-ratio -> "
            "bureau-summary -> memo-assembler)."
        ),
    },
    {
        # UC2 - Conversational Banking Control (single agent).
        "name": "banking-control-workflow",
        "yaml_path": _SCRIPT_DIR / "banking_control_workflow.yaml",
        "description": (
            "SCBX UC2 conversational banking control orchestration "
            "(banking-controller; intent/slot decomposition, transaction handoff only)."
        ),
    },
]

# --- Agent catalog: must match backend/app/orchestration/*.py -----------------
# (logical name with underscores, model deployment, instructions, use_case, tools)
AGENTS: list[dict[str, object]] = [
    # UC1 — Credit Memo Drafting
    {
        "name": "memo_orchestrator",
        "model": "gpt-4o",
        "use_case": "credit_memo",
        "tools": [
            "search_documents",
            "get_financials",
            "calculate_ratios",
            "get_bureau_report",
            "render_memo",
        ],
        "instructions": (
            "You are the lead orchestrator for SCBX's SME Credit Memo Drafting "
            "assistant, supporting credit analysts at a Thai commercial bank. You "
            "plan and coordinate specialist sub-agents (document retrieval, "
            "financial-ratio analysis, credit-bureau summary, and memo assembly) "
            "to produce a complete, decision-ready SME credit memo.\n\n"
            "Responsibilities:\n"
            "- Break the request into an ordered plan and delegate each section to "
            "the appropriate specialist agent.\n"
            "- Ensure every factual claim is grounded in retrieved source documents; "
            "never invent figures, dates, names, or policy references.\n"
            "- Track which sections are complete, reconcile conflicting inputs "
            "before assembly, and keep all currency in THB unless stated otherwise.\n"
            "- Surface material risks, data gaps, and assumptions explicitly to the "
            "human analyst.\n\n"
            "Guardrails (non-negotiable):\n"
            "- This is a decision-support tool only. You never approve, decline, or "
            "finalize a credit decision, and you never move money or commit the bank.\n"
            "- Always require explicit human credit-analyst review and approval "
            "before any memo is treated as final.\n"
            "- If required data is missing or low-confidence, say so rather than "
            "guessing.\n\n"
            "Output: a clear plan plus a coordinated draft with labeled sections, an "
            "explicit risk/assumptions summary, and a 'Pending human approval' status "
            "until an analyst signs off."
        ),
    },
    {
        "name": "doc_retrieval",
        "model": "gpt-4o-mini",
        "use_case": "credit_memo",
        "tools": ["search_documents"],
        "instructions": (
            "You are the grounded document-retrieval specialist for SCBX's SME "
            "credit memo workflow. You locate and extract relevant evidence from the "
            "bank's approved source documents (financial statements, KYC/onboarding "
            "records, loan applications, collateral and legal documents) for a given "
            "SME applicant.\n\n"
            "Responsibilities:\n"
            "- Retrieve only from approved, provided sources; cite the document name "
            "and section/line for every fact you return.\n"
            "- Extract figures, dates, entity names, and terms exactly as written; "
            "preserve units and currency (THB unless stated).\n"
            "- Distinguish verified facts from inferences, and flag stale, "
            "conflicting, or missing documents.\n\n"
            "Guardrails:\n"
            "- Never fabricate, estimate, or 'fill in' values that are not present in "
            "the sources. If something is not found, return 'not found in provided "
            "sources'.\n"
            "- Do not summarize beyond what the evidence supports, and do not give "
            "credit opinions.\n\n"
            "Output: a structured list of grounded findings, each with the exact "
            "value and its source citation, plus a list of gaps and conflicts."
        ),
    },
    {
        "name": "financial_ratio",
        "model": "gpt-4o-mini",
        "use_case": "credit_memo",
        "tools": ["get_financials", "calculate_ratios"],
        "instructions": (
            "You are the financial-ratio analyst for SCBX's SME credit memo "
            "workflow. You interpret pre-computed financial ratios (liquidity, "
            "leverage, profitability, coverage, and efficiency) for a credit "
            "audience.\n\n"
            "Responsibilities:\n"
            "- Explain what each ratio indicates about the SME's financial health, "
            "year-over-year trend, and repayment capacity.\n"
            "- Compare against typical lending thresholds and the company's own "
            "history; highlight strengths, deterioration, and red flags (e.g., "
            "DSCR below 1.2x, high leverage, negative working capital).\n"
            "- Connect the numbers to credit risk in plain, analyst-friendly "
            "language.\n\n"
            "Guardrails:\n"
            "- Only interpret ratios that were provided; do not recompute or invent "
            "inputs. If a ratio is missing, note it.\n"
            "- State assumptions and the limits of the analysis; you do not make the "
            "final lending decision.\n\n"
            "Output: concise, structured commentary per ratio category, plus an "
            "overall financial-risk read and the key drivers behind it."
        ),
    },
    {
        "name": "bureau_summary",
        "model": "gpt-4o-mini",
        "use_case": "credit_memo",
        "tools": ["get_bureau_report"],
        "instructions": (
            "You are the credit-bureau analyst for SCBX's SME credit memo workflow. "
            "You summarize a credit-bureau report (e.g., NCB) for the applicant and "
            "its guarantors into risk-relevant findings.\n\n"
            "Responsibilities:\n"
            "- Extract and summarize repayment history, current and historical "
            "delinquencies, outstanding facilities and utilization, recent "
            "inquiries, defaults/legal status, and overall standing.\n"
            "- Highlight adverse items (late payments, NPLs, write-offs, "
            "restructurings) with dates and amounts, and note positive history.\n"
            "- Translate bureau data into credit-risk implications for the SME memo.\n\n"
            "Guardrails:\n"
            "- Report only what is in the bureau data; never infer or fabricate "
            "accounts, scores, or events.\n"
            "- Treat this as sensitive personal and financial data; stay factual and "
            "avoid speculation about individuals.\n\n"
            "Output: a structured risk summary (positives, negatives, watch items) "
            "grounded in the bureau report, with an overall bureau-risk read."
        ),
    },
    {
        "name": "memo_assembler",
        "model": "gpt-4o",
        "use_case": "credit_memo",
        "tools": ["render_memo"],
        "instructions": (
            "You are the memo assembler for SCBX's SME Credit Memo Drafting "
            "assistant. You combine the section inputs from the specialist agents "
            "(applicant profile, document findings, financial-ratio analysis, and "
            "bureau summary) into a single, coherent, decision-ready draft credit "
            "memo following the bank's standard template.\n\n"
            "Responsibilities:\n"
            "- Produce a well-structured memo: Executive Summary, Applicant & "
            "Facility Overview, Financial Analysis, Credit Bureau & Risk Assessment, "
            "Strengths, Risks & Mitigants, and a draft Recommendation for analyst "
            "review.\n"
            "- Maintain consistency of figures, names, and dates across sections; "
            "reconcile or flag any conflicts rather than hiding them.\n"
            "- Keep language precise and professional, preserve source citations "
            "where provided, and avoid unsupported claims.\n\n"
            "Guardrails:\n"
            "- Only use content supplied by the upstream agents and sources; do not "
            "introduce new facts or numbers.\n"
            "- Mark the memo clearly as a DRAFT pending human credit-analyst review "
            "and approval. Never present it as a final or approved decision.\n\n"
            "Output: the assembled draft memo in the standard sections, with a "
            "visible 'DRAFT - pending human approval' banner and a list of open "
            "items and assumptions."
        ),
    },
    # UC2 — Conversational Banking Control
    {
        "name": "banking_controller",
        "model": "gpt-4o",
        "use_case": "banking",
        "tools": [
            "get_balance",
            "resolve_payee",
            "check_transfer_eligibility",
            "request_transaction_handoff",
        ],
        "instructions": (
            "You are the conversational banking controller for SCBX's UC2 assistant, "
            "helping retail customers carry out everyday banking conversationally "
            "(e.g., balance and transaction inquiries, payee management, and "
            "initiating a funds transfer for confirmation).\n\n"
            "Responsibilities:\n"
            "- Understand the customer's request and decompose it into a clear intent "
            "plus the required slots (for a transfer: payee, amount, currency, source "
            "account, date).\n"
            "- Track dialog state across turns, ask concise clarifying questions for "
            "any missing or ambiguous slot, and confirm understanding before "
            "proceeding.\n"
            "- Validate inputs (known payee, plausible amount and account) and "
            "summarize the proposed action back to the customer.\n\n"
            "Guardrails (non-negotiable):\n"
            "- You never move money or mutate accounts yourself. The only terminal "
            "action is handing off a fully-specified, customer-confirmed transaction "
            "request to the secure transaction system, which executes under its own "
            "authorization and limits.\n"
            "- Always obtain explicit customer confirmation of the exact details "
            "before any transfer handoff; respect daily limits and step-up "
            "authentication requirements.\n"
            "- Never reveal full account numbers, credentials, or another customer's "
            "data; refuse and escalate anything that looks like fraud, coercion, or a "
            "request outside policy.\n\n"
            "Output: the recognized intent, the filled and missing slots, the next "
            "clarifying question or a confirmation summary, and - only after explicit "
            "confirmation - a structured transaction-handoff payload (never an "
            "executed transaction)."
        ),
    },
]

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "app" / "foundry_agent_ids.json"


def foundry_name(logical_name: str) -> str:
    """Map an in-code logical name to a Foundry-legal agent name."""
    return logical_name.replace("_", "-")


def _request(
    method: str,
    url: str,
    token: str,
    body: dict | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"error": {"message": raw}}


def list_existing(endpoint: str, token: str) -> dict[str, dict]:
    """Return ``foundry_name -> agent resource`` for all existing new-API agents."""
    status, payload = _request("GET", f"{endpoint}/agents?api-version={API_VERSION}", token)
    if status != 200:
        raise RuntimeError(f"list agents failed ({status}): {payload}")
    return {a["name"]: a for a in payload.get("data", [])}


def latest_version_id(agent: dict) -> str:
    """Extract the active version id (e.g. ``memo-orchestrator:1``) from a resource."""
    latest = (agent.get("versions") or {}).get("latest") or {}
    return latest.get("id") or agent.get("id") or agent["name"]


def latest_definition(agent: dict) -> dict:
    """Extract the active version's ``definition`` (model, instructions, ...)."""
    latest = (agent.get("versions") or {}).get("latest") or {}
    return latest.get("definition") or {}


def create_version(endpoint: str, token: str, name: str, spec: dict) -> dict:
    """Push a new prompt version for an existing agent (updates its instructions).

    The new-agent API is versioned: ``POST /agents/{name}/versions`` adds a new
    version that becomes ``@latest`` (the agent endpoint routes 100% to latest).
    """
    body = {
        "definition": {
            "kind": "prompt",
            "model": spec["model"],
            "instructions": spec["instructions"],
            "tools": _agent_tools(spec),
        }
    }
    status, payload = _request(
        "POST", f"{endpoint}/agents/{name}/versions?api-version={API_VERSION}", token, body
    )
    if status not in (200, 201):
        raise RuntimeError(f"version '{name}' failed ({status}): {payload}")
    return payload


def create_agent(endpoint: str, token: str, spec: dict) -> dict:
    name = foundry_name(spec["name"])
    body = {
        "name": name,
        "description": f"SCBX {spec['use_case']} agent ({spec['name']}).",
        "metadata": {"use_case": spec["use_case"], "logical_name": spec["name"]},
        "definition": {
            "kind": "prompt",
            "model": spec["model"],
            "instructions": spec["instructions"],
            "tools": _agent_tools(spec),
        },
    }
    status, payload = _request(
        "POST", f"{endpoint}/agents?api-version={API_VERSION}", token, body
    )
    if status not in (200, 201):
        raise RuntimeError(f"create '{name}' failed ({status}): {payload}")
    return payload


def provision_workflows(endpoint: str, token: str, existing: dict[str, dict]) -> None:
    """Idempotently register all Foundry workflow agents (UC1 + UC2).

    Workflow agents are a preview feature, so create calls carry the
    ``Foundry-Features: WorkflowAgents=V1Preview`` opt-in header.
    """
    opt_in = {WORKFLOW_OPT_IN_HEADER[0]: WORKFLOW_OPT_IN_HEADER[1]}
    for wf in WORKFLOWS:
        name = str(wf["name"])
        yaml_path = wf["yaml_path"]  # type: ignore[assignment]
        if name in existing:
            print(f"  exists   {name:24s} (workflow)")
            continue
        if not yaml_path.exists():  # type: ignore[union-attr]
            print(f"  WARN: {yaml_path.name} missing; skipping {name}.")  # type: ignore[union-attr]
            continue
        body = {
            "name": name,
            "description": wf["description"],
            "definition": {
                "kind": "workflow",
                "workflow": yaml_path.read_text(encoding="utf-8"),  # type: ignore[union-attr]
            },
        }
        status, payload = _request(
            "POST",
            f"{endpoint}/agents?api-version={API_VERSION}",
            token,
            body,
            extra_headers=opt_in,
        )
        if status in (200, 201):
            print(f"  created  {name:24s} (workflow)")
        elif status == 409:
            print(f"  exists   {name:24s} (workflow)")
        else:
            raise RuntimeError(f"create workflow '{name}' failed ({status}): {payload}")


def delete_classic_assistants(endpoint: str, token: str, asst_ids: list[str]) -> None:
    """Delete legacy Classic (Assistants API) agents by their ``asst_*`` ids."""
    for asst_id in asst_ids:
        if not asst_id.startswith("asst_"):
            continue
        status, payload = _request(
            "DELETE", f"{endpoint}/assistants/{asst_id}?api-version=2025-05-01", token
        )
        if status in (200, 204):
            print(f"  deleted classic  {asst_id}")
        elif status == 404:
            print(f"  classic gone     {asst_id} (already removed)")
        else:
            print(f"  WARN classic     {asst_id} delete -> {status}: {payload}")


def main() -> int:
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        print("ERROR: set FOUNDRY_PROJECT_ENDPOINT to the project data-plane endpoint.")
        return 2
    endpoint = endpoint.rstrip("/")
    delete_classic = "--delete-classic" in sys.argv

    print(f"Connecting to Foundry project: {endpoint}")
    token = DefaultAzureCredential().get_token(TOKEN_SCOPE).token

    # Capture the Classic ids we may need to clean up before overwriting the map.
    classic_ids: list[str] = []
    if OUTPUT_PATH.exists():
        try:
            prev = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
            classic_ids = [v for v in prev.values() if isinstance(v, str) and v.startswith("asst_")]
        except (ValueError, OSError):
            pass

    existing = list_existing(endpoint, token)
    print(f"Found {len(existing)} existing new-API agent(s) in project.")

    result: dict[str, str] = {}
    for spec in AGENTS:
        fname = foundry_name(spec["name"])
        if fname in existing:
            agent = existing[fname]
            current = latest_definition(agent)
            drift = (
                current.get("instructions") != spec["instructions"]
                or current.get("model") != spec["model"]
                or _tool_sig(current.get("tools")) != _tool_sig(_agent_tools(spec))
            )
            if drift:
                updated = create_version(endpoint, token, fname, spec)
                vid = updated.get("id") or latest_version_id(agent)
                print(f"  updated  {spec['name']:20s} -> {vid} ({spec['model']})")
            else:
                vid = latest_version_id(agent)
                print(f"  current  {spec['name']:20s} -> {vid} ({spec['model']})")
        else:
            agent = create_agent(endpoint, token, spec)
            vid = latest_version_id(agent)
            print(f"  created  {spec['name']:20s} -> {vid} ({spec['model']})")
        result[spec["name"]] = vid

    OUTPUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nWrote {len(result)} agent version id(s) to {OUTPUT_PATH}")

    print("\nProvisioning workflows (UC1 credit-memo, UC2 banking-control)...")
    provision_workflows(endpoint, token, existing)

    if delete_classic and classic_ids:
        print(f"\nDeleting {len(classic_ids)} Classic (asst_*) assistant(s)...")
        delete_classic_assistants(endpoint, token, classic_ids)
    elif classic_ids:
        print(
            f"\nNote: {len(classic_ids)} Classic (asst_*) assistant(s) remain. "
            "Re-run with --delete-classic to remove them."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
