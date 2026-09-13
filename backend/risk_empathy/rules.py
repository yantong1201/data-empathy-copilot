"""Evaluate versioned risk rules against a Phase A snapshot."""

from __future__ import annotations

from typing import Any

from .emotion import evaluate_emotion
from .evidence import (
    abnormal_refund_record,
    aftersales_damage_support,
    adverse_reaction_described,
    agent_suggested_hospital_only,
    consultation_doctor_mentions,
    empty_package_claims,
    locatable_repeat_contact,
    logistics_exception_record,
    medical_care_evidence,
    received_damage_described,
    refund_weight_or_photo_evidence,
    snapshot_inconsistency_schema_items,
    unresolved_workorder,
)
from .pack import load_pack

P0_TYPES = frozenset({"adverse_reaction", "complaint_escalation"})
P1_TYPES = frozenset({"abnormal_refund"})
LEVEL_RANK = {"P0": 0, "P1": 1, "P2": 2, "待定级": 3}


def _rule_map(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["rule_id"]: row for row in pack["rules"]["rules"]}


def _hit(
    spec: dict[str, Any],
    *,
    level: str,
    status: str,
    why: list[str],
    why_not: list[str],
    evidence_refs: list[str],
    missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": spec["rule_id"],
        "risk_type": spec["risk_type"],
        "level": level,
        "status": status,
        "priority": spec["priority"],
        "why": why,
        "why_not": why_not,
        "evidence_refs": evidence_refs,
        "missing_fields": missing_fields or [],
        "version": spec["version"],
        "source": spec["source"],
        "demo_rule": spec.get("demo_rule", True),
    }


def _eval_ar(snapshot: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any] | None:
    described = adverse_reaction_described(snapshot)
    care = medical_care_evidence(snapshot)
    consult = consultation_doctor_mentions(snapshot)
    if not described and not care:
        return None
    refs = [item["source_ref"] for item in described + care]
    if described and care:
        quotes = "；".join(item["quote"] for item in described[:2])
        why = [spec["why_template"].format(evidence=quotes)]
        why_not = [
            "不作医学诊断，不承诺因果",
            "工单不可见不影响已可见就医自述" if (snapshot.get("workorder") or {}).get("visibility") != "visible" else "当前工单可见但不改变已确认就医证据",
        ]
        return _hit(spec, level="P0", status="confirmed", why=why, why_not=why_not, evidence_refs=refs)
    missing = list(spec["missing_fields_when_pending"])
    if described and not care:
        why = ["命中 R-AR-001 候选：买家描述不良反应，但当前无就医/治疗证据，不能确认 P0"]
        why_not = [spec["why_not_boundary"]]
        if consult:
            why_not.append("出现医生/产检医生咨询语义，不构成就医证据")
        if agent_suggested_hospital_only(snapshot):
            why_not.append("客服建议及时就医不是买家就医证据")
        return _hit(
            spec,
            level="待定级",
            status="needs_verification",
            why=why,
            why_not=why_not,
            evidence_refs=refs,
            missing_fields=missing,
        )
    return None


def _eval_comp(snapshot: dict[str, Any], spec: dict[str, Any], emotion: dict[str, Any]) -> dict[str, Any] | None:
    from .evidence import complaint_threats

    threats = complaint_threats(snapshot)
    if not threats:
        return None
    if emotion.get("escalation") != "yes":
        return None
    refs = [item["source_ref"] for item in threats] + list(emotion.get("evidence_refs") or [])
    why = [spec["why_template"].format(evidence=threats[-1]["quote"])]
    return _hit(spec, level="P0", status="confirmed", why=why, why_not=[spec["why_not_boundary"]], evidence_refs=refs)



def _eval_refund(snapshot: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any] | None:
    claims = empty_package_claims(snapshot)
    record = abnormal_refund_record(snapshot)
    if not claims and not record:
        return None
    proofs = refund_weight_or_photo_evidence(snapshot)
    refs = [item["source_ref"] for item in claims]
    if record:
        refs.append(record["source_ref"])
    missing = [name for flag, name in (
        (proofs["outer_box"], "外箱照片"),
        (proofs["waybill"], "面单照片"),
        (proofs["photos"], "内件照片"),
        (proofs["weight"], "出库/揽收重量"),
    ) if not flag]
    complete = not missing
    if complete and record and not record.get("pending_registration"):
        why = [spec["why_template"].format(evidence="当前可见业务记录已具备异常退款确认证据")]
        return _hit(spec, level="P1", status="confirmed", why=why, why_not=[], evidence_refs=refs)
    evidence_bits = []
    if claims:
        evidence_bits.append(claims[0]["quote"])
    if record:
        evidence_bits.append(f"工单登记 is_abnormal={record.get('is_abnormal')} reason={record.get('return_reason')}")
    why = [spec["why_template"].format(evidence="；".join(evidence_bits))]
    why_not = [
        spec["why_not_boundary"],
        "不得把异常=是解释为欺诈或已证实空包裹",
    ]
    if missing:
        why_not.append("缺少：" + "、".join(missing))
    return _hit(
        spec,
        level="待定级",
        status="needs_verification",
        why=why,
        why_not=why_not,
        evidence_refs=refs,
        missing_fields=missing or list(spec["missing_fields_when_pending"]),
    )


def _eval_repeat(snapshot: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any] | None:
    found = locatable_repeat_contact(snapshot)
    if not found:
        return None
    why = [spec["why_template"].format(evidence=found[0]["quote"])]
    return _hit(
        spec,
        level="P2",
        status="confirmed",
        why=why,
        why_not=[spec["why_not_boundary"]],
        evidence_refs=[item["source_ref"] for item in found],
    )


def _eval_logi(snapshot: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any] | None:
    record = logistics_exception_record(snapshot)
    if not record:
        return None
    if received_damage_described(snapshot) and (snapshot.get("workorder") or {}).get("kind") == "reship_exchange":
        return None
    why = [spec["why_template"].format(evidence=record.get("issue_type"))]
    return _hit(
        spec,
        level="P2",
        status="confirmed",
        why=why,
        why_not=[spec["why_not_boundary"]],
        evidence_refs=[record["source_ref"]],
    )


def _eval_damage(snapshot: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any] | None:
    described = received_damage_described(snapshot)
    if not described:
        return None
    support = aftersales_damage_support(snapshot)
    refs = [item["source_ref"] for item in described + support]
    if support:
        why = [spec["why_template"].format(evidence=described[0]["quote"])]
        return _hit(
            spec,
            level="P2",
            status="confirmed",
            why=why,
            why_not=[spec["why_not_boundary"]],
            evidence_refs=refs,
        )
    return _hit(
        spec,
        level="待定级",
        status="needs_verification",
        why=["命中 R-DAMAGE-001 候选：买家描述到手破损，当前可见售后/换货证据不足"],
        why_not=[spec["why_not_boundary"]],
        evidence_refs=refs,
        missing_fields=list(spec["missing_fields_when_pending"]),
    )


def _eval_wo(snapshot: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any] | None:
    record = unresolved_workorder(snapshot)
    if not record:
        return None
    why = [spec["why_template"].format(evidence=f"{record['workorder_id']} status={record['status']}")]
    return _hit(
        spec,
        level="P2",
        status="confirmed",
        why=why,
        why_not=[spec["why_not_boundary"]],
        evidence_refs=[record["source_ref"]],
        missing_fields=[],
    )


def _merge(hits: list[dict[str, Any]], snapshot: dict[str, Any], specs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    typed = [hit for hit in hits if hit["rule_id"] not in {"R-NONE-001", "R-UNCLEAR-001"}]


    confirmed_p0 = [hit for hit in typed if hit["level"] == "P0" and hit["status"] == "confirmed"]
    confirmed_p1 = [hit for hit in typed if hit["level"] == "P1" and hit["status"] == "confirmed"]
    pending_p0_p1 = [
        hit for hit in typed
        if hit["status"] == "needs_verification" and hit["risk_type"] in (P0_TYPES | P1_TYPES)
    ]
    confirmed_p2 = [hit for hit in typed if hit["level"] == "P2" and hit["status"] == "confirmed"]

    selected: list[dict[str, Any]]
    if confirmed_p0:
        selected = typed
        primary = sorted(confirmed_p0, key=lambda h: -h["priority"])[0]
    elif confirmed_p1:
        selected = typed
        primary = sorted(confirmed_p1, key=lambda h: -h["priority"])[0]
    elif pending_p0_p1:
        selected = typed
        primary = sorted(pending_p0_p1, key=lambda h: -h["priority"])[0]
    elif confirmed_p2:
        selected = typed
        primary = sorted(confirmed_p2, key=lambda h: -h["priority"])[0]
    elif typed:
        selected = typed
        primary = sorted(typed, key=lambda h: (LEVEL_RANK[h["level"]], -h["priority"]))[0]
    else:
        inconsistency = snapshot_inconsistency_schema_items(snapshot)
        unclear_spec = specs["R-UNCLEAR-001"]
        none_spec = specs["R-NONE-001"]
        wo = snapshot.get("workorder") or {}
        if inconsistency and wo.get("visibility") != "visible":
            primary = _hit(
                unclear_spec,
                level="待定级",
                status="needs_verification",
                why=[unclear_spec["why_template"]],
                why_not=["来源冲突未裁决，不能据此升级风险", "工单创建前为 no_workorder，不得标成未解决工单"],
                evidence_refs=[ref for item in inconsistency for ref in item.get("source_refs") or []],
                missing_fields=["工单当前是否可见"],
            )
            selected = [primary]
        else:
            primary = _hit(
                none_spec,
                level="P2",
                status="confirmed",
                why=[none_spec["why_template"]],
                why_not=[none_spec["why_not_boundary"]],
                evidence_refs=[],
            )
            selected = [primary]

    why: list[str] = []
    why_not: list[str] = []
    missing: list[str] = []
    refs: list[str] = []
    for hit in selected:
        for line in hit["why"]:
            if line not in why:
                why.append(line)
        for line in hit["why_not"]:
            if line not in why_not:
                why_not.append(line)
        for field in hit["missing_fields"]:
            if field not in missing:
                missing.append(field)
        for ref in hit["evidence_refs"]:
            if ref and ref not in refs:
                refs.append(ref)

    if primary["level"] in {"P0", "P1"} and primary["status"] == "confirmed":
        why_not = [line for line in why_not if "降级" not in line]
        why_not.append("已由规则确定的 P0/P1 不得因情绪缓和、模型置信度或后续工单缺失而降级")

    return {
        "type": primary["risk_type"],
        "level": primary["level"],
        "status": primary["status"],
        "rule_ids": [hit["rule_id"] for hit in selected],
        "why": why or ["当前可见证据支持所命中规则"],
        "why_not": why_not,
        "missing_fields": missing,
        "evidence_refs": refs,
        "hits": selected,
        "primary_rule_id": primary["rule_id"],
    }


def evaluate_risk(snapshot: dict[str, Any], pack: dict[str, Any] | None = None, emotion: dict[str, Any] | None = None) -> dict[str, Any]:
    pack = pack or load_pack()
    emotion = emotion or evaluate_emotion(snapshot, pack)
    specs = _rule_map(pack)
    hits: list[dict[str, Any]] = []
    for rule_id, fn in (
        ("R-AR-001", lambda spec: _eval_ar(snapshot, spec)),
        ("R-COMP-001", lambda spec: _eval_comp(snapshot, spec, emotion)),
        ("R-REFUND-001", lambda spec: _eval_refund(snapshot, spec)),
        ("R-REPEAT-001", lambda spec: _eval_repeat(snapshot, spec)),
        ("R-LOGI-001", lambda spec: _eval_logi(snapshot, spec)),
        ("R-DAMAGE-001", lambda spec: _eval_damage(snapshot, spec)),
        ("R-WO-001", lambda spec: _eval_wo(snapshot, spec)),
    ):
        hit = fn(specs[rule_id])
        if hit is not None:
            hits.append(hit)
    merged = _merge(hits, snapshot, specs)
    merged["rules_version"] = pack["versions"]["rules_version"]
    merged["emotion_escalation"] = emotion["escalation"]
    merged["emotion_negative_signal"] = emotion["negative_signal"]
    return merged
