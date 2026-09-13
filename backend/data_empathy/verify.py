"""Minimal Phase A verification for DATA-C001–C004."""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from .codec import dumps_canonical, dumps_hash_payload
from .fixtures import CASE_FIXTURE_POINTS, generate_case_fixtures
from .loader import DataStore, default_xlsx_path, load_workbook_readonly, repo_root
from .mapping import SOURCE_INCONSISTENCY_KIND
from .selfcheck import EXPECTED_INPUT_AUDIT, run_selfcheck, write_selfcheck
from .snapshot import SnapshotQuery, build_snapshot, collect_future_leaks, is_workorder_claim
from .timeutil import format_iso, parse_shanghai_text


def verify_phase_a(xlsx_path: str | Path | None = None, out_root: Path | None = None) -> dict[str, Any]:
    root = repo_root()
    out_root = Path(out_root) if out_root else root / "data"
    reports_dir = out_root / "reports"
    fixtures_dir = out_root / "fixtures"
    reports_dir.mkdir(parents=True, exist_ok=True)
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    path = Path(xlsx_path) if xlsx_path else default_xlsx_path()
    bundle = load_workbook_readonly(path)
    store = DataStore(bundle)
    selfcheck = run_selfcheck(bundle)
    write_selfcheck(selfcheck, reports_dir / "loader_selfcheck.json")
    (reports_dir / "loader.log").write_text("\n".join(bundle.log) + "\n", encoding="utf-8")
    (reports_dir / "field_mapping.json").write_text(
        dumps_canonical(selfcheck["field_mapping"]), encoding="utf-8"
    )

    checks: list[dict[str, Any]] = []
    checks.append(_c001(selfcheck, bundle))
    checks.append(_c002(store))
    c003 = _c003(store, reports_dir)
    checks.append(c003)
    c004 = _c004(store, fixtures_dir, reports_dir)
    checks.append(c004)

    report = {
        "title": "Phase A DATA-C001–C004 verification",
        "xlsx": str(path),
        "source_sha256": bundle.source_sha256,
        "host_tz_env": os.environ.get("TZ"),
        "checks": checks,
        "passed": all(item["passed"] for item in checks),
        "artifacts": {
            "loader_selfcheck": str(reports_dir / "loader_selfcheck.json"),
            "loader_log": str(reports_dir / "loader.log"),
            "field_mapping": str(reports_dir / "field_mapping.json"),
            "fixtures_manifest": str(fixtures_dir / "manifest.json"),
            "repeatability": str(reports_dir / "repeatability.json"),
            "source_inconsistency_scan": str(reports_dir / "source_inconsistency_scan.json"),
        },
        "note": "Passing these checks is Phase A data-contract evidence, not Agent/Provider/UI delivery.",
    }
    (reports_dir / "phase_a_verification.json").write_text(dumps_canonical(report), encoding="utf-8")
    return report


def _fail(check_id: str, failures: list[str], **extra) -> dict[str, Any]:
    return {"id": check_id, "passed": not failures, "failures": failures, **extra}


def _c001(selfcheck: dict[str, Any], bundle) -> dict[str, Any]:
    failures = []
    if not selfcheck["input_audit_all_match"]:
        failures.append(f"input audit mismatch: {selfcheck['input_audit_match']}")
    if not all(selfcheck["id_types"].values()):
        failures.append(f"id types: {selfcheck['id_types']}")
    if any(bundle.sheets[name].parse_errors for name in bundle.sheets):
        failures.append("parse errors present")
    if not selfcheck["primary_key_uniqueness"]["chat_message_id_unique"]:
        failures.append("message_id not unique")
    if selfcheck["association"]["order_link_rate"] != EXPECTED_INPUT_AUDIT["order_link_hits"]:
        failures.append("order link rate")
    if selfcheck["association"]["workorder_link_rate"] != EXPECTED_INPUT_AUDIT["workorder_link_hits"]:
        failures.append("workorder link rate")
    if len(bundle.sheets) != 7:
        failures.append(f"expected 7 business sheets, got {len(bundle.sheets)}")
    return _fail(
        "DATA-C001",
        failures,
        observed=selfcheck["observed"],
        expected=EXPECTED_INPUT_AUDIT,
        note="Audit numbers confirm loader input, not snapshot filtering.",
    )


def _c002(store: DataStore) -> dict[str, Any]:
    failures = []
    snap = build_snapshot(store, SnapshotQuery(session_id="S00015", message_no=1))
    if snap["workorder"]["visibility"] != "no_workorder":
        failures.append(f"S00015 msg1 workorder={snap['workorder']}")
    if not str(snap["as_of_time"]).endswith("+08:00"):
        failures.append(f"as_of_time missing +08:00: {snap['as_of_time']}")
    first = store.message("S00015", 1)
    if format_iso(first.message_time) != "2026-05-05T16:33:33+08:00":
        failures.append(f"S00015 msg1 time {format_iso(first.message_time)}")
    naive = parse_shanghai_text("2026-05-05 16:33:33")
    if naive != first.message_time:
        failures.append("naive Shanghai parse mismatch")

    # chat filter
    late = build_snapshot(store, SnapshotQuery(session_id="S00015", as_of_time="2026-05-05 16:33:33"))
    if any(msg["message_no"] > 1 for msg in late["chat"]):
        failures.append("future chat leaked at S00015 first message")

    # complete_time empty cannot display completed
    s24 = build_snapshot(store, SnapshotQuery(session_id="S00024", as_of_time="2026-05-06 12:00:00"))
    if s24["workorder"]["visibility"] != "visible":
        failures.append("S00024 after create should be visible")
    if s24["workorder"]["complete_time"] is not None:
        failures.append("S00024 empty complete_time displayed")
    if s24["workorder"]["status"]["snapshot_value"] == "completed":
        failures.append("S00024 displayed completed with empty complete_time")
    if s24["workorder"]["status"]["completed_displayed"]:
        failures.append("S00024 completed_displayed true")

    s01 = build_snapshot(store, SnapshotQuery(session_id="S00001", as_of_time="2026-05-05 18:00:00"))
    if s01["workorder"]["status"]["snapshot_value"] == "completed" or s01["workorder"]["complete_time"]:
        failures.append("S00001 displayed completion with empty complete_time")

    # S00015 complete boundaries
    before_c = build_snapshot(store, SnapshotQuery(session_id="S00015", as_of_time="2026-05-05 23:56:32"))
    at_c = build_snapshot(store, SnapshotQuery(session_id="S00015", as_of_time="2026-05-05 23:56:33"))
    if before_c["workorder"]["complete_time"] is not None:
        failures.append("S00015 complete_time visible one second early")
    if at_c["workorder"]["complete_time"] != "2026-05-05T23:56:33+08:00":
        failures.append("S00015 complete_time not visible at complete")
    if at_c["workorder"]["status"]["snapshot_value"] != "completed":
        failures.append("S00015 not completed at complete_time")

    # order field-level
    before_pay = build_snapshot(store, SnapshotQuery(session_id="S00015", as_of_time="2026-04-19 14:10:00"))
    if before_pay["order"]["visibility"] != "visible":
        failures.append("order should be visible after placed")
    if before_pay["order"]["paid"]["visible"] or before_pay["order"]["paid"]["time"]:
        failures.append("paid_time leaked before paid")
    if before_pay["order"]["shipped"]["visible"]:
        failures.append("shipped leaked before shipped")
    if before_pay["order"]["order_status"]["assertion"] != "unknown":
        failures.append("order status treated as fact without effective time")

    after_ship = build_snapshot(store, SnapshotQuery(session_id="S00015", as_of_time="2026-04-21 03:15:33"))
    if not after_ship["order"]["shipped"]["visible"]:
        failures.append("shipped not visible at shipped_time")

    # host-local independence: format never uses local offset
    if not all(str(s["as_of_time"]).endswith("+08:00") for s in (snap, s24, s01, before_c, at_c)):
        failures.append("output time not +08:00")
    return _fail("DATA-C002", failures, s00015_msg1_workorder=snap["workorder"]["visibility"])


def _c003(store: DataStore, reports_dir: Path) -> dict[str, Any]:
    failures = []
    claim_sessions = set()
    for row in store.bundle.chats:
        if is_workorder_claim(row.message_text, row.role):
            claim_sessions.add(row.session_id)

    scan = []
    leak_count = 0
    missing_conflict = []
    for session_id in sorted(claim_sessions):
        chats = store.require_session(session_id)
        first_claim = next(row for row in chats if is_workorder_claim(row.message_text, row.role))
        snap = build_snapshot(store, SnapshotQuery(session_id=session_id, message_no=first_claim.message_no))
        wo = store.workorders_by_session.get(session_id)
        expect_conflict = wo is None or wo.create_time > first_claim.message_time
        kinds = [item["kind"] for item in snap["source_inconsistency"]]
        has_conflict = SOURCE_INCONSISTENCY_KIND in kinds
        if expect_conflict and not has_conflict:
            missing_conflict.append(session_id)
        if has_conflict:
            item = snap["source_inconsistency"][0]
            for key in ("kind", "source_refs", "as_of_time", "summary"):
                if key not in item or not item[key]:
                    failures.append(f"{session_id} conflict missing {key}")
            refs = item["source_refs"]
            if not any(r.startswith("chat:") for r in refs) or not any(r.startswith("system:") for r in refs):
                failures.append(f"{session_id} conflict missing both sources")
            if "chat_quotes" not in item or not item["chat_quotes"]:
                failures.append(f"{session_id} missing chat quotes")
            if item.get("system_fact", {}).get("fact") != "工单系统暂无记录":
                failures.append(f"{session_id} missing system fact")
        leaks = collect_future_leaks(snap, store)
        if leaks:
            leak_count += 1
            failures.append(f"{session_id} leaks at claim: {leaks}")
        # one second before create if workorder exists
        if wo is not None:
            before = build_snapshot(
                store,
                SnapshotQuery(session_id=session_id, as_of_time=wo.create_time - timedelta(seconds=1)),
            )
            if before["workorder"]["visibility"] != "no_workorder":
                failures.append(f"{session_id} workorder visible before create")
            if before["workorder"].get("workorder_id"):
                failures.append(f"{session_id} future workorder_id exposed")
            before_leaks = collect_future_leaks(before, store)
            if before_leaks:
                failures.append(f"{session_id} leaks before create: {before_leaks}")
            after = build_snapshot(store, SnapshotQuery(session_id=session_id, as_of_time=wo.create_time))
            if after["workorder"]["visibility"] != "visible":
                failures.append(f"{session_id} workorder not visible at create")
            if after["source_inconsistency"]:
                failures.append(f"{session_id} inconsistency remains after create")
        scan.append(
            {
                "session_id": session_id,
                "first_claim_message_no": first_claim.message_no,
                "first_claim_time": format_iso(first_claim.message_time),
                "expect_conflict": expect_conflict,
                "had_conflict": has_conflict,
                "workorder_id": None if wo is None else wo.workorder_id,
                "create_time": None if wo is None else format_iso(wo.create_time),
            }
        )

    # full message-time leak scan for all sessions (not only claims)
    for session_id, rows in store.chats_by_session.items():
        for row in rows:
            snap = build_snapshot(store, SnapshotQuery(session_id=session_id, message_no=row.message_no))
            leaks = collect_future_leaks(snap, store)
            if leaks:
                leak_count += 1
                failures.append(f"{session_id} msg{row.message_no} leaks: {leaks}")
                if leak_count > 20:
                    break
        if leak_count > 20:
            break

    if missing_conflict:
        failures.append(f"claim sessions missing conflict: {missing_conflict}")

    required = {"S00015", "S00024", "S00001"}
    if not required.issubset(claim_sessions):
        failures.append(f"main cases not in claim set: {required - claim_sessions}")

    scan_doc = {
        "claim_session_count": len(claim_sessions),
        "claim_sessions": sorted(claim_sessions),
        "missing_conflict": missing_conflict,
        "rows": scan,
        "note": "Generic claimed_workorder_not_in_system; not limited to three demo cases.",
    }
    (reports_dir / "source_inconsistency_scan.json").write_text(dumps_canonical(scan_doc), encoding="utf-8")
    return _fail(
        "DATA-C003",
        failures,
        claim_session_count=len(claim_sessions),
        missing_conflict=missing_conflict,
    )


def _c004(store: DataStore, fixtures_dir: Path, reports_dir: Path) -> dict[str, Any]:
    failures = []
    first = generate_case_fixtures(store, fixtures_dir)
    second_dir = reports_dir / "_repeat_fixtures"
    second = generate_case_fixtures(store, second_dir)
    if first["file_sha256"] != second["file_sha256"]:
        failures.append("repeat fixture hashes differ")

    # rebuild in-memory twice
    hashes_a = {}
    hashes_b = {}
    for session_id, spec in CASE_FIXTURE_POINTS.items():
        for point in spec["points"]:
            if "message_no" in point:
                q = SnapshotQuery(session_id=session_id, message_no=point["message_no"])
            else:
                q = SnapshotQuery(session_id=session_id, as_of_time=point["as_of"])
            snap_a = build_snapshot(store, q)
            snap_b = build_snapshot(store, q)
            payload_a = dumps_hash_payload(snap_a)
            payload_b = dumps_hash_payload(snap_b)
            if payload_a != payload_b:
                failures.append(f"{session_id}/{point['id']} in-memory JSON differs")
            digest = hashlib.sha256(payload_a.encode("utf-8")).hexdigest()
            hashes_a[f"{session_id}/{point['id']}"] = digest
            hashes_b[f"{session_id}/{point['id']}"] = hashlib.sha256(payload_b.encode("utf-8")).hexdigest()
            if not snap_a["as_of_time"].endswith("+08:00"):
                failures.append(f"{session_id}/{point['id']} time offset")
            refs = snap_a.get("source_refs") or []
            if snap_a["chat"] and not any(r.startswith("chat:") for r in refs):
                failures.append(f"{session_id}/{point['id']} missing chat source_refs")

    # TZ env must not change snapshot hashes
    old_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "UTC"
        snap_utc = build_snapshot(store, SnapshotQuery(session_id="S00015", message_no=1))
        os.environ["TZ"] = "America/New_York"
        snap_ny = build_snapshot(store, SnapshotQuery(session_id="S00015", message_no=1))
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
    if dumps_hash_payload(snap_utc) != dumps_hash_payload(snap_ny):
        failures.append("TZ=UTC vs America/New_York changed snapshot")
    if snap_utc["as_of_time"] != "2026-05-05T16:33:33+08:00":
        failures.append("TZ env changed Shanghai output")

    repeat = {
        "fixture_sha256": first["file_sha256"],
        "repeat_match": first["file_sha256"] == second["file_sha256"],
        "in_memory_match": hashes_a == hashes_b,
        "tz_env_independent": dumps_hash_payload(snap_utc) == dumps_hash_payload(snap_ny),
        "s00015_msg1_as_of": snap_utc["as_of_time"],
    }
    (reports_dir / "repeatability.json").write_text(dumps_canonical(repeat), encoding="utf-8")
    # cleanup second copy? keep for diff evidence
    return _fail("DATA-C004", failures, repeatability=repeat)


def format_verify_text(report: dict[str, Any]) -> str:
    lines = [report["title"], f"passed={report['passed']}", f"xlsx={report['xlsx']}"]
    for item in report["checks"]:
        status = "PASS" if item["passed"] else "FAIL"
        lines.append(f"{item['id']} {status}")
        for fail in item.get("failures") or []:
            lines.append(f"  - {fail}")
    return "\n".join(lines) + "\n"
