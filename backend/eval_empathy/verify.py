"""EVAL-C001–C004 verification over the generated frozen artifacts.

Includes independent hand-calc style spot checks: metric values recomputed
from raw sample rows with a separate minimal implementation must match the
runner-reported numbers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.data_empathy.codec import dumps_canonical
from backend.data_empathy.loader import repo_root

from .datasets import FROZEN_SESSIONS, REGRESSION_SESSIONS, SCENE_MAJORS, SCENE_MINORS

EVAL_DIR = repo_root() / "data" / "eval"
RESULTS = EVAL_DIR / "results"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _base(name: str, ok: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"check": name, "passed": ok, "evidence": evidence}


def verify_phase_e() -> dict[str, Any]:
    issues: list[str] = []
    split = _load(EVAL_DIR / "split_v1.json")
    ontology = _load(EVAL_DIR / "intent_ontology_v1.json")
    gold = _load(EVAL_DIR / "gold_frozen_v1.json")
    report = _load(RESULTS / "frozen_report_v1.json")

    # C001: roster/isolation/ontology/gold
    c1_ok = (
        split["frozen"] == list(FROZEN_SESSIONS)
        and split["regression"] == list(REGRESSION_SESSIONS)
        and len(split["dev"]) == 48
        and split["buyer_isolation"]["isolated"]
        and len(ontology["scene_major"]) == 10
        and len(ontology["scene_minor"]) == 41
        and set(ontology["scene_major"]) == set(SCENE_MAJORS)
        and set(ontology["scene_minor"]) == set(SCENE_MINORS)
        and gold["blind_to_predictions"] is True
        and bool(gold.get("gold_sha256"))
    )
    if not c1_ok:
        issues.append("C001 roster/ontology/gold 校验失败")
    c001 = _base("EVAL-C001", c1_ok, {
        "frozen": split["frozen"], "dev_count": len(split["dev"]),
        "regression": split["regression"],
        "buyer_isolation": split["buyer_isolation"],
        "ontology_sha256": split["ontology_sha256"],
        "gold_sha256": gold["gold_sha256"],
        "gold_method": gold["annotation_method"],
        "split_sha256": split["split_sha256"],
        "frozen_target_units": report["freeze"]["frozen_target_units"],
        "note": "冻结 12 名单与协议一致；回归案例未并入冻结指标",
    })

    # C002: four arms all run, paired per sample, leakage passed
    arms = report["arms"]
    sample_ids = {row["sample_id"] for row in report["samples"]}
    per_arm_ids = {
        arm: {row["sample_id"] for row in report["samples"] if row["arm"] == arm}
        for arm in arms
    }
    paired = all(per_arm_ids[arm] == sample_ids for arm in arms)
    counts = {arm: len(per_arm_ids[arm]) for arm in arms}
    c2_ok = paired and all(counts[arm] == report["freeze"]["frozen_target_units"] for arm in arms) \
        and report["leakage_regression"]["passed"]
    if not c2_ok:
        issues.append("C002 四组配对或泄漏回归失败")
    c002 = _base("EVAL-C002", c2_ok, {
        "arm_sample_counts": counts,
        "paired_per_sample": paired,
        "provider_mode": report["provider_mode"],
        "leakage_regression": report["leakage_regression"],
        "model_effect_note": report["model_effect_note"],
    })

    # C003: formulas + independent spot recomputation
    spot = _spot_recompute(report)
    major_metric = report["per_arm"]["full_agent"]["intent"]["intent_major_macro_f1"]
    c3_ok = spot["all_match"] and major_metric.get("n") is not None \
        and major_metric.get("k_classes_with_support") is not None
    if not c3_ok:
        issues.append("C003 指标抽查不一致")
    full = report["per_arm"]["full_agent"]
    c003 = _base("EVAL-C003", c3_ok, {
        "spot_checks": spot,
        "full_agent_safety": full["safety"],
        "full_agent_errors": full["error_counts"],
        "n_k_reported": {
            "intent_major": full["intent"]["intent_major_macro_f1"]["n"],
            "trajectory": full["trajectory_association_accuracy"]["denominator_expected_associations"],
            "facts": full["fact_field_accuracy"]["denominator_visible_gold_fields"],
            "citation": full["citation_completeness"]["denominator_expected_refs"],
        },
    })

    # C004: report completeness + freeze + boundary/retention
    required_fields = ["sample_id", "set", "arm", "analysis_id", "run_id", "provider",
                       "safety_check_result", "token_usage", "duration_ms", "gold_intent",
                       "pred_intent", "errors", "analysis_json"]
    missing = sorted({
        f for row in report["samples"] for f in required_fields
        if row.get(f) is None
    })
    br = report["boundary_retention"]
    c4_ok = (
        not missing
        and report["freeze"]["frozen"] is True
        and br["retention_set"]["passed"]
        and br["boundary_set"]["passed"]
        and (RESULTS / "frozen_report_v1.csv").exists()
        and (RESULTS / "frozen_report_v1.md").exists()
        and (EVAL_DIR / "gold_regression_v1.json").exists()
    )
    if not c4_ok:
        issues.append("C004 报告完整性/冻结/回归校验失败")
    c004 = _base("EVAL-C004", c4_ok, {
        "missing_fields": missing,
        "freeze": report["freeze"],
        "boundary_retention": br,
        "artifacts": {
            "json": str(RESULTS / "frozen_report_v1.json"),
            "csv": str(RESULTS / "frozen_report_v1.csv"),
            "md": str(RESULTS / "frozen_report_v1.md"),
        },
    })

    result = {
        "phase": "E",
        "passed": all([c001["passed"], c002["passed"], c003["passed"], c004["passed"]]) and not issues,
        "checks": {row["check"]: row for row in (c001, c002, c003, c004)},
        "issues": issues,
        "evidence_boundary": (
            "模型组当前为 MockProvider 离线确定性运行：信息范围消融与全部程序侧指标真实，"
            "模型效果未验证；PPT/视频属阶段 F，本阶段不含展示数字"
        ),
    }
    out = EVAL_DIR / "eval_phase_e_verification.json"
    out.write_text(dumps_canonical(result), encoding="utf-8")
    return result


def _spot_recompute(report: dict[str, Any]) -> dict[str, Any]:
    """Independent minimal recomputation from raw sample rows."""
    checks: dict[str, Any] = {}

    def macro_f1_major(arm: str) -> float:
        rows = [r for r in report["samples"] if r["arm"] == arm]
        per: dict[str, list[int]] = {label: [0, 0, 0] for label in SCENE_MAJORS}  # tp, fp, fn
        for row in rows:
            g = row["gold_intent"]["major"]
            p = row["pred_intent"]["major"]
            if p in per:
                if p == g:
                    per[p][0] += 1
                else:
                    per[p][1] += 1
            if g in per and p != g:
                per[g][2] += 1
        f1s = []
        for tp, fp, fn in per.values():
            if tp + fn == 0:
                continue
            prec = tp / (tp + fp) if tp + fp else 0.0
            rec = tp / (tp + fn)
            f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
        return round(sum(f1s) / len(f1s), 4) if f1s else 0.0

    for arm in ("chat_only", "full_agent", "rules_only"):
        recomputed = macro_f1_major(arm)
        reported = report["per_arm"][arm]["intent"]["intent_major_macro_f1"]["value"]
        checks[f"intent_major_macro_f1[{arm}]"] = {"recomputed": recomputed, "reported": reported,
                                                   "match": recomputed == reported}

    rows_full = [r for r in report["samples"] if r["arm"] == "full_agent"]
    p0_gold = [r for r in rows_full
               if r["gold_risk"]["level"] == "P0" and r["gold_risk"]["status"] == "confirmed"]
    p0_hit = [r for r in p0_gold if r["pred_risk"]["level"] in ("P0",)]
    recomputed_p0 = round(len(p0_hit) / len(p0_gold), 4) if p0_gold else None
    reported_p0 = report["per_arm"]["full_agent"]["risk_recall"]["P0_recall"]["value"]
    checks["P0_recall[full_agent]"] = {
        "recomputed": recomputed_p0, "reported": reported_p0,
        "match": recomputed_p0 == reported_p0,
        "n_gold": len(p0_gold),
    }
    safety_missing = [r["sample_id"] for r in rows_full if r["safety_status"] != "pass"]
    checks["missing_safety_check[full_agent]"] = {
        "recomputed_count": len(safety_missing),
        "reported_count": report["per_arm"]["full_agent"]["safety"]["missing_safety_check"]["count"],
        "match": len(safety_missing)
        == report["per_arm"]["full_agent"]["safety"]["missing_safety_check"]["count"],
    }
    checks["all_match"] = all(v.get("match", True) for v in checks.values())
    return checks


def format_verify_text(report: dict[str, Any]) -> str:
    lines = [
        "Phase E EVAL-C001–C004 verification",
        f"passed={report['passed']}",
    ]
    for name in ("EVAL-C001", "EVAL-C002", "EVAL-C003", "EVAL-C004"):
        row = report["checks"][name]
        lines.append(f"{name}: {'PASS' if row['passed'] else 'FAIL'}")
    for issue in report["issues"]:
        lines.append(f"  issue: {issue}")
    spot = report["checks"]["EVAL-C003"]["evidence"]["spot_checks"]
    for key, value in spot.items():
        if key != "all_match":
            lines.append(f"  spot {key}: {value}")
    lines.append(report["evidence_boundary"])
    return "\n".join(lines)
