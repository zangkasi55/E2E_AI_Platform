"""UC2 — Conversational Banking Control Pattern (deterministic).

Parent agent ``banking_controller`` implements the SEQUENTIAL_CONDITIONAL
pattern ("check balance; if > 5000 THB transfer 2000 to mom") with a strict
separation between:

  * Probabilistic zone (model/heuristic): intent decomposition, slot filling,
    conditional logic.
  * Deterministic zone (ENFORCED, not prompt-driven): guardrails, APIM tool
    scopes / PDP, and the terminal handoff.

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
from ..telemetry.purview_audit import emit_prompt_risk_event
from ..tools import registry

USE_CASE = UseCase.BANKING.value
DEFAULT_THRESHOLD_THB = 5000.0

# ---------------------------------------------------------------------------
# Guardrail patterns — deterministic regexes scanned BEFORE any tool call.
# These detect attempts to override safety policy / safety flags. Matching any
# of them refuses the entire turn.
# ---------------------------------------------------------------------------
GUARDRAIL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("override_rules", re.compile(r"ignore\s+(the\s+)?(bank\s+)?(rules|policy|policies|instructions)", re.I)),
    ("skip_otp", re.compile(r"\b(skip|bypass|disable|no)\s+(the\s+)?otp\b", re.I)),
    ("skip_confirmation", re.compile(r"\b(no|skip|without|disable)\s+(confirmation|approval)\b", re.I)),
    ("disable_step_up", re.compile(r"disable\s+(the\s+)?step[- ]?up(\s+auth(entication)?)?", re.I)),
    ("admin_mode", re.compile(r"\b(admin|developer|system)\s+mode\b", re.I)),
    ("ignore_previous", re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts)", re.I)),
    ("force_execute", re.compile(r"\b(force|just)\s+(execute|move|send|transfer)\b.*\b(now|immediately|no\s+confirmation)\b", re.I)),
    ("move_money_directly", re.compile(r"\b(execute|complete|finalize)\s+(the\s+)?(transfer|payment)\b", re.I)),
]


class GuardrailViolation(Exception):
    """Raised internally when a guardrail pattern matches."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule


class BankingController:
    """Deterministic SEQUENTIAL_CONDITIONAL banking control flow."""

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

        # === Step: check balance ===========================================
        step += 1
        src_account = msg.src_account
        if src_account is None:
            # default to the user's first account in synthetic data
            src_account = self._default_account(msg.user_id)
            slots.src_account = src_account
        balance_res = registry.get_balance(msg.user_id, src_account)
        self._trace(run, step, "get_balance", inp={"user_id": msg.user_id, "account_id": src_account}, out=balance_res)
        if "error" in balance_res:
            run.status = RunStatus.FAILED
            audit_store.save_run(run)
            return BankingResponse(
                run_id=run.run_id, outcome="INFO",
                message=f"Could not read balance: {balance_res['error']}.", steps=run.steps,
            )
        balance = float(balance_res["balance_thb"])

        # If there's no transfer intent, just report the balance.
        if slots.amount_thb is None:
            run.status = RunStatus.COMPLETED
            audit_store.save_run(run)
            return BankingResponse(
                run_id=run.run_id, outcome="INFO",
                message=f"Your {src_account} balance is {balance:,.2f} THB.", steps=run.steps,
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
                steps=run.steps,
            )

        # === Resolve payee =================================================
        step += 1
        payee_res = registry.resolve_payee(msg.user_id, slots.payee_alias or "")
        self._trace(run, step, "resolve_payee", inp={"payee_alias": slots.payee_alias}, out=payee_res)
        if "error" in payee_res:
            run.status = RunStatus.COMPLETED
            audit_store.save_run(run)
            return BankingResponse(
                run_id=run.run_id, outcome="INFO",
                message=f"Could not resolve payee '{slots.payee_alias}'.", steps=run.steps,
            )
        slots.payee_id = payee_res["payee_id"]

        # === Deterministic PDP: eligibility (still no money movement) ======
        step += 1
        elig = registry.check_transfer_eligibility(
            msg.user_id, src_account, slots.payee_id, float(slots.amount_thb)
        )
        self._trace(run, step, "check_transfer_eligibility", inp={"amount": slots.amount_thb}, out=elig)
        policy = PolicyResult(
            eligible=bool(elig.get("eligible")),
            reasons=list(elig.get("reasons", [])),
            scope_ok=bool(elig.get("scope_ok", True)),
        )
        if not policy.eligible:
            run.status = RunStatus.COMPLETED
            audit_store.save_run(run)
            return BankingResponse(
                run_id=run.run_id, outcome="CONDITION_NOT_MET",
                message=f"Transfer not eligible: {', '.join(policy.reasons)}.", steps=run.steps,
            )

        # === TERMINAL: request_transaction_handoff (NO MONEY MOVES) ========
        step += 1
        intent = f"transfer {slots.amount_thb:.0f} THB to {slots.payee_alias} ({slots.payee_id})"
        handoff_payload = registry.request_transaction_handoff(
            intent=intent, slots=slots.model_dump(), policy_result=policy.model_dump()
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
