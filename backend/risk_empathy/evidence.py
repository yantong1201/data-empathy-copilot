"""Evidence extractors from a Phase A snapshot.

These are service-context predicates, not standalone keyword→risk upgrades.
Hospital/doctor tokens are ignored unless the current visible conversation
supports a medical-care reading (or are suppressed as consultation).
"""

from __future__ import annotations

import re
from typing import Any

BUYER_ROLES = frozenset({"买家"})
AGENT_ROLES = frozenset({"客服"})

_CONSULT_PREGNANCY = re.compile(r"孕妇能用|怀孕|产检医生|孕期")
_CONSULT_INGREDIENT = re.compile(r"维A酸|水杨酸|成分")
_ASK_DOCTOR = re.compile(r"问下医生|问一下医生|给产检医生看|给.{0,6}医生看|医生确认后使用")

_ADVERSE = re.compile(
    r"过敏|红肿|刺痛|发红|疹子|瘙痒|有点痒|爆痘|闷痘|致痘|不适|接触性皮炎|脸肿"
)
_PRODUCT_USE = re.compile(r"用了|用了你们|用了几|用了面膜|用了精华|用了面霜|用了眼霜")

_HOSPITAL_NOW = re.compile(r"我人现在在医院|现在在医院")
_HOSPITAL_VISIT = re.compile(r"去医院挂了|挂了皮肤科|今天去医院|再跑一趟医院")
_TREATMENT = re.compile(r"门诊病历|医生诊断|医生开了|氯雷他定|遵医嘱")
_DOCTOR_SAID_DX = re.compile(r"医生说是接触性皮炎")

_AGENT_SUGGEST_HOSPITAL = re.compile(r"请及时就医|建议.{0,8}就医")

_EMPTY_PKG = re.compile(r"里面是空的|空包裹|货都没有|空的")
_REFUND_ONLY = re.compile(r"仅退款")
_ABNORMAL_REASON = re.compile(r"空包裹|待核实|异常仅退款|仅退款-空包裹")

_DAMAGE = re.compile(r"泵头是坏的|按不出来|到手破损|包装破损|破损部位|收到的.{0,12}坏")
_AGENT_DAMAGE = re.compile(r"确认属包装破损|破损换货|到手破损|登记换货")

_COMPLAINT = re.compile(r"走12315|投诉到平台|直接投诉|12315")
_WITHDRAW = re.compile(r"不投诉了")
_SOFTEN_EFF = re.compile(r"处理效率还行")
_ACCEPT_PLAN = re.compile(r"^(那个，)?能|可以，动作快点|行，那就这么办|好，等钱到账")

_NEGATIVE = re.compile(
    r"太坑了|真的服了|服了|必须给我个说法|急|差太多|坑老客户|空的|"
    r"过敏|红肿|坏的|少发|投诉|12315|骗你|钱要定了|破规则"
)

_REPEAT = re.compile(r"第二次进线|之前就联系过|又来找你们|重复进线")

_LOGISTICS_ISSUE = re.compile(r"物流停滞|签收未收到|拦截改址|货物短少|货物破损|丢件")


def buyer_messages(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in snapshot.get("chat") or [] if row.get("role") in BUYER_ROLES]


def agent_messages(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in snapshot.get("chat") or [] if row.get("role") in AGENT_ROLES]


def visible_text(row: dict[str, Any]) -> str:
    return row.get("message_text") or ""


def ref_of(row: dict[str, Any]) -> str:
    return row.get("source_ref") or f"chat:{row.get('session_id')}:{row.get('message_no')}"


def is_pregnancy_consult(snapshot: dict[str, Any]) -> bool:
    texts = [visible_text(row) for row in snapshot.get("chat") or []]
    joined = "\n".join(texts)
    if not _CONSULT_PREGNANCY.search(joined):
        return False
    if _ADVERSE.search(joined) and (_HOSPITAL_NOW.search(joined) or _HOSPITAL_VISIT.search(joined)):
        return False
    return bool(_CONSULT_INGREDIENT.search(joined) or _ASK_DOCTOR.search(joined) or "孕妇能用" in joined)


def quotes(rows: list[dict[str, Any]], pattern: re.Pattern[str]) -> list[dict[str, str]]:
    found = []
    for row in rows:
        text = visible_text(row)
        if pattern.search(text):
            found.append({"source_ref": ref_of(row), "quote": text, "message_no": row.get("message_no")})
    return found


def adverse_reaction_described(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    if is_pregnancy_consult(snapshot):
        return []
    found = []
    for row in buyer_messages(snapshot):
        text = visible_text(row)
        if _ADVERSE.search(text) and (_PRODUCT_USE.search(text) or _ADVERSE.search(text)):
            if _CONSULT_PREGNANCY.search(text) and not (_HOSPITAL_NOW.search(text) or _HOSPITAL_VISIT.search(text)):
                continue
            found.append({"source_ref": ref_of(row), "quote": text, "message_no": row.get("message_no")})
    return found


def medical_care_evidence(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Buyer medical-care evidence in current service context. Not doctor-consult keywords."""
    if is_pregnancy_consult(snapshot):
        return []
    ar = adverse_reaction_described(snapshot)
    ar_present = bool(ar)
    found: list[dict[str, str]] = []
    for row in buyer_messages(snapshot):
        text = visible_text(row)
        if _ASK_DOCTOR.search(text) and not (_HOSPITAL_NOW.search(text) or _HOSPITAL_VISIT.search(text)):
            continue
        hit = False
        if _HOSPITAL_NOW.search(text) and (ar_present or _ADVERSE.search(text)):
            hit = True
        if _HOSPITAL_VISIT.search(text) and (ar_present or _ADVERSE.search(text) or "皮肤科" in text):
            hit = True
        if _DOCTOR_SAID_DX.search(text) and (ar_present or _HOSPITAL_VISIT.search(text)):
            hit = True
        if _TREATMENT.search(text) and ar_present:
            hit = True
        if hit:
            found.append({"source_ref": ref_of(row), "quote": text, "message_no": row.get("message_no")})
    wo = snapshot.get("workorder") or {}
    if wo.get("visibility") == "visible" and wo.get("kind") == "adverse_reaction":
        fields = wo.get("fields") or {}
        if fields.get("sought_medical_care") == "是" and found:
            found.append({
                "source_ref": wo.get("source_ref") or f"workorder:{wo.get('workorder_id')}",
                "quote": f"sought_medical_care={fields.get('sought_medical_care')}",
                "message_no": None,
            })
    return found


def consultation_doctor_mentions(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    found = []
    for row in snapshot.get("chat") or []:
        text = visible_text(row)
        if _ASK_DOCTOR.search(text) or "产检医生" in text:
            found.append({"source_ref": ref_of(row), "quote": text, "message_no": row.get("message_no")})
    return found


def complaint_threats(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    return quotes(buyer_messages(snapshot), _COMPLAINT)


def complaint_withdrawals(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    return quotes(buyer_messages(snapshot), _WITHDRAW)


def efficiency_softens(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    return quotes(buyer_messages(snapshot), _SOFTEN_EFF)


def plan_accepts(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    found = []
    for row in buyer_messages(snapshot):
        text = visible_text(row).strip()
        if _ACCEPT_PLAN.search(text) or text.startswith("那个，能") or "等钱到账就行" in text:
            found.append({"source_ref": ref_of(row), "quote": text, "message_no": row.get("message_no")})
    return found


def empty_package_claims(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    found = quotes(buyer_messages(snapshot), _EMPTY_PKG)
    if not found:
        found = quotes(buyer_messages(snapshot), _REFUND_ONLY)
        found = [item for item in found if "空" in item["quote"] or "不退货" in item["quote"] or "货都没有" in item["quote"]]
    return quotes(buyer_messages(snapshot), _EMPTY_PKG) or [
        item for item in quotes(buyer_messages(snapshot), _REFUND_ONLY)
        if any(token in item["quote"] for token in ("空", "货都没有", "不退货"))
    ]


def abnormal_refund_record(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    wo = snapshot.get("workorder") or {}
    if wo.get("visibility") != "visible":
        return None
    fields = wo.get("fields") or {}
    reason = str(fields.get("return_reason") or "")
    advice = str(fields.get("receive_advice") or "")
    package_type = str(fields.get("package_type") or "")
    abnormal = str(fields.get("is_abnormal") or "")
    if wo.get("kind") == "aftersale_return" and (
        _ABNORMAL_REASON.search(reason + advice + package_type) or abnormal == "是" and "空包裹" in reason
    ):
        return {
            "source_ref": wo.get("source_ref"),
            "is_abnormal": abnormal,
            "return_reason": reason,
            "package_type": package_type,
            "pending_registration": "待核实" in reason or "核实" in advice or package_type == "风控核实",
        }
    return None


def refund_weight_or_photo_evidence(snapshot: dict[str, Any]) -> dict[str, bool]:
    """Structured business evidence. Chat asking for photos is not proof they exist."""
    wo = snapshot.get("workorder") or {}
    fields = wo.get("fields") if wo.get("visibility") == "visible" else {}
    fields = fields or {}
    has_weight = bool(fields.get("outbound_weight") or fields.get("pickup_weight") or fields.get("weight"))
    has_box = bool(fields.get("outer_box_photo") or fields.get("box_photo"))
    has_waybill = bool(fields.get("waybill_photo") or fields.get("face_sheet_photo"))
    has_photos = bool(fields.get("package_photos") or fields.get("inner_photos"))
    return {
        "outer_box": has_box,
        "waybill": has_waybill,
        "photos": has_photos,
        "weight": has_weight,
    }


def received_damage_described(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    return quotes(buyer_messages(snapshot), _DAMAGE)


def aftersales_damage_support(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    found = quotes(agent_messages(snapshot), _AGENT_DAMAGE)
    wo = snapshot.get("workorder") or {}
    if wo.get("visibility") == "visible" and wo.get("kind") == "reship_exchange":
        fields = wo.get("fields") or {}
        reason = str(fields.get("aftersale_reason") or "")
        subtype = str(fields.get("workorder_subtype") or "")
        if "破损" in reason or subtype == "换货":
            if "破损" in reason or received_damage_described(snapshot):
                found.append({
                    "source_ref": wo.get("source_ref"),
                    "quote": reason or subtype,
                    "message_no": None,
                })
    return found


def logistics_exception_record(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    logistics = snapshot.get("logistics") or {}
    wo_part = logistics.get("logistics_workorder")
    if wo_part:
        issue = str((wo_part.get("fields") or {}).get("issue_type") or "")
        if issue:
            return {
                "source_ref": wo_part.get("source_ref"),
                "issue_type": issue,
            }
    wo = snapshot.get("workorder") or {}
    if wo.get("visibility") == "visible" and wo.get("kind") == "logistics":
        fields = wo.get("fields") or {}
        issue = str(fields.get("issue_type") or "")
        if issue and _LOGISTICS_ISSUE.search(issue):
            return {"source_ref": wo.get("source_ref"), "issue_type": issue}
    return None


def unresolved_workorder(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    wo = snapshot.get("workorder") or {}
    if wo.get("visibility") != "visible":
        return None
    status = (wo.get("status") or {}).get("snapshot_value")
    completion = wo.get("completion") or {}
    if status == "not_completed" or completion.get("snapshot_value") == "not_completed":
        return {
            "source_ref": wo.get("source_ref"),
            "workorder_id": wo.get("workorder_id"),
            "kind": wo.get("kind"),
            "create_time": wo.get("create_time"),
            "complete_time": wo.get("complete_time"),
            "status": status,
        }
    return None


def locatable_repeat_contact(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Require an explicit current-event locator. Nickname similarity is ignored."""
    return quotes(buyer_messages(snapshot), _REPEAT)


def negative_buyer_quotes(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    return quotes(buyer_messages(snapshot), _NEGATIVE)


def agent_suggested_hospital_only(snapshot: dict[str, Any]) -> bool:
    if medical_care_evidence(snapshot):
        return False
    return bool(quotes(agent_messages(snapshot), _AGENT_SUGGEST_HOSPITAL))


def snapshot_inconsistency_schema_items(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for raw in snapshot.get("source_inconsistency") or []:
        items.append({
            "kind": raw.get("kind"),
            "source_refs": list(raw.get("source_refs") or []),
            "as_of_time": raw.get("as_of_time"),
            "summary": raw.get("summary"),
        })
    return items
