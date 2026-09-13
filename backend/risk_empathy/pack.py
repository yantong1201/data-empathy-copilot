"""Load versioned risk/policy/emotion contracts."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.data_empathy.loader import repo_root

CONTRACT_DIR = repo_root() / "data" / "contracts" / "risk"
SCHEMA_PATH = repo_root() / "方案文档" / "模块规格" / "02-风险政策与结构化契约-SCHEMA.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_pack() -> dict[str, Any]:
    versions = _read_json(CONTRACT_DIR / "versions.json")
    rules = _read_json(CONTRACT_DIR / "risk_rules_v1.json")
    emotion = _read_json(CONTRACT_DIR / "emotion_constraints_v1.json")
    policy = _read_json(CONTRACT_DIR / "policy_pack_v1.json")
    safety_schema = _read_json(CONTRACT_DIR / "safety_check_result.schema.json")
    degradation_schema = _read_json(CONTRACT_DIR / "degradation_record.schema.json")
    provider_schema = _read_json(SCHEMA_PATH)
    return {
        "versions": versions,
        "rules": rules,
        "emotion": emotion,
        "policy": policy,
        "safety_schema": safety_schema,
        "degradation_schema": degradation_schema,
        "provider_schema": provider_schema,
        "schema_path": str(SCHEMA_PATH),
        "contract_dir": str(CONTRACT_DIR),
    }


def file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pack_fingerprint(pack: dict[str, Any] | None = None) -> dict[str, str]:
    pack = pack or load_pack()
    versions = pack["versions"]
    return {
        "contract_pack": versions["contract_pack"],
        "rules_version": versions["rules_version"],
        "emotion_version": versions["emotion_version"],
        "policy_version": versions["policy_version"],
        "schema_id": versions["schema_id"],
        "prompt_version": versions["prompt_version"],
        "rules_sha256": file_sha256(CONTRACT_DIR / "risk_rules_v1.json"),
        "policy_sha256": file_sha256(CONTRACT_DIR / "policy_pack_v1.json"),
        "emotion_sha256": file_sha256(CONTRACT_DIR / "emotion_constraints_v1.json"),
        "schema_sha256": file_sha256(SCHEMA_PATH),
    }
