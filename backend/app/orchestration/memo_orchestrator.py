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
from ..agents.foundry_workflow_client import invoke_workflow, resume_workflow
from ..config import settings
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
                "review, but form your OWN judgement from its financial data and evidence "
                "— do NOT defer to any recommendation, opinion, or DECLINE/APPROVE advice "
                "written by the relationship manager in the file. Independently read the "
                "figures: latest-year EBITDA and margin, DSCR, leverage, current ratio / "
                "liquidity, bureau score, trailing-12-month delinquencies, and book "
                "equity. If the evidence shows negative EBITDA, a DSCR below 1.25x, a "
                "bureau score below 680, any recent delinquency, a current ratio below "
                "1.0x, or negative book equity, you MUST recommend reject — cite the "
                "specific figures from the file, not its stated recommendation."
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
        """Evaluate the financial EVIDENCE in the attached credit file against
        the credit policy gates.

        The agent forms its own view from the data — revenue, EBITDA, DSCR,
        leverage, liquidity, bureau score, delinquencies, equity. It does NOT
        defer to any recommendation, opinion, or "DECLINE/APPROVE" advice
        written in the file. Only objective figures and observable facts feed
        the gates; whatever the relationship manager concluded is ignored.
        """
        text = (doc_text or "").lower()
        if not text.strip():
            # No document text to analyse — contribute no signal either way.
            return {"passed": True, "checks": []}

        checks: list[dict[str, Any]] = []

        # Bureau score evidence (policy: >= 680).
        m = re.search(r"\bscore\b[^0-9\-]{0,15}(\d{3})\b", text)
        if m:
            score = int(m.group(1))
            checks.append(
                {
                    "name": "document_bureau_score_acceptable",
                    "ok": score >= 680,
                    "detail": f"document bureau score={score}",
                }
            )

        # Delinquencies in the trailing 12 months (policy: == 0). Anchor past the
        # optional "(12m)" qualifier so it is not mistaken for the count.
        m = re.search(r"delinquenc\w*\s*(?:\(?12\s*m\)?)?\s*[:\t ]\s*(\d+)", text)
        if m:
            delinq = int(m.group(1))
            checks.append(
                {
                    "name": "document_recent_delinquencies_clear",
                    "ok": delinq == 0,
                    "detail": f"document delinquencies_12m={delinq}",
                }
            )

        # Current ratio / liquidity evidence (policy: >= 1.0).
        m = re.search(r"current[ _]ratio[^0-9]{0,12}(\d+\.\d+)", text)
        if m:
            cr = float(m.group(1))
            checks.append(
                {
                    "name": "document_current_ratio_ok",
                    "ok": cr >= 1.0,
                    "detail": f"document current_ratio={cr}",
                }
            )

        # EBITDA evidence (policy: latest-year EBITDA / margin non-negative).
        neg_ebitda = bool(
            re.search(r"ebitda[^\n]{0,40}(turned negative|is negative|went negative|negative)", text)
            or re.search(r"ebitda[^a-z0-9]{0,12}[-(]\s?\d", text)
            or re.search(r"ebitda margin[^0-9\-]{0,8}-\s?\d", text)
        )
        if neg_ebitda:
            checks.append(
                {
                    "name": "document_ebitda_non_negative",
                    "ok": False,
                    "detail": "document financials evidence negative EBITDA",
                }
            )

        # Equity / solvency evidence (policy: positive book equity).
        neg_equity = bool(
            re.search(r"book equity[^\n]{0,24}[-(]\s?\d", text)
            or re.search(r"\bequity\b[^\n]{0,12}(-\s?\d|\(\s?\d)", text)
            or "negative equity" in text
            or "technically insolvent" in text
        )
        if neg_equity:
            checks.append(
                {
                    "name": "document_solvent",
                    "ok": False,
                    "detail": "document financials evidence negative book equity / insolvency",
                }
            )

        # DSCR evidence (policy: >= 1.25). Prefer an explicit sub-threshold value;
        # otherwise read a numeric DSCR and compare.
        if re.search(
            r"dscr[^\n]{0,30}(<\s*0|<\s?1\.2[0-4]|below 1\.25|far below 1\.25|coverage[^\n]{0,12}negative)",
            text,
        ):
            checks.append(
                {
                    "name": "document_dscr_meets_threshold",
                    "ok": False,
                    "detail": "document financials evidence DSCR below 1.25x",
                }
            )
        else:
            m = re.search(r"\bdscr\b[^0-9\-\n]{0,20}(-?\d+\.\d+)", text)
            if m:
                dscr = float(m.group(1))
                checks.append(
                    {
                        "name": "document_dscr_meets_threshold",
                        "ok": dscr >= 1.25,
                        "detail": f"document DSCR={dscr}",
                    }
                )

        return {"passed": all(c["ok"] for c in checks), "checks": checks}

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

        # --- Step 0: plan / orchestrate ------------------------------------
        # When ``use_foundry_workflows`` is on, the credit-memo **workflow agent**
        # drives the five child agents (and the HITL Question node) server-side.
        # Python remains the deterministic policy boundary: it still fetches tool
        # data for the gates, runs verification, and owns the AWAITING_APPROVAL
        # state machine below.
        wf = settings.use_foundry_workflows
        wf_handle: dict[str, Any] | None = None
        plan = [
            "doc_retrieval: gather approved-source context",
            "financial_ratio: compute + interpret ratios",
            "bureau_summary: summarize bureau report",
            "memo_assembler: assemble draft",
            "HITL: pause for human approval",
        ]
        if wf:
            # The workflow call is non-critical (Python computes the plan and runs
            # every gate deterministically below), so a workflow/preview error must
            # never fail the run — fall back to the in-process orchestrator agent.
            try:
                wf_result = invoke_workflow(
                    settings.foundry_credit_memo_workflow,
                    (
                        f"Draft an SME credit memo for applicant {applicant_id} using "
                        f"template {request.template_id}. Use your attached tools to "
                        f"retrieve documents, financials and bureau data, assemble the "
                        f"memo, then pause for human approval."
                        + (f"\n\nAttached credit file (excerpt):\n{doc_excerpt}" if doc_excerpt else "")
                    ),
                )
                wf_handle = {
                    "workflow": wf_result.workflow_name,
                    "response_id": wf_result.response_id,
                    "conversation_id": wf_result.conversation_id,
                }
                self._trace(
                    run,
                    step,
                    "memo_orchestrator",
                    "invoke_workflow",
                    inp={"workflow": wf_result.workflow_name, "applicant_id": applicant_id},
                    out={
                        "engine": "foundry_workflow",
                        "status": wf_result.status,
                        "awaiting_input": wf_result.awaiting_input,
                        "response_id": wf_result.response_id,
                        "mocked": wf_result.mocked,
                        "plan": plan,
                    },
                    note=f"Run orchestrated by Foundry workflow agent '{wf_result.workflow_name}'.",
                )
            except Exception as exc:  # noqa: BLE001 - workflow engine is non-critical
                wf = False
                wf_handle = None
                self._trace(
                    run,
                    step,
                    "memo_orchestrator",
                    "invoke_workflow",
                    inp={"workflow": settings.foundry_credit_memo_workflow, "applicant_id": applicant_id},
                    out={
                        "engine": "foundry_workflow",
                        "error": str(exc)[:300],
                        "fallback": "in_process_agents",
                        "plan": plan,
                    },
                    note="Foundry workflow invocation failed; fell back to in-process agent orchestration.",
                )
        if not wf:
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
            # Sensitivity pre-gate + DSPM event are governed catalog tools
            # (scope-checked, advertised in Foundry "Data & tools"). They run
            # in-process so the platform owns the block decision deterministically.
            label_result = registry.classify_document_sensitivity(
                dr_document.get("file_name", ""),
                dr_document.get("mime_type"),
                caller_agent="doc_retrieval",
            )
            event = registry.record_dspm_event(
                run_id=run.run_id,
                file_name=dr_document.get("file_name", ""),
                label_result=label_result,
                user=request.requested_by,
                use_case=USE_CASE,
                caller_agent="doc_retrieval",
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
        if not wf:
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
        _ratio_mock = (
            f"DSCR {ratios.get('dscr')}x, net debt/EBITDA {ratios.get('net_debt_to_ebitda')}x, "
            f"current ratio {ratios.get('current_ratio')}, EBITDA margin {ratios.get('ebitda_margin_pct')}%, "
            f"revenue CAGR {ratios.get('revenue_cagr_pct')}%."
        )
        if wf:
            # The financial-ratio agent was invoked server-side by the workflow.
            ratio_text = _ratio_mock
        else:
            ratio_text = self.agents["financial_ratio"].run_step(
                run_id=run.run_id,
                step=step,
                user_prompt=(
                    f"Analyse whether the financials support approve or reject for {applicant_id}. "
                    f"Computed ratios: {ratios}. "
                    + (f"Attached credit file (excerpt):\n{doc_excerpt}" if doc_excerpt else "No attached document text was provided.")
                ),
                mock_response=_ratio_mock,
            ).text
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
        _bureau_mock = (
            f"Bureau score {bureau.get('score')} ({bureau.get('score_band')}); "
            f"{bureau.get('delinquencies_12m')} delinquencies in 12m; {bureau.get('notes')}"
        )
        if wf:
            bureau_text = _bureau_mock
        else:
            bureau_text = self.agents["bureau_summary"].run_step(
                run_id=run.run_id,
                step=step,
                user_prompt=(
                    f"Assess whether the credit history supports approve or reject for {applicant_id}. "
                    f"Bureau report: {bureau}. "
                    + (f"Attached credit file (excerpt):\n{doc_excerpt}" if doc_excerpt else "No attached document text was provided.")
                ),
                mock_response=_bureau_mock,
            ).text
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
            ratio_text=ratio_text,
            bureau=bureau,
            bureau_text=bureau_text,
        )
        draft = registry.render_memo(
            sections=sections,
            template_id=request.template_id,
            caller_agent="memo_assembler",
        )
        run.draft_memo = draft
        draft_verification = self._verify_memo_draft(draft)
        # Analyse the financial EVIDENCE in the attached credit file (EBITDA,
        # DSCR, current ratio, bureau score, delinquencies, equity) against the
        # policy gates, so a case whose data breaches policy rejects even if the
        # dataset row would pass. The file's own recommendation is ignored.
        document_verification = self._verify_document(doc_content)
        approval_guidance = registry.evaluate_credit_policy(
            [
                retrieval_verification,
                ratios_verification,
                bureau_verification,
                draft_verification,
                document_verification,
            ],
            caller_agent="memo_assembler",
        )
        run.draft_memo["approval_guidance"] = approval_guidance
        if not wf:
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
        # The human-in-the-loop gate lives in the agent workflow: the
        # declarative ``Question`` node ('human_approval') in
        # credit_memo_workflow.yaml owns the pause when the Foundry workflow
        # engine is active. In that mode Python does NOT run an independent
        # approval gate — the workflow paused itself server-side at the node
        # (wf_handle.awaiting_input) and we only record AWAITING_APPROVAL so
        # the UI can deliver the reviewer's answer back to that node (see
        # approve()). In offline/mock mode the Python hitl_gateway is the HITL
        # transport so the demo and tests run without the workflow engine.
        step += 1
        pending = hitl_gateway.pause_for_approval(run.run_id, draft)
        hitl_owner = "agent_workflow_question_node" if wf_handle else "python_hitl_gateway"
        if wf_handle:
            # Persist the workflow resume handle so approve() can route the
            # reviewer's decision back into the workflow's HITL Question node.
            pending.metadata["workflow"] = wf_handle
        run.status = RunStatus.AWAITING_APPROVAL
        self._trace(
            run,
            step,
            "memo_orchestrator",
            "hitl_pause",
            out={
                "status": "awaiting_approval",
                "hitl_owner": hitl_owner,
                "hitl_node": "human_approval" if wf_handle else None,
                "workflow": (wf_handle or {}).get("workflow") if wf_handle else None,
                "channel": "agent_workflow" if wf_handle else "teams",
                "approval_guidance": approval_guidance,
            },
            note=(
                (
                    "Paused at the agent workflow HITL Question node 'human_approval' "
                    "(workflow owns the human-in-the-loop gate). "
                    if wf_handle
                    else "Human approval required. "
                )
                + f"Recommendation={approval_guidance['recommendation']} based on step verifications."
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

        pending = hitl_gateway.get(run_id)
        wf_handle = (pending.metadata.get("workflow") if pending else None) or None
        hitl_gateway.resume(run_id, decision)
        run.approval = decision
        step = len(run.steps)

        # When the Foundry workflow engine is active the HITL gate is the
        # workflow's ``Question`` node, so the reviewer's answer is delivered
        # TO that node and the declarative graph finalizes server-side. The
        # Python /approve endpoint is the transport the UI uses to reach the
        # node (the PoC has no separate Teams channel). The deterministic
        # *policy* reject-gate below is a separate governance guard (not HITL):
        # it prevents a human from force-approving a hard-reject case.
        if wf_handle:
            answer = "approve" if decision.approved else "reject"
            try:
                wf_res = resume_workflow(
                    wf_handle.get("workflow") or settings.foundry_credit_memo_workflow,
                    wf_handle.get("response_id"),
                    answer,
                    conversation_id=wf_handle.get("conversation_id"),
                )
                self._trace(
                    run,
                    step,
                    "memo_orchestrator",
                    "resume_workflow",
                    out={
                        "engine": "foundry_workflow",
                        "hitl_owner": "agent_workflow_question_node",
                        "hitl_node": "human_approval",
                        "decision": answer,
                        "status": wf_res.status,
                        "mocked": wf_res.mocked,
                    },
                    note=(
                        "Reviewer decision delivered to the agent workflow HITL Question "
                        "node 'human_approval'; the workflow drives finalization server-side."
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - workflow engine is non-critical
                self._trace(
                    run,
                    step,
                    "memo_orchestrator",
                    "resume_workflow",
                    out={
                        "engine": "foundry_workflow",
                        "decision": answer,
                        "error": str(exc)[:300],
                        "fallback": "in_process_finalization",
                    },
                    note="Foundry workflow resume failed; Python finalized the decision deterministically.",
                )
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
            # Record the reviewer's rejection at the HITL gate ...
            self._trace(
                run, step, "memo_orchestrator", "hitl_resume",
                status=StepStatus.BLOCKED,
                out={"approved": False, "reviewer": decision.reviewer, "comment": decision.comment},
                note="Human rejected draft.",
            )
            # ... then still run the final audited-memo commit so the DECLINED
            # outcome is logged to the audit ledger (Cosmos), exactly like an
            # approval. A reject is a decision that must be recorded, not a hole
            # in the trail.
            declined = dict(run.draft_memo or {})
            declined["status"] = "declined"
            declined["decision"] = "reject"
            declined["rejected_by"] = decision.reviewer
            if decision.comment:
                declined["reviewer_comment"] = decision.comment
            run.final_memo = declined
            run.status = RunStatus.REFUSED
            self._trace(
                run, len(run.steps), "memo_orchestrator", "finalize_memo",
                out={
                    "decision": "reject",
                    "status": "declined",
                    "reviewer": decision.reviewer,
                    "committed": True,
                },
                note="Rejected memo committed to the audit ledger (Cosmos) — decision logged.",
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
        guidance = registry.evaluate_credit_policy(
            [
                self._verify_doc_retrieval(retrieval_ctx, has_attachment=bool(request.dr_document)),
                self._verify_financials(ratios),
                self._verify_bureau(bureau),
                {"checks": []},
            ],
            caller_agent="memo_assembler",
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
