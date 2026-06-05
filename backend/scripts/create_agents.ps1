$ErrorActionPreference = 'Continue'
$ep = "https://agpoc-aifoundry-dev.services.ai.azure.com/api/projects/agpoc-proj-dev/agents?api-version=2025-05-15-preview"
$tmp = Join-Path $env:TEMP "agbody.json"
$agents = @(
  @{ name = "memo-orchestrator"; model = "gpt-4o"; instr = "You are the UC1 Credit Memo orchestrator for an SME lending workflow. You plan and coordinate four sub-agents in order: doc-retrieval, financial-ratio, bureau-summary, memo-assembler, to draft an SME credit memo grounded only on approved sources. You NEVER finalize a memo without explicit human approval; the assembled draft must pause for a human-in-the-loop decision. Use only synthetic/provided data. Be concise, auditable, and never fabricate figures." },
  @{ name = "doc-retrieval"; model = "gpt-4o-mini"; instr = "You retrieve and ground statements on approved sources only for an SME credit memo. Use only approved synthetic sources; never fabricate. Return grounded findings with source references." },
  @{ name = "financial-ratio"; model = "gpt-4o-mini"; instr = "You interpret computed financial ratios for a credit audience. Explain liquidity, leverage, and coverage ratios plainly. Never invent figures; use only provided synthetic financials." },
  @{ name = "bureau-summary"; model = "gpt-4o-mini"; instr = "You summarize a credit-bureau report into risk-relevant findings for an SME credit decision. Highlight delinquencies, utilization, and risk flags from provided synthetic data only." },
  @{ name = "memo-assembler"; model = "gpt-4o"; instr = "You assemble section bodies into a coherent draft SME credit memo. Produce a structured draft only; the memo is never final without explicit human approval. Use only synthetic/provided content." },
  @{ name = "banking-controller"; model = "gpt-4o"; instr = "You decompose a banking request into intents and slots. You NEVER move money; the only terminal action is a transaction handoff object for a human or downstream system to execute. Use only synthetic data and deterministic guardrails." }
)
foreach ($a in $agents) {
  $body = @{ name = $a.name; definition = @{ kind = "prompt"; model = $a.model; instructions = $a.instr; temperature = 0.2 } } | ConvertTo-Json -Depth 6
  Set-Content -Path $tmp -Value $body -Encoding utf8
  Write-Output "== POST $($a.name) ($($a.model)) =="
  az rest --method post --url $ep --resource "https://ai.azure.com" --headers "Content-Type=application/json" --body "@$tmp" --query "{id:id, name:name, model:definition.model, kind:definition.kind}" -o json 2>&1 | Select-Object -First 12
}
Remove-Item $tmp -ErrorAction SilentlyContinue
