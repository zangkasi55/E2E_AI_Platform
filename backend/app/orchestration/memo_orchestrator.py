"""UC1 — Credit Memo Drafting orchestrator.

Parent agent ``memo_orchestrator`` plans the steps and invokes four sub-agents:
``doc_retrieval`` → ``financial_ratio`` → ``bureau_summary`` → ``memo_assembler``.
Each step:
  * calls the relevant APIM-fronted tool(s) from the registry,
  * runs the sub-agent model call (mocked in MOCK_MODE),
  * emits a :class:`StepTrace` to the audit store,
  * records token usage (handled inside the Agent).

After assembling the draft, the run PAUSES for HITL approval (Durable Functions /
Service Bus abstraction). No memo is final without a human decision.
"""
from __future__ import annotations

import re
from typing import Any

from ..agents.base import Agent
from ..durable.hitl import hitl_gateway
from ..models import (
    ApprovalDecision,
    RunRequest,
    RunState,
    RunStatus,
    StepStatus,
    StepTrace,
    UseCase,
)
from ..telemetry.audit import audit_store
from ..telemetry.purview_audit import emit_label_enforcement_event
from ..governance.sensitivity import resolve_sensitivity_label
from ..tools import registry

USE_CASE = UseCase.CREDIT_MEMO.value


# ---------------------------------------------------------------------------
# Sub-agent definitions (model assignment per POC_SPEC.md — gpt-4o for the
# heavier reasoning/assembly agents, gpt-4o-mini for lighter retrieval/summary).
# ---------------------------------------------------------------------------
def _build_agents() -> dict[str, Agent]:
    return {
        "memo_orchestrator": Agent(
            "memo_orchestrator",
            model="gpt-4o",
            system_prompt=(
                "You plan and coordinate sub-agents to draft an SME credit memo and to "
                "decide whether the case should be APPROVED or REJECTED. Direct the "
                "sub-agents to read the attached credit file, verify the figures against "
                "the verified datasets, and apply the credit policy gates. You never "
                "finalize without human approval."
            ),
            use_case=USE_CASE,
        ),
        "doc_retrieval": Agent(
            "doc_retrieval",
            model="gpt-4o-mini",
            system_prompt=(
                "You retrieve and ground statements on approved sources only. When an "
                "attached credit file is provided, extract the applicant identity and the "
                "key facts it states (requested facility, financial summary, bureau "
                "findings) and cross-check them against the verified datasets."
            ),
            use_case=USE_CASE,
        ),
        "financial_ratio": Agent(
            "financial_ratio",
            model="gpt-4o-mini",
            system_prompt=(
                "You are a credit analyst. Interpret the computed financial ratios for a "
                "credit audience and judge whether the financials support APPROVAL or "
                "REJECTION. Apply policy gates strictly: DSCR >= 1.25x and net debt/EBITDA "
                "<= 4.0x and current ratio >= 1.0x and non-negative EBITDA margin. If DSCR "
                "< 1.10x, EBITDA <= 0, or leverage exceeds 4.0x, explicitly flag a hard "
                "reject. State which gates pass and which fail, then give a clear "
                "approve / reject / request-edits view with reasons."
            ),
            use_case=USE_CASE,
        ),
        "bureau_summary": Agent(
            "bureau_summary",
            model="gpt-4o-mini",
            system_prompt=(
                "You are a credit-bureau analyst. Summarize the bureau report into "
                "risk-relevant findings and judge whether the credit history supports "
                "APPROVAL or REJECTION. Apply policy gates strictly: bureau score >= 680 "
                "and zero delinquencies in the trailing 12 months. A score below 680 or "
                "any recent delinquency is a hard-reject trigger; state it explicitly with "
                "the offending values."
            ),
            use_case=USE_CASE,
        ),
        "memo_assembler": Agent(
            "memo_assembler",
            model="gpt-4o",
            system_prompt=(
                "You assemble section bodies into a coherent draft credit memo AND state a "
                "final recommendation of approve or reject. Weigh the financial analysis, "
                "the bureau assessment, and the attached credit file together. Do not "
                "recommend approval when any policy gate fails. When hard-risk triggers "
                "exist (DSCR/leverage/EBITDA breach, bureau score < 680, or recent "
                "delinquencies), the recommendation must be reject, with the specific "
                "failing gates cited. The attached credit file is the actual case under "
                "review: if it states an explicit DECLINE / 'not recommended for approval' "
                "recommendation, reports negative EBITDA, carries a going-concern "
                "qualification, indicates negative equity / technical insolvency, or a "
                "DSCR below 1.25x, you MUST recommend reject regardless of any dataset "
                "figures — cite the exact language from the file."
            ),
            use_case=USE_CASE,
        ),
    }


class MemoOrchestrator:
    """Coordinates the UC1 credit-memo drafting flow."""

    def __init__(self) -> None:
        self.agents = _build_agents()

    @staticmethod
    def _verify_doc_retrieval(retrieval_ctx: dict[str, Any], has_attachment: bool) -> dict[str, Any]:
        applicant_chunks = retrieval_ctx.get("applicant_chunks", [])
        policy_chunks = retrieval_ctx.get("policy_chunks", [])
        checks = [
            {
                "name": "applicant_evidence_present",
                "ok": len(applicant_chunks) > 0,
                "detail": f"applicant chunks={len(applicant_chunks)}",
            },
            {
                "name": "policy_evidence_present",
                "ok": len(policy_chunks) > 0,
                "detail": f"policy chunks={len(policy_chunks)}",
            },
            {
                "name": "dr_attachment_provided",
                "ok": has_attachment,
                "detail": "attached document provided" if has_attachment else "no attached document",
            },
        ]
        return {"passed": all(c["ok"] for c in checks), "checks": checks}

    @staticmethod
    def _verify_financials(ratios: dict[str, Any]) -> dict[str, Any]:
        dscr = ratios.get("dscr")
        leverage = ratios.get("net_debt_to_ebitda")
        ebitda_margin = ratios.get("ebitda_margin_pct")
        checks = [
            {
                "name": "dscr_meets_threshold",
                "ok": isinstance(dscr, (int, float)) and dscr >= 1.25,
                "detail": f"dscr={dscr}",
            },
            {
                "name": "leverage_within_threshold",
                "ok": isinstance(leverage, (int, float)) and leverage <= 4.0,
                "detail": f"net_debt_to_ebitda={leverage}",
            },
            {
                "name": "liquidity_positive",
                "ok": isinstance(ratios.get("current_ratio"), (int, float)) and ratios.get("current_ratio") >= 1.0,
                "detail": f"current_ratio={ratios.get('current_ratio')}",
            },
            {
                "name": "ebitda_margin_non_negative",
                "ok": isinstance(ebitda_margin, (int, float)) and ebitda_margin >= 0,
                "detail": f"ebitda_margin_pct={ebitda_margin}",
            },
        ]
        return {"passed": all(c["ok"] for c in checks), "checks": checks}

    @staticmethod
    def _verify_bureau(bureau: dict[str, Any]) -> dict[str, Any]:
        score = bureau.get("score")
        delinquencies = bureau.get("delinquencies_12m")
        checks = [
            {
                "name": "bureau_score_acceptable",
                "ok": isinstance(score, (int, float)) and score >= 680,
                "detail": f"score={score}",
            },
            {
                "name": "recent_delinquencies_clear",
                "ok": isinstance(delinquencies, (int, float)) and delinquencies == 0,
                "detail": f"delinquencies_12m={delinquencies}",
            },
        ]
        return {"passed": all(c["ok"] for c in checks), "checks": checks}

    @staticmethod
    def _verify_memo_draft(draft: dict[str, Any]) -> dict[str, Any]:
        section_keys = {s.get("key") for s in draft.get("sections", [])}
        required = {
            "executive_summary",
            "financial_analysis",
            "bureau_assessment",
            "recommendation",
        }
        checks = [
            {
                "name": "draft_status",
                "ok": draft.get("status") == "draft",
                "detail": f"status={draft.get('status')}",
            },
            {
                "name": "required_sections_present",
                "ok": required.issubset(section_keys),
                "detail": f"sections={sorted(section_keys)}",
            },
        ]
        return {"passed": all(c["ok"] for c in checks), "checks": checks}

    @staticmethod
    def _verify_document(doc_text: str) -> dict[str, Any]:
        """Scan the attached credit file itself for explicit reject signals.

        The uploaded document is the actual case under review. When it contains
        hard adverse signals — an explicit decline recommendation, negative
        EBITDA, a going-concern qualification, technical insolvency, or a
        sub-threshold DSCR — those findings override any dataset-derived
        approval. This makes the recommendation reflect what the agent reads in
        the document, not just the row the applicant id maps to.
        """
        text = (doc_text or "").lower()
        if not text.strip():
            # No document text to analyse — contribute no signal either way.
            return {"passed": True, "checks": []}

        def found(pattern: str) -> bool:
            return re.search(pattern, text) is not None

        # Each signal: (check_name, adverse_present, detail_when_adverse)
        signals = [
            (
                "document_recommendation_not_decline",
                bool(
                    found(r"recommendation[:\s][^\n]{0,80}\b(decline|reject)\b")
                    or "not recommended for approval" in text
                    or "does not meet credit standards" in text
                    or "fails on every gate" in text
                    or "fails on every credit gate" in text
                ),
                "explicit decline / not-recommended language in the credit file",
            ),
            (
                "document_ebitda_non_negative",
                bool(
                    found(r"negative ebitda")
                    or found(r"ebitda[^\n]{0,60}(turned negative|is negative|went negative|negative)")
                    or found(r"ebitda[^\n]{0,20}[-(]\s?\d")
                ),
                "credit file reports negative EBITDA",
            ),
            (
                "document_no_going_concern",
                bool("going-concern" in text or "going concern" in text),
                "auditor going-concern qualification noted in the credit file",
            ),
            (
                "document_solvent",
                bool(
                    "technically insolvent" in text
                    or "negative book equity" in text
                    or "negative equity" in text
                ),
                "negative equity / technical insolvency noted in the credit file",
            ),
            (
                "document_dscr_meets_threshold",
                bool(found(r"dscr[^\n]{0,40}(<|below|far below)\s*(0|1\.[0-1]|1\.2[0-4])")),
                "credit file states DSCR below the 1.25x minimum",
            ),
        ]
        checks = [
            {
                "name": name,
                "ok": not adverse,
                "detail": detail if adverse else "no adverse signal in document",
            }
            for name, adverse, detail in signals
        ]
        return {"passed": all(c["ok"] for c in checks), "checks": checks}


    @staticmethod
    def _build_approval_guidance(*verifications: dict[str, Any]) -> dict[str, Any]:
        should_approve: list[str] = []
        should_not_approve: list[str] = []
        for verification in verifications:
            for check in verification.get("checks", []):
                reason = f"{check['name']}: {check['detail']}"
                if check.get("ok"):
                    should_approve.append(reason)
                else:
                    should_not_approve.append(reason)

        hard_reject_markers = {
            "dscr_meets_threshold",
            "leverage_within_threshold",
            "ebitda_margin_non_negative",
            "bureau_score_acceptable",
            "recent_delinquencies_clear",
            # Signals read directly from the attached credit file. Any of these
            # makes the case a hard reject regardless of the dataset row.
            "document_recommendation_not_decline",
            "document_ebitda_non_negative",
            "document_no_going_concern",
            "document_solvent",
            "document_dscr_meets_threshold",
        }
        hard_reject = any(
            reason.split(":", 1)[0] in hard_reject_markers for reason in should_not_approve
        )
        recommendation = "reject" if hard_reject else ("approve" if not should_not_approve else "request_edits")
        return {
            "recommendation": recommendation,
            "should_approve": should_approve,
            "should_not_approve": should_not_approve,
        }

    # -- step helper --------------------------------------------------------
    def _trace(
        self,
        run: RunState,
        step: int,
        agent: str,
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
            agent=agent,
            action=action,
            status=status,
            input=inp or {},
            output=out or {},
            note=note,
        )
        run.steps.append(st)
        audit_store.append_step(st)
        return st

    # -- main entry ---------------------------------------------------------
    def start(self, request: RunRequest) -> RunState:
        """Plan + execute sub-agents, then pause for HITL approval."""
        run = RunState(use_case=UseCase.CREDIT_MEMO, request=request, status=RunStatus.RUNNING)
        run.run_id = run.id  # keep run_id == id for Cosmos partitioning
        audit_store.save_run(run)

        applicant_id = request.applicant_id
        dr_document = request.dr_document.model_dump() if request.dr_document else None
        # Excerpt of the attached credit file the analysis agents read so the
        # decision is grounded in the actual case content, not just metadata.
        doc_content = (dr_document or {}).get("content") or ""
        doc_excerpt = doc_content[:4000]
        step = 0

        # --- Step 0: plan ---------------------------------------------------
        plan = [
            "doc_retrieval: gather approved-source context",
            "financial_ratio: compute + interpret ratios",
            "bureau_summary: summarize bureau report",
            "memo_assembler: assemble draft",
            "HITL: pause for human approval",
        ]
        self.agents["memo_orchestrator"].run_step(
            run_id=run.run_id,
            step=step,
            user_prompt=f"Plan credit memo for {applicant_id} using template {request.template_id}.",
            mock_response="PLAN:\n- " + "\n- ".join(plan),
        )
        self._trace(run, step, "memo_orchestrator", "plan", out={"plan": plan})

        # --- Purview / DSPM sensitivity-label gate -------------------------
        # Before any document is ingested, resolve its Microsoft Purview
        # sensitivity label. Confidential / Highly Confidential files are
        # rejected and the decision is logged to Purview + DSPM for AI.
        if dr_document:
            step += 1
            label_result = resolve_sensitivity_label(
                dr_document.get("file_name", ""),
                dr_document.get("mime_type"),
            )
            event = emit_label_enforcement_event(
                run_id=run.run_id,
                file_name=dr_document.get("file_name", ""),
                label_result=label_result,
                user=request.requested_by,
                use_case=USE_CASE,
            )
            if label_result["blocked"]:
                self._trace(
                    run,
                    step,
                    "doc_retrieval",
                    "purview_label_scan",
                    inp={"attached_document": dr_document},
                    out={"sensitivity": label_result, "dspm_event": event},
                    status=StepStatus.BLOCKED,
                    note=label_result["justification"],
                )
                run.policy_block = {
                    "reason": "sensitivity_label",
                    "label": label_result["label"],
                    "label_full_name": label_result["full_name"],
                    "file_name": dr_document.get("file_name", ""),
                    "justification": label_result["justification"],
                    "dspm_event_id": event.get("id"),
                    "source": label_result["source"],
                }
                run.status = RunStatus.REFUSED
                audit_store.save_run(run)
                return run
            self._trace(
                run,
                step,
                "doc_retrieval",
                "purview_label_scan",
                inp={"attached_document": dr_document},
                out={"sensitivity": label_result, "dspm_event": event},
                status=StepStatus.OK,
                note=label_result["justification"],
            )

        # --- Step 1: doc_retrieval -----------------------------------------
        step += 1
        docs = registry.search_documents(
            query=f"credit policy DSCR leverage outlook {applicant_id}",
            source_filter=applicant_id,
            caller_agent="doc_retrieval",
        )
        policy_docs = registry.search_documents(
            query="DSCR leverage limit",
            source_filter="credit_policy",
            caller_agent="doc_retrieval",
        )
        retrieval_ctx = {"applicant_chunks": docs["results"], "policy_chunks": policy_docs["results"]}
        retrieval_input = {"applicant_id": applicant_id}
        if dr_document:
            retrieval_input["attached_document"] = dr_document
            retrieval_ctx["attached_document"] = dr_document
        retrieval_verification = self._verify_doc_retrieval(retrieval_ctx, has_attachment=bool(dr_document))
        self.agents["doc_retrieval"].run_step(
            run_id=run.run_id,
            step=step,
            user_prompt=f"Summarize grounded context: {retrieval_ctx}",
            mock_response=f"Retrieved {len(docs['results'])} applicant + {len(policy_docs['results'])} policy chunks.",
        )
        self._trace(
            run,
            step,
            "doc_retrieval",
            "search_documents",
            inp=retrieval_input,
            out={**retrieval_ctx, "verification": retrieval_verification},
            status=StepStatus.OK if retrieval_verification["passed"] else StepStatus.BLOCKED,
        )

        # --- Step 2: financial_ratio ---------------------------------------
        step += 1
        financials = registry.get_financials(applicant_id, caller_agent="financial_ratio")
        ratios = registry.calculate_ratios(financials, caller_agent="financial_ratio")
        ratio_agent = self.agents["financial_ratio"].run_step(
            run_id=run.run_id,
            step=step,
            user_prompt=(
                f"Analyse whether the financials support approve or reject for {applicant_id}. "
                f"Computed ratios: {ratios}. "
                + (f"Attached credit file (excerpt):\n{doc_excerpt}" if doc_excerpt else "No attached document text was provided.")
            ),
            mock_response=(
                f"DSCR {ratios.get('dscr')}x, net debt/EBITDA {ratios.get('net_debt_to_ebitda')}x, "
                f"current ratio {ratios.get('current_ratio')}, EBITDA margin {ratios.get('ebitda_margin_pct')}%, "
                f"revenue CAGR {ratios.get('revenue_cagr_pct')}%."
            ),
        )
        ratios_verification = self._verify_financials(ratios)
        self._trace(
            run,
            step,
            "financial_ratio",
            "calculate_ratios",
            inp={"applicant_id": applicant_id},
            out={**ratios, "verification": ratios_verification},
            # A failed financial gate is a RISK finding, not a processing error:
            # the run must continue so the reviewer sees a reject recommendation
            # at the HITL gate. It is therefore never marked BLOCKED here.
            status=StepStatus.OK,
        )

        # --- Step 3: bureau_summary ----------------------------------------
        step += 1
        bureau = registry.get_bureau_report(applicant_id, caller_agent="bureau_summary")
        bureau_agent = self.agents["bureau_summary"].run_step(
            run_id=run.run_id,
            step=step,
            user_prompt=(
                f"Assess whether the credit history supports approve or reject for {applicant_id}. "
                f"Bureau report: {bureau}. "
                + (f"Attached credit file (excerpt):\n{doc_excerpt}" if doc_excerpt else "No attached document text was provided.")
            ),
            mock_response=(
                f"Bureau score {bureau.get('score')} ({bureau.get('score_band')}); "
                f"{bureau.get('delinquencies_12m')} delinquencies in 12m; {bureau.get('notes')}"
            ),
        )
        bureau_verification = self._verify_bureau(bureau)
        self._trace(
            run,
            step,
            "bureau_summary",
            "get_bureau_report",
            inp={"applicant_id": applicant_id},
            out={**bureau, "verification": bureau_verification},
            # A failed bureau gate is a RISK finding (low score / delinquencies),
            # not a processing error. The run continues to the HITL gate carrying
            # a reject recommendation instead of halting here.
            status=StepStatus.OK,
        )

        # --- Step 4: memo_assembler ----------------------------------------
        step += 1
        sections = self._build_sections(
            applicant_id=applicant_id,
            request=request,
            retrieval_ctx=retrieval_ctx,
            ratios=ratios,
            ratio_text=ratio_agent.text,
            bureau=bureau,
            bureau_text=bureau_agent.text,
        )
        draft = registry.render_memo(
            sections=sections,
            template_id=request.template_id,
            caller_agent="memo_assembler",
        )
        run.draft_memo = draft
        draft_verification = self._verify_memo_draft(draft)
        # Analyse the attached credit file itself so an adverse document (explicit
        # decline, negative EBITDA, going-concern, insolvency, sub-threshold DSCR)
        # rejects the case even if the dataset row would otherwise pass.
        document_verification = self._verify_document(doc_content)
        approval_guidance = self._build_approval_guidance(
            retrieval_verification,
            ratios_verification,
            bureau_verification,
            draft_verification,
            document_verification,
        )
        run.draft_memo["approval_guidance"] = approval_guidance
        self.agents["memo_assembler"].run_step(
            run_id=run.run_id,
            step=step,
            user_prompt=(
                f"Assemble the draft credit memo for {applicant_id} and state the final "
                f"recommendation (approve or reject). Policy-gate outcome: "
                f"recommendation={approval_guidance['recommendation']}; "
                f"failing gates={approval_guidance['should_not_approve'] or 'none'}. "
                + (f"Attached credit file (excerpt):\n{doc_excerpt}" if doc_excerpt else "")
            ),
            mock_response=(
                f"Assembled draft with {len(draft.get('sections', []))} sections (status=draft); "
                f"recommendation={approval_guidance['recommendation']}."
            ),
        )
        self._trace(
            run,
            step,
            "memo_assembler",
            "render_memo",
            inp={"template_id": request.template_id},
            out={
                "status": draft.get("status"),
                "verification": draft_verification,
                "approval_guidance": approval_guidance,
            },
            status=StepStatus.OK if draft_verification["passed"] else StepStatus.BLOCKED,
        )

        # --- Step 5: HITL pause --------------------------------------------
        step += 1
        hitl_gateway.pause_for_approval(run.run_id, draft)
        run.status = RunStatus.AWAITING_APPROVAL
        self._trace(
            run,
            step,
            "memo_orchestrator",
            "hitl_pause",
            out={
                "status": "awaiting_approval",
                "channel": "teams",
                "approval_guidance": approval_guidance,
            },
            note=(
                "Human approval required. "
                f"Recommendation={approval_guidance['recommendation']} based on step verifications."
            ),
        )
        audit_store.save_run(run)
        return run

    # -- HITL resume --------------------------------------------------------
    def approve(self, run_id: str, decision: ApprovalDecision) -> RunState:
        """Resume a paused run with a human decision and finalize (or reject)."""
        run = audit_store.get_run(run_id)
        if run is None:
            raise KeyError(f"run not found: {run_id}")
        if run.status != RunStatus.AWAITING_APPROVAL:
            raise ValueError(f"run {run_id} is not awaiting approval (status={run.status}).")

        hitl_gateway.resume(run_id, decision)
        run.approval = decision
        step = len(run.steps)

        guidance = ((run.draft_memo or {}).get("approval_guidance") or {}) if run.draft_memo else {}
        if decision.approved and guidance.get("recommendation") == "reject":
            run.status = RunStatus.REFUSED
            self._trace(
                run,
                step,
                "memo_orchestrator",
                "hitl_resume",
                status=StepStatus.BLOCKED,
                out={
                    "approved": True,
                    "reviewer": decision.reviewer,
                    "policy_override_blocked": True,
                    "recommendation": "reject",
                },
                note=(
                    "Approval refused by deterministic policy: run contains hard-reject risk markers. "
                    "Use reject or submit a separate override workflow outside this PoC path."
                ),
            )
            audit_store.save_run(run)
            return run

        if decision.approved:
            final = dict(run.draft_memo or {})
            final["status"] = "final"
            final["approved_by"] = decision.reviewer
            if decision.edits:
                final["reviewer_edits"] = decision.edits
            run.final_memo = final
            run.status = RunStatus.APPROVED
            self._trace(
                run, step, "memo_orchestrator", "hitl_resume",
                out={"approved": True, "reviewer": decision.reviewer},
                note="Human approved — memo marked final.",
            )
            run.status = RunStatus.COMPLETED
        else:
            run.status = RunStatus.REFUSED
            self._trace(
                run, step, "memo_orchestrator", "hitl_resume",
                status=StepStatus.BLOCKED,
                out={"approved": False, "reviewer": decision.reviewer, "comment": decision.comment},
                note="Human rejected draft.",
            )
        audit_store.save_run(run)
        return run

    # -- section synthesis (deterministic in mock mode) ---------------------
    def _build_sections(
        self,
        *,
        applicant_id: str,
        request: RunRequest,
        retrieval_ctx: dict[str, Any],
        ratios: dict[str, Any],
        ratio_text: str,
        bureau: dict[str, Any],
        bureau_text: str,
    ) -> dict[str, str]:
        """Compose section bodies. The memo_assembler agent would author these in
        live mode; here we deterministically synthesize readable bodies."""
        dscr = ratios.get("dscr")
        nde = ratios.get("net_debt_to_ebitda")
        guidance = self._build_approval_guidance(
            self._verify_doc_retrieval(retrieval_ctx, has_attachment=bool(request.dr_document)),
            self._verify_financials(ratios),
            self._verify_bureau(bureau),
            {"checks": []},
        )
        recommendation = guidance.get("recommendation", "request_edits")
        if recommendation == "approve":
            rec_lean = "supportable subject to standard conditions"
        elif recommendation == "reject":
            rec_lean = "not approvable on current terms; recommend decline"
        else:
            rec_lean = "requires remediation and committee review before any approval"
        return {
            "executive_summary": (
                f"Draft credit memo for {applicant_id}. Facility requested per loan officer. "
                f"Headline metrics: DSCR {dscr}x, net debt/EBITDA {nde}x. Preliminary view: {rec_lean}. "
                f"DRAFT — human decision required."
            ),
            "borrower_profile": f"See applicant master data for {applicant_id}. Grounded on approved filings/industry reports.",
            "facility_request": f"Purpose and tenor per request notes: {request.notes or 'n/a'}.",
            "financial_analysis": ratio_text,
            "ratio_dashboard": (
                f"DSCR={dscr}x | NetDebt/EBITDA={nde}x | CurrentRatio={ratios.get('current_ratio')} | "
                f"EBITDA margin={ratios.get('ebitda_margin_pct')}% | Revenue CAGR={ratios.get('revenue_cagr_pct')}%"
            ),
            "bureau_assessment": bureau_text,
            "risks_mitigants": (
                "Key risks: leverage trajectory, sector cyclicality. Mitigants: collateral, covenants, "
                "contracted cash flows where applicable (see grounded context)."
            ),
            "recommendation": (
                f"DRAFT recommendation: {rec_lean}. This is an agent-produced draft and is NOT a decision. "
                f"A human credit officer must approve, edit, or reject."
            ),
        }


# Shared singleton.
memo_orchestrator = MemoOrchestrator()
