"""Stable analysis_id fingerprint. run_id is a separate execution record."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from backend.data_empathy.codec import dumps_hash_payload

from .pack import pack_fingerprint


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    payload = {
        "schema": snapshot.get("schema"),
        "session_id": snapshot.get("session_id"),
        "message_no": snapshot.get("message_no"),
        "as_of_time": snapshot.get("as_of_time"),
        "source_refs": snapshot.get("source_refs"),
        "source_inconsistency": snapshot.get("source_inconsistency"),
        "order_visibility": (snapshot.get("order") or {}).get("visibility"),
        "workorder_visibility": (snapshot.get("workorder") or {}).get("visibility"),
        "workorder_id": (snapshot.get("workorder") or {}).get("workorder_id"),
        "chat_refs": [row.get("source_ref") for row in snapshot.get("chat") or []],
    }
    return hashlib.sha256(dumps_hash_payload(payload).encode("utf-8")).hexdigest()


def make_analysis_id(
    snapshot: dict[str, Any],
    *,
    provider: str,
    model: str,
    pack: dict[str, Any] | None = None,
) -> str:
    fp = pack_fingerprint(pack)
    parts = {
        "session_id": snapshot.get("session_id"),
        "message_no": snapshot.get("message_no"),
        "as_of_time": snapshot.get("as_of_time"),
        "snapshot_hash": snapshot_hash(snapshot),
        "provider": provider,
        "model": model,
        "prompt_version": fp["prompt_version"],
        "schema_id": fp["schema_id"],
        "schema_sha256": fp["schema_sha256"],
        "rules_version": fp["rules_version"],
        "rules_sha256": fp["rules_sha256"],
        "policy_version": fp["policy_version"],
        "policy_sha256": fp["policy_sha256"],
    }
    digest = hashlib.sha256(dumps_hash_payload(parts).encode("utf-8")).hexdigest()[:20]
    return f"A-{snapshot.get('session_id')}-{digest}"


def make_run_id() -> str:
    return "R-" + uuid.uuid4().hex
