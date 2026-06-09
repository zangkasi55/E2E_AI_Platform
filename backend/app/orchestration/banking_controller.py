"""UC2 — Conversational Banking Control Pattern (deterministic).

Parent agent ``banking_controller`` implements the SEQUENTIAL_CONDITIONAL
pattern ("check balance; if > 5000 THB transfer 2000 to mom") with a strict
separation between:

  * Probabilistic zone (model/heuristic): intent decomposition, slot filling,
    conditional logic.
  * Deterministic zone (ENFORCED, not prompt-driven): guardrails, EKYC identity
    confirmation, APIM tool scopes / PDP, the transfer-limit judgement, and the
    terminal handoff.

Specialist steps (each deterministic in mock mode):
  * EKYC (``ekyc_agent``): the customer confirms they are the account holder;
    no account is touched until this passes.
  * Bank query (``bank_query``): reads the account snapshot (balance/status).
  * Judgement (``judgement_agent``): decides whether the transfer may proceed by
    combining EKYC pass, sufficient remaining balance, and the bank transfer-limit
    policy (default 1500 THB per transaction, adjustable via /api/banking/policy).

HARD RULE (POC_SPEC.md): **no money movement**. The terminal action is always
``request_transaction_handoff`` producing an auditable handoff object with
``requires_confirmation:true`` and ``requires_step_up_auth:true``. There is NO
code path in this controller (or the registry) that executes a transfer.

Guardrails reject prompt-injection style instructions (e.g. "ignore bank rules",
"skip OTP", "disable step-up auth") BEFORE any tool call.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ..config import settings
from ..agents.base import Agent
from ..agents.foundry_workflow_client import invoke_workflow
from ..models import (
    BankingMessage,
    BankingResponse,
    HandoffObject,
    PolicyResult,
    RunState,
    RunStatus,
    Slots,
    StepStatus,
    StepTrace,
    UseCase,
)
from ..telemetry.audit import audit_store
from ..telemetry.otel import start_foundry_agent_span
from ..telemetry.purview_audit import emit_prompt_risk_event
from ..tools import registry

USE_CASE = UseCase.BANKING.value
DEFAULT_THRESHOLD_THB = 5000.0

# ---------------------------------------------------------------------------
# Guardrail patterns — deterministic regexes scanned BEFORE any tool call.
# These detect attempts to override safety policy / safety flags. Matching any
# of them refuses the entire turn. Patterns are tried in order; first hit wins
# and supplies the rule id used for the DSPM-for-AI risk taxonomy. They are kept
# deliberately broad to catch natural-language prompt-injection / jailbreak
# phrasings (ignore/disregard/forget/override/bypass, skip OTP/confirmation,
# disable step-up, admin/system override, role impersonation, "do not log",
# "mark as pre-authorised", "skip fraud checks", etc.).
# ---------------------------------------------------------------------------
GUARDRAIL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Instruction override / UPIA — "ignore/disregard/forget (all) previous instructions".
    ("ignore_previous", re.compile(r"\b(ignore|disregard|forget)\s+(all\s+)?(the\s+)?(previous|prior|above)\s+(instruction|prompt|message)", re.I)),
    # Policy override — ignore/disregard/forget/override/bypass ... rules/policy/control/fraud check/daily limit.
    ("override_rules", re.compile(r"\b(ignore|disregard|forget|override|bypass)\b[\w\s']{0,24}?\b(rule|polic(?:y|ies)|control|fraud\s+check|daily\s+limit)", re.I)),
    # Authentication bypass — OTP.
    ("skip_otp", re.compile(r"\b(skip|bypass|disable|no|without|don'?t\s+(?:require|ask\s+for|need))\b[\w\s']{0,15}?\botp\b", re.I)),
    # Authentication bypass — step-up auth.
    ("disable_step_up", re.compile(r"\b(disable|skip|bypass|without|no|don'?t\s+(?:require|need))\b[\w\s']{0,12}?step[- ]?up", re.I)),
    # Control bypass — confirmation / approval.
    ("skip_confirmation", re.compile(r"\b(skip|no|without|disable|do\s+not|don'?t)\b[\w\s']{0,15}?\b(confirmation|confirm|approval)\b", re.I)),
    # Privilege escalation / role impersonation — admin·system override, act-as, granted permission.
    ("admin_mode", re.compile(r"\b(admin|developer|system)\s+(mode|override)\b|\b(act\s+as|you\s+have\s+permission|bank\s+manager)\b", re.I)),
    # Risky unauthorized action — force/just execute, do-not-log, pre-authorise, skip fraud checks.
    ("force_execute", re.compile(r"\b(force|just)\s+(execute|move|send|transfer|pay)\b|\b(do\s+not|don'?t)\s+log\b|\bmark\s+it\s+as\s+pre-?authoris|\bskip\s+fraud\s+check", re.I)),
    # Direct money-movement intent — execute/complete/finalize the transfer/payment.
    ("move_money_directly", re.compile(r"\b(execute|complete|finalize)\s+(the\s+)?(transfer|payment)\b", re.I)),
]


class GuardrailViolation(Exception):
    """Raised internally when a guardrail pattern matches."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule


class BankingController:
    """Deterministic SEQUENTIAL_CONDITIONAL banking control flow."""

    # EKYC confirm/cancel loop: the customer may cancel up to this many times
    # (re-prompt loop). A cancel beyond this aborts the flow as EKYC_FAILED.
    MAX_EKYC_CANCELS = 2

    def __init__(self) -> None:
        # The probabilistic zone is represented by a single controller agent.
        # In MOCK_MODE its outputs are deterministic; in live mode it would use
        # function-calling for intent/slot extraction.
        self.agent = Agent(
            "banking_controller",
            model="gpt-4o",
            system_prompt=(
                "You decompose a banking request into intents and slots. You never "
                "move money; the only terminal action is a transaction handoff."
            ),
            use_case=USE_CASE,
        )

    # -- trace helper -------------------------------------------------------
    def _trace(
        self,
        run: RunState,
        step: int,
        action: str,
        *,
        inp: dict[str, Any] | None = None,
        out: dict[str, Any] | None = None,
        status: StepStatus = StepStatus.OK,
        note: str | None = None,
    ) -> StepTrace:
        st = StepTrace(
            run_id=run.run_id,
            step=step,
            agent="banking_controller",
            action=action,
            status=status,
            input=inp or {},
            output=out or {},
            note=note,
        )
        run.steps.append(st)
        audit_store.append_step(st)
        return st

    # -- guardrails (deterministic zone) ------------------------------------
    @staticmethod
    def scan_guardrails(message: str) -> Optional[tuple[str, str]]:
        """Return (rule, matched_text) if a guardrail fires, else None."""
        for rule, pattern in GUARDRAIL_PATTERNS:
            m = pattern.search(message)
            if m:
                return rule, m.group(0)
        return None

    # -- probabilistic zone -------------------------------------------------
    def decompose_intent(self, message: str) -> dict[str, Any]:
        """Heuristic intent decomposition + slot filling (mock of the model).

        Detects the canonical 'check balance; if > X transfer Y to <alias>'
        pattern and extracts amount, threshold, and payee alias.
        """
        msg = message.lower()
        wants_balance = "balance" in msg
        # amount to transfer (first 'transfer/send N')
        amt_match = re.search(r"(?:transfer|send|move)\s+(\d[\d,]*)", msg)
        amount = float(amt_match.group(1).replace(",", "")) if amt_match else None
        # threshold ('over/above N')
        thr_match = re.search(r"(?:over|above|more than|greater than|>)\s*(\d[\d,]*)", msg)
        threshold = float(thr_match.group(1).replace(",", "")) if thr_match else None
        # payee alias ('to <word>')
        payee_match = re.search(r"\bto\s+([a-z]+)", msg)
        payee_alias = payee_match.group(1) if payee_match else None

        conditional = bool(threshold) or ("if" in msg)
        intents = []
        if wants_balance:
            intents.append("check_balance")
        if amount is not None:
            intents.append("conditional_transfer" if conditional else "transfer")
        pattern = "SEQUENTIAL_CONDITIONAL" if conditional and amount is not None else "SEQUENTIAL"
        return {
            "intents": intents or ["unknown"],
            "pattern": pattern,
            "slots": {
                "amount_thb": amount,
                "threshold_thb": threshold or DEFAULT_THRESHOLD_THB,
                "payee_alias": payee_alias,
            },
        }

    # -- main entry ---------------------------------------------------------
    def handle(self, msg: BankingMessage) -> BankingResponse:
        """Process one conversational-banking turn end-to-end (no money moves)."""
        run = RunState(use_case=UseCase.BANKING, status=RunStatus.RUNNING)
        run.run_id = run.id
        audit_store.save_run(run)
        with start_foundry_agent_span(
            agent=settings.foundry_banking_workflow,
            run_id=run.run_id,
            action="banking_control_workflow",
            use_case=USE_CASE,
            model="workflow-orchestrator",
        ):
            return self._handle(msg, run)

    def _handle(self, msg: BankingMessage, run: RunState) -> BankingResponse:
        """Execute the banking workflow after the outer telemetry span starts."""
        step = 0

        # === Deterministic guardrail gate (BEFORE any tool call) ===========
        hit = self.scan_guardrails(msg.message)
        if hit:
            rule, matched = hit
            self._trace(
                run, step, "guardrail_scan",
                inp={"message": msg.message},
                out={
                    "blocked": True,
                    "rule": rule,
                    "matched": matched,
                    "guardrail_policy": {
                        "provider": settings.foundry_guardrail_provider,
                        "policy_id": settings.foundry_guardrail_policy_id,
                        "policy_name": settings.foundry_guardrail_policy_name,
                        "mode": settings.foundry_guardrail_mode,
                    },
                },
                status=StepStatus.BLOCKED,
                note="Prompt-injection / policy-override attempt refused before tool use.",
            )
            # DSPM for AI — capture the risky prompt as a data-security event so
            # it surfaces in Purview's activity log / governance observability.
            emit_prompt_risk_event(
                run_id=run.run_id,
                prompt=msg.message,
                rule=rule,
                matched=matched,
                user=msg.user_id,
                use_case=USE_CASE,
                detection_source=(
                    "azure_ai_foundry_guardrail"
                    if settings.foundry_guardrail_provider
                    else "deterministic_guardrail"
                ),
                guardrail_provider=settings.foundry_guardrail_provider,
                guardrail_policy_id=settings.foundry_guardrail_policy_id or None,
                guardrail_policy_name=settings.foundry_guardrail_policy_name or None,
                guardrail_mode=settings.foundry_guardrail_mode,
            )
            run.status = RunStatus.REFUSED
            audit_store.save_run(run)
            return BankingResponse(
                run_id=run.run_id,
                outcome="REFUSED",
                message=(
                    "This request was refused by a safety guardrail "
                    f"({rule}). I cannot bypass bank rules, OTP, confirmation, or step-up "
                    "authentication. No action was taken."
                ),
                steps=run.steps,
            )

        # === Probabilistic zone: intent decomposition + slot filling =======
        decomposition = self.decompose_intent(msg.message)
        wf_traced = False
        if settings.use_foundry_workflows:
            # The banking control workflow agent orchestrates intent
            # decomposition server-side. Guardrails (above) and every
            # deterministic banking step (below) stay in Python so the
            # "no money moves" guarantee is never delegated to the LLM graph.
            # The workflow call is non-critical (the deterministic decomposition
            # above is authoritative), so a workflow/preview error must never
            # fail the run — fall back to the in-process agent path instead.
            try:
                wf_result = invoke_workflow(
                    settings.foundry_banking_workflow,
                    (
                        "Decompose this banking request into intent + slots only. "
                        "Never move money; the host application performs all account "
                        f"actions deterministically.\n\nRequest: {msg.message}"
                    ),
                )
                self._trace(
                    run,
                    step,
                    "invoke_workflow",
                    inp={"workflow": wf_result.workflow_name, "message": msg.message},
                    out={
                        "engine": "foundry_workflow",
                        "status": wf_result.status,
                        "mocked": wf_result.mocked,
                        "decomposition": decomposition,
                    },
                    note=f"Intent decomposition orchestrated by '{wf_result.workflow_name}'.",
                )
                wf_traced = True
            except Exception as exc:  # noqa: BLE001 - workflow engine is non-critical
                self._trace(
                    run,
                    step,
                    "invoke_workflow",
                    inp={"workflow": settings.foundry_banking_workflow, "message": msg.message},
                    out={
                        "engine": "foundry_workflow",
                        "error": str(exc)[:300],
                        "fallback": "in_process_agents",
                    },
                    note="Foundry workflow invocation failed; fell back to in-process agent orchestration.",
                )
        if not wf_traced:
            self.agent.run_step(
                run_id=run.run_id,
                step=step,
                user_prompt=f"Decompose intent: {msg.message}",
                mock_response=str(decomposition),
            )
            self._trace(run, step, "decompose_intent", inp={"message": msg.message}, out=decomposition)
        slots = Slots(
            amount_thb=decomposition["slots"]["amount_thb"],
            threshold_thb=decomposition["slots"]["threshold_thb"],
            payee_alias=decomposition["slots"]["payee_alias"],
            src_account=msg.src_account,
        )

        # === Step: EKYC identity confirmation (confirm/cancel loop) =========
        # The customer is asked to Confirm or Cancel that they are the account
        # holder. Confirm -> proceed. Cancel -> re-prompt (loop). More than two
        # cancels -> abort the whole flow as EKYC_FAILED. ``identity_confirmed``
        # is kept for backward compatibility (== ekyc_decision == "confirm").
        step += 1
        confirmed = bool(msg.identity_confirmed) or msg.ekyc_decision == "confirm"
        with start_foundry_agent_span(
            agent="ekyc_agent",
            run_id=run.run_id,
            step=step,
            action="confirm_identity",
            use_case=USE_CASE,
            model="deterministic-tool",
        ):
            ekyc = registry.confirm_identity(
                msg.user_id,
                confirmed,
                caller_agent="ekyc_agent",
            )
        self._trace(
            run, step, "confirm_identity",
            inp={
                "user_id": msg.user_id,
                "ekyc_decision": msg.ekyc_decision
                or ("confirm" if msg.identity_confirmed else None),
                "ekyc_cancel_count": msg.ekyc_cancel_count,
            },
            out=ekyc,
            status=StepStatus.OK if ekyc.get("ekyc_passed") else StepStatus.BLOCKED,
            note="EKYC — customer must Confirm (or Cancel) they are the account holder before any account action.",
        )
        name = ekyc.get("display_name") or "the account holder"

        # Unknown customer profile -> always a hard EKYC failure.
        if not ekyc.get("user_found", False):
            run.status = RunStatus.COMPLETED
            audit_store.save_run(run)
            return BankingResponse(
                run_id=run.run_id, outcome="EKYC_FAILED",
                message="EKYC failed: we could not find your customer profile. No account was accessed.",
                ekyc=ekyc, ekyc_cancel_count=msg.ekyc_cancel_count, steps=run.steps,
            )

        if not ekyc.get("ekyc_passed"):
            run.status = RunStatus.COMPLETED
            audit_store.save_run(run)
            if msg.ekyc_decision == "cancel":
                new_count = msg.ekyc_cancel_count + 1
                if new_count > self.MAX_EKYC_CANCELS:
                    # Cancelled more than twice -> cancel the whole process.
                    return BankingResponse(
                        run_id=run.run_id, outcome="EKYC_FAILED",
                        message=(
                            f"EKYC failed: identity confirmation was cancelled {new_count} times. "
                            "The process has been cancelled and no account was accessed."
                        ),
                        ekyc=ekyc, ekyc_cancel_count=new_count, steps=run.steps,
                    )
                # Loop: re-prompt the confirm/cancel gate.
                remaining = self.MAX_EKYC_CANCELS + 1 - new_count
                return BankingResponse(
                    run_id=run.run_id, outcome="EKYC_REQUIRED",
                    message=(
                        f"Identity confirmation cancelled (attempt {new_count} of "
                        f"{self.MAX_EKYC_CANCELS + 1}). Please confirm you are {name} to continue, "
                        f"or cancel. {remaining} cancel(s) remaining before the request is stopped."
                    ),
                    ekyc=ekyc, ekyc_cancel_count=new_count, steps=run.steps,
                )
            # No decision yet -> initial confirm/cancel prompt.
            return BankingResponse(
                run_id=run.run_id, outcome="EKYC_REQUIRED",
                message=(
                    f"Before I can access your account, please confirm you are {name}. "
                    "Choose Confirm to proceed, or Cancel."
                ),
                ekyc=ekyc, ekyc_cancel_count=msg.ekyc_cancel_count, steps=run.steps,
            )

        # === Step: bank query (account snapshot) ===========================
        step += 1
        src_account = msg.src_account
        if src_account is None:
            # default to the user's first account in synthetic data
            src_account = self._default_account(msg.user_id)
            slots.src_account = src_account
        with start_foundry_agent_span(
            agent="bank_query",
            run_id=run.run_id,
            step=step,
            action="query_bank_account",
            use_case=USE_CASE,
            model="deterministic-tool",
        ):
            balance_res = registry.query_bank_account(
                msg.user_id,
                src_account,
                caller_agent="bank_query",
            )
        self._trace(run, step, "query_bank_account", inp={"user_id": msg.user_id, "account_id": src_account}, out=balance_res)
        if "error" in balance_res:
            run.status = RunStatus.FAILED
            audit_store.save_run(run)
            return BankingResponse(
                run_id=run.run_id, outcome="INFO",
                message=f"Could not read account: {balance_res['error']}.", ekyc=ekyc, steps=run.steps,
            )
        balance = float(balance_res["balance_thb"])

        # If there's no transfer intent, just report the balance.
        if slots.amount_thb is None:
            run.status = RunStatus.COMPLETED
            audit_store.save_run(run)
            return BankingResponse(
                run_id=run.run_id, outcome="INFO",
                message=f"Your {src_account} balance is {balance:,.2f} THB.", ekyc=ekyc, steps=run.steps,
            )

        # === Conditional logic (probabilistic zone) ========================
        step += 1
        threshold = slots.threshold_thb or DEFAULT_THRESHOLD_THB
        condition_met = balance > threshold
        self._trace(
            run, step, "evaluate_condition",
            inp={"balance_thb": balance, "threshold_thb": threshold},
            out={"condition": f"balance > {threshold}", "result": condition_met},
        )
        if not condition_met:
            run.status = RunStatus.COMPLETED
            audit_store.save_run(run)
            return BankingResponse(
                run_id=run.run_id, outcome="CONDITION_NOT_MET",
                message=(
                    f"Balance {balance:,.2f} THB is not above the {threshold:,.0f} THB "
                    "threshold, so no transfer was prepared."
                ),
                ekyc=ekyc, steps=run.steps,
            )

        # === Resolve payee =================================================
        step += 1
        payee_res = registry.resolve_payee(
            msg.user_id,
            slots.payee_alias or "",
            caller_agent="banking_controller",
        )
        self._trace(run, step, "resolve_payee", inp={"payee_alias": slots.payee_alias}, out=payee_res)
        if "error" in payee_res:
            run.status = RunStatus.COMPLETED
            audit_store.save_run(run)
            return BankingResponse(
                run_id=run.run_id, outcome="INFO",
                message=f"Could not resolve payee '{slots.payee_alias}'.", ekyc=ekyc, steps=run.steps,
            )
        slots.payee_id = payee_res["payee_id"]

        # === Judgement: EKYC + funds + transfer-limit policy (no money moves) ===
        step += 1
        with start_foundry_agent_span(
            agent="judgement_agent",
            run_id=run.run_id,
            step=step,
            action="evaluate_transfer_judgement",
            use_case=USE_CASE,
            model="deterministic-tool",
        ):
            judgement = registry.evaluate_transfer_judgement(
                msg.user_id,
                src_account,
                slots.payee_id,
                float(slots.amount_thb),
                ekyc_passed=bool(ekyc.get("ekyc_passed")),
                caller_agent="judgement_agent",
            )
        self._trace(
            run, step, "evaluate_transfer_judgement",
            inp={"amount": slots.amount_thb, "transfer_limit_thb": judgement.get("transfer_limit_thb")},
            out=judgement,
            status=StepStatus.OK if judgement.get("passed") else StepStatus.BLOCKED,
            note="Judgement combines EKYC pass, sufficient funds, and the bank transfer-limit policy.",
        )
        policy = PolicyResult(
            eligible=bool(judgement.get("passed")),
            reasons=list(judgement.get("reasons", [])),
            scope_ok=bool(judgement.get("scope_ok", True)),
        )
        if not policy.eligible:
            run.status = RunStatus.COMPLETED
            audit_store.save_run(run)
            limit = judgement.get("transfer_limit_thb")
            policy_breached = any(
                r.startswith("exceeds_transfer_limit") or r == "ekyc_not_passed"
                for r in policy.reasons
            )
            outcome = "POLICY_DECLINED" if policy_breached else "CONDITION_NOT_MET"
            if any(r.startswith("exceeds_transfer_limit") for r in policy.reasons) and limit is not None:
                detail = (
                    f"the {float(slots.amount_thb):,.0f} THB transfer exceeds the "
                    f"{float(limit):,.0f} THB per-transaction limit"
                )
            else:
                detail = ", ".join(policy.reasons)
            return BankingResponse(
                run_id=run.run_id, outcome=outcome,
                message=f"Transfer declined by judgement: {detail}. No money has moved.",
                ekyc=ekyc, judgement=judgement, steps=run.steps,
            )

        # === TERMINAL: request_transaction_handoff (NO MONEY MOVES) ========
        step += 1
        intent = f"transfer {slots.amount_thb:.0f} THB to {slots.payee_alias} ({slots.payee_id})"
        handoff_payload = registry.request_transaction_handoff(
            intent=intent,
            slots=slots.model_dump(),
            policy_result=policy.model_dump(),
            caller_agent="banking_controller",
        )
        # Build the strongly-typed, audited handoff object. The model pins
        # requires_confirmation / requires_step_up_auth to Literal[True].
        handoff = HandoffObject(
            run_id=run.run_id,
            user_id=msg.user_id,
            intent=intent,
            slots=slots,
            policy_result=policy,
        )
        audit_store.save_handoff(handoff)
        self._trace(
            run, step, "request_transaction_handoff",
            inp={"intent": intent},
            out={
                "handoff_id": handoff.handoff_id,
                "requires_confirmation": handoff.requires_confirmation,
                "requires_step_up_auth": handoff.requires_step_up_auth,
                "executed": handoff_payload["executed"],
            },
            note="Terminal handoff created. No funds moved; awaits human confirmation + step-up auth.",
        )
        run.status = RunStatus.COMPLETED
        audit_store.save_run(run)
        return BankingResponse(
            run_id=run.run_id,
            outcome="HANDOFF_CREATED",
            message=(
                f"Prepared a transaction handoff for {intent}. No money has moved. "
                "It requires your confirmation and step-up authentication to proceed."
            ),
            handoff=handoff,
            ekyc=ekyc,
            judgement=judgement,
            steps=run.steps,
        )

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _default_account(user_id: str) -> str:
        bal = registry._load_json("banking/users.json")["users"]  # noqa: SLF001 (mock convenience)
        user = next((u for u in bal if u["user_id"] == user_id), None)
        if user and user["accounts"]:
            return user["accounts"][0]["account_id"]
        return "UNKNOWN"


# Shared singleton.
banking_controller = BankingController()
