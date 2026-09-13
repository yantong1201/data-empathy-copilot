"""Illegal Provider JSON: schema check → limited repair → RuleProvider/human/reject."""

from __future__ import annotations

import copy
from typing import Any

from .analysis_id import make_run_id
from .schema_validate import validate_provider_json
from .safety import can_enter_human_confirmation, evaluate_safety, not_run_safety

PROVIDERS = ("QwenProvider", "MockProvider", "RuleProvider")


def _limited_repair(payload: Any) -> tuple[Any, dict[str, Any]]:
    actions: list[str] = []
    changed_facts = False
    lowered_risk = False
    added_sources = False
    hid_missing = False
    if not isinstance(payload, dict):
        return payload, {
            "attempted": True,
            "actions": ["reject_non_object"],
            "changed_facts": False,
            "lowered_risk": False,
            "added_sources": False,
            "hid_missing_fields": False,
            "result": "failed",
        }
    out = copy.deepcopy(payload)
    if "run_id" in out:
        del out["run_id"]
        actions.append("strip_run_id")
    if "safety_check_result" in out:
        del out["safety_check_result"]
        actions.append("strip_safety_check_result")
    if out.get("needs_human_confirmation") is not True:
        out["needs_human_confirmation"] = True
        actions.append("force_needs_human_confirmation_true")
    if isinstance(out.get("message_no"), str) and out["message_no"].isdigit():
        out["message_no"] = int(out["message_no"])
        actions.append("coerce_message_no_int")
    risk = out.get("risk")
    if isinstance(risk, dict):
        for key in ("why", "why_not", "rule_ids"):
            if isinstance(risk.get(key), str):
                risk[key] = [risk[key]]
                actions.append(f"wrap_risk.{key}_string_as_array")
    for key in ("facts", "source_inconsistency", "missing_fields", "recommended_actions", "source_refs"):
        if key not in out:
            out[key] = []
            actions.append(f"fill_empty_{key}")
            if key == "source_refs":
                added_sources = False
            if key == "missing_fields":
                hid_missing = False
    emotion = out.get("emotion")
    if isinstance(emotion, dict) and "evidence_refs" not in emotion:
        emotion["evidence_refs"] = []
        actions.append("fill_empty_emotion.evidence_refs")
    allowed = {
        "session_id", "message_no", "as_of_time", "analysis_id", "intent", "emotion",
        "risk", "facts", "source_inconsistency", "missing_fields", "reply_draft",
        "recommended_actions", "needs_human_confirmation", "source_refs",
    }
    extra = [key for key in list(out.keys()) if key not in allowed]
    for key in extra:
        del out[key]
        actions.append(f"strip_additional_{key}")
    if not actions:
        result = "not_needed"
        attempted = False
    else:
        attempted = True
        result = "repaired"
    return out, {
        "attempted": attempted,
        "actions": actions,
        "changed_facts": changed_facts,
        "lowered_risk": lowered_risk,
        "added_sources": added_sources,
        "hid_missing_fields": hid_missing,
        "result": result,
    }


def process_provider_output(
    original: Any,
    *,
    provider: str = "unknown",
    snapshot: dict[str, Any] | None = None,
    rule_risk: dict[str, Any] | None = None,
    run_safety: bool = True,
    pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if provider not in PROVIDERS:
        provider_name = provider if provider in PROVIDERS else "unknown"
    else:
        provider_name = provider
    run_id = make_run_id()
    before = validate_provider_json(original, pack)
    repaired = original
    repair_meta = {
        "attempted": False,
        "actions": [],
        "changed_facts": False,
        "lowered_risk": False,
        "added_sources": False,
        "hid_missing_fields": False,
        "result": "not_needed",
    }
    if not before["valid"]:
        repaired, repair_meta = _limited_repair(original)
        after = validate_provider_json(repaired, pack)
        if not after["valid"]:
            repair_meta["result"] = "failed"
            analysis_id = repaired.get("analysis_id") if isinstance(repaired, dict) else None
            record = {
                "run_id": run_id,
                "analysis_id": analysis_id,
                "provider": provider_name,
                "schema_valid_before": False,
                "schema_errors": before["errors"],
                "repair": repair_meta,
                "schema_valid_after": False,
                "fallback": {
                    "target": "RuleProvider" if provider_name != "RuleProvider" else "human",
                    "reason": "Schema 非法且有限修复失败；转 RuleProvider 或人工处理，不用静态默认答案",
                },
                "can_enter_human_confirmation": False,
                "original_output": original,
                "repaired_output": repaired,
                "safety_check_result": not_run_safety(analysis_id, run_id),
            }
            return record
    else:
        after = before
        repaired = original

    analysis_id = repaired.get("analysis_id") if isinstance(repaired, dict) else None
    if run_safety and snapshot is not None and rule_risk is not None and isinstance(repaired, dict):
        safety = evaluate_safety(repaired, snapshot, rule_risk, run_id=run_id)
    else:
        safety = not_run_safety(analysis_id, run_id)

    schema_ok = after["valid"]
    confirm = can_enter_human_confirmation(schema_valid=schema_ok, safety=safety)
    if not schema_ok:
        fallback_target = "RuleProvider" if provider_name != "RuleProvider" else "human"
        fallback_reason = "Schema 仍非法"
    elif not confirm:
        fallback_target = "reject_confirmation"
        fallback_reason = "安全校验失败或未运行，不得进入人工确认"
    else:
        fallback_target = "none"
        fallback_reason = "schema 与安全校验均通过，仍须人工确认业务动作"

    return {
        "run_id": run_id,
        "analysis_id": analysis_id,
        "provider": provider_name,
        "schema_valid_before": before["valid"],
        "schema_errors": before["errors"],
        "repair": repair_meta,
        "schema_valid_after": after["valid"],
        "fallback": {"target": fallback_target, "reason": fallback_reason},
        "can_enter_human_confirmation": confirm,
        "original_output": original,
        "repaired_output": repaired,
        "safety_check_result": safety,
    }
