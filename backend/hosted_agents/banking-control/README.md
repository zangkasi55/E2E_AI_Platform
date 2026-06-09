# SCBX UC2 — Banking Control (Foundry hosted agent)

The UC2 conversational-banking control flow packaged as a **Microsoft Foundry
hosted agent** (Microsoft Agent Framework + `responses` protocol). It runs the
same reasoning chain as the declarative `banking-control-workflow`, with a
**deterministic over-limit human-in-the-loop (HITL) gate**:

```
intake → ekyc → bank-query → banking-controller → judgement
       → policy_gate → human_approval_gate → transaction_handoff
```

The four LLM agents reason about the request; `policy_gate` makes the
authoritative over-limit decision (policy `SCBX-RETAIL-XFER-001`, default
**1,500 THB** per transaction). When a transfer **exceeds** the limit the agent
escalates to an authorized banker instead of self-approving — no money moves.

## Files

| File | Purpose |
| --- | --- |
| `main.py` | Agent Framework workflow graph + `ResponsesHostServer` entrypoint |
| `agent.yaml` | Hosted-agent deploy spec (`kind: hosted`, responses 1.0.0) |
| `agent.manifest.yaml` | Catalog/template manifest + model resource binding |
| `Dockerfile` | Container image (`python:3.12-slim`, port 8088) |
| `requirements.txt` | `agent-framework`, `agent-framework-foundry-hosting`, … |
| `.env.example` | Local env template (copy to `.env`) |

## Run locally

```powershell
cd "backend/hosted_agents/banking-control"
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # then fill FOUNDRY_PROJECT_ENDPOINT
python main.py                # serves the responses protocol on :8088
```

## Deploy to Foundry

Authenticate first (`az login`), set the env vars from `.env.example`, then from
this folder run the Foundry agent deploy (builds the image, pushes to ACR, and
registers the hosted agent):

```powershell
cd "backend/hosted_agents/banking-control"
az login
azd up        # or: af agent deploy   (per your Foundry CLI)
```

> Deploy publishes to shared Foundry/ACR infrastructure. Run it only when you
> intend to push the agent live.
