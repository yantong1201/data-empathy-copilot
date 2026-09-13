"""Assemble a schema-valid analysis object from rules/emotion/snapshot.

This is the shared contract filler for later Providers. It is not Qwen/Mock/RuleProvider.
"""

from __future__ import annotations

from typing import Any

from .analysis_id import make_analysis_id
from .emotion import evaluate_emotion
from .evidence import snapshot_inconsistency_schema_items
from .pack import load_pack
from .policy import policies_effective_at, policy_source_refs
from .rules import evaluate_risk

_FORBIDDEN_DRAFT = (
    "接触性皮炎",
    "这是过敏性",
    "确诊",
    "骗子",
    "24小时内电话回访",
    "1-3个工作日内到账",
    "一定退款",
    "保证赔偿",
)



def confirmed_facts(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    order = snapshot.get("order") or {}
    if order.get("visibility") == "visible":
        facts.append({
            "kind": "order_visible",
            "order_id": order.get("order_id"),
            "source_ref": order.get("source_ref"),
            "as_of_time": snapshot.get("as_of_time"),
        })
    wo = snapshot.get("workorder") or {}
    if wo.get("visibility") == "visible":
        facts.append({
            "kind": "workorder_visible",
            "workorder_id": wo.get("workorder_id"),
            "workorder_kind": wo.get("kind"),
            "create_time": wo.get("create_time"),
            "complete_time": wo.get("complete_time"),
            "status": (wo.get("status") or {}).get("snapshot_value"),
            "source_ref": wo.get("source_ref"),
            "as_of_time": snapshot.get("as_of_time"),
        })
    return facts


def _intent(snapshot: dict[str, Any]) -> dict[str, Any]:
    chat = snapshot.get("chat") or []
    major = None
    minor = None
    for row in chat:
        if row.get("scene_major"):
            major = row["scene_major"]
            minor = row.get("scene_minor") or "未细分"
            break
    if not major:
        return {"major": "未标注", "minor": "未标注", "confidence": 0.0}
    return {"major": major, "minor": minor or "未细分", "confidence": 0.5}


def _draft(risk: dict[str, Any], emotion: dict[str, Any], snapshot: dict[str, Any]) -> str:
    session = snapshot.get("session_id")
    missing = "、".join(risk.get("missing_fields") or []) or "无"
    if risk["type"] == "adverse_reaction" and risk["level"] == "P0":
        text = (
            "了解到您目前身体不适并已就医，请先遵医嘱。我这边只根据当前可见记录协助跟进，"
            "不能做医学诊断，也不能承诺退款、赔偿或回访时效。请人工确认下一步沟通口径。"
        )
    elif risk["type"] == "abnormal_refund":
        text = (
            "您反馈包裹异常、希望仅退款。当前还缺少外箱/面单/照片及出库或揽收重量，"
            "记录仍是待核实，不能认定欺诈或空包裹已证实，也不能直接退款。请配合补充证据，由人工确认。"
        )
    elif risk["type"] == "aftersales_damage":
        text = (
            "您反馈商品到手后存在破损。当前按售后换货方向处理，不推断物流或商家责任。"
            "请人工确认换货草稿后再发送。"
        )
    elif emotion.get("escalation") == "yes":
        text = "当前对话出现投诉升级表达。请人工确认安抚与升级口径，系统不会自动升级或发送。"
    else:
        text = "已根据当前时点可见记录整理事实与建议，回复发送前须人工确认。"
    if risk.get("status") == "needs_verification":
        text += f" 待核实字段：{missing}。"
    if snapshot.get("source_inconsistency"):
        text += " 客服声称已建单，但当前工单系统暂无记录，两处来源均保留。"
    for banned in _FORBIDDEN_DRAFT:
        text = text.replace(banned, "")
    _ = session
    return text


def _actions(risk: dict[str, Any]) -> list[str]:
    actions = ["人工确认后再发送"]
    if risk["type"] == "adverse_reaction":
        actions.append("收集就医/治疗与产品使用信息")
        actions.append("创建工单草稿（不自动建单）")
    if risk["type"] == "abnormal_refund":
        actions.append("收集外箱/面单/照片与重量证据")
    if risk["type"] == "aftersales_damage":
        actions.append("创建换货草稿（不自动建单）")
    if risk.get("status") == "needs_verification":
        actions.append("待核实，不升级为已确认 P0/P1")
    return actions


def assemble_analysis(
    snapshot: dict[str, Any],
    *,
    provider: str = "RuleProvider",
    model: str = "rules-v1",
    pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pack = pack or load_pack()
    emotion_full = evaluate_emotion(snapshot, pack)
    risk_full = evaluate_risk(snapshot, pack, emotion_full)
    policies = policies_effective_at(snapshot["as_of_time"], pack)
    analysis_id = make_analysis_id(snapshot, provider=provider, model=model, pack=pack)
    inconsistency = snapshot_inconsistency_schema_items(snapshot)
    emotion = {
        "negative_signal": emotion_full["negative_signal"],
        "escalation": emotion_full["escalation"],
        "evidence_refs": emotion_full["evidence_refs"],
    }
    risk = {
        "type": risk_full["type"],
        "level": risk_full["level"],
        "status": risk_full["status"],
        "rule_ids": risk_full["rule_ids"],
        "why": risk_full["why"],
        "why_not": risk_full["why_not"] or ["当前结论边界已在命中规则中说明"],
    }
    source_refs = list(snapshot.get("source_refs") or [])
    for ref in emotion["evidence_refs"] + risk_full["evidence_refs"] + policy_source_refs(policies):
        if ref not in source_refs:
            source_refs.append(ref)
    payload = {
        "session_id": snapshot["session_id"],
        "message_no": int(snapshot["message_no"]),
        "as_of_time": snapshot["as_of_time"],
        "analysis_id": analysis_id,
        "intent": _intent(snapshot),
        "emotion": emotion,
        "risk": risk,
        "facts": confirmed_facts(snapshot),
        "source_inconsistency": inconsistency,
        "missing_fields": list(risk_full.get("missing_fields") or []),
        "reply_draft": _draft(risk_full, emotion_full, snapshot),
        "recommended_actions": _actions(risk_full),
        "needs_human_confirmation": True,
        "source_refs": source_refs,
    }
    return {
        "analysis": payload,
        "emotion_full": emotion_full,
        "risk_full": risk_full,
        "policies": [row["policy_id"] for row in policies],
        "provider": provider,
        "model": model,
    }
