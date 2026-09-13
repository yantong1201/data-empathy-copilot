"""as_of_time snapshot: field-level filter, no future leak, source inconsistency."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .loader import ChatRecord, DataStore, OrderRecord, WorkorderRecord
from .mapping import (
    AGENT_ROLE,
    COMPLETED_STATUS_VALUES,
    SNAPSHOT_SCHEMA,
    SOURCE_INCONSISTENCY_KIND,
)
from .timeutil import as_of_or_parse, format_iso

CLAIM_RE = re.compile(
    r"(?:"
    r"已(?:为您)?(?:建立|创建|提交|登记|加急登记).{0,12}(?:专项)?(?:工单|换货单|补发单|核实工单|丢件工单|加急工单|记录单)"
    r"|(?:专项)?(?:工单|换货单|补发单|核实工单|丢件工单|加急工单|记录单)已(?:创建|建立|提交|登记|加急)"
    r"|登记了(?:专项)?(?:工单|换货单|补发单|核实工单|丢件工单|加急工单|记录单)"
    r"|登记拒收退回工单"
    r"|已提交核实工单"
    r"|已为您提交，仓库签收"
    r")"
)


@dataclass(frozen=True)
class SnapshotQuery:
    session_id: str
    message_no: int | None = None
    as_of_time: datetime | str | None = None


def is_workorder_claim(text: str | None, role: str | None) -> bool:
    if role != AGENT_ROLE:
        return False
    if not text:
        return False
    return CLAIM_RE.search(text) is not None


def build_snapshot(store: DataStore, query: SnapshotQuery) -> dict[str, Any]:
    session_id = str(query.session_id)
    chats = store.require_session(session_id)
    as_of, message_no = _resolve_as_of(chats, query)
    visible_chat = [row for row in chats if row.message_time <= as_of]
    order = store.orders_by_session.get(session_id)
    workorder = store.workorders_by_session.get(session_id)
    order_snap = _order_snapshot(order, as_of)
    workorder_snap = _workorder_snapshot(workorder, as_of)
    chat_snap = [_chat_snapshot(row, order_snap, workorder_snap) for row in visible_chat]
    logistics = _logistics_snapshot(order_snap, workorder_snap)
    inconsistency = _source_inconsistency(visible_chat, workorder_snap, as_of, session_id)
    current_no = message_no
    if current_no is None and visible_chat:
        current_no = visible_chat[-1].message_no
    source_refs = [row["source_ref"] for row in chat_snap]
    if order_snap["visibility"] == "visible":
        source_refs.append(order_snap["source_ref"])
        if logistics["order_logistics"] is not None:
            source_refs.append(logistics["order_logistics"]["source_ref"])
    if workorder_snap["visibility"] == "visible":
        source_refs.append(workorder_snap["source_ref"])
    for item in inconsistency:
        for ref in item["source_refs"]:
            if ref not in source_refs:
                source_refs.append(ref)
    return {
        "schema": SNAPSHOT_SCHEMA,
        "timezone": "Asia/Shanghai",
        "session_id": session_id,
        "message_no": current_no,
        "as_of_time": format_iso(as_of),
        "query": {
            "session_id": session_id,
            "message_no": query.message_no,
            "as_of_time": format_iso(as_of),
        },
        "chat": chat_snap,
        "order": order_snap,
        "workorder": workorder_snap,
        "logistics": logistics,
        "source_inconsistency": inconsistency,
        "source_refs": source_refs,
        "association": _association(order_snap, workorder_snap),
    }


def _resolve_as_of(chats: list[ChatRecord], query: SnapshotQuery) -> tuple[datetime, int | None]:
    if query.message_no is None and query.as_of_time is None:
        raise ValueError("snapshot requires message_no or as_of_time")
    if query.message_no is not None:
        match = next((row for row in chats if row.message_no == query.message_no), None)
        if match is None:
            raise KeyError(f"message_no {query.message_no} not in session {query.session_id}")
        message_as_of = match.message_time
        if query.as_of_time is None:
            return message_as_of, match.message_no
        as_of = as_of_or_parse(query.as_of_time)
        if as_of != message_as_of:
            raise ValueError(
                "message_no and as_of_time disagree: "
                f"message={format_iso(message_as_of)} as_of={format_iso(as_of)}"
            )
        return as_of, match.message_no
    return as_of_or_parse(query.as_of_time), None


def _chat_snapshot(row: ChatRecord, order_snap: dict[str, Any], workorder_snap: dict[str, Any]) -> dict[str, Any]:
    order_visible = order_snap.get("visibility") == "visible"
    wo_visible = workorder_snap.get("visibility") == "visible"
    linked_order = row.linked_order_id if order_visible and row.linked_order_id == order_snap.get("order_id") else None
    linked_wo = (
        row.linked_workorder_id
        if wo_visible and row.linked_workorder_id == workorder_snap.get("workorder_id")
        else None
    )
    return {
        "session_id": row.session_id,
        "message_no": row.message_no,
        "message_id": row.message_id,
        "message_time": format_iso(row.message_time),
        "role": row.role,
        "buyer_nick": row.buyer_nick,
        "sender": row.sender,
        "shop": row.shop,
        "scene_major": row.scene_major,
        "scene_minor": row.scene_minor,
        "is_target_buyer_message": row.is_target_buyer_message,
        "message_text": row.message_text,
        "content_type": row.content_type,
        "category": row.category,
        "image_path": row.image_path,
        "linked_order_id": linked_order,
        "linked_workorder_id": linked_wo,
        "source_ref": f"chat:{row.session_id}:{row.message_no}",
        "source_row": row.source_row,
    }


def _order_snapshot(order: OrderRecord | None, as_of: datetime) -> dict[str, Any]:
    if order is None:
        return {
            "visibility": "no_order",
            "order_id": None,
            "reason": "session_has_no_order",
        }
    if order.placed_time > as_of:
        return {
            "visibility": "not_yet_visible",
            "order_id": None,
            "reason": "placed_time_after_as_of_time",
        }
    paid_visible = order.paid_time is not None and order.paid_time <= as_of
    shipped_visible = order.shipped_time is not None and order.shipped_time <= as_of
    return {
        "visibility": "visible",
        "order_id": order.order_id,
        "session_id": order.session_id,
        "buyer_nick": order.buyer_nick,
        "shop": order.shop,
        "sku_code": order.sku_code,
        "product_name": order.product_name,
        "quantity": order.quantity,
        "unit_price": order.unit_price,
        "paid_amount": order.paid_amount,
        "placed_time": format_iso(order.placed_time),
        "paid": {
            "visible": paid_visible,
            "time": format_iso(order.paid_time) if paid_visible else None,
            "note": order.paid_time_note if paid_visible else None,
            "reason": None if paid_visible else (
                "paid_time_empty" if order.paid_time is None else "paid_time_after_as_of_time"
            ),
        },
        "shipped": {
            "visible": shipped_visible,
            "time": format_iso(order.shipped_time) if shipped_visible else None,
            "courier": order.courier if shipped_visible else None,
            "tracking_no": order.tracking_no if shipped_visible else None,
            "reason": None if shipped_visible else (
                "shipped_time_empty" if order.shipped_time is None else "shipped_time_after_as_of_time"
            ),
        },
        "order_status": {
            "raw_in_source": True,
            "snapshot_value": None,
            "assertion": "unknown",
            "reason": "missing_status_effective_time",
        },
        "receiver_province": order.receiver_province,
        "receiver_city": order.receiver_city,
        "gift": order.gift,
        "buyer_note": order.buyer_note,
        "source_ref": f"order:{order.order_id}",
        "source_sheet": order.source_sheet,
        "source_row": order.source_row,
    }


def _workorder_snapshot(workorder: WorkorderRecord | None, as_of: datetime) -> dict[str, Any]:
    if workorder is None:
        return {
            "visibility": "no_workorder",
            "workorder_id": None,
            "reason": "session_has_no_workorder",
        }
    if workorder.create_time > as_of:
        return {
            "visibility": "no_workorder",
            "workorder_id": None,
            "reason": "create_time_after_as_of_time",
        }
    complete_visible = (
        workorder.complete_time is not None and workorder.complete_time <= as_of
    )
    if complete_visible:
        status_value = "completed"
        status_raw = workorder.status_raw
        completion_reason = None
    elif workorder.complete_time is None:
        status_value = "not_completed"
        status_raw = None if workorder.status_raw in COMPLETED_STATUS_VALUES else workorder.status_raw
        completion_reason = "complete_time_empty"
    else:
        status_value = "not_completed"
        status_raw = None if workorder.status_raw in COMPLETED_STATUS_VALUES else workorder.status_raw
        completion_reason = "complete_time_after_as_of_time"
    return {
        "visibility": "visible",
        "workorder_id": workorder.workorder_id,
        "session_id": workorder.session_id,
        "order_id": workorder.order_id,
        "buyer_nick": workorder.buyer_nick,
        "shop": workorder.shop,
        "kind": workorder.kind,
        "source_sheet": workorder.source_sheet,
        "handler": workorder.handler,
        "create_time": format_iso(workorder.create_time),
        "complete_time": format_iso(workorder.complete_time) if complete_visible else None,
        "completion": {
            "displayed": complete_visible,
            "snapshot_value": status_value,
            "reason": completion_reason,
        },
        "status": {
            "snapshot_value": status_value,
            "raw": status_raw,
            "completed_displayed": complete_visible,
        },
        "fields": dict(workorder.extra),
        "source_ref": f"workorder:{workorder.workorder_id}",
        "source_row": workorder.source_row,
    }


def _logistics_snapshot(order_snap: dict[str, Any], workorder_snap: dict[str, Any]) -> dict[str, Any]:
    order_logistics = None
    if order_snap.get("visibility") == "visible" and order_snap["shipped"]["visible"]:
        order_logistics = {
            "courier": order_snap["shipped"]["courier"],
            "tracking_no": order_snap["shipped"]["tracking_no"],
            "shipped_time": order_snap["shipped"]["time"],
            "source_ref": f"order:{order_snap['order_id']}:logistics",
        }
    logistics_wo = None
    if workorder_snap.get("visibility") == "visible" and workorder_snap.get("kind") == "logistics":
        logistics_wo = {
            "workorder_id": workorder_snap["workorder_id"],
            "source_ref": workorder_snap["source_ref"],
            "fields": {
                key: workorder_snap["fields"].get(key)
                for key in (
                    "issue_type",
                    "courier",
                    "problem_tracking_no",
                    "warehouse",
                    "handling_plan",
                )
            },
        }
    return {
        "order_logistics": order_logistics,
        "logistics_workorder": logistics_wo,
    }


def _association(
    order_snap: dict[str, Any],
    workorder_snap: dict[str, Any],
) -> dict[str, Any]:
    return {
        "method": "session_id",
        "order_visible": order_snap.get("visibility") == "visible",
        "workorder_visible": workorder_snap.get("visibility") == "visible",
        "order_id": order_snap.get("order_id"),
        "workorder_id": workorder_snap.get("workorder_id"),
        "note": "Backfilled chat keys are not used to prove visibility and are omitted until the record is visible.",
    }


def _source_inconsistency(
    visible_chat: list[ChatRecord],
    workorder_snap: dict[str, Any],
    as_of: datetime,
    session_id: str,
) -> list[dict[str, Any]]:
    if workorder_snap.get("visibility") == "visible":
        return []
    claims = [row for row in visible_chat if is_workorder_claim(row.message_text, row.role)]
    if not claims:
        return []
    chat_refs = [f"chat:{row.session_id}:{row.message_no}" for row in claims]
    system_ref = f"system:workorder:none:{session_id}"
    quotes = [
        {
            "source_ref": f"chat:{row.session_id}:{row.message_no}",
            "message_no": row.message_no,
            "message_time": format_iso(row.message_time),
            "role": row.role,
            "text": row.message_text,
        }
        for row in claims
    ]
    first = quotes[0]["text"]
    summary = (
        f"客服声称已建单（{first}），但工单系统在当前时点没有记录"
    )
    return [
        {
            "kind": SOURCE_INCONSISTENCY_KIND,
            "source_refs": chat_refs + [system_ref],
            "as_of_time": format_iso(as_of),
            "summary": summary,
            "chat_quotes": quotes,
            "system_fact": {
                "source_ref": system_ref,
                "fact": "工单系统暂无记录",
                "workorder_visibility": workorder_snap.get("visibility"),
                "reason": workorder_snap.get("reason"),
            },
        }
    ]


def collect_future_leaks(snapshot: dict[str, Any], store: DataStore) -> list[str]:
    """Return leak descriptions if future workorder/order fields appear."""
    leaks: list[str] = []
    session_id = snapshot["session_id"]
    as_of = as_of_or_parse(snapshot["as_of_time"])
    wo = store.workorders_by_session.get(session_id)
    order = store.orders_by_session.get(session_id)
    blob = _walk_strings(snapshot)
    if wo is not None and wo.create_time > as_of:
        if wo.workorder_id in blob:
            leaks.append(f"future workorder_id {wo.workorder_id}")
        if format_iso(wo.create_time) in blob:
            leaks.append("future workorder create_time")
        if wo.complete_time is not None and format_iso(wo.complete_time) in blob:
            leaks.append("future workorder complete_time")
        for value in wo.extra.values():
            if isinstance(value, str) and value and value in blob and value not in {
                session_id, wo.session_id, wo.buyer_nick or "", wo.shop or ""
            }:
                # extra fields often overlap chat text; only flag unique identifiers
                continue
        if snapshot["workorder"].get("visibility") != "no_workorder":
            leaks.append("workorder visible before create_time")
        if snapshot["workorder"].get("workorder_id"):
            leaks.append("workorder_id present before create_time")
    if wo is not None and wo.create_time <= as_of:
        complete_ok = wo.complete_time is not None and wo.complete_time <= as_of
        if not complete_ok:
            status = snapshot["workorder"].get("status") or {}
            if status.get("snapshot_value") == "completed" or status.get("completed_displayed"):
                leaks.append("completed status displayed without visible complete_time")
            if snapshot["workorder"].get("complete_time"):
                leaks.append("complete_time displayed early")
            if status.get("raw") in COMPLETED_STATUS_VALUES:
                leaks.append("raw completed status leaked")
    if order is not None and order.placed_time > as_of:
        if order.order_id in blob and snapshot["order"].get("visibility") == "visible":
            leaks.append("future order visible")
        if snapshot["order"].get("order_id"):
            leaks.append("order_id present before placed_time")
    if order is not None and order.placed_time <= as_of:
        if order.paid_time is not None and order.paid_time > as_of:
            paid = snapshot["order"].get("paid") or {}
            if paid.get("time") or paid.get("visible"):
                leaks.append("paid_time leaked before field time")
        if order.shipped_time is not None and order.shipped_time > as_of:
            shipped = snapshot["order"].get("shipped") or {}
            if shipped.get("time") or shipped.get("visible") or shipped.get("tracking_no"):
                leaks.append("shipped fields leaked before shipped_time")
    for msg in snapshot.get("chat") or []:
        if wo is not None and wo.create_time > as_of and msg.get("linked_workorder_id"):
            leaks.append(f"chat linked_workorder_id leaked at msg {msg.get('message_no')}")
        if order is not None and order.placed_time > as_of and msg.get("linked_order_id"):
            leaks.append(f"chat linked_order_id leaked at msg {msg.get('message_no')}")
    return leaks


def _walk_strings(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_walk_strings(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return "\n".join(_walk_strings(v) for v in value)
    return str(value)
