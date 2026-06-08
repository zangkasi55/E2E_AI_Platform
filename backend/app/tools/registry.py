"""Canonical tool catalog — callable stubs fronted by APIM.

Each tool:
  * is **scope-checked** against the caller's granted scopes before running
    (deterministic PDP gate; mirrors the APIM policy in the live system),
  * in MOCK_MODE returns synthetic data loaded from ``/data``,
  * in live mode POSTs through APIM (``agpoc-apim-dev``) to the Azure Functions
    tool backend (``agpoc-func-tools-dev``) using httpx.

Signatures match POC_SPEC.md §Canonical tool catalog exactly. The terminal
banking tool ``request_transaction_handoff`` NEVER moves money — it only emits a
handoff object.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import httpx

from ..config import settings
from .mcp_schemas import scope_for


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ToolScopeError(PermissionError):
    """Raised when a caller lacks the required scope for a tool."""


class ToolNotFoundError(KeyError):
    """Raised for an unknown tool name."""


# ---------------------------------------------------------------------------
# Synthetic data loading (mock mode)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _load_json(relative: str) -> dict[str, Any]:
    """Load and cache a JSON file from the synthetic ``data/`` directory."""
    path: Path = settings.data_path / relative
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Scope enforcement (deterministic — not prompt-driven)
# ---------------------------------------------------------------------------
# In the PoC, granted scopes are derived from the agent role. The live system
# resolves these from the Entra access token presented to APIM.
DEFAULT_GRANTED_SCOPES: set[str] = {
    "tools.search.read",
    "tools.financials.read",
    "tools.ratios.compute",
    "tools.bureau.read",
    "tools.memo.write",
    "tools.sensitivity.classify",
    "tools.dspm.write",
    "tools.policy.evaluate",
    "tools.balance.read",
    "tools.payee.read",
    "tools.transfer.evaluate",
    "tools.handoff.create",
}


def _check_scope(tool_name: str, granted_scopes: Optional[set[str]]) -> None:
    """Raise :class:`ToolScopeError` if the required scope is not granted."""
    required = scope_for(tool_name)
    scopes = granted_scopes if granted_scopes is not None else DEFAULT_GRANTED_SCOPES
    if required not in scopes:
        raise ToolScopeError(
            f"Tool '{tool_name}' requires scope '{required}' which is not granted."
        )


def _resolve_agent_id(caller_agent: Optional[str]) -> str:
    if not caller_agent:
        return "orchestrator"
    return settings.foundry_agent_ids.get(caller_agent, caller_agent)


def _apim_token_scope() -> Optional[str]:
    # Prefer an explicit scope, else derive from the tool-bridge app id.
    explicit = (getattr(settings, "apim_token_scope", "") or "").strip()
    if explicit:
        return explicit
    if settings.entra_tool_bridge_client_id:
        return f"api://{settings.entra_tool_bridge_client_id}/.default"
    return None


def _get_apim_auth_header() -> dict[str, str]:
    scope = _apim_token_scope()
    if not scope:
        return {}
    try:
        from ..identity import get_credential

        token = get_credential().get_token(scope).token
        return {"Authorization": f"Bearer {token}"}
    except Exception:
        # Best effort for local/hybrid environments where APIM bearer auth is optional.
        return {}


def _post_through_apim(
    tool_name: str,
    payload: dict[str, Any],
    *,
    caller_agent: Optional[str] = None,
) -> dict[str, Any]:
    """POST a tool invocation through APIM to the Functions backend.

    Includes an Entra bearer token (when configured) and agent identity headers
    so APIM/PDP can enforce and audit per-agent access.
    """
    url = f"{settings.apim_base_url.rstrip('/')}/{tool_name}"
    agent_id = _resolve_agent_id(caller_agent)
    headers = {
        "Content-Type": "application/json",
        "Ocp-Apim-Subscription-Key": settings.apim_subscription_key,
        "x-agent-logical-id": caller_agent or "orchestrator",
        "x-agent-id": agent_id,
    }
    headers.update(_get_apim_auth_header())
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _invoke(
    tool_name: str,
    payload: dict[str, Any],
    mock_fn,
    *,
    caller_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Shared dispatch: mock vs APIM, after the scope gate has passed."""
    if settings.mock_mode:
        return mock_fn()
    return _post_through_apim(tool_name, payload, caller_agent=caller_agent)


# ===========================================================================
# UC1 — Credit Memo tools
# ===========================================================================
def search_documents(
    query: str,
    source_filter: Optional[str] = None,
    *,
    granted_scopes: Optional[set[str]] = None,
    caller_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Search approved-source corpus; returns grounded chunks.

    ``source_filter`` may be a source type (credit_policy|industry_report|
    applicant_filing) or an applicant id (matches ``applicant_scope``).
    """
    _check_scope("search_documents", granted_scopes)

    def mock() -> dict[str, Any]:
        corpus = _load_json("credit_memo/documents.json")["documents"]
        q = (query or "").lower()
        results = []
        for chunk in corpus:
            if source_filter:
                sf = source_filter
                if chunk["source"] != sf and chunk["applicant_scope"] not in (sf, "ALL"):
                    continue
            # naive keyword relevance for the demo
            hay = f"{chunk['title']} {chunk['text']}".lower()
            score = sum(1 for term in q.split() if term and term in hay)
            if score or not q:
                results.append({**chunk, "score": score})
        results.sort(key=lambda c: c["score"], reverse=True)
        return {"query": query, "source_filter": source_filter, "results": results[:5]}

    return _invoke(
        "search_documents",
        {"query": query, "source_filter": source_filter},
        mock,
        caller_agent=caller_agent,
    )


def get_financials(
    applicant_id: str,
    *,
    granted_scopes: Optional[set[str]] = None,
    caller_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Return 3-year financial statements for an applicant."""
    _check_scope("get_financials", granted_scopes)

    def mock() -> dict[str, Any]:
        data = _load_json("credit_memo/financials.json")["financials"]
        fin = data.get(applicant_id)
        if fin is None:
            return {"applicant_id": applicant_id, "error": "not_found"}
        return {"applicant_id": applicant_id, **fin}

    return _invoke(
        "get_financials",
        {"applicant_id": applicant_id},
        mock,
        caller_agent=caller_agent,
    )


def calculate_ratios(
    financials: dict[str, Any],
    *,
    granted_scopes: Optional[set[str]] = None,
    caller_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Compute key credit ratios from a financials object.

    Computes, for the most recent fiscal year: DSCR (EBITDA / interest),
    net debt / EBITDA, current ratio, EBITDA margin, and 2y revenue CAGR.
    Pure function — safe to run locally even in live mode.
    """
    _check_scope("calculate_ratios", granted_scopes)
    years = financials.get("fiscal_years", [])
    if not years:
        return {"error": "no_fiscal_years"}
    years_sorted = sorted(years, key=lambda y: y["year"])
    latest = years_sorted[-1]
    earliest = years_sorted[0]

    ebitda = float(latest["ebitda"])
    interest = float(latest.get("interest_expense", 0)) or 1.0
    total_debt = float(latest.get("total_debt", 0))
    cash = float(latest.get("cash", 0))
    net_debt = max(0.0, total_debt - cash)

    dscr = round(ebitda / interest, 2)
    net_debt_to_ebitda = round(net_debt / ebitda, 2) if ebitda > 0 else None
    current_ratio = round(
        float(latest.get("current_assets", 0))
        / (float(latest.get("current_liabilities", 0)) or 1.0),
        2,
    )
    ebitda_margin = round(ebitda / float(latest["revenue"]) * 100, 1)
    n_years = max(1, latest["year"] - earliest["year"])
    revenue_cagr = round(
        ((float(latest["revenue"]) / float(earliest["revenue"])) ** (1 / n_years) - 1) * 100,
        1,
    )
    return {
        "fiscal_year": latest["year"],
        "dscr": dscr,
        "net_debt_to_ebitda": net_debt_to_ebitda,
        "current_ratio": current_ratio,
        "ebitda_margin_pct": ebitda_margin,
        "revenue_cagr_pct": revenue_cagr,
        "net_debt_thb": net_debt,
    }


def get_bureau_report(
    applicant_id: str,
    *,
    granted_scopes: Optional[set[str]] = None,
    caller_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Return the synthetic credit-bureau report for an applicant."""
    _check_scope("get_bureau_report", granted_scopes)

    def mock() -> dict[str, Any]:
        data = _load_json("credit_memo/bureau.json")["bureau_reports"]
        rep = data.get(applicant_id)
        if rep is None:
            return {"applicant_id": applicant_id, "error": "not_found"}
        return {"applicant_id": applicant_id, **rep}

    return _invoke(
        "get_bureau_report",
        {"applicant_id": applicant_id},
        mock,
        caller_agent=caller_agent,
    )


def render_memo(
    sections: dict[str, Any],
    template_id: str,
    *,
    granted_scopes: Optional[set[str]] = None,
    caller_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Render section bodies into a structured draft using a template.

    Returns a DRAFT only — UC1 hard rule: no memo is final without human
    approval (enforced by the orchestrator + HITL, not here).
    """
    _check_scope("render_memo", granted_scopes)

    def mock() -> dict[str, Any]:
        templates = _load_json("credit_memo/memo_templates.json")["templates"]
        tmpl = next((t for t in templates if t["template_id"] == template_id), None)
        if tmpl is None:
            return {"error": "template_not_found", "template_id": template_id}
        rendered = []
        for sec in tmpl["sections"]:
            rendered.append(
                {
                    "key": sec["key"],
                    "title": sec["title"],
                    "body": sections.get(sec["key"], "(not provided)"),
                    "required": sec["required"],
                }
            )
        return {
            "template_id": template_id,
            "template_name": tmpl["name"],
            "status": "draft",
            "sections": rendered,
        }

    return _invoke(
        "render_memo",
        {"sections": sections, "template_id": template_id},
        mock,
        caller_agent=caller_agent,
    )


# ===========================================================================
# UC1 — Governance gate tools (deterministic policy boundary)
# ===========================================================================
# The sensitivity pre-gate, DSPM-for-AI event sink and credit-policy post-gate
# exposed as first-class, scope-checked catalog tools. Unlike the data tools
# above they are NEVER routed to an external backend via APIM: the sensitivity,
# DSPM and policy decisions must stay in-process so the platform — not the model
# or a remote service — owns the hard guarantees. The scope check still applies,
# so an agent can only call a gate it was granted.

# Hard-reject markers: a breach of any of these makes the case a hard reject
# regardless of other signals (the platform decides on the data, never on advice
# written in the uploaded file).
_HARD_REJECT_MARKERS: set[str] = {
    "dscr_meets_threshold",
    "leverage_within_threshold",
    "ebitda_margin_non_negative",
    "bureau_score_acceptable",
    "recent_delinquencies_clear",
    "document_ebitda_non_negative",
    "document_solvent",
    "document_dscr_meets_threshold",
    "document_bureau_score_acceptable",
    "document_recent_delinquencies_clear",
    "document_current_ratio_ok",
}


def classify_document_sensitivity(
    file_name: str,
    mime_type: Optional[str] = None,
    *,
    granted_scopes: Optional[set[str]] = None,
    caller_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Sensitivity pre-gate: resolve the Microsoft Purview label + ingestion
    decision for an uploaded document. Confidential / Highly Confidential files
    return ``blocked=true`` and must not be ingested by the agent."""
    _check_scope("classify_document_sensitivity", granted_scopes)
    from ..governance.sensitivity import resolve_sensitivity_label

    return resolve_sensitivity_label(file_name, mime_type)


def record_dspm_event(
    run_id: str,
    file_name: str,
    label_result: dict[str, Any],
    user: str,
    use_case: str = "credit_memo",
    *,
    granted_scopes: Optional[set[str]] = None,
    caller_agent: Optional[str] = None,
) -> dict[str, Any]:
    """DSPM for AI: record a sensitivity-label decision as a Microsoft Purview /
    Defender for Cloud data-security-posture event (and emit telemetry)."""
    _check_scope("record_dspm_event", granted_scopes)
    from ..telemetry.purview_audit import emit_label_enforcement_event

    return emit_label_enforcement_event(
        run_id=run_id,
        file_name=file_name,
        label_result=label_result,
        user=user,
        use_case=use_case,
    )


def evaluate_credit_policy(
    verifications: list[dict[str, Any]],
    *,
    granted_scopes: Optional[set[str]] = None,
    caller_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Policy post-gate: turn the per-domain verification checks into a credit
    recommendation. Returns ``recommendation`` (approve | request_edits |
    reject), the passing/failing reasons, and ``hard_reject``. A hard-reject
    marker breach forces ``reject`` and overrides any later human approve."""
    _check_scope("evaluate_credit_policy", granted_scopes)
    should_approve: list[str] = []
    should_not_approve: list[str] = []
    for verification in verifications:
        for check in (verification or {}).get("checks", []):
            reason = f"{check['name']}: {check['detail']}"
            if check.get("ok"):
                should_approve.append(reason)
            else:
                should_not_approve.append(reason)
    hard_reject = any(
        reason.split(":", 1)[0] in _HARD_REJECT_MARKERS for reason in should_not_approve
    )
    recommendation = "reject" if hard_reject else ("approve" if not should_not_approve else "request_edits")
    return {
        "recommendation": recommendation,
        "should_approve": should_approve,
        "should_not_approve": should_not_approve,
        "hard_reject": hard_reject,
    }


# ===========================================================================
# UC2 — Banking tools
# ===========================================================================
def get_balance(
    user_id: str,
    account_id: str,
    *,
    granted_scopes: Optional[set[str]] = None,
    caller_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Read the balance (THB) of a user's account."""
    _check_scope("get_balance", granted_scopes)

    def mock() -> dict[str, Any]:
        users = _load_json("banking/users.json")["users"]
        user = next((u for u in users if u["user_id"] == user_id), None)
        if user is None:
            return {"user_id": user_id, "error": "user_not_found"}
        acct = next((a for a in user["accounts"] if a["account_id"] == account_id), None)
        if acct is None:
            return {"user_id": user_id, "account_id": account_id, "error": "account_not_found"}
        return {
            "user_id": user_id,
            "account_id": account_id,
            "balance_thb": acct["balance_thb"],
            "currency": acct["currency"],
        }

    return _invoke(
        "get_balance",
        {"user_id": user_id, "account_id": account_id},
        mock,
        caller_agent=caller_agent,
    )


def resolve_payee(
    user_id: str,
    payee_alias: str,
    *,
    granted_scopes: Optional[set[str]] = None,
    caller_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve a payee alias (e.g. 'mom') to a payee id for a user."""
    _check_scope("resolve_payee", granted_scopes)

    def mock() -> dict[str, Any]:
        payees = _load_json("banking/payees.json")["payees"]
        entries = payees.get(user_id, [])
        alias = (payee_alias or "").strip().lower()
        match = next((p for p in entries if p["alias"].lower() == alias), None)
        if match is None:
            return {"user_id": user_id, "payee_alias": payee_alias, "error": "payee_not_found"}
        return {"user_id": user_id, "payee_alias": payee_alias, **match}

    return _invoke(
        "resolve_payee",
        {"user_id": user_id, "payee_alias": payee_alias},
        mock,
        caller_agent=caller_agent,
    )


def check_transfer_eligibility(
    user_id: str,
    src_account: str,
    payee_id: str,
    amount: float,
    *,
    granted_scopes: Optional[set[str]] = None,
    caller_agent: Optional[str] = None,
) -> dict[str, Any]:
    """Deterministic PDP check — is this transfer permitted? Moves NO money.

    Returns a policy_result-shaped dict consumed by request_transaction_handoff.
    """
    _check_scope("check_transfer_eligibility", granted_scopes)

    def mock() -> dict[str, Any]:
        reasons: list[str] = []
        eligible = True
        # Re-read balance to validate sufficiency (synthetic).
        bal = get_balance(
            user_id,
            src_account,
            granted_scopes=granted_scopes,
            caller_agent=caller_agent,
        )
        balance = float(bal.get("balance_thb", 0))
        if "error" in bal:
            eligible = False
            reasons.append(f"source_account_invalid:{bal['error']}")
        if amount <= 0:
            eligible = False
            reasons.append("amount_must_be_positive")
        if amount > balance:
            eligible = False
            reasons.append("insufficient_funds")
        # PoC per-transaction soft cap (policy example).
        if amount > 100000:
            eligible = False
            reasons.append("exceeds_poc_per_txn_cap_100000_thb")
        if eligible:
            reasons.append("within_policy")
        return {
            "eligible": eligible,
            "reasons": reasons,
            "scope_ok": True,
            "checked_balance_thb": balance,
        }

    return _invoke(
        "check_transfer_eligibility",
        {
            "user_id": user_id,
            "src_account": src_account,
            "payee_id": payee_id,
            "amount": amount,
        },
        mock,
        caller_agent=caller_agent,
    )


def request_transaction_handoff(
    intent: str,
    slots: dict[str, Any],
    policy_result: dict[str, Any],
    *,
    granted_scopes: Optional[set[str]] = None,
    caller_agent: Optional[str] = None,
) -> dict[str, Any]:
    """TERMINAL banking action — emit an auditable handoff object.

    THIS FUNCTION NEVER MOVES MONEY. It only assembles the handoff payload with
    the non-negotiable safety flags. The actual transfer happens (if ever) in a
    separate, human-confirmed, step-up-authenticated channel outside this PoC.
    """
    _check_scope("request_transaction_handoff", granted_scopes)

    # NOTE: requires_confirmation / requires_step_up_auth are ALWAYS True. They
    # are intentionally not parameters — they cannot be turned off by any caller
    # or prompt. The HandoffObject model further pins them as Literal[True].
    return {
        "type": "transaction_handoff",
        "intent": intent,
        "slots": slots,
        "policy_result": policy_result,
        "requires_confirmation": True,
        "requires_step_up_auth": True,
        "status": "pending_human_confirmation",
        "executed": False,  # explicit: nothing was executed
    }


# ---------------------------------------------------------------------------
# Registry map (name -> callable) for planners / function-calling dispatch.
# ---------------------------------------------------------------------------
TOOL_REGISTRY = {
    "search_documents": search_documents,
    "get_financials": get_financials,
    "calculate_ratios": calculate_ratios,
    "get_bureau_report": get_bureau_report,
    "render_memo": render_memo,
    "get_balance": get_balance,
    "resolve_payee": resolve_payee,
    "check_transfer_eligibility": check_transfer_eligibility,
    "request_transaction_handoff": request_transaction_handoff,
}


def get_tool(name: str):
    """Look up a tool callable by name."""
    try:
        return TOOL_REGISTRY[name]
    except KeyError as exc:  # pragma: no cover
        raise ToolNotFoundError(name) from exc
