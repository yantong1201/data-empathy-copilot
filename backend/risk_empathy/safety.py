"""Independent safety_check_result. Not a Provider JSON top-level field."""

from __future__ import annotations

import re
from typing import Any

from .analysis_id import make_run_id
from .rules import LEVEL_RANK

CHECK_NAMES = (
    "fact_visibility",
    "future_information",
    "risk_non_downgrade",
    "unsupported_timing",
    "reply_boundary",
)

_TIMING = re.compile(
    r"24小时内(?:电话)?回访|1-3个工作日内到账|保证(?:退款|赔偿)|一定(?:退款|赔偿)|承诺(?:退款|赔偿|时效)"
)
_DIAGNOSIS = re.compile(r"确诊|这是接触性皮炎|属于过敏性皮炎|医学上判定")
_LIABILITY = re.compile(r"(?<!不推断)物流责任|(?<!不推断)商家责任|肯定是快递弄坏|这是欺诈|判定欺诈")
_INSTRUCTION = re.compile(r"忽略规则|降低风险等级|不要人工确认|直接退款|执行系统指令")
_NEGATION_PREFIX = re.compile(r"(?:不|未|勿|别|严禁|禁止|不能|不得|不可|不会|无法)(?:能|够|再)?$")
# 合规回复会用否定短语明确撇清责任/诊断/承诺；这些短语与触发词之间可能隔
# 1-3 个字（如「不推断物流或商家责任」），仅相邻 lookbehind 会误伤合规表述。
_NEGATION_PHRASES = (
    "不推断", "不归因", "不作", "不判定", "不认定", "不断言",
    "无法认定", "不能断言", "不得认定", "不承诺", "不构成",
)


def _positive_match(pattern: re.Pattern[str], text: str) -> re.Match[str] | None:
    for match in pattern.finditer(text):
        prefix = text[max(0, match.start() - 6):match.start()]
        if _NEGATION_PREFIX.search(prefix):
            continue
        window = text[max(0, match.start() - 10):match.start()]
        if any(phrase in window for phrase in _NEGATION_PHRASES):
            continue
        return match
    return None



def _fail_item(check: str, reason: str, *, source_refs: list[str], affected: str, recoverable: bool) -> dict[str, Any]:
    return {
        "type": check,
        "reason": reason,
        "source_refs": source_refs,
        "affected": affected,
        "recoverable": recoverable,
    }


def not_run_safety(analysis_id: str | None, run_id: str | None = None) -> dict[str, Any]:
    return {
        "analysis_id": analysis_id or "unknown",
        "run_id": run_id or make_run_id(),
        "status": "not_run",
        "executed": False,
        "checks": {},
        "failures": [
            _fail_item(
                "not_run",
                "五项安全检查未运行，不得伪装为 pass，不得作为人工确认依据",
                source_refs=[],
                affected="safety_check_result",
                recoverable=True,
            )
        ],
        "can_be_human_confirmation_basis": False,
    }


def evaluate_safety(
    analysis: dict[str, Any],
    snapshot: dict[str, Any],
    rule_risk: dict[str, Any],
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or make_run_id()
    analysis_id = analysis.get("analysis_id") or "unknown"
    failures: list[dict[str, Any]] = []
    checks: dict[str, str] = {name: "pass" for name in CHECK_NAMES}

    visible_refs = set(snapshot.get("source_refs") or [])
    for row in snapshot.get("chat") or []:
        visible_refs.add(row.get("source_ref"))
    order = snapshot.get("order") or {}
    if order.get("source_ref"):
        visible_refs.add(order["source_ref"])
    wo = snapshot.get("workorder") or {}
    if wo.get("visibility") == "visible" and wo.get("source_ref"):
        visible_refs.add(wo["source_ref"])

    for i, fact in enumerate(analysis.get("facts") or []):
        if not isinstance(fact, dict):
            checks["fact_visibility"] = "fail"
            failures.append(_fail_item("fact_visibility", "facts 项不是对象", source_refs=[], affected=f"facts[{i}]", recoverable=False))
            continue
        ref = fact.get("source_ref")
        if ref and ref not in visible_refs:
            checks["fact_visibility"] = "fail"
            failures.append(_fail_item(
                "fact_visibility",
                f"事实来源当前时点不可见: {ref}",
                source_refs=[ref],
                affected=f"facts[{i}]",
                recoverable=False,
            ))
        if fact.get("kind") in {"pending_candidate", "unverified_empty_package", "fraud"}:
            checks["fact_visibility"] = "fail"
            failures.append(_fail_item(
                "fact_visibility",
                "待核实候选或冲突不得写入 facts",
                source_refs=[ref] if ref else [],
                affected=f"facts[{i}]",
                recoverable=False,
            ))

    leak_tokens = []
    hidden_wo = snapshot.get("workorder") or {}
    if hidden_wo.get("visibility") != "visible":
        store_id = hidden_wo.get("workorder_id")
        # Snapshot already hides future ids; still scan reply for leaked identifiers in provider output.
    reply = analysis.get("reply_draft") or ""
    blob = reply + " " + str(analysis.get("facts"))
    if "未来工单" in blob or "提前完结" in blob:
        leak_tokens.append("future_marker")
    # If analysis cites a workorder_id that is not visible in snapshot:
    cited_wo = re.findall(r"\b(?:BLFY|KOC|BH|WL)\d+\b", blob)
    visible_wo_id = wo.get("workorder_id") if wo.get("visibility") == "visible" else None
    for token in cited_wo:
        if token != visible_wo_id:
            leak_tokens.append(token)
    if leak_tokens:
        checks["future_information"] = "fail"
        failures.append(_fail_item(
            "future_information",
            f"疑似泄漏当前不可见工单或未来信息: {leak_tokens}",
            source_refs=[],
            affected="reply_draft",
            recoverable=False,
        ))

    provider_level = (analysis.get("risk") or {}).get("level")
    rule_level = rule_risk.get("level")
    rule_status = rule_risk.get("status")
    if rule_status == "confirmed" and rule_level in {"P0", "P1"}:
        if LEVEL_RANK.get(provider_level, 99) > LEVEL_RANK.get(rule_level, 99):
            checks["risk_non_downgrade"] = "fail"
            failures.append(_fail_item(
                "risk_non_downgrade",
                f"Provider 将规则确定的 {rule_level} 降为 {provider_level}",
                source_refs=list((analysis.get("risk") or {}).get("rule_ids") or []),
                affected="risk.level",
                recoverable=False,
            ))

    if _positive_match(_TIMING, reply):
        checks["unsupported_timing"] = "fail"
        failures.append(_fail_item(
            "unsupported_timing",
            "回复含无依据的退款/赔偿/处理时效承诺",
            source_refs=[],
            affected="reply_draft",
            recoverable=True,
        ))

    if _positive_match(_DIAGNOSIS, reply) or _positive_match(_LIABILITY, reply) or _positive_match(_INSTRUCTION, reply):
        checks["reply_boundary"] = "fail"
        reason = "回复越界"
        if _positive_match(_DIAGNOSIS, reply):
            reason = "回复含医学诊断"
        elif _positive_match(_LIABILITY, reply):
            reason = "回复含无依据定责"
        elif _positive_match(_INSTRUCTION, reply):
            reason = "回复把业务文本当作指令或要求绕过规则"
        failures.append(_fail_item(
            "reply_boundary",
            reason,
            source_refs=[],
            affected="reply_draft",
            recoverable=True,
        ))


    status = "fail" if any(v == "fail" for v in checks.values()) else "pass"
    return {
        "analysis_id": analysis_id,
        "run_id": run_id,
        "status": status,
        "executed": True,
        "checks": checks,
        "failures": failures,
        "can_be_human_confirmation_basis": status == "pass",
    }


def can_enter_human_confirmation(
    *,
    schema_valid: bool,
    safety: dict[str, Any],
) -> bool:
    if not schema_valid:
        return False
    if not safety.get("executed"):
        return False
    if safety.get("status") != "pass":
        return False
    if not safety.get("can_be_human_confirmation_basis"):
        return False
    return True
