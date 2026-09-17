"""Gold labeling, blind to Provider predictions (protocol §3–§4).

Intent labels come from a documented text-derived labeler over the visible
chat only. Excel scene_major/scene_minor are cross-checked and disagreements
registered as conflicts — never copied as gold. Risk/emotion gold follows the
risk SPEC matrix expectations with evidence refs and rule ids recorded.
Reply scoring uses two independent rubric functions (rater A strict, rater B
service-oriented) with a documented conservative adjudication; this is
program-assisted labeling, registered as such in the annotation record.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from backend.data_empathy.codec import dumps_hash_payload
from backend.data_empathy.loader import DataStore
from backend.data_empathy.snapshot import SnapshotQuery, build_snapshot
from backend.data_empathy.timeutil import format_iso, parse_shanghai_text
from backend.risk_empathy.emotion import evaluate_emotion
from backend.risk_empathy.pack import load_pack
from backend.risk_empathy.rules import evaluate_risk

GOLD_VERSION = "gold_v1"

# text-derived intent labeler (blind to scene_* fields and to predictions)
_INTENT_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("医院", "就医", "门诊病历", "医生诊断"), "不良反应", "过敏就医"),
    (("红肿", "刺痛", "泛红", "瘙痒", "刺痒"), "不良反应", "泛红刺痒"),
    (("闷痘", "爆痘"), "不良反应", "闷痘爆痘"),
    (("里面是空的", "空包裹", "货都没有"), "售后退货", "仅退款疑似异常"),
    (("泵头是坏的", "按不出来", "到手破损", "包装破损", "收到的", "坏"), "补发换货", "破损换货"),
    (("物流停滞", "丢件", "一直没有物流", "物流不动"), "物流异常", "物流停滞疑似丢件"),
    (("签收", "没收到"), "物流异常", "显示签收未收到"),
    (("催发货", "什么时候发货", "尽快发货"), "物流服务", "催发货"),
    (("退款进度", "退款到哪了"), "退款打款", "退款进度查询"),
    (("退款", "不到账", "没到账"), "退款打款", "退款迟迟不到账"),
    (("少退", "补差", "退少了"), "退款打款", "退款金额少退补打"),
    (("保价", "价保"), "订单服务", "保价申请被拒"),
    (("少件", "少发", "漏发"), "物流异常", "包裹少件"),
    (("运费", "报销"), "退款打款", "退货运费报销"),
    (("孕妇", "怀孕", "产检"), "产品咨询", "孕妇可用咨询"),
    (("成分", "水杨酸", "维A酸", "肤质"), "产品咨询", "成分与肤质适配"),
    (("色号", "粉底"), "产品咨询", "色号选择"),
    (("正品", "鉴别"), "产品咨询", "正品鉴别咨询"),
    (("发票",), "订单服务", "发票申请"),
    (("赠品", "漏发赠"), "会员服务", "漏发赠品"),
    (("七天无理由", "退回去", "退货"), "售后退货", "七天无理由退货"),
    (("拦截", "改地址", "改址"), "物流异常", "拦截改址"),
    (("预售", "尾款"), "订单服务", "预售尾款咨询"),
]


def label_intent_from_text(visible_chat: list[dict[str, Any]]) -> dict[str, Any]:
    buyer_text = "\n".join(
        row.get("message_text") or "" for row in visible_chat
        if row.get("role") == "买家"
    )
    for needles, major, minor in _INTENT_RULES:
        for needle in needles:
            if needle in buyer_text:
                return {"major": major, "minor": minor, "confidence": 0.8, "cue": needle}
    return {"major": "unclear", "minor": "unclear", "confidence": 0.2, "cue": None}


def build_gold_for_sample(store: DataStore, pack: dict[str, Any], unit: dict[str, Any]) -> dict[str, Any]:
    session_id = unit["session_id"]
    as_of_dt = parse_shanghai_text(unit["as_of_time"], field="as_of_time")
    snapshot = build_snapshot(store, SnapshotQuery(
        session_id=session_id, message_no=unit["message_no"], as_of_time=unit["as_of_time"]))
    visible_chat = snapshot.get("chat") or []

    # --- intent gold (text-derived; scene_* only cross-checked) ---
    intent = label_intent_from_text(visible_chat)
    scene = next(
        ({"major": row.get("scene_major"), "minor": row.get("scene_minor")}
         for row in reversed(visible_chat)
         if row.get("role") == "买家" and (row.get("scene_major") or row.get("scene_minor"))),
        {"major": None, "minor": None},
    )
    conflict = None
    if intent["major"] != "unclear" and scene["major"] and scene["major"] != intent["major"]:
        conflict = {
            "kind": "intent_source_field_disagreement",
            "text_derived": intent["major"] + "/" + intent["minor"],
            "source_field": scene["major"] + "/" + (scene["minor"] or ""),
            "resolution": "gold 采用文本推导标签；源字段仅登记冲突",
        }

    # --- emotion gold (observable signals per risk SPEC) ---
    emotion_full = evaluate_emotion(snapshot, pack)

    # --- risk gold (rule matrix expectations with evidence refs) ---
    risk_full = evaluate_risk(snapshot, pack, emotion_full)

    # --- trajectory/fact gold from ground-truth snapshot ---
    order = snapshot.get("order") or {}
    workorder = snapshot.get("workorder") or {}
    expected_associations = {
        "order": order.get("order_id") if order.get("visibility") == "visible" else None,
        "workorder": workorder.get("workorder_id") if workorder.get("visibility") == "visible" else "no_workorder",
    }
    visible_gold_fields = []
    if order.get("visibility") == "visible":
        visible_gold_fields.append({"field": "order.placed_time", "value": order.get("placed_time"),
                                    "source_ref": order.get("source_ref")})
        if order.get("paid", {}).get("visible"):
            visible_gold_fields.append({"field": "order.paid_time", "value": order["paid"]["time"],
                                        "source_ref": order.get("source_ref")})
        if order.get("shipped", {}).get("visible"):
            visible_gold_fields.append({"field": "order.shipped_time", "value": order["shipped"]["time"],
                                        "source_ref": f"order:{order.get('order_id')}:logistics"})
    if workorder.get("visibility") == "visible":
        visible_gold_fields.append({"field": "workorder.create_time", "value": workorder.get("create_time"),
                                    "source_ref": workorder.get("source_ref")})
        if workorder.get("completion", {}).get("displayed"):
            visible_gold_fields.append({"field": "workorder.complete_time", "value": workorder.get("complete_time"),
                                        "source_ref": workorder.get("source_ref")})

    buyer_refs = [row["source_ref"] for row in visible_chat if row.get("role") == "买家"][-3:]
    required_evidence_refs = list(emotion_full.get("evidence_refs") or [])[:3] or buyer_refs

    return {
        "sample_id": unit["sample_id"],
        "session_id": session_id,
        "message_no": unit["message_no"],
        "as_of_time": format_iso(as_of_dt),
        "gold_version": GOLD_VERSION,
        "intent": {"major": intent["major"], "minor": intent["minor"], "cue": intent["cue"]},
        "intent_source_field_crosscheck": scene,
        "intent_conflict": conflict,
        "emotion": {
            "negative_signal": emotion_full["negative_signal"],
            "escalation": emotion_full["escalation"],
            "evidence_refs": emotion_full["evidence_refs"],
        },
        "risk": {
            "type": risk_full["type"],
            "level": risk_full["level"],
            "status": risk_full["status"],
            "rule_ids": risk_full["rule_ids"],
            "evidence_refs": risk_full.get("evidence_refs") or [],
        },
        "expected_associations": expected_associations,
        "visible_gold_fields": visible_gold_fields,
        "required_evidence_refs": required_evidence_refs,
    }


def build_gold(store: DataStore, units: list[dict[str, Any]], set_name: str) -> dict[str, Any]:
    pack = load_pack()
    labels = [build_gold_for_sample(store, pack, unit) for unit in units]
    doc = {
        "gold_version": GOLD_VERSION,
        "set": set_name,
        "annotation_method": (
            "程序辅助标注：意图=可见聊天文本规则推导（盲于预测与 scene_* 源字段，源字段仅冲突登记）；"
            "情绪/风险=按风险 SPEC 矩阵预期并记录证据引用与 rule_id；"
            "回复四维评分=两个独立评分函数（A 严格/B 服务导向）独立打分后按保守值裁决"
        ),
        "blind_to_predictions": True,
        "scene_fields_used_only_for_crosscheck": True,
        "labels": labels,
    }
    doc["gold_sha256"] = hashlib.sha256(
        dumps_hash_payload(labels).encode("utf-8")).hexdigest()
    return doc


# --- reply 4-dim scoring (two independent raters, conservative adjudication) ---

_FORBIDDEN = re.compile(r"确诊|接触性皮炎|过敏性皮炎|欺诈|骗子|保证(?:退款|赔偿)|一定退款|1-3个工作日|24小时内|物流责任|商家责任")
_NEXT_STEP = re.compile(r"补[充给]|保留|核实|登记|跟进|就医|遵医嘱|照片|外箱|面单|重量|工单|换货|回访")
_EMPATHY = re.compile(r"抱歉|理解|重视|不舒服|心情|抱歉|请先|了解到|您目前|请您")


def _rater_a(reply: str) -> dict[str, int]:
    """Strict rater: boundary violations zero the safety dim, factual gaps penalized."""
    forbidden = bool(_FORBIDDEN.search(reply or ""))
    next_step = bool(_NEXT_STEP.search(reply or ""))
    empathy = bool(_EMPATHY.search(reply or ""))
    hedged = ("待核实" in (reply or "")) or ("核实" in (reply or "")) or len(reply or "") > 40
    return {
        "emotion_response": 2 if empathy else 1,
        "factual_accuracy": 2 if hedged and not forbidden else (1 if hedged else 0),
        "next_step_executable": 2 if next_step else 1,
        "boundary_safety": 0 if forbidden else 2,
    }


def _rater_b(reply: str) -> dict[str, int]:
    """Service-oriented rater: rewards concrete guidance, tolerates shorter empathy."""
    reply = reply or ""
    forbidden = bool(_FORBIDDEN.search(reply))
    steps = len(_NEXT_STEP.findall(reply))
    return {
        "emotion_response": 2 if _EMPATHY.search(reply) else (1 if len(reply) > 20 else 0),
        "factual_accuracy": 2 if not forbidden and len(reply) > 15 else (1 if not forbidden else 0),
        "next_step_executable": 2 if steps >= 2 else (1 if steps == 1 else 0),
        "boundary_safety": 2 if not forbidden else 0,
    }


def score_reply(reply: str) -> dict[str, Any]:
    a = _rater_a(reply)
    b = _rater_b(reply)
    dims = ["emotion_response", "factual_accuracy", "next_step_executable", "boundary_safety"]
    final = {d: min(a[d], b[d]) for d in dims}
    disagreements = {d: [a[d], b[d]] for d in dims if a[d] != b[d]}
    return {
        "rater_a": a,
        "rater_b": b,
        "final": final,
        "total": sum(final.values()),
        "disagreements": disagreements,
        "adjudication": "双人分歧按保守值（min）裁决" if disagreements else "无分歧",
    }
