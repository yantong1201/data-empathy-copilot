"""Disposal state, drafts and human-confirmation validation.

Rules implemented here (workbench SPEC §queue):
- Transitions: open→watching, watching→watching, watching→resolved,
  open→resolved (low risk with no pending required actions only).
- P0/P1 (rule confirmed), unfinished required actions or a key source
  conflict can never auto-resolve.
- Confirmations must carry current analysis_id, as_of_time, draft
  revision/draft_hash and an idempotent operation_id; stale analysis, stale
  timepoint or stale draft is rejected with the reason recorded.
- Only analyses with safety_check_result.status=pass (and schema valid,
  safety executed) may serve as confirmation basis.
- Disposal log and confirmation log are append-only (hash-chained).
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from pathlib import Path
from typing import Any

from backend.data_empathy.loader import repo_root

WORKBENCH_DIR = repo_root() / "data" / "workbench"
DISPOSAL_STATE_PATH = WORKBENCH_DIR / "disposal_state.json"
DISPOSAL_LOG_PATH = WORKBENCH_DIR / "disposal_log.jsonl"
CONFIRM_LOG_PATH = WORKBENCH_DIR / "confirm_log.jsonl"
DRAFTS_PATH = WORKBENCH_DIR / "drafts.json"
OPERATIONS_PATH = WORKBENCH_DIR / "operations.json"

ALLOWED_TRANSITIONS = {
    ("open", "watching"),
    ("watching", "watching"),
    ("watching", "resolved"),
    ("open", "resolved"),
}
STATUS_LABELS = {"open": "处理中", "watching": "持续跟进", "resolved": "已解决"}
ACTION_TYPES = {
    "status_change", "apply_reply", "use_reply", "workorder_draft", "escalation_draft",
}


def _now_iso() -> str:
    import datetime as dt

    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="milliseconds")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AppendLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        last_hash = ""
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        last_hash = json.loads(line).get("record_sha256") or ""
                    except json.JSONDecodeError:
                        last_hash = ""
        record = dict(record)
        record["seq"] = sum(1 for line in self.path.open("r", encoding="utf-8") if line.strip()) + 1
        record["ts"] = _now_iso()
        record["prev_record_sha256"] = last_hash
        record["record_sha256"] = hashlib.sha256(
            json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def records(self) -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for line in self.path.open("r", encoding="utf-8")
            if line.strip()
        ]


class WorkbenchState:
    def __init__(self, root: Path | None = None):
        root = root or WORKBENCH_DIR
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.disposal_state_path = root / "disposal_state.json"
        self.disposal_log = AppendLog(root / "disposal_log.jsonl")
        self.confirm_log = AppendLog(root / "confirm_log.jsonl")
        self.drafts_path = root / "drafts.json"
        self.operations_path = root / "operations.json"
        self._lock = threading.RLock()
        self.disposal_state: dict[str, str] = self._load_json(self.disposal_state_path, {})
        self.drafts: dict[str, dict[str, Any]] = self._load_json(self.drafts_path, {})
        self.operations: dict[str, dict[str, Any]] = self._load_json(self.operations_path, {})
        # analysis registry: session_id -> latest analysis metadata
        self.current_analysis: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _load_json(path: Path, default: Any) -> Any:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return default
        return default

    def _save_json(self, path: Path, payload: Any) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
        tmp.replace(path)

    # --- analysis registry -------------------------------------------------

    def register_analysis(
        self,
        *,
        session_id: str,
        as_of_time: str,
        analysis_id: str,
        run_id: str,
        provider_used: str,
        degraded: bool,
        safety_status: str | None,
        confirmable: bool,
        risk: dict[str, Any],
        has_source_conflict: bool,
        required_actions_pending: bool,
    ) -> None:
        with self._lock:
            self.current_analysis[session_id] = {
                "analysis_id": analysis_id,
                "run_id": run_id,
                "as_of_time": as_of_time,
                "provider_used": provider_used,
                "degraded": degraded,
                "safety_status": safety_status,
                "confirmable": confirmable,
                "risk_level": risk.get("level"),
                "risk_status": risk.get("status"),
                "has_source_conflict": has_source_conflict,
                "required_actions_pending": required_actions_pending,
                "registered_at": _now_iso(),
            }

    def status_of(self, session_id: str) -> str:
        return self.disposal_state.get(session_id, "open")

    # --- drafts ------------------------------------------------------------

    def draft_key(self, session_id: str, as_of_time: str) -> str:
        return f"{session_id}@{as_of_time}"

    def get_draft(self, session_id: str, as_of_time: str) -> dict[str, Any] | None:
        return self.drafts.get(self.draft_key(session_id, as_of_time))

    def save_draft(self, session_id: str, as_of_time: str, text: str) -> dict[str, Any]:
        with self._lock:
            key = self.draft_key(session_id, as_of_time)
            existing = self.drafts.get(key) or {"revision": 0}
            revision = int(existing.get("revision") or 0) + 1
            draft = {
                "text": text,
                "revision": revision,
                "draft_hash": _sha(text),
                "updated_at": _now_iso(),
                "session_id": session_id,
                "as_of_time": as_of_time,
            }
            self.drafts[key] = draft
            self._save_json(self.drafts_path, self.drafts)
            return draft

    # --- confirmation ------------------------------------------------------

    def confirm(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            operation_id = str(request.get("operation_id") or "")
            action = str(request.get("action") or "")
            session_id = str(request.get("session_id") or "")
            analysis_id = str(request.get("analysis_id") or "")
            as_of_time = str(request.get("as_of_time") or "")
            draft_revision = request.get("draft_revision")
            draft_hash = str(request.get("draft_hash") or "")
            from_status = str(request.get("from_status") or "")
            to_status = request.get("to_status")
            operator = str(request.get("operator") or "人工客服（演示）")
            payload = request.get("payload") or {}

            base = {
                "operation_id": operation_id,
                "action": action,
                "session_id": session_id,
                "analysis_id": analysis_id,
                "as_of_time": as_of_time,
                "operator": operator,
                "payload": payload,
            }

            # idempotency: same operation_id returns the recorded outcome
            if operation_id and operation_id in self.operations:
                recorded = self.operations[operation_id]
                self.confirm_log.append({
                    "event": "idempotent_replay",
                    "outcome": "replayed",
                    **base,
                    "original_seq": recorded.get("seq"),
                })
                return {"accepted": recorded.get("accepted"), "result": recorded.get("result"),
                        "idempotent_replay": True, "record": recorded}

            def reject(reason: str, detail: str = "") -> dict[str, Any]:
                result = {"accepted": False, "reason": reason, "detail": detail}
                record = self.confirm_log.append({
                    "event": "confirmation", "outcome": "rejected", "reason": reason,
                    "detail": detail, **base,
                })
                if operation_id:
                    self.operations[operation_id] = {
                        "accepted": False, "result": result, "seq": record["seq"],
                    }
                    self._save_json(self.operations_path, self.operations)
                return {"accepted": False, "reason": reason, "detail": detail, "record": record}

            if action not in ACTION_TYPES:
                return reject("invalid_action", f"unknown action {action}")
            if not operation_id:
                return reject("invalid_request", "operation_id required")

            current = self.current_analysis.get(session_id)
            if current is None:
                return reject("no_analysis", "该会话尚无已注册分析，请先运行分析")

            # stale analysis / timepoint / safety gates
            if analysis_id != current["analysis_id"]:
                return reject(
                    "stale_analysis",
                    f"请求携带 analysis_id={analysis_id}，当前分析为 {current['analysis_id']}；旧分析不得确认，请刷新当前分析后重试",
                )
            if as_of_time != current["as_of_time"]:
                return reject(
                    "stale_as_of_time",
                    f"请求时点 {as_of_time} 不是当前分析时点 {current['as_of_time']}；旧时点不得确认",
                )
            if not current.get("confirmable"):
                safety = current.get("safety_status")
                return reject(
                    "safety_not_pass",
                    f"safety_check_result.status={safety}；未通过安全校验或未运行的分析不得作为人工确认依据",
                )

            # draft version gates for reply actions
            if action in {"apply_reply", "use_reply"}:
                draft = self.get_draft(session_id, as_of_time)
                if draft is None:
                    return reject("stale_draft", "当前时点无已保存草稿")
                if int(draft_revision or 0) != int(draft["revision"]) or draft_hash != draft["draft_hash"]:
                    return reject(
                        "stale_draft",
                        f"草稿版本不匹配：请求 revision={draft_revision}，当前 revision={draft['revision']}；草稿已变更，请使用最新草稿重新确认",
                    )

            # transition validation
            if action == "status_change":
                if to_status not in {"open", "watching", "resolved"}:
                    return reject("invalid_transition", f"unknown status {to_status}")
                actual_from = self.status_of(session_id)
                if from_status != actual_from:
                    return reject(
                        "stale_status",
                        f"请求 from_status={from_status}，实际当前状态为 {actual_from}",
                    )
                if (from_status, to_status) not in ALLOWED_TRANSITIONS:
                    return reject(
                        "invalid_transition",
                        f"{from_status}→{to_status} 不在允许转移内（open→watching、watching→watching、watching→resolved、低风险 open→resolved）",
                    )
                if to_status == "resolved":
                    risk_level = current.get("risk_level")
                    risk_status = current.get("risk_status")
                    if risk_level in {"P0", "P1"} and risk_status == "confirmed":
                        return reject(
                            "risk_blocks_resolve",
                            f"规则确定的 {risk_level} 不得自动 resolved；须人工处置完成后由允许路径变更",
                        )
                    if current.get("required_actions_pending"):
                        return reject(
                            "pending_actions_block_resolve",
                            "仍有未完成的必需动作（未完结工单/待核验证据），不得自动 resolved",
                        )
                    if current.get("has_source_conflict"):
                        return reject(
                            "source_conflict_block_resolve",
                            "仍存在关键来源冲突（客服声称已建单但系统暂无记录），不得自动 resolved",
                        )

            # apply
            prev_status = self.status_of(session_id)
            result: dict[str, Any] = {"action": action, "operator": operator}
            record_payload: dict[str, Any] = {}
            if action == "status_change":
                self.disposal_state[session_id] = str(to_status)
                self._save_json(self.disposal_state_path, self.disposal_state)
                result.update({"from_status": prev_status, "to_status": to_status})
                record_payload = {
                    "operation": "确认处置状态变更",
                    "from_status": prev_status,
                    "to_status": to_status,
                }
            elif action == "apply_reply":
                record_payload = {"operation": "确认用建议回复替换编辑框（本地草稿）"}
            elif action == "use_reply":
                record_payload = {"operation": "确认保留当前编辑草稿（不发送）",
                                  "draft_revision": draft_revision, "draft_hash": draft_hash}
            elif action == "workorder_draft":
                record_payload = {"operation": "生成本地工单草稿（不创建真实工单）",
                                  "draft": payload.get("draft") or {}}
            elif action == "escalation_draft":
                record_payload = {"operation": "生成本地人工升级草稿（不调用真实升级）",
                                  "draft": payload.get("draft") or {}}

            record = self.confirm_log.append({
                "event": "confirmation",
                "outcome": "accepted",
                **base,
                "from_status": prev_status,
                "to_status": self.status_of(session_id) if action == "status_change" else None,
                **record_payload,
            })
            disposal_record = self.disposal_log.append({
                "event": "disposal",
                "session_id": session_id,
                "operator": operator,
                "operation_time": _now_iso(),
                "analysis_id": analysis_id,
                "as_of_time": as_of_time,
                "operation": record_payload.get("operation") or action,
                "action_type": action,
                "from_status": prev_status,
                "to_status": self.status_of(session_id) if action == "status_change" else prev_status,
                "operation_id": operation_id,
                "confirm_seq": record["seq"],
            })
            if operation_id:
                self.operations[operation_id] = {
                    "accepted": True, "result": result, "seq": record["seq"],
                }
                self._save_json(self.operations_path, self.operations)
            return {
                "accepted": True,
                "result": result,
                "record": record,
                "disposal_record": disposal_record,
            }

    def disposal_records(self, session_id: str | None = None) -> list[dict[str, Any]]:
        rows = self.disposal_log.records()
        if session_id:
            rows = [row for row in rows if row.get("session_id") == session_id]
        return rows

    def reset_demo_state(self) -> None:
        """Clear mutable demo state (disposal state/drafts/operations). Logs stay."""
        with self._lock:
            self.disposal_state = {}
            self.drafts = {}
            self.operations = {}
            self.current_analysis = {}
            self._save_json(self.disposal_state_path, self.disposal_state)
            self._save_json(self.drafts_path, self.drafts)
            self._save_json(self.operations_path, self.operations)


def new_operation_id() -> str:
    return "OP-" + uuid.uuid4().hex
