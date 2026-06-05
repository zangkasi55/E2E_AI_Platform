"""MCP / OpenAPI-style JSON tool schemas for the canonical tool catalog.

These schemas are what the agents advertise to the model for function-calling
and what APIM (``agpoc-apim-dev``) validates inbound tool requests against.
Signatures match POC_SPEC.md §Canonical tool catalog exactly.

Each schema carries an ``x-scope`` extension naming the OAuth scope the tool
bridge (``agpoc-tool-bridge``) requires — enforced deterministically at the PDP,
not by the model.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Tool schemas keyed by tool name. JSON-Schema ``parameters`` blocks are
# directly usable as OpenAI function-calling tool definitions.
# ---------------------------------------------------------------------------
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ---- UC1: Credit Memo --------------------------------------------------
    "search_documents": {
        "name": "search_documents",
        "description": "Search the approved-source corpus in Azure AI Search and return grounded chunks.",
        "use_case": "credit_memo",
        "x-scope": "tools.search.read",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language search query."},
                "source_filter": {
                    "type": "string",
                    "description": "Restrict to a source type (credit_policy|industry_report|applicant_filing) or applicant id.",
                },
            },
            "required": ["query"],
        },
    },
    "get_financials": {
        "name": "get_financials",
        "description": "Fetch 3-year financial statements for an applicant.",
        "use_case": "credit_memo",
        "x-scope": "tools.financials.read",
        "parameters": {
            "type": "object",
            "properties": {
                "applicant_id": {"type": "string", "description": "Applicant id, e.g. APP-1001."},
            },
            "required": ["applicant_id"],
        },
    },
    "calculate_ratios": {
        "name": "calculate_ratios",
        "description": "Compute key credit ratios (DSCR, net debt/EBITDA, current ratio, margins) from financials.",
        "use_case": "credit_memo",
        "x-scope": "tools.ratios.compute",
        "parameters": {
            "type": "object",
            "properties": {
                "financials": {
                    "type": "object",
                    "description": "Financials object as returned by get_financials.",
                },
            },
            "required": ["financials"],
        },
    },
    "get_bureau_report": {
        "name": "get_bureau_report",
        "description": "Fetch the synthetic credit-bureau report for an applicant.",
        "use_case": "credit_memo",
        "x-scope": "tools.bureau.read",
        "parameters": {
            "type": "object",
            "properties": {
                "applicant_id": {"type": "string", "description": "Applicant id, e.g. APP-1001."},
            },
            "required": ["applicant_id"],
        },
    },
    "render_memo": {
        "name": "render_memo",
        "description": "Render memo section bodies into a structured draft using a template.",
        "use_case": "credit_memo",
        "x-scope": "tools.memo.write",
        "parameters": {
            "type": "object",
            "properties": {
                "sections": {
                    "type": "object",
                    "description": "Map of section key -> body text.",
                },
                "template_id": {"type": "string", "description": "Template id, e.g. TMPL-SME-STD-01."},
            },
            "required": ["sections", "template_id"],
        },
    },
    # ---- UC2: Conversational Banking --------------------------------------
    "get_balance": {
        "name": "get_balance",
        "description": "Read the balance of a user's account (THB).",
        "use_case": "banking",
        "x-scope": "tools.balance.read",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "User id, e.g. USR-001."},
                "account_id": {"type": "string", "description": "Account id, e.g. ACC-001-CUR."},
            },
            "required": ["user_id", "account_id"],
        },
    },
    "resolve_payee": {
        "name": "resolve_payee",
        "description": "Resolve a payee alias (e.g. 'mom') to a payee id for a user.",
        "use_case": "banking",
        "x-scope": "tools.payee.read",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "payee_alias": {"type": "string", "description": "Friendly alias, e.g. 'mom' or 'landlord'."},
            },
            "required": ["user_id", "payee_alias"],
        },
    },
    "check_transfer_eligibility": {
        "name": "check_transfer_eligibility",
        "description": "Deterministic PDP check: is this transfer permitted by policy/scope? Does NOT move money.",
        "use_case": "banking",
        "x-scope": "tools.transfer.evaluate",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "src_account": {"type": "string"},
                "payee_id": {"type": "string"},
                "amount": {"type": "number", "description": "Amount in THB."},
            },
            "required": ["user_id", "src_account", "payee_id", "amount"],
        },
    },
    "request_transaction_handoff": {
        "name": "request_transaction_handoff",
        "description": (
            "TERMINAL action. Produce an auditable handoff object for a human-confirmed, "
            "step-up-authenticated channel. This NEVER executes a transfer."
        ),
        "use_case": "banking",
        "x-scope": "tools.handoff.create",
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "slots": {"type": "object"},
                "policy_result": {"type": "object"},
            },
            "required": ["intent", "slots", "policy_result"],
        },
    },
}


def openai_tool_defs(use_case: str | None = None) -> list[dict[str, Any]]:
    """Return OpenAI ``tools`` definitions, optionally filtered by use case."""
    defs: list[dict[str, Any]] = []
    for schema in TOOL_SCHEMAS.values():
        if use_case and schema["use_case"] != use_case:
            continue
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


def scope_for(tool_name: str) -> str:
    """Return the required OAuth scope for a tool (PDP enforcement)."""
    return TOOL_SCHEMAS[tool_name]["x-scope"]
