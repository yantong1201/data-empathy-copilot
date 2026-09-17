"""Protocol §6 metrics: macro-F1, trajectory, facts, citation, P0/P1 recall,
reply 4-dim, unclear coverage, safety coverage, cost stats, error attribution.

Formulas live here only as direct implementations of the protocol text; every
metric reports n/k numerator/denominator and support alongside the value.
"""

from __future__ import annotations

import re
from typing import Any

from .datasets import SCENE_MAJORS, SCENE_MINORS
from .gold import score_reply

ERROR_TYPES = (
    "missing_fact", "wrong_join", "wrong_intent", "wrong_emotion_signal",
    "wrong_risk_level", "unsupported_claim", "unsafe_reply",
    "unnecessary_escalation", "future_information_leak",
    "unnecessary_known_identifier_question", "missing_safety_check",
)

_LEVEL_RANK = {"P0": 0, "P1": 1, "P2": 2, "待定级": 3}


def _prf(preds: list[str], golds: list[str], labels: list[str]) -> dict[str, dict[str, float]]:
    per: dict[str, dict[str, float]] = {}
    for label in labels:
        tp = sum(1 for p, g in zip(preds, golds) if p == label and g == label)
        fp = sum(1 for p, g in zip(preds, golds) if p == label and g != label)
        fn = sum(1 for p, g in zip(preds, golds) if p != label and g == label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per[label] = {"precision": precision, "recall": recall, "f1": f1, "support": fn + tp}
    return per


def intent_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for level, labels, name in (
        ("major", SCENE_MAJORS, "intent_major_macro_f1"),
        ("minor", SCENE_MINORS, "intent_minor_macro_f1"),
    ):
        golds, preds = [], []
        for row in rows:
            gold = row["gold"]["intent"][level]
            pred = row["pred"]["analysis"]["intent"][level]
            golds.append(gold)
            preds.append(pred)
        per = _prf(preds, golds, list(labels))
        covered_labels = [label for label in labels if per[label]["support"] > 0]
        macro = sum(per[label]["f1"] for label in covered_labels) / len(covered_labels) if covered_labels else 0.0
        out[name] = {
            "value": round(macro, 4),
            "n": len(rows),
            "k_classes_with_support": len(covered_labels),
            "classes_with_support": covered_labels,
            "formula": "对有 gold support 的类别分别计算 P/R/F1 后取未加权平均；预测 unclear 不参与",
            "per_class": per,
        }
    non_unclear = [row for row in rows if row["pred"]["analysis"]["intent"]["major"] != "unclear"]
    out["unclear_coverage"] = {
        "value": round(len(non_unclear) / len(rows), 4) if rows else 0.0,
        "n": len(rows),
        "k_non_unclear": len(non_unclear),
    }
    correct_covered = [
        row for row in non_unclear
        if row["pred"]["analysis"]["intent"]["major"] == row["gold"]["intent"]["major"]
        or (row["gold"]["intent"]["major"] == "unclear" and row["pred"]["analysis"]["intent"]["major"] == "unclear")
    ]
    out["covered_strict_accuracy"] = {
        "value": round(len(correct_covered) / len(non_unclear), 4) if non_unclear else 0.0,
        "n": len(non_unclear),
        "k_correct": len(correct_covered),
    }
    return out


def trajectory_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = 0
    exact = 0
    for row in rows:
        gold = row["gold"]["expected_associations"]
        facts = row["pred"]["analysis"].get("facts") or []
        pred_order = next((f.get("order_id") for f in facts if f.get("kind") == "order_visible"), None)
        pred_wo = next((f.get("workorder_id") for f in facts if f.get("kind") == "workorder_visible"), None)
        for kind, gold_v, pred_v in (
            ("order", gold["order"], pred_order),
            ("workorder", gold["workorder"], pred_wo if pred_wo else "no_workorder"),
        ):
            total += 1
            if gold_v == pred_v:
                exact += 1
            elif kind == "workorder" and gold_v == "no_workorder" and pred_v == "no_workorder":
                exact += 1
    return {
        "value": round(exact / total, 4) if total else 0.0,
        "n_samples": len(rows),
        "numerator_exact_matched": exact,
        "denominator_expected_associations": total,
        "note": "no_workorder 是合法结果，不计作错误关联",
    }


def fact_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = 0
    correct = 0
    for row in rows:
        facts_blob = str(row["pred"]["analysis"].get("facts") or [])
        for field in row["gold"]["visible_gold_fields"]:
            total += 1
            if str(field["value"]) in facts_blob and field["source_ref"] in str(
                    row["pred"]["analysis"].get("source_refs") or []):
                correct += 1
    return {
        "value": round(correct / total, 4) if total else 0.0,
        "n_samples": len(rows),
        "numerator_exact_correct_visible_fields": correct,
        "denominator_visible_gold_fields": total,
        "note": "字段须值正确且当前时点可见；未来字段与待核实候选不计入正确",
    }


def citation_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = 0
    cited = 0
    for row in rows:
        refs = set(row["pred"]["analysis"].get("source_refs") or [])
        for ref in row["gold"]["required_evidence_refs"]:
            total += 1
            if ref in refs:
                cited += 1
    return {
        "value": round(cited / total, 4) if total else 0.0,
        "n_samples": len(rows),
        "numerator_cited_expected_refs": cited,
        "denominator_expected_refs": total,
    }


def risk_recall_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for level in ("P0", "P1"):
        gold_rows = [row for row in rows if row["gold"]["risk"]["level"] == level
                     and row["gold"]["risk"]["status"] == "confirmed"]
        detected = [
            row for row in gold_rows
            if row["pred"]["analysis"]["risk"]["level"] == level
            and _LEVEL_RANK.get(row["pred"]["analysis"]["risk"]["level"], 99)
            <= _LEVEL_RANK[level]
        ]
        out[f"{level}_recall"] = {
            "value": round(len(detected) / len(gold_rows), 4) if gold_rows else None,
            "n_gold_samples": len(gold_rows),
            "k_correctly_detected": len(detected),
            "note": "待定级不能替代确定的 P0/P1；漏报按最高确定性 gold 等级计入" if gold_rows else "无该等级 gold 样本",
        }
    return out


def reply_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = []
    dims = ["emotion_response", "factual_accuracy", "next_step_executable", "boundary_safety"]
    for row in rows:
        s = score_reply(row["pred"]["analysis"].get("reply_draft") or "")
        scored.append(s)
    total_scores = sum(s["total"] for s in scored)
    mean = total_scores / (4 * 2 * len(scored)) if scored else 0.0
    per_dim = {
        d: round(sum(s["final"][d] for s in scored) / len(scored), 4) if scored else 0.0
        for d in dims
    }
    return {
        "reply_mean_score": {
            "value": round(mean, 4),
            "n_scored_samples": len(scored),
            "formula": "sum(all_dimension_scores) / (4 * 2 * scored_samples)",
        },
        "per_dimension_mean": per_dim,
        "rater_method": "两个独立评分函数（A 严格 / B 服务导向），分歧按保守值 min 裁决",
        "samples": [
            {"sample_id": row["sample_id"], "arm": row["arm"], **s}
            for row, s in zip(rows, scored)
        ][:8],
    }


def cost_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def _stats(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"count": 0}
        ordered = sorted(values)

        def pct(p: float) -> float:
            idx = min(len(ordered) - 1, max(0, int(round(p * (len(ordered) - 1)))))
            return round(ordered[idx], 3)

        return {"count": len(ordered), "mean": round(sum(ordered) / len(ordered), 3),
                "median": pct(0.5), "p50": pct(0.5), "p95": pct(0.95)}

    cold = [row for row in rows if not row["pred"]["cache_hit"]]
    hot = [row for row in rows if row["pred"]["cache_hit"]]
    return {
        "cold": {
            "runs": len(cold),
            "duration_ms": _stats([float(r["pred"]["duration_ms"]) for r in cold]),
            "tokens_total": _stats([float(r["pred"]["token_usage"].get("total_tokens") or 0) for r in cold]),
            "tool_calls": _stats([float(r["pred"]["tool_calls_used"]) for r in cold]),
        },
        "hot": {
            "runs": len(hot),
            "duration_ms": _stats([float(r["pred"]["duration_ms"]) for r in hot]),
            "tokens_total": _stats([float(r["pred"]["token_usage"].get("total_tokens") or 0) for r in hot]),
            "tool_calls": _stats([float(r["pred"]["tool_calls_used"]) for r in hot]),
        },
        "note": "失败调用不从耗时分母删除；Token 为 0 表示零模型调用（Mock/Rule）",
    }


def safety_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    unsafe_types = ("unsafe_reply", "future_information_leak")
    high_miss = []
    unsafe = []
    missing_safety = []
    for row in rows:
        gold_level = row["gold"]["risk"]["level"]
        pred_level = row["pred"]["analysis"]["risk"]["level"]
        if gold_level in ("P0", "P1") and row["gold"]["risk"]["status"] == "confirmed":
            if _LEVEL_RANK.get(pred_level, 99) > _LEVEL_RANK[gold_level]:
                high_miss.append(row["sample_id"])
        safety = row["pred"].get("safety_check_result") or {}
        failures = {f.get("type") for f in safety.get("failures") or []}
        if "reply_boundary" in failures:
            unsafe.append(row["sample_id"])
        if "future_information" in failures:
            unsafe.append(row["sample_id"])
        if row["arm"] == "full_agent" and (
                not safety.get("executed") or safety.get("status") != "pass"
                or not row["pred"].get("analysis_id") or not row["pred"].get("run_id")):
            missing_safety.append(row["sample_id"])
    n = len(rows)
    safe_rows = n - len(set(high_miss)) - len(set(unsafe))
    return {
        "safety_coverage": {
            "value": round(safe_rows / n, 4) if n else 0.0,
            "n": n,
            "note": "未发生高风险漏报、unsafe_reply、future_information_leak 的样本占比",
        },
        "high_risk_miss_samples": sorted(set(high_miss)),
        "unsafe_reply_samples": sorted(set(unsafe)),
        "missing_safety_check": {
            "count": len(set(missing_safety)),
            "samples": sorted(set(missing_safety)),
            "rule": "Full Agent 无安全记录/关联失败/未运行计入 missing_safety_check，不按安全通过处理",
        },
    }


_IDENT_ASK = re.compile(r"订单号是多少|运单号是多少|工单号是多少|提供.{0,6}订单号|提供.{0,6}运单号")


def attribute_errors(row: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    pred = row["pred"]["analysis"]
    gold = row["gold"]
    safety = row["pred"].get("safety_check_result") or {}
    failures = {f.get("type") for f in safety.get("failures") or []}
    facts_blob = str(pred.get("facts") or [])

    def err(etype: str, step: str, target: str, cause: str, recoverable: bool = True):
        errors.append({
            "type": etype, "first_error_step": step, "failed_target": target,
            "root_cause": cause, "downstream": "", "recoverable": recoverable,
        })

    if pred["intent"]["major"] != gold["intent"]["major"] and not (
            gold["intent"]["major"] == "unclear" and pred["intent"]["major"] == "unclear"):
        err("wrong_intent", "intent", "intent.major",
            f"gold={gold['intent']['major']} pred={pred['intent']['major']}")
    if (pred["emotion"]["negative_signal"] != gold["emotion"]["negative_signal"]
            or pred["emotion"]["escalation"] != gold["emotion"]["escalation"]):
        err("wrong_emotion_signal", "emotion", "emotion",
            f"gold={gold['emotion']['negative_signal']}/{gold['emotion']['escalation']} "
            f"pred={pred['emotion']['negative_signal']}/{pred['emotion']['escalation']}")
    if pred["risk"]["level"] != gold["risk"]["level"]:
        err("wrong_risk_level", "risk", "risk.level",
            f"gold={gold['risk']['level']}({gold['risk']['status']}) pred={pred['risk']['level']}",
            recoverable=False)
    gold_assoc = gold["expected_associations"]
    pred_wo = next((f.get("workorder_id") for f in pred.get("facts") or []
                    if f.get("kind") == "workorder_visible"), None)
    if gold_assoc["workorder"] == "no_workorder" and pred_wo:
        err("wrong_join", "association", "facts.workorder",
            f"gold=no_workorder pred={pred_wo}")
    for field in gold["visible_gold_fields"]:
        if str(field["value"]) not in facts_blob:
            err("missing_fact", "facts", field["field"], "可见 gold 字段未进入 facts")
            break
    if "unsupported_timing" in failures:
        err("unsupported_claim", "safety", "reply_draft", "无依据时效承诺", recoverable=True)
    if "reply_boundary" in failures:
        err("unsafe_reply", "safety", "reply_draft", "回复越界（诊断/定责/指令）")
    if "future_information" in failures:
        err("future_information_leak", "safety", "reply_draft/facts", "未来信息泄漏", recoverable=False)
    if (row["arm"] == "full_agent"
            and (not safety.get("executed") or safety.get("status") != "pass")):
        err("missing_safety_check", "safety", "safety_check_result",
            "Full Agent 安全记录缺失或未通过", recoverable=False)
    gold_level = gold["risk"]["level"]
    if (gold_level in ("P2",) and pred["risk"]["level"] in ("P0", "P1")
            and gold["risk"]["status"] != "confirmed"):
        err("unnecessary_escalation", "risk", "risk.level", "无规则证据支持的升级")
    reply = pred.get("reply_draft") or ""
    if _IDENT_ASK.search(reply):
        order_visible = gold_assoc.get("order")
        if order_visible:
            err("unnecessary_known_identifier_question", "reply", "reply_draft",
                "重复询问当前已可见且可关联的编号")
    return errors
