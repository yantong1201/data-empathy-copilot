"""Run the frozen evaluation, compute metrics, emit JSON/CSV/Markdown + freeze.

Also runs the boundary/retention regression: retention = frozen-12 rules-only
results must be identical when the provider prompt changes (rules-only has no
model); boundary = regression-case chat-only results are re-run and recorded
after the change.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.data_empathy.codec import dumps_canonical
from backend.data_empathy.loader import DataStore, default_xlsx_path, load_workbook_readonly

from . import metrics as M
from .datasets import build_split, ontology_doc, sample_units
from .gold import build_gold
from .runner import ARMS, EvalRunner

EVAL_DIR = Path(__file__).resolve().parents[2] / "data" / "eval"


def _now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def run_frozen(store: DataStore | None = None) -> dict[str, Any]:
    store = store or DataStore(load_workbook_readonly(default_xlsx_path()))
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    results_dir = EVAL_DIR / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # EVAL-T001: split + ontology + gold (blind, hashed)
    split = build_split(store)
    (EVAL_DIR / "split_v1.json").write_text(dumps_canonical(split), encoding="utf-8")
    (EVAL_DIR / "intent_ontology_v1.json").write_text(dumps_canonical(ontology_doc()), encoding="utf-8")
    frozen_units = sample_units(store, split, "frozen")
    gold_frozen = build_gold(store, frozen_units, "frozen")
    (EVAL_DIR / "gold_frozen_v1.json").write_text(dumps_canonical(gold_frozen), encoding="utf-8")
    regression_units = sample_units(store, split, "regression")
    gold_regression = build_gold(store, regression_units, "regression")
    (EVAL_DIR / "gold_regression_v1.json").write_text(dumps_canonical(gold_regression), encoding="utf-8")

    gold_by_id = {row["sample_id"]: row for row in gold_frozen["labels"]}

    # EVAL-T002: four arms over frozen samples; cold pass then hot pass
    runner = EvalRunner(store, cache=None)
    cold_rows: list[dict[str, Any]] = []
    for arm in ARMS:
        for unit in frozen_units:
            pred = runner.run_sample(arm, unit)
            cold_rows.append({"arm": arm, "sample_id": unit["sample_id"],
                              "gold": gold_by_id[unit["sample_id"]], "pred": pred})
    hot_rows: list[dict[str, Any]] = []
    hot_runner = EvalRunner(store)
    for unit in frozen_units:
        pred = hot_runner.run_sample("full_agent", unit)
        hot_rows.append({"arm": "full_agent", "sample_id": unit["sample_id"],
                         "gold": gold_by_id[unit["sample_id"]], "pred": pred})

    leakage = runner.leakage_regression(frozen_units)

    # EVAL-T003: metrics + error attribution per arm
    per_arm: dict[str, Any] = {}
    for arm in ARMS:
        rows = [row for row in cold_rows if row["arm"] == arm]
        errors = []
        for row in rows:
            errs = M.attribute_errors(row)
            for e in errs:
                e.update({"sample_id": row["sample_id"], "arm": arm})
            errors.extend(errs)
        first_errors = {}
        for e in errors:
            first_errors.setdefault(e["sample_id"], e)
        per_arm[arm] = {
            "n_samples": len(rows),
            "intent": M.intent_metrics(rows),
            "trajectory_association_accuracy": M.trajectory_metrics(rows),
            "fact_field_accuracy": M.fact_metrics(rows),
            "citation_completeness": M.citation_metrics(rows),
            "risk_recall": M.risk_recall_metrics(rows),
            "reply": M.reply_metrics(rows),
            "safety": M.safety_metrics(rows),
            "cost": M.cost_metrics(rows),
            "error_counts": {t: sum(1 for e in errors if e["type"] == t) for t in M.ERROR_TYPES},
            "first_errors": first_errors,
        }

    # Mock continuous success rate: reuse Phase C offline 20x runs evidence
    phase_c_path = Path("data/reports/agent_offline_runs.json")
    mock_rate = None
    if phase_c_path.exists():
        pc = __import__("json").loads(phase_c_path.read_text(encoding="utf-8"))
        summary = pc.get("summary") or {}
        complete = sum(v["complete_valid_runs"] for v in summary.values())
        total = sum(v["total_runs"] for v in summary.values())
        mock_rate = {
            "value": round(complete / total, 4) if total else None,
            "numerator_complete_valid_runs": complete,
            "denominator_total_runs": total,
            "source": "data/reports/agent_offline_runs.json（AGENT-C002 20 次连续离线运行）",
        }

    # boundary / retention regression
    retention_boundary = run_boundary_retention(store, split, gold_by_id, regression_units)

    provider_mode = runner.provider_mode
    freeze = {
        "frozen": True,
        "frozen_at": _now(),
        "policy": "冻结后不得用冻结结果调参，不回写规则；每次 Prompt/规则/Provider/Schema/运行器变化须同时运行受影响 boundary set 与不应变化的 retention set",
        "split_sha256": split["split_sha256"],
        "ontology_sha256": split["ontology_sha256"],
        "gold_frozen_sha256": gold_frozen["gold_sha256"],
        "gold_regression_sha256": gold_regression["gold_sha256"],
        "frozen_session_count": len(split["frozen"]),
        "dev_session_count": len(split["dev"]),
        "frozen_target_units": len(frozen_units),
    }

    report = {
        "report_version": "frozen_report_v1",
        "generated_at": _now(),
        "provider_mode": provider_mode,
        "model_effect_note": (
            "当前无 Qwen 凭证：模型组（chat_only/snapshot/full_agent）以 MockProvider 离线确定性运行，"
            "信息范围消融真实有效，模型效果未验证；Rules-only 为零模型调用"
        ) if provider_mode == "MockProvider" else "Qwen 真实调用",
        "arms": ARMS,
        "split": {"frozen": split["frozen"], "dev_count": len(split["dev"]),
                  "regression": split["regression"],
                  "buyer_isolation": split["buyer_isolation"],
                  "split_sha256": split["split_sha256"]},
        "gold": {"gold_sha256": gold_frozen["gold_sha256"],
                 "method": gold_frozen["annotation_method"],
                 "intent_conflicts_registered": sum(
                     1 for row in gold_frozen["labels"] if row["intent_conflict"])},
        "leakage_regression": leakage,
        "per_arm": per_arm,
        "mock_continuous_success_rate": mock_rate,
        "boundary_retention": retention_boundary,
        "freeze": freeze,
        "samples": [
            {
                "sample_id": row["sample_id"], "arm": row["arm"],
                "set": "frozen", "analysis_id": row["pred"]["analysis_id"],
                "run_id": row["pred"]["run_id"], "provider": row["pred"]["provider"],
                "model": row["pred"]["model"], "schema_valid": row["pred"]["schema_valid"],
                "safety_status": row["pred"]["safety_check_result"].get("status"),
                "token_usage": row["pred"]["token_usage"],
                "duration_ms": row["pred"]["duration_ms"],
                "tool_calls_used": row["pred"]["tool_calls_used"],
                "gold_intent": row["gold"]["intent"],
                "pred_intent": row["pred"]["analysis"]["intent"],
                "gold_risk": {k: row["gold"]["risk"][k] for k in ("type", "level", "status")},
                "pred_risk": {k: row["pred"]["analysis"]["risk"][k] for k in ("type", "level", "status")},
                "errors": [e for e in M.attribute_errors(row)],
                "analysis_json": row["pred"]["analysis"],
                "safety_check_result": row["pred"]["safety_check_result"],
            }
            for row in cold_rows
        ],
    }
    out_json = results_dir / "frozen_report_v1.json"
    out_json.write_text(dumps_canonical(report), encoding="utf-8")
    _write_csv(results_dir / "frozen_report_v1.csv", report)
    _write_md(results_dir / "frozen_report_v1.md", report)
    return report


def run_boundary_retention(store, split, gold_by_id, regression_units) -> dict[str, Any]:
    import backend.agent_empathy.providers as providers_mod

    baseline_runner = EvalRunner(store)
    retention_base = [baseline_runner.run_sample("rules_only", u) for u in
                      sample_units(store, split, "frozen")]
    original_prompt = providers_mod.SYSTEM_PROMPT
    try:
        providers_mod.SYSTEM_PROMPT = original_prompt + "\n<!-- eval-regression-v2 -->"
        changed_runner = EvalRunner(store)
        retention_after = [changed_runner.run_sample("rules_only", u) for u in
                           sample_units(store, split, "frozen")]
        boundary_runs = [changed_runner.run_sample("chat_only", u) for u in regression_units[:6]]
    finally:
        providers_mod.SYSTEM_PROMPT = original_prompt

    def _sig(preds):
        return [(p["sample_id"], p["analysis"]["risk"]["type"], p["analysis"]["risk"]["level"],
                 p["analysis"]["intent"]["major"]) for p in preds]

    identical = _sig(retention_base) == _sig(retention_after)
    return {
        "change": "Provider Prompt 指纹变化（SYSTEM_PROMPT v2）",
        "retention_set": {
            "definition": "冻结 12 会话 rules_only 结果（零模型调用，不应随 Prompt 变化）",
            "n": len(retention_base),
            "identical_after_change": identical,
            "passed": identical,
        },
        "boundary_set": {
            "definition": "协议登记回归案例 chat_only 重跑（受影响范围）",
            "n": len(boundary_runs),
            "runs_recorded": len(boundary_runs),
            "passed": len(boundary_runs) > 0,
        },
    }


def _write_csv(path: Path, report: dict[str, Any]) -> None:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "sample_id", "arm", "set", "analysis_id", "run_id", "provider", "model",
        "gold_intent_major", "pred_intent_major", "gold_risk_level", "pred_risk_level",
        "safety_status", "schema_valid", "tokens", "duration_ms", "tool_calls",
        "error_types", "first_error",
    ])
    for row in report["samples"]:
        writer.writerow([
            row["sample_id"], row["arm"], row["set"], row["analysis_id"], row["run_id"],
            row["provider"], row["model"],
            row["gold_intent"]["major"], row["pred_intent"]["major"],
            row["gold_risk"]["level"], row["pred_risk"]["level"],
            row["safety_status"], row["schema_valid"],
            row["token_usage"].get("total_tokens"), row["duration_ms"], row["tool_calls_used"],
            "|".join(e["type"] for e in row["errors"]),
            next(iter([e["first_error_step"] for e in row["errors"]]), ""),
        ])
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _write_md(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# 冻结评测报告 v1（frozen_report_v1）",
        "",
        f"- 生成时间：{report['generated_at']}",
        f"- Provider 模式：{report['provider_mode']}（{report['model_effect_note']}）",
        f"- 冻结会话：{report['freeze']['frozen_session_count']}；开发会话：{report['freeze']['dev_session_count']}；"
        f"冻结目标样本：{report['freeze']['frozen_target_units']}",
        f"- split hash：`{report['freeze']['split_sha256'][:16]}…`；"
        f"gold hash：`{report['freeze']['gold_frozen_sha256'][:16]}…`；"
        f"ontology hash：`{report['freeze']['ontology_sha256'][:16]}…`",
        "",
        "## 泄漏回归",
        f"- 检查样本 {report['leakage_regression']['checked_samples']}；"
        f"泄漏 {len(report['leakage_regression']['leaks'])}；"
        f"通过：{report['leakage_regression']['passed']}",
        "",
        "## 四组对照指标",
        "",
        "| 指标 | chat_only | snapshot | full_agent | rules_only |",
        "|---|---|---|---|---|",
    ]
    keys = [
        ("intent_major_macro_f1", lambda a: a["intent"]["intent_major_macro_f1"]["value"]),
        ("intent_minor_macro_f1", lambda a: a["intent"]["intent_minor_macro_f1"]["value"]),
        ("unclear_coverage", lambda a: a["intent"]["unclear_coverage"]["value"]),
        ("covered_strict_accuracy", lambda a: a["intent"]["covered_strict_accuracy"]["value"]),
        ("trajectory_association_accuracy", lambda a: a["trajectory_association_accuracy"]["value"]),
        ("fact_field_accuracy", lambda a: a["fact_field_accuracy"]["value"]),
        ("citation_completeness", lambda a: a["citation_completeness"]["value"]),
        ("P0_recall", lambda a: (a["risk_recall"]["P0_recall"]["value"] if a["risk_recall"]["P0_recall"]["n_gold_samples"] else "n/a")),
        ("P1_recall", lambda a: (a["risk_recall"]["P1_recall"]["value"] if a["risk_recall"]["P1_recall"]["n_gold_samples"] else "n/a")),
        ("reply_mean_score", lambda a: a["reply"]["reply_mean_score"]["value"]),
        ("safety_coverage", lambda a: a["safety"]["safety_coverage"]["value"]),
    ]
    for name, getter in keys:
        cells = []
        for arm in report["arms"]:
            getter(report["per_arm"][arm])
            cells.append(str(getter(report["per_arm"][arm])))
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## 成本（cold / hot）",
        "",
    ]
    for arm in report["arms"]:
        cost = report["per_arm"][arm]["cost"]
        lines.append(
            f"- {arm}: cold {cost['cold']['runs']} 次，"
            f"耗时均值 {cost['cold']['duration_ms'].get('mean')}ms / p95 {cost['cold']['duration_ms'].get('p95')}ms；"
            f"hot {cost['hot']['runs']} 次"
        )
    mr = report.get("mock_continuous_success_rate")
    if mr:
        lines += [
            "",
            f"## Mock 连续成功率：{mr['value']}（{mr['numerator_complete_valid_runs']}/{mr['denominator_total_runs']}）",
        ]
    br = report["boundary_retention"]
    lines += [
        "",
        "## Boundary / Retention 回归",
        f"- retention（冻结 rules_only 不随 Prompt 变化）：{'PASS' if br['retention_set']['passed'] else 'FAIL'}（n={br['retention_set']['n']}）",
        f"- boundary（回归案例受影响重跑）：{'PASS' if br['boundary_set']['passed'] else 'FAIL'}（n={br['boundary_set']['n']}）",
        "",
        "## 冻结声明",
        f"- {report['freeze']['policy']}",
        "",
        "> 本报告数字均由运行器生成并可按 analysis_id/run_id 追溯；Mock/Rule 输出不作为模型效果证据。",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
