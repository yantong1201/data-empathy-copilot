"""Loader self-check. Input audit numbers are not snapshot proof."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from .codec import dumps_canonical
from .loader import CanonicalBundle
from .mapping import BUSINESS_SHEETS, CHAT_SHEET, ORDER_SHEET, WORKORDER_SHEETS, field_mapping_document
from .timeutil import format_iso

EXPECTED_INPUT_AUDIT = {
    "chat_rows": 998,
    "chat_sessions": 138,
    "chat_buyers": 112,
    "order_rows": 113,
    "workorder_rows": {
        "补发换货工单": 24,
        "线下打款工单": 13,
        "物流工单": 15,
        "不良反应工单": 10,
        "售后退货工单": 18,
    },
    "workorder_total": 80,
    "order_link_hits": "819/819",
    "workorder_link_hits": "629/629",
    "image_messages": 29,
}


def run_selfcheck(bundle: CanonicalBundle) -> dict[str, Any]:
    chats = bundle.chats
    orders = bundle.orders
    workorders = bundle.workorders
    sheets_report = []
    for name in BUSINESS_SHEETS:
        sheet = bundle.sheets[name]
        sheets_report.append(
            {
                "sheet": name,
                "row_count": sheet.row_count,
                "headers": sheet.headers,
                "canonical_fields": sheet.canonical_fields,
                "parse_errors": sheet.parse_errors,
            }
        )

    chat_sessions = {row.session_id for row in chats}
    chat_buyers = {row.buyer_nick for row in chats}
    message_ids = [row.message_id for row in chats]
    session_msg = [(row.session_id, row.message_no) for row in chats]
    order_ids = [row.order_id for row in orders]
    order_sessions = [row.session_id for row in orders]
    wo_ids = [row.workorder_id for row in workorders]
    wo_sessions = [row.session_id for row in workorders]

    order_id_set = set(order_ids)
    wo_id_set = set(wo_ids)
    chat_order_keys = [row.linked_order_id for row in chats if row.linked_order_id]
    chat_wo_keys = [row.linked_workorder_id for row in chats if row.linked_workorder_id]
    order_hits = sum(1 for key in chat_order_keys if key in order_id_set)
    wo_hits = sum(1 for key in chat_wo_keys if key in wo_id_set)

    chat_nulls = _null_report(
        [
            ("session_id", [row.session_id for row in chats]),
            ("message_id", [row.message_id for row in chats]),
            ("message_time", [row.message_time for row in chats]),
            ("linked_order_id", [row.linked_order_id for row in chats]),
            ("linked_workorder_id", [row.linked_workorder_id for row in chats]),
            ("image_path", [row.image_path for row in chats]),
        ]
    )
    order_nulls = _null_report(
        [
            ("order_id", [row.order_id for row in orders]),
            ("placed_time", [row.placed_time for row in orders]),
            ("paid_time", [row.paid_time for row in orders]),
            ("shipped_time", [row.shipped_time for row in orders]),
            ("tracking_no", [row.tracking_no for row in orders]),
        ]
    )
    wo_nulls = _null_report(
        [
            ("workorder_id", [row.workorder_id for row in workorders]),
            ("create_time", [row.create_time for row in workorders]),
            ("complete_time", [row.complete_time for row in workorders]),
        ]
    )

    time_parse = {
        "chat_message_time_ok": sum(1 for row in chats if isinstance(row.message_time, datetime)),
        "order_placed_ok": sum(1 for row in orders if isinstance(row.placed_time, datetime)),
        "order_paid_ok": sum(1 for row in orders if row.paid_time is None or isinstance(row.paid_time, datetime)),
        "order_shipped_ok": sum(1 for row in orders if row.shipped_time is None or isinstance(row.shipped_time, datetime)),
        "workorder_create_ok": sum(1 for row in workorders if isinstance(row.create_time, datetime)),
        "workorder_complete_ok": sum(
            1 for row in workorders if row.complete_time is None or isinstance(row.complete_time, datetime)
        ),
        "sheet_parse_errors": {
            name: bundle.sheets[name].parse_errors for name in BUSINESS_SHEETS if bundle.sheets[name].parse_errors
        },
    }

    mono = {
        "chat_time_non_decreasing_by_message_no": _chat_monotonic(chats),
        "order_placed_paid_shipped": _order_monotonic(orders),
        "workorder_create_complete": _workorder_monotonic(workorders),
    }

    uniqueness = {
        "chat_message_id_unique": len(message_ids) == len(set(message_ids)),
        "chat_session_message_no_unique": len(session_msg) == len(set(session_msg)),
        "order_id_unique": len(order_ids) == len(set(order_ids)),
        "order_session_unique": len(order_sessions) == len(set(order_sessions)),
        "workorder_id_unique": len(wo_ids) == len(set(wo_ids)),
        "workorder_session_unique": len(wo_sessions) == len(set(wo_sessions)),
        "duplicate_order_sessions": sorted(sid for sid, n in Counter(order_sessions).items() if n > 1),
        "duplicate_workorder_sessions": sorted(sid for sid, n in Counter(wo_sessions).items() if n > 1),
    }

    wo_by_sheet = Counter(row.source_sheet for row in workorders)
    observed = {
        "chat_rows": len(chats),
        "chat_sessions": len(chat_sessions),
        "chat_buyers": len(chat_buyers),
        "order_rows": len(orders),
        "workorder_rows": {name: wo_by_sheet.get(name, 0) for name in WORKORDER_SHEETS},
        "workorder_total": len(workorders),
        "order_link_hits": f"{order_hits}/{len(chat_order_keys)}",
        "workorder_link_hits": f"{wo_hits}/{len(chat_wo_keys)}",
        "image_messages": sum(1 for row in chats if row.image_path),
    }
    audit_match = {key: observed[key] == EXPECTED_INPUT_AUDIT[key] for key in EXPECTED_INPUT_AUDIT}

    id_types = {
        "chat_session_id_all_str": all(isinstance(row.session_id, str) for row in chats),
        "chat_message_id_all_str": all(isinstance(row.message_id, str) for row in chats),
        "chat_linked_order_id_str_or_none": all(
            row.linked_order_id is None or isinstance(row.linked_order_id, str) for row in chats
        ),
        "chat_linked_workorder_id_str_or_none": all(
            row.linked_workorder_id is None or isinstance(row.linked_workorder_id, str) for row in chats
        ),
        "order_id_all_str": all(isinstance(row.order_id, str) for row in orders),
        "workorder_id_all_str": all(isinstance(row.workorder_id, str) for row in workorders),
        "buyer_nick_all_str": all(isinstance(row.buyer_nick, str) for row in chats),
        "no_float_ids": True,
    }

    report = {
        "title": "DATA-T001 loader self-check",
        "note": "Row counts and 819/819、629/629 are input audit evidence, not snapshot acceptance.",
        "source_path": bundle.source_path,
        "source_sha256": bundle.source_sha256,
        "timezone": "Asia/Shanghai",
        "loader_log": bundle.log,
        "sheets": sheets_report,
        "field_mapping": field_mapping_document(),
        "nulls": {"chat": chat_nulls, "order": order_nulls, "workorder": wo_nulls},
        "time_parseability": time_parse,
        "time_monotonicity": mono,
        "primary_key_uniqueness": uniqueness,
        "association": {
            "method": "session_id preferred; nonempty chat backfill keys cross-checked",
            "nonempty_order_keys": len(chat_order_keys),
            "order_key_hits": order_hits,
            "nonempty_workorder_keys": len(chat_wo_keys),
            "workorder_key_hits": wo_hits,
            "order_link_rate": f"{order_hits}/{len(chat_order_keys)}" if chat_order_keys else "0/0",
            "workorder_link_rate": f"{wo_hits}/{len(chat_wo_keys)}" if chat_wo_keys else "0/0",
            "sessions_with_order": sum(1 for sid in chat_sessions if sid in {o.session_id for o in orders}),
            "sessions_with_workorder": sum(1 for sid in chat_sessions if sid in {w.session_id for w in workorders}),
        },
        "id_types": id_types,
        "observed": observed,
        "expected_input_audit": EXPECTED_INPUT_AUDIT,
        "input_audit_match": audit_match,
        "input_audit_all_match": all(audit_match.values()),
        "sample_output_times": {
            "first_chat": format_iso(min(row.message_time for row in chats)) if chats else None,
        },
    }
    return report


def write_selfcheck(report: dict[str, Any], path) -> None:
    path.write_text(dumps_canonical(report), encoding="utf-8")


def _null_report(columns: list[tuple[str, list[Any]]]) -> dict[str, Any]:
    out = {}
    for name, values in columns:
        n = len(values)
        empty = sum(1 for v in values if v is None)
        out[name] = {"null": empty, "non_null": n - empty, "total": n}
    return out


def _chat_monotonic(chats) -> dict[str, Any]:
    by_session = defaultdict(list)
    for row in chats:
        by_session[row.session_id].append(row)
    violations = []
    for session_id, rows in by_session.items():
        rows = sorted(rows, key=lambda r: r.message_no)
        prev_time = None
        prev_no = None
        for row in rows:
            if prev_time is not None and row.message_time < prev_time:
                violations.append(
                    {
                        "session_id": session_id,
                        "from_message_no": prev_no,
                        "to_message_no": row.message_no,
                    }
                )
            prev_time = row.message_time
            prev_no = row.message_no
    return {"ok": not violations, "violations": violations[:50], "violation_count": len(violations)}


def _order_monotonic(orders) -> dict[str, Any]:
    violations = []
    for row in orders:
        if row.paid_time is not None and row.paid_time < row.placed_time:
            violations.append({"order_id": row.order_id, "kind": "paid_before_placed"})
        if row.shipped_time is not None and row.paid_time is not None and row.shipped_time < row.paid_time:
            violations.append({"order_id": row.order_id, "kind": "shipped_before_paid"})
        if row.shipped_time is not None and row.shipped_time < row.placed_time:
            violations.append({"order_id": row.order_id, "kind": "shipped_before_placed"})
    return {"ok": not violations, "violations": violations[:50], "violation_count": len(violations)}


def _workorder_monotonic(workorders) -> dict[str, Any]:
    violations = []
    for row in workorders:
        if row.complete_time is not None and row.complete_time < row.create_time:
            violations.append({"workorder_id": row.workorder_id, "kind": "complete_before_create"})
    return {"ok": not violations, "violations": violations[:50], "violation_count": len(violations)}
