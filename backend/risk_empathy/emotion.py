"""Observable emotion signals only: negative_signal and escalation."""

from __future__ import annotations

from typing import Any

from .evidence import (
    complaint_threats,
    complaint_withdrawals,
    efficiency_softens,
    negative_buyer_quotes,
    plan_accepts,
)
from .pack import load_pack


def evaluate_emotion(snapshot: dict[str, Any], pack: dict[str, Any] | None = None) -> dict[str, Any]:
    pack = pack or load_pack()
    constraints = pack["emotion"]
    threats = complaint_threats(snapshot)
    withdrawals = complaint_withdrawals(snapshot)
    softens = efficiency_softens(snapshot)
    accepts = plan_accepts(snapshot)
    negatives = negative_buyer_quotes(snapshot)

    history: list[dict[str, Any]] = []
    for item in threats:
        history.append({
            "kind": "complaint_threat",
            "source_ref": item["source_ref"],
            "quote": item["quote"],
            "message_no": item["message_no"],
            "current": False,
        })
    for item in withdrawals:
        history.append({
            "kind": "complaint_withdrawn",
            "source_ref": item["source_ref"],
            "quote": item["quote"],
            "message_no": item["message_no"],
            "current": False,
        })
    for item in softens:
        history.append({
            "kind": "service_progress_soften",
            "source_ref": item["source_ref"],
            "quote": item["quote"],
            "message_no": item["message_no"],
            "current": False,
        })

    if not threats:
        escalation = "no"
    else:
        last_threat_no = max(int(item["message_no"]) for item in threats if item["message_no"] is not None)
        later_withdraw = any(int(item["message_no"]) > last_threat_no for item in withdrawals if item["message_no"] is not None)
        later_soften = any(int(item["message_no"]) > last_threat_no for item in softens if item["message_no"] is not None)
        later_accept = any(int(item["message_no"]) > last_threat_no for item in accepts if item["message_no"] is not None)
        if later_withdraw or later_soften or later_accept:
            escalation = "no"
        else:
            escalation = "yes"
            for event in history:
                if event["kind"] == "complaint_threat" and event["message_no"] == last_threat_no:
                    event["current"] = True

    if not (snapshot.get("chat") or []):
        negative_signal = "unclear"
    elif negatives or threats:
        negative_signal = "present"
    else:
        negative_signal = "none"

    evidence_refs: list[str] = []
    for item in negatives + threats + withdrawals + softens:
        ref = item["source_ref"]
        if ref not in evidence_refs:
            evidence_refs.append(ref)

    return {
        "negative_signal": negative_signal,
        "escalation": escalation,
        "evidence_refs": evidence_refs,
        "history": history,
        "allowed_signals": constraints["signals"],
        "note": "Observable service signals only; not a psychological diagnosis.",
    }
