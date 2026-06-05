"""Microsoft Purview sensitivity-label resolution for the credit-memo gate.

Given an uploaded document's metadata (file name / mime type), resolve the
Microsoft Purview / Information Protection sensitivity label that governs it,
and decide whether the credit-memo agent is allowed to ingest it.

Resolution strategy:
  * MOCK_MODE (default): look the file up in the synthetic Purview catalog
    (``data/credit_memo/sensitivity_labels.json``); fall back to a filename
    keyword heuristic that mirrors how Purview auto-labeling tags documents.
  * Live mode: query Microsoft Purview via the Purview SDK
    (``azure-purview-datamap`` / Information Protection). The SDK call is lazily
    imported and, on any failure, degrades gracefully to the same heuristic so
    the gate always fails *closed* on clearly-sensitive names.

Labels ``Confidential`` and ``Highly Confidential`` are blocked from ingestion.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from ..config import settings

# MIP-style labels, ordered most → least sensitive. Order matters for the
# heuristic because "highly confidential" also contains "confidential".
LABEL_HIGHLY_CONFIDENTIAL = "Highly Confidential"
LABEL_CONFIDENTIAL = "Confidential"
LABEL_GENERAL = "General"
LABEL_PUBLIC = "Public"

# Default labels blocked from agent ingestion (overridable via settings).
DEFAULT_BLOCKED_LABELS = (LABEL_CONFIDENTIAL, LABEL_HIGHLY_CONFIDENTIAL)

_LABEL_COLORS = {
    LABEL_HIGHLY_CONFIDENTIAL: "#a4262c",
    LABEL_CONFIDENTIAL: "#d83b01",
    LABEL_GENERAL: "#107c10",
    LABEL_PUBLIC: "#605e5c",
}


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    """Load the synthetic Purview catalog (file_name -> label)."""
    path = settings.data_path / "credit_memo" / "sensitivity_labels.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"labels": {}, "blocked_labels": list(DEFAULT_BLOCKED_LABELS)}


def blocked_labels() -> set[str]:
    configured = getattr(settings, "purview_blocked_labels", None)
    if configured:
        return {str(x).strip() for x in configured if str(x).strip()}
    catalog_blocked = _catalog().get("blocked_labels") or list(DEFAULT_BLOCKED_LABELS)
    return {str(x).strip() for x in catalog_blocked}


def _heuristic_label(file_name: str) -> dict[str, Any]:
    """Approximate Purview auto-labeling from a file name only."""
    name = (file_name or "").lower()
    if any(k in name for k in ("highly confidential", "highly-confidential", "restricted", "top secret", "top-secret")):
        label = LABEL_HIGHLY_CONFIDENTIAL
        full = "Highly Confidential \\ Board & Legal"
    elif "confidential" in name:
        label = LABEL_CONFIDENTIAL
        full = "Confidential \\ Restricted"
    elif "internal" in name:
        label = LABEL_GENERAL
        full = "General \\ Internal Business"
    else:
        label = LABEL_GENERAL
        full = "General \\ Internal Business"
    return {
        "label": label,
        "label_id": f"heuristic-{label.lower().replace(' ', '-')}",
        "full_name": full,
        "color": _LABEL_COLORS.get(label, "#605e5c"),
        "protected": label in (LABEL_CONFIDENTIAL, LABEL_HIGHLY_CONFIDENTIAL),
        "source": "purview_auto_labeling_heuristic",
    }


def _live_label(file_name: str) -> dict[str, Any] | None:
    """Resolve the label from Microsoft Purview in live mode (best-effort).

    Uses the Purview SDK + managed identity. Returns ``None`` on any failure so
    the caller falls back to the catalog/heuristic and the gate fails closed.
    """
    if settings.mock_mode or not settings.purview_catalog_endpoint:
        return None
    try:  # pragma: no cover - exercised only in live mode
        from azure.identity import DefaultAzureCredential
        from azure.purview.datamap import DataMapClient  # type: ignore

        client = DataMapClient(
            endpoint=settings.purview_catalog_endpoint,
            credential=DefaultAzureCredential(),
        )
        # The data-plane search returns catalog assets whose classifications /
        # sensitivity labels are surfaced via Purview Information Protection.
        results = client.discovery.query(body={"keywords": file_name, "limit": 1})
        for asset in (results or {}).get("value", []):
            labels = asset.get("sensitivityLabels") or asset.get("classification") or []
            for lbl in labels:
                name = lbl.get("name") if isinstance(lbl, dict) else str(lbl)
                if name:
                    return {
                        "label": name,
                        "label_id": (lbl.get("id") if isinstance(lbl, dict) else "") or "",
                        "full_name": name,
                        "color": _LABEL_COLORS.get(name, "#605e5c"),
                        "protected": name in (LABEL_CONFIDENTIAL, LABEL_HIGHLY_CONFIDENTIAL),
                        "source": "purview_information_protection",
                    }
        return None
    except Exception:  # pragma: no cover - PoC best-effort
        return None


def resolve_sensitivity_label(file_name: str, mime_type: str | None = None) -> dict[str, Any]:
    """Resolve the Purview sensitivity label and ingestion decision for a file.

    Returns a dict with: ``label``, ``label_id``, ``full_name``, ``color``,
    ``protected``, ``source``, ``blocked`` (bool) and ``justification`` (str).
    """
    catalog = _catalog().get("labels", {})
    resolved: dict[str, Any] | None = None

    # 1) Live Purview lookup (no-op in mock).
    resolved = _live_label(file_name)
    # 2) Synthetic catalog (exact file-name match).
    if resolved is None and file_name in catalog:
        resolved = dict(catalog[file_name])
    # 3) Filename heuristic fallback.
    if resolved is None:
        resolved = _heuristic_label(file_name)

    label = resolved.get("label", LABEL_GENERAL)
    blocked = label in blocked_labels()
    if blocked:
        justification = (
            f"Microsoft Purview classified this file as '{resolved.get('full_name', label)}'. "
            "Files labeled Confidential or Highly Confidential are blocked from agent "
            "ingestion by the credit-memo data-loss-prevention policy."
        )
    else:
        justification = (
            f"Microsoft Purview label '{resolved.get('full_name', label)}' permits agent "
            "ingestion for credit-memo drafting."
        )

    return {
        "file_name": file_name,
        "mime_type": mime_type,
        "label": label,
        "label_id": resolved.get("label_id", ""),
        "full_name": resolved.get("full_name", label),
        "color": resolved.get("color", _LABEL_COLORS.get(label, "#605e5c")),
        "protected": bool(resolved.get("protected", blocked)),
        "source": resolved.get("source", "purview_auto_labeling_heuristic"),
        "blocked": blocked,
        "justification": justification,
    }
