"""Policy pack: as_of_time filter and metadata checks."""

from __future__ import annotations

from typing import Any

from backend.data_empathy.timeutil import parse_shanghai_text

from .pack import load_pack


def policies_effective_at(as_of_time: str, pack: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    pack = pack or load_pack()
    as_of = parse_shanghai_text(as_of_time, field="as_of_time")
    out = []
    for row in pack["policy"]["policies"]:
        start = parse_shanghai_text(row["effective_from"], field="effective_from")
        if row.get("status") == "active" and start <= as_of:
            out.append(row)
    return out


def policy_source_refs(policies: list[dict[str, Any]]) -> list[str]:
    return [f"policy:{row['policy_id']}" for row in policies]


def validate_policy_metadata(pack: dict[str, Any] | None = None) -> list[str]:
    pack = pack or load_pack()
    policies = pack["policy"]["policies"]
    failures = []
    n = len(policies)
    if n < 10 or n > 20:
        failures.append(f"policy count {n} not in 10-20")
    required = [
        "policy_id", "title", "content", "category", "source", "version",
        "effective_from", "status", "allowed_actions", "forbidden_actions",
        "evidence_requirements", "demo_rule",
    ]
    ids = []
    for row in policies:
        ids.append(row.get("policy_id"))
        for key in required:
            if key not in row:
                failures.append(f"{row.get('policy_id')}: missing {key}")
        if row.get("official") is True:
            failures.append(f"{row.get('policy_id')}: must not be marked official without official source")
        if row.get("source") != "比赛演示规则" or not row.get("demo_rule"):
            failures.append(f"{row.get('policy_id')}: demo source/mark required")
        if row.get("status") != "active":
            failures.append(f"{row.get('policy_id')}: expected active")
    if len(ids) != len(set(ids)):
        failures.append("duplicate policy_id")
    return failures
