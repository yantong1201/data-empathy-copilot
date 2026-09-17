"""Scoped analysis assembly for eval arms (chat-only / snapshot / rules-only).

Wraps the Phase B assembler with an explicit intent override and accepts
pre-computed risk/emotion so each evaluation arm controls its own information
scope without touching Phase A/B contracts.
"""

from __future__ import annotations

from typing import Any

from backend.risk_empathy.assemble import assemble_analysis
from backend.risk_empathy.pack import load_pack


def scoped_analysis(
    snapshot: dict[str, Any],
    risk_full: dict[str, Any],
    emotion_full: dict[str, Any],
    *,
    provider: str,
    model: str,
    pack: dict[str, Any] | None = None,
    intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pack = pack or load_pack()
    bundled = assemble_analysis(snapshot, provider=provider, model=model, pack=pack)
    payload = bundled["analysis"]
    if intent:
        payload["intent"] = {
            "major": intent.get("major") or payload["intent"]["major"],
            "minor": intent.get("minor") or payload["intent"]["minor"],
            "confidence": intent.get("confidence")
            if isinstance(intent.get("confidence"), (int, float))
            else payload["intent"]["confidence"],
        }
    payload["risk"] = {
        "type": risk_full.get("type", payload["risk"]["type"]),
        "level": risk_full.get("level", payload["risk"]["level"]),
        "status": risk_full.get("status", payload["risk"]["status"]),
        "rule_ids": risk_full.get("rule_ids", payload["risk"]["rule_ids"]),
        "why": risk_full.get("why") or payload["risk"]["why"],
        "why_not": risk_full.get("why_not") or payload["risk"]["why_not"],
    }
    payload["emotion"] = {
        "negative_signal": emotion_full.get("negative_signal", payload["emotion"]["negative_signal"]),
        "escalation": emotion_full.get("escalation", payload["emotion"]["escalation"]),
        "evidence_refs": emotion_full.get("evidence_refs") or payload["emotion"]["evidence_refs"],
    }
    payload["missing_fields"] = list(risk_full.get("missing_fields") or payload.get("missing_fields") or [])
    return payload
