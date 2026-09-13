"""S00015 / S00024 / S00001 regression fixtures."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any

from .codec import dumps_canonical, dumps_hash_payload
from .loader import DataStore
from .snapshot import SnapshotQuery, build_snapshot
from .timeutil import format_iso, parse_shanghai_text

CASE_FIXTURE_POINTS = {
    "S00015": {
        "workorder_id": "BLFY61738711",
        "points": [
            {"id": "first_message", "message_no": 1, "expect_time": "2026-05-05 16:33:33"},
            {"id": "claim_created", "message_no": 4, "expect_time": "2026-05-05 16:38:49"},
            {"id": "before_create", "as_of": "2026-05-05 17:13:32"},
            {"id": "at_create", "as_of": "2026-05-05 17:13:33"},
            {"id": "before_complete", "as_of": "2026-05-05 23:56:32"},
            {"id": "at_complete", "as_of": "2026-05-05 23:56:33"},
            {"id": "before_order_placed", "as_of": "2026-04-19 14:03:32"},
            {"id": "after_placed_before_paid", "as_of": "2026-04-19 14:10:00"},
            {"id": "after_paid_before_shipped", "as_of": "2026-04-20 00:00:00"},
            {"id": "after_shipped_before_chat", "as_of": "2026-04-21 03:15:33"},
        ],
    },
    "S00024": {
        "workorder_id": "KOC3195289",
        "points": [
            {"id": "first_message", "message_no": 1, "expect_time": "2026-05-05 21:38:52"},
            {"id": "claim_created", "message_no": 4, "expect_time": "2026-05-05 21:42:59"},
            {"id": "before_create", "as_of": "2026-05-05 22:15:51"},
            {"id": "at_create", "as_of": "2026-05-05 22:15:52"},
            {"id": "complete_empty_after_create", "as_of": "2026-05-06 12:00:00"},
            {"id": "before_order_placed", "as_of": "2026-04-29 17:33:51"},
            {"id": "after_placed_before_paid", "as_of": "2026-04-29 17:40:00"},
            {"id": "after_paid_before_shipped", "as_of": "2026-04-30 12:00:00"},
            {"id": "after_shipped_before_chat", "as_of": "2026-05-01 13:55:52"},
        ],
    },
    "S00001": {
        "workorder_id": "BH919209358357",
        "points": [
            {"id": "first_message", "message_no": 1, "expect_time": "2026-05-05 10:18:45"},
            {"id": "claim_created", "message_no": 6, "expect_time": "2026-05-05 10:27:37"},
            {"id": "before_create", "as_of": "2026-05-05 10:29:44"},
            {"id": "at_create", "as_of": "2026-05-05 10:29:45"},
            {"id": "complete_empty_after_create", "as_of": "2026-05-05 18:00:00"},
            {"id": "before_order_placed", "as_of": "2026-04-29 08:27:44"},
            {"id": "after_placed_before_paid", "as_of": "2026-04-29 08:40:00"},
            {"id": "after_paid_before_shipped", "as_of": "2026-04-29 12:00:00"},
            {"id": "after_shipped_before_chat", "as_of": "2026-04-30 08:50:45"},
        ],
    },
}


def generate_case_fixtures(store: DataStore, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "cases": {},
        "source_sha256": store.bundle.source_sha256,
        "source_path": store.bundle.source_path,
    }
    files: dict[str, str] = {}
    for session_id, spec in CASE_FIXTURE_POINTS.items():
        case_dir = out_dir / session_id
        case_dir.mkdir(parents=True, exist_ok=True)
        wo = store.workorders_by_session.get(session_id)
        if wo is None or wo.workorder_id != spec["workorder_id"]:
            raise AssertionError(
                f"{session_id} workorder mismatch: expected {spec['workorder_id']} got {None if wo is None else wo.workorder_id}"
            )
        case_files = []
        for point in spec["points"]:
            query = _point_query(session_id, point)
            if point.get("message_no") is not None and point.get("expect_time"):
                msg = store.message(session_id, point["message_no"])
                expected = parse_shanghai_text(point["expect_time"])
                if msg.message_time != expected:
                    raise AssertionError(
                        f"{session_id} msg{point['message_no']} time {format_iso(msg.message_time)} != {format_iso(expected)}"
                    )
            snapshot = build_snapshot(store, query)
            name = f"{point['id']}.json"
            path = case_dir / name
            payload = dumps_canonical(snapshot)
            path.write_text(payload, encoding="utf-8")
            digest = hashlib.sha256(dumps_hash_payload(snapshot).encode("utf-8")).hexdigest()
            rel = f"{session_id}/{name}"
            files[rel] = digest
            case_files.append(
                {
                    "id": point["id"],
                    "file": rel,
                    "sha256": digest,
                    "as_of_time": snapshot["as_of_time"],
                    "message_no": snapshot["message_no"],
                    "workorder_visibility": snapshot["workorder"]["visibility"],
                    "source_inconsistency_kinds": [item["kind"] for item in snapshot["source_inconsistency"]],
                }
            )
        manifest["cases"][session_id] = {
            "workorder_id": spec["workorder_id"],
            "files": case_files,
        }
    manifest["file_sha256"] = files
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(dumps_canonical(manifest), encoding="utf-8")
    return manifest


def _point_query(session_id: str, point: dict[str, Any]) -> SnapshotQuery:
    if "message_no" in point:
        return SnapshotQuery(session_id=session_id, message_no=point["message_no"])
    return SnapshotQuery(session_id=session_id, as_of_time=point["as_of"])


def boundary_as_of(store: DataStore, session_id: str) -> list[SnapshotQuery]:
    """Create/complete ±1s plus each message time."""
    queries = [
        SnapshotQuery(session_id=session_id, message_no=row.message_no)
        for row in store.require_session(session_id)
    ]
    wo = store.workorders_by_session.get(session_id)
    order = store.orders_by_session.get(session_id)
    extra_times = []
    if wo is not None:
        extra_times.extend(
            [
                wo.create_time - timedelta(seconds=1),
                wo.create_time,
                wo.create_time + timedelta(seconds=1),
            ]
        )
        if wo.complete_time is not None:
            extra_times.extend(
                [
                    wo.complete_time - timedelta(seconds=1),
                    wo.complete_time,
                    wo.complete_time + timedelta(seconds=1),
                ]
            )
    if order is not None:
        extra_times.extend(
            [
                order.placed_time - timedelta(seconds=1),
                order.placed_time,
                order.paid_time - timedelta(seconds=1) if order.paid_time else None,
                order.paid_time,
                order.shipped_time - timedelta(seconds=1) if order.shipped_time else None,
                order.shipped_time,
            ]
        )
    seen = {q.message_no for q in queries}
    for ts in extra_times:
        if ts is None:
            continue
        queries.append(SnapshotQuery(session_id=session_id, as_of_time=ts))
    _ = seen
    return queries
