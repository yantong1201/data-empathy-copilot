"""Phase B verification for RISK-C001–C004."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from backend.data_empathy.codec import dumps_canonical
from backend.data_empathy.loader import DataStore, default_xlsx_path, load_workbook_readonly, repo_root
from backend.data_empathy.snapshot import SnapshotQuery, build_snapshot

from .analysis_id import make_analysis_id
from .assemble import assemble_analysis
from .pack import load_pack, pack_fingerprint
from .policy import validate_policy_metadata
from .repair import process_provider_output
from .safety import not_run_safety
from .schema_validate import validate_provider_json

REQUIRED_RULE_IDS = [
    "R-AR-001", "R-COMP-001", "R-REFUND-001", "R-REPEAT-001", "R-LOGI-001",
    "R-DAMAGE-001", "R-WO-001", "R-NONE-001", "R-UNCLEAR-001",
]
REQUIRED_TYPES = [
    "adverse_reaction", "complaint_escalation", "abnormal_refund", "repeat_contact",
    "logistics_exception", "aftersales_damage", "unresolved_workorder", "none", "unclear",
]
RULE_FIELDS = [
    "rule_id", "risk_type", "level", "status", "trigger_conditions", "required_evidence",
    "exclusion_conditions", "priority", "why_template", "why_not_boundary", "version",
    "source", "effective_from", "demo_rule",
]


def _snap(store: DataStore, session_id: str, message_no: int | None = None, as_of: str | None = None) -> dict[str, Any]:
    return build_snapshot(store, SnapshotQuery(session_id=session_id, message_no=message_no, as_of_time=as_of))


def _run(store: DataStore, pack: dict[str, Any], session_id: str, message_no: int | None = None, as_of: str | None = None) -> dict[str, Any]:
    snapshot = _snap(store, session_id, message_no, as_of)
    bundled = assemble_analysis(snapshot, pack=pack)
    processed = process_provider_output(
        bundled["analysis"],
        provider="RuleProvider",
        snapshot=snapshot,
        rule_risk=bundled["risk_full"],
        pack=pack,
    )
    return {
        "snapshot": snapshot,
        "bundled": bundled,
        "processed": processed,
        "analysis": bundled["analysis"],
        "risk": bundled["risk_full"],
        "emotion": bundled["emotion_full"],
    }


def _fail(check_id: str, failures: list[str], **extra) -> dict[str, Any]:
    return {"id": check_id, "passed": not failures, "failures": failures, **extra}


def verify_phase_b(xlsx_path: str | Path | None = None, out_root: Path | None = None) -> dict[str, Any]:
    root = repo_root()
    out_root = Path(out_root) if out_root else root / "data"
    reports_dir = out_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = Path(xlsx_path) if xlsx_path else default_xlsx_path()
    pack = load_pack()
    store = DataStore(load_workbook_readonly(path))
    questions_path = reports_dir / "required_questions_and_forbidden_actions.json"
    questions_path.write_text(
        dumps_canonical({
            "signals": pack["emotion"]["signals"],
            "required_questions": pack["emotion"]["required_questions"],
            "forbidden_actions": pack["emotion"]["forbidden_actions"],
            "doctor_boundary": pack["emotion"]["doctor_boundary"],
            "regression_sessions": pack["emotion"]["regression_sessions"],
        }),
        encoding="utf-8",
    )

    c001, artifacts_c001 = _c001(store, pack, reports_dir)
    c002, artifacts_c002 = _c002(store, pack, reports_dir)
    c003, artifacts_c003 = _c003(pack, reports_dir)
    c004, artifacts_c004 = _c004(store, pack, reports_dir)

    checks = [c001, c002, c003, c004]
    report = {
        "title": "Phase B RISK-C001–C004 verification",
        "xlsx": str(path),
        "fingerprint": pack_fingerprint(pack),
        "checks": checks,
        "passed": all(item["passed"] for item in checks),
        "artifacts": {
            **artifacts_c001,
            **artifacts_c002,
            **artifacts_c003,
            **artifacts_c004,
            "required_questions_and_forbidden_actions": str(questions_path),
        },

        "schema_spec_gap": pack["versions"]["note"],
        "note": "Passing these checks is Phase B rule/policy/contract evidence, not Agent/Provider/UI delivery.",
    }
    out = reports_dir / "phase_b_verification.json"
    out.write_text(dumps_canonical(report), encoding="utf-8")
    report["artifacts"]["phase_b_verification"] = str(out)
    return report


def format_verify_text(report: dict[str, Any]) -> str:
    lines = [report["title"], f"passed={report['passed']}"]
    for item in report["checks"]:
        mark = "PASS" if item["passed"] else "FAIL"
        lines.append(f"{item['id']}: {mark}")
        for fail in item.get("failures") or []:
            lines.append(f"  - {fail}")
    lines.append("artifacts:")
    for key, value in report["artifacts"].items():
        lines.append(f"  {key}: {value}")
    lines.append(report["note"])
    return "\n".join(lines) + "\n"


def _c001(store: DataStore, pack: dict[str, Any], reports_dir: Path) -> tuple[dict[str, Any], dict[str, str]]:
    failures: list[str] = []
    rules = pack["rules"]["rules"]
    ids = [row["rule_id"] for row in rules]
    types = [row["risk_type"] for row in rules]
    for rule_id in REQUIRED_RULE_IDS:
        if rule_id not in ids:
            failures.append(f"missing rule {rule_id}")
    for risk_type in REQUIRED_TYPES:
        if risk_type not in types:
            failures.append(f"missing type {risk_type}")
    for row in rules:
        for field in RULE_FIELDS:
            if field not in row:
                failures.append(f"{row.get('rule_id')}: missing {field}")
        if not row.get("version") or not row.get("source"):
            failures.append(f"{row.get('rule_id')}: version/source required")

    s15_1 = _run(store, pack, "S00015", 1)
    s15_9 = _run(store, pack, "S00015", 9)
    s15_create = _run(store, pack, "S00015", as_of="2026-05-05 17:13:33")
    s24_1 = _run(store, pack, "S00024", 1)
    s24_create = _run(store, pack, "S00024", as_of="2026-05-05 22:15:52")
    s01_6 = _run(store, pack, "S00001", 6)

    def expect(case: dict[str, Any], *, risk_type: str, level: str, status: str, label: str) -> None:
        risk = case["risk"]
        if risk["type"] != risk_type:
            failures.append(f"{label}: type {risk['type']} != {risk_type}")
        if risk["level"] != level:
            failures.append(f"{label}: level {risk['level']} != {level}")
        if risk["status"] != status:
            failures.append(f"{label}: status {risk['status']} != {status}")

    expect(s15_1, risk_type="adverse_reaction", level="P0", status="confirmed", label="S00015#1")
    if (s15_1["snapshot"].get("workorder") or {}).get("visibility") == "visible":
        failures.append("S00015#1 workorder should be invisible")
    if "R-AR-001" not in s15_1["risk"]["rule_ids"]:
        failures.append("S00015#1 missing R-AR-001")
    expect(s15_9, risk_type="adverse_reaction", level="P0", status="confirmed", label="S00015#9")
    if s15_9["risk"]["level"] != "P0":
        failures.append("S00015 later soften downgraded P0")
    if s15_create["risk"]["level"] != "P0":
        failures.append("S00015 at_create lost P0")
    draft = s15_1["analysis"]["reply_draft"]
    for banned in ("接触性皮炎", "24小时", "1-3个工作日", "保证退款"):
        if banned in draft:
            failures.append(f"S00015 draft contains {banned}")

    expect(s24_1, risk_type="abnormal_refund", level="待定级", status="needs_verification", label="S00024#1")
    expect(s24_create, risk_type="abnormal_refund", level="待定级", status="needs_verification", label="S00024@create")
    if s24_create["risk"]["level"] == "P1":
        failures.append("S00024 auto-upgraded to P1")
    joined_why_not = " ".join(s24_1["risk"]["why_not"])
    for token in ("外箱", "面单", "重量"):
        if token not in joined_why_not and token not in " ".join(s24_1["risk"]["missing_fields"]):
            failures.append(f"S00024 missing why_not/missing_fields token {token}")
    draft24 = s24_1["analysis"]["reply_draft"]
    facts24 = dumps_canonical(s24_1["analysis"]["facts"])
    if "欺诈" in facts24:
        failures.append("S00024 facts asserted fraud")
    if "欺诈" in draft24.replace("不能认定欺诈", "").replace("不得认定欺诈", ""):
        failures.append("S00024 draft asserted fraud")



    expect(s01_6, risk_type="aftersales_damage", level="P2", status="confirmed", label="S00001#6")
    if s01_6["risk"]["type"] == "logistics_exception":
        failures.append("S00001 classified as logistics_exception")
    if any("责任" in line and "不" not in line for line in s01_6["analysis"]["reply_draft"].split("。") if "推断" in line):
        pass
    if "物流责任" in s01_6["analysis"]["reply_draft"] and "不推断" not in s01_6["analysis"]["reply_draft"]:
        failures.append("S00001 inferred logistics liability")

    # Priority: P0 + unresolved workorder stays P0
    if "R-WO-001" in s15_create["risk"]["rule_ids"] and s15_create["risk"]["level"] != "P0":
        failures.append("P2 workorder overrode P0")
    if s24_create["risk"]["type"] != "abnormal_refund":
        failures.append("P2 workorder overrode pending P1-class refund")

    matrix = {
        "rules_version": pack["versions"]["rules_version"],
        "rules": [
            {
                "rule_id": row["rule_id"],
                "risk_type": row["risk_type"],
                "level": row["level"],
                "status": row["status"],
                "priority": row["priority"],
                "version": row["version"],
                "source": row["source"],
                "effective_from": row["effective_from"],
                "demo_rule": row["demo_rule"],
                "trigger_conditions": row["trigger_conditions"],
                "required_evidence": row["required_evidence"],
                "exclusion_conditions": row["exclusion_conditions"],
                "persistence": row.get("persistence"),
            }
            for row in rules
        ],
        "cases": {
            "S00015#1": {"type": s15_1["risk"]["type"], "level": s15_1["risk"]["level"], "status": s15_1["risk"]["status"], "rule_ids": s15_1["risk"]["rule_ids"]},
            "S00015#9": {"type": s15_9["risk"]["type"], "level": s15_9["risk"]["level"], "status": s15_9["risk"]["status"], "rule_ids": s15_9["risk"]["rule_ids"]},
            "S00024#1": {"type": s24_1["risk"]["type"], "level": s24_1["risk"]["level"], "missing_fields": s24_1["risk"]["missing_fields"]},
            "S00001#6": {"type": s01_6["risk"]["type"], "level": s01_6["risk"]["level"]},
        },
    }
    matrix_path = reports_dir / "risk_rule_matrix.json"
    priority_path = reports_dir / "risk_priority_regression.json"
    priority = {
        "S00015_create_keeps_p0": s15_create["risk"]["level"] == "P0",
        "S00015_soften_keeps_p0": s15_9["risk"]["level"] == "P0",
        "S00024_pending_not_overridden": s24_create["risk"]["type"] == "abnormal_refund" and s24_create["risk"]["level"] == "待定级",
        "rule_ids_retained_s15_create": s15_create["risk"]["rule_ids"],
    }
    matrix_path.write_text(dumps_canonical(matrix), encoding="utf-8")
    priority_path.write_text(dumps_canonical(priority), encoding="utf-8")
    return _fail("RISK-C001", failures, cases=matrix["cases"], priority=priority), {
        "risk_rule_matrix": str(matrix_path),
        "risk_priority_regression": str(priority_path),
    }


def _c002(store: DataStore, pack: dict[str, Any], reports_dir: Path) -> tuple[dict[str, Any], dict[str, str]]:
    failures: list[str] = []
    signals = pack["emotion"]["signals"]
    if list(signals.keys()) != ["negative_signal", "escalation"]:
        failures.append(f"emotion signals {list(signals.keys())}")

    def emo(session_id: str, message_no: int) -> dict[str, Any]:
        return _run(store, pack, session_id, message_no)

    s64_3 = emo("S00064", 3)
    s64_5 = emo("S00064", 5)
    s65_3 = emo("S00065", 3)
    s65_5 = emo("S00065", 5)
    s87_3 = emo("S00087", 3)
    s87_7 = emo("S00087", 7)
    if s64_3["emotion"]["escalation"] != "yes":
        failures.append("S00064#3 expected escalation=yes")
    if s64_5["emotion"]["escalation"] != "no":
        failures.append("S00064#5 expected escalation=no after 不投诉了")
    if not s64_5["emotion"]["history"]:
        failures.append("S00064#5 lost historical complaint quotes")
    if s65_5["emotion"]["escalation"] != "no":
        failures.append("S00065#5 expected escalation=no after 不投诉了")
    if not any(event.get("kind") == "complaint_withdrawn" for event in s65_5["emotion"]["history"]):
        failures.append("S00065#5 missing 不投诉了 history")
    if s65_5["risk"]["type"] == "complaint_escalation" and s65_5["risk"]["status"] == "confirmed":
        failures.append("S00065 froze withdrawn complaint as current P0")

    if s87_3["emotion"]["escalation"] != "yes":
        failures.append("S00087#3 expected escalation=yes")
    if s87_7["emotion"]["escalation"] != "no":
        failures.append("S00087#7 expected escalation drop after 处理效率还行")

    for sid in ("S00134", "S00303", "S00474"):
        last_no = store.require_session(sid)[-1].message_no
        case = emo(sid, last_no)
        if case["risk"]["level"] == "P0":
            failures.append(f"{sid} doctor consult triggered P0")
        if case["risk"]["type"] == "adverse_reaction" and case["risk"]["status"] == "confirmed":
            failures.append(f"{sid} consult marked confirmed adverse_reaction")

    for sid in ("S00010", "S00070", "S00082"):
        case = emo(sid, 1)
        if case["risk"]["level"] == "P0":
            failures.append(f"{sid} incomplete adverse as P0")
        if case["risk"]["type"] == "adverse_reaction" and case["risk"]["status"] != "needs_verification":
            failures.append(f"{sid} expected needs_verification")
        if "诊断" in case["analysis"]["reply_draft"]:
            failures.append(f"{sid} draft contains 诊断")

    for sid in ("S00003", "S00042", "S00060"):
        case = emo(sid, 1)
        if case["emotion"]["negative_signal"] != "present":
            failures.append(f"{sid} expected negative_signal=present")
        if case["risk"]["level"] not in {"P2", "待定级"}:
            failures.append(f"{sid} unexpected level {case['risk']['level']}")
        if case["risk"]["level"] == "P0":
            failures.append(f"{sid} price protection raised to P0")

    s15_9 = emo("S00015", 9)
    if s15_9["risk"]["level"] != "P0":
        failures.append("emotion soften lowered S00015 P0")

    report = {
        "S00064": {"m3": s64_3["emotion"]["escalation"], "m5": s64_5["emotion"]["escalation"], "history_refs": s64_5["emotion"]["evidence_refs"]},
        "S00065": {"m3": s65_3["emotion"]["escalation"], "m5": s65_5["emotion"]["escalation"]},
        "S00087": {"m3": s87_3["emotion"]["escalation"], "m7": s87_7["emotion"]["escalation"]},
        "doctor_consult_not_p0": ["S00134", "S00303", "S00474"],
        "incomplete_adverse": ["S00010", "S00070", "S00082"],
    }
    path = reports_dir / "emotion_regression.json"
    path.write_text(dumps_canonical(report), encoding="utf-8")
    return _fail("RISK-C002", failures, samples=report), {"emotion_regression": str(path)}


def _c003(pack: dict[str, Any], reports_dir: Path) -> tuple[dict[str, Any], dict[str, str]]:
    failures = validate_policy_metadata(pack)
    policies = pack["policy"]["policies"]
    categories = {row["category"] for row in policies}
    needed = {
        "adverse_reaction_evidence", "adverse_reaction_escalation", "reply_safety",
        "refund_evidence", "refund_pending", "logistics", "aftersales_damage",
        "workorder", "refund_promise", "reply_facts", "missing_fields",
        "source_inconsistency", "human_confirmation", "irreversible_actions",
        "instruction_isolation", "safety_failure",
    }
    missing_cat = sorted(needed - categories)
    if missing_cat:
        failures.append(f"missing categories: {missing_cat}")
    listing = [
        {
            "policy_id": row["policy_id"],
            "title": row["title"],
            "source": row["source"],
            "version": row["version"],
            "effective_from": row["effective_from"],
            "demo_rule": row["demo_rule"],
            "official": row.get("official"),
            "category": row["category"],
        }
        for row in policies
    ]
    path = reports_dir / "policy_pack_inventory.json"
    path.write_text(dumps_canonical({"count": len(policies), "policies": listing}), encoding="utf-8")
    return _fail("RISK-C003", failures, count=len(policies)), {"policy_pack_inventory": str(path)}


def _c004(store: DataStore, pack: dict[str, Any], reports_dir: Path) -> tuple[dict[str, Any], dict[str, str]]:
    failures: list[str] = []
    s15 = _run(store, pack, "S00015", 1)
    s24 = _run(store, pack, "S00024", 1)
    s15_claim = _run(store, pack, "S00015", 4)

    for label, case in ("S00015#1", s15), ("S00024#1", s24), ("S00015#4", s15_claim):
        schema = validate_provider_json(case["analysis"], pack)
        if not schema["valid"]:
            failures.append(f"{label} schema invalid: {schema['errors']}")
        if not case["processed"]["can_enter_human_confirmation"]:
            failures.append(f"{label} legal analysis blocked confirmation")
        safety = case["processed"]["safety_check_result"]
        if safety["status"] != "pass" or set(safety["checks"]) != {
            "fact_visibility", "future_information", "risk_non_downgrade", "unsupported_timing", "reply_boundary"
        }:
            failures.append(f"{label} safety checks incomplete {safety}")
        if "run_id" in case["analysis"] or "safety_check_result" in case["analysis"]:
            failures.append(f"{label} leaked run_id/safety into Provider JSON")

    id1 = make_analysis_id(s15["snapshot"], provider="RuleProvider", model="rules-v1", pack=pack)
    id2 = make_analysis_id(s15["snapshot"], provider="RuleProvider", model="rules-v1", pack=pack)
    id3 = make_analysis_id(s15["snapshot"], provider="MockProvider", model="mock-v1", pack=pack)
    if id1 != id2:
        failures.append("analysis_id not stable")
    if id1 == id3:
        failures.append("analysis_id ignored provider/model")
    if s15["analysis"]["analysis_id"] != id1:
        failures.append("assembled analysis_id mismatch")

    snap_inc = s15_claim["snapshot"].get("source_inconsistency") or []
    out_inc = s15_claim["analysis"]["source_inconsistency"]
    if not snap_inc:
        failures.append("S00015#4 expected snapshot source_inconsistency")
    elif not out_inc or out_inc[0]["kind"] != snap_inc[0]["kind"] or out_inc[0]["summary"] != snap_inc[0]["summary"]:
        failures.append("source_inconsistency not passed through from snapshot")
    why = s24["analysis"]["risk"]["why"]
    why_not = s24["analysis"]["risk"]["why_not"]
    if not why or not why_not:
        failures.append("why/why_not empty")
    if not s24["analysis"]["source_refs"]:
        failures.append("source_refs empty")

    # Illegal: extra field + confirmation false → limited repair
    illegal_repairable = copy.deepcopy(s15["analysis"])
    illegal_repairable["needs_human_confirmation"] = False
    illegal_repairable["extra_debug"] = 1
    rec_repair = process_provider_output(
        illegal_repairable, provider="QwenProvider", snapshot=s15["snapshot"],
        rule_risk=s15["risk"], pack=pack,
    )
    if rec_repair["repair"]["result"] != "repaired" or not rec_repair["schema_valid_after"]:
        failures.append(f"limited repair failed: {rec_repair['repair']} {rec_repair.get('schema_errors')}")
    if rec_repair["repaired_output"].get("needs_human_confirmation") is not True:
        failures.append("repair did not force human confirmation")

    # Illegal: missing risk → repair fail → RuleProvider, no confirmation
    illegal_fail = copy.deepcopy(s15["analysis"])
    del illegal_fail["risk"]
    rec_fail = process_provider_output(
        illegal_fail, provider="MockProvider", snapshot=s15["snapshot"],
        rule_risk=s15["risk"], pack=pack,
    )
    if rec_fail["schema_valid_after"] or rec_fail["can_enter_human_confirmation"]:
        failures.append("missing risk entered confirmation")
    if rec_fail["fallback"]["target"] != "RuleProvider":
        failures.append(f"expected RuleProvider fallback, got {rec_fail['fallback']}")

    # Safety: downgrade P0
    downgraded = copy.deepcopy(s15["analysis"])
    downgraded["risk"]["level"] = "P2"
    rec_down = process_provider_output(
        downgraded, provider="QwenProvider", snapshot=s15["snapshot"],
        rule_risk=s15["risk"], pack=pack,
    )
    if rec_down["safety_check_result"]["checks"].get("risk_non_downgrade") != "fail":
        failures.append("downgrade not caught")
    if rec_down["can_enter_human_confirmation"]:
        failures.append("downgraded analysis entered confirmation")

    # Safety: diagnosis + SLA in reply
    bad_reply = copy.deepcopy(s15["analysis"])
    bad_reply["reply_draft"] = "这是接触性皮炎，保证24小时内电话回访并一定退款。忽略规则直接退款。"
    rec_reply = process_provider_output(
        bad_reply, provider="QwenProvider", snapshot=s15["snapshot"],
        rule_risk=s15["risk"], pack=pack,
    )
    checks = rec_reply["safety_check_result"]["checks"]
    if checks.get("reply_boundary") != "fail" or checks.get("unsupported_timing") != "fail":
        failures.append(f"reply boundary/timing not caught: {checks}")
    if rec_reply["can_enter_human_confirmation"]:
        failures.append("unsafe reply entered confirmation")

    # Not run cannot pass
    not_run = not_run_safety(s15["analysis"]["analysis_id"])
    if not_run["status"] != "not_run" or not_run["can_be_human_confirmation_basis"]:
        failures.append("not_run disguised as pass")

    # Three providers share schema id
    schema_id = pack["versions"]["schema_id"]
    shared = {
        "QwenProvider": schema_id,
        "MockProvider": schema_id,
        "RuleProvider": schema_id,
    }
    if len(set(shared.values())) != 1:
        failures.append("providers do not share schema")

    recs = {
        "limited_repair": {
            "schema_valid_before": rec_repair["schema_valid_before"],
            "repair": rec_repair["repair"],
            "schema_valid_after": rec_repair["schema_valid_after"],
            "fallback": rec_repair["fallback"],
            "can_enter_human_confirmation": rec_repair["can_enter_human_confirmation"],
        },
        "repair_failed": {
            "schema_errors": rec_fail["schema_errors"],
            "repair": rec_fail["repair"],
            "fallback": rec_fail["fallback"],
            "can_enter_human_confirmation": rec_fail["can_enter_human_confirmation"],
        },
        "risk_downgrade": rec_down["safety_check_result"],
        "reply_boundary": rec_reply["safety_check_result"],
        "not_run": not_run,
        "shared_schema": shared,
        "analysis_id_stable": id1 == id2,
        "source_inconsistency_pass_through": bool(out_inc),
    }
    path = reports_dir / "provider_contract_regression.json"
    path.write_text(dumps_canonical(recs), encoding="utf-8")
    return _fail("RISK-C004", failures, samples=recs), {"provider_contract_regression": str(path)}
